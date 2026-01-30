"""Study mode: sequential learning through methodology."""
import json
import re
from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.llm.deepseek_client import chat_completion
from app.config import USER_ID
from app.rag.decisions import detect_conflicts, build_conflict_context
from app.rag.course_map import build_navigation_block


STUDY_SYSTEM_PROMPT = """Ты — обучающий AI-агент "Трансформация бизнеса с ИИ".
Твоя задача: провести пользователя по методологии и помочь спроектировать внедрение ИИ в его компании.

ПРАВИЛА:
- Приоритет: решения пользователя (COMPANY_MEMORY) > методология > кейсы
- Не цитируй лекции дословно, сжато объясняй суть
- Если есть COMPANY_MEMORY — ссылайся на него
- КРИТИЧЕСКИ ВАЖНО: если есть PREVIOUS_DECISIONS_TO_CHECK, ОБЯЗАТЕЛЬНО проверь их на расхождения с методологией
- Ты НЕ ИМЕЕШЬ ПРАВА молча игнорировать потенциальные конфликты
- Если решение противоречит методологии или пропускает обязательный шаг — укажи это
- Не навязывай, но фиксируй риски

КРИТИЧЕСКИЕ ЗАПРЕТЫ (MEMORY SAFETY):
- ЗАПРЕЩЕНО: брать "решения пользователя" из METHODOLOGY_BLOCK или CASE_STUDIES
- Секция "[ТВОИ ПРЕДЫДУЩИЕ РЕШЕНИЯ]" формируется ТОЛЬКО из COMPANY_MEMORY
- Если COMPANY_MEMORY пустая → в секции пиши "Пока нет зафиксированных решений от тебя"
- Если видишь в тексте "мы сделали", "наш кейс", "в нашей компании" — это НЕ решение пользователя, а пример из курса
- Никогда не приписывай пользователю решения других студентов из транскриптов

ФОРМАТ ОТВЕТА (СТРОГО!):

[СУТЬ]
- 3–7 пунктов, что важно понять из этого блока

[КАК ЭТО ДЕЛАЮТ ПО МЕТОДОЛОГИИ]
- кратко, по шагам

[ПРИМЕРЫ]
- 1–2 кейса (если есть в CASE_STUDIES)

[ТВОИ ПРЕДЫДУЩИЕ РЕШЕНИЯ]
- если есть COMPANY_MEMORY, покажи как это связано

[ВОЗМОЖНЫЕ РАСХОЖДЕНИЯ]
(Обязательно добавь этот раздел, если есть PREVIOUS_DECISIONS_TO_CHECK и обнаружены расхождения!)
- По методологии: что говорит текущий блок
- У тебя принято: что пользователь решил ранее
- Риск: почему это может быть проблемой
(Если расхождений нет — напиши "Расхождений не обнаружено")

[ВОПРОС К ТЕБЕ]
Как ты решил реализовать это в своей компании?

[СЛЕДУЮЩИЙ ШАГ]
Что нужно сделать/описать до следующего блока

SOURCES_USED: [список chunk_id]
"""

ANSWER_SYSTEM_PROMPT = """Ты — обучающий AI-агент. Пользователь ответил на вопрос о решении для своей компании.

Твоя задача:
1. Подтвердить решение или предложить уточнения
2. Если решение конкретное — сформировать запись для памяти

Если пользователь дал конкретное решение, ДОБАВЬ в конце ответа:

<memory_write>
{
  "memory_type": "decision",
  "related_module": <number>,
  "related_day": <number>,
  "related_lecture_id": "<string>",
  "related_topic": "<string>",
  "question_asked": "<вопрос, на который ответил пользователь>",
  "user_decision_raw": "<точный текст пользователя>",
  "user_decision_normalized": "<нормализованное решение 1-2 предложения>"
}
</memory_write>

Если пользователь не дал конкретного решения — не добавляй memory_write.
"""


