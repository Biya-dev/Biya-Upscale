"""FastAPI application: local-only API + static UI.

Security posture:

* Binds to 127.0.0.1 only (never exposed to the network).
* Rejects cross-origin mutating requests (a malicious site cannot drive the
  local API through the user's browser).
* Standard hardening headers on every response.
* Uploads are validated by decoding, never executed, stored under the app's
  own data directory, and originals are never touched.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__
from .config import AppConfig
from .errors import (
    BiyaError,
    InvalidRequestError,
    NotFoundError,
    ModelNotFoundError,
)
from .hardware import detect_hardware
from .imaging import (
    MAX_FILE_BYTES,
    check_dimensions,
    check_extension,
    extension_for_format,
    image_info,
    load_image_bytes,
    normalize_format,
    sanitize_filename,
    validate_scale,
)
from .jobs import JobManager, Job, Pipeline
from .model_store import ModelStore
from .upscaler import Upscaler

log = logging.getLogger("biya_upscale")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


@dataclass
class ImageRecord:
    id: str
    path: Path
    filename: str
    width: int
    height: int
    size_bytes: int
    format: str
    has_alpha: bool
    added_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "format": self.format,
            "has_alpha": self.has_alpha,
            "added_at": self.added_at,
        }


@dataclass
class AppContext:
    config: AppConfig
    store: ModelStore
    upscaler: Upscaler
    jobs: JobManager
    images: dict[str, ImageRecord]
    settings: dict[str, Any]
    started_at: float = field(default_factory=time.time)


def _find_web_dir() -> Optional[Path]:
    """Locate the built frontend (dev tree, packaged data, or env override)."""
    import os
    import sys

    candidates: list[Path] = []
    env = os.environ.get("BIYA_WEB_DIR")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve().parent
    candidates.append(here / "web")                      # PyInstaller data dir
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "web")
    candidates.append(here.parents[1] / "frontend" / "dist")  # repo checkout
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    return None


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=__version__, docs_url=None,
                  redoc_url=None, openapi_url=None)

    # --- middleware --------------------------------------------------------
    @app.middleware("http")
    async def _guard(request: Request, call_next):
        request_host = request.headers.get("host", "")
        try:
            host = urllib.parse.urlsplit(f"//{request_host}").hostname or ""
        except ValueError:
            host = ""
        if host.lower().rstrip(".") not in _LOCAL_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"error": {
                    "code": "forbidden_host",
                    "message": "Requests for non-local hosts are blocked.",
                }},
            )

        origin = request.headers.get("origin")
        if origin:
            try:
                origin_host = urllib.parse.urlparse(origin).hostname or ""
            except ValueError:
                origin_host = ""
            if origin_host.lower().rstrip(".") not in _LOCAL_HOSTS:
                return JSONResponse(
                    status_code=403,
                    content={"error": {
                        "code": "forbidden_origin",
                        "message": "Requests from other origins are blocked.",
                    }},
                )

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'",
        )
        return response

    # --- error handling -----------------------------------------------------
    @app.exception_handler(BiyaError)
    async def _biya_error(_request: Request, exc: BiyaError):
        if exc.detail:
            log.warning("api error (%s): %s", exc.code, exc.detail)
        return JSONResponse(status_code=exc.status, content={"error": exc.to_dict()})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        log.exception("unhandled API error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": {
                "code": "internal",
                "message": "Something went wrong on the server.",
                "hint": "Check the log file for details.",
            }},
        )

    # --- basics --------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        force_cpu = bool(ctx.settings.get("force_cpu"))
        hardware_info = detect_hardware(force_cpu=force_cpu)
        active = ctx.upscaler.active_device
        return {
            "app_name": APP_NAME,
            "version": __version__,
            "device": (active or hardware_info.preferred).to_dict(),
            "detected_device": hardware_info.preferred.to_dict(),
            "devices": [d.to_dict() for d in hardware_info.devices],
            "active": active.to_dict() if active else None,
            "compiled_providers": hardware_info.compiled_providers,
            "models": ctx.store.statuses(),
            "pending_jobs": ctx.jobs.pending_count(),
            "active_jobs": ctx.jobs.active_count(),
            "settings": {
                "theme": ctx.settings.get("theme"),
                "scale": ctx.settings.get("scale", 2),
                "output_format": ctx.settings.get("output_format", "auto"),
                "quality": ctx.settings.get("quality", 95),
                "model_preference": ctx.settings.get("model_preference", "auto"),
                "force_cpu": force_cpu,
            },
            "privacy": (
                "All processing is local. Images never leave this computer."
            ),
        }

    @app.post("/api/settings")
    async def update_settings(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception as exc:
            raise InvalidRequestError("Invalid settings payload.") from exc
        if not isinstance(payload, dict):
            raise InvalidRequestError("Invalid settings payload.")
        allowed = {"theme", "scale", "output_format", "quality",
                   "model_preference", "force_cpu"}
        updates = {k: v for k, v in payload.items() if k in allowed}
        ctx.settings = ctx.config.save_settings(updates)
        if "force_cpu" in updates:
            ctx.upscaler.force_cpu = bool(updates["force_cpu"])
            ctx.upscaler.release()  # rebuild sessions on the right device
        return {"settings": ctx.settings}

    # --- images ---------------------------------------------------------------
    @app.post("/api/images")
    async def upload_image(request: Request, filename: str = Query(...)) -> dict[str, Any]:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_FILE_BYTES:
            raise InvalidRequestError(
                "This file is larger than the 150 MB limit.",
                hint="Try a smaller image.",
            )
        data = await request.body()
        if not data:
            raise InvalidRequestError("No file data received.", hint="Try selecting the file again.")
        display_name = sanitize_filename(filename)
        check_extension(display_name)  # raises UnsupportedFormatError early
        img = load_image_bytes(data, filename=display_name)

        image_id = uuid.uuid4().hex
        ext = Path(display_name).suffix.lower()
        stored = ctx.config.inputs_dir / f"{image_id}{ext}"
        stored.write_bytes(data)

        info = image_info(img, filename=display_name, size_bytes=len(data))
        record = ImageRecord(
            id=image_id,
            path=stored,
            filename=info["filename"],
            width=info["width"],
            height=info["height"],
            size_bytes=info["size_bytes"],
            format=info["format"],
            has_alpha=info["has_alpha"],
        )
        ctx.images[image_id] = record
        img.close()
        return record.to_dict()

    @app.get("/api/images")
    async def list_images() -> dict[str, Any]:
        return {"images": [r.to_dict() for r in ctx.images.values()]}

    @app.get("/api/images/{image_id}/file")
    async def image_file(image_id: str) -> FileResponse:
        record = ctx.images.get(image_id)
        if record is None or not record.path.exists():
            raise NotFoundError("That image is no longer available.")
        media = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
            record.format, "application/octet-stream"
        )
        return FileResponse(
            record.path, media_type=media, filename=record.filename,
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/images/{image_id}")
    async def delete_image(image_id: str) -> dict[str, Any]:
        record = ctx.images.pop(image_id, None)
        if record is None:
            raise NotFoundError("That image is no longer in the list.")
        ctx.jobs.drop_image(image_id)
        try:
            record.path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True}


    # --- model management --------------------------------------------------
    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        return {"models": ctx.store.statuses()}

    @app.post("/api/models/{model_id}/download")
    async def download_model(model_id: str) -> dict[str, Any]:
        ctx.store.get_spec(model_id)  # validates id
        ctx.store.start_download(model_id)
        return {"ok": True, "model": ctx.store.status(model_id)}

    @app.post("/api/models/{model_id}/cancel-download")
    async def cancel_model_download(model_id: str) -> dict[str, Any]:
        ctx.store.cancel_download(model_id)
        return {"ok": True}

    @app.delete("/api/models/{model_id}")
    async def delete_model(model_id: str) -> dict[str, Any]:
        ctx.store.delete(model_id)
        return {"ok": True}

    # --- processing ----------------------------------------------------------
    @app.post("/api/upscale")
    async def start_upscale(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception as exc:
            raise InvalidRequestError("Invalid request body.") from exc
        if not isinstance(payload, dict):
            raise InvalidRequestError("Invalid request body.")

        image_id = str(payload.get("image_id") or "")
        record = ctx.images.get(image_id)
        if record is None:
            raise NotFoundError(
                "That image is no longer selected.",
                hint="Add the image again and retry.",
            )
        try:
            scale = int(payload.get("scale") or 0)
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError("Scale must be 2 or 4.") from exc
        validate_scale(scale)
        check_dimensions(record.width, record.height, scale=scale)

        preference = str(
            payload.get("model_id")
            or ctx.settings.get("model_preference")
            or "auto"
        )
        spec = ctx.store.model_for_scale(scale, preference)
        if not ctx.store.is_ready(spec.id):
            raise ModelNotFoundError(
                f"The model '{spec.name}' has not been downloaded yet.",
                hint="Open the model manager to download it — it stays on your computer.",
            )

        job = ctx.jobs.submit(
            image_id=image_id,
            input_path=record.path,
            filename=record.filename,
            src_width=record.width,
            src_height=record.height,
            scale=scale,
            model_id=spec.id,
        )
        return {"job_id": job.id, "job": job.to_dict()}


    # --- job results ----------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = ctx.jobs.get(job_id)
        if job is None:
            raise NotFoundError("That job is no longer available.")
        return job.to_dict()

    @app.get("/api/jobs")
    async def all_jobs() -> dict[str, Any]:
        return {"jobs": [j.to_dict() for j in _visible_jobs(ctx)]}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict[str, Any]:
        job = ctx.jobs.cancel(job_id)
        if job is None:
            raise NotFoundError("That job is no longer available.")
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/preview")
    async def job_preview(job_id: str) -> FileResponse:
        job = ctx.jobs.get(job_id)
        if job is None or job.status != "done" or not job.result:
            raise NotFoundError("No preview is available yet.")
        preview = Path(job.result["preview_path"])
        if not preview.exists():
            raise NotFoundError("No preview is available yet.")
        return FileResponse(
            preview, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    _MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

    @app.get("/api/jobs/{job_id}/download")
    async def download_result(
        job_id: str,
        format: Optional[str] = Query(None),
        quality: int = Query(95, ge=1, le=100),
    ) -> FileResponse:
        job = ctx.jobs.get(job_id)
        if job is None or job.status != "done" or not job.result:
            raise NotFoundError("That result is no longer available.")
        src = Path(job.result["path"])
        if not src.exists():
            raise NotFoundError("That result file is no longer on disk.")

        fmt = normalize_format(format) if format else "PNG"
        ext = extension_for_format(fmt)
        download_name = f"{job.result['download_stem']}{ext}"

        if fmt == "PNG":
            return FileResponse(
                src,
                media_type="image/png",
                filename=download_name,
                headers={"Cache-Control": "no-store"},
            )

        from PIL import Image

        from .imaging import save_image as _save

        img = Image.open(src)
        img.load()
        tmp_dir = ctx.config.results_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"{uuid.uuid4().hex}{ext}"
        try:
            _save(img, tmp, fmt=fmt, quality=quality)
        finally:
            img.close()
        from starlette.background import BackgroundTask

        return FileResponse(
            tmp,
            media_type=_MEDIA_TYPES[fmt],
            filename=download_name,
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(_unlink_quiet, tmp),
        )

    # --- static frontend ------------------------------------------------------
    web_dir = _find_web_dir()
    if web_dir is not None:
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        async def _missing_ui() -> HTMLResponse:
            return HTMLResponse(
                "<!doctype html><meta charset='utf-8'><title>Biya Upscale</title>"
                "<style>body{font:16px/1.6 system-ui;background:#0b0f14;color:#e7ecf3;"
                "display:grid;place-items:center;height:100vh;margin:0}"
                "main{max-width:34rem;padding:2rem;text-align:center}"
                "code{background:#182230;padding:.15rem .4rem;border-radius:.35rem}"
                "</style><main><h1>Biya Upscale</h1>"
                "<p>The interface has not been built yet.</p>"
                "<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> "
                "and restart the app.</p></main>",
                status_code=503,
            )

    return app


def _visible_jobs(ctx: AppContext) -> list[Job]:
    with ctx.jobs._lock:  # read-only snapshot
        return list(ctx.jobs._jobs.values())


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
