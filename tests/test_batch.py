"""Batch processing with the real pipeline: progress, isolation, formats."""

from __future__ import annotations

import pytest

from biya_upscale.imaging import load_image_bytes, save_image
from biya_upscale.jobs import JobManager


class TestRealBatches:
    def test_mixed_batch_completes_with_correct_dims(
        self, app_ctx, png_bytes, jpg_bytes, webp_bytes, wait_for_job
    ) -> None:
        uploads = [
            ("one.png", png_bytes, 32, 24),
            ("two.jpg", jpg_bytes, 40, 30),
            ("three.webp", webp_bytes, 36, 28),
        ]
        jobs = []
        for name, payload, width, height in uploads:
            img = load_image_bytes(payload, filename=name)
            path = app_ctx.config.inputs_dir / f"batch-{name}"
            save_image(img, path, fmt="PNG")
            jobs.append(
                app_ctx.jobs.submit(
                    image_id=name,
                    input_path=path,
                    filename=name,
                    src_width=img.width,
                    src_height=img.height,
                    scale=2,
                    model_id="realesrgan-x2plus",
                )
            )

        finals = [wait_for_job(app_ctx.jobs, j.id, timeout=60) for j in jobs]
        assert all(j.status == "done" for j in finals), [
            (j.status, j.error) for j in finals
        ]
        for (name, _payload, width, height), final in zip(uploads, finals):
            assert final.result["width"] == width * 2, name
            assert final.result["height"] == height * 2, name

    def test_deleted_input_fails_alone(self, app_ctx, png_bytes, wait_for_job) -> None:
        img = load_image_bytes(png_bytes, filename="ok.png")
        ok_path = app_ctx.config.inputs_dir / "ok.png"
        save_image(img, ok_path, fmt="PNG")
        ok_job = app_ctx.jobs.submit(
            image_id="ok", input_path=ok_path, filename="ok.png",
            src_width=32, src_height=24, scale=2, model_id="realesrgan-x2plus",
        )
        bad_job = app_ctx.jobs.submit(
            image_id="gone", input_path=app_ctx.config.inputs_dir / "gone.png",
            filename="gone.png", src_width=32, src_height=24, scale=2,
            model_id="realesrgan-x2plus",
        )

        assert wait_for_job(app_ctx.jobs, ok_job.id).status == "done"
        failed = wait_for_job(app_ctx.jobs, bad_job.id)
        assert failed.status == "failed"
        assert failed.error["code"] in ("corrupt_image", "not_found", "internal")

    def test_batch_progress_reaches_all_terminal(
        self, app_ctx, png_bytes, wait_for_job
    ) -> None:
        img = load_image_bytes(png_bytes, filename="a.png")
        jobs = []
        for i in range(3):
            path = app_ctx.config.inputs_dir / f"p{i}.png"
            save_image(img, path, fmt="PNG")
            jobs.append(
                app_ctx.jobs.submit(
                    image_id=f"p{i}", input_path=path, filename=f"p{i}.png",
                    src_width=32, src_height=24, scale=2,
                    model_id="realesrgan-x2plus",
                )
            )
        finals = [wait_for_job(app_ctx.jobs, j.id, timeout=60) for j in jobs]
        progress = app_ctx.jobs.active_count()
        assert progress == 0
        expected = sum(1 for j in finals if j.terminal)
        assert expected == 3

    def test_4x_fast_batch(
        self, app_ctx, png_bytes, wait_for_job
    ) -> None:
        img = load_image_bytes(png_bytes, filename="a.png")
        path = app_ctx.config.inputs_dir / "fast.png"
        save_image(img, path, fmt="PNG")
        job = app_ctx.jobs.submit(
            image_id="fast", input_path=path, filename="fast.png",
            src_width=32, src_height=24, scale=4,
            model_id="realesr-general-x4v3",
        )
        final = wait_for_job(app_ctx.jobs, job.id, timeout=60)
        assert final.status == "done", final.error
        assert (final.result["width"], final.result["height"]) == (128, 96)

    def test_results_saved_to_disk(
        self, app_ctx, png_bytes, wait_for_job
    ) -> None:
        from pathlib import Path

        img = load_image_bytes(png_bytes, filename="a.png")
        path = app_ctx.config.inputs_dir / "saved.png"
        save_image(img, path, fmt="PNG")
        job = app_ctx.jobs.submit(
            image_id="saved", input_path=path, filename="saved.png",
            src_width=32, src_height=24, scale=2,
            model_id="realesrgan-x2plus",
        )
        final = wait_for_job(app_ctx.jobs, job.id, timeout=60)
        assert final.status == "done", final.error
        full = Path(final.result["path"])
        preview = Path(final.result["preview_path"])
        assert full.exists() and full.suffix == ".png"
        assert preview.exists() and preview.suffix == ".jpg"
