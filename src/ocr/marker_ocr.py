"""
Marker PDF to Markdown converter.
marker-pdf 패키지를 사용하여 PDF를 Markdown으로 변환합니다.
"""

from .base import PDFBasedOCREngine, _check_import


class MarkerOCREngine(PDFBasedOCREngine):
    """
    Marker: high-accuracy PDF to Markdown conversion.
    Uses deep learning models for layout detection, OCR, and formatting.
    Best for complex layouts with tables, figures, and multi-column text.

    Install: pip install marker-pdf
    """

    def __init__(self):
        super().__init__(name="marker", languages=["en", "ko"])
        self._converter = None

    def _initialize(self):
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        self._model_dict = create_model_dict()
        self._converter = PdfConverter(artifact_dict=self._model_dict)

    def _convert_pdf(self, pdf_path: str) -> str:
        """Convert PDF to Markdown using Marker."""
        rendered = self._converter(pdf_path)
        return rendered.markdown

    @staticmethod
    def is_available() -> bool:
        return _check_import("marker")
