"""Give a detected block of text the balloon it is sitting in.

comic-text-detector finds TEXT, not balloons. Every region it returns carries
``bubble_mask=None``, so ``TextRegion.place_mask()`` falls through to the glyph
footprint and the fitter lays the English out inside the shape of the Japanese.
Japanese runs down the page in a tall narrow column, so the English was being
squeezed into a tall narrow column — which is the whole reason the typesetting
came out at 8-12pt inside a 200px balloon.

This pass walks outward from each block's ink until it meets the dark outline
drawn around it, takes the enclosed paper as the balloon, and refuses anything
that does not actually look like paper (a flat light fill with no drawn edges
in it). Nothing is invented: when no plausible balloon is found the region is
left exactly as the detector returned it, and the fitter falls back to the text
box as before.

Two blocks that land in the SAME balloon — a split bubble, where one run of
dialogue is written as two separated columns — divide that balloon between
them along the line equidistant from their ink, so both are typeset at full
size instead of on top of each other.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..models import TextRegion
from .classical import _edge_density, _interior_ok


class BalloonConfig:
    ink_thresh = 128          # pixel <= this is outline or glyph, not paper
    close_px = 2              # bridge anti-aliasing gaps in a thin outline
    min_area_frac = 0.0004    # of page area
    max_area_frac = 0.28      # a full-page splash balloon is still a balloon
    min_fill = 0.34           # area / bbox area — tails and bursts are ragged
    min_solidity = 0.55       # area / convex hull area
    border_margin = 3         # a blob touching the page edge is background
    min_glyph_inside = 0.80   # of the block's ink must land in the balloon
    min_gain = 1.15           # balloon must beat the text box to be worth it
    max_ink_frac = 0.60       # a balloon is mostly paper, not mostly ink
    min_interior_brightness = 190
    max_interior_std = 50
    max_edge_density = 0.018  # art has drawn edges in it, paper has none
    split_gap_px = 2          # hairline kept between two shares of one balloon
    # Sealing a balloon whose outline is broken. See _local_balloon.
    seals = (3, 5, 8, 12, 17)
    windows = (2.6, 4.0, 6.5)
    # How much two blocks' vertical extents may overlap and still be treated as
    # stacked. Japanese in one balloon runs as columns read right-to-left, so a
    # second block usually sits both LEFT of and BELOW the first; the English
    # replacing it stacks straight down. Anything under this is stacked.
    stack_overlap = 0.35


def _free_labels(gray: np.ndarray, cfg: BalloonConfig):
    """Label every run of connected paper on the page.

    Ink is dilated first so a hairline outline still separates the inside of a
    balloon from the page behind it.
    """
    ink = (gray <= cfg.ink_thresh).astype(np.uint8)
    k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * cfg.close_px + 1, 2 * cfg.close_px + 1))
    free = (1 - cv2.dilate(ink, k, iterations=1)).astype(np.uint8)
    n, labels = cv2.connectedComponents(free, 4)
    return n, labels


def _surrounding_label(labels: np.ndarray, glyph: np.ndarray,
                       ring_px: int = 4) -> int:
    """The run of paper the block's ink is embedded in.

    Taken from a ring hugging the glyphs rather than from the block's box: near
    the edge of a bubble the box overlaps the page behind it, and the majority
    label there is the background.

    `ring_px` has to clear whatever dilation the labelling was done with, or
    the ring lands entirely on the dilated glyphs — which are not paper and so
    carry no label — and the answer comes back as "nothing surrounds this".
    """
    ring = cv2.dilate((glyph > 0).astype(np.uint8),
                      cv2.getStructuringElement(
                          cv2.MORPH_ELLIPSE, (2 * max(1, ring_px) + 1,) * 2))
    sel = (ring > 0) & (glyph == 0) & (labels > 0)
    if not sel.any():
        return 0
    vals, counts = np.unique(labels[sel], return_counts=True)
    return int(vals[int(counts.argmax())])


def _filled(labels: np.ndarray, lab: int):
    """(mask, outer contour) for one run of paper, glyph holes filled in.

    The contour of the paper follows the INSIDE of the outline, so filling it
    gives the balloon interior — the typesetting that used to be in it included,
    the outline itself excluded.
    """
    comp = (labels == lab).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None
    outer = max(cnts, key=cv2.contourArea)
    mask = np.zeros(labels.shape, np.uint8)
    cv2.drawContours(mask, [outer], -1, 255, cv2.FILLED)
    return mask, outer


def _plausible(gray, mask, outer, cfg, page_area: float = 0.0) -> bool:
    """Does this run of paper look like a balloon?

    `page_area` is what the size limits are measured against. It defaults to
    the picture handed in, and is passed explicitly when that picture is a
    window cut out of the page (_local_balloon) rather than the page itself —
    a balloon is a fraction of a PAGE, and judging it against the size of the
    window it was found in would let a window swallow whatever it framed.
    """
    H, W = gray.shape[:2]
    x, y, w, h = cv2.boundingRect(outer)
    if (x <= cfg.border_margin or y <= cfg.border_margin
            or x + w >= W - cfg.border_margin or y + h >= H - cfg.border_margin):
        return False                      # the page behind the art, not a balloon
    page_area = float(page_area) if page_area > 0 else float(H * W)
    # Shape is judged on the balloon with its typesetting filled in. Measuring the
    # bare paper instead would punish a bubble for being full of Japanese: a
    # densely packed one loses a third of its area to glyph holes and stops
    # looking solid, which is exactly the bubble that needs rescuing most.
    area = float((mask > 0).sum())
    if not (page_area * cfg.min_area_frac <= area <= page_area * cfg.max_area_frac):
        return False
    if area / max(1.0, float(w * h)) < cfg.min_fill:
        return False
    hull = cv2.contourArea(cv2.convexHull(outer))
    if area / max(1.0, hull) < cfg.min_solidity:
        return False
    ink = ((gray <= cfg.ink_thresh) & (mask > 0)).astype(np.uint8)
    if float(ink.sum()) / area > cfg.max_ink_frac:
        return False
    if not _interior_ok(gray, mask, ink, cfg):
        return False
    return _edge_density(gray, mask, ink) <= cfg.max_edge_density


def _rows(seed: np.ndarray):
    ys = np.nonzero((seed > 0).any(axis=1))[0]
    return (int(ys[0]), int(ys[-1])) if ys.size else None


def _stacked_bands(seeds: list[np.ndarray], cfg: BalloonConfig):
    """Row cuts if the blocks are stacked down the balloon, else None.

    The nearest-ink division below is the honest answer to "whose pixel is
    this", but it is the wrong answer to "where does this block of English
    go". Two columns of Japanese that sit diagonally apart get a diagonal
    dividing line, and a diagonal edge cuts the usable chord on every line of
    horizontal typesetting — the fitter measures the NARROWEST row in each
    line's band, so a wedge prices out at a couple of sizes smaller than the
    room really available. On the split bubble that was 14pt where the printed
    page has room for 20.

    When the blocks are stacked — which is the normal case, because Japanese
    columns read right-to-left and so a continuation lands below as well as
    left — a typesetter cuts straight across instead, and each block gets the
    balloon's full width. So take that cut, and fall back to nearest-ink only
    when the blocks genuinely sit alongside each other.
    """
    ext = [_rows(s) for s in seeds]
    if any(e is None for e in ext):
        return None
    order = sorted(range(len(seeds)), key=lambda i: sum(ext[i]) / 2.0)
    cuts = []
    for a, b in zip(order, order[1:]):
        (a0, a1), (b0, b1) = ext[a], ext[b]
        span = min(a1 - a0, b1 - b0) + 1
        if min(a1, b1) - max(a0, b0) + 1 > cfg.stack_overlap * span:
            return None                       # side by side, not stacked
        cuts.append((a1 + b0) // 2)
    return order, cuts


def _share(balloon: np.ndarray, seeds: list[np.ndarray],
           cfg: BalloonConfig) -> list[np.ndarray]:
    """Divide one balloon between the blocks inside it.

    Stacked blocks get a straight cut across the balloon so each keeps its full
    width; otherwise every pixel goes to whichever block's ink is nearest, so
    the dividing line sits halfway between the two columns of Japanese. Either
    way a hairline is taken off each share so the two blocks of English cannot
    end up touching.
    """
    bands = _stacked_bands(seeds, cfg)
    if bands is not None:
        order, cuts = bands
        who = np.zeros(balloon.shape, np.int32)
        edges = [0] + [c + 1 for c in cuts] + [balloon.shape[0]]
        for rank, i in enumerate(order):
            who[edges[rank]:edges[rank + 1]] = i
    else:
        dists = [cv2.distanceTransform((seed == 0).astype(np.uint8),
                                       cv2.DIST_L2, 3) for seed in seeds]
        who = np.stack(dists).argmin(0)
    out = []
    k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * cfg.split_gap_px + 1, 2 * cfg.split_gap_px + 1))
    for i, seed in enumerate(seeds):
        cell = ((who == i) & (balloon > 0)).astype(np.uint8)
        cell = cv2.erode(cell, k, iterations=1)
        # Keep only the piece the block's own ink is in: an L-shaped balloon can
        # hand a share a detached scrap on the far side of the dividing line.
        n, lab = cv2.connectedComponents(cell, 4)
        if n > 1:
            hit = lab[seed > 0]
            hit = hit[hit > 0]
            if hit.size:
                vals, counts = np.unique(hit, return_counts=True)
                cell = (lab == int(vals[int(counts.argmax())])).astype(np.uint8)
        out.append(cell * 255)
    return out


def _local_balloon(gray: np.ndarray, r: TextRegion, cfg: BalloonConfig):
    """Find the balloon around one block after the page-wide pass leaked.

    Most balloons that come back with nothing are not missing an outline —
    they have a small hole in one. The usual hole is the tail: it is drawn as
    two strokes that stop short of meeting, and where a balloon sits over a
    gutter that opening lets its interior run out into the white margin. The
    run of paper the block is embedded in then IS the page background, which
    is thrown out (correctly — nothing that reaches the page edge is a
    balloon), and the block ends up with no placement area at all. On this
    chapter that was thirteen of twenty-seven misses.

    Bridging the hole closes the balloon again, and a hole of a few white
    pixels in a drawn line is bridged by dilating the ink a little further
    before the paper is labelled. Too much dilation swallows a small balloon
    whole, so the seals are tried from smallest up and the first that works
    is the one taken.

    The search runs in a window around the block and the window's own edge is
    the test: paper that reaches it has still leaked out, so that seal was too
    small — or the balloon is simply bigger than the window, so the window is
    grown and tried again. Whatever is found is judged by exactly the same
    rules as the page-wide pass, against the size of the PAGE, so a window
    cannot make a scrap of gutter look like a balloon.

    Returns a page-sized mask, or None.
    """
    H, W = gray.shape[:2]
    x, y, w, h = [int(v) for v in r.bbox]
    x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
    w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
    seed = (r.text_mask[y:y + h, x:x + w] > 0)
    if not seed.any():
        return None
    for seal in cfg.seals:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * seal + 1,) * 2)
        for scale in cfg.windows:
            pad = int(max(w, h) * (scale - 1.0) / 2.0) + 8
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
            crop = gray[y0:y1, x0:x1]
            ink = (crop <= cfg.ink_thresh).astype(np.uint8)
            free = (1 - cv2.dilate(ink, k, iterations=1)).astype(np.uint8)
            n, labels = cv2.connectedComponents(free, 4)
            if n <= 1:
                continue
            glyph = np.zeros(crop.shape, np.uint8)
            glyph[y - y0:y - y0 + h, x - x0:x - x0 + w] = seed * 255
            lab = _surrounding_label(labels, glyph, ring_px=seal + 4)
            if lab <= 0:
                continue
            mask, outer = _filled(labels, lab)
            if mask is None:
                continue
            if not _plausible(crop, mask, outer, cfg, page_area=float(H * W)):
                continue
            mask = _give_back(crop, mask, glyph, seal, cfg, float(H * W))
            full = np.zeros((H, W), np.uint8)
            full[y0:y1, x0:x1] = mask
            return full
    return None


def _give_back(crop, mask, glyph, seal, cfg, page_area):
    """Undo the seal's bite.

    Sealing dilates the ink, so the paper it leaves is the balloon interior
    short of `seal - close_px` pixels on every edge. Those pixels are room the
    typesetting is entitled to, so grow the shape back — but grow it into paper
    only, so it stops against the drawn outline instead of stepping over it,
    and keep the piece the block's own ink is in. If what comes back no longer
    looks like a balloon, the sealed shape is kept as it was.
    """
    back = seal - cfg.close_px
    if back <= 0:
        return mask
    grown = cv2.dilate(mask, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * back + 1,) * 2))
    # Ink OUTSIDE the sealed shape is the balloon's own outline and the art
    # past it; ink inside it is the typesetting being replaced, and the shape
    # was filled over that on purpose.
    wall = ((crop <= cfg.ink_thresh) & (mask == 0)).astype(np.uint8) * 255
    grown = cv2.bitwise_and(grown, cv2.bitwise_not(wall))
    n, labels = cv2.connectedComponents((grown > 0).astype(np.uint8), 4)
    hit = labels[glyph > 0]
    hit = hit[hit > 0]
    if not hit.size:
        return mask
    vals, counts = np.unique(hit, return_counts=True)
    kept, outer = _filled(labels, int(vals[int(counts.argmax())]))
    if kept is None or not _plausible(crop, kept, outer, cfg, page_area):
        return mask
    return kept


def _apply(r: TextRegion, mask: np.ndarray) -> bool:
    """Hang a placement area on a region, as geometry the project can store."""
    cnts, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return False
    outer = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(outer) < 24:
        return False
    r.bubble_mask = (mask > 0).astype(np.uint8) * 255
    r.bubble_bbox = tuple(int(v) for v in cv2.boundingRect(outer))
    # Stored as a polygon, not a bitmap: this is what survives a save and gets
    # rebuilt on load (see project.region_from_record).
    r.polygon = cv2.approxPolyDP(outer, 1.0, True).reshape(-1, 2).tolist()
    return True


def sections_in_one_balloon(gray: np.ndarray, regions: list[TextRegion],
                            cfg: BalloonConfig | None = None) -> int:
    """One balloon, one box — and inside that box, one SECTION per clump.

    lee's rule for the box: "the boxes shoud be around the bubbles no 2 of them
    split randomly, each bubbles shoud have their own box". And his rule for
    what is inside it, drawn on the picture in green and blue: "make it so that
    the bubbles can have 2 sections ... and teh typsetting shoud still typeseet
    them in there own sections where the dot is".

    His shout balloon holds a sentence up the right and a small あっ！ lower and
    to the left. Those are two things to read and two things to typeset — but
    one balloon, so one box. What the old code did instead was hand both blocks
    to `_share`, which slices the balloon into full-width horizontal BANDS: the
    dead-flat seam he sent back, one box stacked on the other.

    So the blocks are kept, both of them, and what changes is the geometry
    around them:

    * they are given the same `box_group`, and the editor draws ONE box round
      the group rather than a box each;
    * they are NOT linked. A link means "these are one sentence split across
      balloons", and the translator honours it by splitting one English
      sentence between them. A sentence and an あっ！ under it are two things
      said, and lee asked for them to be READ as two sections, so each keeps
      its own reading and its own translation;
    * and the balloon is divided between them by NEARNESS, not by bands. Every
      pixel of the paper goes to whichever clump of writing is closer to it, so
      the sentence keeps the upper right, あっ！ keeps the lower left, and the
      boundary runs where the writing says it should. Each then typesets inside
      its own share, centred in it — the dot lee drew.

    A balloon that is genuinely two balloons never reaches here: it is two
    enclosures on the page, or one enclosure with a neck the outline detector
    has already divided along, and either way its blocks arrive carrying a
    `bubble_mask` of their own. Anything carrying one is left alone.

    This is a DETECTION-time pass and belongs nowhere else. `attach_balloons`
    runs again on every load, and re-cutting the shares there would overwrite a
    division somebody had corrected by hand.

    Returns how many balloons were divided into sections.
    """
    cfg = cfg or BalloonConfig()
    todo = [r for r in regions
            if r.kind in ("bubble", "narration")
            and r.bubble_mask is None and r.text_mask is not None]
    if len(todo) < 2:
        return 0

    n, labels = _free_labels(gray, cfg)
    if n <= 1:
        return 0

    found: dict[int, list[TextRegion]] = {}
    for r in todo:
        lab = _surrounding_label(labels, r.text_mask)
        if lab > 0:
            found.setdefault(lab, []).append(r)

    group = max([int(getattr(r, "box_group", 0) or 0) for r in regions] or [0])
    done = 0
    for lab, members in found.items():
        if len(members) < 2:
            continue
        mask, outer = _filled(labels, lab)
        if mask is None or not _plausible(gray, mask, outer, cfg):
            continue
        seeds = [(m.text_mask > 0) for m in members]
        if any(not s.any() for s in seeds):
            continue
        # Every block has to be inside the thing we found, or we found the
        # wrong thing and dividing it would divide two different balloons.
        if any(float(((mask > 0) & s).sum()) < cfg.min_glyph_inside * float(s.sum())
               for s in seeds):
            continue
        shares = _by_nearest(mask, seeds)
        if any(not (s > 0).any() for s in shares):
            continue
        group += 1
        # Reading order inside the balloon: Japanese runs right to left, top to
        # bottom, so the topmost of the rightmost columns is spoken first.
        order = sorted(range(len(members)),
                       key=lambda i: (members[i].bbox[1], -members[i].bbox[0]))
        for seq, i in enumerate(order):
            r = members[i]
            r.bubble_mask = shares[i]
            r.bubble_bbox = tuple(int(v) for v in cv2.boundingRect(shares[i]))
            # A chapter is held as geometry, so the outline stored for each
            # section has to be the SECTION's outline. Store the whole
            # balloon's and both sections get the whole balloon back on
            # reload, and the two speeches are typeset on top of each other.
            cs, _ = cv2.findContours((shares[i] > 0).astype(np.uint8),
                                     cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cs:
                big = max(cs, key=cv2.contourArea)
                r.polygon = [[int(a), int(b)] for a, b in big.reshape(-1, 2)]
            r.box_group = group
            r.order = r.order if r.order >= 0 else seq
        done += 1
    return done


def _by_nearest(balloon: np.ndarray, seeds: list[np.ndarray],
                gap: int = 2) -> list[np.ndarray]:
    """Divide the paper between the clumps of writing standing on it.

    Every pixel goes to the writing nearest to it. That is the division a
    typesetter makes by eye, and it is the one thing a band cut cannot do: two
    clumps side by side get a boundary running BETWEEN them, not straight
    across the balloon and through both.

    Two things are done to each share afterwards. A hairline is taken off it,
    so the two blocks of English cannot end up touching along the dividing
    line. And only the piece the block's own ink stands in is kept: a balloon
    with a waist or a tail can hand a share a detached scrap on the far side
    of the division, and a scrap the fitter can see is a scrap it will try to
    typeset into.
    """
    inside = (balloon > 0)
    dists = [cv2.distanceTransform((~(s > 0)).astype(np.uint8), cv2.DIST_L2, 3)
             for s in seeds]
    win = np.stack(dists, axis=0).argmin(axis=0)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * gap + 1, 2 * gap + 1))
    out = []
    for i, seed in enumerate(seeds):
        cell = cv2.erode(((win == i) & inside).astype(np.uint8), k, iterations=1)
        n, lab = cv2.connectedComponents(cell, 4)
        if n > 1:
            hit = lab[(seed > 0) & inside]
            hit = hit[hit > 0]
            if hit.size:
                vals, counts = np.unique(hit, return_counts=True)
                cell = (lab == int(vals[int(counts.argmax())])).astype(np.uint8)
        m = cell * 255
        # The writing is never given away, whatever the erode did at its
        # edges — a character half in one share and half in the other is a
        # character the typesetter has to draw twice.
        m[(seed > 0) & inside] = 255
        out.append(m)
    return out


def attach_balloons(gray: np.ndarray, regions: list[TextRegion],
                    cfg: BalloonConfig | None = None) -> int:
    """Give every speech region the balloon around it. Returns how many got one.

    Sound effects are left alone on purpose: they have no balloon, and the
    ink's own footprint is the right place for them.

    Everything below this line reads `gray <= ink_thresh` as ink and the rest
    as paper, which is a white balloon with dark typesetting — and lee's pages
    have black balloons with white typesetting in them too, an eye with a flat
    black speech shape inside it holding a white ...HUH?. Nothing here could
    ever find one: its interior IS ink by that definition, so it is never a
    run of paper to begin with, and the brightness gate would refuse it if it
    were. lee, with a screenshot of each: *"can you do a tecting for black
    bubbles like teh white bubbles"*.

    So the search is run twice — once on the page, and once on its negative
    for the blocks the first pass left with nothing. Coordinates and masks
    land on the same pixels either way, and every test the upright pass
    applies (enclosed, the right size, a flat fill, no drawn edges in it)
    applies unchanged to the negative, where it means "a flat DARK fill".
    That is the whole of it: no new threshold, and nothing decided by
    guessing at how dark the artwork around a block looks.

    Measured on the two pages lee sent, rebuilt as fixtures: the white balloon
    is found upright and not inverted, the black one inverted and not upright,
    and white typesetting on genuinely textured dark artwork — a real free
    shout, which must stay free — is found by neither, because hatching cuts
    the dark into strips and carries drawn edges the fill test refuses.
    """
    cfg = cfg or BalloonConfig()
    up = _attach(gray, regions, cfg, ("bubble", "narration"))
    # …and again on the negative, for the black balloons. A block the page
    # called free-floating is allowed in this time: on a black balloon the ring
    # of "is there paper round this?" reads as artwork, so a block inside one
    # arrives labelled free text. Finding a balloon around it is the answer to
    # that question, and a better one than the ring gave — so a block that
    # turns out to be in a balloon is called what it is.
    dark = _attach(255 - gray, regions, cfg,
                   ("bubble", "narration", "freefloat"), promote=True)
    return up + dark


def _attach(gray: np.ndarray, regions: list[TextRegion], cfg: BalloonConfig,
            kinds: tuple, promote: bool = False) -> int:
    """One pass of the balloon search over `gray` as it stands.

    `kinds` is which blocks are eligible; `promote` renames a free-floating
    block that turns out to be in a balloon after all.
    """
    todo = [r for r in regions
            if r.kind in kinds
            and r.bubble_mask is None and r.text_mask is not None]
    if not todo:
        return 0

    n, labels = _free_labels(gray, cfg)
    if n <= 1:
        return 0

    # Which run of paper each block sits in. Several blocks can name the same
    # one — that is a split bubble, and they share it below.
    found: dict[int, list[TextRegion]] = {}
    for r in todo:
        lab = _surrounding_label(labels, r.text_mask)
        if lab > 0:
            found.setdefault(lab, []).append(r)

    done = 0
    for lab, members in found.items():
        mask, outer = _filled(labels, lab)
        if mask is None:
            continue
        if not _plausible(gray, mask, outer, cfg):
            continue
        seeds = [(m.text_mask > 0) for m in members]
        keep = [s for s in seeds if s.any()]
        if len(keep) != len(seeds):
            continue
        # Every block must actually be inside what we found, or we found the
        # wrong thing.
        if any(float(((mask > 0) & s).sum()) < cfg.min_glyph_inside * float(s.sum())
               for s in seeds):
            continue
        shares = _share(mask, seeds, cfg) if len(members) > 1 else [mask]
        for r, share in zip(members, shares):
            x, y, w, h = r.bbox
            # Only worth taking if it gives the typesetting more room than the
            # text box it replaces.
            if float((share > 0).sum()) < cfg.min_gain * float(max(1, w * h)):
                continue
            if _apply(r, share):
                done += 1
    got = _second_pass(gray, todo, cfg)
    # Renaming happens once, here, and not beside each `_apply` — the rescue
    # pass below finds balloons too, and a block promoted in one place and not
    # the other is a bug waiting for the day the two paths disagree.
    if promote:
        for r in todo:
            if r.kind == "freefloat" and r.bubble_mask is not None:
                r.kind = "bubble"
    return done + got


def _second_pass(gray: np.ndarray, todo: list[TextRegion],
                 cfg: BalloonConfig) -> int:
    """Rescue the blocks the page-wide pass left with nothing.

    Each is re-searched on its own with a seal that closes a broken outline
    (_local_balloon). Two blocks in one balloon come back with the same shape,
    so anything found is regrouped by overlap and shared out exactly as
    before — otherwise both halves of a split bubble would each claim the
    whole balloon and be typeset on top of each other.
    """
    left = [r for r in todo if r.bubble_mask is None]
    if not left:
        return 0
    found = [(r, _local_balloon(gray, r, cfg)) for r in left]
    found = [(r, m) for r, m in found if m is not None]
    if not found:
        return 0

    groups: list[list[int]] = []
    for i in range(len(found)):
        for g in groups:
            a, b = (found[i][1] > 0), (found[g[0]][1] > 0)
            both = float((a & b).sum())
            if both >= 0.6 * min(float(a.sum()), float(b.sum())):
                g.append(i)
                break
        else:
            groups.append([i])

    done = 0
    for g in groups:
        members = [found[i][0] for i in g]
        mask = max((found[i][1] for i in g), key=lambda m: int((m > 0).sum()))
        seeds = [(m.text_mask > 0) for m in members]
        if any(not s.any() for s in seeds):
            continue
        if any(float(((mask > 0) & s).sum()) < cfg.min_glyph_inside * float(s.sum())
               for s in seeds):
            continue
        shares = _share(mask, seeds, cfg) if len(members) > 1 else [mask]
        for r, share in zip(members, shares):
            x, y, w, h = r.bbox
            if float((share > 0).sum()) < cfg.min_gain * float(max(1, w * h)):
                continue
            if _apply(r, share):
                done += 1
    return done


# --- writing with no balloon round it ---------------------------------------
#
# A caption printed straight onto a blank panel has no balloon, and the walk in
# `attach_balloons` above finds none it may keep. Before this, such a region
# fell back to its own box, which is the box drawn round the JAPANESE — a tall
# narrow column, because that is how Japanese is set. lee's page 10 typeset at
# 12pt in a column 96 pixels wide, next to Japanese printed at twice that.
#
# The paper round it is empty and the English may have it. What it may NOT have
# is the whole run of blank paper, because that run wraps AROUND the drawing:
# on page 10 it reaches from one side of the panel to the other, behind the
# woman and the child, and typesetting into it laid the English across their
# faces. That is the fault this fixes and it is worth being exact about the
# difference — the flood fill goes round an obstacle, and a rectangle stops at
# it. So the box grows sideways and downwards until it MEETS something, in each
# direction independently, and whatever it meets first is where it stops:
# artwork, the panel frame, another region's writing, the edge of the page.
#
# The result can only ever be blank paper, so the typesetting can only ever land
# on blank paper. That is the guarantee, and it does not depend on a threshold.

GROW_STOP = 4          # px of ink in a scanline that counts as "something here"
GROW_CLEAR = 3         # keep this much white between the text and what stopped it
# How much bigger than its own box a region may get, per side, as a fraction of
# that side. lee: *"outide text and sfx should try to fit inside the box or
# slightly bigger"*. Growing until the artwork stops it is too much room — on
# page 10 it gave a caption nearly twice its box in both directions and the
# English came out bigger than the Japanese it replaced. So the paper is a
# margin round the writing, not everything going spare.
#
# It also has to be bounded at all: blank paper does not always end. A page
# whose gutters are white has nothing to stop the scan short of the sheet's
# edge, and on two of lee's pages the room ran the full height and most of the
# width. Being wrong here costs a size or two — the room is only ever used
# where the old code used the bare box, so the floor is always the box.
GROW_MARGIN = 0.25


def _blocked(row: np.ndarray) -> bool:
    return int(row.sum()) >= GROW_STOP


def room_around(gray: np.ndarray, region: TextRegion,
                others: list[TextRegion] | None = None,
                cfg: BalloonConfig | None = None,
                taken: np.ndarray | None = None) -> bool:
    """Give a region with no balloon the empty paper around its writing.

    Returns whether it grew. The region keeps its own box when there is no
    room — nothing is ever made smaller here.

    `taken` is the paper already handed to earlier regions, and it stops the
    growth like any other obstacle. Two captions on one panel are read in
    order, so the first one to be asked gets the room they both reach; without
    this they would each be measured against bare paper and overlap, and the
    English of one would be typeset over the English of the other.
    """
    cfg = cfg or BalloonConfig()
    if region.text_mask is None:
        return False
    H, W = gray.shape[:2]
    x, y, w, h = [int(v) for v in region.bbox]
    x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
    w, h = max(1, min(w, W - x)), max(1, min(h, H - y))

    # Everything that stops the growth: ink on the page, plus every OTHER
    # region's writing. Most writing stops the scan simply by being dark, but
    # not all of it does — white typesetting on a black panel comes back with a
    # mask of the LIGHT pixels, and a scan looking for ink walks straight
    # through it. This region's own writing is never in the way: the scan
    # starts at the edge of its box and only ever moves outwards.
    stop = (gray <= cfg.ink_thresh)
    for o in (others or []):
        if o is region or o.text_mask is None:
            continue
        stop = stop | (o.text_mask > 0)
    if taken is not None:
        stop = stop | (taken > 0)

    mx, my = int(GROW_MARGIN * w), int(GROW_MARGIN * h)
    lo_x, hi_x = max(0, x - mx), min(W, x + w + mx)
    lo_y, hi_y = max(0, y - my), min(H, y + h + my)
    x0, y0, x1, y1 = x, y, x + w, y + h
    while x0 > lo_x and not _blocked(stop[y0:y1, x0 - 1]):
        x0 -= 1
    while x1 < hi_x and not _blocked(stop[y0:y1, x1]):
        x1 += 1
    while y0 > lo_y and not _blocked(stop[y0 - 1, x0:x1]):
        y0 -= 1
    while y1 < hi_y and not _blocked(stop[y1, x0:x1]):
        y1 += 1

    # Stand off whatever stopped us, but never inside the original box.
    x0 = min(x, x0 + GROW_CLEAR); y0 = min(y, y0 + GROW_CLEAR)
    x1 = max(x + w, x1 - GROW_CLEAR); y1 = max(y + h, y1 - GROW_CLEAR)
    if (x1 - x0) * (y1 - y0) < cfg.min_gain * w * h:
        return False                      # not enough room to be worth it

    # Only the placement area is set — NOT the polygon, and NOT bubble_bbox.
    # lee: *"teh box that shoud be considered is teh box that i see"*. The box
    # he sees is the one round the writing and it does not move; this is only
    # where the English is allowed to go. Nothing here is saved either: the
    # rectangle is worked out again from the page and the box on every load,
    # so it always matches the page in front of him.
    box = np.zeros((H, W), np.uint8)
    box[y0:y1, x0:x1] = 255
    region.bubble_mask = box
    return True


def give_room(gray: np.ndarray, regions: list[TextRegion],
              cfg: BalloonConfig | None = None) -> int:
    """Grow every region that ended up with no balloon. Returns how many grew.

    Sound effects are left alone: they are drawn along an axis of their own,
    over artwork, and belong exactly where the original was.
    """
    cfg = cfg or BalloonConfig()
    taken = np.zeros(gray.shape[:2], np.uint8)
    for r in regions:                       # balloons are already spoken for
        if r.bubble_mask is not None:
            taken |= (r.bubble_mask > 0).astype(np.uint8)
    done = 0
    for r in sorted(regions, key=lambda r: (getattr(r, "order", 0), r.id)):
        if r.kind == "sfx" or r.bubble_mask is not None or r.text_mask is None:
            continue
        if getattr(r, "manual", False) or getattr(r, "locked", False):
            continue
        if room_around(gray, r, regions, cfg, taken):
            taken |= (r.bubble_mask > 0).astype(np.uint8)
            done += 1
    return done
