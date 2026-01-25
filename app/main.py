from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
import os
from typing import Optional

from app.rag.ask import ask as rag_ask
from app.rag.study import study_next, reset_progress, process_user_answer, get_user_progress
from app.config import USER_ID

app = FastAPI(
    title="Biz Agent API",
    description="Business Agent API backend service",
    version="0.5.0"
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "web", "static")


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: dict


class AnswerRequest(BaseModel):
    answer: str
    topic: Optional[str] = None
    question: Optional[str] = None


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.5.0"
    }


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest):
    try:
        result = rag_ask(request.question)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/study/start")
async def study_start():
    """Reset progress and start study mode from beginning."""
    try:
        progress = reset_progress(USER_ID)
        return {
            "status": "ok",
            "message": "Прогресс сброшен. Готовы начать обучение!",
            "progress": progress
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/study/next")
async def study_next_endpoint():
    """Get next study block."""
    try:
        result = study_next(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/study/answer")
async def study_answer_endpoint(request: AnswerRequest):
    """Process user answer and save decision to memory."""
    try:
        context = {
            "topic": request.topic or "",
            "question": request.question or "Как ты решил реализовать это в своей компании?"
        }
        result = process_user_answer(USER_ID, request.answer, context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/study/progress")
async def study_progress_endpoint():
    """Get current study progress."""
    try:
        progress = get_user_progress(USER_ID)
        if not progress:
            return {"status": "not_started", "progress": None}
        return {"status": "ok", "progress": progress}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
