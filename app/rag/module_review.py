"""Module review: summaries, gaps detection, and module completion."""
from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.llm.deepseek_client import chat_completion
from app.rag.course_map import get_methodology_lectures_ordered


REVIEW_SYSTEM_PROMPT = """Ты — обучающий AI-агент "Трансформация бизнеса с ИИ".
Режим: REVIEW (обзор модуля).

Твоя задача: подвести итоги модуля, связать методологию с решениями пользователя, выявить пробелы.

ФОРМАТ ОТВЕТА (СТРОГО!):

[СМЫСЛ МОДУЛЯ]
- 3-5 пунктов: главные идеи и цели модуля

[ЧТО ГОВОРИТ МЕТОДОЛОГИЯ]
- ключевые шаги и принципы из лекций Верховского
- что нужно было сделать в этом модуле

[КАК ТЫ РЕШИЛ У СЕБЯ]
- перечисли решения пользователя из COMPANY_DECISIONS
- если решений нет — так и напиши

[ПРОБЕЛЫ]
- темы из MODULE_TOPICS, по которым нет решений в COMPANY_DECISIONS
- если пробелов нет — "Все ключевые темы проработаны"

[ВОПРОСЫ ДЛЯ ЗАКРЕПЛЕНИЯ]
1-3 вопроса для самопроверки по модулю

[РЕКОМЕНДАЦИЯ]
- если есть пробелы: предложи доработать решения
- если всё ок: предложи перейти к следующему модулю
"""

MODULE_SUMMARY_PROMPT = """Ты — обучающий AI-агент. Пользователь подводит итог модуля.

Твоя задача:
1. Подтвердить итог или предложить дополнения
2. Сформировать запись для памяти

ДОБАВЬ в конце ответа:

<memory_write>
{
  "memory_type": "module_summary",
  "related_module": <number>,
  "related_topic": "Итог модуля X",
  "user_decision_raw": "<точный текст пользователя>",
  "user_decision_normalized": "<краткое резюме итога>"
}
</memory_write>
"""


def get_module_methodology_chunks(module: int) -> list[dict]:
    """Get all methodology chunks for a module."""
    client = get_client()

    # Get methodology lectures for this module
    lectures = client.table("course_lectures") \
        .select("lecture_id, lecture_title") \
        .eq("speaker_type", "methodology") \
        .eq("module", module) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .execute()

    if not lectures.data:
        return []

    lecture_ids = [l["lecture_id"] for l in lectures.data]

    # Get chunks for these lectures (with pagination)
    all_chunks = []
    for lecture_id in lecture_ids:
        offset = 0
        limit = 100
        while True:
            chunks = client.table("course_chunks") \
                .select("chunk_id, lecture_id, content, parent_topic, content_type") \
                .eq("lecture_id", lecture_id) \
                .order("sequence_order", desc=False) \
                .range(offset, offset + limit - 1) \
                .execute()

            if not chunks.data:
                break
            all_chunks.extend(chunks.data)
            if len(chunks.data) < limit:
                break
            offset += limit

    return all_chunks


def get_module_topics(module: int) -> list[str]:
    """Extract key topics from module methodology lectures."""
    client = get_client()

    # Get methodology lectures for this module
    lectures = client.table("course_lectures") \
        .select("lecture_id, lecture_title") \
        .eq("speaker_type", "methodology") \
        .eq("module", module) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .execute()

    topics = []
    for lec in (lectures.data or []):
        topics.append(lec["lecture_title"])

    return topics


def get_module_decisions(user_id: str, module: int) -> list[dict]:
    """Get all user decisions for a specific module."""
    client = get_client()

    result = client.table("company_memory") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("status", "active") \
        .eq("related_module", module) \
        .order("created_at", desc=False) \
        .execute()

    return result.data or []


def get_module_progress(user_id: str, module: int) -> dict:
    """Check if user has completed all methodology lectures in module."""
    client = get_client()

    # Get all methodology lectures in this module
    lectures = client.table("course_lectures") \
        .select("lecture_id") \
        .eq("speaker_type", "methodology") \
        .eq("module", module) \
        .execute()

    module_lecture_ids = [l["lecture_id"] for l in (lectures.data or [])]

    if not module_lecture_ids:
        return {"total_lectures": 0, "completed": True}

    # Get current progress
    progress = client.table("user_progress") \
        .select("current_lecture_id, current_sequence_order") \
        .eq("user_id", user_id) \
        .execute()

    if not progress.data:
        return {"total_lectures": len(module_lecture_ids), "completed": False}

    current = progress.data[0]
    current_lecture = current.get("current_lecture_id")

    # Get ordered methodology lectures
    methodology = get_methodology_lectures_ordered()

    # Find indices
    current_idx = -1
    module_last_idx = -1

    for i, lec in enumerate(methodology):
        if lec["lecture_id"] == current_lecture:
            current_idx = i
        if lec["lecture_id"] in module_lecture_ids:
            module_last_idx = i

    # Module is complete if current lecture is after last module lecture
    completed = current_idx > module_last_idx if current_idx >= 0 and module_last_idx >= 0 else False

    return {
        "total_lectures": len(module_lecture_ids),
        "completed": completed,
        "current_lecture": current_lecture
    }


