"""Erase source text.

Most manga bubbles have a flat white interior. For those, filling with the
modal background colour is instant and cleaner than any neural inpainter.
Reserve the expensive path for text over artwork, gradients and screentone.
"""
from __future__ import annotations

import traceback

import cv2
import numpy as np

from . import kinds as _kinds
from . import stopping as _stopping
from .models import Page, TextRegion, turned_box

INK = 128              # pixel <= this counts as ink
BRIGHT = 200           # ...and pixel >= this, on a light-on-dark panel
OUTSIDE_SHARE = 0.35   # ink mostly beyond the region is art, not typesetting
GROW_PX = 9            # slack between the detected interior and the real bubble
RECT_FILL = 0.97       # mask area / bbox area above this counts as a rectangle
DILATE_PX = 3          # anti-aliased glyph edges leave grey haze otherwise
FLAT_STD = 12.0        # background std below this counts as flat
FLAT_LIGHT = 200.0     # ...and this pale as well, to be the local fill's own job
# What counts as a FULLY WHITE bubble - the only thing the local fill keeps once
# a model is configured. lee: *"make it so that the local celener is only used
# fro fully white bubbles every thing else should be handles by the ai
# clenner"*. Both halves matter: `FLAT_STD` at 12 admits paper grain and light
# screentone, and `FLAT_LIGHT` at 200 admits pale grey and the lighter tones -
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
# 3px is not the same guess. It paints the skirt the haze sweep cannot see -
# the skirt is within HALO_TOL of the background, which is exactly what the
# threshold is built to ignore - and a local fill has nothing else to cover it
# with. The model does not need it because it redraws the area regardless.
#
# The fence at the end of inpaint_page bounds the result to the box, its
# doorstep, and the balloon.
NEURAL_CTX = 96        # pixels of surrounding page handed to the model as context
HALO_REACH = 9         # how far past the hard mask a glyph's haze can carry
HALO_TOL = 4           # grey levels under a flat background that still read as ink
TONE_REACH = 6         # the same sweep on texture, kept shorter - see _local_bg
TONE_TOL = 10          # and stricter, because artwork is legitimately dark
GHOST_TOL = 6          # ink still this much darker than its surroundings = ghost
# ...and the same question asked another way, because a median cannot see a
# faint one. `ghost_delta` compares the MEDIAN level where the ink was against
# the ring round it; a ghost three grey levels off white is plainly readable
# and three is under GHOST_TOL. Lowering GHOST_TOL to reach it fires on grain.
#
# What a ghost always has, however faint, is EDGES - it is writing. So the
# second question is about high frequency rather than level: how much detail is
# left inside the painted area, on a page that has none around it.
#
# Measured on lee's chapter 3 (23 manga pages, 252 painted areas) and on the
# 15-page manhwa (120 areas, his own plates):
#
#     flat surroundings        199 of 252   detail inside: median 0.02
#     the 164 flat-fill boxes               every one under 0.30
#     everything above 0.30                 telea or pattern copy - the local
#                                           fallback, and visibly ghosted
#
# 0.35 is an order of magnitude over the floor and above everything the flat
# fill does. GHOST_FLAT is what counts as "no detail around it": past that the
# ring has texture of its own and this test says nothing - which is `_gave_up`'s
# argument in reverse.
GHOST_HF = 0.35        # detail left where the surroundings have none = a ghost
GHOST_FLAT = 0.6       # ...and this is how flat the surroundings have to be
# ...and the THIRD question, which neither of those two can ask: writing the
# mask NEVER COVERED. Both tests above start from `rec["ink"]` - from where the
# mask went - so a kana sitting a little apart from the column is invisible to
# them by construction, and that is what every crop of residue lee has sent is.
# Measured on his page 001: 95% of the ink inside a cleaned region is inside the
# mask, and the leftovers are the 5%.
#
# Inferring it from TONE - "the balloon is clean, so anything off its level is
# ink somebody missed" - was tried and marked a balloon outline, a rock texture,
# hair, speed lines and a whole small panel of artwork as writing to erase. A
# level cannot tell writing from a drawing, and that is not a threshold that
# needs tuning, it is the wrong question.
#
# What CAN tell them apart is the thing trained to: read the finished plate with
# the text segmenter, and anything it still calls text, inside a region this page
# actually cleaned, is text that is still there. See `_reread`. The reader is
# injected rather than imported - `inpaint` knows nothing about weights files -
# and a page with no reader configured cleans exactly as it did before.
RESIDUE_PAD = 2        # slack round what was erased before calling it missed
# The ground a box is written on, where it has one. See `_off_the_ground`.
# GROUND_TOL is measured, not chosen: over lee's 221 boxes the paper inside a
# balloon sits within 3 levels of its own median and a glyph is 200 off it, so
# anything from 5 to 40 separates them - 12 is the middle of that, and the same
# number `FLAT_STD` already calls flat.
GROUND_TOL = 12        # levels off the box's own median that count as writing
GROUND_CLEAR = 0.55    # ...and this much of the box has to BE the ground
# ...and this is how much the ground may wander and still be ONE ground, as the
# median distance from the median - a statistic half the box has to be inside,
# so the writing cannot move it. Measured over lee's 221 boxes: 80% of them are
# at 6 or under (paper, and the flat interior of a black balloon), his grainy
# brushed-black balloon is at 12, and everything this test has to refuse starts
# at 37 - the line screen on the shirt at 37, the dot tone at 70, the credits
# over grass at 51.
GROUND_MAD = 15        # ...and a ground that wanders more than this is not one
GROUND_AROUND = 0.25   # this much of the ring outside the box has to be it too
# ...and this many of the box's hundred cells have to be EMPTY. Writing leaves
# margins and the space between two lines; a field of tone leaves nothing.
# Measured over the 189 boxes on lee's chapter that get this far: the emptiest
# tenth are dense captions at 7 cells of 100, and a light line screen and a
# light dot screen both leave 0.
GROUND_GAPS = 0.03
# ...and this much of the smaller of two readings has to be shared before one
# of them may replace the other. See `_agrees`.
GROUND_AGREE = 0.25
# ...and how wide a mark has to be before it is a SHAPE and not a stroke. A
# balloon with a drawing in it is a box with one solid area in it, and "off the
# ground" cannot tell that from a word by level alone. Writing is made of
# strokes: the widest on lee's pages is a display sound effect at about 20
# pixels, and nothing survives an erosion by 15 unless it is 31 across.
GROUND_SOLID = 15
GLYPH_STROKE = 3       # written strokes are this thick at least; tone dots are not
GLYPH_MIN_AREA = 60    # ...and a letter covers at least this much, however thin
GLYPH_MIN_SIDE = 5     # ...and is at least this wide and this tall
MASK_MAX_SHARE = 0.55  # a "text" mask covering more of its region than this is not text

# The cleaner's own version. A finished plate is cached on disk and reused
# forever, and its name is built from the page, the boxes and the settings -
# none of which change when THIS FILE does. So every improvement to the cleaning
# arrived invisible: the pages had plates already, the plates were reused, and
# the answer to "did it get better" was the picture from before the change. lee,
# after a round of fixes: *"nothing vhanged"*.
#
# Bump this on any change to how a page is cleaned. Every plate made by the old
# code retires itself the moment the new code loads.
# 2026-07-31-a: the local fill now keeps only FULLY WHITE bubbles once a model
# is configured (see WHITE_STD / WHITE_LEVEL). Every page cleaned before that
# still had a plate made by the old rule, and a plate is reused for ever - so
# without this bump the change would have arrived invisible on exactly the
# pages lee was looking at.
# 2026-08-12-a: four changes in one day, and this was forgotten for all four -
# the balloon's bays filled, the fence closed at the balloon, `MODEL_PAD` cut
# from 6 to 2, and `glyphs_only` taught to see mid-tone ink. lee, sent a gold
# plate that was fixed and measured here and still on the page in his editor:
# *"can you explain why its not clening that text?"* This is why. It is the
# fourth time; `test_the_stamp_is_bumped_when_the_cleaner_changes` now compares
# a fingerprint of this file against the stamp, so the next one cannot ship.
# 2026-08-12-b: the glyph mask a SAVED record is rebuilt with is read by tone
# now rather than by darkness, which is how gold on cream finally comes off
# (`project.region_from_record`). That is not in this file, and the plate cache
# does not watch that file either - so the stamp covers it and the fingerprint
# test reads both.
# 2026-08-12-d: the gold-text work is OUT again, at lee's word - *"right now
# hwe teh gold text is clenned the thither stuff gets broken and teh clenning
# gets sigmifivanly worst"*. The tone split in `project.region_from_record` and
# the union in `glyphs_only` both go, so the plates built under -b and -c retire
# and the chapter comes back to what he called a safe point.
# NOT bumped 2026-08-22, and the reasoning is written down because the next
# person to see the fingerprint test red will have to do it again. Two things
# changed in this file since the stamp: the em dashes in the prose became
# hyphens, and `_stopping.check()` went into the region loop. The first is
# comments. The second only ever RAISES - a run that finishes produces the same
# plate to the byte, and a run that does not finish produces no plate at all -
# so no cached plate on anybody's disk is stale because of it. Retiring a
# chapter of plates costs a re-clean, and it buys nothing here.
# 2026-08-22-a: the ghost sweep gained a second question. `ghost_delta` is a
# median and cannot see a haze three grey levels off white; `ghost_detail` asks
# whether anything is still DRAWN where the page around it is blank. It changes
# pixels as well as flags - a box that now reads as ghosted is re-filled or
# asked of the model again - so every plate made before it has to retire.
# 2026-08-23-a: the finished plate is READ, where there is a reader to read it
# with, and writing the mask never covered is erased on a second go (`_reread`).
# It changes pixels on every page that had residue on it - which is the whole
# point - so the plates that still have that residue on them have to retire.
# 2026-08-23-b: and the SCAN is read too, which changes what gets erased on
# every page with a sound effect or a caption on artwork - see `_reader_ink`.
# ...and a fully white bubble keeps the flat fill even with "the model does the
# whole page" chosen, which changes every plain balloon on lee's chapter.
# 2026-08-23-c: the doorstep stops at the balloon (`_complete_strokes`), so a
# box whose corner lands on a bubble's outline no longer follows that outline
# out of the box and bites a wedge out of the edge. lee: *"this is bad its
# reaching out of teh box"*.
# 2026-08-23-d: what the writing IS is measured against the box's own ground
# where it has one, and asked of the reader where it has not (`_off_the_ground`).
# Five rescues collapse into that pair, and it changes the mask on 189 of lee's
# 221 boxes. lee: *"i dont wan you to hard code it for this exmaple i wnat you
# to caome up with a system taht clenneas them all teh time on any manga"*.
# 2026-08-23-e: ...and what stands off that ground has to be CONTAINED in the
# box before it is erased (`_contained`). Without it the rule took the rain
# behind a caption, the outline of a bubble and a man's head, all of which
# stand off the paper exactly like a stroke. lee: *"the ai shoud try to keep
# teh boes instd of removing it ... this guy head is gone even though uts not
# on teh text"*.
# 2026-08-24-a: on a plain white bubble the clean is now EXHAUSTIVE. The colour
# is known, so anything left inside the balloon that is not that colour is a
# leftover, and `_all_of_it` erases it whether or not the ghost test - a median
# over the whole mask, blind to two dashes among three thousand clean pixels -
# can see it. lee, with a crop of a cleaned balloon with two dashes of a kana
# still in it: *"there ate still residue on the whoite boxes ... make the
# clenner allways clenne out all the text"*.
# 2026-08-25-a: the doorstep finishes a stroke and no longer follows a line
# that merely touches one. It reaches eight pixels past the box to complete a
# glyph drawn a little too big, and it was reaching that far along the HAIR
# behind a sound effect, because hair the kana touches is one component with
# them: 1,347px of it on lee's page 008, 86% of everything the doorstep added
# to that box, and it came back chopped into segments. lee, with the crop:
# *"thry to have the clneer fix his"*. Over the chapter, 8,532px less of the
# page painted for 32px more readable residue out of 801,840. The same pass
# gives a TURNED box a doorstep round the box that was turned, instead of round
# the upright rectangle it was derived from - a stroke leaving the quad's
# corner was outside every ring the rule knew about and was left standing.
# 2026-08-29-a: the glyph mask a SAVED record is rebuilt with reads which way
# round the balloon is, instead of assuming ink is dark
# (`project._writing_in`). On lee's page 009 - a solid black balloon with
# white Japanese in it - the old line marked the BALLOON as writing and the
# letters as clean: 24,164 pixels of "ink" in a balloon of 26,758. The
# cleaner was asked to erase ninety per cent of the balloon, `_flat_from` had
# not one pixel of ground left to sample, and Telea filled it from the dotted
# screentone outside. That is not in this file and the plate cache does not
# watch that file either, so the stamp covers it - the same arrangement, and
# the same reason, as 2026-08-12-b.
# 2026-08-29-b: a saved outline is READ against the page before it is used
# (`project._one_ground`), so a box whose outline runs off its balloon onto the
# artwork stops asking for the artwork to be erased. Page 019's outline is a
# rectangle a third bigger than its balloon in every direction, and the writing
# read out of it took in the hatching in the corners. Three of lee's 137
# outlines move; the other 134 come back untouched and their plates would be
# identical - but a plate is keyed on this stamp and not on its pixels, so
# every one of them retires and is made again.
ALGO = "2026-08-29-b"


