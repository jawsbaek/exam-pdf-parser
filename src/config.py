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

    def __init__(self, **kwargs):
        """Load settings from environment variables."""
        defaults = {"GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY")}
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
