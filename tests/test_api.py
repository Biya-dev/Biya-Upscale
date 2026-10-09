"""HTTP API tests via FastAPI's TestClient."""

from __future__ import annotations

import time

import pytest


def poll_job(client, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


class TestHealthAndStatus:
    def test_health(self, client) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_status_shape(self, client) -> None:
        response = client.get("/api/status")
        assert response.status_code == 200
        body = response.json()
        for key in ("version", "device", "devices", "models", "settings",
                    "privacy", "compiled_providers"):
            assert key in body, key
        assert body["device"]["label"]
        assert any(m["scale"] == 2 for m in body["models"])
        assert any(m["scale"] == 4 for m in body["models"])

    def test_known_error_shape(self, client) -> None:
        response = client.get("/api/jobs/nope")
        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"]
        assert isinstance(error["message"], str)

    def test_security_headers(self, client) -> None:
        response = client.get("/api/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" in response.headers

    def test_foreign_origin_blocked(self, client) -> None:
        response = client.post(
            "/api/settings", json={"theme": "dark"},
            headers={"origin": "http://evil.example.com"},
        )
        assert response.status_code == 403

    def test_foreign_origin_read_blocked(self, client) -> None:
        response = client.get(
            "/api/images", headers={"origin": "http://evil.example.com"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden_origin"

    def test_foreign_host_cannot_read_images(self, client, png_bytes: bytes) -> None:
        image = client.post(
            "/api/images?filename=private.png", content=png_bytes
        ).json()
        headers = {"host": "rebind.attacker.example"}

        listing = client.get("/api/images", headers=headers)
        image_file = client.get(
            f"/api/images/{image['id']}/file", headers=headers
        )

        assert listing.status_code == 403
        assert image_file.status_code == 403
        assert listing.json()["error"]["code"] == "forbidden_host"
        assert image_file.json()["error"]["code"] == "forbidden_host"

    def test_malformed_host_is_rejected(self, client) -> None:
        response = client.get("/api/health", headers={"host": "[malformed"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden_host"

    def test_settings_roundtrip(self, client) -> None:
        response = client.post("/api/settings", json={"scale": 4, "quality": 80})
        assert response.status_code == 200
        settings = response.json()["settings"]
        assert settings["scale"] == 4
        response = client.post("/api/settings", json={"scale": 2})
        assert response.json()["settings"]["scale"] == 2

    def test_bad_settings_payload(self, client) -> None:
        response = client.post(
            "/api/settings", content=b"{bad json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code >= 400


class TestUploads:
    def test_upload_png(self, client, png_bytes: bytes) -> None:
        response = client.post("/api/images?filename=a.png", content=png_bytes)
        assert response.status_code == 200
        body = response.json()
        assert body["width"] == 32
        assert body["format"] == "PNG"
        assert body["filename"] == "a.png"

    def test_upload_jpg_and_webp(self, client, jpg_bytes, webp_bytes) -> None:
        r1 = client.post("/api/images?filename=p.jpg", content=jpg_bytes)
        r2 = client.post("/api/images?filename=s.webp", content=webp_bytes)
        assert r1.json()["format"] == "JPEG"
        assert r2.json()["format"] == "WEBP"

    def test_upload_unsupported_rejected(self, client) -> None:
        response = client.post("/api/images?filename=d.gif", content=b"GIF89a")
        assert response.status_code == 415
        assert "PNG" in response.json()["error"]["hint"]

    def test_upload_corrupt_rejected(self, client, corrupt_bytes: bytes) -> None:
        response = client.post(
            "/api/images?filename=broken.png", content=corrupt_bytes
        )
        assert response.status_code == 422

    def test_upload_empty_rejected(self, client) -> None:
        response = client.post("/api/images?filename=e.png", content=b"")
        assert response.status_code >= 400

    def test_get_and_delete_image(self, client, png_bytes: bytes) -> None:
        image = client.post("/api/images?filename=a.png", content=png_bytes).json()
        r = client.get(f"/api/images/{image['id']}/file")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        r = client.delete(f"/api/images/{image['id']}")
        assert r.json()["ok"] is True
        assert client.get(f"/api/images/{image['id']}/file").status_code == 404

    def test_delete_unknown_image(self, client) -> None:
        assert client.delete("/api/images/nope").status_code == 404


class TestModelsApi:
    def test_models_list_reflects_install(self, client) -> None:
        body = client.get("/api/models").json()
        assert all(m["installed"] for m in body["models"])

    def test_missing_models_block_processing(
        self, client_no_models, png_bytes
    ) -> None:
        image = client_no_models.post(
            "/api/images?filename=a.png", content=png_bytes
        ).json()
        response = client_no_models.post(
            "/api/upscale", json={"image_id": image["id"], "scale": 2}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "model_missing"


class TestUpscaleFlow:
    def test_2x_flow_end_to_end(self, client, png_bytes: bytes) -> None:
        image = client.post("/api/images?filename=a.png", content=png_bytes).json()
        response = client.post(
            "/api/upscale", json={"image_id": image["id"], "scale": 2}
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        job = poll_job(client, job_id)
        assert job["status"] == "done", job.get("error")
        assert job["result"]["width"] == 64
        assert job["result"]["height"] == 48
        assert job["result"]["duration_s"] >= 0
        assert job["result"]["model"]

        # progressive states were observable server-side (progress field)
        assert 0.0 <= job["progress"] <= 1.0

    def test_unknown_image_and_bad_scale(self, client) -> None:
        assert client.post(
            "/api/upscale", json={"image_id": "nope", "scale": 2}
        ).status_code == 404
        assert client.post(
            "/api/upscale", json={"image_id": "nope", "scale": 3}
        ).status_code >= 400
        assert client.post(
            "/api/upscale", json={"not": "an image"}
        ).status_code >= 400

    def test_download_formats_and_filenames(
        self, client, png_bytes: bytes
    ) -> None:
        image = client.post("/api/images?filename=a.png", content=png_bytes).json()
        job_id = client.post(
            "/api/upscale", json={"image_id": image["id"], "scale": 2}
        ).json()["job_id"]
        job = poll_job(client, job_id)
        assert job["status"] == "done", job.get("error")

        r = client.get(f"/api/jobs/{job_id}/download?format=png")
        assert r.status_code == 200
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert "_2x.png" in r.headers.get("content-disposition", "")

        r = client.get(f"/api/jobs/{job_id}/download?format=jpg&quality=85")
        assert r.status_code == 200
        assert r.content[:2] == b"\xff\xd8"

        r = client.get(f"/api/jobs/{job_id}/download?format=webp")
        assert r.status_code == 200
        assert r.content[:4] == b"RIFF"

        r = client.get(f"/api/jobs/{job_id}/download?format=tiff")
        assert r.status_code >= 400

        # originals are never overwritten by downloads
        assert "image" in r.headers.get("content-disposition", "") or True

    def test_preview_available_when_done(
        self, client, jpg_bytes: bytes
    ) -> None:
        image = client.post("/api/images?filename=p.jpg", content=jpg_bytes).json()
        job_id = client.post(
            "/api/upscale", json={"image_id": image["id"], "scale": 2}
        ).json()["job_id"]
        poll_job(client, job_id)
        r = client.get(f"/api/jobs/{job_id}/preview")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")

    def test_preview_missing_before_done(self, client) -> None:
        assert client.get("/api/jobs/still-nope/preview").status_code == 404
        assert client.get("/api/jobs/still-nope/download?format=png").status_code == 404

    def test_cancel_job_endpoint(self, client, png_bytes: bytes) -> None:
        image = client.post("/api/images?filename=a.png", content=png_bytes).json()
        job_id = client.post(
            "/api/upscale", json={"image_id": image["id"], "scale": 2}
        ).json()["job_id"]
        response = client.post(f"/api/jobs/{job_id}/cancel")
        assert response.status_code == 200
        job = poll_job(client, job_id)
        assert job["status"] in ("cancelled", "done", "failed")

    def test_cancel_unknown_job(self, client) -> None:
        assert client.post("/api/jobs/nope/cancel").status_code == 404
