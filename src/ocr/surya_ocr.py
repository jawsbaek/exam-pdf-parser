"""
Surya OCR engine.
Surya를 사용한 문서 전문 OCR 텍스트 추출.
"""

from PIL import Image

from .base import OCREngine, _check_import


class SuryaOCR(OCREngine):

    def __init__(self):
        super().__init__(name="surya", languages=["en", "ko"])

    def _initialize(self):
        from surya.recognition import RecognitionPredictor
        self._predictor = RecognitionPredictor()

    def _extract_from_image(self, image: Image.Image) -> str:
        predictions = self._predictor([image], languages=self.languages)
        lines = []
        if predictions and len(predictions) > 0:
            pred = predictions[0]
            if hasattr(pred, 'text_lines'):
                for line in pred.text_lines:
                    lines.append(line.text if hasattr(line, 'text') else str(line))
            elif isinstance(pred, dict) and 'text_lines' in pred:
                for line in pred['text_lines']:
                    text = line.get('text', '') if isinstance(line, dict) else str(line)
                    lines.append(text)
            else:
                lines.append(str(pred))
        return "\n".join(lines)

    @staticmethod
    def is_available() -> bool:
        return _check_import("surya")
