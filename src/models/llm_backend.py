"""
LLM backend abstraction for structuring exam text into ParsedExam.
LLM 공급자를 OCR 파이프라인에서 분리하는 추상화 레이어.
"""

from abc import ABC, abstractmethod

from ..schema import ParsedExam
from ._utils import retry_llm_call


class LLMBackend(ABC):
    """Abstract base class for LLM structuring backends."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    @abstractmethod
    def structure_text(self, prompt: str) -> ParsedExam:
        """
        Structure extracted text into ParsedExam.

        Args:
            prompt: Full prompt including instructions and OCR text

        Returns:
            ParsedExam object
        """
        pass

    def get_token_usage(self) -> tuple[int, int]:
        """Return (input_tokens, output_tokens)."""
        return (self.input_tokens, self.output_tokens)

    def _add_tokens(self, input_t, output_t):
        self.input_tokens += input_t or 0
        self.output_tokens += output_t or 0


class GeminiBackend(LLMBackend):
    """Gemini LLM backend using google-genai SDK."""

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name
        self._client = None  # lazy init

    @retry_llm_call()
    def structure_text(self, prompt: str) -> ParsedExam:
        from google import genai
        from google.genai import types

        from ..config import get_settings

        if self._client is None:
            settings = get_settings()
            self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)

        response = self._client.models.generate_content(
            model=self.model_name,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ParsedExam,
                temperature=0.1,
                max_output_tokens=65536,
            ),
        )

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            self._add_tokens(
                getattr(response.usage_metadata, "prompt_token_count", 0),
                getattr(response.usage_metadata, "candidates_token_count", 0),
            )

        if not response.text:
            if response.candidates:
                reason = getattr(response.candidates[0], "finish_reason", "unknown")
            else:
                reason = "no candidates"
            raise ValueError(
                f"Gemini returned empty response (possibly blocked by safety filters). "
                f"Finish reason: {reason}"
            )

        return ParsedExam.model_validate_json(response.text)
