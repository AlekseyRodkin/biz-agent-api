"""Architect session: structured planning for AI implementation."""
import json
import re
from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.llm.deepseek_client import chat_completion
from app.rag.actions import build_actions_context


ARCHITECT_SYSTEM_PROMPT = """Ты — AI-архитектор внедрения ИИ в бизнес.
Режим: ARCHITECT SESSION (проектирование внедрения).

Твоя задача: на основе методологии Верховского и принятых решений пользователя создать структурированный план внедрения ИИ.

КОНТЕКСТ:
- COMPANY_DECISIONS: уже принятые решения пользователя
- METHODOLOGY: ключевые принципы и шаги из курса
- CASE_STUDIES: примеры других компаний (если есть)
- USER_GOAL: цель сессии
- USER_SCOPE: масштаб (company/department/process)
- USER_CONSTRAINTS: ограничения
- TIME_HORIZON: горизонт планирования

ПРАВИЛА:
- Опирайся на COMPANY_DECISIONS как на факты
- Используй METHODOLOGY как framework
- Выявляй пробелы — где нет решений, но они нужны
- Выявляй конфликты — где решения противоречат методологии
- План должен быть конкретным и реалистичным

ФОРМАТ ОТВЕТА (СТРОГО!):

[ЦЕЛЬ]
- сформулируй цель в терминах бизнес-эффекта

[ЧТО УЖЕ ПРИНЯТО]
- перечисли ключевые решения из COMPANY_DECISIONS
- укажи как они связаны с целью

[ЧТО ГОВОРИТ МЕТОДОЛОГИЯ]
- 3-5 ключевых принципов из METHODOLOGY
- как их применить к этой цели

[ПРОБЕЛЫ (НАДО РЕШИТЬ)]
- что ещё не решено, но критично для достижения цели
- конкретные вопросы, на которые нужен ответ

[РИСКИ / КОНФЛИКТЫ]
- если решения противоречат методологии — укажи
- технические/организационные риски
- если рисков нет — так и напиши

[ПЛАН НА {time_horizon} ДНЕЙ]
День 1–2: [конкретные действия] → [ожидаемый результат]
День 3–5: [конкретные действия] → [ожидаемый результат]
...
(разбей план на логические этапы)

[СЛЕДУЮЩИЙ ШАГ]
- что сделать прямо сейчас
"""

ARCHITECT_SAVE_PROMPT = """Ты — AI-архитектор. Пользователь подтверждает итог архитектурной сессии.

Сформируй запись для сохранения:

<memory_write>
{
  "memory_type": "architect_plan",
  "related_topic": "<краткое название плана>",
  "user_decision_raw": "<полный текст плана пользователя>",
  "user_decision_normalized": "<краткое резюме плана в 2-3 предложения>"
}
</memory_write>
"""


def get_relevant_decisions(embedding: list[float], user_id: str, limit: int = 10) -> list[dict]:
    """Get relevant user decisions from company_memory."""
    client = get_client()
    result = client.rpc(
        "match_company_memory",
        {
            "query_embedding": embedding,
            "match_count": limit,
            "p_user_id": user_id
        }
    ).execute()
    return result.data or []


def get_relevant_methodology(embedding: list[float], limit: int = 12) -> list[dict]:
    """Get relevant methodology chunks."""
    client = get_client()
    result = client.rpc(
        "match_course_chunks",
        {
            "query_embedding": embedding,
            "match_count": limit * 2,
            "filter": {}
        }
    ).execute()
    # Filter to methodology only
    methodology = [c for c in (result.data or []) if c.get("speaker_type") == "methodology"]
    return methodology[:limit]


def get_relevant_cases(embedding: list[float], limit: int = 3) -> list[dict]:
    """Get relevant case study chunks."""
    client = get_client()
    result = client.rpc(
        "match_course_chunks",
        {
            "query_embedding": embedding,
            "match_count": limit * 3,
            "filter": {}
        }
    ).execute()
    # Filter to case_study only
    cases = [c for c in (result.data or []) if c.get("speaker_type") == "case_study"]
    return cases[:limit]


