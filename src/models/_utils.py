"""
Common utilities for LLM model clients.
LLM 클라이언트 공통 유틸리티.
"""

import logging
import random
import time
from functools import wraps

logger = logging.getLogger(__name__)

# Exceptions that should NOT be retried (auth, validation, bad request)
_NON_RETRYABLE_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    PermissionError,
)


def _is_retryable(exc: Exception) -> bool:
    """Determine if an exception is worth retrying."""
    if isinstance(exc, _NON_RETRYABLE_ERRORS):
        return False
    # google-genai client errors (4xx) should not be retried
    exc_name = type(exc).__name__
    if exc_name in ("ClientError", "InvalidArgument", "PermissionDenied", "AuthenticationError"):
        return False
    # HTTP status-based: don't retry 4xx except 429 (rate limit)
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and 400 <= status < 500 and status != 429:
        return False
    return True


def retry_llm_call(max_retries=3, base_delay=2.0):
    """Decorator for retrying LLM calls with exponential backoff.

    Only retries transient errors (network, rate limit, server errors).
    Non-retryable errors (auth, validation) are raised immediately.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1 or not _is_retryable(e):
                        raise
                    delay = base_delay * (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        max_retries,
                        e,
                        delay,
                    )
                    time.sleep(delay)

        return wrapper

    return decorator
