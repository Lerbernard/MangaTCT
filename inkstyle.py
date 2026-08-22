"""What colour the printed text is, measured off the page.

lee: *"whe teh ai read teh text is it posible to have teh ai laos look for
color/formats f teh tetx that its reading for the typesetter ... or is it
better to have teh typesster try to find this info itself"*.

**The pixels, not the reader.** The whole of this chapter's evidence says a
vision model normalises what it is unsure of - 티리스 became 타리스, 드래건
became 드래곤, `….` became `...`. A hex value and an angle are exactly the kind
of continuous quantity it would approximate, and it could not tell you how sure
it was. The page can: a gradient is a regression, and the regression comes with
an R² that says whether it is a gradient at all.

It is also free. No tokens, no extra turn, deterministic, and it can be run
again whenever a box moves.

MEASURED on six pages of lee's chapter 1, 25 boxes, boxes detected for real and
the ink measured off the original::

    ordinary dialogue        R² 0.00 - 0.07   span   0 - 4
    011's gold plaque        R² 0.93          span  78    #736626 -> #C19A5B
    066's 파 and 앙          R² 0.78          span 117    #000000 -> #750104

There is no middle. `GRAD_FIT` and `GRAD_SPAN` sit in the chasm.

Three things this does NOT do, all of them deliberate:

* **It does not trust `text_mask`.** That is the BLOCK the detector found, not
  the letters in it: measure a plain bubble through it and the answer is
  #FAFAFA, which is the paper. The glyphs are found inside the block as the
  pixels that differ from the local paper - which also gets white-on-navy right
  without a second code path, because "differs from the paper" has no polarity.
* **It reports a glow only where the fade goes on for four rings.** 011's
  cream halo does not - it runs 80 20 18 5 - and neither does the small
  balloon on its own page, which runs 34 35 24 2 and is the balloon's edge
  rather than a halo at all. At three rings there is no measurement that keeps
  one and refuses the other, so both are left alone.
* **It never overwrites a colour somebody chose.** It fills in blanks.
"""
from __future__ import annotations

import cv2
import numpy as np

# Fewest glyph pixels worth measuring. Below this the median is one stroke of
# one letter and the gradient fit is noise fitted to noise.
MIN_GLYPH = 120

# How far a pixel must sit from the local paper to be ink, when Otsu inside the
# block says lower. Anti-aliasing on a black-on-white bubble runs to about 20.
INK_FLOOR = 24

# How far apart the two halves of the marked pixels must sit before they are
# taken to be two different things - the letters and the ring round them -
# rather than one thing unevenly lit. 066's red-in-white measures 129 apart;
# plain writing has nothing to split and comes nowhere near.
INK_SPLIT = 40

# ...and how much of that near half may lie INSIDE the shape before it stops
# being a ring and starts being the light end of a gradient.
NEAR_INSIDE = 0.35

# A gradient, or shading? Both numbers have to clear, because either alone
# lies: a flat fill on uneven artwork reaches a high R² with a span of 3, and
# two-tone noise reaches a big span at R² 0.02.
GRAD_FIT = 0.45          # measured: 0.07 is the worst flat, 0.78 the best real
GRAD_SPAN = 45           # measured: 4 is the worst flat, 78 the plaque

# An outline. Measured at the SECOND ring out, because the first is the
# anti-aliased rim of the glyph and every letter on every page has one: 059's
# plain black caption steps 39 at ring 1 and 2 at ring 2.
#
# Deliberately high. At 40 the only thing on six pages that claims an outline
# is 066's sound effects, which have a white one - 011's halo (20) and 029's
# glowing blue (26) are left alone rather than typeset as a hard ring that is
# not what the artist drew.
EDGE_STEP = 40
EDGE_MAX = 4             # rings out to here are the outline; past it, paper

