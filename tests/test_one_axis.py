"""A block of typesetting stands on one axis, and stands on it everywhere.

lee sent the same narration block twice: selected in the editor it was a neat
centred paragraph, and the moment it was deselected the lines fanned out down
the page, each one at a different horizontal centre. Two pictures of the same
words, and the text jumped between them on every click.

There were two placements. The browser centres a block on its frame - one
axis, which is what a paragraph is. The fitter centred every line on the
balloon's own chord AT THAT LINE'S HEIGHT, which agrees with the browser in a
circle (every chord of a circle shares a centre) and disagrees with it in
anything else. The shapes that come out of a page are very often not circles:
a lobe cut off a two-lobed balloon is a wedge, and a caption with no balloon at
all is measured in a box.

These tests pin the property, not the arithmetic: every line of a fitted block
comes back on the same x, whatever shape it was fitted into.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion
from mangatl.typeset import (TypesetConfig, band_span, chord_edges, fit_region,
                             default_font_path, line_axis, place_lines)

H, W = 520, 420
TEXT = ("WHENEVER I HUGGED MIMI, THE BLACK RABBIT THAT MATCHED HER WHITE "
        "RABBIT LULU... OUR PROOF OF FRIENDSHIP...")


def _cfg(**kw):
    kw.setdefault("font_path", default_font_path())
    kw.setdefault("min_font", 10)
    kw.setdefault("max_font", 34)
    return TypesetConfig(**kw)


def _wedge():
    """A shape whose chord centre walks sideways as you go down it.

    Narrow at the top and hanging off to one side at the bottom, so the chord
    at the first line and the chord at the last line have nothing like the
    same centre. This is the shape a lobe cut off a two-lobed balloon has.
    """
    m = np.zeros((H, W), np.uint8)
    pts = np.array([[150, 40], [265, 40], [360, 470], [95, 470]], np.int32)
    cv2.fillPoly(m, [pts], 255)
    return m


def _ragged_columns():
    """The footprint of vertical Japanese: columns of unequal height.

    No two rows of it agree on where the middle is, which is exactly why the
    blocks lee photographed staircased.
    """
    m = np.zeros((H, W), np.uint8)
    for i, (x, top, bot) in enumerate(((90, 60, 460), (150, 90, 400),
                                       (210, 40, 480), (270, 120, 350))):
        for y in range(top, bot, 24):
            cv2.rectangle(m, (x - 8, y), (x + 8, y + 16), 255, -1)
    return m


def _xs(layout):
    return [int(o[0]) for o in layout.line_origins]


# ------------------------------------------------------------- the property

@pytest.mark.parametrize("name, mask", [("wedge", _wedge()),
                                        ("ellipse", None)])
def test_every_line_of_a_fitted_block_shares_one_axis(name, mask):
    if mask is None:
        mask = np.zeros((H, W), np.uint8)
        cv2.ellipse(mask, (210, 260), (150, 210), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, bbox=cv2.boundingRect(mask), bubble_mask=mask)
    r.dst_text = TEXT
    lay = fit_region(r, _cfg())
    assert len(lay.lines) > 3, lay.lines        # a block, not a one-liner
    assert len(set(_xs(lay))) == 1, (name, _xs(lay), lay.lines)


@pytest.mark.parametrize("kind", ["narration", "freefloat"])
def test_a_caption_with_no_balloon_does_not_staircase(kind):
    """The case in lee's screenshot: on-art text, no balloon anywhere.

    The region falls back to its box, and the block that comes out of it is
    centred on one line - which is what the browser draws when the same block
    is selected, so nothing moves when it is clicked. Both halves matter: the
    box is what gives the block one chord to be centred on, and free-floating
    speech used to be handed the Japanese instead.
    """
    ink = _ragged_columns()
    r = TextRegion(id=1, bbox=cv2.boundingRect(ink), text_mask=ink,
                   kind=kind)
    assert r.bubble_mask is None
    r.dst_text = TEXT
    lay = fit_region(r, _cfg())
    assert len(lay.lines) > 3, lay.lines
    xs = _xs(lay)
    assert len(set(xs)) == 1, (xs, lay.lines)
    # And it is the middle of the BOX, which is what the browser falls back to
    # while the block is being dragged.
    bx, _, bw, _ = r.bbox
    assert abs(xs[0] - (bx + bw / 2)) <= 2, (xs[0], r.bbox)
    # The block is also typeset at a readable size. Measured against the
    # Japanese instead, the real fit finds nothing at all - every row of a
    # column of characters has a gap in it - and the block drops through to
    # the last-resort wrap at single figures.
    assert lay.font_size >= 18, (lay.font_size, lay.lines)


def test_hand_broken_lines_land_on_one_axis_too():
    """`place_lines` is what a hand-edited block is re-placed by.

    It shares the fitter's arithmetic on purpose, so a block someone has typed
    breaks into cannot drift away from a block the fitter broke.
    """
    origins = place_lines(["WHENEVER I", "HUGGED MIMI,", "THE BLACK",
                           "RABBIT THAT"], _wedge(), _cfg(), 20, 1.12)
    assert origins is not None
    assert len({int(o[0]) for o in origins}) == 1, origins


# ------------------------------------------------- how the axis is chosen

def test_the_axis_is_read_off_the_lines_not_the_room_they_were_offered():
    """Room the words did not use must not drag the block sideways.

    Choosing the axis from the strip every line could reach WHATEVER it turned
    out to say is the conservative answer, and it is dearer than it looks: on
    the two-lobed bud it narrowed four short words to the width of the worst
    band and cost the block two points of type. Asking the question of the
    lines as they actually came out costs nothing - a block that fits its
    bands still fits them - and leaves the size alone.
    """
    spans = [(40.0, 100.0), (30.0, 140.0)]     # a wedge: 60 wide, then 110
    # Narrow words: both bands can hold them, so the axis is free to sit in
    # the middle of the shape rather than in the middle of the common strip.
    assert line_axis(spans, [20.0, 20.0]) == pytest.approx(77.5)
    # Wide words: now the top band really does bind, and the axis obeys it.
    assert line_axis(spans, [58.0, 58.0]) == pytest.approx(71.0)


def test_an_impossible_block_splits_the_overhang_evenly():
    """Some shapes cannot hold some blocks dead straight.

    Better half a letter over each edge than a whole word off one of them.
    """
    spans = [(0.0, 40.0), (60.0, 100.0)]       # no column in common at all
    assert line_axis(spans, [10.0, 10.0]) == pytest.approx(50.0)
    assert line_axis([], []) == 0.0


def test_the_axis_lets_a_line_reach_both_ends_of_its_band():
    """The measurement the axis is chosen against is the honest one.

    `band_span` is the strip EVERY row of the band has, so a line centred on
    the axis is inside the shape for its whole height - not just at its
    middle row.
    """
    m = _wedge()
    left, right = chord_edges(m > 0)
    a, b = band_span(left, right, 100, 130)
    assert a > 0 and b > a
    assert (m[100:130, int(a):int(b) + 1] > 0).all()
    assert not (m[100:130, int(a) - 3] > 0).all()
