"""
Question image cropper using PyMuPDF.
문제 영역을 이미지로 크롭합니다.
"""

import logging
import os
from pathlib import Path

import fitz  # PyMuPDF

from ..schema import CroppedQuestion, QuestionRegion

logger = logging.getLogger(__name__)


class QuestionCropper:
    """Crop question regions from PDF pages as PNG images."""

    def __init__(self, pdf_path: str, dpi: int = 300, padding: float = 5.0):
        """
        Args:
            pdf_path: Path to the source PDF
            dpi: Resolution for cropped images (default 300 for clarity)
            padding: Extra margin around bbox in PDF points (default 5.0)
        """
        self.pdf_path = Path(pdf_path)
        self.dpi = dpi
        self.padding = padding
        self.zoom = dpi / 72

    def crop_regions(
        self,
        regions: list[QuestionRegion],
        output_dir: str = "output/cropped",
    ) -> list[CroppedQuestion]:
        """
        Crop all question regions to individual PNG images.

        Args:
            regions: Detected question regions with bbox coordinates
            output_dir: Directory to save PNG files

        Returns:
            List of CroppedQuestion with image paths
        """
        os.makedirs(output_dir, exist_ok=True)

        results: list[CroppedQuestion] = []
        mat = fitz.Matrix(self.zoom, self.zoom)

        with fitz.open(self.pdf_path) as doc:
            for region in regions:
                if region.page_idx >= len(doc):
                    logger.warning(
                        "Question %d references page %d but PDF has %d pages, skipping",
                        region.question_number, region.page_idx, len(doc),
                    )
                    continue

                page = doc[region.page_idx]
                page_rect = page.rect

                # Apply padding and clamp to page bounds
                x0, y0, x1, y1 = region.bbox
                rect = fitz.Rect(
                    max(0, x0 - self.padding),
                    max(0, y0 - self.padding),
                    min(page_rect.width, x1 + self.padding),
                    min(page_rect.height, y1 + self.padding),
                )

                pix = page.get_pixmap(matrix=mat, clip=rect)
                img_bytes = pix.tobytes("png")

                # Save to file — use page suffix for cross-page questions
                suffix = f"_p{region.page_idx}" if region.spans_page else ""
                img_path = os.path.join(output_dir, f"q{region.question_number:02d}{suffix}.png")
                Path(img_path).write_bytes(img_bytes)
                logger.debug("Saved question %d crop to %s", region.question_number, img_path)

                results.append(CroppedQuestion(
                    question_number=region.question_number,
                    image_path=img_path,
                    width=pix.width,
                    height=pix.height,
                    source_page=region.page_idx,
                ))

        logger.info("Cropped %d question images from %s", len(results), self.pdf_path.name)
        return results
