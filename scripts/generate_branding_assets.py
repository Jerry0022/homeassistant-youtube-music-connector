#!/usr/bin/env python3
"""Generate branding assets for the integration and companion add-on."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "youtube_music_connector_companion"
BRAND_DIR = REPO_ROOT / "custom_components" / "youtube_music_connector" / "brand"


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack("!I", len(data))
        + tag
        + data
        + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row = pixels[y * width : (y + 1) * width]
        for r, g, b, a in row:
            raw.extend((r, g, b, a))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(clamp(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render_icon(size: int, dark: bool) -> list[tuple[int, int, int, int]]:
    pixels: list[tuple[int, int, int, int]] = []
    top = (122, 12, 24) if not dark else (255, 98, 98)
    bottom = (255, 72, 66) if not dark else (153, 18, 24)
    ring = (255, 226, 168)
    core = (34, 10, 12) if not dark else (72, 8, 12)
    pulse = (255, 255, 255)
    glow = (255, 171, 171)

    center = size / 2
    radius = size * 0.34
    inner_radius = radius * 0.58
    pulse_radius = radius * 1.22

    for y in range(size):
        for x in range(size):
            nx = x + 0.5
            ny = y + 0.5
            gx = nx / size
            gy = ny / size
            bg = mix(top, bottom, gy)

            dx = nx - center
            dy = ny - center
            distance = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)

            color = bg
            alpha = 255

            if distance < pulse_radius:
                shimmer = 0.5 + 0.5 * math.cos(angle * 3 - distance / 18)
                pulse_strength = max(0.0, 1.0 - (distance / pulse_radius) ** 1.7) * 0.34
                color = mix(color, glow, pulse_strength * shimmer)

            if distance < radius:
                color = ring
            if distance < inner_radius:
                color = core

            # Stylized play triangle.
            tx = (nx - center) / radius
            ty = (ny - center) / radius
            in_triangle = (
                tx > -0.12
                and tx < 0.46
                and ty > (-0.50 * tx - 0.18)
                and ty < (0.50 * tx + 0.18)
            )
            if in_triangle:
                color = pulse

            # Small music pulse notch.
            notch_center_x = center - radius * 0.84
            notch_center_y = center - radius * 0.18
            notch = math.hypot(nx - notch_center_x, ny - notch_center_y)
            if notch < radius * 0.14:
                color = pulse

            pixels.append((color[0], color[1], color[2], alpha))

    return pixels


def main() -> int:
    addon_icon = render_icon(256, dark=False)
    addon_dark = render_icon(256, dark=True)
    write_png(ADDON_DIR / "icon.png", 256, 256, addon_icon)
    write_png(ADDON_DIR / "logo.png", 256, 256, addon_icon)
    write_png(ADDON_DIR / "dark_icon.png", 256, 256, addon_dark)
    write_png(ADDON_DIR / "dark_logo.png", 256, 256, addon_dark)

    integration_icon = render_icon(256, dark=False)
    integration_dark = render_icon(256, dark=True)
    write_png(BRAND_DIR / "icon.png", 256, 256, integration_icon)
    write_png(BRAND_DIR / "logo.png", 256, 256, integration_icon)
    write_png(BRAND_DIR / "dark_icon.png", 256, 256, integration_dark)
    write_png(BRAND_DIR / "dark_logo.png", 256, 256, integration_dark)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
