"""A webtoon strip, put back together and cut where it should have been.

A manhwa chapter does not arrive as pages. It is drawn as ONE image, hundreds
of thousands of pixels tall, and the site that serves it slices that image into
tiles of a fixed height so a browser can stream them. The slicer counts pixels.
It has never looked at the artwork.

lee's chapter 1, measured: **690 x 167,617**, cut into 105 tiles of exactly
1600px. Of the 104 cuts, **86 land on ink, 63 go through a speech balloon, and
38 go through the typesetting itself** - one of them straight across the middle of
지구인 용사 소환!, leaving half the glyph heights on one file and half on the
next. Neither half is readable. The reader cannot read it, the cleaner would
have to erase half a word on one page and half on another, and the English has
nowhere to go.

So the tiles are not pages and must not be treated as pages. This module joins
them back into the strip they came from and cuts it again at the **gutters** -
the rows where the artist drew nothing - which is what a typesetter does by hand
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

from . import imgio

# A row is a gutter when nothing is drawn on it. Both tests matter: `std`
# catches texture and typesetting, and the range catches a hard edge in an
# otherwise even row - a panel border crossing an empty margin.
FLAT_STD = 4.0
FLAT_RANGE = 14

# A single flat row is a coincidence - a scanline between two panels of the
# same tone. A band of them is a gutter.
MIN_GUTTER = 6

# What a page should come out at, and the height past which one is no longer
# worth having. The ceiling is not tidiness: the detector letterboxes a whole
# page into one 1024px square, so on a 10,000px page the typesetting arrives
# about 70px tall and it starts missing text.
#
# It is a LIMIT, not a wall. A page runs on past it to reach a real gutter,
# however far that is, and is reported as having run over. lee, on a page cut
# at the ceiling: *"when it reaches teh max lenght it still crops teh text box,
# if posiboe can you have a way of not to do that"*. Nothing is worth cutting
# through the words: a page too tall is a page you can still read, and a
# balloon in halves is not.
TARGET_H = 2400
MAX_H = 6000

# How much taller or shorter than the target a page may be while still counting
# as "near enough" - the window a gutter is looked for in.
NEAR = (0.45, 1.9)


def _rows(path: str) -> np.ndarray:
    """min, max and std of every row of one tile, as float32."""
    g = imgio.imread(path, cv2.IMREAD_GRAYSCALE)
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
    """The middle row of every band of empty rows - the places it may be cut."""
    if not len(flat):
        return []
    d = np.diff(np.concatenate([[0], flat.view(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [int((a + b) // 2) for a, b in zip(starts, ends) if b - a >= min_band]


def plan_cuts(flat: np.ndarray, target: int = TARGET_H,
              ceiling: int = MAX_H) -> tuple[list[int], list[int]]:
    """Where to cut the strip. Returns the cut rows, and which pages ran over.

    Walks down the strip taking the gutter NEAREST the target each time, not
    the first one past it: "first past" overshoots badly where gutters are
    sparse, and a chapter of 3,500px pages when you asked for 2,400 is not what
    was asked for.

    **Every cut is a gutter.** Where the window holds none, the page runs on to
    the next one however far away it is, and past the ceiling if that is what
    it takes; where there is no gutter left at all, the rest of the strip is
    one page. Nothing is ever cut through the artwork.

    It used to cut at the quietest row it could find inside the ceiling, and
    report the page. lee: *"when it reaches teh max lenght it still crops teh
    text box, if posiboe can you have a way of not to do that"*. The quietest
    row available in a panel of solid artwork is still the middle of a balloon,
    and the reason the strip is being re-cut in the first place is that
    somebody else's slicer did exactly that.

    So the ceiling is a limit rather than a wall, and going past it is
    something you are told about instead of something the page pays for. The
    price is real and it is smaller: a very tall page reaches the detector
    shrunk down, because it letterboxes the whole page into 1024px, so boxes on
    it are harder to find. A page you can still read beats half a sentence.
    """
    H = len(flat)
    if H == 0:
        return [], []
    marks = np.array(gutters(flat), dtype=int)
    cuts, over = [0], []
    while H - cuts[-1] > target * NEAR[1]:
        at = cuts[-1]
        lo, hi = at + int(target * NEAR[0]), at + int(target * NEAR[1])
        near = marks[(marks > lo) & (marks < hi)] if len(marks) else np.array([])
        if len(near):
            cuts.append(int(near[np.argmin(abs(near - (at + target)))]))
            continue
        # Nothing in the window. Take the next gutter there is, wherever it is.
        after = marks[marks > hi] if len(marks) else np.array([])
        if not len(after):
            break                  # none left: everything below here is one page
        cuts.append(int(after[0]))
        if after[0] - at > ceiling:
            over.append(int(after[0]))
    cuts.append(H)
    # The tail is normally a short page and not worth mentioning. After a break
    # above it can be most of the chapter, and that is worth mentioning.
    if len(cuts) > 1 and H - cuts[-2] > ceiling:
        over.append(H)
    return cuts, over


def looks_sliced(sizes: list[tuple[int, int]]) -> bool:
    """Is this a strip somebody cut up, rather than a book of pages?

    Deliberately narrow, because being wrong here rearranges somebody's
    chapter. All four have to hold:

    * more than a handful of images - three tiles is a three-page short;
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


