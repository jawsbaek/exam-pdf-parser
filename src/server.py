"""
FastAPI web server for exam PDF parsing service.
시험 문제 PDF 파싱 서비스 웹 서버입니다.

Endpoints:
  POST /api/parse          - sync PDF parsing (small PDFs, ≤5 pages recommended)
  POST /api/parse/async    - async parsing with job ID polling
  GET  /api/jobs/{job_id}  - check async job status
  GET  /api/models         - list available models
  POST /api/validate       - validate a ParsedExam against schema
  GET  /health             - health check
"""

import asyncio
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import MODEL_CONFIG, get_settings
from .parser import ExamParser
from .schema import ParsedExam, ParseResult
from .validator import ValidationResult, validate_exam

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_JOB_TTL_SECONDS = 3600  # 1 hour — jobs are cleaned up after this

# ---------------------------------------------------------------------------
# Job store (in-memory; replace with Redis for multi-process deployments)
# ---------------------------------------------------------------------------

JobStatus = Literal["pending", "running", "done", "failed"]


class JobRecord(BaseModel):
    job_id: str
    status: JobStatus = "pending"
    model_name: str
    created_at: str
    finished_at: str | None = None
    result: ParseResult | None = None
    error: str | None = None


_jobs: dict[str, JobRecord] = {}
_job_queue: asyncio.Queue = asyncio.Queue()


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


async def _worker():
    """Consume jobs from the queue and run them in a thread pool."""
    loop = asyncio.get_running_loop()
    while True:
        job_id, pdf_path, model_name, instruction = await _job_queue.get()
        record = _jobs.get(job_id)
        if record is None:
            _job_queue.task_done()
            continue

        record.status = "running"
        try:
            result = await loop.run_in_executor(
                None,
                _run_parse_sync,
                pdf_path,
                model_name,
                instruction,
            )
            record.result = result
            record.status = "done"
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            record.error = str(exc)
            record.status = "failed"
        finally:
            record.finished_at = datetime.now(timezone.utc).isoformat()
            # Cleanup temp file
            try:
                Path(pdf_path).unlink(missing_ok=True)
            except OSError:
                pass
            _job_queue.task_done()


def _run_parse_sync(pdf_path: str, model_name: str, instruction: str | None) -> ParseResult:
    """Blocking parse — runs inside a thread pool executor."""
    parser = ExamParser(pdf_path)
    return parser.parse_with_model(model_name, instruction=instruction)


async def _cleanup_expired_jobs():
    """Periodically remove completed/failed jobs older than _JOB_TTL_SECONDS."""
    while True:
        await asyncio.sleep(300)  # run every 5 minutes
        now = datetime.now(timezone.utc)
        expired = []
        for job_id, record in _jobs.items():
            if record.status not in ("done", "failed") or not record.finished_at:
                continue
            finished = datetime.fromisoformat(record.finished_at)
            if (now - finished).total_seconds() > _JOB_TTL_SECONDS:
                expired.append(job_id)
        for job_id in expired:
            del _jobs[job_id]
        if expired:
            logger.info("Cleaned up %d expired jobs", len(expired))


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate at least one API key is present
    settings = get_settings()
    if not settings.GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not configured — parsing will fail unless the key is set at runtime")

    worker_task = asyncio.create_task(_worker())
    cleanup_task = asyncio.create_task(_cleanup_expired_jobs())
    yield
    worker_task.cancel()
    cleanup_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Exam PDF Parser API",
    description="Parse Korean/English exam PDFs using Document Parser + LLM (3-layer architecture)",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ParseResponse(BaseModel):
    model_name: str
    parsed_exam: ParsedExam
    total_tokens_input: int
    total_tokens_output: int
    total_cost_usd: float
    parsing_time_seconds: float
    pages_processed: int
    error: str | None = None


class AsyncParseResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    model_name: str
    created_at: str
    finished_at: str | None = None
    result: ParseResult | None = None
    error: str | None = None


class ModelInfo(BaseModel):
    model_name: str
    ocr_engine: str
    llm_model: str
    input_price_per_1m: float
    output_price_per_1m: float


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class ValidateRequest(BaseModel):
    parsed_exam: ParsedExam
    expected_questions: int | None = Field(None, description="Override expected question count")


