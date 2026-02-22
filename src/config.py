"""
Configuration module for exam PDF parser.
환경 변수 및 모델 설정을 관리합니다.
"""

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    GOOGLE_API_KEY: str | None = None

    # Authentication — comma-separated list of valid API keys.
    # Not set = auth disabled (development mode). 미설정 시 인증 비활성화.
    API_KEYS: str | None = None

    # Rate limiting — requests per minute per key/IP (default: 60)
    # 분당 요청 제한 (키/IP별, 기본값: 60)
    RATE_LIMIT_PER_MINUTE: int = 60

    # Maximum simultaneous parse jobs (default: 10)
    # 최대 동시 파싱 작업 수 (기본값: 10)
    MAX_CONCURRENT_PARSES: int = 10

    # MinerU OCR configuration
    # MinerU OCR 설정
    MINERU_LANGUAGE: str = "korean"          # OCR language (korean, en, ch, japan, etc.)
    MINERU_PARSE_METHOD: str = "auto"        # auto, ocr, txt
    MINERU_FORMULA_ENABLE: bool = True       # Enable formula detection
    MINERU_TABLE_ENABLE: bool = True         # Enable table detection
    MINERU_MAKE_MODE: str = "mm_markdown"    # mm_markdown, nlp_markdown, content_list

    def __init__(self, **kwargs):
        """Load settings from environment variables."""
        defaults = {
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
            "API_KEYS": os.getenv("API_KEYS") or None,
            "RATE_LIMIT_PER_MINUTE": int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
            "MAX_CONCURRENT_PARSES": int(os.getenv("MAX_CONCURRENT_PARSES", "10")),
            "MINERU_LANGUAGE": os.getenv("MINERU_LANGUAGE", "korean"),
            "MINERU_PARSE_METHOD": os.getenv("MINERU_PARSE_METHOD", "auto"),
            "MINERU_FORMULA_ENABLE": os.getenv("MINERU_FORMULA_ENABLE", "true").lower() in ("true", "1", "yes"),
            "MINERU_TABLE_ENABLE": os.getenv("MINERU_TABLE_ENABLE", "true").lower() in ("true", "1", "yes"),
            "MINERU_MAKE_MODE": os.getenv("MINERU_MAKE_MODE", "mm_markdown"),
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


# LLM pricing (USD per 1M tokens)
_LLM_PRICING = {
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.0},
}

# Document parsers available for Layer 1
_DOCUMENT_PARSERS = ["mineru"]

# LLM backends available for Layer 2
_LLM_BACKENDS = ["gemini-3-pro-preview"]


def _build_model_config() -> dict:
    """Build MODEL_CONFIG from document parsers x LLM backends."""
    config = {}
    for parser in _DOCUMENT_PARSERS:
        for llm in _LLM_BACKENDS:
            pricing = _LLM_PRICING[llm]
            config[f"{parser}+{llm}"] = {
                "input_price_per_1m": pricing["input"],
                "output_price_per_1m": pricing["output"],
                "provider": "hybrid",
                "ocr_engine": parser,
                "llm_model": llm,
            }
    return config


MODEL_CONFIG = _build_model_config()


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    load_dotenv()
    return Settings()


def sanitize_model_name(name: str) -> str:
    """Sanitize model name for use in file paths."""
    return name.replace("/", "_").replace(":", "_").replace("+", "-plus-")


def check_api_key(provider: str) -> bool:
    """Check if the API key for the given provider is configured."""
    settings = get_settings()
    if provider in ("gemini", "google"):
        return bool(settings.GOOGLE_API_KEY)
    logger.warning("Unknown provider '%s' for API key check", provider)
    return False
