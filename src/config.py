"""
Configuration module for exam PDF parser.
환경 변수 및 모델 설정을 관리합니다.
"""

import os
from functools import lru_cache
from dotenv import load_dotenv
from pydantic import BaseModel


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    GOOGLE_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None

    def __init__(self, **kwargs):
        """Load settings from environment variables."""
        defaults = {
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


# LLM generation limits
LLM_MAX_TOKENS = 32000         # Default max output tokens for text-only LLM calls

# LLM pricing (USD per 1M tokens) - used for cost calculation in hybrid pipelines
_LLM_PRICING = {
    "gemini-3-flash-preview": {"input": 0.15, "output": 3.50},
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.0},
    "gpt-5.1": {"input": 2.50, "output": 10.0},
}

# Document parsers / OCR engines available for Layer 1
_DOCUMENT_PARSERS = [
    "marker", "mineru", "docling",           # PDF → Markdown (recommended)
    "pymupdf-text",                           # Direct PDF text extraction
    "tesseract", "easyocr", "paddleocr",      # Traditional OCR
    "surya", "trocr", "deepseek-ocr",         # ML-based OCR
]

# LLM backends available for Layer 2
_LLM_BACKENDS = ["gemini-3-flash-preview", "gemini-3-pro-preview", "gpt-5.1"]


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


# 모델별 가격 정보 (USD per 1M tokens)
# All models are hybrid: document_parser+llm_backend
MODEL_CONFIG = _build_model_config()


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: Singleton settings object
    """
    load_dotenv()
    return Settings()


def sanitize_model_name(name: str) -> str:
    """Sanitize model name for use in file paths."""
    return name.replace("/", "_").replace(":", "_").replace("+", "-plus-")


def check_api_key(provider: str) -> bool:
    """Check if an API key is configured for the given provider.

    Args:
        provider: One of 'google', 'openai', 'anthropic'

    Returns:
        True if the key is set and non-empty
    """
    settings = get_settings()
    key_map = {
        "google": settings.GOOGLE_API_KEY,
        "gemini": settings.GOOGLE_API_KEY,
        "openai": settings.OPENAI_API_KEY,
        "gpt": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
        "claude": settings.ANTHROPIC_API_KEY,
    }
    return bool(key_map.get(provider))
