# Exam PDF Parser — Web Service Design

## Overview

This document covers the architecture for deploying the 3-layer exam PDF parsing pipeline
(Document Parser → LLM Structuring → Validation) as a web service.

---

## 1. Deployment Options

### Option A: Cloud VM with GPU (Recommended for MinerU)

| Cloud | Instance | GPU | vRAM | ~Cost/hr |
|-------|----------|-----|------|----------|
| GCP | `n1-standard-4` + `nvidia-t4` | T4 | 16 GB | $0.35 |
| AWS | `g4dn.xlarge` | T4 | 16 GB | $0.53 |
| Azure | `Standard_NC4as_T4_v3` | T4 | 16 GB | $0.53 |
| RunPod | GPU pod | RTX 3090 | 24 GB | $0.22 |

**Why GPU?** MinerU uses deep-learning PDF layout models (LayoutLMv3, YOLO) that
are 10–30× faster on CUDA vs CPU. Minimum: 4 GB VRAM; recommended: 16 GB.

### Option B: CPU-only Server (Marker / Docling / API-based)

For Marker + Gemini or Docling + Gemini pipelines you do **not** need a GPU.
A 4-core/8 GB RAM VPS ($20–40/month) is sufficient.

### Option C: Serverless (Gemini API only, no heavy doc parsers)

Use Cloud Run / Lambda with `pymupdf-text+gemini-3-flash-preview`.
Cold starts ~2 s; no GPU; pay-per-request. Not compatible with MinerU/Marker.

---

## 2. MinerU GPU Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ |
| PyTorch | 2.x with CUDA 11.8 or 12.1 |
| CUDA driver | 520+ |
| VRAM | 4 GB minimum, 8 GB recommended |
| RAM | 16 GB recommended |
| Disk | ~10 GB model weights |

MinerU downloads models on first run (LayoutReader, DocLayout-YOLO, UniMERNet).
Pre-download in Docker build step to avoid cold-start delays.

---

## 3. Gemini API Integration

- **Key management**: `GOOGLE_API_KEY` in `.env` / secret manager. Never hardcode.
- **Rate limits**:
  - Free tier: 60 RPM, 1500 RPD for Flash; 2 RPM, 50 RPD for Pro
  - Paid tier: 1000 RPM for Flash; 60 RPM for Pro
- **Recommended model**: `gemini-3-flash-preview` for cost (~$0.0002/exam)
- **Pro model**: `gemini-3-pro-preview` for accuracy (~$0.002/exam)

---

## 4. Async Processing Architecture

```
Client
  │
  ├─ POST /api/parse/async  ──► Enqueue job (in-memory or Redis)
  │                              returns {job_id}
  │
  ├─ GET /api/jobs/{job_id}  ──► Poll status: pending|running|done|failed
  │
  └─ (on done) result embedded in GET response or POST /api/parse (sync)

Background Worker
  └─ asyncio.Queue / ThreadPoolExecutor
       └─ ExamParser.parse_with_model()  (blocking, runs in thread)
```

For production use Redis + Celery or RQ. For single-server use the built-in
`asyncio` background queue (implemented in `server.py`).

---

## 5. File Upload & Temp Storage

- Upload limit: **50 MB** per file (configurable via `MAX_FILE_SIZE_MB`)
- Temp dir: `$TMPDIR/exam-parser-uploads/` (auto-cleaned after job completion)
- Cleanup: immediate on sync parse; deferred (1 hour TTL) for async jobs
- Never store PDFs on disk longer than necessary — treat as transient

---

## 6. Cost Estimation Per Request

| Model | Pages | Input tokens | Output tokens | Cost (USD) |
|-------|-------|-------------|---------------|------------|
| marker+gemini-3-flash-preview | 16 | ~15K | ~8K | ~$0.0002 |
| mineru+gemini-3-flash-preview | 16 | ~20K | ~8K | ~$0.0003 |
| marker+gemini-3-pro-preview | 16 | ~15K | ~8K | ~$0.0019 |
| marker+gpt-5.1 | 16 | ~15K | ~8K | ~$0.0038 |

GPU inference (MinerU): ~$0.001–0.003/request at $0.35/hr GPU × ~5–10 min parse time.

---

## 7. Docker Deployment

### CPU-only (Marker + Gemini)
```bash
docker build -f Dockerfile -t exam-parser:cpu .
docker run -p 8000:8000 -e GOOGLE_API_KEY=... exam-parser:cpu
```

### GPU (MinerU + Gemini)
```bash
docker build -f Dockerfile.gpu -t exam-parser:gpu .
docker run --gpus all -p 8000:8000 -e GOOGLE_API_KEY=... exam-parser:gpu
```

### Health & readiness
```
GET /health           → {"status": "ok", "version": "1.0.0"}
GET /api/models       → list of available model strings
```

---

## 8. API Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/models` | List available models |
| POST | `/api/parse` | Sync parse (≤5 pages recommended) |
| POST | `/api/parse/async` | Async parse → job_id |
| GET | `/api/jobs/{job_id}` | Poll job status |
| POST | `/api/validate` | Validate a ParsedExam JSON |

---

## 9. Security Considerations

- Validate MIME type (must be `application/pdf`) before processing
- Reject files > 50 MB before reading content
- Sanitize file names; never expose original path in responses
- API keys must come from environment, never from request body
- Rate-limit per IP using a middleware or reverse proxy (nginx, Cloudflare)
- CORS: restrict `allow_origins` to your frontend domain in production
