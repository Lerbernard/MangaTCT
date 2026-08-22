"""Two sound effects in one box come apart.

lee, with a box drawn round 와아아아 AND 쾅: *"these 2 clusters shou be thei own
boxes"*, and the rule he read off the page himself - *"if there are a 2-3 box
that are close to eachoter and one that fater away it probably a difrent
sfx"*.

He is right about the shape. Measured over all 49 sound-effect boxes of a
46-page chapter - CRAFT's characters inside each box, and the gap between
neighbours normalised by character size - every box that really is ONE effect
has neighbour gaps of 0.35 or less, and three boxes have gaps of 0.84, 1.26
and 1.75. A clean empty band.

**And distance alone still splits two of those three wrongly.** Cropped and
looked at one at a time:

    001#1  gap 0.84   와아아아 | 쾅              two effects  <- the one to split
    004#3  gap 1.26   콰앙 | a stray CRAFT box    one effect
    030#2  gap 1.75   킥킥 | its own trailing ..  one effect

So the far thing being far is not the test - what it IS is the test. In 001#1
both sides are writing of comparable size, 261px against 118px. The other two
are a speck on empty artwork and a pair of dots. Sized at the cut: 0.45, 0.29,
0.14.

**One positive example.** lee: *"do this ill do anther chapter later"*. Hence
the conservative shape - three conditions, all of which must hold - and hence
this file, which pins what each one was measured against so the next chapter
can widen it on evidence rather than on memory.
"""
import pytest

from mangatl.detect.comictext import (SPLIT_ALIKE, SPLIT_GAP, SPLIT_LEAST,
                                      _around, _core_gap, _cores_in,
                                      _two_effects_in, _widest_link)


def sq(x, y, s):
    """A character box of side `s` with its top-left at (x, y)."""
    return (x, y, x + s, y + s)


# The measured cases, as characters. The sizes and spacings are the real ones.
ROW_AND_BANG = [sq(70, 0, 110), sq(190, 20, 110), sq(310, 45, 110),
                sq(430, 70, 110),                      # 와아아아, a chain
                sq(350, 330, 260)]                     # 쾅, far and BIG
EFFECT_AND_SPECK = [sq(180, 1360, 260), sq(230, 1600, 270),   # 콰앙
                    sq(500, 1370, 78)]                        # a stray box
EFFECT_AND_DOTS = [sq(350, 130, 118), sq(470, 140, 110),      # 킥킥
                   sq(650, 250, 16)]                          # its own `..`


# ------------------------------------------------------------ the measuring

def test_the_gap_is_in_units_of_the_smaller_character():
    """`reach_groups` measures this way and so does this, so a chasm between
    small glyphs and a nick between big ones read on one scale - which is the
    whole reason one threshold can serve every chapter."""
    assert _core_gap(sq(0, 0, 100), sq(150, 0, 100)) == pytest.approx(.5, abs=.01)
    # ...the same 50px gap between characters half the size is twice as far.
    assert _core_gap(sq(0, 0, 50), sq(100, 0, 50)) == pytest.approx(1.0, abs=.01)
    # Touching characters are no distance apart, which is most of a real
    # effect.
    assert _core_gap(sq(0, 0, 100), sq(100, 0, 100)) == 0


def test_the_longest_link_is_a_step_in_a_chain_not_a_span():
    """와아아아 is four characters in a row, so its two ENDS are far apart and
    no bounding measure could tell that from a real break. A spanning tree
    only ever asks about neighbours, so what comes back is the step from the
    row to 쾅."""
    gap, a, b = _widest_link(ROW_AND_BANG)
    assert gap > SPLIT_GAP
    assert sorted([len(a), len(b)]) == [1, 4]
    four = a if len(a) == 4 else b
    assert sorted(four) == [0, 1, 2, 3], "the row is what stays together"


def test_a_row_on_its_own_is_never_torn_up():
    """The same four characters with nothing else in the box. Every link is a
    neighbour step, so the longest one is still a neighbour step."""
    assert _two_effects_in(ROW_AND_BANG[:4]) is None


# ------------------------------------------------------- and the three cases

