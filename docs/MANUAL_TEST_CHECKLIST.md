# Manual test checklist — Biya Upscale v1.0

Run these once per release on a clean install. Test on two machines if you can:
one with an NVIDIA GPU, one CPU-only.

## 1. First launch

- [ ] App starts and opens the window (or browser) at a localhost URL.
- [ ] “Install the upscaling model” dialog appears on first launch.
- [ ] Each model card shows: name, size, license, scale, and a description.
- [ ] No download starts until you click **Download**.
- [ ] Download shows a live percentage bar; the app stays responsive.
- [ ] After download the card flips to **Installed**; closing the dialog
      returns to the main screen.

## 2. Upload (PNG / JPG / WEBP)

- [ ] Drag & drop a PNG — preview, `1920 × 1080`-style dimensions, size shown.
- [ ] File picker adds a JPG and a WEBP; batch list grows (3 items).
- [ ] A `.gif` or `.txt` is refused with a clear message (nothing crashes).
- [ ] A deliberately corrupted PNG is refused as *damaged*, other items unaffected.

## 3. Upscaling

- [ ] 2× on a 1920×1080 JPG → `3840 × 2160`, processing time shown (e.g. 4.2s).
- [ ] 4× on a 320×240 PNG → `1280 × 960`.
- [ ] Before/after slider drags; Before and After line up edge-to-edge.
- [ ] “Processing device” shows the real GPU on GPU machines, **CPU** on
      CPU-only machines (Settings → force CPU also works).
- [ ] Result looks genuinely sharper than the original (edges, text, texture).

## 4. Batch

- [ ] Queue 5 mixed images; progress bar advances `3 / 5 images processed`.
- [ ] Add one corrupted file to the batch — it fails with a reason while the
      other 4 complete.
- [ ] **Cancel** mid-batch stops new jobs; already-done results stay downloadable.
- [ ] **Download all** saves every result; filenames contain `_2x`/`_4x` and
      the originals are untouched.

## 5. Downloads & formats

- [ ] Individual **Download** saves a valid PNG (`_2x.png` / `_4x.png`).
- [ ] JPG output at quality 85 and WEBP output both open correctly.
- [ ] WEBP-with-alpha input → PNG output keeps transparency.

## 6. Offline & privacy

- [ ] After models are installed, disconnect the network: app still upscales.
- [ ] No image data in browser devtools Network tab except localhost calls.
- [ ] No account, no API key, no telemetry prompts anywhere.

## 7. Dark / light mode

- [ ] Toggle in the header switches the whole UI; choice survives reload.
- [ ] Empty (hero) state, queue rows, slider, dialogs all readable in both modes.

## 8. Error paths

- [ ] Upscale without any downloaded model → friendly 409 + dialog opens.
- [ ] A >150 MP output request is refused with a useful hint (try 2×).
- [ ] Kill the model file mid-session → next job reports “model not installed”
      instead of crashing.

Check the log at `%LOCALAPPDATA%/BiyaUpscale/logs/app.log` (Windows) /
`~/.local/share/biya-upscale/logs/app.log` (Linux) after any failure.
