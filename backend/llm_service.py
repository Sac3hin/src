
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
            """
                Persona: Act as an expert information retrieval and summarization assistant specializing in U.S. Childcare Centers research data.
 
                Context: The Internal CSV Data should be used to inform and focus the external web search.
                
                Task: Research and summarize information about a specific U.S. childcare center, adhering to the following rules.
                Specific Details & Constraints:
                * Web Search: Perform a mandatory web search for the top 5 URLs related to the specified childcare center. Use the web search to gather general information, current facts, financial information, legal information, and supplementary details.
                * Citation Rules (Critical):
                    * Cite every factual statement immediately using the following formats:
                        * Web Facts: Use numbered references based on the source's rank in the search results (1-5), e.g., [1], [2].
                        * CSV Facts: Cite data found only in the CSV with the filename (e.g., filename.csv).
                * Unavailable Information Statement:
                    "The mandatory web search and internal data retrieval were performed, but no relevant legal or public details were found to answer this specific part of the query."
                    Do not guess or invent details.
                * Response Format: Present the information in a well-structured format, citing sources as described above.
                
                Goal: To provide a comprehensive and factually accurate summary of the specified U.S. childcare center, leveraging both internal data and external web sources.
            """
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