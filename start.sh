#!/bin/bash
# start.sh — Hermes startup script for RunPod / Linux containers
set -e

echo "═══════════════════════════════════════════════"
echo "  Hermes Agent — Starting on RunPod"
echo "═══════════════════════════════════════════════"

# Validate critical env vars
if [ -z "$TELEGRAM_TOKEN" ]; then
    echo "[ERROR] TELEGRAM_TOKEN is not set. Set it in RunPod Environment Variables."
    exit 1
fi

# Optional: start WebUI in background if WEBUI_ENABLED=true
if [ "${WEBUI_ENABLED:-false}" = "true" ]; then
    echo "[INFO] Starting WebUI on port 7860..."
    python webui/app.py &
    sleep 2
fi

# Start Hermes Telegram bot (foreground — keeps container alive)
echo "[INFO] Starting Hermes Telegram bot..."
exec python main.py
