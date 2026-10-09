"""Serial job queue: one image in flight at a time.

Why serial? Peak RAM/VRAM stays bounded regardless of batch size, progress
reporting stays honest, and one failing image can never stall or kill the
rest of the batch — each job carries its own error state.
"""

from __future__ import annotations

import gc
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import AppConfig
from .errors import BiyaError, OutOfMemoryError, ProcessingCancelled
from .imaging import check_dimensions, load_image_path, make_preview, save_image
from .model_store import ModelStore
from .upscaler import Upscaler

log = logging.getLogger("biya_upscale")

TERMINAL_STATUSES = ("done", "failed", "cancelled")
_MAX_JOB_RECORDS = 500

# Keys in the result dict that must never leave the server process.
_INTERNAL_RESULT_KEYS = ("path", "preview_path")


@dataclass
class Job:
    id: str
    image_id: str
    input_path: Path
    filename: str
    src_width: int
    src_height: int
    scale: int
    model_id: str
    status: str = "queued"
    progress: float = 0.0
    error: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        result = None
        if self.result:
            result = {
                k: v for k, v in self.result.items() if k not in _INTERNAL_RESULT_KEYS
            }
        return {
            "id": self.id,
            "image_id": self.image_id,
            "filename": self.filename,
            "src_width": self.src_width,
            "src_height": self.src_height,
            "scale": self.scale,
            "model_id": self.model_id,
            "status": self.status,
            "progress": round(self.progress, 4),
            "error": self.error,
            "result": result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class Pipeline:
    """The real work for one job: load → AI upscale → save outputs."""

    def __init__(self, config: AppConfig, store: ModelStore, upscaler: Upscaler) -> None:
        self.config = config
        self.store = store
        self.upscaler = upscaler

    def run(self, job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        img = load_image_path(job.input_path)
        check_dimensions(img.width, img.height, scale=job.scale)

        spec = self.store.get_spec(job.model_id)
        if spec.scale != job.scale:
            raise BiyaError(
                f"{spec.name} cannot produce {job.scale}× output.",
                hint="Choose a matching scale factor.",
            )
        model_path = self.store.require_path(job.model_id)

        def on_progress(frac: float) -> None:
            job.progress = max(0.05, min(0.98, 0.05 + 0.93 * float(frac)))

        try:
            outcome = self.upscaler.upscale_image(
                img,
                spec,
                model_path,
                factor=job.scale,
                progress=on_progress,
                cancel=job.cancel,
            )
            result_id = uuid.uuid4().hex
            full_path = self.config.results_dir / f"{result_id}.png"
            preview_path = self.config.results_dir / f"{result_id}.preview.jpg"

            save_image(outcome.image, full_path, fmt="PNG")
            preview = make_preview(outcome.image, max_side=1600)
            save_image(preview, preview_path, fmt="JPEG", quality=82)

            duration = time.perf_counter() - started
            stem = Path(job.filename).stem or "image"
            job.progress = 1.0
            return {
                "result_id": result_id,
                "width": outcome.image.width,
                "height": outcome.image.height,
                "duration_s": round(duration, 2),
                "inference_s": round(outcome.inference_seconds, 2),
                "device": outcome.device.label,
                "device_id": outcome.device.id,
                "model": spec.name,
                "tile": outcome.tile,
                "download_stem": f"{stem}_{job.scale}x",
                "path": str(full_path),
                "preview_path": str(preview_path),
            }
        finally:
            del img
            gc.collect()


class JobManager:
    """Single worker thread + queue. Owns job lifecycle and cancellation."""

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._queue: "queue.Queue[Optional[Job]]" = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._stopped = False
        self._worker = threading.Thread(
            target=self._loop, name="biya-job-worker", daemon=True
        )
        self._worker.start()

    # --- lifecycle ---------------------------------------------------------
    def submit(self, *, image_id: str, input_path: Path, filename: str,
               src_width: int, src_height: int, scale: int, model_id: str) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            image_id=image_id,
            input_path=Path(input_path),
            filename=filename,
            src_width=src_width,
            src_height=src_height,
            scale=scale,
            model_id=model_id,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._prune_locked()
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def jobs_for_image(self, image_id: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.image_id == image_id]

    def cancel(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.terminal:
            return job
        job.cancel.set()
        if job.status == "queued":
            # Never started — finalize immediately; the worker will skip it.
            job.status = "cancelled"
            job.finished_at = time.time()
            job.error = {"code": "cancelled", "message": "Cancelled before it started."}
        return job

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if not job.terminal:
                self.cancel(job.id)

    def drop_image(self, image_id: str, wait: float = 2.0) -> None:
        """Cancel + forget every job belonging to an image; delete results."""
        jobs = self.jobs_for_image(image_id)
        for job in jobs:
            self.cancel(job.id)
        deadline = time.time() + wait
        while any(
            not j.terminal and j.status == "running" for j in jobs
        ) and time.time() < deadline:
            time.sleep(0.05)
        for job in jobs:
            self._delete_result_files(job)
            with self._lock:
                self._jobs.pop(job.id, None)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if not j.terminal)

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == "queued")

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.cancel_all()
        self._queue.put(None)
        self._worker.join(timeout=10)

    # --- internals ----------------------------------------------------------
    def _prune_locked(self) -> None:
        if len(self._jobs) <= _MAX_JOB_RECORDS:
            return
        terminal = sorted(
            (j for j in self._jobs.values() if j.terminal),
            key=lambda j: j.finished_at or 0,
        )
        overflow = len(self._jobs) - _MAX_JOB_RECORDS
        for job in terminal[:overflow]:
            self._jobs.pop(job.id, None)

    @staticmethod
    def _delete_result_files(job: Job) -> None:
        if not job.result:
            return
        for key in _INTERNAL_RESULT_KEYS:
            path = job.result.get(key)
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            if job.cancel.is_set() and job.status == "cancelled":
                continue
            job.status = "running"
            job.started_at = time.time()
            try:
                if job.cancel.is_set():
                    raise ProcessingCancelled("Processing cancelled.")
                job.result = self._pipeline.run(job)
                job.status = "done"
                job.progress = 1.0
            except ProcessingCancelled:
                job.status = "cancelled"
                job.error = {"code": "cancelled", "message": "Processing was cancelled."}
            except BiyaError as exc:
                job.status = "failed"
                job.error = exc.to_dict()
                log.warning("job %s failed: %s", job.id, exc.message)
            except MemoryError as exc:
                job.status = "failed"
                job.error = OutOfMemoryError().to_dict()
                log.warning("job %s out of memory: %s", job.id, exc)
            except Exception as exc:  # keep the batch alive no matter what
                job.status = "failed"
                job.error = {
                    "code": "internal",
                    "message": "Something went wrong while processing this image.",
                    "hint": "Try again — details were written to the log file.",
                }
                log.exception("job %s crashed: %s", job.id, exc)
            finally:
                job.finished_at = time.time()
                gc.collect()

