"""
OCR engines and document parsers for text extraction from exam PDFs.
"""

from .base import OCREngine, PDFBasedOCREngine
from .mineru_ocr import MinerUOCREngine


def get_ocr_engine(name: str) -> OCREngine:
    """Get an OCR engine by name."""
    if name != "mineru":
        raise ValueError(f"Unknown OCR engine: {name}. Available: ['mineru']")
    return MinerUOCREngine()


def list_available_engines() -> dict:
    """List all OCR engines with availability status."""
    return {
        "mineru": {
            "class": "MinerUOCREngine",
            "available": MinerUOCREngine.is_available(),
        }
    }


__all__ = [
    "OCREngine",
    "PDFBasedOCREngine",
    "get_ocr_engine",
    "list_available_engines",
]
