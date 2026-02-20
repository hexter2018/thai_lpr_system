#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=/app

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Thai LPR Worker - Line Crossing + TensorRT Edition"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "[worker] Python version:"
python3 --version
echo ""

# ==================== GPU & CUDA Check ====================
echo "[worker] Checking GPU & CUDA..."
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    echo "[worker] ✓ GPU detected"
    
    # Check PyTorch CUDA
    python3 -c "
import torch
print(f'  PyTorch version: {torch.__version__}')
print(f'  CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  CUDA version: {torch.version.cuda}')
    print(f'  GPU device: {torch.cuda.get_device_name(0)}')
    print(f'  GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB')
else:
    print('  ⚠ PyTorch CUDA not available')
" || echo "[worker] ⚠ PyTorch CUDA check failed"
    
    # Check TensorRT
    python3 -c "
try:
    import tensorrt as trt
    print(f'  TensorRT version: {trt.__version__}')
except ImportError:
    print('  TensorRT not installed (using Ultralytics PyTorch backend)')
" 2>/dev/null || true
    
    echo ""
else
    echo "[worker] ⚠ No GPU detected - using CPU mode"
    echo ""
fi

# ==================== Wait for Redis ====================
echo "[worker] Waiting for Redis..."
REDIS_READY=false
for i in {1..30}; do
    if redis-cli -u "${REDIS_URL:-redis://redis:6379/0}" ping 2>/dev/null | grep -q PONG; then
        echo "[worker] ✓ Redis ready"
        REDIS_READY=true
        break
    fi
    sleep 1
done

if [ "$REDIS_READY" = false ]; then
    echo "[worker] ✗ Redis timeout after 30s"
    exit 1
fi
echo ""

# ==================== Wait for PostgreSQL ====================
echo "[worker] Waiting for PostgreSQL..."
PG_READY=false
for i in {1..30}; do
    if pg_isready -h postgres -p 5432 -U lpr 2>/dev/null; then
        echo "[worker] ✓ PostgreSQL ready"
        PG_READY=true
        break
    fi
    sleep 1
done

if [ "$PG_READY" = false ]; then
    echo "[worker] ✗ PostgreSQL timeout after 30s"
    exit 1
fi
echo ""

# ==================== Model Configuration ====================
echo "[worker] === Model Configuration ==="
echo "[worker] Plate Detection: ${MODEL_PATH:-/models/best.engine}"
echo "[worker] Vehicle Detection: ${VEHICLE_MODEL_PATH:-N/A}"
echo "[worker] Storage Directory: ${STORAGE_DIR:-/storage}"
echo "[worker] TensorRT Enabled: ${USE_TRT_DETECTOR:-false}"
echo ""

# Check if model files exist
if [ -f "${MODEL_PATH:-/models/best.engine}" ]; then
    echo "[worker] ✓ Plate model found:"
    ls -lh "${MODEL_PATH:-/models/best.engine}"
else
    echo "[worker] ⚠ Plate model not found: ${MODEL_PATH:-/models/best.engine}"
    echo "[worker] Looking for fallback models in /models/:"
    ls -lh /models/ 2>/dev/null || echo "[worker]   (empty or not mounted)"
fi
echo ""

# ==================== Worker Configuration ====================
echo "[worker] === Worker Configuration ==="
echo "[worker] Concurrency: ${CELERY_WORKER_CONCURRENCY:-4}"
echo "[worker] Prefetch Multiplier: ${CELERY_WORKER_PREFETCH:-8}"
echo "[worker] Task Time Limit: 300s (hard), 240s (soft)"
echo "[worker] Queues: lpr, tracking, training"
echo "[worker] Max Tasks Per Child: 100"
echo "[worker] Pool: solo (single-process)"
echo ""

# ==================== Start Celery Worker ====================
echo "[worker] 🚀 Starting Celery worker..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exec celery -A alpr_worker.celery_app:celery_app worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=${CELERY_WORKER_CONCURRENCY:-4} \
    --prefetch-multiplier=${CELERY_WORKER_PREFETCH:-8} \
    -Q lpr,tracking,training \
    --max-tasks-per-child=100 \
    --time-limit=300 \
    --soft-time-limit=240 \
    --without-gossip \
    --without-mingle \
    --without-heartbeat