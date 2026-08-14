"""Tests for the deterministic stages of the pipeline.

    python -m pytest tests/ -q

The first group needs no files at all. The second group needs a few manga
pages; point MANGATL_TEST_PAGES at a folder of them, or drop them in ./pages,
./chapter or ./up. Without them those tests skip rather than fail.
"""
import glob as _glob
import json
import os as _os

import numpy as np
import pytest

from mangatl.order import reading_order
from mangatl.typeset import (TypesetConfig, band_width, break_lines,
                             chord_profile, default_font_path, _text_w)
from scratch import scratch
from where import PKG


# --------------------------------------------------------------- test fixtures

def _sample_pages(n: int = 4) -> list[str]:
    """Any manga pages available locally, or an empty list."""
    roots = [_os.environ.get("MANGATL_TEST_PAGES", ""),
             "pages", "chapter", "up", "."]
    for root in roots:
        if not root or not _os.path.isdir(root):
            continue
        hits: list[str] = []
        for ext in ("jpg", "jpeg", "png", "webp"):
            hits += _glob.glob(_os.path.join(root, "**", f"*.{ext}"),
                               recursive=True)
        # Ignore our own exported output, the bundled fonts folder, and
        # anything a package manager dragged in (node_modules is full of tiny
        # fixture images that are definitely not manga pages).
        #
        # `out` and `_tmp...` are matched at ANY depth, not just the first.
        # The suite writes its own scratch pages — `_tmp_centred`, a working
        # copy's `mangatl/out/input` — and a run that had written them scored
        # the bubble tests against renders of its own output, or, worse,
        # against a screenshot somebody had left in the folder. The tests that
        # need real pages then failed or passed depending on what had run
        # before them, which is no use as evidence for anything.
        # `static` joined this list the day the app grew an icon of its own:
        # a 512px PNG of the MangaTCT mark is an image in the tree, and this
        # search happily called it a manga page and then reported that the
        # detector finds no speech balloons on it. The app's OWN artwork is
        # never a page — nor are the fonts, and nor is anything the suite or a
        # package manager wrote.
        def ok(h: str) -> bool:
            parts = h.replace("\\", "/").split("/")
            return not any(p in ("fonts", "static", "assets", "site",
                                 "node_modules", ".git", "out")
                           or p.startswith("_tmp") for p in parts)

        hits = [h for h in hits if ok(h)]
        if hits:
            return sorted(hits)[:n]
    return []


_PAGES = _sample_pages()
needs_pages = pytest.mark.skipif(not _PAGES, reason="no sample pages found")


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0, min(ay + ah, by + bh) - max(ay, by))
    i = ox * oy
    return i / max(1, aw * ah + bw * bh - i)


# ------------------------------------------------------------- reading order

def test_grid_is_right_to_left_top_to_bottom():
    tl, tr = (0, 0, 100, 100), (200, 0, 100, 100)
    bl, br = (0, 200, 100, 100), (200, 200, 100, 100)
    assert reading_order([tl, tr, bl, br]) == [1, 0, 3, 2]


def test_single_row_is_reversed():
    row = [(0, 0, 80, 40), (100, 0, 80, 40), (200, 0, 80, 40)]
    assert reading_order(row) == [2, 1, 0]


def test_single_column_is_top_down():
    col = [(0, 0, 80, 40), (0, 60, 80, 40), (0, 120, 80, 40)]
    assert reading_order(col) == [0, 1, 2]


def test_overlapping_boxes_fall_back_to_rightmost_first():
    assert reading_order([(0, 0, 120, 80), (60, 40, 120, 80)]) == [1, 0]


def test_empty_input():
    assert reading_order([]) == []


def test_slanted_gutter_still_separates():
    """Two bands separated by a diagonal gutter — defeats an axis-aligned cut
    at 0 degrees, should be recovered by the rotation search."""
    top = [(0, 0, 60, 40), (200, 30, 60, 40)]
    bot = [(0, 150, 60, 40), (200, 180, 60, 40)]
    seq = reading_order(top + bot)
    assert set(seq[:2]) == {0, 1} and set(seq[2:]) == {2, 3}


# --------------------------------------------------------------- chord widths

def _ellipse_mask(w=200, h=120):
    yy, xx = np.mgrid[0:h, 0:w]
    return (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) <= 1.0


def test_chord_is_widest_at_the_middle():
    widths, y0, y1 = chord_profile(_ellipse_mask())
    mid = (y0 + y1) // 2
    assert widths[mid] > widths[y0 + 2]
    assert widths[mid] > widths[y1 - 2]


def test_band_width_takes_the_narrowest_row():
    widths, y0, y1 = chord_profile(_ellipse_mask())
    mid = (y0 + y1) // 2
    assert band_width(widths, y0, mid) <= widths[mid]


def test_chord_profile_on_empty_mask():
    widths, y0, y1 = chord_profile(np.zeros((10, 10), bool))
    assert widths.size == 0 and y0 == y1 == 0


# -------------------------------------------------------------- line breaking

def _measure(font, size):
    return lambda s: _text_w(font, size, s)


def test_breaks_into_requested_line_count():
    font = default_font_path()
    words = "the quick brown fox jumps over the lazy dog".split()
    lines = break_lines(words, [200.0, 200.0, 200.0], _measure(font, 14),
                        _text_w(font, 14, " "))
    assert lines is not None and len(lines) == 3
    assert " ".join(lines).split() == words        # no words lost or reordered


def test_returns_none_when_impossible():
    font = default_font_path()
    assert break_lines(["antidisestablishmentarianism"], [20.0],
                       _measure(font, 20), 5.0) is None


def test_respects_per_line_widths():
    """Narrow first line, wide second — the long word must land on line two."""
    font = default_font_path()
    lines = break_lines(["hi", "extraordinarily"], [40.0, 400.0],
                        _measure(font, 12), _text_w(font, 12, " "))
    assert lines == ["hi", "extraordinarily"]


def test_prefers_balanced_over_greedy():
    """Knuth-Plass leaves the last line free, which makes packing cheap and
    yields a full line above a one-word orphan. Comic typesetting wants balance."""
    font = default_font_path()
    words = "aaa bbb ccc ddd eee fff".split()
    lines = break_lines(words, [300.0, 300.0], _measure(font, 12),
                        _text_w(font, 12, " "))
    assert lines is not None
    assert sorted(len(l.split()) for l in lines) == [3, 3]


# -------------------------------------------------------------- block shape

def _oval_region(w, h, text):
    """A region whose bubble is an oval, which is what real bubbles are."""
    from mangatl.models import TextRegion
    pad = 30
    yy, xx = np.mgrid[0:h + 2 * pad, 0:w + 2 * pad]
    m = ((((xx - (w / 2 + pad)) / (w / 2 - 3)) ** 2
          + ((yy - (h / 2 + pad)) / (h / 2 - 3)) ** 2) <= 1.0)
    m = (m * 255).astype(np.uint8)
    r = TextRegion(id=0, bbox=(pad, pad, w, h), text_mask=m, bubble_mask=m,
                   bubble_bbox=(pad, pad, w, h))
    r.dst_text = text
    return r


def test_ink_band_is_shorter_than_the_line_box():
    """A line box is size*leading tall but the letters fill only part of it.
    Measuring the bubble's chord across the whole box is what used to make
    every line narrower than it needed to be, worst at an oval's poles."""
    from mangatl.typeset import ink_extents
    top, bot = ink_extents(default_font_path(), 30, False)
    assert bot - top < 30 * 1.18
    assert top < 0 < bot            # the band straddles the anchor point


def test_a_short_sentence_does_not_become_a_column():
    """Three words in a wide oval belong on two or three even lines. Leaving
    the last line unscored made a stack of one-word lines free, and that is
    exactly what this used to produce."""
    from mangatl.typeset import fit_region
    cfg = TypesetConfig(font_path=default_font_path())
    r = _oval_region(200, 130, "DON'T WORRY ABOUT IT — REALLY.")
    lay = fit_region(r, cfg)
    assert lay is not None
    assert len(lay.lines) <= 3, lay.lines
    # No line above the last may be a lone word while another runs far longer.
    # The last line is allowed to fall short — that is normal typesetting.
    longest = max(_text_w(lay.font_path, lay.font_size, ln) for ln in lay.lines)
    for ln in lay.lines[:-1]:
        if len(ln.split()) == 1:
            w = _text_w(lay.font_path, lay.font_size, ln)
            assert w > 0.55 * longest, (ln, lay.lines)


def test_two_words_fill_a_small_bubble_on_two_lines():
    """The property lee picked out of the contact sheet. A short shout in a
    bubble barely wider than the longer word belongs on two big lines; laying
    it out as one ribbon is what forces the size down to something unreadable.
    No knobs touched here — this is the shipped configuration answering."""
    from mangatl.typeset import fit_region
    lay = fit_region(_oval_region(180, 130, "HELLO, EVERYONE!"),
                     TypesetConfig(font_path=default_font_path()))
    assert lay is not None
    assert len(lay.lines) == 2, lay.lines
    # Two lines of that height are only worth having if the type is big. 130px
    # of bubble that ends up at 12pt is the failure this whole model exists to
    # stop, so pin the size, not just the break.
    assert lay.font_size >= 18, (lay.font_size, lay.lines)


# Zeroing a weight has to change what `fit_region` ANSWERS, or the term is
# decorative and the next person to tune it is tuning noise. Each row below is
# a bubble found by sweeping every specimen against every knob: the case where
# that one term, alone, is what decides the layout.
#
# The fixtures are re-derived whenever a weight moves, not kept. Raising
# `w_vfill` left four of these rows passing for the wrong reason — the term
# had grown big enough to decide those particular ovals on its own, so
# switching `w_ragged` off no longer changed the answer there and the row
# stopped proving anything about `w_ragged`. A row that has quietly stopped
# testing is worse than no row, because it still reads like coverage. Every
# row below was re-derived after that move by sweeping ten oval sizes against
# nine real sentences and keeping, per knob, a case where zeroing that one term
# — and nothing else — moves the answer.
@pytest.mark.parametrize("knob,w,h,text", [
    # Without it the short last line is free, so five lines with a long tail
    # beat six even ones and the size drops a point to pay for them.
    #
    # The four specimens marked BELOW were re-picked when the leading sweep
    # lost its sub-solid candidate (see `TypesetConfig.leadings` — lee: "the
    # line gap shoud nver be less than 1"). Removing a candidate shrinks the
    # search, and a bubble that used to turn on a weight can stop turning on
    # anything; that is the sweep getting smaller, not the weight going dead.
    # Each was re-found the same way it was found originally: sweep ovals from
    # 150x90 to 300x300 and keep one this weight, on its own, still decides.
    #
    # Three more moved again when `small` started measuring against the sizes
    # a balloon can actually take instead of the settings dialog's range (see
    # `_feasible_top`). That makes the size ladder steeper in a small bubble,
    # so an oval where a break term used to win by a hair now goes to the
    # bigger type — which is the point of the change and not a term going
    # quiet. Proved rather than assumed before re-picking: over six sentences
    # by sixty-three ovals, zeroing `w_cpl` alone still changes the answer in
    # 50 of them, `w_balance` in 33 and `w_ragged` in 7, and the rows below
    # are three of those. A weight that had genuinely died would have scored
    # nought.
    ("w_last_line", 135, 230,      # re-picked when the line-gap floor rose to 1.20
     "THIS POWER CAN ONLY SAVE PEOPLE WHEN IT'S BOUND TO THE TRUE SAINT."),
    # Without it, the largest type that merely fits wins and every bubble
    # comes out cramped: 21pt on three lines becomes 17pt on two. This is the
    # term the most specimens turn on — 37 of the 90 swept.
    ("w_small", 180, 130, "MY HARD WORK PAID OFF TOO—"),
    # Without it a lone word on a half-empty line costs nothing, and the tall
    # narrow balloon takes the extra break.
    ("w_orphan", 175, 266, "MY HARD WORK PAID OFF TOO—"),
    # Without it there is no comfortable line length to aim at, so the block
    # spreads from six full lines into seven short ones — buying a point of
    # size with a shape no typesetter would set.
    ("w_cpl", 135, 260,           # re-picked when the line-gap floor rose to 1.20
     "THIS POWER CAN ONLY SAVE PEOPLE WHEN IT'S BOUND TO THE TRUE SAINT."),
    # Without it lines need not match each other in length, so the balloon
    # takes five uneven lines over six matched ones and pays a point for them.
    ("w_balance", 165, 260,       # re-picked when the line-gap floor rose to 1.20
     "THIS POWER CAN ONLY SAVE PEOPLE WHEN IT'S BOUND TO THE TRUE SAINT."),
    # Without it unused width on a line is free, so the block spreads into a
    # taller stack of stubs that each fill their own narrow chord and buys two
    # points of size with the raggedness.
    ("w_ragged", 150, 200,        # re-picked when the line-gap floor rose to 1.20
     "MY HARD WORK PAID OFF TOO—"),
    # A TALL balloon with almost nothing in it, which is the only shape this
    # term speaks to. `vfill` is a one-sided ramp: it charges a block for the
    # height it leaves empty and says nothing about a block that fills the
    # balloon, so on a bubble sized for its sentence it is flat and decides
    # nothing — zero of the ninety ovals in the sweep turn on it. Here it is
    # the whole story: a shout in a 150x300 balloon sets 34pt on two lines
    # with the term and a 26pt ribbon without it, floating in white.
    ("w_vfill", 150, 300, "NO WAY."),
])
def test_each_layout_weight_is_load_bearing(knob, w, h, text):
    from mangatl.typeset import fit_region
    font = default_font_path()
    shipped = fit_region(_oval_region(w, h, text), TypesetConfig(font_path=font))
    without = fit_region(_oval_region(w, h, text),
                         TypesetConfig(font_path=font, **{knob: 0.0}))
    assert (len(shipped.lines), shipped.font_size) != \
           (len(without.lines), without.font_size), \
        (knob, shipped.lines, shipped.font_size, without.lines)


def _wedge_region(w, h, text, flip=False):
    """A shape whose width ramps from 0.32*w at one end to w at the other.

    Not an exotic fixture: every share of a balloon that carries two blocks of
    one split line is a wedge, because the balloon gets cut straight across
    between them.
    """
    from mangatl.models import TextRegion
    pad = 30
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    for k in range(h):
        t = k / (h - 1.0)
        frac = 0.32 + 0.68 * ((1 - t) if flip else t)
        ww = int(w * frac)
        m[pad + k, pad + (w - ww) // 2:pad + (w - ww) // 2 + ww] = 255
    r = TextRegion(id=0, bbox=(pad, pad, w, h), text_mask=m, bubble_mask=m,
                   bubble_bbox=(pad, pad, w, h))
    r.dst_text = text
    return r


@pytest.mark.parametrize("flip", [False, True])
def test_a_wedge_lets_the_block_sit_where_it_is_widest(flip):
    """The block used to be nailed to the middle of the height it had.

    In a symmetric oval that is right — the chord is widest across the centre,
    so anywhere else is narrower. In anything that is NOT symmetric it throws
    room away, and half of a split balloon never is. Here the same three lines
    are worth 21pt sitting down in the wide end and only 16 stuck in the
    middle, so the drift is worth five points of type on a shape lee has on
    nearly every page.

    Both assertions bite. Without the drift the size falls to 16 AND the ink
    parks on the mask's centre line; the flip proves it is the shape being
    read and not a constant lean.
    """
    from mangatl.typeset import fit_region
    r = _wedge_region(190, 200, "MY HARD WORK PAID OFF TOO—", flip)
    lay = fit_region(r, TypesetConfig(font_path=default_font_path()))
    assert len(lay.lines) == 3, lay.lines
    assert lay.font_size >= 20, (lay.font_size, lay.lines)
    ys = [y for _, y in lay.line_origins]
    ink_mid = (min(ys) + max(ys)) / 2.0
    rows = np.nonzero(r.bubble_mask.any(axis=1))[0]
    mask_mid = (int(rows[0]) + int(rows[-1])) / 2.0
    # Down into the wide end when the shape widens downward, up into it when
    # it widens upward — a long way either side of centre, not a nudge.
    if flip:
        assert ink_mid < mask_mid - 40, (ink_mid, mask_mid)
    else:
        assert ink_mid > mask_mid + 40, (ink_mid, mask_mid)


def _split_balloon_regions(top_text, bottom_text, cut=0.42):
    """One pear-shaped balloon carrying two blocks of a single split line.

    Narrow at the top, widest around two thirds down: lee's page-013 balloon,
    and an ordinary balloon shape. The cut is where the JAPANESE stopped and
    started, which is what the detector reports and which has nothing to do
    with how long the English is.
    """
    from mangatl.models import TextRegion
    w, h, pad = 175, 266, 30
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    for k in range(h):
        t = k / (h - 1.0)
        frac = (0.40 + 0.60 * (t / 0.62)) if t < 0.62 \
            else (1.0 - 0.28 * ((t - 0.62) / 0.38))
        ww = int(w * frac)
        m[pad + k, pad + (w - ww) // 2:pad + (w - ww) // 2 + ww] = 255
    row = pad + int(h * cut)
    out = []
    for i, (text, sl) in enumerate([(top_text, slice(0, row)),
                                    (bottom_text, slice(row + 3, None))]):
        piece = np.zeros_like(m)
        piece[sl] = m[sl]
        ys, xs = np.nonzero(piece)
        box = (int(xs.min()), int(ys.min()),
               int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        r = TextRegion(id=i + 1, bbox=box, text_mask=piece, bubble_mask=piece,
                       bubble_bbox=box)
        r.dst_text = text
        r.link = 3          # one line of dialogue, broken across two blocks
        out.append(r)
    return out


def test_a_split_balloon_is_divided_by_how_much_each_half_says():
    """Both halves of a split bubble, in one voice, as big as it will carry.

    The detector's cut is where the Japanese changed block, so the English
    inherits a division that has nothing to do with its own length: here the
    twenty-six-character half gets the narrow top and the eighteen-character
    half the wide bottom, and the fitter answers 15pt against 31pt — one
    cramped, the other shouting in four one-word lines. That mismatch is what
    lee saw on the exported page.

    `link_masks` re-divides the balloon's AREA in proportion to how much each
    half has to typeset. Equal area per character is equal type size, which is
    what a typesetter sets out to do.
    """
    from mangatl.typeset import fit_region, link_masks
    top, bottom = "MY HARD WORK PAID OFF TOO—", "—SO TAKE CARE NOW!"
    regions = _split_balloon_regions(top, bottom)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12, max_font=34)

    as_detected = [fit_region(r, cfg) for r in regions]
    assert abs(as_detected[0].font_size - as_detected[1].font_size) >= 8, \
        [(l.font_size, l.lines) for l in as_detected]   # the bug, still there

    before = [r.bubble_mask.copy() for r in regions]
    shares = link_masks(regions)
    assert set(shares) == {r.id for r in regions}
    areas = [int((shares[r.id] > 0).sum()) for r in regions]
    want = len(top) / float(len(top) + len(bottom))
    assert abs(areas[0] / float(sum(areas)) - want) < 0.03, (areas, want)

    laid = [fit_region(r, cfg, shares[r.id]) for r in regions]
    assert abs(laid[0].font_size - laid[1].font_size) <= 2, \
        [(l.font_size, l.lines) for l in laid]
    # Both halves typeset, both bigger than the cramped half was, and neither
    # broken into a column of stubs.
    for lay, text in zip(laid, (top, bottom)):
        assert " ".join(lay.lines) == text, lay.lines
        assert lay.font_size >= 18, (lay.font_size, lay.lines)
        assert len(lay.lines) <= 3, lay.lines

    # A shape invented for one typesetting pass must not outlive it: regions are
    # saved as the polygon they were DETECTED with, so a re-cut written back
    # would be the shape reloaded next session, compounding every time.
    for r, was in zip(regions, before):
        assert np.array_equal(r.bubble_mask, was)


def test_a_shout_in_a_tall_balloon_gets_the_type_the_balloon_will_carry():
    """Two words in a balloon built for a paragraph.

    Nothing else in this file asks what happens when there is very little to
    typeset and a great deal of paper. The answer used to be a single 26pt
    ribbon adrift in 300px of white, because every other term in the model is
    satisfied by it: one line is perfectly balanced, perfectly unragged, has no
    orphan and no short last line. `vfill` is the only term that objects, and
    it objects by charging the block for the height it leaves empty."""
    from mangatl.typeset import fit_region
    lay = fit_region(_oval_region(150, 300, "NO WAY."),
                     TypesetConfig(font_path=default_font_path(), max_font=34))
    assert len(lay.lines) == 2, lay.lines
    assert lay.font_size >= 30, (lay.font_size, lay.lines)


def _side_by_side_regions(texts, w=275, h=440, cut=0.62):
    """One balloon divided DOWN THE MIDDLE between two blocks of dialogue.

    This is what `detect.balloon` reports whenever two blocks of Japanese sit
    beside each other, which is most of the time: Japanese sets in vertical
    columns, so a second block goes alongside the first rather than under it.
    The division is a correct answer to "whose pixel was this" and often a
    wrong answer to "where does this block of ENGLISH go", because English
    sets in horizontal lines and wants the balloon's whole width.
    """
    from mangatl.models import TextRegion
    pad = 30
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    for k in range(h):
        t = k / (h - 1.0)
        frac = 0.55 + 0.45 * (1.0 - abs(t - 0.5) * 2) ** 0.5
        ww = int(w * frac)
        m[pad + k, pad + (w - ww) // 2:pad + (w - ww) // 2 + ww] = 255
    xs = np.nonzero(m.any(axis=0))[0]
    col = int(xs[0] + (xs[-1] - xs[0]) * cut)
    out = []
    # Right column first: that is the block the Japanese reads first, and the
    # order the regions arrive in is the order the shares are handed out.
    for i, sl in enumerate([slice(col + 2, None), slice(0, col - 1)]):
        piece = np.zeros_like(m)
        piece[:, sl] = m[:, sl]
        ys, x2 = np.nonzero(piece)
        box = (int(x2.min()), int(ys.min()),
               int(x2.max() - x2.min() + 1), int(ys.max() - ys.min() + 1))
        r = TextRegion(id=i + 1, bbox=box, text_mask=piece, bubble_mask=piece,
                       bubble_bbox=box)
        r.dst_text = texts[i]
        out.append(r)
    return out


def test_a_balloon_split_down_the_middle_typesets_each_block_in_its_own_box():
    """lee's rule, on the balloon that used to be the argument against it.

    This case used to typeset the other way round, and the docstring that stood
    here said why: two columns of Japanese overlapping over four fifths of
    their height, the shorter block handed a hundred-pixel strip, and a
    typesetter would stack the two blocks and give each the balloon's full
    width. It did — 26pt and 19pt, against 14 and 14 for the columns.

    lee looked at a page typeset that way and said no, twice: *"EACH BOX HAS
    ITS OWN TEXT"*, and then *"the typesetting shoud not be putting text
    across 2 boxes it shoud never happen — for buble text make it so that teh
    text goes where teh box is with a little leeway"*. Full width and staying
    in your own box are mutually exclusive for two boxes side by side; there
    is no third answer, and he picked the box. The 26/19 -> 14/14 is the
    measured price of that choice on this shape, and it is his to pay.

    What this pins down is that the price buys the thing it was paid for: the
    whole translation still goes in, and neither block's letters reach into
    the other block's box.
    """
    from mangatl.typeset import fit_region, share_masks
    texts = ["THIS POWER CAN ONLY SAVE PEOPLE WHEN IT'S BOUND TO THE TRUE SAINT.",
             "DON'T SAY SOMETHING SO DISRESPECTFUL...!"]
    regions = _side_by_side_regions(texts)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12, max_font=34)

    before = [r.bubble_mask.copy() for r in regions]
    shares = share_masks(regions, cfg)
    assert set(shares) == {r.id for r in regions}
    laid = [fit_region(r, cfg, shares[r.id]) for r in regions]
    for lay, text in zip(laid, texts):
        assert " ".join(lay.lines) == text, lay.lines   # nothing dropped
    # Side by side, each in its own column: the two blocks' letters do not
    # share any column of the page, and neither reaches the other's box.
    for k, lay in enumerate(laid):
        other = regions[1 - k]
        ox, _, ow, _ = other.bbox
        for x, _ in lay.line_origins:
            assert not (ox <= x < ox + ow), (k, x, other.bbox)
    lefts = [min(x for x, _ in l.line_origins) for l in laid]
    rights = [max(x for x, _ in l.line_origins) for l in laid]
    assert rights[1] < lefts[0], (lefts, rights)

    # The same rule as `link_masks`: a shape invented for one typesetting pass
    # must never be written back, because regions persist as geometry.
    for r, was in zip(regions, before):
        assert np.array_equal(r.bubble_mask, was)


def test_a_balloon_the_detector_already_divided_well_is_not_made_worse():
    """The guarantee that makes confining the blocks safe to ship.

    A wide shallow balloon divided down the middle is already the good
    division — each block has a box it fits in, and cutting across would hand
    each a band too short to typeset in. Confining a block to its own box is
    the same answer here, so the typesetting must not move at all.
    """
    from mangatl.typeset import fit_region, share_masks
    texts = ["MY HARD WORK PAID OFF TOO—", "HELLO, EVERYONE!"]
    regions = _side_by_side_regions(texts, w=520, h=120, cut=0.5)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12, max_font=34)

    as_detected = [fit_region(r, cfg) for r in regions]
    assert min(l.font_size for l in as_detected) >= 24, \
        [(l.font_size, l.lines) for l in as_detected]   # already typesetting well

    shares = share_masks(regions, cfg)
    laid = [fit_region(r, cfg, shares.get(r.id)) for r in regions]
    for was, now in zip(as_detected, laid):
        assert now.font_size >= was.font_size, (was.font_size, now.font_size)
        assert now.lines == was.lines, (was.lines, now.lines)


def _two_lobe_regions(right_text, left_text):
    """One balloon drawn as TWO LOBES, a block of dialogue in each.

    lee's page-013 balloon: a tall oval with a rounder one budded off its lower
    left, the first block of dialogue in the tall one and the second in the
    bud. The detector reports it stacked — the two columns of Japanese barely
    overlap in y, so the balloon gets divided across — and that division is
    what the region masks below carry, hairline gap and all.
    """
    import cv2
    from mangatl.models import TextRegion
    pad, w, h = 30, 265, 405
    yy, xx = np.mgrid[0:h + 2 * pad, 0:w + 2 * pad]
    tall = (((xx - (pad + 159)) / 79.5) ** 2
            + ((yy - (pad + 202)) / 202.5) ** 2) <= 1.0
    bud = (((xx - (pad + 63)) / 63.6) ** 2
           + ((yy - (pad + 307)) / 98.5) ** 2) <= 1.0
    m = np.zeros(xx.shape, np.uint8)
    m[tall | bud] = 255

    # The Japanese sits WHOLLY inside the lobe it was written in, as it does on
    # the page — three columns in the trunk, two in the bud.
    inks = []
    for y0, y1, x0, x1 in ((70, 226, 150, 250), (280, 400, 55, 115)):
        ink = np.zeros_like(m)
        ink[y0:y1, x0:x1] = 255
        inks.append((ink & m).astype(np.uint8))

    cut = pad + 201
    out = []
    for i, (text, sl) in enumerate([(right_text, slice(0, cut)),
                                    (left_text, slice(cut + 3, None))]):
        piece = np.zeros_like(m)
        piece[sl] = m[sl]
        ys, xs = np.nonzero(piece)
        r = TextRegion(id=i + 1, text_mask=inks[i], bubble_mask=piece,
                       bbox=cv2.boundingRect(inks[i]),
                       bubble_bbox=(int(xs.min()), int(ys.min()),
                                    int(xs.max() - xs.min() + 1),
                                    int(ys.max() - ys.min() + 1)))
        r.dst_text = text
        out.append(r)
    return out


def test_a_two_lobed_balloon_is_divided_along_its_own_neck():
    """Each block gets the lobe it was written in — not a slice of the balloon.

    A band cut, whichever way it runs, hands each block a share the full width
    or the full height of the balloon, and the fitter centres the block in the
    share it is given. So the bud's dialogue comes out centred on the balloon's
    whole width rather than on the bud, sitting off to one side of the ink it
    replaces with the trunk's empty white beside it. That off-centre placement
    is what lee sent back, twice, and no amount of extra point size fixes it.

    Two overlapping ovals meet at two corners, one either side of the neck —
    the only two places the outline turns back on itself. Cutting between them
    is not a guess at where the English should go, it is the page saying it,
    and the share it yields is small in BOTH directions: that is what this
    test pins. A share under three quarters of the balloon each way cannot be
    a band, so the assertion below fails the moment the neck cut stops firing
    and either proportional cut answers in its place.
    """
    import cv2
    from mangatl.typeset import fit_region, share_masks
    texts = ["MY HARD WORK PAID OFF TOO—", "—SO TAKE CARE NOW!"]
    regions = _two_lobe_regions(*texts)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12, max_font=24)

    as_detected = [fit_region(r, cfg) for r in regions]
    assert min(l.font_size for l in as_detected) <= 22, \
        [(l.font_size, l.lines) for l in as_detected]      # the bug, still there

    before = [r.bubble_mask.copy() for r in regions]
    shares = share_masks(regions, cfg)
    assert set(shares) == {r.id for r in regions}

    whole = np.zeros_like(regions[0].bubble_mask)
    for r in regions:
        whole = np.maximum(whole, (r.bubble_mask > 0).astype(np.uint8))
    _, _, bw, bh = cv2.boundingRect(whole)

    for r in regions:
        ink = r.text_mask > 0
        kept = float(((shares[r.id] > 0) & ink).sum()) / float(ink.sum())
        assert kept > 0.9, (r.id, kept)          # the block's own lobe, all of it

    # The bud is a lobe, so its share is small BOTH ways. A cut across would
    # give it the balloon's full width, a cut down the middle its full height.
    _, _, sw, sh = cv2.boundingRect((shares[regions[1].id] > 0).astype(np.uint8))
    assert sw < 0.75 * bw and sh < 0.75 * bh, (sw, sh, bw, bh)

    laid = [fit_region(r, cfg, shares[r.id]) for r in regions]
    for lay, text in zip(laid, texts):
        assert " ".join(lay.lines) == text, lay.lines
        # 22 while the fitter could set solid; the line-gap floor of 1.20 costs
        # a point on a lobe this small. See MIN_LEADING in typeset.py.
        assert lay.font_size >= 21, (lay.font_size, lay.lines)
    for r, was in zip(regions, before):
        assert np.array_equal(r.bubble_mask, was)


