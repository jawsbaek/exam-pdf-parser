"""
Docling PDF to Markdown converter.
Docling 패키지를 사용하여 PDF를 Markdown으로 변환합니다.
"""

from .base import PDFBasedOCREngine, _check_import


class DoclingOCREngine(PDFBasedOCREngine):
    """
    Docling: IBM's document conversion library.
    Converts PDF, DOCX, and other formats to structured Markdown.
    Good for academic papers and structured documents.

    Install: pip install docling
    """

    def __init__(self):
        super().__init__(name="docling", languages=["en", "ko"])
        self._converter = None

    def _initialize(self):
        from docling.document_converter import DocumentConverter

        self._converter = DocumentConverter()

    def _convert_pdf(self, pdf_path: str) -> str:
        """Convert PDF to Markdown using Docling."""
        result = self._converter.convert(pdf_path)
        return result.document.export_to_markdown()

    @staticmethod
    def is_available() -> bool:
        return _check_import("docling")
