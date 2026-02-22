"""
EasyOCR engine.
EasyOCR을 사용한 다국어 OCR 텍스트 추출.
"""

import numpy as np
from PIL import Image

from .base import OCREngine, _check_import


class EasyOCREngine(OCREngine):

    def __init__(self):
        super().__init__(name="easyocr", languages=["ko", "en"])
        self._reader = None

    def _initialize(self):
        import easyocr
        try:
            import torch
            gpu = torch.cuda.is_available()
        except ImportError:
            gpu = False
        self._reader = easyocr.Reader(self.languages, gpu=gpu)

    def _extract_from_image(self, image: Image.Image) -> str:
        img_array = np.array(image)
        results = self._reader.readtext(img_array, detail=1, paragraph=True)
        lines = []
        for item in results:
            if len(item) >= 2:
                lines.append(item[1])
        return "\n".join(lines)

    @staticmethod
    def is_available() -> bool:
        return _check_import("easyocr")
