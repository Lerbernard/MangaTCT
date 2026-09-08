# -*- coding: utf-8 -*-
"""Letters with nothing inside them, asked for by hand.

lee: *"can you add a trnsparent option in the color picker for the fill, wher
its a white box with ared kine trought it diagonhaly"*.

The white box with the red diagonal is what every drawing program draws for
"none", and that is the reason to draw it that way here: it is a thing people
already recognise, and a plain white swatch sitting in a row of colours reads
as the colour white.

## What it is stored as

`render.NO_FILL` — `#00000000`, an eight-digit hex whose alpha is zero.

A colour, not a flag and not a word. It needs no new field, no new question at
any of the half-dozen places a colour travels through, and everything that
draws with it already works in RGBA — `_hollow_colours` has been handing back
an alpha-zero fill since the day it was written.

**It is not `hollow`.** Hollow says *the rim IS the letterform*, and takes the
rim's colour from the ink for that reason. Somebody who empties the fill by
hand has said nothing about the outline, and theirs stays theirs.

## The one that would have shipped broken

`render_page` draws from `colours_for` and never reads `lay.fg`. So an emptied
fill exported correctly while `lay.fg` said `#000000` — and `lay.fg` is what
the PREVIEW and the panel read. The block would have come out hollow on the
page and solid black on screen, which is the one thing that field exists to
prevent. `_css` carries the alpha when there is one.
"""
import os
import re

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from PIL import Image, ImageDraw, ImageFont                 # noqa: E402

from mangatl import kinds as K                              # noqa: E402
from mangatl import render as R                             # noqa: E402
from mangatl.models import TextRegion                       # noqa: E402
from where import PKG                                       # noqa: E402


@pytest.fixture(autouse=True)
def _own_kinds():
    """THIS FILE SETS ITS OWN BOX TYPES, WHATEVER RAN BEFORE IT.

    `kinds.use` is a module global - the open project's sub-types - and a test
    that registers some and does not put them back leaves them registered for
    the rest of the worker. That is not hypothetical: the inner-glow test below
    renders a `sfx_big`, and whether `sfx_big` is a REGISTERED kind decides
    which path sizes it. Unregistered it is capped at `max_font` and the word
    comes out at 34pt; registered it is a big sound effect sized to its box,
    which here is 160pt - letters five times as tall, with counters twenty-six
    times the area.

    So this file passed alone, passed in most orders, and failed in batch 3
    with `('and a big one never gets there', [673, 1423, 4975], 25152)`: a
    fourteen-pixel glow reaching into a counter it never had a hope of filling.
    Nothing was wrong with the glow. The page was five times bigger than the
    page the numbers were chosen against.

    An effect is in ABSOLUTE PIXELS - which is the whole of *a pen has a width*
    - so "a big glow fills the middle" can only be asked of a stated size. This
    states it.
    """
    was = K.known()
    K.use([])
    yield
    K.use(was)


W = (255, 255, 255, 255)
B = (0, 0, 0, 255)


def _r(**ov):
    return TextRegion(id=1, bbox=[0, 0, 10, 10], kind="bubble",
                      layout_override=ov or None)


# ------------------------------------------------------------ the value

def test_no_fill_is_a_colour_with_no_alpha():
    assert R.hex_rgb(R.NO_FILL) == (0, 0, 0, 0)


def test_eight_digits_carry_an_alpha():
    assert R.hex_rgb("#12345678") == (0x12, 0x34, 0x56, 0x78)


def test_six_digits_are_still_opaque():
    assert R.hex_rgb("#ff0000") == (255, 0, 0, 255)


@pytest.mark.parametrize("bad", ["#abc", "#12345", "#1234567", "", "red",
                                 "#gggggg", None, 7])
def test_and_nothing_else_is_a_colour(bad):
    """Two lengths and no more. A three-digit shorthand would be a second
    spelling of a colour this app never writes, and every place that compares
    one stored colour against another would have to learn about it."""
    assert R.hex_rgb(bad) is None


