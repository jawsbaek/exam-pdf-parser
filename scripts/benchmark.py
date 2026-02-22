#!/usr/bin/env python3
"""
Performance Benchmark Tool - OCR 엔진 + 모델 조합 벤치마크
모든 사용 가능한 OCR 엔진과 모델 조합을 테스트하고,
속도, 정확도, 비용을 비교하는 Markdown 리포트를 생성합니다.

사용법:
    python scripts/benchmark.py <pdf_path> [-o reports/ocr-benchmark.md]
    python scripts/benchmark.py test/2025년-9월-고3-모의고사-영어-문제.pdf
    python scripts/benchmark.py test/exam.pdf --models gemini-2.5-flash gpt-4o-mini
    python scripts/benchmark.py test/exam.pdf --ocr-only
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def benchmark_ocr_engines(pdf_path: str, dpi: int = 200) -> list:
    """Benchmark all available OCR engines on a single PDF."""
    from src.ocr import OCR_ENGINES, list_available_engines
    from src.pdf_parser import PDFParser

    pdf_parser = PDFParser(pdf_path, dpi=dpi)
    images = pdf_parser.get_page_images_as_bytes()
    num_pages = len(images)

    results = []
    available = list_available_engines()

    for engine_name, info in available.items():
        entry = {
            "engine": engine_name,
            "class": info["class"],
            "available": info["available"],
            "pages": num_pages,
            "chars_extracted": 0,
            "init_time": 0.0,
            "ocr_time": 0.0,
            "total_time": 0.0,
            "chars_per_second": 0.0,
            "error": None,
        }

        if not info["available"]:
            entry["error"] = "Not installed"
            results.append(entry)
            continue

        try:
            engine_cls = OCR_ENGINES[engine_name]
            engine = engine_cls()

            # Special handling for pymupdf-text
            if engine_name == "pymupdf-text":
                engine.set_pdf_path(pdf_path)

            text = engine.extract_text(images)
            metrics = engine.get_metrics()

            entry["chars_extracted"] = len(text)
            entry["init_time"] = metrics["init_time_seconds"]
            entry["ocr_time"] = metrics["ocr_time_seconds"]
            entry["total_time"] = metrics["total_time_seconds"]
            entry["chars_per_second"] = round(
                len(text) / metrics["ocr_time_seconds"], 1
            ) if metrics["ocr_time_seconds"] > 0 else 0

            # Extract sample for quality check
            lines = text.split("\n")
            entry["sample_lines"] = lines[:5]

        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {str(e)}"

        results.append(entry)

    return results


def benchmark_models(pdf_path: str, model_names: list = None,
                     dpi: int = 200) -> list:
    """Benchmark parsing models (vision + hybrid) on a single PDF."""
    from src.config import MODEL_CONFIG
    from src.parser import ExamParser

    if model_names is None:
        model_names = list(MODEL_CONFIG.keys())

    parser = ExamParser(pdf_path, dpi=dpi)
    results = []

    for model_name in model_names:
        entry = {
            "model": model_name,
            "type": "hybrid" if "+" in model_name else "vision",
            "provider": MODEL_CONFIG.get(model_name, {}).get("provider", "unknown"),
            "questions_parsed": 0,
            "total_questions": 45,
            "completeness_pct": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "time_seconds": 0.0,
            "cost_per_question": 0.0,
            "tokens_per_question": 0,
            "error": None,
        }

        try:
            print(f"  Testing {model_name}...", end=" ", flush=True)
            result = parser.parse_with_model(model_name)

            n_q = len(result.parsed_exam.questions)
            total_q = result.parsed_exam.exam_info.total_questions

            entry["questions_parsed"] = n_q
            entry["total_questions"] = total_q
            entry["completeness_pct"] = round(n_q / total_q * 100, 1) if total_q > 0 else 0
            entry["input_tokens"] = result.total_tokens_input
            entry["output_tokens"] = result.total_tokens_output
            entry["total_tokens"] = result.total_tokens_input + result.total_tokens_output
            entry["cost_usd"] = round(result.total_cost_usd, 6)
            entry["time_seconds"] = round(result.parsing_time_seconds, 2)
            entry["cost_per_question"] = round(result.total_cost_usd / n_q, 6) if n_q > 0 else 0
            entry["tokens_per_question"] = round(entry["total_tokens"] / n_q) if n_q > 0 else 0

            print(f"{n_q}/{total_q} questions, ${entry['cost_usd']:.4f}, {entry['time_seconds']:.1f}s")

            # Add OCR metrics for hybrid models
            if "+" in model_name and result.ocr_metrics is not None:
                entry["ocr_metrics"] = result.ocr_metrics

        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {str(e)}"
            print(f"FAILED: {entry['error']}")

        results.append(entry)

    return results


def generate_benchmark_report(
    ocr_results: list,
    model_results: list,
    pdf_path: str,
    output_path: str | None = None,
) -> str:
    """Generate a comprehensive Markdown benchmark report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf_name = Path(pdf_path).name

    lines = []
    lines.append("# OCR & Model Benchmark Report")
    lines.append("")
    lines.append(f"- **Date**: {now}")
    lines.append(f"- **Test PDF**: `{pdf_name}`")
    lines.append("- **Generated by**: `scripts/benchmark.py`")
    lines.append("")

    # --- OCR Engine Results ---
    lines.append("## 1. OCR Engine Comparison")
    lines.append("")
    lines.append("| Engine | Available | Chars | Init (s) | OCR (s) | Total (s) | Chars/s | Notes |")
    lines.append("|--------|-----------|-------|----------|---------|-----------|---------|-------|")

    for r in ocr_results:
        avail = "O" if r["available"] else "X"
        chars = f"{r['chars_extracted']:,}" if r["chars_extracted"] else "-"
        init_t = f"{r['init_time']:.2f}" if r["available"] and not r["error"] else "-"
        ocr_t = f"{r['ocr_time']:.2f}" if r["available"] and not r["error"] else "-"
        total_t = f"{r['total_time']:.2f}" if r["available"] and not r["error"] else "-"
        cps = f"{r['chars_per_second']:,.0f}" if r["chars_per_second"] else "-"
        notes = r["error"] or ""
        lines.append(f"| {r['engine']} | {avail} | {chars} | {init_t} | {ocr_t} | {total_t} | {cps} | {notes} |")

    lines.append("")

    # Best OCR
    working_ocr = [r for r in ocr_results if r["available"] and not r["error"]]
    if working_ocr:
        fastest = min(working_ocr, key=lambda x: x["total_time"])
        most_chars = max(working_ocr, key=lambda x: x["chars_extracted"])
        lines.append("**Best OCR Results:**")
        lines.append(f"- Fastest: **{fastest['engine']}** ({fastest['total_time']:.2f}s)")
        lines.append(f"- Most text: **{most_chars['engine']}** ({most_chars['chars_extracted']:,} chars)")
        lines.append("")

    # --- Model Results ---
    if model_results:
        lines.append("## 2. Model Parsing Results")
        lines.append("")

        # Separate vision and hybrid
        vision = [r for r in model_results if r["type"] == "vision"]
        hybrid = [r for r in model_results if r["type"] == "hybrid"]

        if vision:
            lines.append("### Vision Models (Direct Image Parsing)")
            lines.append("")
            lines.append("| Model | Questions | Completeness | Tokens (in/out) | Cost | Time | $/Q |")
            lines.append("|-------|-----------|-------------|-----------------|------|------|-----|")
            for r in vision:
                if r["error"]:
                    lines.append(f"| {r['model']} | - | - | - | - | - | ERROR: {r['error'][:40]} |")
                else:
                    lines.append(
                        f"| {r['model']} | {r['questions_parsed']}/{r['total_questions']} "
                        f"| {r['completeness_pct']}% "
                        f"| {r['input_tokens']:,}/{r['output_tokens']:,} "
                        f"| ${r['cost_usd']:.4f} "
                        f"| {r['time_seconds']:.1f}s "
                        f"| ${r['cost_per_question']:.4f} |"
                    )
            lines.append("")

        if hybrid:
            lines.append("### Hybrid Models (OCR + Text LLM)")
            lines.append("")
            lines.append("| Model | Questions | Completeness | Tokens (in/out) | Cost | Time | $/Q |")
            lines.append("|-------|-----------|-------------|-----------------|------|------|-----|")
            for r in hybrid:
                if r["error"]:
                    lines.append(f"| {r['model']} | - | - | - | - | - | ERROR: {r['error'][:40]} |")
                else:
                    lines.append(
                        f"| {r['model']} | {r['questions_parsed']}/{r['total_questions']} "
                        f"| {r['completeness_pct']}% "
                        f"| {r['input_tokens']:,}/{r['output_tokens']:,} "
                        f"| ${r['cost_usd']:.4f} "
                        f"| {r['time_seconds']:.1f}s "
                        f"| ${r['cost_per_question']:.4f} |"
                    )
            lines.append("")

        # --- Rankings ---
        successful = [r for r in model_results if not r["error"] and r["questions_parsed"] > 0]
        if successful:
            lines.append("## 3. Rankings")
            lines.append("")

            by_completeness = sorted(successful, key=lambda x: x["completeness_pct"], reverse=True)
            by_cost = sorted(successful, key=lambda x: x["cost_usd"])
            by_speed = sorted(successful, key=lambda x: x["time_seconds"])
            by_efficiency = sorted(successful, key=lambda x: x["cost_per_question"])

            lines.append("### Best Completeness")
            for i, r in enumerate(by_completeness[:5], 1):
                pct = r['completeness_pct']
                parsed = r['questions_parsed']
                total = r['total_questions']
                lines.append(f"{i}. **{r['model']}** - {pct}% ({parsed}/{total})")
            lines.append("")

            lines.append("### Lowest Cost")
            for i, r in enumerate(by_cost[:5], 1):
                lines.append(f"{i}. **{r['model']}** - ${r['cost_usd']:.4f}")
            lines.append("")

            lines.append("### Fastest")
            for i, r in enumerate(by_speed[:5], 1):
                lines.append(f"{i}. **{r['model']}** - {r['time_seconds']:.1f}s")
            lines.append("")

            lines.append("### Best Cost Efficiency ($/question)")
            for i, r in enumerate(by_efficiency[:5], 1):
                lines.append(f"{i}. **{r['model']}** - ${r['cost_per_question']:.4f}/q")
            lines.append("")

        # --- Cost Projections ---
        if successful:
            lines.append("## 4. Cost Projections (500 PDFs)")
            lines.append("")
            lines.append("| Model | Est. Cost | Est. Time |")
            lines.append("|-------|-----------|-----------|")
            for r in sorted(successful, key=lambda x: x["cost_usd"]):
                est_cost = r["cost_usd"] * 500
                est_time_min = r["time_seconds"] * 500 / 60
                lines.append(f"| {r['model']} | ${est_cost:.2f} | {est_time_min:.0f} min |")
            lines.append("")

    # --- Recommendations ---
    lines.append("## 5. Recommendations")
    lines.append("")
    if successful:
        best_accuracy = by_completeness[0] if by_completeness else None
        best_value = by_efficiency[0] if by_efficiency else None

        if best_accuracy:
            lines.append(f"- **Best Accuracy**: {best_accuracy['model']} ({best_accuracy['completeness_pct']}%)")
        if best_value:
            lines.append(f"- **Best Value**: {best_value['model']} (${best_value['cost_per_question']:.4f}/q)")
        lines.append("- **For 500+ PDFs**: Use hybrid models with `pymupdf-text` for digital PDFs")
        lines.append("- **For scanned PDFs**: Use `easyocr` or `trocr` + `gemini-2.5-flash`")
    lines.append("")

    report = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport saved to {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark OCR engines and parsing models"
    )
    parser.add_argument("pdf_path", help="Path to test PDF file")
    parser.add_argument("-o", "--output", default="reports/ocr-benchmark.md",
                        help="Output report path (default: reports/ocr-benchmark.md)")
    parser.add_argument("--dpi", type=int, default=200, help="DPI (default: 200)")
    parser.add_argument("--ocr-only", action="store_true", help="Only benchmark OCR engines")
    parser.add_argument("--models", nargs="+", default=None,
                        help="Specific models to test (default: all)")
    parser.add_argument("--json", type=str, default=None,
                        help="Also save raw results as JSON")

    args = parser.parse_args()

    pdf_path = args.pdf_path
    if not Path(pdf_path).exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    print(f"Benchmarking with: {Path(pdf_path).name}")
    print(f"{'='*60}")

    # Phase 1: OCR engines
    print("\nPhase 1: OCR Engine Benchmark")
    print("-" * 40)
    ocr_results = benchmark_ocr_engines(pdf_path, dpi=args.dpi)
    for r in ocr_results:
        status = "OK" if r["available"] and not r["error"] else r.get("error", "N/A")
        print(f"  {r['engine']:15s} | {status}")

    # Phase 2: Model parsing (unless --ocr-only)
    model_results = []
    if not args.ocr_only:
        print("\nPhase 2: Model Parsing Benchmark")
        print("-" * 40)
        model_results = benchmark_models(pdf_path, args.models, dpi=args.dpi)

    # Generate report
    generate_benchmark_report(
        ocr_results, model_results, pdf_path, args.output
    )

    # Save JSON if requested
    if args.json:
        raw = {
            "ocr_results": ocr_results,
            "model_results": model_results,
            "timestamp": datetime.now().isoformat(),
            "pdf_path": pdf_path,
        }
        # Remove non-serializable data
        for r in raw["ocr_results"]:
            r.pop("sample_lines", None)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print(f"JSON results saved to {args.json}")

    print("\nDone!")


if __name__ == "__main__":
    main()
