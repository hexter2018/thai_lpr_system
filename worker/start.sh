#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=/app

echo "[worker] Starting Thai LPR Worker..."
echo "[worker] Python version:"
python3 --version

echo "[worker] Checking GPU..."
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    echo "[worker] ✓ GPU detected"
else
    echo "[worker] ⚠ No GPU detected - using CPU mode"
fi

echo "[worker] Waiting for Redis..."
for i in {1..30}; do
    if redis-cli -u "${REDIS_URL:-redis://redis:6379/0}" ping 2>/dev/null | grep -q PONG; then
        echo "[worker] ✓ Redis ready"
        break
    fi
    sleep 1
done

echo "[worker] Waiting for PostgreSQL..."
for i in {1..30}; do
    if pg_isready -h postgres -p 5432 -U lpr 2>/dev/null; then
        echo "[worker] ✓ PostgreSQL ready"
        break
    fi
    sleep 1
done

echo "[worker] Model path: ${MODEL_PATH:-/models/best.pt}"
echo "[worker] Storage: ${STORAGE_DIR:-/storage}"

echo "[worker] Starting Celery worker..."
exec celery -A alpr_worker.celery_app:celery_app worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 \
    -Q lpr,tracking,training \
    --max-tasks-per-child=100 \
    --time-limit=300 \
    --soft-time-limit=240
