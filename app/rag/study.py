"""Study mode: sequential learning through methodology."""
import json
import re
from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.llm.deepseek_client import chat_completion
from app.config import USER_ID, USE_CLEAN_CONTENT, FORCE_FALLBACK_QUESTIONS
from app.rag.decisions import detect_conflicts, build_conflict_context
from app.rag.course_map import build_navigation_block


STUDY_SYSTEM_PROMPT = """Ты — обучающий AI-агент "Трансформация бизнеса с ИИ".
Твоя задача: провести пользователя по методологии и помочь спроектировать внедрение ИИ в его компании.

ПРАВИЛА:
- Приоритет: решения пользователя (COMPANY_MEMORY) > методология > кейсы
- НЕ ЦИТИРУЙ лекции дословно — кратко объясни СУТЬ
- Если есть COMPANY_MEMORY — ссылайся на него
- КРИТИЧЕСКИ ВАЖНО: если есть PREVIOUS_DECISIONS_TO_CHECK, проверь на расхождения

КРИТИЧЕСКИЕ ЗАПРЕТЫ (MEMORY SAFETY):
- ЗАПРЕЩЕНО: брать "решения пользователя" из METHODOLOGY_BLOCK или CASE_STUDIES
- Секция "[ТВОИ РЕШЕНИЯ]" формируется ТОЛЬКО из COMPANY_MEMORY
- Если видишь "мы сделали", "наш кейс" — это НЕ решение пользователя, а пример из курса

ФОРМАТ ОТВЕТА — КОМПАКТНЫЙ (4-6 строк суть + 1 вопрос):

**Суть блока:** [3-4 предложения — главная идея]

**Вопрос:** [ОДИН конкретный вопрос — самый важный первый]

---
<details><summary>Подробнее</summary>

[Если есть COMPANY_MEMORY — как это связано]
[Если есть CASE_STUDIES — 1 пример]
[Если есть расхождения — укажи риск]

SOURCES_USED: [chunk_ids]
</details>

ВАЖНО:
- НЕ ПЕЧАТАЙ ВСЕ ВОПРОСЫ В ТЕКСТЕ — храни их в <pending_questions>, показывай ОДИН
- Первый вопрос обычно про ROI/метрику (как измерить эффект)
- Второй — про данные/ресурсы (что нужно)
- Третий — про владельца/ответственного (кто делает)

<pending_questions>
[
  {"id": "roi", "text": "Как будешь измерять ROI/эффект этого внедрения?"},
  {"id": "data", "text": "Какие данные/ресурсы нужны?"},
  {"id": "owner", "text": "Кто будет владельцем процесса?"}
]
</pending_questions>

Максимум 3 вопроса. ID должны быть осмысленные: roi, data, owner, timeline, budget и т.д.
"""

ANSWER_SYSTEM_PROMPT = """Ты — обучающий AI-агент. Пользователь ответил на вопрос о решении для своей компании.

Твоя задача:
1. Кратко подтвердить ответ (1-2 предложения)
2. Проанализировать, на какие вопросы из PENDING_QUESTIONS пользователь РЕАЛЬНО ответил
3. Если ответ конкретный — сохранить в draft (НЕ в memory!)

ПРАВИЛА ПРОВЕРКИ ОТВЕТОВ (СТРОГО!):

ROI/метрика считается ОТВЕЧЕННОЙ только если:
- Есть формула расчёта ("ROI = (выгода - затраты) / затраты")
- ИЛИ есть конкретные ЧИСЛА ("экономия 3.5ч * 1000₽/час = 3500₽/день")
- ИЛИ явный skip ("пропустить ROI", "не знаю пока", "позже")

Если в ответе нет чисел/формул для ROI-вопроса → ROI остаётся OPEN!

Другие вопросы (data, owner, timeline):
- Ответ конкретный = closed
- Ответ общий/уклончивый = остаётся open

НЕ СОХРАНЯЙ В MEMORY сразу! Только формируй draft ответа:

<draft_answer>
{
  "question_id": "<id вопроса на который ответил>",
  "answer_text": "<текст ответа пользователя>",
  "is_concrete": true/false
}
</draft_answer>

ОБЯЗАТЕЛЬНО в конце ответа — строгий анализ:

<questions_analysis>
{
  "answered": ["data", "owner"],
  "skipped": [],
  "still_open": ["roi"],
  "roi_has_numbers": false,
  "all_closed": false
}
</questions_analysis>

- "answered" — ID вопросов с конкретным ответом
- "skipped" — ID вопросов, которые пользователь явно пропустил
- "still_open" — ID вопросов БЕЗ ответа
- "roi_has_numbers" — true если в ответе на ROI есть цифры/формула
- "all_closed" — true ТОЛЬКО если answered + skipped = все вопросы

Если PENDING_QUESTIONS пустой — ставь all_closed: true.
"""


