# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Biya Upscale Windows application.

Builds a one-folder distribution under ``dist/BiyaUpscale``:

    pip install -r requirements.txt pyinstaller
    cd frontend && npm install && npm run build && cd ..
    pyinstaller packaging/BiyaUpscale.spec

The frozen app expects ``frontend/dist`` to exist (frontend is bundled as
data files) and the AI models to be downloaded on first launch (kept outside
the installer on purpose — they are ~140 MB and update independently).
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"
WEB = ROOT / "frontend" / "dist"
THIRD_PARTY = ROOT / "docs" / "THIRD_PARTY.md"
REAL_ESRGAN_LICENSE = ROOT / "docs" / "BSD-3-Clause-Real-ESRGAN.txt"

block_cipher = None

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[
        (str(WEB), "web"),
        (str(ROOT / "LICENSE"), "licenses"),
        (str(THIRD_PARTY), "licenses"),
        (str(REAL_ESRGAN_LICENSE), "licenses"),
    ],
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "starlette",
        "httpx",
        "PIL",
        "numpy",
        "onnxruntime",
        "biya_upscale",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchvision", "torchaudio", "tensorflow", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BiyaUpscale",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BiyaUpscale",
)
