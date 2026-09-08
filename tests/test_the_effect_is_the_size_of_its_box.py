"""A sound effect is the size of its box now, not the size of the ink it replaces.

lee: *"for sfx make it so that teh sfx is teh size of teh box, like make it fie
exacly the size of the box, it shou only ever outside teh box if tehsfx would
break teh minimun size for teh text"* - with two crops, one he called perfect
(BEAM filling its box) and one bad (an effect several times the height of the
panel it was on).

## What it was

Two things stood between an effect and its box, and both were deliberate.

`fit_sfx_region` built the target from `sfx_len` and `sfx_wid`, the footprint of
the JAPANESE ink measured at detection - not the box drawn round it. Over lee's
23 pages those average **0.82 and 0.66**, so an effect fitted to the ink filled
about five sixths of the space it was given along its axis, and two thirds
across.

`SFX_MARGIN` was **0.25**: a quarter of each side past the box, per side. That
was lee's own earlier instruction - *"outide text and sfx should try to fit
inside the box or slightly bigger"* - and "slightly bigger" is now nothing.

Measured over the chapter, the block against its box along the long side:

    0.84 -> 1.00      (median 0.84 -> 1.00, min 0.46 -> 0.95)

## And the second half of his sentence

*"it shou only ever outside teh box if tehsfx would break teh minimun size"* -
that escape hatch was already there and is untouched: `clamp_to_box` never
shrinks past `cfg.min_font`, and when the floor stops it the layout says
`spills`. An effect is drawn ON the artwork, so its box is a note of where the
Japanese ink was rather than a wall.

## The frame that lied

Found while measuring this and fixed with it. `clamp_to_box` shrank the letters
and moved the origins but **left `frame` at its pre-shrink size**. A frame is
not decoration: the editor draws the selection from it, a drag moves it,
`frameOf` hands it to the browser to place lines from, and a save writes it
into `layout_override`. `Um...` on lee's page 5 measured 41x20 on the paper and
carried a frame claiming 94x40.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import typeset as T
from mangatl.models import TextRegion


def _sfx(text, w, h, at=(300, 300), **kw):
    x, y = at
    m = np.zeros((y + h + 300, x + w + 300), np.uint8)
    m[y:y + h, x:x + w] = 255
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="sfx", text_mask=m,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    r.order, r.dst_text = 1, text
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _cfg():
    return T.TypesetConfig(font_path=T.default_font_path(), min_font=11,
                           max_font=40)


def _extent(lay, cfg):
    """The block's own axis-aligned extent at the size it ended up.

    On the INK, which is how both `fit_sfx_region` and `clamp_to_box` measure
    it. This used to use the font's ascent-plus-descent, and the two answers
    differed by a few pixels on a word of capitals - room for a descender that
    is not there - which is exactly the disagreement that made the clamp shave
    points off effects the fitter had just called a fit. Measuring the test the
    other way from the code is how that stayed hidden.
    """
    import math
    path = lay.font_path or cfg.font_path
    heights, widths = [], []
    for line in lay.lines:
        top, bot = T.ink_extents(path, lay.font_size, T._has_descenders(line))
        heights.append(bot - top)
        widths.append(T._text_w(path, lay.font_size, line))
    gap = max(0.0, (float(lay.leading or 1.0) - 1.0) * lay.font_size)
    th = sum(heights) + gap * max(0, len(lay.lines) - 1)
    tw = max(widths)
    a = math.radians(float(lay.rotate or 0.0))
    ca, sa = abs(math.cos(a)), abs(math.sin(a))
    return tw * ca + th * sa, tw * sa + th * ca


# ------------------------------------------------------------ the size of it

def test_an_effect_fills_the_width_of_its_box():
    """BEAM in a square box - the crop lee called perfect."""
    cfg = _cfg()
    r = _sfx("BEAM", 160, 160)
    lay = T.fit_region(r, cfg)
    w, _h = _extent(lay, cfg)
    assert w >= 0.95 * 160, (w, lay.font_size)
    assert w <= 160 + 1, (w, lay.font_size)


def test_the_japanese_footprint_no_longer_holds_it_back():
    """The same box, with the ink measured at two thirds of it. That used to
    set the target; now only the angle is taken from the measurement."""
    cfg = _cfg()
    loose = T.fit_region(_sfx("BEAM", 160, 160), cfg)
    small = T.fit_region(_sfx("BEAM", 160, 160, sfx_len=0.66, sfx_wid=0.66,
                              sfx_vertical=False, angle=0.0), cfg)
    assert small.font_size == loose.font_size, (small.font_size,
                                                loose.font_size)


def test_the_switch_is_on_and_the_margin_is_nothing():
    assert T.SFX_FILLS_BOX is True
    assert T.SFX_MARGIN == 0.0


# --------------------------------------------------- ...and inside it, mostly

def test_it_stays_inside_the_box_it_was_given():
    cfg = _cfg()
    for text, w, h in (("BEAM", 160, 160), ("BOOM", 160, 90),
                       ("KA", 60, 60), ("Um...", 41, 94)):
        lay = T.fit_region(_sfx(text, w, h), cfg)
        ew, eh = _extent(lay, cfg)
        assert ew <= w + 2 and eh <= h + 2, (text, ew, eh, w, h,
                                             lay.font_size)


def test_a_tall_japanese_column_shrinks_the_english_to_its_width():
    """The case from lee's page 5: `Um...` in a 41x94 column. English runs
    across, so the binding side is the 41 - and the answer is a smaller word
    inside the box, not a wide one hanging out of it."""
    cfg = _cfg()
    lay = T.fit_region(_sfx("Um...", 41, 94), cfg)
    ew, _eh = _extent(lay, cfg)
    assert ew <= 41 + 2, (ew, lay.font_size)
    assert lay.font_size >= cfg.min_font


def test_but_never_smaller_than_the_minimum():
    """*"it shou only ever outside teh box if tehsfx would break teh minimun
    size for teh text"*. A long word in a small box runs past it and says so,
    because too small to read is worse than past its box."""
    cfg = _cfg()
    lay = T.fit_region(_sfx("KRRRRAKOOOM", 40, 40), cfg)
    assert lay.font_size == cfg.min_font, lay.font_size
    ew, _eh = _extent(lay, cfg)
    assert ew > 40, "the fixture fits after all"
    assert lay.spills, "past its box and not saying so"


# ------------------------------------------------------------- and the frame

# Both dimensions to the pixel now. There used to be a tenth of slack on the
# height with a comment explaining that the frame was built from the ink and
# containment measured from the font metrics, that both were right for their
# own purpose, and that the next person should not tighten it. That comment was
# wrong: the disagreement was not supposed to be there, it was the bug that
# made the clamp shave points off effects the fitter had passed, and the fix
# was to measure both on the ink. A tolerance wide enough to hide a defect is a
# tolerance that hides the defect.
def _close(frame, ew, eh):
    assert abs(frame[2] - ew) <= 3, (frame, ew)
    assert abs(frame[3] - eh) <= 3, (frame, eh)


def test_the_frame_says_how_big_the_letters_actually_are():
    """`clamp_to_box` shrank the words and left the frame describing the block
    from before it. Everything that draws a selection, moves a block or saves
    one reads that frame."""
    cfg = _cfg()
    r = _sfx("Um...", 41, 94)
    lay = T.fit_region(r, cfg)
    assert lay.frame is not None
    _close(lay.frame, *_extent(lay, cfg))


def test_and_the_frame_is_still_right_when_nothing_was_clamped():
    """The other branch: an effect that already fitted is returned untouched,
    and its frame has to be right too - or the fix would only have moved the
    lie from one path to the other."""
    cfg = _cfg()
    lay = T.fit_region(_sfx("KA", 200, 120), cfg)
    _close(lay.frame, *_extent(lay, cfg))


def test_and_the_frame_is_not_simply_the_box():
    """The cheapest way to pass both of the tests above would be to set the
    frame to the region's own box and have done. It is not that: a block is as
    tall as its letters, and the box it sits in is a Japanese column."""
    cfg = _cfg()
    lay = T.fit_region(_sfx("Um...", 41, 94), cfg)
    assert lay.frame[3] < 94 * 0.6, lay.frame