def get_user_progress(user_id: str) -> dict | None:
    """Get current user progress."""
    client = get_client()
    result = client.table("user_progress").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


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
    
    # Get chunks from current lecture, sequence > current
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
    
    # If no more chunks in current lecture, move to next methodology lecture
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


def build_study_context(chunks: list[dict], memory: list[dict], cases: list[dict], conflicts: list[dict] = None) -> str:
    """Build context string for study prompt."""
    parts = []

    if chunks:
        # Filter out student_comment chunks - they should not appear in methodology block
        methodology_chunks = [c for c in chunks if c.get('content_type') != 'student_comment']
        if methodology_chunks:
            parts.append("METHODOLOGY_BLOCK:")
            for c in methodology_chunks:
                parts.append(f"[{c['chunk_id']}] {c['content']}\n")

    if memory:
        parts.append("\nCOMPANY_MEMORY (твои предыдущие решения):")
        for m in memory:
            topic = m.get('related_topic', '')
            decision = m.get('user_decision_normalized') or m.get('user_decision_raw', '')
            parts.append(f"- [{topic}]: {decision}")

    if cases:
        parts.append("\nCASE_STUDIES (примеры):")
        for c in cases:
            parts.append(f"[{c['chunk_id']}] {c['content'][:500]}...\n")

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

    chunks = get_next_methodology_chunks(progress)

    if not chunks:
        return {
            "answer": "Поздравляю! Вы прошли все доступные материалы курса.",
            "sources": {"methodology": [], "memory": [], "cases": [], "conflicts": []},
            "progress": progress,
            "completed": True
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

    # Update progress
    last_chunk = chunks[-1]
    update_progress(user_id, last_chunk["lecture_id"], last_chunk["sequence_order"])

    # Add navigation block to answer
    navigation = build_navigation_block(user_id)
    if navigation:
        answer = f"{answer}\n\n{navigation}"

    return {
        "answer": answer,
        "sources": {
            "methodology": [{"chunk_id": c["chunk_id"], "lecture_id": c["lecture_id"]} for c in chunks],
            "memory": [{"id": str(m.get("id", "")), "topic": m.get("related_topic", "")} for m in memory],
            "cases": [{"chunk_id": c["chunk_id"]} for c in cases],
            "conflicts": [{"decision_id": c["decision_id"], "topic": c["topic"]} for c in conflicts]
        },
        "progress": get_user_progress(user_id),
        "completed": False
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


def process_user_answer(user_id: str, answer: str, context: dict) -> dict:
    """Process user answer and potentially save to memory."""
    progress = get_user_progress(user_id)
    
    # Get current lecture info for context
    lecture_id = progress.get("current_lecture_id", "") if progress else ""
    module = progress.get("current_module", 1) if progress else 1
    day = progress.get("current_day", 1) if progress else 1
    
    # Build context for answer processing
    context_str = f"""
Лекция: {lecture_id}
Модуль: {module}, День: {day}
Тема блока: {context.get('topic', '')}
Вопрос агента: {context.get('question', 'Как ты решил реализовать это в своей компании?')}

Ответ пользователя:
{answer}
"""
    
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {"role": "user", "content": context_str}
    ]
    
    response = chat_completion(messages)
    
    # Parse and save memory if present
    memory_data = parse_memory_write(response)
    memory_id = None
    
    if memory_data:
        # Add lecture context if not present
        if not memory_data.get("related_lecture_id"):
            memory_data["related_lecture_id"] = lecture_id
        if not memory_data.get("related_module"):
            memory_data["related_module"] = module
        if not memory_data.get("related_day"):
            memory_data["related_day"] = day
        
        memory_id = save_memory(user_id, memory_data)
    
    # Remove memory_write block from visible response
    clean_response = re.sub(r'<memory_write>.*?</memory_write>', '', response, flags=re.DOTALL).strip()
    
    return {
        "answer": clean_response,
        "memory_saved": memory_id is not None,
        "memory_id": memory_id
    }
