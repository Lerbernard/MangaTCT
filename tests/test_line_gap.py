"""The gap between lines never closes below the floor.

lee, first: "the line gap shoud nver be less than 1 by default". Then, looking
at his own pages: *"make teh minimun line gap be 1.20"*. Then, looking at his
pages beside the published English chapter: *"the real line gap number is
somewhere between 1 - 1.10 and 1.20 tyhe max youu shoud use is 1.20"* - so
1.20 became the CEILING and the floor went back to where he first put it.

The floor moved twice; the argument for having one did not.

Set solid - a gap of exactly one type size - the ascenders on one line already
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
the panel - that is a person deciding, and lee asked for exactly that once he
had the floor.

The floor itself is `typeset.MIN_LEADING`. The tests below say "at least
solid", which is the older and weaker claim, so that they keep meaning
something whatever the floor is set to; the tests that pin it to 1.20 live in
test_panel_edits_stick.py.
"""
import numpy as np
import pytest
from where import PKG

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
    """The sweep itself. Nothing to measure - just read the list."""
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
    speech - the cramped ones are exactly where the fitter used to reach for a
    tighter gap, so they are the ones worth asking."""
    r, bub = _balloon(rx, ry)
    lay = fit_region(r, _cfg(), bub)
    assert lay.leading >= 1.0, (rx, ry, lay.leading, lay.font_size)
    # And the drawn result agrees with the reported number: origins are line
    # CENTRES, so consecutive gaps are the leading in pixels.
    #
    # A PIXEL OF SLACK, and only since the floor came down to exactly solid.
    # Origins are integers: at leading 1.00 on a 21px size the nominal pitch
    # is 21.0 and the rounded origins alternate 22, 20, 22, 20 - an average of
    # exactly 21 and a rounding artefact, not the fitter choosing anything.
    # At the old floor of 1.20 the same rounding never reached down this far,
    # which is the only reason this used to be exact.
    ys = sorted(y for _, y in lay.line_origins)
    for a, b in zip(ys, ys[1:]):
        assert b - a >= lay.font_size - 1, (rx, ry, b - a, lay.font_size)
    if len(ys) > 1:
        span = (ys[-1] - ys[0]) / float(len(ys) - 1)
        assert span >= lay.font_size - 0.01, (rx, ry, span, lay.font_size)


def test_the_emergency_wrap_is_held_to_the_same_floor():
    """`_plain_fit` is the fall-through when nothing in the sweep fits, and it
    set its own line height off the ink box - which came out under solid on
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
    and packed the lines at the ink height - the tight grey mass the floor is
    there to prevent. It is the LAST-RESORT path, so it is exactly the one that
    runs on the worst-fitting bubbles, which is where it shows.
    """
    from mangatl import typeset as T
    lay, cfg = _cramped("WOULD THE QUEEN OF ZARUDONE TELL YOU TO PEEK")
    assert lay is not None, "pick a box the plain wrap can actually fill"
    assert len(lay.lines) > 1, lay.lines
    assert lay.leading >= T.MIN_LEADING - 0.001, lay.leading


def test_the_lines_it_places_are_really_that_far_apart():
    """The reported number and the geometry have to be the same thing - the
    gap is what you see, the number is only what the panel says."""
    from mangatl import typeset as T
    lay, cfg = _cramped("WOULD THE QUEEN OF ZARUDONE TELL YOU TO PEEK")
    ys = [y for _, y in lay.line_origins]
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert gaps, lay.line_origins
    assert min(gaps) >= lay.font_size * T.MIN_LEADING - 1, (gaps, lay.font_size)


def test_it_shrinks_rather_than_tightening():
    """The way out of a box this cramped is a smaller size, not a smaller gap -
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


# ---------------------------------------------- the same gap on every face

def test_the_same_number_is_a_different_gap_in_every_face():
    """The premise, stated as the thing that is wrong with an em multiple.

    A leading is a multiple of the TYPE SIZE, and faces put different amounts
    of their em into the letters. Measured raw over the sixteen that ship, the
    tall letters run from 0.63 of the em (Gaegu) to 0.87 (Anton) - so the same
    1.20 is airy on one and cramped on the other, by 38%.

    lee: *"also make sure your mesurement is good fro all fonts"*.

    ## And what `px_for` left of it

    Most of that spread was never about ascenders at all: it was the em itself
    meaning a different size on every face, which is now divided out before a
    face is ever opened (`typeset.px_for`, and
    `test_a_point_is_not_a_size.py`). Measured through `_font` the range
    narrows to 0.68-0.85 - Nanum Pen Script and Gochi Hand, whose ascenders
    really are long for their capitals.

    So the conversion below is a RESIDUAL now rather than the whole
    correction, and a smaller residual is not no residual: a 25% difference in
    the white between lines is one anybody can see. Both numbers are asserted,
    because the day the second one closes is the day this whole function can
    go.
    """
    import glob
    from PIL import ImageFont
    from mangatl.typeset import _font
    raw, norm = {}, {}
    for path in sorted(glob.glob(str(PKG / "fonts" / "*.ttf"))):
        box = ImageFont.truetype(path, 100).getbbox("bdhklHT")
        raw[path] = (box[3] - box[1]) / 100.0
        box = _font(path, 100).getbbox("bdhklHT")
        norm[path] = (box[3] - box[1]) / 100.0
    assert len(raw) >= 8, raw
    assert max(raw.values()) / min(raw.values()) > 1.3, \
        ("the faces no longer differ enough for this to matter", raw)
    # ...and after the size conversion there is still a gap worth converting.
    assert max(norm.values()) / min(norm.values()) > 1.15, \
        ("the residual is gone - `leading_for` can go too", norm)


