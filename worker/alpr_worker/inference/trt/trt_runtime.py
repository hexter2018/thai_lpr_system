# worker/alpr_worker/inference/trt/trt_runtime.py
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import tensorrt as trt

from cuda import cudart  # cuda-python

log = logging.getLogger(__name__)


@dataclass
class _Binding:
    name: str
    index: int
    dtype: np.dtype
    shape: Tuple[int, ...]
    is_input: bool
    nbytes: int
    dptr: int  # device pointer (int)


class TensorRTRuntime:
    """
    TensorRT runtime wrapper without PyCUDA (uses cuda-python / cudart).

    Assumptions (typical for YOLOv8 detector):
      - batch fixed 1
      - 1 input, >=1 output (we return the first output)
      - input dtype float32 NCHW
    """

    def __init__(self, engine_path: str):
        self.engine_path = engine_path

        if not os.path.exists(engine_path):
            raise FileNotFoundError(engine_path)

        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)

        with open(engine_path, "rb") as f:
            engine_bytes = f.read()

        self.engine = self.runtime.deserialize_cuda_engine(engine_bytes)
        if self.engine is None:
            raise RuntimeError(
                "Failed to deserialize TensorRT engine. "
                "Likely incompatible GPU compute capability or TRT version mismatch."
            )

        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Failed to create execution context.")

        # Create CUDA stream
        err, self.stream = cudart.cudaStreamCreate()
        self._check(err, "cudaStreamCreate")

        # Setup bindings
        self.bindings_ptrs: List[int] = [0] * self.engine.num_bindings
        self.inputs: List[_Binding] = []
        self.outputs: List[_Binding] = []

        # Resolve dynamic shapes for inputs if needed
        for i in range(self.engine.num_bindings):
            if self.engine.binding_is_input(i):
                shape = tuple(self.engine.get_binding_shape(i))
                if any(d == -1 for d in shape):
                    in_h = int(os.getenv("TRT_INPUT_H", "640"))
                    in_w = int(os.getenv("TRT_INPUT_W", "640"))
                    # assume NCHW
                    new_shape = (1, 3, in_h, in_w)
                    self.context.set_binding_shape(i, new_shape)

        # Allocate device buffers
        for i in range(self.engine.num_bindings):
            name = self.engine.get_binding_name(i)
            is_input = self.engine.binding_is_input(i)

            shape = tuple(self.context.get_binding_shape(i))
            dtype = np.dtype(trt.nptype(self.engine.get_binding_dtype(i)))
            nbytes = int(np.prod(shape) * dtype.itemsize)

            err, dptr = cudart.cudaMalloc(nbytes)
            self._check(err, f"cudaMalloc({name})")

            self.bindings_ptrs[i] = int(dptr)

            b = _Binding(
                name=name,
                index=i,
                dtype=dtype,
                shape=shape,
                is_input=is_input,
                nbytes=nbytes,
                dptr=int(dptr),
            )
            if is_input:
                self.inputs.append(b)
            else:
                self.outputs.append(b)

        if not self.inputs:
            raise RuntimeError("No input bindings found.")
        if not self.outputs:
            raise RuntimeError("No output bindings found.")

        log.info("TensorRT engine loaded: %s", engine_path)
        for b in self.inputs + self.outputs:
            log.info("binding[%d] %s %s shape=%s dtype=%s nbytes=%d",
                     b.index, "IN " if b.is_input else "OUT", b.name, b.shape, b.dtype, b.nbytes)

    def __del__(self):
        try:
            for b in self.inputs + self.outputs:
                try:
                    cudart.cudaFree(b.dptr)
                except Exception:
                    pass
            try:
                cudart.cudaStreamDestroy(self.stream)
            except Exception:
                pass
        except Exception:
            pass

    def infer(self, x: np.ndarray) -> np.ndarray:
        inp = self.inputs[0]

        x = np.asarray(x)
        if x.dtype != inp.dtype:
            x = x.astype(inp.dtype, copy=False)

        # If input shape differs and engine supports dynamic shapes, set binding shape
        if tuple(x.shape) != tuple(inp.shape):
            self.context.set_binding_shape(inp.index, tuple(x.shape))
            # update cached shapes for output too
            inp.shape = tuple(x.shape)
            inp.nbytes = int(np.prod(inp.shape) * inp.dtype.itemsize)

        # H2D
        host = np.ascontiguousarray(x).ravel()
        err = cudart.cudaMemcpyAsync(
            inp.dptr, host.ctypes.data, host.nbytes,
            cudart.cudaMemcpyKind.cudaMemcpyHostToDevice,
            self.stream
        )[0]
        self._check(err, "cudaMemcpyAsync H2D")

        # Execute
        ok = self.context.execute_async_v2(self.bindings_ptrs, self.stream)
        if not ok:
            raise RuntimeError("TensorRT execute_async_v2 returned False")

        # D2H (first output)
        out = self.outputs[0]
        # refresh output shape in case dynamic
        out.shape = tuple(self.context.get_binding_shape(out.index))
        out.nbytes = int(np.prod(out.shape) * out.dtype.itemsize)

        host_out = np.empty(int(np.prod(out.shape)), dtype=out.dtype)
        err = cudart.cudaMemcpyAsync(
            host_out.ctypes.data, out.dptr, host_out.nbytes,
            cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost,
            self.stream
        )[0]
        self._check(err, "cudaMemcpyAsync D2H")

        # Sync
        err = cudart.cudaStreamSynchronize(self.stream)[0]
        self._check(err, "cudaStreamSynchronize")

        return host_out.reshape(out.shape)

    @staticmethod
    def _check(err, where: str):
        if err != cudart.cudaError_t.cudaSuccess:
            raise RuntimeError(f"{where} failed: {err}")