# ------------------------------------------------- sliced, but not evenly

# A seam is a place where one tile ends and the next begins. Across a cut
# through one picture, the last row of a tile and the first row of the next
# are neighbouring rows of the same drawing and agree almost pixel for pixel;
# across two separate pages they are two margins (blank, and told apart
# below) or two unrelated pictures (and disagree). `SEAM_MATCH` is the mean
# absolute difference, in grey levels, under which two rows are one picture;
# `SEAM_BUSY` is the standard deviation a row needs to count as drawn on at
# all - a blank margin against a blank margin says nothing either way.
SEAM_MATCH = 16.0
SEAM_BUSY = 20.0
#: How many seams have to run through a drawing, continuously, before a
#: chapter of uneven tiles is called a sliced strip. Two is a coincidence a
#: book of pages could produce with bleed; four is not.
SEAMS_NEEDED = 4


def _edge_rows(path: str) -> tuple[np.ndarray, np.ndarray] | None:
    g = imgio.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None or g.shape[0] < 4:
        return None
    # Two rows averaged on each side: a JPEG's last row alone carries block
    # noise that a single-row compare mistakes for a different picture.
    return g[:2].astype(np.float32).mean(0), g[-2:].astype(np.float32).mean(0)


def seams_through_ink(paths: list[str]) -> int:
    """How many tile boundaries are cuts through one continuous drawing."""
    edges = [_edge_rows(p) for p in paths]
    n = 0
    for a, b in zip(edges[:-1], edges[1:]):
        if a is None or b is None or a[1].shape != b[0].shape:
            continue
        bottom, top = a[1], b[0]
        if bottom.std() < SEAM_BUSY or top.std() < SEAM_BUSY:
            continue
        if float(np.abs(bottom - top).mean()) < SEAM_MATCH:
            n += 1
    return n


def looks_sliced_unevenly(sizes: list[tuple[int, int]], paths: list[str]) -> bool:
    """A strip cut into tiles of DIFFERENT heights.

    `looks_sliced` reads the signature of a slicer counting pixels: every tile
    the same height. Not every site's slicer counts pixels. The manhua that
    lee's `Manhua/` folder holds came as 41 tiles, all 800 wide, 828 to 2350
    tall - and the seams still ran through balloons, through the middle of a
    line of dialogue, and through a painted 符. Uneven tiles are not evidence
    of pages; they are evidence of a slicer with a different rule.

    So the sizes are asked for what they can still say - one width, many
    tiles, tall - and the pictures are asked the rest: do the seams run
    through drawings, continuously? A book of pages has margins at its seams.
    A strip has whatever the slicer happened to hit.
    """
    if len(sizes) < 6 or len(sizes) != len(paths):
        return False
    if len({w for _h, w in sizes}) != 1:
        return False
    tall = sum(1 for h, w in sizes if h > w * 1.2)
    if tall < len(sizes) * 0.8:
        return False
    return seams_through_ink(paths) >= SEAMS_NEEDED


def restitch(paths: list[str], out_dir: str, stem: str = "page",
             target: int = TARGET_H, ceiling: int = MAX_H,
             ext: str = ".png") -> dict:
    """Join the tiles and write them back out cut at the gutters.

    The output is written straight from the source tiles a slice at a time, so
    the joined strip never exists in memory.
    """
    paths = [p for p in paths if os.path.isfile(p)]
    if len(paths) < 2:
        return {"pages": [], "over": 0, "cuts": 0}
    heights = []
    for p in paths:
        g = imgio.imread(p, cv2.IMREAD_GRAYSCALE)
        heights.append(0 if g is None else g.shape[0])
    flat = row_profile(paths)
    cuts, over = plan_cuts(flat, target, ceiling)
    if len(cuts) < 2:
        return {"pages": [], "over": 0, "cuts": 0}

    # where each tile starts in the joined strip
    starts, run = [], 0
    for h in heights:
        starts.append(run)
        run += h
    os.makedirs(out_dir, exist_ok=True)

    written, over_pages = [], []
    for n, (a, b) in enumerate(zip(cuts[:-1], cuts[1:]), 1):
        if b <= a:
            continue
        rows = []
        for path, s, h in zip(paths, starts, heights):
            e = s + h
            if e <= a or s >= b:
                continue
            im = imgio.imread(path)
            if im is None:
                continue
            rows.append(im[max(0, a - s):min(h, b - s)])
        if not rows:
            continue
        page = np.vstack(rows)
        name = f"{stem}{n:03d}{ext}"
        imgio.imwrite(os.path.join(out_dir, name), page)
        written.append(name)
        if b in over:
            over_pages.append(name)
    return {"pages": written, "over": len(over_pages),
            "over_pages": over_pages, "cuts": len(cuts) - 2,
            "height": int(len(flat))}
