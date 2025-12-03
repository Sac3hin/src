# frontend/app.py
"""
Childcare Insights - Frontend (Streamlit)
-----------------------------------------
Streamlit UI that delegates business logic to backend and config layers.
"""
# --- Path bootstrap: ensure project root on sys.path ---
from datetime import datetime
import os, sys
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(FRONTEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import streamlit as st

from configurations.config import load_settings
from backend.cosmos_dal import CosmosDAL
from backend.utils import is_valid_email, group_sessions_by_date
from backend.llm_service import LLMService
from backend.blob_io import BlobIO


# ------------------------------------------------------------
# App config
# ------------------------------------------------------------
st.set_page_config(
    page_title="Jon",
    page_icon="apple-only.png",  # <-- Replace "jon_icon.png" with the actual path/filename of your image
    layout="wide"
)

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
    # Streamlit preserves st.session_state keys across script reruns (including refresh)
    defaults = {
        "logged_in": False,
        "user": None, # Will store the user dictionary (username, email, id)
        "signup_mode": False,
        "active_session_id": None,
        "chat_buffer": [],
        "rows": [], 
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
        return settings, cosmos, llm, blob
    except Exception as e:
        st.error(f"Service Initialization failed :{e}")
        st.stop()

# MODIFIED unpacking: ai_search_service is no longer returned
settings, dal, llm_service, blob_io = get_services() 

# ------------------------------------------------------------
# Shared UI
# ------------------------------------------------------------
def header_bar():
    cols = st.columns([0.8, 0.2])
    with cols[0]:
    # Using HTML/Markdown to display the image and the title
        st.markdown(
        f"""
        <div style="display: flex; align-items: center;">
            <img src="apple-only.png" style="width: 32px; height: 32px; margin-right: 10px;">
            <h3>Jon</h3>
        </div>
        """,
        unsafe_allow_html=True
    )
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
                # Successfully logged in: set state to True and store user details
                st.session_state["logged_in"] = True
                st.session_state["user"] = {
                    "username": result["username"],
                    "email": result["email"],
                    "id": result["id"],
                }
                st.success(f"Logged in as **{result['username']}**")
                st.rerun() # Rerun to switch to the main app page
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

# Helper to change session ID and jump to Chat page
def switch_session(session_id):
    st.session_state["active_session_id"] = session_id
    st.rerun()

def file_upload_page():
    # Sidebar content for this page is now handled in main()
    
    st.header("📤 Upload Files to Azure Blob Storage")
    prefix = f"{settings.blob_folder}/{st.session_state['user']['username']}/"
    st.caption(f"Container: **{settings.storage_container_name}** | Prefix: **{prefix or '(root)'}**")

    tabs = st.tabs(["📄 List Blobs", "⬆️ Upload Files", "🔎 Read / Preview"]) # MODIFIED TAB TITLE

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
    # Header
    user_name = st.session_state['user']['username']
    st.markdown(f"##### **Hi {user_name}, I'm Jon your AI assistant. Ask me anything about childcare centers.** 👋")
    st.divider()

    # Load active session if exists
    load_active_session()

    # 1. Show previous messages
    for msg in st.session_state["chat_buffer"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            st.caption(msg["ts"])

    # 2. Chat input
    prompt = st.chat_input("Type your message...")
    if not prompt:
        return

    username = st.session_state["user"]["username"]

    # ----------------------------
    # CASE A — No session exists
    # ----------------------------
    if not st.session_state["active_session_id"]:
        # Step 1 → Send user’s input to LLM immediately
        context = "You are Jon, an AI assistant helping users with childcare center information."
        assistant_reply = llm_service.answer_with_context(prompt, context)

        # Step 2 → Create a new session based on user's first message
        session = dal.create_chat_session(username, prompt)
        st.session_state["active_session_id"] = session["id"]

        # Step 3 → Save user + assistant messages
        dal.append_message(username, session["id"], "user", prompt)
        dal.append_message(username, session["id"], "assistant", assistant_reply)

        # Step 4 → Reload + rerun UI
        load_active_session()
        st.rerun()
        return

    # ----------------------------
    # CASE B — Existing session
    # ----------------------------
    session_id = st.session_state["active_session_id"]

    # Save user message
    dal.append_message(username, session_id, "user", prompt)

    # LLM answer
    context = "You are Jon, an AI assistant helping users with childcare center information."
    assistant_reply = llm_service.answer_with_context(prompt, context)

    # Save assistant reply
    dal.append_message(username, session_id, "assistant", assistant_reply)

    # Refresh UI
    load_active_session()
    st.rerun()


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
   
    # 2. Custom Sidebar Content
   
       
        # Navigation Pages
    pages = [
            st.Page(chat_page, title="Chat", icon="💬", default=True),
            st.Page(file_upload_page, title="File Upload", icon="📤"),
    ]
 
        # Use st.navigation to create the primary navigation items (Chat, File Upload)
        # Note: 'History' is removed from pages list
    pg = st.navigation(pages, position="sidebar", expanded=True)
       
    st.divider()
 
    with st.sidebar:
       
        # 3. Previous Chats Section
        st.subheader("Previous Chats")
        username = st.session_state["user"]["username"]
        # Fetch up to the last 10 sessions, ordered by most recent update
        sessions = dal.list_chat_sessions(username)
       
        if not sessions:
            st.caption("No previous conversations.")
        else:
            for s in sessions:
                # Truncate title for display
                title = s.get('title', 'Untitled Chat')
                display_title = title[:30] + '...' if len(title) > 30 else title
               
                # Check if this is the active session to style the button
                is_active = st.session_state["active_session_id"] == s["id"]
               
                # Use a unique key for each button
                key = f"prev_chat_{s['id']}"
 
                # Use HTML/CSS to mimic the button style from the image (selected button has colored background)
                style = ""
                if is_active:
                    # Apply custom styling for the active session button
                    style = """
                        <style>
                        .stButton > button[key="{}"] {{
                            background-color: #e6f7ff; /* Light blue/gray background */
                            border-color: #1890ff; /* Blue border */
                            color: #1890ff; /* Blue text */
                            font-weight: bold;
                        }}
                        </style>
                    """.format(key)
                    st.markdown(style, unsafe_allow_html=True)
               
                # Use the unique key for the button
                if st.button(display_title, key=key, use_container_width=True):
                    # On click, set the active session ID and jump to the Chat page
                    switch_session(s["id"])
 
        st.divider()
       
        # Move the "Signed in as" message to the bottom
        st.markdown(
            f"""
            <div style="position: fixed; bottom: 0; left: 0; padding: 10px 15px; background-color: white; width: 100%; box-sizing: border-box; border-top: 1px solid #f0f0f0;">
                <p style="margin: 0; font-size: small;">Signed in as: <b>{st.session_state['user']['username']}</b></p>
            </div>
            """,
            unsafe_allow_html=True
        )
 
    # Execute the selected page
    pg.run()
 
 
if __name__ == "__main__":
    main()