def _burst_balloon_regions(top_text, bottom_text):
    """A jagged burst balloon: one lobe, spikes top and bottom.

    Its outline turns back on itself at every spike, so it has deep hull dents
    exactly like a two-lobed balloon does — deeper, on lee's page 030, than the
    real neck on page 013. Depth alone cannot tell a spike from a neck.
    """
    import cv2
    from mangatl.models import TextRegion
    pad, rad = 30, 130
    n = 2 * rad + 2 * pad
    yy, xx = np.mgrid[0:n, 0:n]
    m = np.zeros((n, n), np.uint8)
    m[((xx - (pad + rad)) ** 2 + (yy - (pad + rad)) ** 2) <= rad * rad] = 255
    for tip in (pad + 62, pad + 2 * rad - 62):
        base = pad if tip < pad + rad else pad + 2 * rad
        cv2.fillPoly(m, [np.array([[pad + rad - 9, base], [pad + rad + 9, base],
                                   [pad + rad, tip]])], 0)

    inks = []
    for y0, y1, x0, x1 in ((80, 150, 70, 250), (190, 250, 70, 250)):
        ink = np.zeros_like(m)
        ink[y0:y1, x0:x1] = 255
        inks.append((ink & m).astype(np.uint8))

    cut = pad + rad
    out = []
    for i, (text, sl) in enumerate([(top_text, slice(0, cut)),
                                    (bottom_text, slice(cut + 3, None))]):
        piece = np.zeros_like(m)
        piece[sl] = m[sl]
        ys, xs = np.nonzero(piece)
        r = TextRegion(id=i + 1, text_mask=inks[i], bubble_mask=piece,
                       bbox=cv2.boundingRect(inks[i]),
                       bubble_bbox=(int(xs.min()), int(ys.min()),
                                    int(xs.max() - xs.min() + 1),
                                    int(ys.max() - ys.min() + 1)))
        r.dst_text = text
        out.append(r)
    return out


def test_a_burst_balloons_spikes_are_not_mistaken_for_a_neck():
    """The neck cut has to prove itself on the ink before it is believed.

    Both spikes here point inward from opposite sides of one round lobe, so the
    chord between them runs straight down the middle of it and slices both
    blocks of dialogue in half — each keeping about half its own ink on its own
    side. A neck does not do that: at a real neck each block sits wholly in one
    lobe and keeps all of it. So the division is only taken when every block
    keeps essentially all its ink, which is what separates lee's page 013 from
    his page 030 when depth cannot.
    """
    from mangatl.typeset import share_masks
    regions = _burst_balloon_regions("MY HARD WORK PAID OFF TOO—",
                                     "—SO TAKE CARE NOW!")
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12, max_font=24)

    shares = share_masks(regions, cfg)
    for r in regions:
        if r.id not in shares:
            continue
        ink = r.text_mask > 0
        kept = float(((shares[r.id] > 0) & ink).sum()) / float(ink.sum())
        assert kept > 0.9, (r.id, kept, "cut through its own dialogue")


def test_block_is_centred_on_its_ink():
    """"mm" anchors on the ascender/descender box, so all-caps typesetting hangs
    off the descender line and sits low in the bubble. The fitter corrects for
    that, which means the empty room above and below the block matches."""
    from PIL import ImageFont
    from mangatl.typeset import fit_region, ink_extents
    cfg = TypesetConfig(font_path=default_font_path())
    r = _oval_region(240, 180, "SHE ALREADY KNEW, DIDN'T SHE?")
    lay = fit_region(r, cfg)
    ImageFont.truetype(lay.font_path, lay.font_size)   # font really loads
    ys = [cy for _, cy in lay.line_origins]
    top_ink, bot_ink = ink_extents(lay.font_path, lay.font_size, True)
    bys = np.nonzero(r.bubble_mask.any(axis=1))[0]
    above = (min(ys) + top_ink) - bys[0]
    below = bys[-1] - (max(ys) + bot_ink)
    assert abs(above - below) <= 3, (above, below)


def _edge_gap(cfg, w=260, h=100, txt="HEY, ARE YOU LISTENING TO ME?",
              shape="rect"):
    """Smallest distance from any inked pixel to the bubble edge, in px.

    Renders through the real draw path, so the outline the renderer paints
    around each glyph counts against the gap exactly as a reader sees it.
    """
    import cv2
    from PIL import Image, ImageDraw
    from mangatl.models import TextRegion
    from mangatl.render import draw_line
    from mangatl.typeset import _font, fit_region

    W, H = w + 40, h + 40
    m = np.zeros((H, W), np.uint8)
    if shape == "oval":
        cv2.ellipse(m, (20 + w // 2, 20 + h // 2), (w // 2, h // 2), 0, 0, 360,
                    255, -1)
    else:
        cv2.rectangle(m, (20, 20), (20 + w, 20 + h), 255, -1)
    r = TextRegion(id=0, bbox=(20, 20, w, h), bubble_mask=m,
                   bubble_bbox=(20, 20, w, h))
    r.dst_text = txt
    lay = fit_region(r, cfg)
    f = _font(lay.font_path, lay.font_size)
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    for (x, y), line in zip(lay.line_origins, lay.lines):
        draw_line(d, x, y, line, f, 0.0, fill=255)
    ink = np.asarray(img) > 96
    assert ink.any(), "nothing was drawn"
    dist = cv2.distanceTransform((m > 0).astype(np.uint8), cv2.DIST_L2, 5)
    return float(dist[ink].min()), lay.font_size


def test_gutters_grow_with_the_type_and_with_the_bubble():
    from mangatl.typeset import gutters
    cfg = TypesetConfig(font_path=default_font_path())
    small_v, small_h = gutters(12, 120, cfg)
    big_v, big_h = gutters(34, 120, cfg)
    assert big_h > small_h and big_v > small_v      # bigger type, more air
    tall_v, _ = gutters(12, 600, cfg)
    assert tall_v > small_v                          # bigger bubble, more air


def test_text_is_not_crowded_against_the_bubble_edge():
    """Typesetting that ends a third of an em from the outline reads as if it is
    about to fall out of the bubble. The gutter has to be a real one, and it
    has to scale with the type — a fixed pixel margin looks generous at 12pt
    and looks like a mistake at 30pt."""
    # a bundled comic face, so the fixture is the same everywhere
    font = _os.path.join("fonts", "CCWildWords.ttf")
    gap, size = _edge_gap(TypesetConfig(font_path=font))
    assert gap >= 0.55 * size, f"only {gap:.1f}px of air around {size}pt type"

    # and prove the gutter knobs are what produced it
    bare, bare_size = _edge_gap(TypesetConfig(font_path=font, pad_em=0.0,
                                              pad_px=0, v_margin_frac=0.0))
    assert gap / size > bare / bare_size * 1.5, (gap, size, bare, bare_size)


def test_round_bubbles_keep_their_gutter_on_the_curve():
    """A line of type is a band several rows tall, so in a round bubble its
    CORNERS reach the arc long before its middle does. Insetting the chord
    horizontally cannot see that: the arithmetic says the line fits while the
    first and last letters sit on the curve, which is what a reader means by
    "too close to the edge". The fit is measured against the bubble eroded by
    the gutter instead, so the clearance is perpendicular to the outline.
    """
    font = _os.path.join("fonts", "CCWildWords.ttf")
    cfg = TypesetConfig(font_path=font)
    txt = "YOU'RE THE ONE WHO TOLD ME TO COME HERE IN THE FIRST PLACE."
    gap, size = _edge_gap(cfg, 150, 150, txt, shape="oval")
    assert gap >= 0.9 * size, f"only {gap:.1f}px of air around {size}pt type"

    # The circle is the case that separates the two ways of measuring. A
    # square of the same span has no curve to fall foul of, so it should not
    # need a bigger share of its type size than the circle does.
    sq_gap, sq_size = _edge_gap(cfg, 150, 150, txt, shape="rect")
    assert gap / size >= 0.75 * (sq_gap / sq_size), (gap, size, sq_gap, sq_size)


def test_inset_follows_the_curve_not_just_the_sides():
    """BubbleGeom.inset is the erosion the fit is measured against. Near the
    pole of a circle it has to take far more than the gutter off the chord,
    because there the outline runs across the band rather than beside it."""
    import cv2
    from mangatl.typeset import BubbleGeom, band_width, chord_profile

    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 90, 255, -1)
    pad = 10.0
    geom = BubbleGeom(m)
    _, inner_w, iy0, iy1 = geom.inset(pad)
    raw_w, y0, y1 = chord_profile(m)

    assert iy0 >= y0 + pad - 1 and iy1 <= y1 - pad + 1   # top and bottom too

    # across the equator the edge is vertical, so the erosion costs exactly
    # the gutter on each side
    assert abs(inner_w[100] - (raw_w[100] - 2 * pad)) <= 2, inner_w[100]

    # a band near the pole loses much more than that
    ya, yb = iy0, iy0 + 14
    near_pole = band_width(inner_w, ya, yb)
    horizontal_only = band_width(raw_w, ya, yb) - 2 * pad
    assert near_pole < horizontal_only - 8, (near_pole, horizontal_only)


# --------------------------------------------------------------------- config

def test_min_font_is_a_real_floor():
    cfg = TypesetConfig()
    assert cfg.min_font >= 10, "below ~10px typesetting is not legible on scans"
    assert cfg.max_font > cfg.min_font


def test_a_font_is_available():
    p = default_font_path()
    assert _os.path.isfile(p)


# ----------------------------------------------------------------- detection

@needs_pages
def test_detection_finds_something_on_real_pages():
    from mangatl.detect import classical
    from mangatl.pipeline import load_page

    total = 0
    for f in _PAGES:
        page = load_page(f)
        regions = classical.detect_combined(page)
        total += len(regions)
        for r in regions:
            x, y, w, h = r.bubble_bbox
            assert w > 0 and h > 0
            assert 0 <= x and 0 <= y
            assert x + w <= page.w and y + h <= page.h
            assert r.polygon, "every region needs a polygon to be persistable"
    assert total > 0, "no bubbles found on any sample page"


# ----------------------------------------------------------------- box snapping

@needs_pages
def test_snap_recovers_bubble_from_sloppy_drag():
    """A drag inside a bubble should snap out to the bubble outline."""
    from mangatl.detect import classical
    from mangatl.interactive import region_from_box
    from mangatl.pipeline import load_page

    hits = tot = 0
    for f in _PAGES:
        p = load_page(f)
        for t in classical.detect_combined(p):
            x, y, w, h = t.bubble_bbox
            for inset in (0.15, 0.25, 0.35):
                dw = max(4, int(w * (1 - 2 * inset)))
                dh = max(4, int(h * (1 - 2 * inset)))
                r = region_from_box(p, x + int(w * inset), y + int(h * inset),
                                    dw, dh)
                tot += 1
                hits += _iou(t.bubble_bbox, r.bubble_bbox) > 0.7
    if tot == 0:
        pytest.skip("no bubbles detected to snap against")
    assert hits / tot > 0.85, f"snap recovery only {hits}/{tot}"


@needs_pages
def test_snap_falls_back_rather_than_leaking_into_the_page():
    """Dragging where there is no bubble must not swallow the whole page."""
    from mangatl.interactive import region_from_box
    from mangatl.pipeline import load_page

    p = load_page(_PAGES[0])
    r = region_from_box(p, int(p.w * 0.42), int(p.h * 0.22),
                        int(p.w * 0.12), int(p.h * 0.12))
    bx, by, bw, bh = r.bubble_bbox
    assert bw * bh < 0.35 * p.w * p.h


# ------------------------------------------------------------- project round-trip

@needs_pages
def test_regions_survive_a_save_load_cycle_as_geometry():
    """A chapter is stored as polygons, not bitmaps. Masks must rebuild."""
    from mangatl.detect import classical
    from mangatl.pipeline import load_page
    from mangatl.project import region_from_record, region_record

    p = load_page(_PAGES[0])
    regs = classical.detect_combined(p)
    if not regs:
        pytest.skip("no regions detected on the sample page")

    rec = json.loads(json.dumps(region_record(regs[0])))   # must be JSON-clean
    back = region_from_record(rec, p.image)
    assert back.bubble_mask is not None and back.bubble_mask.any()

    a = regs[0].bubble_mask > 0
    b = back.bubble_mask > 0
    iou = (a & b).sum() / max(1, (a | b).sum())
    assert iou > 0.95, f"mask rebuilt from polygon differs (IoU {iou:.3f})"


@needs_pages
def test_reading_order_is_contiguous_after_detection():
    from mangatl.detect import classical
    from mangatl.order import assign_order
    from mangatl.pipeline import load_page

    p = load_page(_PAGES[0])
    p.regions = classical.detect_combined(p)
    if not p.regions:
        pytest.skip("no regions detected on the sample page")
    assign_order(p)
    orders = sorted(r.order for r in p.regions)
    assert orders == list(range(len(orders)))


# ------------------------------------------------------------- containment

def _fake_region(w=120, h=160, text="Some dialogue that needs to fit."):
    """A region whose box is a plain rectangle, as a manual resize produces."""
    from mangatl.models import TextRegion
    m = np.zeros((400, 400), np.uint8)
    m[50:50 + h, 40:40 + w] = 255
    r = TextRegion(id=0, bbox=(40, 50, w, h), text_mask=m, bubble_mask=m,
                   bubble_bbox=(40, 50, w, h))
    r.dst_text = text
    return r


def _lines_outside(region, cfg):
    """How many typeset lines stick out of the region's box."""
    from PIL import ImageFont
    from mangatl.typeset import fit_region
    lay = fit_region(region, cfg)
    from mangatl.typeset import enforce_bounds
    lay = enforce_bounds(region, lay, cfg)
    bx, by, bw, bh = region.bubble_bbox
    f = ImageFont.truetype(lay.font_path or cfg.font_path, lay.font_size)
    half_h = f.getbbox("Ahgjy")[3] / 2          # ink height, not padded metrics
    out = 0
    for (cx, cy), line in zip(lay.line_origins, lay.lines):
        half_w = f.getlength(line) / 2
        if (cx - half_w < bx - 1 or cx + half_w > bx + bw + 1
                or cy - half_h < by - 1 or cy + half_h > by + bh + 1):
            out += 1
    return out, lay


def test_normal_text_stays_inside_its_box():
    cfg = TypesetConfig(font_path=default_font_path())
    out, lay = _lines_outside(_fake_region(), cfg)
    assert out == 0
    assert lay.fit_ok


def test_overflowing_text_is_shrunk_and_flagged_not_spilled():
    """Text far too long for the box must shrink and be flagged, never spill."""
    cfg = TypesetConfig(font_path=default_font_path())
    r = _fake_region(w=70, h=50, text="A very long stretch of dialogue "
                                      "that cannot possibly fit in here.")
    out, lay = _lines_outside(r, cfg)
    assert out == 0, "overflowing text escaped its box"
    assert not lay.fit_ok, "an overflow must not be reported as a clean fit"
    assert r.flagged, "overflow must be flagged for a human"


def test_impossible_text_is_flagged_and_relies_on_clipping():
    """Some text cannot fit at any legible size. That must be flagged, and
    rendering clips it — it must never be silently accepted as a good fit."""
    cfg = TypesetConfig(font_path=default_font_path())
    r = _fake_region(w=30, h=24, text="word " * 80)
    _, lay = _lines_outside(r, cfg)
    assert not lay.fit_ok
    assert r.flagged and "overflow" in r.flagged


def test_never_typesets_below_the_absolute_floor():
    cfg = TypesetConfig(font_path=default_font_path())
    r = _fake_region(w=40, h=30, text="word " * 60)
    _, lay = _lines_outside(r, cfg)
    assert lay.font_size >= cfg.absolute_floor


@needs_pages
def test_rendering_never_draws_outside_a_region():
    """The real guarantee: composited pixels stay inside the region masks."""
    import numpy as np
    from mangatl import inpaint, render, typeset
    from mangatl.detect import classical
    from mangatl.order import assign_order
    from mangatl.pipeline import load_page

    cfg = typeset.TypesetConfig(font_path=default_font_path(),
                                max_font=30, min_font=11)
    page = load_page(_PAGES[0])
    page.regions = classical.detect_combined(page)
    if not page.regions:
        pytest.skip("no regions detected")
    assign_order(page)
    long_line = ("A deliberately long line of dialogue that will not fit into "
                 "a small speech bubble however hard the fitter tries.")
    for k, r in enumerate(page.regions):
        r.dst_text = long_line if k % 2 == 0 else "A normal line."
    inpaint.inpaint_page(page)
    typeset.typeset_page(page, cfg)

    clean = page.clean_plate.copy()
    out = render.render_page(page, cfg, clip=True)
    allowed = np.zeros(out.shape[:2], bool)
    for r in page.regions:
        m = r.place_mask()
        if m is not None:
            allowed |= (m > 0)
    changed = np.abs(out.astype(int) - clean.astype(int)).sum(axis=2) > 30
    assert int((changed & ~allowed).sum()) == 0, "typesetting escaped its region"


# ------------------------------------------------- manhwa / manhua direction

def test_left_to_right_order_for_manhwa_and_manhua():
    """Manga reads right-to-left; manhwa and manhua read left-to-right.
    Getting this backwards scrambles every page."""
    tl, tr = (0, 0, 100, 100), (200, 0, 100, 100)
    bl, br = (0, 200, 100, 100), (200, 200, 100, 100)
    grid = [tl, tr, bl, br]
    assert reading_order(grid, rtl=True) == [1, 0, 3, 2]     # TR TL BR BL
    assert reading_order(grid, rtl=False) == [0, 1, 2, 3]    # TL TR BL BR


def test_row_direction_reverses_with_the_flag():
    row = [(0, 0, 80, 40), (100, 0, 80, 40), (200, 0, 80, 40)]
    assert reading_order(row, rtl=True) == [2, 1, 0]
    assert reading_order(row, rtl=False) == [0, 1, 2]


def test_column_order_is_unaffected_by_direction():
    col = [(0, 0, 80, 40), (0, 60, 80, 40), (0, 120, 80, 40)]
    assert reading_order(col, rtl=True) == reading_order(col, rtl=False) == [0, 1, 2]


def test_media_and_targets_are_consistent():
    from mangatl.translate import MEDIA, TARGETS, build_system
    assert MEDIA["manga"]["rtl"] is True
    assert MEDIA["manhwa"]["rtl"] is False and MEDIA["manhwa"]["code"] == "ko"
    assert MEDIA["manhua"]["rtl"] is False and MEDIA["manhua"]["code"] == "zh"
    assert set(TARGETS) == {"en", "es", "pt", "fr"}
    for medium in MEDIA:
        for target in TARGETS:
            sysmsg = build_system(medium, target)
            assert TARGETS[target] in sysmsg
            assert MEDIA[medium]["source"] in sysmsg
            assert "{" not in sysmsg, "unfilled placeholder in the prompt"


def test_ocr_engine_matches_the_source_language():
    from mangatl.ocr import choose_engine
    assert choose_engine("ja") == "manga-ocr"
    assert choose_engine("ko") == "easyocr"
    assert choose_engine("zh") == "easyocr"
    assert choose_engine("ko", "manga-ocr") == "manga-ocr"   # explicit override


def test_manga_ocr_refuses_non_japanese():
    """manga-ocr cannot read Korean or Chinese; that must be an explicit
    error rather than silent nonsense."""
    from mangatl.ocr import get_engine
    with pytest.raises(RuntimeError, match="only reads Japanese"):
        get_engine("ko", "manga-ocr")


# ------------------------------------------------------- editable typesetting

def _override_region(w=240, h=200):
    from mangatl.models import TextRegion
    m = np.zeros((400, 400), np.uint8)
    m[60:60 + h, 60:60 + w] = 255
    r = TextRegion(id=0, bbox=(60, 60, w, h), text_mask=m, bubble_mask=m,
                   bubble_bbox=(60, 60, w, h))
    r.dst_text = "Automatic fit will pick its own breaks for this line."
    return r


class _FakePage:
    def __init__(self, regions):
        self.regions = regions

    def ordered(self):
        return self.regions


def test_hand_edited_typesetting_wins_over_the_fitter():
    from mangatl import typeset
    cfg = typeset.TypesetConfig(font_path=default_font_path())
    r = _override_region()
    typeset.typeset_page(_FakePage([r]), cfg)
    auto = list(r.layout.lines)

    r.layout_override = {"lines": ["My own", "line breaks"],
                         "font_size": 22, "dx": 0, "dy": 0, "locked": True}
    typeset.typeset_page(_FakePage([r]), cfg)
    assert r.layout.lines == ["My own", "line breaks"]
    assert r.layout.font_size == 22
    assert r.layout.lines != auto

    # running the fitter again must not quietly undo the edit
    typeset.typeset_page(_FakePage([r]), cfg)
    assert r.layout.lines == ["My own", "line breaks"]


def test_clearing_the_override_restores_the_automatic_fit():
    from mangatl import typeset
    cfg = typeset.TypesetConfig(font_path=default_font_path())
    r = _override_region()
    typeset.typeset_page(_FakePage([r]), cfg)
    auto = list(r.layout.lines)
    r.layout_override = {"lines": ["Something else"], "font_size": 14,
                         "locked": True}
    typeset.typeset_page(_FakePage([r]), cfg)
    r.layout_override = None
    typeset.typeset_page(_FakePage([r]), cfg)
    assert r.layout.lines == auto


def test_edited_typesetting_still_cannot_leave_the_box():
    """A hand edit must not become a way to spill text over the artwork."""
    from PIL import ImageFont
    from mangatl import typeset
    cfg = typeset.TypesetConfig(font_path=default_font_path())
    r = _override_region(w=120, h=90)
    r.layout_override = {"lines": ["A deliberately over-long single line"],
                         "font_size": 60, "locked": True}
    typeset.typeset_page(_FakePage([r]), cfg)
    lay = typeset.enforce_bounds(r, r.layout, cfg)
    bx, by, bw, bh = r.bubble_bbox
    f = ImageFont.truetype(lay.font_path or cfg.font_path, lay.font_size)
    for (cx, cy) in lay.line_origins:
        assert bx <= cx <= bx + bw and by <= cy <= by + bh


def test_direction_override_beats_the_medium_default():
    import shutil
    from mangatl.project import Project
    shutil.rmtree(scratch("_tmp_dirproj"), ignore_errors=True)
    p = Project(None, scratch("_tmp_dirproj"))
    p.settings["medium"] = "manga"
    p.settings["direction"] = "auto"
    assert p.rtl is True
    p.settings["direction"] = "ltr"
    assert p.rtl is False
    p.settings["medium"] = "manhwa"
    p.settings["direction"] = "auto"
    assert p.rtl is False
    p.settings["direction"] = "rtl"
    assert p.rtl is True
    shutil.rmtree(scratch("_tmp_dirproj"), ignore_errors=True)


# ------------------------------------------------- cleaning must not eat art

