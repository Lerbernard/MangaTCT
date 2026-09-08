# -*- coding: utf-8 -*-
"""A block may take a balloon. It may not take somebody else's.

lee, over a crop of page 005 with a word in it that had turned to nonsense:
*"u is moving again"*, and the month before, of the same box: *"em is very far
form the original box"*.

The word was `Zarudone` and it was not drawn wrong. A second block was printed
straight through it::

    ...Would the
    Queen of
    Z(Um:!ɔne      <- "Zarudone" with "Um..." set on top of it
    tell you to
    peek?

`あの…` sits at the top right of the big balloon and is detected as free text,
its own ink at `[773, 972, 41, 94]`. It was typeset at `[687, 1099, 60, 28]` -
120px away, in the middle of the dialogue.

## How a freefloat ends up holding a whole balloon

`attach_balloons` offers the balloon search to free-floating blocks for one
reason: so that a block which turns out to be inside a balloon can be
**renamed** a bubble. On a reload that renaming is deliberately off - lee:
*"boxes chaning type after i reload the projet"*; the label wins over the
geometry. What was left was the worst half of both rules: the block kept the
kind that says it has no balloon, and was handed one anyway.

Worse on the reload path than at detection, because of who is eligible. At
detection both blocks are looking, so `_share` divides the balloon between
them. On a reload the dialogue already carries its mask and is skipped, so the
freefloat is the ONLY member - and one member gets the whole thing.

Then `typeset.share_masks` declines to divide it. `_balloon_groups` asks only
bubbles to share a balloon, on purpose, so that a GRRRR drawn across a
balloon's flank cannot shove a line of dialogue. So: two blocks, one piece of
paper, both centred in it.

## Why the fix is not "stop offering it"

That was tried first and it is wrong. `test_a_box_you_named_stays_named` says
why in one line - *"refusing to look would typeset the English into the bare
box"* - and the bare box is the tall narrow column the Japanese was set in. A
caption sitting alone in a balloon needs that balloon.

What no block is entitled to is the shape a balloon-carrying block is ALREADY
typesetting into. So the search still runs, and `project.drop_borrowed_
balloons` hands back what was not this block's to have, on the way in.

**The test is that the shape is somebody else's, not that it is big.** A
freefloat is entitled to a shape larger than its box - that is what
`give_room` is for. Two shares of one balloon are disjoint by construction
(the detector takes a hairline off each), so an overlap anywhere near
`SAME_BALLOON` can only be one shape counted twice.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import project as P                           # noqa: E402
from mangatl.models import TextRegion                      # noqa: E402


def _shape(w=420, h=420, cx=210, cy=210, rx=150, ry=110):
    """One balloon's paper, as a mask."""
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
    return m


