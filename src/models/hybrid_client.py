"""
Hybrid OCR + LLM client.
OCR로 텍스트를 추출한 후, 텍스트 전용 LLM으로 구조화합니다.
"""

from ..config import LLM_MAX_TOKENS, check_api_key, get_settings
from ..ocr import get_ocr_engine
from ..prompt import get_parsing_prompt
from ..schema import ParsedExam
from ._utils import retry_llm_call, strip_code_fences
from .base import ModelClient

# Explicit LLM routing: keyword prefix → method name
_LLM_ROUTER = {
    "gemini": "_call_gemini",
    "gpt": "_call_openai",
    "claude": "_call_anthropic",
}

# Maps LLM prefix to the env var name (for clear error messages)
_KEY_NAMES = {
    "gemini": "GOOGLE_API_KEY",
    "gpt": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}


class HybridOCRClient(ModelClient):
    """
    Hybrid pipeline: Document parser/OCR text extraction -> text-only LLM structuring.

    Layer 1 (Parsing): PDF → Marker/MinerU/Docling/PyMuPDF/Tesseract/EasyOCR → Text/Markdown
    Layer 2 (Structuring): Text/Markdown → Gemini/GPT → ParsedExam JSON
    """

    def __init__(self, model_name: str, pdf_path: str | None = None):
        super().__init__(model_name=model_name)
        # Parse model_name format: "ocr_engine+llm_model"
        parts = model_name.split("+", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Hybrid model name must be 'ocr+llm' format, got: {model_name}"
            )
        self.ocr_name = parts[0]
        self.llm_name = parts[1]

        # Early API key validation — fail before expensive OCR extraction
        for prefix in _LLM_ROUTER:
            if prefix in self.llm_name:
                if not check_api_key(prefix):
                    raise ValueError(
                        f"{_KEY_NAMES[prefix]} is not set. "
                        f"Required for LLM backend '{self.llm_name}'."
                    )
                break

        self.ocr_engine = get_ocr_engine(self.ocr_name)
        self.ocr_metrics = {}
        self._pdf_path = pdf_path
        self._llm_client = None

        # Set PDF path for engines that support direct PDF processing
        # (PyMuPDF, Marker, MinerU, Docling)
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
        # Step 1: OCR text extraction
        extracted_text = self.ocr_engine.extract_text(images)
        self.ocr_metrics = self.ocr_engine.get_metrics()

        # Step 2: Send text to LLM for structuring
        prompt = instruction or get_parsing_prompt()
        text_prompt = self._build_text_prompt(prompt, extracted_text)

        # Route to appropriate LLM
        parsed_exam = self._call_llm(text_prompt)
        return parsed_exam

    def _build_text_prompt(self, base_prompt: str, extracted_text: str) -> str:
        return f"""{base_prompt}

## OCR 추출 텍스트
아래는 시험지에서 OCR로 추출한 원본 텍스트입니다.
이 텍스트를 분석하여 구조화하세요. OCR 오류는 문맥에 맞게 교정하세요.

{extracted_text}
"""

    def _call_llm(self, prompt: str) -> ParsedExam:
        """Route to the appropriate LLM based on self.llm_name."""
        for prefix, method_name in _LLM_ROUTER.items():
            if prefix in self.llm_name:
                return getattr(self, method_name)(prompt)
        raise ValueError(f"Unsupported LLM for hybrid: {self.llm_name}")

    @retry_llm_call()
    def _call_gemini(self, prompt: str) -> ParsedExam:
        from google import genai
        from google.genai import types

        if self._llm_client is None:
            settings = get_settings()
            self._llm_client = genai.Client(api_key=settings.GOOGLE_API_KEY)

        response = self._llm_client.models.generate_content(
            model=self.llm_name,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ParsedExam,
                temperature=0.1,
            ),
        )

        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self._add_tokens(
                getattr(response.usage_metadata, 'prompt_token_count', 0),
                getattr(response.usage_metadata, 'candidates_token_count', 0),
            )

        return ParsedExam.model_validate_json(response.text)

    @retry_llm_call()
    def _call_openai(self, prompt: str) -> ParsedExam:
        from openai import OpenAI

        if self._llm_client is None:
            settings = get_settings()
            self._llm_client = OpenAI(api_key=settings.OPENAI_API_KEY)

        response = self._llm_client.beta.chat.completions.parse(
            model=self.llm_name,
            messages=[
                {"role": "system", "content": "You are an expert exam data extraction system. Parse the provided text into structured JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format=ParsedExam,
            max_completion_tokens=LLM_MAX_TOKENS,
        )

        if response.usage:
            self._add_tokens(response.usage.prompt_tokens, response.usage.completion_tokens)

        return response.choices[0].message.parsed

    @retry_llm_call()
    def _call_anthropic(self, prompt: str) -> ParsedExam:
        from anthropic import Anthropic

        if self._llm_client is None:
            settings = get_settings()
            self._llm_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        response = self._llm_client.messages.create(
            model=self.llm_name,
            max_tokens=LLM_MAX_TOKENS,
            temperature=0.1,
            system="You are an expert exam data extraction system. Parse the provided text into structured JSON.",
            messages=[
                {"role": "user", "content": f"{prompt}\n\nJSON만 출력하세요. 코드블록이나 마크다운은 포함하지 마세요."}
            ],
        )

        self._add_tokens(response.usage.input_tokens, response.usage.output_tokens)

        if not response.content:
            raise ValueError("Anthropic API returned an empty content list.")
        block = response.content[0]
        if not hasattr(block, "text"):
            raise ValueError(f"Anthropic API returned unexpected content block type: {type(block).__name__}")
        text = strip_code_fences(block.text)
        return ParsedExam.model_validate_json(text)

    def get_ocr_metrics(self) -> dict:
        """Return OCR-specific timing metrics."""
        return self.ocr_metrics