class ValidateResponse(BaseModel):
    is_valid: bool
    total_errors: int
    total_warnings: int
    issues: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _save_upload(upload: UploadFile) -> str:
    """Save uploaded file to a temp location, return the path.

    Validates MIME type before reading, then streams in chunks to enforce size limit
    without buffering the entire file in memory.
    """
    # MIME check before reading content
    if not (
        upload.content_type == "application/pdf"
        or (upload.filename or "").lower().endswith(".pdf")
    ):
        raise HTTPException(status_code=415, detail="Only PDF files are supported")

    suffix = ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="exam-")
    try:
        total_size = 0
        chunk_size = 1024 * 1024  # 1 MB chunks
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_FILE_SIZE_BYTES:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE_BYTES // 1024 // 1024} MB)")
            tmp.write(chunk)
        tmp.flush()
        tmp.close()
    except HTTPException:
        raise
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    return tmp.name


def _validate_model(model_name: str) -> None:
    if model_name not in MODEL_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{model_name}'. Call GET /api/models for valid options.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
async def health():
    """Health check."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/models", response_model=ModelsResponse, tags=["meta"])
async def list_models():
    """List all available parser+LLM model combinations."""
    models = [
        ModelInfo(
            model_name=name,
            ocr_engine=cfg["ocr_engine"],
            llm_model=cfg["llm_model"],
            input_price_per_1m=cfg["input_price_per_1m"],
            output_price_per_1m=cfg["output_price_per_1m"],
        )
        for name, cfg in MODEL_CONFIG.items()
    ]
    return ModelsResponse(models=models)


@app.post("/api/parse", response_model=ParseResponse, tags=["parse"])
async def parse_sync(
    file: UploadFile = File(..., description="PDF file to parse"),
    model: str = Form(default="mineru+gemini-3-pro-preview", description="Model string e.g. mineru+gemini-3-pro-preview"),
    instruction: str | None = Form(default=None, description="Optional custom instruction prompt"),
):
    """
    Synchronous PDF parsing. Blocks until complete.

    Recommended for small PDFs (≤5 pages). For larger files use POST /api/parse/async.
    """
    _validate_model(model)
    pdf_path = await _save_upload(file)

    loop = asyncio.get_running_loop()
    try:
        result: ParseResult = await loop.run_in_executor(
            None, _run_parse_sync, pdf_path, model, instruction
        )
    except Exception as exc:
        logger.exception("Sync parse failed")
        raise HTTPException(status_code=500, detail="PDF parsing failed. Check server logs for details.") from exc
    finally:
        try:
            Path(pdf_path).unlink(missing_ok=True)
        except OSError:
            pass

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return ParseResponse(
        model_name=result.model_name,
        parsed_exam=result.parsed_exam,
        total_tokens_input=result.total_tokens_input,
        total_tokens_output=result.total_tokens_output,
        total_cost_usd=result.total_cost_usd,
        parsing_time_seconds=result.parsing_time_seconds,
        pages_processed=result.pages_processed,
    )


@app.post("/api/parse/async", response_model=AsyncParseResponse, tags=["parse"])
async def parse_async(
    file: UploadFile = File(..., description="PDF file to parse"),
    model: str = Form(default="mineru+gemini-3-pro-preview"),
    instruction: str | None = Form(default=None),
):
    """
    Asynchronous PDF parsing. Returns a job_id immediately.

    Poll GET /api/jobs/{job_id} to check status and retrieve results.
    """
    _validate_model(model)
    pdf_path = await _save_upload(file)

    job_id = str(uuid.uuid4())
    record = JobRecord(
        job_id=job_id,
        model_name=model,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _jobs[job_id] = record

    await _job_queue.put((job_id, pdf_path, model, instruction))

    return AsyncParseResponse(
        job_id=job_id,
        status="pending",
        message=f"Job enqueued. Poll GET /api/jobs/{job_id} for status.",
    )


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse, tags=["parse"])
async def get_job(job_id: str):
    """Check the status of an async parsing job."""
    record = _jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        model_name=record.model_name,
        created_at=record.created_at,
        finished_at=record.finished_at,
        result=record.result,
        error=record.error,
    )


@app.post("/api/validate", response_model=ValidateResponse, tags=["validate"])
async def validate(body: ValidateRequest):
    """
    Validate a ParsedExam JSON for structural completeness.

    Pass the `parsed_exam` object from a /api/parse response to check for errors.
    """
    loop = asyncio.get_running_loop()
    validation: ValidationResult = await loop.run_in_executor(
        None,
        validate_exam,
        body.parsed_exam,
        None,  # no answer key via API (upload not yet supported here)
        body.expected_questions,
    )
    return ValidateResponse(
        is_valid=validation.is_valid,
        total_errors=validation.total_errors,
        total_warnings=validation.total_warnings,
        issues=[issue.model_dump() for issue in validation.issues],
    )
