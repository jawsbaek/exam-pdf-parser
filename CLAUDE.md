# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean/English exam PDF parser focused on MinerU + Gemini 3 Pro pipeline. 3-layer architecture: MinerU (Document Parser) → Gemini Pro (LLM Structuring) → Validation. Extracts questions from Korean CSAT/mock exams into structured JSON. Also serves as a FastAPI web service.

## Commands

```bash
# Install (UV recommended)
uv pip install -e ".[doc-mineru]"    # MinerU document parser
uv pip install "mineru[core]"        # MinerU full dependencies (torch, doclayout-yolo, etc.)
uv pip install -e ".[web]"           # FastAPI web server
uv pip install -e ".[dev]"           # + pytest, black, ruff

# Parse single PDF (use .venv python)
.venv/bin/python main.py test/2025년-9월-고3-모의고사-영어-문제.pdf -m mineru+gemini-3-pro-preview -o output/result.json

# Parse with validation
.venv/bin/python main.py test/2025년-9월-고3-모의고사-영어-문제.pdf -m mineru+gemini-3-pro-preview --validate --answer-key test/answer.md

# List models/parsers
.venv/bin/python main.py --list-models
.venv/bin/python main.py --list-ocr

# Run web server
uvicorn src.server:app --host 0.0.0.0 --port 8000

# Docker (CPU)
docker build -t exam-parser .
docker run -p 8000:8000 -e GOOGLE_API_KEY=... exam-parser

# Dev tools
black src/ scripts/ --line-length 120
ruff check src/ scripts/ --fix
pytest tests/
```

## Architecture

3-layer pipeline producing `ParsedExam` (Pydantic). Primary model: `mineru+gemini-3-pro-preview`. Layer 1 MinerU extracts text/markdown, Layer 2 Gemini Pro structures it into JSON, Layer 3 validates.

**Key abstractions:**
- `ModelClient` (ABC, `src/models/base.py`) — LLM clients. `parse_exam(images) → ParsedExam`
- `OCREngine` (ABC, `src/ocr/base.py`) — document parsers. Lazy init via `_ensure_initialized()`
- `HybridOCRClient` (`src/models/hybrid_client.py`) — composes parser + LLM
- `ExamParser` (`src/parser.py`) — main orchestrator
- `PDFParser` (`src/pdf_parser.py`) — PDF→PNG via PyMuPDF. `get_page_images_as_bytes() → List[Tuple[bytes, mime]]`

**Document Parser (Layer 1):** MinerU v2.x (`src/ocr/mineru_ocr.py`) — GPU recommended (CUDA 11.8+, 4GB+ VRAM), CPU fallback supported

**LLM Backend (Layer 2):** gemini-3-pro-preview via google-genai SDK

**Adding new parser:** subclass `OCREngine`, implement `set_pdf_path()` + `extract_from_pdf()`, register in `OCR_ENGINES` in `src/ocr/__init__.py`

**Adding new LLM:** add pricing to `_LLM_PRICING` in `src/config.py`, add to `_LLM_BACKENDS`, implement `_call_*` in `src/models/hybrid_client.py`

## Web Server (`src/server.py`)

FastAPI web service for PDF parsing. See `DESIGN.md` for full architecture.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/parse` | Sync PDF parsing |
| POST | `/api/parse/async` | Async parsing → job_id |
| GET | `/api/jobs/{job_id}` | Poll job status |
| GET | `/api/models` | List available models |
| POST | `/api/validate` | Validate ParsedExam JSON |
| GET | `/health` | Health check |

**Auth:** `src/auth.py` — API key via `X-API-Key` header or `api_key` query param. Set `API_KEYS` env var (comma-separated). Disabled when unset (dev mode).

## Data Models (`src/schema.py`)

`ParsedExam` → `ExamInfo` + `list[Question]`. `Question` fields: number, question_text, question_type (22 enum types including 듣기/서술형/오류수정/배열/문장전환), passage, choices, points, vocabulary_notes, image/table flags, sub_questions, group_range. `ExamInfo` fields: title, year, month, grade, subject (auto-detected), total_questions (dynamic).

## Evaluation and Validation

`src/evaluator.py`: `parse_answer_md(filepath) → AnswerKey`; `evaluate(parsed_exam, answer_key) → EvalResult`. Weighted scoring: coverage 30%, passage similarity 30%, choice accuracy 25%, question text similarity 15%.

`src/validator.py`: `validate_exam(parsed_exam, answer_key?) → ValidationResult`. Checks:
- Schema completeness (required fields, point values 1-5, question_type set)
- Numbering continuity (gaps, duplicates, count mismatch)
- Choice count (5 per MCQ), choice numbering, empty text, duplicate choices
- Passage presence for passage-required types, short passage warning (<20 chars)
- **Listening questions** (1-17): type=LISTENING enforcement, no passage, choices required
- **Group questions**: group_range "N~M" format, member completeness, first question passage
- **Content quality**: duplicate question_text, duplicate choices, image/table description consistency
- Answer key cross-reference (if provided)

## Configuration

- API keys in `.env`: `GOOGLE_API_KEY` (required)
- Pipeline: MinerU + Gemini 3 Pro (`mineru+gemini-3-pro-preview`)
- Settings singleton via `get_settings()` with `@lru_cache()`
- LLM prompt in `src/prompt.py` — temperature 0.1, Korean-primary, dedicated listening question section, auto-detects exam type

### MinerU OCR Settings (env vars in `.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `MINERU_LANGUAGE` | `korean` | OCR language (`korean`, `en`, `ch`, `japan`) |
| `MINERU_PARSE_METHOD` | `auto` | `auto` (detect text/scan), `ocr` (force OCR), `txt` (text-only) |
| `MINERU_FORMULA_ENABLE` | `true` | Formula detection — disable for non-math exams to speed up |
| `MINERU_TABLE_ENABLE` | `true` | Table detection — keep enabled for vocabulary/grammar tables |
| `MINERU_MAKE_MODE` | `mm_markdown` | `mm_markdown` (full: tables + images), `nlp_markdown` (text only) |

`MinerUOCREngine` (`src/ocr/mineru_ocr.py`) accepts these via constructor or `configure()` method. `HybridOCRClient` auto-applies settings from `get_settings()` at init.

## Known Gotchas

- Always use `llm_name` as the parameter name (not `llm`). `add_explanations()` and `full_flow.py` expect `llm_name`.
- MinerU v2.x restructured its API — use `mineru.pdf_extract` not legacy imports.
- When running long processes (MinerU parsing, full pipeline tests), run them in the background rather than blocking interactively.

## Architecture Guardrails

- This project uses a settled 3-layer architecture: **Layer 1** MinerU for OCR/document parsing, **Layer 2** Gemini Pro for LLM structuring, **Layer 3** `validator.py` for validation.
- **Never** use vision-based direct LLM parsing or alternative OCR engines unless explicitly asked.
- Do not explore hybrid approaches or parser alternatives — the pipeline is decided.

## Verification

After editing Python files, always verify before considering work complete:
1. `python -m py_compile <file>` — syntax check
2. `ruff check src/ --fix` — lint and auto-fix
3. `python -c 'import <module>'` — import check for modified modules

## Code style

- Line length: 120 (both black and ruff)
- Ruff rules: E, F, I, W
- Python 3.12 (`.python-version`)
- Use modern Python 3.12+ syntax: `type X = ...` aliases, `match` statements, `X | Y` unions instead of `Union[X, Y]`
- Bilingual comments (Korean/English) are normal
- Google-style docstrings
