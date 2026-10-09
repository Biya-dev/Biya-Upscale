"""GPU acceleration tests.

These tests are opportunistic by design:

* On a machine with a GPU execution provider installed (CUDA / DirectML /
  CoreML via ``onnxruntime-gpu`` or ``onnxruntime-directml``) they verify that
  the app actually uses the GPU and that GPU output matches CPU output.
* On CPU-only machines they skip — the CPU fallback is covered everywhere else.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from biya_upscale.hardware import detect_hardware
from biya_upscale.upscaler import Upscaler


def _gpu_device():
    info = detect_hardware()
    gpus = [d for d in info.devices if d.kind == "gpu"]
    if not gpus:
        pytest.skip(
            "no GPU execution provider installed "
            "(install onnxruntime-gpu or onnxruntime-directml); CPU fallback in use"
        )
    return gpus[0]


def _image() -> Image.Image:
    arr = np.zeros((24, 24, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:24, 0:24]
    arr[..., 0] = (xx * 9) % 256
    arr[..., 1] = (yy * 9) % 256
    arr[..., 2] = ((xx + yy) * 6) % 256
    return Image.fromarray(arr, "RGB")


class TestGpuAcceleration:
    def test_detection_exposes_gpu(self) -> None:
        device = _gpu_device()
        assert device.label
        assert device.provider != "CPUExecutionProvider"

    def test_gpu_session_executes(self, model_store) -> None:
        expected = _gpu_device()
        upscaler = Upscaler()
        try:
            spec = model_store.get_spec("realesr-general-x4v3")
            outcome = upscaler.upscale_image(
                _image(), spec, model_store.require_path(spec.id)
            )
            assert outcome.device.id == expected.id, (
                f"expected {expected.id}, ran on {outcome.device.id} "
                f"({outcome.providers})"
            )
            assert (outcome.image.width, outcome.image.height) == (96, 96)
        finally:
            upscaler.release()

    def test_gpu_output_matches_cpu(self, model_store) -> None:
        _gpu_device()  # skip on CPU-only machines
        image = _image()
        spec = model_store.get_spec("realesr-general-x4v3")
        path = model_store.require_path(spec.id)

        gpu = Upscaler()
        try:
            gpu_out = np.asarray(
                gpu.upscale_image(image, spec, path).image, dtype=np.int16
            )
        finally:
            gpu.release()

        cpu = Upscaler(force_cpu=True)
        try:
            cpu_out = np.asarray(
                cpu.upscale_image(image, spec, path).image, dtype=np.int16
            )
        finally:
            cpu.release()

        mean_diff = float(np.abs(gpu_out - cpu_out).mean())
        assert mean_diff < 2.0, f"CPU/GPU outputs diverge: {mean_diff}"
