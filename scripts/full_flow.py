#!/usr/bin/env python3
"""
Full Flow Script - PDF 파싱 → 해설 생성 → 저장 파이프라인
MinerU+LLM으로 PDF를 파싱하고 해설을 추가한 뒤 JSON + Markdown으로 저장합니다.

사용법:
    python scripts/full_flow.py exam.pdf
    python scripts/full_flow.py exam1.pdf exam2.pdf --model mineru+gemini-3-flash-preview
    python scripts/full_flow.py exam.pdf --skip-explain -o output/my_results/
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parser import ExamParser
from src.schema import ParsedExam, QuestionType

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()

# 기본 테스트 PDF 경로 (인자 없을 때 사용)
_PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_PDFS = [
    str(_PROJECT_ROOT / "test/2025년-9월-고3-모의고사-영어-문제.pdf"),
    str(_PROJECT_ROOT / "verify/Hyper4 250904 학생용 28.pdf"),
    str(_PROJECT_ROOT / "verify/Hyper4 250904 학생용 29.pdf"),
]

# 선택지 원문자 (①②③④⑤)
CIRCLE_NUMBERS = ["①", "②", "③", "④", "⑤"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse PDFs with MinerU+LLM, add explanations, and save structured output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/full_flow.py test/exam.pdf
  python scripts/full_flow.py test/exam.pdf --model mineru+gemini-3-flash-preview --llm gemini-3-flash-preview
  python scripts/full_flow.py test/a.pdf test/b.pdf -o output/my_results/ --skip-explain
        """,
    )
    parser.add_argument(
        "pdfs",
        nargs="*",
        help="PDF file path(s) to process (default: 3 built-in test PDFs)",
    )
    parser.add_argument(
        "--model", "-m",
        default="mineru+gemini-3-flash-preview",
        help="Hybrid model for parsing (default: mineru+gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--llm",
        default="gemini-3-flash-preview",
        help="LLM backend for explanation generation (default: gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output/full_flow",
        help="Output directory (default: output/full_flow/)",
    )
    parser.add_argument(
        "--skip-explain",
        action="store_true",
        help="Skip explanation generation step",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI for PDF rendering (default: 200)",
    )
    return parser.parse_args()


def is_listening(q) -> bool:
    """듣기 문제 여부 확인"""
    return q.question_type == QuestionType.LISTENING


def build_markdown_summary(parsed_exam: ParsedExam) -> str:
    """ParsedExam으로부터 인간이 읽기 쉬운 Markdown 요약 생성"""
    info = parsed_exam.exam_info
    questions = parsed_exam.questions

    explained = [q for q in questions if not is_listening(q) and getattr(q, "explanation", None)]
    skipped = [q for q in questions if is_listening(q)]

    lines: list[str] = []
    lines.append(f"# {info.title or '시험 문제'}")
    lines.append("")
    lines.append(f"- Year: {info.year}, Month: {info.month}, Grade: {info.grade}")
    lines.append(f"- Subject: {info.subject or 'N/A'}")
    lines.append(f"- Total Questions: {info.total_questions or len(questions)}")
    lines.append(f"- Questions with Explanations: {len(explained)}")
    lines.append(f"- Skipped (Listening/Audio): {len(skipped)}")
    lines.append("")

    for q in questions:
        q_type = q.question_type.value if q.question_type else "기타"
        lines.append(f"## Question {q.number} [{q_type}] ({q.points}점)")
        lines.append("")
        lines.append(f"**문제:** {q.question_text}")
        lines.append("")

        if q.passage:
            lines.append(f"**지문:** {q.passage}")
            lines.append("")

        if q.choices:
            lines.append("**선택지:**")
            for choice in q.choices:
                idx = choice.number - 1
                symbol = CIRCLE_NUMBERS[idx] if 0 <= idx < len(CIRCLE_NUMBERS) else f"{choice.number}."
                lines.append(f"{symbol} {choice.text}")
            lines.append("")

        if is_listening(q):
            lines.append("**해설:** ⏭️ 듣기 문제 - 해설 생략")
        else:
            explanation = getattr(q, "explanation", None)
            if explanation:
                lines.append(f"**해설:** {explanation}")
            else:
                lines.append("**해설:** (해설 없음)")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def process_pdf(
    pdf_path: Path,
    model: str,
    llm: str,
    output_dir: Path,
    skip_explain: bool,
    dpi: int,
) -> dict:
    """단일 PDF 처리: 파싱 → 해설 → 저장. 결과 요약 dict 반환."""
    result = {
        "pdf": pdf_path.name,
        "status": "pending",
        "questions": 0,
        "explained": 0,
        "json_path": None,
        "md_path": None,
        "error": None,
    }

    # Step 1: Parse PDF
    console.print(f"  [cyan]Step 1:[/cyan] Parsing with [bold]{model}[/bold]...")
    try:
        exam_parser = ExamParser(str(pdf_path), dpi=dpi)
        parse_result = exam_parser.parse_with_model(model)
        parsed_exam = parse_result.parsed_exam
        n_q = len(parsed_exam.questions)
        console.print(
            f"    [green]✓[/green] Parsed {n_q} questions "
            f"(${parse_result.total_cost_usd:.4f}, {parse_result.parsing_time_seconds:.1f}s)"
        )
        result["questions"] = n_q
    except Exception as e:
        result["status"] = "parse_failed"
        result["error"] = f"Parse error: {e}"
        console.print(f"    [red]✗ Parse failed:[/red] {e}")
        return result

    # Step 2: Add explanations
    if not skip_explain:
        console.print(f"  [cyan]Step 2:[/cyan] Generating explanations with [bold]{llm}[/bold]...")
        try:
            from src.explainer import add_explanations
            parsed_exam = add_explanations(parsed_exam, llm_name=llm)
            explained_count = sum(
                1 for q in parsed_exam.questions
                if not is_listening(q) and getattr(q, "explanation", None)
            )
            console.print(f"    [green]✓[/green] Explanations added to {explained_count} questions")
            result["explained"] = explained_count
        except ImportError:
            console.print("    [yellow]⚠ src.explainer not available — skipping explanations[/yellow]")
        except Exception as e:
            console.print(f"    [yellow]⚠ Explanation error:[/yellow] {e} — saving without explanations")
    else:
        console.print("  [dim]Step 2: Skipped (--skip-explain)[/dim]")

    # Step 3: Save JSON
    pdf_stem = pdf_path.stem
    json_path = output_dir / f"{pdf_stem}.json"
    console.print(f"  [cyan]Step 3:[/cyan] Saving JSON → {json_path.name}")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(parsed_exam.model_dump(), f, ensure_ascii=False, indent=2)
        result["json_path"] = str(json_path)
        console.print(f"    [green]✓[/green] JSON saved")
    except Exception as e:
        console.print(f"    [red]✗ JSON save failed:[/red] {e}")

    # Step 4: Save Markdown summary
    md_path = output_dir / f"{pdf_stem}_summary.md"
    console.print(f"  [cyan]Step 4:[/cyan] Saving Markdown summary → {md_path.name}")
    try:
        md_content = build_markdown_summary(parsed_exam)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        result["md_path"] = str(md_path)
        console.print(f"    [green]✓[/green] Markdown saved")
    except Exception as e:
        console.print(f"    [red]✗ Markdown save failed:[/red] {e}")

    result["status"] = "success"
    return result


