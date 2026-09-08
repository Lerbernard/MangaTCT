# -*- coding: utf-8 -*-
"""White writing on a black balloon, and the one line that assumed otherwise.

lee, with page 9 of his chapter: *"why is teh typeseeting so bad"*. It was not
the typesetting.

## What was on the page

A solid black balloon with white Japanese in it, exported with its interior
turned into a mottled field of screentone dots. The English sat on that mess
and could not be read.

## The one line

`project.region_from_record` rebuilds a saved region's glyph mask from the
scan, and it did it like this::

    glyph = (gray <= INK) & (bubble > 0)

**Ink is dark.** It is, almost everywhere - a manga page is black on white -
and the exceptions are rare enough to go unnoticed for a long time. On this
balloon that line marked the BALLOON as writing and the LETTERS as clean:
**24,164 pixels of "ink" in a balloon of 26,758**, ninety per cent of it.

Everything downstream then did exactly what it was told and got it wrong:

* the cleaner was asked to erase ninety per cent of the balloon;
* `inpaint._flat_from` samples the ground standing off the ink by twelve
  pixels, and twelve pixels round that mask is the whole balloon - so it had
  **not one pixel** of ground to measure, answered "I cannot tell", and the
  flat fill was refused on the one box whose colour was least in doubt;
* Telea filled the hole from what surrounds it, which is dotted screentone.

## The rule

**The writing is the minority.** A balloon is mostly ground with a little
writing on it, so if the dark pixels are most of the balloon then dark is the
GROUND and the writing is what stands out of it.

Asked only of a genuinely black balloon - 60% dark and up, against about 10%
for a white one on the same page - because the two populations are nowhere near
each other and a rule that fired in between would be guessing.

And asked of a BALLOON and of nothing else, which is what the `balloon` flag is
for. A balloon is a shape whose ground is one colour; the rectangle that stands
in where there is no balloon is a box round leaning writing, and a box round a
heavy sound effect really can be more ink than paper. Trusting the fraction
alone turned one of those inside out - caught here by
`test_a_rectangle_of_writing_is_not_a_black_balloon`, which is the argument for
writing the test that states the BOUNDARY and not only the one that states the
case.

`inpaint.ALGO` is bumped, so every plate cleaned by the old rule retires
itself. The same arrangement, and the same reason, as the 2026-08-12-b entry:
this is not in `inpaint.py` and the plate cache does not watch this file.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.project import _writing_in, DARK_GROUND, INK, PAPER   # noqa: E402


def _balloon(w=120, h=180):
    """A filled ellipse, the way a balloon mask arrives."""
    m = np.zeros((h + 60, w + 60), np.uint8)
    cv2.ellipse(m, (w // 2 + 30, h // 2 + 30), (w // 2, h // 2),
                0, 0, 360, 255, -1)
    return m


def _page(bubble, ground, ink):
    """A scan: `ground` inside the balloon, artwork outside, `ink` writing."""
    g = np.full(bubble.shape, 40, np.uint8)        # dark artwork outside
    g[bubble > 0] = ground
    # four bars of writing, well inside
    ys, xs = np.nonzero(bubble)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    for k in range(4):
        y = y0 + (y1 - y0) * (k + 1) // 6
        g[y:y + 7, x0 + 25:x1 - 25] = ink
    return g


def _lit(mask):
    return int((mask > 0).sum())


# ------------------------------------------------------- the rule

def test_dark_writing_on_a_white_balloon_is_the_writing():
    """The ordinary case, and it must not move a pixel."""
    b = _balloon()
    g = _page(b, ground=250, ink=10)
    got = _writing_in(g, b)
    assert _lit(got) > 100, "no writing found at all"
    assert _lit(got) < 0.25 * _lit(b), ("the ground came back as writing",
                                        _lit(got), _lit(b))
    # ...and it is where the letters are: dark inside the balloon.
    assert (g[got > 0] <= INK).all()


def test_white_writing_on_a_black_balloon_is_also_the_writing():
    """lee's page 009. This is the one that used to come back inside out."""
    b = _balloon()
    g = _page(b, ground=12, ink=250)
    got = _writing_in(g, b, balloon=True)
    assert _lit(got) > 100, "no writing found at all"
    assert _lit(got) < 0.25 * _lit(b), ("the balloon came back as writing",
                                        _lit(got), _lit(b))
    assert (g[got > 0] >= PAPER).all()


