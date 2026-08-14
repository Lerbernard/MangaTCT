"""A caption is boxed off by straight edges. A balloon is boxed off by a curve.

lee, twice. First *"one box over 2 text boxes and its missed labled as an
outside box"*, and then, of page 006's caption coming back as Outside text:
*"a dn teh ai fuly misslabed teh 6th picture"*.

Counted over every box on all 67 pages of his chapter 1, and every one of the
240 looked at: **23 are captions and not one came back as `narration`.** About
one box in eight.

**Two things were wrong with the old test.** It measured the mean darkness of a
6-pixel strip outside each side and wanted 0.5, which a 3-pixel rule inside a
6-pixel strip cannot reach — and widening the strip makes it worse, not better,
so page 006 scores 0.00 on every side at every distance out to 70 pixels. And
it was looking for the wrong thing anyway: half this chapter's captions have no
dark rule at all. Four are navy system panels with an ornate LIGHT frame and
two are gold.

**The uniform-region idea was tried and failed**, and that is worth keeping.
Flood the paper the writing sits on and ask whether it is a rectangle: on a
white page a white caption panel's inside is continuous with the page around
it, so it is not. Region fill came out at 0.68 for captions against 0.77 for
balloons — no separation at all. The same fact that killed the two-white-lobes
idea for the double balloon.

So ask about the EDGE and not the region. Scan outward from each side for one
row — or column — where the picture changes sharply at the same place right
across the box. A printed rule does that; so does the boundary of a navy panel,
a gold frame, and a white panel lying on artwork. A balloon outline is a curve
and crosses any given row in two places, so it cannot.

    reach 1.2   across 0.70..0.90   step 20..45   3 sides
        -> 16 of 23 captions, 0 of 118 balloons wrongly called captions

All nine combinations in that range give exactly 16 and 0, which is what makes
it a threshold and not a fit. Reaching to 2.0 finds one or two more and starts
flagging balloons at the loose end. The seven it misses stay `bubble`, which is
what they are today, so nothing gets worse.

Run through the real detector on the pages lee sent, 006's caption now comes
back as a Caption box, and page 007's four captions with it.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT


def _page(h=400, w=400, fill=255):
    return np.full((h, w), fill, np.uint8)


BOX = (100, 100, 300, 220)          # X1, Y1, X2, Y2 -- 200 by 120


def _words(g, box=BOX, v=0, inset=20):
    """Something for the box to be drawn round.

    Inset from the box's own edges, and this matters: the scan compares the row
    just outside an edge with the row just inside it, so writing that starts
    exactly ON the edge is itself a straight edge right across the box. The
    first version of these fixtures did that and every one of them found four
    sides, balloons included.
    """
    x0, y0, x1, y1 = box
    for i in range(x0 + inset, x1 - inset, 24):
        g[y0 + inset:y1 - inset, i:min(i + 14, x1 - inset)] = v
    return g


def _panel(g, x0, y0, x1, y1, edge=0, inside=None):
    if inside is not None:
        g[y0:y1, x0:x1] = inside
    g[y0:y0 + 3, x0:x1] = edge
    g[y1 - 3:y1, x0:x1] = edge
    g[y0:y1, x0:x0 + 3] = edge
    g[y0:y1, x1 - 3:x1] = edge
    return g


# ---------------------------------------------------------------- the rule

def test_a_ruled_caption_has_four_straight_edges():
    g = _page()
    _panel(g, 60, 60, 340, 260)
    _words(g)
    assert CT._straight_edges(g, BOX) == 4


def test_a_balloon_has_none():
    """An ellipse crosses any given row in two places and never right across
    the box, which is the whole of why this works."""
    g = _page()
    cv2.ellipse(g, (200, 160), (170, 130), 0, 0, 360, 0, 3)
    _words(g)
    assert CT._straight_edges(g, BOX) == 0


def test_a_light_frame_on_a_dark_panel_counts():
    """Four of this chapter's captions are navy panels with an ornate light
    frame. There is no dark rule to find and the old test could not see them."""
    g = _page(fill=255)
    g[60:260, 60:340] = 30                    # the panel
    _panel(g, 60, 60, 340, 260, edge=230)     # ...with a LIGHT frame
    _words(g, v=255)
    assert CT._straight_edges(g, BOX) >= 3


def test_a_borderless_panel_on_artwork_counts():
    """No rule drawn at all — just white paper laid over the drawing. The
    boundary is still a straight edge."""
    g = _page(fill=40)
    g[60:260, 60:340] = 250
    _words(g)
    assert CT._straight_edges(g, BOX) == 4


def test_the_bar_is_three_sides_and_not_four():
    """A caption running off the edge of the panel, or with one side lost in
    the artwork, is still a caption."""
    g = _page()
    _panel(g, 60, 60, 340, 260)
    g[60:260, 330:341] = 255                  # rub out the right-hand rule
    _words(g)
    assert CT._straight_edges(g, BOX) == 3
    assert CT._classify_kind(g, BOX) == "narration"


def test_two_sides_is_not_enough():
    """A panel rule above and below the writing and nothing either side is a
    band across the page, not a caption box. Two of the chapter's balloons sit
    between panel edges like that and both stay balloons."""
    g = _page()
    g[60:63, :] = 0
    g[257:260, :] = 0
    _words(g)
    assert CT._straight_edges(g, BOX) == 2
    assert CT._classify_kind(g, BOX) != "narration"


def test_the_edge_has_to_run_the_whole_way_across():
    """A short rule under half the box is a piece of the drawing."""
    g = _page()
    _panel(g, 60, 60, 340, 260)
    _words(g)
    g[60:63, 60:220] = 255                    # break the top rule in the middle
    assert CT._straight_edges(g, BOX) == 3


def test_the_reach_is_measured_off_the_box():
    """1.2 times the box's own height and width. A rule further out than that
    belongs to the panel the caption is in, not to the caption."""
    g = _page(1400, 1400)
    box = (600, 600, 800, 720)
    _words(g, box)
    _panel(g, 40, 40, 1360, 1360)             # a frame right round the page
    assert CT._straight_edges(g, box) == 0


# ------------------------------------------------------- and where it sits

def test_the_caption_question_is_asked_before_the_outside_text_one():
    """Page 006's caption is a white panel on a starfield: the ring round it is
    0.433 bright against a 0.45 bar, so the freefloat test claimed it before
    anything else got a look. That is what lee saw."""
    g = _page(fill=10)                        # a dark page
    g[60:260, 60:340] = 250                   # a bright panel on it
    _words(g)
    assert CT._classify_kind(g, BOX) == "narration"


def test_text_on_open_artwork_is_still_outside_text():
    g = _page(fill=10)
    _words(g, v=255)
    assert CT._classify_kind(g, BOX) == "freefloat"


def test_a_balloon_is_still_a_balloon():
    g = _page()
    cv2.ellipse(g, (200, 160), (170, 130), 0, 0, 360, 0, 3)
    _words(g)
    assert CT._classify_kind(g, BOX) == "bubble"


def test_the_numbers_are_the_measured_ones():
    """Anywhere in reach 1.2 / across 0.70-0.90 / step 20-45 gives the same 16
    and 0 on the chapter. Outside it, one of those two stops being true."""
    assert CT.RULE_REACH == 1.2
    assert 0.70 <= CT.RULE_ACROSS <= 0.90
    assert 20 <= CT.RULE_STEP <= 45
    assert CT.RULE_SIDES == 3
