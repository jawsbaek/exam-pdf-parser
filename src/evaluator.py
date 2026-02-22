"""
Evaluation system for scoring parsed exam outputs against ground truth.
answer.md 파일을 파싱하고 모델 출력을 평가하는 시스템.
"""

import re
from difflib import SequenceMatcher
from pathlib import Path
from pydantic import BaseModel

from .schema import AnswerEntry, AnswerKey, Choice, ParsedExam


# ---------------------------------------------------------------------------
# Evaluation result models
# ---------------------------------------------------------------------------


class QuestionEval(BaseModel):
    number: int
    found: bool
    passagesimilarity: float = 0.0   # 0.0-1.0
    choices_correct: int = 0
    choices_total: int = 0
    question_textsimilarity: float = 0.0


class EvalResult(BaseModel):
    model_name: str
    total_questions_expected: int
    total_questions_found: int
    coverage_pct: float
    avg_passagesimilarity: float
    avg_choice_accuracy: float
    avg_question_textsimilarity: float
    overall_score: float
    per_question: list[QuestionEval]


# ---------------------------------------------------------------------------
# answer.md parser
# ---------------------------------------------------------------------------

# Unicode circled digits → int
_CIRCLE_MAP = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
}


def _parse_choices(block: str) -> list[Choice]:
    """Extract choices from the answer block.

    Handles two formats:
      - Plain:    ① some text
      - Markdown: - ① some text  or  - ① (with text on same line)
    Also handles bare digits like `2 text` that appear when circles are stripped.
    """
    choices: list[Choice] = []
    seen: set[int] = set()

    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue

        # Skip metadata markers
        if line.startswith("_(") or line.startswith("해당 문서"):
            continue

        # Strip leading "- " markdown list prefix
        if line.startswith("- "):
            line = line[2:].strip()

        # Match circled digit at start
        for circle, num in _CIRCLE_MAP.items():
            if line.startswith(circle):
                text = line[len(circle):].strip()
                if num not in seen:
                    choices.append(Choice(number=num, text=text))
                    seen.add(num)
                break
        else:
            # Bare digit at start (e.g. "2 frustrated → bored")
            m = re.match(r"^(\d)\s+(.*)", line)
            if m:
                num = int(m.group(1))
                text = m.group(2).strip()
                if num not in seen and 1 <= num <= 10:
                    choices.append(Choice(number=num, text=text))
                    seen.add(num)

    choices.sort(key=lambda c: c.number)
    return choices


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def _parse_question_block(raw: str) -> AnswerEntry | None:
    """Parse a single question block (everything between two question headers).

    Returns None if the block doesn't look like a valid question.
    """
    # Extract question number from first line  (e.g. "문제 18", "### 문제 23")
    header_match = re.search(r"문제\s+(\d+)", raw)
    if not header_match:
        return None
    number = int(header_match.group(1))

    # ---- question text ----
    # Supports: `문제:`, `**문제:**`, with optional leading "N. "
    qt_match = re.search(
        r"(?:\*\*문제:\*\*|문제:)\s*(.+?)(?:\n|$)", raw
    )
    question_text = normalize_text(qt_match.group(1)) if qt_match else ""

    # ---- passage ----
    # Between `지문:` / `**지문:**` and the next `답:` / `**답:**`
    passage_match = re.search(
        r"(?:\*\*지문:\*\*|지문:)\s*(.*?)(?=\*\*답:\*\*|답:|$)",
        raw,
        re.DOTALL,
    )
    passage: str | None = None
    if passage_match:
        raw_passage = passage_match.group(1)
        # Remove trailing "+N" lines (point markers)
        raw_passage = re.sub(r"\n?\+\d+\s*$", "", raw_passage, flags=re.MULTILINE)
        passage = normalize_text(raw_passage) or None

    # ---- points ----
    points = 2
    points_match = re.search(r"\+(\d+)", raw)
    if points_match:
        val = int(points_match.group(1))
        # +4 in the file seems to be a formatting artefact; treat 3 as 3점
        if val == 3:
            points = 3
        # "[3점]" in question_text is the canonical 3-point marker
    if "[3점]" in question_text:
        points = 3

    # ---- choices ----
    answer_match = re.search(
        r"(?:\*\*답:\*\*|답:)(.*?)$",
        raw,
        re.DOTALL,
    )
    choices: list[Choice] = []
    if answer_match:
        choices = _parse_choices(answer_match.group(1))

    return AnswerEntry(
        number=number,
        question_text=question_text,
        passage=passage,
        choices=choices,
        points=points,
    )


