"""A box only CRAFT saw needs more than a graze before it joins a measured one.

lee, on his own chapter's page 029: *"oo7 is acualy god because it dont crop
any part of teh sfx while 029 has a sfx green box thats donst exist"*.

What the run actually does, traced end to end on 029:

1. CRAFT boxes a character group at (306,1328)-(362,1390) on the stone
   balustrade behind the two women. There is no writing in it.
2. Nothing else on the page saw that mark, so `craft.merge_into` makes it a
   region of its own -- a box with **no text mask**, because no pass that
   measures ink was ever involved.
3. `_grow_to_the_stroke` follows the dark band of the balustrade and the box
   goes from 72x78 to 166x176, a compound **5.2x**.
4. That grown rectangle now grazes the box over the real 웅성 lower down the
   panel -- which came off the coverage pass and DOES carry a mask -- by
   **0.090** of the smaller.
5. `_join_overlapping`'s floor is 0.05, so they join, and the sound effect
   comes out as one box **282x304** lying across a piece of architecture.

The fault is step 5 and not step 3: growing before joining is deliberate and
right, and it is what puts a shout split across two clipped boxes back
together. Four other pairs on this chapter overlap ONLY because both boxes
grew, and every one of them must join.

**What separates them is provenance, and only provenance.** Measured over 26
pages of chapter 1, on all 24 pairs of boxes that overlap at join time:

    both sides CRAFT's alone      0.015 (001's fragment, which joins later in
                                  the run at 0.322 once it has grown again),
                                  0.093 (045 울렁), 0.182, 0.189, 0.202,
                                  0.203, 0.273, 0.322, 0.765, 1.000
                                                     -- all must join
    exactly one side CRAFT's      0.090  029#6 / the 웅성   <- the only wrong one
                                  0.283, 0.389, 0.618, 1.000 x5  -- must join
    neither side CRAFT's          0.019 .. 0.846     -- untouched

The gap on the mixed rows runs from 0.090 to 0.283 with nothing in it, and the
nine above it include 042's chapter title and 031's two balloons. `JOIN_ALONE`
sits at 0.20, near the middle of a 3.1x chasm.

Three other separations were measured on the same pairs and every one of them
puts a REAL pair on the wrong side, which is why the rule is not written on
any of them:

    how far the box grew   the biggest grower on the chapter, 8.56x, is a real
                           fragment of 001's effect (lee: *"12 and 5 are small
                           part of a bigger sfx"*)
    ink colour agreement   029's pair are 12 apart out of 255 -- among the
                           CLOSEST of the 20 pairs
    ink in the overlap     029 is at 0.119 and 045's real 울렁 pair at 0.000

**Manga is off.** CRAFT only runs on manhwa and manhua, so on manga no region
ever has `text_mask=None` and this rule can never fire.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT
from mangatl.models import TextRegion


def _r(bbox, kind="sfx", mask=None):
    """A region. `mask=None` is a box only CRAFT saw."""
    return TextRegion(id=0, bbox=tuple(int(v) for v in bbox),
                      text_mask=mask, bubble_mask=None,
                      bubble_bbox=tuple(int(v) for v in bbox), kind=kind)


PAGE_W, PAGE_H = 690, 3600          # a canvas that holds every box named here


def _measured(bbox, kind="sfx"):
    """A region a pass that measures ink produced: it carries a mask.

    Page-sized, like every mask the run actually makes -- `_join_overlapping`
    takes the maximum of two masks and two crops would not broadcast.
    """
    x, y, w, h = bbox
    m = np.zeros((PAGE_H, PAGE_W), np.uint8)
    m[y:y + h, x:x + w] = 255
    return _r(bbox, kind=kind, mask=m)


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a.bbox
    bx, by, bw, bh = b.bbox
    ox = min(ax + aw, bx + bw) - max(ax, bx)
    oy = min(ay + ah, by + bh) - max(ay, by)
    if ox <= 0 or oy <= 0:
        return 0.0
    return ox * oy / float(min(aw * ah, bw * bh))


# --------------------------------------------------------------- lee's 029

# The two rectangles as the run actually produces them, after the grow.
PHANTOM = (220, 1298, 166, 176)          # CRAFT's alone, on the balustrade
UNGSEONG = (304, 1442, 198, 160)         # the coverage pass's, over 웅성


def test_the_pair_on_029_really_does_graze():
    """The measurement the rule is written on, pinned so it cannot drift."""
    got = _overlap(_r(PHANTOM), _r(UNGSEONG))
    assert 0.085 <= got <= 0.095
    assert CT.JOIN_OVER < got < CT.JOIN_ALONE


def test_a_box_only_craft_saw_does_not_swallow_the_effect_next_to_it():
    """lee's 029: the balustrade box and the 웅성 box stay two boxes."""
    craft_only = _r(PHANTOM)
    measured = _measured(UNGSEONG)
    out = CT._join_overlapping([craft_only, measured], CT.JOIN_OVER)
    assert len(out) == 2
    assert {tuple(r.bbox) for r in out} == {PHANTOM, UNGSEONG}