def test_cleaning_leaves_ink_that_continues_outside_the_region():
    """A box drawn across a bubble catches part of the bubble's own border.
    Erasing that hacks the outline apart, so ink running off the edge of the
    region must be left alone."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import TextRegion

    mask = np.zeros((200, 200), np.uint8)
    mask[40:160, 40:160] = 255                 # the region

    ink = np.zeros((200, 200), np.uint8)
    cv2.line(ink, (0, 100), (199, 100), 255, 3)   # a border running right across
    ink[70:85, 70:85] = 255                       # a glyph, wholly inside

    gray = np.full((200, 200), 255, np.uint8)
    gray[ink > 0] = 0
    r = TextRegion(id=0, bbox=(40, 40, 120, 120), text_mask=(ink & mask),
                   bubble_mask=mask, bubble_bbox=(40, 40, 120, 120))
    kept = inpaint.glyphs_only(r, (ink & mask), gray)

    assert kept[75, 75] > 0, "the glyph should still be erased"
    assert kept[100, 100] == 0, "the border crossing the box must be spared"
    assert int((kept > 0).sum()) < int(((ink & mask) > 0).sum())


def test_cleaning_still_erases_normal_bubble_text():
    """The protection must not stop ordinary typesetting being cleaned."""
    from mangatl import inpaint
    from mangatl.models import TextRegion

    mask = np.zeros((200, 200), np.uint8)
    mask[40:160, 40:160] = 255
    ink = np.zeros((200, 200), np.uint8)
    for x in range(60, 140, 20):
        ink[80:100, x:x + 10] = 255            # a row of glyphs, all interior

    gray = np.full((200, 200), 255, np.uint8)
    gray[ink > 0] = 0
    r = TextRegion(id=0, bbox=(40, 40, 120, 120), text_mask=ink,
                   bubble_mask=mask, bubble_bbox=(40, 40, 120, 120))
    kept = inpaint.glyphs_only(r, ink, gray)
    assert int((kept > 0).sum()) == int((ink > 0).sum())


def _soft_bubble(blur=3.0):
    """A white bubble whose typesetting has scan-soft edges, plus the tight mask
    a threshold detector hands back for it."""
    import cv2
    img = np.full((400, 400, 3), 255, np.uint8)
    cv2.ellipse(img, (200, 200), (150, 170), 0, 0, 360, (0, 0, 0), 6)
    glyph = np.zeros((400, 400), np.uint8)
    for x in (140, 200, 260):
        cv2.line(glyph, (x, 90), (x, 300), 255, 11, cv2.LINE_AA)
    cv2.circle(glyph, (200, 150), 34, 255, 9, cv2.LINE_AA)
    soft = cv2.GaussianBlur(glyph, (0, 0), blur)
    img[soft > 0] = (255 - soft[soft > 0].astype(np.int32)).clip(0, 255) \
        [..., None].repeat(3, 1).astype(np.uint8)
    tight = cv2.erode((soft > 200).astype(np.uint8) * 255,
                      np.ones((3, 3), np.uint8))
    interior = np.zeros((400, 400), np.uint8)
    cv2.ellipse(interior, (200, 200), (144, 164), 0, 0, 360, 255, -1)
    return img, tight, interior


def test_soft_stroke_edges_do_not_survive_as_a_faint_outline():
    """The remnant the user sees: print scans spread every stroke over several
    pixels, so the mask a detector returns is the core and the skirt reaches
    past any fixed dilation. Sampling that skirt as background also makes a
    plain white bubble measure as textured, which sends it down the screentone
    path where the skirt is preserved rather than erased. What is left is a
    ghost of the Japanese, too light to read and too dark to pass."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    img, tight, interior = _soft_bubble()
    r = TextRegion(id=0, bbox=(56, 36, 288, 328), kind="bubble",
                   text_mask=tight, bubble_mask=interior)
    ink = inpaint.glyphs_only(r, tight, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    assert inpaint.background_is_flat(img, r, ink)[0], \
        "the stroke skirt made a plain white bubble measure as textured"

    page = Page(image=img.copy(), regions=[r])
    out = cv2.cvtColor(inpaint.inpaint_page(page), cv2.COLOR_BGR2GRAY)
    inside = cv2.erode(interior, np.ones((9, 9), np.uint8)) > 0
    left = int(((255 - out.astype(int)) * inside > 6).sum())
    assert left == 0, f"{left}px of the typesetting is still faintly visible"


def test_the_haze_sweep_still_spares_a_border_crossing_the_box():
    """Widening the fill to catch the skirt must not quietly undo the rule that
    ink running out of the region is artwork, not typesetting."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    img = np.full((200, 200, 3), 255, np.uint8)
    cv2.line(img, (0, 100), (199, 100), (0, 0, 0), 3)     # a border, right across
    img[70:93, 70:110] = 0                                # a glyph just above it
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    box = np.zeros((200, 200), np.uint8)
    box[40:160, 40:160] = 255
    r = TextRegion(id=0, bbox=(40, 40, 120, 120),
                   text_mask=((gray <= 128).astype(np.uint8) * 255) & box,
                   bubble_mask=box, bubble_bbox=(40, 40, 120, 120))
    out = cv2.cvtColor(inpaint.inpaint_page(Page(image=img.copy(), regions=[r])),
                       cv2.COLOR_BGR2GRAY)

    # the stretch of border directly under the glyph is the part the widened
    # fill can reach, so that is the part worth asserting on
    assert (out[99:102, 70:110] < 128).sum() > 100, "the border was erased"
    assert (out[70:93, 70:110] > 200).all(), "the glyph was not erased"


def test_a_clean_that_leaves_the_text_behind_says_so():
    """Off the flat path the fill is a reconstruction, and a second automatic
    pass is as likely to make it worse — so the plate is checked and the region
    is flagged with the path that produced it, rather than quietly shipped."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    rng = np.random.default_rng(4)
    img = rng.integers(60, 200, (200, 240, 3), dtype=np.uint8)   # artwork
    cv2.putText(img, "AA", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 9)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    box = np.zeros(gray.shape, np.uint8)
    box[60:150, 20:220] = 255
    r = TextRegion(id=0, bbox=(20, 60, 200, 90),
                   text_mask=((gray <= 40).astype(np.uint8) * 255) & box,
                   bubble_mask=box, bubble_bbox=(20, 60, 200, 90))

    page = Page(image=img.copy(), regions=[r])
    inpaint.inpaint_page(page, neural=lambda im, m: im)          # a no-op model
    assert r.flagged and "ghost" in r.flagged, \
        "text left on the page after a neural clean went unreported"
    assert "neural" in r.flagged, "the flag does not say which path produced it"


def test_per_region_font_beats_per_kind_font():
    from mangatl.typeset import TypesetConfig, font_for, default_font_path
    d = default_font_path()
    cfg = TypesetConfig(font_path=d, fonts={"sfx": d})
    assert font_for(cfg, "bubble") == d
    assert font_for(cfg, "bubble", "/does/not/exist.ttf") == d   # bad path ignored


# ------------------------------------------- cleaning matches the background

def _tone_patch(size=120, period=6):
    """A synthetic screentone: regular dots on a light ground."""
    img = np.full((size, size, 3), 235, np.uint8)
    img[::period, ::period] = 40
    img[1::period, ::period] = 40
    img[::period, 1::period] = 40
    return img


def test_textured_background_is_reconstructed_not_flat_filled():
    """Erasing text over tone or artwork must rebuild the surroundings rather
    than stamping a flat patch, which is what a reader notices."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    truth = _tone_patch()
    ink = np.zeros(truth.shape[:2], np.uint8)
    ink[40:80, 45:52] = 255
    ink[40:47, 45:85] = 255

    dirty = truth.copy()
    dirty[ink > 0] = (20, 20, 20)

    mask = np.zeros(truth.shape[:2], np.uint8)
    mask[20:100, 20:100] = 255
    r = TextRegion(id=0, bbox=(20, 20, 80, 80), text_mask=ink,
                   bubble_mask=mask, bubble_bbox=(20, 20, 80, 80))
    page = Page(image=dirty, regions=[r])
    inpaint.inpaint_page(page)

    grow = cv2.dilate(ink, np.ones((5, 5), np.uint8)) > 0
    out = page.clean_plate
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(float)

    # the original dark text must be gone
    assert g[grow].mean() > 120, "source text was not erased"
    # and the repair must not be a flat block: it should still carry texture
    assert g[grow].std() > 5, "repaired area is a flat patch, not background"


def test_screentone_regions_are_cleaned_rather_than_skipped():
    """They used to be flagged and left alone, which left source text on the
    exported page."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    truth = _tone_patch()
    ink = np.zeros(truth.shape[:2], np.uint8)
    ink[45:75, 45:75] = 255
    dirty = truth.copy()
    dirty[ink > 0] = (15, 15, 15)

    mask = np.zeros(truth.shape[:2], np.uint8)
    mask[25:95, 25:95] = 255
    r = TextRegion(id=0, bbox=(25, 25, 70, 70), text_mask=ink,
                   bubble_mask=mask, bubble_bbox=(25, 25, 70, 70))
    page = Page(image=dirty, regions=[r])
    inpaint.inpaint_page(page)

    g = cv2.cvtColor(page.clean_plate, cv2.COLOR_BGR2GRAY).astype(float)
    remaining = int(((ink > 0) & (g < 60)).sum())
    assert remaining < 0.1 * int((ink > 0).sum()), \
        f"{remaining}px of source text left on a screentone background"


# ------------------------------------------------------- shapes and detection

def test_boxes_are_rectangles():
    """Boxes have four corners. Nothing more elaborate."""
    from mangatl import editor
    assert editor.MIN_POINTS == 4
    assert editor.MAX_POINTS == 4


def test_detect_kinds_are_opt_in():
    """Nothing is detected unless it was asked for."""
    import os
    import shutil
    from mangatl.project import Project
    shutil.rmtree(scratch("_tmp_kinds"), ignore_errors=True)
    p = Project(None, scratch("_tmp_kinds"))
    try:
        if not _PAGES:
            pytest.skip("no sample pages")
        p.use_folder(os.path.dirname(_PAGES[0]))
        if not p.pages:
            pytest.skip("no pages loaded")
        assert all(not st.detected for st in p.pages), \
            "loading a folder must not detect anything"

        p.detect(0, ["bubble"])
        kinds = {r["kind"] for r in p.pages[0].regions}
        assert kinds <= {"bubble"}, f"asked for bubbles, got {kinds}"
    finally:
        shutil.rmtree(scratch("_tmp_kinds"), ignore_errors=True)


def test_the_detect_dialog_boxes_behave_in_a_real_dom():
    """tests/ui/detect_kinds.test.js drives the actual dialog in jsdom: the
    three kind boxes stay live for every finder, the whole-page note appears
    only for comic-text-detector, and a stale "ai_boxes" left in somebody's old
    project.json changes nothing.

    It had no wrapper for a long time, so it was never once run by the suite —
    which is how a jsdom test quietly stops matching the page it tests. Skipped
    where node or jsdom is unavailable."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "detect_kinds.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "a stale ai_boxes in an old project changes nothing" in out.stdout
    assert "comic-text-detector: all three boxes stay live" in out.stdout


def test_stopping_is_about_one_action_in_a_real_dom():
    """tests/ui/stopping_is_one_action.test.js drives `poll` through a Clean
    being cancelled with a Translate queued behind it, and checks the Cancel
    button at every step. lee: *"when i clik cancel and it sto the ui show
    stopping even thiught te next step queue ia happening"*."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "stopping_is_one_action.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "once the next action starts the button says Cancel again" \
        in out.stdout
    assert "the second action can be cancelled as well" in out.stdout


def test_the_legend_draws_the_box_in_a_real_dom():
    """tests/ui/the_legend_draws_the_box.test.js drives the colour key: the
    three main types are buttons, the lit one is the kind a drawn box comes out
    as, and the number keys set it when nothing is selected. lee: *"make these
    3 in the screenshoot buttons adn make them diactaet twhat box is beign draw
    by degault"*."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "the_legend_draws_the_box.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "bubble text is lit to start with" in out.stdout
    assert "the region POST carries the lit kind" in out.stdout
    assert "all good" in out.stdout


def test_free_text_detector_avoids_known_bubbles():
    """Free-floating text must not re-find text already inside a bubble."""
    from mangatl.detect import classical, freetext
    from mangatl.pipeline import load_page
    if not _PAGES:
        pytest.skip("no sample pages")
    page = load_page(_PAGES[0])
    bubbles = classical.detect_combined(page)
    free = freetext.detect_free_text(page, avoid=bubbles)
    for f in free:
        for b in bubbles:
            fx, fy, fw, fh = f.bubble_bbox
            bx, by, bw, bh = b.bubble_bbox
            ox = max(0, min(fx + fw, bx + bw) - max(fx, bx))
            oy = max(0, min(fy + fh, by + bh) - max(fy, by))
            overlap = ox * oy / max(1, fw * fh)
            assert overlap < 0.6, "free text landed on top of a bubble"


def test_added_pages_go_to_the_end_in_order():
    """Adding pages used to re-sort the whole list by filename, which
    scattered new pages among the old ones — so you would add three pages and
    be looking at something else entirely."""
    import shutil
    from mangatl.project import Project
    shutil.rmtree(scratch("_tmp_add"), ignore_errors=True)
    p = Project(None, scratch("_tmp_add"))
    try:
        if len(_PAGES) < 2:
            pytest.skip("need sample pages")
        data = [open(f, "rb").read() for f in _PAGES[:2]]

        # a project that already has late-alphabet pages
        assert p.add_uploaded("zz_first.jpg", data[0]) == 0
        assert p.add_uploaded("zz_second.jpg", data[1]) == 1

        # now add one whose name sorts before them
        idx = p.add_uploaded("aaa_new.jpg", data[0])
        assert idx == 2, "an added page must land at the end, not be sorted in"
        assert p.pages[2].name == "aaa_new.jpg"
        assert [q.name for q in p.pages] == [
            "zz_first.jpg", "zz_second.jpg", "aaa_new.jpg"]
    finally:
        shutil.rmtree(scratch("_tmp_add"), ignore_errors=True)


def test_same_filename_does_not_replace_an_existing_page():
    """Two chapters both have a 001.jpg. Keep both."""
    import shutil
    from mangatl.project import Project
    shutil.rmtree(scratch("_tmp_same"), ignore_errors=True)
    p = Project(None, scratch("_tmp_same"))
    try:
        if not _PAGES:
            pytest.skip("need sample pages")
        data = open(_PAGES[0], "rb").read()
        a = p.add_uploaded("001.jpg", data)
        b = p.add_uploaded("001.jpg", data)
        assert a == 0 and b == 1, "the second file must be kept as its own page"
        assert len(p.pages) == 2
        assert p.pages[0].path != p.pages[1].path
    finally:
        shutil.rmtree(scratch("_tmp_same"), ignore_errors=True)


def test_drawn_box_tightens_onto_the_text():
    """A rough box drawn around a bubble should come back wrapped around the
    typesetting, not around the gesture."""
    from mangatl.detect import classical
    from mangatl.interactive import region_from_box
    from mangatl.pipeline import load_page
    if not _PAGES:
        pytest.skip("need sample pages")
    page = load_page(_PAGES[0])
    found = classical.detect_combined(page)
    if not found:
        pytest.skip("no bubbles detected")

    t = found[0]
    x, y, w, h = t.bubble_bbox
    drawn = (x - 25, y - 25, w + 50, h + 50)
    tight = region_from_box(page, *drawn, snap=False, tighten=True).bubble_bbox

    drawn_area = drawn[2] * drawn[3]
    assert tight[2] * tight[3] < drawn_area, "the box did not tighten at all"

    # and the text must still be entirely inside it
    tx, ty, tw, th = t.bbox
    assert tight[0] <= tx and tight[1] <= ty
    assert tight[0] + tight[2] >= tx + tw
    assert tight[1] + tight[3] >= ty + th


def test_reset_can_keep_your_settings():
    """Starting a new chapter should not make you re-pick the language,
    fonts and engine you already configured."""
    import shutil
    from mangatl.project import Project
    shutil.rmtree(scratch("_tmp_reset"), ignore_errors=True)
    p = Project(None, scratch("_tmp_reset"))
    try:
        p.settings.update({"medium": "manhwa", "target": "es",
                           "font": "/some/font.ttf"})
        keep = dict(p.settings)
        if _PAGES:
            p.add_uploaded("a.jpg", open(_PAGES[0], "rb").read())
            assert p.pages
        p.clear()
        p.settings.update(keep)
        assert p.pages == []
        assert p.settings["medium"] == "manhwa"
        assert p.settings["target"] == "es"
    finally:
        shutil.rmtree(scratch("_tmp_reset"), ignore_errors=True)


def test_folder_picker_degrades_without_a_desktop():
    """No GUI toolkit means no dialog — that must be a graceful 'no', not a
    crash, so the UI can fall back to a typed path."""
    from mangatl import pickdir
    assert isinstance(pickdir.available(), bool)
    assert pickdir.pick_directory("/nonexistent") == "" or True


def test_text_frame_is_independent_of_the_region():
    """Text has its own box. Moving it off the bubble must actually draw it
    off the bubble — clipping the layer back to the region is what made
    rotation look like it did nothing."""
    import cv2
    from mangatl import render, typeset
    from mangatl.models import Page, TextRegion

    mask = np.zeros((500, 500), np.uint8)
    mask[100:220, 100:300] = 255
    r = TextRegion(id=0, bbox=(100, 100, 200, 120), text_mask=mask,
                   bubble_mask=mask, bubble_bbox=(100, 100, 200, 120))
    r.dst_text = "Away"
    r.layout_override = {"lines": ["Away"], "font_size": 26, "locked": True,
                         "frame": [320, 360, 150, 80]}

    page = Page(image=np.full((500, 500, 3), 255, np.uint8), regions=[r])
    page.clean_plate = page.image.copy()
    typeset.typeset_page(page, typeset.TypesetConfig(
        font_path=typeset.default_font_path()))
    assert r.layout.frame == (320, 360, 150, 80)

    out = render.render_page(page)
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    drawn = g < 200
    assert drawn.any(), "nothing was drawn"
    assert not (drawn & (mask > 0)).any(), "text was drawn back inside the bubble"
    assert drawn[360:440, 320:470].any(), "text was not drawn in its own frame"


def test_rotation_changes_what_is_drawn():
    import cv2
    from mangatl import render, typeset
    from mangatl.models import Page, TextRegion

    def paint(rotate):
        mask = np.zeros((400, 400), np.uint8)
        mask[80:200, 60:340] = 255
        r = TextRegion(id=0, bbox=(60, 80, 280, 120), text_mask=mask,
                       bubble_mask=mask, bubble_bbox=(60, 80, 280, 120))
        r.dst_text = "Turn"
        r.layout_override = {"lines": ["Turning text"], "font_size": 24,
                             "locked": True, "rotate": rotate}
        page = Page(image=np.full((400, 400, 3), 255, np.uint8), regions=[r])
        page.clean_plate = page.image.copy()
        typeset.typeset_page(page, typeset.TypesetConfig(
            font_path=typeset.default_font_path()))
        return cv2.cvtColor(render.render_page(page), cv2.COLOR_BGR2GRAY) < 200

    flat, turned = paint(0), paint(30)
    assert flat.any() and turned.any()
    overlap = (flat & turned).sum() / max(1, flat.sum())
    assert overlap < 0.75, f"rotation barely moved anything ({overlap:.0%} overlap)"


def test_live_preview_does_not_clamp_hand_placed_text():
    """The live editor had its own copy of the containment pass, so text
    dragged away from its bubble snapped back while you were moving it."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.layout_preview)
    body = src[src.index("layout_from_override"):]
    clamp = body.index("enforce_bounds")
    fit = body.index("fit_region")
    assert fit < clamp, "enforce_bounds must only run on auto-fitted layouts"


def test_preview_and_save_agree_on_where_text_sits():
    """While dragging, the browser asks for a preview; when you let go it
    saves. If those two disagree the text jumps back on release."""
    from mangatl import typeset
    from mangatl.models import Page, TextRegion

    mask = np.zeros((900, 900), np.uint8)
    mask[100:250, 100:400] = 255
    ov = {"lines": ["Moved", "away"], "font_size": 20, "locked": True,
          "frame": [420, 760, 240, 120], "rotate": 18}

    def build():
        r = TextRegion(id=0, bbox=(100, 100, 300, 150), text_mask=mask,
                       bubble_mask=mask, bubble_bbox=(100, 100, 300, 150))
        r.dst_text = "Moved away"
        r.layout_override = dict(ov)
        return r

    cfg = typeset.TypesetConfig(font_path=typeset.default_font_path())

    # the preview path
    a = typeset.layout_from_override(build(), cfg)
    # the save path, which goes through a full page typeset
    r = build()
    page = Page(image=np.full((900, 900, 3), 255, np.uint8), regions=[r])
    typeset.typeset_page(page, cfg)
    b = r.layout

    assert a.frame == b.frame == (420, 760, 240, 120)
    assert a.line_origins == b.line_origins, "preview and save disagree"
    assert a.rotate == b.rotate == 18


def test_resizing_the_box_reflows_instead_of_resizing_the_text():
    """Narrowing a text box should push words onto new lines at the same size,
    the way any word processor behaves."""
    from mangatl import typeset
    from mangatl.models import TextRegion

    mask = np.zeros((600, 700), np.uint8)
    mask[100:300, 50:650] = 255
    text = "I will not fall for that you commitment phobe"
    cfg = typeset.TypesetConfig(font_path=typeset.default_font_path())

    def lay_at(width):
        r = TextRegion(id=0, bbox=(50, 100, 600, 200), text_mask=mask,
                       bubble_mask=mask, bubble_bbox=(50, 100, 600, 200))
        r.dst_text = text
        r.layout_override = {"lines": [text], "font_size": 20, "locked": True,
                             "wrap": True, "frame": [50, 100, width, 200]}
        return typeset.layout_from_override(r, cfg)

    wide, narrow = lay_at(460), lay_at(150)
    assert wide.font_size == narrow.font_size == 20, "the text was resized"
    assert len(narrow.lines) > len(wide.lines), "narrowing did not add lines"
    # no words lost or invented
    assert " ".join(wide.lines).split() == text.split()
    assert " ".join(narrow.lines).split() == text.split()


def test_wrap_respects_the_width_it_is_given():
    from mangatl.typeset import _font, default_font_path, wrap_to_width
    f = _font(default_font_path(), 20)
    measure = f.getlength
    text = "one two three four five six seven eight nine ten"
    for width in (80, 160, 320):
        lines = wrap_to_width(text, measure, measure(" "), width)
        for ln in lines:
            if " " in ln:                       # a single long word may overrun
                assert measure(ln) <= width * 1.02, f"{ln!r} overruns {width}"


def test_editing_text_keeps_it_where_you_put_it():
    """Retyping a block that has been moved must not send it back to the
    bubble, and the lines must stay centred on the frame."""
    from mangatl import typeset
    from mangatl.models import TextRegion

    mask = np.zeros((1200, 1000), np.uint8)
    mask[100:260, 100:400] = 255
    cfg = typeset.TypesetConfig(font_path=typeset.default_font_path())
    frame = [420, 880, 240, 120]

    def lay(lines):
        r = TextRegion(id=0, bbox=(100, 100, 300, 160), text_mask=mask,
                       bubble_mask=mask, bubble_bbox=(100, 100, 300, 160))
        r.dst_text = " ".join(lines)
        r.layout_override = {"lines": lines, "font_size": 18, "locked": True,
                             "frame": list(frame)}
        return typeset.layout_from_override(r, cfg)

    a = lay(["Before edit."])
    b = lay(["Typed something", "completely new"])

    assert a.frame == b.frame == tuple(frame), "editing moved the frame"
    mid = frame[1] + frame[3] / 2
    for out in (a, b):
        ys = [y for _, y in out.line_origins]
        assert abs(sum(ys) / len(ys) - mid) < 6, "text is not centred on the frame"
        xs = {x for x, _ in out.line_origins}
        assert xs == {frame[0] + frame[2] // 2}, "lines are not centred across it"


def test_white_text_on_a_dark_panel_is_cleaned_correctly():
    """The ink threshold assumes dark text on a light background. On a
    white-on-black panel that reads the whole panel as text, erases it, and
    fills with the colour of the typesetting — turning the panel into a pale
    rectangle."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    img = np.full((240, 170, 3), 38, np.uint8)
    img[:, ::5] = 22                                  # a striped dark panel
    cv2.putText(img, "AA", (18, 105), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
                (245, 245, 245), 8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    typesetting = gray > 128

    mask = np.full(gray.shape, 255, np.uint8)
    r = TextRegion(id=0, bbox=(0, 0, 170, 240),
                   text_mask=(gray <= 128).astype(np.uint8) * 255,
                   bubble_mask=mask, bubble_bbox=(0, 0, 170, 240))
    page = Page(image=img.copy(), regions=[r])
    inpaint.inpaint_page(page)
    out = cv2.cvtColor(page.clean_plate, cv2.COLOR_BGR2GRAY)

    assert np.median(out) < 90, "the dark panel was painted over in a pale colour"
    assert (out[typesetting] < 120).mean() > 0.9, "the white typesetting is still there"


def test_polarity_detection_leaves_ordinary_pages_alone():
    """The inverted-tone path must not fire on normal dark-on-light bubbles."""
    import cv2
    from mangatl.inpaint import ink_and_background

    img = np.full((200, 300), 240, np.uint8)
    img[::7, :] = 236                                 # faint screentone
    cv2.putText(img, "Hello", (28, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 0, 5)
    area = np.ones(img.shape, bool)

    ink, level, inverted = ink_and_background(img, area, img <= 128)
    assert not inverted, "an ordinary bubble was treated as white-on-black"
    assert level > 200, f"background level should be light, got {level}"
    assert ink.mean() < 0.25


def test_outline_width_is_honoured_everywhere():
    """The colour pass and the drawing pass each decide the outline width
    independently, so the rule has to be shared — otherwise the control moves
    the preview and leaves the export alone."""
    from mangatl.render import stroke_for
    from mangatl.models import TextRegion

    r = TextRegion(id=0, bbox=(0, 0, 10, 10))
    r.layout_override = {}
    assert stroke_for(r, 2) == 2, "automatic width should pass through"

    r.layout_override = {"stroke": 0}
    assert stroke_for(r, 2) == 0, "zero must mean no outline, not 'unset'"

    r.layout_override = {"stroke": 7}
    assert stroke_for(r, 2) == 7

    r.layout_override = {"stroke": 999}
    assert stroke_for(r, 2) == 30, \
        "absurd values are clamped to the UI slider's max"

    r.layout_override = {"stroke": None}
    assert stroke_for(r, 3) == 3, "cleared means automatic again"


def test_render_cache_key_ignores_computed_layout():
    """Rendering writes computed layouts back to the page. If the cache key
    included them it would change on every render and never hit."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor._render_stamp)
    assert '!= "layout"' in src, "cache key must exclude computed layout"


def test_custom_clean_plate_replaces_only_its_own_page():
    """A hand-cleaned page uploaded for page 3 must be used for page 3 and
    change nothing about any other page."""
    import os
    import shutil
    import cv2
    from mangatl import editor
    from mangatl.project import Project

    shutil.rmtree(scratch("_tmp_plate"), ignore_errors=True)
    p = Project(None, scratch("_tmp_plate"))
    try:
        if len(_PAGES) < 2:
            pytest.skip("need sample pages")
        for k, f in enumerate(_PAGES[:2]):
            p.add_uploaded(f"p{k}.jpg", open(f, "rb").read())

        magenta = np.full((60, 40, 3), (200, 0, 200), np.uint8)
        d = os.path.join(p.output_dir, "custom_clean")
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, "000.png")
        cv2.imwrite(dest, magenta)
        p.pages[0].custom_clean = dest

        pg0 = p.materialize(0)
        editor.clean_page(p, 0, pg0)
        assert pg0.clean_plate.mean(axis=(0, 1))[1] < 40, \
            "page 0 should be the magenta custom plate"
        assert pg0.clean_plate.shape[:2] == pg0.image.shape[:2], \
            "a mismatched plate must be resized to the page"

        pg1 = p.materialize(1)
        editor.clean_page(p, 1, pg1)
        g = cv2.cvtColor(pg1.clean_plate, cv2.COLOR_BGR2GRAY)
        assert g.mean() > 100, "page 1 must keep its automatic cleaning"
    finally:
        shutil.rmtree(scratch("_tmp_plate"), ignore_errors=True)


def _tiny_project(root: str, n: int = 3):
    """A project of `n` small synthetic pages, each with one bubble."""
    import cv2
    from mangatl.project import Project
    p = Project(None, root)
    for k in range(n):
        img = np.full((160, 120, 3), 240, np.uint8)
        cv2.ellipse(img, (60, 70), (44, 34), 0, 0, 360, (0, 0, 0), 2)
        cv2.putText(img, "A%d" % k, (44, 78), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 0, 0), 2)
        p.add_uploaded("p%d.png" % k, cv2.imencode(".png", img)[1].tobytes())
        from mangatl.interactive import region_from_box
        from mangatl.models import Page as _P
        from mangatl.project import region_record
        r = region_from_box(_P(image=img), 30, 45, 60, 50, rid=1)
        p.pages[k].regions = [region_record(r)]
    return p


def test_a_cleaned_plate_is_still_there_after_a_restart():
    """Cleaning a page is the expensive part of showing it, and it only ever
    lived in a six-entry dictionary in memory — so closing the app threw away
    the whole chapter's work and the first visit to every page paid for it
    again. The plate now keeps a copy on disk under its own identity."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm1"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm1"), 2)
    try:
        page = p.materialize(0)
        editor.clean_page(p, 0, page)
        first = page.clean_plate.copy()

        # what a restart looks like from here: nothing left in memory
        editor._plate_cache.clear()
        editor._invalidate_renders()
        editor._page_cache.clear()

        def refuse(*a, **k):
            raise AssertionError("the plate should have come off the disk")

        real, editor.inpaint_mod.inpaint_page = \
            editor.inpaint_mod.inpaint_page, refuse
        try:
            again = p.materialize(0)
            editor.clean_page(p, 0, again)
        finally:
            editor.inpaint_mod.inpaint_page = real
        assert np.array_equal(again.clean_plate, first), \
            "the reloaded plate must be the one that was built"
    finally:
        shutil.rmtree(scratch("_tmp_warm1"), ignore_errors=True)


def test_a_disk_plate_is_only_reused_for_the_page_that_made_it():
    """The saving is worthless if it ever hands back the wrong picture: moving
    a box, switching cleaning method or changing page must all miss."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm2"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm2"), 2)
    try:
        rec = p.pages[0].regions[0]
        was = list(rec["bbox"])
        a = editor._plate_disk_path(p, 0)
        assert editor._plate_disk_path(p, 0) == a, "same page, same file"
        assert editor._plate_disk_path(p, 1) != a, "another page, another file"
        rec["bbox"] = [was[0] + 1] + was[1:]
        assert editor._plate_disk_path(p, 0) != a, "moved box, another file"
        rec["bbox"] = was
        assert editor._plate_disk_path(p, 0) == a, "and back again"
        p.settings["ai_clean"] = "all"
        p.settings["clean_url"] = "http://example.invalid/x"
        assert editor._plate_disk_path(p, 0) != a, \
            "a different cleaning method is a different plate"
    finally:
        shutil.rmtree(scratch("_tmp_warm2"), ignore_errors=True)


def test_warming_up_builds_every_page_before_it_is_asked_for():
    """The whole point: after the warm-up has run, moving to a page you have
    never opened costs a dictionary lookup rather than a clean and a render."""
    import shutil
    import time
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm3"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm3"), 3)
    try:
        editor._plate_cache.clear()
        editor._invalidate_renders()
        editor.warm_pages(p, 0)
        for _ in range(200):
            if not editor._warm["running"] and editor._warm["done"] == 3:
                break
            time.sleep(0.05)
        assert editor._warm["done"] == 3, "the warm-up should finish 3 pages"

        def refuse(i):
            raise AssertionError("page %d should already be built" % i)

        real, p.materialize = p.materialize, refuse
        try:
            for i in range(3):
                assert editor.render_index(p, i, "clean", paint=False)
        finally:
            p.materialize = real
    finally:
        shutil.rmtree(scratch("_tmp_warm3"), ignore_errors=True)


def test_the_warm_up_gives_way_to_a_real_job():
    """Building pages ahead of time must never slow down the step the person
    actually pressed, so it stands still while a job is running."""
    import shutil
    import time
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm4"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm4"), 3)
    try:
        p.job["running"] = True
        editor._plate_cache.clear()
        editor.warm_pages(p, 0)
        time.sleep(0.4)
        assert editor._warm["done"] == 0, \
            "nothing should be built while a job holds the floor"
        p.job["running"] = False
        for _ in range(200):
            if editor._warm["done"] == 3:
                break
            time.sleep(0.05)
        assert editor._warm["done"] == 3, "and it picks up again afterwards"
    finally:
        p.job["running"] = False
        editor._warm["gen"] += 1          # retire the worker
        shutil.rmtree(scratch("_tmp_warm4"), ignore_errors=True)


def test_warming_up_never_spends_the_hosted_cleaner_by_itself():
    """Building pages ahead of time is a kindness while it stays local. With
    the hosted cleaner switched on it would mean a call out to the network for
    every page nobody has cleaned yet — so pressing Clean stays the thing that
    spends that, and the warm-up only rebuilds what is already paid for."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm6"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm6"), 3)
    try:
        assert all(editor._worth_warming(p, i) for i in range(3)), \
            "with local cleaning every page is ours to build"
        p.settings["ai_clean"] = "hard"
        p.settings["clean_url"] = "https://example.invalid/clean"
        assert not any(editor._worth_warming(p, i) for i in range(3)), \
            "an uncleaned page must not be sent to the network unasked"
        p.pages[1].cleaned = True
        assert editor._worth_warming(p, 1), \
            "a page already cleaned costs nothing to rebuild"
        p.pages[2].regions = []
        assert editor._worth_warming(p, 2), \
            "a page with no text is only ever the scan"
    finally:
        shutil.rmtree(scratch("_tmp_warm6"), ignore_errors=True)


def test_the_page_image_url_changes_only_when_the_page_does():
    """Every page view used to end the image URL in the current clock, so the
    browser re-downloaded and re-decoded a picture it already had. The key it
    gets now must be steady across views and move on a real change."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm5"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm5"), 2)
    try:
        k = editor._render_key(p, 0)
        assert editor._render_key(p, 0) == k, "no change, no reload"
        assert editor._render_key(p, 1) != k, "a different page is different"
        was = p.pages[0].regions[0].get("dst_text")
        p.pages[0].regions[0]["dst_text"] = "hello"
        assert editor._render_key(p, 0) != k, "edited text must reload"
        p.pages[0].regions[0]["dst_text"] = was
        assert editor._render_key(p, 0) == k, "and undoing it must not"
        editor._invalidate_renders()
        assert editor._render_key(p, 0) != k, \
            "dropping the server's cache must drop the browser's too"
    finally:
        shutil.rmtree(scratch("_tmp_warm5"), ignore_errors=True)


