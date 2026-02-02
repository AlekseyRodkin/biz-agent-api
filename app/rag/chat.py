"""Chat module: conversation history and message routing."""
import json
import logging
import uuid
from datetime import datetime
from app.db.supabase_client import get_client

logger = logging.getLogger(__name__)
from app.rag.ask import ask as rag_ask
from app.rag.study import (
    study_next, process_user_answer, reset_progress, get_user_progress,
    skip_question, get_pending_questions, get_open_questions, get_current_question,
    all_questions_closed, get_questions_stats, get_pending_block_id, clear_pending_questions
)
from app.rag.architect_session import architect_session
from app.rag.rituals import daily_focus, weekly_review
from app.rag.module_review import module_review
from app.rag.actions import create_actions_from_plan, get_actions_status
from app.rag.course_map import get_course_progress
from app.rag.search import search, format_search_results_for_chat, detect_search_intent


# Welcome message for Study mode (auto-start)
STUDY_WELCOME_MESSAGE = """**Привет!** 👋

Мы начинаем обучение по методологии Николая Верховского — «Трансформация бизнеса с ИИ».

Я буду шаг за шагом объяснять подход и помогать тебе адаптировать его под твою компанию. По ходу обучения ты будешь принимать решения, которые я сохраню — они станут основой твоего плана внедрения.

**Как это работает:**
- Я даю блок методологии + вопрос
- Ты отвечаешь своими словами
- Я сохраняю твоё решение и идём дальше

Готов начать? Просто напиши **«Поехали»** или **«Да»**."""


# Command definitions for /help
COMMANDS_HELP = """**Доступные команды:**

| Команда | Описание |
|---------|----------|
| `/help` | Показать список команд |
| `/start` | Сбросить прогресс и начать обучение |
| `/next` | Следующий блок курса |
| `/daily` | Дневной фокус: задачи на сегодня |
| `/weekly` | Недельный обзор: прогресс и блокеры |
| `/review <module>` | Обзор модуля (1-4) |
| `/plan <цель>` | Создать план внедрения |
| `/actions <plan_id>` | Сгенерировать экшены из плана |
| `/exec` | Ссылка на Executive Dashboard |

Пример: `/review 1` или `/plan Внедрить AI в отдел продаж`"""


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


# ============================================================================
# Welcome State Management
# ============================================================================

def has_seen_welcome(user_id: str) -> bool:
    """Check if user has already seen welcome screen."""
    client = get_client()
    result = client.table("user_progress").select("seen_welcome").eq("user_id", user_id).execute()
    if result.data and result.data[0].get("seen_welcome"):
        return True
    return False


def mark_welcome_seen(user_id: str) -> None:
    """Mark that user has seen welcome screen."""
    client = get_client()
    # Ensure user_progress record exists
    existing = client.table("user_progress").select("user_id").eq("user_id", user_id).execute()
    if existing.data:
        client.table("user_progress").update({"seen_welcome": True}).eq("user_id", user_id).execute()
    else:
        # Create new progress record with seen_welcome=True
        client.table("user_progress").insert({
            "user_id": user_id,
            "mode": "study",
            "current_module": 1,
            "current_day": 1,
            "current_sequence_order": 0,
            "seen_welcome": True
        }).execute()


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


def ensure_study_welcome(user_id: str) -> list:
    """
    Ensure Study mode has a welcome message.
    If history is empty, create and save the welcome message.
    Returns the history (with welcome message if created).
    """
    messages = get_history(user_id, mode="study", limit=1)

    if not messages:
        # No messages yet - create welcome message
        save_message(user_id, "study", "assistant", STUDY_WELCOME_MESSAGE, {"type": "welcome"})
        # Return the newly created message
        return get_history(user_id, mode="study", limit=50)

    return get_history(user_id, mode="study", limit=50)


