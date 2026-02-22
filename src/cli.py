"""
Command-line interface for exam parser.
시험 문제 파서의 CLI 인터페이스입니다.
"""

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import sanitize_model_name
from .parser import ExamParser
from .schema import ParseResult

console = Console()


def format_parse_result(result: ParseResult) -> None:
    """Display parse result in a formatted table."""
    table = Table(title=f"Parsing Results - {result.model_name}")

    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Model", result.model_name)
    table.add_row("Questions Parsed", str(len(result.parsed_exam.questions)))
    table.add_row("Pages Processed", str(result.pages_processed))
    table.add_row("Input Tokens", f"{result.total_tokens_input:,}")
    table.add_row("Output Tokens", f"{result.total_tokens_output:,}")
    table.add_row("Total Tokens", f"{result.total_tokens_input + result.total_tokens_output:,}")
    table.add_row("Cost (USD)", f"${result.total_cost_usd:.4f}")
    table.add_row("Parsing Time", f"{result.parsing_time_seconds:.2f}s")

    console.print(table)

    # Display exam info
    exam_info = result.parsed_exam.exam_info
    info_text = f"""
Title: {exam_info.title}
Subject: {exam_info.subject}
Year: {exam_info.year or 'N/A'}
Month: {exam_info.month or 'N/A'}
Grade: {exam_info.grade or 'N/A'}
Total Questions: {exam_info.total_questions}
    """.strip()

    console.print(Panel(info_text, title="Exam Information", border_style="green"))


def compare_results(results: dict) -> None:
    """Display comparison table of multiple parsing results."""
    table = Table(title="Model Comparison")

    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Questions", justify="right", style="green")
    table.add_column("Input Tokens", justify="right", style="blue")
    table.add_column("Output Tokens", justify="right", style="blue")
    table.add_column("Cost (USD)", justify="right", style="magenta")
    table.add_column("Time (s)", justify="right", style="yellow")
    table.add_column("$/Question", justify="right", style="red")

    for model_name, result in results.items():
        if result.error:
            table.add_row(model_name, f"ERROR: {result.error[:40]}", "-", "-", "-", "-", "-")
            continue

        num_questions = len(result.parsed_exam.questions)
        cost_per_q = result.total_cost_usd / num_questions if num_questions > 0 else 0

        table.add_row(
            model_name,
            str(num_questions),
            f"{result.total_tokens_input:,}",
            f"{result.total_tokens_output:,}",
            f"${result.total_cost_usd:.4f}",
            f"{result.parsing_time_seconds:.2f}",
            f"${cost_per_q:.4f}"
        )

    console.print(table)


def save_results(result: ParseResult, output_path: Path) -> None:
    """Save parse result to JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

    console.print(f"[green]V[/green] Results saved to {output_path}")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Parse exam PDFs using document parsers + LLM structuring (3-layer architecture)"
    )

    parser.add_argument(
        "pdf_path",
        type=str,
        nargs="?",
        help="Path to exam PDF file"
    )

    parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        help="Model to use (default: mineru+gemini-3-pro-preview)"
    )

    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output JSON file path"
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI for PDF to image conversion (default: 200)"
    )

    parser.add_argument(
        "--instruction",
        type=str,
        default=None,
        help="Custom instruction prompt"
    )

    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all supported models and exit"
    )

    parser.add_argument(
        "--list-ocr",
        action="store_true",
        help="List available document parsers / OCR engines and exit"
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation layer on parsed results"
    )

    parser.add_argument(
        "--answer-key",
        type=str,
        default=None,
        help="Path to answer.md for validation cross-reference"
    )

    args = parser.parse_args()

    # List OCR engines / document parsers
    if args.list_ocr:
        from .ocr import list_available_engines

        table = Table(title="Document Parsers")
        table.add_column("Engine", style="cyan")
        table.add_column("Available", style="green")

        for name, info in list_available_engines().items():
            avail = "[green]Yes[/green]" if info["available"] else "[red]No[/red]"
            table.add_row(name, avail)

        console.print(table)
        console.print("\n[dim]Install:[/dim]")
        console.print("  mineru: pip install mineru")
        return

    # List models
    if args.list_models:
        from .config import MODEL_CONFIG

        table = Table(title="Supported Models (Document Parser + LLM)")
        table.add_column("Model", style="cyan")
        table.add_column("Parser", style="yellow")
        table.add_column("LLM", style="green")
        table.add_column("Input ($/1M)", justify="right", style="blue")
        table.add_column("Output ($/1M)", justify="right", style="magenta")

        for model_name, config in MODEL_CONFIG.items():
            table.add_row(
                model_name,
                config["ocr_engine"],
                config["llm_model"],
                f"${config['input_price_per_1m']:.2f}",
                f"${config['output_price_per_1m']:.2f}"
            )

        console.print(table)
        return

    # Validate PDF path
    if not args.pdf_path:
        console.print("[red]Error:[/red] pdf_path is required (unless using --list-models)")
        sys.exit(1)

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        console.print(f"[red]Error:[/red] PDF file not found: {pdf_path}")
        sys.exit(1)

    # Initialize parser
    exam_parser = ExamParser(str(pdf_path), dpi=args.dpi)

    try:
        if args.model:
            # Parse with specific model
            console.print(f"[blue]Parsing with {args.model}...[/blue]")
            result = exam_parser.parse_with_model(args.model, instruction=args.instruction)

            # Run validation if requested
            if args.validate:
                _run_validation(result, args.answer_key)

            format_parse_result(result)

            if args.output:
                save_results(result, Path(args.output))

        else:
            # Parse with all models
            console.print("[blue]Parsing with all available models...[/blue]")
            results = exam_parser.parse_with_all_models(instruction=args.instruction)

            if not results:
                console.print("[red]No models succeeded[/red]")
                sys.exit(1)

            # Run validation if requested
            if args.validate:
                for model_name, result in results.items():
                    console.print(f"\n[blue]Validation: {model_name}[/blue]")
                    _run_validation(result, args.answer_key)

            compare_results(results)

            if args.output:
                output_dir = Path(args.output)
                output_dir.mkdir(parents=True, exist_ok=True)

                for model_name, result in results.items():
                    output_file = output_dir / f"{sanitize_model_name(model_name)}.json"
                    save_results(result, output_file)

    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _run_validation(result: ParseResult, answer_key_path: str | None = None) -> None:
    """Run validation layer on a parse result."""
    from .validator import validate_exam

    answer_key = None
    if answer_key_path:
        from .evaluator import parse_answer_md
        answer_key = parse_answer_md(answer_key_path)

    validation = validate_exam(result.parsed_exam, answer_key=answer_key)

    if validation.is_valid:
        console.print(f"  [green]VALID[/green] - {validation.total_warnings} warnings")
    else:
        console.print(f"  [red]INVALID[/red] - {validation.total_errors} errors, {validation.total_warnings} warnings")

    for issue in validation.issues:
        color = "red" if issue.level == "error" else "yellow"
        q_prefix = f"Q{issue.question_number}: " if issue.question_number else ""
        console.print(f"  [{color}]{issue.level.upper()}[/{color}] {q_prefix}{issue.message}")


if __name__ == "__main__":
    main()