def ink_and_background(gray: np.ndarray, area: np.ndarray,
                       fallback: np.ndarray
                       ) -> tuple[np.ndarray, float, bool]:
    """Find the typesetting inside `area`, whichever way round the tones are.

    Assuming dark text on a light background wrecks white-on-black panels: the
    whole dark background gets treated as text, erased, and filled with the
    colour of the typesetting. Split the region in two by Otsu instead, and let
    the rim decide which side is the background - a bubble or panel touches
    its own edge, the words in the middle of it do not.

    Returns the glyph mask, the background level to fill with, and whether the
    tones were the other way round (light typesetting on a dark panel).
    """
    vals = gray[area]
    if vals.size < 40:
        # Too little to split. It used to return two values here and three
        # everywhere else, so a region with a placement area under 40 pixels
        # took the WHOLE PAGE down with a ValueError halfway through cleaning -
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
    # split is meaningless - a picture, not words - so leave it alone.
    if not ink.any() or ink.sum() > 0.55 * area.sum():
        return fallback, float(np.median(gray[area])), False
    level = float(np.median(gray[bg])) if bg.any() else float(np.median(vals))
    return ink, level, bool(bg_is_dark)


def _letterlike(mask: np.ndarray, min_stroke: int = GLYPH_STROKE) -> np.ndarray:
    """Drop everything in `mask` too thin to be a written stroke.

    This is only for a mask that came from a blind light/dark split rather than
    from the text detector. On a black panel the light side of that split is the
    SCREENTONE as well as the words, and a field of dots dilated by the few
    pixels a glyph edge needs is the whole panel - which is then handed to the
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
    # comes out of the cleaner untouched - half a page of text still standing
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
# finds - measured over the chapter, the median box holds 0.99 of the split and
# 137 of 139 are over 0.95, while the plates are at 0.15 and 0.39, with nothing
# in between.
#
# It cannot be done that way. On SCREENTONE the split legitimately finds far
# more than the detector - every dot - and the detector is the one that is
# right; `test_the_widened_mask_does_not_eat_the_screentone_around_it` is that
# case and it goes red immediately. Gating on `is_screentone` does not separate
# them either: measured on this chapter it answers True for the gold plate and
# for ordinary bubbles alike.
#
# What is needed is a reading of WHAT the split found that the mask did not -
# rows of letters, or scattered dots - and neither the ratio nor the tone test
# is that. Left undone rather than shipped half-measured, because the cost of
# getting it wrong is artwork erased, which is the one thing that cannot be
# undone from a flag.

GLYPH_REACH = 8        # how far past its box a caught stroke may be followed
# ...and how much of a mark may still lie beyond that before it stops being a
# stroke's tail and starts being a line that merely touches the writing. The
# same share `glyphs_only` and `_only_what_the_box_contains` use for the same
# claim, named separately because this one is measured against the DOORSTEP.
DOORSTEP_SHARE = OUTSIDE_SHARE


def _complete_strokes(erase: np.ndarray, gray: np.ndarray, inverted: bool,
                      bbox, inside: "np.ndarray | None" = None,
                      area: "np.ndarray | None" = None) -> np.ndarray:
    """Finish the strokes the box cut in half, and nothing else.

    The mask is clipped at the box, so a glyph drawn a little past it comes out
    erased up to the cut and left standing after it - the stubs and rims in
    lee's screenshots, and the reason "the text is non negotiable" was not being
    met. What is added here is ink in the DOORSTEP - the ring of `GLYPH_REACH`
    pixels just outside the box, never inside it - that is joined to ink the box
    already caught. A stroke leaving the box is completed; line work crossing
    the middle of the box, which may well touch a glyph, is not adopted, because
    nothing inside the box is added at all.

    `inside` says a BALLOON was found round this box, and it buys one extra
    condition: the doorstep may FINISH a stroke, not adopt one. lee's page 003
    is why. The corner of a box lands on the balloon's own outline, the mask
    catches 23 pixels of it, and this rule followed the arc out of the box and
    took 125 more - so the fill painted white over the outline and the leaves
    behind it, and the bubble came back with a wedge cut out of its edge. He
    sent the crop: *"this is bad its reaching out of teh box"*.

    Position cannot tell those apart: the outline sits just outside the
    detected interior, and so does writing that pokes past it, which is the
    whole reason the fence dilates the balloon at all. What tells them apart is
    the SHARE. A bubble is drawn round its words with room to spare, so a
    stroke this box really caught is mostly inside it - 0.93 on the stroke in
    `test_a_glyph_drawn_past_its_box_is_finished_not_cut_in_half`. The bubble's
    outline is 0.155: the box did not catch that stroke, it clipped a corner of
    something that goes right round the balloon.

    Only where there IS a balloon. Measured over lee's chapter, 146 components
    are adopted here and 61 of them have more in the doorstep than the box
    caught - but 48 of those 61 are sound effects, whose box is drawn tight on
    a mark that genuinely carries on, and refusing them puts the stubs back:
    *"the tetxt is a non negotiable they need to go"*. A box with no balloon
    behaves exactly as it did.

    `area` is the box somebody TURNED, when they turned one. Everything here is
    a ring round a shape, and for a turned box the shape is not `bbox` - `bbox`
    is the upright rectangle the turn is computed from, and the quad's corners
    sweep well outside it. A stroke leaving the quad's lower-right corner
    landed clean outside the ring built round the rectangle and was never
    offered to the doorstep at all: the fixture in
    `test_a_glyph_poking_past_a_turned_edge_still_comes_off` came back with
    125px of 136 still standing, a bead of ink hanging off the corner. A
    comment here used to call using `bbox` deliberate, on the grounds that a
    ring round the turned box's BOUNDING RECTANGLE would be a ring round
    something much bigger than the box. That is true and it is an argument
    against the bounding rectangle, not for it - the quad itself is neither.
    """
    m = _u8(erase)
    if not m.any():
        return m
    x, y, w, h = (int(v) for v in bbox)
    H, W = gray.shape[:2]
    if area is not None:
        box = area > 0
        room = cv2.dilate(box.astype(np.uint8),
                          np.ones((2 * GLYPH_REACH + 1,) * 2, np.uint8)) > 0
    else:
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
    # which pieces of doorstep ink touch what the box caught, labelled ACROSS
    # THE PAGE so a mark that carries on past the doorstep can be told from one
    # that ends in it - the same reason `glyphs_only` labels the page and not
    # the crop: cut at the boundary, everything looks self-contained
    _, lab = cv2.connectedComponents(full.astype(np.uint8), 8)
    touching = set(np.unique(lab[(m > 0) & box])) - {0}
    if not touching:
        return m
    # A STROKE THE BOX CUT ENDS IN THE DOORSTEP. That is what a doorstep is
    # for: eight pixels, about half a stroke, the tail of a glyph drawn a
    # little past its box. A mark with most of itself still to come out there
    # is not a tail, it is a line that happens to touch the writing - and on a
    # sound effect, drawn over the picture rather than in a bubble, that is the
    # ordinary case. lee's page 008: the hair behind あはは touches the kana, so
    # the doorstep followed the strand out and the fill took 1,347px of hair -
    # 86% of everything the doorstep added to that box. He sent the crop of it
    # coming back in pieces: *"thry to have the clneer fix his"*.
    #
    # A SHARE and not a yes-or-no. "Does any of it lie past the doorstep" reads
    # beautifully and is useless: one anti-aliased pixel at the tip of the
    # 1,804px bar in `test_a_glyph_poking_past_a_turned_edge_still_comes_off`
    # lies past it, and that one pixel threw the whole stroke away and put the
    # stub back. `OUTSIDE_SHARE` is the number the rest of this file already
    # uses for exactly this claim.
    #
    # The `inside` clause below cannot stand in for it. That one asks how the
    # ink is SHARED between box and doorstep, which a long mark crossing a
    # small box passes comfortably, and it only runs where a balloon was found
    # - which is never, on the boxes this is about.
    kept = set()
    for li in touching:
        comp = lab == li
        total = int(comp.sum())
        if total and int((comp & ~room).sum()) > DOORSTEP_SHARE * total:
            continue
        kept.add(li)
    touching = kept
    if not touching:
        return m
    if inside is not None:
        touching = {li for li in touching
                    if int(((lab == li) & box).sum())
                    >= int(((lab == li) & doorstep).sum())}
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

    NOT ON A SOUND EFFECT, and it was measured before that was left alone.
    `place_mask()` hands an effect its own INK - right for typesetting one along
    the mark it replaces, and not an area at all - so the shape test below bails
    out and the rule has never run on one. Giving it the BOX instead, which is
    the obvious repair, costs more than it saves: over lee's 48 sound effects it
    took 29,679px out of the masks, and 19,899 of those were pixels the text
    detector calls writing against 8,195 of artwork. An effect is drawn over the
    picture with its box pulled tight around it, so its own strokes fail
    containment as readily as the artwork behind them do.
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
        # Nothing survived - the box is probably tight around text touching its
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
    it was scanning all thirty megapixels - twenty-odd regions each dilating,
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
    on a gradient, on artwork, there is no single level - so the sweep was
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
    guesses low. What survives is a faint outline of every character - too
    light to read as text, too dark to read as clean, and unmistakable once the
    bubble around it is pure white. No guessing is needed: anything measurably
    darker than the background, close to ink already being erased, IS that ink.

    `bg_level` is that background, and it is either one number (a flat bubble
    has only one) or a whole array from `_local_bg` (screentone, gradients,
    artwork - where the level is different in every part of the region). The
    test is the same either way, which is the point.

    `spare` is what `glyphs_only` deliberately refused to erase - the bubble
    outline, artwork crossing the box - and the haze sweep must not quietly
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


def ghost_detail(after: np.ndarray, ink: np.ndarray) -> float:
    """How much detail is left where the ink was, on a page that has none
    around it. 0.0 when the surroundings are not flat enough to ask.

    The companion to `ghost_delta`, and deliberately a different statistic.
    That one asks how DARK the old ink still is, as a median, and a faint even
    haze barely moves a median. This one asks whether anything is still DRAWN
    there - a high-pass, which is what writing is made of and what a fill is
    not.

    Both are needed. A thick grey smear moves the median and blurs the edges;
    a three-level haze of the actual glyph shapes moves neither the median nor
    `_gave_up`'s standard deviation, and is the one lee's pages kept.
    """
    m = (ink > 0).astype(np.uint8)
    core = cv2.erode(m, np.ones((3, 3), np.uint8)) > 0
    if core.sum() < 20:
        core = m > 0
    ring = (cv2.dilate(m, np.ones((2 * HALO_REACH + 5,) * 2, np.uint8)) > 0) \
        & ~(_dilated(m, HALO_REACH) > 0)
    if core.sum() < 20 or ring.sum() < 20:
        return 0.0
    g = after.astype(np.float32)
    if g.ndim == 3:
        g = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hf = np.abs(g - cv2.GaussianBlur(g, (0, 0), 2.0))
    out = float(np.median(hf[ring]))
    if out >= GHOST_FLAT:
        return 0.0            # the artwork round it has detail of its own
    return float(np.median(hf[core]))


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
    background is what makes a plain white bubble measure as textured - which
    then sends it down the screentone or neural path, where the same skirt
    survives as the faint outline of the words. Fall back to a tight ring only
    when the region is too small to stand back in.

    `spare` is ink the region contains but is not erasing - the slice of bubble
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
    tone in it - see WHITE_STD.

    The sample stands off the ink by `DILATE_PX + HALO_REACH`, which is the
    distance the halo fill can reach, so the question is asked over the paper
    the answer will be used to paint.

    There used to be a fallback: when that left fewer than thirty pixels, ask
    again with a three-pixel stand-off instead. It is gone, and this is the
    fix for lee's *"it jusm amde a white box insated of matching the
    backgroung"* - a column of vertical Japanese on artwork.

    A column's box is thirty pixels wide. The ink grown by twelve covers ALL
    of it, so the proper sample is not small, it is EMPTY - measured on a
    fixture cut to his: zero pixels at twelve, and the fallback then handed
    back a three-pixel rim hugging the letters. On his page that rim is the
    white cloak the words are printed on, so the rim says "flat, and white",
    and that verdict licenses `_with_halo` to paint white out to nine pixels,
    and `_sweep_ghosts` to widen it to fifteen - across the hatched hood
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

    The flat fill's entire justification is that the colour is KNOWN - so
    unlike every other route, it can be checked. Paint it and look: if the box
    still shows the words where the paint went, the colour was not known.

    lee's page 024 is why. A see-through balloon with a beam of light across it
    was called flat, because `_flat_from` samples the paper immediately AROUND
    the words and on that box the words cover half of it - so the sample is a
    corner, and a corner of a gradient is flat. A slab of one grey then goes
    down over the whole box and the faint writing survives on top of it.

    Which is the worst outcome available, because it also blinds the second
    pass. That step reads the page the FIRST one produced - it must, or it
    would undo work already done - and what it now reads is a uniform field:
    it finds 4% of the box where the original shows 60%, so it erases almost
    nothing and a fifth of the writing is left legible. lee: *"can this be
    fixed?"*.

    Checking the fill instead of second-guessing the verdict is what makes this
    safe. Every attempt to catch page 024 by measuring the balloon BEFORE
    painting it - the same flatness question asked over a wider sample - either
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
    background - in COLOUR, and never against a fixed level.

    Everything else in the cleaner reads a page in grey and splits it at a
    number. That is a reading of black-on-white, and lee's chapter keeps
    handing back boxes it is simply not true of:

    * gold on navy (page 030) - 84% of the box is "dark ink" and the mask is
      the night sky. Gold and navy are three greys apart and half the colour
      wheel apart.
    * gold on cream (pages 003, 012) - 91% of the box is "bright ink".
    * dark words on a translucent balloon with a beam of light across it
      (page 024) - the background runs 0 to 255 inside one box, so no single
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
    each stroke reaches, growing from those seeds and nowhere else - ink that
    never reaches the strong level is not writing and is never picked up,
    however much of it there is.

    **Nothing that runs off the edge of the box.** Writing sits wholly inside
    the box drawn round it; a frame, a rule or a piece of decoration carries on
    past it. On page 003 the three biggest pieces this finds are the plate's
    corner scrollwork and every one of them touches an edge, while no letter
    comes near one. lee: *"clen the text only nan not the side design"*.

    Only pieces that are also LARGE, and only where touching an edge means
    anything: on a box drawn snugly round its words the words touch the edges
    too, and the rule then throws the writing away - page 012 went from 8% of
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


def _turned(region) -> bool:
    """Is this a box the person drew and TURNED?

    Only a box somebody drew can be turned at all - and `turn`, not `angle`:
    a sound effect drawn by hand is given an angle the moment it is drawn, the
    axis its artwork runs along, and reading that as a turn would have leant
    the clean of every one of them.
    """
    if not getattr(region, "manual", False):
        return False
    return abs(float(getattr(region, "turn", 0.0) or 0.0)) > 0.01


def _own_area(region, shape, pad: int) -> "np.ndarray | None":
    """A turned box's own outline, grown by `pad` - or None if it is upright.

    Everywhere the cleaner asks "is this inside the region" it asks it of
    `bbox`, and `bbox` stays the UPRIGHT rectangle a turned box is derived
    from: that is what the turn is computed off and what straightening it
    returns to. So a turned box's corners sweep outside every rectangle the
    cleaner knows about, and the writing standing in them is clipped away
    before anything can erase it - twice over, once out of the erase mask and
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
# WIDER than the window is invisible to it - the median sees the stroke as
# background and nothing differs from it. Big display writing and thick
# sound effects are exactly that. So the second step tries several windows and
# keeps whichever leaves least, rather than one width chosen in advance.
# lee: *"can you make a tunning ... and have teh clenner run thru all of them"*.
SECOND_REACH = (FOCUS_REACH, 81, 121)
# ...but never a reading that calls essentially the whole box writing. At 121
# the median is close to the box's own average, so on page 004's violet effect
# the reading comes back claiming 93% of the box, which would take the artwork
# with it. Measured across lee's chapter the honest readings run to 76% - a
# sound effect really can be most of its own box - and only that one is above
# 85%. So the line is drawn where the readings actually separate, not where it
# felt safe: a first guess of 40% threw away the true readings on four boxes.
SECOND_MOST = 0.85
# ...and much less than that when there is no model to rebuild what is painted
# over. The local fill is a blur however it is done - copying texture in
# (`shift_fill`) measured 3.8 against the artwork's own 43 - so it is only
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

    A patch with a hard edge reads as damage - a rectangle of blur with a rim
    round it. lee: *"some if teh sfx clenning has aome notisable edges"*. So it
    is opaque over the writing and fades out across the few pixels around it,
    the same thing the flat path does with its halo.
    """
    a = np.clip(cv2.GaussianBlur(ink.astype(np.float32), (0, 0), 1.6) * 1.6,
                0.0, 1.0)[:, :, None]
    return np.clip(sub.astype(np.float32) * (1 - a)
                   + back.astype(np.float32) * a, 0, 255).astype(sub.dtype)


def second_pass(page: Page, out: np.ndarray, neural=None) -> list:
    """Clean the hard spots - after the ordinary clean, and only what it left.

    lee: *"i want the clenner to work in 2 step one step clenas teh normal like
    in the stage i said was teh safe state and the a second clen that clena
    steh hard spots like teh gold text etc"*.

    This is the right shape for it, and better than anything tried before it.
    Every earlier attempt had to GUESS, before cleaning, which boxes the fixed
    levels would fail on - and each guess that was broad enough to catch the
    gold also took boxes away from the model, the ghost retry and the
    screentone path, all of which were doing their job. A second pass does not
    guess. It looks at what the first one actually produced, and whatever is
    still standing is by definition what the first reading missed.

    It also cannot undo the first pass: it only ever paints where the writing
    survived, so a box that came out clean is not touched at all, and step one
    is exactly the cleaner lee called the safe state.

    What it erases is read the colour way - see `focus_ink` - because the boxes
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
        # Each candidate has to look like writing on its own terms - several
        # separate marks, not one blob, which is what artwork and a misread
        # gradient both come back as - and none of them may claim most of the
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
        # INK as its area (see models.py) - right for typesetting, and exactly
        # wrong here, because the whole reason a box reaches the second step is
        # that its ink was not found. On lee's page 019 the gold effect's mask
        # is all but empty, so clipping to it left nothing to erase and the
        # effect stood through both steps untouched. An effect's box IS the
        # region; there is no balloon it could be inside of.
        # WHAT to erase is read off the cleaned page - what survived is the only
        # honest measure of what the first reading missed. What to paint back
        # comes from the ORIGINAL.
        #
        # By the time the first pass has finished with a box it failed on, it
        # has painted over part of it: page 024 is a translucent balloon that
        # `_flat_from` called flat, so a slab of one grey went down across a
        # background whose local variation is 48. Taking the fill from that is
        # copying the wreck back in. The original still has the beam, the
        # gradient and the speckle the fill needs - and the median lifts the
        # writing off it, which is the whole trick.
        # ...and now put something back where it was.
        #
        # A median is a blur, and on artwork that shows: measured over lee's
        # sound effects the area it paints comes back with a tenth of the fine
        # detail the original had there, with a visible edge where the patch
        # stops. lee: *"some if teh sfx clenning has aome notisable edges and
        # ae too blurry"*. Nothing local can do better - copying texture in
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
        # No model - and then it depends what this box is standing on.
        #
        # The local fill is a median, and a median cannot make texture. Over
        # paper, over a gradient, over a balloon that is all one thing, that
        # costs nothing and takes the writing off. Over hatching, screentone or
        # grass it flattens what it covers and leaves a smooth patch in the
        # middle of the drawing - worse than the words were, because the words
        # at least looked deliberate. lee has seen this one: *"the bubble got
        # wraped"*, on the grass of page 010.
        #
        # So the artwork around the writing is measured - what the median
        # cannot hold, which is exactly what would be lost - and where it is
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
        # announce itself: painted with a hard edge it reads as damage - a
        # rectangle of blur with a rim. lee: *"some if teh sfx clenning has
        # aome notisable edges"*. So the patch is feathered, opaque over the
        # writing and fading out across the few pixels around it, which is the
        # same thing the flat path does with its halo.
        # ...with the background read at the SAME width that won the mask.
        #
        # These are one estimate and always were - the mask is what differs
        # from the background and the fill is the background - so reading them
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
    # it instead - see where this is called.
    return did


