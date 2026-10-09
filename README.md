# Biya Upscale

**Upscale your images with AI — without uploading them anywhere.**

Biya Upscale is a free desktop/web application that runs image upscaling
**locally on your computer** using real open-source AI models (Real-ESRGAN).
There is no cloud inference, no account, no API key, and no per-user cost.

## 1. What Biya Upscale is

A local image upscaler for Windows (and any OS that runs Python):

- Drop in PNG, JPG/JPEG or WEBP images — one at a time or in batches.
- Upscale **2×** or **4×** with genuine AI super-resolution (ONNX Runtime).
- Selects from the execution providers available in the installed ONNX Runtime:
  CUDA, DirectML, CoreML, or CPU. The packaged Windows build has been verified
  on one NVIDIA RTX 2050 using DirectML; other GPUs, providers, and CPU-only
  machines have not been independently certified.
- Compare Before/After with a slider, then download PNG, JPG or WEBP.
- Works offline for inference after the selected model has been downloaded.

The core promise: **your images never leave your computer.** The first model
download requires an Internet connection. Results vary by image and may
contain invented or altered details; inspect important outputs before use.
The quality model can make small text and numbers less legible, so do not use
AI-upscaled output as a faithful copy of documents or text-heavy screenshots.

## 2. Features

| Area | Details |
|---|---|
| Input | Drag & drop, file picker, multi-select; PNG / JPG / JPEG / WEBP; filename, dimensions, size and live preview per file |
| AI upscaling | Native 2× and 4× models (Real-ESRGAN RRDBNet / SRVGGNetCompact); model registry is data-driven so new models drop in later |
| Acceleration | Detects providers available in the installed runtime and reports the active device; packaged Windows inference verified on NVIDIA RTX 2050 via DirectML only |
| Comparison | Before/after drag slider, original → new resolution, processing time, device and model used |
| Download | Single images or **Download all**; PNG (lossless), JPG, WEBP with quality control; originals are never overwritten (`photo_4x.png`) |
| Batch | `3 / 10 images processed` progress; per-file success/failure; one bad file never stops the batch; cancellable |
| Model manager | First launch offers the download — shows name, size (~64 MB quality / ~5 MB fast), BSD-3 license and purpose; SHA-256 verified; stored locally |
| Privacy | Localhost-only server, no uploads, no account, no API key, no telemetry; cross-origin mutations blocked |
| UI | Modern dark/light modes, responsive, works offline |

## 3. Privacy

This is a feature, not a footnote:

- Every pixel is processed in a server that only listens on **127.0.0.1** —
  nothing is reachable from your network, let alone the internet.
- Images are never uploaded or stored remotely. There is no account system,
  no API key, and no telemetry (not even opt-in code paths exist).
- AI models live in your local app-data folder after *you* approve the
  download. The UI states this up front.
- The local API rejects requests from foreign origins, and every source file
  you select is treated as untrusted input (decoded only, size-capped,
  never executed).

## 4. Supported hardware

| Tier | Requirement | Notes |
|---|---|---|
| Packaged build verified | Windows 11 + NVIDIA RTX 2050 | DirectML inference tested; this is one hardware configuration, not a compatibility guarantee |
| Other possible providers | CUDA, DirectML on other GPUs, CoreML, CPU | Provider availability depends on the installed runtime and hardware; these combinations have not been independently certified for this release |

Performance and memory use depend on image size, model, runtime, and hardware.
The app uses tiled inference and retries smaller tiles after recognized
out-of-memory errors, but this does not guarantee every image will fit on
every GPU. No general RAM or VRAM minimum has been established.

## 5. Installation

**Prerequisites:** Python 3.11+ and Node.js 18+ (Node is only needed to build
the UI once).

```powershell
# 1. Python dependencies (virtualenv recommended)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Build the interface
cd frontend
npm install
npm run build
cd ..
```

> GPU users: swap the CPU wheel for a GPU one —
> `pip install onnxruntime-gpu` (NVIDIA) or
> `pip install onnxruntime-directml` (any Windows GPU) — instead of
> `onnxruntime`. Nothing else changes.

## 6. Model installation

Models are **not** bundled with the installer. On first launch the app shows
an *Install the upscaling model* dialog:

- **Real-ESRGAN x4 Plus** (~64 MB) — quality default for 4×.
- **Real-ESRGAN x2 Plus** (~64 MB) — native 2×.
- **Real-ESRGAN General x4 v3 (fast)** (~5 MB) — for CPU-only machines.

Each card lists size, license (BSD-3-Clause) and purpose. Nothing downloads
until you click **Download**; files are checked against pinned SHA-256 hashes
and stored under
your app-data folder (`%LOCALAPPDATA%/BiyaUpscale/models` on Windows).
After that, everything works with no internet.

Command-line alternative: `python tools/download_models.py`

## 7. Running the application

```powershell
python run.py                 # native window if pywebview is installed, else browser
python run.py --browser       # force the browser UI
python run.py --no-browser    # server only (useful for testing)
python run.py --port 9000     # custom localhost port
python run.py --force-cpu     # ignore GPUs
python run.py --data-dir D:\BiyaData   # custom working directory
```

Then open `http://127.0.0.1:8765/` — drop images in, pick 2×/4×, hit
**Upscale**.

### Exact commands to run the project

```powershell
# fresh checkout → running app (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
python tools/download_models.py
python run.py
```

