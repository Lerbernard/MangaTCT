"""A box only comic-text-detector believes in has to show its letters.

lee, after being shown all fifteen junk boxes with comic-text-detector's mask
drawn over them: *"the middle path is one line: keep a CTD sfx box only when
COO is silent and the box passes the balloon test or has real glyph structure.
I'd want to measure it rather than guess"*.

Measured over 23 pages of Japanese. Of 241 boxes, sixteen are comic-text-
detector's own `sfx` family with nothing from COO on them, and eleven of the
sixteen are the artwork -- a fence rail, two hands, a face, two flower marks,
a chin line, a shoulder, two eyes, a rail. Every other cell of the table is
nearly clean. Counting bodies of ink in the mask splits that cell: the real
ones carry 15 and 17 characters against a ceiling of 4 for every artwork box.

    route                                   missed   junk
    CTD finds all + COO labels                   4     15
    CTD finds all + COO labels + this rule       6      4

lee turned it down once -- *"go back to this CTD + COO labels (before)"* --
and then, having seen a page detected both ways, took it: *"this + this rule
(now)"*. So the bar is 5 and the pass runs.

Four things have to hold, and each is a way it could go quietly wrong:

* **The route reads the switch.** A route carrying its own copy of the bar
  would go on dropping boxes the day the switch here is turned off, and every
  measurement test below would still pass.
* **Only one cell is ever asked.** A box COO agrees with is a sound effect
  whatever the mask shows, and a box comic-text-detector calls dialogue is
  never asked. Widening it would throw away the 113 bubble boxes that hold
  one bad box between them.
* **The count is of BODIES, not of ink.** Fill does not separate these --
  measured 0.13-0.37 for the artwork against 0.18-0.38 for the writing -- and
  a rule written against fill would look identical and do nothing.
* **A box with no mask under it is not silently dropped.** `glyph_bodies` is
  asked of `page.seg_mask`, and a caller with no mask must not lose its whole
  sfx family to a measurement that could not be taken.
"""
import numpy as np
import pytest

from where import PKG

from mangatl.detect import dbcoo


def _mask(shape, blobs):
    """A page mask with `blobs` separate square marks of `side` pixels."""
    m = np.zeros(shape, np.uint8)
    for x, y, side in blobs:
        m[y:y + side, x:x + side] = 255
    return m


def test_a_line_of_writing_is_many_bodies():
    m = _mask((200, 200), [(20, 20 + 18 * i, 10) for i in range(8)])
    assert dbcoo.glyph_bodies(m, (10, 10, 60, 190)) == 8


def test_one_shape_is_one_body():
    m = _mask((200, 200), [(20, 20, 80)])
    assert dbcoo.glyph_bodies(m, (10, 10, 120, 120)) == 1


def test_specks_do_not_count_as_characters():
    """Screen tone and printing dirt are not letters."""
    m = _mask((200, 200), [(20 + 12 * i, 20, 3) for i in range(9)])
    assert dbcoo.glyph_bodies(m, (10, 10, 190, 60)) == 0


def test_only_the_ink_inside_the_box_is_counted():
    m = _mask((200, 200), [(20, 20, 10), (150, 150, 10)])
    assert dbcoo.glyph_bodies(m, (0, 0, 60, 60)) == 1


def test_a_missing_mask_answers_zero_rather_than_raising():
    assert dbcoo.glyph_bodies(None, (0, 0, 50, 50)) == 0


def test_a_box_off_the_page_answers_zero():
    m = _mask((200, 200), [(20, 20, 10)])
    assert dbcoo.glyph_bodies(m, (300, 300, 340, 340)) == 0


def test_the_box_is_clipped_to_the_page_rather_than_wrapping():
    """A rectangle running off the edge still counts what is on the page."""
    m = _mask((200, 200), [(180, 180, 12)])
    assert dbcoo.glyph_bodies(m, (170, 170, 260, 260)) == 1


def test_a_box_off_the_left_edge_does_not_read_the_right_one():
    """A negative coordinate counts from the far side unless it is clamped."""
    m = _mask((200, 200), [(10, 10, 12)])
    assert dbcoo.glyph_bodies(m, (-50, -50, 50, 50)) == 1


def test_a_body_of_exactly_the_floor_is_a_character():
    """40 pixels of area is in, not out -- the comparison is `>=`."""
    m = np.zeros((100, 100), np.uint8)
    m[20:25, 20:28] = 255          # 5 x 8 = 40 pixels exactly
    assert dbcoo.glyph_bodies(m, (0, 0, 100, 100), min_area=40) == 1
    assert dbcoo.glyph_bodies(m, (0, 0, 100, 100), min_area=41) == 0


def test_the_bar_is_five_bodies():
    """lee, having seen both pages: *"this + this rule (now)"*.

    The measured split: 15 and 17 bodies for the two real boxes, a ceiling of
    4 for every one of the eleven artwork ones. Five is the only number
    between them, and 0 turns the whole pass off.
    """
    assert dbcoo.SFX_GLYPHS == 5


def test_the_bar_sits_between_the_two_shapes():
    """Fifteen bodies for 001's credits strip against one for a hand."""
    writing = _mask((300, 300), [(20, 20 + 18 * i, 10) for i in range(15)])
    artwork = _mask((300, 300), [(20, 20, 90)])
    assert dbcoo.glyph_bodies(writing, (0, 0, 300, 300)) >= dbcoo.SFX_GLYPHS
    assert dbcoo.glyph_bodies(artwork, (0, 0, 300, 300)) < dbcoo.SFX_GLYPHS


def test_the_balloon_arm_is_off():
    """It changes no miss on the chapter and puts one junk box back."""
    assert dbcoo.SFX_KEEP_WALLED is False


def test_the_route_reads_the_switch_rather_than_a_number_of_its_own():
    """`glyphs` reaches `detect_ctd_sfx` and defaults to whatever is set here.

    Not to a literal: a route carrying its own copy of the bar would go on
    dropping boxes the day the switch here is turned off, and every other test
    in this file would still pass.
    """
    import inspect
    sig = inspect.signature(dbcoo.detect_ctd_sfx)
    assert sig.parameters["glyphs"].default == dbcoo.SFX_GLYPHS
    assert sig.parameters["glyphs"].default == 5


def test_the_speck_floor_is_its_own_setting():
    m = _mask((200, 200), [(20 + 12 * i, 20, 5) for i in range(6)])
    assert dbcoo.glyph_bodies(m, (0, 0, 200, 60), min_area=100) == 0
    assert dbcoo.glyph_bodies(m, (0, 0, 200, 60), min_area=4) == 6


@pytest.mark.parametrize("side,want", [(6, 1), (7, 1)])
def test_a_body_is_kept_at_the_area_floor(side, want):
    """40 pixels of area: a 6x6 mark is 36 and out, a 7x7 is 49 and in."""
    m = _mask((100, 100), [(20, 20, side)])
    assert dbcoo.glyph_bodies(m, (0, 0, 100, 100)) == (0 if side == 6
                                                       else want)


def test_the_route_still_carries_a_docstring_about_what_it_costs():
    """The trade is lee's to revisit, so the numbers stay next to the code."""
    assert "missed" in dbcoo.detect_ctd_sfx.__doc__
    assert PKG
