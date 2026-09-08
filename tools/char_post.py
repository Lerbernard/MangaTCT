#!/usr/bin/env python3
"""Finish a generated character: take the ground off, put the mark on.

    python tools/char_post.py out/char/sheet_8493120.png
    python tools/char_post.py out/char/*.png --mark 398,276,56
    python tools/char_post.py out/char/sheet_8493120.png --no-mark

For each input it writes three files beside it:

    <name>_cut.png      her, on nothing - the one to keep
    <name>_white.png    on white, for the app and for sheets
    <name>_dark.png     on the chapter card's ground

## Why the ground comes off rather than being prompted away

The model is told `white background` and paints a flat blue-grey anyway, every
time. Arguing with it costs a generation a go; cutting it costs nothing and is
exact, because what it paints IS flat - one colour, reaching the edges. So the
cut is a flood from the border rather than a colour key: a key would also
punch holes through anything inside her that happens to match the ground, and
on a navy coat under grey light that is most of the coat's shadows.

## Why the mark is stamped and not prompted

An image model cannot draw a logo the same way twice. Prompt it and every
picture wears a slightly different, slightly wrong M, which is worse than no
M at all - a wobbly trademark reads as a fake. So the drawing is asked for the
character and the mark goes on afterwards, from `static/favicon.svg`, at the
exact proportions it has everywhere else in the app.
"""
import argparse
import glob
import io
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = os.path.join(HERE, "static", "favicon.svg")
WHITE = (255, 255, 255)
DARK = (24, 18, 15)                 # the chapter card's ground, BGR


