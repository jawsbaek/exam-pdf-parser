"""
Sliding-window rate limiter for exam PDF parser service.
시험 PDF 파서 서비스의 슬라이딩 윈도우 속도 제한 모듈입니다.

In-memory, per-API-key rate limiting. No external dependencies.

Limits (configurable via env vars):
  RATE_LIMIT_PER_MINUTE  — max requests per minute per key (default: 60)
  MAX_CONCURRENT_PARSES  — max simultaneous parse jobs (default: 10)

Usage:
    from .rate_limit import check_rate_limit

    @app.post("/api/parse")
    async def parse(
        ...,
        _: None = Depends(check_rate_limit),
    ):
        ...
"""

import asyncio
import logging
import os
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status

from .auth import require_api_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at import time; restart to pick up changes)
# ---------------------------------------------------------------------------

_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
_MAX_CONCURRENT_PARSES: int = int(os.getenv("MAX_CONCURRENT_PARSES", "10"))

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# Sliding window: maps identity key -> deque of request timestamps (float, epoch seconds)
# 슬라이딩 윈도우: 식별 키 -> 요청 타임스탬프 데크
_windows: dict[str, deque[float]] = {}
_windows_lock = asyncio.Lock()

# Semaphore for concurrent parse jobs (created lazily on first use)
_parse_semaphore: asyncio.Semaphore | None = None
_semaphore_lock = asyncio.Lock()


def _get_identity(api_key: str | None, request: Request) -> str:
    """Return a stable identity string for rate-limit bucketing.

    Uses the API key when available; falls back to client IP.
    API 키가 있으면 사용하고, 없으면 클라이언트 IP를 사용합니다.
    """
    if api_key:
        return f"key:{api_key}"
    # Respect X-Forwarded-For when behind a proxy
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"


async def _get_semaphore() -> asyncio.Semaphore:
    """Return the global parse semaphore, creating it if necessary.

    Lazy init is required because asyncio objects must be created within
    a running event loop.
    asyncio 객체는 실행 중인 이벤트 루프 내에서 생성해야 합니다.
    """
    global _parse_semaphore
    if _parse_semaphore is None:
        async with _semaphore_lock:
            if _parse_semaphore is None:
                _parse_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PARSES)
    return _parse_semaphore


async def _check_sliding_window(identity: str) -> None:
    """Enforce per-identity sliding window rate limit (thread-safe).

    Raises HTTP 429 with Retry-After header if the limit is exceeded.
    제한 초과 시 Retry-After 헤더와 함께 HTTP 429를 반환합니다.
    """
    now = time.monotonic()
    window_start = now - 60.0  # 1-minute sliding window

    async with _windows_lock:
        if identity not in _windows:
            _windows[identity] = deque()

        window = _windows[identity]

        # Drop timestamps outside the current window
        while window and window[0] < window_start:
            window.popleft()

        if len(window) >= _RATE_LIMIT_PER_MINUTE:
            # Oldest request in window determines when a slot opens
            oldest = window[0]
            retry_after = int(60 - (now - oldest)) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded: {_RATE_LIMIT_PER_MINUTE} requests/minute. "
                    f"Retry after {retry_after} seconds."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)


async def check_rate_limit(
    request: Request,
    api_key: str | None = Depends(require_api_key),
) -> None:
    """FastAPI dependency that enforces rate limiting for parse endpoints.

    Checks both:
      1. Sliding window: max RATE_LIMIT_PER_MINUTE requests/minute per identity
      2. Semaphore: max MAX_CONCURRENT_PARSES simultaneous parse jobs

    Raises HTTP 429 if either limit is exceeded.
    두 가지 제한을 모두 확인합니다: 슬라이딩 윈도우와 동시 파싱 세마포어.
    """
    identity = _get_identity(api_key, request)

    # 1. Sliding window check (per identity, per minute)
    await _check_sliding_window(identity)

    # 2. Concurrent parse job limit (global semaphore, non-blocking check)
    semaphore = await _get_semaphore()
    acquired = semaphore._value > 0  # peek without acquiring
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Server busy: max {_MAX_CONCURRENT_PARSES} concurrent parse jobs reached. "
                "Please retry shortly."
            ),
            headers={"Retry-After": "5"},
        )
