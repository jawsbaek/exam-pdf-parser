#!/usr/bin/env python3
"""
validate.py - Exam PDF Parser Output Validator

Compares parsed exam JSON output against ground truth for questions 19-22.
Also checks overall exam structure properties.

Usage:
    python scripts/validate.py output/gpt-5.2.json
    python scripts/validate.py output/gemini-3.1-pro.json --verbose
    python scripts/validate.py --compare output/gpt-5.2.json output/gemini-3.1-pro.json
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from src.evaluator import normalize_text, similarity

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("[WARNING] 'rich' not installed. Output will be plain text. Install with: pip install rich")

# ---------------------------------------------------------------------------
# GROUND TRUTH DATA
# ---------------------------------------------------------------------------
# Source: 2025년 9월 고3 영어 모의고사 (RTF answer key)
GROUND_TRUTH = {
    19: {
        "question_number": 19,
        "question_type": "심경변화",
        "points": 2,
        "question_text": "다음 글에 드러난 Sierra의 심경 변화로 가장 적절한 것은?",
        "question_text_key_phrases": ["Sierra", "심경 변화"],
        "passage": (
            "Sierra shook as she walked back and forth in front of her professor's office. "
            "The week before, she had turned in her art assignment and today, Professor Fox had asked Sierra to come see her. "
            "\"Oh, no.\" Sierra thought, \"What if she thinks my paintings are horrible?\" "
            "Sierra's sweating hand turned the door handle. "
            "Professor Fox smiled and said, \"Sierra, your paintings were amazing and so unique! Can I display them at the school exhibition?\" "
            "Sierra smiled brightly as she exclaimed, \"Oh, this is so wonderful! "
            "It's always been a dream of mine to share my art with others! This is the best day ever!\""
        ),
        "passage_key_phrases": ["Sierra shook", "professor's office", "school exhibition", "best day ever"],
        "passage_similarity_threshold": 0.85,
        "choices": [
            {"number": 1, "text": "angry → calm"},
            {"number": 2, "text": "frustrated → bored"},
            {"number": 3, "text": "nervous → delighted"},
            {"number": 4, "text": "relieved → surprised"},
            {"number": 5, "text": "thrilled → panicked"},
        ],
        "choice_similarity_threshold": 0.80,
    },
    20: {
        "question_number": 20,
        "question_type": "주장",
        "points": 2,
        "question_text": "다음 글에서 필자가 주장하는 바로 가장 적절한 것은?",
        "question_text_key_phrases": ["필자", "주장"],
        "passage": (
            "Showing up late for work and using abusive language are the kinds of problems that every business wants to eliminate. "
            "Business leaders looking to achieve this often focus on finding \"bad apples\" who break their rules and then punishing them. "
            "This assumes that the bad apples are acting badly on purpose. "
            "In fact, one common reason that employees give for breaking rules is that they were unaware their behavior was undesirable. "
            "There are some actors who knowingly act against policy, but many problems are unintentional failings. "
            "If businesses want better employees, those businesses must create clear standards and educate their employees directly about how to follow them. "
            "Without these standards there would be no way to distinguish bad apples from merely uninformed apples."
        ),
        "passage_key_phrases": ["bad apples", "unintentional failings", "clear standards", "uninformed apples"],
        "passage_similarity_threshold": 0.85,
        "choices": [
            # choices[0] must contain "생산성 향상" (NOT "혁신성 향상")
            {"number": 1, "text_must_contain": "생산성 향상", "text_must_not_contain": "혁신성 향상"},
            # choices[1] exact key phrase check
            {"number": 2, "text_must_contain": "기업은 행동", "text_must_contain2": "명확한 규정"},
            {"number": 3, "text_must_contain": "비윤리적"},
            {"number": 4, "text_must_contain": "보상"},
            {"number": 5, "text_must_contain": "공정한 평가"},
        ],
        "choice_similarity_threshold": 0.70,
        # Reference texts for similarity scoring
        "choices_reference": [
            {"number": 1, "text": "생산성 향상을 위해 기업은 직원 윤리 교육을 주기적으로 시행해야 한다."},
            {"number": 2, "text": "기업은 행동수칙에 대한 명확한 규정을 마련하여 직원을 교육해야 한다."},
            {"number": 3, "text": "직원의 비윤리적 행위 예방을 위해 기업은 상벌 규정을 정비해야 한다."},
            {"number": 4, "text": "근무 성과에 따른 보상을 통해 기업은 우수 직원을 이탈하지 않게 한다."},
            {"number": 5, "text": "기업은 직원에 대한 공정한 평가를 위해 동료 평가를 실시해야 한다."},
        ],
    },
    21: {
        "question_number": 21,
        "question_type": "함의",
        "points": 3,
        "question_text": "밑줄 친 come back home again이 다음 글에서 의미하는 바로 가장 적절한 것은?",
        "question_text_key_phrases": ["come back home again", "의미하는 바"],
        "passage_starts_with": "Here is a fundamental quality of music",
        "passage_key_phrases": [
            "fundamental quality of music",
            "frequency",
            "octave",
            "circularity",
        ],
        "passage_similarity_threshold": 0.85,
        "choices_reference": [
            {"number": 1, "text": "identified tonal differences within the same octave"},
            {"number": 2, "text": "returned to the original note with an identical frequency"},
            {"number": 3, "text": "reached a note named the same but with a different pitch"},
            {"number": 4, "text": "restored musical sensitivity by adapting to various octaves"},
            {"number": 5, "text": "constructed frequency patterns from notes with the same name"},
        ],
        "choice_similarity_threshold": 0.75,
    },
    22: {
        "question_number": 22,
        "question_type": "요지",
        "points": 2,
        "question_text": "다음 글의 요지로 가장 적절한 것은?",
        "question_text_key_phrases": ["요지"],
        "passage_starts_with": "One reason that people participate in social media",
        "passage_key_phrases": [
            "social media",
            "social capital",
            "Nan Lin",
        ],
        "passage_similarity_threshold": 0.85,
        "choices_reference": [
            {"number": 1, "text": "소셜 미디어를 통한 관계망의 확장은 중요한 사회적 자본이 된다."},
            {"number": 2, "text": "사회적 규범과 가치를 공유하는 것이 인간관계 형성의 기반이다."},
            {"number": 3, "text": "뉴 미디어의 등장은 사회적 자본 형성의 방식을 변화시킨다."},
            {"number": 4, "text": "다양한 인적 자본 구축은 소셜 미디어 활동에 필수적이다."},
            {"number": 5, "text": "사회적 경험은 인격 함양과 세계관 확장에 도움이 된다."},
        ],
        "choice_constraints": {
            # choices[0] (choice #1): must contain "관계망"
            1: {"must_contain": "관계망"},
            # choices[3] (choice #4): must contain "활동" NOT "활용"
            4: {"must_contain": "활동", "must_not_contain": "활용"},
        },
        "choice_similarity_threshold": 0.75,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_questions(data: dict) -> dict:
    """Extract questions dict keyed by question number."""
    questions_list = data.get("parsed_exam", {}).get("questions", [])
    return {q["number"]: q for q in questions_list if "number" in q}


def extract_exam_info(data: dict) -> dict:
    return data.get("parsed_exam", {}).get("exam_info", {})


# ---------------------------------------------------------------------------
# Field Checkers
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    field: str
    passed: bool
    score: float  # 0.0 - 1.0
    detail: str


def check_question_text(q: dict, gt: dict) -> FieldResult:
    actual = normalize_text(q.get("question_text", ""))
    expected = normalize_text(gt["question_text"])
    sim = similarity(actual, expected)
    # Check key phrases
    phrases = gt.get("question_text_key_phrases", [])
    missing = [p for p in phrases if p not in actual]
    passed = sim >= 0.80 and not missing
    detail = f"similarity={sim:.3f}"
    if missing:
        detail += f" | missing phrases: {missing}"
    return FieldResult("question_text", passed, sim, detail)


def check_passage(q: dict, gt: dict) -> FieldResult:
    actual = normalize_text(q.get("passage") or "")
    threshold = gt.get("passage_similarity_threshold", 0.85)

    # Check starts_with constraint
    starts_with = gt.get("passage_starts_with")
    if starts_with and not actual.startswith(starts_with[:30]):
        # Loose check: first 30 chars
        starts_ok = starts_with[:20].lower() in actual.lower()
    else:
        starts_ok = True

    # Check key phrases
    key_phrases = gt.get("passage_key_phrases", [])
    missing_phrases = [p for p in key_phrases if p.lower() not in actual.lower()]

    # Similarity against reference passage if available
    ref_passage = gt.get("passage", "")
    if ref_passage:
        ref_normalized = normalize_text(ref_passage)
        sim = similarity(actual, ref_normalized)
    else:
        # No reference passage; rely on key phrases only
        sim = 1.0 - (len(missing_phrases) / max(len(key_phrases), 1))

    passed = sim >= threshold and starts_ok and not missing_phrases
    detail = f"similarity={sim:.3f}"
    if not starts_ok:
        detail += f" | passage start mismatch (expected: '{starts_with[:40]}...')"
    if missing_phrases:
        detail += f" | missing key phrases: {missing_phrases}"
    return FieldResult("passage", passed, sim, detail)


def check_choices(q: dict, gt: dict, verbose: bool = False) -> list:
    """Returns list of FieldResult, one per choice."""
    actual_choices = q.get("choices", [])
    results = []

    # Build actual lookup by number
    actual_by_num = {c["number"]: c for c in actual_choices}

    # Count check
    expected_count = 5
    actual_count = len(actual_choices)
    count_passed = actual_count == expected_count
    results.append(FieldResult(
        "choices_count",
        count_passed,
        1.0 if count_passed else 0.0,
        f"actual={actual_count}, expected={expected_count}"
    ))

    # Use choices_reference if available, else choices
    ref_choices = gt.get("choices_reference", gt.get("choices", []))
    threshold = gt.get("choice_similarity_threshold", 0.75)
    constraints = gt.get("choice_constraints", {})

    for ref_c in ref_choices:
        num = ref_c["number"]
        ref_text = normalize_text(ref_c["text"])
        actual_c = actual_by_num.get(num)

        if actual_c is None:
            results.append(FieldResult(
                f"choice_{num}",
                False,
                0.0,
                f"choice #{num} missing from output"
            ))
            continue

        actual_text = normalize_text(actual_c.get("text", ""))
        sim = similarity(actual_text, ref_text)

        issues = []

        # Constraint checks from choices_reference list (for Q20)
        gt_choice = None
        if "choices" in gt:
            gt_choices_by_num = {c["number"]: c for c in gt.get("choices", [])}
            gt_choice = gt_choices_by_num.get(num)

        if gt_choice:
            must_contain = gt_choice.get("text_must_contain")
            must_not_contain = gt_choice.get("text_must_not_contain")
            must_contain2 = gt_choice.get("text_must_contain2")
            if must_contain and must_contain not in actual_text:
                issues.append(f"must contain '{must_contain}'")
            if must_not_contain and must_not_contain in actual_text:
                issues.append(f"must NOT contain '{must_not_contain}' (found it)")
            if must_contain2 and must_contain2 not in actual_text:
                issues.append(f"must contain '{must_contain2}'")

        # choice_constraints (for Q22)
        if num in constraints:
            c_must = constraints[num].get("must_contain")
            c_must_not = constraints[num].get("must_not_contain")
            if c_must and c_must not in actual_text:
                issues.append(f"must contain '{c_must}'")
            if c_must_not and c_must_not in actual_text:
                issues.append(f"must NOT contain '{c_must_not}' (found it)")

        passed = sim >= threshold and not issues
        detail = f"similarity={sim:.3f}"
        if verbose:
            detail += f" | actual='{actual_text[:60]}'"
        if issues:
            detail += f" | constraints failed: {issues}"

        results.append(FieldResult(f"choice_{num}", passed, sim, detail))

    return results


def check_points(q: dict, gt: dict) -> FieldResult:
    actual = q.get("points")
    expected = gt["points"]
    passed = actual == expected
    return FieldResult(
        "points",
        passed,
        1.0 if passed else 0.0,
        f"actual={actual}, expected={expected}"
    )


def check_question_type(q: dict, gt: dict) -> FieldResult:
    actual = q.get("question_type")
    passed = actual is not None and actual != ""
    # Also check it's somewhat reasonable
    expected_type = gt.get("question_type", "")
    sim = similarity(normalize_text(actual or ""), normalize_text(expected_type))
    detail = f"actual='{actual}', expected='{expected_type}', similarity={sim:.2f}"
    # Partial credit: not null is the minimum
    return FieldResult("question_type", passed, sim if passed else 0.0, detail)


# ---------------------------------------------------------------------------
# Question Validator
# ---------------------------------------------------------------------------

class QuestionValidationResult:
    def __init__(self, qnum: int):
        self.qnum = qnum
        self.field_results: list[FieldResult] = []
        self.found = True

    @property
    def passed(self) -> bool:
        return self.found and all(r.passed for r in self.field_results)

    @property
    def score(self) -> float:
        if not self.found:
            return 0.0
        if not self.field_results:
            return 1.0
        return sum(r.score for r in self.field_results) / len(self.field_results)

    @property
    def pass_rate(self) -> float:
        if not self.found or not self.field_results:
            return 0.0
        return sum(1 for r in self.field_results if r.passed) / len(self.field_results)


def validate_question(q: dict, gt: dict, verbose: bool = False) -> QuestionValidationResult:
    result = QuestionValidationResult(gt["question_number"])

    result.field_results.append(check_question_text(q, gt))
    result.field_results.append(check_passage(q, gt))
    result.field_results.extend(check_choices(q, gt, verbose=verbose))
    result.field_results.append(check_points(q, gt))
    result.field_results.append(check_question_type(q, gt))

    return result


# ---------------------------------------------------------------------------
# Structural Checks
# ---------------------------------------------------------------------------

class StructureResult:
    def __init__(self):
        self.checks: list[FieldResult] = []

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_rate(self) -> float:
        if not self.checks:
            return 1.0
        return sum(1 for c in self.checks if c.passed) / len(self.checks)


def check_structure(data: dict) -> StructureResult:
    result = StructureResult()
    questions = data.get("parsed_exam", {}).get("questions", [])
    qmap = {q["number"]: q for q in questions if "number" in q}

    # Total question count
    total = len(questions)
    result.checks.append(FieldResult(
        "total_questions",
        total == 45,
        1.0 if total == 45 else max(0.0, 1.0 - abs(total - 45) / 45),
        f"actual={total}, expected=45"
    ))

    # Q1-17: listening (passage null or empty)
    listening_ok = 0
    listening_total = 0
    for n in range(1, 18):
        q = qmap.get(n)
        if q is None:
            continue
        listening_total += 1
        passage = q.get("passage")
        if passage is None or passage == "" or passage == []:
            listening_ok += 1

    result.checks.append(FieldResult(
        "listening_q1_17_no_passage",
        listening_ok == listening_total and listening_total > 0,
        listening_ok / max(listening_total, 1),
        f"{listening_ok}/{listening_total} listening questions have null/empty passage"
    ))

    # Q18-45: reading (passage not null/empty)
    reading_ok = 0
    reading_total = 0
    for n in range(18, 46):
        q = qmap.get(n)
        if q is None:
            continue
        reading_total += 1
        passage = q.get("passage")
        if passage and passage != "":
            reading_ok += 1

    result.checks.append(FieldResult(
        "reading_q18_45_has_passage",
        reading_ok == reading_total and reading_total > 0,
        reading_ok / max(reading_total, 1),
        f"{reading_ok}/{reading_total} reading questions have non-empty passage"
    ))

    # 3-point questions: should exist and be correctly flagged
    three_pt = [q for q in questions if q.get("points") == 3]
    # Standard exam has several 3-point questions in reading section
    result.checks.append(FieldResult(
        "three_point_questions_exist",
        len(three_pt) > 0,
        1.0 if len(three_pt) > 0 else 0.0,
        f"found {len(three_pt)} questions marked as 3 points"
    ))

    # Q21 specifically should be 3 points
    q21 = qmap.get(21)
    if q21:
        q21_3pt = q21.get("points") == 3
        result.checks.append(FieldResult(
            "q21_is_3_points",
            q21_3pt,
            1.0 if q21_3pt else 0.0,
            f"Q21 points={q21.get('points')}, expected=3"
        ))

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def make_status_str(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def report_single(
    path: str,
    data: dict,
    verbose: bool = False,
    console=None
):
    """Generate and print full validation report for one output file."""
    questions = extract_questions(data)
    exam_info = extract_exam_info(data)

    if console and HAS_RICH:
        console.print(Panel(
            f"[bold]Validating:[/bold] {path}\n"
            f"[bold]Model:[/bold] {data.get('model_name', 'unknown')}\n"
            f"[bold]Exam:[/bold] {exam_info.get('title', 'N/A')}",
            title="[bold cyan]Exam Validation Report[/bold cyan]",
            border_style="cyan"
        ))
    else:
        print(f"\n{'='*70}")
        print(f"Validating: {path}")
        print(f"Model: {data.get('model_name', 'unknown')}")
        print(f"Exam: {exam_info.get('title', 'N/A')}")
        print(f"{'='*70}\n")

    # --- Structural checks ---
    struct_result = check_structure(data)

    if console and HAS_RICH:
        struct_table = Table(
            title="[bold]Structural Checks[/bold]",
            box=box.SIMPLE_HEAVY,
            show_header=True,
        )
        struct_table.add_column("Check", style="cyan", no_wrap=True)
        struct_table.add_column("Status", justify="center", width=6)
        struct_table.add_column("Detail")

        for c in struct_result.checks:
            status_style = "green" if c.passed else "red"
            struct_table.add_row(
                c.field,
                Text(make_status_str(c.passed), style=status_style),
                c.detail,
            )
        console.print(struct_table)
        console.print(
            f"  Structure pass rate: [{'green' if struct_result.passed else 'red'}]"
            f"{struct_result.pass_rate*100:.1f}%[/]"
        )
    else:
        print("STRUCTURAL CHECKS")
        print("-" * 50)
        for c in struct_result.checks:
            print(f"  [{make_status_str(c.passed)}] {c.field}: {c.detail}")
        print(f"  Structure pass rate: {struct_result.pass_rate*100:.1f}%\n")

    # --- Per-question checks ---
    q_results: dict[int, QuestionValidationResult] = {}
    for qnum, gt in GROUND_TRUTH.items():
        q = questions.get(qnum)
        if q is None:
            r = QuestionValidationResult(qnum)
            r.found = False
            q_results[qnum] = r
            if console and HAS_RICH:
                console.print(f"[red]  Q{qnum}: NOT FOUND in output[/red]")
            else:
                print(f"  Q{qnum}: NOT FOUND in output")
        else:
            q_results[qnum] = validate_question(q, gt, verbose=verbose)

    # Print per-question tables
    for qnum, qr in q_results.items():
        if console and HAS_RICH:
            q_table = Table(
                title=f"[bold]Q{qnum} — {GROUND_TRUTH[qnum]['question_type']} ({GROUND_TRUTH[qnum]['points']}pt)[/bold]",
                box=box.SIMPLE,
                show_header=True,
            )
            q_table.add_column("Field", style="cyan", no_wrap=True)
            q_table.add_column("Status", justify="center", width=6)
            q_table.add_column("Score", justify="right", width=6)
            q_table.add_column("Detail")

            for fr in qr.field_results:
                status_style = "green" if fr.passed else "red"
                q_table.add_row(
                    fr.field,
                    Text(make_status_str(fr.passed), style=status_style),
                    f"{fr.score:.2f}",
                    fr.detail[:100],
                )
            console.print(q_table)
            console.print(
                f"  Q{qnum} overall: [{'green' if qr.passed else 'red'}]"
                f"{'PASS' if qr.passed else 'FAIL'}[/] "
                f"(field pass rate: {qr.pass_rate*100:.1f}%, avg score: {qr.score:.3f})"
            )
        else:
            print(f"\nQ{qnum} — {GROUND_TRUTH[qnum]['question_type']} ({GROUND_TRUTH[qnum]['points']}pt)")
            print("-" * 50)
            for fr in qr.field_results:
                print(f"  [{make_status_str(fr.passed)}] {fr.field} (score={fr.score:.2f}): {fr.detail}")
            print(f"  Q{qnum} overall: {make_status_str(qr.passed)} (pass rate={qr.pass_rate*100:.1f}%, avg score={qr.score:.3f})")

    # --- Summary ---
    all_q_passed = all(qr.passed for qr in q_results.values())
    all_struct_passed = struct_result.passed
    overall_passed = all_q_passed and all_struct_passed

    total_fields = sum(len(qr.field_results) for qr in q_results.values()) + len(struct_result.checks)
    passed_fields = (
        sum(sum(1 for fr in qr.field_results if fr.passed) for qr in q_results.values())
        + sum(1 for c in struct_result.checks if c.passed)
    )
    accuracy = passed_fields / total_fields * 100 if total_fields else 0.0

    if console and HAS_RICH:
        summary_color = "green" if overall_passed else "red"
        console.print(Panel(
            f"Questions 19-22: [{'green' if all_q_passed else 'red'}]{'ALL PASS' if all_q_passed else 'SOME FAIL'}[/]\n"
            f"Structural checks: [{'green' if all_struct_passed else 'red'}]{'ALL PASS' if all_struct_passed else 'SOME FAIL'}[/]\n"
            f"Fields passed: {passed_fields}/{total_fields}\n"
            f"[bold]Overall accuracy: [{summary_color}]{accuracy:.1f}%[/][/bold]\n"
            f"[bold]Result: [{summary_color}]{'PASS (100%)' if overall_passed else 'FAIL'}[/][/bold]",
            title="[bold]Summary[/bold]",
            border_style=summary_color
        ))
    else:
        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"  Questions 19-22: {'ALL PASS' if all_q_passed else 'SOME FAIL'}")
        print(f"  Structural checks: {'ALL PASS' if all_struct_passed else 'SOME FAIL'}")
        print(f"  Fields passed: {passed_fields}/{total_fields}")
        print(f"  Overall accuracy: {accuracy:.1f}%")
        print(f"  Result: {'PASS (100%)' if overall_passed else 'FAIL'}")
        print(f"{'='*70}\n")

    return overall_passed, accuracy


# ---------------------------------------------------------------------------
# Compare Mode
# ---------------------------------------------------------------------------

def report_compare(path_a: str, path_b: str, verbose: bool = False, console=None):
    """Compare two output files side by side."""
    data_a = load_json(path_a)
    data_b = load_json(path_b)
    qa = extract_questions(data_a)
    qb = extract_questions(data_b)

    name_a = data_a.get("model_name", Path(path_a).stem)
    name_b = data_b.get("model_name", Path(path_b).stem)

    if console and HAS_RICH:
        console.print(Panel(
            f"[bold]Comparing:[/bold]\n  A: {path_a} ({name_a})\n  B: {path_b} ({name_b})",
            title="[bold cyan]Side-by-Side Comparison[/bold cyan]",
            border_style="cyan"
        ))
    else:
        print(f"\n{'='*70}")
        print("COMPARING:")
        print(f"  A: {path_a} ({name_a})")
        print(f"  B: {path_b} ({name_b})")
        print(f"{'='*70}\n")

    for qnum, gt in GROUND_TRUTH.items():
        q_a = qa.get(qnum)
        q_b = qb.get(qnum)

        fields_to_compare = ["question_text", "passage", "points", "question_type"]

        if console and HAS_RICH:
            cmp_table = Table(
                title=f"[bold]Q{qnum} — {gt['question_type']}[/bold]",
                box=box.SIMPLE,
                show_header=True,
            )
            cmp_table.add_column("Field", style="cyan", no_wrap=True, width=16)
            cmp_table.add_column(f"A: {name_a[:20]}", width=35)
            cmp_table.add_column(f"B: {name_b[:20]}", width=35)
            cmp_table.add_column("Same?", justify="center", width=6)

            for field in fields_to_compare:
                val_a = normalize_text(str(q_a.get(field, "N/A") if q_a else "MISSING"))[:60]
                val_b = normalize_text(str(q_b.get(field, "N/A") if q_b else "MISSING"))[:60]
                same = val_a == val_b
                cmp_table.add_row(
                    field,
                    val_a,
                    val_b,
                    Text("YES" if same else "NO", style="green" if same else "red"),
                )

            # Choices
            choices_a = {c["number"]: c["text"] for c in (q_a.get("choices", []) if q_a else [])}
            choices_b = {c["number"]: c["text"] for c in (q_b.get("choices", []) if q_b else [])}
            for n in range(1, 6):
                ca = normalize_text(choices_a.get(n, "MISSING"))[:60]
                cb = normalize_text(choices_b.get(n, "MISSING"))[:60]
                sim = similarity(ca, cb)
                same = sim >= 0.90
                cmp_table.add_row(
                    f"choice_{n}",
                    ca,
                    cb,
                    Text(f"{sim:.2f}", style="green" if same else "yellow"),
                )

            console.print(cmp_table)
        else:
            print(f"\nQ{qnum} — {gt['question_type']}")
            print("-" * 70)
            for field in fields_to_compare:
                val_a = normalize_text(str(q_a.get(field, "N/A") if q_a else "MISSING"))[:60]
                val_b = normalize_text(str(q_b.get(field, "N/A") if q_b else "MISSING"))[:60]
                same = "YES" if val_a == val_b else "NO"
                print(f"  {field:<18} [{same}]")
                if verbose or val_a != val_b:
                    print(f"    A: {val_a}")
                    print(f"    B: {val_b}")

            choices_a = {c["number"]: c["text"] for c in (q_a.get("choices", []) if q_a else [])}
            choices_b = {c["number"]: c["text"] for c in (q_b.get("choices", []) if q_b else [])}
            for n in range(1, 6):
                ca = normalize_text(choices_a.get(n, "MISSING"))[:60]
                cb = normalize_text(choices_b.get(n, "MISSING"))[:60]
                sim = similarity(ca, cb)
                same = "YES" if sim >= 0.90 else f"sim={sim:.2f}"
                print(f"  choice_{n:<14} [{same}]")
                if verbose or sim < 0.90:
                    print(f"    A: {ca}")
                    print(f"    B: {cb}")

    # Also compare passage similarity between A and B for each question
    if console and HAS_RICH:
        pass_table = Table(
            title="[bold]Passage Similarity (A vs B)[/bold]",
            box=box.SIMPLE,
        )
        pass_table.add_column("Question", justify="center")
        pass_table.add_column("Similarity", justify="center")
        pass_table.add_column("Assessment")

        for qnum in GROUND_TRUTH:
            q_a = qa.get(qnum)
            q_b = qb.get(qnum)
            if q_a and q_b:
                pa = normalize_text(q_a.get("passage") or "")
                pb = normalize_text(q_b.get("passage") or "")
                sim = similarity(pa, pb)
                color = "green" if sim >= 0.95 else "yellow" if sim >= 0.80 else "red"
                pass_table.add_row(
                    f"Q{qnum}",
                    Text(f"{sim:.4f}", style=color),
                    "Near-identical" if sim >= 0.95 else "Similar" if sim >= 0.80 else "Divergent"
                )
        console.print(pass_table)
    else:
        print("\nPassage Similarity (A vs B):")
        for qnum in GROUND_TRUTH:
            q_a = qa.get(qnum)
            q_b = qb.get(qnum)
            if q_a and q_b:
                pa = normalize_text(q_a.get("passage") or "")
                pb = normalize_text(q_b.get("passage") or "")
                sim = similarity(pa, pb)
                print(f"  Q{qnum}: {sim:.4f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate parsed exam JSON against ground truth (Q19-22)."
    )
    parser.add_argument("files", nargs="+", help="JSON output file(s) to validate")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare two JSON files side by side (requires exactly 2 files)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show extra detail (actual text in choice comparisons, etc.)"
    )
    parser.add_argument(
        "--no-rich",
        action="store_true",
        help="Disable rich formatting even if installed"
    )
    args = parser.parse_args()

    use_rich = HAS_RICH and not args.no_rich
    console = Console() if use_rich else None

    if args.compare:
        if len(args.files) != 2:
            print("Error: --compare requires exactly 2 file arguments.", file=sys.stderr)
            sys.exit(2)
        report_compare(args.files[0], args.files[1], verbose=args.verbose, console=console)
        sys.exit(0)

    # Single or multiple file validation
    all_passed = True
    for path in args.files:
        try:
            data = load_json(path)
        except FileNotFoundError:
            print(f"Error: file not found: {path}", file=sys.stderr)
            all_passed = False
            continue
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
            all_passed = False
            continue

        passed, accuracy = report_single(path, data, verbose=args.verbose, console=console)
        if not passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
