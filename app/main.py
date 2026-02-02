from fastapi import FastAPI, HTTPException, Depends, Request, Form, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
import os
import logging
from typing import Optional
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# Configure logging for all modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

from app.rag.ask import ask as rag_ask
from app.rag.study import study_next, reset_progress, process_user_answer, get_user_progress
from app.rag.decisions import decisions_review, refine_decision, get_user_decisions_list
from app.rag.course_map import get_course_map, get_course_progress
from app.rag.module_review import module_review, save_module_summary, check_module_completion
from app.rag.architect_session import architect_session, save_architect_plan
from app.rag.actions import (
    create_actions_from_plan, get_actions, get_action,
    start_action, complete_action, block_action, get_actions_status
)
from app.rag.rituals import daily_focus, weekly_review
from app.rag.metrics import (
    create_metric, get_metrics, get_metric, update_metric_value,
    calculate_impact, link_action_to_metric, get_metrics_for_action
)
from app.rag.dashboard import executive_dashboard
from app.rag.exports import export_decisions, export_actions, export_metrics, export_plans
from app.rag.chat import get_history, process_chat_message, get_chat_status, ensure_study_welcome, mark_welcome_seen
from app.rag.search import search as rag_search
from app.rag.guardrails import (
    GuardrailError, SCHEMA_VERSION,
    validate_architect_save, validate_metric_create,
    validate_actions_from_plan, validate_action_block,
    validate_action_link_metric, check_duplicate_plan, check_duplicate_metric
)
from app.db.supabase_client import get_client
from app.config import USER_ID, APP_USERNAME, APP_PASSWORD, SESSION_SECRET, SESSION_TTL_DAYS
from app.llm.deepseek_client import LLMError

app = FastAPI(
    title="Biz Agent API",
    description="Business Agent API backend service",
    version="2.9.1"
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "web", "static")

# Session serializer (signed cookies via itsdangerous)
SESSION_MAX_AGE = SESSION_TTL_DAYS * 24 * 60 * 60  # seconds


def get_serializer():
    """Get URLSafeTimedSerializer for session cookies."""
    if not SESSION_SECRET:
        raise HTTPException(status_code=500, detail="SESSION_SECRET not configured")
    return URLSafeTimedSerializer(SESSION_SECRET)


def create_session_cookie(username: str) -> str:
    """Create signed session cookie value."""
    serializer = get_serializer()
    return serializer.dumps({"user": username})


def verify_session_cookie(session: str) -> Optional[str]:
    """Verify session cookie and return username or None."""
    if not session:
        return None
    try:
        serializer = get_serializer()
        data = serializer.loads(session, max_age=SESSION_MAX_AGE)
        return data.get("user")
    except (SignatureExpired, BadSignature):
        return None


def require_session(session: Optional[str] = Cookie(None)) -> str:
    """Dependency to require valid session. Returns username."""
    user = verify_session_cookie(session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_session_or_redirect(request: Request, session: Optional[str] = Cookie(None)) -> Optional[str]:
    """Check session for UI pages. Returns username or None (for redirect)."""
    return verify_session_cookie(session)


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


class MetricCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    scope: str = "company"
    baseline_value: Optional[float] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    related_plan_id: Optional[str] = None


class MetricUpdateRequest(BaseModel):
    current_value: float


class ActionLinkMetricRequest(BaseModel):
    metric_id: str


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": app.version,
        "schema_version": SCHEMA_VERSION
    }


@app.get("/auth/status")
async def auth_status(session: Optional[str] = Cookie(None)):
    """Check auth configuration status (no secrets exposed)."""
    user = verify_session_cookie(session)
    return {
        "authenticated": user is not None,
        "username": user,
        "session_ttl_days": SESSION_TTL_DAYS
    }


# --- Login / Logout ---

LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login | Biz Agent</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body {{ background-color: #f8f9fa; min-height: 100vh; display: flex; align-items: center; }}
        .login-card {{ max-width: 400px; margin: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="login-card">
            <div class="card shadow">
                <div class="card-header bg-primary text-white text-center">
                    <h4><i class="bi bi-shield-lock"></i> Biz Agent Login</h4>
                </div>
                <div class="card-body">
                    {error_html}
                    <form method="POST" action="/login">
                        <div class="mb-3">
                            <label for="username" class="form-label">Username</label>
                            <input type="text" class="form-control" id="username" name="username" required autofocus>
                        </div>
                        <div class="mb-3">
                            <label for="password" class="form-label">Password</label>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                        <button type="submit" class="btn btn-primary w-100">
                            <i class="bi bi-box-arrow-in-right"></i> Login
                        </button>
                    </form>
                </div>
                <div class="card-footer text-muted text-center">
                    <small>Session valid for {ttl_days} days</small>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""


@app.get("/login")
async def login_page(error: Optional[str] = None):
    """Render login page."""
    error_html = ""
    if error:
        error_html = f'<div class="alert alert-danger"><i class="bi bi-exclamation-triangle"></i> {error}</div>'
    html = LOGIN_PAGE_HTML.format(error_html=error_html, ttl_days=SESSION_TTL_DAYS)
    return HTMLResponse(content=html)


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    """Process login form and set session cookie."""
    if not APP_USERNAME or not APP_PASSWORD:
        return RedirectResponse(url="/login?error=Auth+not+configured", status_code=303)

    if username != APP_USERNAME or password != APP_PASSWORD:
        return RedirectResponse(url="/login?error=Invalid+credentials", status_code=303)

    # Create session cookie and redirect to dashboard
    session_value = create_session_cookie(username)
    response = RedirectResponse(url="/ui/exec", status_code=303)
    response.set_cookie(
        key="session",
        value=session_value,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax"
    )
    return response


@app.post("/logout")
async def logout():
    """Clear session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session")
    return response


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


@app.get("/me/decisions")
async def get_my_decisions_endpoint(_: str = Depends(require_session)):
    """Get current user's decisions list for UI display. Requires session."""
    try:
        decisions = get_user_decisions_list(USER_ID)
        return {"total": len(decisions), "decisions": decisions}
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
async def module_summary_endpoint(request: ModuleSummaryRequest, _: str = Depends(require_session)):
    """Save module summary to memory. Requires admin token."""
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
async def architect_plan_save_endpoint(request: ArchitectPlanSaveRequest, _: str = Depends(require_session)):
    """Save architect plan to memory. Requires admin token."""
    try:
        # Guardrails: validate input
        goal, plan = validate_architect_save(request.goal, request.plan)

        # Guardrails: check for duplicates
        duplicate_id = check_duplicate_plan(USER_ID, goal)
        if duplicate_id:
            raise HTTPException(
                status_code=409,
                detail=f"Similar plan already exists (id: {duplicate_id}). Use refine or create with different goal."
            )

        plan_id = save_architect_plan(USER_ID, plan, goal)
        if not plan_id:
            raise HTTPException(status_code=500, detail="Failed to save plan")
        return {
            "status": "ok",
            "plan_id": str(plan_id),
            "message": "Архитектурный план сохранён"
        }
    except GuardrailError as e:
        raise HTTPException(status_code=e.code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/actions/from-plan")
async def actions_from_plan_endpoint(request: ActionsFromPlanRequest, _: str = Depends(require_session)):
    """Generate action items from an architect plan. Requires admin token."""
    try:
        # Guardrails: validate plan exists and is architect_plan
        validate_actions_from_plan(request.plan_id, USER_ID)

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
    except GuardrailError as e:
        raise HTTPException(status_code=e.code, detail=e.message)
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
async def start_action_endpoint(action_id: str, _: str = Depends(require_session)):
    """Set action status to in_progress. Requires admin token."""
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
async def complete_action_endpoint(action_id: str, request: ActionCompleteRequest = None, _: str = Depends(require_session)):
    """Set action status to done. Requires admin token."""
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
async def block_action_endpoint(action_id: str, request: ActionBlockRequest, _: str = Depends(require_session)):
    """Set action status to blocked. Requires admin token."""
    try:
        # Guardrails: validate reason is not empty
        reason = validate_action_block(request.reason)

        action = block_action(USER_ID, action_id, reason)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return {"status": "ok", "action": action}
    except GuardrailError as e:
        raise HTTPException(status_code=e.code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ritual/daily")
async def daily_focus_endpoint():
    """Get daily focus: actions for today and blockers."""
    try:
        result = daily_focus(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ritual/weekly")
async def weekly_review_endpoint():
    """Get weekly review: progress, blockers, recommendations."""
    try:
        result = weekly_review(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/metrics/create")
async def create_metric_endpoint(request: MetricCreateRequest, _: str = Depends(require_session)):
    """Create a new metric for tracking outcomes. Requires admin token."""
    try:
        # Guardrails: validate input
        validate_metric_create(
            request.name,
            request.scope,
            request.related_plan_id,
            USER_ID
        )

        # Guardrails: check for duplicates
        duplicate_id = check_duplicate_metric(USER_ID, request.name)
        if duplicate_id:
            raise HTTPException(
                status_code=409,
                detail=f"Metric with same name already exists (id: {duplicate_id})"
            )

        metric = create_metric(
            USER_ID,
            request.name,
            request.description,
            request.scope,
            request.baseline_value,
            request.target_value,
            request.current_value,
            request.unit,
            request.related_plan_id
        )
        if not metric:
            raise HTTPException(status_code=500, detail="Failed to create metric")
        return {"status": "ok", "metric": metric}
    except GuardrailError as e:
        raise HTTPException(status_code=e.code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics_endpoint(status: Optional[str] = None):
    """Get all metrics, optionally filtered by status."""
    try:
        metrics = get_metrics(USER_ID, status)
        return {"total": len(metrics), "metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics/impact")
async def metrics_impact_endpoint():
    """Get impact analysis across all metrics."""
    try:
        result = calculate_impact(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics/{metric_id}")
async def get_metric_endpoint(metric_id: str):
    """Get a single metric by ID."""
    try:
        metric = get_metric(USER_ID, metric_id)
        if not metric:
            raise HTTPException(status_code=404, detail="Metric not found")
        return metric
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/metrics/{metric_id}/update")
async def update_metric_endpoint(metric_id: str, request: MetricUpdateRequest, _: str = Depends(require_session)):
    """Update the current value of a metric. Requires admin token."""
    try:
        metric = update_metric_value(USER_ID, metric_id, request.current_value)
        if not metric:
            raise HTTPException(status_code=404, detail="Metric not found")
        return {"status": "ok", "metric": metric}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/actions/{action_id}/link-metric")
async def link_action_metric_endpoint(action_id: str, request: ActionLinkMetricRequest, _: str = Depends(require_session)):
    """Link an action to a metric. Requires admin token."""
    try:
        # Guardrails: validate both action and metric exist
        validate_action_link_metric(action_id, request.metric_id, USER_ID)

        action = link_action_to_metric(USER_ID, action_id, request.metric_id)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return {"status": "ok", "action": action}
    except GuardrailError as e:
        raise HTTPException(status_code=e.code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/actions/{action_id}/metric")
async def get_action_metric_endpoint(action_id: str):
    """Get the metric linked to an action."""
    try:
        metric = get_metrics_for_action(USER_ID, action_id)
        if not metric:
            return {"status": "ok", "metric": None, "message": "No metric linked"}
        return {"status": "ok", "metric": metric}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboard/exec")
async def executive_dashboard_endpoint(_: str = Depends(require_session)):
    """Get executive dashboard with aggregated data. Requires admin token."""
    try:
        result = executive_dashboard(USER_ID)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export/decisions")
async def export_decisions_endpoint(format: str = "json", _: str = Depends(require_session)):
    """Export all decisions in JSON, CSV, or Markdown format. Requires admin token."""
    try:
        result = export_decisions(USER_ID, format)
        if format == "csv":
            return PlainTextResponse(content=result, media_type="text/csv")
        if format == "md":
            return PlainTextResponse(content=result, media_type="text/markdown")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export/actions")
async def export_actions_endpoint(format: str = "json", _: str = Depends(require_session)):
    """Export all actions in JSON, CSV, or Markdown format. Requires admin token."""
    try:
        result = export_actions(USER_ID, format)
        if format == "csv":
            return PlainTextResponse(content=result, media_type="text/csv")
        if format == "md":
            return PlainTextResponse(content=result, media_type="text/markdown")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export/metrics")
async def export_metrics_endpoint(format: str = "json", _: str = Depends(require_session)):
    """Export all metrics in JSON, CSV, or Markdown format. Requires admin token."""
    try:
        result = export_metrics(USER_ID, format)
        if format == "csv":
            return PlainTextResponse(content=result, media_type="text/csv")
        if format == "md":
            return PlainTextResponse(content=result, media_type="text/markdown")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/export/plans")
async def export_plans_endpoint(format: str = "json", _: str = Depends(require_session)):
    """Export all architect plans in JSON, CSV, or Markdown format. Requires admin token."""
    try:
        result = export_plans(USER_ID, format)
        if format == "csv":
            return PlainTextResponse(content=result, media_type="text/csv")
        if format == "md":
            return PlainTextResponse(content=result, media_type="text/markdown")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChatSendRequest(BaseModel):
    mode: str  # ask, study, architect
    message: str


class ChatResetRequest(BaseModel):
    scope: str = "current"  # current or all



class SearchRequest(BaseModel):
    query: str
    scope: str = "all"  # all, course, methodology, case_study, memory
    limit: int = 8


@app.get("/chat/history")
async def chat_history_endpoint(
    mode: Optional[str] = None,
    limit: int = 50,
    _: str = Depends(require_session)
):
    """Get chat history, optionally filtered by mode. Requires session."""
    try:
        if mode and mode not in ["ask", "study", "architect"]:
            raise HTTPException(status_code=400, detail="Invalid mode. Use: ask, study, architect")

        # For Study mode: ensure welcome message exists (auto-start)
        if mode == "study":
            messages = ensure_study_welcome(USER_ID)
        else:
            messages = get_history(USER_ID, mode, limit)

        return {"messages": messages, "total": len(messages)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/send")
async def chat_send_endpoint(request: ChatSendRequest, _: str = Depends(require_session)):
    """Send a chat message and get response. Requires session."""
    from fastapi.responses import JSONResponse

    # Validation errors - not retryable
    if request.mode not in ["ask", "study", "architect"]:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid mode. Use: ask, study, architect",
                "request_id": None,
                "retryable": False
            }
        )
    if not request.message.strip():
        return JSONResponse(
            status_code=400,
            content={
                "error": "Message cannot be empty",
                "request_id": None,
                "retryable": False
            }
        )

    try:
        result = process_chat_message(USER_ID, request.mode, request.message)
        return result

    except LLMError as e:
        # Structured LLM error with retryable flag
        status_code = 504 if e.retryable else 502
        return JSONResponse(
            status_code=status_code,
            content={
                "error": e.message,
                "request_id": e.request_id,
                "retryable": e.retryable
            }
        )

    except Exception as e:
        # Unexpected error - potentially retryable
        import uuid
        request_id = str(uuid.uuid4())[:8]
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Внутренняя ошибка сервера",
                "request_id": request_id,
                "retryable": True
            }
        )


@app.post("/chat/reset")
async def chat_reset_endpoint(request: ChatResetRequest, _: str = Depends(require_session)):
    """Reset chat history and progress. Requires session."""
    client = get_client()

    try:
        if request.scope == "current":
            # Get current mode from user_progress
            progress = client.table("user_progress").select("mode").eq("user_id", USER_ID).execute()
            current_mode = progress.data[0]["mode"] if progress.data else "study"
            # Delete only current mode messages
            client.table("chat_messages").delete().eq("user_id", USER_ID).eq("mode", current_mode).execute()
        elif request.scope == "all":
            # Delete all messages
            client.table("chat_messages").delete().eq("user_id", USER_ID).execute()
        else:
            raise HTTPException(status_code=400, detail="Scope must be 'current' or 'all'")

        # Reset progress
        client.table("user_progress").upsert({
            "user_id": USER_ID,
            "mode": "study",
            "current_module": 1,
            "current_day": 1,
            "current_lecture_id": None,
            "current_sequence_order": 0
        }).execute()

        return {"ok": True, "scope": request.scope}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/status")
async def chat_status_endpoint(_: str = Depends(require_session)):
    """Get chat status info for UI header. Requires session."""
    try:
        status = get_chat_status(USER_ID)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/welcome/seen")
async def mark_welcome_seen_endpoint(_: str = Depends(require_session)):
    """Mark that user has seen welcome screen. Requires session."""
    try:
        mark_welcome_seen(USER_ID)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search")
async def search_endpoint(request: SearchRequest, _: str = Depends(require_session)):
    """
    Semantic search across course and memory. Requires session.

    Scopes:
    - all: search everywhere
    - course: all course chunks
    - methodology: only Верховский lectures
    - case_study: only case study lectures
    - memory: only company memory (user decisions)
    """
    try:
        if not request.query or len(request.query.strip()) < 2:
            raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

        valid_scopes = ["all", "course", "methodology", "case_study", "memory"]
        if request.scope not in valid_scopes:
            raise HTTPException(status_code=400, detail=f"Scope must be one of: {', '.join(valid_scopes)}")

        limit = min(max(request.limit, 1), 20)  # Clamp between 1 and 20

        result = rag_search(request.query, USER_ID, request.scope, limit)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/source/chunk/{chunk_id}")
async def get_source_chunk(chunk_id: str, _: str = Depends(require_session)):
    """Get full source content for a chunk. Requires session."""
    try:
        client = get_client()

        # Get chunk with lecture info
        result = client.table("course_chunks") \
            .select("chunk_id, lecture_id, content, clean_content, content_type, speaker_type, sequence_order, metadata") \
            .eq("chunk_id", chunk_id) \
            .execute()

        if not result.data or len(result.data) == 0:
            raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")

        chunk = result.data[0]

        # Get lecture details
        lecture_result = client.table("course_lectures") \
            .select("lecture_title, speaker_name") \
            .eq("lecture_id", chunk["lecture_id"]) \
            .execute()

        lecture = lecture_result.data[0] if lecture_result.data else {}

        return {
            "chunk_id": chunk["chunk_id"],
            "lecture_id": chunk["lecture_id"],
            "lecture_title": lecture.get("lecture_title", ""),
            "speaker_type": chunk["speaker_type"],
            "speaker_name": lecture.get("speaker_name", ""),
            "content_type": chunk["content_type"],
            "sequence_order": chunk["sequence_order"],
            "content_raw": chunk["content"],
            "content_clean": chunk.get("clean_content"),
            "metadata": chunk.get("metadata", {})
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/app")
async def serve_app_ui(session: Optional[str] = Cookie(None)):
    """Chat App UI - main interface. Requires session."""
    user = verify_session_cookie(session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(os.path.join(STATIC_DIR, "app.html"))


@app.get("/ui/exec")
async def serve_exec_ui(session: Optional[str] = Cookie(None)):
    """Executive Dashboard UI with Bootstrap. Requires session."""
    user = verify_session_cookie(session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(os.path.join(STATIC_DIR, "exec.html"))


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
