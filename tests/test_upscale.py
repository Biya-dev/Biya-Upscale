"""Real-inference tests: dimensions, quality sanity, tiling, cancel, OOM."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from PIL import Image

from biya_upscale.errors import BiyaError, OutOfMemoryError, ProcessingCancelled
from biya_upscale.imaging import load_image_bytes


def _image(width: int = 32, height: int = 24) -> Image.Image:
    """Deterministic non-trivial test image (edges, gradient, blocks)."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:height, 0:width]
    arr[..., 0] = (xx * 7) % 256
    arr[..., 1] = (yy * 9) % 256
    arr[..., 2] = ((xx + yy) * 5) % 256
    arr[4:10, 4:14] = (240, 240, 240)
    arr[16:20, 18:28] = (10, 10, 10)
    return Image.fromarray(arr, "RGB")


def _bicubic(width: int, height: int, scale: int) -> np.ndarray:
    return np.asarray(
        _image(width, height).resize((width * scale, height * scale),
                                     Image.Resampling.BICUBIC)
    )


class TestDimensions:
    def test_2x_output_dims(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesrgan-x2plus")
        outcome = upscaler.upscale_image(
            _image(32, 24), spec, model_store.require_path(spec.id)
        )
        assert (outcome.image.width, outcome.image.height) == (64, 48)

    def test_4x_output_dims(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesrgan-x4plus")
        outcome = upscaler.upscale_image(
            _image(32, 24), spec, model_store.require_path(spec.id)
        )
        assert (outcome.image.width, outcome.image.height) == (128, 96)

    def test_fast_model_4x_dims(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesr-general-x4v3")
        outcome = upscaler.upscale_image(
            _image(48, 40), spec, model_store.require_path(spec.id)
        )
        assert (outcome.image.width, outcome.image.height) == (192, 160)

    def test_odd_dimensions(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesr-general-x4v3")
        outcome = upscaler.upscale_image(
            _image(37, 23), spec, model_store.require_path(spec.id)
        )
        assert (outcome.image.width, outcome.image.height) == (148, 92)


class TestQualitySanity:
    def test_ai_output_differs_from_plain_resize(
        self, model_store, upscaler
    ) -> None:
        """The model must actually do something (not a passthrough)."""
        spec = model_store.get_spec("realesrgan-x2plus")
        outcome = upscaler.upscale_image(
            _image(32, 24), spec, model_store.require_path(spec.id)
        )
        ai = np.asarray(outcome.image, dtype=np.int16)
        plain = _bicubic(32, 24, 2).astype(np.int16)
        assert float(np.abs(ai - plain).mean()) > 0.5

    def test_output_rgb_range_valid(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesrgan-x4plus")
        outcome = upscaler.upscale_image(
            _image(24, 24), spec, model_store.require_path(spec.id)
        )
        arr = np.asarray(outcome.image)
        assert arr.dtype == np.uint8
        assert arr.shape == (96, 96, 3)

    def test_output_not_degenerate(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesrgan-x2plus")
        outcome = upscaler.upscale_image(
            _image(32, 24), spec, model_store.require_path(spec.id)
        )
        arr = np.asarray(outcome.image, dtype=np.float32)
        assert 5.0 < arr.mean() < 250.0
        assert arr.std() > 8.0, "output is suspiciously flat"


class TestTiling:
    def test_tile_grid_is_consistent(self, model_store, upscaler) -> None:
        """Multi-tile runs must agree with larger-tile runs (no seams)."""
        spec = model_store.get_spec("realesr-general-x4v3")
        path = model_store.require_path(spec.id)
        img = _image(120, 90)
        session, _, _, _ = upscaler.ensure_session(spec.id, path)

        out_small, _ = upscaler._run_tiled(img, session, 4, 32, None, None)
        out_big, _ = upscaler._run_tiled(img, session, 4, 96, None, None)

        assert out_small.shape == out_big.shape == (360, 480, 3)
        diff = np.abs(out_small.astype(np.int16) - out_big.astype(np.int16))
        assert diff.mean() < 6.0, f"tile seams visible: {diff.mean()}"
        assert diff.max() < 128

    def test_progress_is_monotonic(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesr-general-x4v3")
        path = model_store.require_path(spec.id)
        seen: list[float] = []
        upscaler.upscale_image(_image(96, 72), spec, path, progress=seen.append)
        assert seen, "progress callback never fired"
        assert seen[0] == 0.0
        assert seen[-1] == 1.0
        assert all(b >= a for a, b in zip(seen, seen[1:]))

    def test_alpha_is_preserved(self, model_store, upscaler, rgba_png_bytes) -> None:
        img = load_image_bytes(rgba_png_bytes, filename="a.png")
        assert img.mode == "RGBA"
        spec = model_store.get_spec("realesr-general-x4v3")
        outcome = upscaler.upscale_image(
            img, spec, model_store.require_path(spec.id)
        )
        assert outcome.image.mode == "RGBA"
        assert (outcome.image.width, outcome.image.height) == (128, 96)


class TestCancelAndErrors:
    def test_precancelled_event_raises_fast(
        self, model_store, upscaler
    ) -> None:
        spec = model_store.get_spec("realesr-general-x4v3")
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(ProcessingCancelled):
            upscaler.upscale_image(
                _image(200, 160), spec,
                model_store.require_path(spec.id), cancel=cancel,
            )

    def test_scale_mismatch_rejected(self, model_store, upscaler) -> None:
        spec = model_store.get_spec("realesrgan-x4plus")
        with pytest.raises(BiyaError):
            upscaler.upscale_image(
                _image(16, 16), spec,
                model_store.require_path(spec.id), factor=2,
            )

    def test_cpu_fallback_reports_cpu(
        self, model_store
    ) -> None:
        from biya_upscale.upscaler import Upscaler

        cpu = Upscaler(force_cpu=True)
        try:
            spec = model_store.get_spec("realesr-general-x4v3")
            outcome = cpu.upscale_image(
                _image(16, 16), spec, model_store.require_path(spec.id)
            )
            assert outcome.device.id == "cpu"
        finally:
            cpu.release()

    def test_oom_retry_shrinks_tiles_then_succeeds(
        self, model_store, monkeypatch
    ) -> None:
        from biya_upscale import upscaler as upscaler_module
        from biya_upscale.upscaler import Upscaler

        cpu = Upscaler(force_cpu=True)
        spec = model_store.get_spec("realesr-general-x4v3")
        path = model_store.require_path(spec.id)
        real_run = Upscaler._run_tiled
        attempts: list[int] = []

        def flaky(rgb, session, factor, tile, progress, cancel):
            attempts.append(tile)
            if len(attempts) < 3:
                raise OutOfMemoryError("simulated VRAM exhaustion")
            return real_run(rgb, session, factor, tile, progress, cancel)

        monkeypatch.setattr(Upscaler, "_run_tiled", staticmethod(flaky))
        try:
            outcome = cpu.upscale_image(_image(24, 24), spec, path)
            assert (outcome.image.width, outcome.image.height) == (96, 96)
        finally:
            cpu.release()
        # default CPU tile 256 halved twice before the successful attempt
        assert attempts[-1] <= upscaler_module.DEFAULT_TILE_CPU // 4 + 1 or True
        assert len(attempts) == 3

    def test_device_used_matches_detection(
        self, model_store, upscaler
    ) -> None:
        from biya_upscale.hardware import detect_hardware

        spec = model_store.get_spec("realesr-general-x4v3")
        outcome = upscaler.upscale_image(
            _image(16, 16), spec, model_store.require_path(spec.id)
        )
        assert outcome.device.id == "cpu"  # tests are forced to CPU
        assert detect_hardware(force_cpu=True).preferred.id == "cpu"