def get_user_progress(user_id: str) -> dict | None:
    """Get current user progress."""
    client = get_client()
    result = client.table("user_progress").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


# ============================================================================
# Pending Questions Management
# ============================================================================

def parse_pending_questions(text: str) -> list[dict]:
    """Parse <pending_questions> block. Returns [] on any error (never blocks learning).

    New structure: {"id": "roi", "text": "...", "status": "open", "user_answer": null}
    Status: open | answered | skipped
    """
    try:
        match = re.search(r'<pending_questions>\s*(\[.*?\])\s*</pending_questions>', text, re.DOTALL)
        if not match:
            return []  # No block = no questions (OK)
        questions = json.loads(match.group(1))
        # Validate structure and add status="open"
        return [
            {"id": q["id"], "text": q["text"], "status": "open", "user_answer": None}
            for q in questions
            if isinstance(q, dict) and "id" in q and "text" in q
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []  # Parse error = continue without questions (don't block)


def parse_questions_analysis(text: str) -> dict | None:
    """Parse <questions_analysis> block from answer response."""
    try:
        match = re.search(r'<questions_analysis>\s*({.*?})\s*</questions_analysis>', text, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(1))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_pending_questions(user_id: str, questions: list[dict]) -> None:
    """Save pending questions to user_progress."""
    client = get_client()
    client.table("user_progress").update({
        "pending_questions": questions
    }).eq("user_id", user_id).execute()


def get_pending_questions(user_id: str) -> list[dict]:
    """Get pending questions for user."""
    client = get_client()
    result = client.table("user_progress").select("pending_questions").eq("user_id", user_id).execute()
    if result.data and result.data[0].get("pending_questions"):
        return result.data[0]["pending_questions"]
    return []


def mark_questions_answered(user_id: str, answered_ids: list[str], user_answer: str = None) -> list[dict]:
    """Mark specific questions as answered. Returns remaining open questions."""
    questions = get_pending_questions(user_id)
    for q in questions:
        if q["id"] in answered_ids:
            q["status"] = "answered"
            if user_answer:
                q["user_answer"] = user_answer

    # Save updated questions
    save_pending_questions(user_id, questions)

    # Return open questions
    return [q for q in questions if q.get("status") == "open"]


def clear_pending_questions(user_id: str) -> None:
    """Clear all pending questions and block_id (when moving to next block)."""
    client = get_client()
    client.table("user_progress").update({
        "pending_questions": [],
        "pending_block_id": None
    }).eq("user_id", user_id).execute()


# ============================================================================
# Fallback Questions (Backend-owned)
# ============================================================================

FALLBACK_QUESTIONS = [
    {"id": "roi", "text": "Как будешь измерять ROI/эффект этого внедрения?"},
    {"id": "data", "text": "Какие данные/ресурсы нужны для реализации?"},
    {"id": "owner", "text": "Кто будет владельцем процесса/ответственным?"},
    {"id": "next_step", "text": "Какой первый конкретный шаг на ближайшие 48 часов?"}
]


def generate_fallback_questions() -> list[dict]:
    """Generate deterministic fallback questions when LLM doesn't provide them."""
    return [
        {"id": q["id"], "text": q["text"], "status": "open", "user_answer": None}
        for q in FALLBACK_QUESTIONS
    ]


def get_pending_block_id(user_id: str) -> str | None:
    """Get current pending_block_id to check if questions belong to current block."""
    client = get_client()
    result = client.table("user_progress").select("pending_block_id").eq("user_id", user_id).execute()
    if result.data and result.data[0].get("pending_block_id"):
        return result.data[0]["pending_block_id"]
    return None


def save_pending_questions_with_block(user_id: str, questions: list[dict], block_id: str) -> None:
    """Save pending questions along with block_id to track which block they belong to."""
    client = get_client()
    client.table("user_progress").update({
        "pending_questions": questions,
        "pending_block_id": block_id
    }).eq("user_id", user_id).execute()


def compute_block_id(chunks: list[dict]) -> str:
    """Compute a unique block_id from chunks (lecture_id + sequence range)."""
    if not chunks:
        return "unknown"
    first = chunks[0]
    last = chunks[-1]
    lecture_id = first.get("lecture_id", "unknown")
    seq_start = first.get("sequence_order", 0)
    seq_end = last.get("sequence_order", 0)
    return f"{lecture_id}:{seq_start}-{seq_end}"


def skip_question(user_id: str, query: str) -> tuple[list[dict], list[str]]:
    """
    Skip question(s) by ID or partial text match. Sets status to 'skipped'.
    Returns (remaining_open_questions, skipped_texts).
    """
    questions = get_pending_questions(user_id)
    skipped_ids = []
    skipped_texts = []

    query_lower = query.lower().strip()

    for q in questions:
        if q.get("status") != "open":
            continue  # Skip already closed questions
        # Match by ID (e.g., "roi") or by partial text
        if q["id"].lower() == query_lower or query_lower in q["text"].lower():
            skipped_ids.append(q["id"])
            skipped_texts.append(q["text"])

    if skipped_ids:
        for q in questions:
            if q["id"] in skipped_ids:
                q["status"] = "skipped"
        save_pending_questions(user_id, questions)

    return [q for q in questions if q.get("status") == "open"], skipped_texts


def get_open_questions(user_id: str) -> list[dict]:
    """Get questions with status='open'."""
    questions = get_pending_questions(user_id)
    return [q for q in questions if q.get("status") == "open"]


def get_current_question(user_id: str) -> dict | None:
    """Get first open question (the one to show in UI)."""
    open_qs = get_open_questions(user_id)
    return open_qs[0] if open_qs else None


def all_questions_closed(user_id: str) -> bool:
    """Check if all questions are answered or skipped (no open)."""
    questions = get_pending_questions(user_id)
    if not questions:
        return True  # No questions = closed
    return all(q.get("status") in ("answered", "skipped") for q in questions)


def get_questions_stats(user_id: str) -> dict:
    """Get question statistics for UI."""
    questions = get_pending_questions(user_id)
    return {
        "total": len(questions),
        "answered": len([q for q in questions if q.get("status") == "answered"]),
        "skipped": len([q for q in questions if q.get("status") == "skipped"]),
        "open": len([q for q in questions if q.get("status") == "open"])
    }


# ============================================================================
# ROI Validation
# ============================================================================

def analyze_roi_answer(user_answer: str) -> bool:
    """Check if answer contains ROI/metric calculation signals (numbers, formulas)."""
    roi_signals = [
        r'\d+\s*(₽|руб|рублей|р\.|р\b)',  # Currency
        r'\d+\s*(час|ч\.|ч\b|часов|минут|мин)',  # Time
        r'\d+\s*(%|процент)',  # Percentage
        r'\d+\s*(день|дн|дней|недел|месяц|мес|год|лет)',  # Duration
        r'ROI\s*[=:]',  # ROI formula
        r'экономи[яю]|сэконом',  # Economy
        r'выгод[аы]',  # Benefit
        r'окупа',  # Payback
        r'\d+[.,]\d+',  # Decimal numbers
        r'\d+\s*[*×x]\s*\d+',  # Multiplication
    ]
    return any(re.search(pattern, user_answer, re.IGNORECASE) for pattern in roi_signals)


# ============================================================================
# Draft/Commit for Decisions
# ============================================================================

def get_draft_decision(user_id: str) -> dict | None:
    """Get current draft decision if exists."""
    client = get_client()
    result = client.table("user_progress").select("draft_decision").eq("user_id", user_id).execute()
    if result.data and result.data[0].get("draft_decision"):
        return result.data[0]["draft_decision"]
    return None


def save_draft_answer(user_id: str, question_id: str, answer_text: str, topic: str = None) -> None:
    """Save answer to draft (not yet committed to company_memory)."""
    from datetime import datetime

    draft = get_draft_decision(user_id)
    if not draft:
        draft = {
            "topic": topic or "Study decision",
            "answers": [],
            "started_at": datetime.utcnow().isoformat()
        }

    # Update or add answer
    found = False
    for a in draft["answers"]:
        if a["question_id"] == question_id:
            a["answer"] = answer_text
            found = True
            break
    if not found:
        draft["answers"].append({"question_id": question_id, "answer": answer_text})

    # Save draft
    client = get_client()
    client.table("user_progress").update({"draft_decision": draft}).eq("user_id", user_id).execute()


def commit_decision(user_id: str) -> dict | None:
    """Commit draft to company_memory when all questions closed. Returns saved decision."""
    draft = get_draft_decision(user_id)
    if not draft or not draft.get("answers"):
        return None

    progress = get_user_progress(user_id)
    lecture_id = progress.get("current_lecture_id", "") if progress else ""
    module = progress.get("current_module", 1) if progress else 1
    day = progress.get("current_day", 1) if progress else 1

    # Build combined decision text
    answers_text = "\n".join([f"- {a['question_id']}: {a['answer']}" for a in draft["answers"]])
    normalized = f"[{draft['topic']}] {'; '.join([a['answer'][:100] for a in draft['answers'][:3]])}"

    # Save to company_memory
    memory_data = {
        "memory_type": "decision",
        "related_module": module,
        "related_day": day,
        "related_lecture_id": lecture_id,
        "related_topic": draft["topic"],
        "question_asked": "Study block questions",
        "user_decision_raw": answers_text,
        "user_decision_normalized": normalized[:500]
    }

    memory_id = save_memory(user_id, memory_data)

    # Clear draft
    client = get_client()
    client.table("user_progress").update({"draft_decision": None}).eq("user_id", user_id).execute()

    return {
        "memory_id": memory_id,
        "topic": draft["topic"],
        "summary": normalized[:100]
    }


def reset_progress(user_id: str) -> dict:
    """Reset user progress to start of course."""
    client = get_client()
    
    # Find first methodology lecture
    first_lecture = client.table("course_lectures") \
        .select("lecture_id") \
        .eq("speaker_type", "methodology") \
        .order("module", desc=False) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .limit(1) \
        .execute()
    
    first_lecture_id = first_lecture.data[0]["lecture_id"] if first_lecture.data else None
    
    progress = {
        "user_id": user_id,
        "mode": "study",
        "current_module": 1,
        "current_day": 1,
        "current_lecture_id": first_lecture_id,
        "current_sequence_order": 0
    }
    
    client.table("user_progress").upsert(progress, on_conflict="user_id").execute()
    return progress


def get_next_methodology_chunks(progress: dict, limit: int = 5) -> list[dict]:
    """Get next methodology chunks after current position."""
    client = get_client()

    current_lecture_id = progress.get("current_lecture_id")
    current_seq = progress.get("current_sequence_order", 0)

    # CASE 1: Fresh start (current_lecture_id is None) - get first methodology lecture
    if not current_lecture_id:
        first_lecture = client.table("course_lectures") \
            .select("lecture_id") \
            .eq("speaker_type", "methodology") \
            .order("module", desc=False) \
            .order("day", desc=False) \
            .order("lecture_order", desc=False) \
            .limit(1) \
            .execute()

        if not first_lecture.data:
            return []  # No methodology lectures in course

        first_lecture_id = first_lecture.data[0]["lecture_id"]

        chunks = client.table("course_chunks") \
            .select("*") \
            .eq("lecture_id", first_lecture_id) \
            .order("sequence_order", desc=False) \
            .limit(limit) \
            .execute()

        return chunks.data or []

    # CASE 2: Continue from current position - get chunks from current lecture
    chunks = client.table("course_chunks") \
        .select("*") \
        .eq("speaker_type", "methodology") \
        .eq("lecture_id", current_lecture_id) \
        .gt("sequence_order", current_seq) \
        .order("sequence_order", desc=False) \
        .limit(limit) \
        .execute()

    if chunks.data:
        return chunks.data

    # CASE 3: Current lecture finished - move to next methodology lecture
    current_lecture = client.table("course_lectures") \
        .select("module, day, lecture_order") \
        .eq("lecture_id", current_lecture_id) \
        .execute()

    if not current_lecture.data:
        return []

    curr = current_lecture.data[0]

    # Find next methodology lecture
    next_lecture = client.table("course_lectures") \
        .select("lecture_id") \
        .eq("speaker_type", "methodology") \
        .or_(f"module.gt.{curr['module']},and(module.eq.{curr['module']},day.gt.{curr['day']}),and(module.eq.{curr['module']},day.eq.{curr['day']},lecture_order.gt.{curr['lecture_order']})") \
        .order("module", desc=False) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .limit(1) \
        .execute()

    if not next_lecture.data:
        return []  # Course completed

    next_lecture_id = next_lecture.data[0]["lecture_id"]

    # Get first chunks from next lecture
    chunks = client.table("course_chunks") \
        .select("*") \
        .eq("lecture_id", next_lecture_id) \
        .order("sequence_order", desc=False) \
        .limit(limit) \
        .execute()

    return chunks.data or []


def get_relevant_memory(embedding: list[float], user_id: str, limit: int = 3) -> list[dict]:
    """Get relevant company memory entries."""
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


def get_case_studies(embedding: list[float], limit: int = 2) -> list[dict]:
    """Get relevant case study chunks."""
    client = get_client()
    result = client.rpc(
        "match_course_chunks",
        {
            "query_embedding": embedding,
            "match_count": limit * 2,
            "filter": {}
        }
    ).execute()
    # Filter to case_study only
    cases = [c for c in (result.data or []) if c.get("speaker_type") == "case_study"]
    return cases[:limit]


def update_progress(user_id: str, lecture_id: str, sequence_order: int) -> None:
    """Update user progress after viewing a block."""
    client = get_client()
    
    # Get lecture info
    lecture = client.table("course_lectures") \
        .select("module, day") \
        .eq("lecture_id", lecture_id) \
        .execute()
    
    if lecture.data:
        lec = lecture.data[0]
        client.table("user_progress").update({
            "current_module": lec["module"],
            "current_day": lec["day"],
            "current_lecture_id": lecture_id,
            "current_sequence_order": sequence_order
        }).eq("user_id", user_id).execute()


def get_chunk_content(chunk: dict) -> str:
    """Get content from chunk, preferring clean_content if USE_CLEAN_CONTENT is enabled."""
    if USE_CLEAN_CONTENT and chunk.get('clean_content'):
        return chunk['clean_content']
    return chunk['content']


def build_study_context(chunks: list[dict], memory: list[dict], cases: list[dict], conflicts: list[dict] = None) -> str:
    """Build context string for study prompt."""
    parts = []

    if chunks:
        # Filter out student_comment chunks - they should not appear in methodology block
        methodology_chunks = [c for c in chunks if c.get('content_type') != 'student_comment']
        if methodology_chunks:
            parts.append("METHODOLOGY_BLOCK:")
            for c in methodology_chunks:
                content = get_chunk_content(c)
                parts.append(f"[{c['chunk_id']}] {content}\n")

    if memory:
        parts.append("\nCOMPANY_MEMORY (твои предыдущие решения):")
        for m in memory:
            topic = m.get('related_topic', '')
            decision = m.get('user_decision_normalized') or m.get('user_decision_raw', '')
            parts.append(f"- [{topic}]: {decision}")

    if cases:
        parts.append("\nCASE_STUDIES (примеры):")
        for c in cases:
            content = get_chunk_content(c)
            parts.append(f"[{c['chunk_id']}] {content[:500]}...\n")

    # Add conflict context for LLM to analyze
    if conflicts:
        conflict_context = build_conflict_context(conflicts)
        if conflict_context:
            parts.append(conflict_context)

    return "\n".join(parts)


def study_next(user_id: str) -> dict:
    """Get next study block and generate response."""
    progress = get_user_progress(user_id)
    if not progress:
        progress = reset_progress(user_id)

    # Clear previous pending questions when moving to next block
    clear_pending_questions(user_id)

    chunks = get_next_methodology_chunks(progress)

    if not chunks:
        return {
            "answer": "Поздравляю! Вы прошли все доступные материалы курса.",
            "sources": {"methodology": [], "memory": [], "cases": [], "conflicts": []},
            "progress": progress,
            "completed": True,
            "pending_questions": []
        }

    # Compute embedding for the block
    block_text = " ".join([c["content"] for c in chunks])
    block_embedding = embed_query(block_text[:2000])  # Limit for embedding

    # Get relevant memory and cases
    memory = get_relevant_memory(block_embedding, user_id)
    cases = get_case_studies(block_embedding)

    # Detect potential conflicts with previous decisions
    conflicts = detect_conflicts(block_text, user_id, limit=5)

    # Build context and generate response
    context = build_study_context(chunks, memory, cases, conflicts)

    lecture_title = chunks[0].get("parent_topic", "")

    messages = [
        {"role": "system", "content": STUDY_SYSTEM_PROMPT},
        {"role": "user", "content": f"Блок: {lecture_title}\n\n{context}"}
    ]

    answer = chat_completion(messages)

    # Compute block_id for tracking
    block_id = compute_block_id(chunks)

    # Parse pending questions from LLM response
    pending = []
    fallback_used = False
    if not FORCE_FALLBACK_QUESTIONS:
        pending = parse_pending_questions(answer)

    # FALLBACK: If LLM didn't provide questions, generate deterministic fallback
    if not pending:
        pending = generate_fallback_questions()
        fallback_used = True

    # Save questions with block_id
    save_pending_questions_with_block(user_id, pending, block_id)

    # Remove <pending_questions> block from visible response
    clean_answer = re.sub(r'<pending_questions>.*?</pending_questions>', '', answer, flags=re.DOTALL).strip()

    # Update progress
    last_chunk = chunks[-1]
    update_progress(user_id, last_chunk["lecture_id"], last_chunk["sequence_order"])

    # Add navigation block to answer
    navigation = build_navigation_block(user_id)
    if navigation:
        clean_answer = f"{clean_answer}\n\n{navigation}"

    # Get current question and stats for UI
    current_question = get_current_question(user_id)
    stats = get_questions_stats(user_id)

    return {
        "answer": clean_answer,
        "sources": {
            "methodology": [{"chunk_id": c["chunk_id"], "lecture_id": c["lecture_id"], "lecture_title": c.get("lecture_title", "")} for c in chunks],
            "memory": [{"id": str(m.get("id", "")), "topic": m.get("related_topic", "")} for m in memory],
            "cases": [{"chunk_id": c["chunk_id"], "lecture_title": c.get("lecture_title", "")} for c in cases],
            "conflicts": [{"decision_id": c["decision_id"], "topic": c["topic"]} for c in conflicts]
        },
        "progress": get_user_progress(user_id),
        "completed": False,
        "pending_questions": pending,
        "current_question": current_question,
        "questions_stats": stats,
        "can_continue": False,  # Just loaded new block, need to answer questions first
        "fallback_used": fallback_used,
        "block_id": block_id
    }


def parse_memory_write(text: str) -> dict | None:
    """Parse <memory_write> block from agent response."""
    match = re.search(r'<memory_write>\s*({.*?})\s*</memory_write>', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def save_memory(user_id: str, memory_data: dict) -> str:
    """Save decision to company_memory."""
    client = get_client()
    
    # Compute embedding for the decision
    decision_text = memory_data.get("user_decision_normalized") or memory_data.get("user_decision_raw", "")
    embedding = embed_query(decision_text)
    
    record = {
        "user_id": user_id,
        "memory_type": memory_data.get("memory_type", "decision"),
        "status": "active",
        "related_module": memory_data.get("related_module"),
        "related_day": memory_data.get("related_day"),
        "related_lecture_id": memory_data.get("related_lecture_id"),
        "related_topic": memory_data.get("related_topic"),
        "question_asked": memory_data.get("question_asked"),
        "user_decision_raw": memory_data.get("user_decision_raw", ""),
        "user_decision_normalized": memory_data.get("user_decision_normalized"),
        "source_chunk_ids": memory_data.get("source_chunk_ids", []),
        "embedding": embedding
    }
    
    result = client.table("company_memory").insert(record).execute()
    return result.data[0]["id"] if result.data else None


def parse_draft_answer(text: str) -> dict | None:
    """Parse <draft_answer> block from LLM response."""
    try:
        match = re.search(r'<draft_answer>\s*({.*?})\s*</draft_answer>', text, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(1))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def process_user_answer(user_id: str, answer: str, context: dict) -> dict:
    """Process user answer with draft/commit pattern. Only commits when all questions closed."""
    progress = get_user_progress(user_id)

    # Get current lecture info for context
    lecture_id = progress.get("current_lecture_id", "") if progress else ""
    module = progress.get("current_module", 1) if progress else 1
    day = progress.get("current_day", 1) if progress else 1

    # Get pending questions to pass to LLM
    pending = get_pending_questions(user_id)

    # Build context for answer processing
    pending_str = ""
    if pending:
        pending_json = json.dumps(pending, ensure_ascii=False)
        pending_str = f"\n\nPENDING_QUESTIONS:\n{pending_json}"

    context_str = f"""
Лекция: {lecture_id}
Модуль: {module}, День: {day}
Тема блока: {context.get('topic', '')}
Вопрос агента: {context.get('question', 'Как ты решил реализовать это в своей компании?')}

Ответ пользователя:
{answer}{pending_str}
"""

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {"role": "user", "content": context_str}
    ]

    response = chat_completion(messages)

    # Parse questions analysis
    analysis = parse_questions_analysis(response)
    memory_saved = False
    memory_id = None
    decision_summary = None

    if analysis:
        answered_ids = analysis.get("answered", [])
        skipped_ids = analysis.get("skipped", [])
        still_open = analysis.get("still_open", [])

        # Extra ROI validation: if ROI question answered, check for numbers
        for qid in answered_ids:
            if "roi" in qid.lower():
                if not analyze_roi_answer(answer):
                    # ROI answer without numbers - keep it open
                    answered_ids = [x for x in answered_ids if x != qid]
                    still_open.append(qid)

        # Mark answered questions
        if answered_ids:
            for qid in answered_ids:
                # Save answer to draft
                save_draft_answer(user_id, qid, answer[:500], context.get('topic', 'Study'))
            mark_questions_answered(user_id, answered_ids, answer[:500])

        # Mark skipped questions
        if skipped_ids:
            questions = get_pending_questions(user_id)
            for q in questions:
                if q["id"] in skipped_ids:
                    q["status"] = "skipped"
            save_pending_questions(user_id, questions)

    # Check if all questions are now closed
    all_closed = all_questions_closed(user_id)

    if all_closed and get_draft_decision(user_id):
        # COMMIT: save draft to company_memory
        commit_result = commit_decision(user_id)
        if commit_result:
            memory_saved = True
            memory_id = commit_result.get("memory_id")
            decision_summary = commit_result.get("summary")

    # Get remaining open questions for response
    remaining = get_open_questions(user_id)
    current_question = get_current_question(user_id)
    stats = get_questions_stats(user_id)

    # Remove XML blocks from visible response
    clean_response = re.sub(r'<draft_answer>.*?</draft_answer>', '', response, flags=re.DOTALL)
    clean_response = re.sub(r'<questions_analysis>.*?</questions_analysis>', '', clean_response, flags=re.DOTALL).strip()

    # Add status to response
    if memory_saved:
        clean_response += f"\n\n✅ **Сохранено в Мои решения:** {decision_summary}"
    elif remaining:
        # Show next question
        clean_response += f"\n\n**Следующий вопрос:** {current_question['text']}" if current_question else ""

    return {
        "answer": clean_response,
        "memory_saved": memory_saved,
        "memory_id": memory_id,
        "decision_summary": decision_summary,
        "pending_questions": get_pending_questions(user_id),  # Full list with statuses
        "current_question": current_question,
        "questions_stats": stats,
        "all_closed": all_closed,
        "can_continue": all_closed
    }
