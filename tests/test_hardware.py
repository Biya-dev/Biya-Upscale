"""Hardware / execution-provider detection tests."""

from __future__ import annotations

from biya_upscale.hardware import (
    CPU_DEVICE,
    PROVIDER_BY_DEVICE,
    _nvidia_smi,
    compiled_providers,
    detect_hardware,
    preload_acceleration_libs,
)


class TestDetection:
    def test_always_reports_at_least_cpu(self) -> None:
        info = detect_hardware()
        assert info.devices, "must never return an empty device list"
        assert info.devices[-1].id == "cpu"
        assert info.preferred in info.devices
        assert info.preferred.label

    def test_cpu_fallback_forced(self) -> None:
        info = detect_hardware(force_cpu=True)
        assert [d.id for d in info.devices] == ["cpu"]
        assert info.preferred.id == "cpu"
        assert info.preferred.kind == "cpu"
        assert info.preferred.provider == "CPUExecutionProvider"

    def test_compiled_providers_include_cpu(self) -> None:
        providers = compiled_providers()
        assert "CPUExecutionProvider" in providers

    def test_device_serialisation(self) -> None:
        payload = detect_hardware().to_dict()
        assert {"devices", "preferred", "compiled_providers"} <= set(payload)
        for device in payload["devices"]:
            assert {"id", "label", "kind", "provider"} <= set(device)

    def test_gpu_devices_have_gpu_provider(self) -> None:
        for device in detect_hardware().devices:
            if device.kind == "gpu":
                assert device.provider != "CPUExecutionProvider"
                assert "CUDA" in device.provider or "Dml" in device.provider or "CoreML" in device.provider

    def test_nvidia_smi_never_raises(self) -> None:
        name, vram = _nvidia_smi()
        if name is None:
            assert vram is None
        else:
            assert isinstance(name, str) and name

    def test_preload_is_safe_noop_on_cpu(self) -> None:
        # must not raise regardless of platform / installed libs
        preload_acceleration_libs("cpu")
        preload_acceleration_libs("directml")

    def test_cpu_device_constant(self) -> None:
        assert CPU_DEVICE.id == "cpu"
        assert PROVIDER_BY_DEVICE["cpu"] == "CPUExecutionProvider"


def test_gpu_detection_when_available() -> None:
    """If a GPU provider is compiled in, detection must expose it."""
    info = detect_hardware()
    gpu_devices = [d for d in info.devices if d.kind == "gpu"]
    providers = compiled_providers()
    if "CUDAExecutionProvider" in providers or "DmlExecutionProvider" in providers:
        assert gpu_devices, "GPU provider compiled in but no GPU device reported"
        for device in gpu_devices:
            assert device.label
            assert any(
                marker in device.label
                for marker in ("GPU", "CUDA", "DirectML", "Apple", "CoreML")
            )
    else:
        # CPU-only build: detection correctly reports CPU only.
        assert not gpu_devices
