"""A second pair of eyes for the writing comic-text-detector cannot see.

Why there is a second detector at all
-------------------------------------

comic-text-detector has two heads that find writing: `blk`, which boxes blocks
of text, and `seg`, a mask marking every pixel of writing. Everything Find text
returns comes from one or the other. Measured on lee's Korean webtoon, chapter
227 page 026 -- 720x2770, eight 하아 written in red brush across a blue panel,
covering something like a sixth of the page:

    blocks: conf>0.05: 0   conf>0.10: 0   conf>0.22: 0   conf>0.40: 0
    mask:   keep>0.05: 0.254%   keep>0.20: 0.042%   keep>0.30: 0.028%

Zero blocks at any confidence, and a mask that is black -- the few specks it
does hold do not sit on any of the eight. The same brush-drawn shapes on
WHITE, page
018, gives a mask at 1.15% and CTD boxes it: but only the half of each stroke
that crosses white, which is why lee saw 다닥써! come back as its left half and
차차 as its top half.

So three of the four things lee reported --

    *"the sfc not fully beigng found"*        -- half a stroke is on the mask
    *"the 2 boxes beigng found as one"*       -- and the grouping guesses
    *"one text haing manyt small boxes"*      -- at the fragments that are

-- are one fact seen three ways: **the mask goes black on coloured brush
shapes laid over artwork**. No threshold reaches it, because there is
nothing under the threshold to reach. Squashing less of the page into the
model's 1024 square does not reach it either: re-run in 720px windows, page 018
goes from 3 boxes to 7 and every one of them is a smaller fragment.

What CRAFT is
-------------

The detector inside easyocr, which this app already installs for Korean OCR --
no new dependency, and detection only, so no recognition cost. It was trained
on SCENE text: writing photographed on shopfronts, signs and road markings.
Coloured writing lying on a busy background is not its hard case, it is the
case it exists for. On page 026 it covers 82% of the sound-effect ink with no
box bigger than 1.8% of the page, against CTD's nothing at all.

What this module is NOT
-----------------------

It is not a replacement. CTD boxes dialogue better than anything else here --
it finds black balloons with white typesetting, which nothing that looks for
dark ink can ever do -- and none of that changes. This is a second SOURCE OF
MARKS for the coverage pass, on manhwa and manhua only, and manga never calls
it.

Two stages, and only the first is CRAFT
---------------------------------------

`easyocr.Reader.detect` runs CRAFT and then `group_text_box`, which merges
characters into a LINE so the reader has something to read. That second stage
assumes printed text on a baseline and it is wrong here at every setting tried:
on page 026 it merged three 하아 spread across a panel into one box covering a
third of the page. `get_textbox` is the stage before it, and what it returns --
one quadrilateral per character group -- is the right input to OUR grouping,
which was measured on this chapter.
"""
from __future__ import annotations

import numpy as np

# Measured on chapter 227 page 026, the page CTD's mask is black on. Sweeping
# `canvas_size`, `mag_ratio` and `text_threshold` moved NOTHING -- every row of
# the sweep identical -- because the page's long side already hits the canvas
# cap and `text_threshold` only seeds regions that `low_text` then grows. The
# two that matter, scored on how much of the sound-effect ink is covered and on
# the biggest box as a share of the page:
#
#   low_text  link   pieces   biggest   ink covered
#      0.40    0.4        8     41.7%         93.7%
#      0.45    0.8       24      6.7%         89.1%
#      0.50    0.8       30      1.8%         82.1%   <- here
#      0.55    0.8       33      1.6%         73.9%
#
# 0.50 / 0.8 is where no piece is large enough to be a panel and the ink is
# still covered. Coverage bought by swallowing a panel is not coverage: at
# low_text 0.30 one box covers 46% of the page and "covers 94% of the ink".
#
# Fragmentation is not a cost at this stage. Grouping is the next stage's job.
LOW_TEXT = 0.50
LINK_THRESH = 0.80
TEXT_THRESH = 0.60
CANVAS = 2560
MAG_RATIO = 1.0
# How much of a CRAFT group a block-head region has to cover before its veto
# stands. See `merge_into`.
BLOCK_HOLDS = 0.5

