# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

General-purpose Korean/English exam PDF parser. 3-layer pipeline: Document Parsers → LLM Structuring → Validation. Extracts questions from any exam type into structured JSON with auto-detection of language and subject.

## Commands

```bash
# Install (UV recommended)
uv pip install -e ".[all]"          # everything (including doc parsers)
uv pip install -e ".[doc-parsers]"  # marker, mineru, docling
uv pip install -e ".[dev]"          # + pytest, black, ruff

# Parse single PDF
python main.py test/2025년-9월-고3-모의고사-영어-문제.pdf -m marker+gemini-3-flash-preview -o output/result.json

# Parse with all models (comparison)
python main.py test/2025년-9월-고3-모의고사-영어-문제.pdf

# Parse with validation
python main.py test/2025년-9월-고3-모의고사-영어-문제.pdf -m marker+gemini-3-flash-preview --validate --answer-key test/answer.md

# Model comparison with accuracy evaluation
python scripts/run_comparison.py test/2025년-9월-고3-모의고사-영어-문제.pdf \
  --answer test/answer.md \
  --models marker+gemini-3-flash-preview,docling+gpt-5.1 \
  --output output/comparison/ \
  --report output/report.md

# List models/parsers
python main.py --list-models
python main.py --list-ocr

# Batch processing (500+ PDFs)
python scripts/batch_parser.py ./exams/ -m marker+gemini-3-flash-preview -w 8 -o results/

# Dev tools
black src/ scripts/ --line-length 120
ruff check src/ scripts/ --fix
pytest tests/
```

## Architecture

3-layer pipeline producing `ParsedExam` (Pydantic). All models use hybrid format `{parser}+{llm}` (e.g., `marker+gemini-3-flash-preview`): Layer 1 parser extracts text/markdown, Layer 2 LLM structures it into JSON, Layer 3 validates.

**Key abstractions:**
- `ModelClient` (ABC, `src/models/base.py`) — LLM clients. `parse_exam(images) → ParsedExam`
- `OCREngine` (ABC, `src/ocr/base.py`) — document parsers. Lazy init via `_ensure_initialized()`
- `HybridOCRClient` (`src/models/hybrid_client.py`) — composes parser + LLM
- `ExamParser` (`src/parser.py`) — main orchestrator
- `PDFParser` (`src/pdf_parser.py`) — PDF→PNG via PyMuPDF. `get_page_images_as_bytes() → List[Tuple[bytes, mime]]`

**Supported parsers (Layer 1):** marker, mineru, docling (deep learning, recommended); pymupdf-text, tesseract, easyocr, paddleocr, surya, trocr, deepseek-ocr (traditional)

**LLM backends (Layer 2):** gemini-3-flash-preview (cheapest, recommended), gpt-5.1

**Adding new parser:** subclass `OCREngine`, implement `set_pdf_path()` + `extract_from_pdf()`, register in `OCR_ENGINES` in `src/ocr/__init__.py`

**Adding new LLM:** add pricing to `_LLM_PRICING` in `src/config.py`, add to `_LLM_BACKENDS`, implement `_call_*` in `src/models/hybrid_client.py`

## Data Models (`src/schema.py`)

`ParsedExam` → `ExamInfo` + `list[Question]`. `Question` fields: number, question_text, question_type (19 enum types), passage, choices, points, vocabulary_notes, image/table flags, sub_questions, group_range. `ExamInfo` fields: title, year, month, grade, subject (auto-detected), total_questions (dynamic).

## Evaluation and Validation

`src/evaluator.py`: `parse_answer_md(filepath) → AnswerKey`; `evaluate(parsed_exam, answer_key) → EvalResult`. Weighted scoring: coverage 30%, passage similarity 30%, choice accuracy 25%, question text similarity 15%.

`src/validator.py`: `validate_exam(parsed_exam, answer_key?) → ValidationResult`. Checks: schema completeness, numbering continuity, choice count (5 per MCQ), passage presence, answer key cross-reference.

## Configuration

- API keys in `.env`: `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Model pricing auto-generated from `_LLM_PRICING` x `_DOCUMENT_PARSERS` in `src/config.py`
- Settings singleton via `get_settings()` with `@lru_cache()`
- LLM prompt in `src/prompt.py` — temperature 0.1, Korean-primary, auto-detects exam type

## Code style

- Line length: 120 (both black and ruff)
- Ruff rules: E, F, I, W
- Python 3.12 (`.python-version`)
- Bilingual comments (Korean/English) are normal
- Google-style docstrings
