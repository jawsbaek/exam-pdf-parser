"""
Common utilities for LLM model clients.
LLM 클라이언트 공통 유틸리티 (코드 펜스 제거, 리트라이, 토큰 집계).
"""

import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM response text."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def retry_llm_call(max_retries=3, base_delay=2.0):
    """Decorator for retrying LLM calls with exponential backoff."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2**attempt)
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
