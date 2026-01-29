from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
import os
from typing import Optional

from app.rag.ask import ask as rag_ask
from app.rag.study import study_next, reset_progress, process_user_answer, get_user_progress
from app.rag.decisions import decisions_review, refine_decision
from app.rag.course_map import get_course_map, get_course_progress
from app.rag.module_review import module_review, save_module_summary, check_module_completion
from app.rag.architect_session import architect_session, save_architect_plan
from app.rag.actions import (
    create_actions_from_plan, get_actions, get_action,
    start_action, complete_action, block_action, get_actions_status
)
from app.config import USER_ID

app = FastAPI(
    title="Biz Agent API",
    description="Business Agent API backend service",
    version="1.2.0"
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


class RefineRequest(BaseModel):
    decision_id: str
    updated_decision: str


class ModuleReviewRequest(BaseModel):
    module: int


class ModuleSummaryRequest(BaseModel):
    module: int
    summary: str


class ArchitectSessionRequest(BaseModel):
    goal: str
    scope: str = "company"
    constraints: list[str] = []
    time_horizon_days: int = 14


class ArchitectPlanSaveRequest(BaseModel):
    goal: str
    plan: str


class ActionsFromPlanRequest(BaseModel):
    plan_id: str


class ActionCompleteRequest(BaseModel):
    result: Optional[str] = None


class ActionBlockRequest(BaseModel):
    reason: str


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.2.0"
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


@app.get("/decisions/review")
async def decisions_review_endpoint():
    """Review all active decisions grouped by module/topic."""
    try:
        result = decisions_review(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/decisions/refine")
async def decisions_refine_endpoint(request: RefineRequest):
    """Refine an existing decision: supersede old, create new."""
    try:
        result = refine_decision(USER_ID, request.decision_id, request.updated_decision)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/course/map")
async def course_map_endpoint():
    """Get full course structure: modules → days → lectures."""
    try:
        result = get_course_map()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/course/progress")
async def course_progress_endpoint():
    """Get user progress with percentages and navigation preview."""
    try:
        result = get_course_progress(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/module/review")
async def module_review_endpoint(request: ModuleReviewRequest):
    """Review a module: methodology summary, decisions, gaps."""
    try:
        result = module_review(USER_ID, request.module)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/module/summary")
async def module_summary_endpoint(request: ModuleSummaryRequest):
    """Save module summary to memory."""
    try:
        summary_id = save_module_summary(USER_ID, request.module, request.summary)
        if not summary_id:
            raise HTTPException(status_code=500, detail="Failed to save summary")
        return {
            "status": "ok",
            "module": request.module,
            "summary_id": str(summary_id),
            "message": f"Итог модуля {request.module} сохранён"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/module/status/{module}")
async def module_status_endpoint(module: int):
    """Check module completion status."""
    try:
        result = check_module_completion(USER_ID, module)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/session/architect")
async def architect_session_endpoint(request: ArchitectSessionRequest):
    """Run architect session: structured planning for AI implementation."""
    try:
        result = architect_session(
            USER_ID,
            request.goal,
            request.scope,
            request.constraints,
            request.time_horizon_days
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/session/architect/save")
async def architect_plan_save_endpoint(request: ArchitectPlanSaveRequest):
    """Save architect plan to memory."""
    try:
        plan_id = save_architect_plan(USER_ID, request.plan, request.goal)
        if not plan_id:
            raise HTTPException(status_code=500, detail="Failed to save plan")
        return {
            "status": "ok",
            "plan_id": str(plan_id),
            "message": "Архитектурный план сохранён"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/actions/from-plan")
async def actions_from_plan_endpoint(request: ActionsFromPlanRequest):
    """Generate action items from an architect plan."""
    try:
        actions = create_actions_from_plan(USER_ID, request.plan_id)
        if not actions:
            raise HTTPException(status_code=400, detail="No actions could be parsed from plan")
        return {
            "status": "ok",
            "total_actions": len(actions),
            "actions": [
                {"id": str(a["id"]), "title": a["title"], "day_range": a.get("day_range")}
                for a in actions
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/actions")
async def get_actions_endpoint(status: Optional[str] = None):
    """Get action items, optionally filtered by status."""
    try:
        actions = get_actions(USER_ID, status)
        return {
            "total": len(actions),
            "actions": actions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/actions/status")
async def actions_status_endpoint():
    """Get summary of action items status."""
    try:
        result = get_actions_status(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/actions/{action_id}")
async def get_action_endpoint(action_id: str):
    """Get a single action item."""
    try:
        action = get_action(USER_ID, action_id)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return action
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/actions/{action_id}/start")
async def start_action_endpoint(action_id: str):
    """Set action status to in_progress."""
    try:
        action = start_action(USER_ID, action_id)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return {"status": "ok", "action": action}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/actions/{action_id}/complete")
async def complete_action_endpoint(action_id: str, request: ActionCompleteRequest = None):
    """Set action status to done."""
    try:
        result_text = request.result if request else None
        action = complete_action(USER_ID, action_id, result_text)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return {"status": "ok", "action": action}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/actions/{action_id}/block")
async def block_action_endpoint(action_id: str, request: ActionBlockRequest):
    """Set action status to blocked."""
    try:
        action = block_action(USER_ID, action_id, request.reason)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return {"status": "ok", "action": action}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
