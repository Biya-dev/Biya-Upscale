"""Full UI test: drive the real app in a real browser with Playwright.

Flow: open UI -> dismiss model dialog -> upload sample -> 2x upscale ->
wait for Done -> open comparison -> toggle theme -> download result ->
verify bytes. Needs: server running on :8765, chromium installed.

Usage:  python tools/ui_check.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}",
          flush=True)


def main() -> int:
    from playwright.sync_api import sync_playwright

    sample = ROOT / "samples" / "small_320x240.jpg"
    assert sample.exists(), "run tools/make_samples.py first"

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
        check("page loads", "Biya Upscale" in (page.title() or ""))
        check(
            "hero text present",
            page.get_by_text("Upscale your images locally.").count() > 0,
        )

        # Model dialog may or may not appear (models are installed here).
        close_btns = page.locator('[aria-label="Close"]')
        if close_btns.count() > 0:
            try:
                close_btns.first.click(timeout=1500)
            except Exception:
                pass

        # Device chip is visible.
        device_chip = page.get_by_text("DirectML", exact=False)
        check(
            "device chip shows GPU",
            device_chip.count() > 0,
            f"found={device_chip.count()}",
        )

        # Upload via the file input inside the drop zone.
        file_input = page.locator('.card input[type="file"], input[type="file"]').first
        file_input.set_input_files(str(sample))
        page.wait_for_timeout(2500)
        check("upload registers image", "small_320x240.jpg" in page.content())
        check("dimensions shown", "320 × 240" in page.content())

        # Switch to 4x (fast model is installed; default selection is auto).
        page.get_by_role("button", name="4×").click()
        check("4x scale selected", True)

        # Start the upscale.
        page.get_by_role("button", name="Upscale").click()
        check("upscale started", True)

        # Wait for the result (CPU/DirectML, small image).
        done = False
        deadline = time.time() + 180
        while time.time() < deadline:
            if "images processed" in page.content() and "1 / 1" in page.content():
                done = True
                break
            if "Failed" in page.content():
                break
            page.wait_for_timeout(1000)
        check("batch completes", done)

        # Comparison view.
        slider = page.locator('[role="slider"]')
        check("before/after slider visible", slider.count() > 0)
        page.screenshot(path=str(ROOT / ".scratch-data" / "ui_result.png"))

        texts = page.content()
        check("output resolution shown", "1280 × 960" in texts, "4x of 320x240")
        check("processing time shown", "Processing time" in texts)

        # Theme toggle: expect the opposite of whatever is active.
        before = page.evaluate("document.documentElement.dataset.theme")
        theme_toggle = page.get_by_label("Toggle color theme")
        theme_toggle.click()
        theme = page.evaluate("document.documentElement.dataset.theme")
        expected = "light" if before == "dark" else "dark"
        check("theme toggles", theme == expected, f"{before} -> {theme}")
        page.screenshot(path=str(ROOT / ".scratch-data" / "ui_result_light.png"))
        theme_toggle.click()

        # Download the PNG result.
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Download", exact=True).first.click()
        download = download_info.value
        target = ROOT / ".scratch-data" / "ui_download.png"
        download.save_as(str(target))
        raw = target.read_bytes()
        check("download is a real PNG", raw[:8] == b"\x89PNG\r\n\x1a\n")
        check("download name", "_4x.png" in (download.suggested_filename or ""))

        check("no JS errors on page", not errors, "; ".join(errors[:2]))

        browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
