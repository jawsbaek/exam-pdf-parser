"""
API key authentication for exam PDF parser service.
시험 PDF 파서 서비스의 API 키 인증 모듈입니다.

API keys are loaded from the API_KEYS environment variable (comma-separated).
If API_KEYS is not set, authentication is DISABLED (open access for development).

Usage:
    from .auth import require_api_key

    @app.get("/api/endpoint")
    async def endpoint(api_key: str = Depends(require_api_key)):
        ...
"""

import logging
import os

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery

logger = logging.getLogger(__name__)

# FastAPI security schemes — try header first, then query param
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def _load_api_keys() -> frozenset[str]:
    """Load valid API keys from environment variable.

    Returns an empty frozenset if API_KEYS is not set (auth disabled).
    환경 변수에서 유효한 API 키를 로드합니다. 미설정 시 인증 비활성화.
    """
    raw = os.getenv("API_KEYS", "").strip()
    if not raw:
        return frozenset()
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    return frozenset(keys)


async def require_api_key(
    header_key: str | None = Security(_api_key_header),
    query_key: str | None = Security(_api_key_query),
) -> str | None:
    """FastAPI dependency that enforces API key authentication.

    - If API_KEYS env var is not set: passes through (development mode).
    - If API_KEYS is set: requires a valid key via X-API-Key header or api_key query param.
    - Raises HTTP 401 if key is missing or invalid.

    Returns the authenticated API key (or None in open-access mode).
    """
    valid_keys = _load_api_keys()

    # Auth disabled — open access (development mode)
    # API_KEYS 미설정 시 인증 비활성화 (개발 모드)
    if not valid_keys:
        return None

    # Prefer header over query param
    provided_key = header_key or query_key

    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide via X-API-Key header or api_key query parameter.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if provided_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return provided_key