# ...and it has to be FLAT, which is what separates an outline from a glow and
# from a caption sitting on a small white patch of artwork. An outline is one
# colour: 066's white ring measures 6 across its three rings. A falloff is not:
# 029's blue sound effect moves 27 between the first ring and the second, and
# 059's plain caption 39 - both of those cleared the step on their own, and
# both are wrong.
EDGE_FLAT = 20

# A GLOW is the other shape the same bands can make: not a plateau and a cliff
# but a long smooth decay. Measured as the step off the settled paper at each
# ring, over six pages:
#
#   plain dialogue            33  0  0  0        one blended rim, then nothing
#   066's outlined effects    62 71 64 17        a plateau, then a cliff
#   029's glowing effects    125 94 78 56 36     a decay that goes on
#   011's cream halo          80 20 18  5        a decay that stops
#
# `GLOW_BANDS` is 4 because of the last two lines. 011's halo really is a soft
# one and it is a shame to lose it - but the same page's small balloon reads
# 34 35 24 2, which is the balloon's own edge and not a halo at all, and at
# three bands there is no measurement that keeps one and refuses the other.
# Four bands keeps only what nothing else on six pages imitates.
GLOW_MIN = 15            # how far off the paper a ring must still be
GLOW_BANDS = 4           # ...and how many rings must manage it
GLOW_TAIL = 0.2          # the glow ends where it fades to this much of its start

# A DROP SHADOW is the only one of these that is not symmetric: the ink again,
# offset and darker. Everything else round a letter - an outline, a glow, the
# blended rim - sits evenly all the way round, so the centre of what is dark
# outside the letters is the centre of the letters. A shadow moves it.
SHADOW_DARK = 20         # how much darker than the paper counts as shadow
SHADOW_OFF = 1.5         # ...and how far the centre must move, in pixels
# The renderer draws a shadow down and to the right at a fixed 45 degrees -
# see `typesetting.js`, which multiplies `sh_dist` by 0.707 on both axes - so
# one measured anywhere else cannot be drawn. That is not a test here: the
# search below only tries positive offsets, so a shadow up and to the left is
# never found in the first place, and a separate check for the direction would
# be a line no page could ever reach.
SHADOW_HIT = 0.5         # ...and how much of the shifted ink must land on it
SHADOW_MAX = 10          # the furthest offset worth looking for

# One black per chapter. The same ink measures #000000 on one page and #010101
# on the next - JPEG, tone, and the median landing a shade either way - and
# typeset side by side that is two blacks. Anything within this of a colour
# already seen in the run is taken to BE that colour.
#
# Measured across six pages: the blacks span 0 to 4, the whites 0 to 3, and the
# nearest two colours that are genuinely different things are 16 apart. 8 sits
# in the middle of that gap.
SNAP = 8


def _hex(bgr) -> str:
    b, g, r = (int(round(float(c))) for c in bgr[:3])
    return "#%02X%02X%02X" % (max(0, min(255, r)), max(0, min(255, g)),
                              max(0, min(255, b)))


def _rings(mask: np.ndarray, upto: int) -> list:
    """The mask, then the ring at each distance 1..upto outside it."""
    out, prev = [], mask > 0
    for d in range(1, upto + 1):
        k = np.ones((2 * d + 1, 2 * d + 1), np.uint8)
        grown = cv2.dilate((mask > 0).astype(np.uint8), k) > 0
        out.append(grown & ~prev)
        prev = grown
    return out


def _far(img, rings, lo: int, hi: int):
    """The settled colour outside everything: the paper, or the artwork."""
    got = [img[b] for b in rings[lo:hi] if b.any()]
    return np.median(np.concatenate(got), 0) if got else None


