# backend/chroma_dal.py

import os
import time
from typing import List, Dict, Optional
# Import for rate limit handling
from tenacity import retry, wait_random_exponential, stop_after_attempt, retry_if_exception_type 

import chromadb
from chromadb import Client, Collection
from chromadb.config import Settings as ChromaSettings
from configurations.config import Settings
from openai import AzureOpenAI
from openai import RateLimitError, APIError # Import specific OpenAI exceptions

# --- Embedding Helper with Rate Limit Logic ---
class AzureOpenAIChromaEmbeddings:
    """
    A wrapper to use the AzureOpenAI client for ChromaDB embedding.
    Includes rate limit handling (retry with exponential backoff).
    """
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = AzureOpenAI(
            api_key=settings.openai_key,
            api_version=settings.openai_api_version,
            azure_endpoint=settings.openai_endpoint,
        )
        self._deployment = settings.embedding_model_name

    # Apply tenacity retry logic for RateLimitError
    @retry(
        wait=wait_random_exponential(min=1, max=10), # Wait between 1 and 10 seconds
        stop=stop_after_attempt(6),                  # Retry up to 6 times
        retry=retry_if_exception_type(RateLimitError) # Only retry on rate limit errors
    )
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Azure OpenAI batch embedding handles list of strings efficiently
        response = self._client.embeddings.create(
            model=self._deployment,
            input=texts,
        )
        return [item.embedding for item in response.data]

    # Required by some Chroma/LangChain interfaces (used for single query embedding)
    @retry(
        wait=wait_random_exponential(min=1, max=4),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RateLimitError)
    )
    def embed_query(self, text: str) -> List[float]:
        response = self._client.embeddings.create(
            model=self._deployment,
            input=[text],
        )
        return response.data[0].embedding

    # Implement __call__ for compatibility if Chroma requires it (it usually calls embed_documents/embed_query)
    def __call__(self, text):
        return self.embed_query(text)


class ChromaDAL:
    def __init__(self, settings: Settings):
        self._settings = settings
        
        # 1. Setup persistence directory (ensures storage on the App Service persistent volume)
        self._base_dir = os.path.join(os.getcwd(), "chromadb")
        if not os.path.exists(self._base_dir):
            os.makedirs(self._base_dir)

        # 2. Initialize Chroma Client (Persistent storage)
        self._client = Client(
            ChromaSettings(
                persist_directory=self._base_dir,
                is_persistent=True,
            )
        )
        
        # 3. Initialize the correct embedding function (Azure OpenAI with Rate Limiting)
        self._embed_func = AzureOpenAIChromaEmbeddings(settings)

    def _user_collection_name(self, username: str, file_name: str) -> str:
        """
        Creates a unique, sanitized collection name for a user's file.
        """
        safe_name = ''.join(e for e in file_name if e.isalnum() or e in ['_', '-']).strip().replace(' ', '_')
        safe_user = username.strip().lower().replace("@", "_").replace(" ", "_")
        return f"{safe_user}_{safe_name}"[:63] 

    # --- KEY FUNCTION FOR INDEX REUSE ---
    def get_or_create_collection(self, username: str, file_name: str) -> Collection:
        """
        Gets a Chroma collection if it exists, otherwise creates it.
        This ensures existing collections are reused, avoiding re-indexing.
        """
        name = self._user_collection_name(username, file_name)
        
        # Chroma's get_or_create handles the check and creation logic
        collection = self._client.get_or_create_collection(
            name=name,
            # Pass the embedding function so Chroma can use it for querying (not indexing)
            embedding_function=self._embed_func,
            metadata={
                "username": username,
                "file_name": file_name,
            }
        )
        
        # NOTE: If a collection exists, it is loaded (reused). If it doesn't, it is created.
        return collection
        
    def vector_search_user(self, username: str, query_vector: List[float], k: int = 5) -> List[Dict]:
        """
        Searches all collections belonging to a user.
        """
        # (Implementation remains the same as previously defined)
        # ...
        collections = self._client.list_collections()
        # Simple filter: checks if the collection name starts with the user's sanitized name
        safe_user_prefix = self._user_collection_name(username, "")[:-1] # Get user prefix
        
        results: List[Dict] = []
        
        # In a complex app, you might want to only query collections listed in the metadata that belong to the user
        for collection_dict in collections:
            # Re-initialize collection object using get_collection to ensure it has the embedding_function
            collection_name = collection_dict.name 
            if collection_name.startswith(safe_user_prefix):
                collection = self._client.get_collection(name=collection_name, embedding_function=self._embed_func)

                res = collection.query(
                    query_embeddings=[query_vector],
                    n_results=k,
                    include=['documents', 'metadatas', 'distances']
                )
                
                # Reformat results
                for doc, meta, dist in zip(res['documents'][0], res['metadatas'][0], res['distances'][0]):
                    results.append({
                        "document": doc,
                        "metadata": meta,
                        "score": 1 - dist,
                    })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:k]
    

    