# How much cleaning has to have happened in a box before it is worth asking the
# model to draw the whole of it again. Below this the clean touched a few
# pixels - a stray mark, a rim - and there is nothing to make coherent.
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
    across by hand - find a mark running into the patch, find one leaving it
    going the same way, curve between them - and it worked on the fixtures and
    on three boxes of the chapter, and it was never going to do more, because
    every rule that kept it from drawing ON the artwork also kept it from
    drawing most of the lines. It could not touch a gradient, a shadow, a face,
    or any line it was not certain about.

    A model draws, and it is already what this cleaner hands its hard boxes to.
    What it has never been given is the WHOLE of what the clean painted, in one
    go, on the page as it arrived. On a box that needed the second pass it has
    been given two masks over the same box at two different times, and the two
    answers meet somewhere in the middle - and where the first answer came from
    a local route, the model has never seen that part at all. That seam is the
    thing left to fix here.

    **Only boxes the second pass touched.** Those are the boxes that were
    painted twice, which is the whole reason to paint them once instead: on
    lee's chapter that is 21 of 145, so the page costs a handful of calls
    rather than one per box.

    **Judged on one thing.** A redraw that works puts detail BACK - lines,
    gradient, tone - so any measure of "how much is going on in this box" goes
    up when it succeeds, and no such measure can be used to accept it. The
    single thing that can go wrong and not be an improvement is the model
    putting the words back, which it can do because it is being handed the page
    with the words still on it. So that is what is measured, in the writing's
    own footprint, and nothing else. `_gave_up` already covers the other
    failure - an answer that erases the area instead of drawing it.
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


