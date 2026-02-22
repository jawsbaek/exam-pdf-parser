"""
PaddleOCR engine.
PaddleOCR을 사용한 고성능 OCR 텍스트 추출.
"""

import numpy as np
from PIL import Image

from .base import OCREngine, _check_import


class PaddleOCREngine(OCREngine):

    def __init__(self):
        super().__init__(name="paddleocr", languages=["korean", "en"])
        self._ocr = None

    def _initialize(self):
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(use_angle_cls=True, lang="korean", show_log=False)

    def _extract_from_image(self, image: Image.Image) -> str:
        img_array = np.array(image)
        result = self._ocr.ocr(img_array, cls=True)
        lines = []
        if result and result[0]:
            # Sort by vertical position (top to bottom)
            items = sorted(result[0], key=lambda x: (x[0][0][1] // 50, x[0][0][0]))
            for item in items:
                if len(item) >= 2 and item[1]:
                    text = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                    lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def is_available() -> bool:
        return _check_import("paddleocr")
