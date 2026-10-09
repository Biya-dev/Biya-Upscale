"""Hardware / acceleration detection.

The goal is an honest, human-readable device label:

    Processing device: NVIDIA GeForce RTX 2050 (CUDA)
    Processing device: GPU (DirectML)
    Processing device: CPU

Detection is dynamic: we ask ONNX Runtime which execution providers were
compiled in. CPU always remains the guaranteed fallback.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

PROVIDER_BY_DEVICE = {
    "cuda": "CUDAExecutionProvider",
    "directml": "DmlExecutionProvider",
    "coreml": "CoreMLExecutionProvider",
    "cpu": "CPUExecutionProvider",
}


@dataclass(frozen=True)
class DeviceInfo:
    id: str                      # cuda | directml | coreml | cpu
    label: str                   # shown in the UI
    kind: str                    # gpu | cpu
    provider: str                # onnxruntime provider name
    gpu_name: Optional[str] = None
    vram_mb: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CPU_DEVICE = DeviceInfo(
    id="cpu",
    label="CPU",
    kind="cpu",
    provider=PROVIDER_BY_DEVICE["cpu"],
)


@dataclass
class HardwareInfo:
    """Aggregated view returned by /api/status."""

    devices: list[DeviceInfo] = field(default_factory=list)
    preferred: DeviceInfo = field(default_factory=lambda: CPU_DEVICE)
    compiled_providers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "devices": [d.to_dict() for d in self.devices],
            "preferred": self.preferred.to_dict(),
            "compiled_providers": self.compiled_providers,
        }


def _nvidia_smi() -> tuple[Optional[str], Optional[int]]:
    """Query the NVIDIA driver for GPU name + VRAM. Returns (None, None) if absent."""
    try:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            **kwargs,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None, None
        first = out.stdout.strip().splitlines()[0]
        name, _, mem = first.partition(",")
        vram = None
        try:
            vram = int(float(mem.strip()))
        except ValueError:
            pass
        return name.strip() or None, vram
    except (OSError, subprocess.SubprocessError):
        return None, None


def _torch_lib_dirs() -> list[str]:
    """Locate the DLL directory of a pip-installed torch (no import needed)."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("torch")
        if spec and spec.origin:
            lib_dir = Path(spec.origin).parent / "lib"
            if lib_dir.is_dir():
                pattern = "*.dll" if sys.platform == "win32" else "*.so*"
                if glob.glob(str(lib_dir / pattern)):
                    return [str(lib_dir)]
    except Exception:
        pass
    return []


def _find_nvidia_dll_dirs() -> list[str]:
    """Locate CUDA runtime DLLs (cublas/cudnn/...) shipped by pip packages.

    Common situation: the user has PyTorch with bundled NVIDIA libraries but no
    system-wide CUDA toolkit. We search every plausible site-packages root so
    ``onnxruntime-gpu`` can find what it needs.
    """
    roots: set[Path] = set()
    for entry in sys.path:
        if entry:
            roots.add(Path(entry))
    # venvs hide the base interpreter's site-packages from sys.path; check it too.
    for candidate in (
        Path(sys.base_prefix) / "Lib" / "site-packages",
        Path(sys.base_prefix) / "lib" / "site-packages",
        Path(sys.prefix) / "Lib" / "site-packages",
    ):
        roots.add(candidate)

    found: list[str] = []
    patterns = ("nvidia/*/bin", "nvidia/*/*/bin", "nvidia/*/*/*/bin")
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            for path in glob.glob(str(root / pattern)):
                if sys.platform == "win32":
                    if glob.glob(os.path.join(path, "*.dll")):
                        found.append(path)
                elif glob.glob(os.path.join(path, "*.so*")):
                    found.append(path)
    return sorted(set(found))



_DLL_PRELOADED = False


def preload_acceleration_libs(device_id: str) -> None:
    """Best-effort: make CUDA libraries importable before session creation."""
    global _DLL_PRELOADED
    if _DLL_PRELOADED or device_id != "cuda" or sys.platform != "win32":
        return
    _DLL_PRELOADED = True
    dirs = _find_nvidia_dll_dirs() + _torch_lib_dirs()
    if not dirs:
        return
    try:
        import onnxruntime as ort

        preload = getattr(ort, "preload_dlls", None)
        if callable(preload):
            try:
                preload(search_path=dirs, library_path=None)
                return
            except TypeError:
                preload()  # older signature
            except Exception:
                pass
    except Exception:
        pass
    for path in dirs:
        try:
            os.add_dll_directory(path)
        except OSError:
            pass
    os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")


def compiled_providers() -> list[str]:
    try:
        import onnxruntime as ort

        # ORT >= 1.29 may ship CUDA as a plugin EP that must be registered.
        register = getattr(ort, "_register_bundled_cuda_plugin_ep", None)
        if callable(register):
            try:
                register(warn_on_failure=False)
            except Exception:
                pass
        return list(ort.get_available_providers())
    except Exception:
        return []


def detect_hardware(force_cpu: bool = False) -> HardwareInfo:
    """Return available devices, best first. Never raises."""
    providers = compiled_providers()
    devices: list[DeviceInfo] = []

    if not force_cpu:
        if "CUDAExecutionProvider" in providers:
            name, vram = _nvidia_smi()
            devices.append(
                DeviceInfo(
                    id="cuda",
                    label=f"{name} (CUDA)" if name else "NVIDIA GPU (CUDA)",
                    kind="gpu",
                    provider=PROVIDER_BY_DEVICE["cuda"],
                    gpu_name=name,
                    vram_mb=vram,
                )
            )
        if "DmlExecutionProvider" in providers:
            name, vram = _nvidia_smi()  # may be an NVIDIA card driven via DirectML
            label = f"{name} (DirectML)" if name else "GPU (DirectML)"
            devices.append(
                DeviceInfo(
                    id="directml",
                    label=label,
                    kind="gpu",
                    provider=PROVIDER_BY_DEVICE["directml"],
                    gpu_name=name,
                    vram_mb=vram,
                )
            )
        if "CoreMLExecutionProvider" in providers:
            devices.append(
                DeviceInfo(
                    id="coreml",
                    label="Apple GPU (CoreML)",
                    kind="gpu",
                    provider=PROVIDER_BY_DEVICE["coreml"],
                )
            )

    devices.append(CPU_DEVICE)
    return HardwareInfo(
        devices=devices,
        preferred=devices[0],
        compiled_providers=providers,
    )
