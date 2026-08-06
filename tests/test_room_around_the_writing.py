"""Writing with no balloon gets the empty paper around it — and nothing else.

lee's page 10 is three panels of blank white paper with the narration printed
straight onto them, no balloons anywhere. Two things went wrong there, and this
file locks the answer to both.

The balloon finder walks outward from the writing until it meets an outline.
With no balloon rim to stop it, it ran to the panel frame and handed the
typesetter half a panel — so the English was set at 33pt straight across the
woman and the child. The finder wraps AROUND an obstacle, because it follows a
run of connected paper, and the paper on that page reaches from one side of the
panel to the other behind the figures.

The fallback was no good either: with no balloon at all the region fell back to
its own box, which is the box round the JAPANESE — a tall narrow column,
because that is how Japanese is set. On page 10 that typeset at 12pt beside
Japanese printed at twice the size.

`give_room` is the answer to both. The box grows in each direction
independently until it MEETS something — artwork, the panel frame, another
region's writing, the edge of the page — and stops there. A rectangle stops at
an obstacle where a flood fill goes round it, and that difference is the whole
fix: the area can only ever be blank paper, so the typesetting can only ever land
on blank paper. No threshold decides that; the geometry does.

What is locked here:

* it grows into blank paper
* it stops at artwork, and never covers it
* two captions on one panel do not grow into each other
* it never shrinks anything, and never touches a region that has a balloon
* sound effects are left where they were drawn
* a hand-placed box is not overruled
* the box the person SEES does not move — only the room the English may use
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect.balloon import attach_balloons, give_room, room_around
from mangatl.models import TextRegion


def _page(h=600, w=800):
    """Blank white panel on a black page, the way lee's page 10 is drawn."""
    g = np.zeros((h, w), np.uint8)
    g[40:h - 40, 40:w - 40] = 255
    return g


def _writing(g, x, y, w, h):
    """A column of Japanese: short dark marks stacked down the page."""
    m = np.zeros(g.shape, np.uint8)
    for k in range(y, y + h - 8, 22):
        cv2.rectangle(g, (x, k), (x + w, k + 14), 20, -1)
        cv2.rectangle(m, (x, k), (x + w, k + 14), 255, -1)
    return m


