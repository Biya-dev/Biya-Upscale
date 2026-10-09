"""Quick GPU verification: create a CUDA session and run real inference."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from biya_upscale.config import AppConfig  # noqa: E402
from biya_upscale.imaging import load_image_path  # noqa: E402
from biya_upscale.model_store import ModelStore  # noqa: E402
from biya_upscale.upscaler import Upscaler  # noqa: E402


def main() -> int:
    config = AppConfig()
    store = ModelStore(config.models_dir)
    spec = store.get_spec("realesr-general-x4v3")
    path = store.require_path(spec.id)

    upscaler = Upscaler()  # auto-detect: should pick CUDA on this machine
    img = load_image_path(ROOT / "samples" / "small_320x240.jpg")

    progress: list[float] = []
    started = time.perf_counter()
    outcome = upscaler.upscale_image(
        img, spec, path, progress=progress.append
    )
    elapsed = time.perf_counter() - started

    print(f"device   : {outcome.device.label} (id={outcome.device.id})")
    print(f"providers: {outcome.providers}")
    print(f"output   : {outcome.image.width}x{outcome.image.height}")
    print(f"elapsed  : {elapsed:.2f}s (inference {outcome.inference_seconds:.2f}s)")
    arr = np.asarray(outcome.image)
    print(f"stats    : mean={arr.mean():.1f} std={arr.std():.1f}")

    dest = ROOT / ".scratch-data" / "gpu_4x_fast.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    outcome.image.save(dest)
    print(f"saved    : {dest}")
    ok = outcome.device.id in ("cuda", "directml", "coreml")
    print("GPU_INFERENCE_OK" if ok else "GPU_INFERENCE_FALLBACK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
