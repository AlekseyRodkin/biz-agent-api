"""Decisions: review, refine, and conflict detection."""
from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query


def get_all_active_decisions(user_id: str) -> list[dict]:
    """Get all active decisions for user."""
    client = get_client()
    result = client.table("company_memory") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("status", "active") \
        .order("related_module", desc=False) \
        .order("created_at", desc=False) \
        .execute()
    return result.data or []


def get_user_decisions_list(user_id: str, limit: int = 50) -> list[dict]:
    """Get list of user decisions for display in UI.

    Returns simplified list with only display-relevant fields.
    """
    client = get_client()
    result = client.table("company_memory") \
        .select("id, related_topic, user_decision_normalized, user_decision_raw, created_at, related_module") \
        .eq("user_id", user_id) \
        .eq("status", "active") \
        .eq("memory_type", "decision") \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()

    decisions = []
    for d in (result.data or []):
        decisions.append({
            "id": str(d["id"]),
            "topic": d.get("related_topic") or "Без темы",
            "decision": d.get("user_decision_normalized") or d.get("user_decision_raw") or "",
            "created_at": d["created_at"],
            "module": d.get("related_module")
        })
    return decisions


def group_decisions_by_module(decisions: list[dict]) -> dict:
    """Group decisions by module and topic."""
    grouped = {}

    for d in decisions:
        module = d.get("related_module") or 0
        topic = d.get("related_topic") or "Без темы"

        module_key = f"Модуль {module}" if module else "Общее"

        if module_key not in grouped:
            grouped[module_key] = {}

        if topic not in grouped[module_key]:
            grouped[module_key][topic] = []

        grouped[module_key][topic].append({
            "id": str(d.get("id", "")),
            "memory_type": d.get("memory_type"),
            "question_asked": d.get("question_asked"),
            "user_decision_raw": d.get("user_decision_raw"),
            "user_decision_normalized": d.get("user_decision_normalized"),
            "created_at": d.get("created_at"),
            "related_lecture_id": d.get("related_lecture_id")
        })

    return grouped


def decisions_review(user_id: str) -> dict:
    """Review all active decisions grouped by module/topic."""
    decisions = get_all_active_decisions(user_id)
    grouped = group_decisions_by_module(decisions)

    # Build formatted text
    formatted_parts = []
    for module_key in sorted(grouped.keys()):
        formatted_parts.append(f"\n## {module_key}")
        for topic, items in grouped[module_key].items():
            formatted_parts.append(f"\n### {topic}")
            for i, item in enumerate(items, 1):
                decision = item.get("user_decision_normalized") or item.get("user_decision_raw", "")
                formatted_parts.append(f"- Решение {i}: {decision}")

    return {
        "total_decisions": len(decisions),
        "grouped": grouped,
        "formatted": "\n".join(formatted_parts) if formatted_parts else "Нет принятых решений."
    }


def refine_decision(user_id: str, decision_id: str, updated_decision: str) -> dict:
    """Refine an existing decision: supersede old, create new."""
    client = get_client()

    # Get old decision
    old_result = client.table("company_memory") \
        .select("*") \
        .eq("id", decision_id) \
        .eq("user_id", user_id) \
        .execute()

    if not old_result.data:
        return {"success": False, "error": "Decision not found"}

    old_decision = old_result.data[0]

    if old_decision.get("status") == "superseded":
        return {"success": False, "error": "Decision already superseded"}

    # Mark old as superseded
    client.table("company_memory") \
        .update({"status": "superseded"}) \
        .eq("id", decision_id) \
        .execute()

    # Compute new embedding
    new_embedding = embed_query(updated_decision)

    # Create new decision
    new_record = {
        "user_id": user_id,
        "memory_type": old_decision.get("memory_type", "decision"),
        "status": "active",
        "related_module": old_decision.get("related_module"),
        "related_day": old_decision.get("related_day"),
        "related_lecture_id": old_decision.get("related_lecture_id"),
        "related_topic": old_decision.get("related_topic"),
        "question_asked": old_decision.get("question_asked"),
        "user_decision_raw": updated_decision,
        "user_decision_normalized": updated_decision,
        "source_chunk_ids": old_decision.get("source_chunk_ids", []),
        "embedding": new_embedding
    }

    new_result = client.table("company_memory").insert(new_record).execute()
    new_id = new_result.data[0]["id"] if new_result.data else None

    return {
        "success": True,
        "old_decision_id": decision_id,
        "old_status": "superseded",
        "new_decision_id": str(new_id) if new_id else None,
        "new_status": "active"
    }


def detect_conflicts(methodology_text: str, user_id: str, limit: int = 5) -> list[dict]:
    """Detect potential conflicts between methodology and user decisions.

    Returns list of user decisions related to current methodology block.
    The actual conflict analysis is done by LLM in the prompt.
    """
    client = get_client()

    # Embed methodology text
    methodology_embedding = embed_query(methodology_text[:2000])

    # Find relevant user decisions
    result = client.rpc(
        "match_company_memory",
        {
            "query_embedding": methodology_embedding,
            "match_count": limit,
            "p_user_id": user_id
        }
    ).execute()

    decisions = result.data or []

    if not decisions:
        return []

    # Return decisions with reasonable similarity (related to this topic)
    conflicts = []
    for d in decisions:
        similarity = d.get("similarity", 0)
        if similarity > 0.5:  # Lower threshold to catch more potential conflicts
            conflicts.append({
                "decision_id": str(d.get("id", "")),
                "topic": d.get("related_topic", ""),
                "user_decision": d.get("user_decision_normalized") or d.get("user_decision_raw", ""),
                "similarity": similarity
            })

    return conflicts


def build_conflict_context(conflicts: list[dict]) -> str:
    """Build context string for conflict detection in prompt."""
    if not conflicts:
        return ""

    parts = ["\nPREVIOUS_DECISIONS_TO_CHECK (проверь на расхождения с текущим блоком методологии):"]
    for c in conflicts:
        topic = c.get("topic", "")
        decision = c.get("user_decision", "")
        parts.append(f"- [{topic}]: {decision}")

    return "\n".join(parts)