def inpaint_page(page: Page, neural=None, neural_all: bool = False,
                 look=None) -> np.ndarray:
    """`neural(img, mask) -> img` is an optional LaMa-style callable.

    `look(bgr) -> full-page text mask` is an optional READER, and it is asked
    one question: what writing is still on the finished plate. Everything else
    in this file decides where the ink is BEFORE cleaning and then trusts
    itself; this is the one step that checks. See `_reread`.

    Normally only TEXTURED backgrounds (screentone, art) go to the inpainter;
    flat white bubbles are filled instantly with their background colour. With
    `neural_all=True` every cleaned region that is not a FULLY WHITE bubble is
    routed through `neural` instead, for people who want the model to do all of
    it - pale grey, tone, gradients and artwork included. The white bubble is
    kept back because there is nothing there to guess: see the flat path below.

    The model is called once per REGION, on a crop with `NEURAL_CTX` pixels of
    page around it, rather than once on the whole page. A hosted inpainter
    handed a full page splits the mask into connected pieces itself and runs
    once per piece - which is once per GLYPH, each seeing a window too small to
    tell what the background was doing. A bubble at a time is both far fewer
    calls and a far better view, and it means a change to one bubble only
    re-runs that bubble.
    """
    out = page.image.copy()
    gray = _gray(page.image)
    hard_mask = np.zeros(page.image.shape[:2], np.uint8)
    # Every region that was actually erased, so the finished plate can be
    # checked for leftovers. Cleaning is a chain of guesses - where the ink is,
    # how wide the strokes are, which fill to use - and the one thing that is
    # not a guess is looking at the result.
    done: list[dict] = []
    # With no model to hand it to, screentone is copied rather than inpainted:
    # Telea smears a regular dot pattern into grey mush, so those regions are
    # healed one at a time by shift_fill, which slides in REAL dots from nearby.
    # That is a stand-in for a model, not a preference - a hosted inpainter,
    # when there is one, is given the tone as well. Copying a block of dots
    # only holds while the pattern is uniform, and it is a gradient exactly
    # where it matters most, which is where the copied block shows as a patch.
    tone_masks: list[np.ndarray] = []
    # One entry per region the model will be asked about: the crop to send and
    # the mask within it. See the docstring - a bubble at a time, not a page.
    hard_jobs: list[dict] = []
    # ...and, where there is a reader, WHAT THE WRITING IS. See `_reader_ink`:
    # a saved region carries no bitmap, so the mask it is rebuilt with is "the
    # dark pixels inside the box", and on a sound effect over screentone that
    # is the screentone.
    writing = _looked(look, page.image, gray.shape)
    # ...and where it said so, inside the boxes. The fence at the end keeps a
    # fill inside the balloon, and a balloon that stops short of the words is
    # how lee's page 003 kept two kana; what the reader calls writing is the
    # one claim that outranks a guessed outline. Gathered here so the fence can
    # excuse it whether the first pass erased it or `_reread` found it after.
    reader_room = np.zeros(gray.shape, bool)

    for r in page.regions:
        # Stop means stop -- one check per region. See `stopping`: cleaning is
        # the slowest thing here, so this is the loop the button was failing.
        _stopping.check()
        # sound effects USED to be skipped wholesale; they are cleaned now too
        # (their typesetting sits on the art like any other text). A specific
        # SFX can still be spared with its per-region "keep original" toggle.
        if r.text_mask is None or getattr(r, "skip_clean", False):
            continue
        full_area = r.place_mask()
        # WHAT IS THE WRITING IN THIS BOX. Two answers, and between them they
        # cover every box on a page:
        #
        #   * the box has ONE GROUND - paper, a black panel, a grey plate - and
        #     then the writing is exactly what differs from it, measured, with
        #     nothing to guess. `_off_the_ground`.
        #   * the ground is artwork or screentone, which nothing can model, and
        #     then only a thing trained on text can say. `_reader_ink`.
        #
        # Where the ground answers, the reader is still added to it: it sees the
        # white outline round a mark that no level test can, and it is capped so
        # it can only ever add a little.
        #
        # Where neither answers, the old chain below stands - the dark pixels in
        # the box, the light/dark split, `_letterlike` - which is what this pair
        # replaced and what is left when both of them decline.
        told = _reader_ink(writing, r, gray.shape)
        ground = _off_the_ground(gray, r.bbox)
        base = r.text_mask
        # ...and a ground reading has to have SOMETHING in common with whatever
        # else this box has been said to be - the reader where there is one, the
        # mask the region carries where there is not. See `_agrees`.
        if ground is not None and not _agrees(
                ground, told if told is not None else _in_box(base, r.bbox)):
            ground = None
        if ground is not None:
            base = ground if told is None else (ground | told)
        elif told is not None:
            base = told
        inverted = False
        if full_area is not None:
            w = _window(gray.shape, full_area, base)
            polar, _, inverted = ink_and_background(
                gray[w], full_area[w] > 0, base[w] > 0)
            # Light text on a dark panel: the detector's mask is the panel
            # itself, so replace it. On an ordinary page leave the mask alone
            # - folding in the Otsu split there erases screentone dots along
            # with the words.
            #
            # The split has no idea what a letter is, though: on a black panel
            # carrying white tone it hands back the dots too, and three pixels
            # of dilation turns a field of dots into a filled box. Keep only
            # what is thick enough to have been drawn with a brush.
            #
            # NOT for a sound effect. `place_mask()` hands an sfx its own INK
            # as its area (models.py) - right for typesetting, ruinous here: the
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
            # still stands - the halo, the stroke completion and the ghost
            # check all need to know which way the ink goes - but what to
            # erase is what was found.
            #
            # ...and only when neither of the two above answered. Both of them
            # already know which way round the tones run - the median does not
            # care, and the reader reads white on black as readily as black on
            # white - so this is the last resort it always was, not a third
            # opinion overruling them.
            if inverted and _kinds.family_of(r.kind) != "sfx" \
                    and ground is None and told is None:
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
        # These two read the whole page on purpose: whether a stroke carries on
        # past the region is exactly the question a crop cannot answer.
        base_u8 = _u8(base)
        # lee: *"the cleneer shoud only clean the box that has the text"*.
        #
        # `place_mask()` is the BALLOON - the room the English may use - and it
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
        # to erase, and none of them is a reason to erase none of it - but with
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
        # on the page - lee: *"the tetxt is a non negotiable they need to go"*.
        # So each stroke the box caught is completed: its whole connected
        # component is erased, as long as MOST of that component is inside the
        # box (a stroke that is really artwork running through fails that and is
        # left alone), and never further than GLYPH_REACH past the box.
        # Not on a focus box: what this adds is ink the FIXED levels find in
        # the doorstep, and on a box that needed the switch those levels are a
        # reading of the background - on page 030 they would adopt the night
        # sky. A focus mask is not clipped at a threshold in the first place, so
        # it has no half-glyphs to finish.
        #
        # ...and on a box somebody TURNED, a ring round THAT box. `box_lim`
        # above already hands the corners a turn sweeps out to the region, but
        # only by `DILATE_PX`; the doorstep is eight, and a stroke leaving the
        # quad's corner falls outside any ring built round the upright
        # rectangle. It was left standing, 125px of 136 on the fixture for it.
        # ...and the doorstep stops at the balloon, where there is one: what is
        # just outside a bubble's box and joined to its writing is the bubble's
        # own outline as often as it is a glyph. See `_complete_strokes`.
        bm = getattr(r, "bubble_mask", None)
        if bm is not None and getattr(bm, "shape", None)[:2] != gray.shape[:2]:
            bm = None
        erase = _complete_strokes(erase, gray, inverted, r.bbox, bm,
                                  _own_area(r, gray.shape, 0))
        spare = _spared(base_u8, erase, gray, inverted)
        if told is not None:
            reader_room |= told & (box_lim > 0)

        # ...and the box goes into the window as well, not only the balloon and
        # the mask. Every measurement below is bounded by `area` or by the mask
        # itself, so a wider window is the same answer computed on a bigger
        # crop - but `_reread` looks for writing anywhere in the BOX, and a
        # balloon that stops short of the words draws a window that stops short
        # of them too. That is lee's page 003 exactly, and the check would have
        # been blind to it in the one case it exists for.
        w = _window(gray.shape, full_area, erase, box_lim)
        g, area = gray[w], (None if full_area is None else full_area[w])
        ink, spare_c = erase[w], spare[w]
        flat, bg, spread = ((False, np.zeros(3), 255.0) if area is None else
                            _flat_from(page.image[w], area, ink, spare_c))
        d = _dilated(ink)
        # ...and WHERE THIS REGION MAY LOOK for writing it missed: THE BOX THE
        # PERSON DREW, and nothing else. Not the window - that is a rectangle
        # round the balloon and takes in whatever else is standing in it - and
        # not the mask, which is the thing being checked.
        #
        # And deliberately not the balloon either, which is the whole reason
        # lee's page 003 still says しゅぁ and もる. Both of those are inside
        # his box, on the balloon's own white, and OUTSIDE the interior the
        # balloon finder drew - it stops a dozen rows short of the writing.
        # Every step here is clipped to that interior, so the words were never
        # in a mask, and the fence at the end would have put them back if they
        # had been. The box is the person's statement that the words are in
        # here; the balloon is a guess about where a shape ends. See `_reread`,
        # which is why it is safe to prefer the first over the second HERE and
        # nowhere else: a trained reader has to call these pixels writing
        # before anything looks at them.
        own_c = box_lim[w] > 0
        rec = {"r": r, "win": w, "ink": ink, "inv": inverted,
               "how": "", "flat": None, "job": None,
               "own": own_c, "left": None}
        done.append(rec)
        # lee: *"the ai shoud be clening those not the cleaner the cleneer only
        # need to cleaner the white bubbles"*. A flat background is the local
        # fill's whole justification - the colour is KNOWN, so the fill is exact
        # and instant, and no model can beat it. But "flat" says nothing about
        # what the area is: the inside of a black panel is flat too, and a solid
        # dark field carrying white typesetting is precisely the hard case he wants
        # the model on. So with a model configured, the local path keeps the
        # thing it is unbeatable at - the pale flat bubble - and everything else
        # goes to the model.
        # With a model configured the local path keeps the one thing it is
        # unbeatable at and nothing else: a FULLY WHITE balloon, where the
        # colour is known exactly, so the fill is exact and instant. Pale grey,
        # light screentone and anything with grain in it go to the model.
        # lee: *"the local celener is only used fro fully white bubbles every
        # thing else should be handles by the ai clenner"*.
        # With no model there is nothing to hand them to, so the old, looser
        # test stands - a flat fill still beats Telea on a pale flat area.
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
        # clenner"* - a cloak is not a bubble.
        #
        # By FAMILY, and not by `on_art`. That function also answers yes when
        # no balloon was FOUND - and a balloon the finder missed is still a
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
        # ...and a FULLY WHITE bubble takes it even with "the model does the
        # whole page" chosen. lee, having run the chapter that way and looked:
        # *"look into making the local clenner do teh white biexes because it
        # did a bettr jib"*, with a picture of a plain bubble the model had
        # left one speck of a kana in.
        #
        # It is not a preference between two cleaners. On a white balloon the
        # background is KNOWN - one colour, measured off the paper around the
        # words - so the fill is exactly right by construction and instant and
        # free. A model, however good, is guessing at a thing that is not in
        # doubt, and a guess can leave a speck. "The whole page" means every
        # area the local path cannot prove it has right, and that is what it
        # now does: pale grey, tone, gradients, artwork, all of it still goes.
        slab = None
        if mine:
            level = _bg_level(g, area, ink, bg, spare_c)
            wide = _with_halo(g, area, d, spare_c, level, inverted)
            tried = page.image[w].copy()
            tried[wide > 0] = bg.astype(tried.dtype)
            if _slab_worked(page.image[w], tried, ink):
                slab = (wide, level)
            else:
                mine = False
        if slab is not None:
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
                tone_masks.append((r.id, full_d))
                rec["how"] = "pattern copy"
                r.flagged = (r.flagged or "") + \
                    " screentone: cleaned by pattern copy, worth a look"
            else:
                # Hand it to the model (or Telea) to redraw from the pixels
                # around it. Give it a wider mask than the flat path gets: the
                # model redraws whatever it is handed and nothing else, so a
                # stroke edge left outside the mask is a stroke edge left on
                # the page - and unlike a flat fill, being generous costs
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
                # artwork is allowed to be dark on its own account - and only
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
                # gone for good. Text left standing is recoverable - the
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
                    # cleaned or just skipped - fix that so this never happen, it
                    # shoud not skip boxes"*.
                    #
                    # The danger was never the letters; it is the HALO and the
                    # model's padding, which on a dark panel can walk out of the
                    # writing and across the artwork. So drop back to the
                    # letter-like core - no halo, no padding - and clean that.
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
    # neighbours rather than a half-inpainted page. That is also what makes the
    # next line necessary: the plate being sourced from still has every OTHER
    # region's Japanese on it, and the copy will take it if it fits. See
    # `shift_fill`, and lee's page 001 with a speech balloon printed across a
    # character's kimono.
    if tone_masks:
        # The BOXES, not the ink in them. A box is where somebody - the
        # detector or a person - said there is writing, and it is the only
        # answer here that does not depend on how good the mask is: without a
        # reader a box's "ink" on screentone IS the screentone, and blocking
        # that as a source would take the tone away from the one route that
        # exists to copy tone. A box is a small part of the paper and the rest
        # of it is still there to source from.
        each = {}
        for r in page.regions:
            if r.text_mask is None:
                continue
            own = _own_area(r, gray.shape, DILATE_PX)
            b = np.zeros(gray.shape, np.uint8)
            if own is None:
                bx, by, bw, bh = (int(v) for v in r.bbox)
                b[max(0, by - DILATE_PX):by + bh + DILATE_PX,
                  max(0, bx - DILATE_PX):bx + bw + DILATE_PX] = 1
            else:
                b[own] = 1
            each[r.id] = b
        for rid, tm in tone_masks:
            # every box but this one's: a hole is allowed to source from the
            # rest of its own box, which is the paper right beside it
            avoid = np.zeros(gray.shape, np.uint8)
            for k, b in each.items():
                if k != rid:
                    avoid |= b
            out = shift_fill(out, tm, avoid=avoid)

    if neural is not None:
        for job in hard_jobs:
            _run_neural(out, job, neural)
    elif hard_mask.any():
        out = cv2.inpaint(out, hard_mask, 3, cv2.INPAINT_TELEA)

    # ...and only now, with the page as clean as the first pass can make it, is
    # it worth reading. Before the sweep, so that what the reader finds is
    # repaired by the same three paths that repair a ghost, and reported by the
    # same flag if it survives them.
    reread = _reread(page.image, out, done, look) if look is not None else 0
    _sweep_ghosts(gray, out, done, neural, page.image)

    # ---- the fence ----------------------------------------------------------
    # lee: *"the clenners shoud only clean withing the box, it hsoud never touch
    # a pixel outside teh box area, both the local and the ai - the box that
    # shoud be considered is teh box that i see"*.
    #
    # Half a dozen steps above can each reach past the box they were given: the
    # halo sweep grows the mask until the background stops looking like ink, the
    # model's padding adds a couple of pixels, the ghost sweep re-fills a flat
    # bubble to its own edges, a screentone copy works page-wide. Every one of
    # them has a reason, and none of them is a reason to change a pixel of a page
    # nobody drew a box around - which is how a whole bubble came back wiped with
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
        # box" cannot both be true. GLYPH_REACH is that margin - eight pixels,
        # about half a stroke - and only ink CONNECTED to what the box caught
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
        # region's to repaint - the outline included, which is why the sky came
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
    # ...with ONE exception, and it is the balloon clause it excuses, never the
    # box. lee's page 003 is what it is for: two bubbles whose found interior
    # stops a dozen rows short of the last line of kana, so the words sit inside
    # his box, on the balloon's own white, and outside the shape. Clipped to
    # that shape the cleaner cannot reach them - and it is not a threshold that
    # can be loosened, because "a bit outside the balloon" is also where the
    # artwork is.
    #
    # What makes this safe is what was asked, not how far it reaches: a text
    # segmenter looked at the page and called these pixels writing. That is the
    # one claim that outranks a guessed outline, and it is still inside the box
    # the person drew - which is the rule he actually stated.
    #
    # Both readings count, and they have to: the one taken before anything was
    # erased (`_reader_ink`, gathered into `reader_room`) and the one taken of
    # the finished plate (`_reread`). Only the second was excused at first, and
    # it left the fence undoing in silence exactly what the first pass had got
    # right - erased before the sweep looks, so never seen as residue, and
    # painted back at the end.
    if reader_room.any():
        allowed |= _dilated(reader_room, DILATE_PX) > 0
    for rec in done:
        left = rec.get("left")
        if left is not None and np.any(left):
            allowed[rec["win"]] |= _dilated(_u8(left), DILATE_PX) > 0
    out[~allowed] = page.image[~allowed]

    # ...and then the second step, over whatever the first one left standing.
    # After the fence, so it inherits every rule about where a region may
    # paint; it reads the page the first pass produced and touches nothing the
    # first pass already cleaned. See `second_pass`.
    again = second_pass(page, out, neural)

    # ...and last of all, the artwork - but only where there is a model to
    # redraw it with. See `redraw`.
    drawn = redraw(page, out, neural, again)

    # Who cleaned what. Every argument about this page's cleaning so far has
    # been conducted by looking at it and guessing; this is the count.
    # "fell back" is a region the model was asked for and did not deliver.
    stats: dict = {}
    if reread:
        # Boxes the reader found writing in that no mask had covered. Counted
        # because it is the one number that says whether the extra pass is
        # earning its two seconds a page.
        stats["missed text found"] = reread
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
    # ...and which boxes had writing the mask never covered, so the person
    # looking at the report can go and see whether the second go got it.
    for rec in done:
        if np.any(rec.get("left")):
            rec["r"].clean_route = \
                ((rec["r"].clean_route or "") + " + reread").strip()
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
    reconstruction - two stacked generations, each adding its own noise floor,
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
# one colour instead - which is not a cleaned page, it is an erased one. lee,
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