def _poly(mask):
    cnts, _ = cv2.findContours((mask > 0).astype(np.uint8),
                               cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outer = max(cnts, key=cv2.contourArea)
    return cv2.approxPolyDP(outer, 1.0, True).reshape(-1, 2).tolist()


def _region(rid, kind, bbox, mask):
    return TextRegion(id=rid, bbox=bbox, kind=kind,
                      text_mask=None,
                      bubble_mask=(None if mask is None
                                   else (mask > 0).astype(np.uint8) * 255),
                      bubble_bbox=tuple(bbox),
                      polygon=(None if mask is None else _poly(mask)))


def _pair(free_kind="freefloat"):
    """The shape of lee's page: a bubble and a free block holding the same
    balloon, and the free block's own ink well away from the middle."""
    m = _shape()
    return [_region(0, "bubble", [180, 190, 60, 40], m),
            _region(5, free_kind, [330, 90, 41, 94], m)]


# ------------------------------------------------------------------ the case

def test_the_free_block_gives_the_balloon_back():
    rs = _pair()
    assert P.drop_borrowed_balloons(rs) == 1
    free = rs[1]
    assert free.bubble_mask is None
    assert tuple(free.bubble_bbox) == (330, 90, 41, 94)
    assert free.polygon == [[330, 90], [371, 90], [371, 184], [330, 184]]


def test_the_bubble_keeps_it():
    """It is the owner. Nothing about this pass may take a balloon off a block
    that is entitled to one."""
    rs = _pair()
    P.drop_borrowed_balloons(rs)
    assert rs[0].bubble_mask is not None
    assert len(rs[0].polygon) > 4


def test_a_sound_gives_it_back_too():
    """`NO_BALLOON_KINDS` is the two families, not just the one lee hit."""
    rs = _pair("sfx")
    assert P.drop_borrowed_balloons(rs) == 1
    assert rs[1].bubble_mask is None


def test_a_sub_type_is_answered_by_its_family():
    """A box's geometry is decided by which of the three families it is, never
    by which sub-type - the rule `_no_balloon` was written to keep.

    `sfx_big` is one of lee's own, so it has to be registered here the way an
    open project registers it. An unregistered sub-type reads as a bubble by
    design (`kinds.family_of`: an unknown kind is the family where being wrong
    costs least), which means this pass leaves it alone rather than taking a
    balloon off something that might be entitled to one - the safe way round.
    """
    from mangatl import kinds as K
    was = K.known()
    try:
        K.use([{"key": "sfx_big", "family": "sfx"}])
        rs = _pair("sfx_big")
        assert P.drop_borrowed_balloons(rs) == 1
        assert rs[1].bubble_mask is None
    finally:
        K.use(was)


def test_the_stale_polygon_goes_as_well_as_the_mask():
    """The two come apart. `region_from_record` already refuses to rebuild a
    MASK from a balloon polygon on a kind that cannot have one, so a chapter
    loads with the mask gone and the polygon still borrowed - and the polygon
    is what the editor draws as the box, so lee sees a piece of free text
    outlined as the whole balloon and can drag the balloon by it."""
    rs = _pair()
    rs[1].bubble_mask = None                     # ...as it arrives off disk
    assert P.drop_borrowed_balloons(rs) == 1
    assert rs[1].polygon == [[330, 90], [371, 90], [371, 184], [330, 184]]


# ------------------------------------------------------- and what it leaves

def test_a_free_block_alone_in_a_balloon_keeps_it():
    """The case the search exists for. Nobody else is typesetting into this
    balloon, so it is not borrowed - and taking it away would put the English
    back in the tall narrow column the Japanese was set in."""
    rs = [_region(5, "freefloat", [180, 190, 60, 40], _shape())]
    assert P.drop_borrowed_balloons(rs) == 0
    assert rs[0].bubble_mask is not None


def test_a_free_block_with_a_shape_of_its_own_keeps_it():
    """Bigger than its box is not the test. `give_room` hands unballooned
    writing the empty paper around it, which is exactly that, and this pass
    must not undo it."""
    mine = _shape(cx=340, cy=130, rx=60, ry=70)
    rs = [_region(0, "bubble", [180, 190, 60, 40], _shape()),
          _region(5, "freefloat", [330, 90, 41, 94], mine)]
    assert P.drop_borrowed_balloons(rs) == 0
    assert rs[1].bubble_mask is not None


def test_two_real_shares_of_one_balloon_are_left_alone():
    """Shares are DISJOINT - the detector takes a hairline off each. Two of
    them must never look like one shape held twice."""
    whole = _shape()
    left, right = whole.copy(), whole.copy()
    left[:, 210:] = 0
    right[:, :214] = 0
    rs = [_region(0, "bubble", [120, 190, 60, 40], left),
          _region(5, "freefloat", [260, 190, 60, 40], right)]
    assert P.drop_borrowed_balloons(rs) == 0
    assert rs[1].bubble_mask is not None


def test_a_page_of_bubbles_is_untouched():
    rs = [_region(0, "bubble", [180, 190, 60, 40], _shape()),
          _region(1, "bubble", [180, 190, 60, 40], _shape())]
    assert P.drop_borrowed_balloons(rs) == 0
    assert all(r.bubble_mask is not None for r in rs)


def test_nothing_to_hand_it_back_to():
    """Two free blocks holding one shape and no owner in sight. Odd, and not
    this pass's business: it takes a balloon back TO somebody."""
    rs = _pair()
    rs[0].kind = "sfx"
    assert P.drop_borrowed_balloons(rs) == 0


def test_the_search_still_offers_a_balloon_to_free_text():
    """The other half, pinned here as well as in
    `test_a_box_you_named_stays_named`: narrowing the search was tried as the
    fix and takes the balloon off a caption alone in one. It stays wide, and
    the borrowing is answered afterwards."""
    import inspect

    from mangatl.detect import balloon as B
    src = inspect.getsource(B.attach_balloons)
    assert src.count("freefloat") >= 2, "the search stopped offering it"


def test_the_repair_runs_on_the_way_in():
    """Every reload comes through `find_balloons`, and it has to run there -
    after the search, which is where the borrowing happens, and before
    `give_room`, which is what puts the block back on its own paper."""
    import inspect

    src = inspect.getsource(P.find_balloons)
    at_attach = src.index("attach_balloons(")
    at_drop = src.index("drop_borrowed_balloons(")
    at_room = src.index("give_room(")
    assert at_attach < at_drop < at_room, src
