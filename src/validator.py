"""
Post-parse validation layer for exam parsing results.
파싱 결과의 구조적 완전성과 정확성을 검증합니다.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from .schema import AnswerKey, ParsedExam, QuestionType


class ValidationIssue(BaseModel):
    """Single validation issue found in parsed exam."""

    level: Literal["error", "warning"] = Field(description="'error' or 'warning'")
    question_number: int | None = None
    message: str


class ValidationResult(BaseModel):
    """Result of validating a parsed exam."""

    is_valid: bool
    total_errors: int = 0
    total_warnings: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)


# Question types that are written response (no choices expected)
_WRITTEN_TYPES = {
    QuestionType.WRITING,
    QuestionType.ERROR_CORRECTION,
    QuestionType.REARRANGE,
    QuestionType.REWRITE,
}

# Question types that typically require a passage
_PASSAGE_TYPES = {
    QuestionType.MAIN_IDEA,
    QuestionType.TITLE,
    QuestionType.MOOD_CHANGE,
    QuestionType.PURPOSE,
    QuestionType.CLAIM,
    QuestionType.IMPLICATION,
    QuestionType.BLANK_FILL,
    QuestionType.ORDER,
    QuestionType.INSERT,
    QuestionType.SUMMARY,
    QuestionType.IRRELEVANT,
    QuestionType.REFERENCE,
    QuestionType.CONTENT_MATCH,
    QuestionType.LONG_PASSAGE,
}

# group_range 형식 패턴: "N~M" (전각 물결표 포함) / Group range format regex
_GROUP_RANGE_RE = re.compile(r"^\d+[~～]\d+$")


def validate_exam(
    parsed_exam: ParsedExam,
    answer_key: AnswerKey | None = None,
    expected_questions: int | None = None,
    valid_points: tuple[int, ...] = (2, 3),
    listening_max: int = 17,
) -> ValidationResult:
    """
    Validate a parsed exam for structural completeness and accuracy.

    Args:
        parsed_exam: The parsed exam to validate
        answer_key: Optional ground truth for cross-reference
        expected_questions: Expected number of questions (overrides exam_info)

    Returns:
        ValidationResult with all issues found
    """
    issues: list[ValidationIssue] = []

    _validate_schema_completeness(parsed_exam, issues, valid_points=valid_points)
    _validate_numbering_continuity(parsed_exam, issues, expected_questions)
    _validate_choices(parsed_exam, issues, listening_max=listening_max)
    _validate_passages(parsed_exam, issues)
    _validate_listening_questions(parsed_exam, issues, listening_max=listening_max)
    _validate_group_questions(parsed_exam, issues)
    _validate_content_quality(parsed_exam, issues)

    if answer_key:
        _validate_against_answer_key(parsed_exam, answer_key, issues)

    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")

    return ValidationResult(
        is_valid=errors == 0,
        total_errors=errors,
        total_warnings=warnings,
        issues=issues,
    )


def _validate_schema_completeness(
    parsed_exam: ParsedExam, issues: list[ValidationIssue], valid_points: tuple[int, ...] = (2, 3)
):
    """Check that all questions have required fields."""
    if not parsed_exam.exam_info.title:
        issues.append(ValidationIssue(level="warning", message="Exam title is empty"))

    if not parsed_exam.exam_info.subject:
        issues.append(ValidationIssue(level="warning", message="Exam subject is empty"))

    if not parsed_exam.questions:
        issues.append(ValidationIssue(level="error", message="No questions found in parsed exam"))
        return

    for q in parsed_exam.questions:
        if not q.question_text or not q.question_text.strip():
            issues.append(
                ValidationIssue(
                    level="error",
                    question_number=q.number,
                    message=f"Question {q.number}: missing question_text",
                )
            )

        # 배점 범위 검사: 1 미만 또는 5 초과이면 오류 / Points out of plausible range → error
        if q.points < 1 or q.points > 5:
            issues.append(
                ValidationIssue(
                    level="error",
                    question_number=q.number,
                    message=f"Question {q.number}: invalid point value {q.points} (must be 1–5)",
                )
            )
        elif q.points not in valid_points:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: unusual point value {q.points} (expected {valid_points})",
                )
            )

        # 문제 유형 누락 경고 / Warn if question_type is not set
        if q.question_type is None:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: question_type is not set",
                )
            )

        # 세부 문항 유효성 검사 / Validate sub_questions entries if present
        if q.sub_questions is not None:
            for idx, sub in enumerate(q.sub_questions):
                if not sub or not sub.strip():
                    issues.append(
                        ValidationIssue(
                            level="warning",
                            question_number=q.number,
                            message=f"Question {q.number}: sub_questions[{idx}] is empty",
                        )
                    )


def _validate_numbering_continuity(
    parsed_exam: ParsedExam,
    issues: list[ValidationIssue],
    expected_questions: int | None = None,
):
    """Check question numbering is continuous without gaps or duplicates."""
    if not parsed_exam.questions:
        return

    numbers = [q.number for q in parsed_exam.questions]

    # Check for duplicates
    seen = set()
    for n in numbers:
        if n in seen:
            issues.append(
                ValidationIssue(
                    level="error",
                    question_number=n,
                    message=f"Duplicate question number: {n}",
                )
            )
        seen.add(n)

    # Check continuity
    sorted_nums = sorted(seen)
    if sorted_nums:
        expected_start = sorted_nums[0]
        expected_end = sorted_nums[-1]
        expected_set = set(range(expected_start, expected_end + 1))
        missing = expected_set - seen
        if missing:
            missing_str = ", ".join(str(n) for n in sorted(missing))
            issues.append(
                ValidationIssue(
                    level="error",
                    message=f"Missing question numbers: {missing_str}",
                )
            )

    # Check against expected total
    total = expected_questions or parsed_exam.exam_info.total_questions
    if total and len(seen) != total:
        issues.append(
            ValidationIssue(
                level="warning",
                message=f"Expected {total} questions, found {len(seen)}",
            )
        )


def _validate_choices(parsed_exam: ParsedExam, issues: list[ValidationIssue], listening_max: int = 17):
    """Validate choice counts for multiple choice questions."""
    for q in parsed_exam.questions:
        # Skip listening questions (1-17) and non-MCQ types
        if q.question_type == QuestionType.LISTENING:
            continue

        if q.choices:
            num_choices = len(q.choices)
            if num_choices != 5:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        question_number=q.number,
                        message=f"Question {q.number}: has {num_choices} choices (expected 5 for MCQ)",
                    )
                )

            # Verify choice numbering (should be 1-5)
            choice_numbers = [c.number for c in q.choices]
            expected_choice_nums = list(range(1, num_choices + 1))
            if sorted(choice_numbers) != expected_choice_nums:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        question_number=q.number,
                        message=f"Question {q.number}: choice numbering mismatch {choice_numbers}",
                    )
                )

            # Check for empty choice text
            for c in q.choices:
                if not c.text or not c.text.strip():
                    issues.append(
                        ValidationIssue(
                            level="error",
                            question_number=q.number,
                            message=f"Question {q.number}, choice {c.number}: empty choice text",
                        )
                    )
        elif q.number > listening_max and q.question_type not in _WRITTEN_TYPES:
            # Non-listening questions should generally have choices (skip written response types)
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: no choices found (expected for non-listening question)",
                )
            )


def _validate_passages(parsed_exam: ParsedExam, issues: list[ValidationIssue]):
    """Validate passage presence for question types that require them."""
    for q in parsed_exam.questions:
        if q.question_type in _PASSAGE_TYPES and not q.passage:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number} ({q.question_type.value}): missing passage",
                )
            )


def _validate_listening_questions(
    parsed_exam: ParsedExam,
    issues: list[ValidationIssue],
    listening_max: int = 17,
):
    """
    듣기 문제 유효성 검사 / Validate listening question structure.

    - LISTENING 유형 문제는 선택지가 있어야 함
    - LISTENING 유형 문제는 지문이 없어야 함 (있으면 경고)
    - 수능 영어 기준 1~listening_max 번은 LISTENING 유형이어야 함
    """
    q_by_number = {q.number: q for q in parsed_exam.questions}

    for q in parsed_exam.questions:
        if q.question_type == QuestionType.LISTENING:
            # 듣기 문제는 선택지가 있어야 함 / Listening questions should have choices
            if not q.choices:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        question_number=q.number,
                        message=f"Question {q.number} (LISTENING): no choices found",
                    )
                )

            # 듣기 문제는 지문이 없어야 함 / Listening questions should not have a passage
            if q.passage:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        question_number=q.number,
                        message=f"Question {q.number} (LISTENING): unexpected passage present",
                    )
                )

    # 수능 영어 기준: 1~listening_max 번은 LISTENING 유형이어야 함
    # CSAT English: questions 1 to listening_max should be type LISTENING
    for num in range(1, listening_max + 1):
        q = q_by_number.get(num)
        if q is not None and q.question_type != QuestionType.LISTENING:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=num,
                    message=(
                        f"Question {num}: expected LISTENING type for CSAT English "
                        f"(1~{listening_max}), got {q.question_type}"
                    ),
                )
            )


def _validate_group_questions(parsed_exam: ParsedExam, issues: list[ValidationIssue]):
    """
    묶음 문제 유효성 검사 / Validate grouped question consistency.

    - group_range 형식은 "N~M" 이어야 함
    - group_range에 명시된 번호가 모두 존재해야 함
    - 그룹의 첫 번째 문제에 지문이 있어야 함
    """
    groups: dict[str, list] = {}

    for q in parsed_exam.questions:
        if q.group_range is None:
            continue

        # group_range 형식 검사 / Validate group_range format
        if not _GROUP_RANGE_RE.match(q.group_range):
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: invalid group_range format '{q.group_range}' (expected 'N~M')",
                )
            )

        if q.group_range not in groups:
            groups[q.group_range] = []
        groups[q.group_range].append(q)

    for group_range, group_qs in groups.items():
        # 그룹 내 문제를 번호 순으로 정렬 / Sort questions by number
        group_qs_sorted = sorted(group_qs, key=lambda x: x.number)

        # group_range에서 예상 번호 범위 파싱 / Parse expected range from group_range
        range_match = re.match(r"(\d+)[~～](\d+)", group_range)
        if range_match:
            expected_start = int(range_match.group(1))
            expected_end = int(range_match.group(2))
            actual_numbers = {q.number for q in group_qs}
            missing_in_group = set(range(expected_start, expected_end + 1)) - actual_numbers
            if missing_in_group:
                missing_str = ", ".join(str(n) for n in sorted(missing_in_group))
                issues.append(
                    ValidationIssue(
                        level="warning",
                        message=f"Group [{group_range}]: missing question numbers {missing_str}",
                    )
                )

        # 첫 번째 문제에 지문이 있어야 함 / First question in group should have the passage
        first_q = group_qs_sorted[0]
        if not first_q.passage:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=first_q.number,
                    message=f"Question {first_q.number}: first question in group [{group_range}] has no passage",
                )
            )


def _validate_content_quality(parsed_exam: ParsedExam, issues: list[ValidationIssue]):
    """
    콘텐츠 품질 검사 / Content-level quality checks.

    - 너무 짧은 지문 경고 (< 20자)
    - 문제 간 중복 question_text 감지
    - 동일 문제 내 중복 선택지 텍스트 감지
    - has_image=true / has_table=true인데 image_description=null 경고
    """
    # 중복 question_text 감지 / Detect duplicate question_text across questions
    text_seen: dict[str, int] = {}  # normalized text → first question number
    for q in parsed_exam.questions:
        if q.question_text and q.question_text.strip():
            normalized = q.question_text.strip()
            if normalized in text_seen:
                issues.append(
                    ValidationIssue(
                        level="warning",
                        question_number=q.number,
                        message=(
                            f"Question {q.number}: question_text is identical to "
                            f"question {text_seen[normalized]}"
                        ),
                    )
                )
            else:
                text_seen[normalized] = q.number

    for q in parsed_exam.questions:
        # 너무 짧은 지문 경고 / Warn on suspiciously short passages
        if q.passage and len(q.passage.strip()) < 20:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: passage is suspiciously short ({len(q.passage.strip())} chars)",
                )
            )

        # 동일 문제 내 중복 선택지 텍스트 감지 / Detect duplicate choice texts within same question
        if q.choices:
            choice_texts_seen: dict[str, int] = {}  # text → choice number
            for c in q.choices:
                if c.text and c.text.strip():
                    normalized_choice = c.text.strip()
                    if normalized_choice in choice_texts_seen:
                        issues.append(
                            ValidationIssue(
                                level="warning",
                                question_number=q.number,
                                message=(
                                    f"Question {q.number}: choice {c.number} text is identical to "
                                    f"choice {choice_texts_seen[normalized_choice]}"
                                ),
                            )
                        )
                    else:
                        choice_texts_seen[normalized_choice] = c.number

        # has_image=true인데 image_description=null 경고
        # Warn if has_image is True but image_description is missing
        if q.has_image and not q.image_description:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: has_image=True but image_description is missing",
                )
            )

        # has_table=true인데 image_description=null 경고
        # Warn if has_table is True but image_description is missing
        if q.has_table and not q.image_description:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: has_table=True but image_description is missing",
                )
            )


def _validate_against_answer_key(
    parsed_exam: ParsedExam,
    answer_key: AnswerKey,
    issues: list[ValidationIssue],
):
    """Cross-reference parsed exam with answer key."""
    pred_by_number = {q.number: q for q in parsed_exam.questions}
    gt_by_number = {e.number: e for e in answer_key.entries}

    # Check for questions in answer key but missing from parsed exam
    for number in sorted(gt_by_number.keys()):
        if number not in pred_by_number:
            issues.append(
                ValidationIssue(
                    level="error",
                    question_number=number,
                    message=f"Question {number}: present in answer key but missing from parsed exam",
                )
            )

    # Check choice count matches
    for number, gt in gt_by_number.items():
        pred = pred_by_number.get(number)
        if pred and gt.choices and pred.choices:
            if len(pred.choices) != len(gt.choices):
                issues.append(
                    ValidationIssue(
                        level="warning",
                        question_number=number,
                        message=(
                            f"Question {number}: choice count mismatch "
                            f"(parsed={len(pred.choices)}, expected={len(gt.choices)})"
                        ),
                    )
                )