# ...and the second way the same failure arrives, which the pair above cannot
# see. lee, with a crop of page 1: a solid BLACK bar where the Japanese `SHHH`
# had been - *"i dont know if the ckenner or the amount of step required to
# properly clenn it is too low but this is happening"*.
#
# That box sits on the pale, smooth, sparkly gradient at the top of the page.
# The ring around it has nothing like 12 levels of detail in it, so the test
# above never fires, and a slab is flat ON FLAT and accepted. "A flat answer on
# flat paper is right" is true only when it is the SAME flat.
#
# So: whatever the ring's detail, an answer that is flat AND nothing like the
# level of what surrounds it is a refusal too. The number is measured rather
# than picked - over the 221 boxes the cleaner paints on lee's chapter, the gap
# between a fill's own mean and the mean of the ring just outside it
# (`his/level.py`):
#
#     every fill        mean 5.3   median 0.7   p90 15.7   max 105.2
#     the FLAT ones     mean 1.6   median 0.6   p90  1.5   max  31.6
#
# and the flat ones are the only ones this clause ever looks at. A fill that is
# right sits within a level or two of the paper it is patching; the worst
# legitimate case in the whole chapter is 32. A black bar on pale paper is 150
# to 200 away. Sixty is about twice the worst real answer and about a third of
# the failure, which is as much daylight as either side needs.
GAVE_UP_LEVEL = 60.0