def process_command(user_id: str, command: str, args: str) -> tuple[str, dict]:
    """Process a slash command and return (content, metadata)."""
    cmd = command.lower()

    if cmd == "help":
        return COMMANDS_HELP, {"command": "help"}

    elif cmd == "start":
        progress = reset_progress(user_id)
        return "✅ Прогресс сброшен. Готов к обучению!\n\nНапиши `/next` чтобы начать.", {"command": "start", "progress": progress}

    elif cmd == "next":
        result = study_next(user_id)
        if result.get("completed"):
            return "🎉 Поздравляю! Ты прошёл весь курс!", {"command": "next", "completed": True}
        return result.get("content", ""), {"command": "next", "block": result.get("block"), "progress": result.get("progress")}

    elif cmd == "daily":
        result = daily_focus(user_id)
        # Format daily focus as readable text
        content = f"**📋 Дневной фокус**\n\n"
        if result.get("actions_today"):
            content += "**Задачи на сегодня:**\n"
            for a in result["actions_today"]:
                content += f"- {a['title']} ({a['status']})\n"
        else:
            content += "Нет активных задач на сегодня.\n"
        if result.get("blockers"):
            content += f"\n**⚠️ Блокеры:** {len(result['blockers'])}\n"
            for b in result["blockers"]:
                content += f"- {b['title']}: {b.get('blocked_reason', 'N/A')}\n"
        return content, {"command": "daily", "data": result}

    elif cmd == "weekly":
        result = weekly_review(user_id)
        # Format weekly review as readable text
        content = f"**📊 Недельный обзор**\n\n"
        if result.get("summary"):
            s = result["summary"]
            content += f"- Выполнено: {s.get('done', 0)}\n"
            content += f"- В работе: {s.get('in_progress', 0)}\n"
            content += f"- Заблокировано: {s.get('blocked', 0)}\n"
            content += f"- Запланировано: {s.get('planned', 0)}\n"
        if result.get("recommendations"):
            content += f"\n**💡 Рекомендации:**\n"
            for r in result["recommendations"]:
                content += f"- {r}\n"
        return content, {"command": "weekly", "data": result}

    elif cmd == "review":
        if not args:
            return "❌ Укажите номер модуля: `/review 1`", {"command": "review", "error": "missing_module"}
        try:
            module_num = int(args.strip())
            if module_num < 1 or module_num > 4:
                return "❌ Модуль должен быть от 1 до 4", {"command": "review", "error": "invalid_module"}
            result = module_review(user_id, module_num)
            if result.get("error"):
                return f"❌ {result['error']}", {"command": "review", "error": result["error"]}
            content = f"**📚 Обзор модуля {module_num}**\n\n"
            if result.get("methodology_summary"):
                content += f"**Методология:**\n{result['methodology_summary'][:500]}...\n\n"
            if result.get("decisions"):
                content += f"**Ваши решения:** {len(result['decisions'])}\n"
            if result.get("gaps"):
                content += f"\n**Пробелы:** {', '.join(result['gaps'][:3])}\n"
            return content, {"command": "review", "module": module_num, "data": result}
        except ValueError:
            return "❌ Номер модуля должен быть числом: `/review 1`", {"command": "review", "error": "invalid_format"}

    elif cmd == "plan":
        if not args or len(args.strip()) < 3:
            return "❌ Укажите цель: `/plan Внедрить AI в отдел продаж`", {"command": "plan", "error": "missing_goal"}
        result = architect_session(user_id, args.strip())
        return result.get("plan", ""), {"command": "plan", "goal": args.strip(), "context_used": result.get("context_used", {})}

    elif cmd == "actions":
        if not args:
            return "❌ Укажите plan_id: `/actions <uuid>`", {"command": "actions", "error": "missing_plan_id"}
        try:
            actions = create_actions_from_plan(user_id, args.strip())
            if not actions:
                return "❌ Не удалось создать экшены из плана", {"command": "actions", "error": "no_actions"}
            content = f"✅ Создано {len(actions)} экшенов:\n\n"
            for a in actions[:5]:
                content += f"- {a['title']} (дни: {a.get('day_range', 'N/A')})\n"
            if len(actions) > 5:
                content += f"\n...и ещё {len(actions) - 5}"
            return content, {"command": "actions", "total": len(actions), "plan_id": args.strip()}
        except Exception as e:
            return f"❌ Ошибка: {str(e)}", {"command": "actions", "error": str(e)}

    elif cmd == "exec":
        return "📊 **Executive Dashboard**\n\n[Открыть Dashboard](/ui/exec)", {"command": "exec"}

    else:
        return f"❌ Неизвестная команда: `/{cmd}`\n\nИспользуйте `/help` для списка команд.", {"command": "unknown", "attempted": cmd}


