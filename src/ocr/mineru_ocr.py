"""
MinerU PDF to Markdown converter.
MinerU 패키지를 사용하여 PDF를 Markdown으로 변환합니다.
Supports MinerU v2.x (mineru package) and legacy v1.x (magic_pdf package).
"""

import os
import tempfile
from pathlib import Path

from .base import PDFBasedOCREngine, _check_import


class MinerUOCREngine(PDFBasedOCREngine):
    """
    MinerU: high-quality PDF extraction with layout analysis.
    Supports OCR and text-based PDFs with accurate structure preservation.

    Install: pip install "mineru[core]"
    """

    def __init__(self):
        super().__init__(name="mineru", languages=["en", "ko"])
        self._use_v2 = None  # auto-detect

    def _initialize(self):
        # Try v2 first (mineru package), then fallback to v1 (magic_pdf)
        try:
            from mineru.backend.pipeline.pipeline_analyze import doc_analyze  # noqa: F401

            self._use_v2 = True
        except ImportError:
            import magic_pdf  # noqa: F401

            self._use_v2 = False

    def _extract_v2(self, pdf_path: str) -> str:
        """MinerU v2.x pipeline (mineru package)."""
        from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json
        from mineru.backend.pipeline.pipeline_analyze import doc_analyze
        from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make
        from mineru.data.data_reader_writer import FileBasedDataWriter
        from mineru.utils.enum_class import MakeMode

        pdf_bytes = Path(pdf_path).read_bytes()

        # doc_analyze expects lists (batch API)
        infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = doc_analyze(
            [pdf_bytes], ["en"], parse_method="auto", formula_enable=True, table_enable=True
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_dir = os.path.join(tmp_dir, "images")
            os.makedirs(image_dir, exist_ok=True)
            image_writer = FileBasedDataWriter(image_dir)

            model_list = infer_results[0]
            images_list = all_image_lists[0]
            pdf_doc = all_pdf_docs[0]
            _lang = lang_list[0]
            _ocr_enable = ocr_enabled_list[0]

            middle_json = result_to_middle_json(
                model_list, images_list, pdf_doc, image_writer, _lang, _ocr_enable, True
            )

            pdf_info = middle_json["pdf_info"]
            md_content = union_make(pdf_info, MakeMode.NLP_MD, os.path.basename(image_dir))

        return md_content

    def _extract_v1(self, pdf_path: str) -> str:
        """Legacy MinerU v1.x pipeline (magic_pdf package)."""
        from magic_pdf.data.data_reader_writer import FileBasedDataWriter
        from magic_pdf.data.dataset import PymuDocDataset
        from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze

        pdf_bytes = Path(pdf_path).read_bytes()
        dataset = PymuDocDataset(pdf_bytes)
        infer_result = doc_analyze(dataset)

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_dir = os.path.join(tmp_dir, "images")
            os.makedirs(image_dir, exist_ok=True)
            image_writer = FileBasedDataWriter(image_dir)
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
            md_content = pipe_result.get_markdown(image_dir)

        return md_content

    def _convert_pdf(self, pdf_path: str) -> str:
        """Convert PDF to Markdown using MinerU (v2 or v1 based on available package)."""
        if self._use_v2:
            return self._extract_v2(pdf_path)
        return self._extract_v1(pdf_path)

    @staticmethod
    def is_available() -> bool:
        return _check_import("mineru") or _check_import("magic_pdf")
