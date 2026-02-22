"""
PyMuPDF text extraction (not true OCR).
PDF에서 직접 텍스트를 추출합니다 (디지털 PDF에 적합).
"""

from .base import PDFBasedOCREngine, _check_import


class PyMuPDFTextExtractor(PDFBasedOCREngine):
    """
    Direct text extraction from PDF using PyMuPDF.
    Works best with digital PDFs (not scanned images).
    Falls back to page-level OCR for image-based pages.
    """

    def __init__(self):
        super().__init__(name="pymupdf-text", languages=["en", "ko"])

    def _initialize(self):
        import fitz  # noqa: F401

    def _convert_pdf(self, pdf_path: str) -> str:
        """Extract text directly from PDF file."""
        import fitz

        all_text = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc):
                text = page.get_text("text")
                if text.strip():
                    all_text.append(f"--- Page {i+1} ---\n{text}")
                else:
                    # Try OCR-like extraction with text blocks
                    blocks = page.get_text("blocks")
                    block_texts = []
                    for block in blocks:
                        if block[6] == 0:  # text block
                            block_texts.append(block[4])
                    if block_texts:
                        all_text.append(f"--- Page {i+1} ---\n" + "\n".join(block_texts))

        return "\n\n".join(all_text)

    @staticmethod
    def is_available() -> bool:
        return _check_import("fitz")