def process_chat_message(user_id: str, mode: str, message: str) -> dict:
    """Process a chat message based on mode and return response."""
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] CHAT_SEND_START mode={mode} user={user_id}")

    # Save user message
    save_message(user_id, mode, "user", message)
    logger.info(f"[{request_id}] CHAT_SEND_DB_USER_SAVED")

    response_content = ""
    metadata = {}

    # Check for search intent (works in any mode)
    is_search, search_query, search_scope = detect_search_intent(message)
    if is_search and search_query:
        logger.info(f"[{request_id}] CHAT_PIPELINE_START type=search scope={search_scope}")
        search_result = search(search_query, user_id, search_scope, limit=8)
        logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=search results={search_result['total']}")
        response_content = format_search_results_for_chat(search_result)
        metadata = {
            "type": "search",
            "query": search_query,
            "scope": search_scope,
            "results": search_result["results"]
        }
        save_message(user_id, mode, "assistant", response_content, metadata)
        return {
            "role": "assistant",
            "content": response_content,
            "metadata": metadata,
            "mode": mode
        }

    # Check for commands (start with /)
    if message.strip().startswith("/"):
        parts = message.strip()[1:].split(maxsplit=1)
        command = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        response_content, metadata = process_command(user_id, command, args)
        # Save assistant response
        save_message(user_id, mode, "assistant", response_content, metadata)
        return {
            "role": "assistant",
            "content": response_content,
            "metadata": metadata,
            "mode": mode
        }

    if mode == "ask":
        # QA mode - use existing ask pipeline
        logger.info(f"[{request_id}] CHAT_PIPELINE_START type=rag_ask")
        result = rag_ask(message)
        logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=rag_ask")
        response_content = result["answer"]
        metadata = {"sources": result["sources"]}

    elif mode == "study":
        # Study mode - human-friendly chat
        # Regular text = continue learning (no /next required)
        msg_lower = message.lower().strip()

        # Handle skip command (/skip q1, пропустить ROI, skip q2)
        skip_query = None
        if message.startswith("/skip "):
            skip_query = message[6:].strip()
        elif msg_lower.startswith("пропустить "):
            skip_query = message[len("пропустить "):].strip()
        elif msg_lower.startswith("skip "):
            skip_query = message[5:].strip()

        if skip_query:
            logger.info(f"[{request_id}] CHAT_PIPELINE_START type=skip_question query={skip_query}")
            remaining, skipped_texts = skip_question(user_id, skip_query)
            logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=skip_question skipped={len(skipped_texts)}")

            # Get updated stats after skip
            stats = get_questions_stats(user_id)
            current_q = get_current_question(user_id)
            can_continue = all_questions_closed(user_id)

            if skipped_texts:
                response_content = f"⏭️ Пропущено: {'; '.join(skipped_texts)}"
                if remaining:
                    response_content += f"\n\n**Следующий вопрос:** {current_q['text']}" if current_q else ""
                    response_content += f"\n\n✅ Закрыто: {stats['answered'] + stats['skipped']} | ⬜ Осталось: {stats['open']}"
                else:
                    response_content += "\n\n✅ Все вопросы закрыты. Напиши «Дальше» для следующего блока."
            else:
                response_content = f"❌ Не нашёл вопрос «{skip_query}» среди ожидающих."
                pending = get_pending_questions(user_id)
                if pending:
                    open_qs = [q for q in pending if q.get("status") == "open"]
                    if open_qs:
                        pending_texts = [f"{q['id']}: {q['text']}" for q in open_qs]
                        response_content += f"\n\nОткрытые вопросы:\n" + "\n".join(f"- {t}" for t in pending_texts)

            metadata = {
                "type": "skip",
                "skipped": skipped_texts,
                "pending_questions": get_pending_questions(user_id),
                "current_question": current_q,
                "questions_stats": stats,
                "can_continue": can_continue
            }
            save_message(user_id, mode, "assistant", response_content, metadata)
            return {
                "role": "assistant",
                "content": response_content,
                "metadata": metadata,
                "mode": mode
            }

        # Patterns that mean "continue" / "yes, let's go"
        continue_patterns = [
            "next", "далее", "дальше", "следующий",
            "да", "yes", "поехали", "давай", "го", "go",
            "ок", "ok", "окей", "okay", "хорошо", "ладно",
            "понял", "понятно", "ясно", "продолжай", "продолжим",
            "готов", "готова", "начнём", "начнем", "вперёд", "вперед"
        ]

        # Check if message is a "continue" signal
        is_continue = any(pattern in msg_lower for pattern in continue_patterns) and len(msg_lower) < 50

        if msg_lower in ["start", "начать", "сброс", "reset"]:
            # Reset progress
            logger.info(f"[{request_id}] CHAT_PIPELINE_START type=reset_progress")
            progress = reset_progress(user_id)
            logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=reset_progress")
            response_content = "✅ Прогресс сброшен. Готов к обучению!\n\nНапиши «Поехали» чтобы начать."
            metadata = {"progress": progress}
        elif is_continue:
            # GATE LOGIC v2.9.4: Check pending_block_id to avoid stale gate blocking
            pending_block_id = get_pending_block_id(user_id)
            progress = get_user_progress(user_id)
            current_lecture_id = progress.get("current_lecture_id") if progress else None

            # Check if pending_questions are stale (no block_id or fresh start)
            should_skip_gate = False
            if not pending_block_id:
                # No block_id = fresh start or after reset
                logger.info(f"[{request_id}] CHAT_GATE_SKIP reason=no_pending_block_id")
                should_skip_gate = True
            elif not current_lecture_id:
                # No current lecture = fresh start, clear stale questions
                logger.info(f"[{request_id}] CHAT_GATE_SKIP reason=no_current_lecture, clearing_stale")
                clear_pending_questions(user_id)
                should_skip_gate = True

            if should_skip_gate:
                # Skip gate, get next block
                logger.info(f"[{request_id}] CHAT_PIPELINE_START type=study_next (fresh)")
                result = study_next(user_id)
                logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=study_next")
                if result.get("completed"):
                    response_content = "🎉 Поздравляю! Ты прошёл весь курс!"
                else:
                    response_content = result.get("answer", "") or result.get("content", "")
                    metadata = {
                        "block": result.get("block"),
                        "progress": result.get("progress"),
                        "sources": result.get("sources", {}),
                        "pending_questions": result.get("pending_questions", []),
                        "current_question": result.get("current_question"),
                        "questions_stats": result.get("questions_stats", {}),
                        "can_continue": result.get("can_continue", False),
                        "fallback_used": result.get("fallback_used", False)
                    }
            else:
                # Normal gate check: block if open questions exist
                open_questions = get_open_questions(user_id)

                if open_questions:
                    # GATE BLOCKED - user must close questions first
                    current = open_questions[0]
                    stats = get_questions_stats(user_id)
                    pending = get_pending_questions(user_id)

                    logger.info(f"[{request_id}] CHAT_GATE_BLOCKED open_questions={len(open_questions)}")

                    response_content = f"⚠️ **Сначала закроем вопрос:**\n\n**{current['text']}**"

                    if stats["answered"] > 0 or stats["skipped"] > 0:
                        response_content += f"\n\n✅ Закрыто: {stats['answered'] + stats['skipped']} | ⬜ Осталось: {stats['open']}"

                    response_content += "\n\n_Ответь на вопрос или напиши «пропустить» чтобы идти дальше._"

                    metadata = {
                        "type": "gate_blocked",
                        "current_question": current,
                        "pending_questions": pending,
                        "questions_stats": stats,
                        "can_continue": False
                    }
                else:
                    # All questions closed - allow next block
                    logger.info(f"[{request_id}] CHAT_PIPELINE_START type=study_next")
                    result = study_next(user_id)
                    logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=study_next")
                    if result.get("completed"):
                        response_content = "🎉 Поздравляю! Ты прошёл весь курс!"
                    else:
                        response_content = result.get("answer", "") or result.get("content", "")
                        metadata = {
                            "block": result.get("block"),
                            "progress": result.get("progress"),
                            "sources": result.get("sources", {}),
                            "pending_questions": result.get("pending_questions", []),
                            "current_question": result.get("current_question"),
                            "questions_stats": result.get("questions_stats", {}),
                            "can_continue": result.get("can_continue", False)
                        }
        else:
            # Process as answer to the question
            logger.info(f"[{request_id}] CHAT_PIPELINE_START type=process_user_answer")
            progress = get_user_progress(user_id)
            context = {
                "topic": progress.get("current_lecture_id", "") if progress else "",
                "question": "Как ты решил реализовать это в своей компании?"
            }
            result = process_user_answer(user_id, message, context)
            logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=process_user_answer")
            response_content = result.get("answer", "") or result.get("response", "")
            metadata = {
                "decision_saved": result.get("memory_saved", False),
                "decision_id": result.get("memory_id"),
                "decision_summary": result.get("decision_summary"),
                "pending_questions": result.get("pending_questions", []),
                "current_question": result.get("current_question"),
                "questions_stats": result.get("questions_stats", {}),
                "all_closed": result.get("all_closed", False),
                "can_continue": result.get("can_continue", False)
            }
            # After processing answer, guide user based on can_continue
            if response_content:
                if result.get("can_continue", False):
                    response_content += "\n\n---\n\n**Отлично!** Напиши «Дальше» когда будешь готов к следующему блоку."
                # If not all closed, the next question is already in response from process_user_answer

    elif mode == "architect":
        # Architect mode - generate implementation plan
        logger.info(f"[{request_id}] CHAT_PIPELINE_START type=architect_session")
        result = architect_session(user_id, message)
        logger.info(f"[{request_id}] CHAT_PIPELINE_DONE type=architect_session")
        response_content = result.get("plan", "")
        metadata = {
            "goal": result.get("goal"),
            "scope": result.get("scope"),
            "context_used": result.get("context_used", {})
        }

    # Save assistant response
    save_message(user_id, mode, "assistant", response_content, metadata)
    logger.info(f"[{request_id}] CHAT_SEND_DB_ASSISTANT_SAVED len={len(response_content)}")

    logger.info(f"[{request_id}] CHAT_SEND_RESPONSE_SENT")
    return {
        "role": "assistant",
        "content": response_content,
        "metadata": metadata,
        "mode": mode
    }


