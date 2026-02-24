"""
Question region detection from MinerU layout data.
MinerU middle_json에서 문제 영역을 감지합니다.

Column-aware processing: Korean exams use 2-column layout.
MinerU returns blocks in reading order that interleaves columns,
so we split blocks into columns and process each independently.
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


class QuestionRegionDetector:
    """Detect question regions from MinerU middle_json layout data.

    Uses column-aware processing to correctly handle 2-column exam layouts.
    """

    def __init__(self, min_question: int = 1, max_question: int = 50):
        self._min_q = min_question
        self._max_q = max_question

    def detect(self, middle_json: dict) -> list[QuestionRegion]:
        """
        Analyze para_blocks per page to detect question boundaries.

        Splits blocks into columns, processes each independently, then
        groups consecutive blocks between question number patterns
        into QuestionRegion objects with union bounding boxes.
        """
        regions: list[QuestionRegion] = []
        prev_page_last_q: int | None = None

        for page_info in middle_json.get("pdf_info", []):
            page_idx = page_info.get("page_idx", 0)
            blocks = page_info.get("para_blocks") or page_info.get("preproc_blocks", [])

            page_size = page_info.get("page_size", [842, 1191])
            page_width = page_size[0] if isinstance(page_size, list) else 842

            # Split into columns and process each independently
            columns = self._split_into_columns(blocks, page_width)
            page_regions: list[QuestionRegion] = []
            for i, col_blocks in enumerate(columns):
                # Only first column carries over from previous page's last question
                carry = prev_page_last_q if i == 0 else None
                col_regions = self._detect_in_column(col_blocks, page_idx, carry_over_q_num=carry)
                page_regions.extend(col_regions)
            regions.extend(page_regions)

            # Track last question on this page for cross-page carry-over
            if page_regions:
                prev_page_last_q = max(r.question_number for r in page_regions)

        # Post-processing: fix OCR digit-split errors and cross-page questions
        regions = self._fix_sequential_order(regions)
        regions = self._merge_cross_page(regions)
        regions.sort(key=lambda r: r.question_number)

        logger.info("Detected %d question regions", len(regions))
        return regions

    def _split_into_columns(self, blocks: list[dict], page_width: float) -> list[list[dict]]:
        """Split page blocks into separate columns for independent processing.

        Korean exam pages use 2-column layout. MinerU returns blocks in a
        reading order that interleaves columns, causing sequential grouping
        to assign blocks from one column to questions in the other.

        Splitting prevents union bboxes from incorrectly spanning both columns
        and ensures each question gets only its own column's blocks.
        """
        if not blocks:
            return []

        mid_x = page_width / 2
        left: list[dict] = []
        right: list[dict] = []

        for block in blocks:
            if "bbox" not in block:
                continue
            x0, _, x1, _ = block["bbox"]
            center_x = (x0 + x1) / 2

            if center_x <= mid_x:
                left.append(block)
            else:
                right.append(block)

        # Sort each column by y-coordinate for proper sequential processing
        left.sort(key=lambda b: b["bbox"][1])
        right.sort(key=lambda b: b["bbox"][1])

        result = []
        if left:
            result.append(left)
        if right:
            result.append(right)
        return result if result else [[]]

    def _detect_in_column(
        self, blocks: list[dict], page_idx: int, carry_over_q_num: int | None = None,
    ) -> list[QuestionRegion]:
        """Detect question regions within a single column of blocks.

        Args:
            blocks: Blocks in this column, sorted by y-coordinate
            page_idx: Page index
            carry_over_q_num: Last question number from previous page's column.
                Used to assign cross-page continuation blocks to the correct question.

        Blocks before the first detected question are handled based on context:
        - If a section header was seen (e.g., [41~42]): group passage → assign to first question
        - If carry_over_q_num is set (no section header): cross-page continuation → assign to carry-over
        - Otherwise: assign to first question as generous crop
        """
        regions: list[QuestionRegion] = []

        current_q_num: int | None = None
        current_bboxes: list[list[float]] = []
        current_text = ""
        # Track blocks before first question
        pre_question_bboxes: list[list[float]] = []
        saw_section_header = False

        for block in blocks:
            if "bbox" not in block:
                continue

            text = self._extract_block_text(block)
            if not text.strip():
                if current_q_num is not None:
                    current_bboxes.append(block["bbox"])
                else:
                    pre_question_bboxes.append(block["bbox"])
                continue

            # Skip section headers like [31~34]
            if self._is_section_header(text):
                saw_section_header = True
                continue

            q_num, _group_range = self._detect_question_start(text)

            if q_num is not None and q_num != current_q_num:
                # Save previous question
                if current_q_num is not None:
                    regions.append(QuestionRegion(
                        question_number=current_q_num,
                        page_idx=page_idx,
                        bbox=self._union_bbox(current_bboxes),
                        text_preview=current_text[:80],
                    ))
                # Handle pre-question blocks
                current_q_num = q_num
                if pre_question_bboxes:
                    if not saw_section_header and carry_over_q_num is not None:
                        # Cross-page continuation — assign to previous page's question
                        regions.append(QuestionRegion(
                            question_number=carry_over_q_num,
                            page_idx=page_idx,
                            bbox=self._union_bbox(pre_question_bboxes),
                            text_preview="(continuation from previous page)",
                            spans_page=True,
                        ))
                        current_bboxes = [block["bbox"]]
                    else:
                        # Group passage or first-question context — assign to this question
                        current_bboxes = pre_question_bboxes + [block["bbox"]]
                    pre_question_bboxes = []
                else:
                    current_bboxes = [block["bbox"]]
                current_text = text
            elif current_q_num is not None:
                current_bboxes.append(block["bbox"])
                current_text += " " + text
            else:
                # Blocks before any question
                pre_question_bboxes.append(block["bbox"])

        # Save last question in column
        if current_q_num is not None:
            regions.append(QuestionRegion(
                question_number=current_q_num,
                page_idx=page_idx,
                bbox=self._union_bbox(current_bboxes),
                text_preview=current_text[:80],
            ))

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
