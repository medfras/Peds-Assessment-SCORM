FROM python:3.11-slim

WORKDIR /app

# Install curl for HEALTHCHECK; install deps from audited lockfile
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies from the audited lockfile (exact pins, matches CI pip-audit)
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# Copy application code
COPY app/ ./app/
COPY static/ ./static/

# Non-root user — runs as UID 1001 (INF-05)
RUN adduser --uid 1001 --no-create-home --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe — process must be up and accepting connections (INF-04)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