## 8. Building the Windows version

```powershell
# prerequisites (once)
pip install -r requirements.txt -r requirements-dev.txt
cd frontend; npm install; npm run build; cd ..

# exact build command
pyinstaller packaging/BiyaUpscale.spec
```

This produces `dist/BiyaUpscale/BiyaUpscale.exe` (one-folder bundle, includes
the UI; models download on first launch so the installer stays small).
Verify the packaged build:

```powershell
.\dist\BiyaUpscale\BiyaUpscale.exe --no-browser --port 8765
# in another shell:
python tools/e2e_check.py http://127.0.0.1:8765
```

Optional native window (no browser needed):

```powershell
pip install pywebview
python run.py   # opens a desktop window automatically
```


## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| “Model is not installed” | Open **Models** (header) and download it. |
| Download fails | Check the connection and retry; partial files are deleted automatically. Delete a stuck file from the models folder and retry. |
| “Not enough memory” | Close other apps, try 2×, a smaller image, or the ~5 MB fast model. |
| GPU not used | Install the right wheel (`onnxruntime-gpu` / `-directml`), restart, and check the device chip. CUDA also needs a CUDA 12/13 runtime. |
| Port busy | The app automatically picks the next free port and prints it. |
| Raw log | `%LOCALAPPDATA%/BiyaUpscale/logs/app.log` (Windows) or `~/.local/share/biya-upscale/logs/app.log` (Linux). The UI never shows stack traces, the log does. |
| Fresh start | Delete the data folder (`%LOCALAPPDATA%/BiyaUpscale`) — settings, cached results and (re-downloadable) models reset. |

## 10. License information

- **App code: MIT** — see `LICENSE`.
- **AI models: BSD-3-Clause** (Xintao Wang / Tencent ARC Lab). Full texts and
  model cards in `docs/THIRD_PARTY.md` and
  `docs/BSD-3-Clause-Real-ESRGAN.txt`; every model is attributed in the UI.
- All other libraries: MIT / BSD / Apache / HPND — listed in
  `docs/THIRD_PARTY.md`. No GPL code ships in the app itself (PyInstaller,
  a build-only tool, carries its own linking exception).

---

## Tests

```powershell
python -m pytest                    # full suite (needs models + network once)
python -m pytest tests/test_imaging.py tests/test_jobs.py -q   # fast subset
python tools/e2e_check.py           # live server: 30 real API checks
python tools/ui_check.py            # real browser: 15 UI checks (needs chromium)
```

Manual release checklist: `docs/MANUAL_TEST_CHECKLIST.md`.

## Project structure

```
Biya-Upscale/
├── run.py                      # launcher: python run.py
├── requirements*.txt           # Python deps (runtime / dev)
├── pytest.ini                  # test config
├── backend/biya_upscale/
│   ├── __main__.py             # startup, window/browser, shutdown
│   ├── server.py               # FastAPI: routes, security headers, static UI
│   ├── jobs.py                 # serial queue, pipeline, cancel, isolation
│   ├── upscaler.py             # tiled ONNX inference, OOM retry, providers
│   ├── model_store.py          # registry + verified downloads + state
│   ├── hardware.py             # CUDA/DirectML/CoreML/CPU detection
│   ├── imaging.py              # validation, alpha handling, save, previews
│   ├── config.py               # data dirs + settings
│   └── errors.py               # user-friendly typed errors
├── frontend/src/               # React + TS + Tailwind (Header, DropZone,
│                               # ImageQueue, CompareSlider, ResultPanel,
│                               # ModelDialog, api client, theme)
├── tests/                      # pytest: imaging, models, jobs, upscale,
│                               # batch, api, gpu, hardware, errors
├── tools/                      # download_models, make_samples, smoke_upscale,
│                               # gpu_check, e2e_check, ui_check
├── packaging/BiyaUpscale.spec  # PyInstaller Windows build
├── samples/                    # generated test images
└── docs/                       # checklist, licenses, third-party credits
```

## Dependencies

Python: `fastapi uvicorn pillow numpy httpx onnxruntime`
(swap `onnxruntime` → `onnxruntime-gpu` or `onnxruntime-directml` for GPU).
Dev: `pytest playwright pyinstaller pywebview`.
Frontend: `react react-dom vite @vitejs/plugin-react @tailwindcss/vite typescript tailwindcss`.

## Known limitations

- GPU wheels need matching runtimes (CUDA 12/13 for `onnxruntime-gpu`); if
  they are absent the app cleanly falls back to CPU.
- 4× outputs of images above ~40 MP are refused (150 MP output cap).
- “Download all” triggers sequential browser downloads (browsers may ask
  permission once for multiple files).
- The native window needs `pywebview` + WebView2; otherwise the browser UI
  is used (identical features).
- Portrait EXIF orientation is applied on import; other metadata is stripped
  from results (by design — no location data leaks).
- First inference after launch includes one-time model warm-up (~seconds).

## Recommended next features

1. Per-model picker per job + anime/illustration model preset.
2. Optional output width/height target (e.g. “make it 4K wide”).
3. Face-restore toggle (GFPGAN-style post-process, local, optional download).
4. Folder watch: auto-upscale new files dropped into a folder.
5. Portable ZIP distribution + auto-updater (free static hosting).
6. macOS/Linux packaging parity (same codebase already supports both).
