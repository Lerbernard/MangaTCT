"""A box with nothing in it, and the guard that used to keep it.

`_a_stray_mark` throws away a rectangle that holds one thin swash and little
else -- *"a systme that clears out bad boxes a pr boxes on art"*. It had a
guard at the top that read

    if not ink.any():
        return False

so a box holding **nothing at all** -- the emptiest case the rule describes --
was the one case it refused to judge, and the box survived.

Nothing found it, because while CRAFT was the only second detector nothing
ever made one. Measured over all 69 pages of lee's chapter: of the 23 boxes
that only CRAFT finds, **not one has under 5% ink in it** and the median is
28%. CRAFT boxes character clusters, and a character cluster is ink.

It showed the moment a detector arrived that could put a rectangle on blank
paper. Trying DBNet in CRAFT's place produced 208 boxes against CRAFT's 177,
and 35 of the 54 it alone found had **under 5% ink**, 29 of them exactly
zero -- empty rectangles sitting on the white beside a balloon. Every one of
them walked through this rule untouched.

DBNet is not being shipped (see `claude/two-detectors-and-one-real-bug`), so
the empty boxes are hypothetical again. The bug is not. Falling through gives
the right answer with no new code: no marks is not more than `STRAY_PIECES`,
and a fill of zero is under any threshold.

And it is not quite a no-op. Over the same 69 pages the fix changes exactly
one page and changes it for the better: 008 gains a box on the 사 of the pale
blue 사아아, a sound effect CRAFT half-finds. An empty box next to it was
being kept, and `_join_overlapping` was folding the real one into it.
"""
import cv2
import numpy as np
import pytest

from where import PKG

from mangatl.detect import comictext as CT


def _blank(v=245):
    return np.full((300, 300), v, np.uint8)


def _mask_of(page):
    return ((page < CT.INK).astype(np.uint8) * 255)


# ------------------------------------------------- the empty box goes

def test_a_box_holding_nothing_is_a_stray():
    """The case the guard used to exempt."""
    page = _blank()
    assert CT._a_stray_mark(page, (0, 0, 300, 300), _mask_of(page))


def test_a_box_holding_nothing_is_a_stray_without_a_mask_either():
    """No text mask, so the rule reads the paper itself. Blank paper has no
    dark side and no light side worth the name, and either way there is
    nothing in the rectangle."""
    assert CT._a_stray_mark(_blank(), (0, 0, 300, 300), None)


def test_an_empty_box_on_a_dark_page_is_a_stray_too():
    """A black panel is as empty as a white one. The rule picks whichever of
    dark-or-light is the sparser and asks how much of the box it fills; on
    flat paper of any tone the answer is nothing."""
    assert CT._a_stray_mark(np.full((300, 300), 12, np.uint8),
                            (0, 0, 300, 300), None)


def test_a_box_with_an_all_zero_mask_is_a_stray():
    """The mask is what the cleaner paints out. A region carrying an empty one
    is a region that would paint nothing, which is the definition of a box
    with nothing in it."""
    assert CT._a_stray_mark(_blank(), (0, 0, 300, 300),
                            np.zeros((300, 300), np.uint8))


# ------------------------------------------------- and writing still stays

def test_a_line_of_writing_is_still_kept():
    """The whole rule, unchanged where it matters. Four syllable blocks."""
    page = _blank()
    for i in range(4):
        cv2.rectangle(page, (40 + i * 55, 130), (80 + i * 55, 175), 30, -1)
    assert not CT._a_stray_mark(page, (0, 0, 300, 300), _mask_of(page))


def test_a_shape_that_fills_its_box_is_still_kept():
    page = _blank()
    cv2.rectangle(page, (30, 30), (270, 270), 30, -1)
    assert not CT._a_stray_mark(page, (0, 0, 300, 300), _mask_of(page))


def test_one_thin_swash_is_still_a_stray():
    """The box lee actually reported: an ornamental flourish, alone."""
    page = _blank()
    cv2.line(page, (30, 150), (270, 150), 30, 3)
    assert CT._a_stray_mark(page, (0, 0, 300, 300), _mask_of(page))


def test_exactly_two_marks_in_an_empty_rectangle_is_still_a_stray():
    """`STRAY_PIECES` is *at most* two, not fewer than two.

    Two crumbs left on the strokes of an effect are two of the eleven boxes
    the rule was measured on -- 031's 쳐벅 -- so the boundary has to be
    inclusive. Two marks and almost no fill is a stray; three marks is
    writing.
    """
    page = _blank()
    cv2.circle(page, (80, 150), 5, 30, -1)
    cv2.circle(page, (220, 150), 5, 30, -1)
    assert CT._a_stray_mark(page, (0, 0, 300, 300), _mask_of(page))
    cv2.circle(page, (150, 150), 5, 30, -1)
    assert not CT._a_stray_mark(page, (0, 0, 300, 300), _mask_of(page))


def test_a_box_too_small_to_judge_is_still_left_alone():
    """Under 400 px of rectangle the rule declines, and that guard stays --
    it is about the measurement being meaningless at that size, not about
    what is inside."""
    assert not CT._a_stray_mark(_blank(), (0, 0, 15, 15), None)


# ------------------------------------------------- the guard is really gone

def test_the_early_return_is_not_in_the_source():
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert "if not ink.any():\n        return False" not in src
    # ...and why, written where the code is.
    assert "emptiest case of this rule" in src


def test_the_sweep_is_still_only_asked_on_the_formats_that_measured_it():
    """Manga's boxes were never measured against this and it stays off there.
    Turning it on everywhere is a mutant, not a tidy-up."""
    assert CT.tuning_for("manga")["stray_fill"] is None
    assert CT.tuning_for("manhwa")["stray_fill"] == CT.STRAY_FILL
    assert CT.tuning_for("manhua")["stray_fill"] == CT.STRAY_FILL


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
