"""Smoke test: run real AI inference at 2x and 4x on a sample image.

Usage:  python tools/smoke_upscale.py [scale ...]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from biya_upscale.config import AppConfig  # noqa: E402
from biya_upscale.imaging import load_image_path, save_image  # noqa: E402
from biya_upscale.model_store import ModelStore  # noqa: E402
from biya_upscale.upscaler import Upscaler  # noqa: E402

OUT_DIR = ROOT / ".scratch-data" / "smoke"


def run(scale: int) -> None:
    src = ROOT / "samples" / "small_320x240.jpg"
    if not src.exists():
        raise SystemExit("run tools/make_samples.py first")

    config = AppConfig()
    store = ModelStore(config.models_dir)
    spec = store.model_for_scale(scale)
    if not store.is_ready(spec.id):
        raise SystemExit(f"model {spec.id} not installed — run tools/download_models.py")

    upscaler = Upscaler()
    img = load_image_path(src)
    print(f"input : {img.width}x{img.height}  model={spec.name}  scale={scale}x")

    started = time.perf_counter()
    last = [-1.0]

    def on_progress(frac: float) -> None:
        if frac - last[0] >= 0.25:
            last[0] = frac
            print(f"  progress {frac * 100:5.1f}%")

    outcome = upscaler.upscale_image(
        img, spec, store.require_path(spec.id), progress=on_progress
    )
    elapsed = time.perf_counter() - started
    print(
        f"output: {outcome.image.width}x{outcome.image.height}  "
        f"{elapsed:.2f}s  device={outcome.device.label}  tile={outcome.tile}"
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"small_320x240_{scale}x.png"
    save_image(outcome.image, dest, fmt="PNG")
    print(f"saved : {dest}")


def main() -> None:
    scales = [int(a) for a in sys.argv[1:]] or [2, 4]
    for scale in scales:
        print(f"--- {scale}x ---")
        run(scale)


if __name__ == "__main__":
    main()
