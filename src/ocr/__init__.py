"""
OCR engines and document parsers for text extraction from exam PDFs.
"""

import importlib

from .base import OCREngine, PDFBasedOCREngine

# Registry: engine_name -> (module_suffix, class_name)
# Modules are loaded on demand via importlib (lazy imports).
_ENGINE_REGISTRY: dict[str, tuple[str, str]] = {
    # Document parsers (PDF → Markdown, recommended for Layer 1)
    "marker": ("marker_ocr", "MarkerOCREngine"),
    "mineru": ("mineru_ocr", "MinerUOCREngine"),
    "docling": ("docling_ocr", "DoclingOCREngine"),
    # Direct PDF text extraction
    "pymupdf-text": ("pymupdf_ocr", "PyMuPDFTextExtractor"),
    # Traditional OCR engines
    "tesseract": ("tesseract_ocr", "TesseractOCR"),
    "easyocr": ("easyocr_ocr", "EasyOCREngine"),
    "paddleocr": ("paddleocr_ocr", "PaddleOCREngine"),
    "surya": ("surya_ocr", "SuryaOCR"),
    "trocr": ("trocr_ocr", "TrOCREngine"),
    "deepseek-ocr": ("deepseek_ocr", "DeepSeekOCREngine"),
}


def _load_engine_class(name: str) -> type:
    """Dynamically load an OCR engine class by registry name."""
    module_suffix, class_name = _ENGINE_REGISTRY[name]
    module = importlib.import_module(f".{module_suffix}", package=__package__)
    return getattr(module, class_name)


def get_ocr_engine(name: str) -> OCREngine:
    """Get an OCR engine by name. Returns a new instance each call; expensive model init is cached inside each engine via _ensure_initialized()."""
    if name not in _ENGINE_REGISTRY:
        raise ValueError(f"Unknown OCR engine: {name}. Available: {list(_ENGINE_REGISTRY.keys())}")
    return _load_engine_class(name)()


def list_available_engines() -> dict:
    """List all OCR engines with availability status."""
    return {
        name: {
            "class": class_name,
            "available": _load_engine_class(name).is_available(),
        }
        for name, (_, class_name) in _ENGINE_REGISTRY.items()
    }


def __getattr__(name: str):
    """Lazy attribute access for backward-compatible OCR_ENGINES dict."""
    if name == "OCR_ENGINES":
        engines = {n: _load_engine_class(n) for n in _ENGINE_REGISTRY}
        globals()[name] = engines  # cache to avoid repeated computation
        return engines
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "OCREngine",
    "PDFBasedOCREngine",
    "OCR_ENGINES",
    "get_ocr_engine",
    "list_available_engines",
]