def test_the_css_form_only_grows_when_there_is_something_to_say():
    assert R._css((255, 0, 0, 255)) == "#ff0000"
    assert R._css((255, 0, 0)) == "#ff0000"
    assert R._css((0, 0, 0, 0)) == "#00000000"
    assert R._css((1, 2, 3, 128)) == "#01020380"


# ------------------------------------------------------- what it does

def test_an_emptied_fill_reaches_the_drawing():
    fg, edge = R.colours_for(_r(fg=R.NO_FILL), W, B)
    assert fg[3] == 0, "the fill is still opaque"


def test_the_outline_is_left_exactly_as_it_was():
    """An emptied fill has nothing to be invisible against, and the outline is
    the only thing left on the page - turning it over would be turning over
    the whole of what was asked for."""
    fg, edge = R.colours_for(_r(fg=R.NO_FILL), W, B)
    assert edge == B, edge
    fg, edge = R.colours_for(_r(fg=R.NO_FILL, edge="#ff0000"), W, B)
    assert R._css(edge) == "#ff0000"


def test_a_solid_black_fill_still_turns_a_black_edge_over():
    """The rule above is about ALPHA, not about black - the invisible-edge
    rule has to go on working for the case it was written for."""
    fg, edge = R.colours_for(_r(fg="#000000"), W, B)
    assert R._css(edge) == "#ffffff"


