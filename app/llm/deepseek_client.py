from openai import OpenAI
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL
        )
    return _client


def chat_completion(messages: list[dict]) -> str:
    client = get_client()
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages
    )
    return response.choices[0].message.content or ""