def test_the_box_lee_pointed_at_comes_apart():
    got = _two_effects_in(ROW_AND_BANG)
    assert got is not None
    a, b = got
    assert sorted([len(a), len(b)]) == [1, 4]


def test_a_stray_craft_box_does_not_split_an_effect():
    """004#3. The far thing is a rectangle on empty artwork, and at 78px
    against 270px it is not writing of the same size as 콰앙."""
    assert _two_effects_in(EFFECT_AND_SPECK) is None


def test_an_effects_own_trailing_dots_stay_with_it():
    """030#2. `킥킥..` - the dots are 16px against 118px. They are part of
    what is being said, and a box of their own would be a box of nothing."""
    assert _two_effects_in(EFFECT_AND_DOTS) is None


def test_two_characters_are_never_split():
    """With two you cannot tell a chain from a break: there is one gap and
    nothing to call it long against. Thirty-one of the chapter's 49 boxes hold
    exactly two characters, so this guard is most of the safety."""
    far = [sq(0, 0, 100), sq(400, 400, 100)]
    assert _core_gap(*far) > SPLIT_GAP, "the fixture has to be a wide gap"
    assert _two_effects_in(far) is None
    assert SPLIT_LEAST == 3


def test_a_gap_inside_the_measured_range_is_left_alone():
    """0.35 is the widest gap found inside a real effect on the chapter, and
    the bar is 0.60 - so the whole measured range of real effects sits under
    it with room to spare."""
    close = [sq(0, 0, 100), sq(130, 0, 100), sq(260, 0, 100)]
    assert max(_core_gap(close[i], close[i + 1]) for i in (0, 1)) < SPLIT_GAP
    assert _two_effects_in(close) is None


def test_the_two_bars_sit_in_the_gaps_they_were_measured_into():
    """Written down as a test because a threshold with no room either side is
    a threshold that moves the first time anything else does.

    Gap: real effects reach 0.35, the merges start at 0.84.
    Alike: the merge is 0.45, the two false ones are 0.29 and 0.14.
    """
    assert 0.35 < SPLIT_GAP < 0.84
    assert 0.29 < SPLIT_ALIKE < 0.45


# ------------------------------------------------------------- the plumbing

def test_only_the_characters_inside_the_box_are_asked_about():
    pieces = [sq(10, 10, 40), sq(300, 300, 40), sq(20, 15, 30)]
    got = _cores_in(pieces, (0, 0, 100, 100))
    assert len(got) == 2 and all(g[0] < 100 for g in got)


def test_a_character_a_pixel_outside_still_counts():
    """The box IS the union of these rectangles, so rounding has already put
    one of them a hair outside the box it helped define. Refusing it there
    would drop a character out of its own effect."""
    assert len(_cores_in([sq(-2, -2, 40)], (0, 0, 100, 100))) == 1
    # ...but a whole character's width away is somebody else's box.
    assert _cores_in([sq(140, 0, 40)], (0, 0, 100, 100)) == []


def test_the_new_box_is_drawn_round_its_own_characters():
    # x 10..90 and y 20..50, inclusive: 81 wide and 31 tall.
    assert _around([sq(10, 20, 30), sq(60, 20, 30)]) == (10, 20, 81, 31)


def test_the_split_runs_after_the_last_join():
    """A join is what puts the two halves of ONE effect back together, so a
    split running before it would be undone by the very next line - and after
    the census too, so the kind it reads is the settled one rather than the
    coverage pass's first guess."""
    import inspect

    from mangatl.detect import comictext
    src = inspect.getsource(comictext.detect_comictext)
    assert src.rindex("_join_overlapping(regions, join_over)") < \
        src.index("_two_effects_in(cores)")


def test_nothing_but_sound_effects_is_ever_split():
    """Dialogue is printed type in a balloon: the block head boxes it well,
    and two speakers in one balloon are `_each_text_its_own_box`'s question,
    asked of the writing rather than of the spacing."""
    import inspect

    from mangatl.detect import comictext
    src = inspect.getsource(comictext.detect_comictext)
    at = src.index("_two_effects_in(cores)")
    assert '_kinds.family_of(r.kind) == "sfx"' in src[at - 400:at]
