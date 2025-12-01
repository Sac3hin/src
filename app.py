# frontend/app.py
"""
Childcare Insights - Frontend (Streamlit)
-----------------------------------------
Streamlit UI that delegates business logic to backend and config layers.
"""
# --- Path bootstrap: ensure project root on sys.path ---
import os, sys
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(FRONTEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
import pandas as pd
from datetime import datetime
from configurations.config import load_settings
from backend.cosmos_dal import CosmosDAL
from backend.utils import is_valid_email, group_sessions_by_date
from backend.llm_service import LLMService
from backend.blob_io import BlobIO
# REMOVE: from backend.ai_search_service import AISearchService
from backend.chroma_dal import ChromaDAL # <-- ADDED: New ChromaDB Data Access Layer
from backend.rag_service import RAGService

# ------------------------------------------------------------
# App config
# ------------------------------------------------------------
st.set_page_config(page_title="Childcare Insights", page_icon="👶", layout="wide")

def _hide_sidebar_when_unauthenticated():
    # Hide the entire sidebar and default navigation (if any)
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarNav"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
# ------------------------------------------------------------
# Init session state
# ------------------------------------------------------------
def init_state():
    defaults = {
        "logged_in": False,
        "user": None,
        "signup_mode": False,
        "active_session_id": None,
        "chat_buffer": [],
        "rows": [], # Added this to ensure it's always initialized
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()
# ------------------------------------------------------------
# Data/services
# ------------------------------------------------------------
@st.cache_resource
def get_services():
    try:
        settings = load_settings() 
        cosmos = CosmosDAL(settings) 
        ok, msg = cosmos.ping()
        if not ok:
            st.sidebar.error(msg)
            st.error("Unable to connect to Cosmos DB. Check .env and network.")
            st.stop()
        llm = LLMService(settings)
        blob = BlobIO(settings)
        
        # --- Dependency Injection Change: Replace AISearchService with ChromaDAL ---
        chroma_dal = ChromaDAL(settings) # <-- ADDED
        # REMOVE: ai_search = AISearchService(settings)
        
        # MODIFIED: Pass chroma_dal instead of ai_search
        rag = RAGService(settings, blob, chroma_dal, llm) 
        
        # MODIFIED return tuple: removed ai_search_service
        return settings, cosmos, llm, blob, chroma_dal, rag 
    except Exception as e:
        st.error(f"Service Initialization failed :{e}")
        st.stop()

# MODIFIED unpacking: ai_search_service is no longer returned
settings, dal, llm_service, blob_io, chroma_dal_service, rag_service = get_services() 

# ------------------------------------------------------------
# Shared UI
# ------------------------------------------------------------
def header_bar():
    cols = st.columns([0.8, 0.2])
    with cols[0]:
        st.markdown("### 👶 Childcare Insights")
    with cols[1]:
        if st.session_state["logged_in"]:
            st.button("Logout", type="secondary", on_click=logout)

def logout():
    st.session_state["logged_in"] = False
    st.session_state["user"] = None
    st.session_state["active_session_id"] = None
    st.session_state["chat_buffer"] = []
# ------------------------------------------------------------
# Auth pages (rendered inside entrypoint "frame")
# ------------------------------------------------------------
def login_page():
    st.title("🔐 Sign In")
    st.write("Welcome back! Please sign in to continue.")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Login", type="primary", use_container_width=True):
            ok, result = dal.validate_login(username, password)
            if ok:
                st.session_state["logged_in"] = True
                st.session_state["user"] = {
                    "username": result["username"],
                    "email": result["email"],
                    "id": result["id"],
                }
                st.success(f"Logged in as **{result['username']}**")
                st.rerun()
            else:
                st.error(result)
    with col2:
        if st.button("Sign Up", use_container_width=True):
            st.session_state["signup_mode"] = True
            st.rerun()

    st.caption("Tip: On sign-up, your username becomes the part before '@' in your email.")

def signup_page():
    st.title("🆕 Create Account")
    st.write("Enter your email and create a password.")
    email = st.text_input("Email Address")
    password = st.text_input("Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Register", type="primary"):
            if not is_valid_email(email):
                st.error("Please provide a valid email.")
                return
            if len(password) < 8:
                st.error("Password must be at least 8 characters.")
                return
            if password != confirm:
                st.error("Passwords do not match.")
                return

            ok, msg = dal.create_user(email, password)
            if ok:
                st.success(msg)
                st.session_state["signup_mode"] = False
                st.info("You can now sign in with your username and password.")
            else:
                st.error(msg)
    with col2:
        if st.button("Back to Sign In"):
            st.session_state["signup_mode"] = False
            st.rerun()
# ------------------------------------------------------------
# Pages (functions) for navigation
# ------------------------------------------------------------
def file_upload_page():
    # Sidebar content (only visible post-login)
    user = st.session_state.get("user")
    if st.session_state.get("user"):
        st.sidebar.markdown(f"**Signed in as:** {st.session_state['user']['username']}")
    st.sidebar.divider()
    # MODIFIED CAPTION: AI Search -> ChromaDB
    st.sidebar.caption("Blob → ChromaDB → GPT‑4o is now wired.")

    st.header("📤 Upload Files to Azure Blob Storage")
    prefix = f"{settings.blob_folder}/{st.session_state['user']['username']}/"
    st.caption(f"Container: **{settings.storage_container_name}** | Prefix: **{prefix or '(root)'}**")

    tabs = st.tabs(["📄 List Blobs", "⬆️ Upload Files", "🔎 Read / Preview", "🔄 Sync with ChromaDB"]) # MODIFIED TAB TITLE

    # --- Tab 1: List Blobs ---
    with tabs[0]:
        st.subheader("List Blobs")
        recursive = st.checkbox("Recursive listing", value=True)
        ext_filter_raw = st.text_input("Extension filter (comma-separated)", value=".csv,.parquet,.txt", placeholder=".csv,.parquet,.txt")
        ext_filters = [e.strip() for e in ext_filter_raw.split(",") if e.strip()]
        user_loc = st.session_state['user']['username']
        if st.button("Refresh list", type="primary"):
            try:
                rows = blob_io.list_blobs_with_metadata(
                    username=user_loc,
                    recursive=recursive,
                    extension_filter=ext_filters
                )
                st.session_state["rows"] = rows
                st.success(f"Found {len(rows)} blob(s).")
            except Exception as e:
                st.error(f"Failed to list blobs: {e}")

        rows = st.session_state.get("rows", [])
        if rows:
            df_display = pd.DataFrame(rows) if pd else rows
            st.dataframe(df_display, use_container_width=True)
        else:
            st.info("No blobs listed yet. Click **Refresh list**.")

    # --- Tab 2: Upload Files ---
    with tabs[1]:
        st.subheader("Upload Files to Azure Blob")
        st.caption("Files will be uploaded under the configured prefix (if any).")

        uploaded_files = st.file_uploader("Select files", accept_multiple_files=True, label_visibility="visible")
        target_subdir = st.text_input("Optional subfolder under prefix", value="", placeholder="e.g., staged/incoming")
        overwrite_upload = st.checkbox("Overwrite on upload", value=True)

        if uploaded_files and st.button("Upload", type="primary"):
            for uf in uploaded_files:
                try:
                    # Compose blob path: prefix / subdir / filename
                    parts = [p for p in [prefix.strip("/"), target_subdir.strip("/"), uf.name] if p]
                    blob_path = "/".join(parts)

                    content_type = blob_io.detect_content_type(uf.name, getattr(uf, "type", None))
                    data = uf.read()
                    blob_io.upload_blob_bytes(
                        blob_name = blob_path,
                        data=data,
                        overwrite=overwrite_upload,
                        content_type=content_type
                    )
                    st.success(f"Uploaded: {blob_path} ({len(data)} bytes) | content_type={content_type}")
                except Exception as e:
                    st.error(f"Failed to upload {uf.name}: {e}")

    # --- Tab 3: Read / Preview ---
    with tabs[2]:
        st.subheader("Read / Preview Blob")
        rows = st.session_state.get("rows", [])
        options = [r["name"] for r in rows] if rows else []
        blob_choice = st.selectbox("Pick a blob from the list (if available):", options) if options else None
        blob_manual = st.text_input("Or enter a blob path manually:", value=blob_choice or "")

        preview_type = st.radio("Preview type", options=["Auto", "Text", "CSV", "Parquet", "Bytes"], index=0)
        csv_nrows = st.number_input("CSV preview rows", min_value=1, max_value=1000, value=20, step=1)
        parquet_cols = st.text_input("Parquet columns (comma-separated, optional)", value="")

        if st.button("Load preview", type="primary"):
            if not blob_manual.strip():
                st.error("Please select or enter a blob path.")
            else:
                name = blob_manual.strip()
                try:
                    # Auto-detect by extension
                    ext = os.path.splitext(name)[1].lower()
                    chosen = preview_type
                    if preview_type == "Auto":
                        if ext == ".csv":
                            chosen = "CSV"
                        elif ext in (".parquet", ".pq"):
                            chosen = "Parquet"
                        elif ext in (".txt", ".log", ".json"):
                            chosen = "Text"
                        else:
                            chosen = "Bytes"

                    if chosen == "Text":
                        text = blob_io.read_blob_text(blob_name=name,encoding="utf-8")
                        st.code(text[:5000], language="text")  # show up to 5k chars
                    elif chosen == "CSV":
                        if pd is None:
                            st.error("pandas is required for CSV preview. `pip install pandas`")
                        else:
                            df = blob_io.read_csv_blob_df(blob_name=name,nrows=csv_nrows)
                            st.dataframe(df, use_container_width=True)
                    elif chosen == "Parquet":
                        if pd is None:
                            st.error("pandas + pyarrow are required for Parquet preview. `pip install pandas pyarrow`")
                        else:
                            kwargs = {}
                            cols = [c.strip() for c in parquet_cols.split(",") if c.strip()]
                            if cols:
                                kwargs["columns"] = cols
                            df = blob_io.read_parquet_blob_df(blob_name=name,**kwargs)
                            st.dataframe(df, use_container_width=True)
                    else:  # Bytes
                        data = blob_io.read_blob_bytes(blob_name=name,encoding="utf-8")
                        st.write(f"Blob size: {len(data)} bytes")
                        st.code(data[:200].hex(), language="text")  # show first 200 bytes as hex
                    st.success("Preview loaded.")
                except Exception as e:
                    st.error(f"Failed to read/preview blob: {e}")

    st.caption("Config is read from `.env`. For large files, consider chunked streaming if needed.")
    
    # --- Tab 4: Sync with ChromaDB --- # MODIFIED
    with tabs[3]:

        st.subheader("🔄 Sync with ChromaDB (RAG)") # MODIFIED

        # List ALL blobs in the container (not just per-user folder)
        user_loc = st.session_state['user']['username']
        try:
            all_docs = blob_io.list_blobs_with_metadata(
                username=user_loc,
                recursive=recursive,
                extension_filter=ext_filters
            )
        except Exception as e:
            st.error(f"Failed to list container documents: {e}")
            return

        # Filter to CSVs
        csv_docs = [d for d in all_docs if str(d.get("name","")).lower().endswith(".csv")]
        names = [d["name"] for d in csv_docs]
        if not names:
            st.info("No CSV files found in this container.")
            return

        selected = st.selectbox("Choose a CSV from the container", names)
        rows_per_chunk = st.number_input("Rows per chunk", min_value=10, max_value=1000, value=100, step=10)

        # MODIFIED BUTTON TEXT
        if st.button("Sync selected CSV to my ChromaDB", type="primary"): 
            if not user:
                st.error("Please sign in.")
            else:
                try:
                    res = rag_service.ingest_csv_blob(user["username"], selected, rows_per_chunk=int(rows_per_chunk))
                    # MODIFIED SUCCESS MESSAGE to reflect ChromaDB terminology
                    st.success(f"Chunks uploaded: {res['chunks_uploaded']} to collection: {res['collection_name']}") 
                except Exception as e:
                    st.error(f"Sync failed: {e}")

# --------------------- CHAT ---------------------
def load_active_session():
    username = st.session_state["user"]["username"]
    session_id = st.session_state["active_session_id"]
    if not session_id:
        st.session_state["chat_buffer"] = []
        return
    session = dal.get_chat_session(username, session_id)
    st.session_state["chat_buffer"] = session.get("messages", []) if session else []

def chat_page():
    if st.session_state.get("user"):
        st.sidebar.markdown(f"**Signed in as:** {st.session_state['user']['username']}")
    st.sidebar.divider()
    # MODIFIED CAPTION: AI Search -> ChromaDB
    st.sidebar.caption("Blob → ChromaDB → GPT4o is now wired.")

    # MODIFIED HEADER
    st.header("💬 Chat (RAG on ChromaDB + GPT4o)") 
    load_active_session()

    for msg in st.session_state["chat_buffer"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            st.caption(msg["ts"])

    prompt = st.chat_input("Ask about childcare centers, availability, fees, etc.")
    if prompt:
        username = st.session_state["user"]["username"]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not st.session_state["active_session_id"]:
            # First question becomes title/filename
            session = dal.create_chat_session(username, prompt)
            st.session_state["active_session_id"] = session["id"]
            st.session_state["chat_buffer"] = session["messages"]
            st.rerun()
            return

        # Append user's message
        dal.append_message(username, st.session_state["active_session_id"], "user", prompt)
        context = "you are helpful ai assistant"
        # Get answer from GPT‑4o with context (stub)
        answer = llm_service.answer_with_context(prompt,context)

        # --- RAG answer ---
        answer = rag_service.answer_with_rag(username, prompt, top_k=5)

        # Append assistant message
        dal.append_message(username, st.session_state["active_session_id"], "assistant", answer)

        # Refresh UI
        load_active_session()
        st.rerun()

def history_page():
    if st.session_state.get("user"):
        st.sidebar.markdown(f"**Signed in as:** {st.session_state['user']['username']}")
    st.sidebar.divider()
    # MODIFIED CAPTION: AI Search -> ChromaDB
    st.sidebar.caption("Blob → ChromaDB → GPT‑4o is now wired.")

    st.header("🗂️ History")
    username = st.session_state["user"]["username"]
    sessions = dal.list_chat_sessions(username)
    groups = group_sessions_by_date(sessions)

    def render_group(title, items):
        st.subheader(title)
        if not items:
            st.caption("No items")
            return
        for s in items:
            ts = s.get("updated_at", s.get("created_at"))
            label = f"{ts} · '{s.get('title', 'untitled_chat')}'"
            if st.button(label, key=f"open_{s['id']}"):
                st.session_state["active_session_id"] = s["id"]
                # Stay on History; user can click Chat in the navigation,
                # or you can also jump programmatically if you use file pages.
                st.rerun()

    render_group("Today",       groups["Today"])
    render_group("Yesterday",   groups["Yesterday"])
    render_group("Past 7 Days", groups["Past 7 Days"])
    render_group("Older",       groups["Older"])
# ------------------------------------------------------------
# Entry point: frame + conditional navigation
# ------------------------------------------------------------
def main():
    header_bar()

    # --- Auth gate ---
    if not st.session_state["logged_in"]:
        # Hide any sidebar while on login/signup
        _hide_sidebar_when_unauthenticated()

        if st.session_state["signup_mode"]:
            signup_page()
        else:
            login_page()
        return

    # --- Logged in: show sidebar + navigation ---
    pages = [
        st.Page(file_upload_page, title="File Upload", icon="📤"),
        st.Page(chat_page,          title="Chat",          icon="💬", default=True),  # Default page after login
        st.Page(history_page,       title="History",       icon="🗂️"),
    ]

    # Navigation appears in the sidebar; returns the selected page object
    pg = st.navigation(pages, position="sidebar", expanded=True)

    # Execute the selected page
    pg.run()


if __name__ == "__main__":
    main()