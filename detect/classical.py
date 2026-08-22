"""Zero-weights bubble detector.

Finds speech bubbles as compact white blobs that enclose dark glyphs. This
exists so the pipeline runs end-to-end on day one without training or
downloading anything. It handles clean white bubbles well and misses
free-floating text, bubbles over dark art, and irregular burst bubbles.
Swap in detect.yolo once you have weights; the interface is identical.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..models import Page, TextRegion


class ClassicalConfig:
    white_thresh = 200        # pixel >= this counts as bubble interior
    ink_thresh = 128          # pixel <= this counts as glyph ink
    min_area_frac = 0.0008    # of page area
    max_area_frac = 0.15
    min_solidity = 0.80       # blob_area / convex_hull_area
    min_fill = 0.55           # blob_area / bbox_area
    min_glyphs = 2            # holes that look like text
    min_ink_frac = 0.015      # ink area / bubble area
    max_ink_frac = 0.45
    border_margin = 3         # blobs touching the page edge are background
    text_pad = 2
    min_interior_brightness = 190
    max_interior_std = 50
    max_edge_density = 0.018  # see _edge_density: art has drawn edges, paper has none


def _glyph_holes(hier, idx, contours, blob_area, cfg):
    """Child contours of blob `idx` that plausibly are glyphs.

    Returns (count, largest_area). The caller accepts either several glyph
    holes, or a single SUBSTANTIAL one - a bubble holding nothing but 「!?」
    or 「…」 is one connected shape, and demanding two glyphs silently
    dropped every such bubble.
    """
    n, biggest = 0, 0.0
    child = hier[0][idx][2]
    while child != -1:
        a = cv2.contourArea(contours[child])
        if 4 <= a <= blob_area * 0.35:
            n += 1
            biggest = max(biggest, a)
        child = hier[0][child][0]
    return n, biggest


def _enough_glyphs(n: int, biggest: float, need: int) -> bool:
    return n >= need or (n == 1 and biggest >= 15)


def detect(page: Page, cfg: ClassicalConfig | None = None) -> list[TextRegion]:
    cfg = cfg or ClassicalConfig()
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape
    page_area = H * W

    white = (gray >= cfg.white_thresh).astype(np.uint8) * 255
    # close small gaps so anti-aliased glyph edges don't fragment the interior
    white = cv2.morphologyEx(
        white, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )

    contours, hier = cv2.findContours(white, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return []

    regions: list[TextRegion] = []
    rid = 0
    for i, cnt in enumerate(contours):
        if hier[0][i][3] != -1:       # only outer contours
            continue
        area = cv2.contourArea(cnt)
        if not (page_area * cfg.min_area_frac <= area <= page_area * cfg.max_area_frac):
            continue

        x, y, w, h = cv2.boundingRect(cnt)
        if (x <= cfg.border_margin or y <= cfg.border_margin
                or x + w >= W - cfg.border_margin or y + h >= H - cfg.border_margin):
            continue                   # page background / margin
        if area / max(1.0, w * h) < cfg.min_fill:
            continue
        hull = cv2.convexHull(cnt)
        if area / max(1.0, cv2.contourArea(hull)) < cfg.min_solidity:
            continue
        ng, biggest = _glyph_holes(hier, i, contours, area, cfg)
        if not _enough_glyphs(ng, biggest, cfg.min_glyphs):
            continue

        bubble_mask = np.zeros((H, W), np.uint8)
        cv2.drawContours(bubble_mask, [cnt], -1, 255, cv2.FILLED)

        ink = ((gray <= cfg.ink_thresh) & (bubble_mask > 0)).astype(np.uint8) * 255
        ink_frac = float(ink.sum() / 255) / area
        if not (cfg.min_ink_frac <= ink_frac <= cfg.max_ink_frac):
            continue

        if not _interior_ok(gray, bubble_mask, ink, cfg):
            continue
        if _edge_density(gray, bubble_mask, ink) > cfg.max_edge_density:
            continue

        ys, xs = np.nonzero(ink)
        if xs.size == 0:
            continue
        tx0, tx1 = max(0, xs.min() - cfg.text_pad), min(W - 1, xs.max() + cfg.text_pad)
        ty0, ty1 = max(0, ys.min() - cfg.text_pad), min(H - 1, ys.max() + cfg.text_pad)
        tw, th = tx1 - tx0 + 1, ty1 - ty0 + 1

        regions.append(
            TextRegion(
                id=rid,
                bbox=(int(tx0), int(ty0), int(tw), int(th)),
                text_mask=ink,
                bubble_mask=bubble_mask,
                bubble_bbox=(int(x), int(y), int(w), int(h)),
                polygon=cnt.reshape(-1, 2).tolist(),
                kind="bubble",
                src_vertical=th > tw * 1.15,
            )
        )
        rid += 1

    return regions


class OutlineConfig:
    """Detect the bubble's dark OUTLINE and take the region it encloses.

    The white-blob method fails whenever a bubble's interior connects to the
    white page background - the merged blob then touches the page border and is
    rejected. That is the dominant failure mode on many chapters. A closed dark
    outline still separates interior from background, so this method recovers
    them.
    """

    ink_thresh = 128
    close_px = 2              # bridge anti-aliasing gaps in thin outlines
    min_area_frac = 0.0008
    max_area_frac = 0.15
    min_solidity = 0.62       # glyph holes reduce measured area, so looser
    min_fill = 0.42
    min_ink_frac = 0.010
    max_ink_frac = 0.55
    min_glyph_components = 2
    border_margin = 3
    text_pad = 2
    # A bubble interior is a near-uniform light fill. A panel full of artwork
    # is neither, which is how a whole panel ends up detected as one bubble.
    min_interior_brightness = 190
    max_interior_std = 50
    max_edge_density = 0.018  # see _edge_density
    # A balloon drawn as two lobes holds two speeches, one written in each, and
    # they are not one speech. See `_neck_split` for what has to be true before
    # a dent in the outline is believed to be a neck.
    neck_depth_frac = 0.10    # a dent this deep, against the balloon's short side
    neck_lobe_frac = 0.18     # each lobe is this much of the balloon
    neck_text_frac = 0.15     # ... and holds this much of the writing
    neck_whole_glyph = 0.90   # and no character is cut in half
    neck_facing = 0.85        # the two dents point at each other: a WAIST


def _neck_split(bubble_mask, glyph, cfg) -> list:
    """One balloon, two lobes: whose writing is in which.

    A balloon drawn as two overlapping ovals is one enclosure, so the outline
    detector finds one region in it, reads one block of Japanese out of it and
    hands the translator one speech - and two speeches come back merged into a
    single paragraph, typeset across the waist as though the artist had drawn
    a circle. lee has asked for this three times and it is the last thing on
    the page still doing it: MAKE THEM BOTH SAY IN THEIR OWN BOX.

    The division is the artist's, not ours: two ovals meet at two corners, and
    the chord between those two dents in the hull is the neck. `typeset.neck_cuts`
    reads them, and reads them off the same closed mask the typesetter will re-read
    at typeset time, so the split found here is the split typeset later.

    A chord divides ANY shape in two, though, so what matters is what is refused.
    A dent must bite a real distance into the balloon; each side must be a lobe
    rather than a chip off the rim; every character must land wholly on one side,
    which is what stops a chord slipping between two columns of a perfectly
    ordinary balloon; and both sides must actually hold writing, which is what
    throws away the balloon's TAIL - a tail leaves two dents as deep as any neck
    and the piece it cuts off is empty. Fail any of them and the next candidate
    is tried; fail them all and the balloon stays one region, exactly as before.

    Returns `(lobe, writing)` per lobe in reading order, or [] for one lobe.
    Each lobe is handed its OWN half of the balloon rather than the whole of
    it, which is the shape `detect.balloon` hands the blocks it divides: the
    typesetter re-reads the neck off the two halves closed back together, and
    what it measures the division against is what the detector already said.
    Give both halves the whole balloon instead and the thing it measures
    against is both speeches typeset on top of each other, which "wins" on
    size every time and throws the division away.
    """
    from ..typeset import neck_cuts

    m = (bubble_mask > 0).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        return []
    short = min(int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1)
    area = float(m.sum())

    g = (glyph > 0).astype(np.uint8)
    ink = float(g.sum())
    if ink <= 0:
        return []
    ng, glab, gstats, _ = cv2.connectedComponentsWithStats(g, 8)

    for lab, n in neck_cuts(m, min_depth=cfg.neck_depth_frac * short,
                            min_facing=cfg.neck_facing):
        sizes = sorted(((int((lab == j).sum()), j) for j in range(1, n)),
                       reverse=True)
        if len(sizes) < 2 or sizes[1][0] < cfg.neck_lobe_frac * area:
            continue
        if sum(a for a, _ in sizes[2:]) > 0.05 * area:
            continue                      # shattered, not divided
        keep = {sizes[0][1]: 0, sizes[1][1]: 1}
        parts = [np.zeros(g.shape, np.uint8), np.zeros(g.shape, np.uint8)]
        whole = True
        for j in range(1, ng):
            sel = glab == j
            hit = lab[sel]
            hit = hit[hit > 0]
            if not hit.size:
                continue                  # sits on the chord itself
            v, cnt = np.unique(hit, return_counts=True)
            lb = int(v[int(cnt.argmax())])
            if lb in keep and float(cnt.max()) / float(sel.sum()) >= cfg.neck_whole_glyph:
                parts[keep[lb]][sel] = 255
            elif int(gstats[j, 4]) >= 6:
                whole = False             # the chord runs through a character
                break
        if not whole:
            continue
        if min(float((p > 0).sum()) for p in parts) < cfg.neck_text_frac * ink:
            continue
        out = [(((lab == j) & (bubble_mask > 0)).astype(np.uint8) * 255,
                parts[keep[j]]) for _, j in sizes[:2]]
        return sorted(out, key=lambda lg: _reading_key(lg[1]))
    return []


def _reading_key(part):
    """Top to bottom, then right to left - the order Japanese is read in."""
    ys, xs = np.nonzero(part)
    if xs.size == 0:
        return (1 << 30, 0)
    return (int(ys.min()), -int(xs.max()))


def detect_outline(page: Page, cfg: OutlineConfig | None = None,
                   link_base: int = 0) -> list[TextRegion]:
    cfg = cfg or OutlineConfig()
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape
    page_area = H * W

    ink = (gray <= cfg.ink_thresh).astype(np.uint8)
    k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * cfg.close_px + 1, 2 * cfg.close_px + 1)
    )
    ink_closed = cv2.dilate(ink, k, iterations=1)
    free = (1 - ink_closed).astype(np.uint8)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, 4)
    regions: list[TextRegion] = []
    rid = 0
    # `link_base` keeps two passes over the same page from handing out the same
    # link id to two unrelated balloons, which would tell the translator to read
    # them as one sentence.
    link_seq = int(link_base)

    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (page_area * cfg.min_area_frac <= area <= page_area * cfg.max_area_frac):
            continue
        if (x <= cfg.border_margin or y <= cfg.border_margin
                or x + w >= W - cfg.border_margin or y + h >= H - cfg.border_margin):
            continue                      # page background, not an enclosure
        if area / max(1.0, w * h) < cfg.min_fill:
            continue

        comp = (labels == i).astype(np.uint8)
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        outer = max(cnts, key=cv2.contourArea)
        hull_a = cv2.contourArea(cv2.convexHull(outer))
        if area / max(1.0, hull_a) < cfg.min_solidity:
            continue

        # Fill the outer contour: interior including the glyph holes.
        bubble_mask = np.zeros((H, W), np.uint8)
        cv2.drawContours(bubble_mask, [outer], -1, 255, cv2.FILLED)
        b_area = float((bubble_mask > 0).sum())
        if b_area <= 0:
            continue

        glyph = ((gray <= cfg.ink_thresh) & (bubble_mask > 0)).astype(np.uint8)
        ink_frac = float(glyph.sum()) / b_area
        if not (cfg.min_ink_frac <= ink_frac <= cfg.max_ink_frac):
            continue
        ng, _, gstats, _ = cv2.connectedComponentsWithStats(glyph, 8)
        comp_areas = [int(gstats[j, 4]) for j in range(1, ng)
                      if gstats[j, 4] >= 6]
        if not _enough_glyphs(len(comp_areas), max(comp_areas, default=0),
                              cfg.min_glyph_components):
            continue
        if not _interior_ok(gray, bubble_mask, glyph, cfg):
            continue
        if _edge_density(gray, bubble_mask, glyph) > cfg.max_edge_density:
            continue

        lobes = _neck_split(bubble_mask, glyph, cfg)
        link = 0
        if len(lobes) >= 2:
            link_seq += 1
            link = link_seq
        else:
            lobes = [(bubble_mask, glyph * 255)]

        for shape, piece in lobes:
            ys, xs = np.nonzero(piece)
            if xs.size == 0:
                continue
            tx0, tx1 = max(0, xs.min() - cfg.text_pad), min(W - 1, xs.max() + cfg.text_pad)
            ty0, ty1 = max(0, ys.min() - cfg.text_pad), min(H - 1, ys.max() + cfg.text_pad)
            tw, th = tx1 - tx0 + 1, ty1 - ty0 + 1

            poly, bb = outer, (int(x), int(y), int(w), int(h))
            if link:
                lc, _ = cv2.findContours(shape, cv2.RETR_EXTERNAL,
                                         cv2.CHAIN_APPROX_SIMPLE)
                if not lc:
                    continue
                poly = max(lc, key=cv2.contourArea)
                bb = tuple(int(v) for v in cv2.boundingRect(poly))

            regions.append(TextRegion(
                id=rid,
                bbox=(int(tx0), int(ty0), int(tw), int(th)),
                text_mask=piece,
                bubble_mask=shape,
                bubble_bbox=bb,
                # Geometry is what survives being saved: masks are dropped and
                # rebuilt from this outline. Store the LOBE's own outline, or a
                # reopened chapter hands both speeches the whole balloon again
                # and typesets them on top of each other.
                polygon=poly.reshape(-1, 2).tolist(),
                kind="bubble",
                link=link,
                src_vertical=th > tw * 1.15,
            ))
            rid += 1

    return regions


def _interior_ok(gray, bubble_mask, glyph, cfg) -> bool:
    """Is the area inside the outline a flat, light bubble fill?"""
    inside = (bubble_mask > 0) & (glyph == 0)
    if inside.sum() < 50:
        return False
    px = gray[inside]
    return (float(px.mean()) >= cfg.min_interior_brightness
            and float(px.std()) <= cfg.max_interior_std)


def _edge_density(gray, bubble_mask, glyph) -> float:
    """Fraction of high-gradient pixels in the interior, glyphs excluded.

    A bubble fill is flat paper: after masking out the typesetting (plus a small
    halo for its anti-aliased rim) almost nothing has gradient. A face, a
    horse, a fistful of screentone - anything that merely LOOKS like a bubble
    to the shape checks - is full of drawn edges. Measured on a real chapter,
    true bubbles sit at 0.000-0.011 and art impostors at 0.02-0.30, so a
    threshold between the two removes most false boxes without touching a
    single real one.
    """
    halo = cv2.dilate((glyph > 0).astype(np.uint8),
                      np.ones((5, 5), np.uint8)) > 0
    clean = (bubble_mask > 0) & ~halo
    if clean.sum() < 50:
        return 1.0
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    return float((lap[clean] > 40).mean())


def _add_new(out: list, taken: list, found: list) -> None:
    """Keep what a later pass found and an earlier one did not.

    A lobe of a two-lobed balloon passes through here on its own feet, because
    it was given its OWN outline and its own box at the moment it was divided -
    the two halves share a `link`, not a rectangle. Were they instead to share
    the whole balloon's rectangle, the second would look exactly like a
    duplicate of the first and half of what the balloon says would be dropped
    between detection and the screen.
    """
    for r in found:
        if all(_iou(r.bubble_bbox, t) < 0.35 for t in taken):
            out.append(r)
            taken.append(r.bubble_bbox)


def _max_link(regions: list) -> int:
    return max((int(getattr(r, "link", 0) or 0) for r in regions), default=0)


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ox * oy
    return inter / max(1.0, aw * ah + bw * bh - inter)


def drop_parents(regions: list[TextRegion], min_children: int = 2
                 ) -> list[TextRegion]:
    """Remove a box that encloses several others.

    A panel whose background happens to be light reads as one big enclosure
    containing all of its bubbles. Keeping the children and dropping the parent
    is almost always what the typesetter wants.
    """
    boxes = [r.bubble_bbox for r in regions]
    keep = []
    for i, r in enumerate(regions):
        kids = sum(1 for k, b in enumerate(boxes)
                   if k != i and _contains(boxes[i], b)
                   and b[2] * b[3] < 0.75 * boxes[i][2] * boxes[i][3])
        if kids < min_children:
            keep.append(r)
    return keep


def detect_inverted(page: Page, cfg: ClassicalConfig | None = None
                    ) -> list[TextRegion]:
    """White-on-black typesetting: shouts, flashbacks, narration boxes sitting
    on dark art. It is the white-blob detector run on the NEGATIVE of the
    page - a dark shape enclosing light glyphs becomes a light shape
    enclosing dark glyphs, which is exactly what detect() knows how to find.
    Coordinates and masks land on the same pixels either way, so cleaning
    and typesetting work unchanged."""
    if cfg is None:
        cfg = ClassicalConfig()
        # dark shout / flashback panels run larger than white bubbles do
        cfg.max_area_frac = 0.25
        # A dark aura bubble's fill is wispy ink, not flat paper, so the
        # strict edge-density cut would erase every one of them. Only the
        # degenerate case - an interior so busy no clean fill remains, e.g. a
        # window pane full of lattice - reads near 1.0; cut only that.
        cfg.max_edge_density = 0.5
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return detect(Page(image=(255 - gray)), cfg)


def detect_combined(page: Page) -> list[TextRegion]:
    """Union of the methods, de-duplicated. Outline-first: it is the most
    reliable; a second, heavier-closing outline pass recovers bubbles whose
    border has gaps (open tails, wavy whisper bubbles) that let the interior
    leak into the panel background; white-blob picks up bubbles whose outline
    is broken or absent; the inverted pass picks up white-on-black typesetting
    the other two are blind to."""
    out = detect_outline(page)
    taken = [r.bubble_bbox for r in out]

    wide = OutlineConfig()
    wide.close_px = 5                 # bridge tail openings up to ~10 px
    _add_new(out, taken, detect_outline(page, wide, link_base=_max_link(out)))
    _add_new(out, taken, detect(page))
    _add_new(out, taken, detect_inverted(page))
    out = drop_parents(out)
    for r in out:
        _mark_narration(r)
    for i, r in enumerate(out):
        r.id = i
    return out


def _mark_narration(r: TextRegion) -> None:
    """A straight-sided rectangle full of text is a narration / caption box,
    not a speech bubble - flag it so it typesets as narration. Rounded bubbles
    fill only ~60-86% of their bounding box; a rectangle fills ~95%+, which
    separates the two cleanly. Never touches sfx or free-floating text."""
    if r.kind not in ("bubble",):
        return
    poly = r.polygon
    bb = r.bubble_bbox or r.bbox
    if not poly or not bb:
        return
    bw, bh = bb[2], bb[3]
    if bw < 8 or bh < 8:
        return
    cnt = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
    extent = cv2.contourArea(cnt) / max(1.0, float(bw * bh))
    peri = cv2.arcLength(cnt, True)
    corners = len(cv2.approxPolyDP(cnt, 0.03 * peri, True))
    # fills its box like a rectangle, and its outline simplifies to a few
    # straight sides (a rounded bubble stays many-cornered even simplified)
    if extent >= 0.90 and corners <= 8:
        r.kind = "narration"


def detect_within(page: Page, box, cfg: "OutlineConfig | None" = None
                  ) -> list[TextRegion]:
    """Re-run detection inside one box and return what is in there.

    This is the Split action: when one box has swallowed several bubbles, look
    inside it for the individual ones.
    """
    x, y, w, h = [int(v) for v in box]
    H, W = page.image.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(W - x, w), min(H - y, h)
    sub = Page(image=page.image[y:y + h, x:x + w].copy())
    found = detect_outline(sub, cfg) + [
        r for r in detect(sub)
        if all(_iou(r.bubble_bbox, o.bubble_bbox) < 0.35
               for o in detect_outline(sub))]
    found = drop_parents(found)

    out = []
    for r in found:
        bx, by, bw, bh = r.bubble_bbox
        # ignore a "child" that is just the box itself
        if bw * bh > 0.88 * w * h:
            continue
        tx, ty, tw, th = r.bbox
        r.bbox = (tx + x, ty + y, tw, th)
        r.bubble_bbox = (bx + x, by + y, bw, bh)
        if r.polygon:
            r.polygon = [[px + x, py + y] for px, py in r.polygon]
        full_b = np.zeros((H, W), np.uint8)
        full_b[y:y + h, x:x + w] = r.bubble_mask
        full_t = np.zeros((H, W), np.uint8)
        full_t[y:y + h, x:x + w] = r.text_mask
        r.bubble_mask, r.text_mask = full_b, full_t
        out.append(r)
    return out


def detect_panels(page: Page, min_frac: float = 0.02) -> list[tuple[int, int, int, int]]:
    """Panels as large regions bounded by dark gutters. Approximate by design:
    reading order only needs rough grouping, and region-level XY-cut recovers
    from panel misses."""
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    H, W = gray.shape

    ink = (gray < 100).astype(np.uint8)
    # dilate ink so panel border strokes become solid separators
    ink = cv2.dilate(ink, np.ones((3, 3), np.uint8), iterations=1)
    free = (1 - ink).astype(np.uint8)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, 8)
    panels = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < H * W * min_frac:
            continue
        if w < W * 0.12 or h < H * 0.04:
            continue
        if a / max(1, w * h) < 0.45:
            continue
        panels.append((int(x), int(y), int(w), int(h)))

    panels.sort(key=lambda b: -b[2] * b[3])
    kept: list[tuple[int, int, int, int]] = []
    for p in panels:
        if not any(_contains(k, p) for k in kept):
            kept.append(p)
    return kept


def _contains(outer, inner, tol: int = 6) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (ix >= ox - tol and iy >= oy - tol
            and ix + iw <= ox + ow + tol and iy + ih <= oy + oh + tol)
