"""Erase source text.

Most manga bubbles have a flat white interior. For those, filling with the
modal background colour is instant and cleaner than any neural inpainter.
Reserve the expensive path for text over artwork, gradients and screentone.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import kinds as _kinds
from .models import Page, TextRegion

INK = 128              # pixel <= this counts as ink
BRIGHT = 200           # ...and pixel >= this, on a light-on-dark panel
OUTSIDE_SHARE = 0.35   # ink mostly beyond the region is art, not typesetting
GROW_PX = 9            # slack between the detected interior and the real bubble
RECT_FILL = 0.97       # mask area / bbox area above this counts as a rectangle
DILATE_PX = 3          # anti-aliased glyph edges leave grey haze otherwise
FLAT_STD = 12.0        # background std below this counts as flat
FLAT_LIGHT = 200.0     # ...and this pale as well, to be the local fill's own job
# What counts as a FULLY WHITE bubble — the only thing the local fill keeps once
# a model is configured. lee: *"make it so that the local celener is only used
# fro fully white bubbles every thing else should be handles by the ai
# clenner"*. Both halves matter: `FLAT_STD` at 12 admits paper grain and light
# screentone, and `FLAT_LIGHT` at 200 admits pale grey and the lighter tones —
# and every one of those is a page the model does better and the flat fill
# leaves a patch on.
WHITE_STD = 5.0        # a real balloon interior is very nearly one colour
WHITE_LEVEL = 236.0    # ...and that colour is white, not pale
TONE_PEAK_RATIO = 3.0  # FFT peak / mean, above this looks like screentone
NEURAL_PAD = 2         # slack on the mask the LOCAL methods are given
MODEL_PAD = 6          # ...and on the one the MODEL is given, which is bigger
#
# The model reconstructs the area it is handed and copies nothing, so a mask
# that stops at the glyph's own edge leaves the anti-aliased rim of every stroke
# standing — the faint outlines and half-erased letters in lee's crops. Erasers
# built on LaMa are normally fed the text mask grown by 8-15px for exactly this
# reason. It is a trade: tone and line work within `MODEL_PAD` of a stroke are
# redrawn rather than kept, which the model is good at and a local fill is not.
# The local path keeps the tight mask, where the same generosity would smear.
# The fence at the end of inpaint_page bounds both to the box and its doorstep.
NEURAL_CTX = 96        # pixels of surrounding page handed to the model as context
HALO_REACH = 9         # how far past the hard mask a glyph's haze can carry
HALO_TOL = 4           # grey levels under a flat background that still read as ink
TONE_REACH = 6         # the same sweep on texture, kept shorter — see _local_bg
TONE_TOL = 10          # and stricter, because artwork is legitimately dark
GHOST_TOL = 6          # ink still this much darker than its surroundings = ghost
GLYPH_STROKE = 3       # written strokes are this thick at least; tone dots are not
GLYPH_MIN_AREA = 60    # ...and a letter covers at least this much, however thin
GLYPH_MIN_SIDE = 5     # ...and is at least this wide and this tall
MASK_MAX_SHARE = 0.55  # a "text" mask covering more of its region than this is not text

# The cleaner's own version. A finished plate is cached on disk and reused
# forever, and its name is built from the page, the boxes and the settings —
# none of which change when THIS FILE does. So every improvement to the cleaning
# arrived invisible: the pages had plates already, the plates were reused, and
# the answer to "did it get better" was the picture from before the change. lee,
# after a round of fixes: *"nothing vhanged"*.
#
# Bump this on any change to how a page is cleaned. Every plate made by the old
# code retires itself the moment the new code loads.
# 2026-07-31-a: the local fill now keeps only FULLY WHITE bubbles once a model
# is configured (see WHITE_STD / WHITE_LEVEL). Every page cleaned before that
# still had a plate made by the old rule, and a plate is reused for ever — so
# without this bump the change would have arrived invisible on exactly the
# pages lee was looking at.
ALGO = "2026-07-31-a"


def ink_and_background(gray: np.ndarray, area: np.ndarray,
                       fallback: np.ndarray
                       ) -> tuple[np.ndarray, float, bool]:
    """Find the typesetting inside `area`, whichever way round the tones are.

    Assuming dark text on a light background wrecks white-on-black panels: the
    whole dark background gets treated as text, erased, and filled with the
    colour of the typesetting. Split the region in two by Otsu instead, and let
    the rim decide which side is the background — a bubble or panel touches
    its own edge, the words in the middle of it do not.

    Returns the glyph mask, the background level to fill with, and whether the
    tones were the other way round (light typesetting on a dark panel).
    """
    vals = gray[area]
    if vals.size < 40:
        # Too little to split. It used to return two values here and three
        # everywhere else, so a region with a placement area under 40 pixels
        # took the WHOLE PAGE down with a ValueError halfway through cleaning —
        # the page came back 500 and nothing said why. Nothing that small is
        # inverted, so the answer is "the detector's own mask, the median tone,
        # the usual way round".
        return (fallback,
                float(np.median(vals)) if vals.size else 255.0,
                False)

    t, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = area & (gray <= t)
    light = area & (gray > t)

    rim = area & ~(cv2.erode(area.astype(np.uint8),
                             np.ones((7, 7), np.uint8)) > 0)
    bg_is_dark = int((dark & rim).sum()) >= int((light & rim).sum())

    ink = light if bg_is_dark else dark
    bg = dark if bg_is_dark else light

    # Typesetting is a minority of its own panel. If "text" came out huge the
    # split is meaningless — a picture, not words — so leave it alone.
    if not ink.any() or ink.sum() > 0.55 * area.sum():
        return fallback, float(np.median(gray[area])), False
    level = float(np.median(gray[bg])) if bg.any() else float(np.median(vals))
    return ink, level, bool(bg_is_dark)


def _letterlike(mask: np.ndarray, min_stroke: int = GLYPH_STROKE) -> np.ndarray:
    """Drop everything in `mask` too thin to be a written stroke.

    This is only for a mask that came from a blind light/dark split rather than
    from the text detector. On a black panel the light side of that split is the
    SCREENTONE as well as the words, and a field of dots dilated by the few
    pixels a glyph edge needs is the whole panel — which is then handed to the
    inpainter as "text" and comes back as a solid rectangle. The dots are the
    one thing that reliably tells them apart: typesetting is drawn with a brush
    and tone is not.

    Opening with a disc erases anything thinner than the disc. Components with
    something left are kept WHOLE, so a stroke keeps its thin tail and its
    anti-aliased edge; a dot with no thick part anywhere keeps nothing.
    """
    m = _u8(mask)
    if not m.any():
        return m
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * min_stroke + 1,) * 2)
    seed = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    if not seed.any():
        # Nothing in here is thick enough to be a brush stroke. That is a
        # statement about the whole region, not about which parts to drop, and
        # the callers below have their own guard for it.
        return m
    n, lab = cv2.connectedComponents(m, 8)
    keep = set(np.unique(lab[seed > 0])) - {0}
    # ...and anything big enough to be a letter even though it is thin. The
    # opening above is sized for the strokes of DISPLAY type; a column of small
    # kana on the same panel is drawn thinner, loses every component to it, and
    # comes out of the cleaner untouched — half a page of text still standing
    # beside a bubble that cleaned perfectly. A screentone dot is a handful of
    # pixels; a glyph is not, whatever its stroke width.
    if n > 1:
        stats = cv2.connectedComponentsWithStats(m, 8)[2]
        for li in range(1, n):
            if li in keep:
                continue
            w_, h_, area = (int(stats[li, cv2.CC_STAT_WIDTH]),
                            int(stats[li, cv2.CC_STAT_HEIGHT]),
                            int(stats[li, cv2.CC_STAT_AREA]))
            if area >= GLYPH_MIN_AREA and min(w_, h_) >= GLYPH_MIN_SIDE:
                keep.add(li)
    return np.isin(lab, list(keep)).astype(np.uint8) if keep else m



GLYPH_REACH = 8        # how far past its box a caught stroke may be followed


def _complete_strokes(erase: np.ndarray, gray: np.ndarray, inverted: bool,
                      bbox) -> np.ndarray:
    """Finish the strokes the box cut in half, and nothing else.

    The mask is clipped at the box, so a glyph drawn a little past it comes out
    erased up to the cut and left standing after it — the stubs and rims in
    lee's screenshots, and the reason "the text is non negotiable" was not being
    met. What is added here is ink in the DOORSTEP — the ring of `GLYPH_REACH`
    pixels just outside the box, never inside it — that is joined to ink the box
    already caught. A stroke leaving the box is completed; line work crossing
    the middle of the box, which may well touch a glyph, is not adopted, because
    nothing inside the box is added at all.
    """
    m = _u8(erase)
    if not m.any():
        return m
    x, y, w, h = (int(v) for v in bbox)
    H, W = gray.shape[:2]
    box = np.zeros((H, W), bool)
    box[max(0, y):y + h, max(0, x):x + w] = True
    room = np.zeros((H, W), bool)
    room[max(0, y - GLYPH_REACH):y + h + GLYPH_REACH,
         max(0, x - GLYPH_REACH):x + w + GLYPH_REACH] = True
    doorstep = room & ~box
    if not doorstep.any():
        return m

    full = ((gray >= BRIGHT) if inverted else (gray <= INK))
    cand = (full & doorstep).astype(np.uint8)
    if not cand.any():
        return m
    # which pieces of doorstep ink touch what the box caught
    _, lab = cv2.connectedComponents(
        ((full & room).astype(np.uint8)), 8)
    touching = set(np.unique(lab[(m > 0) & box])) - {0}
    if not touching:
        return m
    add = np.isin(lab, list(touching)) & doorstep
    out = m.copy()
    out[add] = 255
    return out


def glyphs_only(region, text_mask: np.ndarray,
                gray: np.ndarray | None = None,
                bright_ink: bool = False) -> np.ndarray:
    """Drop ink that continues outside the region.

    A box drawn across a bubble catches part of the bubble's own border, and
    erasing that leaves the outline hacked apart. Typesetting sits wholly inside
    its region; a border or a piece of artwork carries on past the edge.

    Deciding that needs the whole page, not the masked crop: the crop has
    already been cut at the boundary, so everything looks self-contained. With
    `gray` we label the ink across the page and drop any component that has
    pixels outside the region.
    """
    area = region.place_mask()
    if area is None or gray is None:
        return text_mask

    # Only rectangular masks need this. A detected bubble mask follows the
    # interior and stops short of the outline, so its ink is all typesetting.
    # A hand-drawn rectangle is the case that slices through a bubble border,
    # and it is also the only shape where "fills its own bounding box" holds.
    # Every region on the page asks this question, so ask it in OpenCV rather
    # than by materialising a page-sized boolean array to add up.
    au8 = _u8(area)
    _, _, bw, bh = cv2.boundingRect(au8)
    if bw == 0 or bh == 0:
        return text_mask
    if cv2.countNonZero(au8) < RECT_FILL * bw * bh:
        return text_mask
    ink_in = (text_mask > 0)
    if not ink_in.any():
        return text_mask

    # The detected mask is the bubble INTERIOR and sits a little inside the
    # true white area, so typesetting often pokes a few pixels past it. Test
    # containment against a slightly grown mask, or ordinary text reads as
    # artwork and never gets cleaned.
    grown = cv2.dilate((area > 0).astype(np.uint8),
                       np.ones((GROW_PX, GROW_PX), np.uint8)) > 0

    # Which way round the tones are matters here: on a white-on-black panel the
    # typesetting is the LIGHT side, and labelling the dark side instead means
    # every component test below is run on the panel rather than on the words,
    # so nothing is ever dropped and artwork running out of the box is erased
    # along with the text.
    full = ((gray >= BRIGHT) if bright_ink else (gray <= INK)).astype(np.uint8)
    n, lab = cv2.connectedComponents(full, 8)
    inside_labels = set(np.unique(lab[ink_in])) - {0}

    keep = np.zeros_like(text_mask)
    for li in inside_labels:
        comp = lab == li
        total = int(comp.sum())
        outside = int((comp & ~grown).sum())
        # A letter that merely brushes the bubble outline joins it as one
        # component, so "touches the edge" is too strict. What marks a border
        # or a piece of artwork is that most of it lies outside the region.
        if total and outside > OUTSIDE_SHARE * total:
            continue
        keep[comp & ink_in] = 255

    if int((keep > 0).sum()) < 0.05 * int(ink_in.sum()):
        # Nothing survived — the box is probably tight around text touching its
        # edge. Erasing nothing at all is worse than the original problem.
        return text_mask
    return keep


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _u8(m: np.ndarray) -> np.ndarray:
    """A mask OpenCV will take, without copying a whole page if avoidable."""
    if m.dtype == np.uint8:
        return m
    if m.dtype == bool:
        return m.view(np.uint8)
    return (m > 0).astype(np.uint8)


def _window(shape, *masks) -> tuple[slice, slice]:
    """A padded box around the given masks, as a slice pair.

    A bubble occupies about one percent of a page, but every step of cleaning
    it was scanning all thirty megapixels — twenty-odd regions each dilating,
    thresholding and comparing the entire scan. Doing the same arithmetic
    inside the box the region actually sits in is the same result and about
    fifty times less of it, which is most of the wait before a cleaned page
    appears. The padding leaves room for every dilation and ring the region's
    own measurements reach for.
    """
    H, W = shape[:2]
    x0, y0, x1, y1 = W, H, 0, 0
    for m in masks:
        if m is None:
            continue
        x, y, w, h = cv2.boundingRect(_u8(m))
        if w == 0 or h == 0:
            continue
        x0, y0 = min(x0, x), min(y0, y)
        x1, y1 = max(x1, x + w), max(y1, y + h)
    if x1 <= x0 or y1 <= y0:
        return slice(0, H), slice(0, W)
    pad = 2 * HALO_REACH + 8
    return (slice(max(0, y0 - pad), min(H, y1 + pad)),
            slice(max(0, x0 - pad), min(W, x1 + pad)))


def _bg_level(gray: np.ndarray, area: np.ndarray, ink: np.ndarray, bg,
              spare: np.ndarray | None = None) -> float:
    """The background's own grey level, measured well clear of the typesetting.

    Averaging the whole non-ink part of the region includes the haze, which
    drags the level down towards the ink and makes the haze look like
    background. Stand back from the strokes first.
    """
    clear = (area > 0) & (_dilated(ink, DILATE_PX + HALO_REACH) == 0)
    if spare is not None and spare.any():
        clear &= ~(_dilated(spare.astype(np.uint8)) > 0)
    if int(clear.sum()) >= 30:
        return float(np.median(gray[clear]))
    return float(np.mean(bg))


def _dilated(mask: np.ndarray, px: int = DILATE_PX) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return cv2.dilate(_u8(mask), k, iterations=1)


def _local_bg(gray: np.ndarray, bright_ink: bool = False,
              reach: int = TONE_REACH) -> np.ndarray:
    """What the background would be under the typesetting, pixel by pixel.

    The haze sweep only ever worked on flat bubbles, because it needs something
    to call "the background" and a flat bubble has exactly one. On screentone,
    on a gradient, on artwork, there is no single level — so the sweep was
    skipped and the mask fell back to a fixed dilation, which is a guess at
    stroke width that guesses low. That is why a bubble over tone still shows
    the shape of the words it used to hold.

    A background does not need to be flat to be knowable. Closing the image
    with a kernel wider than a stroke removes the strokes and leaves what was
    around them, so every pixel gets its own local level and the same "darker
    than its background means ink" test works on a gradient as well as on
    white. Opening does the mirror job for white typesetting on a dark panel.

    int16 rather than uint8 so callers can subtract a tolerance without
    wrapping around at zero.
    """
    px = 2 * max(2, reach) + 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px, px))
    op = cv2.MORPH_OPEN if bright_ink else cv2.MORPH_CLOSE
    return cv2.morphologyEx(gray, op, k).astype(np.int16)


def _grow(win: tuple[slice, slice], shape, px: int) -> tuple[slice, slice]:
    """The same window with more of the page around it."""
    ys, xs = win
    H, W = shape[:2]
    return (slice(max(0, ys.start - px), min(H, ys.stop + px)),
            slice(max(0, xs.start - px), min(W, xs.stop + px)))


def _spared(base: np.ndarray, kept: np.ndarray, gray: np.ndarray,
            bright_ink: bool) -> np.ndarray:
    """Whole components `glyphs_only` decided to leave alone.

    Protecting only the exact pixels it dropped is not enough: a bubble outline
    is one connected stroke, and the halo sweep would eat the half of it that
    the detector's mask never covered. Take the component.
    """
    if kept is base:
        return np.zeros(gray.shape, bool)   # nothing was filtered at all
    dropped = (base > 0) & (kept == 0)
    if not dropped.any():
        return np.zeros(gray.shape, bool)
    solid = ((gray > INK) if bright_ink else (gray <= INK)).astype(np.uint8)
    _, lab = cv2.connectedComponents(solid, 8)
    labels = set(np.unique(lab[dropped])) - {0}
    if not labels:
        return dropped
    return np.isin(lab, list(labels))


def _with_halo(gray: np.ndarray, area: np.ndarray, hard: np.ndarray,
               spare: np.ndarray, bg_level, bright_ink: bool = False,
               reach_px: int = HALO_REACH, tol: int = HALO_TOL,
               touching: bool = False) -> np.ndarray:
    """Widen a fill until it swallows the glyph's anti-aliased haze.

    A fixed dilation is a guess about stroke width, and on a large scan it
    guesses low. What survives is a faint outline of every character — too
    light to read as text, too dark to read as clean, and unmistakable once the
    bubble around it is pure white. No guessing is needed: anything measurably
    darker than the background, close to ink already being erased, IS that ink.

    `bg_level` is that background, and it is either one number (a flat bubble
    has only one) or a whole array from `_local_bg` (screentone, gradients,
    artwork — where the level is different in every part of the region). The
    test is the same either way, which is the point.

    `spare` is what `glyphs_only` deliberately refused to erase — the bubble
    outline, artwork crossing the box — and the haze sweep must not quietly
    take it back.

    `touching` keeps only haze that is joined to a stroke. On a flat bubble
    anything dark near the words is the words, so this is off; on screentone
    and artwork it is the difference between taking a stroke's own skirt and
    taking every dot that happens to lie beside it.
    """
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach_px + 1,) * 2)
    reach = cv2.dilate((hard > 0).astype(np.uint8), k) > 0
    off_bg = (gray > bg_level + tol) if bright_ink else (gray < bg_level - tol)
    halo = reach & (area > 0) & off_bg
    if spare is not None and spare.any():
        halo &= ~spare
    both = ((hard > 0) | halo).astype(np.uint8)
    if not touching:
        return both
    n, lab = cv2.connectedComponents(both, 8)
    keep = set(np.unique(lab[hard > 0])) - {0}
    if not keep:
        return both
    return np.isin(lab, list(keep)).astype(np.uint8)


def ghost_delta(before: np.ndarray, after: np.ndarray, ink: np.ndarray,
                bright_ink: bool = False) -> float:
    """How much of the typesetting is still showing, in grey levels.

    Measured against the ink's own immediate surroundings rather than against
    white, so it means the same thing on a flat bubble, on screentone and on
    artwork: if the text is gone, the pixels where it used to be are as dark as
    the ring around them and this is ~0. A positive number is a ghost, and how
    big it is, is how visible it is.
    """
    m = (ink > 0).astype(np.uint8)
    core = cv2.erode(m, np.ones((3, 3), np.uint8)) > 0
    if core.sum() < 20:
        core = m > 0
    ring = (cv2.dilate(m, np.ones((2 * HALO_REACH + 5,) * 2, np.uint8)) > 0) \
        & ~(_dilated(m, HALO_REACH) > 0)
    if core.sum() < 20 or ring.sum() < 20:
        return 0.0
    sign = -1.0 if bright_ink else 1.0

    def gap(im: np.ndarray) -> float:
        return sign * float(np.median(im[ring].astype(np.float32))
                            - np.median(im[core].astype(np.float32)))

    # `before` decides WHERE the ink was; `after` decides whether it is still
    # there. Comparing after-to-after only would call a perfectly filled hole
    # and an untouched page equally clean.
    if gap(before) < GHOST_TOL:
        return 0.0                       # never was dark: nothing to leave behind
    return gap(after)


def background_is_flat(img: np.ndarray, region: TextRegion,
                       ink: np.ndarray | None = None,
                       spare: np.ndarray | None = None
                       ) -> tuple[bool, np.ndarray]:
    """Std of the background pixels inside the region.

    `ink` is the mask actually being erased; on a white-on-black panel that is
    not the same thing as `region.text_mask`, and using the wrong one makes a
    striped panel look flat and get painted over in one colour.

    Stand well clear of the strokes before measuring. A scan spreads every
    stroke over several pixels, and sampling that skirt as though it were
    background is what makes a plain white bubble measure as textured — which
    then sends it down the screentone or neural path, where the same skirt
    survives as the faint outline of the words. Fall back to a tight ring only
    when the region is too small to stand back in.

    `spare` is ink the region contains but is not erasing — the slice of bubble
    outline a hand-drawn box catches. That is not background either. Counting
    it as background made every such box measure as textured and sent a plain
    white bubble to the inpainter, which is both slower and worse than filling
    it with white.
    """
    area = region.place_mask()
    if area is None:
        return False, np.zeros(3)
    ink = region.text_mask if ink is None else ink
    sl = _window(area.shape, area, ink)
    flat, bg, _ = _flat_from(img[sl], area[sl], ink[sl],
                             None if spare is None else spare[sl])
    return flat, bg


def _flat_from(img: np.ndarray, area: np.ndarray, ink: np.ndarray,
               spare: np.ndarray | None) -> tuple[bool, np.ndarray, float]:
    """Is the background behind this text one colour, what colour, and how one
    colour. The third answer is what tells a white balloon from a pale one with
    tone in it — see WHITE_STD.

    The sample stands off the ink by `DILATE_PX + HALO_REACH`, which is the
    distance the halo fill can reach, so the question is asked over the paper
    the answer will be used to paint.

    There used to be a fallback: when that left fewer than thirty pixels, ask
    again with a three-pixel stand-off instead. It is gone, and this is the
    fix for lee's *"it jusm amde a white box insated of matching the
    backgroung"* — a column of vertical Japanese on artwork.

    A column's box is thirty pixels wide. The ink grown by twelve covers ALL
    of it, so the proper sample is not small, it is EMPTY — measured on a
    fixture cut to his: zero pixels at twelve, and the fallback then handed
    back a three-pixel rim hugging the letters. On his page that rim is the
    white cloak the words are printed on, so the rim says "flat, and white",
    and that verdict licenses `_with_halo` to paint white out to nine pixels,
    and `_sweep_ghosts` to widen it to fifteen — across the hatched hood
    beside the column. The least representative sample on the page, used to
    justify the widest fill.

    "I cannot see enough background to tell" is not "the background is flat".
    It is now answered as what it is, and a region nobody can measure goes to
    the model, which is where lee wants the hard ones anyway.
    """
    keep_out = None if spare is None else (_dilated(spare.astype(np.uint8)) > 0)
    inside = (area > 0) & (_dilated(ink, DILATE_PX + HALO_REACH) == 0)
    if keep_out is not None:
        inside &= ~keep_out
    if inside.sum() < 30:
        return False, np.zeros(3), 255.0
    px = img[inside]
    spread = float(px.std(axis=0).mean())
    return bool(spread < FLAT_STD), px.mean(axis=0), spread


def is_screentone(img: np.ndarray, region: TextRegion) -> bool:
    """Regular dot patterns get smeared by LaMa; detect and avoid."""
    x, y, w, h = region.bbox
    patch = img[y:y + h, x:x + w]
    if patch.size == 0 or min(patch.shape[:2]) < 24:
        return False
    g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g -= g.mean()
    mag = np.abs(np.fft.fftshift(np.fft.fft2(g)))
    cy, cx = np.array(mag.shape) // 2
    mag[cy - 2:cy + 3, cx - 2:cx + 3] = 0   # kill DC
    return bool(mag.max() / max(1e-6, mag.mean()) > TONE_PEAK_RATIO * 20)


def inpaint_page(page: Page, neural=None, neural_all: bool = False) -> np.ndarray:
    """`neural(img, mask) -> img` is an optional LaMa-style callable.

    Normally only TEXTURED backgrounds (screentone, art) go to the inpainter;
    flat white bubbles are filled instantly with their background colour. With
    `neural_all=True` every cleaned region — flat bubbles included — is routed
    through `neural` instead, for people who want the model to do all of it.

    The model is called once per REGION, on a crop with `NEURAL_CTX` pixels of
    page around it, rather than once on the whole page. A hosted inpainter
    handed a full page splits the mask into connected pieces itself and runs
    once per piece — which is once per GLYPH, each seeing a window too small to
    tell what the background was doing. A bubble at a time is both far fewer
    calls and a far better view, and it means a change to one bubble only
    re-runs that bubble.
    """
    out = page.image.copy()
    gray = _gray(page.image)
    hard_mask = np.zeros(page.image.shape[:2], np.uint8)
    # Every region that was actually erased, so the finished plate can be
    # checked for leftovers. Cleaning is a chain of guesses — where the ink is,
    # how wide the strokes are, which fill to use — and the one thing that is
    # not a guess is looking at the result.
    done: list[dict] = []
    # With no model to hand it to, screentone is copied rather than inpainted:
    # Telea smears a regular dot pattern into grey mush, so those regions are
    # healed one at a time by shift_fill, which slides in REAL dots from nearby.
    # That is a stand-in for a model, not a preference — a hosted inpainter,
    # when there is one, is given the tone as well. Copying a block of dots
    # only holds while the pattern is uniform, and it is a gradient exactly
    # where it matters most, which is where the copied block shows as a patch.
    tone_masks: list[np.ndarray] = []
    # One entry per region the model will be asked about: the crop to send and
    # the mask within it. See the docstring — a bubble at a time, not a page.
    hard_jobs: list[dict] = []

    for r in page.regions:
        # sound effects USED to be skipped wholesale; they are cleaned now too
        # (their typesetting sits on the art like any other text). A specific
        # SFX can still be spared with its per-region "keep original" toggle.
        if r.text_mask is None or getattr(r, "skip_clean", False):
            continue
        full_area = r.place_mask()
        base = r.text_mask
        inverted = False
        if full_area is not None:
            w = _window(gray.shape, full_area, base)
            polar, _, inverted = ink_and_background(
                gray[w], full_area[w] > 0, base[w] > 0)
            # Light text on a dark panel: the detector's mask is the panel
            # itself, so replace it. On an ordinary page leave the mask alone
            # — folding in the Otsu split there erases screentone dots along
            # with the words.
            #
            # The split has no idea what a letter is, though: on a black panel
            # carrying white tone it hands back the dots too, and three pixels
            # of dilation turns a field of dots into a filled box. Keep only
            # what is thick enough to have been drawn with a brush.
            #
            # NOT for a sound effect. `place_mask()` hands an sfx its own INK
            # as its area (models.py) — right for typesetting, ruinous here: the
            # rim vote in `ink_and_background` is then taken over the strokes
            # themselves rather than over anything around them, so it is not a
            # reading of the page at all. On lee's page 12 a plain dark sfx on
            # dark hatched artwork came back `inverted`, the split handed back
            # the bright hatch lines, `_letterlike` kept 206 pixels of that
            # against the detector's 3096, and the sfx was left standing on
            # the page with 7% of it rubbed out. lee: *"the sfx is not gettig
            # clened that the biggest issiue ... ill ratter have it do a bad
            # job then not do it at all"*.
            #
            # And the replacement's own justification cannot apply to an sfx.
            # It exists because a dark-ink detector mask on a black panel is
            # the PANEL; an sfx's mask comes off the segmentation head and is
            # the mark itself, whichever way round the ink runs. `inverted`
            # still stands — the halo, the stroke completion and the ghost
            # check all need to know which way the ink goes — but what to
            # erase is what was found.
            if inverted and _kinds.family_of(r.kind) != "sfx":
                base = np.zeros(gray.shape, bool)
                base[w] = _letterlike(polar) > 0
        # These two read the whole page on purpose: whether a stroke carries on
        # past the region is exactly the question a crop cannot answer.
        base_u8 = _u8(base)
        # lee: *"the cleneer shoud only clean the box that has the text"*.
        #
        # `place_mask()` is the BALLOON — the room the English may use — and it
        # is the right area for measuring a background and for deciding what is
        # flat. It is not the right area to erase: on a wide oval with a narrow
        # column of kana in it, anything else inside that oval was fair game.
        # The erase mask is clipped to the box the writing was found in, plus a
        # couple of pixels so a glyph touching the edge keeps its own rim.
        box_lim = np.zeros(gray.shape, np.uint8)
        bx, by, bw, bh = (int(v) for v in r.bbox)
        box_lim[max(0, by - DILATE_PX):by + bh + DILATE_PX,
                max(0, bx - DILATE_PX):bx + bw + DILATE_PX] = 1
        base_u8 = base_u8 * box_lim
        erase = glyphs_only(r, base_u8, gray, inverted)
        # Every one of the filters above can, on the wrong page, throw away
        # everything: an Otsu split that found no minority side, a letterlike
        # pass with nothing thick enough in it, a containment test that decided
        # the whole box carries on outside. Each is a judgement about WHICH ink
        # to erase, and none of them is a reason to erase none of it — but with
        # an empty mask that is exactly what happened, silently, box after box.
        # Fall back to what the detector actually found inside this region.
        #
        # `found` and not `base_u8`: base_u8 is what is LEFT of the detector's
        # mask after the filters, and the filter most able to empty it runs
        # before it is even built. When `_letterlike` returned nothing, the
        # fallback fell back to nothing and the box was silently left alone.
        # lee, twice, looking at an untouched sound effect: *"ill ratter have
        # it do a bad job then not do it at all"*.
        found = _u8(r.text_mask) * box_lim
        if not erase.any() and found.any():
            erase = found.copy()
            if full_area is not None:
                erase[~(full_area > 0)] = 0
            r.flagged = (r.flagged or "") + \
                " clean: fell back to the detector's own text mask here"
        # A stroke is one thing. Clipping the mask at the box cut every glyph
        # that reached past it in half, and half a glyph erased is a stub left
        # on the page — lee: *"the tetxt is a non negotiable they need to go"*.
        # So each stroke the box caught is completed: its whole connected
        # component is erased, as long as MOST of that component is inside the
        # box (a stroke that is really artwork running through fails that and is
        # left alone), and never further than GLYPH_REACH past the box.
        erase = _complete_strokes(erase, gray, inverted, r.bbox)
        spare = _spared(base_u8, erase, gray, inverted)

        w = _window(gray.shape, full_area, erase)
        g, area = gray[w], (None if full_area is None else full_area[w])
        ink, spare_c = erase[w], spare[w]
        flat, bg, spread = ((False, np.zeros(3), 255.0) if area is None else
                            _flat_from(page.image[w], area, ink, spare_c))
        d = _dilated(ink)
        rec = {"r": r, "win": w, "ink": ink, "inv": inverted,
               "how": "", "flat": None, "job": None}
        done.append(rec)
        # lee: *"the ai shoud be clening those not the cleaner the cleneer only
        # need to cleaner the white bubbles"*. A flat background is the local
        # fill's whole justification — the colour is KNOWN, so the fill is exact
        # and instant, and no model can beat it. But "flat" says nothing about
        # what the area is: the inside of a black panel is flat too, and a solid
        # dark field carrying white typesetting is precisely the hard case he wants
        # the model on. So with a model configured, the local path keeps the
        # thing it is unbeatable at — the pale flat bubble — and everything else
        # goes to the model.
        # With a model configured the local path keeps the one thing it is
        # unbeatable at and nothing else: a FULLY WHITE balloon, where the
        # colour is known exactly, so the fill is exact and instant. Pale grey,
        # light screentone and anything with grain in it go to the model.
        # lee: *"the local celener is only used fro fully white bubbles every
        # thing else should be handles by the ai clenner"*.
        # With no model there is nothing to hand them to, so the old, looser
        # test stands — a flat fill still beats Telea on a pale flat area.
        white = bool(flat and spread <= WHITE_STD
                     and float(np.mean(bg)) >= WHITE_LEVEL)
        # …and it has to BE a bubble. The three tests above are all about the
        # paper immediately round the words, and on lee's page a column of
        # outside text printed on a white cloak passes every one of them: the
        # cloak is white, it is flat, and the sample never reaches the hatched
        # hood eight pixels away. The box is then filled with one colour, which
        # is the white box he keeps sending pictures of.
        #
        # A block with no balloon is standing on ARTWORK, whatever the paper
        # under this particular word looks like, and artwork is the model's
        # job. lee, in so many words: *"the local celener is only used fro
        # fully white bubbles every thing else should be handles by the ai
        # clenner"* — a cloak is not a bubble.
        #
        # By FAMILY, and not by `on_art`. That function also answers yes when
        # no balloon was FOUND — and a balloon the finder missed is still a
        # balloon. Using it here sent a plain white bubble on a fixture whose
        # outline the finder could not read straight to the model, which costs
        # money and is the opposite of the rule. What a box IS, is a thing the
        # person set; whether a shape was found round it is a thing the code
        # guessed.
        #
        # No `neural is not None` guard on this, and it would be dead if there
        # were one: `white` is only ever read on the line below when a model IS
        # configured, so with none the rule already does nothing. Saying it
        # twice would look like care and be indistinguishable from its absence.
        if _kinds.family_of(getattr(r, "kind", "")) in ("freefloat", "sfx"):
            white = False
        mine = white if neural is not None else flat
        if mine and not (neural is not None and neural_all):
            # The fixed dilation is a guess at stroke width and it guesses low
            # on a big scan, leaving a faint outline of every character. The
            # background here is flat, so the haze can simply be measured
            # against it instead.
            level = _bg_level(g, area, ink, bg, spare_c)
            d = _with_halo(g, area, d, spare_c, level, inverted)
            out[w][d > 0] = bg.astype(out.dtype)
            rec["how"] = "flat fill"
            rec["flat"] = (area, spare_c, bg, level)
        else:
            if neural is None and is_screentone(page.image, r):
                # Nothing to hand it to: copy real texture in rather than
                # letting Telea blur the dots into a grey blob. Healed per
                # region so each patch matches its own surroundings, and
                # shift_fill hunts several region-widths away, so this one
                # stays whole-page.
                full_d = np.zeros(gray.shape, np.uint8)
                full_d[w] = d
                tone_masks.append(full_d)
                rec["how"] = "pattern copy"
                r.flagged = (r.flagged or "") + \
                    " screentone: cleaned by pattern copy, worth a look"
            else:
                # Hand it to the model (or Telea) to redraw from the pixels
                # around it. Give it a wider mask than the flat path gets: the
                # model redraws whatever it is handed and nothing else, so a
                # stroke edge left outside the mask is a stroke edge left on
                # the page — and unlike a flat fill, being generous costs
                # nothing, because what replaces it is reconstructed anyway.
                #
                # That is also what makes the haze sweep safe here. It only
                # ever ran on flat bubbles, because it needs a background level
                # and a flat bubble has exactly one; on tone and gradients the
                # mask fell back to a fixed few pixels, which is a guess at
                # stroke width that guesses low, and the skirt of every stroke
                # survived as the outline of the words. _local_bg gives a level
                # per pixel so the same measurement works here. Shorter reach
                # and a stricter tolerance than the flat path gets, because
                # artwork is allowed to be dark on its own account — and only
                # ink CONTIGUOUS with a stroke counts, so screentone dots and
                # line work that merely pass nearby are left standing.
                if area is not None:
                    d = _with_halo(g, area, d, spare_c,
                                   _local_bg(g, inverted), inverted,
                                   reach_px=TONE_REACH, tol=TONE_TOL,
                                   touching=True)
                wide = _dilated(d, NEURAL_PAD)
                # Last check before the point of no return, and only on the one
                # path where the mask is OURS: on a dark panel the detector's
                # answer was thrown away and replaced with a light/dark split,
                # and a split that has gone wrong does not look like a
                # slightly-off clean. The inpainter is asked to replace most of
                # a panel and answers with a flat block, which is the artwork
                # gone for good. Text left standing is recoverable — the
                # paint-out tool is right there. So when our own guess has
                # swallowed its region, keep the page and say so. Where the
                # detector says the whole box is typesetting, that is its call to
                # make and it is usually right.
                if inverted and area is not None and \
                        int(((wide > 0) & (area > 0)).sum()) > \
                        MASK_MAX_SHARE * int((area > 0).sum()):
                    # It used to give up here and leave the box untouched, which
                    # is how a page came back with its sound effects and its
                    # narration columns still on it. lee: *"these box are badly
                    # cleaned or just skipped — fix that so this never happen, it
                    # shoud not skip boxes"*.
                    #
                    # The danger was never the letters; it is the HALO and the
                    # model's padding, which on a dark panel can walk out of the
                    # writing and across the artwork. So drop back to the
                    # letter-like core — no halo, no padding — and clean that.
                    # Something always gets erased, and the worst case is a rim
                    # left behind rather than a panel replaced by a grey block.
                    d = _dilated(ink)
                    wide = d
                    rec["core"] = True
                    r.flagged = (r.flagged or "") + \
                        " clean: the typesetting here is hard to tell from the " \
                        "artwork, so only the strokes were erased — check it"
                hard_mask[w][wide > 0] = 255
                rec["how"] = "neural" if neural is not None else "telea"
                if neural is not None:
                    # `tight` travels with the job so that a refused or broken
                    # call can be repaired locally at the right size instead of
                    # smearing the model's generous mask.
                    rec["job"] = {"win": w, "mask": _dilated(d, MODEL_PAD),
                                  "tight": d}
                    hard_jobs.append(rec["job"])

    # Screentone first, on the still-untouched plate, so the copy sources clean
    # neighbours rather than a half-inpainted page.
    for tm in tone_masks:
        out = shift_fill(out, tm)

    if neural is not None:
        for job in hard_jobs:
            _run_neural(out, job, neural)
    elif hard_mask.any():
        out = cv2.inpaint(out, hard_mask, 3, cv2.INPAINT_TELEA)

    _sweep_ghosts(gray, out, done, neural, page.image)

    # ---- the fence ----------------------------------------------------------
    # lee: *"the clenners shoud only clean withing the box, it hsoud never touch
    # a pixel outside teh box area, both the local and the ai — the box that
    # shoud be considered is teh box that i see"*.
    #
    # Half a dozen steps above can each reach past the box they were given: the
    # halo sweep grows the mask until the background stops looking like ink, the
    # model's padding adds a couple of pixels, the ghost sweep re-fills a flat
    # bubble to its own edges, a screentone copy works page-wide. Every one of
    # them has a reason, and none of them is a reason to change a pixel of a page
    # nobody drew a box around — which is how a whole bubble came back wiped with
    # two small boxes in it.
    #
    # So there is one fence, at the end, after everything: whatever any of them
    # did outside the boxes on screen is undone. It cannot be forgotten by a step
    # added later, and it is the same rule for the local fill and for the model.
    allowed = np.zeros(gray.shape, bool)
    for r in page.regions:
        if r.text_mask is None or getattr(r, "skip_clean", False):
            continue
        x, y, w, h = (int(v) for v in r.bbox)
        # The doorstep, and nothing more: a glyph drawn a little past its box
        # has to be finishable, or "the text must go" and "never outside the
        # box" cannot both be true. GLYPH_REACH is that margin — eight pixels,
        # about half a stroke — and only ink CONNECTED to what the box caught
        # can use it (see _complete_strokes).
        allowed[max(0, y - GLYPH_REACH):y + h + GLYPH_REACH,
                max(0, x - GLYPH_REACH):x + w + GLYPH_REACH] = True
    out[~allowed] = page.image[~allowed]

    # Who cleaned what. Every argument about this page's cleaning so far has
    # been conducted by looking at it and guessing; this is the count.
    # "fell back" is a region the model was asked for and did not deliver.
    stats: dict = {}
    for rec in done:
        stats[rec["how"] or "?"] = stats.get(rec["how"] or "?", 0) + 1
        if rec.get("core"):
            # cleaned, but only its letter strokes: the halo could not be
            # trusted here. Counted so the report can say which boxes to look at
            stats["core only"] = stats.get("core only", 0) + 1
    for job in hard_jobs:
        if job.get("fell_back"):
            stats["neural"] = max(0, stats.get("neural", 0) - 1)
            stats["fell back"] = stats.get("fell back", 0) + 1
    # Two very different reasons a box was not cleaned, told apart at last:
    # one is "there was nothing recorded to erase", the other is "you asked me
    # to keep this one". lee kept finding untouched text and looking for a bug
    # in the cleaner; a closed eye is not a bug, it just has to say so.
    stats["kept"] = sum(1 for r in page.regions
                        if getattr(r, "skip_clean", False))
    stats["skipped"] = sum(1 for r in page.regions
                           if r.text_mask is None
                           and not getattr(r, "skip_clean", False))
    # …and the same fact on each box, which is the one the person can act on.
    # A count for the chapter says six were filled flat; it cannot say WHICH,
    # and "which" is the whole question when one of the six is a column of
    # outside text that had no business on that path.
    for r in page.regions:
        r.clean_route = ""
        r.clean_core = False
    for rec in done:
        rec["r"].clean_route = rec["how"] or ""
        rec["r"].clean_core = bool(rec.get("core"))
    for job in hard_jobs:
        if job.get("fell_back"):
            for rec in done:
                if rec.get("job") is job:
                    rec["r"].clean_route = "fell back"
    page.clean_stats = stats
    page.clean_plate = out
    return out


def _run_neural(out: np.ndarray, job: dict, neural, extra: int = 0,
                again: "np.ndarray | None" = None) -> None:
    """Redraw one region in place, showing the model the page around it.

    `extra` widens the mask on a retry: the first answer left the typesetting
    visible, and the usual reason is that a little of it lay outside what the
    model was asked to replace.

    `again` is the ORIGINAL page, and it is what makes a retry a second
    attempt rather than a second layer. Without it the retry read `out`, which
    already holds the first answer, so the model was asked to redraw its own
    reconstruction — two stacked generations, each adding its own noise floor,
    which over a flat black balloon comes back as a grainy rectangle where the
    fill around it is smooth. Handed the original, the region under the mask
    goes back to the page as it arrived and the model answers the same
    question it was asked the first time, with more room.

    Only the part under the FIRST mask is restored. Everything else in the
    context window may be another region's finished cleaning, and putting the
    page back over that would undo a neighbour's work.
    """
    m = job["mask"] if extra <= 0 else _dilated(job["mask"], extra)
    ctx = _grow(job["win"], out.shape, NEURAL_CTX)
    sub = out[ctx]
    if again is not None:
        sub = sub.copy()
        back = np.zeros(sub.shape[:2], np.uint8)
        ys0, xs0 = job["win"]
        back[ys0.start - ctx[0].start: ys0.stop - ctx[0].start,
             xs0.start - ctx[1].start: xs0.stop - ctx[1].start] = job["mask"]
        sub[back > 0] = again[ctx][back > 0]
    sm = np.zeros(sub.shape[:2], np.uint8)
    ys, xs = job["win"]
    sm[ys.start - ctx[0].start: ys.stop - ctx[0].start,
       xs.start - ctx[1].start: xs.stop - ctx[1].start][m > 0] = 255
    if not sm.any():
        return
    try:
        filled = neural(sub, sm)
    except Exception:
        job["fell_back"] = True
        return _local_fill(out, job)      # refused, or unreachable
    if filled is None or filled.shape != sub.shape:
        job["fell_back"] = True
        return _local_fill(out, job)
    if _gave_up(sub, filled, sm):
        job["fell_back"] = True
        job["gave_up"] = True
        return _local_fill(out, job)
    out[ctx] = _feather(sub, filled, sm)


# What "the model gave up" looks like, in grey levels.
#
# A model that cannot reconstruct an area sometimes hands back a flat patch of
# one colour instead — which is not a cleaned page, it is an erased one. lee,
# with a screenshot of a white rectangle sitting where a column of Japanese
# used to be on hatched cloth: *"the ai seem to have given up and just made teh
# white box instard of cleaning teh text"*.
#
# The test cannot be "is the answer flat", because inside a plain bubble the
# right answer IS flat. It has to be "is the answer flat where its surroundings
# are not". So both numbers are measured: the detail in a ring just outside the
# mask, on the page as it was handed to the model, and the detail inside the
# mask in what came back.
GAVE_UP_DETAIL = 12.0   # the ring has to have something in it (cf. FLAT_STD)
GAVE_UP_FLAT = 4.0      # ...and the answer to have nothing


def _gave_up(sub: np.ndarray, filled: np.ndarray, mask: np.ndarray) -> bool:
    """Did the model erase this area rather than redraw it?

    Measured on a ring `HALO_REACH` wide just outside the mask, so "the
    surroundings" means the artwork the fill has to match rather than the whole
    window. A flat answer on flat paper is right and passes; a flat answer
    against hatching, tone or line work is a refusal wearing the shape of a
    result, and goes to the local fill instead — which at least copies from the
    page rather than inventing a blank.
    """
    m = mask > 0
    if not m.any():
        return False
    near = _dilated(mask, HALO_REACH) > 0
    ring = near & ~(_dilated(mask, DILATE_PX) > 0)
    if int(ring.sum()) < 50:
        return False                      # nothing to compare against
    g_in = _gray(filled)[m]
    g_ring = _gray(sub)[ring]
    return bool(float(g_ring.std()) >= GAVE_UP_DETAIL
                and float(g_in.std()) < GAVE_UP_FLAT)


def _local_fill(out: np.ndarray, job: dict) -> None:
    """Repair one region without the model, at the size a local method should
    be given.

    Reached when the hosted cleaner refuses or cannot be reached. It used to be
    reached with the model's own mask — dilated by `NEURAL_PAD` because a model
    reconstructs whatever it is shown — and a plain fill over that much of a
    dark panel is the grey smear lee sent a picture of. The tight mask is the
    typesetting and a couple of pixels of its edge, which is all a local fill has
    any business replacing.
    """
    m = job.get("tight")
    if m is None or not m.any():
        return
    w = job["win"]
    sub = out[w]
    full = np.zeros(sub.shape[:2], np.uint8)
    full[m > 0] = 255
    out[w] = _feather(sub, cv2.inpaint(sub, full, 3, cv2.INPAINT_TELEA), full)


def _sweep_ghosts(gray: np.ndarray, out: np.ndarray, done: list[dict],
                  neural=None, original: "np.ndarray | None" = None) -> None:
    """Look at the finished plate and deal with typesetting that is still there.

    A flat bubble can be refilled on the spot — the fill colour is known and
    correct, the only thing that was wrong is how far it reached — so widen and
    go again. A region the model drew gets one more go too, with a wider mask,
    because the usual reason a ghost survives a redraw is that a sliver of the
    stroke was never inside the mask, and asking again about a slightly bigger
    area is the whole fix. Results are cached by content upstream, so the retry
    costs nothing on a page that is merely being re-rendered.

    Anything still showing after that is left alone and reported: a third
    automatic pass on a reconstruction is as likely to make it worse, so say
    what happened and which path produced it, and let the person decide.
    """
    after = _gray(out)
    redone = False
    for rec in done:
        if not rec["flat"]:
            continue
        w = rec["win"]
        if ghost_delta(gray[w], after[w], rec["ink"], rec["inv"]) <= GHOST_TOL:
            continue
        area, spare, bg, level = rec["flat"]
        wider = _with_halo(gray[w], area, _dilated(rec["ink"]), spare, level,
                           rec["inv"], reach_px=HALO_REACH + 6,
                           tol=max(3, HALO_TOL // 2))
        out[w][wider > 0] = bg.astype(out.dtype)
        redone = True

    if neural is not None:
        for rec in done:
            if rec["flat"] or not rec["job"]:
                continue
            w = rec["win"]
            if ghost_delta(gray[w], after[w], rec["ink"], rec["inv"]) \
                    <= GHOST_TOL:
                continue
            _run_neural(out, rec["job"], neural, extra=DILATE_PX + 2,
                        again=original)
            redone = True

    if redone:
        after = _gray(out)

    for rec in done:
        w = rec["win"]
        left = ghost_delta(gray[w], after[w], rec["ink"], rec["inv"])
        if left <= GHOST_TOL:
            continue
        rec["r"].flagged = (rec["r"].flagged or "") + \
            (" ghost: source text is still faintly visible after the %s "
             "(%d levels) — paint it out in Edit" % (rec["how"] or "clean",
                                                     round(left)))


def _feather(orig: np.ndarray, filled: np.ndarray, mask: np.ndarray,
             px: float = 2.0) -> np.ndarray:
    """Blend the inpainted patch over a soft mask edge.

    A hard mask boundary leaves a visible rectangle/halo where the model's fill
    meets untouched art. Feathering the seam over a couple of pixels hides it
    while keeping the interior fully replaced.

    The ramp has to lie OUTSIDE the mask. Blurring the mask itself puts the
    halfway point exactly on its edge, so half of whatever was there survives
    the fill — and what is at the edge of a mask drawn round a letter is the
    letter's own anti-aliased rim. That is the pale outline of the original
    kanji left sitting on an otherwise clean patch: not ink the sweep can find,
    because the sweep looks for what is darker than its surroundings and this
    is a bright rim on a fill. Grow first, then blur, and the mask is fully
    replaced right up to its own boundary.
    """
    grow = max(1, int(round(px)))
    m = cv2.dilate((mask > 0).astype(np.uint8),
                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                             (2 * grow + 1,) * 2)).astype(np.float32)
    m = cv2.GaussianBlur(m, (0, 0), px)
    if filled.ndim == 3:
        m = m[..., None]
    blended = orig.astype(np.float32) * (1 - m) + filled.astype(np.float32) * m
    return blended.astype(orig.dtype)


# The local healing brush used to live here: ~460 lines of PatchMatch-style
# per-patch matching and Poisson blending, plus `heal_spot`, which tried three
# fills on a band around the spot and kept whichever rebuilt that band closest
# to the page. It measured well — mean error 40.9 -> 36.1 over 96 spots on
# eight real pages — and it is gone, because measuring well is not the same as
# being worth having. Every one of those three fills can only move texture that
# is already somewhere nearby, and the spots lee retouches after the Clean step
# are the ones where the artwork underneath was never on the page at all.
# lee, with the brush in his hand: *"remoev teh regualr healing brush, its
# ass"*. There is one healing brush now and it goes to the AI cleaner, which
# redraws. See the /heal endpoint in editor.py.
#
# `shift_fill` stays: it is not the brush. It is the Clean step's own offline
# fill, used on every page that never reaches a model.


def shift_fill(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Content-aware fill without opencv-contrib: copy REAL pixels in.

    Diffusion inpainting (Telea) smears — a healed spot on screentone or
    hatching turns into a grey blur that reads as damage. Manga art is
    overwhelmingly repetitive at brush scale, so the honest fix is to find
    the translation of the image that best matches the ring AROUND the hole
    and copy those actual pixels into it. Dots stay dots, hatches stay
    hatches, flats stay flat. Whatever a shift cannot source (off-image, or
    inside the hole itself) falls back to Telea, and the caller feathers the
    seam.
    """
    m = mask > 0
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        return img.copy()
    H, W = m.shape

    ring = cv2.dilate(m.astype(np.uint8),
                      np.ones((9, 9), np.uint8)).astype(bool) & ~m
    ry, rx = np.nonzero(ring)
    if rx.size < 12:
        return cv2.inpaint(img, m.astype(np.uint8) * 255, 5,
                           cv2.INPAINT_TELEA)

    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    step = max(4, min(bw, bh) // 2)
    reach = 4 * max(bw, bh)
    cands = []
    r = step
    while r <= reach:
        for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r),
                       (r, r), (-r, r), (r, -r), (-r, -r)):
            cands.append((dx, dy))
        r += step

    f = img.astype(np.float32)
    # How much the artwork around this hole actually varies. It is the price of
    # NOT sourcing a pixel: whatever a shift cannot reach falls through to Telea
    # at the bottom of this function, and Telea reproduces the local mean and
    # none of the texture — so its squared error on textured art is, near enough,
    # that texture's variance. On flat paper the figure is ~0 and Telea is
    # perfect, which is exactly when coverage should stop mattering.
    rough = float(f[ring].reshape(rx.size, -1).var(axis=0).mean())
    best = None
    for dx, dy in cands:
        sy, sx = ry + dy, rx + dx
        ok = (sy >= 0) & (sy < H) & (sx >= 0) & (sx < W)
        if ok.mean() < 0.7:
            continue
        oy, ox, osy, osx = ry[ok], rx[ok], sy[ok], sx[ok]
        known = ~m[osy, osx]
        if known.mean() < 0.7:
            continue
        d = f[oy[known], ox[known]] - f[osy[known], osx[known]]
        score = float((d * d).mean())
        # The ring alone was scoring the wrong thing, and this is the smear.
        # A shift SHORTER than the hole lands part of the hole back on itself,
        # so those pixels have no source and go to Telea — while the ring, which
        # sits outside the hole, matches perfectly and reports a flawless zero.
        # On period-9 vertical hatching a 64px-wide hole was won by dx=18 with a
        # ring score of exactly 0.00; it sourced 83% of the hole and Telea
        # blurred the remaining 18-pixel strip, for a true error of 48.9 against
        # the 0.00 that dy=36 was sitting there offering. Charging the unsourced
        # share at `rough` puts the two on the same scale. Over 175 measured
        # holes across hatching, screentone, line art, a panel border, gradients
        # and paper grain the mean error went 17.9 -> 5.2, with no case worse by
        # more than the noise floor on a hole cut into pure random grain, where
        # no fill can be right.
        sy, sx = ys + dy, xs + dx
        inside = (sy >= 0) & (sy < H) & (sx >= 0) & (sx < W)
        cover = float((inside & ~m[np.clip(sy, 0, H - 1),
                                   np.clip(sx, 0, W - 1)]).mean())
        score += (1.0 - cover) * rough
        if best is None or score < best[0]:
            best = (score, dx, dy)

    out = img.copy()
    remaining = m.copy()
    if best is not None:
        _, dx, dy = best
        hy, hx = ys, xs
        sy, sx = hy + dy, hx + dx
        ok = (sy >= 0) & (sy < H) & (sx >= 0) & (sx < W)
        oky, okx, oksy, oksx = hy[ok], hx[ok], sy[ok], sx[ok]
        src_known = ~m[oksy, oksx]
        out[oky[src_known], okx[src_known]] = img[oksy[src_known],
                                                  oksx[src_known]]
        remaining[oky[src_known], okx[src_known]] = False

    if remaining.any():
        out = cv2.inpaint(out, remaining.astype(np.uint8) * 255, 5,
                          cv2.INPAINT_TELEA)
    return out