def get_chat_status(user_id: str) -> dict:
    """Get status info for chat UI header and sidebar."""
    progress = get_user_progress(user_id)
    seen_welcome = has_seen_welcome(user_id)

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

    # Get methodology-based course progress
    course_progress_data = get_course_progress(user_id)

    # Extract methodology progress
    methodology_current = 0
    methodology_total = course_progress_data.get("total_methodology_lectures", 19)
    methodology_percent = course_progress_data.get("percent_methodology", 0)

    if course_progress_data.get("started") and course_progress_data.get("current"):
        current_info = course_progress_data["current"]
        methodology_current = current_info.get("lecture_index", 0)
        # Include completed + partial progress
        completed_count = len(course_progress_data.get("completed_lectures", []))
        methodology_current = completed_count  # Show completed, not current index

    # Also get chunk-based progress as technical metric
    course_stats = client.table("course_chunks") \
        .select("id", count="exact") \
        .execute()
    total_chunks = course_stats.count or 0

    current_chunk = 0
    if progress:
        current_chunk = progress.get("current_sequence_order", 0)

    # Get blocked actions count
    blocked_actions = client.table("action_items") \
        .select("id", count="exact") \
        .eq("user_id", user_id) \
        .eq("status", "blocked") \
        .execute()
    blockers_count = blocked_actions.count or 0

    # Get in_progress actions count
    in_progress_actions = client.table("action_items") \
        .select("id", count="exact") \
        .eq("user_id", user_id) \
        .eq("status", "in_progress") \
        .execute()
    in_progress_count = in_progress_actions.count or 0

    # Get off-track metrics (current_value worse than baseline, not achieved)
    metrics_result = client.table("metrics") \
        .select("id, baseline_value, current_value, target_value, status") \
        .eq("user_id", user_id) \
        .eq("status", "active") \
        .execute()

    off_track_count = 0
    for m in (metrics_result.data or []):
        baseline = m.get("baseline_value")
        current = m.get("current_value")
        target = m.get("target_value")
        if baseline is not None and current is not None and target is not None:
            # Determine if improvement means increase or decrease
            if target > baseline:
                # Higher is better, off-track if current < baseline
                if current < baseline:
                    off_track_count += 1
            else:
                # Lower is better, off-track if current > baseline
                if current > baseline:
                    off_track_count += 1

    return {
        "progress": progress,
        "seen_welcome": seen_welcome,
        "message_counts": {
            "ask": ask_count,
            "study": study_count,
            "architect": architect_count
        },
        "sidebar": {
            "methodology": {
                "completed": methodology_current,
                "total": methodology_total,
                "percent": round(methodology_percent, 1)
            },
            "chunks": {
                "current": current_chunk,
                "total": total_chunks
            },
            "blockers": blockers_count,
            "off_track_metrics": off_track_count,
            "actions_in_progress": in_progress_count
        }
    }
