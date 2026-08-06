"""The gap between lines never closes below the floor.

lee, first: "the line gap shoud nver be less than 1 by default". Later, looking
at his own pages: *"make teh minimun line gap be 1.20"*. The floor moved; the
argument for having one did not.

Set solid — a gap of exactly one type size — the ascenders on one line already
reach up to where the descenders on the line above come down. Anything tighter
and they interleave, and a block that interleaves stops looking like lines of
speech and starts looking like a grey brick. It is the cheapest-looking thing a
typesetter can do, and the fitter was reaching for it whenever a balloon got
awkward, because a tighter gap is always the easiest way to make one more line
fit.

The way out of a balloon that will not take the words is a smaller size, not a
smaller gap. So the floor holds in the two places the FITTER chooses a gap for
itself: the sweep of leadings it tries, and the emergency wrap it falls through
to when nothing in the sweep fits. It does not hold over a number typed into
the panel — that is a person deciding, and lee asked for exactly that once he
had the floor.

The floor itself is `typeset.MIN_LEADING`. The tests below say "at least
solid", which is the older and weaker claim, so that they keep meaning
something whatever the floor is set to; the tests that pin it to 1.20 live in
test_panel_edits_stick.py.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion
from mangatl.typeset import (TypesetConfig, _plain_fit, default_font_path,
                             fit_region, layout_from_override)

H, W = 600, 600
TEXT = ("I'M SORRY, ADA... IT'S MY OWN WEAKNESS THAT DID THIS TO YOU, AND "
        "THERE IS NOTHING I CAN SAY NOW THAT WOULD EVER MAKE IT RIGHT.")


def _cfg(**kw):
    kw.setdefault("font_path", default_font_path())
    kw.setdefault("min_font", 10)
    kw.setdefault("max_font", 34)
    return TypesetConfig(**kw)


def test_no_leading_the_fitter_may_choose_is_under_solid():
    """The sweep itself. Nothing to measure — just read the list."""
    for lead in _cfg().leadings:
        assert lead >= 1.0, (lead, _cfg().leadings)


def _balloon(rx, ry):
    bub = np.zeros((H, W), np.uint8)
    cv2.ellipse(bub, (300, 300), (rx, ry), 0, 0, 360, 255, -1)
    ink = np.zeros((H, W), np.uint8)
    cv2.rectangle(ink, (300 - rx // 2, 300 - ry // 2),
                  (300 + rx // 2, 300 + ry // 2), 255, -1)
    r = TextRegion(id=1, bbox=cv2.boundingRect(ink), text_mask=ink,
                   bubble_mask=bub, bubble_bbox=cv2.boundingRect(bub))
    r.dst_text = TEXT
    return r, bub


@pytest.mark.parametrize("rx,ry", [(220, 150), (150, 210), (90, 240),
                                   (240, 70), (70, 120), (110, 95)])
def test_a_fitted_block_never_closes_its_lines_tighter_than_solid(rx, ry):
    """Balloons of every proportion, including ones far too small for the
    speech — the cramped ones are exactly where the fitter used to reach for a
    tighter gap, so they are the ones worth asking."""
    r, bub = _balloon(rx, ry)
    lay = fit_region(r, _cfg(), bub)
    assert lay.leading >= 1.0, (rx, ry, lay.leading, lay.font_size)
    # And the drawn result agrees with the reported number: origins are line
    # CENTRES, so consecutive gaps are the leading in pixels.
    ys = sorted(y for _, y in lay.line_origins)
    for a, b in zip(ys, ys[1:]):
        assert b - a >= lay.font_size, (rx, ry, b - a, lay.font_size)


def test_the_emergency_wrap_is_held_to_the_same_floor():
    """`_plain_fit` is the fall-through when nothing in the sweep fits, and it
    set its own line height off the ink box — which came out under solid on
    every font this app ships."""
    shape = np.zeros((H, W), np.uint8)
    cv2.rectangle(shape, (250, 250), (330, 400), 255, -1)   # far too narrow
    lay = _plain_fit(TEXT, shape > 0, _cfg())
    assert lay is not None
    ys = sorted(y for _, y in lay.line_origins)
    assert len(ys) >= 2, lay.lines
    for a, b in zip(ys, ys[1:]):
        assert b - a >= lay.font_size, (b - a, lay.font_size)


def test_a_leading_typed_in_by_hand_is_honoured_however_tight():
    """The floor is on what the FITTER chooses, not on what a person asks for.

    lee asked for a minimum of 1.20 and then, having seen it, asked for the
    other half: *"the line spacing shoud only be a minimun of 1.20 for the
    typesetting the user shoud be able to go lowwer"*. Somebody tightening a
    line on purpose is making a decision, and it stands.
    """
    r, bub = _balloon(220, 150)
    lines = ["I'M SORRY, ADA...", "IT WAS MY OWN", "WEAKNESS."]
    for want in (1.55, 0.82):
        r.layout_override = {"locked": True, "leading": want, "font_size": 18,
                             "lines": lines}
        lay = layout_from_override(r, _cfg(), bub)
        assert lay is not None
        assert lay.leading == pytest.approx(want), (want, lay.leading)
    ys = sorted(y for _, y in lay.line_origins)
    assert ys[1] - ys[0] < lay.font_size, (ys, lay.font_size)


# ------------------------------------------- the emergency wrap obeys it too

def _cramped(text, w=120, h=90, min_font=12):
    """A box too small for the text at any comfortable size, which is what
    sends the fitter to `_plain_fit`."""
    import numpy as np
    from mangatl import typeset as T
    mask = np.zeros((h + 40, w + 40), np.uint8)
    mask[20:20 + h, 20:20 + w] = 255
    cfg = T.TypesetConfig(font_path=T.default_font_path(),
                          min_font=min_font, max_font=min_font + 2)
    return T._plain_fit(text, mask, cfg), cfg


def test_the_emergency_wrap_keeps_the_floor():
    """lee, looking at his own page: *"trhe nimimun line gap is not ebeing
    enforced ty the typesetter"*.

    `MIN_LEADING`'s own docstring says it bounds "the sweep of leadings and the
    emergency wrap". The sweep honoured it; the emergency wrap set `leading=1.0`
    and packed the lines at the ink height — the tight grey mass the floor is
    there to prevent. It is the LAST-RESORT path, so it is exactly the one that
    runs on the worst-fitting bubbles, which is where it shows.
    """
    from mangatl import typeset as T
    lay, cfg = _cramped("WOULD THE QUEEN OF ZARUDONE TELL YOU TO PEEK")
    assert lay is not None, "pick a box the plain wrap can actually fill"
    assert len(lay.lines) > 1, lay.lines
    assert lay.leading >= T.MIN_LEADING - 0.001, lay.leading


def test_the_lines_it_places_are_really_that_far_apart():
    """The reported number and the geometry have to be the same thing — the
    gap is what you see, the number is only what the panel says."""
    from mangatl import typeset as T
    lay, cfg = _cramped("WOULD THE QUEEN OF ZARUDONE TELL YOU TO PEEK")
    ys = [y for _, y in lay.line_origins]
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert gaps, lay.line_origins
    assert min(gaps) >= lay.font_size * T.MIN_LEADING - 1, (gaps, lay.font_size)


def test_it_shrinks_rather_than_tightening():
    """The way out of a box this cramped is a smaller size, not a smaller gap —
    which is what the size sweep is for."""
    from mangatl import typeset as T
    roomy, _ = _cramped("SHORT LINE", w=300, h=220)
    tight, _ = _cramped("SHORT LINE", w=120, h=70)
    if tight is not None:
        assert tight.font_size <= roomy.font_size
        assert tight.leading >= T.MIN_LEADING - 0.001, tight.leading


def test_a_person_may_still_go_tighter_by_hand():
    """The floor bounds the FITTER. A number typed into the panel is a person
    deciding, and it stands however tight."""
    from mangatl import typeset as T
    from mangatl.models import TextRegion
    import numpy as np
    r = TextRegion(id=1, bbox=(20, 20, 200, 150), kind="bubble")
    r.dst_text = "TWO LINES HERE"
    m = np.zeros((220, 260), np.uint8)
    m[20:170, 20:220] = 255
    r.bubble_mask = m
    r.text_mask = m
    r.layout_override = {"lines": ["TWO", "LINES"], "font_size": 20,
                         "leading": 0.9}
    cfg = T.TypesetConfig(font_path=T.default_font_path(),
                          min_font=12, max_font=34)
    lay = T.layout_from_override(r, cfg)
    assert abs(lay.leading - 0.9) < 0.001, lay.leading
