"""Application configuration and on-disk layout.

Everything the app writes lives in a single per-user data directory:

* ``models/``  — downloaded AI models (never bundled in the installer)
* ``inputs/``  — copies of images the user selected for processing
* ``results/`` — upscaled outputs
* ``settings.json`` — user preferences

Environment override: ``BIYA_DATA_DIR`` (used heavily by the test suite).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

DEFAULT_PORT = 8765

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": None,           # None = follow system, "dark" | "light"
    "scale": 2,              # last used scale factor
    "output_format": "auto", # auto | png | jpg | webp
    "quality": 95,           # jpg/webp quality
    "model_preference": "auto",  # auto | model id
    "force_cpu": False,
    "window": True,          # open native window on launch (falls back to browser)
}


def default_data_dir() -> Path:
    """Resolve the per-user data directory (created lazily)."""
    env = os.environ.get("BIYA_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "BiyaUpscale"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BiyaUpscale"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "biya-upscale"


@dataclass
class AppConfig:
    data_dir: Path = field(default_factory=default_data_dir)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)

    # --- directories -----------------------------------------------------
    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def inputs_dir(self) -> Path:
        return self.data_dir / "inputs"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.models_dir, self.inputs_dir, self.results_dir):
            path.mkdir(parents=True, exist_ok=True)

    # --- settings ----------------------------------------------------------
    def load_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        try:
            if self.settings_path.exists():
                stored = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    settings.update(stored)
        except (OSError, ValueError):
            # Corrupt settings must never prevent the app from starting.
            pass
        return settings

    def save_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        settings = self.load_settings()
        # Never persist unknown keys (typos, stale clients, bad input).
        settings.update({k: v for k, v in updates.items() if k in DEFAULT_SETTINGS})
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass
        return settings


def resolve_port(requested: Optional[int] = None) -> int:
    """Pick the port: explicit > env > default (never a public interface)."""
    if requested:
        return requested
    env = os.environ.get("BIYA_PORT")
    if env and env.isdigit():
        return int(env)
    return DEFAULT_PORT
