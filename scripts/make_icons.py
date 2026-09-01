#!/usr/bin/env python3
"""Generate the app's PWA icons, in pure standard library.

There is no image library here and there is not going to be one: this project
takes no new dependencies, for the same reason it takes no build step — one GP
maintains it. PNG is a chunk format wrapping zlib-compressed scanlines, which
`zlib` and `struct` already give us, and the mark is drawn from filled
rectangles so no font rendering is needed either. `rota/palette.py` already
does OKLCH-to-sRGB colour maths from scratch; this is the same bargain.

The mark is a rota grid: four columns of three blocks, one of them picked out
in a contrasting tint. It is what the app actually shows, it survives being
scaled to a 48px home-screen icon, and it needs no glyph outlines.

Every colour is read from `static/css/tokens.css` and `rota/palette.py` rather
than written here, so the icon cannot drift away from the app's palette.

Run it with `python scripts/make_icons.py`. It rewrites `static/icons/`, and
`tests/test_pwa.py` regenerates into a temp directory and asserts the
result is byte-identical to what is committed — so the script and the PNGs
cannot silently disagree.
"""

import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "icons"

# The tint whose block is picked out. Duty carries this tint in the practice's
# own configuration, and Duty is the role the day view pins to the top — but
# the icon reads the palette, never the database, so a session type being
# recoloured in /admin/ can never change what the home screen shows.
ACCENT_TINT_KEY = "red-strong"


# --------------------------------------------------------------------------
# colour, read rather than written
# --------------------------------------------------------------------------

def _token(name: str) -> str:
    """A custom property's value from the light block of tokens.css."""
    css = (ROOT / "static" / "css" / "tokens.css").read_text()
    # Only the bare :root block — the dark redefinitions come later in the
    # file and would win a naive last-match search.
    light = css[css.index(":root {"):css.index("@media")]
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})", light)
    if not match:
        raise SystemExit(f"{name} not found in the light :root block of tokens.css")
    return match.group(1)


def _rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


# --------------------------------------------------------------------------
# a very small PNG writer
# --------------------------------------------------------------------------

def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def _png(pixels: list[list[tuple[int, int, int]]]) -> bytes:
    """Truecolour, 8 bits per channel, no interlacing, filter type 0.

    Filter 0 ("None") on every scanline keeps this honest: a real encoder
    would try the five filters per row for a smaller file, and these icons
    are small enough that the complexity buys nothing.
    """
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for r, g, b in row:
            raw += bytes((r, g, b))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------
# the mark
# --------------------------------------------------------------------------

COLUMNS, ROWS = 4, 3
# Which block is picked out, as (column, row) from the top left. Second
# column, middle row: off-centre enough to read as a marked session rather
# than a decorative centre point, and well inside the maskable safe zone.
MARKED = (1, 1)


def render(size: int, inset: float) -> list[list[tuple[int, int, int]]]:
    """One icon as a pixel grid.

    `inset` is the fraction of the edge left as bare ground. A maskable icon
    needs its content inside a circle of 80% diameter, so it takes a much
    larger inset than the plain one — the corners of a maskable icon can be
    cropped to any shape the platform likes.
    """
    ground = _rgb(_token("--accent"))
    block = _rgb(_token("--accent-soft"))

    sys.path.insert(0, str(ROOT))
    from rota import palette
    marked = _rgb(palette.TINTS[ACCENT_TINT_KEY].bg)

    pixels = [[ground] * size for _ in range(size)]

    span = size * (1 - 2 * inset)
    left = top = size * inset
    # A gap of a third of a block reads as a grid rather than as stripes at
    # 48px, which is the size that actually has to survive.
    gap = span / (COLUMNS + (COLUMNS - 1) / 3) / 3
    block_w = (span - gap * (COLUMNS - 1)) / COLUMNS
    block_h = (span - gap * (ROWS - 1)) / ROWS

    for col in range(COLUMNS):
        for row in range(ROWS):
            x0 = round(left + col * (block_w + gap))
            y0 = round(top + row * (block_h + gap))
            x1 = round(left + col * (block_w + gap) + block_w)
            y1 = round(top + row * (block_h + gap) + block_h)
            fill = marked if (col, row) == MARKED else block
            for y in range(max(y0, 0), min(y1, size)):
                for x in range(max(x0, 0), min(x1, size)):
                    pixels[y][x] = fill
    return pixels


# name -> (pixel size, inset fraction)
ICONS = {
    "icon-192.png": (192, 0.16),
    "icon-512.png": (512, 0.16),
    # Maskable: content inside the 80%-diameter safe circle, so a platform
    # cropping to a circle, squircle or rounded square never clips a block.
    "maskable-512.png": (512, 0.28),
    # iOS applies its own corner radius and does not read the manifest, so
    # this one is referenced directly from base.html.
    "apple-touch-icon.png": (180, 0.16),
    "favicon-32.png": (32, 0.12),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (size, inset) in ICONS.items():
        (OUT / name).write_bytes(_png(render(size, inset)))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