_readers: dict = {}


def lay_out_for_the_cpu(reader) -> None:
    """Turn CRAFT's weights over so the CPU can use its fast convolution.

    lee: *"i relly wan to decrease teh time it takes because riht now it takes
    froever"*.

    Measured on his 32-page chapter, timed end to end through `Project.detect`:
    **CRAFT is 93% of Find text**. The block head is 2.2 seconds and it runs
    beside CRAFT rather than after it, so it costs nothing; the measuring this
    package does -- the harvest, the walls, the grow, the kinds, the balloons,
    the ordering -- is 5.4 seconds across all 32 pages put together. There is
    nothing to shave anywhere else. Either CRAFT gets cheaper or Find text does
    not.

    Everything that makes CRAFT cheaper by giving it LESS TO LOOK AT costs
    boxes. Its canvas at 1600 is very nearly twice as fast and changes what is
    found on seven of twelve pages, every change a box lost -- 029 goes from 8
    boxes to 6. At 2048 it still moves three of twelve. lee's standing rule is
    that a missed sound effect is worse than a slow one, so the resolution
    stays where it is.

    What is left is the SAME arithmetic done better. PyTorch stores a picture
    as one plane per colour; oneDNN's fast convolution wants the channels of a
    pixel side by side, and given weights in that order it takes the blocked
    path instead of a fallback. Nothing about the model changes -- same
    weights, same layers, same input, same output shape -- so this is a layout
    change and not a numerical one. Timed on page 029: 7.45s to 5.76s.

    Same boxes, and that was measured rather than assumed. All 32 pages found
    twice, once each way, comparing every region's rectangle, kind and reading
    order: **zero pages differ**, and the chapter goes from 10.38 to 8.71
    seconds a page. The score maps do move, in the seventh decimal (1.1e-06),
    which is under every threshold this file thresholds them at by five orders
    of magnitude.

    Two faster runtimes were measured and neither is shippable. Batch-norm
    folding on top of this is 5.32s, another 8%, and costs 30 seconds of
    tracing at startup -- it does not pay for itself on a short run and lee
    clicks Find text on single pages. `torch.compile` is 4.79s, a real 1.25x,
    and costs 65 seconds and a working C++ compiler on the first run: on
    Windows, which is what lee is on, that is MSVC and most machines have not
    got it.

    Wrapped in try/except and silent, because this is a speed-up and nothing
    else. A torch too old to know the flag, or an easyocr that stops calling
    its detector `detector`, should leave a slower Find text and not a
    traceback.
    """
    try:
        import torch
        reader.detector.to(memory_format=torch.channels_last)
    except Exception:
        pass


def _reader(langs: tuple):
    """One easyocr Reader per language set, kept for the life of the process.

    Building one loads the CRAFT weights off disk, which is slow enough to
    notice on a 36-page chapter and pointless to repeat.
    """
    if langs not in _readers:
        import easyocr
        r = easyocr.Reader(list(langs), gpu=False, verbose=False)
        # Once, here, and not at every page: the layout is a property of the
        # weights and turning them over again on each call would be a copy per
        # page for no gain.
        lay_out_for_the_cpu(r)
        _readers[langs] = r
    return _readers[langs]


def available() -> bool:
    """Whether CRAFT can run here at all.

    easyocr is a real install -- it brings torch with it -- and a person who
    has not done the Korean OCR setup should get a chapter found the old way,
    not a traceback.
    """
    try:
        import easyocr  # noqa: F401
    except Exception:
        return False
    return True