def _gave_up(sub: np.ndarray, filled: np.ndarray, mask: np.ndarray) -> bool:
    """Did the model erase this area rather than redraw it?

    Measured on a ring `HALO_REACH` wide just outside the mask, so "the
    surroundings" means the artwork the fill has to match rather than the whole
    window. A flat answer on flat paper is right and passes; a flat answer
    against hatching, tone or line work is a refusal wearing the shape of a
    result, and goes to the local fill instead - which at least copies from the
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
    flat = float(g_in.std()) < GAVE_UP_FLAT
    # Flat where the surroundings are not...
    if flat and float(g_ring.std()) >= GAVE_UP_DETAIL:
        return True
    # ...or flat and nothing like the level of them, which is the same refusal
    # on paper too smooth for the first test to see. See `GAVE_UP_LEVEL`.
    return bool(flat and abs(float(g_in.mean()) - float(g_ring.mean()))
                >= GAVE_UP_LEVEL)


def _local_fill(out: np.ndarray, job: dict) -> None:
    """Repair one region without the model, at the size a local method should
    be given.

    Reached when the hosted cleaner refuses or cannot be reached. It used to be
    reached with the model's own mask - dilated by `NEURAL_PAD` because a model
    reconstructs whatever it is shown - and a plain fill over that much of a
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


def _looked(look, img: np.ndarray, shape) -> "np.ndarray | None":
    """Ask the reader about a page, and take no for an answer.

    A reader that throws, that is not configured, or that hands back something
    the wrong shape is a reason to skip a check - never a reason to fail the
    page somebody is cleaning.
    """
    if look is None:
        return None
    try:
        m = look(img)
    except Exception:
        traceback.print_exc()
        return None
    if m is None:
        return None
    m = np.asarray(m)
    if m.ndim != 2 or m.shape != tuple(shape[:2]):
        return None
    return m > 0


def _strokes_not_shapes(mask: np.ndarray) -> np.ndarray:
    """Drop what is too WIDE to have been written.

    Level alone cannot tell a word from a drawing - both are off the ground -
    and a balloon with a picture in it is a box where that matters: the drawing
    is one solid area, and erasing it is artwork gone for good. Writing is made
    of strokes, so nothing in it survives an erosion by `GROUND_SOLID`; a filled
    shape keeps most of itself. This is the same argument `second_pass` makes
    with "several separate marks, not one blob", made where it does not need
    the marks to be several - a single `\u3057` is still a stroke.
    """
    m = _u8(mask)
    if not m.any():
        return mask > 0
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (2 * GROUND_SOLID + 1,) * 2)
    core = cv2.erode(m, k)
    if not core.any():
        return mask > 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    out = np.zeros(mask.shape, bool)
    for i in range(1, n):
        sel = lab == i
        if int((sel & (core > 0)).sum()) >= 0.2 * int(st[i, cv2.CC_STAT_AREA]):
            continue                       # a shape, not a stroke
        out |= sel
    return out


def _in_box(mask: "np.ndarray | None", bbox) -> "np.ndarray | None":
    """A page-sized mask clipped to one box - what a region says about itself,
    rather than everything its threshold caught on the page."""
    if mask is None:
        return None
    x, y, w, h = (int(v) for v in bbox)
    m = np.asarray(mask)
    out = np.zeros(m.shape[:2], bool)
    out[max(0, y):y + h, max(0, x):x + w] = True
    return (m > 0) & out


def _agrees(a: "np.ndarray | None", b: "np.ndarray | None") -> bool:
    """Do two readings of the same box have anything in common?

    A ground reading and a mask reading can both be plausible and be about
    different things: on dark artwork with bright hatching over it, the box's
    median is the artwork and what stands off it is the HATCH, while the mark
    somebody boxed is a shade darker still and never leaves the tolerance. The
    two answers then share nothing at all, and that is the signature - not the
    size of either one, which looks reasonable in both.

    So a ground reading may CORRECT the mask a region carries; it may not
    replace it with something the region has never heard of. Where the region
    has no other opinion worth the name, there is nothing to disagree with and
    the ground stands alone.
    """
    if a is None or b is None:
        return True
    na, nb = int(np.count_nonzero(a)), int(np.count_nonzero(b))
    if min(na, nb) < GLYPH_MIN_AREA:
        return True
    return int(np.count_nonzero(a & b)) >= GROUND_AGREE * min(na, nb)


def _off_the_ground(gray: np.ndarray, bbox) -> "np.ndarray | None":
    """The writing in this box, where the box has ONE GROUND to write on.

    Every box on a page is writing on a ground, and there are only two kinds of
    ground. One can be modelled - paper, a black panel, a grey plate, anything
    that is one level - and there the writing is EXACTLY what differs from that
    level, with nothing to guess and no detector needed. The other cannot:
    artwork, and screentone, where the ground is a pattern at the same scale as
    a stroke. lee: *"i dont wan you to hard code it for this exmaple i wnat you
    to caome up with a system taht clenneas them all teh time on any manga"*.

    This is the first case, and it is most boxes. The level is the median of the
    box - a box is drawn round writing with room to spare, so most of it IS the
    ground - and the writing is what sits more than `GROUND_TOL` off it. That
    one sentence covers black on white, WHITE ON BLACK, grey on grey and gold on
    cream alike, which is five rescues in this file replaced by a measurement:

      * the light/dark split and the rim vote that decides which way round it
        goes - the median does not care which way round the tones run;
      * `_letterlike`, which dropped a column of ruby off lee's page 009
        because a 6-pixel kana is the size of a screentone dot;
      * the empty-mask fallback, and the `SAW_ENOUGH` idea that was left
        undone because no ratio could tell tone from writing.

    Five things keep it honest, and every one of them is a way it was caught
    being wrong on a real page or a fixture built from one:

      * IT REFUSES A GROUND THAT WANDERS (`GROUND_MAD`). Screentone, artwork
        and gradients are not one level, and it says so rather than guessing.
        The reader is what answers there.
      * ...and refuses a box with more ink in it than ground (`GROUND_CLEAR`).
      * THE GROUND HAS TO CONTINUE OUTSIDE THE BOX (`GROUND_AROUND`). A box is
        drawn ON something, so the thing it sits on is there just outside it
        too. Without this, a box drawn tight on a bold mark reads the MARK as
        its ground and hands back the paper, which is the box erased.
      * WRITING LEAVES GAPS (`GROUND_GAPS`). Split the box into a hundred cells
        and some of them - margins, the space between two lines - have nothing
        in them. A field of tone has nothing empty anywhere. Measured: every
        one of the 189 boxes on lee's chapter that gets this far leaves at
        least 7 cells of 100 empty, and a light line screen and a light dot
        screen leave none at all. This is what tells a column of ruby from a
        field of tone, which are the same thing close up.
      * and runs, not marks, so paper grain and a stray dot are not writing,
        with no run bigger than `MASK_MAX_SHARE` of the box.
    """
    x, y, w, h = (int(v) for v in bbox)
    H, W = gray.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w < 8 or h < 8:
        return None
    sub = gray[y:y + h, x:x + w].astype(np.int16)
    lvl = float(np.median(sub))
    # How far the ground itself wanders, measured so that the writing cannot
    # move it: half the box is within the MAD of the median, and writing is
    # never half the box. Past `GROUND_MAD` this is not one ground.
    mad = float(np.median(np.abs(sub - lvl)))
    if mad > GROUND_MAD:
        return None
    # ...and the tolerance is the ground's own wander, never less than
    # `GROUND_TOL`. lee's brushed-black balloon is grainy over ±36 levels and
    # the white writing on it is 240 clear of the median; a fixed tolerance
    # either calls that grain writing or calls a pale grey stroke ground.
    tol = max(float(GROUND_TOL), 3.0 * mad)
    off = np.abs(sub - lvl) > tol
    if float((~off).mean()) < GROUND_CLEAR:
        return None                       # more ink than ground: not a reading
    # ...and the ground has to be there outside the box as well.
    pad = GLYPH_REACH
    X0, Y0 = max(0, x - pad), max(0, y - pad)
    X1, Y1 = min(W, x + w + pad), min(H, y + h + pad)
    near = gray[Y0:Y1, X0:X1].astype(np.int16)
    out = np.ones(near.shape, bool)
    out[y - Y0:y - Y0 + h, x - X0:x - X0 + w] = False
    if int(out.sum()) >= 200 and \
            float((np.abs(near[out] - lvl) <= tol).mean()) < GROUND_AROUND:
        return None
    # ...and writing leaves gaps. A hundred cells, and a ground fills them all.
    n = 10
    ys = np.linspace(0, h, n + 1).astype(int)
    xs = np.linspace(0, w, n + 1).astype(int)
    cells = empty = 0
    for a in range(n):
        for b in range(n):
            cell = off[ys[a]:ys[a + 1], xs[b]:xs[b + 1]]
            if cell.size < 9:
                continue
            cells += 1
            empty += float(cell.mean()) < 0.05
    if cells and empty < GROUND_GAPS * cells:
        return None
    keep = _whole_glyphs(off, most=int(MASK_MAX_SHARE * w * h))
    if not keep.any():
        return None
    keep = _strokes_not_shapes(keep)
    if not keep.any():
        return None
    keep = _contained(keep, gray, lvl, tol, (x, y, w, h))
    if not keep.any():
        return None
    out = np.zeros(gray.shape, bool)
    out[y:y + h, x:x + w] = keep
    return out


