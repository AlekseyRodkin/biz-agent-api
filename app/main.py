from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
import os

from app.rag.ask import ask as rag_ask

app = FastAPI(
    title="Biz Agent API",
    description="Business Agent API backend service",
    version="0.2.3"
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "web", "static")


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: dict


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.2.3"
    }


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest):
    try:
        result = rag_ask(request.question)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
