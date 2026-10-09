"""Local AI upscaling via ONNX Runtime.

Key properties:

* Real model inference (Real-ESRGAN family, loaded from a local ONNX file).
* Tiled execution with overlap so large images never require holding the
  whole float tensor in memory — and so 4 GB VRAM GPUs can process 4K input.
* Automatic provider fallback: CUDA → DirectML → CoreML → CPU.
* Out-of-memory recovery: halve the tile size and retry before giving up.
* Cooperative cancellation between tiles.
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

from . import hardware
from .errors import BiyaError, ModelLoadError, OutOfMemoryError, ProcessingCancelled
from .hardware import CPU_DEVICE, DeviceInfo
from .imaging import split_alpha
from .model_store import ModelSpec

log = logging.getLogger("biya_upscale")

ProgressFn = Optional[object]  # Callable[[float], None]

DEFAULT_TILE_GPU = 192       # input-px per tile side on GPU
DEFAULT_TILE_CPU = 256       # input-px per tile side on CPU
MIN_TILE = 64
TILE_PAD = 32                # overlap (input px) hiding receptive-field seams

_MEMORY_KEYWORDS = (
    "out of memory",
    "oom",
    "failed to allocate",
    "bad_alloc",
    "memory limit",
    "cannot allocate",
    "insufficient memory",
    "not enough memory",
    "allocation failed",
)


def _looks_like_oom(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(key in msg for key in _MEMORY_KEYWORDS)


@dataclass
class UpscaleOutcome:
    image: Image.Image
    inference_seconds: float
    device: DeviceInfo
    tile: int
    providers: list[str]


class Upscaler:
    """Caches one inference session per model and runs tiled inference."""

    def __init__(self, force_cpu: bool = False,
                 preferred_device: Optional[str] = None) -> None:
        self.force_cpu = force_cpu
        self.preferred_device = preferred_device
        self._sessions: dict[str, object] = {}
        self._session_meta: dict[str, tuple[DeviceInfo, list[str], int]] = {}
        self._lock = threading.RLock()
        self.active_device: Optional[DeviceInfo] = None

    # --- device / session management --------------------------------------
    def _candidate_devices(self) -> list[DeviceInfo]:
        info = hardware.detect_hardware(force_cpu=self.force_cpu)
        devices = list(info.devices)
        if self.preferred_device and not self.force_cpu:
            devices.sort(key=lambda d: 0 if d.id == self.preferred_device else 1)
        return devices

    def detected_devices(self) -> list[DeviceInfo]:
        return hardware.detect_hardware(force_cpu=self.force_cpu).devices

    def _create_session(self, model_path):
        import onnxruntime as ort

        errors: list[str] = []
        for device in self._candidate_devices():
            hardware.preload_acceleration_libs(device.id)
            providers = [device.provider]
            if device.provider != CPU_DEVICE.provider:
                providers.append(CPU_DEVICE.provider)
            try:
                opts = ort.SessionOptions()
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                opts.intra_op_num_threads = 0  # let ORT pick
                session = ort.InferenceSession(
                    str(model_path), sess_options=opts, providers=providers
                )
                active = list(session.get_providers())
                if device.provider in active:
                    log.info("model loaded on %s (%s)", device.label, active)
                    return session, device, active
                if device.id == "cpu":
                    log.info("model loaded on CPU (%s)", active)
                    return session, device, active
                errors.append(f"{device.id}: provider not actually available")
                del session
            except Exception as exc:  # provider failed to initialize
                log.warning("provider %s failed to load: %s", device.id, exc)
                errors.append(f"{device.id}: {exc}")
                if _looks_like_oom(exc):
                    # keep memory pressure down before the next attempt
                    gc.collect()
        raise ModelLoadError(
            "The AI model could not be loaded on this computer.",
            hint=(
                "Try again after restarting the app, or switch to CPU in "
                "Settings. Details were written to the log file."
            ),
            detail="; ".join(errors) or "no providers available",
        )

    def ensure_session(self, model_id: str, model_path):
        with self._lock:
            session = self._sessions.get(model_id)
            if session is not None:
                device, providers, tile = self._session_meta[model_id]
                return session, device, providers, tile
            session, device, providers = self._create_session(model_path)
            default_tile = DEFAULT_TILE_CPU if device.id == "cpu" else DEFAULT_TILE_GPU
            self._sessions[model_id] = session
            self._session_meta[model_id] = (device, providers, default_tile)
            self.active_device = device
            return session, device, providers, default_tile

    def release(self, model_id: Optional[str] = None) -> None:
        """Free inference sessions (and with them GPU memory)."""
        with self._lock:
            if model_id is None:
                self._sessions.clear()
                self._session_meta.clear()
            else:
                self._sessions.pop(model_id, None)
                self._session_meta.pop(model_id, None)
        gc.collect()


    # --- inference ---------------------------------------------------------
    def upscale_image(
        self,
        img: Image.Image,
        spec: ModelSpec,
        model_path,
        *,
        factor: Optional[int] = None,
        progress: Optional[object] = None,   # Callable[[float], None]
        cancel: Optional[threading.Event] = None,
    ) -> UpscaleOutcome:
        """Upscale a PIL image with real AI inference. Returns the result.

        ``model_path`` must already be validated by the model store.
        """
        factor = int(factor or spec.scale)
        if factor != spec.scale:
            raise BiyaError(
                f"{spec.name} produces {spec.scale}× output, not {factor}×.",
                hint="Pick a matching scale factor or model.",
            )

        rgb, alpha = split_alpha(img)
        session, device, providers, tile = self.ensure_session(spec.id, model_path)

        start = time.perf_counter()
        out_array, tile_used = self._run_with_retry(
            spec, model_path, rgb, tile, factor, progress, cancel
        )
        if cancel is not None and cancel.is_set():
            # Inference for a single-tile image cannot be interrupted mid-run;
            # honour the cancellation as soon as it finishes.
            del out_array
            raise ProcessingCancelled("Processing cancelled.")
        elapsed = time.perf_counter() - start

        result = Image.fromarray(out_array, "RGB")
        if alpha is not None:
            alpha_up = alpha.resize(
                (rgb.width * factor, rgb.height * factor), Image.Resampling.LANCZOS
            )
            result.putalpha(alpha_up)

        del out_array
        gc.collect()

        with self._lock:
            meta = self._session_meta.get(spec.id)
        final_device = meta[0] if meta else device
        final_providers = meta[1] if meta else providers
        return UpscaleOutcome(
            image=result,
            inference_seconds=elapsed,
            device=final_device,
            tile=tile_used,
            providers=final_providers,
        )

    def _run_with_retry(self, spec, model_path, rgb, tile, factor, progress, cancel):
        """Run tiled inference, shrinking the tile size on out-of-memory."""
        current_tile = int(tile)
        last_oom: Optional[OutOfMemoryError] = None
        while True:
            try:
                session, _device, _providers, _ = self.ensure_session(
                    spec.id, model_path
                )
                out, tile_used = self._run_tiled(
                    rgb, session, factor, current_tile, progress, cancel
                )
                with self._lock:
                    meta = self._session_meta.get(spec.id)
                    if meta:
                        # remember the tile size that actually worked
                        self._session_meta[spec.id] = (meta[0], meta[1], current_tile)
                return out, tile_used
            except OutOfMemoryError as exc:
                last_oom = exc
                if current_tile <= MIN_TILE:
                    raise OutOfMemoryError(
                        "Not enough memory to upscale this image.",
                        hint=(
                            "Close other applications to free memory, or try a "
                            "smaller image / the 2× scale."
                        ),
                        detail=str(exc),
                    ) from exc
                log.warning(
                    "out of memory at tile=%d, retrying with tile=%d",
                    current_tile,
                    max(MIN_TILE, current_tile // 2),
                )
                # Drop the session to release VRAM, then retry smaller.
                self.release(spec.id)
                gc.collect()
                current_tile = max(MIN_TILE, current_tile // 2)
                if progress:
                    try:
                        progress(0.0)
                    except Exception:
                        pass


    @staticmethod
    def _run_tiled(rgb, session, factor, tile, progress, cancel):
        """Tile-grid inference. Returns (uint8 HWC array, tile size used)."""
        arr = np.asarray(rgb, dtype=np.uint8)
        height, width = int(arr.shape[0]), int(arr.shape[1])
        pad = min(TILE_PAD, max(8, tile // 4)) if tile < MIN_TILE else TILE_PAD
        rows = (height + tile - 1) // tile
        cols = (width + tile - 1) // tile
        total = rows * cols
        done = 0

        out = np.empty((height * factor, width * factor, 3), dtype=np.uint8)
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name

        if progress:
            progress(0.0)

        for row in range(rows):
            for col in range(cols):
                if cancel is not None and cancel.is_set():
                    raise ProcessingCancelled("Processing cancelled.")

                y0, y1 = row * tile, min((row + 1) * tile, height)
                x0, x1 = col * tile, min((col + 1) * tile, width)
                # Region actually fed to the network (tile + receptive pad).
                ey0, ey1 = max(0, y0 - pad), min(height, y1 + pad)
                ex0, ex1 = max(0, x0 - pad), min(width, x1 + pad)

                patch = arr[ey0:ey1, ex0:ex1]
                tensor = np.ascontiguousarray(
                    patch.transpose(2, 0, 1), dtype=np.float32
                )[None] / 255.0

                try:
                    result = session.run([output_name], {input_name: tensor})[0]
                except Exception as exc:
                    if _looks_like_oom(exc):
                        raise OutOfMemoryError(
                            "The device ran out of memory while upscaling.",
                            detail=f"{type(exc).__name__}: {exc}",
                        ) from exc
                    raise BiyaError(
                        "The AI model failed while processing this image.",
                        detail=f"{type(exc).__name__}: {exc}",
                    ) from exc

                tile_out = result[0] if getattr(result, "ndim", 0) == 4 else result
                tile_hwc = tile_out.transpose(1, 2, 0)
                np.clip(tile_hwc, 0.0, 1.0, out=tile_hwc)
                tile_u8 = np.rint(tile_hwc * 255.0).astype(np.uint8)

                # Crop away the padded region so tiles never double-blend.
                sy0 = (y0 - ey0) * factor
                sx0 = (x0 - ex0) * factor
                sy1 = sy0 + (y1 - y0) * factor
                sx1 = sx0 + (x1 - x0) * factor
                out[y0 * factor:y1 * factor, x0 * factor:x1 * factor] = tile_u8[
                    sy0:sy1, sx0:sx1
                ]

                del tensor, result, tile_out, tile_hwc, tile_u8
                done += 1
                if progress:
                    progress(done / total)

        if progress:
            progress(1.0)
        return out, tile