def test_a_gap_is_converted_for_the_face_it_is_set_in():
    """So the number is read on the default face and converted. What stays the
    same across faces is the gap you can SEE - the pitch as a multiple of the
    height of the tall letters - not the number in the font file.

    Measured through `_font`, which is how `leading_for` measures it and how
    the letters are actually drawn. Reading the raw file here instead was this
    test asking its question in one unit and answering it in another, and it
    is what went red the day `px_for` landed.
    """
    import glob
    from mangatl.typeset import (leading_for, LEADING_REF, MIN_LEADING,
                                 MAX_LEADING, _font)
    seen = []
    for path in sorted(glob.glob(str(PKG / "fonts" / "*.ttf"))):
        em = leading_for(path, 1.10)
        assert MIN_LEADING <= em <= MAX_LEADING, (path, em)
        box = _font(path, 100).getbbox("bdhklHT")
        asc = (box[3] - box[1]) / 100.0
        # The gap you SEE is the pitch less the letters.
        seen.append((path, round(em - asc, 3), em))
    free = [v for _p, v, em in seen if MIN_LEADING < em < MAX_LEADING]
    assert len(free) >= 8, seen
    assert max(free) - min(free) <= 0.011, \
        ("the same number is still a different gap on different faces", seen)
    assert LEADING_REF > 0


def test_the_ceiling_binds_on_a_face_with_very_long_ascenders():
    """A hard maximum means some face always sits on it, and its lines really
    are a little tighter than everything else's. That is the honest consequence
    of a ceiling, and the alternative - letting one face past it - is worse.

    **Which face changed.** It used to be Anton, which puts 0.87 of its em into
    its letters against the reference face's 0.68 - but almost all of that was
    the em, not the ascender, and `px_for` divides the em out before the face
    is opened. Anton is drawn at 0.70 now and asks for 1.12, comfortably inside
    the band.

    The ceiling still binds, on the faces where the difference is REAL: Nanum
    Pen Script and Gochi Hand are handwriting, with ascenders long out of all
    proportion to their capitals (0.85 and 0.84 against the reference 0.68), so
    matching the reference white wants more than lee's 1.20 allows.
    """
    from mangatl.typeset import leading_for, MAX_LEADING
    tall = str(PKG / "fonts" / "NanumPenScript-Regular.ttf")
    if not __import__("os").path.exists(tall):
        pytest.skip("Nanum Pen Script is not bundled here")
    # Every number in the band comes back at the ceiling: matching the
    # reference white would want more than the ceiling allows at all of them.
    assert leading_for(tall, 1.20) == MAX_LEADING
    assert leading_for(tall, 1.06) == MAX_LEADING


def test_the_size_conversion_took_the_easy_half_of_the_leading_problem():
    """Anton is the whole argument for `px_for` in one face.

    Raw, its tall letters are 0.87 of the em - so far past the reference that
    matching the white wanted 1.32 and got clamped to the ceiling on every
    number in the band. That was never a fact about Anton's ascenders; it was
    the em meaning something different. Drawn through `_font` it measures 0.70,
    two hundredths off the reference, and it asks for a leading like anything
    else's.
    """
    from mangatl.typeset import leading_for, MAX_LEADING
    anton = str(PKG / "fonts" / "Anton-Regular.ttf")
    if not __import__("os").path.exists(anton):
        pytest.skip("Anton is not bundled here")
    assert leading_for(anton, 1.10) < MAX_LEADING, leading_for(anton, 1.10)


def test_a_face_that_is_not_there_is_converted_for_the_one_that_is():
    """A path that does not exist is not an error here: `_font` falls back to
    the default face, and the default face is what will actually be drawn - so
    the gap is converted for THAT, which is the honest answer rather than the
    number as typed."""
    from mangatl.typeset import leading_for, default_font_path
    assert leading_for("/no/such/font.ttf", 1.13) == \
        leading_for(default_font_path(), 1.13)


def test_a_face_that_cannot_be_measured_at_all_leaves_the_number_alone():
    """And if even that fails, the number as given. A measurement that cannot
    be made is not a reason to fail a page."""
    import mangatl.typeset as T
    was = T._font
    T._font = lambda *a, **k: (_ for _ in ()).throw(OSError("no fonts here"))
    try:
        assert T.leading_for("/no/such/font.ttf", 1.13) == 1.13
    finally:
        T._font = was
