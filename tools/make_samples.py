"""Generate sample images for manual testing (PNG / JPG / WEBP)."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"


def gradient_background(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            r = int(40 + 140 * x / width)
            g = int(60 + 120 * y / height)
            b = int(120 + 100 * (1 - x / width))
            px[x, y] = (r, g, b)
    return img


def add_scene(img: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    # sun
    draw.ellipse([w * 0.68, h * 0.12, w * 0.86, h * 0.32], fill=(250, 220, 120))
    # mountains
    draw.polygon(
        [(0, h), (w * 0.25, h * 0.42), (w * 0.5, h)], fill=(38, 52, 74)
    )
    draw.polygon(
        [(w * 0.3, h), (w * 0.6, h * 0.35), (w * 0.95, h)], fill=(52, 70, 96)
    )
    # foreground strip + grid of small marks (fine detail for upscale checks)
    draw.rectangle([0, h * 0.86, w, h], fill=(24, 32, 46))
    for i in range(18):
        x = w * 0.04 + i * (w * 0.9 / 18)
        draw.line([(x, h * 0.89), (x, h * 0.97)], fill=(210, 220, 235), width=2)
        draw.text((x + 4, h * 0.9), "Biya", fill=(255, 255, 255))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) PNG landscape 1920x1080
    scene = add_scene(gradient_background(1920, 1080))
    scene.save(OUT / "landscape_1920x1080.png")

    # 2) small JPG (the classic "low-res input" case) 320x240
    small = gradient_background(320, 240)
    draw = ImageDraw.Draw(small)
    draw.ellipse([40, 40, 150, 150], fill=(230, 90, 90))
    draw.rectangle([170, 60, 280, 200], outline=(255, 255, 255), width=4)
    draw.text((60, 200), "320x240 sample", fill=(255, 255, 255))
    small.save(OUT / "small_320x240.jpg", quality=90)

    # 3) WEBP with alpha 800x600
    sticker = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(sticker)
    d.ellipse([100, 75, 700, 525], fill=(60, 200, 160, 255), outline=(20, 40, 60, 255), width=12)
    d.ellipse([260, 200, 330, 280], fill=(255, 255, 255, 255))
    d.ellipse([470, 200, 540, 280], fill=(255, 255, 255, 255))
    d.arc([280, 300, 520, 440], start=20, end=160, fill=(20, 40, 60, 255), width=14)
    sticker.save(OUT / "sticker_800x600_alpha.webp")

    # 4) noisy "photo-like" texture (stress-tests real detail recovery)
    noise = gradient_background(640, 480).filter(ImageFilter.GaussianBlur(1.5))
    d = ImageDraw.Draw(noise)
    for i in range(0, 640, 8):
        d.line([(i, 0), (i, 480)], fill=(255 if (i // 8) % 2 else 0,) * 3, width=1)
    d.ellipse([80, 120, 560, 400], outline=(255, 240, 120), width=6)
    d.text((240, 250), "DETAIL TEST " + "x" * 10, fill=(255, 255, 255))
    noise.save(OUT / "texture_640x480.png")

    # 5) invalid file for error-path testing
    (OUT / "not_an_image.png").write_bytes(
        b"This is definitely not a PNG file, just text pretending to be one."
    )

    for path in sorted(OUT.iterdir()):
        print(f"{path.name:36} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
