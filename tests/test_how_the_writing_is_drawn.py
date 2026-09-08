"""Writing drawn as an outline, and a sound effect that is one character.

Two findings off one page. lee, with page 006 open and STRETCH beside のびー:
*"for the stratch sfx it not even close"*.

He is right, and the measurements say exactly how far off:

    のびー   3 characters, hollow, rim 2px, letters 218 tall in a 418x218 box
    STRETCH  7 letters, solid, outline 14px, letters 87 tall

Three separate wrongnesses. The OUTLINE is fixed here; the size and the face
are deliberately not, and the last section says why.

## What is measured

`inkstyle._outline` reports two facts off the original page - that the
writing is a hollow letterform rather than a filled one, and how thick its rim
is as a fraction of the writing's height, so the number still means something
at whatever size the English is set.

Measured, not asked, and that was lee's call when I put the two ways to him.
It is the same call he made about colour, for the reason written at the top of
`inkstyle.py`: a model normalises what it is unsure of and cannot tell you how
sure it was.

## What is drawn with it

The letters are drawn as a LINE with nothing inside them, at the width the
original's line had. Three things had to be true together and the first two
attempts each had one of them wrong:

* **The fill is nothing.** Filling a hollow letterform with paper makes an
  opaque white shape of something the artwork shows through: STRETCH in solid
  white blanked the panel it was drawn on.
* **The line is the INK colour**, not `edge`. `edge` is a halo - the colour
  picked to hold letters off what is behind them, which on light artwork is
  white - and a transparent middle inside a white rim is nothing on the page
  at all. That was the first go, and it looked like a watermark.
* **The width is in PIXELS.** It was a fraction of the writing's height, which
  gave STRETCH a 1px rim beside のびー's 2, because our letters are less than
  half the height of his: proportionally identical, visibly half as thick on
  the same sheet of paper. lee: *"i like b a lot but if you could get it to
  match the ouline and bordee size it would be perfect"*. A pen has a width.
  The artist drew the big effect and the small one with the same nib.

## What is NOT done with it

The SIZE is left alone. Growing an effect to the height the Japanese had came
out enormous - lee, on the render: *"no do not spill that looks way too big"*
- so the fitter still fits the box, and *"dont worrry about the curve on the
tecxt"* settles the last one: no hand-drawn face is chased.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inkstyle
from mangatl.models import TextRegion


def _hollow_page(rim=2, size=160):
    """A ring: a hollow letterform in the plainest form there is."""
    img = np.full((size + 80, size + 80, 3), 250, np.uint8)
    c = (size // 2 + 40, size // 2 + 40)
    cv2.circle(img, c, size // 2, (5, 5, 5), rim)
    return img


def _solid_page(size=160):
    """The same shape filled in."""
    img = np.full((size + 80, size + 80, 3), 250, np.uint8)
    cv2.circle(img, (size // 2 + 40, size // 2 + 40), size // 2, (5, 5, 5), -1)
    return img


def _block(img):
    b = np.zeros(img.shape[:2], np.uint8)
    b[20:-20, 20:-20] = 255
    return b


def test_a_hollow_letterform_is_found():
    got = inkstyle.measure_region(_hollow_page(), _block(_hollow_page()))
    assert got.get("hollow") is True, got


def test_a_filled_one_is_not():
    """The discrimination that matters. Ordinary writing is filled, and a rim
    width measured on it is the width of a BRUSH STROKE - a fact about the
    face, not about an outline. Reporting it as one would put a hairline halo
    round every line of dialogue in the chapter and call it a measurement."""
    img = _solid_page()
    got = inkstyle.measure_region(img, _block(img))
    assert not got.get("hollow"), got
    assert "weight" not in got


def test_the_rim_is_measured_in_pixels():
    """IN PIXELS, and this is the one that took two goes.

    It was a fraction of the writing's height, on the reasoning that the
    English is set at a different size. That gave STRETCH a 1px rim beside
    のびー's 2 - proportionally identical, and visibly half as thick on the
    same sheet of paper. A pen has a width: the artist drew the big effect and
    the small one with the same nib, and the line it leaves does not scale
    with how large the letters are.
    """
    img = _hollow_page(rim=2, size=160)
    got = inkstyle.measure_region(img, _block(img))
    assert got.get("hollow") is True
    assert got["rim"] == 2, got

    # ...and the SAME rim on letters twice the size is STILL 2. This is the
    # property the whole change is about: the pen did not get bigger.
    big = _hollow_page(rim=2, size=320)
    assert inkstyle.measure_region(big, _block(big))["rim"] == 2

    # A thicker line reads thicker. Not a number: the estimator deliberately
    # under-reads a wide band (see `_outline`) because it is measuring a
    # rectangle of page that holds artwork as well as writing, and the median
    # is what survives that. Under-reading is the safe direction - too thin is
    # a line, too thick is the blob this exists to stop being.
    thick = _hollow_page(rim=10, size=160)
    fat = inkstyle.measure_region(thick, _block(thick))
    assert fat.get("hollow") is True
    assert fat["rim"] > got["rim"] * 2, (got, fat)


def test_it_reports_no_colours_at_all():
    """The half that was learned the hard way. `_outline` used to write `fg`
    and `edge` as well - the paper as a fill and the ink as an outline - and
    a hollow letter filled with paper is an opaque white shape where the
    artwork used to show through. On page 006 that blanked the panel.

    Two facts, no colours. Whatever finally acts on this decides what to draw;
    the measurement only says what is there.
    """
    img = _hollow_page()
    got = inkstyle.measure_region(img, _block(img))
    assert got.get("hollow") is True
    # `fg` is the ordinary colour measurement and is still made. What must not
    # be here is a colour DERIVED from the hollow finding - deciding what to
    # DRAW is `render._hollow_colours`, where the page can be looked at.
    assert "edge" not in got, got


def _region(**ov):
    r = TextRegion(id=1, bbox=(10, 10, 90, 40), kind="sfx")
    r.layout_override = dict(ov)
    return r


def test_a_hollow_block_is_drawn_with_no_fill_and_an_inked_line():
    """Both swaps at once, because either alone is invisible: a transparent
    middle inside a WHITE rim is nothing on the page, and an inked rim round a
    WHITE middle is the solid word it was before."""
    from mangatl.render import _hollow_colours
    ink, halo = (0, 0, 0, 255), (255, 255, 255, 255)
    fg, edge = _hollow_colours(_region(hollow=True, rim=2), ink, halo)
    assert fg[3] == 0, ("the letters still have a fill", fg)
    assert edge[:3] == ink[:3] and edge[3] == 255, \
        ("the line is not the colour the letters were going to be", edge)


def test_ordinary_writing_is_untouched():
    from mangatl.render import _hollow_colours
    ink, halo = (0, 0, 0, 255), (255, 255, 255, 255)
    assert _hollow_colours(_region(), ink, halo) == (ink, halo)


def test_a_colour_in_the_override_is_the_line_not_an_exception():
    """The trap the first version fell into, and it would have meant the whole
    thing never fired on a real page.

    `inkstyle.measure_page` writes `fg` into `layout_override` for every region
    it can read - the MEASURED ink colour, not somebody's choice, and nothing
    in the record tells the two apart. A guard that bailed out on any `fg`
    present therefore bailed out always. It is also the colour wanted: the ink
    is what the line is drawn in.

    Which is what the page showed. のびー is black ink on light artwork; the
    background rule had chosen WHITE letters for that box, so deferring to it
    drew a white line on white paper.
    """
    from mangatl.render import _hollow_colours
    measured_ink = (2, 2, 2, 255)
    r = _region(hollow=True, rim=2, fg="#020202")
    fg, edge = _hollow_colours(r, measured_ink, (255, 255, 255, 255))
    assert fg[3] == 0
    assert edge[:3] == (2, 2, 2), edge


def test_the_measured_rim_is_the_width_that_is_drawn():
    """And it does NOT move with the point size, which is the whole finding."""
    from mangatl.render import _measured_width

    class _L:
        font_size = 102
    assert _measured_width(_region(hollow=True, rim=2), _L(), 14) == 2
    _L.font_size = 300
    assert _measured_width(_region(hollow=True, rim=2), _L(), 42) == 2
    # ...and writing that is not hollow keeps the legibility rule of thumb.
    assert _measured_width(_region(), _L(), 42) == 42


def test_the_preview_is_told_the_same_thing_as_the_exporter():
    """The browser draws its own typesetting. `assign_colours` says in its own
    docstring that the two must agree, and a hollow block is exactly where
    they would come apart: the export would draw a rim round nothing and the
    preview a solid word.

    The colours reach the browser as CSS, so "no fill" has to travel as a
    colour rather than as a flag - `rgba(...,0)`.
    """
    import inspect
    from mangatl import editor
    from where import PKG
    assert editor._css_rgba((2, 2, 2, 0)) == "rgba(2,2,2,0)"
    assert editor._css_rgba((0, 0, 0, 255)) == "rgba(0,0,0,1)"
    # The payload builder asks the same function the exporter does. Matched on
    # the CALL and not on its exact arguments: the preview gained a fourth one
    # (the unsaved override, which cannot be put on a shared region while the
    # server answers on threads) and this went red over a call that had got
    # more correct, not less. See `test_the_preview_and_the_page_agree`.
    assert "_hollow_colours(region, fg, edge" in inspect.getsource(editor), \
        "the browser preview is not told about hollow writing"

    # ...and the browser applies the rule ITSELF as well, because the fill it
    # draws prefers `layout_override.fg` over anything the server sends - and
    # that key is the measured INK colour. Without this the preview drew a
    # solid word where the export drew a rim round nothing.
    #
    # Matched on the FUNCTION and not on the three lines it used to be. The
    # box you type in and the ring round it need the same pair and each had a
    # copy of it; the copies disagreed, and clicking a block changed its
    # colour. `inkPair` is the one place now - see `test_the_box_you_type_into`.
    js = (PKG / "static" / "js" / "typesetting.js").read_text(encoding="utf-8")
    assert "function inkPair(" in js, \
        "the preview has no single answer for the fill and the rim"
    body = js.split("function inkPair(r, L, ss){")[1].split("\n}")[0]
    assert "const hollow=!!ov.hollow;" in body, \
        "the preview does not know about hollow writing"
    assert "const fill=hollow?'rgba(0,0,0,0)':inkc;" in body
    assert "const rim=hollow?" in body and ":inkc)" in body, \
        "the preview draws the line in the halo colour, which is invisible"
    assert "inkPair(r,L)" in js.split("function drawText(){")[1], \
        "the drawing does not ask it"


# ---------------------------------------------- one character does not lean

def test_one_japanese_character_is_set_flat():
    """lee: *"also if the jappennese sfx chareter is just one charater in the
    box it shoud just be flat with no angle"*.

    He is right about the geometry and not only the look. `sfx.sfx_frame` fits
    an axis through the ink, and an axis through ONE glyph is not a direction
    of writing - it is the long way through that glyph's own shape. ン slopes
    down-left and ク slopes down-right, so two single-character effects side by
    side lean opposite ways for a reason nobody reading the page can see.
    """
    from mangatl.typeset import fit_sfx_region, TypesetConfig, _one_character
    cfg = TypesetConfig()

    def lay_for(src):
        r = TextRegion(id=1, bbox=(40, 40, 220, 120), kind="sfx")
        r.polygon = [(40, 40), (260, 40), (260, 160), (40, 160)]
        r.src_text = src
        r.sfx_len, r.sfx_wid = 0.9, 0.9
        r.sfx_vertical = False
        r.angle = 22.0
        return fit_sfx_region(r, "THUD", cfg)

    assert _one_character(TextRegion(id=1, bbox=(0, 0, 9, 9), kind="sfx",
                                     src_text="ン"))
    one, many = lay_for("ン"), lay_for("ドドド")
    assert one is not None and many is not None
    assert not float(one.rotate or 0.0), \
        ("a single character was set on a slant: %r" % one.rotate)
    assert abs(float(many.rotate)) > 1, \
        ("three characters stopped leaning too: %r" % many.rotate)


def test_a_composed_character_counts_as_one():
    """ド is one character. A reader that hands it back as ト plus a combining
    ゙ is describing the same one glyph in two codepoints, and the count has to
    be of characters rather than of the encoding it arrived in."""
    import unicodedata
    from mangatl.typeset import _one_character
    apart = unicodedata.normalize("NFD", "ド")
    assert len(apart) == 2, "the fixture is not actually decomposed"
    for src in ("ド", apart, " ド ", "ド\n"):
        assert _one_character(
            TextRegion(id=1, bbox=(0, 0, 9, 9), kind="sfx", src_text=src)), src
    for src in ("ドン", "のびー", "", "  "):
        assert not _one_character(
            TextRegion(id=1, bbox=(0, 0, 9, 9), kind="sfx", src_text=src)), src
