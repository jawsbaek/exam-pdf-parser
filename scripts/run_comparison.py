#!/usr/bin/env python3
"""
Model Comparison Runner - 모델별 파싱 결과 비교 및 리포트 생성
여러 모델로 시험 PDF를 파싱하고 정답과 비교하여 Markdown 리포트를 생성합니다.

사용법:
    python scripts/run_comparison.py test/exam.pdf \\
        --answer test/answer.md \\
        --models gemini-2.5-flash,gpt-5-mini \\
        --output output/comparison/ \\
        --report output/report.md
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from src.config import sanitize_model_name
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multi-model comparison and generate accuracy report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_comparison.py test/exam.pdf --models gemini-2.5-flash,gpt-5-mini
  python scripts/run_comparison.py test/exam.pdf --answer test/answer.md --output output/comparison/ --report output/report.md
        """,
    )
    parser.add_argument("pdf_path", help="Path to exam PDF file")
    parser.add_argument(
        "--answer", "-a",
        default=None,
        help="Path to answer key Markdown file (e.g. test/answer.md)"
    )
    parser.add_argument(
        "--models", "-m",
        default=None,
        help="Comma-separated list of models (default: all vision models)"
    )
    parser.add_argument(
        "--output", "-o",
        default="output/comparison",
        help="Output directory for JSON results (default: output/comparison)"
    )
    parser.add_argument(
        "--report", "-r",
        default=None,
        help="Output path for Markdown report (default: <output>/report.md)"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI for PDF rendering (default: 200)"
    )
    parser.add_argument(
        "--include-hybrid",
        action="store_true",
        help="Include hybrid OCR+LLM models"
    )
    return parser.parse_args()


def load_answer_key(answer_path: str):
    """Load and parse answer key from Markdown file. Returns None if not available."""
    try:
        from src.evaluator import parse_answer_md
        answer_key = parse_answer_md(answer_path)
        console.print(f"[green]Loaded answer key from {answer_path}[/green]")
        return answer_key
    except ImportError:
        console.print("[yellow]Warning: src.evaluator not available — skipping accuracy evaluation[/yellow]")
        return None
    except Exception as e:
        console.print(f"[yellow]Warning: could not load answer key: {e}[/yellow]")
        return None


def run_model(parser, model_name: str) -> dict:
    """Run a single model and return result dict with timing info."""
    entry = {
        "model": model_name,
        "result": None,
        "eval": None,
        "error": None,
        "time_seconds": 0.0,
    }
    start = time.time()
    try:
        result = parser.parse_with_model(model_name)
        entry["result"] = result
        entry["time_seconds"] = round(time.time() - start, 2)
    except Exception as e:
        entry["error"] = f"{type(e).__name__}: {e}"
        entry["time_seconds"] = round(time.time() - start, 2)
    return entry


def evaluate_result(result, answer_key) -> dict | None:
    """Evaluate a ParseResult against an AnswerKey. Returns eval dict or None."""
    if answer_key is None or result is None:
        return None
    try:
        from src.evaluator import evaluate
        eval_result = evaluate(result.parsed_exam, answer_key, model_name=result.model_name)
        # Convert EvalResult Pydantic model to the dict format expected by report generation
        per_question_dict = {
            str(qe.number): {
                "found": qe.found,
                "similarity": round(
                    (qe.passage_similarity + qe.question_text_similarity) / 2, 3
                ) if qe.found else None,
                "passage_similarity": qe.passage_similarity,
                "choices_correct": qe.choices_correct,
                "choices_total": qe.choices_total,
                "question_text_similarity": qe.question_text_similarity,
            }
            for qe in eval_result.per_question
        }
        return {
            "overall_accuracy_pct": round(eval_result.overall_score * 100, 2),
            "passage_accuracy_pct": round(eval_result.avg_passage_similarity * 100, 2),
            "choice_accuracy_pct": round(eval_result.avg_choice_accuracy * 100, 2),
            "question_text_accuracy_pct": round(eval_result.avg_question_text_similarity * 100, 2),
            "coverage_pct": eval_result.coverage_pct,
            "total_questions_expected": eval_result.total_questions_expected,
            "total_questions_found": eval_result.total_questions_found,
            "per_question": per_question_dict,
        }
    except ImportError:
        return None
    except Exception as e:
        console.print(f"[yellow]  Evaluation error: {e}[/yellow]")
        return None