def test_the_two_answers_are_the_same_shape():
    """The same marks, drawn either way round, has to come back as the
    same marks - not as one set of marks and one photographic negative."""
    b = _balloon()
    light = _writing_in(_page(b, ground=250, ink=10), b, balloon=True)
    dark = _writing_in(_page(b, ground=12, ink=250), b, balloon=True)
    both = int(((light > 0) & (dark > 0)).sum())
    either = int(((light > 0) | (dark > 0)).sum()) or 1
    assert both / either > 0.9, (both, either)


def test_the_old_rule_is_what_it_used_to_be_on_a_white_balloon():
    """Byte for byte, so that a chapter of white balloons is untouched."""
    b = _balloon()
    g = _page(b, ground=250, ink=10)
    was = ((g <= INK) & (b > 0)).astype(np.uint8) * 255
    assert np.array_equal(_writing_in(g, b), was)


def test_nothing_fires_in_between():
    """A balloon half in shadow is not a black balloon. The two populations
    are 10% and 84% dark on lee's own page, so the line is drawn in the gap
    and the middle is left with the rule that has always held."""
    b = _balloon()
    g = np.full(b.shape, 40, np.uint8)
    g[b > 0] = 250
    ys, xs = np.nonzero(b)
    half = (ys.min() + ys.max()) // 2
    shade = b.copy()
    shade[half:, :] = 0
    g[(b > 0) & (shade == 0)] = 20        # the bottom half in shadow: 50% dark
    got = _writing_in(g, b)
    assert (g[got > 0] <= INK).all(), "the dark half was read as writing"


def test_a_rectangle_of_writing_is_not_a_black_balloon():
    """The boundary, and the reason the rule takes a flag rather than trusting
    the fraction. Where there is no balloon the box stands in, and a box round
    a heavy sound effect really can be more ink than paper - this fixture is
    63% dark. Left to the fraction alone the rule turned it inside out, and
    this test is what caught that before it went anywhere."""
    box = np.zeros((90, 200), np.uint8)
    box[10:80, 10:190] = 255
    g = np.full(box.shape, 250, np.uint8)
    g[20:70, 20:180] = 10                 # a very fat dark word: 63% of the box
    got = _writing_in(g, box)             # no balloon: the flag is not set
    assert (g[got > 0] <= INK).all(), "a fat word was read as a black balloon"
    assert _lit(got) > 1000
    # ...and the flag is the ONLY thing holding it: with a balloon it flips,
    # which is exactly why nothing but a balloon may pass it.
    flipped = _writing_in(g, box, balloon=True)
    assert (g[flipped > 0] >= PAPER).all()


def test_an_empty_area_answers_nothing_rather_than_raising():
    b = np.zeros((40, 40), np.uint8)
    assert _lit(_writing_in(np.full((40, 40), 128, np.uint8), b,
                           balloon=True)) == 0


# ------------------------------------------------- and the cleaner can see

def test_the_ground_is_measurable_again():
    """The consequence, and the reason the picture was a mess. `_flat_from`
    stands off the ink by twelve pixels to sample the ground; round a mask that
    IS the balloon there is nothing left to stand on."""
    from mangatl import inpaint as I
    b = _balloon(w=140, h=210)
    g = _page(b, ground=12, ink=250)
    img = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

    was = ((g <= INK) & (b > 0)).astype(np.uint8)
    now = (_writing_in(g, b, balloon=True) > 0).astype(np.uint8)
    room = lambda ink: int(((b > 0) & (I._dilated(
        ink, I.DILATE_PX + I.HALO_REACH) == 0)).sum())
    assert room(was) == 0, "the old mask left ground to sample after all"
    assert room(now) > 500, ("the new mask still swallows the balloon",
                             room(now))

    ok, col, _spread = I._flat_from(img, b, now, None)
    assert ok, "a solid black balloon still does not read as flat"
    assert col.mean() < 60, col


def test_the_stamp_was_bumped():
    """Every plate made by the old rule has the wrong mask baked into it, and
    a plate is reused for ever. See the note above `inpaint.ALGO`."""
    from mangatl import inpaint as I
    assert I.ALGO >= "2026-08-29-a", I.ALGO


def test_the_line_between_the_two_is_written_down_once():
    assert 0.5 < DARK_GROUND < 0.8, DARK_GROUND
    assert PAPER == 255 - INK