def parse_answer_md(filepath: str) -> AnswerKey:
    """Parse answer.md into an AnswerKey.

    The file mixes two styles:
    - Legacy (Q18-22):  `문제 N` / `문제:` / `지문:` / `답:`
    - Markdown (Q23+):  `### 문제 N` / `**문제:**` / `**지문:**` / `**답:**`

    Grouped questions ([41~42], [43~45]) have a shared `**지문:**` block
    followed by sub-question blocks like `**문제 41:** ...` / `**답:** ...`.
    """
    text = Path(filepath).read_text(encoding="utf-8")
    entries: dict[int, AnswerEntry] = {}

    # -----------------------------------------------------------------------
    # Pass 1: extract grouped-question sections first and remove them.
    # A grouped section starts with `### [N~M]` and ends before the next `###`
    # or EOF.  Within it, sub-questions are introduced by `**문제 NN:**`.
    # -----------------------------------------------------------------------
    group_section_re = re.compile(
        r"###\s*\[(\d+)[~～](\d+)\](.*?)(?=\n###\s|\Z)",
        re.DOTALL,
    )
    for gmatch in group_section_re.finditer(text):
        group_text = gmatch.group(3)

        # Shared passage: between **지문:** and the first **문제 NN:**
        shared_passage: str | None = None
        gp_match = re.search(
            r"(?:\*\*지문:\*\*|지문:)\s*(.*?)(?=\*\*문제\s+\d+|\Z)",
            group_text,
            re.DOTALL,
        )
        if gp_match:
            shared_passage = normalize_text(gp_match.group(1)) or None

        # Split on sub-question headers **문제 NN:**
        sub_split_re = re.compile(r"(?=\*\*문제\s+\d+[:\*])")
        sub_parts = sub_split_re.split(group_text)
        for part in sub_parts:
            part = part.strip()
            if not part:
                continue
            entry = _parse_sub_question(part, shared_passage)
            if entry:
                entries[entry.number] = entry

    # Remove grouped sections so they don't interfere with Pass 2
    remaining = group_section_re.sub("", text)

    # -----------------------------------------------------------------------
    # Pass 2: parse regular (non-grouped) questions.
    # Split on top-level question headers: `문제 N` or `### 문제 N`
    # -----------------------------------------------------------------------
    split_re = re.compile(r"(?=(?:^|\n)(?:#{1,3}\s*)?문제\s+\d+(?!\s*[:\*]))")
    for block in split_re.split(remaining):
        block = block.strip()
        if not block:
            continue
        entry = _parse_question_block(block)
        if entry and entry.number not in entries:
            entries[entry.number] = entry

    return AnswerKey(entries=sorted(entries.values(), key=lambda e: e.number))


def _parse_sub_question(raw: str, shared_passage: str | None) -> AnswerEntry | None:
    """Parse a sub-question block like **문제 41:** ... **답:** ..."""
    num_match = re.search(r"\*\*문제\s+(\d+)", raw)
    if not num_match:
        return None
    number = int(num_match.group(1))

    # Question text: the line with the question number
    qt_match = re.search(r"\*\*문제\s+\d+[:\*]\*\*\s*(.+?)(?:\n|$)", raw)
    question_text = normalize_text(qt_match.group(1)) if qt_match else ""

    # Choices from **답:** section
    answer_match = re.search(r"(?:\*\*답:\*\*|답:)(.*?)$", raw, re.DOTALL)
    choices: list[Choice] = []
    if answer_match:
        choices = _parse_choices(answer_match.group(1))

    points = 3 if "[3점]" in question_text else 2

    return AnswerEntry(
        number=number,
        question_text=question_text,
        passage=shared_passage,
        choices=choices,
        points=points,
    )


