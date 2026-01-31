import logging
import os
import uuid
from openai import OpenAI
from openai import APITimeoutError, APIConnectionError, APIStatusError
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)

# Timeout in seconds for DeepSeek API calls
DEEPSEEK_TIMEOUT = 60

# Simulate timeout for testing (set SIMULATE_TIMEOUT=true in env)
SIMULATE_TIMEOUT = os.getenv("SIMULATE_TIMEOUT", "").lower() == "true"

_client: OpenAI | None = None


class LLMError(Exception):
    """Base exception for LLM errors."""
    def __init__(self, message: str, request_id: str, retryable: bool = False):
        self.message = message
        self.request_id = request_id
        self.retryable = retryable
        super().__init__(message)


class LLMTimeoutError(LLMError):
    """Timeout error - retryable."""
    def __init__(self, message: str, request_id: str):
        super().__init__(message, request_id, retryable=True)


class LLMConnectionError(LLMError):
    """Connection error - retryable."""
    def __init__(self, message: str, request_id: str):
        super().__init__(message, request_id, retryable=True)


class LLMAuthError(LLMError):
    """Auth error (401/403) - not retryable."""
    def __init__(self, message: str, request_id: str):
        super().__init__(message, request_id, retryable=False)


class LLMRateLimitError(LLMError):
    """Rate limit error (429) - retryable after delay."""
    def __init__(self, message: str, request_id: str):
        super().__init__(message, request_id, retryable=True)


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

    # Simulate timeout for testing
    if SIMULATE_TIMEOUT:
        logger.warning(f"[{request_id}] DEEPSEEK_SIMULATED_TIMEOUT (SIMULATE_TIMEOUT=true)")
        raise LLMTimeoutError(
            f"Simulated timeout (SIMULATE_TIMEOUT=true)",
            request_id
        )

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
        raise LLMTimeoutError(
            f"Сервис думает слишком долго (>{DEEPSEEK_TIMEOUT}с)",
            request_id
        )

    except APIConnectionError as e:
        logger.error(f"[{request_id}] DEEPSEEK_CONNECTION_ERROR: {e}")
        raise LLMConnectionError(
            "Не удалось подключиться к AI-сервису",
            request_id
        )

    except APIStatusError as e:
        logger.error(f"[{request_id}] DEEPSEEK_STATUS_ERROR status={e.status_code}: {e.message}")
        if e.status_code in (401, 403):
            raise LLMAuthError(
                "Ошибка авторизации AI-сервиса",
                request_id
            )
        elif e.status_code == 429:
            raise LLMRateLimitError(
                "AI-сервис перегружен, попробуйте позже",
                request_id
            )
        else:
            raise LLMError(
                f"Ошибка AI-сервиса (код {e.status_code})",
                request_id,
                retryable=e.status_code >= 500
            )

    except LLMError:
        raise  # Re-raise our custom errors

    except Exception as e:
        logger.error(f"[{request_id}] DEEPSEEK_UNEXPECTED_ERROR: {type(e).__name__}: {e}")
        raise LLMError(
            f"Неожиданная ошибка: {type(e).__name__}",
            request_id,
            retryable=False
        )