def pieces(img: np.ndarray, langs: tuple = ("ko", "en"),
           low_text: float = LOW_TEXT, link_thresh: float = LINK_THRESH,
           text_thresh: float = TEXT_THRESH) -> list[list[int]]:
    """Every character group CRAFT can find, as [x0, y0, x1, y1].

    Deliberately ungrouped -- see the module docstring. These are marks, and
    something else decides which of them are one sound effect.
    """
    from easyocr.detection import get_textbox

    r = _reader(tuple(langs))
    polys = get_textbox(
        r.detector, img, canvas_size=CANVAS, mag_ratio=MAG_RATIO,
        text_threshold=text_thresh, link_threshold=link_thresh,
        low_text=low_text, poly=False, device="cpu", optimal_num_chars=None)
    out = []
    for q in (polys[0] if polys else []):
        a = np.asarray(q, dtype=float).reshape(-1, 2)
        x0, y0 = a.min(0)
        x1, y1 = a.max(0)
        if x1 > x0 and y1 > y0:
            out.append([int(x0), int(y0), int(x1), int(y1)])
    return out


def marks(boxes) -> list[dict]:
    """CRAFT's pieces in the shape `comictext.reach_groups` reads."""
    return [{"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3],
             "sz": max(b[2] - b[0], b[3] - b[1])} for b in boxes]


def group(boxes, near_x: float, near_y: float) -> list[dict]:
    """CRAFT's pieces gathered into sound effects, by the SAME reach the mask's
    marks go through -- `comictext.reach_groups`, not a second copy of it.

    Each group comes back as `{"box": [x0,y0,x1,y1], "pieces": [...]}`, keeping
    what it was made of. `merge_into` needs that: a group can come out the size
    of a panel, and the pieces are the answer to it.

    The NUMBERS are the format's, not this function's, and the ones that suit
    the mask do not suit CRAFT: the mask's marks are stroke fragments, often a
    fraction of one syllable, so a reach of "1.8 times the smaller mark" is a
    fraction of a syllable. CRAFT hands back whole character groups, so the
    same 1.8 is 1.8 whole syllables, and on page 026 it swept all eight 하아
    into one box covering 26% of the page. Same rule, different marks, and the
    reach is measured again on this input.
    """
    from .comictext import reach_groups

    mk = marks(boxes)
    out = []
    for members in reach_groups(mk, near_x=near_x, near_y=near_y).values():
        mine = [boxes[i] for i in members]
        out.append({"box": [min(b[0] for b in mine), min(b[1] for b in mine),
                            max(b[2] for b in mine), max(b[3] for b in mine)],
                    "pieces": mine})
    return out


