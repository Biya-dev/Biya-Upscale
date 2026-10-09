# Release checklist — Biya Upscale v1.0

First-install checklist (tried per new machine) and final-release checklist
(tried per clean test machine). Both assume the model has already been
downloaded once.

---

## A. First-install checklist

Run on a fresh machine. Record the outcome of each item, OK / N/A / FAIL.

### A1. Install & bootstrap

- [ ] Python 3.11+ installed (64-bit). Check: `python --version`
- [ ] Node.js 18+ installed (only needed to rebuild the UI). Check: `node --version`
- [ ] `.venv` created and activated: `python -m venv .venv`
- [ ] Runtime deps installed: `pip install -r requirements.txt`
- [ ] Dev/test deps installed on dev machines: `pip install -r requirements-dev.txt`
- [ ] Frontend built: `cd frontend && npm install && npm run build`

### A2. Launch

- [ ] `python run.py` starts; browser opens at `http://127.0.0.1:8765/`
- [ ] App reports **Biya Upscale 1.0.0**
- [ ] App reports `processing device: NVIDIA GeForce RTX 2050 (DirectML)` (or the
      detected device); falls back to CPU if no GPU or forced with `--force-cpu`
- [ ] “Install the upscaling model” dialog appears on first launch
- [ ] Model card shows name, size, license, scale, description
- [ ] Nothing downloads until **Download** is clicked
- [ ] Download shows a live percentage bar; UI stays responsive
### A3. Functional smoke

- [ ] Drag & drop a PNG → preview + dimensions + size shown
- [ ] File picker adds a JPG and a WEBP; batch list grows
- [ ] `.gif` / `.txt` is refused with a clear message (nothing crashes)
- [ ] Corrupted PNG is refused as *damaged*; other items unaffected
- [ ] 2× on a small JPG → correct output dimensions + processing time
- [ ] 4× on a small PNG → correct output dimensions
- [ ] Before/after slider drags; Before and After line up edge-to-edge
- [ ] Upload, upscale, comparison and download all work on the native window
      (if pywebview is installed) **and** the browser

### A4. Batch + cancel + downloads

- [ ] Queue 3 images; progress bar advances (`3 / 5 images processed` style)
- [ ] Add one corrupted file → fails with a reason; others still complete
- [ ] **Cancel** mid-batch stops new jobs; done results stay downloadable
- [ ] **Download all** saves every result; filenames contain `_2x`/`_4x`;
      originals untouched
- [ ] JPG and WEBP downloads open correctly
- [ ] WEBP-with-alpha input → PNG output keeps transparency
- [ ] `Download all` on a fresh machine downloads multiple files without
      permission prompts (or the prompt is handled gracefully)

### A5. Offline + privacy

- [ ] After models are installed, disconnect the network: app still upscales
- [ ] DevTools Network tab shows only localhost calls (no image uploads)
- [ ] No account, no API key, no telemetry prompts anywhere in the UI
- [ ] Cross-origin browser tabs cannot trigger an upscaling job (403)

### A6. Modeling

- [ ] Models live in `%LOCALAPPDATA%/BiyaUpscale/models` (or the chosen data dir)
- [ ] Model files are SHA-256 verified at download time
## B. Final-release checklist

Clean, freshly-installed machine. Run from the root of the repository.

### B1. Build & packaging

- [ ] `python -m venv .venv` · `pip install -r requirements.txt`
- [ ] `cd frontend && npm install && npm run build` (tsc clean, vite builds clean)
- [ ] `pip install -r requirements-dev.txt`
- [ ] `pyinstaller packaging/BiyaUpscale.spec --noconfirm`
- [ ] `dist/BiyaUpscale/BiyaUpscale.exe --no-browser --port 8765` starts
- [ ] Packaged app serves the UI: `http://127.0.0.1:8765/api/health` → 200
- [ ] Packaged app serves frontend: `http://127.0.0.1:8765/` → HTML with
      `<title>Biya Upscale</title>`
- [ ] Packaged app does a real 2× upscale (1280×960 expected on the sample)
- [ ] Packaged app's model manager shows the installed model card correctly
- [ ] Test outputs after packaging are identical to the dev-server outputs:
      `30/30 e2e checks`, `15/15 UI checks`

### B2. Tests

```powershell
python -m pytest                    # full suite, all pass
python tools/e2e_check.py http://127.0.0.1:8765   # 30/30
python tools/ui_check.py            # 15/15 (needs chromium)
```

- [ ] `python -m pytest -q` → **0 failures, 0 errors**
- [ ] `e2e_check.py` → **30/30** (including cancellation → terminal state)
- [ ] `ui_check.py` → **15/15** (including theme toggle, no JS errors)
- [ ] GPU/CPU parity check passes on a machine with an NVIDIA GPU
- [ ] Tile-seam / seam / OOM-retry / foreign-origin / corrupt-cascade checks
      all pass

- [ ] Missing model mid-session → next job reports “model not installed”
- [ ] Deleting a model file mid-session → next job reports “model not installed”
### B3. Final smoke on a clean machine

- [ ] Fresh `BIYA_DATA_DIR` → models are offered, download works, first upscale
      succeeds in < 60 s
- [ ] `--force-cpu` → clean CPU fallback, results identical in dimensions
- [ ] `--port 9000` → starts on the requested port (not the default)
- [ ] `--no-browser` → no browser opens (for CI / packaging scripts)
- [ ] `--version` prints `Biya Upscale 1.0.0`
- [ ] Ctrl+C shuts down cleanly; `app.log` is written and rotated
- [ ] Windows Defender / SmartScreen do not block the exe (if they do, add an
      exception or adjust the packaging step)

### B4. Documentation

- [ ] `README.md` reflects the current install/build/run commands
- [ ] `docs/MANUAL_TEST_CHECKLIST.md` has no unchecked items
- [ ] `docs/THIRD_PARTY.md` lists every third-party library with license + version
- [ ] `docs/BSD-3-Clause-Real-ESRGAN.txt` is the model license text
- [ ] `LICENSE` is the app's MIT license
- [ ] `requirements.txt` / `requirements-dev.txt` list current versions
- [ ] `packaging/BiyaUpscale.spec` matches the shipped artifact
- [ ] `CHANGELOG.md` (or similar) has at least the v1.0 summary

### B5. Sign-off

- [ ] No `TODO` / `FIXME` / `XXX` markers remain in shipped source
- [ ] No telemetry, analytics, or network calls exist in the shipped code path
- [ ] No user data leaves the machine (API rejects foreign origins with 403)
- [ ] The installer package (one folder) is < 40 MB on disk including models
- [ ] The app can be uninstalled by deleting `%LOCALAPPDATA%/BiyaUpscale`
- [ ] Backup/restore of the data folder restores settings, cache, and (re-)
      downloaded models

---

## C. Known knowns (accept for v1.0)

- GPU wheels need matching runtimes (CUDA 12/13 for `onnxruntime-gpu`);
  the app falls back to CPU cleanly when they are absent.
- Portrait EXIF orientation is applied on import; metadata is stripped from
  results by design.
- “Download all” triggers sequential browser downloads.
- Native window needs `pywebview` + WebView2; otherwise the browser UI is used.

      instead of crashing
- [ ] Settings round-trip: change theme/scale/format/quality, reload, values
      persist (unknown keys silently dropped)

- [ ] After download the card flips to **Installed**
- [ ] Main screen is visible after closing the dialog
