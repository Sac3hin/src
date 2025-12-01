
# backend/rag_service.py
from typing import List, Dict
from openai import AzureOpenAI
from configurations.config import Settings
from backend.blob_io import BlobIO
#from backend.ai_search_service import AISearchService
from backend.llm_service import LLMService
from backend.chunker import csv_rows_to_chunks
from backend.chroma_dal import ChromaDAL


class RAGService:
    def __init__(self, settings: Settings, blob_io: BlobIO, chroma_dal: ChromaDAL, llm_service: LLMService):
        self._settings = settings
        self._blob = blob_io
        self._chroma = chroma_dal
        self._llm = llm_service

        # Embedding client (Azure OpenAI)
        self._embed_client = AzureOpenAI(
            api_key=settings.openai_key,
            api_version=settings.openai_api_version,
            azure_endpoint=settings.openai_endpoint,
        )
        self._embedding_deployment = settings.embedding_model_name  # set to "text-embedding-3-large" in .env

    # ----- Ingestion pipeline -----
    def ingest_csv_blob(self, username: str, blob_name: str, rows_per_chunk: int = 100) -> Dict:
        """
        Download CSV from Blob Storage, chunk, embed vectors, and upsert into the user's ChromaDB collection.
        """
        # 1) Get/Create Collection (replace ensure_user_index)
        collection = self._chroma.get_or_create_collection(username, blob_name) # <-- MODIFIED

        # 2) Download bytes
        csv_bytes = self._blob.read_blob_bytes(blob_name)

        # 3) Chunk
        chunks = csv_rows_to_chunks(csv_bytes, rows_per_chunk=rows_per_chunk)
    
        # NEW: Prepare documents, metadata, and embeddings list for ChromaDB bulk insert
        texts = []
        metadatas = []
        ids = []
    
        for i, text in enumerate(chunks, start=1):
        # The content and metadata are prepared, but we still need the vector for ChromaDB's add method.
        # Unlike Azure Search, we can just add the text/metadata/ID and let Chroma/LangChain handle the embedding (if using LangChain)
        # OR we can pass the vectors explicitly. Sticking to explicit vectors for consistency with previous RAG logic:
            emb = self._embed_client.embeddings.create(
            model=self._embedding_deployment,
            input=text,
            )
            vec = emb.data[0].embedding # list[float]
        
            texts.append(text)
            metadatas.append({
            "username": username,
            "file_name": blob_name,
            "chunk_no": i,
            })
            ids.append(f"{blob_name}::{i}")

        # 5) Upsert into ChromaDB
        # NOTE: The add method will overwrite documents with the same ID, effectively "upserting".
        collection.add(
            embeddings=vec, # ADDED: Need to pass the vectors explicitly
            documents=texts,
            metadatas=metadatas,
            ids=ids,
        )
    
        # 6) Return result
        return {"collection_name": collection.name, "chunks_uploaded": len(texts)}
    
    # backend/rag_service.py (Modified Query)

    def answer_with_rag(self, username: str, question: str, top_k: int = 5) -> str:
        """
        Embed query, vector-search relevant chunks in the user's ChromaDB, and pass the best context to GPT-4o.
        """
        # 1) Embed query with the SAME embedding model
        q = self._embed_client.embeddings.create(model=self._embedding_deployment, input=question)
        qvec = q.data[0].embedding

        # 2) Search ChromaDB (using all collections for the user's data)
        # The ChromaDAL needs a method to search across all user data or by a query-specific filter.
        # For simplicity, we'll assume a way to search all user documents:
        results = self._chroma.vector_search_user(username, qvec, k=top_k) # <-- NEW CALL

        # Compose context string from the top chunks
        ctx_lines = []
        for r in results:
            # Assuming search results structure: (document, metadata, score)
            doc = r.get("document", "No content")
            meta = r.get("metadata", {})
            file_name = meta.get('file_name', 'N/A')
            chunk_no = meta.get('chunk_no', 'N/A')
            
            ctx_lines.append(f"[{file_name} | chunk {chunk_no}] {doc}")
            
        context = "\n\n---\n".join(ctx_lines) if ctx_lines else "No relevant chunks found."

        return self._llm.answer_with_context(question, context)