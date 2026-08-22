#!/usr/bin/env python3
"""Draw the MangaTCT mark as a PNG and a Windows .ico.

The mark itself lives in `static/favicon.svg` and is inlined in the top-left
of the editor. Tk cannot read SVG and Windows wants an `.ico`, so the same
outline is drawn here with PIL and written out beside it - which is how the
Save-as dialog stops wearing Tk's own blue feather.

    python tools/make_icon.py

The path is the one out of the SVG, in its 64x64 viewBox: an abstract M whose
right leg falls away into a brush stroke. The fill is the same two-stop
gradient, angled the way the SVG angles it (x2=.25, y2=1).
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "mangatl", "static")

VIEW = 64
PATH = [(7, 10), (18, 10), (32, 30), (46, 10), (57, 10), (57, 46),
        (46.5, 46), (46.5, 26.5), (35.5, 42), (28.5, 42), (17.5, 26.5),
        (17.5, 47), (11.5, 60), (7, 47)]
TOP, BOTTOM = (0xFF, 0xC4, 0x00), (0xFF, 0x9D, 0x00)
# The gradient's direction in the SVG: from (0,0) to (.25,1) of the box.
DIR = (0.25, 1.0)
SS = 8                      # drawn this many times over and shrunk back down


def _gradient(size: int) -> Image.Image:
    g = Image.new("RGB", (size, size))
    px = g.load()
    dx, dy = DIR
    span = dx * dx + dy * dy
    for y in range(size):
        for x in range(size):
            # how far along the gradient's axis this pixel is, 0..1
            t = ((x / size) * dx + (y / size) * dy) / span
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            px[x, y] = tuple(int(round(a + (b - a) * t))
                             for a, b in zip(TOP, BOTTOM))
    return g


# How much of the square the mark fills. An icon is looked at at 16px in a
# title bar, where the SVG's own margin - it sits in x 7..57 of a 64 box, with
# room round it for the wordmark beside it - is margin nobody can afford.
FILL = 0.94


def mark(size: int = 512) -> Image.Image:
    """The mark on transparency, `size` square, filling it."""
    big = size * SS
    xs = [x for x, _y in PATH]
    ys = [y for _x, y in PATH]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    scale = big * FILL / max(w, h)
    ox = (big - w * scale) / 2 - min(xs) * scale
    oy = (big - h * scale) / 2 - min(ys) * scale
    shape = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape).polygon(
        [(x * scale + ox, y * scale + oy) for x, y in PATH], fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(_gradient(size).resize((big, big), Image.NEAREST), (0, 0),
              shape)
    return out.resize((size, size), Image.LANCZOS)


def main() -> int:
    png = os.path.join(STATIC, "icon.png")
    ico = os.path.join(STATIC, "icon.ico")
    art = mark(512)
    art.save(png)
    # Every size Windows asks for, from the taskbar down to the title bar.
    art.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(png)
    print(ico)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
