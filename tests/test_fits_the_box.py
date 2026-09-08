"""Outside text and sound effects stay in their box, or a little past it.

lee: *"outide text and sfx should try to fit inside the box or slightly
bigger"*, looking at page 10 typeset at 26pt where the Japanese it replaced
was printed at about half that.

Both had the same fault from opposite ends.

**Outside text** was given every scrap of blank paper it could reach before
running into artwork. That kept the English off the drawing, which was the bug
before it, but a caption on an empty panel could reach nearly twice its own box
in both directions and the typesetting grew to fill it. The paper it gets is now
a MARGIN round the writing - a quarter of the box on each side - rather than
everything going spare.

**A sound effect** is laid out along the axis the Japanese ran on, and Japanese
effects run down the page. The English runs across, so a tall narrow box got a
wide short line: CRASH!! in a 120x260 box came out 237 wide and hung 59px out
of each side, straight over the artwork. It is now shrunk until it fits, by the
same margin.

The clamp only makes letters SMALLER. It never moves an effect and never
straightens one - `enforce_bounds` would do both, which is why sound effects
have always been kept out of it.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect.balloon import GROW_MARGIN, give_room
from mangatl.models import TextRegion
from mangatl import typeset as T


def _blank(h=600, w=800):
    g = np.zeros((h, w), np.uint8)
    g[40:h - 40, 40:w - 40] = 255
    return g


def _column(g, x, y, w, h):
    m = np.zeros(g.shape, np.uint8)
    for k in range(y, y + h - 8, 22):
        cv2.rectangle(g, (x, k), (x + w, k + 14), 20, -1)
        cv2.rectangle(m, (x, k), (x + w, k + 14), 255, -1)
    return m


def _sfx(text, w, h, angle=0.0):
    # TWO Japanese characters, and the count is now load-bearing: a sound
    # effect whose source is ONE character is set flat, because an axis
    # through a single glyph is the long way through that glyph's own shape
    # and not a direction of writing. lee: *"if the jappennese sfx chareter is
    # just one charater in the box it shoud just be flat with no angle"*. The
    # placeholder here used to be "x", which quietly made every effect in this
    # file a single-character one.
    r = TextRegion(id=1, bbox=(300, 300, w, h), kind="sfx", order=1,
                   src_text="ドン", dst_text=text, angle=angle,
                   sfx_vertical=h > w, sfx_len=0.9, sfx_wid=0.6,
                   text_mask=np.zeros((900, 900), np.uint8))
    r.text_mask[300:300 + h, 300:300 + w] = 255
    return r


def _drawn(lay, cfg):
    """The rectangle the typesetting actually covers."""
    path = lay.font_path or cfg.font_path or T.default_font_path()
    f = T._font(path, lay.font_size)
    asc, desc = f.getmetrics()
    xs, ys = [], []
    for (cx, cy), line in zip(lay.line_origins, lay.lines):
        half = f.getlength(line) / 2
        xs += [cx - half, cx + half]
        ys += [cy - (asc + desc) / 2, cy + (asc + desc) / 2]
    return min(xs), min(ys), max(xs), max(ys)


def _overflow(r, lay, cfg):
    x, y, w, h = r.bbox
    x0, y0, x1, y1 = _drawn(lay, cfg)
    return max(x - x0, y - y0, x1 - (x + w), y1 - (y + h))


# ------------------------------------------------------- outside text

def test_the_room_is_a_margin_not_everything_going_spare():
    g = _blank()
    m = _column(g, 600, 120, 40, 300)
    r = TextRegion(id=1, bbox=(600, 120, 41, 292), text_mask=m,
                   kind="freefloat", order=1, src_text="x", dst_text="X")
    assert give_room(g, [r]) == 1
    ys, xs = np.nonzero(r.bubble_mask > 0)
    x, y, w, h = r.bbox
    assert xs.max() - xs.min() + 1 <= w * (1 + 2 * GROW_MARGIN) + 2
    assert ys.max() - ys.min() + 1 <= h * (1 + 2 * GROW_MARGIN) + 2


def test_the_margin_is_slight():
    """'Slightly bigger', not 'as big as the panel allows'."""
    assert 0 < GROW_MARGIN <= 0.35


def test_artwork_still_wins_over_the_margin():
    """The margin is a ceiling, not an entitlement: a drawing right beside the
    writing still stops the room short of it."""
    g = _blank()
    m = _column(g, 600, 150, 40, 260)
    r = TextRegion(id=1, bbox=(600, 150, 41, 252), text_mask=m,
                   kind="freefloat", order=1, src_text="x", dst_text="X")
    cv2.rectangle(g, (560, 60), (594, 540), 30, -1)      # a wall on the left
    give_room(g, [r])
    ys, xs = np.nonzero(r.bubble_mask > 0)
    assert xs.min() > 594, "the room ran into the drawing"


# ------------------------------------------------------- sound effects

def test_a_tall_effect_is_shrunk_to_fit_across():
    """The case lee will have seen: Japanese running down the page, English
    running across it."""
    cfg = T.TypesetConfig()
    r = _sfx("CRASH!!", 120, 260)
    loose = T.fit_sfx_region(r, "CRASH!!", cfg)
    before = _overflow(r, loose, cfg)
    after = _overflow(r, T.fit_region(r, cfg), cfg)
    assert before > 0.25 * 120, "fixture is wrong: it already fitted"
    assert after < before
    assert after <= T.SFX_MARGIN * max(r.bbox[2], r.bbox[3]) + 1


def test_an_effect_that_already_fits_is_left_alone():
    cfg = T.TypesetConfig()
    for text, w, h in (("BOOM", 160, 90), ("KA", 60, 60),
                       ("WHOOOOSH", 200, 80)):
        r = _sfx(text, w, h)
        loose = T.fit_sfx_region(r, text, cfg)
        assert T.fit_region(r, cfg).font_size == loose.font_size, text


def test_the_clamp_only_ever_shrinks():
    cfg = T.TypesetConfig()
    for text, w, h in (("CRASH!!", 120, 260), ("THUD", 90, 300),
                       ("BOOM", 160, 90), ("RUMBLERUMBLE", 150, 150)):
        r = _sfx(text, w, h)
        loose = T.fit_sfx_region(r, text, cfg)
        assert T.fit_region(r, cfg).font_size <= loose.font_size, text


def test_a_leaning_effect_keeps_its_lean():
    """`enforce_bounds` would straighten it. This must not."""
    cfg = T.TypesetConfig()
    r = _sfx("WHOOOOOOSH", 120, 300, angle=20.0)
    loose = T.fit_sfx_region(r, "WHOOOOOOSH", cfg)
    tight = T.fit_region(r, cfg)
    assert round(float(tight.rotate), 3) == round(float(loose.rotate), 3)
    assert abs(float(tight.rotate)) > 0


def test_a_lean_is_measured_as_a_lean():
    """A leaning line covers the box of its ROTATED rectangle, which is bigger
    than the line itself. Measuring it flat under-shrinks the effect and leaves
    a corner of it out over the artwork."""
    import math
    cfg = T.TypesetConfig()
    r = _sfx("KABOOOOM", 150, 150, angle=45.0)
    lay = T.fit_region(r, cfg)
    path = lay.font_path or cfg.font_path or T.default_font_path()
    f = T._font(path, lay.font_size)
    asc, desc = f.getmetrics()
    tw = max(f.getlength(l) for l in lay.lines)
    th = (asc + desc) * len(lay.lines) * float(lay.leading or 1.0)
    a = math.radians(float(lay.rotate))
    ext = tw * abs(math.cos(a)) + th * abs(math.sin(a))
    assert ext <= 150 * (1 + 2 * T.SFX_MARGIN) + 2, \
        f"the leaning effect covers {ext:.0f}px of a 150px box"


def test_the_clamp_moves_nothing():
    """It changes the SIZE and nothing else. An effect is placed where the
    Japanese ink was; sliding it towards the middle of the rectangle drawn
    round it would take it off the thing it belongs to."""
    cfg = T.TypesetConfig()
    r = _sfx("CRASH!!", 120, 260)
    loose = T.fit_sfx_region(r, "CRASH!!", cfg)
    tight = T.fit_region(r, cfg)
    assert tight.font_size < loose.font_size, "fixture: the clamp did not fire"
    assert list(tight.line_origins) == list(loose.line_origins)


def test_the_words_all_survive_the_shrink():
    cfg = T.TypesetConfig()
    r = _sfx("CRASH!!", 120, 260)
    assert " ".join(T.fit_region(r, cfg).lines).replace(" ", "") == "CRASH!!"


def test_it_never_shrinks_below_the_floor():
    cfg = T.TypesetConfig()
    r = _sfx("AAAAAAAAAAAAAAAAAAAAAAAAAAAA", 40, 400)
    lay = T.fit_region(r, cfg)
    assert lay.font_size >= cfg.absolute_floor


def test_dialogue_is_not_touched_by_the_effect_clamp():
    """A speech region answers to its balloon, not to its box."""
    cfg = T.TypesetConfig()
    g = np.full((600, 800), 255, np.uint8)
    cv2.ellipse(g, (400, 300), (170, 120), 0, 0, 360, 20, 3)
    mask = np.zeros((600, 800), np.uint8)
    cv2.ellipse(mask, (400, 300), (165, 115), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, bbox=(380, 250, 40, 100), text_mask=mask.copy(),
                   bubble_mask=mask, kind="bubble", order=1,
                   src_text="x", dst_text="THIS IS A WHOLE LINE OF SPEECH")
    lay = T.fit_region(r, cfg)
    x0, y0, x1, y1 = _drawn(lay, cfg)
    assert x1 - x0 > 40, "speech was squeezed into its Japanese column"


def test_a_line_turned_on_its_side_is_measured_on_its_side():
    """A wide box with the effect running DOWN it: flat, the line is 60px tall
    and fits easily; turned upright it is 250px long and hangs out of both ends.
    Measuring it flat leaves it hanging."""
    from mangatl.models import TextLayout
    cfg = T.TypesetConfig()
    r = _sfx("KRRRRAKOOOM", 300, 80)
    path = cfg.font_path or T.default_font_path()
    lay = TextLayout(lines=["KRRRRAKOOOM"], font_size=40, leading=1.0,
                     line_origins=[(450, 340)], font_path=path, rotate=90.0)
    flat_w = T._text_w(path, 40, "KRRRRAKOOOM")
    assert flat_w > 80 * (1 + 2 * T.SFX_MARGIN), "fixture: it fits upright"
    out = T.clamp_to_box(r, lay, cfg)
    assert out.font_size < 40, "an upright line was measured lying down"
    # It goes down as far as the floor and no further, and says so when it
    # stops there.
    #
    # This used to assert plain containment, which worked while `SFX_MARGIN`
    # was 0.25 and "the box" was really the box plus a quarter of it. With
    # lee's *"make it fie exacly the size of the box"* the margin is nothing,
    # eleven letters do not cross 80px at any readable size, and the right
    # answer is the one the code gives: stop at `min_font` and set `spills`.
    # Asserting containment here now would be asserting that the escape hatch
    # does not work.
    room = 80 * (1 + 2 * T.SFX_MARGIN) + 2
    if T._text_w(path, out.font_size, "KRRRRAKOOOM") > room:
        assert out.font_size == cfg.min_font, out.font_size
        assert out.spills, "stopped by the floor and not saying so"
    else:
        assert not out.spills, "inside its box and claiming otherwise"


def test_every_line_counts_towards_the_height():
    """An effect broken over two lines is twice as tall. Measuring one line
    lets the second one hang out of the box."""
    from mangatl.models import TextLayout
    cfg = T.TypesetConfig()
    r = _sfx("KA BOOM", 400, 70)
    path = cfg.font_path or T.default_font_path()
    one = TextLayout(lines=["KA"], font_size=60, leading=1.0,
                     line_origins=[(500, 345)], font_path=path)
    two = TextLayout(lines=["KA", "BOOM"], font_size=60, leading=1.0,
                     line_origins=[(500, 315), (500, 375)], font_path=path)
    kept = T.clamp_to_box(r, one, cfg).font_size
    shrunk = T.clamp_to_box(r, two, cfg).font_size
    assert shrunk < kept, "the second line was not counted"
