"""Image loading, validation, previews and saving.

All input files are treated as untrusted: they are only ever decoded by
Pillow (never executed), size-checked before decoding, and copied into the
app's own working directory. Originals are never modified.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedFormatError,
)

# Hard limits — generous for consumer photos, protective for RAM/VRAM.
MAX_INPUT_PIXELS = 40_000_000       # 40 MP
MAX_OUTPUT_PIXELS = 150_000_000     # 150 MP (allows 4K @ 4x = 133 MP)
MAX_FILE_BYTES = 150 * 1024 * 1024  # 150 MB upload cap

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Pillow internal guard kept in place as an extra safety net.
Image.MAX_IMAGE_PIXELS = 200_000_000

_EXT_BY_FORMAT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


def normalize_format(fmt: str) -> str:
    """Map user-facing format names (jpg/jpeg) onto Pillow names."""
    fmt = fmt.lower().strip().lstrip(".")
    if fmt in ("jpg", "jpeg"):
        return "JPEG"
    if fmt in ("png", "webp"):
        return fmt.upper()
    raise UnsupportedFormatError(
        f"'{fmt}' is not a supported output format.",
        hint="Choose PNG, JPG or WEBP.",
    )


def extension_for_format(fmt: str) -> str:
    return _EXT_BY_FORMAT[normalize_format(fmt)]


def sanitize_filename(name: str) -> str:
    """Keep only the basename of a user-provided name; default to 'image'."""
    base = Path(str(name).replace("\\", "/")).name
    cleaned = "".join(c for c in base if c.isalnum() or c in " ._()-[]").strip()
    cleaned = cleaned.lstrip(".")
    return cleaned or "image"


def check_extension(filename: str) -> str:
    ext = Path(sanitize_filename(filename)).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"'{Path(filename).name or filename}' is not a supported file type.",
            hint="Supported formats: PNG, JPG/JPEG and WEBP.",
        )
    return ext


def check_dimensions(width: int, height: int, *, scale: int = 1) -> None:
    if width <= 0 or height <= 0:
        raise CorruptImageError("The image has invalid dimensions.")
    if width * height > MAX_INPUT_PIXELS:
        raise ImageTooLargeError(
            f"This image is too large ({width}×{height}).",
            hint=(
                f"The limit is {MAX_INPUT_PIXELS // 1_000_000} megapixels "
                f"({width * height // 1_000_000} MP here). Resize it first."
            ),
        )
    out_px = width * height * scale * scale
    if out_px > MAX_OUTPUT_PIXELS:
        raise ImageTooLargeError(
            f"A {scale}× upscale of this image would produce "
            f"{width * scale}×{height * scale} pixels "
            f"({out_px // 1_000_000} MP).",
            hint=(
                f"Output is capped at {MAX_OUTPUT_PIXELS // 1_000_000} MP. "
                "Try the 2× scale or a smaller image."
            ),
        )


def validate_scale(scale: int) -> int:
    if scale not in (2, 4):
        raise UnsupportedFormatError(
            f"{scale}× is not a supported scale factor.",
            hint="Choose 2× or 4×.",
        )
    return scale


def load_image_bytes(data: bytes, *, filename: str = "image") -> Image.Image:
    """Decode untrusted bytes into a verified, fully-loaded PIL image."""
    if not data:
        raise CorruptImageError("The file is empty.", hint="The upload may have failed.")
    if len(data) > MAX_FILE_BYTES:
        raise ImageTooLargeError(
            "This file is larger than the 150 MB limit.",
            hint="Try a smaller image or a more efficient format.",
        )
    ext = Path(sanitize_filename(filename)).suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"'{Path(filename).name}' is not a supported file type."
        )

    try:
        img = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(
            "This image is too large to open safely.",
            hint="Resize the image in an editor and try again.",
        ) from exc
    except UnidentifiedImageError as exc:
        raise CorruptImageError(
            "This file is not a readable image.",
            hint="It may be corrupted, or not really a PNG/JPG/WEBP file.",
        ) from exc
    except Exception as exc:  # Pillow raises many format-specific errors
        raise CorruptImageError(
            "This image could not be opened.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    fmt = (img.format or "").upper()
    if fmt not in ("PNG", "JPEG", "WEBP"):
        raise UnsupportedFormatError(
            f"{fmt or 'Unknown'} images are not supported.",
            hint="Supported formats: PNG, JPG/JPEG and WEBP.",
        )

    check_dimensions(img.width, img.height)

    try:
        img.load()  # forces full decode; raises on truncated files
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError("This image is too large to open safely.") from exc
    except Exception as exc:
        raise CorruptImageError(
            "This image is damaged and could not be fully read.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    try:
        img = ImageOps.exif_transpose(img) or img
    except Exception:
        pass  # broken EXIF must not block processing
    # exif_transpose may return a copy — restore the source format metadata.
    img.format = fmt
    check_dimensions(img.width, img.height)
    return img


def load_image_path(path: Path) -> Image.Image:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CorruptImageError(f"Could not read '{path.name}'.") from exc
    return load_image_bytes(data, filename=path.name)


def image_info(img: Image.Image, *, filename: str, size_bytes: int) -> dict[str, Any]:
    fmt = (img.format or "").upper()
    if fmt not in ("PNG", "JPEG", "WEBP"):
        fmt = "UNKNOWN"
    return {
        "filename": sanitize_filename(filename),
        "width": img.width,
        "height": img.height,
        "size_bytes": size_bytes,
        "format": fmt,
        "mode": img.mode,
        "has_alpha": has_alpha(img),
    }



def has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P":
        return "transparency" in img.info
    return False


def split_alpha(img: Image.Image) -> tuple[Image.Image, Optional[Image.Image]]:
    """Return (RGB image, alpha channel or None)."""
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        rgba = img.convert("RGBA")
        return rgba.convert("RGB"), rgba.getchannel("A")
    if img.mode != "RGB":
        return img.convert("RGB"), None
    return img, None


def save_image(img: Image.Image, path: Path, *, fmt: str, quality: int = 95) -> None:
    """Atomically save (``.part`` then rename) so partial files never linger."""
    fmt = normalize_format(fmt)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if fmt == "JPEG":
        kwargs.update(quality=max(1, min(int(quality), 100)), optimize=True, progressive=True)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")  # JPEG has no alpha
    elif fmt == "WEBP":
        kwargs.update(quality=max(1, min(int(quality), 100)), method=4)
    tmp = path.with_name(path.name + ".part")
    try:
        img.save(tmp, format=fmt, **kwargs)
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def make_preview(img: Image.Image, *, max_side: int = 1600) -> Image.Image:
    """Small preview used by the before/after slider (keeps RAM low)."""
    copy = img.copy()
    longest = max(copy.width, copy.height)
    if longest > max_side:
        ratio = max_side / longest
        copy = copy.resize(
            (max(1, round(copy.width * ratio)), max(1, round(copy.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    if copy.mode not in ("RGB", "L"):
        copy = copy.convert("RGB")
    return copy

