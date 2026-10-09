"""Job queue semantics: serial processing, isolation, cancellation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from biya_upscale.errors import (
    BiyaError,
    CorruptImageError,
    ProcessingCancelled,
)
from biya_upscale.jobs import JobManager


class FakePipeline:
    """Deterministic pipeline double: behaviour keyed off the filename."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, job) -> dict:
        self.calls.append(job.filename)
        if job.filename.startswith("boom"):
            raise RuntimeError("kaboom — raw detail must stay in the log")
        if job.filename.startswith("denied"):
            raise CorruptImageError(
                "This image is damaged and could not be fully read."
            )
        if job.filename.startswith("oom"):
            raise MemoryError("malloc failed")
        if job.filename.startswith("slow"):
            self.started.set()
            for _ in range(400):  # ~8s max
                if job.cancel.is_set():
                    raise ProcessingCancelled("Processing cancelled.")
                if self.release.wait(0.02):
                    break
        job.progress = 1.0
        return {
            "result_id": job.filename, "width": 8, "height": 8,
            "duration_s": 0.01, "inference_s": 0.01, "device": "CPU",
            "device_id": "cpu", "model": "fake", "tile": 16,
            "download_stem": "x", "path": "/tmp/x", "preview_path": "/tmp/p",
        }


def submit(manager: JobManager, name: str, image_id: str = "img-1"):
    return manager.submit(
        image_id=image_id,
        input_path=Path(f"/nonexistent/{name}"),
        filename=name,
        src_width=4,
        src_height=4,
        scale=2,
        model_id="fake-model",
    )


def wait_terminal(manager: JobManager, job_id: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job and job.terminal:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal state")


@pytest.fixture()
def manager():
    fake = FakePipeline()
    mgr = JobManager(fake)  # type: ignore[arg-type]
    yield mgr, fake
    mgr.shutdown()


class TestSuccessAndFailure:
    def test_successful_job(self, manager) -> None:
        mgr, _ = manager
        job = submit(mgr, "ok.png")
        final = wait_terminal(mgr, job.id)
        assert final.status == "done"
        assert final.progress == 1.0
        assert final.result["width"] == 8
        assert final.error is None
        assert final.started_at and final.finished_at

    def test_biya_error_is_friendly(self, manager) -> None:
        mgr, _ = manager
        job = submit(mgr, "denied.png")
        final = wait_terminal(mgr, job.id)
        assert final.status == "failed"
        assert final.error["code"] == "corrupt_image"
        assert "Traceback" not in final.error["message"]

    def test_crash_never_escapes(self, manager) -> None:
        mgr, _ = manager
        job = submit(mgr, "boom.png")
        final = wait_terminal(mgr, job.id)
        assert final.status == "failed"
        assert final.error["code"] == "internal"
        assert "kaboom" not in final.error["message"]  # raw detail hidden

    def test_memory_error_maps_to_oom(self, manager) -> None:
        mgr, _ = manager
        job = submit(mgr, "oom.png")
        final = wait_terminal(mgr, job.id)
        assert final.status == "failed"
        assert final.error["code"] == "out_of_memory"

    def test_one_failure_does_not_stop_the_batch(self, manager) -> None:
        mgr, fake = manager
        ids = [
            submit(mgr, "ok1.png").id,
            submit(mgr, "boom.png").id,
            submit(mgr, "denied.png").id,
            submit(mgr, "ok2.png").id,
        ]
        finals = [wait_terminal(mgr, jid) for jid in ids]
        assert [j.status for j in finals] == ["done", "failed", "failed", "done"]
        # serial execution order preserved
        assert fake.calls == ["ok1.png", "boom.png", "denied.png", "ok2.png"]

    def test_serial_processing_one_at_a_time(self, manager) -> None:
        mgr, _ = manager
        jobs = [submit(mgr, f"ok{i}.png") for i in range(3)]
        finals = [wait_terminal(mgr, j.id) for j in jobs]
        assert all(j.status == "done" for j in finals)
        starts = [j.started_at for j in finals]
        ends = [j.finished_at for j in finals]
        # strictly serialized: each job starts after the previous finished
        assert starts[1] >= ends[0] - 0.01
        assert starts[2] >= ends[1] - 0.01


class TestCancellation:
    def test_cancel_queued_job(self, manager) -> None:
        mgr, fake = manager
        blocker = submit(mgr, "slow.png")
        queued = submit(mgr, "ok.png")
        assert fake.started.wait(5)
        cancelled = mgr.cancel(queued.id)
        assert cancelled is not None
        fake.release.set()
        wait_terminal(mgr, blocker.id)
        final = wait_terminal(mgr, queued.id)
        assert final.status == "cancelled"

    def test_cancel_running_job(self, manager) -> None:
        mgr, fake = manager
        job = submit(mgr, "slow.png")
        assert fake.started.wait(5)
        mgr.cancel(job.id)
        fake.release.set()
        final = wait_terminal(mgr, job.id)
        assert final.status in ("cancelled", "done")
        if final.status == "cancelled":
            assert final.error["code"] == "cancelled"

    def test_cancel_is_idempotent(self, manager) -> None:
        mgr, _ = manager
        job = submit(mgr, "ok.png")
        mgr.cancel(job.id)
        mgr.cancel(job.id)
        final = wait_terminal(mgr, job.id)
        assert final.status in ("cancelled", "done")

    def test_cancel_unknown_job_returns_none(self, manager) -> None:
        mgr, _ = manager
        assert mgr.cancel("nope") is None


class TestBookkeeping:
    def test_jobs_for_image_and_drop(self, manager) -> None:
        mgr, _ = manager
        a1 = submit(mgr, "a1.png", image_id="A")
        a2 = submit(mgr, "a2.png", image_id="A")
        b1 = submit(mgr, "b1.png", image_id="B")
        wait_terminal(mgr, a1.id)
        wait_terminal(mgr, a2.id)
        wait_terminal(mgr, b1.id)
        assert len(mgr.jobs_for_image("A")) == 2
        mgr.drop_image("A")
        assert mgr.get(a1.id) is None
        assert mgr.get(a2.id) is None
        assert mgr.get(b1.id) is not None

    def test_result_paths_not_serialised(self, manager) -> None:
        mgr, _ = manager
        job = submit(mgr, "ok.png")
        final = wait_terminal(mgr, job.id)
        payload = final.to_dict()
        assert "path" not in payload["result"]
        assert "preview_path" not in payload["result"]
        assert final.result["path"] == "/tmp/x"  # kept server-side

    def test_active_and_pending_counts(self, manager) -> None:
        mgr, fake = manager
        blocker = submit(mgr, "slow.png")
        assert fake.started.wait(5)
        queued = submit(mgr, "ok.png")
        assert mgr.active_count() >= 1
        assert mgr.pending_count() >= 1
        fake.release.set()
        wait_terminal(mgr, blocker.id)
        wait_terminal(mgr, queued.id)
        assert mgr.active_count() == 0
        assert mgr.pending_count() == 0

