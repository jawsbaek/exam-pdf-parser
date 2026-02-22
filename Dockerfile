# ============================================================
# Exam PDF Parser — Production Dockerfile
# Multi-stage build for minimal image size
# ============================================================

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        libmupdf-dev \
        libfreetype6-dev \
        libharfbuzz-dev \
        libopenjp2-7-dev \
        libjpeg-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache ".[web]"

COPY src/ ./src/
COPY main.py ./
RUN uv pip install --system --no-cache -e .

# --- Stage 2: Runtime ---
FROM python:3.12-slim AS runtime

# Runtime-only system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmupdf-dev \
        libfreetype6 \
        libharfbuzz0b \
        libopenjp2-7 \
        libjpeg-turbo-progs \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ ./src/
COPY main.py ./

# Non-root user
RUN useradd -m -u 1001 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /tmp/exam-parser-uploads \
    && chown appuser:appuser /tmp/exam-parser-uploads

USER appuser

# Environment defaults (override at deploy time)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    UVICORN_WORKERS=2

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use tini for proper signal handling (PID 1 reaping)
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--access-log"]
