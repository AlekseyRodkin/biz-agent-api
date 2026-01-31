"""Search module: semantic search across course and memory."""
import logging
from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.config import USER_ID, USE_CLEAN_CONTENT

logger = logging.getLogger(__name__)


def search(
    query: str,
    user_id: str = None,
    scope: str = "all",
    limit: int = 8
) -> dict:
    """
    Perform semantic search across course chunks and/or company memory.

    Args:
        query: Search query text
        user_id: User ID for memory search
        scope: One of: all, course, methodology, case_study, memory
        limit: Maximum number of results

    Returns:
        dict with results list and metadata
    """
    user_id = user_id or USER_ID
    embedding = embed_query(query)
    client = get_client()

    results = []

    # Determine what to search
    search_course = scope in ["all", "course", "methodology", "case_study"]
    search_memory = scope in ["all", "memory"]

    # Search course chunks
    if search_course:
        filter_params = {}
        if scope == "methodology":
            filter_params = {"speaker_type": "methodology"}
        elif scope == "case_study":
            filter_params = {"speaker_type": "case_study"}

        course_results = client.rpc(
            "match_course_chunks",
            {
                "query_embedding": embedding,
                "filter": filter_params,
                "match_count": limit * 2  # Get more to filter later
            }
        ).execute()

        for item in (course_results.data or [])[:limit]:
            # Get lecture info
            lecture = client.table("course_lectures") \
                .select("lecture_title, speaker_name") \
                .eq("lecture_id", item.get("lecture_id", "")) \
                .execute()

            lecture_info = lecture.data[0] if lecture.data else {}

            # Get clean content if available
            content = item.get("content", "")
            if USE_CLEAN_CONTENT:
                chunk_data = client.table("course_chunks") \
                    .select("clean_content") \
                    .eq("chunk_id", item.get("chunk_id", "")) \
                    .execute()
                if chunk_data.data and chunk_data.data[0].get("clean_content"):
                    content = chunk_data.data[0]["clean_content"]

            # Create snippet (first 250 chars)
            snippet = content[:250].strip()
            if len(content) > 250:
                snippet += "..."

            results.append({
                "type": "course",
                "chunk_id": item.get("chunk_id"),
                "lecture_id": item.get("lecture_id"),
                "lecture_title": lecture_info.get("lecture_title", ""),
                "speaker_name": lecture_info.get("speaker_name", ""),
                "speaker_type": item.get("speaker_type", ""),
                "similarity": round(item.get("similarity", 0), 3),
                "snippet": snippet
            })

    # Search company memory
    if search_memory:
        memory_results = client.rpc(
            "match_company_memory",
            {
                "query_embedding": embedding,
                "p_user_id": user_id,
                "match_count": limit
            }
        ).execute()

        for item in (memory_results.data or []):
            # Create snippet from decision
            decision = item.get("user_decision_normalized") or item.get("user_decision_raw", "")
            snippet = decision[:250].strip()
            if len(decision) > 250:
                snippet += "..."

            results.append({
                "type": "memory",
                "id": item.get("id"),
                "memory_type": item.get("memory_type"),
                "related_topic": item.get("related_topic", ""),
                "similarity": round(item.get("similarity", 0), 3),
                "snippet": snippet
            })

    # Sort by similarity and limit
    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    results = results[:limit]

    return {
        "query": query,
        "scope": scope,
        "total": len(results),
        "results": results
    }


def format_search_results_for_chat(search_result: dict) -> str:
    """
    Format search results as chat-friendly text with clickable buttons.

    Args:
        search_result: Result from search() function

    Returns:
        Formatted string for chat display
    """
    results = search_result.get("results", [])
    query = search_result.get("query", "")

    if not results:
        return f"По запросу «{query}» ничего не найдено."

    lines = [f"**Найдено {len(results)} результатов по запросу «{query}»:**\n"]

    for i, r in enumerate(results, 1):
        if r["type"] == "course":
            title = r.get("lecture_title") or r.get("lecture_id", "")
            speaker = r.get("speaker_name", "")
            chunk_id = r.get("chunk_id", "")
            similarity = r.get("similarity", 0)
            snippet = r.get("snippet", "")

            lines.append(f"**{i}. {title}** ({speaker})")
            lines.append(f"   `{chunk_id}` — {similarity:.0%}")
            lines.append(f"   _{snippet[:150]}..._" if len(snippet) > 150 else f"   _{snippet}_")
            lines.append(f"   [OPEN_SOURCE:{chunk_id}]")
            lines.append("")
        else:
            # Memory result
            topic = r.get("related_topic", "Решение")
            memory_id = r.get("id", "")
            similarity = r.get("similarity", 0)
            snippet = r.get("snippet", "")

            lines.append(f"**{i}. {topic}** (твоё решение)")
            lines.append(f"   {similarity:.0%}")
            lines.append(f"   _{snippet[:150]}..._" if len(snippet) > 150 else f"   _{snippet}_")
            lines.append("")

    return "\n".join(lines)


def detect_search_intent(message: str) -> tuple[bool, str, str]:
    """
    Detect if message is a search intent and extract query and scope.

    Returns:
        (is_search, query, scope)
    """
    msg_lower = message.lower().strip()

    # Search trigger patterns
    search_triggers = [
        "найди ", "найти ", "поиск ", "искать ",
        "где говорили ", "где говорится ", "где было ",
        "find ", "search ",
        "покажи где ", "в каких лекциях "
    ]

    for trigger in search_triggers:
        if msg_lower.startswith(trigger):
            query = message[len(trigger):].strip()
            # Detect scope
            scope = "all"
            if "у верховского" in query.lower() or "верховский" in query.lower():
                scope = "methodology"
                # Remove scope hint from query
                query = query.lower().replace("у верховского", "").replace("верховский", "").strip()
            elif "в кейсах" in query.lower() or "в примерах" in query.lower():
                scope = "case_study"
                query = query.lower().replace("в кейсах", "").replace("в примерах", "").strip()
            elif "в памяти" in query.lower() or "в решениях" in query.lower():
                scope = "memory"
                query = query.lower().replace("в памяти", "").replace("в решениях", "").strip()

            return True, query, scope

    return False, "", ""