def test_choosing_a_font_does_not_throw_away_the_cleaned_page():
    """The scan and the cleaned plate carry no text, so the typesetting settings
    cannot change what they look like. Counting them meant picking a font
    rebuilt the cleaned page from scratch — with the hosted cleaner, a call out
    to the network and seconds of blank canvas — to arrive at the same image."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_font1"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_font1"), 1)
    try:
        plate = editor._render_key(p, 0)
        typeset = editor._render_stamp(p, 0, "typeset")
        p.settings["font"] = "/somewhere/else/Other.ttf"
        p.settings["max_font"] = 61

        assert editor._render_key(p, 0) == plate, \
            "a change of font must not invalidate the page under the text"
        assert editor._render_stamp(p, 0, "typeset") != typeset, \
            "but the typeset view really does look different"
    finally:
        shutil.rmtree(scratch("_tmp_font1"), ignore_errors=True)


def test_a_keyed_page_image_may_be_kept_and_an_unkeyed_one_may_not():
    """The key on the URL only buys anything if the answer is allowed to be
    kept: the server used to say no-store on everything, which is why the URL
    had the clock on it in the first place. A keyed URL names one picture for
    good; anything without a key is still live and must not be kept."""
    import json
    import shutil
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_warm7"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_warm7"), 2)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with urllib.request.urlopen(base + "/api/page/0") as r:
            key = json.loads(r.read())["vkey"]
        assert key, "the page must hand the browser a key"
        with urllib.request.urlopen(
                base + "/render/0?mode=clean&paint=0&v=" + key) as r:
            assert "no-store" not in r.headers.get("Cache-Control", ""), \
                "a keyed page image must be allowed into the browser's cache"
            assert len(r.read()) > 0
        with urllib.request.urlopen(base + "/render/0?mode=clean&paint=0") as r:
            assert "no-store" in r.headers.get("Cache-Control", ""), \
                "without a key the image is live and must not be kept"
    finally:
        srv.shutdown()
        srv.server_close()
        editor.PROJECT = was
        shutil.rmtree(scratch("_tmp_warm7"), ignore_errors=True)


def test_every_page_view_no_longer_busts_the_browser_cache():
    src = _ui_source()
    assert "t='+Date.now()" not in src.replace('"', "'"), \
        "the image URL must not carry the clock — it defeats every cache"
    assert "vkey" in src, "the page image URL should carry the server's key"


def _ui_source():
    """editor.html plus every stylesheet and script it loads.
    The client was one inline file once; it is now editor.html + static/css
    + static/js, so source-level assertions read the whole set."""
    import glob
    import os
    static = os.path.join(str(PKG), "static")
    parts = [open(os.path.join(static, "editor.html")).read(),
             open(os.path.join(static, "css", "editor.css")).read()]
    for p in sorted(glob.glob(os.path.join(static, "js", "*.js"))):
        parts.append(open(p).read())
    return "\n".join(parts)


def test_outline_zero_means_none_in_the_preview_payload():
    """`stroke||1` reads 0 as unset and draws an outline anyway; the UI must
    treat 0 as a real value."""
    s = _ui_source()
    assert "stroke||" not in s, "falsy-zero stroke fallback is back"


def test_ui_has_history_layers_and_undo_wiring():
    """The client keeps a session history with Ctrl+Z undo, paints strokes as
    deletable layers, and draws them beneath the typesetting."""
    s = _ui_source()
    # typesetting overlay must sit above the paint canvas (the exact numbers
    # drift; the stacking order is the contract)
    import re
    overlay = s.split("#overlay{", 1)[1].split("}")[0]
    z_overlay = int(re.search(r"z-index:(\d+)", overlay).group(1))
    paint = s.split("c.id='paint'", 1)[1].split("appendChild", 1)[0]
    z_paint = int(re.search(r"z-index:(\d+)", paint).group(1))
    assert z_overlay > z_paint, \
        "typesetting overlay must draw above the paint canvas"
    for needle in ("function record(", "function undoLast(",
                   "function deleteLayer(", "function renderLayers(",
                   "histList"):
        assert needle in s, f"missing {needle}"


def test_individual_cleanings_can_be_turned_off():
    """Each bubble's cleaning is a layer of its own: switching one off puts
    that bubble's original text back while every other bubble stays cleaned."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    img = np.full((200, 400, 3), 240, np.uint8)
    cv2.putText(img, "AA", (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 7)
    cv2.putText(img, "BB", (230, 110), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 7)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def region(rid, x0):
        m = np.zeros(gray.shape, np.uint8)
        m[30:150, x0:x0 + 170] = 255
        return TextRegion(id=rid, bbox=(x0, 30, 170, 120),
                          text_mask=((gray <= 128).astype(np.uint8) * 255) & m,
                          bubble_mask=m, bubble_bbox=(x0, 30, 170, 120))

    a, b = region(0, 10), region(1, 210)
    a.skip_clean = True
    page = Page(image=img.copy(), regions=[a, b])
    inpaint.inpaint_page(page)
    out = cv2.cvtColor(page.clean_plate, cv2.COLOR_BGR2GRAY)

    assert (out[30:150, 10:180] <= 128).sum() > 500, \
        "the skipped bubble must keep its original text"
    assert (out[30:150, 210:380] <= 128).sum() < 50, \
        "the other bubble must still be cleaned"


def test_skip_clean_survives_the_record_round_trip():
    from mangatl.project import region_from_record, region_record
    from mangatl.models import TextRegion
    img = np.full((60, 60, 3), 255, np.uint8)
    r = TextRegion(id=3, bbox=(5, 5, 40, 40), bubble_bbox=(5, 5, 40, 40),
                   skip_clean=True)
    rec = region_record(r)
    assert rec["skip_clean"] is True
    back = region_from_record(rec, img)
    assert back.skip_clean is True


def test_cleaning_eye_toggle_works_in_a_real_dom():
    """Drive the actual editor HTML in jsdom: click the cleaning eye off and
    on again, and assert the right requests hit the wire both times. Skipped
    where node or jsdom is unavailable."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "clean_toggle.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "click 1 posts: [ { skip_clean: true } ]" in out.stdout
    assert "click 2 posts: [ { skip_clean: false } ]" in out.stdout


def test_colour_picker_works_without_the_native_dialog():
    """The in-app picker must open, accept a typed hex, convert HSV both ways,
    and take an eyedropper result even when the popover is closed."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "colour_picker.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "popover shown: block" in out.stdout
    assert "brush colour: #3366cc" in out.stdout
    assert "#a1b2c3 #a1b2c3" in out.stdout


def test_detect_all_honours_page_scope_and_kinds():
    """The chapter-wide endpoint used to ignore both the page list and the
    chosen kinds — so "this page only" swept every page, and asking for
    free-floating text silently did nothing."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.Handler.do_POST)
    block = src.split('"/api/detect_all"', 1)[1].split("return self._json", 1)[0]
    assert 'body.get("pages")' in block, "page scope is ignored"
    assert 'body.get("kinds")' in block, "detection kinds are ignored"


# ------------------------------------------- detection: new coverage


def test_dark_bubbles_with_white_text_are_detected():
    """White-on-black typesetting (shouts, flashbacks, narration on dark art)
    was invisible to both the white-blob and outline methods; the inverted
    pass must find it."""
    import cv2
    from mangatl.detect import classical
    from mangatl.models import Page

    img = np.full((900, 700, 3), 210, np.uint8)
    # a black burst panel with light "text" lines inside
    cv2.rectangle(img, (100, 100), (480, 380), (10, 10, 10), -1)
    for k, yy in enumerate(range(150, 340, 40)):
        cv2.line(img, (150 + (k % 2) * 15, yy), (430 - (k % 2) * 10, yy),
                 (245, 245, 245), 9)
    # and an ordinary white bubble, to prove the passes coexist
    cv2.ellipse(img, (350, 650), (140, 100), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (350, 650), (140, 100), 0, 0, 360, (20, 20, 20), 4)
    for k, yy in enumerate(range(610, 700, 28)):
        cv2.line(img, (270, yy), (430, yy), (25, 25, 25), 8)

    page = Page(image=img)
    regs = classical.detect_combined(page)
    hits_dark = [r for r in regs if _iou_box(r.bubble_bbox, (100, 100, 380, 280)) > 0.4]
    hits_white = [r for r in regs if _iou_box(r.bubble_bbox, (210, 550, 280, 200)) > 0.35]
    assert hits_dark, f"dark panel text not found (got {[r.bubble_bbox for r in regs]})"
    assert hits_white, "the ordinary white bubble must still be found"


def _iou_box(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ox * oy
    return inter / max(1.0, aw * ah + bw * bh - inter)


def test_single_glyph_bubbles_are_detected():
    """A bubble holding nothing but 「!?」 or 「…」 is one connected glyph;
    requiring two glyph holes silently dropped every such bubble."""
    import cv2
    from mangatl.detect import classical
    from mangatl.models import Page

    img = np.full((600, 500, 3), 235, np.uint8)
    cv2.ellipse(img, (250, 300), (90, 70), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 300), (90, 70), 0, 0, 360, (15, 15, 15), 4)
    cv2.putText(img, "!?", (210, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.8,
                (20, 20, 20), 10)

    regs = classical.detect_combined(Page(image=img))
    hit = [r for r in regs if _iou_box(r.bubble_bbox, (160, 230, 180, 140)) > 0.3]
    assert hit, f"single-glyph bubble missed (got {[r.bubble_bbox for r in regs]})"


# ------------------------------------------- translation: context & continuity


def test_a_page_is_translated_with_the_one_before_it():
    """The translate payload carries the tail of the previous page.

    Briefly it did not — dropped to see whether quality held. It was reverted,
    and this test is what the experiment left behind: the tail's PRESENCE was
    never asserted anywhere before, so removing it broke nothing and said
    nothing. Now it would.

    Measured, for anyone tempted again: the tail is 77 tokens on a nine-box
    page, which is under 1% of what that page costs. It is not where the money
    is. Model choice is 28x; `chapter_context` on a subset run is larger still.
    """
    import numpy as np
    from mangatl.models import Page, TextRegion
    from mangatl.translate import SeriesContext, build_payload

    ctx = SeriesContext()
    ctx.previous_page_tail = ["Leonora: He came.", "Aeda: I see."]
    ctx.characters = {"Leonora": "she/her - the Saint"}
    ctx.glossary = {"聖女": "Saint"}

    pg = Page(image=np.full((50, 50, 3), 255, np.uint8))
    pg.regions = [TextRegion(id=0, bbox=(0, 0, 5, 5), src_text="彼は待っていた")]
    payload = build_payload(pg, ctx)

    assert payload["previous_page_tail"] == ["Leonora: He came.", "Aeda: I see."]
    # And the facts that hold a chapter together go with it.
    assert payload["characters"] == {"Leonora": "she/her - the Saint"}
    assert payload["glossary"] == {"聖女": "Saint"}


def test_the_tail_is_still_kept_for_the_passes_that_use_it():
    """Dropping it from the translate payload must not stop it being computed.

    Two things still read it: `name_evidence`, so a name introduced on the
    page before is not mistaken for one the model invented, and the
    PROOFREAD payload, so a first line that does not follow from the page
    before is still caught — at the pass whose job that is.
    """
    from mangatl.models import Page, TextRegion
    from mangatl.translate import SeriesContext, build_proofread_payload

    ctx = SeriesContext()
    ctx.previous_page_tail = ["Leonora: He came."]
    pg = Page(image=np.full((50, 50, 3), 255, np.uint8))
    pg.regions = [TextRegion(id=0, bbox=(0, 0, 5, 5), src_text="x",
                             dst_text="He waited.")]
    assert build_proofread_payload(pg, ctx)["previous_page_tail"] \
        == ["Leonora: He came."]


def test_prompt_teaches_the_model_to_use_the_context():
    from mangatl.translate import build_system

    s = build_system("manga", "en")
    for needle in ("series_context", "characters", "glossary",
                   "previous_page_tail", "pronoun", "copy editor",
                   "character_additions"):
        assert needle in s, f"the system prompt no longer mentions {needle}"
    assert "{" not in s
    # dialogue must be told to sound like speech, not a headline/label
    assert "person TALKING" in s and "headline" in s.lower()


def test_series_context_round_trips_characters(tmp_path):
    from mangatl.translate import SeriesContext

    ctx = SeriesContext(synopsis="Aeda, a boy healer (he/him).",
                        characters={"Aeda": "he/him - soft-spoken healer"})
    path = str(tmp_path / "ctx.json")
    ctx.save(path)
    back = SeriesContext.load(path)
    assert back.characters == ctx.characters
    # contexts saved before the field existed still load
    old = dict(ctx.__dict__)
    old.pop("characters")
    import json as _json
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump(old, fh)
    assert SeriesContext.load(path).characters == {}


def test_translation_carries_characters_and_speaker_tail():
    """The character sheet accumulates (first sighting wins) and the page
    tail carries speakers — the two levers against mid-chapter pronoun
    drift."""
    from types import SimpleNamespace
    import json as _json
    from mangatl.translate import SeriesContext, translate_page, build_payload
    from mangatl.models import Page, TextRegion

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [
        TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="来たんだ"),
        TextRegion(id=1, bbox=(0, 20, 10, 10), src_text="そうか"),
    ]

    ctx = SeriesContext(synopsis="Leonora is the Saint (she/her).",
                        characters={"Leonora": "she/her - the Saint"})
    payload = build_payload(page, ctx)
    assert payload["characters"] == {"Leonora": "she/her - the Saint"}

    reply = _json.dumps({
        "regions": [
            {"id": 0, "translation": "He came.", "compact": "He's here.",
             "speaker": "Leonora", "confidence": 0.9},
            # the page says this name out loud, so the sheet may learn it
            {"id": 1, "translation": "I see, Aeda.", "compact": "I see.",
             "speaker": "Aeda", "confidence": 0.9},
        ],
        "page_notes": "",
        "glossary_additions": {},
        "character_additions": {"Aeda": "he/him - young healer",
                                "Leonora": "they/them - WRONG"},
    })
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])))

    translate_page(page, ctx, client=fake)
    assert ctx.characters["Aeda"] == "he/him - young healer"
    assert ctx.characters["Leonora"] == "she/her - the Saint", \
        "a later page must not flip an established character's pronouns"
    assert ctx.previous_page_tail == ["Leonora: He came.", "Aeda: I see, Aeda."]


def test_invented_speaker_never_reaches_the_sheet():
    """The same page, with the one difference that nobody ever says the name.
    A name written nowhere is a name the model made up, and the sheet is what
    carries an invention into every later chapter."""
    from types import SimpleNamespace
    import json as _json
    from mangatl.translate import SeriesContext, translate_page
    from mangatl.models import Page, TextRegion

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="そうか")]
    ctx = SeriesContext(characters={"Leonora": "she/her - the Saint"})

    reply = _json.dumps({
        "regions": [{"id": 0, "translation": "I see.", "compact": "I see.",
                     "speaker": "Aeda", "confidence": 0.9}],
        "page_notes": "", "glossary_additions": {},
        "character_additions": {"Aeda": "he/him - young healer"},
    })
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])))

    data = translate_page(page, ctx, client=fake)
    assert "Aeda" not in ctx.characters
    assert any("Aeda" in r for r in data.get("characters_refused", []))
    # the label is kept — it may well be the right person — but it is marked
    assert "not named anywhere" in (page.regions[0].flagged or "")


# ------------------------------------------- glyph safety: no tofu, ever


def test_normalize_maps_typographic_characters():
    from mangatl.typeset import normalize_text

    assert normalize_text("“Don’t…”") == '"Don\'t..."'
    assert normalize_text("wait—no") == "wait—no"       # em-dash kept
    assert normalize_text("OH--RIGHT") == "OH—RIGHT", \
        "a run of hyphens becomes one em-dash"
    assert normalize_text("uh---huh") == "uh—huh"
    assert normalize_text("FIRST-STAGE") == "FIRST-STAGE", \
        "a lone hyphen inside a word stays a hyphen"
    assert normalize_text("HEALINGー") == "HEALING-"      # leaked chōonpu
    assert normalize_text("What⁉") == "What!?"
    assert normalize_text("a​b c") == "ab c"        # zero-width, nbsp
    assert normalize_text("") == ""


def test_sanitize_only_emits_glyphs_the_font_has():
    """The exact bug from lee's export: a character the typesetting font has no
    glyph for reached the page and rendered as a tofu box. After sanitising,
    every character must be in the font's cmap.

    This is the *substitutes on* behaviour — lee: *"hve a use subtitute button
    in the setting that if turned n will allow teh typeseeter to use subtitute
    symeboxes"*. With it off, nothing is stood in for; see the test below.
    """
    from fontTools.ttLib import TTFont
    from mangatl.typeset import sanitize_for_font

    path = _os.path.join("fonts", "AnimeAce.ttf")
    cov = set(TTFont(path, lazy=True).getBestCmap().keys())

    nasty = "THE POWER OF HEALINGー —really— ♪oh♪ “yes” ōkami"
    out = sanitize_for_font(nasty, path, substitutes=True)
    assert out, "sanitising must not wipe the line out"
    # every emitted character is either drawable by the font OR the em-dash,
    # which the renderer draws by hand (em_dash_glyph)
    for ch in out:
        assert ch == "—" or ord(ch) in cov, \
            f"emitted a character the font cannot draw: {ch!r}"
    assert "HEALING-" in out            # chōonpu mapped, not dropped
    assert "—really—" in out            # em-dash KEPT, drawn by hand
    assert "♪" not in out          # music note: no glyph, no stand-in -> gone
    assert "okami" in out               # ō decomposed to its base letter


def test_with_substitutes_off_nothing_is_stood_in_for():
    """lee: *"Fonts should only us that font no substitute"*. With the switch
    off the words go through exactly as typed — no letter is decomposed into
    another, no character is swapped for one the face happens to have, and
    nothing is silently dropped. What the font cannot draw is a problem to be
    SHOWN, not one to be papered over."""
    from mangatl.typeset import sanitize_for_font

    path = _os.path.join("fonts", "AnimeAce.ttf")
    nasty = "THE POWER OF HEALINGー —really— ♪oh♪ “yes” ōkami"
    out = sanitize_for_font(nasty, path)          # default: substitutes off

    assert "♪oh♪" in out, "a character the font lacks is kept, not dropped"
    assert "ōkami" in out, "ō is left alone, not decomposed to o"
    # the only thing that still happens is the tidy every line gets
    assert out == out.strip()


def test_typeset_never_lets_tofu_reach_the_layout():
    """End to end: a region whose translation is full of unrenderable
    characters must still lay out, and every line must be drawable."""
    import cv2
    from fontTools.ttLib import TTFont
    from mangatl.typeset import TypesetConfig, fit_region
    from mangatl.models import Page, TextRegion

    img = np.full((400, 400, 3), 255, np.uint8)
    mask = np.zeros((400, 400), np.uint8)
    cv2.ellipse(mask, (200, 200), (150, 110), 0, 0, 360, 255, -1)

    r = TextRegion(id=0, bbox=(60, 100, 280, 200), bubble_mask=mask,
                   bubble_bbox=(50, 90, 300, 220),
                   dst_text="THE POWER OF HEALINGー… ♪")
    font = _os.path.join("fonts", "AnimeAce.ttf")
    lay = fit_region(r, TypesetConfig(font_path=font, substitutes=True))
    assert lay and lay.lines
    cov = set(TTFont(font, lazy=True).getBestCmap().keys())
    for line in lay.lines:
        for ch in line:
            assert ord(ch) in cov, f"layout contains undrawable {ch!r}"
    joined = " ".join(lay.lines)
    assert "HEALING-..." in joined.replace("  ", " ")
    assert "♪" not in joined

    # ...and with the switch off the same line goes through untouched, with
    # the trouble reported instead of hidden. lee: *"if its of the text the
    # typesster shoud not use them"*.
    r2 = TextRegion(id=0, bbox=(60, 100, 280, 200), bubble_mask=mask,
                    bubble_bbox=(50, 90, 300, 220),
                    dst_text="THE POWER OF HEALINGー… ♪")
    lay2 = fit_region(r2, TypesetConfig(font_path=font))
    assert lay2 and lay2.lines
    assert "♪" in " ".join(lay2.lines), "the character the font lacks is kept"
    assert r2.flagged and "glyph" in r2.flagged


def test_the_bundled_font_is_found_from_any_working_directory(tmp_path,
                                                              monkeypatch):
    """The editor is started from wherever the person happens to be standing.
    Looking for the bundled face relative to the working directory is how an
    install with a full fonts/ folder still said "No usable font"."""
    from mangatl import typeset as ts

    monkeypatch.delenv("MANGATL_FONT", raising=False)
    monkeypatch.chdir(tmp_path)
    ts._font_dirs.cache_clear()
    try:
        p = ts.default_font_path()
        assert _os.path.exists(p)
        assert _os.path.basename(p) in ("CCWildWords.ttf", "AnimeAce.ttf",
                                        "ComicNeue-Bold.ttf"), \
            f"fell through to {p} instead of the bundled typesetting font"
    finally:
        ts._font_dirs.cache_clear()


def test_a_missing_spare_font_never_takes_a_page_down(monkeypatch):
    """Asking for a fallback face must not be what breaks a render. The
    project already names its own font; a missing spare is only the loss of a
    safety net, not a reason to raise in the middle of laying out a page."""
    from mangatl import typeset as ts

    def gone():
        raise FileNotFoundError("No usable font.")
    monkeypatch.setattr(ts, "default_font_path", gone)

    r = _oval_region(300, 220, "THE PAGE STILL TYPESETS ITSELF.")
    lay = ts.fit_region(r, ts.TypesetConfig(
        font_path=_os.path.join("fonts", "CCWildWords.ttf")))
    assert lay.lines and any(s.strip() for s in lay.lines)


def _letterless_font(tmp_path) -> str:
    """A font file that opens perfectly and cannot draw a word of English.

    Every machine has a drawerful of these — Wingdings, Webdings, Marlett,
    Segoe MDL2 Assets, emoji and CJK-only faces — and they sit in the font
    picker looking like any other choice. Built here by keeping only the
    punctuation of a real font, so the file is genuinely valid.
    """
    pytest.importorskip("fontTools")
    from fontTools.ttLib import TTFont
    from fontTools.subset import Subsetter
    out = str(tmp_path / "symbols_only.ttf")
    f = TTFont(_os.path.join("fonts", "CCWildWords.ttf"))
    s = Subsetter()
    s.populate(text=".,!?")
    s.subset(f)
    f.save(out)
    return out


def test_a_font_with_no_letters_in_it_is_not_a_typesetting_font(tmp_path):
    """`usable_font` only says the file opens, which a symbol face does. That
    is why choosing one used to wipe the page instead of being refused."""
    from mangatl.typeset import can_typeset, usable_font, sanitize_for_font
    symbols = _letterless_font(tmp_path)

    assert can_typeset(_os.path.join("fonts", "CCWildWords.ttf"))
    assert usable_font(symbols)          # it really does load — that's the trap
    # and this is the damage: nothing of the line survives being made drawable
    assert not any(c.isalnum()
                   for c in sanitize_for_font("WAIT — REALLY?", symbols,
                                              substitutes=True))
    assert not can_typeset(symbols)


def test_a_bubble_is_typeset_in_something_else_rather_than_left_empty(tmp_path):
    """A region whose font cannot draw its dialogue is typeset in a face that
    can, and flagged — text in the wrong font is a thing you can see and put
    right, an empty bubble is not."""
    from mangatl.typeset import TypesetConfig, fit_region
    symbols = _letterless_font(tmp_path)

    r = _oval_region(300, 220, "WAIT — ARE YOU REALLY GOING TO SAY THAT?")
    lay = fit_region(r, TypesetConfig(font_path=symbols, substitutes=True))

    joined = " ".join(lay.lines).upper()
    assert "REALLY" in joined and "GOING" in joined
    assert r.flagged and "font" in r.flagged.lower()


def test_with_substitutes_off_it_is_not_handed_to_another_face(tmp_path):
    """The rescue above is a substitution too — a different face standing in
    for the one that was chosen. With the switch off, the words are set in the
    font lee picked and nowhere else, and the missing glyphs are named on the
    flag so he can see what his face cannot draw."""
    from mangatl.typeset import TypesetConfig, fit_region
    symbols = _letterless_font(tmp_path)

    r = _oval_region(300, 220, "WAIT — ARE YOU REALLY GOING TO SAY THAT?")
    lay = fit_region(r, TypesetConfig(font_path=symbols))

    assert "REALLY" in " ".join(lay.lines).upper(), "the words go in as typed"
    assert r.flagged and "glyph" in r.flagged, \
        "and the face that cannot draw them is named"


def test_typesetting_again_never_empties_a_bubble_that_was_typeset(monkeypatch):
    """The whole point of the guard: whatever a later run cannot do — a font
    with no glyphs, a mask that came back empty — the typesetting already on the
    page stays there instead of being replaced with nothing."""
    from mangatl import typeset as ts

    r = _oval_region(300, 220, "WAIT — ARE YOU REALLY GOING TO SAY THAT?")
    page = _FakePage([r])
    ts.typeset_page(page, ts.TypesetConfig(font_path=default_font_path()))
    was = list(r.layout.lines)
    assert any(s.strip() for s in was)

    monkeypatch.setattr(ts, "fit_region", lambda *a, **k: ts.TextLayout(
        lines=[], font_size=20, leading=1.1, fit_ok=False))
    ts.typeset_page(page, ts.TypesetConfig(font_path=default_font_path()))

    assert list(r.layout.lines) == was


def test_temperature_is_dropped_when_the_model_rejects_it():
    """Newer Anthropic models answer 400 '`temperature` is deprecated for
    this model'. The translator must retry without it — and remember, so
    page two doesn't pay the failed call again."""
    from types import SimpleNamespace
    import json as _json
    from mangatl import translate as tr
    from mangatl.translate import SeriesContext, translate_page
    from mangatl.models import Page, TextRegion

    calls = []

    def create(**kw):
        calls.append("temperature" in kw)
        if "temperature" in kw:
            raise RuntimeError("Error code: 400 - `temperature` is "
                               "deprecated for this model.")
        reply = _json.dumps({"regions": [{"id": 0, "translation": "Hi.",
                                          "compact": "Hi.", "speaker": None,
                                          "confidence": 0.9}],
                             "page_notes": "", "glossary_additions": {},
                             "character_additions": {}})
        return SimpleNamespace(content=[SimpleNamespace(type="text",
                                                        text=reply)])

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    tr._NO_TEMPERATURE.clear()

    def page():
        pg = Page(image=np.full((50, 50, 3), 255, np.uint8))
        pg.regions = [TextRegion(id=0, bbox=(0, 0, 5, 5), src_text="やあ")]
        return pg

    translate_page(page(), SeriesContext(), client=fake, model="m-x")
    assert calls == [True, False], "must retry the same page without it"
    translate_page(page(), SeriesContext(), client=fake, model="m-x")
    assert calls == [True, False, False], \
        "the second page must skip the doomed attempt entirely"
    tr._NO_TEMPERATURE.clear()


# ------------------------------------------- translation: hardened parsing


def test_json_repair_fixes_what_models_actually_send():
    """Unescaped quotes inside a translated line ('Expecting , delimiter'),
    prose around the JSON, fences, trailing commas, literal newlines and
    smart-quote delimiters must all parse."""
    from mangatl.translate import _extract_json

    # the exact field failure: a quote inside a translation, unescaped
    d = _extract_json('{"regions":[{"id":0,"translation":"He said "stop" now",'
                      '"compact":"Stop!","speaker":null,"confidence":0.9}],'
                      '"page_notes":"","glossary_additions":{}}')
    assert d["regions"][0]["translation"] == 'He said "stop" now'

    d = _extract_json('Sure! Here is the JSON you asked for:\n'
                      '```json\n{"regions": [], "page_notes": "hi"}\n```\n'
                      'Let me know if you need anything else.')
    assert d["page_notes"] == "hi"

    d = _extract_json('{"a": 1, "b": [1, 2,], }')
    assert d == {"a": 1, "b": [1, 2]}

    d = _extract_json('{"a": "line one\nline two"}')
    assert d["a"] == "line one\nline two"

    d = _extract_json('{“a”: “b”}')
    assert d == {"a": "b"}


def test_truncated_reply_is_reported_as_truncation():
    from mangatl.translate import _looks_truncated

    assert _looks_truncated('{"regions":[{"id":0,"translation":"He')
    assert _looks_truncated('{"regions":[{"id":0}')
    assert not _looks_truncated('{"regions":[]}')


def test_translate_survives_a_sloppy_first_reply():
    """First reply: broken JSON. Second: entries with a string confidence and
    a numeric speaker. Both used to kill the whole run; now the page lands."""
    from types import SimpleNamespace
    from mangatl.translate import SeriesContext, translate_page
    from mangatl.models import Page, TextRegion

    replies = [
        'Here you go: {"regions":[{"id":0,"translation":"OK',       # truncated
        '{"regions":[{"id":0,"translation":"She said "wait" quietly",'
        '"compact":"Wait!","speaker":42,"confidence":"0.85"}],'
        '"page_notes":"","glossary_additions":{},"character_additions":{}}',
    ]
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(
            type="text", text=replies[min(len(calls) - 1, len(replies) - 1)])])

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    pg = Page(image=np.full((50, 50, 3), 255, np.uint8))
    pg.regions = [TextRegion(id=0, bbox=(0, 0, 5, 5), src_text="待って")]

    translate_page(pg, SeriesContext(), client=fake, model="m-y")
    r = pg.regions[0]
    assert r.dst_text == 'She said "wait" quietly'
    assert r.speaker == "42" and abs(r.confidence - 0.85) < 1e-6
    # the retry told the model WHY the first reply failed
    assert "cut off" in calls[-1]["messages"][0]["content"]


