#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH=/app

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[worker] ERROR: Python interpreter not found in PATH"
  exit 1
fi

echo "[worker] python:" && "$PYTHON_BIN" -V

# Auto build/select TensorRT engine per GPU
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[worker] NVIDIA GPU detected. Ensuring TensorRT engine..."
  "$PYTHON_BIN" /app/bin/ensure_engine.py || {
    echo "[worker] WARNING: Engine build failed, will attempt fallback"
  }

  if [[ -f /models/.model_path ]]; then
    export MODEL_PATH="$(cat /models/.model_path)"
    echo "[worker] MODEL_PATH set to: $MODEL_PATH"
  else
    echo "[worker] No .model_path file, checking for fallback models..."
    if [[ -f /models/best.engine ]]; then
      export MODEL_PATH="/models/best.engine"
      echo "[worker] MODEL_PATH set to (cached engine): $MODEL_PATH"
    elif [[ -f /models/best.pt ]]; then
      export MODEL_PATH="/models/best.pt"
      echo "[worker] MODEL_PATH set to (fallback .pt): $MODEL_PATH"
    fi
  fi
else
  echo "[worker] No nvidia-smi -> running without GPU"
  if [[ -f /models/best.pt ]]; then
    export MODEL_PATH="/models/best.pt"
    echo "[worker] MODEL_PATH set to: $MODEL_PATH"
  fi
fi

if [[ -z "${MODEL_PATH:-}" ]]; then
  echo "[worker] ERROR: No model found! Checked for .engine and .pt"
  exit 1
fi

echo "[worker] starting celery..."
if [[ "${PRELOAD_MODELS:-1}" == "1" ]]; then
  echo "[worker] preloading detector and OCR models..."
  "$PYTHON_BIN" - <<'PY'
from alpr_worker.inference.detector import PlateDetector
from alpr_worker.inference.ocr import PlateOCR

PlateDetector()
PlateOCR()
print("[worker] preload complete")
PY
fi

celery -A alpr_worker.celery_app:celery_app worker \
  -l info \
  --pool=solo \
  -Q default,celery