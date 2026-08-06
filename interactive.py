"""Turn a user's rough drag into a precise region.

The user should not have to trace a bubble. They drag a loose rectangle over
it and we snap to the enclosing outline, exactly like the automatic detector
does — falling back to the raw rectangle when there is no bubble to snap to
(free-floating dialogue, sound effects, text over art).
"""
from __future__ import annotations

import cv2
import numpy as np

from .score import text_likeness
from .models import Page, RegionKind, TextRegion

INK = 128
PAD = 14           # look this far outside the drag for the true outline
CLOSE_PX = 2


def _fallback(img, x, y, w, h, kind, rid, exact: bool = False) -> TextRegion:
    """Build a region from the rectangle itself, with no outline to snap to.

    `exact` keeps the rectangle as the region's own box. Without it the box is
    pulled in to the ink inside the rectangle, which is right when a rectangle
    is a rough gesture at some writing and wrong when the rectangle IS the
    answer — a box the user just dragged to the size they wanted. Letting go of
    a resize and watching the box spring back onto the letters was this.
    """
    H, W = img.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    mask[y:y + h, x:x + w] = 255
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    glyph = ((gray <= INK) & (mask > 0)).astype(np.uint8) * 255
    ys, xs = np.nonzero(glyph)
    if xs.size:
        ink = (int(xs.min()), int(ys.min()),
               int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    else:
        ink = (x, y, w, h)
    bbox = (x, y, w, h) if exact else ink
    return TextRegion(
        id=rid, bbox=bbox, text_mask=glyph, bubble_mask=mask,
        bubble_bbox=(x, y, w, h), kind=kind,
        polygon=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        # Which way the ORIGINAL writing runs is a fact about the ink, not
        # about the rectangle somebody dragged round it.
        src_vertical=ink[3] > ink[2] * 1.15,
    )


def _free_mask(gray, mode):
    if mode == "outline":
        # interior enclosed by a dark outline
        ink = (gray <= INK).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * CLOSE_PX + 1,) * 2)
        return (1 - cv2.dilate(ink, k, iterations=1)).astype(np.uint8)
    # "white": a bright blob, for bubbles whose outline is broken or absent
    white = (gray >= 200).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(white, cv2.MORPH_CLOSE, k)


