"""
OCR engines and document parsers for text extraction from exam PDFs.
"""

from .base import OCREngine, PDFBasedOCREngine
from .mineru_ocr import MinerUOCREngine

# OCR engine registry — add new engines here
OCR_ENGINES: dict[str, type[OCREngine]] = {
    "mineru": MinerUOCREngine,
}


def register_ocr_engine(name: str, engine_class: type[OCREngine]) -> None:
    """Register a new OCR engine."""
    OCR_ENGINES[name] = engine_class


def get_ocr_engine(name: str) -> OCREngine:
    """Get an OCR engine by name."""
    engine_class = OCR_ENGINES.get(name)
    if engine_class is None:
        raise ValueError(f"Unknown OCR engine: {name}. Available: {list(OCR_ENGINES.keys())}")
    return engine_class()


def list_available_engines() -> dict:
    """List all OCR engines with availability status."""
    return {
        name: {
            "class": cls.__name__,
            "available": cls.is_available(),
        }
        for name, cls in OCR_ENGINES.items()
    }


__all__ = [
    "OCREngine",
    "PDFBasedOCREngine",
    "OCR_ENGINES",
    "register_ocr_engine",
    "get_ocr_engine",
    "list_available_engines",
]
