"""Shared fixtures for the Biya Upscale test suite.

Design notes:

* Every test that touches disk uses an isolated ``BIYA_DATA_DIR`` (tmp).
* Real AI models live in the app's normal model directory — downloaded once
  (by ``tools/download_models.py`` or the app itself). Tests that need real
  inference skip cleanly when the models or network are unavailable.
* Processing in tests is forced onto the CPU for determinism; GPU detection
  has its own dedicated test.
"""

from __future__ import annotations

import io
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from biya_upscale.config import AppConfig  # noqa: E402
from biya_upscale.jobs import JobManager, Pipeline  # noqa: E402
from biya_upscale.model_store import ModelStore  # noqa: E402
from biya_upscale.server import AppContext, create_app  # noqa: E402
from biya_upscale.upscaler import Upscaler  # noqa: E402

# The canonical (non-tmp) app config — owns the shared model directory.
REAL_CONFIG = AppConfig()


@pytest.fixture()
def data_dir(tmp_path: Path) -> AppConfig:
    """Isolated app config rooted in a temp directory."""
    config = AppConfig(tmp_path / "biya-data")
    config.ensure_dirs()
    return config


@pytest.fixture(scope="session")
def model_store() -> ModelStore:
    """The real model store; downloads models once if they are missing."""
    store = ModelStore(REAL_CONFIG.models_dir)
    missing = [s.id for s in store.specs if not store.is_ready(s.id)]
    if missing:
        try:
            for model_id in missing:
                store.download_blocking(model_id)
        except Exception as exc:  # network unavailable
            pytest.skip(f"models unavailable and download failed: {exc}")
    return store


@pytest.fixture(scope="session")
def upscaler() -> Upscaler:
    """A shared CPU upscaler (session creation is expensive)."""
    up = Upscaler(force_cpu=True)
    yield up
    up.release()


# --- image fixtures ---------------------------------------------------------
def make_test_image(width: int = 32, height: int = 24, fmt: str = "PNG",
                    mode: str = "RGB", **save_kwargs) -> bytes:
    img = Image.new(mode, (width, height), (30, 120, 200, 255) if mode == "RGBA" else (30, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


@pytest.fixture()
def png_bytes() -> bytes:
    return make_test_image(32, 24, "PNG")


@pytest.fixture()
def jpg_bytes() -> bytes:
    return make_test_image(40, 30, "JPEG", quality=90)


@pytest.fixture()
def webp_bytes() -> bytes:
    return make_test_image(36, 28, "WEBP")


@pytest.fixture()
def rgba_png_bytes() -> bytes:
    return make_test_image(32, 24, "PNG", mode="RGBA")


@pytest.fixture()
def corrupt_bytes() -> bytes:
    # A file with a valid PNG magic number but garbage payload.
    return b"\x89PNG\r\n\x1a\n" + b"this is not a real png payload" * 4


@pytest.fixture()
def local_http_server():
    """Serve a temp directory over localhost HTTP (for download tests)."""
    import tempfile
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = Path(tempfile.mkdtemp(prefix="biya-http-"))

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D102
            pass

    def handler(*args, **kwargs):
        return QuietHandler(*args, directory=str(root), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Server:
        url_root = f"http://127.0.0.1:{server.server_address[1]}"
        directory = root

        def shutdown(self):
            server.shutdown()
            server.server_close()

    server_obj = Server()
    yield server_obj
    server_obj.shutdown()


# --- application fixtures ----------------------------------------------------
@pytest.fixture()
def app_ctx(data_dir: AppConfig, model_store: ModelStore, upscaler: Upscaler):
    """Full application context on isolated dirs with real models."""
    context = AppContext(
        config=data_dir,
        store=ModelStore(model_store.models_dir),  # same models, fresh state
        upscaler=upscaler,
        jobs=JobManager(Pipeline(data_dir, model_store, upscaler)),
        images={},
        settings=data_dir.load_settings(),
    )
    yield context
    context.jobs.shutdown()


@pytest.fixture()
def client(app_ctx: AppContext):
    from fastapi.testclient import TestClient

    with TestClient(
        create_app(app_ctx), base_url="http://127.0.0.1"
    ) as test_client:
        yield test_client


@pytest.fixture()
def client_no_models(data_dir: AppConfig, upscaler: Upscaler):
    """App whose model directory is empty (model-missing flows)."""
    empty_models = ModelStore(data_dir.models_dir, specs=())
    context = AppContext(
        config=data_dir,
        store=empty_models,
        upscaler=upscaler,
        jobs=JobManager(Pipeline(data_dir, empty_models, upscaler)),
        images={},
        settings=data_dir.load_settings(),
    )
    from biya_upscale.model_store import REGISTRY

    # Register the real specs but with no files on disk.
    empty_models._states.clear()
    for spec in REGISTRY:
        from biya_upscale.model_store import ModelState

        empty_models._states[spec.id] = ModelState(spec=spec)

    from fastapi.testclient import TestClient

    with TestClient(
        create_app(context), base_url="http://127.0.0.1"
    ) as test_client:
        yield test_client
    context.jobs.shutdown()


@pytest.fixture()
def wait_for_job():
    """Poll helper: wait until a job reaches a terminal state."""
    import time as _time

    from biya_upscale.jobs import TERMINAL_STATUSES

    def _wait(jobs: JobManager, job_id: str, timeout: float = 60.0):
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            job = jobs.get(job_id)
            if job is not None and job.status in TERMINAL_STATUSES:
                return job
            _time.sleep(0.05)
        raise AssertionError(f"job {job_id} did not finish in {timeout}s")

    return _wait
