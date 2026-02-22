"""
PDF parsing utilities using PyMuPDF.
PDF 파일을 이미지로 변환하여 처리합니다.
"""

from pathlib import Path

import fitz  # PyMuPDF


class PDFParser:
    """PDF 파일을 이미지로 변환하는 파서"""

    def __init__(self, pdf_path: str, dpi: int = 200):
        """
        Initialize PDF parser.

        Args:
            pdf_path: Path to PDF file
            dpi: Resolution for image conversion (default: 200)
        """
        if not 72 <= dpi <= 600:
            raise ValueError(f"DPI must be between 72 and 600, got {dpi}")
        self.pdf_path = Path(pdf_path)
        self.dpi = dpi
        self.zoom = dpi / 72  # PDF default is 72 DPI

    def get_page_images_as_bytes(self) -> list[tuple[bytes, str]]:
        """
        Get all pages as PNG bytes with MIME type.

        Returns:
            List of (image_bytes, mime_type) tuples
        """
        images = []
        mat = fitz.Matrix(self.zoom, self.zoom)

        with fitz.open(self.pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                images.append((img_bytes, "image/png"))

        return images
