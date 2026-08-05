from __future__ import annotations

import colorsys
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageStat, UnidentifiedImageError


@dataclass(frozen=True, slots=True)
class BrandPalette:
    primary: str
    secondary: str
    dark: str
    foreground: str = "#FFFFFF"


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(c))):02X}" for c in rgb)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise ValueError("invalid color")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def relative_luminance(color: str) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second, strict=True)))


def _darken(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(value * factor))) for value in rgb)


def _saturation(rgb: tuple[int, int, int]) -> float:
    return colorsys.rgb_to_hsv(*(value / 255 for value in rgb))[1]


def extract_brand_palette(raw: bytes) -> BrandPalette:
    """Extract a stable, accessible palette without a legacy ColorThief dependency.

    White/near-white background pixels are ignored. The image is bounded before
    quantization, and final dark colors are adjusted until white text has WCAG AA
    contrast. This keeps report rendering deterministic across workers.
    """
    if not raw:
        raise ValueError("empty image")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            image = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("invalid image") from exc

    image.thumbnail((320, 320), Image.Resampling.LANCZOS)
    pixels: list[tuple[int, int, int]] = []
    for red, green, blue, alpha in image.get_flattened_data():
        if alpha < 96:
            continue
        maximum, minimum = max(red, green, blue), min(red, green, blue)
        if minimum >= 238 or (maximum - minimum < 8 and minimum >= 210):
            continue
        pixels.append((red, green, blue))
    if not pixels:
        mean = tuple(round(value) for value in ImageStat.Stat(image.convert("RGB")).mean)
        pixels = [mean]

    strip = Image.new("RGB", (len(pixels), 1))
    strip.putdata(pixels)
    quantized = strip.quantize(colors=min(12, max(2, len(set(pixels)))), method=Image.Quantize.MEDIANCUT)
    palette_raw = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], reverse=True)
    candidates: list[tuple[int, tuple[int, int, int]]] = []
    for count, index in counts:
        offset = index * 3
        if offset + 2 >= len(palette_raw):
            continue
        rgb = tuple(palette_raw[offset:offset + 3])
        candidates.append((count, rgb))
    if not candidates:
        candidates = [(1, (11, 74, 169)), (1, (20, 165, 162))]

    saturated = [item for item in candidates if _saturation(item[1]) >= 0.28]
    pool = saturated or candidates
    primary_rgb = max(pool, key=lambda item: (item[0], -sum(item[1])))[1]
    distinct = [item for item in pool if _distance(item[1], primary_rgb) >= 70]
    secondary_rgb = max(distinct or pool, key=lambda item: (item[0] * (0.5 + _saturation(item[1])), sum(item[1])))[1]
    if _distance(secondary_rgb, primary_rgb) < 35:
        secondary_rgb = (20, 165, 162)

    dark_rgb = min(candidates, key=lambda item: sum(item[1]))[1]
    primary = _hex(primary_rgb)
    secondary = _hex(secondary_rgb)
    dark = _hex(dark_rgb)
    while contrast_ratio(dark, "#FFFFFF") < 4.5:
        dark_rgb = _darken(dark_rgb, 0.88)
        dark = _hex(dark_rgb)
    if contrast_ratio(primary, "#FFFFFF") < 3.0:
        primary_rgb = _darken(primary_rgb, 0.78)
        primary = _hex(primary_rgb)
    return BrandPalette(primary=primary, secondary=secondary, dark=dark)
