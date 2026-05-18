"""
rag_agent.py — Minimal RAG pipeline: retrieve from AI Search → generate with Azure OpenAI.

Used both as a runnable agent and as the 'target' callable for the Evaluation SDK.
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI

load_dotenv(override=True)

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "contoso-policies")
AOAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AOAI_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]

credential = DefaultAzureCredential(process_timeout=30)

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential
)

llm = AzureOpenAI(
    azure_endpoint=AOAI_ENDPOINT,
    azure_ad_token_provider=lambda: credential.get_token(
        "https://cognitiveservices.azure.com/.default"
    ).token,
    api_version="2024-12-01-preview",
)

SYSTEM_PROMPT = (
    "You are a helpful Contoso support assistant. Answer the user's question "
    "using ONLY the provided context. If the context doesn't contain the answer, "
    "say 'I don't have that information.' Do not make up facts."
)


def retrieve(query: str, top_k: int = 3) -> str:
    """Search the index and return the top-k chunks joined as a single string."""
    results = search_client.search(search_text=query, top=top_k)
    chunks = [doc["content"] for doc in results]
    return "\n---\n".join(chunks)


def generate(query: str, context: str) -> str:
    """Call Azure OpenAI with the retrieved context."""
    response = llm.chat.completions.create(
        model=AOAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {query}",
            },
        ],
        temperature=0.0,
        max_tokens=512,
    )
    return response.choices[0].message.content


def ask(query: str) -> dict:
    """
    Full RAG pipeline — returns query, context, and response.

    This signature is what the Evaluation SDK 'target' callable expects:
    it receives a dict row and returns a dict with output fields.
    """
    context = retrieve(query)
    response = generate(query, context)
    return {"context": context, "response": response}


# ── Quick manual test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    q = "What is the refund policy?"
    result = ask(q)
    print(f"Query:    {q}")
    print(f"Context:  {result['context'][:200]}...")
    print(f"Response: {result['response']}")
