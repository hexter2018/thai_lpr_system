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

# ==================== TensorRT Engine Preparation ====================
ensure_engine_model() {
    local model_name="$1"
    local pt_path="$2"
    local onnx_path="$3"
    local output_path_file="$4"

    local cached_engine_path=""

    if [ "${USE_TRT_DETECTOR:-false}" != "true" ]; then
        return 0
    fi

    if [ -f "$output_path_file" ]; then
        cached_engine_path="$(cat "$output_path_file" 2>/dev/null || true)"
        if [ -n "$cached_engine_path" ] && [ -f "$cached_engine_path" ]; then
            echo "[worker] ✓ Using cached ${model_name} engine from ${output_path_file}: $cached_engine_path"
            if [ "$model_name" = "plate" ]; then
                export MODEL_PATH="$cached_engine_path"
            else
                export VEHICLE_MODEL_PATH="$cached_engine_path"
            fi
            return 0
        fi
    fi

    if [ ! -f "$pt_path" ] && [ ! -f "$onnx_path" ]; then
        echo "[worker] ⚠ ${model_name} source model not found (.pt/.onnx): $pt_path / $onnx_path"
        return 0
    fi

    echo "[worker] Preparing TensorRT engine for ${model_name}..."
    if MODELS_DIR="${MODELS_DIR:-/models}" \
        PT_PATH="$pt_path" \
        ONNX_PATH="$onnx_path" \
        OUTPUT_PATH_FILE="$output_path_file" \
        python3 /app/bin/ensure_engine.py; then
        local engine_path
        engine_path="$(cat "$output_path_file")"
        echo "[worker] ✓ ${model_name} engine ready: $engine_path"
        if [ "$model_name" = "plate" ]; then
            export MODEL_PATH="$engine_path"
        else
            export VEHICLE_MODEL_PATH="$engine_path"
        fi
    else
        echo "[worker] ⚠ Failed to prepare ${model_name} engine. Will use configured path/fallback."
    fi
}

# Build/resolve engines from .pt/.onnx before worker start
ensure_engine_model "plate" \
    "${PLATE_PT_PATH:-/models/best.pt}" \
    "${PLATE_ONNX_PATH:-/models/best.onnx}" \
    "${MODELS_DIR:-/models}/.model_path"

ensure_engine_model "vehicle" \
    "${VEHICLE_PT_PATH:-/models/vehicles.pt}" \
    "${VEHICLE_ONNX_PATH:-/models/vehicles.onnx}" \
    "${MODELS_DIR:-/models}/.vehicle_model_path"

resolve_model_path() {
    local configured_path="$1"
    shift || true
    if [ -z "$configured_path" ]; then
        configured_path=""
    fi

    if [[ "$(basename "$configured_path")" == .*model_path ]] && [ -f "$configured_path" ]; then
        local resolved_path
        resolved_path="$(cat "$configured_path" 2>/dev/null)"
        if [ -n "$resolved_path" ] && [ -f "$resolved_path" ]; then
            echo "$resolved_path"
            return 0
        fi
    fi

    for candidate_path in "$@"; do
        if [ -n "$candidate_path" ] && [ -f "$candidate_path" ]; then
            echo "$candidate_path"
            return 0
        fi
    done

    echo "$configured_path"
}

# ==================== Model Configuration ====================
echo "[worker] === Model Configuration ==="
resolved_plate_model="$(resolve_model_path "${MODEL_PATH:-/models/.model_path}")"
resolved_vehicle_model="$(resolve_model_path \
    "${VEHICLE_MODEL_PATH:-/models/.vehicle_model_path}" \
    "${MODELS_DIR:-/models}/vehicles.engine" \
    "${MODELS_DIR:-/models}/vehicles.onnx" \
    "${MODELS_DIR:-/models}/vehicles.pt")"

if [ "$resolved_vehicle_model" != "${VEHICLE_MODEL_PATH:-/models/.vehicle_model_path}" ]; then
    export VEHICLE_MODEL_PATH="$resolved_vehicle_model"
fi
echo "[worker] Plate Detection: ${resolved_plate_model:-N/A}"
echo "[worker] Vehicle Detection: ${resolved_vehicle_model:-N/A}"
echo "[worker] Storage Directory: ${STORAGE_DIR:-/storage}"
echo "[worker] TensorRT Enabled: ${USE_TRT_DETECTOR:-false}"
echo ""

# Check if model files exist
if [ -n "$resolved_plate_model" ] && [ -f "$resolved_plate_model" ]; then
    echo "[worker] ✓ Plate model found:"
    ls -lh "$resolved_plate_model"
else
    echo "[worker] ⚠ Plate model not found: ${resolved_plate_model:-N/A}"
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
    --without-mingle 