def test_the_effect_keeps_its_own_box_and_not_the_union():
    """The point of the rule is the EFFECT's box, not the phantom's.

    A box that covers 웅성 and the balustrade together is the thing lee saw;
    282x304 is what the union comes to.
    """
    out = CT._join_overlapping([_r(PHANTOM), _measured(UNGSEONG)],
                               CT.JOIN_OVER)
    assert (220, 1298, 282, 304) not in {tuple(r.bbox) for r in out}


# ------------------------------------------------- and what must still join

def test_two_boxes_craft_alone_saw_still_join_on_a_graze():
    """045's 울렁, in two boxes that overlap by 0.093 -- a graze under the
    raised bar and over the old floor.

    Neither side was seen by a pass that measures ink, so the raised bar does
    not apply and the old floor stands. This is the pair the rule would break
    if it were written on the overlap alone rather than on provenance: it sits
    at 0.093 against 029's 0.090, three thousandths apart on the wrong side.
    """
    a, b = _r((411, 2754, 94, 118)), _r((419, 2860, 104, 114))
    got = _overlap(a, b)
    assert CT.JOIN_OVER < got < CT.JOIN_ALONE
    assert abs(got - _overlap(_r(PHANTOM), _r(UNGSEONG))) < 0.01
    assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 1


def test_two_measured_boxes_still_join_on_a_graze():
    """Neither side is CRAFT's alone, so nothing changes for them either."""
    a, b = _measured((100, 100, 120, 120)), _measured((180, 100, 120, 120))
    assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 1


def test_a_craft_box_well_inside_a_measured_one_still_joins():
    """042's chapter title: the mixed pairs that must join sit at 0.283 and up.

    The rule refuses a graze, not an overlap -- a box CRAFT invented that
    really does lie inside a measured one is the same piece of writing.
    """
    craft_only = _r((390, 186, 216, 114))
    measured = _measured((175, 92, 344, 148))
    assert _overlap(craft_only, measured) >= CT.JOIN_ALONE
    assert len(CT._join_overlapping([craft_only, measured], CT.JOIN_OVER)) == 1


def test_the_bar_only_rises_when_exactly_one_side_is_crafts_alone():
    """Both-alone and neither-alone are the old rule, unchanged."""
    graze = ((0, 0, 100, 100), (90, 0, 100, 100))          # 0.10 of the smaller
    for a, b in ((_r(graze[0]), _r(graze[1])),
                 (_measured(graze[0]), _measured(graze[1]))):
        assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 1
    mixed = CT._join_overlapping([_r(graze[0]), _measured(graze[1])],
                                 CT.JOIN_OVER)
    assert len(mixed) == 2


def test_the_raised_bar_is_above_the_floor_it_replaces():
    assert CT.JOIN_ALONE > CT.JOIN_OVER


def test_manga_never_reaches_this_rule():
    """CRAFT is off on manga, so no manga region can be a box CRAFT alone saw."""
    assert CT.tuning_for("manga").get("craft_x") is None
    assert CT.tuning_for("manhwa").get("craft_x") is not None
