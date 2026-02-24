"""Test the question cropping pipeline with a real CSAT exam PDF."""

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from src.cropper import crop_and_explain

PDF_PATH = "test/2025년-9월-고3-모의고사-영어-문제.pdf"
OUTPUT_DIR = "output/cropped_test"
EXPECTED_QUESTIONS = 45
LISTENING_QUESTIONS = 17  # Q1-17 are listening (no crop explanation possible)


def main():
    print(f"=== 시험지 크롭 테스트 ===")
    print(f"PDF: {PDF_PATH}")
    print(f"Expected: {EXPECTED_QUESTIONS} questions (listening: 1-{LISTENING_QUESTIONS})")
    print()

    t0 = time.monotonic()
    result = crop_and_explain(
        pdf_path=PDF_PATH,
        output_dir=OUTPUT_DIR,
        dpi=300,
        add_explanations=False,  # Skip Gemini for now — just test cropping
    )
    elapsed = time.monotonic() - t0

    print(f"\n=== 결과 ===")
    print(f"Total questions detected: {result.total_questions}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Metrics: {result.crop_metrics}")
    print()

    # Check each question
    detected_nums = sorted(q.question_number for q in result.questions)
    expected_nums = list(range(1, EXPECTED_QUESTIONS + 1))
    missing = set(expected_nums) - set(detected_nums)
    extra = set(detected_nums) - set(expected_nums)

    print(f"Detected question numbers: {detected_nums}")
    print(f"Missing: {missing if missing else 'none'}")
    print(f"Extra: {extra if extra else 'none'}")
    print()

    # Print per-question details
    for q in sorted(result.questions, key=lambda x: x.question_number):
        listening = "🎧" if q.question_number <= LISTENING_QUESTIONS else "📝"
        print(f"  Q{q.question_number:2d} {listening} {q.width:4d}x{q.height:<4d} page={q.source_page} {q.image_path}")

    # Summary
    print(f"\n=== 요약 ===")
    print(f"검출률: {len(detected_nums)}/{EXPECTED_QUESTIONS} ({len(detected_nums)/EXPECTED_QUESTIONS*100:.0f}%)")
    if missing:
        print(f"누락 문제: {sorted(missing)}")
    if result.total_questions == EXPECTED_QUESTIONS:
        print("PASS: 45문제 전체 검출 성공!")
    else:
        print(f"PARTIAL: {result.total_questions}문제 검출 ({EXPECTED_QUESTIONS - result.total_questions}개 누락)")


if __name__ == "__main__":
    main()
