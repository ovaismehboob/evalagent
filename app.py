"""
app.py — FastAPI wrapper for the RAG agent.

Exposes the RAG pipeline as an HTTP API so it can run in a container on AKS.

Endpoints:
  POST /ask   — Run a query through the RAG pipeline
  GET  /health — Liveness / readiness probe
"""

from fastapi import FastAPI
from pydantic import BaseModel
from rag_agent import ask

app = FastAPI(title="Contoso RAG Agent")


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    query: str
    context: str
    response: str


@app.post("/ask", response_model=QueryResponse)
def handle_ask(request: QueryRequest):
    result = ask(request.query)
    return QueryResponse(query=request.query, **result)


@app.get("/health")
def health():
    return {"status": "healthy"}
