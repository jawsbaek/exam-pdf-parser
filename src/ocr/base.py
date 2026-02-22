"""
Base class for OCR engines.
OCR 엔진의 기본 인터페이스를 정의합니다.
"""

import io
import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image


def _check_import(*module_names: str) -> bool:
    """Check if all given module names can be imported."""
    for name in module_names:
        try:
            __import__(name)
        except ImportError:
            return False
    return True


class OCREngine(ABC):
    """Base class for all OCR engines"""

    def __init__(self, name: str, languages: list[str] | None = None):
        self.name = name
        self.languages = languages or ["en", "ko"]
        self._initialized = False
        self._init_lock = threading.Lock()
        self.init_time = 0.0
        self.ocr_time = 0.0

    def _ensure_initialized(self):
        with self._init_lock:
            if not self._initialized:
                start = time.time()
                self._initialize()
                self.init_time = time.time() - start
                self._initialized = True

    @abstractmethod
    def _initialize(self):
        """Initialize the OCR engine (lazy loading)."""
        pass

    @abstractmethod
    def _extract_from_image(self, image: Image.Image) -> str:
        """Extract text from a single PIL Image."""
        pass

    def extract_text(self, images: list[tuple[bytes, str]]) -> str:
        """
        Extract text from list of (image_bytes, mime_type) tuples.

        Args:
            images: List of (image_bytes, mime_type) tuples

        Returns:
            Concatenated extracted text from all images
        """
        self._ensure_initialized()

        all_text = []
        start = time.time()

        for i, (img_bytes, _mime) in enumerate(images):
            try:
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                text = self._extract_from_image(img)
                all_text.append(f"--- Page {i+1} ---\n{text}")
            except Exception as e:
                all_text.append(f"--- Page {i+1} ---\n[OCR extraction failed: {e}]")

        self.ocr_time = time.time() - start
        return "\n\n".join(all_text)

    def get_metrics(self) -> dict:
        """Return timing metrics."""
        return {
            "engine": self.name,
            "init_time_seconds": round(self.init_time, 2),
            "ocr_time_seconds": round(self.ocr_time, 2),
            "total_time_seconds": round(self.init_time + self.ocr_time, 2),
        }

    @staticmethod
    def is_available() -> bool:
        """Check if this OCR engine's dependencies are installed."""
        return False


class PDFBasedOCREngine(OCREngine):
    """
    Intermediate base class for engines that operate directly on PDF files.
    Handles set_pdf_path(), extract_from_pdf() routing, and image fallback stub.
    Subclasses only need to implement: _initialize(), _convert_pdf(), is_available().
    """

    def __init__(self, name: str, languages: list[str] | None = None):
        super().__init__(name=name, languages=languages)
        self._pdf_path: Path | None = None

    def set_pdf_path(self, pdf_path: str):
        """Set PDF path for direct PDF conversion."""
        self._pdf_path = Path(pdf_path)

    @abstractmethod
    def _convert_pdf(self, pdf_path: str) -> str:
        """Convert PDF file to text/markdown. Called by extract_from_pdf()."""
        pass

    def _extract_from_image(self, image: Image.Image) -> str:
        """Stub: PDF-based engines don't process individual images."""
        logging.getLogger(__name__).warning(
            "%s works best with PDF files, not individual images", self.__class__.__name__
        )
        return ""

    def extract_from_pdf(self, pdf_path: str) -> str:
        """Convert PDF to text/markdown, tracking timing."""
        self._ensure_initialized()
        start = time.time()
        text = self._convert_pdf(pdf_path)
        self.ocr_time = time.time() - start
        return text

    def extract_text(self, images: list[tuple[bytes, str]]) -> str:
        """Route to PDF path if set, otherwise fall back to image-based extraction."""
        if self._pdf_path and self._pdf_path.exists():
            return self.extract_from_pdf(str(self._pdf_path))
        return super().extract_text(images)
