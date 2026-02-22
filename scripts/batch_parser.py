#!/usr/bin/env python3
"""
Batch PDF Parser - 대량 PDF 일괄 처리 시스템
500+ PDF 파일을 병렬 처리하여 구조화된 결과를 생성합니다.

사용법:
    python scripts/batch_parser.py <pdf_dir> -m <model> [-w 4] [-o results/] [--retry 3]
    python scripts/batch_parser.py ./exams/ -m gemini-2.5-flash -w 8 -o results/batch/
    python scripts/batch_parser.py ./exams/ -m pymupdf-text+gemini-2.5-flash --cost-limit 10.0
"""

import argparse
import csv
import json
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class BatchResult:
    """Single PDF processing result"""
    pdf_path: str
    status: str  # "success", "error", "skipped"
    model_name: str = ""
    questions_parsed: int = 0
    total_questions_expected: int = 45
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    time_seconds: float = 0.0
    error_message: str = ""
    output_file: str = ""


@dataclass
class BatchStats:
    """Aggregate batch processing statistics"""
    total_files: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_cost_usd: float = 0.0
    total_time_seconds: float = 0.0
    start_time: str = ""
    end_time: str = ""
    model_name: str = ""
    results: list = field(default_factory=list)


def parse_single_pdf(pdf_path: str, model_name: str, output_dir: str,
                     dpi: int = 200, instruction: str | None = None) -> BatchResult:
    """Parse a single PDF file. Designed to run in a subprocess."""
    from src.parser import ExamParser

    result = BatchResult(pdf_path=pdf_path, model_name=model_name)
    start = time.time()

    try:
        parser = ExamParser(pdf_path, dpi=dpi)
        parse_result = parser.parse_with_model(model_name, instruction=instruction)

        result.status = "success"
        result.questions_parsed = len(parse_result.parsed_exam.questions)
        result.total_questions_expected = parse_result.parsed_exam.exam_info.total_questions
        result.input_tokens = parse_result.total_tokens_input
        result.output_tokens = parse_result.total_tokens_output
        result.cost_usd = parse_result.total_cost_usd
        result.time_seconds = time.time() - start

        # Save individual result
        if output_dir:
            safe_name = Path(pdf_path).stem.replace("/", "_").replace(" ", "_")
            out_file = Path(output_dir) / f"{safe_name}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(parse_result.model_dump(), f, ensure_ascii=False, indent=2)
            result.output_file = str(out_file)

    except Exception as e:
        result.status = "error"
        result.error_message = f"{type(e).__name__}: {str(e)}"
        result.time_seconds = time.time() - start

    return result


def parse_with_retry(pdf_path: str, model_name: str, output_dir: str,
                     max_retries: int = 3, dpi: int = 200,
                     instruction: str | None = None) -> BatchResult:
    """Parse with retry logic for transient failures."""
    last_result = None
    for attempt in range(max_retries):
        result = parse_single_pdf(pdf_path, model_name, output_dir, dpi, instruction)
        if result.status == "success":
            return result
        last_result = result
        if attempt < max_retries - 1:
            delay = 2 ** attempt  # exponential backoff
            time.sleep(delay)
    return last_result


def find_pdf_files(directory: str) -> list:
    """Recursively find all PDF files in directory."""
    pdf_dir = Path(directory)
    if not pdf_dir.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    pdfs = sorted(pdf_dir.rglob("*.pdf"))
    return [str(p) for p in pdfs]


