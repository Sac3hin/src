
# backend/llm_service.py
from typing import List
from openai import AzureOpenAI
from configurations.config import Settings

class LLMService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = AzureOpenAI(
            api_key=settings.openai_key,
            api_version=settings.openai_api_version,
            azure_endpoint=settings.openai_endpoint,
        )
        self._chat_deployment = settings.openai_deployment_name

    # --- Chat Completion ---
    def answer_with_context(self, question: str, context: str) -> str:
        system_prompt = (
            "You are a helpful AI assistant."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ]
        resp = self._client.chat.completions.create(
            model=self._chat_deployment,
            messages=messages
        )
        return resp.choices[0].message.content