"""
Question region detection from MinerU layout data.
MinerU middle_json에서 문제 영역을 감지합니다.
"""

import logging
import re
from collections import Counter

from ..schema import QuestionRegion

logger = logging.getLogger(__name__)

# Korean exam question number patterns (ordered by specificity)
# Key insight: Korean exams often have "N.다음" (no space after dot)
_Q_NUM_PATTERNS = [
    re.compile(r'^\[(\d{1,2})\s*[~∼]\s*(\d{1,2})\]'),  # [41~42] or [41 ~ 42] group questions
    re.compile(r'^【(\d{1,2})】'),                        # 【18】 format
    re.compile(r'^\[(\d{1,2})\]'),                       # [18] format
    re.compile(r'^(\d{1,2})\.'),                         # "18." or "18.다음" (no space needed)
    re.compile(r'^(\d{1,2})\s'),                         # "18 " format (last resort)
]

# Section header patterns to skip (not actual questions)
_SECTION_HEADER_RE = re.compile(
    r'^\[\s*\d{1,2}\s*[~∼]\s*\d{1,2}\s*\]'  # [31~34], [36~37] section headers
)


class QuestionRegionDetector:
    """Detect question regions from MinerU middle_json layout data."""

    def __init__(self, min_question: int = 1, max_question: int = 50):
        self._min_q = min_question
        self._max_q = max_question

    def detect(self, middle_json: dict) -> list[QuestionRegion]:
        """
        Analyze para_blocks per page to detect question boundaries.

        Groups consecutive blocks between question number patterns
        into QuestionRegion objects with union bounding boxes.
        """
        regions: list[QuestionRegion] = []

        for page_info in middle_json.get("pdf_info", []):
            page_idx = page_info.get("page_idx", 0)
            blocks = page_info.get("para_blocks") or page_info.get("preproc_blocks", [])

            current_q_num = None
            current_bboxes: list[list[float]] = []
            current_text = ""

            for block in blocks:
                if "bbox" not in block:
                    continue

                text = self._extract_block_text(block)
                if not text.strip():
                    if current_q_num is not None:
                        current_bboxes.append(block["bbox"])
                    continue

                # Skip section headers like [31~34]
                if self._is_section_header(text):
                    continue

                q_num, group_range = self._detect_question_start(text)

                if q_num is not None and q_num != current_q_num:
                    # Save previous question
                    if current_q_num is not None:
                        regions.append(QuestionRegion(
                            question_number=current_q_num,
                            page_idx=page_idx,
                            bbox=self._union_bbox(current_bboxes),
                            text_preview=current_text[:80],
                        ))
                    # Start new question
                    current_q_num = q_num
                    current_bboxes = [block["bbox"]]
                    current_text = text
                elif current_q_num is not None:
                    current_bboxes.append(block["bbox"])
                    current_text += " " + text

            # Save last question on page
            if current_q_num is not None:
                regions.append(QuestionRegion(
                    question_number=current_q_num,
                    page_idx=page_idx,
                    bbox=self._union_bbox(current_bboxes),
                    text_preview=current_text[:80],
                ))

        # Post-processing: fix sequential order and fill gaps
        regions = self._fix_sequential_order(regions)
        regions = self._merge_cross_page(regions)
        regions.sort(key=lambda r: r.question_number)

        logger.info("Detected %d question regions", len(regions))
        return regions

    def _extract_block_text(self, block: dict) -> str:
        """Extract text content from a MinerU block (lines -> spans -> content)."""
        texts = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                content = span.get("content", "")
                if content:
                    texts.append(content)
        return " ".join(texts).strip()

    def _is_section_header(self, text: str) -> bool:
        """Check if text is a section header like [31~34] (not an actual question).

        Section headers are short standalone text with a range bracket and a brief descriptor.
        Group questions like [41~42] have substantial body text after the bracket.
        """
        text = text.strip()
        if re.match(r'^\[\s*\d', text) and ('\\sim' in text or '~' in text or '∼' in text):
            bracket_end = text.find(']')
            if bracket_end != -1:
                after = text[bracket_end + 1:].strip()
                # Section headers are short; group questions have substantial text
                if not after or len(after) < 30:
                    return True
        return False

    def _detect_question_start(self, text: str) -> tuple[int | None, str | None]:
        """Detect question number at start of text. Returns (number, group_range) or (None, None)."""
        text = text.strip()
        for pattern in _Q_NUM_PATTERNS:
            m = pattern.match(text)
            if m:
                q_num = int(m.group(1))
                if not (self._min_q <= q_num <= self._max_q):
                    continue
                group_range = None
                if len(m.groups()) >= 2 and m.group(2):
                    group_range = f"{m.group(1)}~{m.group(2)}"
                return q_num, group_range
        return None, None

    def _fix_sequential_order(self, regions: list[QuestionRegion]) -> list[QuestionRegion]:
        """
        Fix out-of-order detections caused by OCR splitting digits.

        Example: MinerU splits "34." into block ending with "3" + block starting with "4."
        causing Q34 to be detected as Q4. Fix by resolving duplicate question numbers
        using page context — if Q4 appears on page 0 (correct) AND page 5 (should be Q34),
        fix the out-of-place duplicate.
        """
        if not regions:
            return regions

        # Step 1: Find duplicate question numbers
        num_counts = Counter(r.question_number for r in regions)
        duplicates = {n for n, c in num_counts.items() if c > 1}

        if not duplicates:
            return regions

        # Step 2: For each duplicate, determine which one is out of place
        # Build a set of all detected numbers to find gaps
        all_nums = {r.question_number for r in regions}
        fixed = []

        for r in regions:
            if r.question_number not in duplicates:
                fixed.append(r)
                continue

            # This is a duplicate — check if it's the out-of-place one
            # Heuristic: find neighboring questions on the same page to infer expected number
            same_page = [
                rr.question_number for rr in regions
                if rr.page_idx == r.page_idx and rr is not r and rr.question_number not in duplicates
            ]

            if same_page:
                neighbors = sorted(same_page)
                # Expected range on this page
                expected_min = min(neighbors) - 3
                expected_max = max(neighbors) + 3

                if expected_min <= r.question_number <= expected_max:
                    # This instance fits the page context — keep it
                    fixed.append(r)
                else:
                    # Out of place — try to infer correct number
                    # Find the gap near the neighbors
                    for candidate in range(max(1, min(neighbors) - 2), min(self._max_q, max(neighbors) + 2) + 1):
                        if candidate not in all_nums and candidate % 10 == r.question_number % 10:
                            logger.info(
                                "Fixed Q%d → Q%d (page %d neighbors: %s)",
                                r.question_number, candidate, r.page_idx, neighbors,
                            )
                            fixed.append(QuestionRegion(
                                question_number=candidate,
                                page_idx=r.page_idx,
                                bbox=r.bbox,
                                text_preview=r.text_preview,
                                spans_page=r.spans_page,
                            ))
                            all_nums.add(candidate)
                            break
                    else:
                        # Couldn't fix — keep original
                        fixed.append(r)
            else:
                # No non-duplicate neighbors — keep as-is
                fixed.append(r)

        return fixed

    def _union_bbox(self, bboxes: list[list[float]]) -> tuple[float, float, float, float]:
        """Compute union bounding box from multiple bboxes."""
        x0 = min(b[0] for b in bboxes)
        y0 = min(b[1] for b in bboxes)
        x1 = max(b[2] for b in bboxes)
        y1 = max(b[3] for b in bboxes)
        return (x0, y0, x1, y1)

    def _merge_cross_page(self, regions: list[QuestionRegion]) -> list[QuestionRegion]:
        """Handle questions spanning page boundaries."""
        seen: dict[int, list[QuestionRegion]] = {}
        for r in regions:
            seen.setdefault(r.question_number, []).append(r)

        merged = []
        for q_num, group in seen.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                for r in group:
                    r.spans_page = True
                    merged.append(r)
        return merged