def save_csv_report(stats: BatchStats, output_path: str):
    """Save batch results as CSV."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "pdf_path", "status", "model_name", "questions_parsed",
            "total_questions_expected", "input_tokens", "output_tokens",
            "cost_usd", "time_seconds", "error_message", "output_file"
        ])
        writer.writeheader()
        for r in stats.results:
            writer.writerow(asdict(r))


def save_json_report(stats: BatchStats, output_path: str):
    """Save batch summary as JSON."""
    summary = {
        "batch_summary": {
            "total_files": stats.total_files,
            "processed": stats.processed,
            "succeeded": stats.succeeded,
            "failed": stats.failed,
            "skipped": stats.skipped,
            "total_tokens_input": stats.total_tokens_input,
            "total_tokens_output": stats.total_tokens_output,
            "total_cost_usd": round(stats.total_cost_usd, 6),
            "total_time_seconds": round(stats.total_time_seconds, 2),
            "avg_time_per_pdf": round(stats.total_time_seconds / stats.processed, 2) if stats.processed > 0 else 0,
            "avg_cost_per_pdf": round(stats.total_cost_usd / stats.processed, 6) if stats.processed > 0 else 0,
            "model_name": stats.model_name,
            "start_time": stats.start_time,
            "end_time": stats.end_time,
        },
        "results": [asdict(r) for r in stats.results],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def run_batch(
    pdf_dir: str,
    model_name: str,
    output_dir: str | None = None,
    workers: int = 4,
    max_retries: int = 3,
    dpi: int = 200,
    instruction: str | None = None,
    cost_limit: float | None = None,
    file_limit: int | None = None,
) -> BatchStats:
    """
    Run batch processing on all PDFs in a directory.

    Args:
        pdf_dir: Directory containing PDF files
        model_name: Model to use for parsing
        output_dir: Directory to save results
        workers: Number of parallel workers
        max_retries: Maximum retry attempts per file
        dpi: DPI for PDF-to-image conversion
        instruction: Custom parsing instruction
        cost_limit: Stop if total cost exceeds this (USD)
        file_limit: Maximum number of files to process
    """
    from tqdm import tqdm

    # Find PDFs
    pdf_files = find_pdf_files(pdf_dir)
    if file_limit:
        pdf_files = pdf_files[:file_limit]

    if not pdf_files:
        print(f"No PDF files found in {pdf_dir}")
        return BatchStats()

    # Setup output directory
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

    stats = BatchStats(
        total_files=len(pdf_files),
        model_name=model_name,
        start_time=datetime.now().isoformat(),
    )

    print(f"\n{'='*60}")
    print("Batch PDF Parser")
    print(f"{'='*60}")
    print(f"  Directory: {pdf_dir}")
    print(f"  PDF files: {len(pdf_files)}")
    print(f"  Model: {model_name}")
    print(f"  Workers: {workers}")
    print(f"  Max retries: {max_retries}")
    if cost_limit:
        print(f"  Cost limit: ${cost_limit:.2f}")
    print(f"{'='*60}\n")

    # Determine worker count and executor type
    is_hybrid = "+" in model_name
    gpu_heavy_ocr = any(engine in model_name for engine in ("trocr", "deepseek"))
    if gpu_heavy_ocr:
        effective_workers = 1
    elif is_hybrid:
        effective_workers = min(workers, 2)
    else:
        effective_workers = workers

    # Use ThreadPoolExecutor for API-only models (no subprocess overhead)
    PoolExecutor = ProcessPoolExecutor if is_hybrid else ThreadPoolExecutor

    cost_exceeded = False
    pdf_queue = list(pdf_files)
    queue_idx = 0
    max_pending = effective_workers * 2

    with PoolExecutor(max_workers=effective_workers) as executor:
        pending = set()

        # Submit initial batch
        initial_count = min(max_pending, len(pdf_queue))
        for i in range(initial_count):
            future = executor.submit(
                parse_with_retry,
                pdf_queue[i], model_name, output_dir or "",
                max_retries, dpi, instruction
            )
            pending.add(future)
        queue_idx = initial_count

        with tqdm(total=len(pdf_files), desc="Processing", unit="pdf") as pbar:
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)

                for future in done:
                    result = future.result()
                    stats.results.append(result)
                    stats.processed += 1

                    if result.status == "success":
                        stats.succeeded += 1
                        stats.total_tokens_input += result.input_tokens
                        stats.total_tokens_output += result.output_tokens
                        stats.total_cost_usd += result.cost_usd
                        stats.total_time_seconds += result.time_seconds
                        pbar.set_postfix({
                            "ok": stats.succeeded,
                            "fail": stats.failed,
                            "cost": f"${stats.total_cost_usd:.4f}"
                        })
                    elif result.status == "error":
                        stats.failed += 1
                        pbar.set_postfix({
                            "ok": stats.succeeded,
                            "fail": stats.failed,
                            "last_err": result.error_message[:30]
                        })
                    else:
                        stats.skipped += 1

                    pbar.update(1)

                # Check cost limit before submitting more
                if cost_limit and stats.total_cost_usd >= cost_limit:
                    print(f"\n[COST LIMIT] Reached ${stats.total_cost_usd:.4f} >= ${cost_limit:.2f}. Stopping.")
                    cost_exceeded = True
                    for f in pending:
                        f.cancel()
                    pending.clear()
                    break

                # Submit more work up to max_pending
                while queue_idx < len(pdf_queue) and len(pending) < max_pending:
                    future = executor.submit(
                        parse_with_retry,
                        pdf_queue[queue_idx], model_name, output_dir or "",
                        max_retries, dpi, instruction
                    )
                    pending.add(future)
                    queue_idx += 1

    stats.end_time = datetime.now().isoformat()

    # Print summary
    print(f"\n{'='*60}")
    print("BATCH COMPLETE")
    print(f"{'='*60}")
    print(f"  Processed: {stats.processed}/{stats.total_files}")
    print(f"  Succeeded: {stats.succeeded}")
    print(f"  Failed:    {stats.failed}")
    print(f"  Skipped:   {stats.skipped}")
    print(f"  Total tokens: {stats.total_tokens_input + stats.total_tokens_output:,}")
    print(f"  Total cost:   ${stats.total_cost_usd:.4f}")
    print(f"  Total time:   {stats.total_time_seconds:.1f}s")
    if stats.succeeded > 0:
        print(f"  Avg cost/PDF: ${stats.total_cost_usd / stats.succeeded:.4f}")
        print(f"  Avg time/PDF: {stats.total_time_seconds / stats.succeeded:.1f}s")
    if cost_exceeded:
        print("  [!] Stopped early due to cost limit")
    print(f"{'='*60}\n")

    # Save reports
    if output_dir:
        save_csv_report(stats, str(Path(output_dir) / "batch_results.csv"))
        save_json_report(stats, str(Path(output_dir) / "batch_summary.json"))
        print(f"Reports saved to {output_dir}/")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Batch process multiple PDF files for exam parsing"
    )
    parser.add_argument("pdf_dir", help="Directory containing PDF files")
    parser.add_argument("-m", "--model", required=True, help="Model name (e.g. gemini-2.5-flash)")
    parser.add_argument("-o", "--output", default="results/batch/", help="Output directory (default: results/batch/)")
    parser.add_argument("-w", "--workers", type=int, default=4, help="Number of parallel workers (default: 4)")
    parser.add_argument("--retry", type=int, default=3, help="Max retries per file (default: 3)")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for image conversion (default: 200)")
    parser.add_argument("--instruction", type=str, default=None, help="Custom parsing instruction")
    parser.add_argument("--cost-limit", type=float, default=None, help="Stop if total cost exceeds this USD amount")
    parser.add_argument("--file-limit", type=int, default=None, help="Maximum number of files to process")

    args = parser.parse_args()

    run_batch(
        pdf_dir=args.pdf_dir,
        model_name=args.model,
        output_dir=args.output,
        workers=args.workers,
        max_retries=args.retry,
        dpi=args.dpi,
        instruction=args.instruction,
        cost_limit=args.cost_limit,
        file_limit=args.file_limit,
    )


if __name__ == "__main__":
    main()
