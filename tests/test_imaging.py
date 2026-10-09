"""Image loading, validation, saving and safety-limit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from biya_upscale import imaging
from biya_upscale.errors import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedFormatError,
)


class TestLoadSupportedFormats:
    def test_load_png(self, png_bytes: bytes) -> None:
        img = imaging.load_image_bytes(png_bytes, filename="a.png")
        assert (img.width, img.height) == (32, 24)
        assert img.format == "PNG"
        assert img.mode in ("RGB", "P")

    def test_load_jpeg(self, jpg_bytes: bytes) -> None:
        img = imaging.load_image_bytes(jpg_bytes, filename="photo.jpg")
        assert (img.width, img.height) == (40, 30)
        assert img.format == "JPEG"

    def test_load_jpeg_extension_variant(self, jpg_bytes: bytes) -> None:
        img = imaging.load_image_bytes(jpg_bytes, filename="photo.jpeg")
        assert img.format == "JPEG"

    def test_load_webp(self, webp_bytes: bytes) -> None:
        img = imaging.load_image_bytes(webp_bytes, filename="sticker.webp")
        assert (img.width, img.height) == (36, 28)
        assert img.format == "WEBP"

    def test_load_rgba_keeps_alpha(self, rgba_png_bytes: bytes) -> None:
        img = imaging.load_image_bytes(rgba_png_bytes, filename="rgba.png")
        assert imaging.has_alpha(img)

    def test_split_alpha_returns_channels(self, rgba_png_bytes: bytes) -> None:
        img = imaging.load_image_bytes(rgba_png_bytes, filename="rgba.png")
        rgb, alpha = imaging.split_alpha(img)
        assert rgb.mode == "RGB"
        assert alpha is not None
        assert alpha.size == (32, 24)


class TestInvalidInputs:
    def test_empty_bytes_rejected(self) -> None:
        with pytest.raises(CorruptImageError):
            imaging.load_image_bytes(b"", filename="x.png")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(CorruptImageError):
            imaging.load_image_bytes(b"totally not an image", filename="x.png")

    def test_corrupt_png_rejected(self, corrupt_bytes: bytes) -> None:
        with pytest.raises(CorruptImageError):
            imaging.load_image_bytes(corrupt_bytes, filename="broken.png")

    def test_unsupported_extension_rejected(self) -> None:
        with pytest.raises(UnsupportedFormatError):
            imaging.check_extension("archive.zip")
        with pytest.raises(UnsupportedFormatError):
            imaging.check_extension("movie.gif")

    def test_path_traversal_neutralized(self) -> None:
        assert imaging.sanitize_filename("../../etc/passwd") == "passwd"
        assert imaging.sanitize_filename("C:\\Windows\\evil.exe") == "evil.exe"
        assert imaging.sanitize_filename("") == "image"


class TestLimits:
    def test_input_pixel_cap(self) -> None:
        with pytest.raises(ImageTooLargeError):
            imaging.check_dimensions(9000, 9000)  # 81 MP > 40 MP

    def test_output_pixel_cap(self) -> None:
        with pytest.raises(ImageTooLargeError):
            imaging.check_dimensions(9000, 6000, scale=4)  # 864 MP output

    def test_reasonable_sizes_pass(self) -> None:
        imaging.check_dimensions(1920, 1080, scale=4)
        imaging.check_dimensions(6000, 5000, scale=2)  # 30 MP -> 120 MP

    def test_invalid_scale_rejected(self) -> None:
        with pytest.raises(UnsupportedFormatError):
            imaging.validate_scale(3)
        assert imaging.validate_scale(2) == 2
        assert imaging.validate_scale(4) == 4

    def test_format_normalisation(self) -> None:
        assert imaging.normalize_format("jpg") == "JPEG"
        assert imaging.normalize_format("JPEG") == "JPEG"
        assert imaging.normalize_format(".png") == "PNG"
        assert imaging.normalize_format("webp") == "WEBP"
        with pytest.raises(UnsupportedFormatError):
            imaging.normalize_format("tiff")


class TestSaveAndPreview:
    def test_save_is_atomic_and_creates_parent(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (10, 10), (1, 2, 3))
        dest = tmp_path / "nested" / "out.png"
        imaging.save_image(img, dest, fmt="PNG")
        assert dest.exists()
        assert not dest.with_name(dest.name + ".part").exists()

    def test_save_jpeg_drops_alpha(
        self, tmp_path: Path, rgba_png_bytes: bytes
    ) -> None:
        img = imaging.load_image_bytes(rgba_png_bytes, filename="a.png")
        dest = tmp_path / "out.jpg"
        imaging.save_image(img, dest, fmt="JPEG", quality=85)
        saved = Image.open(dest)
        assert saved.format == "JPEG"
        assert saved.mode == "RGB"

    def test_roundtrip_webp(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (16, 16), (200, 100, 50))
        dest = tmp_path / "out.webp"
        imaging.save_image(img, dest, fmt="WEBP", quality=90)
        reloaded = imaging.load_image_path(dest)
        assert reloaded.format == "WEBP"
        assert (reloaded.width, reloaded.height) == (16, 16)

    def test_preview_respects_max_side(self) -> None:
        big = Image.new("RGBA", (3200, 800), (9, 9, 9, 255))
        preview = imaging.make_preview(big, max_side=1600)
        assert max(preview.width, preview.height) == 1600
        assert preview.width / preview.height == pytest.approx(4.0, rel=0.01)

    def test_preview_keeps_small_images(self) -> None:
        img = Image.new("RGB", (300, 200))
        preview = imaging.make_preview(img, max_side=1600)
        assert (preview.width, preview.height) == (300, 200)

    def test_image_info_shape(self, jpg_bytes: bytes) -> None:
        img = imaging.load_image_bytes(jpg_bytes, filename="photo.jpg")
        info = imaging.image_info(
            img, filename="photo.jpg", size_bytes=len(jpg_bytes)
        )
        assert info["width"] == 40
        assert info["format"] == "JPEG"
        assert info["size_bytes"] == len(jpg_bytes)
        assert info["has_alpha"] is False

    def test_load_image_path(self, tmp_path: Path) -> None:
        source = tmp_path / "sample.png"
        source.write_bytes(Image.new("RGB", (11, 7)).tobytes()[:0] or b"")
        # write a real PNG instead of raw bytes
        Image.new("RGB", (11, 7), (5, 6, 7)).save(source)
        img = imaging.load_image_path(source)
        assert (img.width, img.height) == (11, 7)

    def test_missing_file_raises_corrupt(self, tmp_path: Path) -> None:
        with pytest.raises(CorruptImageError):
            imaging.load_image_path(tmp_path / "nope.png")

