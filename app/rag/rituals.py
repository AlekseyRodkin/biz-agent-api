"""Ritual mode: daily focus and weekly review."""
from datetime import datetime, timedelta
from app.db.supabase_client import get_client
from app.llm.deepseek_client import chat_completion
from app.rag.metrics import get_metrics_for_weekly


DAILY_FOCUS_PROMPT = """Ты — AI-ассистент для управления проектами внедрения ИИ.
Режим: DAILY FOCUS (ежедневный фокус).

На основе текущих действий пользователя сформируй краткий фокус на день.

ФОРМАТ ОТВЕТА (СТРОГО!):

[ФОКУС НА СЕГОДНЯ]
- перечисли 1-3 главных действия, на которых нужно сосредоточиться

[БЛОКЕРЫ]
- если есть заблокированные действия — укажи их и причину
- если нет — напиши "Блокеров нет"

[ВОПРОСЫ]
1. Что ты сделаешь первым?
2. Что может помешать выполнению?
3. Какой результат ты ожидаешь к концу дня?
"""

WEEKLY_REVIEW_PROMPT = """Ты — AI-ассистент для управления проектами внедрения ИИ.
Режим: WEEKLY REVIEW (еженедельный обзор).

На основе статистики недели сформируй обзор и рекомендации.

ФОРМАТ ОТВЕТА (СТРОГО!):

[ИТОГИ НЕДЕЛИ]
- что выполнено
- ключевые результаты

[ЧТО НЕ ЗАВЕРШЕНО]
- какие действия остались в работе или запланированы
- почему это важно

[ЭФФЕКТ ЗА НЕДЕЛЮ]
- если есть метрики — укажи изменения (baseline → current, delta)
- если метрик нет — напиши "Метрики не заведены"

[РИСКИ]
- заблокированные действия и их причины
- что может помешать на следующей неделе

[РЕКОМЕНДАЦИИ]
- 2-3 конкретных совета на следующую неделю
- что нужно сделать в первую очередь
"""


def get_actions_for_daily(user_id: str) -> dict:
    """Get actions data for daily focus."""
    client = get_client()

    # Get in_progress actions
    in_progress = client.table("action_items") \
        .select("id, title, day_range, description") \
        .eq("user_id", user_id) \
        .eq("status", "in_progress") \
        .order("sequence_order", desc=False) \
        .execute()

    # Get planned actions (next 3)
    planned = client.table("action_items") \
        .select("id, title, day_range, description") \
        .eq("user_id", user_id) \
        .eq("status", "planned") \
        .order("sequence_order", desc=False) \
        .limit(3) \
        .execute()

    # Get blocked actions
    blocked = client.table("action_items") \
        .select("id, title, day_range, block_reason") \
        .eq("user_id", user_id) \
        .eq("status", "blocked") \
        .execute()

    return {
        "in_progress": in_progress.data or [],
        "planned": planned.data or [],
        "blocked": blocked.data or []
    }


def get_actions_for_weekly(user_id: str) -> dict:
    """Get actions data for weekly review."""
    client = get_client()

    # Calculate week boundaries
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday

    # Get done actions this week
    done = client.table("action_items") \
        .select("id, title, day_range, result, updated_at") \
        .eq("user_id", user_id) \
        .eq("status", "done") \
        .gte("updated_at", week_start.isoformat()) \
        .lte("updated_at", (week_end + timedelta(days=1)).isoformat()) \
        .order("updated_at", desc=True) \
        .execute()

    # Get in_progress
    in_progress = client.table("action_items") \
        .select("id, title, day_range") \
        .eq("user_id", user_id) \
        .eq("status", "in_progress") \
        .execute()

    # Get planned
    planned = client.table("action_items") \
        .select("id, title, day_range") \
        .eq("user_id", user_id) \
        .eq("status", "planned") \
        .execute()

    # Get blocked
    blocked = client.table("action_items") \
        .select("id, title, day_range, block_reason") \
        .eq("user_id", user_id) \
        .eq("status", "blocked") \
        .execute()

    # Get active plans
    plans = client.table("company_memory") \
        .select("id, related_topic") \
        .eq("user_id", user_id) \
        .eq("memory_type", "architect_plan") \
        .eq("status", "active") \
        .execute()

    return {
        "done_this_week": done.data or [],
        "in_progress": in_progress.data or [],
        "planned": planned.data or [],
        "blocked": blocked.data or [],
        "active_plans": plans.data or [],
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat()
    }


def build_daily_context(data: dict) -> str:
    """Build context for daily focus prompt."""
    parts = [f"Дата: {datetime.utcnow().strftime('%Y-%m-%d')}"]

    # In progress
    parts.append("\nДЕЙСТВИЯ В РАБОТЕ:")
    if data["in_progress"]:
        for a in data["in_progress"]:
            parts.append(f"- [День {a['day_range']}] {a['title']}")
    else:
        parts.append("- Нет действий в работе")

    # Planned
    parts.append("\nЗАПЛАНИРОВАНО (следующие):")
    if data["planned"]:
        for a in data["planned"]:
            parts.append(f"- [День {a['day_range']}] {a['title']}")
    else:
        parts.append("- Нет запланированных действий")

    # Blocked
    parts.append("\nЗАБЛОКИРОВАНО:")
    if data["blocked"]:
        for a in data["blocked"]:
            reason = a.get("block_reason", "причина не указана")
            parts.append(f"- {a['title']} — {reason}")
    else:
        parts.append("- Нет заблокированных действий")

    return "\n".join(parts)


