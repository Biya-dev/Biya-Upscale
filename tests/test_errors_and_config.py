"""Error semantics and configuration persistence."""

from __future__ import annotations

from pathlib import Path

from biya_upscale import imaging
from biya_upscale.config import DEFAULT_SETTINGS, AppConfig, resolve_port
from biya_upscale.errors import (
    BiyaError,
    CorruptImageError,
    ImageTooLargeError,
    InvalidRequestError,
    ModelNotFoundError,
    NotFoundError,
    OutOfMemoryError,
    ProcessingCancelled,
    UnsupportedFormatError,
)


class TestErrorContracts:
    def test_all_errors_serialize_safely(self) -> None:
        errors = [
            InvalidRequestError("bad request"),
            UnsupportedFormatError(),
            CorruptImageError(),
            ImageTooLargeError("too big", hint="shrink it"),
            ModelNotFoundError(),
            OutOfMemoryError(),
            ProcessingCancelled("cancelled"),
            NotFoundError("gone"),
        ]
        for error in errors:
            payload = error.to_dict()
            assert payload["code"]
            assert isinstance(payload["message"], str) and payload["message"]
            assert set(payload) <= {"code", "message", "hint"}
            # never leak internals
            assert "Traceback" not in payload["message"]

    def test_status_codes(self) -> None:
        assert UnsupportedFormatError().status == 415
        assert CorruptImageError().status == 422
        assert ImageTooLargeError("x").status == 413
        assert ModelNotFoundError().status == 409
        assert NotFoundError("x").status == 404
        assert InvalidRequestError("x").status == 400

    def test_default_hints(self) -> None:
        assert "PNG" in UnsupportedFormatError().hint
        assert "model manager" in ModelNotFoundError().hint.lower()
        assert OutOfMemoryError().hint

    def test_base_is_exception(self) -> None:
        assert issubclass(BiyaError, Exception)


class TestConfig:
    def test_dirs_created(self, tmp_path: Path) -> None:
        config = AppConfig(tmp_path / "data")
        config.ensure_dirs()
        assert config.models_dir.is_dir()
        assert config.inputs_dir.is_dir()
        assert config.results_dir.is_dir()

    def test_settings_roundtrip(self, tmp_path: Path) -> None:
        config = AppConfig(tmp_path / "data")
        config.ensure_dirs()
        saved = config.save_settings({"theme": "light", "scale": 4})
        assert saved["theme"] == "light"
        reloaded = config.load_settings()
        assert reloaded["scale"] == 4
        assert reloaded["quality"] == DEFAULT_SETTINGS["quality"]

    def test_corrupt_settings_do_not_crash(self, tmp_path: Path) -> None:
        config = AppConfig(tmp_path / "data")
        config.ensure_dirs()
        config.settings_path.write_text("{ not json", encoding="utf-8")
        settings = config.load_settings()
        assert settings["scale"] == 2  # defaults survive

    def test_unknown_keys_ignored_on_save(self, tmp_path: Path) -> None:
        config = AppConfig(tmp_path / "data")
        config.ensure_dirs()
        settings = config.save_settings({"theme": "dark", "evil_key": 1})
        assert "evil_key" not in settings

    def test_env_data_dir(self, monkeypatch) -> None:
        monkeypatch.setenv("BIYA_DATA_DIR", "/tmp/biya-test-dir")
        assert AppConfig().data_dir == Path("/tmp/biya-test-dir")

    def test_resolve_port(self, monkeypatch) -> None:
        monkeypatch.delenv("BIYA_PORT", raising=False)
        assert resolve_port(None) == 8765
        assert resolve_port(9000) == 9000
        monkeypatch.setenv("BIYA_PORT", "9123")
        assert resolve_port(None) == 9123


class TestScaleHelpers:
    def test_output_format_extension(self) -> None:
        assert imaging.extension_for_format("jpg") == ".jpg"
        assert imaging.extension_for_format("png") == ".png"
        assert imaging.extension_for_format("webp") == ".webp"
