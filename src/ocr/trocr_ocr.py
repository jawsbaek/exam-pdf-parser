"""
TrOCR engine.
Microsoft TrOCR (Transformer-based OCR) 을 사용한 텍스트 추출.
Vision Transformer + Language Model 기반의 최신 OCR.
"""

from PIL import Image

from .base import OCREngine, _check_import


class TrOCREngine(OCREngine):
    """TrOCR: Transformer-based Optical Character Recognition"""

    def __init__(self, model_name: str = "microsoft/trocr-base-printed"):
        super().__init__(name="trocr", languages=["en", "ko"])
        self._processor = None
        self._model = None
        self._model_name = model_name

    def _initialize(self):
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        self._processor = TrOCRProcessor.from_pretrained(self._model_name)
        self._model = VisionEncoderDecoderModel.from_pretrained(self._model_name)

        # Use GPU if available
        self._device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self._model.to(self._device)
        self._model.eval()

    def _extract_from_image(self, image: Image.Image) -> str:
        """
        TrOCR processes line-level images, so we split the page into
        horizontal strips and OCR each strip individually.
        """
        import torch

        lines = self._segment_lines(image)
        extracted = []

        # Process in batches for efficiency
        batch_size = 8
        for i in range(0, len(lines), batch_size):
            batch = lines[i:i + batch_size]
            pixel_values = self._processor(
                images=batch, return_tensors="pt"
            ).pixel_values.to(self._device)

            with torch.no_grad():
                generated_ids = self._model.generate(
                    pixel_values,
                    max_new_tokens=128,
                )

            texts = self._processor.batch_decode(generated_ids, skip_special_tokens=True)
            extracted.extend(texts)

        return "\n".join(extracted)

    def _segment_lines(self, image: Image.Image, min_height: int = 20, padding: int = 2) -> list:
        """
        Segment a page image into individual text lines using
        horizontal projection profile.
        """
        import numpy as np

        gray = image.convert("L")
        arr = np.array(gray)

        # Binarize (white text on dark = invert, dark text on white = keep)
        threshold = 200
        binary = (arr < threshold).astype(np.uint8)

        # Horizontal projection
        h_proj = binary.sum(axis=1)

        # Find line boundaries
        in_line = False
        lines = []
        line_start = 0
        gap_start = 0
        min_gap = 3  # Minimum gap pixels between lines

        for y, val in enumerate(h_proj):
            if val > 0:
                if not in_line:
                    line_start = y
                    in_line = True
                gap_start = 0
            elif in_line:  # val == 0 and in_line
                if gap_start == 0:
                    gap_start = y
                if y - gap_start >= min_gap:
                    if gap_start - line_start >= min_height:
                        lines.append((max(0, line_start - padding), min(arr.shape[0], gap_start + padding)))
                    in_line = False
                    gap_start = 0

        # Handle last line
        if in_line and arr.shape[0] - line_start >= min_height:
            lines.append((max(0, line_start - padding), arr.shape[0]))

        # Crop line images
        line_images = []
        for y1, y2 in lines:
            line_img = image.crop((0, y1, image.width, y2))
            line_images.append(line_img)

        # If no lines detected, return the whole image
        if not line_images:
            line_images = [image]

        return line_images

    @staticmethod
    def is_available() -> bool:
        return _check_import("transformers")
