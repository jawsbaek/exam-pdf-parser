# ============================================================
# Exam PDF Parser — CPU Dockerfile (Marker / Docling + Gemini)
# For MinerU + GPU support use Dockerfile.gpu
# ============================================================
FROM python:3.12-slim

# System dependencies for PyMuPDF and document parsers
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmupdf-dev \
        libfreetype6 \
        libharfbuzz0b \
        libopenjp2-7 \
        libjpeg-turbo-progs \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

# Copy project definition first (layer cache)
COPY pyproject.toml ./
COPY README.md ./

# Install base + web deps (no heavy doc parsers in CPU image by default)
RUN uv pip install --system -e ".[web]"

# Copy source
COPY src/ ./src/
COPY main.py ./

# Non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Temp directory for uploads (writable by appuser)
RUN mkdir -p /tmp/exam-parser-uploads

EXPOSE 8000

# Default: run with 2 workers (adjust for your CPU count)
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
