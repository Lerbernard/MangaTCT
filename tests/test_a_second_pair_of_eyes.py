"""The detector that sees what comic-text-detector's mask cannot.

lee, on a Korean webtoon with every box type ticked::

    try to fix the bouble detecttion and teh 2 boxes beigng found as one and
    teh sfc not fully beigng found and one text haing manyt small boxes

Three of those four are one fact. Measured on chapter 227 page 026 -- 720x2770,
eight 하아 in red brush across a blue panel, covering something like a sixth of
the page::

    blocks: conf>0.05: 0   conf>0.10: 0   conf>0.22: 0   conf>0.40: 0
    mask:   keep>0.05: 0.254%   keep>0.20: 0.042%   keep>0.30: 0.028%

Nothing at any confidence and a mask that is black. The same shapes on WHITE
(page 018) puts 1.15% on the mask and CTD boxes it -- but only the half of each
stroke that crosses white, which is 다닥써! coming back as its left half. So the
missing sound effects, the half-found ones and the ones in many small pieces
are all **the mask going black on coloured brush-drawn shapes over artwork**.

CRAFT -- easyocr's detector, already installed here for Korean OCR -- covers
82% of that ink with no box over 1.8% of the page.

These tests are the guard on the JOINT: that the second detector adds to the
first rather than overruling it, that it is grouped by the same rule the mask's
marks are, and that a box big enough to be a panel never becomes a region.
"""
import numpy as np
import pytest

from where import PKG

from mangatl.detect import craft as CR
from mangatl.detect import comictext as CT
from mangatl.models import TextRegion


def _g(x0, y0, x1, y1, pieces=None):
    """One CRAFT group: its box, and the pieces it was made of."""
    return {"box": [x0, y0, x1, y1], "pieces": pieces or [[x0, y0, x1, y1]]}


def _r(x, y, w, h, kind="sfx"):
    return TextRegion(id=0, bbox=(x, y, w, h), kind=kind,
                      bubble_bbox=(x, y, w, h))


# ------------------------------------------------- the settings, and why

def test_the_craft_settings_are_the_measured_ones():
    """Swept on page 026 against how much sound-effect ink is covered and how
    big the biggest box is:

        low_text  link   pieces   biggest   ink covered
           0.40    0.4        8     41.7%         93.7%
           0.45    0.8       24      6.7%         89.1%
           0.50    0.8       30      1.8%         82.1%   <- here
           0.55    0.8       33      1.6%         73.9%

    A box covering 46% of the page "covers 94% of the ink" and is a panel.
    """
    assert CR.LOW_TEXT == 0.50
    assert CR.LINK_THRESH == 0.80


def test_the_knobs_that_measured_nothing_are_not_pretended_to_matter():
    """`canvas_size`, `mag_ratio` and `text_threshold` gave an IDENTICAL result
    on every row of the sweep -- the page's long side already hits the canvas
    cap, and text_threshold only seeds regions that low_text then grows. They
    are constants with that written next to them, not tuning."""
    src = (PKG / "detect" / "craft.py").read_text(encoding="utf-8")
    assert "moved NOTHING" in src


def test_a_machine_without_easyocr_is_not_a_traceback(monkeypatch):
    """easyocr brings torch with it, and this app can be installed without
    ever having done the Korean OCR setup. Find text on that machine has to go
    on working the way it did yesterday -- one detector, no second opinion, no
    traceback in the middle of a chapter.

    The import is forced to fail rather than trusted to: easyocr IS installed
    on the machine these tests run on, so the guard is dead code here unless
    something breaks it on purpose.
    """
    import builtins
    real = builtins.__import__

    def no_easyocr(name, *a, **k):
        if name == "easyocr" or name.startswith("easyocr."):
            raise ImportError("no easyocr on this machine")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_easyocr)
    assert CR.available() is False


def test_a_machine_with_easyocr_says_so():
    """The other side of the guard. Skipped rather than failed where easyocr
    is genuinely absent: this one asserts a fact about the machine, and a test
    that fails because of what is installed says nothing about the code. The
    test above is the load-bearing one and needs no easyocr at all."""
    pytest.importorskip("easyocr")
    assert CR.available() is True


# --------------------------------------------------------- one rule, two uses

def test_the_reach_is_the_same_function_the_mask_goes_through():
    """The whole claim of this module is *same rule, different marks*. Two
    copies of a union-find drift, and then the format's numbers mean one thing
    on the mask and another here."""
    src = (PKG / "detect" / "craft.py").read_text(encoding="utf-8")
    assert "reach_groups" in src
    hv = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    at = hv.index("def _harvest(")
    assert "reach_groups(" in hv[at:at + 2000], \
        "the mask's own harvest must go through it too"


