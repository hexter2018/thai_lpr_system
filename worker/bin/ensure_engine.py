#!/usr/bin/env python3
import os
import re
import subprocess
from pathlib import Path

def sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    return p.stdout.strip()

def has_nvidia_smi() -> bool:
    try:
        out = sh(["bash", "-lc", "command -v nvidia-smi"])
        return bool(out)
    except Exception:
        return False

def gpu_compute_cap() -> str:
    # returns like "8.6"
    out = sh(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"])
    line = out.splitlines()[0].strip()
    return line

def gpu_name() -> str:
    out = sh(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    return out.splitlines()[0].strip()

def tensorrt_version() -> str:
    try:
        import tensorrt as trt  # type: ignore
        v = getattr(trt, "__version__", "unknown")
        # keep major.minor (e.g. 10.15)
        m = re.match(r"^(\d+\.\d+)", str(v))
        return m.group(1) if m else str(v)
    except Exception:
        return "unknown"

def ensure_onnx(pt_path: Path, onnx_path: Path, imgsz: int) -> None:
    if onnx_path.exists():
        return
    if not pt_path.exists():
        raise RuntimeError(f"Missing {pt_path} and {onnx_path}. Provide best.onnx or best.pt.")
    print(f"[ensure_engine] Exporting ONNX from {pt_path} -> {onnx_path}")
    # Use ultralytics python API
    from ultralytics import YOLO  # type: ignore
    model = YOLO(str(pt_path), task="detect")
    # export to the same /models dir
    model.export(format="onnx", imgsz=imgsz, opset=12, simplify=True)
    # ultralytics exports beside pt by default; locate generated onnx
    exported = pt_path.with_suffix(".onnx")
    if exported.exists() and exported != onnx_path:
        exported.replace(onnx_path)
    if not onnx_path.exists():
        raise RuntimeError("ONNX export failed (best.onnx not found after export).")

def try_load_engine(engine_path: Path) -> bool:
    # Quick compatibility check: try deserialize engine
    try:
        import tensorrt as trt  # type: ignore
        logger = trt.Logger(trt.Logger.ERROR)
        runtime = trt.Runtime(logger)
        with open(engine_path, "rb") as f:
            data = f.read()
        eng = runtime.deserialize_cuda_engine(data)
        return eng is not None
    except Exception:
        return False

def build_engine(
    onnx_path: Path,
    engine_path: Path,
    fp16: bool,
    workspace: int,
    workspace_mode: str,
) -> None:
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "trtexec",
        f"--onnx={onnx_path}",
        f"--saveEngine={engine_path}",
    ]
    if workspace_mode == "mempool":
        # TensorRT v10+ uses memPoolSize for workspace memory in MiB.
        cmd.append(f"--memPoolSize=workspace:{workspace}M")
    else:
        cmd.append(f"--workspace={workspace}")
    if fp16:
        cmd.append("--fp16")
    # Optional: verbose for debugging
    # cmd.append("--verbose")

    print("[ensure_engine] Building engine via trtexec:")
    print("  " + " ".join(cmd))
    out = sh(cmd)
    print(out)
    if not engine_path.exists():
        raise RuntimeError("Engine build failed: engine file not created.")

def main():
    models_dir = Path(os.getenv("MODELS_DIR", "/models"))
    pt_path = Path(os.getenv("PT_PATH", str(models_dir / "best.pt")))
    onnx_path = Path(os.getenv("ONNX_PATH", str(models_dir / "best.onnx")))

    engine_dir = Path(os.getenv("ENGINE_DIR", str(models_dir / "engines")))
    engine_dir.mkdir(parents=True, exist_ok=True)
    imgsz = int(os.getenv("DETECTOR_IMGSZ", "640"))
    fp16 = os.getenv("TRT_FP16", "1") == "1"
    raw_ws = os.getenv("TRT_WORKSPACE", "4096")
    try:
        workspace = int(raw_ws)
    except ValueError:
        # fallback safe default
        workspace = 4096
    force_rebuild = os.getenv("TRT_FORCE_REBUILD", "0") == "1"

    if not has_nvidia_smi():
        print("[ensure_engine] No NVIDIA GPU detected (nvidia-smi not found). Skip engine.")
        return 0

    cc = gpu_compute_cap()            # "8.6"
    sm = "sm" + cc.replace(".", "")   # "sm86"
    gname = gpu_name()
    trt_ver = tensorrt_version()      # "10.15" (best effort)
    trt_tag = "trt" + trt_ver.replace(".", "_")
    workspace_mode = os.getenv("TRT_WORKSPACE_MODE", "auto").lower()
    if workspace_mode not in {"auto", "mempool", "workspace"}:
        workspace_mode = "auto"
    if workspace_mode == "auto":
        major = None
        try:
            major = int(str(trt_ver).split(".")[0])
        except (ValueError, IndexError):
            major = None
        workspace_mode = "mempool" if (major is not None and major >= 10) else "workspace"

    engine_path = engine_dir / f"best_{sm}_{trt_tag}_fp16.engine"

    print(f"[ensure_engine] GPU={gname} compute={cc} -> {sm}")
    print(f"[ensure_engine] TensorRT={trt_ver} -> {trt_tag}")
    print(f"[ensure_engine] Target engine: {engine_path}")

    if engine_path.exists() and not force_rebuild:
        ok = try_load_engine(engine_path)
        if ok:
            print(f"[ensure_engine] Engine OK (cached): {engine_path}")
            # export to env file for start.sh
            (models_dir / ".model_path").write_text(str(engine_path))
            return 0
        print("[ensure_engine] Cached engine exists but incompatible -> rebuild")

    ensure_onnx(pt_path, onnx_path, imgsz)
    build_engine(
        onnx_path,
        engine_path,
        fp16=fp16,
        workspace=workspace,
        workspace_mode=workspace_mode,
    )

    # Validate
    if not try_load_engine(engine_path):
        raise RuntimeError("Engine built but failed to deserialize (still incompatible).")

    print(f"[ensure_engine] Engine ready: {engine_path}")
    (models_dir / ".model_path").write_text(str(engine_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
