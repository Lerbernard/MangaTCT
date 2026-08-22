"""Reading order.

Japanese manga reads right-to-left, top-to-bottom. Korean manhwa and Chinese
manhua read LEFT-to-right, like a western comic. Getting this backwards
scrambles every page, so it is a parameter rather than an assumption.

Recursive XY-cut. Slanted panel gutters defeat axis-aligned cuts, so we retry
the search over a few rotations of the coordinate frame before falling back to
a sort.
"""
from __future__ import annotations

import math
from typing import Sequence

Box = tuple[float, float, float, float]  # x, y, w, h

ROTATIONS = (0.0, -6.0, 6.0, -12.0, 12.0, -18.0, 18.0, -24.0, 24.0)
MIN_GAP = 4.0  # px; smaller gaps are noise, not gutters

# Panel-border detection (only used when a page image is supplied). A real
# manga panel gutter carries a solid black border line; empty space INSIDE one
# panel (between two bubbles, with artwork around them) does not. A gap backed
# by such a line is taken as a panel boundary BEFORE the normal rows-first
# search, so a tall panel beside two stacked panels reads right-column-first
# instead of being sliced into rows. Conservative on purpose: only a nearly
# solid, region-spanning line qualifies, so pages without clear borders order
# exactly as they did before this was added.
BORDER_DARK = 0.92     # fraction of the line that must be ink (near-solid)
BORDER_HALF = 12       # px to each side of the cut to hunt for the line
_INK = 80              # <= this grey value counts as black ink


def _border_v(gray, x: float, y0: float, y1: float) -> float:
    x0 = max(0, int(x - BORDER_HALF)); x1 = min(gray.shape[1], int(x + BORDER_HALF))
    y0 = max(0, int(y0)); y1 = min(gray.shape[0], int(y1))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(((gray[y0:y1, x0:x1] < _INK).mean(axis=0)).max())


def _border_h(gray, y: float, x0: float, x1: float) -> float:
    y0 = max(0, int(y - BORDER_HALF)); y1 = min(gray.shape[0], int(y + BORDER_HALF))
    x0 = max(0, int(x0)); x1 = min(gray.shape[1], int(x1))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(((gray[y0:y1, x0:x1] < _INK).mean(axis=1)).max())


def _rotate_boxes(boxes: Sequence[Box], deg: float) -> list[Box]:
    """Rotate box centres about the origin, keeping w/h. Approximate but
    sufficient: we only need to find a separating axis, not exact geometry."""
    if deg == 0.0:
        return list(boxes)
    t = math.radians(deg)
    ct, st = math.cos(t), math.sin(t)
    out = []
    for (x, y, w, h) in boxes:
        cx, cy = x + w / 2, y + h / 2
        rx, ry = cx * ct - cy * st, cx * st + cy * ct
        # conservative axis-aligned envelope after rotation
        nw = abs(w * ct) + abs(h * st)
        nh = abs(w * st) + abs(h * ct)
        out.append((rx - nw / 2, ry - nh / 2, nw, nh))
    return out


