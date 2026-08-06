"""A webtoon strip, put back together and cut where it should have been.

A manhwa chapter does not arrive as pages. It is drawn as ONE image, hundreds
of thousands of pixels tall, and the site that serves it slices that image into
tiles of a fixed height so a browser can stream them. The slicer counts pixels.
It has never looked at the artwork.

lee's chapter 1, measured: **690 x 167,617**, cut into 105 tiles of exactly
1600px. Of the 104 cuts, **86 land on ink, 63 go through a speech balloon, and
38 go through the typesetting itself** — one of them straight across the middle of
지구인 용사 소환!, leaving half the glyph heights on one file and half on the
next. Neither half is readable. The reader cannot read it, the cleaner would
have to erase half a word on one page and half on another, and the English has
nowhere to go.

So the tiles are not pages and must not be treated as pages. This module joins
them back into the strip they came from and cuts it again at the **gutters** —
the rows where the artist drew nothing — which is what a typesetter does by hand
before starting.

On that chapter: 81 gutters, and cutting only at them gives 43 pages with
**zero** cuts through anything.

Nothing here loads the whole strip. A 690x167,617 image is 347MB in memory and
a longer one is worse, so the row profile is built tile by tile and each output
page is written by copying the slices it needs. Peak memory is one tile plus
one page.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

# A row is a gutter when nothing is drawn on it. Both tests matter: `std`
# catches texture and typesetting, and the range catches a hard edge in an
# otherwise even row — a panel border crossing an empty margin.
FLAT_STD = 4.0
FLAT_RANGE = 14

# A single flat row is a coincidence — a scanline between two panels of the
# same tone. A band of them is a gutter.
MIN_GUTTER = 6

# What a page should come out at, and the height past which one is no longer
# worth having. The ceiling is not tidiness: the detector letterboxes a whole
# page into one 1024px square, so on a 10,000px page the typesetting arrives
# about 70px tall and it starts missing text. Where no gutter exists inside the
# ceiling the strip is cut at the QUIETEST row instead, and that page is
# reported so it can be looked at.
TARGET_H = 2400
MAX_H = 6000

# How much taller or shorter than the target a page may be while still counting
# as "near enough" — the window a gutter is looked for in.
NEAR = (0.45, 1.9)


def _rows(path: str) -> np.ndarray:
    """min, max and std of every row of one tile, as float32."""
    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return np.zeros((0, 3), np.float32)
    return np.stack([g.min(1), g.max(1), g.std(1)], 1).astype(np.float32)


def row_profile(paths: list[str]) -> np.ndarray:
    """One row per row of the joined strip: True where nothing is drawn."""
    parts = [_rows(p) for p in paths]
    parts = [x for x in parts if len(x)]
    if not parts:
        return np.zeros(0, bool)
    r = np.vstack(parts)
    return (r[:, 2] < FLAT_STD) & ((r[:, 1] - r[:, 0]) < FLAT_RANGE)


def gutters(flat: np.ndarray, min_band: int = MIN_GUTTER) -> list[int]:
    """The middle row of every band of empty rows — the places it may be cut."""
    if not len(flat):
        return []
    d = np.diff(np.concatenate([[0], flat.view(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [int((a + b) // 2) for a, b in zip(starts, ends) if b - a >= min_band]


def quietest(flat: np.ndarray, lo: int, hi: int) -> int:
    """The least-bad row to cut through when there is no gutter to use.

    Least-bad is the middle of the longest run of empty rows in the window,
    even if that run is shorter than a gutter — a two-pixel gap between panels
    is not a gutter but it is a far better place to cut than the middle of a
    face. With nothing empty at all it comes back with the middle of the
    window, and the caller flags the page.
    """
    lo, hi = max(0, lo), min(len(flat), hi)
    if hi <= lo:
        return hi
    win = flat[lo:hi]
    if not win.any():
        return (lo + hi) // 2
    d = np.diff(np.concatenate([[0], win.view(np.int8), [0]]))
    a, b = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    k = int(np.argmax(b - a))
    return lo + int((a[k] + b[k]) // 2)


def plan_cuts(flat: np.ndarray, target: int = TARGET_H,
              ceiling: int = MAX_H) -> tuple[list[int], list[int]]:
    """Where to cut the strip. Returns the cut rows and which ones hit ink.

    Walks down the strip taking the gutter NEAREST the target each time, not
    the first one past it: "first past" overshoots badly where gutters are
    sparse, and a chapter of 3,500px pages when you asked for 2,400 is not what
    was asked for. Where the window holds no gutter at all the page is allowed
    to run on to the next one — up to the ceiling, and then it is cut at the
    quietest row available and reported.
    """
    H = len(flat)
    if H == 0:
        return [], []
    marks = np.array(gutters(flat), dtype=int)
    cuts, forced = [0], []
    while H - cuts[-1] > target * NEAR[1]:
        at = cuts[-1]
        lo, hi = at + int(target * NEAR[0]), at + int(target * NEAR[1])
        near = marks[(marks > lo) & (marks < hi)] if len(marks) else np.array([])
        if len(near):
            cuts.append(int(near[np.argmin(abs(near - (at + target)))]))
            continue
        # nothing in the window: run on to the next gutter, if one is close
        # enough to still be a usable page
        after = marks[marks > hi] if len(marks) else np.array([])
        if len(after) and after[0] - at <= ceiling:
            cuts.append(int(after[0]))
            continue
        cut = quietest(flat, at + int(target * 0.7), at + ceiling)
        cuts.append(int(cut))
        forced.append(int(cut))
    cuts.append(H)
    return cuts, forced


def looks_sliced(sizes: list[tuple[int, int]]) -> bool:
    """Is this a strip somebody cut up, rather than a book of pages?

    Deliberately narrow, because being wrong here rearranges somebody's
    chapter. All four have to hold:

    * more than a handful of images — three tiles is a three-page short;
    * every one the same WIDTH, which a scan of paper pages never is;
    * all but the last the same HEIGHT, to the pixel. That is the signature of
      a machine slicing by count. Pages drawn as pages differ by a few pixels
      at least, and usually by a lot;
    * and taller than they are wide. A slice of a webtoon is a tall ribbon.

    The last tile is exempt from the height rule: it is the remainder.
    """
    if len(sizes) < 6:
        return False
    ws = {w for _h, w in sizes}
    if len(ws) != 1:
        return False
    hs = [h for h, _w in sizes]
    if len(set(hs[:-1])) != 1:
        return False
    if hs[-1] > hs[0]:
        return False
    return hs[0] > sizes[0][1] * 1.2


def restitch(paths: list[str], out_dir: str, stem: str = "page",
             target: int = TARGET_H, ceiling: int = MAX_H,
             ext: str = ".png") -> dict:
    """Join the tiles and write them back out cut at the gutters.

    The output is written straight from the source tiles a slice at a time, so
    the joined strip never exists in memory.
    """
    paths = [p for p in paths if os.path.isfile(p)]
    if len(paths) < 2:
        return {"pages": [], "forced": 0, "cuts": 0}
    heights = []
    for p in paths:
        g = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        heights.append(0 if g is None else g.shape[0])
    flat = row_profile(paths)
    cuts, forced = plan_cuts(flat, target, ceiling)
    if len(cuts) < 2:
        return {"pages": [], "forced": 0, "cuts": 0}

    # where each tile starts in the joined strip
    starts, run = [], 0
    for h in heights:
        starts.append(run)
        run += h
    os.makedirs(out_dir, exist_ok=True)

    written, forced_pages = [], []
    for n, (a, b) in enumerate(zip(cuts[:-1], cuts[1:]), 1):
        if b <= a:
            continue
        rows = []
        for path, s, h in zip(paths, starts, heights):
            e = s + h
            if e <= a or s >= b:
                continue
            im = cv2.imread(path)
            if im is None:
                continue
            rows.append(im[max(0, a - s):min(h, b - s)])
        if not rows:
            continue
        page = np.vstack(rows)
        name = f"{stem}{n:03d}{ext}"
        cv2.imwrite(os.path.join(out_dir, name), page)
        written.append(name)
        if b in forced:
            forced_pages.append(name)
    return {"pages": written, "forced": len(forced_pages),
            "forced_pages": forced_pages, "cuts": len(cuts) - 2,
            "height": int(len(flat))}
