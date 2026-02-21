#!/usr/bin/env python3
import os
import re
import subprocess

from pathlib import Path
from shutil import which

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
    return out.splitlines()[0].strip()


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

    try:
        model = YOLO(str(pt_path), task="detect")
        # export to the same /models dir
        model.export(format="onnx", imgsz=imgsz, opset=12, simplify=True)
    except Exception as exc:
        msg = str(exc)
        if "C3k2" in msg:
            raise RuntimeError(
                "ONNX export failed because this .pt model requires a newer Ultralytics package "
                "(missing module: C3k2). Upgrade ultralytics in the worker image, then retry. "
                f"Original error: {exc}"
            ) from exc
        raise

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
        engine = runtime.deserialize_cuda_engine(data)
        return engine is not None
    except Exception:
        return False

def pick_compatible_cached_engine(engine_dir: Path, engine_prefix: str, sm: str) -> Path | None:
    pattern = f"{engine_prefix}_{sm}_trt*_fp16.engine"
    candidates = sorted(engine_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if try_load_engine(candidate):
            return candidate
    return None


def resolve_trtexec() -> Path:
    trtexec_bin = os.getenv("TRTEXEC_PATH")
    if trtexec_bin:
        trtexec = Path(trtexec_bin)
        if not trtexec.exists():
            raise RuntimeError(f"TRTEXEC_PATH points to missing file: {trtexec}")
        return trtexec

    detected = which("trtexec")
    if detected:
        return Path(detected)

    # Common TensorRT container install locations.
    for candidate in [
        Path("/usr/src/tensorrt/bin/trtexec"),
        Path("/usr/local/tensorrt/bin/trtexec"),
        Path("/opt/tensorrt/bin/trtexec"),
    ]:
        if candidate.exists():
            return candidate

    raise RuntimeError(
        "TensorRT engine build requires 'trtexec', but it was not found in PATH. "
        "Set TRTEXEC_PATH to the binary location or install TensorRT CLI tools."
    )

def build_engine(onnx_path: Path, engine_path: Path, fp16: bool, workspace: int, workspace_mode: str) -> None:
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    trtexec = resolve_trtexec()

    cmd = [
        str(trtexec),
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

    print("[ensure_engine] Building engine via trtexec:")
    print("  " + " ".join(cmd))
    out = sh(cmd)
    print(out)
    if not engine_path.exists():
        raise RuntimeError("Engine build failed: engine file not created.")

def main() -> int:
    models_dir = Path(os.getenv("MODELS_DIR", "/models"))
    pt_path = Path(os.getenv("PT_PATH", str(models_dir / "best.pt")))
    onnx_path = Path(os.getenv("ONNX_PATH", str(models_dir / "best.onnx")))

    engine_dir = Path(os.getenv("ENGINE_DIR", str(models_dir / "engines")))
    engine_dir.mkdir(parents=True, exist_ok=True)

    output_path_file = Path(os.getenv("OUTPUT_PATH_FILE", str(models_dir / ".model_path")))
    engine_basename = os.getenv("ENGINE_BASENAME", onnx_path.stem)

    imgsz = int(os.getenv("DETECTOR_IMGSZ", "640"))
    fp16 = os.getenv("TRT_FP16", "1") == "1"
    
    try:
        workspace = workspace = int(os.getenv("TRT_WORKSPACE", "4096"))
    except ValueError:
        # fallback safe default
        workspace = 4096
    force_rebuild = os.getenv("TRT_FORCE_REBUILD", "0") == "1"

    if not has_nvidia_smi():
        print("[ensure_engine] No NVIDIA GPU detected (nvidia-smi not found). Skip engine.")
        return 0

    cc = gpu_compute_cap()
    sm = "sm" + cc.replace(".", "")
    gname = gpu_name()
    trt_ver = tensorrt_version()
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

    engine_path = engine_dir / f"{engine_basename}_{sm}_{trt_tag}_fp16.engine"

    print(f"[ensure_engine] GPU={gname} compute={cc} -> {sm}")
    print(f"[ensure_engine] TensorRT={trt_ver} -> {trt_tag}")
    print(f"[ensure_engine] Target engine: {engine_path}")

    if engine_path.exists() and not force_rebuild and try_load_engine(engine_path):
        print(f"[ensure_engine] Engine OK (cached): {engine_path}")
        output_path_file.write_text(str(engine_path))
        return 0

    if not force_rebuild:
        fallback_engine = pick_compatible_cached_engine(engine_dir, engine_basename, sm)
        if fallback_engine:
            print(f"[ensure_engine] Using compatible cached engine: {fallback_engine}")
            output_path_file.write_text(str(fallback_engine))
            return 0

    ensure_onnx(pt_path, onnx_path, imgsz)

    try:
        build_engine(
            onnx_path,
            engine_path,
            fp16=fp16,
            workspace=workspace,
            workspace_mode=workspace_mode,
        )
    except RuntimeError as exc:
        if "trtexec" in str(exc) and not force_rebuild:
            fallback_engine = pick_compatible_cached_engine(engine_dir, engine_basename, sm)
            if fallback_engine:
                print(f"[ensure_engine] trtexec unavailable, using cached engine: {fallback_engine}")
                output_path_file.write_text(str(fallback_engine))
                return 0
        raise

    # Validate
    if not try_load_engine(engine_path):
        raise RuntimeError("Engine built but failed to deserialize (still incompatible).")

    print(f"[ensure_engine] Engine ready: {engine_path}")
    output_path_file.write_text(str(engine_path))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ensure_engine] ERROR: {exc}")
        raise SystemExit(1)
