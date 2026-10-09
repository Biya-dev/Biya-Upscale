"""Model management: registry, download, verification, lifecycle.

Design goals:

* The installer stays small — models are downloaded on demand, only after the
  user explicitly confirms (name, size, license, purpose are all shown).
* Files are integrity-checked (SHA-256) and written atomically.
* The registry is plain data, so additional models can be added later
  (anime variants, fast/light variants, other architectures).
* Everything lives locally under the app's data directory.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .errors import ModelDownloadError, ModelNotFoundError, ProcessingCancelled

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    scale: int                      # native upscale factor of the model
    size_bytes: int
    sha256: str
    url: str
    filename: str
    license: str = "BSD-3-Clause"
    homepage: str = "https://github.com/xinntao/Real-ESRGAN"
    architecture: str = "RRDBNet (Real-ESRGAN)"
    summary: str = ""               # shown in the model manager dialog
    default: bool = False           # default model for its scale

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "scale": self.scale,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "license": self.license,
            "homepage": self.homepage,
            "architecture": self.architecture,
            "summary": self.summary,
            "default": self.default,
            "filename": self.filename,
        }


# --- Registry -----------------------------------------------------------
# Official Real-ESRGAN weights, re-exported to ONNX (fp32, dynamic H×W,
# opset 17) with published SHA-256 checksums. BSD-3-Clause.
REGISTRY: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="realesrgan-x4plus",
        name="Real-ESRGAN x4 Plus",
        scale=4,
        size_bytes=67_051_616,
        sha256="5c586662929cbc686c1a5c38d9c060dbdb4ea5863a1f7672b8c0761e6b89c033",
        url=(
            "https://huggingface.co/SceneWorks/real-esrgan-onnx/resolve/"
            "09f741bac80a246b407da3ee902bf5f3291b602f/real_esrgan_x4.onnx"
        ),
        filename="realesrgan_x4plus.onnx",
        summary=(
            "The flagship Real-ESRGAN model for photographic images. It can "
            "invent texture and distort small text; avoid documents and "
            "text-heavy screenshots. Native 4× super-resolution."
        ),
        default=True,
    ),
    ModelSpec(
        id="realesrgan-x2plus",
        name="Real-ESRGAN x2 Plus",
        scale=2,
        size_bytes=67_073_434,
        sha256="7115ba92e8a1bfa63d68558ef006ef3d91273a068d321b1439f8bb1c9179002c",
        url=(
            "https://huggingface.co/SceneWorks/real-esrgan-onnx/resolve/"
            "09f741bac80a246b407da3ee902bf5f3291b602f/real_esrgan_x2.onnx"
        ),
        filename="realesrgan_x2plus.onnx",
        summary=(
            "Native 2× Real-ESRGAN model. Sharper, more faithful results than "
            "downscaling a 4× output — ideal for mild enlargements."
        ),
        default=True,
    ),
    ModelSpec(
        id="realesr-general-x4v3",
        name="Real-ESRGAN General x4 v3 (fast)",
        scale=4,
        size_bytes=4_866_417,
        sha256="1940a93ee08283a0a7286183186357b1688fe9fa8ede74604b424586aaddf112",
        url=(
            "https://huggingface.co/CoderViking/realesr-general-x4v3-onnx/"
            "resolve/c6a971706797c7502945a2b4c4274fce4900d4ab/"
            "realesr-general-x4v3.onnx"
        ),
        filename="realesr_general_x4v3.onnx",
        architecture="SRVGGNetCompact (Real-ESRGAN)",
        summary=(
            "Small, speedy 4× model (~5 MB). A great choice on CPU-only "
            "machines or when speed matters more than maximum detail."
        ),
        default=False,
    ),
)

DEFAULT_MODEL_BY_SCALE = {spec.scale: spec.id for spec in REGISTRY if spec.default}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ModelState:
    """Mutable download/runtime state for one registry entry."""

    spec: ModelSpec
    state: str = "not_downloaded"   # not_downloaded | downloading | ready | error
    progress: float = 0.0           # 0..1 while downloading
    error: Optional[str] = None
    download_cancel: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelStore:
    """Owns the registry state on disk: download, verify, report, delete."""

    def __init__(self, models_dir: Path, specs: Optional[Iterable[ModelSpec]] = None) -> None:
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, ModelState] = {
            spec.id: ModelState(spec=spec) for spec in (specs or REGISTRY)
        }
        self._sync()
        self._delete_hooks: list[Callable[[str], None]] = []

    # --- registry --------------------------------------------------------
    @property
    def specs(self) -> list[ModelSpec]:
        return [s.spec for s in self._states.values()]

    def get_spec(self, model_id: str) -> ModelSpec:
        state = self._states.get(model_id)
        if state is None:
            raise ModelNotFoundError(
                f"Unknown model '{model_id}'.",
                hint="Reload the app; the model list may have changed.",
            )
        return state.spec

    def path(self, model_id: str) -> Path:
        return self.models_dir / self.get_spec(model_id).filename

    def _sync(self) -> None:
        """Reconcile registry state with what is actually on disk."""
        for state in self._states.values():
            path = self.models_dir / state.spec.filename
            if path.exists():
                expected = state.spec.size_bytes
                size_matches = not expected or path.stat().st_size == expected
                hash_matches = (
                    not state.spec.sha256
                    or _sha256_file(path) == state.spec.sha256.lower()
                )
                if not size_matches or not hash_matches:
                    # Incomplete/corrupt leftover — safe to remove, it is
                    # re-downloadable and never user data.
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    state.state = "not_downloaded"
                    state.error = None
                else:
                    state.state = "ready"
                    state.error = None
            elif state.state == "ready":
                state.state = "not_downloaded"

    # --- queries ---------------------------------------------------------
    def is_ready(self, model_id: str) -> bool:
        state = self._states.get(model_id)
        return bool(state and state.state == "ready")

    def require_path(self, model_id: str) -> Path:
        spec = self.get_spec(model_id)
        if not self.is_ready(model_id):
            raise ModelNotFoundError(
                f"The model '{spec.name}' is not installed or failed integrity verification.",
                hint="Open the model manager to download it (one click, stored locally).",
            )
        return self.models_dir / spec.filename

    def status(self, model_id: str) -> dict[str, Any]:
        state = self._states[model_id]
        with state.lock:
            payload = {
                **state.spec.to_dict(),
                "state": state.state,
                "progress": round(state.progress, 4),
                "error": state.error,
                "installed": state.state == "ready",
            }
        return payload

    def statuses(self) -> list[dict[str, Any]]:
        return [self.status(mid) for mid in self._states]

    def model_for_scale(self, scale: int, preference: str = "auto") -> ModelSpec:
        """Pick which installed model should run for the requested scale."""
        candidates = [s for s in self.specs if s.scale == scale]
        if not candidates:
            raise ModelNotFoundError(
                f"No model supports {scale}× upscaling.",
                hint="Only 2× and 4× are available.",
            )
        if preference and preference != "auto" and preference in self._states:
            pref = self._states[preference].spec
            if pref.scale == scale:
                return pref
            raise ModelNotFoundError(
                f"'{pref.name}' does not provide {scale}× upscaling.",
                hint="Choose a matching model or switch the scale.",
            )
        default_id = DEFAULT_MODEL_BY_SCALE.get(scale)
        for spec in candidates:
            if spec.id == default_id:
                return spec
        return candidates[0]

    def delete(self, model_id: str) -> None:
        state = self._states[self.get_spec(model_id).id]
        with state.lock:
            if state.state == "downloading":
                raise ModelDownloadError("A download is already running for this model.")
            path = self.models_dir / state.spec.filename
            if path.exists():
                path.unlink()
            state.state = "not_downloaded"
            state.progress = 0.0
            state.error = None
        self._notify_deleted(model_id)

    # --- hooks ------------------------------------------------------------
    def add_delete_hook(self, fn: Callable[[str], None]) -> None:
        """Register a callback (e.g. the upscaler evicting a session)."""
        self._delete_hooks.append(fn)

    def _notify_deleted(self, model_id: str) -> None:
        for fn in self._delete_hooks:
            try:
                fn(model_id)
            except Exception:
                pass


    # --- downloads ---------------------------------------------------------
    def start_download(self, model_id: str,
                       on_progress: Optional[Callable[[float], None]] = None) -> None:
        """Start a background download. Raises if one is already running."""
        state = self._states[self.get_spec(model_id).id]
        with state.lock:
            if state.state == "downloading":
                raise ModelDownloadError(
                    f"'{state.spec.name}' is already being downloaded."
                )
            state.state = "downloading"
            state.progress = 0.0
            state.error = None
            state.download_cancel = threading.Event()
            thread = threading.Thread(
                target=self._download_worker,
                args=(state, on_progress),
                name=f"model-dl-{state.spec.id}",
                daemon=True,
            )
            state.thread = thread
        thread.start()

    def wait_download(self, model_id: str, timeout: Optional[float] = None) -> bool:
        thread = self._states[self.get_spec(model_id).id].thread
        if thread:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def cancel_download(self, model_id: str) -> None:
        state = self._states[self.get_spec(model_id).id]
        state.download_cancel.set()

    def download_blocking(self, model_id: str,
                          on_progress: Optional[Callable[[float], None]] = None) -> Path:
        """Synchronously download + verify (used by tests and the worker)."""
        state = self._states[self.get_spec(model_id).id]
        with state.lock:
            if state.state == "downloading":
                raise ModelDownloadError(
                    f"'{state.spec.name}' is already being downloaded."
                )
            state.state = "downloading"
            state.progress = 0.0
            state.error = None
            state.download_cancel = threading.Event()
        self._download_worker(state, on_progress)
        with state.lock:
            if state.state == "ready":
                return self.models_dir / state.spec.filename
            error = state.error
        raise ModelDownloadError(
            error or "The model download failed unexpectedly. Please try again."
        )

    def _download_worker(self, state: ModelState,
                         on_progress: Optional[Callable[[float], None]]) -> None:
        import hashlib as _hashlib

        import httpx

        spec = state.spec
        final_path = self.models_dir / spec.filename
        tmp_path = final_path.with_name(final_path.name + ".part")
        cancel = state.download_cancel

        def fail(message: str) -> None:
            with state.lock:
                state.state = "error"
                state.error = message
                state.progress = 0.0
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

        try:
            digest = _hashlib.sha256()
            downloaded = 0
            total = spec.size_bytes or 0
            with httpx.stream(
                "GET",
                spec.url,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, read=60.0),
            ) as response:
                if response.status_code >= 400:
                    fail(
                        f"Download failed (HTTP {response.status_code}). "
                        "Check your connection and try again."
                    )
                    return
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    total = int(content_length)
                with open(tmp_path, "wb") as fh:
                    for chunk in response.iter_bytes(CHUNK):
                        if cancel.is_set():
                            raise ProcessingCancelled("Download cancelled.")
                        fh.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            progress = min(1.0, downloaded / total)
                            with state.lock:
                                state.progress = progress
                            if on_progress:
                                on_progress(progress)




            if cancel.is_set():
                raise ProcessingCancelled("Download cancelled.")

            if spec.sha256:
                actual = digest.hexdigest()
                if actual.lower() != spec.sha256.lower():
                    fail(
                        "The downloaded file failed the integrity check and was "
                        "deleted. Please try again."
                    )
                    return
            if spec.size_bytes and tmp_path.stat().st_size != spec.size_bytes:
                fail(
                    "The downloaded file had the wrong size and was deleted. "
                    "Please try again."
                )
                return

            import os as _os

            _os.replace(tmp_path, final_path)
            with state.lock:
                state.state = "ready"
                state.progress = 1.0
                state.error = None
            if on_progress:
                on_progress(1.0)
        except ProcessingCancelled:
            fail("Download cancelled.")
            with state.lock:
                state.state = "not_downloaded"
                state.error = None
        except httpx.HTTPError as exc:
            fail(
                "Could not reach the download server. Check your internet "
                "connection and try again."
            )
            _log_download_error(spec.id, f"{type(exc).__name__}: {exc}")
        except OSError as exc:
            fail("Could not save the model file. Check disk space and permissions.")
            _log_download_error(spec.id, f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # defensive: never crash the thread silently
            fail("The model download failed unexpectedly. Please try again.")
            _log_download_error(spec.id, f"{type(exc).__name__}: {exc}")


def _log_download_error(model_id: str, detail: str) -> None:
    import logging

    logging.getLogger("biya_upscale").warning(
        "model download error (%s): %s", model_id, detail
    )
