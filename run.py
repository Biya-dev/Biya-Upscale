"""Convenience launcher: ``python run.py``.

Keeps the repository root importable without installing the package.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "backend"))

from biya_upscale.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