def cut(bgr: np.ndarray, tol: int = 26) -> np.ndarray:
    """BGRA, with the flat ground behind her made transparent."""
    h, w = bgr.shape[:2]
    # Flood in from all four corners. `floodFill` wants a mask two bigger than
    # the picture and marks what it reached with 1s.
    mask = np.zeros((h + 2, w + 2), np.uint8)
    # FIXED_RANGE, and it is the whole thing. Without it `floodFill` compares
    # each pixel to the one it came FROM, so a tolerance of 26 walks the length
    # of any gradual change - out of the grey ground, up the shaded side of the
    # coat, through the hair, and the figure comes back as confetti. Fixed
    # range compares to the SEED, which is the question being asked: is this
    # pixel the ground colour.
    flags = (4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
             | (255 << 8))
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        cv2.floodFill(bgr.copy(), mask, seed, 0,
                      (tol,) * 3, (tol,) * 3, flags)
    bg = mask[1:-1, 1:-1] > 0
    # One pixel back off the edge she was cut along, so the ground's colour
    # does not survive as a halo in the antialiasing.
    bg = cv2.dilate(bg.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    out = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    out[..., 3] = np.where(bg, 0, 255).astype(np.uint8)
    return out


def mark_bgra(size: int) -> np.ndarray:
    import cairosvg
    from PIL import Image
    png = cairosvg.svg2png(url=MARK, output_width=size, output_height=size)
    im = np.array(Image.open(io.BytesIO(png)).convert("RGBA"))
    return cv2.cvtColor(im, cv2.COLOR_RGBA2BGRA)


# How dark the thread's own relief goes, and how far the coat's shading is
# allowed to pull the gold down. Both measured by eye on a navy coat: below
# these it is a sticker again, above them the mark goes muddy in the folds.
RELIEF = 0.45
CLOTH = 0.55


def worn(fig: np.ndarray, m: np.ndarray, x: int, y: int,
         patch: bool) -> np.ndarray:
    """The mark ON the uniform rather than on top of the picture.

    lee: *"the m shoud be part of teh uniform"*. Pasted flat it reads as a
    sticker laid over the photograph, because it is: the coat underneath has
    folds, a shaded side and a lit side, and the mark has none of them. Three
    things fix that, and they are the three things that make real insignia
    look real:

    * **the cloth's own shading, multiplied through it.** Whatever is dark
      under the mark - a fold, the shadow under the lapel - darkens the mark
      in the same place, so it lies on the surface instead of hovering over it.
    * **relief.** A stitched or printed mark sits slightly proud of the cloth:
      a dark edge below and right of it, a lighter one above and left.
    * optionally **a patch**, for a uniform that carries its insignia on a
      backing - a rounded field in the coat's own colour with a stitched gold
      edge, which is what a shoulder flash actually is.
    """
    h, w = m.shape[:2]
    H, W = fig.shape[:2]
    if x < 0 or y < 0 or x + w > W or y + h > H:
        return over(fig, m, x, y)              # off the edge: nothing to read
    under = fig[y:y + h, x:x + w, :3].astype(np.float32)

    out = fig
    if patch:
        # The backing: the coat's own colour a little darker, rounded, with a
        # gold stitch round it. Sized off the mark, not off a guess.
        pad = int(round(w * 0.22))
        # ...with two pixels of nothing round it. The stitch below is the
        # gradient of the backing's alpha, and a shape drawn hard against the
        # edge of its own array has no gradient there - which came out as a
        # patch with gold in the corners and bare sides.
        rim = 2
        field = np.zeros((h + 2 * pad + 2 * rim, w + 2 * pad + 2 * rim, 4),
                         np.uint8)
        base = tuple(int(v) for v in np.median(under.reshape(-1, 3),
                                               axis=0) * 0.82)
        r = int(round(w * 0.18))
        box = (rim, rim, field.shape[1] - 1 - rim,
               field.shape[0] - 1 - rim)
        cv2.rectangle(field, (box[0] + r, box[1]), (box[2] - r, box[3]),
                      (*base, 255), -1)
        cv2.rectangle(field, (box[0], box[1] + r), (box[2], box[3] - r),
                      (*base, 255), -1)
        for cx, cy in ((box[0] + r, box[1] + r), (box[2] - r, box[1] + r),
                       (box[0] + r, box[3] - r), (box[2] - r, box[3] - r)):
            cv2.circle(field, (cx, cy), r, (*base, 255), -1)
        # the stitch, in the mark's own gold
        edge = cv2.morphologyEx(field[..., 3], cv2.MORPH_GRADIENT,
                                np.ones((3, 3), np.uint8))
        field[edge > 0, :3] = (0, 157, 255)     # BGR of #ff9d00
        out = over(out, field, x - pad - rim, y - pad - rim)
        under = out[y:y + h, x:x + w, :3].astype(np.float32)

    # the cloth's shading, through the mark
    lum = cv2.cvtColor(under.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    lum = cv2.GaussianBlur(lum, (0, 0), max(1.0, w / 14.0)).astype(np.float32)
    k = lum / max(1.0, float(np.median(lum)))
    k = np.clip(1.0 + (k - 1.0) * CLOTH, 0.55, 1.35)[..., None]
    m = m.copy()
    m[..., :3] = np.clip(m[..., :3].astype(np.float32) * k, 0, 255).astype(np.uint8)

    # relief: a dark copy down-right, a pale one up-left, both behind it
    a = m[..., 3]
    off = max(1, int(round(w / 34.0)))
    for (dx, dy, col, amt) in ((off, off, (0, 0, 0), RELIEF),
                               (-off, -off, (255, 255, 255), RELIEF * 0.5)):
        sh = np.zeros_like(m)
        sh[..., :3] = col
        sh[..., 3] = (a.astype(np.float32) * amt).astype(np.uint8)
        out = over(out, sh, x + dx, y + dy)
    return over(out, m, x, y)


def over(under: np.ndarray, top: np.ndarray, x: int, y: int) -> np.ndarray:
    """`top` composited onto `under` at (x, y). Both BGRA."""
    h, w = top.shape[:2]
    H, W = under.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return under
    sub = top[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sub[..., 3:4].astype(np.float32) / 255.0
    dst = under[y0:y1, x0:x1]
    dst[..., :3] = (sub[..., :3] * a + dst[..., :3] * (1 - a)).astype(np.uint8)
    dst[..., 3] = np.maximum(dst[..., 3], sub[..., 3])
    return under


def on(fig: np.ndarray, colour) -> np.ndarray:
    card = np.zeros(fig.shape, np.uint8)
    card[..., :3] = colour
    card[..., 3] = 255
    return over(card, fig, 0, 0)[..., :3]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--mark", default="398,276,56",
                    help="x,y,size of the mark on the coat")
    ap.add_argument("--no-mark", action="store_true")
    ap.add_argument("--as", dest="how", default="worn",
                    choices=("worn", "patch", "flat"),
                    help="worn: shaded into the cloth. patch: on a stitched "
                         "backing. flat: a plain stamp.")
    ap.add_argument("--tol", type=int, default=26,
                    help="how close to the corner colour still counts as ground")
    a = ap.parse_args()

    files = []
    for p in a.paths:
        files.extend(sorted(glob.glob(p)) or [p])
    x, y, s = (int(v) for v in a.mark.split(","))

    for p in files:
        bgr = cv2.imread(p, cv2.IMREAD_COLOR)
        if bgr is None:
            print("skip (unreadable)", p)
            continue
        fig = cut(bgr, a.tol)
        if not a.no_mark:
            m = mark_bgra(s)
            fig = (over(fig, m, x, y) if a.how == "flat"
                   else worn(fig, m, x, y, a.how == "patch"))
        stem = os.path.splitext(p)[0]
        cv2.imwrite(stem + "_cut.png", fig)
        cv2.imwrite(stem + "_white.png", on(fig, WHITE))
        cv2.imwrite(stem + "_dark.png", on(fig, DARK))
        print("wrote", stem + "_cut.png", "+ _white + _dark")


if __name__ == "__main__":
    main()