def test_the_page_comes_out_hollow():
    """Through `draw_line`, the way `render_page` calls it. The letters are
    drawn in a colour that is not the outline's, so 'the fill went' and 'the
    fill is the same colour as the rim' cannot be confused."""
    font = os.path.join(str(PKG), "fonts", "ComicNeue-Regular.ttf")
    img = Image.new("RGBA", (640, 170), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(font, 110)
    R.draw_line(d, 320, 85, "SPLASH", f, 0.0, 0.0,
                fill=(0, 0, 0, 0), stroke_width=3, stroke_fill=(220, 30, 30, 255))
    flat = Image.new("RGB", img.size, (255, 255, 255))
    flat.paste(img, (0, 0), img)
    a = np.array(flat)
    red = int(((a[:, :, 0] > 150) & (a[:, :, 1] < 90)).sum())
    black = int((a.max(2) < 80).sum())
    assert red > 500, "no outline was drawn"
    assert black == 0, "something filled the letters in"


def test_the_layout_carries_it_to_the_screen():
    """`assign_colours` is what the preview and the panel read, and it wrote
    six digits. The block came out hollow on the page and solid black on
    screen."""
    import inspect
    src = inspect.getsource(R.assign_colours)
    assert "_css(fg)" in src and "_css(edge)" in src, src


# --------------------------------------------------------- the picker

def test_the_outline_may_not_be_emptied():
    """Letters with no fill are a real thing - the outline is the letterform.
    Letters with no OUTLINE are just letters, which is what clearing that field
    already gives. An outline of nothing on a fill of nothing is a block that
    does not exist.

    This used to read `got == ["lyFg"]`, which said the same thing by listing
    the whole world. The OUTER GLOW joined the list when a sound effect over
    artwork started getting one whether or not anybody asked
    (`render.auto_glow`): an empty glow field means *nobody has spoken* now, so
    `none` has to be sayable, and the picker is where it is said. Nothing about
    the outline changed - so this asks about the outline.
    """
    js = open(os.path.join(str(PKG), "static", "js", "typesetting-edit.js"),
              encoding="utf8").read()
    m = re.search(r"const CAN_BE_EMPTY = \[([^\]]*)\]", js)
    assert m, "nothing says which wells may be emptied"
    got = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    assert "lyFg" in got, got
    assert "lyEdge" not in got, got
    # ...and every name on the list is a well that really can be nothing.
    assert set(got) <= {"lyFg", "lyGlow"}, got


def test_the_browser_writes_the_same_value_the_server_reads():
    js = open(os.path.join(str(PKG), "static", "js", "picker.js"),
              encoding="utf8").read()
    m = re.search(r"const NO_FILL = '([^']+)'", js)
    assert m, "the picker has no NO_FILL"
    assert m.group(1) == R.NO_FILL, (m.group(1), R.NO_FILL)


def test_the_swatch_is_offered_and_is_not_a_colour():
    """It does not move the wheel or the hex box: transparent has no hue, so
    treating it as a colour would light up whatever the wheel was last on."""
    js = open(os.path.join(str(PKG), "static", "js", "picker.js"),
              encoding="utf8").read()
    assert "setPickedNone()" in js
    assert "noswatch" in js, "the swatch is not drawn"
    body = js.split("function setPickedNone()")[1].split("\n}")[0]
    assert "pickerApply" not in body, "the wheel was asked about transparent"
    assert "NO_FILL" in body


def test_it_is_drawn_as_a_white_box_with_a_red_line_through_it():
    css = open(os.path.join(str(PKG), "static", "css", "editor.css"),
               encoding="utf8").read()
    block = css.split(".noswatch{")[1].split("}")[0]
    assert "#fff" in block, "the box is not white"
    assert re.search(r"#e0313\d|#f00|red", block), "there is no red line"
    assert "linear-gradient" in block and "bottom left" in block, \
        "the line is not a diagonal"


def test_the_panel_reads_eight_digits_back():
    """`cssHex` is what fills the well when the panel is built. It matched six
    digits only, so a block somebody had emptied read as solid black."""
    js = open(os.path.join(str(PKG), "static", "js", "panels.js"),
              encoding="utf8").read()
    body = js.split("function cssHex(c, fallback){")[1].split("\n}")[0]
    assert "{8}" in body, "cssHex still cannot read an emptied fill"


def test_the_well_says_none_rather_than_eight_hex_digits():
    """A transparent chip on a dark panel looks like a field nobody has
    touched, and "not set" and "set to nothing" are different answers."""
    js = open(os.path.join(str(PKG), "static", "js", "panels.js"),
              encoding="utf8").read()
    assert "function wellBits(" in js
    body = js.split("function wellBits(")[1].split("\n}")[0]
    assert "isNoFill" in body and "'none'" in body, body
    assert "noswatch" in body, "the emptied well is not drawn as the swatch"


def test_an_emptied_block_is_typed_into_as_an_emptied_block():
    """It used to BORROW the rim's colour, so that there was something to see.
    lee looked at a hollow effect turn solid the moment he clicked it: *"fix
    teh issue of when i clcik a box and teh text color change it shodu always
    be teh same"*. `test_the_box_you_type_into` is the whole story.

    Both spellings still have to be recognised: `rgba(...,0)`, which is what
    the server sends the preview, and the hex the picker writes."""
    js = open(os.path.join(str(PKG), "static", "js", "typesetting.js"),
              encoding="utf8").read()
    body = js.split("function noInk(c){")[1].split("\n}")[0]
    assert "{6}00" in body, "an emptied fill is read as if it were ink"
    assert "rgba" in body
    assert "const inkOf=" not in js, "the borrowing is back"


# ------------------------------------------- light on letters with no fill

def _glow_page(ov):
    """One word, no fill, rendered the way `render_page` renders it."""
    from mangatl.typeset import TypesetConfig, fit_region
    from mangatl.models import Page
    img = np.full((240, 720, 3), 255, np.uint8)
    r = TextRegion(id=0, bbox=(30, 40, 660, 160),
                   polygon=[[30, 40], [690, 40], [690, 200], [30, 200]],
                   kind="sfx_big", dst_text="SPLASH", src_text="x")
    r.text_mask = np.zeros((240, 720), np.uint8)
    r.text_mask[40:200, 30:690] = 255
    p = Page(image=img)
    p.regions = [r]
    cfg = TypesetConfig()
    r.layout = fit_region(r, cfg)
    r.layout.fg, r.layout.edge, r.layout.stroke = "#ffffff", "#000000", 4
    r.layout_override = dict({"fg": R.NO_FILL, "edge": "#000000",
                              "stroke": 4}, **ov)
    return R.render_page(p, cfg).astype(int)


def _count(a, ch):
    """Pixels that are decidedly that colour and nothing else. BGR."""
    other = [i for i in range(3) if i != ch]
    return int(((a[:, :, ch] > 150)
                & (a[:, :, other[0]] < 110) & (a[:, :, other[1]] < 110)).sum())


def _inside(plain):
    """The paper the letterform ENCLOSES - the see-through middle itself.

    Counting white pixels over the whole page instead was the first go, and it
    is not a measurement: the halo eats paper outside the letters as well, the
    two effects eat different amounts of it, and the whole total moves with
    whatever font the run ends up using. This asks the only question that
    matters - is the middle still the page? - and asks it of pixels that the
    same run's own plain render says are enclosed.
    """
    ink = (plain.astype(np.uint8).max(2) < 200).astype(np.uint8)
    seed = (1 - ink).astype(np.uint8)
    cv2.floodFill(seed, np.zeros((seed.shape[0] + 2, seed.shape[1] + 2),
                                 np.uint8), (0, 0), 2)
    return seed == 1                         # paper no border can reach


def test_an_outer_glow_reaches_a_block_with_no_fill():
    """lee: *"make it so that i can add outer and inter glow to transparent
    text"*. The halo is drawn from the silhouette, not from the fill, so this
    already worked - it is here so that it goes on working."""
    a = _glow_page({"glow": "#ff0000", "glow_size": 12})
    assert _count(a, 2) > 1500, "no halo"


def test_and_stops_at_the_letters_the_way_it_does_on_a_solid_one():
    """A glow is light AROUND a shape. The exporter stamps the letters over
    the halo and a transparent fill ERASES it inside them, which is what keeps
    the middle see-through; without that the block is a red blob."""
    a = _glow_page({"glow": "#ff0000", "glow_size": 12})
    plain = _glow_page({})
    # the halo eats into the paper ROUND the word...
    assert int((a.min(2) > 250).sum()) < int((plain.min(2) > 250).sum())
    # ...and not into the paper the word encloses
    inside = _inside(plain)
    dirty = int((inside & (a.min(2) <= 250)).sum())
    assert dirty < 0.35 * int(inside.sum()), (dirty, int(inside.sum()))


def test_an_inner_glow_comes_off_the_rim_and_reaches_further_as_it_grows():
    """THE LETTERFORM IS NOT ALWAYS THE GLYPH.

    On writing with nothing inside it the letterform is the RIM -
    `_hollow_colours` says so and draws it that way - so the glyph body is a
    hole. The first go glowed into the hole from its own edges, which poured
    the colour straight across the see-through middle: a block lee had
    deliberately emptied came back solid green. The second cut the glow to the
    ring, which kept the middle but made the number do nothing, because a rim
    is four pixels wide and the effect saturated at once. lee: *"inner glow
    donst acvculy grwo when i increase teh number"*.

    So the light comes OFF the rim and reaches inward, and how far it reaches
    is what the number buys. Small leaves the middle alone; large fills it,
    which is what an inner glow is for.
    """
    plain = _glow_page({})
    inside = _inside(plain)
    room = int(inside.sum())

    def lit(a):
        """Enclosed paper the glow has DECIDEDLY taken - not merely tinted.
        Every size tints some of every counter, so a threshold at the edge of
        white measures the blur's tail rather than the effect's reach."""
        return int((inside & (a.min(2) <= 120)).sum())

    got = [lit(_glow_page({"iglow": "#00ff00", "iglow_size": s}))
           for s in (2, 6, 14)]
    assert _count(_glow_page({"iglow": "#00ff00", "iglow_size": 6}), 1) > 200, \
        "no inner glow at all"
    assert got[0] < 0.4 * room, ("even the smallest fills it", got[0], room)
    assert got[0] < got[1] < got[2], ("the number does nothing", got)
    assert got[2] > 0.8 * room, ("and a big one never gets there", got, room)


def test_a_block_with_a_fill_is_lit_exactly_as_it_was():
    """The scoping is `fg[3] == 0` and nothing else - the rule for solid
    letters is untouched, or every page that has an inner glow on it moves."""
    import inspect
    # the painting lives in `_ink_layer` now - one style's whole stack,
    # called once per distinct style so part of the text can wear its own
    src = inspect.getsource(R._ink_layer)
    assert "hole = fg[3] == 0" in src, "the scoping moved"
    body = src.split("igcol = hex_rgb")[1]
    assert "if hole:" in body, body[:400]


# ------------------------------------------ the one colour there is left

def _hollow(**hand):
    return TextRegion(id=1, bbox=[0, 0, 10, 10], kind="sfx_big",
                      layout_measured={"hollow": True, "rim": 4,
                                       "fg": "#020202"},
                      layout_override=(hand or None))


def test_an_outline_set_by_hand_is_the_one_thing_there_is_to_set():
    """lee, with a hollow SPLAAASH and #ff0000 in the outline well: *"teh
    outline color donet do anything even thoug teh outline is what is left"*.

    The rim takes the ink's colour because an AUTOMATIC edge is a halo - a
    colour `_ink_colours` chose against the artwork to hold the letters off
    it - and a letter that is only a line, drawn in a halo colour, is nothing
    on the page. That reasoning has nothing to say about a person."""
    ink = (2, 2, 2, 255)
    fg, edge = R._hollow_colours(_hollow(edge="#ff0000"), ink, W)
    assert fg[3] == 0
    assert R._css(edge) == "#ff0000"


def test_and_the_ink_is_still_what_is_left_when_nobody_set_one():
    fg, edge = R._hollow_colours(_hollow(), (2, 2, 2, 255), W)
    assert R._css(edge) == "#020202", "the rim went back to the halo colour"


def test_an_emptied_outline_is_not_a_choice_of_outline():
    """An outline of nothing on a fill of nothing is a block that does not
    exist, so it falls back the way no answer does."""
    fg, edge = R._hollow_colours(_hollow(edge=R.NO_FILL), (2, 2, 2, 255), W)
    assert R._css(edge) == "#020202"


def test_a_fill_in_the_override_is_still_not_read_as_a_choice():
    """It would be the obvious way to ask for a filled letterform, and it
    cannot be read that way: `saveTypesetting` wrote the fill well's value
    into `layout_override` on every save, and until the well learned to say
    "none" that value was the measured ink. Every hollow block in a chapter
    worked on before today has it, and turning them all solid on load is not
    a feature."""
    fg, edge = R._hollow_colours(_hollow(fg="#020202"), (2, 2, 2, 255), W)
    assert fg[3] == 0, "an old save turned a hollow block solid"


def test_the_hand_is_read_off_the_override_and_not_off_the_ranking():
    """`style_of` merges the measurement in, so asking it "was this set?"
    always answers yes for anything `inkstyle` reads. That ambiguity is the
    one the field split exists to end."""
    assert R.hand_style(_hollow(edge="#ff0000")) == {"edge": "#ff0000"}
    assert R.hand_style(_hollow()) == {}


def test_the_browser_ranks_the_rim_the_same_way():
    js = open(os.path.join(str(PKG), "static", "js", "typesetting.js"),
              encoding="utf8").read()
    body = js.split("function inkPair(r, L, ss){")[1].split("\n}")[0]
    assert "r.layout_override" in body, "the preview cannot tell a hand edit"
    assert "hand.edge" in body, "a hand outline is ignored in the preview"


def test_the_fill_well_says_none_on_a_hollow_block():
    """lee: *"the transparent text shoud acuuly be transaparent with teh
    transtaptrent box in teh text color box"*. The well is the control as well
    as the readout - what it shows is what the next save writes back."""
    js = open(os.path.join(str(PKG), "static", "js", "panels.js"),
              encoding="utf8").read()
    assert "function lyFill(" in js
    body = js.split("function lyFill(r, ov, L){")[1].split("\n}")[0]
    assert "inkPair" in body and "hole" in body, body
    assert "wellBits('lyFg', lyFill(" in js, "the well does not use it"


def test_the_preview_draws_the_halo_off_the_line_and_not_through_it():
    """A `text-shadow` is painted BEHIND the letters, and letters with no fill
    let it through - so the preview showed a halo in the middle the export
    knocks out.

    The first answer was a `drop-shadow` off a stroked span, which works off
    what the element actually PAINTS. The answer now is SVG: the hollow branch
    strokes at twice the width and masks the glyph body out, so the halo is cut
    to the paper OUTSIDE the letters exactly as `render_page` cuts it - and the
    inner glow is cut to the hole instead, which the CSS version could not draw
    at all. See `typesetting.hollowInk`.
    """
    js = open(os.path.join(str(PKG), "static", "js", "typesetting.js"),
              encoding="utf8").read()
    assert re.search(r"if\(glOn\s*&&\s*!hole\)", js), \
        "the preview still shadows the glow through an empty letter"
    # every caller draws through the ONE ink now (`inkRun`) - the page's
    # `inked` and the mirror's `stack` are one-line delegates to it
    head = js.split("function inkRun(")[1].split("if(S.sw>0){")[0]
    assert "hollowInk(" in head, "the hollow branch draws no halo of its own"
    body = js.split("function hollowInk(")[1].split("\nfunction ")[0]
    # Cut to the paper outside, and to the hole inside. Two masks, one each.
    assert "'out'" in body and "'in'" in body, body[:400]
    # ...and NOT as one fat centred stroke, which is where the first go went
    # wrong: a stroke is centred on the outline, so half of every pixel of it
    # goes inward, and at a size worth setting "half" is the whole letter.
    # lee: *"outer glow files teh whole thing"*.
    assert "mask" in body, "nothing is being cut away"
    assert "webkitTextStroke" not in head, \
        "the hollow rim is a centred CSS stroke again"


# --------------------------------------- and the box you type inside

def test_the_edit_box_wears_the_pages_own_rim():
    """lee, with a picture of SI in a heavy rim: *"this is what hapenes when
    i clcika text with a lot of outline"* - and later, of the ring's
    replacement, *"when i clcik a transparent box, it ussly get a white
    fill"*.

    Both designs died of the same constraint: the box you type in is ONE
    element, and one element cannot layer. A ring of hard shadows bulged and
    gapped and painted over the box's own background; a centred stroke
    filled a hollow letter's see-through middle with the rim's colour. So
    the rim (and every other effect) is drawn by `editInkMirror` on a twin
    UNDER the box - `hollowInk`'s masked SVG for a hollow block, a doubled
    stroke covered by the fill above for a solid one - and the box keeps
    only the fill and the caret.
    """
    js = open(os.path.join(str(PKG), "static", "js", "typesetting.js"),
              encoding="utf8").read()
    assert "function editShadow(" not in js, "the ring design is back"
    body = js.split("function editInkMirror(ta, r){")[1].split(
        "\nfunction ")[0]
    # the mirror draws through the ONE ink - `inkRun` - which is where the
    # masked SVG rim and the doubled stroke both live now
    assert "inkRun(" in body, "the mirror builds its own ink again"
    ink = js.split("function inkRun(")[1].split("\nfunction ")[0]
    assert "hollowInk(" in ink, "the hollow rim is not the page's own"
    assert re.search(r"2\s*\*\s*S\.sw", ink), \
        "the solid rim is not the doubled stroke the fill covers"
