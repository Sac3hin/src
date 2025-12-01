
# configurations/config.py
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

@dataclass(frozen=True)
class Settings:
    # Cosmos
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_db_name: str
    password_salt: str

    # Azure OpenAI
    openai_endpoint: str
    openai_key: str
    openai_api_version: str
    openai_deployment_name: str
    embedding_model_name: str

    # Azure Storage
    storage_connection_string: str
    storage_container_name: str
    blob_folder: str  
    ssl_cert: str

    # Azure AI Search
    ai_search_service_name: str
    ai_search_endpoint: str
    ai_search_admin_key: str
    ai_search_index_name: str

def load_settings(env_path: Optional[str] = None) -> Settings:
    load_dotenv(dotenv_path=env_path)

    cosmos_endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
    cosmos_key = os.getenv("COSMOS_KEY", "").strip()
    cosmos_db_name = os.getenv("COSMOS_DB_NAME", "childcare_app").strip()
    password_salt = os.getenv("PASSWORD_SALT", "change_me_in_production").strip()

    openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    openai_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "").strip()
    openai_deployment_name = os.getenv("AZURE_DEPLOYMENT_NAME", "").strip()
    embedding_model_name = os.getenv("AZURE_EMBEDDING_MODEL_NAME", "").strip()

    storage_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    storage_container_name = os.getenv("AZURE_CONTAINER_NAME", "").strip()
    blob_folder = os.getenv("AZURE_CONTAINER_FOLDER_NAME", "").strip()
    ssl_cert = os.getenv("AZURE_SKIP_SSL_VERIFY","").strip()

    ai_search_service_name = os.getenv("AZURE_AI_SEARCH_SERVICE_NAME", "").strip()
    ai_search_endpoint = os.getenv("AZURE_AI_SEARCH_SERVICE_ENDPOINT", "").strip()
    ai_search_admin_key = os.getenv("AZURE_AI_SEARCH_ADMIN_KEY", "").strip()
    ai_search_index_name = os.getenv("AZURE_AI_SEARCH_INDEX_NAME","").strip()

    # Minimal validation
    if not storage_connection_string or not storage_container_name:
        raise RuntimeError("Missing Azure Storage settings in .env")
    if not blob_folder:
        raise RuntimeError("Missing AZURE_BLOB_FOLDER in .env (folder prefix inside container)")
    if not ai_search_endpoint or not ai_search_admin_key:
        raise RuntimeError("Missing Azure AI Search settings in .env")
    if not openai_endpoint or not openai_key or not openai_api_version or not openai_deployment_name or not embedding_model_name:
        raise RuntimeError("Missing Azure OpenAI settings in .env")
    if not cosmos_endpoint or ".documents.azure.com" not in cosmos_endpoint or not cosmos_key:
        raise RuntimeError("Missing/invalid Cosmos settings in .env")

    return Settings(
        cosmos_endpoint=cosmos_endpoint,
        cosmos_key=cosmos_key,
        cosmos_db_name=cosmos_db_name,
        password_salt=password_salt,
        openai_endpoint=openai_endpoint,
        openai_key=openai_key,
        openai_api_version=openai_api_version,
        openai_deployment_name=openai_deployment_name,
        embedding_model_name=embedding_model_name,
        storage_connection_string=storage_connection_string,
        storage_container_name=storage_container_name,
        blob_folder=blob_folder,
        ssl_cert=ssl_cert,
        ai_search_service_name=ai_search_service_name,
        ai_search_endpoint=ai_search_endpoint,
        ai_search_admin_key=ai_search_admin_key,
        ai_search_index_name=ai_search_index_name,
    )
