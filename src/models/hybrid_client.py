"""
Hybrid OCR + LLM client.
OCR로 텍스트를 추출한 후, Gemini LLM으로 구조화합니다.
"""

from ..config import check_api_key, get_settings
from ..ocr import get_ocr_engine
from ..prompt import get_parsing_prompt
from ..schema import ParsedExam
from ._utils import retry_llm_call
from .base import ModelClient


class HybridOCRClient(ModelClient):
    """
    Hybrid pipeline: MinerU PDF extraction -> Gemini LLM structuring.

    Layer 1 (Parsing): PDF → MinerU → Markdown
    Layer 2 (Structuring): Markdown → Gemini → ParsedExam JSON
    """

    def __init__(self, model_name: str, pdf_path: str | None = None):
        super().__init__(model_name=model_name)
        parts = model_name.split("+", 1)
        if len(parts) != 2:
            raise ValueError(f"Hybrid model name must be 'ocr+llm' format, got: {model_name}")
        self.ocr_name = parts[0]
        self.llm_name = parts[1]

        if not check_api_key("gemini"):
            raise ValueError("GOOGLE_API_KEY is not set. Required for Gemini LLM backend.")

        self.ocr_engine = get_ocr_engine(self.ocr_name)

        # Pass MinerU configuration from settings
        settings = get_settings()
        if hasattr(self.ocr_engine, "configure"):
            self.ocr_engine.configure(
                language=settings.MINERU_LANGUAGE,
                parse_method=settings.MINERU_PARSE_METHOD,
                formula_enable=settings.MINERU_FORMULA_ENABLE,
                table_enable=settings.MINERU_TABLE_ENABLE,
                make_mode=settings.MINERU_MAKE_MODE,
            )

        self.ocr_metrics = {}
        self._pdf_path = pdf_path
        self._client = None

        if pdf_path and hasattr(self.ocr_engine, "set_pdf_path"):
            self.ocr_engine.set_pdf_path(pdf_path)

    def set_pdf_path(self, pdf_path: str):
        """Set PDF path for engines that support direct PDF processing."""
        self._pdf_path = pdf_path
        if hasattr(self.ocr_engine, "set_pdf_path"):
            self.ocr_engine.set_pdf_path(pdf_path)

    def parse_exam(
        self,
        images: list[tuple[bytes, str]],
        instruction: str | None = None,
    ) -> ParsedExam:
        extracted_text = self.ocr_engine.extract_text(images)
        self.ocr_metrics = self.ocr_engine.get_metrics()

        prompt = instruction or get_parsing_prompt()
        text_prompt = self._build_text_prompt(prompt, extracted_text)
        return self._call_gemini(text_prompt)

    def _build_text_prompt(self, base_prompt: str, extracted_text: str) -> str:
        return f"""{base_prompt}

## OCR 추출 텍스트
아래는 시험지에서 OCR로 추출한 원본 텍스트입니다.
이 텍스트를 분석하여 구조화하세요. OCR 오류는 문맥에 맞게 교정하세요.

{extracted_text}
"""

    @retry_llm_call()
    def _call_gemini(self, prompt: str) -> ParsedExam:
        from google import genai
        from google.genai import types

        if self._client is None:
            settings = get_settings()
            self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)

        response = self._client.models.generate_content(
            model=self.llm_name,
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
            raise ValueError(
                "Gemini returned empty response (possibly blocked by safety filters). "
                f"Finish reason: {getattr(response.candidates[0], 'finish_reason', 'unknown') if response.candidates else 'no candidates'}"
            )

        return ParsedExam.model_validate_json(response.text)

    def get_ocr_metrics(self) -> dict:
        """Return OCR-specific timing metrics."""
        return self.ocr_metrics