def build_architect_context(
    goal: str,
    scope: str,
    constraints: list[str],
    time_horizon: int,
    decisions: list[dict],
    methodology: list[dict],
    cases: list[dict],
    actions_context: str = ""
) -> str:
    """Build context for architect prompt."""
    parts = []

    parts.append(f"USER_GOAL: {goal}")
    parts.append(f"USER_SCOPE: {scope}")
    parts.append(f"TIME_HORIZON: {time_horizon} дней")

    if constraints:
        parts.append(f"USER_CONSTRAINTS: {', '.join(constraints)}")

    # Current actions (if any)
    if actions_context:
        parts.append(f"\n{actions_context}")

    # Decisions
    parts.append("\nCOMPANY_DECISIONS (уже принятые решения):")
    if decisions:
        for d in decisions:
            topic = d.get("related_topic", "")
            decision = d.get("user_decision_normalized") or d.get("user_decision_raw", "")
            memory_type = d.get("memory_type", "decision")
            parts.append(f"- [{topic}] ({memory_type}): {decision}")
    else:
        parts.append("- Нет принятых решений")

    # Methodology
    parts.append("\nMETHODOLOGY (принципы Верховского):")
    if methodology:
        for m in methodology:
            parts.append(f"[{m['chunk_id']}] {m['content'][:600]}...")
    else:
        parts.append("- Нет релевантной методологии")

    # Cases
    if cases:
        parts.append("\nCASE_STUDIES (примеры):")
        for c in cases:
            parts.append(f"[{c['chunk_id']}] {c['content'][:400]}...")

    return "\n".join(parts)


def architect_session(
    user_id: str,
    goal: str,
    scope: str = "company",
    constraints: list[str] = None,
    time_horizon_days: int = 14
) -> dict:
    """Run architect session and generate structured plan."""
    constraints = constraints or []

    # Compute embedding for the goal
    goal_embedding = embed_query(goal)

    # Retrieve context
    decisions = get_relevant_decisions(goal_embedding, user_id, limit=10)
    methodology = get_relevant_methodology(goal_embedding, limit=12)
    cases = get_relevant_cases(goal_embedding, limit=3)

    # Get current actions context
    actions_context = build_actions_context(user_id)

    # Build context
    context = build_architect_context(
        goal, scope, constraints, time_horizon_days,
        decisions, methodology, cases, actions_context
    )

    # Generate plan
    prompt = ARCHITECT_SYSTEM_PROMPT.replace("{time_horizon}", str(time_horizon_days))

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": context}
    ]

    answer = chat_completion(messages)

    return {
        "goal": goal,
        "scope": scope,
        "constraints": constraints,
        "time_horizon_days": time_horizon_days,
        "plan": answer,  # Note: "plan" for consistency with chat.py
        "sources": {
            "decisions": [
                {"id": str(d.get("id", "")), "topic": d.get("related_topic", "")}
                for d in decisions
            ],
            "methodology": [
                {"chunk_id": m.get("chunk_id", ""), "lecture_id": m.get("lecture_id", "")}
                for m in methodology
            ],
            "cases": [
                {"chunk_id": c.get("chunk_id", "")}
                for c in cases
            ]
        },
        "total_decisions_used": len(decisions),
        "total_methodology_used": len(methodology)
    }


def save_architect_plan(user_id: str, plan_text: str, goal: str) -> str:
    """Save architect plan to company_memory."""
    client = get_client()

    # Compute embedding
    embedding = embed_query(plan_text)

    # Normalize: take first 500 chars
    normalized = plan_text[:500] if len(plan_text) > 500 else plan_text

    record = {
        "user_id": user_id,
        "memory_type": "architect_plan",
        "status": "active",
        "related_topic": f"План: {goal[:100]}",
        "user_decision_raw": plan_text,
        "user_decision_normalized": normalized,
        "embedding": embedding
    }

    result = client.table("company_memory").insert(record).execute()
    return result.data[0]["id"] if result.data else None


def parse_memory_write(text: str) -> dict | None:
    """Parse <memory_write> block from response."""
    match = re.search(r'<memory_write>\s*({.*?})\s*</memory_write>', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None
