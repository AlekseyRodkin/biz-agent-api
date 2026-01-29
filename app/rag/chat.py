"""Chat module: conversation history and message routing."""
import json
from datetime import datetime
from app.db.supabase_client import get_client
from app.rag.ask import ask as rag_ask
from app.rag.study import study_next, process_user_answer, reset_progress, get_user_progress
from app.rag.architect_session import architect_session


def save_message(user_id: str, mode: str, role: str, content: str, metadata: dict = None) -> str:
    """Save a chat message to database."""
    client = get_client()
    data = {
        "user_id": user_id,
        "mode": mode,
        "role": role,
        "content": content,
        "metadata": metadata or {}
    }
    result = client.table("chat_messages").insert(data).execute()
    if result.data:
        return result.data[0]["id"]
    return None


def get_history(user_id: str, mode: str = None, limit: int = 50) -> list:
    """Get chat history, optionally filtered by mode."""
    client = get_client()
    query = client.table("chat_messages").select("*").eq("user_id", user_id)

    if mode:
        query = query.eq("mode", mode)

    result = query.order("created_at", desc=True).limit(limit).execute()

    # Reverse to get chronological order
    messages = result.data if result.data else []
    messages.reverse()
    return messages


def process_chat_message(user_id: str, mode: str, message: str) -> dict:
    """Process a chat message based on mode and return response."""

    # Save user message
    save_message(user_id, mode, "user", message)

    response_content = ""
    metadata = {}

    if mode == "ask":
        # QA mode - use existing ask pipeline
        result = rag_ask(message)
        response_content = result["answer"]
        metadata = {"sources": result["sources"]}

    elif mode == "study":
        # Study mode - handle commands and answers
        msg_lower = message.lower().strip()

        if msg_lower in ["next", "далее", "дальше", "следующий"]:
            # Get next study block
            result = study_next(user_id)
            if result.get("completed"):
                response_content = "🎉 Поздравляю! Ты прошёл весь курс!"
            else:
                response_content = result.get("content", "")
                metadata = {
                    "block": result.get("block"),
                    "progress": result.get("progress")
                }
        elif msg_lower in ["start", "начать", "сброс", "reset"]:
            # Reset progress
            progress = reset_progress(user_id)
            response_content = "✅ Прогресс сброшен. Готов к обучению!\n\nНапиши 'next' чтобы начать."
            metadata = {"progress": progress}
        else:
            # Process as answer
            progress = get_user_progress(user_id)
            context = {
                "topic": progress.get("current_lecture_id", "") if progress else "",
                "question": "Как ты решил реализовать это в своей компании?"
            }
            result = process_user_answer(user_id, message, context)
            response_content = result.get("response", "")
            metadata = {
                "decision_saved": result.get("decision_saved", False),
                "decision_id": result.get("decision_id")
            }

    elif mode == "architect":
        # Architect mode - generate implementation plan
        result = architect_session(user_id, message)
        response_content = result.get("plan", "")
        metadata = {
            "goal": result.get("goal"),
            "scope": result.get("scope"),
            "context_used": result.get("context_used", {})
        }

    # Save assistant response
    save_message(user_id, mode, "assistant", response_content, metadata)

    return {
        "role": "assistant",
        "content": response_content,
        "metadata": metadata,
        "mode": mode
    }


def get_chat_status(user_id: str) -> dict:
    """Get status info for chat UI header."""
    progress = get_user_progress(user_id)

    # Get last messages per mode
    client = get_client()

    # Count messages per mode
    ask_count = len(client.table("chat_messages")
        .select("id")
        .eq("user_id", user_id)
        .eq("mode", "ask")
        .execute().data or [])

    study_count = len(client.table("chat_messages")
        .select("id")
        .eq("user_id", user_id)
        .eq("mode", "study")
        .execute().data or [])

    architect_count = len(client.table("chat_messages")
        .select("id")
        .eq("user_id", user_id)
        .eq("mode", "architect")
        .execute().data or [])

    return {
        "progress": progress,
        "message_counts": {
            "ask": ask_count,
            "study": study_count,
            "architect": architect_count
        }
    }
