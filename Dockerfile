# Multi-stage production Dockerfile for Hong Kong Weather Prediction Agent
FROM python:3.13-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Runtime Stage
FROM python:3.13-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create unprivileged user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/backups /app/logs && \
    chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .

USER appuser

ENV PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "from app.jobs.health import run_health_check_job; res = run_health_check_job(); exit(0 if res.get('is_healthy') else 1)"

CMD ["python", "-m", "app.jobs.scheduler"]
