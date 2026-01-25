from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.config import USER_ID


def retrieve_context(question: str) -> dict:
    embedding = embed_query(question)
    client = get_client()

    company_results = client.rpc(
        "match_company_memory",
        {
            "query_embedding": embedding,
            "p_user_id": USER_ID,
            "match_count": 6
        }
    ).execute()

    course_results = client.rpc(
        "match_course_chunks",
        {
            "query_embedding": embedding,
            "filter": {},
            "match_count": 12
        }
    ).execute()

    return {
        "company": company_results.data or [],
        "course": course_results.data or []
    }
