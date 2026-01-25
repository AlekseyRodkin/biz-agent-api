from app.rag.retrieve import retrieve_context
from app.rag.prompt import build_messages
from app.llm.deepseek_client import chat_completion


def ask(question: str) -> dict:
    context = retrieve_context(question)
    messages = build_messages(question, context)
    answer = chat_completion(messages)

    sources = {
        "company": [
            {"id": item.get("id"), "content": item.get("content", "")[:200]}
            for item in context.get("company", [])
        ],
        "course": [
            {"chunk_id": item.get("chunk_id", item.get("id")), "content": item.get("content", "")[:200]}
            for item in context.get("course", [])
        ]
    }

    return {
        "answer": answer,
        "sources": sources
    }
