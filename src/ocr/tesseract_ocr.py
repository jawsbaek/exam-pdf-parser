"""
Tesseract OCR engine.
Google Tesseract를 사용한 OCR 텍스트 추출.
"""

from PIL import Image

from .base import OCREngine, _check_import


class TesseractOCR(OCREngine):

    def __init__(self):
        super().__init__(name="tesseract", languages=["eng", "kor"])
        self._pytesseract = None

    def _initialize(self):
        import pytesseract
        self._pytesseract = pytesseract

    def _extract_from_image(self, image: Image.Image) -> str:
        lang_str = "+".join(self.languages)
        config = "--oem 3 --psm 6"
        return self._pytesseract.image_to_string(image, lang=lang_str, config=config)

    @staticmethod
    def is_available() -> bool:
        return _check_import("pytesseract")
