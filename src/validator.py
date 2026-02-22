"""
Post-parse validation layer for exam parsing results.
파싱 결과의 구조적 완전성과 정확성을 검증합니다.
"""

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

        if q.points not in valid_points:
            issues.append(
                ValidationIssue(
                    level="warning",
                    question_number=q.number,
                    message=f"Question {q.number}: unusual point value {q.points} (expected {valid_points})",
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
