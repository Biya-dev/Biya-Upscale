"""Download all registry models into the app's model directory.

Usage:  python tools/download_models.py [--models-dir PATH]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from biya_upscale.config import AppConfig  # noqa: E402
from biya_upscale.model_store import ModelStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", default=None)
    args = parser.parse_args()

    config = AppConfig()
    config.ensure_dirs()
    models_dir = Path(args.models_dir) if args.models_dir else config.models_dir
    store = ModelStore(models_dir)
    print(f"models dir: {models_dir}")

    failed = False
    for spec in store.specs:
        if store.is_ready(spec.id):
            print(f"[ready]    {spec.id:<26} {spec.size_bytes / 1e6:6.1f} MB")
            continue
        print(f"[download] {spec.id:<26} {spec.size_bytes / 1e6:6.1f} MB  {spec.url}")
        started = time.time()
        last = -1

        def on_progress(fraction: float, _spec=spec) -> None:
            nonlocal last
            pct = int(fraction * 20) * 5
            if pct != last:
                last = pct
                print(f"    {_spec.id}: {pct:3d}%", flush=True)

        try:
            store.download_blocking(spec.id, on_progress=on_progress)
            print(f"[ok]       {spec.id} in {time.time() - started:.1f}s")
        except Exception as exc:  # noqa: BLE001
            failed = True
            status = store.status(spec.id)
            print(f"[failed]   {spec.id}: {exc}")
            print(f"           {status.get('error')}")

    ok = all(store.is_ready(spec.id) for spec in store.specs)
    print("all models installed" if ok else "some models failed")
    return 0 if ok and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