def test_two_pieces_side_by_side_are_one_effect():
    boxes = [[0, 0, 40, 40], [60, 0, 100, 40]]      # 20px gap, 40px pieces
    got = CR.group(boxes, near_x=0.6, near_y=0.3)
    assert len(got) == 1
    assert got[0]["box"] == [0, 0, 100, 40]
    assert got[0]["pieces"] == boxes, "a group keeps what it was made of"


def test_two_pieces_stacked_are_two_effects_at_the_same_reach():
    """Writing runs along a line: the reach is wide and flat, so the same gap
    joins sideways and does not join vertically. This is the property the
    ellipse exists for."""
    boxes = [[0, 0, 40, 40], [0, 60, 40, 100]]      # the same 20px gap
    got = CR.group(boxes, near_x=0.6, near_y=0.3)
    assert len(got) == 2


def test_a_piece_reaches_by_the_smaller_of_the_two():
    """A big mark must not reach across a panel to pull in a small one."""
    boxes = [[0, 0, 400, 400], [430, 0, 450, 20]]   # gap 30, smaller is 20
    assert len(CR.group(boxes, near_x=1.0, near_y=1.0)) == 2
    assert len(CR.group(boxes, near_x=2.0, near_y=2.0)) == 1


# ------------------------------------------------------------- the three cases

def test_a_group_over_nothing_becomes_a_new_region():
    """The 하아 case: CTD returned nothing there at all."""
    regions = [_r(0, 0, 50, 50, "bubble")]
    added = CR.merge_into(regions, {id(regions[0])},
                          [_g(300, 300, 400, 400)], 720, 2770, cap=0.05)
    assert added == [(300, 300, 400, 400)]
    assert regions[0].bbox == (0, 0, 50, 50), "the balloon must not move"


def test_a_group_over_a_block_head_region_is_dropped():
    """CTD's block head is the best thing here at dialogue -- it finds black
    balloons with white typesetting, which nothing looking for dark ink can.
    CRAFT run over a balloon reaches past its edge into the drawing, so where
    the two disagree about a balloon the block head wins.

    The block here HOLDS the group -- it covers most of it, which is what
    CRAFT spilling past a balloon's edge looks like. A block that covers only
    a fragment is the next test, and it is the other way round."""
    r = _r(100, 100, 200, 100, "bubble")
    added = CR.merge_into([r], {id(r)}, [_g(90, 90, 320, 220)],
                          720, 2770, cap=0.5)
    assert added == []
    assert r.bbox == (100, 100, 200, 100), "and it is not grown either"


def test_a_block_fragment_does_not_veto_the_writing_it_missed():
    """lee's chapter title: thirteen display characters CRAFT boxed cleanly,
    vetoed because the block head had seen two FRAGMENTS of it -- each
    covering a tenth to a third of the group. lee: *"4 missed most of teh
    text"*. A block region only stands in a group's way when it covers at
    least `BLOCK_HOLDS` of it."""
    r = _r(100, 100, 60, 40, "freefloat")           # a fragment
    g = _g(90, 90, 400, 260)
    ga = (400 - 90) * (260 - 90)
    assert (60 * 40) / ga < CR.BLOCK_HOLDS, "not the fragment case"
    added = CR.merge_into([r], {id(r)}, [g], 720, 2770, cap=0.5)
    assert added, "the fragment vetoed the whole title again"


def test_the_veto_bar_is_the_published_one():
    """The line between a balloon and a fragment. CRAFT past a balloon edge
    leaves the block covering most of the group; the title's fragments
    covered 0.10-0.36 of theirs."""
    assert 0.36 < CR.BLOCK_HOLDS <= 0.75


def test_a_group_over_a_half_found_effect_grows_it():
    """*"the sfc not fully beigng found"*. On page 018 the mask holds the half
    of 다닥써! that crosses white, so CTD boxes the left half and CRAFT boxes
    the whole thing. The region grows to hold both."""
    r = _r(100, 100, 100, 60, "sfx")                # CTD: the left half
    added = CR.merge_into([r], set(), [_g(100, 100, 320, 170)],
                          720, 2770, cap=0.5)
    assert added == [], "one effect, one box -- not the half plus the whole"
    assert r.bbox == (100, 100, 220, 70)


def test_growing_is_a_union_and_not_a_replacement():
    """The two boxes are measurements of the same writing by two detectors and
    each can be short at a different edge. On page 018 CRAFT reaches further
    right than the mask did; the mask, which is measured off actual ink, can
    sit a few pixels higher. Taking CRAFT's box wholesale would crop whatever
    only CTD saw -- and the region carries the text mask the cleaner paints
    out, so a cropped box leaves ink on the page."""
    r = _r(100, 100, 120, 80, "sfx")                # 100..220 x 100..180
    CR.merge_into([r], set(), [_g(150, 130, 320, 170)], 720, 2770, cap=0.5)
    assert r.bbox == (100, 100, 220, 80), \
        "x0 and y0 come from CTD, x1 from CRAFT, y1 from CTD"


