# GistFlow Dockerfile
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better cache
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim

# Labels
LABEL maintainer="GistFlow Team"
LABEL description="Automated ETL pipeline for processing Gmail newsletters into structured Notion knowledge"
LABEL version="0.1.0"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd -r gistflow && useradd -r -g gistflow gistflow

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=gistflow:gistflow gistflow ./gistflow
COPY --chown=gistflow:gistflow main.py .

# Create directories for data and logs
RUN mkdir -p /app/data /app/logs && \
    chown -R gistflow:gistflow /app/data /app/logs

# Switch to non-root user
USER gistflow

# Health check
HEALTHCHECK --interval=5m --timeout=30s --start-period=10s --retries=3 \
    CMD python -c "from gistflow.config import get_settings; get_settings()" || exit 1

# Default command
CMD ["python", "main.py"]