#!/usr/bin/env bash
set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/models}"
ONNX="${ONNX_PATH:-$MODELS_DIR/best.onnx}"
ENGINE_DIR="${ENGINE_DIR:-$MODELS_DIR/engines}"
mkdir -p "$ENGINE_DIR"

# if no nvidia-smi => no NVIDIA GPU available
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[ensure_engine] No NVIDIA GPU detected. Skipping TensorRT engine."
  exit 0
fi

# Get compute capability like "8.6"
CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -n1 | tr -d ' ')
CC_TAG="sm${CC/./}"   # 8.6 -> sm86

# Get trtexec version (best effort)
TRT_VER=$(trtexec --version 2>/dev/null | head -n1 | sed -E 's/.*TensorRT ([0-9]+\.[0-9]+).*/\1/' || true)
if [[ -z "${TRT_VER}" ]]; then
  TRT_VER="unknown"
fi
TRT_TAG="trt${TRT_VER//./_}"  # 10.15 -> trt10_15

ENGINE="$ENGINE_DIR/best_${CC_TAG}_${TRT_TAG}.engine"

if [[ -f "$ENGINE" ]]; then
  echo "[ensure_engine] Found cached engine: $ENGINE"
  export MODEL_PATH="$ENGINE"
  exit 0
fi

if [[ ! -f "$ONNX" ]]; then
  echo "[ensure_engine] ONNX not found: $ONNX"
  echo "Put best.onnx into /models first."
  exit 1
fi

echo "[ensure_engine] Building engine for $CC_TAG ($TRT_TAG) ..."
trtexec --onnx="$ONNX" --saveEngine="$ENGINE" --fp16 --workspace=4096

echo "[ensure_engine] Built: $ENGINE"
export MODEL_PATH="$ENGINE"