def detect_gaps(topics: list[str], decisions: list[dict]) -> list[str]:
    """Detect topics without decisions."""
    decision_topics = set()
    for d in decisions:
        topic = d.get("related_topic", "")
        if topic:
            decision_topics.add(topic.lower())
        # Also check lecture_id
        lecture_id = d.get("related_lecture_id", "")
        if lecture_id:
            decision_topics.add(lecture_id.lower())

    gaps = []
    for topic in topics:
        # Check if any decision relates to this topic
        topic_lower = topic.lower()
        has_decision = False
        for dt in decision_topics:
            if topic_lower in dt or dt in topic_lower:
                has_decision = True
                break
        if not has_decision:
            gaps.append(topic)

    return gaps


def build_review_context(module: int, chunks: list[dict], decisions: list[dict], topics: list[str], gaps: list[str]) -> str:
    """Build context for review prompt."""
    parts = [f"МОДУЛЬ: {module}"]

    # Topics
    parts.append("\nMODULE_TOPICS (ключевые темы модуля):")
    for t in topics:
        parts.append(f"- {t}")

    # Methodology summary (first 500 chars of each lecture's first chunk)
    parts.append("\nMETHODOLOGY_SUMMARY:")
    seen_lectures = set()
    for c in chunks:
        if c["lecture_id"] not in seen_lectures:
            seen_lectures.add(c["lecture_id"])
            parts.append(f"[{c['lecture_id']}] {c['content'][:500]}...")

    # User decisions
    parts.append("\nCOMPANY_DECISIONS (решения пользователя по модулю):")
    if decisions:
        for d in decisions:
            topic = d.get("related_topic", "")
            decision = d.get("user_decision_normalized") or d.get("user_decision_raw", "")
            parts.append(f"- [{topic}]: {decision}")
    else:
        parts.append("- Нет принятых решений")

    # Gaps
    parts.append("\nGAPS (темы без решений):")
    if gaps:
        for g in gaps:
            parts.append(f"- {g}")
    else:
        parts.append("- Все темы проработаны")

    return "\n".join(parts)


def module_review(user_id: str, module: int) -> dict:
    """Generate module review with methodology summary, decisions, and gaps."""
    # Get data
    chunks = get_module_methodology_chunks(module)
    topics = get_module_topics(module)
    decisions = get_module_decisions(user_id, module)
    gaps = detect_gaps(topics, decisions)
    progress = get_module_progress(user_id, module)

    if not chunks:
        return {
            "error": f"No methodology content found for module {module}",
            "module": module
        }

    # Build context
    context = build_review_context(module, chunks, decisions, topics, gaps)

    # Generate review
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": context}
    ]

    answer = chat_completion(messages)

    return {
        "module": module,
        "answer": answer,
        "topics": topics,
        "decisions": [
            {
                "id": str(d.get("id", "")),
                "topic": d.get("related_topic", ""),
                "decision": d.get("user_decision_normalized") or d.get("user_decision_raw", "")
            }
            for d in decisions
        ],
        "gaps": gaps,
        "progress": progress,
        "total_decisions": len(decisions),
        "total_gaps": len(gaps)
    }


def save_module_summary(user_id: str, module: int, summary_text: str) -> str:
    """Save module summary to company_memory."""
    client = get_client()

    # Compute embedding
    embedding = embed_query(summary_text)

    record = {
        "user_id": user_id,
        "memory_type": "module_summary",
        "status": "active",
        "related_module": module,
        "related_topic": f"Итог модуля {module}",
        "user_decision_raw": summary_text,
        "user_decision_normalized": summary_text[:500] if len(summary_text) > 500 else summary_text,
        "embedding": embedding
    }

    result = client.table("company_memory").insert(record).execute()
    return result.data[0]["id"] if result.data else None


def check_module_completion(user_id: str, module: int) -> dict:
    """Check if module is complete and review is recommended."""
    progress = get_module_progress(user_id, module)
    decisions = get_module_decisions(user_id, module)
    topics = get_module_topics(module)
    gaps = detect_gaps(topics, decisions)

    return {
        "module": module,
        "methodology_completed": progress["completed"],
        "total_decisions": len(decisions),
        "total_gaps": len(gaps),
        "review_recommended": progress["completed"] and len(gaps) > 0,
        "ready_for_next_module": progress["completed"] and len(gaps) == 0
    }