def _contained(keep: np.ndarray, gray: np.ndarray, lvl: float, tol: float,
               box) -> np.ndarray:
    """Drop what only LOOKS like writing because the box cut it off.

    Off-the-ground is measured inside the box, and inside a box a hatched
    background, a bubble's outline and the edge of somebody's head are all
    marks standing off the paper exactly like a stroke. What they are not is
    CONTAINED: they carry on outside the box, and typesetting does not - the
    box was drawn round it.

    lee, sent a page cleaned with the ground rule and no containment: *"the ai
    shoud try to keep teh boes instd of removing it ... this guy head is gone
    even though uts not on teh text"*. Measured on his chapter, 7% of every
    ground answer was ink with nothing the reader would call writing anywhere
    near it, and it was the vertical rain behind a caption, the outline of a
    bubble, and a man's head.

    Same rule and same number as `glyphs_only`, which has always said this
    about the detector's own mask - it just could not be asked about a mark no
    fixed threshold can see. Asked against the ground, it can.
    """
    x, y, w, h = box
    H, W = gray.shape[:2]
    pad = max(2 * GLYPH_REACH, w // 4, h // 4)
    X0, Y0 = max(0, x - pad), max(0, y - pad)
    X1, Y1 = min(W, x + w + pad), min(H, y + h + pad)
    near = gray[Y0:Y1, X0:X1].astype(np.int16)
    off = (np.abs(near - lvl) > tol).astype(np.uint8)
    n, lab = cv2.connectedComponents(off, 8)
    if n <= 1:
        return keep
    box_of = np.zeros(off.shape, bool)
    box_of[y - Y0:y - Y0 + h, x - X0:x - X0 + w] = True
    inside = np.zeros(off.shape, bool)
    inside[y - Y0:y - Y0 + h, x - X0:x - X0 + w] = keep
    edge = np.zeros(off.shape, bool)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    out = np.zeros(keep.shape, bool)
    for li in set(np.unique(lab[inside])) - {0}:
        comp = lab == li
        total = int(comp.sum())
        if total and int((comp & ~box_of).sum()) > OUTSIDE_SHARE * total:
            continue                      # it carries on outside: artwork
        if (comp & edge).any():
            continue                      # ...and this one has no end in sight
        out |= (comp & inside)[y - Y0:y - Y0 + h, x - X0:x - X0 + w]
    return out


def _reader_ink(writing: "np.ndarray | None", r,
                shape) -> "np.ndarray | None":
    """What the READER says the writing in this region is.

    A saved region carries no bitmap - a 40-page chapter would sit on close to
    a gigabyte of them - so the mask it is rebuilt with is the only thing
    geometry can give: THE DARK PIXELS INSIDE THE BOX. On a white bubble that
    is the words and nothing else, which is why it stood for so long.

    On lee's page 013 it is the screentone. A sound effect drawn in white
    outline over a horizontal line screen has 11,352 dark pixels in its box and
    the letters are not among them - the mask is every tone line, the whole
    rectangle goes to the model, and what comes back is a rebuilt patch of tone
    with the shape of the box in it. lee, with the crop: *"see how i can see
    the lines of teh clenner that shoud not happen it should clenly fit with
    teh art"*. On his page 001 the same rule marks the trousers and the dark
    foliage under a line of white credits.

    Every rescue in `inpaint_page` - the light-on-dark split, `_letterlike`,
    `glyphs_only`, the empty-mask fallback - is a repair for that one rule, and
    not one of them can repair the case where the dark pixels in the box ARE
    the artwork. Nothing can, from a level. So where a reader is configured it
    is asked first, and what it says the writing is, is what gets erased: 5,066
    pixels of glyph on that sound effect instead of 11,352 pixels of shirt.

    Returns None when there is no reader, or when it finds nothing here worth
    calling writing - and then the old mask stands, because a detector that
    cannot see a mark is not evidence that the mark is not there. That is the
    sfx case in particular: a big stylised one is not what it was trained on.

    ...and None again when it calls MOST OF THE BOX writing. A box is drawn
    round the words with room to spare, so the glyphs in it are a fifth of it
    and a fifth is what the reader answers on every region of lee's chapter -
    the worst is 19%. An answer over `MASK_MAX_SHARE` is not a tighter reading
    of the writing, it is the reader having lost the plate, and acting on it
    here would erase the box rather than the words. That is the same cap
    `_reread` applies to the same reader for the same reason.
    """
    if writing is None:
        return None
    x, y, w, h = (int(v) for v in r.bbox)
    box = np.zeros(shape[:2], bool)
    # The doorstep as well as the box, the same margin `_complete_strokes` and
    # the fence use: a glyph drawn a little past its box is still this box's.
    box[max(0, y - GLYPH_REACH):y + h + GLYPH_REACH,
        max(0, x - GLYPH_REACH):x + w + GLYPH_REACH] = True
    m = writing & box
    n = int(m.sum())
    if n < GLYPH_MIN_AREA or n > MASK_MAX_SHARE * int(box.sum()):
        return None
    return m


def _whole_glyphs(mask: np.ndarray, most: int = 0) -> np.ndarray:
    """Keep what is big enough to have been WRITING, in runs rather than one
    mark at a time.

    `most` caps a run from above as well: a run bigger than that is not a word,
    it is the ground. That is what tells a column of ruby from a field of
    screentone - both are specks a stroke apart, and only one of them covers
    the box.

    The reader answers per pixel, and a per-pixel answer has fringe on it: a
    dot of screentone it was unsure about, two pixels of a balloon rim, the
    edge of a stroke that was already erased. None of those is a character
    somebody has to read, and all of them are pixels this would otherwise go
    and repaint.

    The size test is taken over the RUN and not over each piece, and lee's page
    003 is the argument. The three kana left standing in that bubble measure
    230, 53 and 36 pixels: per piece, a threshold that keeps the 36 keeps a
    speck of tone as well, and one that drops it erases one character out of
    three and leaves the other two on the page. Together they are 319 pixels
    within half a stroke's reach of each other, which no speck of anything is.
    Writing comes in runs; that is what makes it writing.

    Only the pixels themselves are kept - the gaps a run is grouped across are
    never painted.
    """
    m = _u8(mask)
    if not m.any():
        return mask > 0
    n, grp = cv2.connectedComponents(_dilated(m, GLYPH_REACH), 8)
    keep = np.zeros(mask.shape, bool)
    ink = m > 0
    for i in range(1, n):
        sel = (grp == i) & ink
        if int(sel.sum()) < GLYPH_MIN_AREA:
            continue
        if most and int(sel.sum()) > most:
            continue
        ys, xs = np.nonzero(sel)
        if xs.max() - xs.min() + 1 < GLYPH_MIN_SIDE or \
                ys.max() - ys.min() + 1 < GLYPH_MIN_SIDE:
            continue
        keep |= sel
    return keep


def _reread(before: np.ndarray, out: np.ndarray, done: list[dict], look) -> int:
    """Read the finished plate and find writing that was never in a mask.

    lee, with two crops of a white balloon that still plainly says しゅぁ and
    もる: *"can you fix the issue of the text not fully getting clenned off
    boxes"*, and before that *"i also want to create a systhem that looks for
    thet text ain the boxes and tells teh clenner where they are and the
    clenner will only clenn that are isnstad of the whoile box"*. This is that
    system, and the answer to *"can read text return the are athat need to be
    clenned?"* is yes - the segmentation head, run again on the result.

    `look(bgr) -> full-page mask` is the reader, injected by the caller so this
    file never learns where a weights file lives. With none, this never runs and
    the page is cleaned exactly as it was.

    Three things make the answer usable, and each of them was a way of getting
    it wrong:

      * only INSIDE A BOX THIS PAGE CLEANED (`rec["own"]`). Run on lee's page
        001 the reader still marks 44% of what it marked on the original, and
        nearly all of that is a painted chapter title and two drawn sound
        effects that nobody ever drew a box round. They are not residue; they
        are text this page was never asked to erase.
      * only where THE CLEANER NEVER PAINTED. A stroke that was erased and left
        a faint rim is still read as text, and it is not this test's business -
        `ghost_delta` and `ghost_detail` have been asking about exactly that
        for a version now, and they can measure how faint it is.
      * only pieces the size of a LETTER, in runs (`_whole_glyphs`).

    ...and one thing keeps it from ever being a catastrophe: if what is left
    covers most of the region, the reader is not pointing at residue, it is
    disagreeing about the whole box. Say so and change nothing. Erasing "most
    of a box" on the strength of a second opinion is how a panel of artwork
    goes, and artwork does not come back.

    Returns how many regions had something left in them.
    """
    still = _looked(look, out, out.shape)
    if still is None or not still.any():
        return 0
    still = still.copy()

    # Everywhere this page was PAINTED, and a couple of pixels of slack round
    # it. Page-wide rather than per-region on purpose: boxes overlap, and a
    # stroke cleaned by its neighbour is cleaned.
    #
    # What was painted, rather than what the masks said - the halo sweep, the
    # model's own padding and the feathered seam all reach past a mask, and
    # every pixel any of them touched has been dealt with, well or badly. This
    # test is only ever about the pixels NOTHING touched. The mask goes in as
    # well, for the fill that happened to paint a pixel its own colour.
    page_gray = _gray(before)
    gone = page_gray != _gray(out)
    for rec in done:
        gone[rec["win"]] |= _u8(rec["ink"]) > 0
    still &= ~(_dilated(gone, RESIDUE_PAD) > 0)

    n = 0
    for rec in done:
        own = rec.get("own")
        if own is None or not own.any():
            continue
        w = rec["win"]
        left = _whole_glyphs(still[w] & own)
        if not left.any():
            continue
        # ...and then the same widening every other mask in this file gets,
        # on the terms the ghost sweep's SECOND GO uses rather than the first
        # pass's: reach further, and count anything barely off the background.
        # The reader answers with the stroke, and a stroke on a page has an
        # anti-aliased skirt no threshold set for a first pass can see; filled
        # without it, the fill reads that skirt as the colour to paint with and
        # lee's two kana came back as pale blobs instead of gone. Measured on
        # his box: the darkest pixel left in it is 211 at the first pass's
        # tolerance, 236 at the ordinary one and 248 at this one, on paper at
        # 255.
        #
        # Being this generous is safe HERE and would not be in the first pass,
        # for the reason the whole check is: `touching` keeps it to ink joined
        # to what the reader called writing, and `own` keeps it inside the box.
        g = page_gray[w]
        left = _with_halo(g, own.astype(np.uint8), _u8(left), None,
                          _local_bg(g, rec["inv"]), rec["inv"],
                          reach_px=HALO_REACH + 6, tol=max(3, HALO_TOL // 2),
                          touching=True) > 0
        if int(left.sum()) > MASK_MAX_SHARE * int(own.sum()):
            rec["r"].flagged = (rec["r"].flagged or "") + \
                " clean: the page reads as still having writing over most of " \
                "this box — check it, it was left as it is"
            continue
        rec["left"] = left
        job = rec.get("job")
        if job is not None:
            # The model is asked about the whole region again, so the pixels
            # it was never shown have to be in the mask it is shown this time.
            tight = ((job["tight"] > 0) | (_dilated(_u8(left)) > 0))
            job["tight"] = tight.astype(np.uint8) * 255
            job["mask"] = _dilated(job["tight"], MODEL_PAD)
        n += 1
    return n


def _erase_mask(rec: dict) -> np.ndarray:
    """Everything this region means to have erased: what the mask caught, and
    whatever the reader found afterwards that it never covered."""
    left = rec.get("left")
    if left is None or not np.any(left):
        return _u8(rec["ink"])
    return (((rec["ink"] > 0) | (left > 0)).astype(np.uint8)) * 255


def _ghost_left(before, after, rec) -> tuple:
    """Is there still typesetting in this box, and by which measure?

    Three independent tests and any of them is enough: how dark the old ink
    still is against its ring (`ghost_delta`), how much is still DRAWN there
    where the page around it is blank (`ghost_detail`), and - where a reader
    read the plate - the same two questions again about writing the mask never
    covered at all (`_reread`).

    That last mask is asked about SEPARATELY rather than folded into the first,
    and the arithmetic is why. Both measures are medians taken over the whole
    ink mask; two hundred pixels of missed kana beside three thousand pixels of
    properly cleaned column moves neither one. Measured on its own it is the
    loudest ghost on the page - and once it has been filled, the same
    measurement is what says so, so a repaired box stops complaining without
    anybody having to remember to clear anything.
    """
    w = rec["win"]
    for ink, what in ((rec["ink"], ""), (rec.get("left"), "missed ")):
        if ink is None or not np.any(ink):
            continue
        lvl = ghost_delta(before[w], after[w], ink, rec["inv"])
        if lvl > GHOST_TOL:
            return True, "%s%d levels" % (what, round(lvl))
        hf = ghost_detail(after[w], ink)
        if hf > GHOST_HF:
            return True, "%sstill drawn (detail %.2f)" % (what, hf)
    return False, ""


# ON A PLAIN BUBBLE THERE IS NOTHING TO PROTECT, so nothing is left standing.
#
# Every other route in this file has to be careful, because it is painting over
# artwork and a mask that reaches too far erases a drawing. A fully white
# balloon interior is the one place in a manga page where that is not true: the
# colour is KNOWN, measured off the paper around the words, and anything inside
# that is not that colour is either writing or a mark on the paper. There is no
# third thing to be careful of.
#
# It is needed because the ghost test cannot see small leftovers. `_ghost_left`
# is a median over the whole ink mask, and lee's crop is the case that defeats
# it: a balloon over a face, cleaned, with two dashes of a kana about twenty
# pixels long still in the middle of the white. Two hundred pixels beside three
# thousand properly cleaned ones moves no median, and the detector will not read
# two dashes as text either, so neither the ghost sweep nor the re-read ever
# fires. lee: *"there ate still residue on the whoite boxes use a better
# offlien clenner for it or make the clenner allways clenne out all the text"*.
# The second half of that is this: on a white box, always, all of it.
FLAT_ALL_TOL = 10      # levels off the known colour that count as a mark
FLAT_ALL_MAD = 4.0     # ...or this many times the paper's own grain
FLAT_ALL_MOST = 0.5    # a component bigger than this much of the box is art


def _all_of_it(sub: np.ndarray, area: np.ndarray, bg: np.ndarray) -> int:
    """Erase everything left on a known ground. Returns pixels painted."""
    inside = area > 0
    if int(inside.sum()) < 100:
        return 0
    g = _gray(sub).astype(np.int16)
    lvl = float(np.median(g[inside]))
    mad = float(np.median(np.abs(g[inside] - lvl)))
    tol = max(float(FLAT_ALL_TOL), FLAT_ALL_MAD * mad)
    off = inside & (np.abs(g - lvl) > tol)
    if not off.any():
        return 0
    # A BLOB IS NOT A MARK. A balloon can legitimately have something drawn in
    # it - a sweat drop, a small figure, the tail of the balloon beside it - and
    # the two tests that already know the difference are reused rather than
    # guessed at again: a run of writing is capped from above, and a shape whose
    # middle survives erosion is a drawing rather than a stroke.
    keep = _whole_glyphs(off, most=int(FLAT_ALL_MOST * inside.sum()))
    keep = _strokes_not_shapes(keep)
    if not keep.any():
        return 0
    sub[keep] = bg.astype(sub.dtype)
    return int(keep.sum())


def _sweep_ghosts(gray: np.ndarray, out: np.ndarray, done: list[dict],
                  neural=None, original: "np.ndarray | None" = None) -> None:
    """Look at the finished plate and deal with typesetting that is still there.

    A flat bubble can be refilled on the spot - the fill colour is known and
    correct, the only thing that was wrong is how far it reached - so widen and
    go again. A region the model drew gets one more go too, with a wider mask,
    because the usual reason a ghost survives a redraw is that a sliver of the
    stroke was never inside the mask, and asking again about a slightly bigger
    area is the whole fix. Results are cached by content upstream, so the retry
    costs nothing on a page that is merely being re-rendered.

    A region with no model and nothing flat about it gets the one repair a
    local method can be trusted with - Telea over the missed strokes - and only
    when a reader has actually pointed at them.

    Anything still showing after that is left alone and reported: a third
    automatic pass on a reconstruction is as likely to make it worse, so say
    what happened and which path produced it, and let the person decide.
    """
    after = _gray(out)

    redone = False
    for rec in done:
        if not rec["flat"]:
            continue
        # ...and this one is not gated on the ghost test, deliberately. See
        # `_all_of_it`: what it is for is the leftover a median cannot see.
        area, spare, bg, level = rec["flat"]
        if _all_of_it(out[rec["win"]], area, bg):
            redone = True
    if redone:
        after = _gray(out)

    for rec in done:
        if not rec["flat"]:
            continue
        w = rec["win"]
        if not _ghost_left(gray, after, rec)[0]:
            continue
        area, spare, bg, level = rec["flat"]
        wider = _with_halo(gray[w], area, _dilated(_erase_mask(rec)), spare,
                           level, rec["inv"], reach_px=HALO_REACH + 6,
                           tol=max(3, HALO_TOL // 2))
        out[w][wider > 0] = bg.astype(out.dtype)
        redone = True

    for rec in done:
        if rec["flat"]:
            continue
        w = rec["win"]
        if not _ghost_left(gray, after, rec)[0]:
            continue
        if neural is not None and rec["job"]:
            _run_neural(out, rec["job"], neural, extra=DILATE_PX + 2,
                        again=original)
            redone = True
        elif np.any(rec.get("left")):
            # No model to ask and nothing flat to refill: Telea over the
            # missed strokes and nothing else. It is the weakest repair here
            # and it is still the right one - what it is covering is a
            # character somebody can read, and `_local_fill` is given the
            # tight mask precisely so a local method cannot smear a region.
            _local_fill(out, {"win": w, "tight": _dilated(_u8(rec["left"]))})
            redone = True

    if redone:
        after = _gray(out)

    for rec in done:
        still, how = _ghost_left(gray, after, rec)
        if not still:
            continue
        rec["r"].flagged = (rec["r"].flagged or "") + \
            (" ghost: source text is still faintly visible after the %s "
             "(%s) — paint it out in Edit" % (rec["how"] or "clean", how))


def _feather(orig: np.ndarray, filled: np.ndarray, mask: np.ndarray,
             px: float = 2.0) -> np.ndarray:
    """Blend the inpainted patch over a soft mask edge.

    A hard mask boundary leaves a visible rectangle/halo where the model's fill
    meets untouched art. Feathering the seam over a couple of pixels hides it
    while keeping the interior fully replaced.

    The ramp has to lie OUTSIDE the mask. Blurring the mask itself puts the
    halfway point exactly on its edge, so half of whatever was there survives
    the fill - and what is at the edge of a mask drawn round a letter is the
    letter's own anti-aliased rim. That is the pale outline of the original
    kanji left sitting on an otherwise clean patch: not ink the sweep can find,
    because the sweep looks for what is darker than its surroundings and this
    is a bright rim on a fill. Grow first, then blur, and the mask is fully
    replaced right up to its own boundary.
    """
    grow = max(1, int(round(px)))
    hard = (mask > 0).astype(np.float32)
    m = cv2.dilate(hard.astype(np.uint8),
                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                             (2 * grow + 1,) * 2)).astype(np.float32)
    m = cv2.GaussianBlur(m, (0, 0), px)
    # ...and the mask itself is OPAQUE, which growing before the blur was meant
    # to achieve and does not. A Gaussian at this radius peaks around 0.77 even
    # in the middle of a wide stroke, so every fill in this file - the model's
    # and the local one - was leaving 23% of the original ink on the page. On a
    # black glyph over white that is a pixel at 206, which is a legible outline
    # of the word that was there, and it is the ghost `ghost_detail` was written
    # to find. Measured: 1px stroke 0.64, 3px 0.75, 10px 0.77.
    #
    # So the ramp is what lies OUTSIDE, exactly as the paragraph above says, and
    # inside there is no ramp at all.
    m = np.maximum(m, hard)
    if filled.ndim == 3:
        m = m[..., None]
    blended = orig.astype(np.float32) * (1 - m) + filled.astype(np.float32) * m
    return blended.astype(orig.dtype)


# The local healing brush used to live here: ~460 lines of PatchMatch-style
# per-patch matching and Poisson blending, plus `heal_spot`, which tried three
# fills on a band around the spot and kept whichever rebuilt that band closest
# to the page. It measured well - mean error 40.9 -> 36.1 over 96 spots on
# eight real pages - and it is gone, because measuring well is not the same as
# being worth having. Every one of those three fills can only move texture that
# is already somewhere nearby, and the spots lee retouches after the Clean step
# are the ones where the artwork underneath was never on the page at all.
# lee, with the brush in his hand: *"remoev teh regualr healing brush, its
# ass"*. There is one healing brush now and it goes to the AI cleaner, which
# redraws. See the /heal endpoint in editor.py.
#
# `shift_fill` stays: it is not the brush. It is the Clean step's own offline
# fill, used on every page that never reaches a model.


def shift_fill(img: np.ndarray, mask: np.ndarray,
               avoid: "np.ndarray | None" = None) -> np.ndarray:
    """Content-aware fill without opencv-contrib: copy REAL pixels in.

    Diffusion inpainting (Telea) smears - a healed spot on screentone or
    hatching turns into a grey blur that reads as damage. Manga art is
    overwhelmingly repetitive at brush scale, so the honest fix is to find
    the translation of the image that best matches the ring AROUND the hole
    and copy those actual pixels into it. Dots stay dots, hatches stay
    hatches, flats stay flat. Whatever a shift cannot source (off-image, or
    inside the hole itself) falls back to Telea, and the caller feathers the
    seam.

    `avoid` IS THE REST OF THE JAPANESE ON THE PAGE, and it is only nominally
    optional. The search reaches four hole-widths in every direction, which on
    a 210px sound-effect box is most of the paper, and it picks the shift whose
    RING matches best. A flat ring matches a balloon's flat interior
    beautifully - so on lee's page 001 the winning shift copied a speech
    balloon into the hole and the page came back with 「ここの湯は…濁って…」
    printed across a character's kimono. The hole has no idea what it is being
    handed; nothing downstream looks either.

    Only the hole ITSELF was ever excluded, on the grounds that a source has to
    exist. Writing is the same argument: it is about to be erased everywhere
    else on this page too, so it is not there to be copied. It is charged like
    an off-image source - the shift loses coverage and pays `rough` for it -
    rather than forbidden outright, because on a page where every direction
    runs into some writing, a shift that clips the corner of a bubble is still
    better than a page-wide Telea smear.
    """
    m = mask > 0
    no_src = m if avoid is None else (m | (avoid > 0))
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
    # none of the texture - so its squared error on textured art is, near enough,
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
        known = ~no_src[osy, osx]
        if known.mean() < 0.7:
            continue
        d = f[oy[known], ox[known]] - f[osy[known], osx[known]]
        score = float((d * d).mean())
        # The ring alone was scoring the wrong thing, and this is the smear.
        # A shift SHORTER than the hole lands part of the hole back on itself,
        # so those pixels have no source and go to Telea - while the ring, which
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
        cover = float((inside & ~no_src[np.clip(sy, 0, H - 1),
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
        src_known = ~no_src[oksy, oksx]
        out[oky[src_known], okx[src_known]] = img[oksy[src_known],
                                                  oksx[src_known]]
        remaining[oky[src_known], okx[src_known]] = False

    if remaining.any():
        out = cv2.inpaint(out, remaining.astype(np.uint8) * 255, 5,
                          cv2.INPAINT_TELEA)
    return out