# ---------------------------------------------------------------------------
# Scoring / evaluation
# ---------------------------------------------------------------------------


def similarity(a: str, b: str) -> float:
    """Return SequenceMatcher ratio between two strings (0.0-1.0)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _choice_accuracy(pred_choices: list[Choice], gt_choices: list[Choice]) -> tuple[int, int]:
    """Return (correctly_matched, total_gt_choices).

    A choice is 'correct' if the extracted choice with the same number has
    text similarity >= 0.5 with the ground truth text.
    """
    if not gt_choices:
        return 0, 0

    gt_map = {c.number: c.text for c in gt_choices}
    pred_map = {c.number: c.text for c in pred_choices}

    correct = 0
    for num, gt_text in gt_map.items():
        pred_text = pred_map.get(num, "")
        if similarity(pred_text, gt_text) >= 0.5:
            correct += 1

    return correct, len(gt_choices)


def evaluate(parsed_exam: ParsedExam, answer_key: AnswerKey, model_name: str = "") -> EvalResult:
    """Score a ParsedExam against an AnswerKey.

    Weights:
      - Coverage (found questions / expected): 30%
      - Passage similarity:                    30%
      - Choice accuracy:                       25%
      - Question text similarity:              15%
    """
    gt_by_number = {e.number: e for e in answer_key.entries}
    pred_by_number = {q.number: q for q in parsed_exam.questions}

    per_question: list[QuestionEval] = []

    passage_sims: list[float] = []
    choice_accs: list[float] = []
    qt_sims: list[float] = []

    for number, gt in sorted(gt_by_number.items()):
        pred = pred_by_number.get(number)
        found = pred is not None

        if not found:
            qe = QuestionEval(
                number=number,
                found=False,
                passagesimilarity=0.0,
                choices_correct=0,
                choices_total=len(gt.choices),
                question_textsimilarity=0.0,
            )
            per_question.append(qe)
            passage_sims.append(0.0)
            choice_accs.append(0.0)
            qt_sims.append(0.0)
            continue

        # Passage similarity
        p_sim = similarity(pred.passage or "", gt.passage or "")

        # Choice accuracy
        correct, total = _choice_accuracy(pred.choices, gt.choices)
        c_acc = correct / total if total > 0 else 1.0  # no choices → full credit

        # Question text similarity
        qt_sim = similarity(pred.question_text, gt.question_text)

        per_question.append(
            QuestionEval(
                number=number,
                found=True,
                passagesimilarity=p_sim,
                choices_correct=correct,
                choices_total=total,
                question_textsimilarity=qt_sim,
            )
        )

        passage_sims.append(p_sim)
        choice_accs.append(c_acc)
        qt_sims.append(qt_sim)

    total_expected = len(gt_by_number)
    total_found = sum(1 for qe in per_question if qe.found)
    coverage = total_found / total_expected if total_expected > 0 else 0.0

    avg_passage = sum(passage_sims) / len(passage_sims) if passage_sims else 0.0
    avg_choice = sum(choice_accs) / len(choice_accs) if choice_accs else 0.0
    avg_qt = sum(qt_sims) / len(qt_sims) if qt_sims else 0.0

    overall = (
        0.30 * coverage
        + 0.30 * avg_passage
        + 0.25 * avg_choice
        + 0.15 * avg_qt
    )

    return EvalResult(
        model_name=model_name or (parsed_exam.exam_info.title if parsed_exam.exam_info else "unknown"),
        total_questions_expected=total_expected,
        total_questions_found=total_found,
        coverage_pct=round(coverage * 100, 2),
        avg_passagesimilarity=round(avg_passage, 4),
        avg_choice_accuracy=round(avg_choice, 4),
        avg_question_textsimilarity=round(avg_qt, 4),
        overall_score=round(overall, 4),
        per_question=per_question,
    )
