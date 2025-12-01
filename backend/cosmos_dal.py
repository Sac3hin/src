
# backend/cosmos_dal.py
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError, CosmosHttpResponseError

from configurations.config import Settings
from backend.security import hash_password
from backend.utils import sanitize_title, iso_now

class CosmosDAL:
    """
    Data Access Layer for Cosmos DB (NoSQL API).
    Manages: users container and chats container.
    Partition key: /username
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = CosmosClient(settings.cosmos_endpoint, settings.cosmos_key)
        self._database = self._client.create_database_if_not_exists(id=settings.cosmos_db_name)

        # Containers
        self._users = self._database.create_container_if_not_exists(
            id="users",
            partition_key=PartitionKey(path="/username"),
        )
        self._chats = self._database.create_container_if_not_exists(
            id="chats",
            partition_key=PartitionKey(path="/username"),
        )

    # ---- Users ----
    def get_user(self, username: str) -> Optional[Dict]:
        username = username.strip().lower()
        try:
            return self._users.read_item(item=username, partition_key=username)
        except CosmosResourceNotFoundError:
            return None

    def create_user(self, email: str, password: str) -> Tuple[bool, str]:
        username = email.split("@")[0].strip().lower()
        if self.get_user(username):
            return False, "Email/username already registered."
        user_item = {
            "id": username,
            "username": username,
            "email": email.strip().lower(),
            "password_hash": hash_password(password, self._settings.password_salt),
            "created_at": iso_now(),
            "type": "user",
        }
        try:
            self._users.create_item(user_item)
            return True, f"Account created. Your username is **{username}**."
        except CosmosHttpResponseError as e:
            return False, f"Failed to create user: {e}"

    def validate_login(self, username: str, password: str):
        user = self.get_user(username)
        if not user:
            return False, "User not found."
        if user.get("password_hash") != hash_password(password, self._settings.password_salt):
            return False, "Incorrect password."
        return True, user

    # ---- Chats ----
    def create_chat_session(self, username: str, first_prompt: str) -> Dict:
        session_id = str(uuid4())
        title = sanitize_title(first_prompt)
        now_iso = iso_now()
        item = {
            "id": session_id,
            "username": username,
            "title": title,                 # first prompt becomes session filename/title
            "created_at": now_iso,
            "updated_at": now_iso,
            "messages": [
                {"role": "user", "text": first_prompt, "ts": now_iso}
            ],
            "type": "chat_session",
        }
        self._chats.create_item(item)
        return item

    def append_message(self, username: str, session_id: str, role: str, text: str) -> Optional[Dict]:
        try:
            session = self._chats.read_item(item=session_id, partition_key=username)
            ts = iso_now()
            session["messages"].append({"role": role, "text": text, "ts": ts})
            session["updated_at"] = ts
            self._chats.upsert_item(session)
            return session
        except CosmosResourceNotFoundError:
            return None

    def get_chat_session(self, username: str, session_id: str) -> Optional[Dict]:
        try:
            return self._chats.read_item(item=session_id, partition_key=username)
        except CosmosResourceNotFoundError:
            return None

    def list_chat_sessions(self, username: str) -> List[Dict]:
        query = "SELECT c.id, c.title, c.created_at, c.updated_at FROM c WHERE c.type = 'chat_session'"
        items = list(self._chats.query_items(query=query, partition_key=username))
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return items

    # ---- Diagnostics ----
    def ping(self) -> Tuple[bool, str]:
        try:
            _ = list(self._client.list_databases())
            return True, "Cosmos connection OK."
        except Exception as e:
            return False, f"Cosmos connection FAILED: {e}"