def glyph_ink(img, block, paper) -> np.ndarray:
    """The letters inside a block, whichever way round they are printed.

    Twice, because writing with a ring round it is THREE populations and not
    two: the paper, the outline, and the letters. One split says "not paper"
    and hands back the letters WITH their outline stuck to them - which on
    066's dark red 파 in its white ring measures the average of red and white,
    a colour that is on no part of the page. The second split is only taken
    when the two halves are far apart (`INK_SPLIT`); on ordinary writing there
    is nothing to separate and it is left alone.
    """
    d = np.abs(img.astype(np.int16) - np.asarray(paper, np.int16)).max(2)
    d = np.where(block > 0, d, 0).astype(np.uint8)
    inside = d[block > 0]
    if inside.size < MIN_GLYPH:
        return np.zeros(d.shape, bool)
    t, _ = cv2.threshold(inside, 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # `>` and not `>=`: OpenCV's Otsu returns the value BELOW the cut, so on
    # letters ringed in white the two populations come back as {63, 192} with
    # t = 63, and `>=` keeps the ring.
    marked = (d > float(t)) & (d >= INK_FLOOR) & (block > 0)
    m = d[marked]
    if m.size >= MIN_GLYPH:
        t2, _ = cv2.threshold(m, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        near, far = m[m <= t2], m[m > t2]
        if near.size and far.size and \
                float(far.mean() - near.mean()) >= INK_SPLIT:
            # ...and the near half has to sit AROUND the far half rather than
            # mixed through it. A letter filled with a gradient splits just as
            # readily as a letter inside a ring - 066's 파 runs from black to
            # #750104 - and taking that split there keeps the darkest core and
            # throws the gradient away. A ring is on the outside: hardly any
            # of it survives eroding the marked shape.
            side = marked & (d <= float(t2))
            inner = cv2.erode(marked.astype(np.uint8),
                              np.ones((5, 5), np.uint8)) > 0
            if float((side & inner).sum()) <= NEAR_INSIDE * max(1, side.sum()):
                return marked & (d > float(t2))
    return marked


def measure_region(img, block) -> dict:
    """What the writing in `block` is painted with. {} when it cannot tell.

    Keys are the ones the typesetter already draws with: `fg`, and `fg1`/`fg2`/
    `grad_angle` where the fill really is a gradient, and `edge`/`stroke` where
    there really is a ring round the letters.
    """
    if img is None or block is None or not (block > 0).any():
        return {}
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    out_rings = _rings(block, 11)
    paper = _far(img, out_rings, 6, 11)
    if paper is None:
        return {}
    ink = glyph_ink(img, block, paper)
    # The rim of a glyph is a blend of the glyph and whatever is behind it, so
    # it is dropped before anything is measured. On thin writing there is
    # nothing left after that, and the rim is all there is.
    core = cv2.erode(ink.astype(np.uint8), np.ones((3, 3), np.uint8))
    if int(core.sum()) < MIN_GLYPH:
        core = ink.astype(np.uint8)
    ys, xs = np.nonzero(core)
    if len(ys) < MIN_GLYPH:
        return {}
    px = img[ys, xs].astype(np.float64)
    style = {"fg": _hex(np.median(px, 0))}

    # ---- the gradient, as a straight line fitted through the colour
    A = np.stack([xs, ys, np.ones_like(xs)], 1).astype(np.float64)
    coef, *_ = np.linalg.lstsq(A, px, rcond=None)
    resid = ((px - A @ coef) ** 2).sum()
    spread = ((px - px.mean(0)) ** 2).sum()
    r2 = 1.0 - resid / spread if spread > 1e-9 else 0.0
    gx, gy = float(coef[0].mean()), float(coef[1].mean())
    t = xs * gx + ys * gy
    lo = np.median(px[t <= np.percentile(t, 10)], 0)
    hi = np.median(px[t >= np.percentile(t, 90)], 0)
    span = float(np.abs(lo - hi).max())
    if r2 >= GRAD_FIT and span >= GRAD_SPAN:
        # The app's angle is 0 = top to bottom, clockwise from there, and the
        # first stop sits at the low end of the axis. See `typesetting.js`,
        # which paints (sin a, cos a) and puts `fg1` at the minimum.
        # float(), not numpy's. `np.float64` subclasses `float` so JSON does
        # take it, which is exactly why this is worth pinning: it survives the
        # round trip out to the project file and comes back a plain float, so
        # anything comparing types across a save is quietly asymmetric.
        style["grad_angle"] = round(
            float(np.degrees(np.arctan2(gx, gy))) % 360.0, 1)
        style["fg1"], style["fg2"] = _hex(lo), _hex(hi)

    # ---- the ring round the letters
    ink_rings = _rings(ink.astype(np.uint8) * 255, EDGE_MAX + 6)
    beyond = _far(img, ink_rings, EDGE_MAX + 1, EDGE_MAX + 6)
    if beyond is not None:
        wide, band = 0, []
        for d in range(1, EDGE_MAX + 1):
            b = ink_rings[d - 1]
            if b.sum() < 20:
                break
            c = np.median(img[b], 0)
            # Ring 1 is the anti-aliased rim of the glyph, and on every
            # letter ever printed it is a blend that steps a long way off the
            # paper - white on black blends to mid-grey, which is 175. It is
            # never evidence on its own, and `wide >= 2` below is what says so.
            if float(np.abs(c - beyond).max()) < EDGE_STEP:
                break
            if band and float(np.abs(c - band[0]).max()) > EDGE_FLAT:
                break                    # a falloff, not a ring
            wide = d
            band.append(c)
        if wide >= 2:
            style["edge"] = _hex(np.median(np.stack(band), 0))
            style["stroke"] = int(wide)
        else:
            style.update(_glow(img, ink_rings, beyond))
    style.update(_shadow(img, ink, paper))
    return style


def _glow(img, rings, beyond) -> dict:
    """A halo: a step off the paper that decays instead of stopping."""
    if beyond is None:
        return {}
    steps, cols = [], []
    for b in rings:
        if b.sum() < 20:
            break
        c = np.median(img[b], 0)
        cols.append(c)
        steps.append(float(np.abs(c - beyond).max()))
    if len(steps) < GLOW_BANDS:
        return {}
    # From the SECOND ring, because the first is the blended rim of the glyph
    # and it is huge on every letter - white on black blends to 175.
    tail = steps[1:]
    if tail[0] < GLOW_MIN:
        return {}
    if len(tail) < GLOW_BANDS - 1 or tail[GLOW_BANDS - 2] < GLOW_MIN:
        return {}
    size = 1
    for d, v in enumerate(tail, start=2):
        if v >= GLOW_TAIL * tail[0]:
            size = d
    return {"glow": _hex(np.median(np.stack(cols[1:3]), 0)),
            "glow_size": int(size)}


def _shadow(img, ink, paper) -> dict:
    """The ink again, offset and darker. The one asymmetric thing round a
    letter, which is exactly how it is told from a glow."""
    near = cv2.dilate(ink.astype(np.uint8),
                      np.ones((17, 17), np.uint8)) > 0
    out = near & ~ink
    if out.sum() < MIN_GLYPH:
        return {}
    lum = img.astype(np.float64).mean(2)
    dark = out & (lum <= float(np.asarray(paper, float).mean()) - SHADOW_DARK)
    if dark.sum() < MIN_GLYPH:
        return {}
    iy, ix = np.nonzero(ink)
    dy, dx = np.nonzero(dark)
    off = (float(dx.mean() - ix.mean()), float(dy.mean() - iy.mean()))
    dist = float(np.hypot(*off))
    if dist < SHADOW_OFF:
        return {}
    # ...and it has to be the LETTERS again, not merely something dark lying
    # off to one side. Shift the ink and see how much of where it lands is
    # dark: a shadow is a copy of the letters, so nearly all of it is. A
    # balloon's own black outline is dark and sits down-and-right as often as
    # not, and almost none of it lines up - which is what this refuses, and
    # what stopped three plain bubbles claiming a shadow they do not have.
    #
    # The centroid of the dark only ESTIMATES the offset, because the part of
    # the shadow hidden under the letters is not in it and drags the answer
    # outwards. So it is a starting point and the neighbours are tried too.
    # Cropped to the writing first, so trying every offset is a hundred small
    # shifts and not a hundred page-sized ones.
    y0, y1 = max(0, iy.min() - 12), min(ink.shape[0], iy.max() + 13)
    x0, x1 = max(0, ix.min() - 12), min(ink.shape[1], ix.max() + 13)
    ci, cd = ink[y0:y1, x0:x1], dark[y0:y1, x0:x1]
    best, bx, by = 0.0, 0, 0
    for sy in range(1, SHADOW_MAX + 1):
        for sx in range(1, SHADOW_MAX + 1):
            moved = np.roll(np.roll(ci, sy, 0), sx, 1)
            moved[:sy] = False
            moved[:, :sx] = False
            land = moved & ~ci
            if land.sum() < MIN_GLYPH:
                continue
            hit = float((land & cd).sum()) / float(land.sum())
            if hit > best + 0.02:        # a nearer offset wins a near-tie
                best, bx, by = hit, sx, sy
    if best < SHADOW_HIT:
        return {}
    dist = float(np.hypot(bx, by))
    if dist < SHADOW_OFF:
        return {}
    return {"shadow": _hex(np.median(img[dark], 0)),
            "sh_dist": round(dist, 1),
            "sh_blur": int(max(1, round(dist)))}


def block_of(page, region, owner=None, index: int = -1) -> np.ndarray | None:
    """The area this region's writing stands in, as a mask of the page.

    The pixels the region OWNS where there are any - two boxes that overlap
    must not measure each other's letters - and the box itself otherwise,
    which is the usual case for a sound effect the detector gave no mask.
    """
    img = getattr(page, "image", None)
    if img is None:
        return None
    if owner is not None and index >= 0:
        m = (owner == index)
        if m.any():
            return m.astype(np.uint8) * 255
    m = np.zeros(img.shape[:2], np.uint8)
    x, y, w, h = (int(v) for v in region.bbox)
    m[max(0, y):max(0, y + h), max(0, x):max(0, x + w)] = 255
    return m if m.any() else None


def _snap(seen: dict, value: str) -> str:
    """The colour this one really is, given what the chapter has said so far.

    `seen` is a tally kept for the length of a run, so page 9's #000000 comes
    back as page 1's #010101 rather than as a second black. The most-used
    match wins, which is what stops a chain of near-misses walking the colour
    across the chapter one shade at a time.
    """
    if seen is None:
        return value
    best = None
    for c, n in seen.items():
        if _dist(c, value) <= SNAP and (best is None or n > seen[best]):
            best = c
    if best is None:
        seen[value] = seen.get(value, 0) + 1
        return value
    seen[best] += 1
    return best


def _dist(a: str, b: str) -> int:
    try:
        return max(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16))
                   for i in (1, 3, 5))
    except Exception:
        return 999


def measure_page(page, seen: dict | None = None) -> int:
    """Fill in the colours for every region on a page. Returns how many.

    Run at the END of the read step, which is the last moment the ORIGINAL
    letters are still on the page - cleaning wipes them, and by the time the
    typesetter runs there is nothing left to measure.

    A colour already in the override is a colour somebody chose, and is left
    exactly as it is. This only ever fills in blanks.
    """
    from .ocr import _pixel_owner
    img = getattr(page, "image", None)
    regions = list(getattr(page, "regions", None) or [])
    if img is None or not regions:
        return 0
    owner, index_of = _pixel_owner(page)
    done = 0
    for r in regions:
        block = block_of(page, r, owner, index_of.get(r.id, -1))
        if block is None:
            continue
        try:
            got = measure_region(img, block)
        except Exception:
            continue
        if not got:
            continue
        for k in ("fg", "fg1", "fg2", "edge", "glow", "shadow"):
            if k in got:
                got[k] = _snap(seen, got[k])
        ov = dict(getattr(r, "layout_override", None) or {})
        fresh = {k: v for k, v in got.items()
                 if ov.get(k) in (None, "", 0)}
        if not fresh:
            continue
        ov.update(fresh)
        r.layout_override = ov
        done += 1
    return done