def _snap_at_pad(img, x, y, w, h, pad, mode="outline"):
    """Try to find the enclosure around the drag using a window of `pad`.

    Returns the outer contour in page coordinates, or None if the component
    containing the drag runs off the window — which means the window is still
    inside the bubble and we have to look further out.
    """
    H, W = img.shape[:2]
    cx0, cy0 = max(0, x - pad), max(0, y - pad)
    cx1, cy1 = min(W, x + w + pad), min(H, y + h + pad)
    crop = img[cy0:cy1, cx0:cx1]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    free = _free_mask(gray, mode)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, 4)
    ccy, ccx = (y + h // 2) - cy0, (x + w // 2) - cx0
    lbl = 0
    if 0 <= ccy < labels.shape[0] and 0 <= ccx < labels.shape[1]:
        lbl = int(labels[ccy, ccx])
    if lbl == 0:
        # centre landed on a glyph; take the largest fully-enclosed component
        best, best_a = 0, 0
        for i in range(1, n):
            bx, by, bw, bh, a = stats[i]
            if (bx > 0 and by > 0 and bx + bw < crop.shape[1]
                    and by + bh < crop.shape[0] and a > best_a):
                best, best_a = i, a
        lbl = best
    if lbl == 0:
        return None

    bx, by, bw, bh, area = stats[lbl]
    at_edge = (bx <= 0 or by <= 0
               or bx + bw >= crop.shape[1] or by + bh >= crop.shape[0])
    hit_page_edge = (cx0 == 0 and cy0 == 0 and cx1 == W and cy1 == H)
    if at_edge and not hit_page_edge:
        return None                       # window still inside the bubble

    comp = (labels == lbl).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    outer = max(cnts, key=cv2.contourArea) + np.array([[cx0, cy0]])

    # At a small window the search can latch onto a counter inside a glyph.
    # A real bubble contains the drag; a glyph hole does not.
    ob = cv2.boundingRect(outer)
    ox = max(0, min(x + w, ob[0] + ob[2]) - max(x, ob[0]))
    oy = max(0, min(y + h, ob[1] + ob[3]) - max(y, ob[1]))
    if (ox * oy) / max(1.0, w * h) < 0.6:
        return None
    return outer


def tighten_to_text(page: Page, region: TextRegion, pad: int = 6) -> TextRegion:
    """Shrink a region down to the typesetting it contains.

    Finding the text means finding the bubble first — glyphs routinely touch
    the outline, and at any single brightness threshold the interior tends to
    merge with the page around it. The snap path already solves that, and the
    region it returns carries the glyph bounds in `bbox`, so tightening is
    just: snap, then keep the text bounds rather than the bubble.
    """
    ink = region.text_mask
    if ink is None or not ink.any():
        return region

    ys, xs = np.nonzero(ink)
    H, W = ink.shape
    x0 = max(0, int(xs.min()) - pad); x1 = min(W - 1, int(xs.max()) + pad)
    y0 = max(0, int(ys.min()) - pad); y1 = min(H - 1, int(ys.max()) + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return region

    box = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    mask = np.zeros((H, W), np.uint8)
    mask[y0:y1 + 1, x0:x1 + 1] = 255
    region.bubble_mask = mask
    region.bubble_bbox = box
    region.bbox = box
    region.polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return region


def region_from_box(
    page: Page, x: int, y: int, w: int, h: int,
    kind: RegionKind = "bubble", rid: int = 0, snap: bool = True,
    tighten: bool = False,
) -> TextRegion:
    """Build a region from a user's rectangle.

    With snap=True we look for the bubble outline enclosing the rectangle.
    With snap=False the rectangle is used exactly as drawn — which is what a
    deliberate move or resize needs, since re-snapping there would just undo
    the edit.
    """
    img = page.image
    H, W = img.shape[:2]
    x = max(0, min(W - 2, int(x)));  y = max(0, min(H - 2, int(y)))
    w = max(2, min(W - x, int(w)));  h = max(2, min(H - y, int(h)))

    if tighten and kind == "bubble":
        # Look for a bubble INSIDE the drawn box and keep the typesetting in it.
        # Snapping cannot help here: the box already contains the bubble, so
        # the enclosing outline it would find is the panel.
        from .detect.classical import OutlineConfig, detect_within
        cfg = OutlineConfig()
        cfg.min_area_frac = 0.02      # limits are relative to the crop, not
        cfg.max_area_frac = 0.98      # the page, so they have to be relaxed
        inside = detect_within(page, (x, y, w, h), cfg)
        if inside:
            best = max(inside, key=lambda q: int((q.text_mask > 0).sum()))
            best.id = rid
            best.kind = kind
            return tighten_to_text(page, best)

    if not snap or kind != "bubble":
        # snap=False is the deliberate-edit path — a move, a resize, or "Box
        # as-is". The rectangle handed in is the whole of the answer, so it is
        # kept to the pixel. Snapping being off never meant "shrink it onto the
        # typesets instead", which is what it used to do.
        r = _fallback(img, x, y, w, h, kind, rid, exact=not snap)
        r.confidence = round(text_likeness(r), 3)
        return r

    # The user usually drags INSIDE the bubble, so a small window sees only
    # white. Grow the window until the enclosing outline closes around it.
    # Two strategies. "outline" finds the interior enclosed by the bubble's
    # dark border; "white" finds a bright blob, which is what works when the
    # border is broken or the bubble is borderless.
    size = max(w, h)
    # The window must be able to outgrow the BUBBLE, not just the drag — a
    # small mark dragged inside a big bubble used to run out of pads and
    # silently fall back to the raw rectangle. The leak/containment checks
    # below make the larger windows safe.
    pads = [max(8, int(size * f)) for f in (0.25, 0.6, 1.2, 2.5, 5.0, 10.0)]
    outer = None
    for mode in ("outline", "white"):
        for pad in pads:
            outer = _snap_at_pad(img, x, y, w, h, pad, mode)
            if outer is not None:
                break
        if outer is not None:
            break

    if outer is None:
        r = _fallback(img, x, y, w, h, kind, rid)
        r.confidence = round(text_likeness(r), 3)
        return r

    bb = cv2.boundingRect(outer)
    # The user drags a small mark inside a big bubble, so an area ratio is the
    # wrong test. What matters is that the snap CONTAINS the drag and has not
    # leaked out into the page.
    ox = max(0, min(x + w, bb[0] + bb[2]) - max(x, bb[0]))
    oy = max(0, min(y + h, bb[1] + bb[3]) - max(y, bb[1]))
    contained = (ox * oy) / max(1.0, w * h)
    leaked = (bb[2] * bb[3]) > 0.35 * (W * H)
    if contained < 0.75 or leaked or bb[2] * bb[3] < 0.5 * w * h:
        r = _fallback(img, x, y, w, h, kind, rid)
        r.confidence = round(text_likeness(r), 3)
        return r

    bubble = np.zeros((H, W), np.uint8)
    cv2.drawContours(bubble, [outer], -1, 255, cv2.FILLED)
    full_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    glyph = ((full_gray <= INK) & (bubble > 0)).astype(np.uint8) * 255

    ys, xs = np.nonzero(glyph)
    if xs.size == 0:
        r = _fallback(img, x, y, w, h, kind, rid)
        r.confidence = round(text_likeness(r), 3)
        return r
    tb = (int(xs.min()), int(ys.min()),
          int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

    r = TextRegion(
        id=rid, bbox=tb, text_mask=glyph, bubble_mask=bubble,
        bubble_bbox=(int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])),
        polygon=outer.reshape(-1, 2).tolist(),
        kind=kind, src_vertical=tb[3] > tb[2] * 1.15,
    )
    r.confidence = round(text_likeness(r), 3)
    return r


def renumber(page: Page) -> None:
    from .order import assign_order
    for i, r in enumerate(page.regions):
        r.id = i
    assign_order(page)