def test_growing_keeps_the_text_mask():
    """The mask on the region is a real measurement of where ink is and it is
    what the cleaner paints out. Growing the box must not throw it away."""
    r = _r(100, 100, 100, 60, "sfx")
    r.text_mask = np.ones((60, 100), np.uint8)
    CR.merge_into([r], set(), [_g(100, 100, 320, 170)], 720, 2770, cap=0.5)
    assert r.text_mask is not None


def test_growing_takes_the_bubble_box_with_it():
    """`bubble_bbox` is where the English may be placed. Left behind, the
    typesetter would fit English into the half CTD found."""
    r = _r(100, 100, 100, 60, "sfx")
    CR.merge_into([r], set(), [_g(100, 100, 320, 170)], 720, 2770, cap=0.5)
    assert r.bubble_bbox == r.bbox


def test_a_region_with_no_bubble_box_does_not_gain_one():
    r = _r(100, 100, 100, 60, "sfx")
    r.bubble_bbox = None
    CR.merge_into([r], set(), [_g(100, 100, 320, 170)], 720, 2770, cap=0.5)
    assert r.bubble_bbox is None


# -------------------------------------------------------------- and the panel

def test_a_group_the_size_of_a_panel_is_thrown_away():
    """At low_text 0.30 CRAFT returns a box covering 46% of page 026, and it
    would score as covering 94% of the sound-effect ink. The cleaner would
    paint the panel out."""
    added = CR.merge_into([], set(), [_g(0, 0, 720, 1400)], 720, 2770,
                          cap=0.05)
    assert added == []


def test_a_panel_sized_group_falls_back_to_its_pieces():
    """The bottom of page 026 is four 하아 cascading diagonally down a dress.
    CRAFT boxes their nine syllables correctly -- the biggest raw piece on the
    whole chapter is 2.2% of its page -- and then the grouping sweeps all nine
    into one box 26% of the page, because **every consecutive pair has gx = 0
    and gy = 0**: the bounding boxes overlap, since the cascade runs diagonally.

    Zero gap is zero gap at every threshold. No reach separates them, so this
    is not a number to tune, it is a case to have an answer for. Nine boxes on
    nine syllables is worse than four boxes on four effects and much better
    than a box that has the cleaner paint out a quarter of the page -- and
    joining boxes by hand takes a second, while finding a sound effect that
    silently vanished does not.
    """
    pieces = [[0, 0, 100, 300], [95, 100, 200, 400], [195, 200, 300, 500]]
    g = {"box": [0, 0, 300, 500], "pieces": pieces}
    added = CR.merge_into([], set(), [g], 720, 2770, cap=0.05)
    assert len(added) == 3, "the writing survives as its syllables"
    assert [a[0] for a in added] == [0, 95, 195]


def test_the_fallback_is_not_a_way_round_the_cap():
    """The pieces get measured against the cap too. A group can be over it
    because ONE of its pieces is a panel and the rest are writing — CRAFT does
    return the occasional huge box — and letting the fallback wave that one
    through would put a painted-out panel back on the page by the side door."""
    pieces = [[0, 0, 60, 60], [0, 100, 720, 1500]]
    g = {"box": [0, 0, 720, 1500], "pieces": pieces}
    added = CR.merge_into([], set(), [g], 720, 2770, cap=0.05)
    assert added == [(0, 0, 60, 60)], "the small piece only"


def test_a_group_with_one_piece_over_the_cap_is_still_dropped():
    """The fallback is not a way round the cap. A single CRAFT piece that is
    somehow the size of a panel has nothing smaller to fall back to and must
    not become a region."""
    g = {"box": [0, 0, 720, 1400], "pieces": [[0, 0, 720, 1400]]}
    assert CR.merge_into([], set(), [g], 720, 2770, cap=0.05) == []


def test_the_cap_is_measured_against_the_page_and_not_the_box():
    """Same box, two page sizes: on a short page it is a panel, on a long one
    it is a sound effect."""
    g = [_g(0, 0, 400, 400)]
    assert CR.merge_into([], set(), g, 720, 1000, cap=0.05) == []
    assert CR.merge_into([], set(), g, 720, 8000, cap=0.05) != []


# ------------------------------------------------------------------ the joint

def test_nothing_here_touches_manga():
    """Every manga number was measured by cropping and looking at each box the
    gates dropped across 39 pages. A second detector added for the webtoons
    must not be reachable from a manga chapter."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert '"manga"' in src
    assert CT.tuning_for("manga")["join_x"] is None