def build_weekly_context(data: dict, metrics_context: str = "") -> str:
    """Build context for weekly review prompt."""
    parts = [f"Неделя: {data['week_start']} — {data['week_end']}"]

    # Done this week
    parts.append("\nВЫПОЛНЕНО ЗА НЕДЕЛЮ:")
    if data["done_this_week"]:
        for a in data["done_this_week"]:
            result = a.get("result", "")
            result_str = f" → {result[:100]}" if result else ""
            parts.append(f"- {a['title']}{result_str}")
    else:
        parts.append("- Ничего не завершено")

    # In progress
    parts.append("\nВ РАБОТЕ:")
    if data["in_progress"]:
        for a in data["in_progress"]:
            parts.append(f"- [День {a['day_range']}] {a['title']}")
    else:
        parts.append("- Нет")

    # Planned
    parts.append("\nЗАПЛАНИРОВАНО:")
    if data["planned"]:
        for a in data["planned"]:
            parts.append(f"- [День {a['day_range']}] {a['title']}")
    else:
        parts.append("- Нет")

    # Blocked
    parts.append("\nЗАБЛОКИРОВАНО:")
    if data["blocked"]:
        for a in data["blocked"]:
            reason = a.get("block_reason", "причина не указана")
            parts.append(f"- {a['title']} — {reason}")
    else:
        parts.append("- Нет")

    # Stats
    total = len(data["done_this_week"]) + len(data["in_progress"]) + len(data["planned"]) + len(data["blocked"])
    done_count = len(data["done_this_week"])
    parts.append(f"\nСТАТИСТИКА: {done_count}/{total} выполнено")

    # Metrics
    if metrics_context:
        parts.append(f"\n{metrics_context}")
    else:
        parts.append("\nМЕТРИКИ: не заведены")

    return "\n".join(parts)


def daily_focus(user_id: str) -> dict:
    """Generate daily focus report."""
    data = get_actions_for_daily(user_id)
    context = build_daily_context(data)

    messages = [
        {"role": "system", "content": DAILY_FOCUS_PROMPT},
        {"role": "user", "content": context}
    ]

    answer = chat_completion(messages)

    return {
        "date": datetime.utcnow().strftime('%Y-%m-%d'),
        "answer": answer,
        "actions": {
            "in_progress": [{"id": str(a["id"]), "title": a["title"]} for a in data["in_progress"]],
            "planned": [{"id": str(a["id"]), "title": a["title"]} for a in data["planned"]],
            "blocked": [{"id": str(a["id"]), "title": a["title"], "reason": a.get("block_reason")} for a in data["blocked"]]
        },
        "has_blockers": len(data["blocked"]) > 0
    }


def weekly_review(user_id: str) -> dict:
    """Generate weekly review report."""
    data = get_actions_for_weekly(user_id)
    metrics_context = get_metrics_for_weekly(user_id)
    context = build_weekly_context(data, metrics_context)

    messages = [
        {"role": "system", "content": WEEKLY_REVIEW_PROMPT},
        {"role": "user", "content": context}
    ]

    answer = chat_completion(messages)

    total = len(data["done_this_week"]) + len(data["in_progress"]) + len(data["planned"]) + len(data["blocked"])
    done_count = len(data["done_this_week"])

    return {
        "week_start": data["week_start"],
        "week_end": data["week_end"],
        "answer": answer,
        "stats": {
            "done_this_week": done_count,
            "in_progress": len(data["in_progress"]),
            "planned": len(data["planned"]),
            "blocked": len(data["blocked"]),
            "total": total,
            "progress_percent": round((done_count / total * 100) if total > 0 else 0, 1)
        },
        "active_plans": len(data["active_plans"]),
        "has_blockers": len(data["blocked"]) > 0,
        "has_metrics": bool(metrics_context)
    }


def get_blockers_context(user_id: str) -> str:
    """Get blockers context for integration with other modes."""
    client = get_client()

    blocked = client.table("action_items") \
        .select("title, block_reason") \
        .eq("user_id", user_id) \
        .eq("status", "blocked") \
        .execute()

    if not blocked.data:
        return ""

    lines = ["[ЗАБЛОКИРОВАННЫЕ ДЕЙСТВИЯ — ТРЕБУЮТ ВНИМАНИЯ]"]
    for a in blocked.data:
        reason = a.get("block_reason", "причина не указана")
        lines.append(f"- {a['title']} — {reason}")

    return "\n".join(lines)


def get_no_actions_context(user_id: str) -> str:
    """Check if there are no active actions and suggest creating from plan."""
    client = get_client()

    # Check for any active actions
    active = client.table("action_items") \
        .select("id", count="exact") \
        .eq("user_id", user_id) \
        .in_("status", ["planned", "in_progress"]) \
        .execute()

    if active.count and active.count > 0:
        return ""

    # Check for plans
    plans = client.table("company_memory") \
        .select("id, related_topic") \
        .eq("user_id", user_id) \
        .eq("memory_type", "architect_plan") \
        .eq("status", "active") \
        .limit(1) \
        .execute()

    if plans.data:
        return f"[НЕТ АКТИВНЫХ ДЕЙСТВИЙ]\nЕсть план: {plans.data[0].get('related_topic', 'architect_plan')}\nРекомендация: создай действия из плана через /actions/from-plan"

    return "[НЕТ АКТИВНЫХ ДЕЙСТВИЙ]\nРекомендация: создай architect_plan через /session/architect"
