# ─────────────────────────────────────────────────
# Dockerfile — Gemini Cloud Sentinel
# Multi-stage build for a lean production image
# ─────────────────────────────────────────────────

# ── Stage 1: Build deps ───────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


# ── Stage 2: Production image ─────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Gemini Cloud Sentinel"
LABEL org.opencontainers.image.description="Self-healing Infrastructure Governance Bot"
LABEL org.opencontainers.image.source="https://github.com/CloudWatchtower"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application source
COPY sentinel/ ./sentinel/

# Ensure local pip packages are on PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose MCP server port
EXPOSE 8000

# ── Default command: start the MCP server ─────────
# Override with:
#   docker run ... python -m sentinel.sentinel --mode review ...
#   docker run ... python -m sentinel.auto_remediate ...
CMD ["uvicorn", "sentinel.mcp_server:app", "--host", "0.0.0.0", "--port", "8000"]
