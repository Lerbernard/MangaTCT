# -*- coding: utf-8 -*-
"""What the typesetter fits into when it has nothing to fit into.

lee: *"if the typesetter can't find a box it hsoud fall back to using the
box"*.

`place_mask()` has said *"Bubble if we have one, else the box"* since the day
it was written, and it kept that promise only while some OTHER mask was around
to say how big the page is::

    if self.text_mask is None or family_of(self.kind) == "sfx":
        return self.text_mask          # ...which is None

`H, W = self.text_mask.shape[:2]` is the line that needed it, so with no ink
mask the box was never built and `None` came back instead. `_fit_region` then
returned a layout with no lines in it, which on the page is a balloon that
lost its dialogue.

## Who is in that state

**Every region in a reopened chapter.** `TextRegion.to_dict` drops
`text_mask`, `bubble_mask` and `share_mask` - nothing written to disk
remembers a shape - so re-typesetting a block after a reload emptied it. The
same fact is already written up in `test_ink_colour._forget_masks`, where it
explains why reloaded pages typeset white speech in black; this is the other
half of the bill.

**And any sound effect whose ink nobody found.** An sfx keeps its own ink on
purpose, and a mask of all zeros is not None - it survived every guard and
then measured a shape with no room anywhere in it.

## Where the fallback goes

In the FITTER, not in `place_mask`. The eraser reads `place_mask()` too
(`inpaint`), and a box-shaped answer there would rub out a rectangle of
artwork round writing whose footprint nobody could find. `box_mask()` is the
shared arithmetic; only the typesetter asks for it.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion                       # noqa: E402
from mangatl.typeset import TypesetConfig, fit_region       # noqa: E402
import mangatl.typeset as T                                 # noqa: E402


LINE = "THIS IS THE DIALOGUE THAT WENT MISSING"


def _r(kind="bubble", **kw):
    return TextRegion(id=1, bbox=(30, 40, 300, 120), kind=kind,
                      dst_text=LINE, **kw)


# ------------------------------------------------- the shape it falls back to

def test_a_region_with_no_mask_at_all_still_gets_typeset():
    r = _r()
    assert r.place_mask() is None, "fixture no longer reproduces the state"
    lay = fit_region(r, TypesetConfig())
    assert lay.lines, "the block came back empty"
    assert " ".join(lay.lines).replace("- ", "") .split() == LINE.split()


def test_the_words_land_inside_the_box_they_were_given():
    r = _r()
    lay = fit_region(r, TypesetConfig())
    x, y, w, h = r.bbox
    for cx, cy in lay.line_origins:
        assert x <= cx <= x + w, (cx, r.bbox)
        assert y <= cy <= y + h, (cy, r.bbox)


def test_it_is_the_box_and_not_a_line_of_type_at_the_floor():
    """The failure it replaces was not "smaller", it was "nothing". This is
    the other direction: a box 300x120 has room for real type."""
    lay = fit_region(_r(), TypesetConfig())
    assert lay.font_size > TypesetConfig().min_font, lay.font_size


def test_a_sound_effect_whose_ink_was_never_found():
    """All zeros is not None. It passed every guard and then priced every
    line at no room at all."""
    r = _r(kind="sfx")
    r.text_mask = np.zeros((400, 500), np.uint8)
    assert r.place_mask() is not None and not r.place_mask().any()
    lay = fit_region(r, TypesetConfig())
    assert lay.lines, "an effect with no measured ink came back empty"


def test_an_empty_balloon_is_not_a_balloon_either():
    r = _r()
    r.bubble_mask = np.zeros((400, 500), np.uint8)
    lay = fit_region(r, TypesetConfig())
    assert lay.lines


# ------------------------------------------------------ and nothing else moved

def test_a_region_that_has_a_shape_is_left_completely_alone():
    """The fallback fires on `None` or on nothing-at-all, and on nothing
    else - a balloon still wins, and so does an ink mask that has ink in it."""
    r = _r()
    r.bubble_mask = np.zeros((400, 500), np.uint8)
    r.bubble_mask[60:150, 40:320] = 255
    with_shape = fit_region(r, TypesetConfig())
    assert with_shape.lines
    assert r.place_mask() is r.bubble_mask


def test_the_eraser_is_not_handed_a_rectangle():
    """`place_mask()` is what `inpaint` clips its erasing to. If the fallback
    had gone in there, a block whose ink nobody could find would have had the
    whole rectangle round it rubbed out - artwork and all."""
    r = _r()
    assert r.place_mask() is None
    r2 = _r(kind="sfx")
    r2.text_mask = np.zeros((400, 500), np.uint8)
    assert not r2.place_mask().any(), "the eraser was given the box"


def test_the_arithmetic_lives_in_one_place():
    import inspect
    src = inspect.getsource(T._fit_region)
    assert "box_mask(" in src, "the fitter builds its own rectangle"
    assert "np.zeros" not in src.split("kind_font")[0], \
        "the box is drawn twice, once here and once on the model"


# ------------------------------------------------------------- the box itself

def test_the_box_mask_is_page_sized_when_there_is_a_page_to_size_it_by():
    r = _r()
    r.text_mask = np.zeros((400, 500), np.uint8)
    m = r.box_mask()
    assert m.shape == (400, 500)
    x, y, w, h = r.bbox
    assert int((m > 0).sum()) == w * h
    assert (m[y:y + h, x:x + w] > 0).all()


def test_and_stops_at_the_boxs_own_corner_when_there_is_not():
    """Everything downstream works in page coordinates from (0, 0), so a
    shorter array holds the box in the same place a full-page one would."""
    r = _r()
    m = r.box_mask()
    x, y, w, h = r.bbox
    assert m.shape == (y + h, x + w)
    assert (m[y:y + h, x:x + w] > 0).all()
    assert int((m > 0).sum()) == w * h


def test_a_box_with_no_size_is_not_a_box():
    assert TextRegion(id=1, bbox=(10, 10, 0, 40)).box_mask() is None
    assert TextRegion(id=1, bbox=(10, 10, 40, 0)).box_mask() is None


def test_a_box_off_the_edge_of_the_page_is_brought_back_on():
    r = TextRegion(id=1, bbox=(480, 380, 300, 300))
    r.text_mask = np.zeros((400, 500), np.uint8)
    m = r.box_mask()
    assert m.shape == (400, 500)
    assert (m > 0).any(), "the whole box was clipped away"
