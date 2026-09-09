# ── Hermes Agent — Docker image for RunPod persistent pod ─────────────────
# Base: Python 3.11 slim (no GPU needed unless using HF_DEVICE=cuda)
# For GPU support swap base to: pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime
FROM python:3.11-slim

# Install system deps (chromium for scraper_agent if needed, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Remove Windows-specific files and local venv
RUN rm -f start.bat .hermes.lock || true

# Expose WebUI port (optional, only if you enable webui)
EXPOSE 7860

# Health check: verify the process is alive
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD pgrep -f "python main.py" > /dev/null || exit 1

# Startup
CMD ["/bin/bash", "start.sh"]
