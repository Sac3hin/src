
# backend/blob_io.py
#!/usr/bin/env python3
from typing import List, Dict, Optional
import mimetypes
import re
from io import BytesIO, StringIO
import pandas as pd
# Azure SDK
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.pipeline.transport import RequestsTransport

# Suppress InsecureRequestWarning when SSL is disabled
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from configurations.config import Settings


class BlobIO:
    """
    Azure Blob I/O helper wired to Settings (.env):
      - Uses: AZURE_STORAGE_CONNECTION_STRING, AZURE_CONTAINER_NAME,
              AZURE_CONTAINER_FOLDER_NAME, AZURE_SKIP_SSL_VERIFY
      - Creates a per-user folder under the configured root prefix.
      - Provides generic blob operations (list/read/upload) and
        convenience per-user helpers.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

        # Parse skip SSL flag from settings.ssl_cert (string from .env: AZURE_SKIP_SSL_VERIFY)
        raw_skip = str(getattr(settings, "ssl_cert", "")).strip().lower()
        skip_ssl = raw_skip in {"0", "false", "no", "n", "off"}

        # Build a transport that can skip certificate verification if requested.
        transport = RequestsTransport(connection_verify=not skip_ssl)

        # Create BlobServiceClient from connection string, with the custom transport.
        self._service: BlobServiceClient = BlobServiceClient.from_connection_string(
            conn_str=settings.storage_connection_string,
            transport=transport,
        )

        self._container_name = settings.storage_container_name
        # Normalize root folder prefix (no leading/trailing slashes)
        self._root_prefix = settings.blob_folder.strip("/")

        # Ensure container client exists (create container if it doesn't exist)
        self._container = self._service.get_container_client(self._container_name)
        try:
            self._container.create_container()
        except Exception:
            # If already exists or insufficient permissions, ignore.
            pass

    # ---------- Helpers ----------

    @staticmethod
    def _safe_username(username: str) -> str:
        """Normalize username for prefix usage."""
        u = username.strip().lower()
        return re.sub(r"[^a-z0-9._-]", "-", u)

    def _user_prefix(self, username: str) -> str:
        """Return the path prefix for a given user."""
        safe_user = self._safe_username(username)
        if self._root_prefix:
            return f"{self._root_prefix}/{safe_user}"
        return safe_user

    def detect_content_type(self, filename: str, uploaded_type: Optional[str]) -> Optional[str]:
        """
        Infer content type. Prefer uploaded file's MIME type; fallback to filename.
        """
        if uploaded_type:
            return uploaded_type
        guessed, _ = mimetypes.guess_type(filename)
        return guessed

    # ---------- Generic Blob Operations (settings-aware) ----------

    def list_blobs_with_metadata(
        self,
        username: str,
        recursive: bool = False,
        extension_filter: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        List blobs (with metadata) under an optional prefix.

        If `username` is provided, the prefix becomes:
            <root_prefix>/<username>[/<blob_folder>]
        else if `blob_folder` is provided, prefix becomes:
            <blob_folder>/
        else lists all blobs in the container.

        Returns: list of dicts {name, size, last_modified, content_type}
        """

        container_client = self._service.get_container_client(self._container_name)
        # Compose prefix
        blob_folders = self._root_prefix+'/'+username
        prefix = blob_folders.strip("/")+ "/" if (blob_folders and blob_folders.strip()) else None
        rows: List[Dict] = []

        # Choose iterator based on `recursive`
        iterator = container_client.walk_blobs(name_starts_with=prefix) if recursive \
            else container_client.list_blobs(name_starts_with=prefix)

        for item in iterator:
            if hasattr(item, "name"):
                name = item.name
                if extension_filter:
                    if not any(name.lower().endswith(ext.lower()) for ext in extension_filter):
                        continue

                content_type = None
                cs = getattr(item, "content_settings", None)
                if cs:
                    # content_settings may be an object with attribute or dict-like
                    try:
                        content_type = cs.content_type
                    except AttributeError:
                        content_type = cs.get("content_type") if isinstance(cs, dict) else None

                rows.append({
                    "name": name,
                    "size": getattr(item, "size", None),
                    "last_modified": getattr(item, "last_modified", None),
                    "content_type": content_type,
                })

        return rows

    def upload_blob_bytes(
        self,
        blob_name: str,
        data: bytes,
        content_type: Optional[str] = None,
        overwrite: bool = True,
    ) -> str:
        """
        Upload raw bytes to a blob path within the configured container.
        Preserves folder structure in `blob_name`. Returns the blob URL.
        """
        cs = ContentSettings(content_type=content_type) if content_type else None
        blob_client = self._container.get_blob_client(blob=blob_name)
        blob_client.upload_blob(data=data, overwrite=overwrite, content_settings=cs)
        return blob_client.url

    def read_blob_bytes(self, blob_name: str) -> bytes:
        """
        Read an entire blob into memory as bytes.
        """
        blob_client = self._container.get_blob_client(blob=blob_name)
        stream = blob_client.download_blob()
        return stream.readall()

    def read_blob_text(self, blob_name: str, encoding: str = "utf-8") -> str:
        """
        Read a blob into memory as decoded text.
        """
        raw = self.read_blob_bytes(blob_name)
        return raw.decode(encoding)

    def read_csv_blob_df(self, blob_name: str, **read_csv_kwargs):
        """
        Read a CSV blob directly into a pandas DataFrame (in-memory).
        Requires pandas.
        """
        if pd is None:
            raise ImportError("pandas is required to load CSV preview.")
        text = self.read_blob_text(blob_name, encoding="utf-8")
        return pd.read_csv(StringIO(text), **read_csv_kwargs)

    def read_parquet_blob_df(self, blob_name: str, **read_parquet_kwargs):
        """
        Read a Parquet blob directly into a pandas DataFrame (in-memory).
        Requires pandas + pyarrow.
        """
        if pd is None:
            raise ImportError("pandas + pyarrow is required to load Parquet preview.")
        data = self.read_blob_bytes(blob_name)
        return pd.read_parquet(BytesIO(data), **read_parquet_kwargs)