def _find_gaps(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Clear gaps along one axis as (width, midpoint), widest first - the
    widest gutter is the likeliest real panel boundary."""
    if len(intervals) < 2:
        return []
    ivs = sorted(intervals)
    gaps: list[tuple[float, float]] = []
    reach = ivs[0][1]
    for lo, hi in ivs[1:]:
        if lo - reach > MIN_GAP:
            gaps.append((lo - reach, (reach + lo) / 2))
        reach = max(reach, hi)
    gaps.sort(reverse=True)
    return gaps


def _split(idxs: list[int], boxes: list[Box], axis: int, at: float):
    """axis 0 = x (vertical cut), 1 = y (horizontal cut)."""
    lo, hi = [], []
    for i in idxs:
        c = boxes[i][axis] + boxes[i][axis + 2] / 2
        (lo if c < at else hi).append(i)
    return lo, hi


def _xycut(idxs: list[int], rot_boxes: list[list[Box]], rtl: bool,
           gray=None) -> list[int]:
    if len(idxs) <= 1:
        return list(idxs)

    # 0. PANEL BORDER (only with a page image, unrotated frame). A gap with a
    #    solid black border line through it is a real panel gutter and is taken
    #    before the rows-first search below, so the right column of a page is
    #    finished before crossing to a tall neighbouring panel. Skipped
    #    entirely when no image is supplied, so behaviour is unchanged then.
    if gray is not None:
        base = rot_boxes[0]
        bxs = [base[i][0] for i in idxs] + [base[i][0] + base[i][2] for i in idxs]
        bys = [base[i][1] for i in idxs] + [base[i][1] + base[i][3] for i in idxs]
        rx0, rx1, ry0, ry1 = min(bxs), max(bxs), min(bys), max(bys)
        border: list[tuple[float, int, float]] = []   # (width, axis, at)
        for w, gx in _find_gaps([(base[i][0], base[i][0] + base[i][2])
                                 for i in idxs]):
            if _border_v(gray, gx, ry0, ry1) >= BORDER_DARK:
                border.append((w, 0, gx))
        for w, gy in _find_gaps([(base[i][1], base[i][1] + base[i][3])
                                 for i in idxs]):
            if _border_h(gray, gy, rx0, rx1) >= BORDER_DARK:
                border.append((w, 1, gy))
        for w, axis, at in sorted(border, reverse=True):
            lo, hi = _split(idxs, base, axis, at)
            if lo and hi:
                if axis == 0:
                    first, second = (hi, lo) if rtl else (lo, hi)
                else:
                    first, second = lo, hi          # top before bottom
                return (_xycut(first, rot_boxes, rtl, gray)
                        + _xycut(second, rot_boxes, rtl, gray))

    # 1. HORIZONTAL cuts, searched across EVERY rotation before any vertical
    #    cut is considered - rows before columns is how these pages read.
    #    (Vertical used to fire at 0° before a slanted row gutter was ever
    #    tried at ±6°, which split diagonal layouts into columns and read a
    #    bottom panel before the top panel had finished.)
    cand: list[tuple[float, int, float]] = []
    for ri, rb in enumerate(rot_boxes):
        for w, gy in _find_gaps([(rb[i][1], rb[i][1] + rb[i][3])
                                 for i in idxs]):
            cand.append((w, ri, gy))
    for w, ri, gy in sorted(cand, reverse=True):
        top, bottom = _split(idxs, rot_boxes[ri], 1, gy)
        if top and bottom:
            return (_xycut(top, rot_boxes, rtl, gray)
                    + _xycut(bottom, rot_boxes, rtl, gray))

    # 2. vertical cut. Manga takes the RIGHT block first; manhwa and
    #    manhua take the left, like a western comic.
    cand = []
    for ri, rb in enumerate(rot_boxes):
        for w, gx in _find_gaps([(rb[i][0], rb[i][0] + rb[i][2])
                                 for i in idxs]):
            cand.append((w, ri, gx))
    for w, ri, gx in sorted(cand, reverse=True):
        left, right = _split(idxs, rot_boxes[ri], 0, gx)
        if left and right:
            first, second = (right, left) if rtl else (left, right)
            return (_xycut(first, rot_boxes, rtl, gray)
                    + _xycut(second, rot_boxes, rtl, gray))

    # 3. No clean cut anywhere: overlapping / heavily diagonal layout.
    #    Band the boxes into visual rows by vertical position and read each
    #    band across - much closer to how a human resolves a messy page than
    #    the old rightmost-edge sort.
    base = rot_boxes[0]
    order = sorted(idxs, key=lambda i: base[i][1] + base[i][3] / 2)
    heights = sorted(base[i][3] for i in idxs)
    med_h = heights[len(heights) // 2] or 1.0
    bands: list[tuple[float, list[int]]] = []
    for i in order:
        yc = base[i][1] + base[i][3] / 2
        if bands and yc - bands[-1][0] <= 0.6 * med_h:
            bands[-1][1].append(i)
        else:
            bands.append((yc, [i]))
    out: list[int] = []
    for _, band in bands:
        band.sort(key=lambda i: (-(base[i][0] + base[i][2]), base[i][1])
                  if rtl else (base[i][0], base[i][1]))
        out += band
    return out


def reading_order(boxes: Sequence[Box], rtl: bool = True, gray=None) -> list[int]:
    """Indices of `boxes` in reading order.

    rtl=True for Japanese manga, rtl=False for manhwa, manhua and western
    comics. `gray` is an optional grayscale page image; when given, real panel
    borders are used to keep the reading order inside panels (see _xycut).
    """
    boxes = list(boxes)
    if not boxes:
        return []
    rot_boxes = [_rotate_boxes(boxes, d) for d in ROTATIONS]
    return _xycut(list(range(len(boxes))), rot_boxes, rtl, gray)


def _order_box(r) -> Box:
    """The box a region occupies for ORDERING: the union of its text box and
    its bubble. Tight text boxes invent gaps that the bubbles themselves
    close, and a phantom row gap between two tall side-by-side panels reads
    the page in the wrong sequence."""
    bx = r.bbox
    bb = getattr(r, "bubble_bbox", None)
    if not bb:
        return bx
    x0, y0 = min(bx[0], bb[0]), min(bx[1], bb[1])
    x1 = max(bx[0] + bx[2], bb[0] + bb[2])
    y1 = max(bx[1] + bx[3], bb[1] + bb[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _page_gray(page):
    """Grayscale page image for panel-border detection, or None. A blank
    placeholder image (the editor builds one when it only re-orders existing
    boxes) is uniform, which would read as border everywhere - reject it so
    ordering falls back to the geometry-only path."""
    img = getattr(page, "image", None)
    if img is None or getattr(img, "size", 0) == 0 or getattr(img, "ndim", 0) < 2:
        return None
    if min(img.shape[:2]) < 8:
        return None
    try:
        import cv2
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    except Exception:
        return None
    if float(g.max()) - float(g.min()) < 20:     # uniform -> not a real page
        return None
    return g


def assign_order(page, rtl: bool = True) -> None:
    """Order panels, then regions within each panel. Sets region.order in place."""
    from .models import Page  # noqa: F401

    regions = page.regions
    if not regions:
        return

    gray = _page_gray(page)

    if page.panels:
        panel_seq = reading_order(page.panels, rtl, gray)
        for rank, pi in enumerate(panel_seq):
            for r in regions:
                if r.panel_id == pi:
                    r._prank = rank  # type: ignore[attr-defined]
        for r in regions:
            if not hasattr(r, "_prank"):
                r._prank = len(panel_seq)  # type: ignore[attr-defined]
    else:
        for r in regions:
            r._prank = 0  # type: ignore[attr-defined]

    counter = 0
    for prank in sorted({r._prank for r in regions}):  # type: ignore[attr-defined]
        grp = [r for r in regions if r._prank == prank]  # type: ignore[attr-defined]
        for i in reading_order([_order_box(r) for r in grp], rtl, gray):
            grp[i].order = counter
            counter += 1

    for r in regions:
        delattr(r, "_prank")


def assign_panels(page, iou_parent: float = 0.5) -> None:
    """Attach each region to the panel that contains most of it."""
    for r in page.regions:
        best, best_frac = None, 0.0
        rx, ry, rw, rh = r.bbox
        for pi, (px, py, pw, ph) in enumerate(page.panels):
            ox = max(0, min(rx + rw, px + pw) - max(rx, px))
            oy = max(0, min(ry + rh, py + ph) - max(ry, py))
            frac = (ox * oy) / max(1, rw * rh)
            if frac > best_frac:
                best, best_frac = pi, frac
        r.panel_id = best if best_frac >= iou_parent else None
