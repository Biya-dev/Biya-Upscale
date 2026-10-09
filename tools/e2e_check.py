"""End-to-end API check against a running server (default http://127.0.0.1:8765).

Usage:  python tools/e2e_check.py [base_url]
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")


def tiny_png(size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0)

    # 1) health + status
    r = client.get("/api/health")
    check("health endpoint", r.status_code == 200 and r.json()["status"] == "ok")
    r = client.get("/api/status")
    status = r.json()
    check("status endpoint", r.status_code == 200 and "models" in status)
    print(f"       device: {status.get('device', {}).get('label', '?')}")

    # 2) upload a real JPEG
    sample = (ROOT / "samples" / "small_320x240.jpg").read_bytes()
    r = client.post("/api/images?filename=small_320x240.jpg", content=sample)
    ok = r.status_code == 200 and r.json().get("width") == 320
    check("upload JPEG (320x240)", ok, str(r.text)[:120] if not ok else "")
    image_id = r.json()["id"] if ok else None

    # 3) reject unsupported / corrupt / empty files
    r = client.post("/api/images?filename=notes.txt", content=b"hello world")
    check("reject .txt (415)", r.status_code == 415, f"got {r.status_code}")
    bad = (ROOT / "samples" / "not_an_image.png").read_bytes()
    r = client.post("/api/images?filename=not_an_image.png", content=bad)
    check("reject corrupt png (422)", r.status_code == 422, f"got {r.status_code}")
    r = client.post("/api/images?filename=missing.png", content=b"")
    check("reject empty upload", r.status_code >= 400, f"got {r.status_code}")

    # 4) invalid inputs
    r = client.post("/api/upscale", json={"image_id": "nope", "scale": 2})
    check("unknown image -> 404", r.status_code == 404, f"got {r.status_code}")
    if image_id:
        r = client.post("/api/upscale", json={"image_id": image_id, "scale": 3})
        check("invalid scale -> 4xx", r.status_code >= 400, f"got {r.status_code}")

    # 5) real 2x upscale job
    r = client.post("/api/upscale", json={"image_id": image_id, "scale": 2})
    check("start 2x job", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    job_id = r.json()["job_id"]
    started = time.time()
    job = None
    while time.time() - started < 90:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.3)
    ok = bool(job and job["status"] == "done")
    check(
        "2x job completes",
        ok,
        f"status={job['status'] if job else '?'} error={job.get('error') if job else ''}",
    )
    if ok:
        res = job["result"]
        check(
            "2x output dimensions 640x480",
            res["width"] == 640 and res["height"] == 480,
            f"{res['width']}x{res['height']}",
        )
        print(
            f"       time={res['duration_s']}s device={res['device']} "
            f"model={res['model']}"
        )

        # 6) preview + downloads in every format
        r = client.get(f"/api/jobs/{job_id}/preview")
        check(
            "preview image",
            r.status_code == 200 and r.headers["content-type"].startswith("image/"),
        )
        r = client.get(f"/api/jobs/{job_id}/download?format=png")
        is_png = r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
        check("download PNG magic bytes", is_png, f"got {r.status_code}")
        cd = r.headers.get("content-disposition", "")
        check("download filename *_2x.png", "_2x.png" in cd, cd)
        r = client.get(f"/api/jobs/{job_id}/download?format=jpg&quality=90")
        is_jpg = r.status_code == 200 and r.content[:2] == b"\xff\xd8"
        check("download JPG conversion", is_jpg, f"got {r.status_code}")
        r = client.get(f"/api/jobs/{job_id}/download?format=webp")
        is_webp = (
            r.status_code == 200
            and r.content[:4] == b"RIFF"
            and r.content[8:12] == b"WEBP"
        )
        check("download WEBP conversion", is_webp, f"got {r.status_code}")

    # 7) batch of small images (fast model) — everything must complete
    job_ids: list[str] = []
    for i in range(3):
        r = client.post(
            f"/api/images?filename=tiny{i}.png", content=tiny_png(64 + i * 8)
        )
        check(f"batch upload {i + 1}", r.status_code == 200, r.text[:120])
        if r.status_code != 200:
            continue
        rid = r.json()["id"]
        r = client.post(
            "/api/upscale",
            json={"image_id": rid, "scale": 4, "model_id": "realesr-general-x4v3"},
        )
        check(f"batch job {i + 1} queued", r.status_code == 200, r.text[:120])
        if r.status_code == 200:
            job_ids.append(r.json()["job_id"])

    started = time.time()
    final: list[dict] = []
    while time.time() - started < 90:
        final = [client.get(f"/api/jobs/{jid}").json() for jid in job_ids]
        if all(j["status"] in ("done", "failed", "cancelled") for j in final):
            break
        time.sleep(0.3)
    dones = [j for j in final if j["status"] == "done"]
    check(
        "batch: all 3 processed",
        len(dones) == 3,
        str([(j["status"], j.get("error")) for j in final]),
    )
    for j in dones:
        check(
            f"batch: {j['filename']} 4x dims",
            j["result"]["width"] == j["src_width"] * 4
            and j["result"]["height"] == j["src_height"] * 4,
            f"{j['result']['width']}x{j['result']['height']}",
        )

    # 8) cancellation
    r = client.post("/api/images?filename=cancelme.png", content=tiny_png(48))
    rid = r.json()["id"]
    r = client.post("/api/upscale", json={"image_id": rid, "scale": 4})
    cancel_id = r.json()["job_id"]
    r = client.post(f"/api/jobs/{cancel_id}/cancel")
    check("cancel endpoint responds", r.status_code == 200, r.text[:120])
    # Cancellation takes effect at the next tile boundary (small images finish
    # their single tile first), so allow a few seconds.
    job = {"status": "running"}
    deadline = time.time() + 20
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{cancel_id}").json()
        if job["status"] in ("cancelled", "done", "failed"):
            break
        time.sleep(0.3)
    check(
        "cancelled job reaches terminal state",
        job["status"] in ("cancelled", "done", "failed"),
        job["status"],
    )

    # 9) settings round-trip
    r = client.post("/api/settings", json={"theme": "dark", "scale": 4})
    check(
        "settings persist",
        r.status_code == 200 and r.json()["settings"]["scale"] == 4,
    )

    # 10) security: foreign origins cannot mutate state
    r = client.post(
        "/api/settings",
        json={"theme": "light"},
        headers={"origin": "http://evil.example.com"},
    )
    check("foreign origin blocked (403)", r.status_code == 403, f"got {r.status_code}")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

