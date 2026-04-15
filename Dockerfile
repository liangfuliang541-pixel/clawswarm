# ClawSwarm Dockerfile
# Multi-stage build for small image size

FROM python:3.12-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Stage 1: Install dependencies ──────────────────────────────────────────
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime image ──────────────────────────────────────────────────
FROM base AS runtime

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Install optional but recommended packages for observability
RUN pip install --no-cache-dir \
    websockets>=11.0 \
    opentelemetry-api>=1.20 \
    opentelemetry-sdk>=1.20 \
    opentelemetry-exporter-otlp>=1.20

# Copy project
COPY . .

# Environment defaults
ENV CLAWSWARM_BASE_DIR=/data/swarm
ENV CLAWSWARM_ENV=production
ENV CLAWSWARM_OTEL_ENABLED=false

# Create swarm directories
RUN mkdir -p $CLAWSWARM_BASE_DIR/{queue,in_progress,results,agents,memory,logs,checkpoint}

# Expose ports
# 5000 - Master API
# 5171 - Node API (base port, +1 per additional node)
# 8765 - WebSocket Event Server

EXPOSE 5000 5171 5172 5173 8765

# Default command: start master API
CMD ["python", "master_api.py"]

# ── Development image ────────────────────────────────────────────────────────
FROM runtime AS dev

RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    black \
    ruff

COPY . .

CMD ["python", "-m", "pytest", "tests/", "-v"]
