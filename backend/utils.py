
# backend/utils.py
import re
from datetime import datetime, timedelta

def sanitize_title(s: str, max_len: int = 60) -> str:
    s = (s or "").strip()
    if not s:
        s = "untitled_chat"
    s = re.sub(r"[^A-Za-z0-9\-\._ ]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:max_len]

def iso_now() -> str:
    return datetime.utcnow().isoformat()

def is_valid_email(e: str) -> bool:
    return re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", e or "") is not None

def group_sessions_by_date(sessions):
    """
    Group sessions by Today, Yesterday, Past 7 Days, Older.
    sessions: list of dicts with updated_at/created_at ISO timestamps
    """
    groups = {"Today": [], "Yesterday": [], "Past 7 Days": [], "Older": []}
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    for s in sessions:
        dt_str = s.get("updated_at", s.get("created_at"))
        try:
            dt = datetime.fromisoformat(dt_str)
        except Exception:
            dt = now
        d = dt.date()
        if d == today:
            groups["Today"].append(s)
        elif d == yesterday:
            groups["Yesterday"].append(s)
        elif d >= week_ago:
            groups["Past 7 Days"].append(s)
        else:
            groups["Older"].append(s)
    return groups
