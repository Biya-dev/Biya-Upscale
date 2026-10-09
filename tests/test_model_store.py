"""Model registry, download, verification and lifecycle tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from biya_upscale.errors import ModelDownloadError, ModelNotFoundError
from biya_upscale.model_store import (
    DEFAULT_MODEL_BY_SCALE,
    REGISTRY,
    ModelSpec,
    ModelStore,
)


def spec_for(url: str, filename: str, sha256: str = "",
             size: int = 0, model_id: str = "test-model") -> ModelSpec:
    return ModelSpec(
        id=model_id,
        name="Test Model",
        scale=4,
        size_bytes=size,
        sha256=sha256,
        url=url,
        filename=filename,
        summary="for tests",
    )


class TestRegistry:
    def test_registry_integrity(self) -> None:
        ids = [s.id for s in REGISTRY]
        assert len(ids) == len(set(ids)), "duplicate model ids"
        scales = set()
        for spec in REGISTRY:
            assert spec.scale in (2, 4)
            assert spec.size_bytes > 0
            assert spec.url.startswith("https://")
            assert spec.license
            assert spec.summary
            assert spec.filename.endswith(".onnx")
            assert len(spec.sha256) == 64
            int(spec.sha256, 16)  # valid hex
            scales.add(spec.scale)
        assert scales == {2, 4}, "need both 2x and 4x models"
        assert set(DEFAULT_MODEL_BY_SCALE) == {2, 4}

    def test_default_models_are_registered(self) -> None:
        for scale, model_id in DEFAULT_MODEL_BY_SCALE.items():
            spec = next(s for s in REGISTRY if s.id == model_id)
            assert spec.scale == scale
            assert spec.default


class TestModelMissing:
    def test_require_path_raises_helpfully(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        with pytest.raises(ModelNotFoundError) as exc:
            store.require_path("realesrgan-x4plus")
        assert "not installed" in exc.value.message.lower()
        assert exc.value.hint

    def test_not_ready_until_file_exists(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        assert not store.is_ready("realesrgan-x4plus")
        assert store.status("realesrgan-x4plus")["state"] == "not_downloaded"

    def test_unknown_model_id(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        with pytest.raises(ModelNotFoundError):
            store.get_spec("does-not-exist")


class TestModelSelection:
    def test_auto_picks_default_for_scale(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        assert store.model_for_scale(2).scale == 2
        assert store.model_for_scale(4).scale == 4
        assert store.model_for_scale(4).default

    def test_explicit_preference(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        fast = store.model_for_scale(4, "realesr-general-x4v3")
        assert fast.id == "realesr-general-x4v3"

    def test_preference_scale_mismatch_rejected(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        with pytest.raises(ModelNotFoundError):
            store.model_for_scale(2, "realesr-general-x4v3")  # a 4x model

    def test_unknown_preference_falls_back_to_default(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir)
        assert store.model_for_scale(4, "nope").default

    def test_unsupported_scale(self, data_dir) -> None:
        store = ModelStore(data_dir.models_dir, specs=(REGISTRY[0],))
        with pytest.raises(ModelNotFoundError):
            store.model_for_scale(8)


class TestSyncAndDelete:
    def test_ready_state_from_disk(self, data_dir) -> None:
        spec = spec_for("http://unused", "m.onnx", size=5)
        path = data_dir.models_dir / "m.onnx"
        path.write_bytes(b"12345")
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        assert store.is_ready("test-model")

    def test_wrong_size_file_is_removed(self, data_dir) -> None:
        spec = spec_for("http://unused", "m.onnx", size=5)
        path = data_dir.models_dir / "m.onnx"
        path.write_bytes(b"12")  # incomplete leftover
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        assert not store.is_ready("test-model")
        assert not path.exists(), "corrupt leftover should be cleaned up"

    def test_same_size_wrong_hash_file_is_removed(self, data_dir) -> None:
        spec = spec_for(
            "http://unused",
            "m.onnx",
            sha256=hashlib.sha256(b"right").hexdigest(),
            size=5,
        )
        path = data_dir.models_dir / "m.onnx"
        path.write_bytes(b"wrong")

        store = ModelStore(data_dir.models_dir, specs=(spec,))

        assert not store.is_ready("test-model")
        assert not path.exists(), "same-size model with wrong hash must be removed"

    def test_delete_removes_file_and_fires_hook(self, data_dir) -> None:
        spec = spec_for("http://unused", "m.onnx", size=3)
        path = data_dir.models_dir / "m.onnx"
        path.write_bytes(b"abc")
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        fired: list[str] = []
        store.add_delete_hook(fired.append)
        assert store.is_ready("test-model")
        store.delete("test-model")
        assert not path.exists()
        assert fired == ["test-model"]
        assert store.status("test-model")["state"] == "not_downloaded"


class TestDownloads:
    def test_successful_download_verifies_sha(
        self, data_dir, local_http_server
    ) -> None:
        payload = b"model-bytes-" * 1000
        (local_http_server.directory / "model.onnx").write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        spec = spec_for(
            f"{local_http_server.url_root}/model.onnx", "model.onnx",
            sha256=sha, size=len(payload),
        )
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        seen: list[float] = []
        result = store.download_blocking("test-model", on_progress=seen.append)
        assert result.read_bytes() == payload
        assert store.is_ready("test-model")
        assert seen and max(seen) == 1.0

    def test_bad_checksum_rejected_and_deleted(
        self, data_dir, local_http_server
    ) -> None:
        payload = b"tampered"
        (local_http_server.directory / "model.onnx").write_bytes(payload)
        spec = spec_for(
            f"{local_http_server.url_root}/model.onnx", "model.onnx",
            sha256="0" * 64, size=len(payload),
        )
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        with pytest.raises(ModelDownloadError):
            store.download_blocking("test-model")
        status = store.status("test-model")
        assert status["state"] == "error"
        assert "integrity" in status["error"].lower()
        assert not (data_dir.models_dir / "model.onnx").exists()

    def test_unreachable_server_gives_friendly_error(self, data_dir) -> None:
        spec = spec_for("http://127.0.0.1:1/model.onnx", "model.onnx")
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        with pytest.raises(ModelDownloadError) as exc:
            store.download_blocking("test-model")
        status = store.status("test-model")
        assert status["state"] == "error"
        assert "connection" in exc.value.message.lower() or "internet" in str(exc.value.message).lower()

    def test_http_404_reported(self, data_dir, local_http_server) -> None:
        spec = spec_for(f"{local_http_server.url_root}/missing.onnx", "m.onnx")
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        with pytest.raises(ModelDownloadError) as exc:
            store.download_blocking("test-model")
        status = store.status("test-model")
        assert status["state"] == "error"
        assert "404" in status["error"]

    def test_double_download_blocked(self, data_dir) -> None:
        spec = spec_for("http://127.0.0.1:1/model.onnx", "model.onnx")
        store = ModelStore(data_dir.models_dir, specs=(spec,))
        with pytest.raises(ModelDownloadError):
            store.start_download("test-model")
            store.start_download("test-model")  # while first runs
        store.wait_download("test-model", timeout=10)