def save_result_json(result, output_dir: Path, model_name: str) -> Path:
    """Save ParseResult to JSON file."""
    safe_name = sanitize_model_name(model_name)
    out_path = output_dir / f"{safe_name}_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
    return out_path


def generate_markdown_report(
    entries: list[dict],
    pdf_path: str,
    answer_path: str | None,
    output_dir: Path,
) -> str:
    """Generate a Markdown comparison report from model run entries."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf_name = Path(pdf_path).name
    has_eval = any(e["eval"] is not None for e in entries)

    lines = []
    lines.append("# Exam Parser Model Comparison Report")
    lines.append("")
    lines.append(f"- **Date**: {now}")
    lines.append(f"- **PDF**: `{pdf_name}`")
    if answer_path:
        lines.append(f"- **Answer Key**: `{Path(answer_path).name}`")
    lines.append(f"- **Models Tested**: {len(entries)}")
    lines.append("")

    # --- Summary Table ---
    lines.append("## Summary")
    lines.append("")
    if has_eval:
        lines.append(
            "| Model | Questions | Coverage | Passage Acc | Choice Acc | Overall | Cost | Time |"
        )
        lines.append(
            "|-------|-----------|----------|-------------|------------|---------|------|------|"
        )
    else:
        lines.append("| Model | Questions | Coverage | Cost | Time |")
        lines.append("|-------|-----------|----------|------|------|")

    successful = []
    for e in entries:
        model = e["model"]
        if e["error"]:
            if has_eval:
                lines.append(f"| {model} | - | - | - | - | - | - | - |")
            else:
                lines.append(f"| {model} | - | - | - | - |")
            continue

        r = e["result"]
        n_q = len(r.parsed_exam.questions)
        total_q = r.parsed_exam.exam_info.total_questions or n_q
        coverage = f"{round(n_q / total_q * 100, 1)}%" if total_q > 0 else "N/A"
        cost = f"${r.total_cost_usd:.4f}"
        t = f"{e['time_seconds']:.1f}s"

        ev = e["eval"]
        if has_eval and ev:
            passage_acc = f"{ev.get('passage_accuracy_pct', 0):.1f}%"
            choice_acc = f"{ev.get('choice_accuracy_pct', 0):.1f}%"
            overall = f"{ev.get('overall_accuracy_pct', 0):.1f}%"
            lines.append(
                f"| {model} | {n_q}/{total_q} | {coverage} | {passage_acc} | {choice_acc} | {overall} | {cost} | {t} |"
            )
        else:
            lines.append(f"| {model} | {n_q}/{total_q} | {coverage} | {cost} | {t} |")

        successful.append(e)

    lines.append("")

    # --- Rankings ---
    if successful:
        lines.append("## Rankings")
        lines.append("")

        if has_eval:
            by_accuracy = sorted(
                [e for e in successful if e["eval"]],
                key=lambda x: x["eval"].get("overall_accuracy_pct", 0),
                reverse=True,
            )
            if by_accuracy:
                best = by_accuracy[0]
                acc = best["eval"].get("overall_accuracy_pct", 0)
                lines.append(f"- **Best Accuracy**: {best['model']} ({acc:.1f}%)")

        by_coverage = sorted(
            successful,
            key=lambda x: len(x["result"].parsed_exam.questions),
            reverse=True,
        )
        by_cost = sorted(successful, key=lambda x: x["result"].total_cost_usd)
        by_speed = sorted(successful, key=lambda x: x["time_seconds"])

        if by_coverage:
            b = by_coverage[0]
            n_q = len(b["result"].parsed_exam.questions)
            total_q = b["result"].parsed_exam.exam_info.total_questions or n_q
            lines.append(f"- **Best Coverage**: {b['model']} ({n_q}/{total_q})")

        if by_cost:
            b = by_cost[0]
            lines.append(f"- **Lowest Cost**: {b['model']} (${b['result'].total_cost_usd:.4f})")

        if by_speed:
            b = by_speed[0]
            lines.append(f"- **Fastest**: {b['model']} ({b['time_seconds']:.1f}s)")

        # Cost efficiency
        def cost_per_q(e):
            n = len(e["result"].parsed_exam.questions)
            return e["result"].total_cost_usd / n if n > 0 else float("inf")

        by_efficiency = sorted(successful, key=cost_per_q)
        if by_efficiency:
            b = by_efficiency[0]
            lines.append(f"- **Best Cost-Efficiency**: {b['model']} (${cost_per_q(b):.4f}/q)")

        lines.append("")

    # --- Per-Question Details ---
    if has_eval and successful:
        lines.append("## Per-Question Details")
        lines.append("")

        eval_models = [e for e in successful if e["eval"] and "per_question" in e["eval"]]
        if eval_models:
            header_models = [e["model"] for e in eval_models]
            header = "| Q# | " + " | ".join(header_models) + " |"
            sep = "|----|-" + "-|-".join(["------"] * len(eval_models)) + "-|"
            lines.append(header)
            lines.append(sep)

            # Collect all question numbers
            all_q_nums = set()
            for e in eval_models:
                for q_num in e["eval"]["per_question"].keys():
                    all_q_nums.add(int(q_num))

            for q_num in sorted(all_q_nums):
                row = f"| {q_num} |"
                for e in eval_models:
                    pq = e["eval"]["per_question"].get(str(q_num), {})
                    found = pq.get("found", False)
                    sim = pq.get("similarity", None)
                    if not found:
                        cell = "missing"
                    elif sim is not None:
                        cell = f"{sim:.2f}"
                    else:
                        cell = "found"
                    row += f" {cell} |"
                lines.append(row)

            lines.append("")

    # --- Hard Questions ---
    if has_eval and successful:
        eval_models = [e for e in successful if e["eval"] and "per_question" in e["eval"]]
        if eval_models:
            all_q_nums = set()
            for e in eval_models:
                for q_num in e["eval"]["per_question"].keys():
                    all_q_nums.add(int(q_num))

            missed_by_all = []
            for q_num in sorted(all_q_nums):
                missed_all = all(
                    not e["eval"]["per_question"].get(str(q_num), {}).get("found", False)
                    for e in eval_models
                )
                if missed_all:
                    missed_by_all.append(q_num)

            lines.append("## Hard Questions")
            lines.append("")
            if missed_by_all:
                lines.append(f"Questions missed by **all** models: {', '.join(str(q) for q in missed_by_all)}")
            else:
                lines.append("No questions were missed by all models.")
            lines.append("")

    # --- Errors ---
    failed = [e for e in entries if e["error"]]
    if failed:
        lines.append("## Errors")
        lines.append("")
        for e in failed:
            lines.append(f"- **{e['model']}**: `{e['error']}`")
        lines.append("")

    # --- Output files ---
    lines.append("## Output Files")
    lines.append("")
    lines.append(f"Results saved to: `{output_dir}/`")
    lines.append("")

    return "\n".join(lines)


def print_summary_table(entries: list[dict], has_eval: bool) -> None:
    """Print rich summary table to console."""
    table = Table(title="Model Comparison Summary")
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Questions", justify="right", style="green")
    table.add_column("Cost", justify="right", style="magenta")
    table.add_column("Time", justify="right", style="yellow")
    if has_eval:
        table.add_column("Overall Acc", justify="right", style="blue")
    table.add_column("Status", style="white")

    for e in entries:
        model = e["model"]
        if e["error"]:
            table.add_row(model, "-", "-", f"{e['time_seconds']:.1f}s",
                          *(["-"] if has_eval else []), f"[red]FAILED[/red]")
            continue
        r = e["result"]
        n_q = len(r.parsed_exam.questions)
        total_q = r.parsed_exam.exam_info.total_questions or n_q
        cost = f"${r.total_cost_usd:.4f}"
        t = f"{e['time_seconds']:.1f}s"
        status = "[green]OK[/green]"

        if has_eval and e["eval"]:
            acc = f"{e['eval'].get('overall_accuracy_pct', 0):.1f}%"
            table.add_row(model, f"{n_q}/{total_q}", cost, t, acc, status)
        else:
            row = [model, f"{n_q}/{total_q}", cost, t]
            if has_eval:
                row.append("-")
            row.append(status)
            table.add_row(*row)

    console.print(table)


def main():
    args = parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        console.print(f"[red]Error:[/red] PDF not found: {pdf_path}")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = Path(args.report) if args.report else output_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine models
    from src.parser import ExamParser, HYBRID_MODELS

    if args.models:
        model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        model_names = list(HYBRID_MODELS)

    console.print(Panel(
        f"[bold]PDF:[/bold] {pdf_path.name}\n"
        f"[bold]Models:[/bold] {', '.join(model_names)}\n"
        f"[bold]Output:[/bold] {output_dir}\n"
        f"[bold]Report:[/bold] {report_path}",
        title="Exam Parser Comparison",
        border_style="blue",
    ))

    # Load answer key (optional)
    answer_key = None
    if args.answer:
        answer_key = load_answer_key(args.answer)

    # Initialize parser
    exam_parser = ExamParser(str(pdf_path), dpi=args.dpi)

    # Run each model
    entries = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Running models...", total=len(model_names))

        for model_name in model_names:
            progress.update(task, description=f"[cyan]{model_name}[/cyan]")
            entry = run_model(exam_parser, model_name)

            if entry["error"]:
                console.print(f"  [red]FAILED[/red] {model_name}: {entry['error']}")
            else:
                r = entry["result"]
                n_q = len(r.parsed_exam.questions)
                total_q = r.parsed_exam.exam_info.total_questions or n_q
                console.print(
                    f"  [green]OK[/green] {model_name}: {n_q}/{total_q} questions, "
                    f"${r.total_cost_usd:.4f}, {entry['time_seconds']:.1f}s"
                )

                # Save individual JSON result
                json_path = save_result_json(r, output_dir, model_name)
                console.print(f"     Saved: {json_path}")

                # Evaluate against answer key
                entry["eval"] = evaluate_result(r, answer_key)
                if entry["eval"]:
                    acc = entry["eval"].get("overall_accuracy_pct", 0)
                    console.print(f"     Accuracy: {acc:.1f}%")

            entries.append(entry)
            progress.advance(task)

    # Print summary
    has_eval = any(e["eval"] is not None for e in entries)
    console.print("")
    print_summary_table(entries, has_eval)

    # Generate Markdown report
    report_md = generate_markdown_report(entries, str(pdf_path), args.answer, output_dir)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    console.print(f"\n[green]Report saved to:[/green] {report_path}")

    # Save summary JSON
    summary_data = []
    for e in entries:
        item = {
            "model": e["model"],
            "error": e["error"],
            "time_seconds": e["time_seconds"],
        }
        if e["result"]:
            r = e["result"]
            item.update({
                "questions_parsed": len(r.parsed_exam.questions),
                "total_questions": r.parsed_exam.exam_info.total_questions,
                "cost_usd": r.total_cost_usd,
                "input_tokens": r.total_tokens_input,
                "output_tokens": r.total_tokens_output,
            })
        if e["eval"]:
            item["eval"] = e["eval"]
        summary_data.append(item)

    summary_path = output_dir / "comparison_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)
    console.print(f"[green]Summary JSON saved to:[/green] {summary_path}")


if __name__ == "__main__":
    main()
