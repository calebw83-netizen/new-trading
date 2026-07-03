from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


OUT = Path("ios/TradeRadar/TradeRadar/Assets.xcassets/AppIcon.appiconset")
SIZES = [40, 58, 60, 80, 87, 120, 180, 1024]


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, size: int) -> None:
    pixels = []
    for y in range(size):
        row = bytearray()
        row.append(0)
        for x in range(size):
            radius = size * 0.2
            corner = min(x, y, size - 1 - x, size - 1 - y)
            in_corner = corner < radius
            alpha = 255
            if in_corner:
                cx = radius if x < size / 2 else size - radius
                cy = radius if y < size / 2 else size - radius
                if math.hypot(x - cx, y - cy) > radius:
                    alpha = 0
            r, g, b = 18, 108, 90
            if alpha and size * 0.62 < y < size * 0.72 and size * 0.18 < x < size * 0.82:
                r, g, b = 244, 246, 242
            if alpha and abs(y - (size * 0.68 - (x - size * 0.2) * 0.55)) < size * 0.035 and size * 0.2 < x < size * 0.78:
                r, g, b = 255, 255, 255
            if alpha and (x - size * 0.72) ** 2 + (y - size * 0.28) ** 2 < (size * 0.06) ** 2:
                r, g, b = 255, 248, 214
            row.extend([r, g, b, alpha])
        pixels.append(bytes(row))

    raw = b"".join(pixels)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        write_png(OUT / f"Icon-{size}.png", size)


if __name__ == "__main__":
    main()