def _region(rid, g, x, y, w, h, kind="freefloat"):
    m = _writing(g, x, y, w, h)
    ys, xs = np.nonzero(m)
    bbox = (int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return TextRegion(id=rid, bbox=bbox, text_mask=m, kind=kind, order=rid,
                      src_text="x", dst_text="X")


def _area(r):
    return int((r.bubble_mask > 0).sum()) if r.bubble_mask is not None else 0


def test_a_caption_on_blank_paper_gets_the_paper():
    """More than the bare column the Japanese was set in, and no more than the
    margin allows — see test_fits_the_box for that ceiling."""
    from mangatl.detect.balloon import GROW_MARGIN
    g = _page()
    r = _region(1, g, 600, 120, 40, 300)
    box = r.bbox[2] * r.bbox[3]
    assert give_room(g, [r]) == 1
    assert box < _area(r) <= box * (1 + 2 * GROW_MARGIN) ** 2 + 1


def test_it_never_covers_the_drawing():
    """The fault on page 10: the English laid across the woman and the child.

    A rectangle stops at the figure; the flood fill the balloon finder uses
    goes round it. This is that difference, measured.
    """
    g = _page()
    cv2.circle(g, (400, 300), 120, 30, -1)        # the drawing
    art = g <= 128
    r = _region(1, g, 600, 150, 40, 260)
    assert give_room(g, [r]) == 1
    area = r.bubble_mask > 0
    assert not (area & art).any(), "the placement area swallowed the artwork"


def test_two_captions_on_one_panel_keep_out_of_each_other():
    g = _page()
    a = _region(1, g, 620, 120, 40, 260)
    b = _region(2, g, 120, 320, 40, 200)
    assert give_room(g, [a, b]) == 2
    assert not ((a.bubble_mask > 0) & (b.bubble_mask > 0)).any()
    # and neither swallowed the other's writing
    assert not ((a.bubble_mask > 0) & (b.text_mask > 0)).any()
    assert not ((b.bubble_mask > 0) & (a.text_mask > 0)).any()


def test_the_writing_is_always_inside_the_room_it_gets():
    g = _page()
    r = _region(1, g, 600, 120, 40, 300)
    give_room(g, [r])
    assert ((r.bubble_mask > 0) | (r.text_mask == 0)).all()


def test_it_never_makes_anything_smaller():
    g = _page()
    cv2.circle(g, (660, 260), 150, 30, -1)        # hemmed in on every side
    r = _region(1, g, 600, 150, 30, 120)
    x, y, w, h = r.bbox
    give_room(g, [r])
    if r.bubble_mask is not None:
        ys, xs = np.nonzero(r.bubble_mask > 0)
        assert xs.min() <= x and ys.min() <= y
        assert xs.max() >= x + w - 1 and ys.max() >= y + h - 1


def test_a_region_with_a_balloon_is_left_alone():
    g = np.full((600, 800), 255, np.uint8)
    cv2.ellipse(g, (400, 300), (170, 120), 0, 0, 360, 20, 3)
    r = _region(1, g, 380, 240, 30, 120, kind="bubble")
    assert attach_balloons(g, [r]) == 1
    before = _area(r)
    assert give_room(g, [r]) == 0
    assert _area(r) == before


def test_a_sound_effect_stays_where_it_was_drawn():
    g = _page()
    r = _region(1, g, 600, 120, 40, 300, kind="sfx")
    assert give_room(g, [r]) == 0
    assert r.bubble_mask is None


def test_a_box_placed_by_hand_is_not_overruled():
    g = _page()
    r = _region(1, g, 600, 120, 40, 300)
    r.manual = True
    assert give_room(g, [r]) == 0


def test_the_box_the_person_sees_does_not_move():
    """Only the placement area is set. The outline drawn in the editor is the
    box round the writing and it stays exactly where it was."""
    g = _page()
    r = _region(1, g, 600, 120, 40, 300)
    bbox, poly, bub = r.bbox, r.polygon, r.bubble_bbox
    give_room(g, [r])
    assert r.bbox == bbox
    assert r.polygon == poly
    assert r.bubble_bbox == bub


def test_nothing_is_saved_so_it_matches_the_page_every_time():
    """The rectangle is worked out again from the page on every load. Running
    it twice must give the same answer, and running it on a region that
    already has one must not compound."""
    g = _page()
    r = _region(1, g, 600, 120, 40, 300)
    give_room(g, [r])
    first = _area(r)
    assert give_room(g, [r]) == 0          # it already has an area
    assert _area(r) == first


def test_room_around_reports_whether_it_grew():
    g = _page()
    r = _region(1, g, 600, 120, 40, 300)
    assert room_around(g, r, [r]) is True
    tight = _page()
    cv2.rectangle(tight, (560, 100), (700, 440), 30, -1)
    s = _region(2, tight, 600, 150, 20, 60)
    # boxed in on all sides by ink: there is no room worth taking
    assert room_around(tight, s, [s]) is False


def test_the_page_edge_stops_it():
    g = np.full((300, 400), 255, np.uint8)     # paper right to the edge
    r = _region(1, g, 190, 100, 20, 80)
    give_room(g, [r])
    ys, xs = np.nonzero(r.bubble_mask > 0)
    assert xs.min() >= 0 and ys.min() >= 0
    assert xs.max() < 400 and ys.max() < 300


def test_it_stops_at_writing_the_page_does_not_show_as_ink():
    """Most writing stops the growth just by being dark. Not all of it does.

    White typesetting on a black panel comes back with a mask the cleaner built
    from the INVERTED split, and those pixels are the light ones — so a scan
    looking for dark ink walks straight through them. A sound effect is also
    never given a room of its own, so it is not in the paper already handed
    out either. Its mask has to stop the caption beside it on its own account,
    or the English gets typeset over the effect.
    """
    g = _page()
    cap = _region(1, g, 620, 120, 40, 260)
    # a pale effect: its mask marks pixels the page shows as PAPER
    pale = np.zeros(g.shape, np.uint8)
    pale[120:380, 300:346] = 255
    fx = TextRegion(id=2, bbox=(300, 120, 46, 260), text_mask=pale,
                    kind="sfx", order=2, src_text="x", dst_text="X")
    assert (g[120:380, 300:346] > 128).all(), "fixture: the effect must be pale"
    assert give_room(g, [cap, fx]) == 1          # only the caption grew
    assert fx.bubble_mask is None
    assert not ((cap.bubble_mask > 0) & (pale > 0)).any()


def test_the_standoff_never_eats_into_the_box():
    """Room is kept clear of whatever stopped the growth. On an axis with no
    room to give, that clearance must not be taken out of the writing's own
    box — the floor is always the box."""
    g = _page()
    r = _region(1, g, 600, 200, 60, 160)
    x, y, w, h = r.bbox
    # walls flush against both sides of the column: nowhere at all to go
    # sideways, plenty of room up and down
    cv2.rectangle(g, (x - 40, 60), (x - 1, 540), 30, -1)
    cv2.rectangle(g, (x + w, 60), (x + w + 40, 540), 30, -1)
    assert give_room(g, [r]) == 1
    ys, xs = np.nonzero(r.bubble_mask > 0)
    assert xs.min() <= x, f"the room bit into the box: {xs.min()} > {x}"
    assert xs.max() >= x + w - 1
    assert ys.min() <= y and ys.max() >= y + h - 1
    assert (r.bubble_mask > 0)[y:y + h, x:x + w].all()


def test_blank_paper_does_not_go_on_for_ever():
    """A page whose gutters are white has nothing to stop the scan short of
    the sheet's own edge. On two of lee's pages the room ran the full height
    and most of the width. A caption belongs near where it was printed, so the
    reach is bounded by the size of the writing itself."""
    g = np.full((900, 1200), 255, np.uint8)     # nothing on the page at all
    r = _region(1, g, 560, 400, 30, 120)
    assert give_room(g, [r]) == 1
    ys, xs = np.nonzero(r.bubble_mask > 0)
    assert xs.min() > 0 and xs.max() < 1199, "the room ran to the paper's edge"
    assert ys.min() > 0 and ys.max() < 899
    assert int((r.bubble_mask > 0).sum()) < 0.25 * g.size
