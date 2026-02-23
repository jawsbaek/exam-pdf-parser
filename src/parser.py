"""
Main exam parser orchestrator.
3-Layer Architecture: Parsing → LLM Structuring → Validation.

Layer 1: Document parsers (Marker/MinerU/Docling/PyMuPDF/OCR) extract text from PDF
Layer 2: LLM (Gemini/GPT) structures text into ParsedExam JSON
Layer 3: Validator checks completeness and accuracy
"""

import logging
import time
from pathlib import Path

from .config import MODEL_CONFIG
from .models.hybrid_client import HybridOCRClient
from .pdf_parser import PDFParser
from .schema import ExamInfo, ParsedExam, ParseResult

logger = logging.getLogger(__name__)

# All models are hybrid (document parser + LLM)
HYBRID_MODELS = [k for k in MODEL_CONFIG if "+" in k]


class ExamParser:
    """Main exam parser that orchestrates the 3-layer pipeline."""

    SUPPORTED_MODELS = {name: HybridOCRClient for name in HYBRID_MODELS}

    def __init__(self, pdf_path: str, dpi: int = 200):
        self.pdf_parser = PDFParser(pdf_path, dpi=dpi)
        self.pdf_path = Path(pdf_path)

    def parse_with_model(
        self,
        model_name: str,
        instruction: str | None = None
    ) -> ParseResult:
        if model_name not in MODEL_CONFIG:
            raise ValueError(
                f"Unsupported model: {model_name}. "
                f"Supported: {list(MODEL_CONFIG.keys())}"
            )

        start_time = time.time()

        client = HybridOCRClient(model_name=model_name, pdf_path=str(self.pdf_path))

        # Skip expensive image conversion for PDF-based engines (e.g., MinerU)
        if client.ocr_engine.is_pdf_based:
            images = []
            pages_processed = self.pdf_parser.page_count
        else:
            images = self.pdf_parser.get_page_images_as_bytes()
            pages_processed = len(images)

        parsed_exam = client.parse_exam(images, instruction=instruction)
        parsing_time = time.time() - start_time

        input_tokens, output_tokens = client.get_token_usage()
        cost = self._calculate_cost(model_name, input_tokens, output_tokens)

        result = ParseResult(
            model_name=model_name,
            parsed_exam=parsed_exam,
            total_tokens_input=input_tokens,
            total_tokens_output=output_tokens,
            total_cost_usd=cost,
            parsing_time_seconds=parsing_time,
            pages_processed=pages_processed,
        )

        # Attach OCR metrics
        if hasattr(client, 'get_ocr_metrics'):
            result.ocr_metrics = client.get_ocr_metrics()

        return result

    def parse_with_all_models(
        self,
        instruction: str | None = None,
    ) -> dict[str, ParseResult]:
        """Parse exam using all available hybrid models."""
        results: dict[str, ParseResult] = {}

        for model_name in HYBRID_MODELS:
            try:
                logger.info("Parsing with %s...", model_name)
                result = self.parse_with_model(model_name, instruction=instruction)
                results[model_name] = result
                logger.info("  %s done in %.2fs", model_name, result.parsing_time_seconds)
            except Exception as e:
                logger.error("  %s failed: %s", model_name, e)
                results[model_name] = ParseResult(
                    model_name=model_name,
                    parsed_exam=ParsedExam(exam_info=ExamInfo(title=""), questions=[]),
                    error=str(e),
                )

        return results

    @staticmethod
    def _calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
        if model_name not in MODEL_CONFIG:
            return 0.0
        config = MODEL_CONFIG[model_name]
        input_cost = (input_tokens / 1_000_000) * config["input_price_per_1m"]
        output_cost = (output_tokens / 1_000_000) * config["output_price_per_1m"]
        return input_cost + output_cost


