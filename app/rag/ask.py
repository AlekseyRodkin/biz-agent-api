from app.rag.retrieve import retrieve_context
from app.rag.prompt import build_messages
from app.llm.deepseek_client import chat_completion


def ask(question: str) -> dict:
    context = retrieve_context(question)
    messages = build_messages(question, context)
    answer = chat_completion(messages)

    sources = {
        "company": [
            {
                "id": item.get("id"),
                "memory_type": item.get("memory_type"),
                "related_topic": item.get("related_topic"),
                "question_asked": item.get("question_asked"),
                "user_decision_raw": item.get("user_decision_raw"),
                "similarity": item.get("similarity")
            }
            for item in context.get("company", [])
        ],
        "course": [
            {
                "chunk_id": item.get("chunk_id"),
                "lecture_id": item.get("lecture_id"),
                "lecture_title": item.get("lecture_title"),
                "speaker_type": item.get("speaker_type"),
                "content_type": item.get("content_type"),
                "sequence_order": item.get("sequence_order"),
                "similarity": item.get("similarity")
            }
            for item in context.get("course", [])
        ]
    }

    return {
        "answer": answer,
        "sources": sources
    }
