"""Erase source text.

Most manga bubbles have a flat white interior. For those, filling with the
modal background colour is instant and cleaner than any neural inpainter.
Reserve the expensive path for text over artwork, gradients and screentone.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import kinds as _kinds
from .models import Page, TextRegion, turned_box

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
MODEL_PAD = 2          # ...and on the one the MODEL is given
#
# MODEL_PAD was 6. Measured over lee's chapter, as a share of the box each mask
# belongs to: the glyphs themselves are **14.5%**, the DILATE_PX seed takes that
# to **41%**, the haze sweep adds a point, and the model's 6px took it to
# **73%**. lee, watching a clean run: *"the ai tries to clenned everything in
# the box, it shoud only try to clen teh text"*. He is describing 73%.
#
# Korean sets at a 3-4px stroke with 6-10px between glyphs, so nine pixels of
# growth welds a page of writing into one slab, and what replaces that slab is
# whatever the model imagines over paper it never needed to touch.
#
# Six was a GUESS at how far a stroke's anti-aliased rim carries. `_with_halo`
# is the measurement that guess was replaced by, and it has already run by the
# time this is applied: anything measurably darker than the local background
# and joined to a stroke IS that stroke, and the seed's own 3px is under it.
# Measured on the same 139 boxes, the mask at 1px misses no more ink than at
# 6px and is **42%** of the box instead of 73%.
#
# Kept at 1 rather than 0 for the sub-pixel edge, which is the one thing a
# threshold cannot see.
#
# The SEED stays at DILATE_PX and was tried at 1: the local fills got worse
# (page 012's plain bubble went from 7% of its writing left to 24%). That
# 3px is not the same guess. It paints the skirt the haze sweep cannot see —
# the skirt is within HALO_TOL of the background, which is exactly what the
# threshold is built to ignore — and a local fill has nothing else to cover it
# with. The model does not need it because it redraws the area regardless.
#
# The fence at the end of inpaint_page bounds the result to the box, its
# doorstep, and the balloon.
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
# 2026-08-12-a: four changes in one day, and this was forgotten for all four —
# the balloon's bays filled, the fence closed at the balloon, `MODEL_PAD` cut
# from 6 to 2, and `glyphs_only` taught to see mid-tone ink. lee, sent a gold
# plate that was fixed and measured here and still on the page in his editor:
# *"can you explain why its not clening that text?"* This is why. It is the
# fourth time; `test_the_stamp_is_bumped_when_the_cleaner_changes` now compares
# a fingerprint of this file against the stamp, so the next one cannot ship.
# 2026-08-12-b: the glyph mask a SAVED record is rebuilt with is read by tone
# now rather than by darkness, which is how gold on cream finally comes off
# (`project.region_from_record`). That is not in this file, and the plate cache
# does not watch that file either — so the stamp covers it and the fingerprint
# test reads both.
# 2026-08-12-d: the gold-text work is OUT again, at lee's word — *"right now
# hwe teh gold text is clenned the thither stuff gets broken and teh clenning
# gets sigmifivanly worst"*. The tone split in `project.region_from_record` and
# the union in `glyphs_only` both go, so the plates built under -b and -c retire
# and the chapter comes back to what he called a safe point.
ALGO = "2026-08-13-e"


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


# A rescue that stood here is GONE, and the reason is worth keeping.
#
# lee's two gold caption plates come back with their writing on: a bbox-only
# region's glyph mask is `gray <= 128` and gold on cream runs 150 to 190, so the
# mask holds a few pixels of the darkest filigree and none of the words. The
# obvious fix is to notice that the mask holds far less than the tone split
# finds — measured over the chapter, the median box holds 0.99 of the split and
# 137 of 139 are over 0.95, while the plates are at 0.15 and 0.39, with nothing
# in between.
#
# It cannot be done that way. On SCREENTONE the split legitimately finds far
# more than the detector — every dot — and the detector is the one that is
# right; `test_the_widened_mask_does_not_eat_the_screentone_around_it` is that
# case and it goes red immediately. Gating on `is_screentone` does not separate
# them either: measured on this chapter it answers True for the gold plate and
# for ordinary bubbles alike.
#
# What is needed is a reading of WHAT the split found that the mask did not —
# rows of letters, or scattered dots — and neither the ratio nor the tone test
# is that. Left undone rather than shipped half-measured, because the cost of
# getting it wrong is artwork erased, which is the one thing that cannot be
# undone from a flag.

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
    # ...and on a FOCUS box, the reading its own mask came from. The two lines
    # below ask "does this stroke carry on outside the region", and they answer
    # it by finding the stroke in the page again at a fixed level — which is
    # the one thing a focus box has already been declared not to obey. On lee's
    # page 003 the gold is nowhere in `gray <= INK`, so every component came
    # back empty, and the mask went from 13% of the box to 1%: the switch was
    # on, the mask was right, and this threw it away one line later.
    full = ((text_mask > 0).astype(np.uint8) if in_focus(region)
            else ((gray >= BRIGHT) if bright_ink else (gray <= INK)
                  ).astype(np.uint8))
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


# How much of a box's writing may still be standing where the flat fill painted
# before the fill is thrown away as a wrong answer. Measured over lee's chapter:
# 121 boxes take the flat fill, their median leaves 1% of the writing and their
# ninetieth leaves 2%. Page 024 leaves 20%. The next worst is 5.5%, so the line
# is drawn in the middle of a gap of four times, not at a number that felt safe.
SLAB_LEFT = 0.10


def _slab_worked(orig: np.ndarray, painted: np.ndarray,
                 ink: np.ndarray) -> bool:
    """Did filling this box with one colour actually take the writing off?

    The flat fill's entire justification is that the colour is KNOWN — so
    unlike every other route, it can be checked. Paint it and look: if the box
    still shows the words where the paint went, the colour was not known.

    lee's page 024 is why. A see-through balloon with a beam of light across it
    was called flat, because `_flat_from` samples the paper immediately AROUND
    the words and on that box the words cover half of it — so the sample is a
    corner, and a corner of a gradient is flat. A slab of one grey then goes
    down over the whole box and the faint writing survives on top of it.

    Which is the worst outcome available, because it also blinds the second
    pass. That step reads the page the FIRST one produced — it must, or it
    would undo work already done — and what it now reads is a uniform field:
    it finds 4% of the box where the original shows 60%, so it erases almost
    nothing and a fifth of the writing is left legible. lee: *"can this be
    fixed?"*.

    Checking the fill instead of second-guessing the verdict is what makes this
    safe. Every attempt to catch page 024 by measuring the balloon BEFORE
    painting it — the same flatness question asked over a wider sample — either
    missed it or took plain white bubbles down with it, because a sample wide
    enough to see the beam also reaches the drawn outline. The fill's own
    result has no such ambiguity: 024 measures four times worse than the next
    box in the chapter.
    """
    look = _dilated(_u8(ink), DILATE_PX + 1) > 0
    if look.sum() < 60:
        return True                      # nothing recorded to check against
    def _edge(z):
        return float(np.abs(cv2.Laplacian(
            cv2.cvtColor(z, cv2.COLOR_BGR2GRAY), cv2.CV_64F))[look].mean())
    was = _edge(orig)
    if was < 1.0:
        return True                      # there was nothing there to remove
    return _edge(painted) < SLAB_LEFT * was


FOCUS_REACH = 41       # how far a focus box looks for its own background
FOCUS_DIFF = 26        # ...and how far from it a pixel must be to be writing
# How much of the writing the ordinary reading has to be MISSING before a box
# is read in focus by itself. Measured over lee's chapter: every box he has
# sent back scores 57% or more (page 003 is 91%, the two navy plates 76 and
# 78), and nine boxes in ten score under 33%. Where it fires on a box that was
# already fine it costs nothing — focus came out equal or better on 65 of 67
# of those, and on the other two there was no writing in the box to find.
FOCUS_WHEN = 0.85


def focus_background(bgr: np.ndarray, reach: int = FOCUS_REACH) -> np.ndarray:
    """The box as it would look with the writing lifted off it.

    A median wider than a stroke cannot see strokes, so what comes back is the
    paper, the gradient, the frame and the artwork with the words gone. Both
    halves of a focus clean are this one estimate: the mask is what differs
    from it, and the fill is it. They cannot disagree about where the
    background is, because there is only one of them.
    """
    if bgr is None or bgr.size == 0:
        return bgr
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    k = int(reach) | 1
    k = max(3, min(k, (min(bgr.shape[:2]) - 1) | 1))
    return cv2.medianBlur(bgr, k)


def focus_mask(bgr: np.ndarray, reach: int = FOCUS_REACH,
               diff: int = FOCUS_DIFF) -> np.ndarray:
    """The writing in a box, read as whatever differs from its own LOCAL
    background — in COLOUR, and never against a fixed level.

    Everything else in the cleaner reads a page in grey and splits it at a
    number. That is a reading of black-on-white, and lee's chapter keeps
    handing back boxes it is simply not true of:

    * gold on navy (page 030) — 84% of the box is "dark ink" and the mask is
      the night sky. Gold and navy are three greys apart and half the colour
      wheel apart.
    * gold on cream (pages 003, 012) — 91% of the box is "bright ink".
    * dark words on a translucent balloon with a beam of light across it
      (page 024) — the background runs 0 to 255 inside one box, so no single
      level can be right anywhere but the middle.

    A median blur wider than a stroke cannot see strokes: it keeps the frame,
    the gradient, the artwork and the beam, and hands back the page as it would
    look with the writing lifted off. Whatever differs from THAT is the writing,
    wherever the background happens to sit and whatever colour it is.

    Measured on lee's four bad boxes: the mask covers every glyph on all four,
    against 1% to 16% of the ink found by the fixed rule.
    """
    if bgr is None or bgr.size == 0:
        return np.zeros(bgr.shape[:2] if bgr is not None else (0, 0), np.uint8)
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    bg = focus_background(bgr, reach)
    apart = np.abs(bgr.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    return (apart > int(diff)).astype(np.uint8) * 255


def focus_ink(bgr: np.ndarray, reach: int = FOCUS_REACH,
              diff: int = FOCUS_DIFF) -> np.ndarray:
    """What to actually erase in a focus box: whole strokes, and no decoration.

    Two things `focus_mask` deliberately does not do, because it is the mask
    the DECISION is taken on and has to stay comparable with what a fixed level
    produces. Both are refinements lee asked for on seeing the gold plate.

    **The whole stroke, not the part over the threshold.** A glyph's edge is
    anti-aliased into its background over several pixels, so one level cuts
    every stroke wherever it happens to fall and leaves the rest as a coloured
    rim round each letter. lee: *"get rid of the resedue yellow"*. So the
    strong level only says WHERE the writing is and a weak one says how far
    each stroke reaches, growing from those seeds and nowhere else — ink that
    never reaches the strong level is not writing and is never picked up,
    however much of it there is.

    **Nothing that runs off the edge of the box.** Writing sits wholly inside
    the box drawn round it; a frame, a rule or a piece of decoration carries on
    past it. On page 003 the three biggest pieces this finds are the plate's
    corner scrollwork and every one of them touches an edge, while no letter
    comes near one. lee: *"clen the text only nan not the side design"*.

    Only pieces that are also LARGE, and only where touching an edge means
    anything: on a box drawn snugly round its words the words touch the edges
    too, and the rule then throws the writing away — page 012 went from 8% of
    its caption left to the whole caption standing.
    """
    strong = focus_mask(bgr, reach, diff)
    if not strong.any():
        return strong
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    apart = np.abs(bgr.astype(np.int16)
                   - focus_background(bgr, reach).astype(np.int16)).max(axis=2)
    weak = (apart > max(4, int(diff) // 3)).astype(np.uint8)
    _, lab = cv2.connectedComponents(weak, 8)
    m = (np.isin(lab, list(set(np.unique(lab[strong > 0])) - {0}))
         & (weak > 0)).astype(np.uint8)

    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 2:
        H, W = m.shape[:2]
        big = 2.0 * float(np.median(st[1:, cv2.CC_STAT_AREA]))
        edge = [i for i in range(1, n)
                if st[i, cv2.CC_STAT_LEFT] <= 0 or st[i, cv2.CC_STAT_TOP] <= 0
                or st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH] >= W
                or st[i, cv2.CC_STAT_TOP] + st[i, cv2.CC_STAT_HEIGHT] >= H]
        drop = [i for i in edge if st[i, cv2.CC_STAT_AREA] > big]
        if drop and len(drop) < n - 1 and len(edge) <= 0.25 * (n - 1):
            m[np.isin(lab, drop)] = 0
    return m * 255


def focus_is_needed(bgr: np.ndarray, ordinary: np.ndarray) -> bool:
    """Is the ordinary reading of this box missing the writing?

    The two readings are compared, and the question asked of the ordinary one
    is only ever "does it cover the writing" — never "is it too big". A mask
    that takes in some background is a mask that erases a little more paper;
    a mask that misses the words leaves the words on the page, and that is the
    complaint every time.

    So: of what the focus reading calls writing, how much does the ordinary
    reading not have? On lee's page 003 the answer is 91% — the gold is
    nowhere in `gray >= 200`, so the mask is the cream paper and the caption
    survives the clean intact.
    """
    foc = focus_mask(bgr) > 0
    if not foc.any():
        # Nothing to find. On page 008 that is the truth — the box holds half
        # a black panel and half a white one and no writing at all — and the
        # ordinary reading erased the black half. Saying "no" here leaves the
        # box on the path it is on today, which is the conservative answer
        # whenever the two readings do not disagree.
        return False
    # Nothing too thin to have been drawn with a brush, and more than a couple
    # of separate marks. A local background is exactly what a field of
    # screentone differs from, so on tone or grain this reading hands back the
    # DOTS, and a box of dots then looks like writing the ordinary reading is
    # missing. Typesetting is drawn with a brush and tone is not; a misread
    # gradient or a piece of artwork comes back as one blob, and writing never
    # does.
    foc = _letterlike(foc.astype(np.uint8) * 255) > 0
    if not foc.any():
        return False
    if cv2.connectedComponents(foc.astype(np.uint8), 8)[0] - 1 < 3:
        return False
    # Nothing too thin to have been drawn with a brush, and more than a couple
    # of separate marks. A local background is exactly what a field of
    # screentone differs from, so on tone or grain this reading hands back the
    # DOTS — and a box of dots then looks like writing the ordinary reading is
    # missing, which took a page of light tone off the model's hands.
    # Typesetting is drawn with a brush and tone is not; a misread gradient or
    # a piece of artwork comes back as one blob, and writing never does.
    foc = _letterlike(foc.astype(np.uint8) * 255) > 0
    if not foc.any() or cv2.connectedComponents(
            foc.astype(np.uint8), 8)[0] - 1 < 3:
        return False
    miss = float((foc & ~(ordinary > 0)).sum()) / float(foc.sum())
    if miss > FOCUS_WHEN:
        return True

    # ...and the case this was all built for, which does not need a share that
    # high to be certain: ink the grey pipeline is BLIND to. `gray <= 128` and
    # `gray >= 200` between them describe every page the cleaner was written
    # for, and gold falls down the gap — neither dark enough nor bright enough
    # — while being plainly a different COLOUR from the paper it sits on.
    #
    # Measured over lee's chapter: three boxes have ink in that gap that is
    # also coloured, and all three are boxes he has sent back. Not one other
    # box in 78 comes near it, which is what makes this safe to act on where a
    # share alone is not: an ordinary page's writing is black or white, and
    # neither is in the gap.
    if miss > 0.5:
        ink = focus_ink(bgr) > 0
        if ink.any():
            grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)[ink]
            sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1][ink]
            if (INK < float(np.median(grey)) < BRIGHT
                    and float(np.median(sat)) > 60):
                return True
    return False


def in_focus(region) -> bool:
    """Is this box being read against its own background — by hand or by the
    page? `focus` is lee's switch and is saved; `focus_auto` is what the page
    decided on the way past and is not."""
    return bool(getattr(region, "focus", False)
                or getattr(region, "focus_auto", False))


def _turned(region) -> bool:
    """Is this a box the person drew and TURNED?

    Only a box somebody drew can be turned at all — and `turn`, not `angle`:
    a sound effect drawn by hand is given an angle the moment it is drawn, the
    axis its artwork runs along, and reading that as a turn would have leant
    the clean of every one of them.
    """
    if not getattr(region, "manual", False):
        return False
    return abs(float(getattr(region, "turn", 0.0) or 0.0)) > 0.01


def _own_area(region, shape, pad: int) -> "np.ndarray | None":
    """A turned box's own outline, grown by `pad` — or None if it is upright.

    Everywhere the cleaner asks "is this inside the region" it asks it of
    `bbox`, and `bbox` stays the UPRIGHT rectangle a turned box is derived
    from: that is what the turn is computed off and what straightening it
    returns to. So a turned box's corners sweep outside every rectangle the
    cleaner knows about, and the writing standing in them is clipped away
    before anything can erase it — twice over, once out of the erase mask and
    once at the fence.

    Rebuilt here from the angle rather than read off `place_mask()`, because
    only a region with a BALLOON has one of those. A box called outside text
    or sound effect loads with no placement area at all, and those are most of
    the boxes anybody draws by hand.
    """
    if not _turned(region):
        return None
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [np.array(turned_box(region.bbox, region.turn), np.int32)],
                 1)
    return cv2.dilate(m, np.ones((2 * pad + 1,) * 2, np.uint8)) > 0


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


# How much of a box's writing has to be left standing after the ordinary clean
# before it is worth a second go. Measured as edge energy against the original,
# which is the same number every argument about this cleaning has been settled
# with. Below this the box came out clean and the second pass never sees it.
SECOND_LEFT = 0.06
# The reading is a median wider than a stroke, so writing whose strokes are
# WIDER than the window is invisible to it — the median sees the stroke as
# background and nothing differs from it. Big display writing and thick
# sound effects are exactly that. So the second step tries several windows and
# keeps whichever leaves least, rather than one width chosen in advance.
# lee: *"can you make a tunning ... and have teh clenner run thru all of them"*.
SECOND_REACH = (FOCUS_REACH, 81, 121)
# ...but never a reading that calls essentially the whole box writing. At 121
# the median is close to the box's own average, so on page 004's violet effect
# the reading comes back claiming 93% of the box, which would take the artwork
# with it. Measured across lee's chapter the honest readings run to 76% — a
# sound effect really can be most of its own box — and only that one is above
# 85%. So the line is drawn where the readings actually separate, not where it
# felt safe: a first guess of 40% threw away the true readings on four boxes.
SECOND_MOST = 0.85
# ...and much less than that when there is no model to rebuild what is painted
# over. The local fill is a blur however it is done — copying texture in
# (`shift_fill`) measured 3.8 against the artwork's own 43 — so it is only
# honest over a small patch. Handed most of a box it flattens whatever was
# there: on page 010 the grass inside a sound effect went from a texture of 34
# to 2.8, and the balloon beside it stopped looking like part of the drawing.
# lee: *"the bubble got wraped"*. A model rebuilds; a blur cannot, so without
# one the second step does the small jobs and leaves the big ones alone.
SECOND_MOST_LOCAL = 0.45
# ...and with no model, not over texture at all. A median cannot make hatching,
# screentone or grass, so painting one over them trades legible words for a
# smooth patch in the middle of the drawing. Measured as what the median cannot
# hold in the artwork AROUND the writing: every box the second step improves in
# lee's chapter measures 15 or under, most of them under 3, and a hatched panel
# measures 35.
SECOND_GRAIN = 22.0


def _feathered(sub: np.ndarray, back: np.ndarray,
               ink: np.ndarray) -> np.ndarray:
    """Paint `back` over `sub` where `ink` is, without a hard edge.

    A patch with a hard edge reads as damage — a rectangle of blur with a rim
    round it. lee: *"some if teh sfx clenning has aome notisable edges"*. So it
    is opaque over the writing and fades out across the few pixels around it,
    the same thing the flat path does with its halo.
    """
    a = np.clip(cv2.GaussianBlur(ink.astype(np.float32), (0, 0), 1.6) * 1.6,
                0.0, 1.0)[:, :, None]
    return np.clip(sub.astype(np.float32) * (1 - a)
                   + back.astype(np.float32) * a, 0, 255).astype(sub.dtype)


def second_pass(page: Page, out: np.ndarray, neural=None) -> list:
    """Clean the hard spots — after the ordinary clean, and only what it left.

    lee: *"i want the clenner to work in 2 step one step clenas teh normal like
    in the stage i said was teh safe state and the a second clen that clena
    steh hard spots like teh gold text etc"*.

    This is the right shape for it, and better than anything tried before it.
    Every earlier attempt had to GUESS, before cleaning, which boxes the fixed
    levels would fail on — and each guess that was broad enough to catch the
    gold also took boxes away from the model, the ghost retry and the
    screentone path, all of which were doing their job. A second pass does not
    guess. It looks at what the first one actually produced, and whatever is
    still standing is by definition what the first reading missed.

    It also cannot undo the first pass: it only ever paints where the writing
    survived, so a box that came out clean is not touched at all, and step one
    is exactly the cleaner lee called the safe state.

    What it erases is read the colour way — see `focus_ink` — because the boxes
    that survive step one are precisely the ones no fixed grey level describes:
    gold on navy, gold on cream, dark words on a balloon you can see the sky
    through.
    """
    if page.image is None or page.image.ndim != 3:
        return []
    gray0 = cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
    gray1 = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    H, W = gray0.shape[:2]
    did = []
    for r in page.regions:
        if r.text_mask is None or getattr(r, "skip_clean", False):
            continue
        sfx = _kinds.family_of(getattr(r, "kind", "")) == "sfx"
        x, y, w, h = (int(v) for v in r.bbox)
        x, y = max(0, x), max(0, y)
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
        if w < 13 or h < 13:
            continue
        box = (slice(y, y + h), slice(x, x + w))
        was = float(np.abs(cv2.Laplacian(gray0[box], cv2.CV_64F)).mean())
        if was < 1.0:
            continue
        if float(np.abs(cv2.Laplacian(gray1[box], cv2.CV_64F)).mean()) \
                < SECOND_LEFT * was:
            continue                      # the first pass got it

        # Read on the CLEANED page, not the original: what is being looked for
        # is what SURVIVED, and on the original that is mixed in with
        # everything the first pass has already taken off.
        # ...at every window, and keep whichever leaves least.
        #
        # One width cannot serve every box. The reading is a median wider than
        # a stroke, so writing whose strokes are WIDER than the window is
        # invisible to it: on page 060's outlined writing the 41px window
        # finds 2% of the box and leaves a third of the writing, and the 81px
        # one finds 21% and leaves 5%. Which width is right is a fact about the
        # box, so it is measured per box rather than chosen in advance.
        #
        # Each candidate has to look like writing on its own terms — several
        # separate marks, not one blob, which is what artwork and a misread
        # gradient both come back as — and none of them may claim most of the
        # box. At 121 the median is close to the box's own average, so on page
        # 004's violet effect the reading returns 93% of the box; a reading
        # that large is not a reading of writing, whatever it leaves behind.
        room = None
        area = None if sfx else r.place_mask()
        if area is not None and getattr(area, "shape", None)[:2] == gray0.shape[:2]:
            room = (area > 0)[box]
            if not room.any():
                continue
        cands = []
        for reach in SECOND_REACH:
            cand = _letterlike(focus_ink(out[box], reach=reach)) > 0
            if room is not None:
                cand &= room
            most = SECOND_MOST if neural is not None else SECOND_MOST_LOCAL
            if cand.sum() < 60 or float(cand.mean()) > most:
                continue
            if cv2.connectedComponents(cand.astype(np.uint8), 8)[0] - 1 < 3:
                continue
            cands.append((reach, cand))
        if not cands:
            continue
        # Judged on the RESULT, and every candidate judged over the SAME
        # ground. Scoring each one inside its own mask is not a comparison: a
        # small mask over flat paper scores near zero by erasing almost
        # nothing, and wins. The ground is what any of them thinks is writing.
        ref = np.zeros_like(cands[0][1])
        for _, c in cands:
            ref |= c
        ink, best, width = None, None, FOCUS_REACH
        for reach, cand in cands:
            got = _feathered(out[box], focus_background(page.image[box], reach),
                             cand)
            score = float(np.abs(cv2.Laplacian(
                cv2.cvtColor(got, cv2.COLOR_BGR2GRAY), cv2.CV_64F))[ref].mean())
            if best is None or score < best:
                ink, best, width = cand, score, reach
        # Where this region is allowed to paint.
        #
        # Not `place_mask()` on a sound effect. That hands an effect its own
        # INK as its area (see models.py) — right for typesetting, and exactly
        # wrong here, because the whole reason a box reaches the second step is
        # that its ink was not found. On lee's page 019 the gold effect's mask
        # is all but empty, so clipping to it left nothing to erase and the
        # effect stood through both steps untouched. An effect's box IS the
        # region; there is no balloon it could be inside of.
        # WHAT to erase is read off the cleaned page — what survived is the only
        # honest measure of what the first reading missed. What to paint back
        # comes from the ORIGINAL.
        #
        # By the time the first pass has finished with a box it failed on, it
        # has painted over part of it: page 024 is a translucent balloon that
        # `_flat_from` called flat, so a slab of one grey went down across a
        # background whose local variation is 48. Taking the fill from that is
        # copying the wreck back in. The original still has the beam, the
        # gradient and the speckle the fill needs — and the median lifts the
        # writing off it, which is the whole trick.
        # ...and now put something back where it was.
        #
        # A median is a blur, and on artwork that shows: measured over lee's
        # sound effects the area it paints comes back with a tenth of the fine
        # detail the original had there, with a visible edge where the patch
        # stops. lee: *"some if teh sfx clenning has aome notisable edges and
        # ae too blurry"*. Nothing local can do better — copying texture in
        # (`shift_fill`) and diffusing it in (Telea) both measured the same.
        #
        # So where there is a model, the second step ASKS IT, with the mask the
        # first pass should have had, on the page as it arrived. That is the
        # whole reason the first attempt came back with the writing still on
        # it: the model redrew faithfully, from a mask that did not cover the
        # words. Given the right mask it rebuilds the artwork instead of
        # smearing it. lee: *"the tie it takes to cleen is small so you ca add
        # as many steps ai you need to get all the boxes right"*.
        #
        # The median stays for a project with no model configured, where there
        # is nothing to ask and a soft patch still beats legible source text.
        wide = _dilated(_u8(ink), MODEL_PAD)
        if neural is not None:
            job = {"win": box, "mask": wide, "tight": _u8(ink)}
            try:
                _run_neural(out, job, neural, again=page.image)
            except Exception:
                job["fell_back"] = True
            if not job.get("fell_back"):
                did.append(r)
                continue
        # No model — and then it depends what this box is standing on.
        #
        # The local fill is a median, and a median cannot make texture. Over
        # paper, over a gradient, over a balloon that is all one thing, that
        # costs nothing and takes the writing off. Over hatching, screentone or
        # grass it flattens what it covers and leaves a smooth patch in the
        # middle of the drawing — worse than the words were, because the words
        # at least looked deliberate. lee has seen this one: *"the bubble got
        # wraped"*, on the grass of page 010.
        #
        # So the artwork around the writing is measured — what the median
        # cannot hold, which is exactly what would be lost — and where it is
        # real, a box with no model behind it is left as the first pass made
        # it. Across lee's chapter every box the second step improves measures
        # 15 or under here and most measure under 3; a hatched panel measures
        # 35. Nothing in his chapter is refused by this.
        #
        # None of it applies when a model answered: it redraws the texture
        # rather than blurring it, which is why that branch returned above.
        held = cv2.cvtColor(page.image[box], cv2.COLOR_BGR2GRAY).astype(
            np.float32) - cv2.cvtColor(
                focus_background(page.image[box]),
                cv2.COLOR_BGR2GRAY).astype(np.float32)
        # Round the WRITING, and not merely round the mask that was chosen:
        # everything any candidate called writing and everything the first pass
        # recorded, because a word left out of the chosen mask is still a word
        # and would otherwise be measured as if it were texture.
        writing = ref | (_letterlike(focus_ink(page.image[box])) > 0)
        around = ~(_dilated(_u8(writing), MODEL_PAD) > 0)
        if around.sum() > 200 and float(held[around].std()) >= SECOND_GRAIN:
            continue
        # A soft patch still beats legible source text, but it must not
        # announce itself: painted with a hard edge it reads as damage — a
        # rectangle of blur with a rim. lee: *"some if teh sfx clenning has
        # aome notisable edges"*. So the patch is feathered, opaque over the
        # writing and fading out across the few pixels around it, which is the
        # same thing the flat path does with its halo.
        # ...with the background read at the SAME width that won the mask.
        #
        # These are one estimate and always were — the mask is what differs
        # from the background and the fill is the background — so reading them
        # at different widths is reading two different pages. On lee's page 024
        # the writing covers half the box, which is exactly the case where the
        # narrow median is the writing rather than the paper: the mask is
        # chosen at 121 and the fill was then taken at 41, and what went down
        # was a mottled cast of the words it had just erased.
        out[box] = _feathered(out[box],
                              focus_background(page.image[box], width), ink)
        did.append(r)
    # NOT `clean_route` here: the report writes that from the first pass's own
    # record a few lines later, so anything set now is overwritten. Said after
    # it instead — see where this is called.
    return did


# How much cleaning has to have happened in a box before it is worth asking the
# model to draw the whole of it again. Below this the clean touched a few
# pixels — a stray mark, a rim — and there is nothing to make coherent.
REDRAW_LEAST = 200
# How much of the distance from the original the answer has to keep in the
# writing's own footprint. This is the one thing that can go wrong that would
# not be an improvement: the model, handed the page as it arrived, draws the
# words back.
REDRAW_GHOST = 0.8


def redraw(page: Page, out: np.ndarray, neural=None, again=()) -> list:
    """The last step of a clean: ask the model to draw the cleaned area again,
    once, as one piece.

    lee: *"can we add a redraw step that cleans up the art and the area that
    the cleaner cleaned?"*, *"it shoud mak sure lines are staignt and curvers
    ar matching"*, and then, of the local version of this: *"remove teh
    redrawing it did nothing try to improve on what i asked with the other
    tool"*.

    He is right that it did nothing, and the reason is worth writing down.

    Nothing local can draw. A median, Telea and a copy of real texture from
    elsewhere on the page all measured the same, and none of them knows that a
    panel border was running through the box. The local version carried lines
    across by hand — find a mark running into the patch, find one leaving it
    going the same way, curve between them — and it worked on the fixtures and
    on three boxes of the chapter, and it was never going to do more, because
    every rule that kept it from drawing ON the artwork also kept it from
    drawing most of the lines. It could not touch a gradient, a shadow, a face,
    or any line it was not certain about.

    A model draws, and it is already what this cleaner hands its hard boxes to.
    What it has never been given is the WHOLE of what the clean painted, in one
    go, on the page as it arrived. On a box that needed the second pass it has
    been given two masks over the same box at two different times, and the two
    answers meet somewhere in the middle — and where the first answer came from
    a local route, the model has never seen that part at all. That seam is the
    thing left to fix here.

    **Only boxes the second pass touched.** Those are the boxes that were
    painted twice, which is the whole reason to paint them once instead: on
    lee's chapter that is 21 of 145, so the page costs a handful of calls
    rather than one per box.

    **Judged on one thing.** A redraw that works puts detail BACK — lines,
    gradient, tone — so any measure of "how much is going on in this box" goes
    up when it succeeds, and no such measure can be used to accept it. The
    single thing that can go wrong and not be an improvement is the model
    putting the words back, which it can do because it is being handed the page
    with the words still on it. So that is what is measured, in the writing's
    own footprint, and nothing else. `_gave_up` already covers the other
    failure — an answer that erases the area instead of drawing it.
    """
    if neural is None or page.image is None or page.image.ndim != 3:
        return []
    if out.shape != page.image.shape:
        return []
    H, W = out.shape[:2]
    changed = np.abs(out.astype(np.int16)
                     - page.image.astype(np.int16)).max(2) > 6
    if not changed.any():
        return []
    did = []
    for r in again:
        x, y, w, h = (int(v) for v in r.bbox)
        x, y = max(0, x), max(0, y)
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
        if w < 13 or h < 13:
            continue
        box = (slice(y, y + h), slice(x, x + w))
        patch = changed[box]
        if patch.sum() < REDRAW_LEAST:
            continue
        # How far the painted area has been taken from the page it started as.
        # Measured over what was PAINTED, which is also all the model is
        # allowed to write on: everywhere else in the box the answer and the
        # original are the same pixel, before and after, and averaging those in
        # only divides both sides of the comparison by the same number.
        def _away(z):
            return float(np.abs(z.astype(np.int16)
                                - page.image[box].astype(np.int16)
                                ).max(2)[patch].mean())

        had = _away(out[box])
        if had < 1.0:
            continue                       # nothing was taken off here anyway
        job = {"win": box, "mask": _dilated(_u8(patch), MODEL_PAD),
               "tight": _u8(patch)}
        # Undone over the CONTEXT window and not just the box. `_run_neural`
        # hands the model a crop with `NEURAL_CTX` of page around the region
        # and writes its answer back over that whole crop, so putting only the
        # box back leaves a rim of somebody else's redraw on the page.
        ctx = _grow(box, out.shape, NEURAL_CTX)
        keep = out[ctx].copy()
        try:
            _run_neural(out, job, neural, again=page.image)
        except Exception:
            job["fell_back"] = True
        if job.get("fell_back") or _away(out[box]) < REDRAW_GHOST * had:
            out[ctx] = keep                # it drew the words back, or refused
            continue
        did.append(r)
    return did


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
            # ...and never over a FOCUS box. Its mask was already read
            # against its own local background, which is a better reading than
            # a global split by construction — that is what the switch is for.
            # On lee's page 030 the split is taken over a navy plate carrying a
            # white frame, so it separates the FRAME from everything else and
            # puts the gold in with the sky.
            if inverted and _kinds.family_of(r.kind) != "sfx" \
                    and not in_focus(r):
                base = np.zeros(gray.shape, bool)
                base[w] = _letterlike(polar) > 0
        # ...and only now, with every reading this cleaner has had its go, ask
        # whether the writing is still not in the mask. Asked here rather than
        # where the mask is built, because the rescue above is a reading too:
        # white text on a black panel is handled correctly by it, and a focus
        # decision taken before it fires on that page for no reason.
        #
        # lee, told the switch was one click per box: *"no cliking or anything
        # it shoud be automatic"*.
        bx0, by0, bw0, bh0 = (int(v) for v in r.bbox)
        bx0, by0 = max(0, bx0), max(0, by0)
        bw0 = max(1, min(bw0, gray.shape[1] - bx0))
        bh0 = max(1, min(bh0, gray.shape[0] - by0))
        crop = (slice(by0, by0 + bh0), slice(bx0, bx0 + bw0))
        if in_focus(r):
            # Read against the box's own background instead. Written into the
            # region as well, because the fitter and the report both ask the
            # region what happened to it.
            lit = np.zeros(gray.shape, np.uint8)
            lit[crop] = focus_ink(page.image[crop])
            if full_area is not None:
                lit[~(full_area > 0)] = 0
            if lit.any():
                base = lit > 0
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
        #
        # ...or, on a box somebody TURNED, the box they turned. See `_own_area`.
        own = _own_area(r, gray.shape, DILATE_PX)
        box_lim = np.zeros(gray.shape, np.uint8)
        bx, by, bw, bh = (int(v) for v in r.bbox)
        if own is None:
            box_lim[max(0, by - DILATE_PX):by + bh + DILATE_PX,
                    max(0, bx - DILATE_PX):bx + bw + DILATE_PX] = 1
        else:
            box_lim[own] = 1
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
        # Not on a focus box: what this adds is ink the FIXED levels find in
        # the doorstep, and on a box that needed the switch those levels are a
        # reading of the background — on page 030 they would adopt the night
        # sky. A focus mask is not clipped at a threshold in the first place, so
        # it has no half-glyphs to finish.
        #
        # Off `bbox` even on a turned box, deliberately. What this adds is
        # doorstep ink joined to ink the box already caught, and "doorstep"
        # here is a RING round a rectangle — handed the turned box's bounding
        # rectangle it would be a ring eight pixels outside a shape much bigger
        # than the box, which the fence undoes again anyway. The corners a turn
        # sweeps out are already the region's own, through `box_lim` above.
        if not in_focus(r):
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
        # ...and then the fill is TRIED, and kept only if it worked. See
        # `_slab_worked`: the one route that knows what it is painting is the
        # one route that can be marked, and lee's page 024 is a balloon the
        # sample called flat and the fill left the writing standing on.
        slab = None
        if mine and not (neural is not None and neural_all) and not in_focus(r):
            level = _bg_level(g, area, ink, bg, spare_c)
            wide = _with_halo(g, area, d, spare_c, level, inverted)
            tried = page.image[w].copy()
            tried[wide > 0] = bg.astype(tried.dtype)
            if _slab_worked(page.image[w], tried, ink):
                slab = (wide, level)
            else:
                mine = False
        if in_focus(r):
            # A FOCUS box paints its own background back over the writing.
            #
            # The switch was put in for the MASK — the fixed ink levels read
            # these boxes' backgrounds instead of their words — but the same
            # median that finds the mask has already produced the thing every
            # other route is trying to reconstruct: the box as it would look
            # with the writing lifted off, gradient, frame, beam and all. There
            # is nothing to guess and nobody to ask.
            #
            # Measured on lee's four bad boxes, writing left afterwards:
            # gold on cream 41% -> 9%, gold on navy 15% -> 7%, the see-through
            # balloon 22% -> 12%, the gold plate 88% -> 7%. It also costs
            # nothing: these were going to the paid model and coming back with
            # the gold still on them.
            back = focus_background(page.image[w])
            out[w][d > 0] = back[d > 0]
            rec["how"] = "focus"
        elif slab is not None:
            # The fixed dilation is a guess at stroke width and it guesses low
            # on a big scan, leaving a faint outline of every character. The
            # background here is flat, so the haze can simply be measured
            # against it instead.
            d, level = slab
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
    reach_k = np.ones((2 * GLYPH_REACH + 1,) * 2, np.uint8)
    for r in page.regions:
        if r.text_mask is None or getattr(r, "skip_clean", False):
            continue
        x, y, w, h = (int(v) for v in r.bbox)
        # The doorstep, and nothing more: a glyph drawn a little past its box
        # has to be finishable, or "the text must go" and "never outside the
        # box" cannot both be true. GLYPH_REACH is that margin — eight pixels,
        # about half a stroke — and only ink CONNECTED to what the box caught
        # can use it (see _complete_strokes).
        #
        # ...and on a box somebody TURNED, that box, not the upright rectangle
        # it was derived from. See `_own_area`.
        room = _own_area(r, gray.shape, GLYPH_REACH)
        if room is None:
            room = np.zeros(gray.shape, bool)
            room[max(0, y - GLYPH_REACH):y + h + GLYPH_REACH,
                 max(0, x - GLYPH_REACH):x + w + GLYPH_REACH] = True
        # ...AND inside the balloon, where there is one.
        #
        # The box is a rectangle and a balloon is not, so a box drawn round
        # writing that reaches the edge of its bubble also covers a corner of
        # whatever is outside it. lee, with a screenshot of a night sky with a
        # white rectangle bitten out of it beside a speech bubble: *"the box
        # extarnt out f the bubble but the clenner shoud not mess uo teh bubble
        # this bad"*.
        #
        # A balloon is the page saying THE WORDS ARE IN HERE. Nothing outside
        # one can be this region's typesetting, so nothing outside one is this
        # region's to repaint — the outline included, which is why the sky came
        # back square.
        #
        # Only where a balloon was actually FOUND: `bubble_mask` is None for a
        # bare box, and `place_mask()` would hand a sound effect its own ink,
        # which is far too tight to clean against. Grown by the same doorstep
        # the box gets, because the detected interior stops a little short of
        # the drawn outline and ordinary writing pokes past it.
        #
        # This is safe to do only because the mask can now be trusted to cover
        # the writing: it used to have bays bitten out of it exactly where a
        # word was, and clipping to it then would have PRESERVED that word.
        # See `detect.balloon._no_bays_in_the_writing`.
        bm = getattr(r, "bubble_mask", None)
        if bm is not None and getattr(bm, "shape", None)[:2] == gray.shape[:2]:
            room &= cv2.dilate((bm > 0).astype(np.uint8), reach_k) > 0
        allowed |= room
    out[~allowed] = page.image[~allowed]

    # ...and then the second step, over whatever the first one left standing.
    # After the fence, so it inherits every rule about where a region may
    # paint; it reads the page the first pass produced and touches nothing the
    # first pass already cleaned. See `second_pass`.
    again = second_pass(page, out, neural)

    # ...and last of all, the artwork — but only where there is a model to
    # redraw it with. See `redraw`.
    drawn = redraw(page, out, neural, again)

    # Who cleaned what. Every argument about this page's cleaning so far has
    # been conducted by looking at it and guessing; this is the count.
    # "fell back" is a region the model was asked for and did not deliver.
    stats: dict = {}
    if again:
        stats["second pass"] = len(again)
    if drawn:
        stats["redrawn"] = len(drawn)
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
    # ...and the second step, said last because everything above rewrites the
    # route from the FIRST pass's own record. A box that needed both says both:
    # the person looking at the report wants to know which of these had writing
    # standing on them after the ordinary clean.
    for r in again:
        r.clean_route = ((r.clean_route or "") + " + second").strip()
    for r in drawn:
        r.clean_route = ((r.clean_route or "") + " + redraw").strip()
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
