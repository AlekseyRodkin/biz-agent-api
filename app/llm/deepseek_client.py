import logging
import uuid
from openai import OpenAI
from openai import APITimeoutError, APIConnectionError, APIStatusError
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)

# Timeout in seconds for DeepSeek API calls
DEEPSEEK_TIMEOUT = 60

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=DEEPSEEK_TIMEOUT
        )
    return _client


def chat_completion(messages: list[dict]) -> str:
    """Call DeepSeek chat completion with timeout and error handling."""
    request_id = str(uuid.uuid4())[:8]

    logger.info(f"[{request_id}] DEEPSEEK_START model={DEEPSEEK_MODEL} messages={len(messages)}")

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            timeout=DEEPSEEK_TIMEOUT
        )

        content = response.choices[0].message.content or ""
        logger.info(f"[{request_id}] DEEPSEEK_DONE len={len(content)}")

        return content

    except APITimeoutError as e:
        logger.error(f"[{request_id}] DEEPSEEK_TIMEOUT after {DEEPSEEK_TIMEOUT}s: {e}")
        raise RuntimeError(f"DeepSeek timeout after {DEEPSEEK_TIMEOUT}s (request_id: {request_id})")

    except APIConnectionError as e:
        logger.error(f"[{request_id}] DEEPSEEK_CONNECTION_ERROR: {e}")
        raise RuntimeError(f"DeepSeek connection error (request_id: {request_id})")

    except APIStatusError as e:
        logger.error(f"[{request_id}] DEEPSEEK_STATUS_ERROR status={e.status_code}: {e.message}")
        raise RuntimeError(f"DeepSeek API error {e.status_code} (request_id: {request_id})")

    except Exception as e:
        logger.error(f"[{request_id}] DEEPSEEK_UNEXPECTED_ERROR: {type(e).__name__}: {e}")
        raise RuntimeError(f"DeepSeek unexpected error (request_id: {request_id}): {type(e).__name__}")
