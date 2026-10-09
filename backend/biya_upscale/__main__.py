"""Entry point: ``python run.py`` or ``python -m biya_upscale``.

Starts the local server (127.0.0.1 only) and opens either a native window
(pywebview, if installed) or the default browser.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from . import APP_NAME, __version__
from .config import AppConfig, resolve_port
from .hardware import detect_hardware
from .jobs import JobManager, Pipeline
from .model_store import ModelStore
from .server import AppContext, create_app
from .upscaler import Upscaler

log = logging.getLogger("biya_upscale")


def setup_logging(data_dir: Path, verbose: bool = False) -> None:
    """File log (rotating) + concise console output. Never a stack trace in the UI."""
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("biya_upscale")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(console)


def find_free_port(start: int, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biya-upscale",
        description="Private, local AI image upscaling — nothing is uploaded.",
    )
    parser.add_argument("--port", type=int, default=None, help="local port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open any UI")
    parser.add_argument("--window", action="store_true", help="force the native window")
    parser.add_argument("--browser", action="store_true", help="force the browser UI")
    parser.add_argument("--force-cpu", action="store_true", help="ignore GPUs and use the CPU")
    parser.add_argument("--data-dir", default=None, help="override the data directory")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {__version__}")
    return parser


def _wait_ready(url: str, timeout: float = 15.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = httpx.get(url + "api/health", timeout=1.0)
            if response.status_code == 200:
                return True
        except Exception:
            time.sleep(0.15)
    return False


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    config = AppConfig(Path(args.data_dir)) if args.data_dir else AppConfig()
    config.ensure_dirs()
    setup_logging(config.data_dir, verbose=args.verbose)
    settings = config.load_settings()

    force_cpu = bool(args.force_cpu or settings.get("force_cpu"))
    hardware_info = detect_hardware(force_cpu=force_cpu)
    log.info(
        "processing device: %s | runtime providers: %s",
        hardware_info.preferred.label,
        ", ".join(hardware_info.compiled_providers) or "none detected",
    )

    store = ModelStore(config.models_dir)
    upscaler = Upscaler(force_cpu=force_cpu)
    store.add_delete_hook(upscaler.release)
    pipeline = Pipeline(config, store, upscaler)
    jobs = JobManager(pipeline)
    ctx = AppContext(
        config=config,
        store=store,
        upscaler=upscaler,
        jobs=jobs,
        images={},
        settings=settings,
    )
    app = create_app(ctx)

    port = find_free_port(resolve_port(args.port))
    url = f"http://127.0.0.1:{port}/"

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None,
                       access_log=False)
    )

    want_window = (
        (args.window or bool(settings.get("window", True)))
        and not args.browser
        and not args.no_browser
    )
    webview = None
    if want_window:
        try:
            import webview as webview  # type: ignore  # noqa: F401
        except Exception:
            log.info("native window support not installed — using the browser")

    print(f"\n  {APP_NAME} {__version__}")
    print(f"  {url}")
    print("  All processing is local. Images never leave this computer.\n")

    server_thread: Optional[threading.Thread] = None
    used_window = False
    try:
        if webview is not None:
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            if not _wait_ready(url):
                raise RuntimeError("server did not start in time")
            try:
                webview.create_window(
                    APP_NAME, url, width=1240, height=840, min_size=(920, 620)
                )
                webview.start()
                used_window = True
            except Exception as exc:
                log.warning("native window failed (%s) — falling back to browser", exc)

        if not used_window:
            if server_thread is None:
                # Run uvicorn on the main thread; open the browser shortly after.
                if not args.no_browser:
                    threading.Timer(0.8, lambda: _open(url)).start()
                server.run()
            else:
                # Window failed but the server thread is live: browse + wait.
                if not args.no_browser:
                    _open(url)
                print("  Press Ctrl+C to quit.")
                while server_thread.is_alive():
                    server_thread.join(0.5)
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.should_exit = True
        jobs.shutdown()
        upscaler.release()
        log.info("stopped")
    return 0


def _open(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())