def print_final_table(summaries: list[dict]) -> None:
    """최종 처리 결과 Rich 테이블 출력"""
    table = Table(title="Full Flow Summary", show_lines=True)
    table.add_column("PDF", style="cyan", no_wrap=False)
    table.add_column("Status", justify="center")
    table.add_column("Questions", justify="right", style="green")
    table.add_column("Explained", justify="right", style="yellow")
    table.add_column("Output", style="dim")

    for s in summaries:
        status_str = "[green]✓ OK[/green]" if s["status"] == "success" else f"[red]✗ {s['status']}[/red]"
        q_str = str(s["questions"]) if s["questions"] else "-"
        ex_str = str(s["explained"]) if s["explained"] else "-"
        out = ""
        if s["json_path"]:
            out = Path(s["json_path"]).name
        elif s["error"]:
            out = s["error"][:50]
        table.add_row(s["pdf"], status_str, q_str, ex_str, out)

    console.print(table)


def main():
    args = parse_args()

    pdf_paths = [Path(p) for p in args.pdfs] if args.pdfs else [Path(p) for p in DEFAULT_PDFS]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold]Model:[/bold] {args.model}\n"
        f"[bold]LLM:[/bold] {args.llm}\n"
        f"[bold]PDFs:[/bold] {len(pdf_paths)}\n"
        f"[bold]Output:[/bold] {output_dir}\n"
        f"[bold]Skip Explain:[/bold] {args.skip_explain}",
        title="[bold blue]Full Flow Pipeline[/bold blue]",
        border_style="blue",
    ))

    summaries: list[dict] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        overall = progress.add_task("Processing PDFs...", total=len(pdf_paths))

        for pdf_path in pdf_paths:
            progress.update(overall, description=f"[cyan]{pdf_path.name}[/cyan]")
            console.print(f"\n[bold]{'─'*60}[/bold]")
            console.print(f"[bold magenta]PDF:[/bold magenta] {pdf_path}")

            if not pdf_path.exists():
                console.print(f"  [red]✗ File not found:[/red] {pdf_path}")
                summaries.append({
                    "pdf": pdf_path.name,
                    "status": "not_found",
                    "questions": 0,
                    "explained": 0,
                    "json_path": None,
                    "md_path": None,
                    "error": "File not found",
                })
                progress.advance(overall)
                continue

            summary = process_pdf(
                pdf_path=pdf_path,
                model=args.model,
                llm=args.llm,
                output_dir=output_dir,
                skip_explain=args.skip_explain,
                dpi=args.dpi,
            )
            summaries.append(summary)
            progress.advance(overall)

    console.print(f"\n[bold]{'─'*60}[/bold]")
    print_final_table(summaries)

    # Save run metadata
    meta_path = output_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "model": args.model,
                "llm": args.llm,
                "skip_explain": args.skip_explain,
                "dpi": args.dpi,
                "pdfs_processed": len(summaries),
                "results": summaries,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    console.print(f"\n[green]Run metadata saved to:[/green] {meta_path}")


if __name__ == "__main__":
    main()