def _overlap(a, b) -> float:
    """How much of `a` lies inside `b`, as a share of `a`."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / float(area)


def _under_cap(groups, limit: float) -> list:
    """Every box worth considering, with the panel-sized ones traded in.

    A group whose own box is over `limit` gives it up and offers the pieces it
    was made of instead. Done in ONE flattening pass rather than by pushing the
    pieces back onto a work queue: a piece that is itself over the limit would
    offer itself again for ever, and then the only thing between this and an
    infinite loop would be a guard somebody could delete. A piece has nothing
    smaller to fall back to, so it is dropped, and this cannot loop at all.
    """
    out = []
    for item in groups:
        box = item["box"]
        if (box[2] - box[0]) * (box[3] - box[1]) <= limit:
            out.append(box)
            continue
        for b in (item.get("pieces") or []):
            if b != box and (b[2] - b[0]) * (b[3] - b[1]) <= limit:
                out.append(b)
    return out


def merge_into(regions, from_block, groups, page_w: int, page_h: int,
               cap: float, pad: int = 0):
    """Fold CRAFT's sound effects into what comic-text-detector already found.

    Three cases, and the third is the one lee actually reported.

    **A group over nothing** is writing neither head saw. It becomes a new
    region, kind `sfx` -- the same call the coverage pass makes, for the same
    reason: writing that is not set inside a block is hand-drawn over the
    artwork, and calling it sfx keeps it out of the balloon fitter.

    **A group over a BLOCK-HEAD region** is dropped. The block head is the best
    thing here at dialogue -- it boxes black balloons with white typesetting,
    which nothing looking for dark ink can find -- and CRAFT run over a balloon
    will happily reach past its edge into the drawing. Where the two disagree
    about a balloon, the block head is right.

    **A group over a COVERAGE-PASS region** grows that region to hold both.
    This is *"the sfc not fully beigng found"*: on page 018 the mask covers the
    half of 다닥써! that crosses white and drops the half that crosses artwork,
    so CTD returns the left half and CRAFT returns the whole thing. Growing is
    right and replacing is not -- the region carries a text mask the cleaner
    paints out, and that mask is a real measurement of where ink is.

    **A group the size of a panel falls back to the pieces it was made of**
    (see `_under_cap`), rather than being thrown away. A box that large would
    have the cleaner paint out a quarter of the page, so it cannot stand -- but
    the writing under it is real and dropping it silently is how a sound effect
    goes missing.

    That case is not hypothetical and it is not fixable by tuning. The bottom
    of page 026 is four 하아 cascading diagonally down the dress, and CRAFT
    boxes their nine syllables correctly -- none over 2.2% of the page. Every
    consecutive pair of those nine has **gx = 0 and gy = 0**: the bounding
    boxes literally overlap, because the cascade is diagonal. Zero gap is zero
    gap at every threshold, so no reach separates them and the whole cascade
    comes out as one box 26% of the page wide. Nine boxes on nine syllables is
    a worse answer than four boxes on four effects and a far better one than a
    painted-out dress, and a person can join boxes by hand in a second.

    Returns the list of groups that became new regions, so a caller can say how
    many the second detector actually added.
    """
    limit = cap * page_w * page_h
    added = []
    for g in _under_cap(groups, limit):
        hit_block = False
        grow = None
        for r in regions:
            x, y, w, h = r.bbox
            box = (x, y, x + w, y + h)
            if _overlap(g, box) <= 0 and _overlap(box, g) <= 0:
                continue
            if id(r) in from_block:
                # The block head outranks CRAFT about a balloon -- and a
                # balloon is a block that actually HOLDS the group's writing.
                # lee's chapter title ("일당백으로 / 구귀족들을 위협하는", huge
                # display type over dark artwork) died here for a different
                # reason: the block head saw two FRAGMENTS of it, each
                # covering a tenth to a third of a CRAFT group that had all
                # thirteen characters boxed cleanly, and a fragment vetoed
                # the whole. lee: *"4 missed most of teh text"*.
                #
                # So the veto is measured now: a block region only stands in
                # a group's way when it covers at least `BLOCK_HOLDS` of it.
                # CRAFT spilling past a balloon's edge leaves the block
                # covering most of the group, so every balloon keeps its
                # veto; a fragment on writing the head plainly failed to see
                # does not.
                ga = max(1, (g[2] - g[0]) * (g[3] - g[1]))
                ox = min(g[2], x + w) - max(g[0], x)
                oy = min(g[3], y + h) - max(g[1], y)
                if ox > 0 and oy > 0 and ox * oy >= BLOCK_HOLDS * ga:
                    hit_block = True
                    break
                continue
            if grow is None or (r.bbox[2] * r.bbox[3]
                                > grow.bbox[2] * grow.bbox[3]):
                grow = r
        if hit_block:
            continue
        if grow is not None:
            x, y, w, h = grow.bbox
            nx0 = max(0, min(x, g[0] - pad))
            ny0 = max(0, min(y, g[1] - pad))
            nx1 = min(page_w, max(x + w, g[2] + pad))
            ny1 = min(page_h, max(y + h, g[3] + pad))
            grow.bbox = (nx0, ny0, nx1 - nx0, ny1 - ny0)
            if grow.bubble_bbox is not None:
                grow.bubble_bbox = grow.bbox
            continue
        added.append((max(0, g[0] - pad), max(0, g[1] - pad),
                      min(page_w, g[2] + pad), min(page_h, g[3] + pad)))
    return added