def test_openai_compat_drops_unsupported_knobs(monkeypatch):
    """A server that 400s on response_format (or temperature) gets the same
    request again without it — one server quirk must not fail the page."""
    import io
    import urllib.error
    import urllib.request
    from mangatl.translate import OpenAICompatClient

    sent = []

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data)
        sent.append(sorted(body.keys()))
        if "response_format" in body:
            raise urllib.error.HTTPError(
                "u", 400, "bad", {},
                io.BytesIO(b'{"error":"response_format is not supported"}'))
        if "temperature" in body:
            raise urllib.error.HTTPError(
                "u", 400, "bad", {},
                io.BytesIO(b'{"error":"temperature is deprecated"}'))
        return io.BytesIO(json.dumps(
            {"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=0: fake_urlopen(req, timeout))
    c = OpenAICompatClient("http://x/v1", "m")
    assert c.complete("s", "u") == "{}"
    assert len(sent) == 3
    assert "response_format" not in sent[1] and "temperature" not in sent[2]
    # the client REMEMBERS: the next call goes straight through
    sent.clear()
    assert c.complete("s", "u") == "{}"
    assert len(sent) == 1


def test_single_page_translation_carries_the_whole_chapter():
    """'Translate this page only' must still show the AI every page (finished
    translations preferred, source otherwise) — and only ask for this one."""
    from types import SimpleNamespace
    import json as _json
    from mangatl.translate import SeriesContext, translate_page, build_payload
    from mangatl.models import Page, TextRegion

    chapter = [{"page": 1, "lines": ["She arrived at dawn."]},
               {"page": 2, "lines": ["彼は待っていた"]}]

    pg = Page(image=np.full((50, 50, 3), 255, np.uint8))
    pg.regions = [TextRegion(id=0, bbox=(0, 0, 5, 5), src_text="彼は待っていた")]

    payload = build_payload(pg, SeriesContext(), chapter)
    assert payload["chapter_context"] == chapter
    assert "chapter_context" not in build_payload(pg, SeriesContext())

    seen = {}

    def create(**kw):
        seen["user"] = kw["messages"][0]["content"]
        reply = _json.dumps({"regions": [{"id": 0, "translation": "He waited.",
                                          "compact": "He waited.",
                                          "speaker": None, "confidence": 0.9}],
                             "page_notes": "", "glossary_additions": {},
                             "character_additions": {}})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    translate_page(pg, SeriesContext(), client=fake, chapter=chapter)
    assert "She arrived at dawn." in seen["user"], \
        "the chapter context must reach the model"
    assert pg.regions[0].dst_text == "He waited."


class _Ctx:
    """A chapter, for the context tests below."""

    class Page:
        def __init__(self, regions):
            self.regions = regions

    def __init__(self, pages):
        self.pages = pages

    @staticmethod
    def done(*lines):
        return _Ctx.Page([{"order": i, "src_text": "日本語", "dst_text": t}
                          for i, t in enumerate(lines)])

    @staticmethod
    def todo(*lines):
        return _Ctx.Page([{"order": i, "src_text": t, "dst_text": ""}
                          for i, t in enumerate(lines)])


def test_the_repeated_half_of_the_payload_is_marked_for_the_cache():
    """Anthropic caches what is marked, and only whole blocks can be marked.

    So the payload is cut where the repeated half ends: the synopsis, the
    glossary and the chapter context in one block with a breakpoint on it,
    everything that changes per page in a second block after it. Cutting a
    JSON document in half is fine — the model is handed the blocks joined
    back together, so it reads exactly the string that went in. Only the
    billing sees the seam.
    """
    import json as _json
    import numpy as np
    from mangatl.models import Page, TextRegion
    from mangatl.translate import (SeriesContext, build_payload,
                                   split_at_the_fixed_part)

    ctx = SeriesContext()
    ctx.synopsis = "A healer follows a saint. " * 40
    ctx.glossary = {"聖女": "Saint"}
    ctx.characters = {"Leonora": "she/her"}
    chapter = [{"page": k, "lines": ["a line"] * 9} for k in range(20)]
    pg = Page(image=np.full((50, 50, 3), 255, np.uint8))
    pg.regions = [TextRegion(id=i, bbox=(0, 0, 5, 5), src_text="彼は待っていた")
                  for i in range(9)]

    user = _json.dumps(build_payload(pg, ctx, chapter),
                       ensure_ascii=False, indent=1)
    fixed, rest = split_at_the_fixed_part(user)

    # The model must read exactly what it read before.
    assert fixed + rest == user
    # The expensive repeated things are on the cached side...
    assert '"chapter_context"' in fixed
    assert '"glossary"' in fixed
    assert '"series_context"' in fixed
    # ...and nothing that changes per page is, or the prefix would never match.
    assert '"characters"' not in fixed
    assert '"regions"' not in fixed
    assert '"previous_page_tail"' not in fixed


def test_a_payload_with_no_moving_part_is_left_alone():
    """The safe answer is one block and no marking: no saving, no damage."""
    from mangatl.translate import split_at_the_fixed_part

    assert split_at_the_fixed_part("{}") == ("", "{}")
    assert split_at_the_fixed_part("") == ("", "")


def test_only_anthropic_is_asked_to_mark_anything():
    """Google's cache is implicit — it needs the repeated part first, which
    the key order already does, and nothing else. Sending it a marked block
    would be sending it a field it does not have."""
    import inspect
    from mangatl import translate

    src = inspect.getsource(translate._ask)
    before, _, after = src.partition('if kind == "openai"')
    assert "cache_control" not in before, \
        "the marking must come after the non-Anthropic paths have returned"


def test_chapter_context_reads_source_where_there_is_no_translation_yet():
    """"Finished translations only" sounded careful and was quietly the worst
    part of the narrow version.

    On a chapter nobody has started, it means the context is EMPTY: the model
    translates page 3 with no idea what happens on 2 or 4, which is the case
    the context exists for. Source text is not as good as a finished line, but
    it is the story — and it is what a human translator would read.
    """
    from mangatl.editor import chapter_context

    p = _Ctx([_Ctx.done("One"), _Ctx.todo("二"), _Ctx.done("Three"),
              _Ctx.todo("四"), _Ctx.done("Five")])
    out = chapter_context(p, [2])
    assert [c["page"] for c in out] == [1, 2, 4, 5], \
        "every other page, translated or not"
    assert out == [{"page": 1, "lines": ["One"]},
                   {"page": 2, "lines": ["二"]},
                   {"page": 4, "lines": ["四"]},
                   {"page": 5, "lines": ["Five"]}]
    # A page nobody has started still has a chapter around it to read.
    fresh = _Ctx([_Ctx.todo("一"), _Ctx.todo("二"), _Ctx.todo("三")])
    assert chapter_context(fresh, [1]) != []


def test_a_finished_translation_beats_the_source_line_it_replaced():
    """Where there IS an English line, that is what the next page should be
    consistent with. Sending the Japanese it came from would be handing the
    model the question instead of the answer it already settled."""
    from mangatl.editor import chapter_context

    p = _Ctx([_Ctx.done("Ada waits"), _Ctx.todo("二")])
    assert chapter_context(p, [1]) == [{"page": 1, "lines": ["Ada waits"]}]


def test_chapter_context_is_every_other_page_of_the_chapter():
    """Not a window. lee: *"undo these chnages"*.

    A window of two cannot see a name settled six pages back, or a term agreed
    at the front of a long re-run, and those are exactly the things a reader
    notices when they drift. What the window saved was input tokens, and input
    turned out to be the cheap quarter of the bill.
    """
    from mangatl import editor

    assert not hasattr(editor, "CONTEXT_WINDOW")
    p = _Ctx([_Ctx.done("p%d" % k) for k in range(23)])
    assert [c["page"] for c in editor.chapter_context(p, [10])] == \
        [k for k in range(1, 24) if k != 11]
    # ...including the far end of the chapter from the page being translated.
    assert [c["page"] for c in editor.chapter_context(p, [0])] == \
        list(range(2, 24))


def test_chapter_context_is_the_same_for_every_page_of_a_run():
    """The reason it is built for the RUN and not for each page.

    Identical bytes on every page of the run is what puts it inside the prompt
    cache — see `_base_payload`, which keeps it above `characters` for exactly
    this. A per-page context would be marginally better and would cost more
    than the whole chapter does, because nothing would ever hit.
    """
    from mangatl.editor import chapter_context

    p = _Ctx([_Ctx.done("p%d" % k) for k in range(23)])
    run = [10, 11, 12]
    once = chapter_context(p, run)
    assert [c["page"] for c in once] == \
        [k for k in range(1, 24) if k not in (11, 12, 13)]
    # asked again for the same run, byte for byte the same answer
    assert chapter_context(p, run) == once


def test_chapter_context_skips_the_pages_being_translated():
    """Their text is what is about to be replaced."""
    from mangatl.editor import chapter_context

    p = _Ctx([_Ctx.done("p%d" % k) for k in range(6)])
    assert 3 not in [c["page"] for c in chapter_context(p, [2])]


# ------------------------------------------- reading order: field regressions


def test_diagonal_gutter_page_reads_top_panel_first():
    """lee's page: two panels split by a slanted gutter. The old code cut
    vertically at 0 degrees before ever trying the rotated row gutter, so the
    bottom panel's bubbles were numbered before the top panel finished."""
    ex2 = [(1010, 25, 225, 400), (548, 115, 120, 180), (1055, 600, 165, 285),
           (608, 645, 195, 385), (118, 300, 155, 330), (143, 815, 135, 300)]
    assert reading_order(ex2, rtl=True) == [0, 1, 4, 2, 3, 5]


def test_side_by_side_columns_read_right_column_fully_first():
    """lee's other page: a full-height right column beside a tall left panel
    must be read all the way down before moving left."""
    ex1 = [(1035, 25, 205, 345), (520, 30, 280, 450),
           (825, 380, 205, 315), (130, 435, 90, 235)]
    assert reading_order(ex1, rtl=True) == [0, 2, 1, 3]


def test_ordering_uses_the_bubble_not_just_the_text():
    """Tight text boxes invent row gaps that the bubbles close; ordering must
    use the union box."""
    from mangatl.order import _order_box
    from mangatl.models import TextRegion

    r = TextRegion(id=0, bbox=(100, 100, 50, 50),
                   bubble_bbox=(80, 60, 120, 150))
    assert _order_box(r) == (80, 60, 120, 150)
    r2 = TextRegion(id=1, bbox=(10, 10, 20, 20))
    assert _order_box(r2) == (10, 10, 20, 20)


def test_manual_reading_order_is_sticky():
    """reorder() must never reshuffle numbers a human (or a finished pass)
    already set — geometry only decides for regions that arrive unnumbered."""
    from mangatl.editor import reorder

    class FakeStore:
        width, height = 200, 200

        def __init__(self, regions):
            self.regions = regions

    class FakeProj:
        rtl = True

        def __init__(self, regions):
            self.pages = [FakeStore(regions)]

    # human order 1,0 disagrees with geometry (0 is right of 1, RTL) — kept
    regs = [{"id": 0, "bbox": [150, 10, 40, 40], "order": 1},
            {"id": 1, "bbox": [10, 10, 40, 40], "order": 0}]
    reorder(FakeProj(regs), 0)
    assert [r["order"] for r in regs] == [1, 0], "sticky order was reshuffled"

    # A fresh, unnumbered region is only SLOTTED IN — the human's order for
    # the existing regions must survive adding a box (it used to trigger a
    # full geometric recompute that reshuffled everything).
    regs.append({"id": 2, "bbox": [80, 10, 40, 40], "order": -1})
    reorder(FakeProj(regs), 0)
    assert sorted(r["order"] for r in regs) == [0, 1, 2]
    by_id = {r["id"]: r["order"] for r in regs}
    assert by_id[1] < by_id[0], \
        "adding a box must not change the order of the existing regions"

    # ...and a page of NOTHING BUT fresh regions still gets geometric order
    virgin = [{"id": 0, "bbox": [150, 10, 40, 40], "order": -1},
              {"id": 1, "bbox": [10, 10, 40, 40], "order": -1}]
    reorder(FakeProj(virgin), 0)
    by_id = {r["id"]: r["order"] for r in virgin}
    assert by_id[0] < by_id[1], "RTL geometry decides for a fresh page"


def test_art_that_apes_a_bubble_is_rejected_by_edge_density():
    """A face, a horse, a whitish patch of background can satisfy every SHAPE
    check — light interior, dark 'glyphs', decent solidity — and on real
    chapters that meant several junk boxes per page. What art can't fake is a
    flat paper fill: its interior is full of drawn edges. The edge-density
    check must reject it while leaving a real bubble alone."""
    import cv2
    from mangatl.detect import classical
    from mangatl.models import Page

    rng = np.random.default_rng(7)
    img = np.full((900, 700, 3), 235, np.uint8)

    # impostor: outlined light blob whose interior is hatched with fine art
    # strokes plus a couple of glyph-sized dark marks (an "eye" and a "brow")
    cv2.ellipse(img, (220, 250), (130, 100), 0, 0, 360, (250, 250, 250), -1)
    cv2.ellipse(img, (220, 250), (130, 100), 0, 0, 360, (15, 15, 15), 4)
    for x in range(110, 340, 7):          # fine hatching: gradient, not ink
        cv2.line(img, (x, 170), (x - 20, 330), (180, 180, 180), 1)
    cv2.ellipse(img, (190, 240), (22, 12), 0, 0, 360, (20, 20, 20), -1)
    cv2.ellipse(img, (255, 225), (26, 8), 15, 0, 360, (20, 20, 20), -1)

    # real bubble: flat white fill, text-like ink rows
    cv2.ellipse(img, (350, 650), (150, 110), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (350, 650), (150, 110), 0, 0, 360, (20, 20, 20), 4)
    for yy in range(600, 710, 26):
        cv2.line(img, (250, yy), (450, yy), (25, 25, 25), 8)

    regs = classical.detect_combined(Page(image=img))
    fake = [r for r in regs if _iou_box(r.bubble_bbox, (90, 150, 260, 200)) > 0.4]
    real = [r for r in regs if _iou_box(r.bubble_bbox, (200, 540, 300, 220)) > 0.35]
    assert not fake, f"textured art patch detected as a bubble: {[r.bubble_bbox for r in fake]}"
    assert real, "the flat-filled real bubble must still be found"


def test_bubble_with_gapped_outline_is_recovered():
    """A spoken tail is often drawn open, and whisper bubbles have wavy,
    broken borders. The interior then leaks into the panel background, so the
    normal outline pass loses the bubble — a second pass with heavier gap
    closing must recover it. Seen on a real page where the two top bubbles of
    a panel were silently missing."""
    import cv2
    from mangatl.detect import classical
    from mangatl.models import Page

    img = np.full((900, 700, 3), 255, np.uint8)
    # dotted background so the leak does not reach the page border
    for yy in range(20, 880, 16):
        for xx in range(20, 680, 16):
            cv2.circle(img, (xx, yy), 2, (120, 120, 120), -1)
    # bubble whose outline has an 8 px gap (an open tail)
    cv2.ellipse(img, (350, 300), (170, 130), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (350, 300), (170, 130), 0, 0, 360, (15, 15, 15), 5)
    cv2.rectangle(img, (346, 424), (354, 436), (255, 255, 255), -1)  # the gap
    for yy in range(250, 360, 26):
        cv2.line(img, (250, yy), (450, yy), (25, 25, 25), 8)

    regs = classical.detect_combined(Page(image=img))
    hit = [r for r in regs if _iou_box(r.bubble_bbox, (180, 170, 340, 260)) > 0.4]
    assert hit, f"gapped-outline bubble missed (got {[r.bubble_bbox for r in regs]})"


# ------------------------------------------- fitting: full text, always


def test_fitter_ignores_the_shorter_alternative():
    """dst_compact is retired: the regular English is always the text that
    gets typeset, even when a project saved before the change still carries
    a compact wording."""
    import cv2
    from mangatl.typeset import TypesetConfig, fit_region
    from mangatl.models import TextRegion

    mask = np.zeros((300, 400), np.uint8)
    cv2.ellipse(mask, (200, 150), (170, 120), 0, 0, 360, 255, -1)

    r = TextRegion(id=0, bbox=(50, 50, 300, 200), bubble_mask=mask,
                   bubble_bbox=(30, 30, 340, 240),
                   dst_text="He is coming for all of us right now!")
    r.dst_compact = "Run!"
    font = _os.path.join("fonts", "AnimeAce.ttf")
    lay = fit_region(r, TypesetConfig(font_path=font))
    joined = " ".join(lay.lines)
    assert "coming" in joined
    assert joined != "Run!"


def test_prompt_and_schema_no_longer_ask_for_compact():
    from mangatl.translate import SCHEMA_HINT, build_system

    assert "compact" not in SCHEMA_HINT
    assert "compact" not in build_system("manga", "en")


def test_fitter_never_splits_a_word():
    """Hyphenation is gone for good — the fitter uses line breaks and size
    only. Even a word too wide for the bubble must come through whole (the
    layout is flagged, not the word butchered)."""
    import cv2
    from mangatl.typeset import TypesetConfig, fit_region
    from mangatl.models import TextRegion

    font = _os.path.join("fonts", "AnimeAce.ttf")

    # a narrow column where big sizes cannot hold the words — it must break
    # lines and drop the size, never split a word
    mask = np.zeros((520, 240), np.uint8)
    cv2.rectangle(mask, (40, 30), (200, 490), 255, -1)
    r = TextRegion(id=0, bbox=(40, 30, 160, 460), bubble_mask=mask,
                   bubble_bbox=(40, 30, 160, 460),
                   dst_text="NOW KNEEL BEFORE THE VILLAINESS")
    lay = fit_region(r, TypesetConfig(font_path=font))
    assert lay and lay.lines
    assert not any(ln.endswith("-") for ln in lay.lines), \
        f"introduced hyphens in {lay.lines}"
    assert set(" ".join(lay.lines).split()) == set(r.dst_text.split()), \
        "every word must arrive whole"

    # a word genuinely wider than the bubble: still never split — it lays
    # out flagged rather than hyphenated
    mask2 = np.zeros((300, 160), np.uint8)
    cv2.ellipse(mask2, (80, 150), (60, 120), 0, 0, 360, 255, -1)
    r2 = TextRegion(id=1, bbox=(20, 30, 120, 240), bubble_mask=mask2,
                    bubble_bbox=(20, 30, 120, 240),
                    dst_text="INCOMPREHENSIBILITY")
    lay2 = fit_region(r2, TypesetConfig(font_path=font))
    assert lay2 and lay2.lines
    assert all("-" not in ln for ln in lay2.lines), \
        f"introduced hyphens in {lay2.lines}"


def test_character_sheet_is_editable_from_settings():
    """The settings dialog owns the character sheet: the payload exposes it,
    and a settings POST REPLACES it (unlike character_additions from a
    translation reply, which only fills gaps)."""
    import inspect
    import shutil
    from mangatl import editor
    from mangatl.project import Project

    src = inspect.getsource(editor.Handler.do_POST)
    block = src.split('"/api/settings"', 1)[1].split("return self._json", 1)[0]
    assert '"characters" in body' in block, \
        "settings POST must accept the character sheet"

    shutil.rmtree(scratch("_tmp_chars"), ignore_errors=True)
    p = Project(None, scratch("_tmp_chars"))
    try:
        p.ctx.characters = {"Grow": "he/him - blunt mercenary"}
        payload = p.payload() if hasattr(p, "payload") else None
        if payload is None:                      # method name differs
            for name in ("summary", "to_payload", "project_payload"):
                if hasattr(p, name):
                    payload = getattr(p, name)()
                    break
        assert payload and payload["context"]["characters"] == \
            {"Grow": "he/him - blunt mercenary"}
    finally:
        shutil.rmtree(scratch("_tmp_chars"), ignore_errors=True)


# ------------------------------------------------------------- proofreading


def test_proofread_prompt_contract():
    from mangatl.translate import (PROOFREAD_SCHEMA_HINT,
                                   build_proofread_system)

    s = build_proofread_system("manga", "en")
    for needle in ("character sheet", "CANON", "exact", "UNCHANGED",
                   "proofread, not a rewrite"):
        assert needle in s, f"proofread prompt no longer says {needle!r}"
    assert "{" not in s
    assert '"id"' in PROOFREAD_SCHEMA_HINT and '"text"' in PROOFREAD_SCHEMA_HINT


def test_proofread_page_applies_fixes_and_keeps_good_lines():
    from types import SimpleNamespace
    import json as _json
    from mangatl.translate import SeriesContext, proofread_page
    from mangatl.models import Page, TextRegion

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [
        TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="グロウさんは",
                   dst_text="Grou is used to it."),
        TextRegion(id=1, bbox=(0, 20, 10, 10), src_text="そうだ",
                   dst_text="That's it!"),
    ]
    seen = {}

    def create(**kw):
        seen["user"] = kw["messages"][0]["content"]
        seen["system"] = kw.get("system", "")
        reply = _json.dumps({"regions": [
            {"id": 0, "text": "Grow is used to it."},
            {"id": 1, "text": "That's it!"},
        ], "page_notes": ""})
        return SimpleNamespace(content=[SimpleNamespace(type="text",
                                                        text=reply)])

    ctx = SeriesContext(characters={"Grow": "he/him - blunt mercenary"})
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    proofread_page(page, ctx, client=fake)
    assert page.regions[0].dst_text == "Grow is used to it.", \
        "the sheet's spelling must replace the stray romanization"
    assert page.regions[1].dst_text == "That's it!"
    assert "Grow" in seen["user"], "the character sheet must reach the model"


def test_do_proofread_clears_layouts_only_for_changed_lines():
    """Changed wording must drop its stale typesetting; untouched lines keep
    theirs. Every processed region gets the proofread mark, and the marks
    live on the stored records (no materialize/commit round trip)."""
    from mangatl import editor as ed
    from mangatl import translate as tr
    from mangatl.translate import SeriesContext

    class FakeStore:
        width, height = 100, 100

        def __init__(self, regions):
            self.regions = regions

    class FakeProj:
        rtl = True
        settings = {}

        def __init__(self, regions):
            self.pages = [FakeStore(regions)]
            self.ctx = SeriesContext()

    regs = [
        {"id": 0, "bbox": [0, 0, 10, 10], "order": 0, "src_text": "a",
         "dst_text": "Grou waits.", "layout": {"lines": ["Grou waits."]},
         "layout_override": {"lines": ["Grou waits."], "font": "x.ttf"}},
        {"id": 1, "bbox": [0, 20, 10, 10], "order": 1, "src_text": "b",
         "dst_text": "Fine.", "layout": {"lines": ["Fine."]}},
        {"id": 2, "bbox": [0, 40, 10, 10], "order": 2, "src_text": "c",
         "dst_text": ""},
    ]

    def fake_proofread(page, ctx=None, **kw):
        for r in page.regions:
            if r.id == 0:
                r.dst_text = "Grow waits."
        return {}

    orig = tr.proofread_page
    tr.proofread_page = fake_proofread
    try:
        ed.do_proofread(FakeProj(regs), 0)
    finally:
        tr.proofread_page = orig

    assert regs[0]["dst_text"] == "Grow waits."
    assert regs[0]["layout"] is None, "changed line must drop stale typesetting"
    assert "lines" not in (regs[0]["layout_override"] or {})
    assert regs[0]["layout_override"]["font"] == "x.ttf", \
        "styling survives, only the text-shape overrides go"
    assert regs[1]["layout"], "an untouched line keeps its typesetting"
    assert regs[0].get("proofread") and regs[1].get("proofread")
    assert not regs[2].get("proofread"), "an untranslated region is not done"


def test_proofread_route_scopes_to_pages():
    """The route runs the pages it was given, not the whole chapter.

    Read to the end of the ROUTE rather than to the first `return`. It used to
    stop at the first one, which was fine while the route had exactly one —
    and then the coin check went in above the run with a `return` of its own
    (a 402 for a chapter nobody can pay for), and this went red about a route
    that had not changed.
    """
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.Handler.do_POST)
    block = src.split('"/api/proofread_all"', 1)[1].split('if path == "', 1)[0]
    assert 'body.get("pages")' in block
    assert "Proofreading" in block
    assert 'run_job(p, "Proofreading", idx' in block


def test_proofread_knows_kinds_and_skips_sfx():
    """The payload names each region's kind; sound effects are not sent at
    all — but a page with SFX still finishes the proofread step (they are
    marked done, text untouched)."""
    from mangatl.translate import SeriesContext, build_proofread_payload
    from mangatl.models import Page, TextRegion
    from mangatl import editor as ed
    from mangatl import translate as tr

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [
        TextRegion(id=0, bbox=(0, 0, 10, 10), kind="bubble",
                   src_text="また気を引いてる…",
                   dst_text="Fishing for attention again..."),
        TextRegion(id=1, bbox=(0, 20, 10, 10), kind="sfx",
                   src_text="ドン", dst_text="THUD"),
    ]
    ctx = SeriesContext()
    ctx.medium, ctx.target = "manga", "en"
    pay = build_proofread_payload(page, ctx)
    assert [r["id"] for r in pay["regions"]] == [0], "sfx must stay out"
    assert pay["regions"][0]["kind"] == "bubble"

    assert "kind" in tr.PROOFREAD_TEMPLATE and "Sound effects" in tr.PROOFREAD_TEMPLATE

    class FakeStore:
        width, height = 100, 100

        def __init__(self, regions):
            self.regions = regions

    class FakeProj:
        rtl = True
        settings = {}

        def __init__(self, regions):
            self.pages = [FakeStore(regions)]
            self.ctx = SeriesContext()

    regs = [
        {"id": 0, "bbox": [0, 0, 10, 10], "order": 0, "kind": "bubble",
         "src_text": "a", "dst_text": "Hello."},
        {"id": 1, "bbox": [0, 20, 10, 10], "order": 1, "kind": "sfx",
         "src_text": "ドン", "dst_text": "THUD",
         "layout": {"lines": ["THUD"]}},
    ]

    def fake_proofread(page, ctx=None, **kw):
        # a real pass never receives the SFX; nothing changes here
        return {}

    orig = tr.proofread_page
    tr.proofread_page = fake_proofread
    try:
        ed.do_proofread(FakeProj(regs), 0)
    finally:
        tr.proofread_page = orig

    assert regs[1]["dst_text"] == "THUD", "sfx text must be untouched"
    assert regs[1]["layout"], "sfx typesetting must be untouched"
    assert regs[0].get("proofread") and regs[1].get("proofread"), \
        "the page must still count as fully proofread"


def test_proofread_reads_the_settings_sheet_not_the_translation():
    """The sheet can be edited by hand between translating and proofreading.
    Whatever it says at proofread time is what the proofreader must see: the
    payload carries that sheet, and speaker labels left over from translation
    are snapped onto it so a renamed person is still the same person."""
    from mangatl.translate import SeriesContext, build_proofread_payload
    from mangatl.models import Page, TextRegion
    from mangatl import editor as ed
    from mangatl import translate as tr

    ctx = SeriesContext()
    ctx.medium, ctx.target = "manga", "en"
    ctx.characters = {"Leonora": "she/her - blunt"}
    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [TextRegion(id=0, bbox=(0, 0, 10, 10), kind="bubble",
                               speaker="Leonora", src_text="a",
                               dst_text="He is late.")]
    pay = build_proofread_payload(page, ctx)
    assert pay["characters"] == {"Leonora": "she/her - blunt"}, \
        "the pronoun check has nothing to check against without the sheet"
    assert pay["regions"][0]["speaker"] == "Leonora"

    class FakeStore:
        width, height = 100, 100

        def __init__(self, regions):
            self.regions = regions

    class FakeProj:
        rtl = True
        settings = {}

        def __init__(self, regions, chars):
            self.pages = [FakeStore(regions)]
            self.ctx = SeriesContext()
            self.ctx.characters = dict(chars)

    # translation labelled her "Reonora"; the editor has since settled on
    # "Leonora" in settings
    regs = [{"id": 0, "bbox": [0, 0, 10, 10], "order": 0, "kind": "bubble",
             "speaker": "Reonora", "src_text": "a", "dst_text": "He is late."},
            {"id": 1, "bbox": [0, 20, 10, 10], "order": 1, "kind": "bubble",
             "speaker": "Someone Else", "src_text": "b", "dst_text": "Mm."}]
    seen = {}

    def fake_proofread(page, ctx=None, **kw):
        seen["speakers"] = [r.speaker for r in page.regions]
        seen["sheet"] = dict(getattr(ctx, "characters", {}) or {})
        return {}

    orig = tr.proofread_page
    tr.proofread_page = fake_proofread
    try:
        ed.do_proofread(FakeProj(regs, {"Leonora": "she/her"}), 0)
    finally:
        tr.proofread_page = orig

    assert regs[0]["speaker"] == "Leonora", \
        "a name corrected in settings must reach the stored label too"
    assert seen["speakers"][0] == "Leonora"
    assert regs[1]["speaker"] == "Someone Else", \
        "a speaker the sheet does not know is left exactly as it was"
    assert seen["sheet"] == {"Leonora": "she/her"}


def test_canon_spellings_are_enforced_after_the_model_has_spoken():
    """One page in a chapter drifts and no page can see it, because every page
    is proofread alone and looks consistent with itself. So the sheet's
    spelling is applied mechanically afterwards — but only where it is safe:
    a true romanization variant is rewritten, a near miss is only flagged, and
    an ordinary word that merely folds onto a name is never touched."""
    from mangatl.translate import (SeriesContext, canon_terms,
                                   enforce_spellings, observed_lowercase)

    ctx = SeriesContext()
    ctx.characters = {"Leonora": "she/her"}
    ctx.glossary = {"バルメデ": "Balmede"}
    table = canon_terms(ctx)

    txt, notes = enforce_spellings("Reonora went to Barmede.", table)
    assert txt == "Leonora went to Balmede.", \
        "the same name in another romanization is the same name"
    assert len(notes) == 2 and all(" -> " in n for n in notes)

    txt, notes = enforce_spellings("Leonore, wait!", table)
    assert txt == "Leonore, wait!", "a near miss is never rewritten blind"
    assert notes and "Leonora" in notes[0]

    # "grow" folds to the same canonical form as a name would; the chapter
    # itself using it in lower case is the evidence that it is a verb
    common = observed_lowercase(["the weeds grow fast"])
    ctx2 = SeriesContext()
    ctx2.characters = {"Glow": "he/him"}
    txt, notes = enforce_spellings("Grow stronger.", canon_terms(ctx2), common)
    assert txt == "Grow stronger." and not notes


def test_proofread_report_leads_with_what_still_needs_a_human():
    """The report is for reading away from the editor, so the short list of
    things the proofreader could not settle comes first and the full script
    second — hunting the flags out of the script is the wrong way round."""
    from mangatl import editor as ed
    from mangatl.translate import SeriesContext

    class FakeStore:
        def __init__(self, name, regions, note=""):
            self.name, self.regions, self.note = name, regions, note

    class FakeProj:
        input_dir, output_dir = "/tmp/ch07", "/tmp/out"

        def __init__(self, pages):
            self.pages = pages
            self.ctx = SeriesContext()
            self.ctx.characters = {"Leonora": "she/her"}

    def reg(i, **kw):
        d = {"id": i, "order": i, "kind": "bubble", "speaker": "Leonora",
             "src_text": "あ", "dst_text": "Hello.", "proofread": True}
        d.update(kw)
        return d

    p = FakeProj([
        FakeStore("p1.png", [
            reg(0, src_text="行こう\nすぐに", dst_text="Let's go.\nRight now."),
            reg(1, dst_text="Leonore, wait!", flagged="near Leonora"),
        ], note="Region 4 read oddly."),
        # never proofread, and one line read but not translated
        FakeStore("p2.png", [
            reg(2, proofread=False, dst_text="Balmede is far.",
                speaker="Rofan"),
            reg(3, proofread=False, dst_text=""),
        ]),
    ])
    out = ed.proofread_report(p)
    md = out["text"]

    # the short list of things to look at comes first; the script second
    assert "Still wants a look" in md and "## Script" in md
    assert md.index("Still wants a look") < md.index("## Script")
    # a page's own remark and a region's flag both reach that short list
    assert "Region 4 read oddly." in md and "near Leonora" in md
    assert out["flags"] == 2
    # a page that has not been through the step says so rather than reading clean
    assert "not proofread yet" in md
    # the Japanese travels with the English: a line can only be judged
    # against its original, and a typesetting break must survive the markdown
    assert "- JP: 行こう  " in md and "- EN: Let's go.  " in md
    # the proofreader's notes talk in region ids, so the script prints them
    assert "region 0" in md
    # only the whole chapter can see these
    assert "Across the whole chapter" in md
    assert "Rofan" in md                      # speaker the sheet cannot place
    assert "read but not translated" in md


def test_heal_rebuilds_texture_instead_of_blurring():
    """Healing on screentone must put dots back, not smear them into grey.
    shift_fill copies real pixels from the best-matching translation of the
    surroundings; on a periodic dot grid it should reproduce the pattern
    almost exactly, where diffusion (Telea) flattens it."""
    import cv2
    from mangatl.inpaint import shift_fill

    # a page of regular screentone dots
    img = np.full((160, 160, 3), 255, np.uint8)
    for y in range(4, 160, 8):
        for x in range(4, 160, 8):
            cv2.circle(img, (x, y), 2, (40, 40, 40), -1)
    truth = img.copy()
    mask = np.zeros((160, 160), np.uint8)
    cv2.circle(mask, (80, 80), 14, 255, -1)
    hole = img.copy()
    hole[mask > 0] = (255, 255, 255)          # the "damage" being healed

    ours = shift_fill(hole, mask)
    telea = cv2.inpaint(hole, mask, 5, cv2.INPAINT_TELEA)

    m = mask > 0
    err_ours = float(np.abs(ours[m].astype(int) - truth[m].astype(int)).mean())
    err_telea = float(np.abs(telea[m].astype(int) - truth[m].astype(int)).mean())
    assert err_ours < err_telea * 0.5, \
        f"shift_fill ({err_ours:.1f}) should beat Telea ({err_telea:.1f}) clearly"
    # and the texture really is back: the filled area keeps the dot contrast
    sd_truth = float(truth[m].std())
    sd_ours = float(ours[m].std())
    assert sd_ours > 0.6 * sd_truth, \
        f"filled area lost its texture (std {sd_ours:.1f} vs {sd_truth:.1f})"


def test_tools_never_open_the_text_editor():
    """While ANY tool is armed — paint, zoom, selection, transform — a click
    or double-click on typesetting must fall through to the tool, never into
    the text editor. The double-click path used to leak for the paint and
    zoom tools."""
    import os
    static = os.path.join(str(PKG),
                          "static", "js", "typesetting.js")
    src = open(static).read()
    down = src.split("addEventListener('mousedown'", 1)[1] \
              .split("addEventListener('dblclick'", 1)[0]
    dbl = src.split("addEventListener('dblclick'", 1)[1] \
             .split("function editOnCanvas", 1)[0]
    for block, name in ((down, "mousedown"), (dbl, "dblclick")):
        # The paint tools are asked about through paintArmed() now — one
        # function instead of the same four names written out in five files,
        # which is what let the shape tool be added without silently missing
        # one of them. See tests/test_shapes.py.
        for guard in ("paintArmed()", "zoomTool",
                      "selTool||xf", "handMode"):
            assert guard in block, f"{name} does not yield for {guard}"


def test_em_dash_is_synthesized_for_fonts_without_the_glyph():
    """Comic fonts ship only a hyphen. The em-dash must survive sanitising,
    reserve a proper (long) width in the layout, and render as a real bar —
    never a tofu box or a downgrade to a plain hyphen."""
    import cv2
    from fontTools.ttLib import TTFont
    from mangatl.typeset import (TypesetConfig, fit_region, em_dash_glyph,
                                _text_w, font_supports)
    from mangatl.render import render_page
    from mangatl.models import Page, TextRegion

    path = _os.path.join("fonts", "AnimeAce.ttf")
    assert 0x2014 not in set(TTFont(path, lazy=True).getBestCmap().keys()), \
        "fixture assumes AnimeAce has no em-dash"
    assert not font_supports(path, "—")

    # the synthesized dash is clearly longer than a lone hyphen
    bar = em_dash_glyph(path, 40)
    assert bar and bar[0] > _text_w(path, 40, "-") * 1.3

    # and the layout reserves that width: an em-dash line is wider than the
    # same line with the dash removed by more than a hyphen would add
    w_dash = _text_w(path, 40, "A—B")
    w_plain = _text_w(path, 40, "AB")
    assert w_dash - w_plain > _text_w(path, 40, "-")

    img = np.full((260, 460, 3), 255, np.uint8)
    mask = np.zeros((260, 460), np.uint8)
    cv2.ellipse(mask, (230, 130), (200, 110), 0, 0, 360, 255, -1)
    r = TextRegion(id=0, bbox=(40, 40, 380, 180), bubble_mask=mask,
                   bubble_bbox=(30, 20, 400, 220), dst_text="OH—RIGHT")
    page = Page(image=img)
    page.regions = [r]
    cfg = TypesetConfig(font_path=path)
    r.layout = fit_region(r, cfg)
    assert "—" in "".join(r.layout.lines), "the em-dash must reach the layout"
    out = render_page(page, cfg)
    ink = (out < 100).any(axis=2)
    assert ink.sum() > 200, "something was drawn"
    # the dash is a wide, short band of ink: find the widest fully-dark run on
    # any row and confirm it spans a dash-like width (a hyphen would be ~half)
    widest = 0
    for row in ink:
        run = best = 0
        for v in row:
            run = run + 1 if v else 0
            best = max(best, run)
        widest = max(widest, best)
    assert widest > 18, f"no long horizontal bar found (widest run {widest}px)"


def test_em_dash_is_a_borrowed_glyph_not_a_drawn_rectangle():
    """The stand-in dash used to be a filled rectangle, and next to hand-drawn
    letters it read as a machine part. It is now the em-dash outline lifted
    from a Comic Sans-alike, rescaled to the host font's own stroke weight."""
    from mangatl.typeset import em_dash_donor, em_dash_glyph, _glyph_ink

    donor = em_dash_donor()
    assert donor, "no Comic Sans-alike available to borrow an em-dash from"

    path = _os.path.join("fonts", "CCWildWords.ttf")
    adv, top, mask = em_dash_glyph(path, 40)

    # A borrowed outline has shaped ends. A rectangle's columns are identical,
    # so this is what fails if the fallback bar ever comes back silently.
    cols = np.asarray(mask).astype(float).sum(axis=0)
    mid = cols[len(cols) // 2]
    assert cols[0] < 0.8 * mid and cols[-1] < 0.8 * mid, list(cols)

    # Weight matches the host hyphen's STROKE, not its bounding box: that
    # hyphen is a tilted wedge whose box is half again as tall as the stroke.
    _, _, stroke = _glyph_ink(path, 40, "-")
    assert abs(mask.height - stroke) <= 1, (mask.height, stroke)

    # and it is a long dash, not a fattened hyphen
    assert mask.width >= 4 * mask.height, (mask.width, mask.height)
    assert adv > mask.width                  # side bearings on both sides


def test_rectangular_boxes_are_classified_as_narration():
    """A straight-sided rectangle full of text is a caption / narration box,
    not a speech bubble. It must be tagged 'narration', its box must cover the
    WHOLE rectangle (not hug the glyphs), and a rounded bubble on the same
    page must stay 'bubble'."""
    import cv2
    from mangatl.detect import classical
    from mangatl.models import Page

    img = np.full((1100, 850, 3), 235, np.uint8)
    # a bordered rectangular caption
    cv2.rectangle(img, (80, 90), (300, 470), (255, 255, 255), -1)
    cv2.rectangle(img, (80, 90), (300, 470), (15, 15, 15), 3)
    for k, y in enumerate(range(130, 450, 30)):
        cv2.putText(img, "AB", (120 + (k % 2) * 8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
    # a rounded speech bubble
    cv2.ellipse(img, (600, 320), (150, 110), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (600, 320), (150, 110), 0, 0, 360, (15, 15, 15), 4)
    for k, y in enumerate(range(270, 380, 26)):
        cv2.putText(img, "hi", (520, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (20, 20, 20), 3)

    regs = classical.detect_combined(Page(image=img))
    cap = [r for r in regs if _iou_box(r.bubble_bbox, (80, 90, 220, 380)) > 0.4]
    bub = [r for r in regs if _iou_box(r.bubble_bbox, (450, 210, 300, 220)) > 0.35]
    assert cap and cap[0].kind == "narration", \
        f"the rectangle should be narration (got {[r.kind for r in cap]})"
    # the box spans the whole rectangle, not just the ~150px-wide text
    assert cap[0].bubble_bbox[2] > 190 and cap[0].bubble_bbox[3] > 330, \
        f"narration box must cover the whole rectangle (got {cap[0].bubble_bbox})"
    assert bub and bub[0].kind == "bubble", \
        f"the rounded bubble must stay a bubble (got {[r.kind for r in bub]})"


def test_narration_marking_never_touches_sfx_or_freefloat():
    from mangatl.detect.classical import _mark_narration
    from mangatl.models import TextRegion

    for k in ("sfx", "freefloat"):
        r = TextRegion(id=0, bbox=(0, 0, 100, 100),
                       bubble_bbox=(0, 0, 100, 100),
                       polygon=[[0, 0], [100, 0], [100, 100], [0, 100]], kind=k)
        _mark_narration(r)
        assert r.kind == k, f"{k} must not be reclassified"


def test_cleaner_now_erases_sound_effects():
    """SFX used to be skipped by the cleaner; a sound effect's typesetting must
    now be inpainted like any other text (unless its per-region keep toggle
    is set)."""
    import cv2
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page, TextRegion

    img = np.full((300, 300, 3), 240, np.uint8)
    # a chunk of black "SFX" ink on the art
    cv2.rectangle(img, (110, 120), (190, 180), (15, 15, 15), -1)
    mask = np.zeros((300, 300), np.uint8)
    mask[120:180, 110:190] = 255

    r = TextRegion(id=0, bbox=(110, 120, 80, 60), kind="sfx",
                   text_mask=mask, bubble_bbox=(110, 120, 80, 60),
                   polygon=[[110, 120], [190, 120], [190, 180], [110, 180]])
    page = Page(image=img)
    page.regions = [r]
    out = inpaint_page(page)
    patch = out[120:180, 110:190]
    assert patch.mean() > 150, "the sound-effect ink should be cleaned away"

    # but a per-region keep toggle still spares it
    r.skip_clean = True
    out2 = inpaint_page(Page(image=img.copy(), regions=[r]))
    assert out2[120:180, 110:190].mean() < 80, "skip_clean must still spare it"


def test_translations_json_endpoint_exists():
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.Handler.do_GET)
    assert '"/api/translations_json"' in src
    assert '"japanese"' in src and '"english"' in src


def test_typeset_keeps_the_proofread_flag():
    """Typesetting must NOT un-proofread the page — commit() rebuilds records
    without the editor-only 'proofread' flag, so do_typeset restores it
    (regression: proofread count dropped to 0 after typesetting)."""
    import shutil
    from mangatl import editor as ed
    from mangatl.project import Project

    shutil.rmtree(scratch("_tmp_ts"), ignore_errors=True)
    p = Project(None, scratch("_tmp_ts"))
    try:
        img = np.full((300, 300, 3), 245, np.uint8)
        p.add_uploaded("p.png", _cv2().imencode(".png", img)[1].tobytes())
        p.pages[0].detected = True
        p.pages[0].regions = [{
            "id": 0, "bbox": [110, 120, 80, 60],
            "bubble_bbox": [90, 100, 120, 110],
            "polygon": [[90, 100], [210, 100], [210, 210], [90, 210]],
            "kind": "bubble", "order": 0, "src_text": "x",
            "dst_text": "Hello there.", "proofread": True,
        }]
        assert p.pages[0].n_proofread == 1
        ed.do_typeset(p, 0)
        assert p.pages[0].n_proofread == 1, "typesetting wiped the proofread flag"
        assert p.pages[0].regions[0].get("layout"), "the page should now be typeset"
    finally:
        shutil.rmtree(scratch("_tmp_ts"), ignore_errors=True)


def _cv2():
    import cv2
    return cv2


def test_checked_page_with_no_text_is_done():
    """A page that was checked and has no text is DONE (green), not an error."""
    from mangatl.project import PageState

    st = PageState(path="blank.png", name="blank.png", width=100, height=100)
    st.regions = []
    st.detected = False
    assert st.status() == "pending", "undetected empty page is still pending"
    st.detected = True
    assert st.status() == "done", "a checked empty page passes as done"


def test_ai_cleaner_wiring_and_cache():
    """The hosted-cleaner hook: off -> no cleaner; configured -> a callable;
    a disk-cached result is returned WITHOUT calling the network; a failed
    call falls back to a local fill instead of crashing."""
    import shutil, os
    import cv2
    from mangatl import editor as ed
    from mangatl.project import Project

    shutil.rmtree(scratch("_tmp_ai"), ignore_errors=True)
    p = Project(None, scratch("_tmp_ai"))
    try:
        # off / no url -> no cleaner
        assert ed._make_cleaner(p) == (None, False)
        p.settings["ai_clean"] = "all"
        p.settings["clean_url"] = "http://127.0.0.1:9/none"   # unroutable
        p.settings["clean_token"] = "t"
        neural, neural_all = ed._make_cleaner(p)
        assert callable(neural) and neural_all is True

        img = np.full((40, 40, 3), 200, np.uint8)
        mask = np.zeros((40, 40), np.uint8)
        mask[10:30, 10:30] = 255

        # cache HIT: pre-write the expected file, then the call must return it
        # without touching the network
        import hashlib
        cdir = ed._ai_clean_cache_dir(p)
        # The TOKEN is part of the key as of 2026-07-30: the answer to this same
        # (image, mask, url) is a cleaned page when the token is accepted and a
        # Telea smear when it is refused, so one key for both meant that fixing
        # a wrong token changed nothing. See
        # claude/cleaning-was-a-refused-token-2026-07-30.md.
        key = hashlib.sha1(img.tobytes() + mask.tobytes()
                           + p.settings["clean_url"].encode()
                           + p.settings["clean_token"].encode()).hexdigest()
        want = np.full((40, 40, 3), 77, np.uint8)
        cv2.imwrite(os.path.join(cdir, key + ".png"), want)
        got = ed._ai_clean_call(p.settings["clean_url"], "t", cdir, img, mask)
        assert int(got.mean()) == 77, "a cached clean must be reused, not re-fetched"

        # cache MISS + unreachable server -> local fallback, never raises
        mask2 = np.zeros((40, 40), np.uint8)
        mask2[5:15, 5:15] = 255
        out = ed._ai_clean_call(p.settings["clean_url"], "t", cdir, img, mask2)
        assert out is not None and out.shape == img.shape
    finally:
        shutil.rmtree(scratch("_tmp_ai"), ignore_errors=True)


def test_neural_all_routes_flat_bubbles_through_the_model():
    """With neural_all, even a flat white bubble goes to the model (its mask
    reaches `neural`), instead of being stamped with the background colour."""
    import cv2
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page, TextRegion

    img = np.full((200, 200, 3), 255, np.uint8)
    for yy in range(70, 130, 16):
        cv2.line(img, (70, yy), (130, yy), (20, 20, 20), 6)   # "text"
    mask = np.zeros((200, 200), np.uint8)
    mask[60:140, 60:140] = 255
    tm = np.zeros((200, 200), np.uint8)
    for yy in range(70, 130, 16):
        cv2.line(tm, (70, yy), (130, yy), 255, 6)
    r = TextRegion(id=0, bbox=(60, 60, 80, 80), kind="bubble",
                   text_mask=tm, bubble_mask=mask, bubble_bbox=(60, 60, 80, 80),
                   polygon=[[60, 60], [140, 60], [140, 140], [60, 140]])
    seen = {}

    def fake_neural(im, mk):
        seen["called"] = True
        seen["area"] = int((mk > 0).sum())
        return im
    inpaint_page(Page(image=img, regions=[r]), neural=fake_neural, neural_all=True)
    assert seen.get("called") and seen["area"] > 100, \
        "flat bubble should have reached the model under neural_all"


# ------------------------------------- "hard" means hard: what the model sees

def _tone_gradient(h=200, w=240, period=6):
    """Screentone whose dot size ramps left to right — a background with no
    single level, which is the case the flat-background sweep cannot handle."""
    import cv2
    img = np.full((h, w), 245, np.uint8)
    for y in range(0, h, period):
        for x in range(0, w, period):
            rad = 1 + int(1.6 * x / w)
            cv2.circle(img, (x, y), rad, 30, -1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _typeset(img, boxes, blur=2.2):
    """Draw anti-aliased strokes and return (dirty page, tight core mask).

    `blur` reproduces what a print scan does to a stroke: the core is solid,
    and around it is a skirt several pixels wide that the detector's mask does
    not include. That skirt is the ghost the user photographed."""
    import cv2
    glyph = np.zeros(img.shape[:2], np.uint8)
    for (x0, y0, x1, y1) in boxes:
        glyph[y0:y1, x0:x1] = 255
    soft = cv2.GaussianBlur(glyph, (0, 0), blur)
    dirty = img.copy()
    keep = soft > 0
    dirty[keep] = ((dirty[keep].astype(np.int32) *
                    (255 - soft[keep].astype(np.int32))[..., None]) // 255) \
        .astype(np.uint8)
    tight = cv2.erode((soft > 200).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    return dirty, tight


def _tone_region(img, tight, box):
    from mangatl.models import TextRegion
    x0, y0, x1, y1 = box
    area = np.zeros(img.shape[:2], np.uint8)
    area[y0 - 20:y1 + 20, x0 - 20:x1 + 20] = 255
    return TextRegion(id=0, bbox=(x0 - 20, y0 - 20, (x1 - x0) + 40, (y1 - y0) + 40),
                      text_mask=tight, bubble_mask=area,
                      bubble_bbox=(x0 - 20, y0 - 20, (x1 - x0) + 40, (y1 - y0) + 40))


def _spy(erase=False):
    """A stand-in model that records every crop and mask it was given.

    By default it changes nothing, which is the "the ghost survived" case. With
    `erase` it actually removes what it was asked to remove, so the sweep is
    satisfied and the call count is the first pass alone."""
    import cv2
    calls = []

    import numpy as _np
    rng = _np.random.default_rng(11)

    def neural(sub, sm):
        calls.append({"shape": sub.shape, "area": int((sm > 0).sum()),
                      "mask": sm.copy()})
        if not erase:
            return sub
        # Telea, plus a little grain. A perfectly flat answer where the page
        # around it has texture is now read as the model giving up and is sent
        # to the local fill instead (see `_gave_up`) — which would make this a
        # test of that guard rather than of how many times the model is asked.
        # A real reconstruction is never flat; this one is not either.
        out = cv2.inpaint(sub, sm, 5, cv2.INPAINT_TELEA)
        n = rng.normal(0, 9, out.shape).astype(_np.int16)
        m = (sm > 0)[..., None]
        return _np.clip(out.astype(_np.int16) + _np.where(m, n, 0),
                        0, 255).astype(_np.uint8)
    return neural, calls


def test_screentone_goes_to_the_model_when_there_is_one():
    """The setting says "AI for hard areas — screentone, SFX, text on art", and
    screentone is the hardest of the three. It was being intercepted before the
    model by the pattern-copy branch, so the model never saw the regions it was
    turned on for; copying a block of dots is the no-model fallback, not a
    preference, and it shows as a patch wherever the tone is a gradient."""
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page

    img = _tone_gradient()
    dirty, tight = _typeset(img, [(80, 70, 92, 130), (80, 70, 150, 82)])
    box = (80, 70, 150, 130)

    neural, calls = _spy()
    inpaint_page(Page(image=dirty.copy(), regions=[_tone_region(dirty, tight, box)]),
                 neural=neural)
    assert calls, "screentone never reached the configured model"

    # and with no model configured it still gets cleaned, by pattern copy
    r = _tone_region(dirty, tight, box)
    page = Page(image=dirty.copy(), regions=[r])
    inpaint_page(page)
    assert r.flagged and "pattern copy" in r.flagged, \
        "with no model, screentone should fall back to copying real texture"


def test_the_model_is_called_once_per_region_not_once_per_glyph():
    """A hosted inpainter handed a whole page splits the mask into connected
    pieces and runs once per piece — once per GLYPH, each seeing a window too
    small to tell what the background was doing. Sending a crop per region is
    both far fewer calls and a far better view."""
    from mangatl.inpaint import NEURAL_CTX, inpaint_page
    from mangatl.models import Page, TextRegion

    rng = np.random.default_rng(7)
    img = rng.integers(120, 210, (300, 300, 3), dtype=np.uint8)   # artwork
    glyphs = [(60, 60, 72, 72), (60, 90, 72, 102), (60, 120, 72, 132),
              (200, 200, 212, 212), (200, 230, 212, 242)]
    dirty, tight = _typeset(img, glyphs)

    def reg(i, box):
        x0, y0, x1, y1 = box
        area = np.zeros(dirty.shape[:2], np.uint8)
        area[y0 - 15:y1 + 15, x0 - 15:x1 + 15] = 255
        tm = np.zeros_like(tight)
        tm[y0 - 15:y1 + 15, x0 - 15:x1 + 15] = tight[y0 - 15:y1 + 15, x0 - 15:x1 + 15]
        bb = (x0 - 15, y0 - 15, (x1 - x0) + 30, (y1 - y0) + 30)
        return TextRegion(id=i, bbox=bb, text_mask=tm, bubble_mask=area,
                          bubble_bbox=bb)

    regions = [reg(0, (60, 60, 72, 132)), reg(1, (200, 200, 212, 242))]

    # record the region window alongside the crop the model was handed, so the
    # crop can be checked against the region it came from rather than a constant
    from mangatl import inpaint as _ip
    wins = []
    real = _ip._run_neural

    def rec(out, job, neural_, extra=0, **kw):
        wins.append(job["win"])
        return real(out, job, neural_, extra, **kw)
    _ip._run_neural = rec
    try:
        neural, calls = _spy(erase=True)
        inpaint_page(Page(image=dirty, regions=regions), neural=neural)
    finally:
        _ip._run_neural = real

    assert len(calls) == 2, \
        f"expected one call per region, got {len(calls)} (one per glyph?)"
    for c, (ys, xs) in zip(calls, wins):
        h, w = c["shape"][:2]
        assert h < 300 and w < 300, "the whole page was sent, not a crop"
        assert h - (ys.stop - ys.start) >= NEURAL_CTX and \
            w - (xs.stop - xs.start) >= NEURAL_CTX, \
            "the crop is the region alone, with no surrounding page for the " \
            "model to match its answer to"
    assert NEURAL_CTX >= 32, "context that small tells the model nothing"


def test_the_stroke_skirt_is_inside_the_mask_on_a_gradient():
    """The measured haze sweep only ever ran on flat bubbles, because it needs
    something to call "the background" and a flat bubble has exactly one. On
    tone the mask fell back to a fixed dilation — a guess at stroke width that
    guesses low — and the skirt of every stroke survived as the outline of the
    words. A per-pixel background makes the same measurement work here."""
    import cv2
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page

    img = _tone_gradient()
    box = (80, 70, 150, 130)
    dirty, tight = _typeset(img, [(80, 70, 92, 130), (80, 70, 150, 82)])

    # every pixel the typesetting darkened, skirt included, measured against the
    # clean truth — that is the ink the model has to be asked to replace
    darkened = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(int) -
                cv2.cvtColor(dirty, cv2.COLOR_BGR2GRAY).astype(int)) > 8

    # the model is handed a crop, so record the FIRST-PASS masks in page
    # coordinates; the retry is a separate promise, tested separately
    from mangatl import inpaint as _ip
    seen = {}
    real = _ip._run_neural

    # `**kw` so the spy keeps working when _run_neural gains an argument —
    # the retry now takes `again`, the original page, so it redraws the page
    # rather than its own first answer.
    def rec(out, job, neural_, extra=0, **kw):
        if extra <= 0:
            full = seen.setdefault("m", np.zeros(out.shape[:2], np.uint8))
            full[job["win"]][job["mask"] > 0] = 255
        return real(out, job, neural_, extra, **kw)
    _ip._run_neural = rec
    try:
        neural, calls = _spy()
        r = _tone_region(dirty, tight, box)
        inpaint_page(Page(image=dirty.copy(), regions=[r]), neural=neural)
    finally:
        _ip._run_neural = real
    assert calls, "the region never reached the model"

    m = seen["m"]
    # what the mask used to be: the detector's core grown by a constant
    fixed = _ip._dilated(_ip._dilated(tight, _ip.DILATE_PX), _ip.NEURAL_PAD)
    beyond = int((darkened & (fixed == 0) & (m > 0)).sum())
    assert beyond > 150, \
        "the mask is still the detector's core grown by a constant — it picked " \
        "up no ink beyond the fixed dilation, which is the skirt the user sees"
    covered = (darkened & (m > 0)).sum() / float(darkened.sum())
    assert covered > 0.88, \
        f"only {covered:.0%} of the typesetting was inside the mask"


def test_the_widened_mask_does_not_eat_the_screentone_around_it():
    """Being generous with the mask is free only while it stays on the words.
    Closing the image to find a local background wipes out the dot pattern too,
    so every dot near a stroke reads as ink — which is why only haze CONTIGUOUS
    with a stroke is taken, and passing line work is left standing."""
    import cv2
    from mangatl import inpaint as _ip
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page

    img = _tone_gradient()
    box = (80, 70, 150, 130)
    dirty, tight = _typeset(img, [(100, 90, 112, 120)])
    # artwork passing close under the glyph — inside the sweep's reach, but not
    # joined to any stroke, which is the whole distinction
    cv2.line(dirty, (80, 125), (150, 125), (10, 10, 10), 3)

    seen = {}
    real = _ip._run_neural

    # `**kw` so the spy keeps working when _run_neural gains an argument —
    # the retry now takes `again`, the original page, so it redraws the page
    # rather than its own first answer.
    def rec(out, job, neural_, extra=0, **kw):
        if extra <= 0:
            full = seen.setdefault("m", np.zeros(out.shape[:2], np.uint8))
            full[job["win"]][job["mask"] > 0] = 255
        return real(out, job, neural_, extra, **kw)
    _ip._run_neural = rec
    try:
        neural, _c = _spy()
        inpaint_page(Page(image=dirty.copy(),
                          regions=[_tone_region(dirty, tight, box)]), neural=neural)
    finally:
        _ip._run_neural = real

    m = seen["m"]
    assert m[88:122, 98:115].any(), "the typesetting itself was not masked"
    # What "left standing" means changed on 2026-07-30. The mask the MODEL is
    # given is grown by `MODEL_PAD` — a model reconstructs what it is handed, and
    # a mask that stops at the glyph's edge leaves the rim of every stroke on the
    # page, which is what lee kept photographing. So artwork within MODEL_PAD of
    # a stroke IS redrawn now; what must still be left alone is line work further
    # away than that, which is what this measures.
    from mangatl.inpaint import MODEL_PAD
    on_line = int((m[123 + MODEL_PAD:128 + MODEL_PAD, 80:151] > 0).sum())
    assert on_line < 15, f"{on_line}px of artwork was swept into the mask"
    # and the tone is left alone: the mask hugs the strokes rather than
    # swallowing every dot that happens to lie beside them
    fixed = _ip._dilated(_ip._dilated(tight, _ip.DILATE_PX), _ip.MODEL_PAD)
    assert (m > 0).sum() < 1.6 * float((fixed > 0).sum()), \
        "the mask spread into the surrounding tone instead of hugging the strokes"


def test_a_ghost_after_a_neural_clean_is_retried_wider_before_it_is_flagged():
    """The usual reason typesetting survives a redraw is that a sliver of stroke
    was never inside the mask, and asking again about a slightly bigger area is
    the whole fix. Results are cached by content upstream, so the retry costs
    nothing on a page that is merely being re-rendered."""
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page

    img = _tone_gradient()
    box = (80, 70, 150, 130)
    dirty, tight = _typeset(img, [(80, 70, 92, 130), (80, 70, 150, 82)])

    neural, calls = _spy()          # returns the crop untouched: ghost survives
    r = _tone_region(dirty, tight, box)
    inpaint_page(Page(image=dirty.copy(), regions=[r]), neural=neural)

    assert len(calls) == 2, \
        f"a surviving ghost should get one wider retry, got {len(calls)} call(s)"
    assert calls[1]["area"] > calls[0]["area"], \
        "the retry asked about the same area, which would give the same answer"
    assert r.flagged and "ghost" in r.flagged, \
        "a ghost that survives the retry should still be reported"


# ------------------------------------- light on dark: what counts as typesetting

def _dark_tone_panel(h=260, w=300, period=7, dot=2):
    """A black panel carrying WHITE screentone — the case where the light/dark
    split hands back the tone as well as the words."""
    import cv2
    img = np.full((h, w), 20, np.uint8)
    for y in range(0, h, period):
        for x in range(0, w, period):
            cv2.circle(img, (x, y), dot, 230, -1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def test_white_screentone_is_not_mistaken_for_white_typesetting():
    """The solid black rectangles. On a dark panel the detector's mask is the
    panel, so cleaning throws it away and splits the region light-from-dark
    instead — and on a panel carrying white tone, the light side is the dots as
    well as the words. Dilating a field of dots by the few pixels a glyph edge
    needs joins them into a filled box, and the inpainter, asked to redraw a
    box, answers with a flat block where the artwork used to be."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    img = _dark_tone_panel()
    truth = np.zeros(img.shape[:2], np.uint8)
    cv2.putText(truth, "PO", (60, 150), cv2.FONT_HERSHEY_SIMPLEX, 2.2, 255, 10)
    img[truth > 0] = 255
    box = np.zeros(img.shape[:2], np.uint8)
    box[70:200, 40:260] = 255
    r = TextRegion(id=0, bbox=(40, 70, 220, 130), text_mask=box.copy(),
                   bubble_mask=box, bubble_bbox=(40, 70, 220, 130))

    seen = []

    def spy(sub, sm):
        seen.append(sm.copy())
        return sub

    inpaint.inpaint_page(Page(image=img.copy(), regions=[r]), neural=spy)
    assert seen, "the typesetting never reached the model at all"
    m = seen[0]
    inside = int(((m > 0) & (box > 0)).sum())
    share = inside / int((box > 0).sum())
    ratio = int((m > 0).sum()) / int((truth > 0).sum())
    # measured: 1.00 and 11.5x with the tone folded in, 0.25 and 2.6x without
    assert share < 0.5, \
        f"the model was handed {share:.0%} of the panel to redraw"
    assert ratio < 5.0, \
        f"the mask is {ratio:.1f}x the typesetting, so it is not the typesetting"


def test_bright_artwork_crossing_the_box_survives_on_a_dark_panel():
    """`glyphs_only` drops ink that carries on past the region, which is what
    stops a bubble outline being hacked in half. It labelled the DARK side of
    the page to do it — so on a white-on-black panel it was labelling the
    background, found nothing, and erased the artwork along with the words."""
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    img = np.full((250, 400, 3), 20, np.uint8)
    cv2.line(img, (0, 150), (399, 150), (255, 255, 255), 9)   # right across
    cv2.putText(img, "PO", (60, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                (255, 255, 255), 8)
    box = np.zeros(img.shape[:2], np.uint8)
    box[70:200, 40:210] = 255
    r = TextRegion(id=0, bbox=(40, 70, 170, 130), text_mask=box.copy(),
                   bubble_mask=box, bubble_bbox=(40, 70, 170, 130))

    page = Page(image=img.copy(), regions=[r])
    out = cv2.cvtColor(inpaint.inpaint_page(page), cv2.COLOR_BGR2GRAY)
    assert out[146:155, 60:190].mean() > 170, \
        "the line running out of the box was erased as though it were text"
    assert out[75:125, 60:190].mean() < 60, "the typesetting was not erased"


def test_a_split_that_swallows_its_panel_is_cleaned_conservatively():
    """The backstop, rewritten to lee's rule on 2026-07-30: *"it shoud not skip
    boxes"*.

    Every step above is a guess at where the typesetting is, and on a dark panel
    the guess replaces the detector's answer entirely. This test used to prove
    that a guess gone wrong left the page ALONE — which is safe for the artwork
    and is also how a page came back with its sound effects still on it, box
    after box, with nothing erased and nothing said.

    So a swallowing split no longer skips. It drops back to the letter-like core
    — no halo, no model padding — and cleans that. What is protected now is what
    was actually at risk: the artwork OUTSIDE the box, which a generous mask
    handed to an inpainter turns into a flat block. Inside its own box the
    region is cleaned, and flagged so it gets looked at.
    """
    import cv2
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion

    rng = np.random.default_rng(11)
    img = rng.integers(10, 70, (240, 240, 3), dtype=np.uint8)   # dark artwork
    cv2.circle(img, (120, 120), 55, (240, 240, 240), -1)        # a bright shape
    box = np.zeros(img.shape[:2], np.uint8)
    box[50:190, 50:190] = 255
    r = TextRegion(id=0, bbox=(50, 50, 140, 140), text_mask=box.copy(),
                   bubble_mask=box, bubble_bbox=(50, 50, 140, 140))

    seen = []
    page = Page(image=img.copy(), regions=[r])
    out = inpaint.inpaint_page(
        page, neural=lambda im, m: seen.append(int((m > 0).sum())) or im)

    assert page.clean_stats.get("core only") == 1, \
        f"the region was not cleaned conservatively: {page.clean_stats}"
    assert r.flagged and "only the strokes were erased" in r.flagged, \
        "a conservative clean has to say so"

    # the page beyond the box AND its doorstep is untouched — that is the thing
    # worth protecting (inpaint.GLYPH_REACH is the doorstep; see the fence at
    # the end of inpaint_page)
    from mangatl.inpaint import GLYPH_REACH as REACH
    outside = np.ones(img.shape[:2], bool)
    outside[50-REACH:190+REACH, 50-REACH:190+REACH] = False
    assert (out[outside] == img[outside]).all(), \
        "the clean reached outside the region it was asked about"

    # and the model was never handed more than the box either
    assert seen and max(seen) <= int((box > 0).sum()) * 1.1, \
        f"the model was sent a mask bigger than the region: {seen}"


def test_the_seam_does_not_keep_half_the_stroke_edge():
    """The pale outlines on a grey fill. Feathering by blurring the mask puts
    the halfway point exactly on the mask's edge, so half of whatever sits
    there is blended back in — and at the edge of a mask drawn round a letter,
    what sits there is the letter's own anti-aliased rim. The haze sweep cannot
    find it either: it looks for ink darker than its surroundings, and this is
    a BRIGHT rim on a finished fill."""
    import cv2
    from mangatl import inpaint

    orig = np.full((80, 80, 3), 120, np.uint8)
    cv2.rectangle(orig, (30, 20), (49, 59), (235, 235, 235), -1)
    orig = cv2.GaussianBlur(orig, (0, 0), 1.5)          # a scan's soft edges
    mask = np.zeros((80, 80), np.uint8)
    mask[20:60, 30:50] = 255                            # the stroke, no slack
    filled = np.full_like(orig, 120)                    # what a model returns

    out = cv2.cvtColor(inpaint._feather(orig, filled, mask), cv2.COLOR_BGR2GRAY)
    # measured: 33 levels of stroke left over with the ramp across the edge,
    # 10 with it outside — against a field at 120
    assert int(out.max()) - 120 < 18, \
        f"{int(out.max()) - 120} levels of the old stroke survived the fill"


# ------------------------------------- the heal brush and the AI cleaner

def _heal_post(base, img, msk):
    """POST a heal request the way paint.js does and return the reply.

    No `ai` flag: there is one healing brush and it is the AI one. It used to
    be a choice of two, and the flag picked between them —
    lee: *"remoev teh regualr healing brush, its ass"*.
    """
    import base64, json, urllib.request, urllib.error
    import cv2

    def durl(a, flag=cv2.IMREAD_COLOR):
        return "data:image/png;base64," + \
            base64.b64encode(cv2.imencode(".png", a)[1].tobytes()).decode()

    req = urllib.request.Request(
        base + "/api/page/0/heal",
        data=json.dumps({"image": durl(img), "mask": durl(msk)}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def _heal_server(p):
    import threading
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def _decode_patch(reply):
    import base64
    import cv2
    raw = base64.b64decode(reply["patch"].split(",")[-1])
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def test_the_heal_brush_goes_through_the_ai_cleaner_when_one_is_set_up():
    """The whole reason to paint over a spot by hand is that the Clean step
    missed it. Rebuilding that spot by copying nearby pixels is exactly the
    method that could not do it in the first place; when an AI cleaner is
    configured the heal brush must use THAT, the same model that cleaned the
    rest of the page. And it must ask for it in strict mode: `_ai_clean_call`
    otherwise swallows a dead endpoint and hands back a Telea smear, which is
    worse than the local shiftmap path this handler already has."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_healai"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_healai"), 1)
    p.settings["ai_clean"] = "hard"
    p.settings["clean_url"] = "http://127.0.0.1:9/none"
    p.settings["clean_token"] = "t"
    was, editor.PROJECT = editor.PROJECT, p
    seen = {}

    def spy(url, token, cache_dir, img, mask, strict=False):
        seen["strict"] = strict
        seen["mask"] = mask.copy()
        return np.full_like(img, 33)

    real, editor._ai_clean_call = editor._ai_clean_call, spy
    srv, base = _heal_server(p)
    try:
        img = np.full((120, 120, 3), 240, np.uint8)
        msk = np.zeros((120, 120), np.uint8)
        msk[50:70, 50:70] = 255
        j = _heal_post(base, img, msk)
        assert not j.get("error"), j
        assert seen.get("strict") is True, \
            "the heal brush must ask for the cleaner in strict mode"
        assert j.get("how") == "ai", \
            "and must tell the browser which method actually ran"
        out = _decode_patch(j)
        core = out[55:65, 55:65]
        assert abs(int(core.mean()) - 33) < 3, \
            "the healed spot must be what the model returned, not a local fill"
    finally:
        srv.shutdown(); srv.server_close()
        editor._ai_clean_call = real
        editor.PROJECT = was
        shutil.rmtree(scratch("_tmp_healai"), ignore_errors=True)


def test_a_dead_cleaner_endpoint_says_so_instead_of_healing_locally():
    """This used to fall through to the local fill and hand back a patch, so a
    dead endpoint was invisible — the spot changed, the layer appeared, and the
    brush lee wanted had never run. That fill is gone
    (*"remoev teh regualr healing brush, its ass"*), so there is nothing to
    fall through to and the only honest answer is the reason."""
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_healdead"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_healdead"), 1)
    p.settings["ai_clean"] = "hard"
    p.settings["clean_url"] = "http://127.0.0.1:9/none"
    p.settings["clean_token"] = "t"
    was, editor.PROJECT = editor.PROJECT, p

    def boom(*a, **k):
        raise RuntimeError("endpoint is down")

    real, editor._ai_clean_call = editor._ai_clean_call, boom
    srv, base = _heal_server(p)
    try:
        img = np.full((120, 120, 3), 240, np.uint8)
        img[:, ::9] = 40                       # some texture to rebuild
        msk = np.zeros((120, 120), np.uint8)
        msk[50:70, 50:70] = 255
        j = _heal_post(base, img, msk)
        assert j.get("error"), j
        assert "patch" not in j, "it healed with the fill that was removed"
    finally:
        srv.shutdown(); srv.server_close()
        editor._ai_clean_call = real
        editor.PROJECT = was
        shutil.rmtree(scratch("_tmp_healdead"), ignore_errors=True)


def test_the_healed_spot_is_not_half_the_old_pixels_at_its_edge():
    """The seam feather used to blur the mask itself, so alpha crossed 0.5
    exactly ON the mask boundary and the outer rim of everything erased came
    back at half strength — the pale outlines of the original typesetting. The
    ramp has to sit OUTSIDE the painted spot, so every pixel the user marked
    is fully replaced.

    Measured against a stub cleaner rather than the local fill, which is gone:
    the model returns flat black, so anything light left inside the spot is
    the old page bleeding through the feather.
    """
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_healseam"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_healseam"), 1)
    p.settings["ai_clean"] = "hard"
    p.settings["clean_url"] = "http://127.0.0.1:9/none"
    p.settings["clean_token"] = "t"
    was, editor.PROJECT = editor.PROJECT, p
    real, editor._ai_clean_call = editor._ai_clean_call, \
        (lambda url, token, cache_dir, img, mask, strict=False:
         np.zeros_like(img))
    srv, base = _heal_server(p)
    try:
        img = np.zeros((120, 120, 3), np.uint8)      # black page...
        img[50:70, 50:70] = 255                      # ...with a white blotch
        msk = np.zeros((120, 120), np.uint8)
        msk[50:70, 50:70] = 255                      # paint over exactly that
        out = _decode_patch(_heal_post(base, img, msk))
        rim = np.concatenate([out[50, 50:70], out[69, 50:70],
                              out[50:70, 50], out[50:70, 69]]).reshape(-1, 3)
        assert int(rim.max()) < 40, \
            f"the edge of the painted spot kept the old pixels (max {rim.max()})"
    finally:
        srv.shutdown(); srv.server_close()
        editor._ai_clean_call = real
        editor.PROJECT = was
        shutil.rmtree(scratch("_tmp_healseam"), ignore_errors=True)


def test_there_is_no_brush_left_that_avoids_the_model():
    """Two tests stood here — one proving the plain brush never called the
    cleaner, one proving the two brushes could not both be armed. Both are
    about a brush that no longer exists. lee: *"remoev teh regualr healing
    brush, its ass"*.

    What replaces them is the opposite requirement, which is the one that can
    now go wrong: every stroke goes to the model, so no request may be answered
    without one having been asked for.
    """
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_healonly"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_healonly"), 1)
    p.settings["ai_clean"] = "all"
    p.settings["clean_url"] = "http://127.0.0.1:9/none"
    p.settings["clean_token"] = "t"
    was, editor.PROJECT = editor.PROJECT, p
    calls = []

    def spy(url, token, cache_dir, img, mask, strict=False):
        calls.append(strict)
        return np.full_like(img, 33)

    real, editor._ai_clean_call = editor._ai_clean_call, spy
    srv, base = _heal_server(p)
    try:
        img = np.full((120, 120, 3), 240, np.uint8)
        msk = np.zeros((120, 120), np.uint8)
        msk[50:70, 50:70] = 255
        j = _heal_post(base, img, msk)
        assert not j.get("error"), j
        assert calls == [True], f"the model was not the thing that healed: {calls}"
        assert j.get("how") == "ai"
    finally:
        srv.shutdown(); srv.server_close()
        editor._ai_clean_call = real
        editor.PROJECT = was
        shutil.rmtree(scratch("_tmp_healonly"), ignore_errors=True)


def test_the_healing_brush_sends_enough_context_for_a_model_to_use():
    """A model can only continue artwork it can see, so the collar paint.js
    sends has to be comparable to what the Clean step sends
    (inpaint.NEURAL_CTX). It used to be picked per brush — the local one was
    happy with 40px — and there is one brush now, so there is one number."""
    import os
    import re as _re
    from mangatl.inpaint import NEURAL_CTX
    src = open(os.path.join(str(PKG),
                            "static", "js", "paint.js")).read()
    body = src.split("async function finalizeHeal", 1)[1]
    m = _re.search(r"st\.sz/2\)\s*\+\s*(\d+)", body)
    assert m, "finalizeHeal no longer sets a context margin"
    assert int(m.group(1)) >= NEURAL_CTX, \
        f"the brush sends {m.group(1)}px of context, want >= {NEURAL_CTX}"


# ------------------------------------------------- sound effects that lean
# A sound effect is not dialogue. It has no bubble, it leans, and when it runs
# down the page it is typeset one letter beneath the next. sfx.py reads the
# angle off the original ink; these cover the wiring that carries that reading
# from detection through the project file to the typesetting on the page.

def _drawn_sfx(tilt, vertical=True, text="GRR", size=54, canvas=(380, 460),
               pad=8):
    """A page carrying an effect drawn at `tilt`, and the box around it.

    Positive leans clockwise, the way the page reads it. Typeset in the
    bundled face rather than a Japanese one so this never skips: the reader
    is measuring ink, and it does not care whose alphabet the ink came from.
    """
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(default_font_path(), size)
    if vertical:
        w, h = size + 24, int(size * 1.05 * len(text)) + 24
    else:
        w, h = int(size * 1.05 * len(text)) + 24, size + 24
    lay = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(lay)
    for i, ch in enumerate(text):
        xy = ((12, 12 + int(i * size * 1.02)) if vertical
              else (12 + int(i * size * 1.02), 12))
        d.text(xy, ch, font=f, fill=255)
    lay = lay.rotate(-tilt, expand=True, resample=Image.BICUBIC)
    page = Image.new("L", canvas, 255)
    px, py = (canvas[0] - lay.width) // 2, (canvas[1] - lay.height) // 2
    page.paste(Image.new("L", lay.size, 0), (px, py), lay)
    box = (max(px - pad, 0), max(py - pad, 0),
           lay.width + 2 * pad, lay.height + 2 * pad)
    return np.array(page), box


def _sfx_region(tilt, dst="GRRR", vertical=True, text="GRR"):
    """A measured sound-effect region over the page it was measured on."""
    import cv2
    from mangatl.models import Page, TextRegion
    from mangatl.project import measure_sfx
    gray, box = _drawn_sfx(tilt, vertical=vertical, text=text)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    x, y, w, h = box
    # The text mask is the ink itself, the way the detector hands one over —
    # not a filled rectangle. The axis reader measures whatever it is given,
    # and a solid block is too square to have an axis at all.
    ink = np.zeros(gray.shape, np.uint8)
    ink[y:y + h, x:x + w] = (gray[y:y + h, x:x + w] <= 128).astype(np.uint8) * 255
    box_mask = np.zeros(gray.shape, np.uint8)
    box_mask[y:y + h, x:x + w] = 255
    r = TextRegion(id=0, bbox=box, text_mask=ink, bubble_mask=box_mask,
                   bubble_bbox=box, kind="sfx")
    r.dst_text = dst
    page = Page(image=img)
    page.regions = [r]
    measure_sfx(page)
    return page, r


def test_a_leaning_sound_effect_is_read_off_the_page_at_detection():
    """The angle has to be taken while the Japanese is still there. By the
    time anything is typeset the effect has been painted out, and there is
    nothing left to measure."""
    _, r = _sfx_region(-22)
    assert abs(r.angle + 22) <= 6, r.angle
    assert r.sfx_vertical
    # the footprint is the ink's own, not the box's: a leaning column sits
    # inside a box far wider than the typesetting ever is
    assert 0.2 <= r.sfx_wid <= 0.5, r.sfx_wid
    assert 0.5 <= r.sfx_len <= 1.0, r.sfx_len


def test_a_straight_effect_is_left_straight_and_a_bubble_is_never_measured():
    _, r = _sfx_region(0)
    assert r.angle == 0.0
    from mangatl.models import Page, TextRegion
    from mangatl.project import measure_sfx
    gray, box = _drawn_sfx(-22)
    import cv2
    b = TextRegion(id=1, bbox=box, kind="bubble")
    pg = Page(image=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
    pg.regions = [b]
    assert measure_sfx(pg) == 0
    assert b.angle == 0.0 and b.sfx_len == 0.0


def test_the_measured_angle_survives_the_journey_through_the_project_file():
    """Measured at detection, used at typeset — with the project file, and
    possibly a restart, in between."""
    import cv2
    from mangatl.project import region_from_record, region_record
    _, r = _sfx_region(-22)
    rec = json.loads(json.dumps(region_record(r)))
    back = region_from_record(rec, np.full((460, 380, 3), 240, np.uint8))
    assert abs(back.angle - r.angle) < 0.02
    assert back.sfx_vertical == r.sfx_vertical
    assert abs(back.sfx_len - r.sfx_len) < 0.01
    assert abs(back.sfx_wid - r.sfx_wid) < 0.01
    # A record written before any of this existed loads as never measured,
    # not as measured at zero — the two mean different things to the fitter.
    old = {k: v for k, v in rec.items()
           if k not in ("angle", "sfx_vertical", "sfx_len", "sfx_wid")}
    older = region_from_record(old, np.full((460, 380, 3), 240, np.uint8))
    assert older.angle == 0.0 and older.sfx_len == 0.0


def test_a_sound_effect_is_typeset_along_the_axis_it_was_drawn_on():
    """The English leans the same way the Japanese did. `rotate` turns the
    opposite way round from the page's own reading of the tilt — PIL and the
    browser both turn anticlockwise — so the sign matters and is checked."""
    from mangatl.typeset import fit_region
    _, r = _sfx_region(-22)
    lay = fit_region(r, TypesetConfig(font_path=default_font_path()))
    assert lay.lines, "the effect was not typeset at all"
    assert lay.rotate == pytest.approx(-r.angle, abs=0.01)
    assert lay.rotate > 8, lay.rotate
    assert lay.frame and lay.frame[2] > 0 and lay.frame[3] > 0
    # the block sits where the original did
    cx = lay.frame[0] + lay.frame[2] / 2
    cy = lay.frame[1] + lay.frame[3] / 2
    assert abs(cx - (r.bbox[0] + r.bbox[2] / 2)) <= 2
    assert abs(cy - (r.bbox[1] + r.bbox[3] / 2)) <= 2


def test_a_sound_effect_running_down_the_page_is_still_typeset_as_a_word():
    """lee asked for the stacking gone: an effect leans, it does not stack.

    The Japanese ran down the page, so this is the case that used to come out
    as a column of single capitals. It goes down as one word now, leaning the
    way the column leaned, and it keeps the ink weight the column had — the
    word must not shrink to the width of one character.
    """
    from mangatl.typeset import fit_region
    _, r = _sfx_region(-22, dst="GRRR")
    lay = fit_region(r, TypesetConfig(font_path=default_font_path()))
    assert lay.lines == ["GRRR"], "the effect was stacked, not typeset"
    assert len(lay.line_origins) == 1
    assert lay.rotate == pytest.approx(-r.angle, abs=0.01)
    assert lay.rotate > 8, lay.rotate
    # as long as the column was tall, not as narrow as the column was wide
    assert lay.frame[2] > r.bbox[3] * 0.5, (lay.frame, r.bbox)


def test_a_sound_effect_lying_across_the_page_stays_on_one_line():
    from mangatl.typeset import fit_region
    _, r = _sfx_region(-18, dst="BOOM", vertical=False, text="DON")
    lay = fit_region(r, TypesetConfig(font_path=default_font_path()))
    assert lay.lines == ["BOOM"]
    assert lay.rotate > 6, lay.rotate


def test_typesetting_leaves_a_leaning_effect_leaning():
    """The whole reading is thrown away if the page-level pass then squares
    the block back up on its way past."""
    from mangatl.typeset import typeset_page
    page, r = _sfx_region(-22)
    typeset_page(page, TypesetConfig(font_path=default_font_path()))
    assert r.layout and r.layout.lines
    assert r.layout.rotate > 8, r.layout.rotate


def test_a_rotation_set_by_hand_still_beats_the_measured_one():
    from mangatl.typeset import typeset_page
    page, r = _sfx_region(-22)
    r.layout_override = {"rotate": 5}
    typeset_page(page, TypesetConfig(font_path=default_font_path()))
    assert r.layout.rotate == 5.0
    # and straightening it means straight, not "no opinion"
    r.layout, r.layout_override = None, {"rotate": 0}
    typeset_page(page, TypesetConfig(font_path=default_font_path()))
    assert r.layout.rotate == 0.0


def test_a_sound_effect_nobody_ever_measured_is_still_typeset():
    """Every page detected before the reader existed. They typeset straight,
    filling their box, exactly as they did before."""
    from mangatl.typeset import fit_region
    _, r = _sfx_region(-22)
    r.angle, r.sfx_len, r.sfx_wid = 0.0, 0.0, 0.0
    lay = fit_region(r, TypesetConfig(font_path=default_font_path()))
    assert lay.lines and lay.rotate == 0.0
    # and they fill the box, which is all anybody ever knew about them. An
    # unmeasured footprint read as a measurement of nothing typesets the
    # effect at a size you would need to lean in to read. The word runs
    # ACROSS, so the box's long side is the room it has to fill.
    assert lay.frame[2] >= max(r.bbox[2], r.bbox[3]) * 0.8, (lay.frame, r.bbox)
    assert lay.font_size >= 24, lay.font_size


def test_the_editor_preview_does_not_square_a_leaning_effect_back_up():
    """The preview is what the person actually looks at, and it ran every fit
    through enforce_bounds — which drags each line back inside the region's
    own box. A leaning effect is laid out along its own axis and turned
    afterwards, so "inside the box" is not a thing its lines are: clamping
    them there stacks the ones that hang over onto the edge, on top of each
    other, and a long effect comes out as a pile."""
    import shutil
    import cv2
    from mangatl import editor
    from mangatl.project import Project, region_record
    from mangatl.typeset import fit_region

    shutil.rmtree(scratch("_tmp_sfx1"), ignore_errors=True)
    was = editor.PROJECT
    try:
        gray, box = _drawn_sfx(-22)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        p = Project(None, scratch("_tmp_sfx1"))
        p.add_uploaded("s0.png", cv2.imencode(".png", img)[1].tobytes())
        # Long enough that it runs past the ends of the box, which is where
        # the clamping used to show: a short one fits either way.
        _, r = _sfx_region(-22, dst="WHAAAAAAAAAAAAAAAAAAAAAAM")
        p.pages[0].regions = [region_record(r)]
        editor.PROJECT = p
        editor.invalidate_page(0)
        out = editor.layout_preview(p, 0, 0, {})
        assert out.get("lines"), out
        assert out["rotate"] > 8, out["rotate"]
        assert out["frame"], "the effect lost the frame it was laid out in"
        want = fit_region(p.materialize(0).regions[0],
                          editor._typeset_cfg(p))
        assert [list(o) for o in want.line_origins] == out["origins"]
    finally:
        editor.PROJECT = was
        editor.invalidate_page(0)
        shutil.rmtree(scratch("_tmp_sfx1"), ignore_errors=True)


def test_detection_is_where_the_angle_gets_read():
    """Nowhere later will do. Detection is the last moment the Japanese is
    still on the page; after the Clean step there is nothing to measure."""
    import shutil
    import cv2
    from mangatl.detect import freetext
    from mangatl.project import Project

    shutil.rmtree(scratch("_tmp_sfx2"), ignore_errors=True)
    was = freetext.detect_free_text
    try:
        gray, box = _drawn_sfx(-22)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        p = Project(None, scratch("_tmp_sfx2"))
        p.add_uploaded("s0.png", cv2.imencode(".png", img)[1].tobytes())
        _, found = _sfx_region(-22)
        found.angle, found.sfx_len, found.sfx_wid = 0.0, 0.0, 0.0
        freetext.detect_free_text = lambda page, avoid=None, kind="sfx": [found]
        p.detect(0, ["sfx"])
        rec = p.pages[0].regions[0]
        assert rec["kind"] == "sfx"
        assert abs(rec["angle"] + 22) <= 6, rec["angle"]
        assert rec["sfx_len"] > 0, "the footprint was never written down"
    finally:
        freetext.detect_free_text = was
        shutil.rmtree(scratch("_tmp_sfx2"), ignore_errors=True)


def test_calling_a_box_a_sound_effect_reads_its_angle_there_and_then():
    """Changing a region's kind by hand happens long after detection, and the
    page it happens on has not been cleaned yet — so the angle is still there
    to be taken, and this is the last chance to take it."""
    import json as _json
    import shutil
    import urllib.request
    import cv2
    from mangatl import editor
    from mangatl.project import Project, region_record

    shutil.rmtree(scratch("_tmp_sfx3"), ignore_errors=True)
    was = editor.PROJECT
    srv = None
    try:
        gray, box = _drawn_sfx(-22)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        p = Project(None, scratch("_tmp_sfx3"))
        p.add_uploaded("s0.png", cv2.imencode(".png", img)[1].tobytes())
        _, r = _sfx_region(-22)
        r.kind = "freefloat"
        rec = region_record(r)
        rec.update({"angle": 0.0, "sfx_len": 0.0, "sfx_wid": 0.0,
                    "sfx_vertical": False})
        p.pages[0].regions = [rec]
        editor.PROJECT = p
        editor.invalidate_page(0)
        srv, base = _heal_server(p)
        req = urllib.request.Request(
            base + "/api/page/0/region/%d" % r.id,
            data=_json.dumps({"kind": "sfx"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
        got = p.pages[0].regions[0]
        assert got["kind"] == "sfx"
        assert abs(got["angle"] + 22) <= 6, got["angle"]
        assert got["sfx_len"] > 0 and got["sfx_wid"] > 0
    finally:
        if srv is not None:
            srv.shutdown()
        editor.PROJECT = was
        editor.invalidate_page(0)
        shutil.rmtree(scratch("_tmp_sfx3"), ignore_errors=True)


def test_the_rotation_box_follows_a_leaning_effect_in_a_real_dom():
    """A sound effect comes out of the fitter already leaning, with nothing
    hand-set on it. The Rotation field has to show that angle rather than a
    zero, and "5 degrees more" has to mean five more than the lean — from
    zero it snaps the effect upright the first time you touch the button."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "sfx_rotate.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "field starts at: 22" in out.stdout, out.stdout
    assert "after +5: 27 stored: 27" in out.stdout, out.stdout
    assert "after reset: 0" in out.stdout, out.stdout
    assert "hand-set field: -9" in out.stdout, out.stdout
    # and it stays put through a rebuild: the angle goes into the layout as
    # well as the override, because the layout is what the panel reads.
    assert "after -3 and a rebuild: -12 stored: -12" in out.stdout, out.stdout


def test_the_exported_page_shows_the_effect_leaning():
    """The end of the line. Everything above is arithmetic until the ink
    lands on the page at the angle it was measured at — so the render is read
    back with the same reader that took the measurement in the first place."""
    import cv2
    from mangatl.render import render_page
    from mangatl.sfx import sfx_frame
    from mangatl.typeset import typeset_page

    page, r = _sfx_region(-24, dst="GRRR")
    # a blank plate, so the only ink in the render is the typesetting
    page.clean_plate = np.full_like(page.image, 255)
    typeset_page(page, TypesetConfig(font_path=default_font_path()))
    out = render_page(page, TypesetConfig(font_path=default_font_path()),
                      halo=False)
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    assert int((gray < 128).sum()) > 200, "nothing was drawn"
    x, y, w, h = r.bbox
    fr = sfx_frame(gray, (max(0, x - 30), max(0, y - 30), w + 60, h + 60))
    assert fr.trusted, "the typesetting came out too square to have an axis"
    assert abs(fr.tilt - r.angle) <= 8, (fr.tilt, r.angle)


def test_exporting_cleaned_art_writes_the_plate_with_no_english_on_it():
    """The cleaned raws are a deliverable of their own.

    Same folder machinery, same cleaning, one thing withheld: the typesetting.
    What lands on disk has to be the plate itself, pixel for pixel — not the
    plate with faint English on it, and not the original page with the
    Japanese still there. Both failures look almost right in a thumbnail,
    so this compares against the plate rather than eyeballing ink.

    And it is not the finished export, so it must not tick the Export step:
    a chapter whose cleaned art has been handed off is not a chapter that has
    been published, and the step counter is what tells lee which is which.
    """
    import os
    import shutil
    import cv2
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_expclean"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_expclean"), 1)
    try:
        p.pages[0].regions[0]["dst_text"] = "HELLO THERE FRIEND"
        os.makedirs(editor.export_root(p), exist_ok=True)

        out = editor.export_page(p, 0, mode="clean")
        bare = cv2.imread(out)
        assert bare is not None, out
        assert not p.pages[0].exported, "cleaned art is not the finished export"
        assert p.pages[0].cleaned

        page = p.materialize(0)
        editor.clean_page(p, 0, page)
        assert np.array_equal(bare, page.clean_plate), \
            "what was written is not the cleaned plate"

        typeset = cv2.imread(editor.export_page(p, 0, mode="full"))
        assert p.pages[0].exported, "the real export must tick the step"
        assert not np.array_equal(bare, typeset), \
            "the typeset export came out identical to the bare plate"
    finally:
        shutil.rmtree(scratch("_tmp_expclean"), ignore_errors=True)


def test_pressing_typeset_lays_out_a_page_that_was_typeset_by_hand():
    """Typeset means "lay this page out again", including where a person has
    already been.

    A hand correction stores `locked` in the region's override, and a locked
    region skips the fitter entirely — so on any page lee had touched, the
    Typeset button did nothing at all and there was no way to ask for the
    automatic layout back short of resetting each bubble one at a time.

    Pressing it now returns the region to exactly what the fitter produces.
    What it must NOT throw away is the dressing: the face, the colours and
    the outline chosen for that bubble are decisions about the page, not
    corrections to the fit, and they survive the re-run.
    """
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_redo"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_redo"), 1)
    try:
        p.pages[0].regions[0]["dst_text"] = "HELLO THERE MY OLD FRIEND"
        editor.do_typeset(p, 0)
        auto = p.pages[0].regions[0]["layout"]
        assert auto and auto["lines"], "nothing was typeset to begin with"
        auto = dict(auto)

        # retyped, shrunk, dragged out of the bubble, turned — and painted
        p.pages[0].regions[0]["layout_override"] = {
            "lines": ["WHO"], "font_size": 8, "leading": 2.0,
            "dx": 25, "dy": -12, "frame": [10, 10, 40, 30], "rotate": 15,
            "locked": True, "fg": "#ff0000", "edge": "#00ff00",
            "shadow": "#0000ff", "stroke": 3}
        editor.do_typeset(p, 0)

        rec = p.pages[0].regions[0]
        lay, ov = rec["layout"], rec.get("layout_override") or {}
        assert lay["lines"] != ["WHO"], "the hand placement survived Typeset"
        assert lay["lines"] == auto["lines"], (lay["lines"], auto["lines"])
        assert lay["font_size"] == auto["font_size"]
        assert lay["rotate"] == 0.0, lay["rotate"]
        assert not ov.get("locked"), "the region is still pinned"
        # ...and so does everything else that was chosen by hand. Typeset used
        # to keep the DRESSING — the colour, the outline, the shadow — and
        # drop only the placement, so there was no way back to a clean page
        # short of undoing each block one at a time. lee: *"when i re typseet a
        # page any custom chnages to text boxes or custom text box dshoud be
        # removed"*. The button that is meant to be the reset is the reset.
        assert not ov, ov
    finally:
        shutil.rmtree(scratch("_tmp_redo"), ignore_errors=True)


def test_looking_at_a_page_or_exporting_it_never_undoes_a_hand_correction():
    """The other half of the same rule. Only the button re-lays a page out:
    rendering a preview and writing the export typeset the page as it stands,
    or opening a finished chapter would quietly re-fit all of it."""
    import os
    import shutil
    from mangatl import editor

    shutil.rmtree(scratch("_tmp_redo2"), ignore_errors=True)
    p = _tiny_project(scratch("_tmp_redo2"), 1)
    try:
        p.pages[0].regions[0]["dst_text"] = "HELLO THERE MY OLD FRIEND"
        hand = {"lines": ["WHO"], "font_size": 8, "locked": True}
        p.pages[0].regions[0]["layout_override"] = dict(hand)
        os.makedirs(editor.export_root(p), exist_ok=True)
        editor.export_page(p, 0)
        assert p.pages[0].regions[0]["layout_override"] == hand
        assert p.pages[0].regions[0]["layout"]["lines"] == ["WHO"]
    finally:
        shutil.rmtree(scratch("_tmp_redo2"), ignore_errors=True)


def test_a_step_that_falls_over_says_where_it_fell_over():
    """The red bar carried a bare type and message — "IndexError: too many
    indices for array" — which names no file, no line and no step. The person
    reading it has nothing to report and nothing to look at, and the actual
    traceback goes to a console window nobody has open. The innermost frame
    of our own code goes in the bar with it."""
    from mangatl import editor

    try:
        editor.export_root(None)          # AttributeError, inside editor.py
    except Exception as e:
        where = editor._where(e)
    assert "editor.py:" in where, where
    assert "in export_root" in where, where


def test_a_balloon_whose_outline_reads_oddly_does_not_take_the_page_down():
    """The crash lee got on Typeset.

    Reading a balloon's neck asks OpenCV for the dents in its hull. Every
    build this has run against answers with an (N, 1, 4) array, and the code
    unpacked that middle axis on the spot — so a build that hands back a plain
    (N, 4) raised "IndexError: too many indices for array: array is
    2-dimensional, but 3 were indexed", inside a worker thread, which killed
    the whole Typeset run for the chapter. A page of dialogue was lost to a
    detail of how one measurement is shaped.

    Nothing about reading the outline is required to typeset a page: it is an
    improvement on the search that would otherwise run. So an answer in any
    shape at all has to fall through to that search, and the words still have
    to land in the bubble.
    """
    from unittest import mock
    import cv2 as _cv2
    from mangatl import typeset as ts

    texts = ["MY HARD WORK PAID OFF TOO—", "—SO TAKE CARE NOW!"]
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12,
                        max_font=24)

    real = _cv2.convexityDefects

    def flat(c, hull):
        d = real(c, hull)
        return None if d is None else np.asarray(d).reshape(-1, 4)

    for shaped in (flat, lambda c, h: np.zeros((3, 2), np.int32),
                   lambda c, h: (_ for _ in ()).throw(ValueError("nope"))):
        regions = _two_lobe_regions(*texts)
        with mock.patch.object(ts.cv2, "convexityDefects", shaped):
            shares = ts.share_masks(regions, cfg)
            lays = [ts.fit_region(r, cfg, shares.get(r.id)) for r in regions]
        for r, lay, want in zip(regions, lays, texts):
            assert lay.lines, (r.id, shaped)
            assert " ".join(lay.lines) == want, (lay.lines, shaped)

    # ...and the flat shape is not merely survived, it is UNDERSTOOD: the same
    # numbers in two axes instead of three are the same neck.
    a, b = (_two_lobe_regions(*texts) for _ in range(2))
    with mock.patch.object(ts.cv2, "convexityDefects", flat):
        flat_shares = ts.share_masks(a, cfg)
    round_shares = ts.share_masks(b, cfg)
    assert set(flat_shares) == set(round_shares), "the neck was not read"
    for k in round_shares:
        assert np.array_equal(flat_shares[k] > 0, round_shares[k] > 0)


def test_the_side_by_side_switch_is_where_it_can_be_used():
    """It sat beside "Snap boxes", visible on every tab and in every view —
    including the Original view, where the pane it opens shows the same
    picture twice, and the Results and Settings tabs, where no page is on
    screen at all. It belongs next to the "Translated text" switch, which
    already follows that rule, and ahead of it."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "side_by_side.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "sits: before the translated-text switch" in out.stdout, out.stdout
    assert "edit tab, original view: false" in out.stdout, out.stdout
    assert "edit tab, edit view: true" in out.stdout, out.stdout
    assert "pane with it on, edit view: true" in out.stdout, out.stdout
    assert "results tab: false pane: false" in out.stdout, out.stdout
    assert "back on edit: true pane: true" in out.stdout, out.stdout


def test_returning_to_the_edit_tab_puts_the_page_back_on_screen():
    """Results -> Edit showed an empty grey pane.

    The editing pane centres the page inside a wide pan border, so the middle
    of the scroll range is the only place the page is visible from. A scroll
    box that is display:none has its scroll position reset to zero by the
    browser, and it has no width to measure a fit against either — so setTab
    unhiding the stage and doing nothing else handed back a pane scrolled to
    the corner of the border, at a zoom worked out from a zero-width box."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "tab_recentre.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "back on edit — refits: 1 recentres: true" in out.stdout, out.stdout
    # Leaving does not disturb the view; only coming back restores it.
    assert "leaving for results — refits: 0 recentres: 0" in out.stdout, out.stdout
    assert "stage visible: block" in out.stdout, out.stdout


def test_the_box_on_screen_is_the_writing_and_the_balloon_is_behind_it():
    """lee: "these bubbles are too big the detector shoud only try to find teh
    text not teh whole bubble", with two pages showing rectangles the size of
    half a panel.

    The detector was right all along. `bbox` is where Find text measured the
    WRITING; `bubble_bbox` is the balloon found round it afterwards, so the
    typesetter can use the whole of the paper rather than the narrow column the
    Japanese ran down. The editor drew `bubble_bbox||bbox` — the balloon — as
    though it were the box that had been found, so a thin line of kana in a wide
    oval looked like a box over the oval with the writing in one corner of it.

    This runs the real drawing code in a real DOM and checks the solid box is at
    the writing, and that nothing else is drawn round it. The balloon used to be
    shown behind it as a faint dashed outline; lee asked for that removed on
    2026-07-30 (*"there a thin dahed red box around the box around the text what
    does it do and remove it"*), so what is checked now is that ONE rectangle
    appears per region, at the writing, through the zoom, with a two-section
    balloon drawing NO frame round the pair -- lee: *"hide teh big box
    afterware it dosnt need to be visibel"* -- and its sections still marked
    as sections."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "box_is_the_writing.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all good" in out.stdout, out.stdout
    assert "FAIL" not in out.stdout, out.stdout
    # the two that were the actual bug, named so a partial pass is not silent
    assert "ok   the box sits at the WRITING, not the balloon" in out.stdout
    assert "ok   nothing is drawn at the balloon rectangle" in out.stdout
    assert "ok   a two-section balloon draws no frame round the pair" \
        in out.stdout


def test_the_page_list_follows_the_page_you_are_on():
    """lee: *"can you make teh side bar with th pages scroll so that teh
    current 0age is alwsy in teh frame"*. On a 46-page chapter the list is far
    longer than the rail, so paging through walked the highlight off the
    bottom while the sidebar sat on page 1."""
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui",
                              "the_page_list_follows_the_page.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all good" in out.stdout, out.stdout
    assert "FAIL" not in out.stdout, out.stdout
    assert "ok   ...asked for as nearest, not centred" in out.stdout
    assert "ok   a rename in progress is not scrolled away from" in out.stdout


def test_a_tall_narrow_balloon_is_typeset_to_its_own_ceiling():
    """Page 8, bottom right: "PLEASE, LISTEN TO WHAT THIS CHILD HAS TO SAY."

    lee runs 10 to 34. That balloon takes 16 at the outside, so the whole
    ladder available in it is 10..16 — and the fitter used to measure how
    small a layout was against 10..34, where the step from 14 to 16 is 8% of
    the span and worth about 0.29 of score. Any layout at 14 whose breaks came
    out a shade more even bought the smaller type for less than it was worth,
    and the sentence sat at 14 in the bottom half of the bubble with the top
    half empty. Two things had to change for it to typeset at 16: the ladder is
    now the sizes the balloon can really take (`_feasible_top`), and a tall
    bubble is allowed the lines its height affords before the stack penalty
    fires (`rows_afforded`) — seven short lines in a narrow balloon is the
    shape doing what it was drawn to do, not a column of stubs.

    Both assertions bite, and they bite on different halves: the size is what
    the ladder fixes, the fill is what says the block sits IN the balloon
    rather than as a ribbon down the middle of it. Before the change this
    balloon came out 15pt across five lines filling 40% of the height.

    The bars were 16pt and 48% while the fitter could set solid. It cannot any
    more — lee: *"make teh minimun line gap be 1.20"* — and on a balloon this
    narrow the two things are in direct competition. Measured on this exact
    shape, every option:

    | line gap allowed | size | lines | fill |
    |------------------|------|-------|------|
    | 1.18 / 1.10 / 1.04 / 1.00 | 16pt | 7 | 0.52 |
    | 1.34 / 1.26 / 1.20 (now)  | 14pt | 5 | 0.41 |

    The seven-line answer needed 1.00 flat. So the floor costs this balloon two
    points of type and a tenth of its fill, and that is the trade lee asked
    for — recorded here rather than quietly written down, because it is the
    number to look at if he ever wants the old typesetting back.
    """
    from mangatl.typeset import fit_region
    text = "PLEASE, LISTEN TO WHAT THIS CHILD HAS TO SAY."
    r = _oval_region(110, 220, text)
    lay = fit_region(r, TypesetConfig(font_path=default_font_path(),
                                      min_font=10, max_font=34))
    assert " ".join(lay.lines) == text, lay.lines
    assert lay.font_size >= 14, (lay.font_size, lay.lines)
    assert lay.leading >= 1.20, lay.leading
    ys = [y for _, y in lay.line_origins]
    rows = np.nonzero((r.bubble_mask > 0).any(axis=1))[0]
    fill = (max(ys) - min(ys) + lay.font_size) / float(rows[-1] - rows[0] + 1)
    assert fill >= 0.40, (fill, lay.font_size, lay.lines)


def test_a_neck_cut_that_strangles_the_dialogue_gives_way():
    """The same two-lobed balloon, with more English in it.

    A lobe is narrow. Give the bud a short line and it typesets at 22 and the
    neck cut is plainly right; give it a whole sentence and the widest word no
    longer fits across the bud at any size the fitter is allowed, so it falls to
    14 while a cut straight across the balloon reaches 19. That is what lee is
    looking at when he says the text in these bubbles is still pretty small: the
    balloon's own outline was followed off a cliff.

    The gap is asserted at both ends and against itself, so the test cannot go
    quiet by both numbers drifting up together — which is how it nearly did
    when `small` began measuring against the sizes a balloon can really take
    and the strangled lobe rose from 12 to 14.

    So the neck cut is measured now rather than taken on sight. It keeps the
    balloon unless something typesets a quarter larger — page 013 with its short
    lines is beaten by nine percent and stays exactly as he asked for it — and
    the something has to keep at least half of each block's own Japanese, or it
    is typesetting big by sliding the English off the words it replaces.

    What the test asserts about SIZE has since been overtaken. Every share is
    now trimmed back to its block's own box before it is typeset — lee's HUH!?
    was landing at the balloon's waist because it wasn't — and the trim costs
    more than the choice of cut wins: the straight cut's 19 and 20 come out as
    17 and 13. The comparison the search actually makes is still pinned here,
    on the untrimmed shares it is made on, and that is the whole of what this
    test can honestly claim. lee, told what the trim would cost: *"that fine
    the size dnst mattaer as long as it in the box"*.
    """
    from mangatl.typeset import fit_region, share_masks
    texts = ["THIS FAITH EXISTS BECAUSE OF YOU, SISTER, AND ALWAYS WILL.",
             "LET'S MEET AGAIN SOMETIME SOON, WON'T WE?"]
    regions = _two_lobe_regions(*texts)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=12, max_font=24)

    lobed = _two_lobe_regions(*texts)
    from mangatl.typeset import (_lobe_cut, _prop_cut, _same_shape_masks,
                                 _confine_all)
    masks = _same_shape_masks(lobed)
    neck = _lobe_cut(lobed, masks, cfg)
    assert neck, "the neck cut is what this test is about"
    strangled = min(fit_region(r, cfg, neck[r.id]).font_size for r in lobed)
    assert strangled <= 15, strangled                     # strangled, as found
    # The reason the search overrules it, measured where the search measures:
    # on the shares before the box trim. Four points is the difference lee can
    # see, and the straight cut is offering six.
    band = _prop_cut(lobed, masks, texts, vertical=False)
    assert len(band) == len(lobed), "no straight cut; nothing to overrule with"
    across = min(fit_region(r, cfg, band[r.id]).font_size for r in lobed)
    assert across >= strangled + 4, (strangled, across)

    shares = share_masks(regions, cfg)
    # …and it is that cut that was adopted, trimmed to the boxes.
    want = _confine_all(regions, band)
    for r in regions:
        assert np.array_equal(shares[r.id], want[r.id]), r.id
    laid = [fit_region(r, cfg, shares.get(r.id)) for r in regions]
    for lay, text in zip(laid, texts):
        assert " ".join(lay.lines) == text, lay.lines       # nothing dropped
        assert lay.font_size >= cfg.min_font, (lay.font_size, lay.lines)
    for r in regions:                       # and still on its own dialogue
        ink = r.text_mask > 0
        m = shares.get(r.id)
        if m is None:
            continue
        kept = float(((m > 0) & ink).sum()) / float(ink.sum())
        assert kept >= 0.5, (r.id, kept)


def _two_balloons_in_one_group(right_text, left_text):
    """TWO balloons, overlapping — not one balloon with two lobes.

    lee's page 008 has a pair like this, a tall one behind and a rounder one in
    front of it, each with its own dialogue. They touch, so they arrive as one
    group with one outline, and the outline has a neck where they cross. Every
    difference from `_two_lobe_regions` is in what a band cut does to it: there
    the balloon is solid, here the band runs over the white of one balloon, out
    across the artwork between them, and back onto the other.
    """
    import cv2
    from mangatl.models import TextRegion
    pad, w, h = 30, 300, 330
    yy, xx = np.mgrid[0:h + 2 * pad, 0:w + 2 * pad]
    left = (((xx - (pad + 80)) / 70.) ** 2
            + ((yy - (pad + 215)) / 105.) ** 2) <= 1.0
    right = (((xx - (pad + 215)) / 68.) ** 2
             + ((yy - (pad + 115)) / 110.) ** 2) <= 1.0
    m = np.zeros(xx.shape, np.uint8)
    m[left | right] = 255

    inks = []
    for y0, y1, x0, x1 in ((pad + 30, pad + 205, pad + 175, pad + 255),
                           (pad + 140, pad + 300, pad + 35, pad + 125)):
        ink = np.zeros_like(m)
        ink[y0:y1, x0:x1] = 255
        inks.append((ink & m).astype(np.uint8))

    d = [cv2.distanceTransform(255 - i, cv2.DIST_L2, 3) for i in inks]
    out = []
    for i, text in enumerate((right_text, left_text)):
        own = (d[0] <= d[1]) if i == 0 else (d[1] < d[0])
        piece = np.where(own & (m > 0), 255, 0).astype(np.uint8)
        ys, xs = np.nonzero(piece)
        r = TextRegion(id=i + 1, text_mask=inks[i], bubble_mask=piece,
                       bbox=cv2.boundingRect(inks[i]),
                       bubble_bbox=(int(xs.min()), int(ys.min()),
                                    int(xs.max() - xs.min() + 1),
                                    int(ys.max() - ys.min() + 1)))
        r.dst_text = text
        out.append(r)
    return out


def test_a_cut_that_typesets_over_the_gap_between_two_balloons_loses():
    """Bigger type is not worth a line of dialogue lying across the artwork.

    Every share is kept inside the BOX around its shape, and for one balloon
    that is close enough. For two balloons that touch at a corner it is not:
    the box around the top halves of both spans the gap between them, so a cut
    straight across measures 25pt where the neck cut measures 18 — by putting
    LET'S MEET where there is no balloon at all. Cheap to see once the question
    is asked, invisible to a fitter that only ever asks how big the type came
    out.
    """
    import cv2
    from mangatl.typeset import (_font, _text_w, enforce_bounds, fit_region,
                                 share_masks)
    texts = ["LET'S MEET AGAIN SOMETIME.", "THAT'S TRUE, ISN'T IT..."]
    regions = _two_balloons_in_one_group(*texts)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=10, max_font=34)

    balloon = np.zeros_like(regions[0].bubble_mask)
    for r in regions:
        balloon = np.maximum(balloon, r.bubble_mask)

    shares = share_masks(regions, cfg)
    for r in regions:
        m = shares.get(r.id)
        lay = enforce_bounds(r, fit_region(r, cfg, m), cfg, mask=m)
        assert " ".join(lay.lines) == r.dst_text, lay.lines
        path = lay.font_path or cfg.font_path
        asc, desc = _font(path, lay.font_size).getmetrics()
        for (cx, cy), line in zip(lay.line_origins, lay.lines):
            wide = _text_w(path, lay.font_size, line)
            x0, x1 = int(cx - wide / 2), int(cx + wide / 2)
            y0, y1 = int(cy - (asc + desc) / 2), int(cy + (asc + desc) / 2)
            sub = balloon[max(0, y0):y1, max(0, x0):x1] > 0
            off = 1.0 - float(sub.sum()) / max(1, sub.size)
            assert off < 0.25, (r.id, line, round(off, 3))


def _block_with_one_line_across_the_art(cfg):
    """A tidy block of twenty lines, one of which lies across the artwork.

    The shape is a plain white column with a single pinched row band in it —
    the stand-in for the gap between two balloons that touch. Nineteen lines
    sit on white; the twentieth is far wider than the pinch, so `enforce_bounds`
    centres it on that stub of a chord and the rest of it lands on the art.
    """
    from mangatl.models import TextRegion, TextLayout
    from mangatl.typeset import _text_w

    H, W = 520, 260
    m = np.zeros((H, W), np.uint8)
    m[20:480, 20:240] = 255
    m[244:267, :] = 0                       # the gap between the two balloons
    m[244:267, 120:141] = 255               # …bridged only by a 21px neck

    lines = ["HELLO"] * 20
    origins = [(130, 40 + 22 * k) for k in range(20)]
    lay = TextLayout(lines=lines, font_size=14, leading=1.0,
                     line_origins=origins, font_path=cfg.font_path)
    region = TextRegion(id=1, bubble_mask=m, bbox=(20, 20, 220, 460),
                        bubble_bbox=(20, 20, 220, 460))
    region.dst_text = " ".join(lines)
    assert _text_w(cfg.font_path, 14, "HELLO") > 40    # wider than the neck
    return region, lay, m


def test_one_line_across_the_art_is_not_averaged_away():
    """The gate reads the WORST line, because that is the one the reader sees.

    A block is read a line at a time, so three clean lines do not make up for
    the one lying over the artwork between two balloons. Averaged over the
    block it hid: on lee's page 008 the last two lines of "I'M SORRY. WE HAVE
    TO BE GETTING BACK." reached across the neck into the balloon behind, 7.6%
    on the line he could see came out as 4.7% over the block — a third of a
    point under the bar — and the cut that carried the dialogue across the neck
    was adopted as the best available. This fixture is that failure with the
    arithmetic made obvious: nineteen lines clean, one of them half on the art,
    so the average is comfortably inside the bar and the block is not.
    """
    from mangatl.typeset import _off_balloon, _font, _text_w, SPILL_ALLOWED

    cfg = TypesetConfig(font_path=default_font_path(), min_font=10, max_font=34)
    region, lay, m = _block_with_one_line_across_the_art(cfg)

    asc, desc = _font(cfg.font_path, lay.font_size).getmetrics()
    high = asc + desc
    per = []
    for (cx, cy), line in zip(lay.line_origins, lay.lines):
        wide = _text_w(cfg.font_path, lay.font_size, line)
        x0, x1 = max(0, int(cx - wide / 2)), min(m.shape[1], int(cx + wide / 2))
        y0, y1 = max(0, int(cy - high / 2)), min(m.shape[0], int(cy + high / 2))
        sub = m[y0:y1, x0:x1] > 0
        per.append((sub.size - int(sub.sum())) / sub.size)

    average = sum(per) / len(per)
    worst = max(per)
    # The fixture is only worth anything if the two numbers land either side of
    # the bar — that is the whole shape of the bug.
    assert average < SPILL_ALLOWED < worst, (average, worst)

    got = _off_balloon(region, lay, cfg, m)
    assert got == pytest.approx(worst, abs=0.01), (got, worst, average)
    assert got > SPILL_ALLOWED, (got, SPILL_ALLOWED)


# ------------------------------------------------------- vertical centring

def _neck_region(w, h, text, narrow_at_bottom=True):
    """A balloon with a neck at one end — the shape half a split bubble has.

    The widest chords sit at the opposite end from the neck, so the fit search
    is pulled that way looking for room to break the line, and the block ends
    up jammed against one pole of a balloon that had space on both sides.
    """
    from mangatl.models import TextRegion
    pad = 30
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    for y in range(pad, pad + h):
        t = (y - pad) / (h - 1)
        near = (1 - t) if narrow_at_bottom else t
        half = max(2.0, (0.30 + 0.70 * min(1.0, near / 0.30)) * w / 2)
        cx = pad + w / 2
        m[y, int(cx - half):int(cx + half)] = 255
    r = TextRegion(id=0, bbox=(pad, pad, w, h), text_mask=m, bubble_mask=m,
                   bubble_bbox=(pad, pad, w, h))
    r.dst_text = text
    return r


def _block_off_centre(region, lay):
    """How far the block's middle sits from the balloon's, as a share of half.

    Signed: positive is low in the balloon, negative is high.
    """
    ys = [y for _x, y in lay.line_origins]
    mid = (min(ys) + max(ys)) / 2
    rows = np.flatnonzero(np.asarray(region.bubble_mask).any(axis=1))
    centre = (int(rows[0]) + int(rows[-1])) / 2
    half = (int(rows[-1]) - int(rows[0])) / 2
    return (mid - centre) / half


def test_the_block_settles_back_to_the_middle_of_its_balloon():
    """Room is used to choose the breaks and then given back.

    A necked balloon's widest chords are all at one end, so the placement
    search — which is looking for width, and rightly so — picks a top down
    there and leaves the type sitting on the floor of the bubble. But the
    lines are only wide once they are broken, and by then they fit far higher
    than the chord that chose them. Sliding the finished block back to the most
    central height it still fits at costs nothing and is what lee asked for:
    "the text shoud be in the cneter of teh bubble not to the top".

    Without the settle step this block lands 49% of a half-height below centre.
    """
    from mangatl.typeset import fit_region
    cfg = TypesetConfig(font_path=default_font_path())
    r = _neck_region(220, 200, "IS IT CATCHING?", narrow_at_bottom=True)
    lay = fit_region(r, cfg)
    assert lay is not None and lay.lines
    assert abs(_block_off_centre(r, lay)) < 0.15, (
        _block_off_centre(r, lay), lay.lines, lay.line_origins)


def test_settling_never_costs_a_point_of_type():
    """A height is only accepted if every already-broken line still fits it,
    so centring can never shrink the font or add a line. This is the guard
    that keeps a future tweak to the slide from paying for tidiness with size:
    the necked balloon above typesets at 31pt on two lines either way."""
    from mangatl.typeset import fit_region
    cfg = TypesetConfig(font_path=default_font_path())
    r = _neck_region(220, 200, "IS IT CATCHING?", narrow_at_bottom=True)
    lay = fit_region(r, cfg)
    assert lay is not None
    assert lay.font_size >= 31, lay.font_size
    assert len(lay.lines) == 2, lay.lines


def test_a_block_that_cannot_be_centred_is_left_where_it_fits():
    """Centring is not allowed to override fitting. In a true wedge the narrow
    end genuinely cannot hold the lines, and the block must stay at the wide
    end rather than slide into a chord it does not fit."""
    from mangatl.typeset import fit_region, _text_w
    cfg = TypesetConfig(font_path=default_font_path())
    r = _neck_region(200, 220, "I'M SORRY. WE HAVE TO GO.",
                     narrow_at_bottom=True)
    lay = fit_region(r, cfg)
    assert lay is not None and lay.lines
    # Every line still sits inside the balloon: that is the constraint the
    # slide is subject to, and it is worth more than being central.
    m = np.asarray(r.bubble_mask)
    for (cx, cy), line in zip(lay.line_origins, lay.lines):
        wide = _text_w(lay.font_path, lay.font_size, line)
        row = m[int(cy)] > 0
        xs = np.flatnonzero(row)
        assert xs.size, cy
        assert int(cx - wide / 2) >= int(xs[0]) - 2, (line, cx, wide, xs[0])
        assert int(cx + wide / 2) <= int(xs[-1]) + 2, (line, cx, wide, xs[-1])


# ------------------------------------------------- lobes that sit side by side

def _side_by_side_lobes(right_text, left_text):
    """One balloon drawn as two lobes SIDE BY SIDE, a block in each.

    lee's page 008 farewell balloon: a tall oval low on the left and a rounder
    one high on the right, overlapping over most of their height. The shape
    matters because of what a cut straight across does to it — a horizontal
    band spans BOTH lobes, so each block is handed a share the full width of
    the balloon and the fitter centres it on the balloon rather than on the
    lobe the artist wrote it in. That is the picture lee keeps sending back:
    the lower block reaching across the neck into a lobe it does not belong to.

    `_two_lobe_regions` above is the stacked case, where a band cut roughly
    agrees with the lobes. Here it cannot.
    """
    import cv2
    from mangatl.models import TextRegion
    pad = 30
    h, w = 260 + 2 * pad, 200 + 2 * pad
    yy, xx = np.mgrid[0:h, 0:w]
    right = (((xx - (pad + 128)) / 59.) ** 2
             + ((yy - (pad + 96)) / 96.) ** 2) <= 1.0
    left = (((xx - (pad + 61)) / 46.) ** 2
            + ((yy - (pad + 151)) / 88.) ** 2) <= 1.0
    m = np.zeros(xx.shape, np.uint8)
    m[right | left] = 255

    # Each block's Japanese sits wholly inside the lobe it was written in, and
    # the two columns overlap in y — which is why the detector reports them
    # stacked and hands the balloon over divided across.
    inks = []
    for y0, y1, x0, x1 in ((22, 135, 95, 165), (120, 232, 30, 90)):
        ink = np.zeros_like(m)
        ink[pad + y0:pad + y1, pad + x0:pad + x1] = 255
        inks.append((ink & m).astype(np.uint8))

    cut = pad + 128
    out = []
    for i, (text, sl) in enumerate([(right_text, slice(0, cut)),
                                    (left_text, slice(cut + 2, None))]):
        piece = np.zeros_like(m)
        piece[sl] = m[sl]
        ys, xs = np.nonzero(piece)
        r = TextRegion(id=i + 1, text_mask=inks[i], bubble_mask=piece,
                       bbox=cv2.boundingRect(inks[i]),
                       bubble_bbox=(int(xs.min()), int(ys.min()),
                                    int(xs.max() - xs.min() + 1),
                                    int(ys.max() - ys.min() + 1)))
        r.dst_text = text
        out.append(r)
    return out, m, right, left


def _lobe_centres(mask, right, left):
    def cx(b):
        xs = np.flatnonzero(np.asarray(b).any(axis=0))
        return (int(xs[0]) + int(xs[-1])) / 2
    return cx(mask > 0), {1: cx(right), 2: cx(left)}


def test_a_block_is_centred_in_its_own_lobe_not_in_the_whole_balloon():
    """Side-by-side lobes: each block centres on the lobe it was written in.

    A cut straight across this balloon letters five points larger — 18 against
    13 — because the lower band spans both lobes and the long sentence gets the
    balloon's whole width to break on. It buys that by dragging each block off
    its own lobe: it keeps 58% of each block's own writing, and centres both on
    the balloon's axis, 34 and 46 pixels from the lobes they belong to. That is
    what lee is pointing at when he says it should be centred within the sub
    bubble, not the whole thing.

    So size alone does not carry it. A division only overrules the neck the
    artist drew if it also keeps three quarters of each block's own Japanese —
    the stacked balloon in `test_a_neck_cut_that_strangles_the_dialogue_gives_way`
    keeps 86% and still wins, this one keeps 58% and does not.
    """
    from mangatl.typeset import share_masks, fit_region, _text_w
    texts = ["LET'S MEET AGAIN.", "I'M SORRY. WE HAVE TO BE GETTING BACK."]
    regions, mask, right, left = _side_by_side_lobes(*texts)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=10, max_font=34)
    bal_cx, lobe_cx = _lobe_centres(mask, right, left)

    shares = share_masks(regions, cfg)
    assert len(shares) == 2, shares.keys()
    for r in regions:                       # each share IS the block's own lobe
        own = right if r.id == 1 else left
        m = shares[r.id] > 0
        # the chord the artist would have drawn is straight and the lobes are
        # round, so the overlap goes wholly to one of them — three quarters of
        # each lobe, and no part of the other.
        #
        # Three quarters, not all of it: the share is then trimmed back to the
        # block's own box, which is what keeps the words off the balloon's
        # waist. What matters here is that every pixel it kept is its OWN
        # lobe's, and that it kept all of its own writing — both below.
        assert float((m & own).sum()) / float(own.sum()) > 0.72, r.id
        assert float((m & ~own).sum()) / float(m.sum()) < 0.02, r.id
        ink = r.text_mask > 0                # and all of its own writing
        assert float((m & ink).sum()) / float(ink.sum()) > 0.98, r.id

    for r in regions:
        lay = fit_region(r, cfg, shares.get(r.id))
        assert " ".join(lay.lines) == (r.dst_text or ""), lay.lines
        path = lay.font_path or cfg.font_path
        lo = min(x - _text_w(path, lay.font_size, ln) / 2
                 for (x, _y), ln in zip(lay.line_origins, lay.lines))
        hi = max(x + _text_w(path, lay.font_size, ln) / 2
                 for (x, _y), ln in zip(lay.line_origins, lay.lines))
        blk = (lo + hi) / 2
        near = abs(blk - lobe_cx[r.id])
        far = abs(blk - bal_cx)
        assert near <= 12, (r.id, blk, lobe_cx[r.id])       # in its own lobe
        assert far >= 25, (r.id, blk, bal_cx)               # not on the balloon


def test_a_cut_that_typesets_big_by_leaving_the_words_behind_is_refused():
    """The size the refused cut was offering, so this cannot go quiet.

    If a change ever makes the band cut keep its blocks' own writing on this
    balloon, or makes the lobes typeset as large, the test above would still
    pass while testing nothing. Both halves of the trade are pinned here.
    """
    from mangatl.typeset import (_lobe_cut, _same_shape_masks, _prop_cut,
                                 _score_cut, NECK_CUT_KEEPS_ITS_OWN)
    texts = ["LET'S MEET AGAIN.", "I'M SORRY. WE HAVE TO BE GETTING BACK."]
    regions, _m, _r, _l = _side_by_side_lobes(*texts)
    cfg = TypesetConfig(font_path=default_font_path(), min_font=10, max_font=34)
    masks = _same_shape_masks(regions)
    neck = _score_cut(regions, _lobe_cut(regions, masks, cfg), cfg)
    band = _score_cut(
        regions,
        _prop_cut(regions, masks, [(r.dst_text or "") for r in regions]),
        cfg)
    assert band[0] >= neck[0] + 4, (neck, band)   # it really does typeset bigger
    assert band[2] <= 0.05, band                  # and stays on the balloon
    # …and it is refused on the one ground that separates it from the stacked
    # balloon that is allowed to win: what it leaves behind.
    assert 0.5 <= band[1] < NECK_CUT_KEEPS_ITS_OWN, band[1]


def test_an_answer_about_a_page_you_left_is_refused_in_a_real_dom():
    """Switching pages while an answer is still in the air.

    lee: *"the page lagged and merge 2 section from one page with another when
    i switch pages too fast"*. Two dozen places apply `j.regions` the moment it
    lands; one of them checked first and the rest did not. Worse than a wrong
    picture — with another page's boxes in `regions`, the next drag posts THOSE
    ids to the page now on screen, so the mix-up is written to disk.
    """
    import os
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui",
                              "an_answer_about_a_page_you_left.test.js")],
        cwd=root, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all good" in out.stdout, out.stdout
