# -*- coding: utf-8 -*-
"""The box you type into, and why it stopped changing colour.

lee, with two screenshots of the same block a second apart - hollow outlined
letters, then the same word solid black with a red squiggle under it:
*"fix teh issue of when i clcik a box and teh text color change it shodu
always be teh same , also remove teh red spellcheck on teh box"*.

## The colour

`placeEditor` worked the ink out for itself, and got two things wrong at once.

    const inkOf=c=>(... ? (st.edge||L.edge||'#000') : c);
    const taInk=inkOf(st.fg||L.fg||'#000');

**It borrowed.** With no fill it typed in the RIM's colour instead, so that
there was something to see - which turned a block somebody had deliberately
emptied solid the moment it was clicked and hollow again the moment it was
clicked away.

**And it read the wrong field.** `st.fg` is the colour the server sent;
`drawText` reads `ov.fg` first, which is the MEASURED ink. A block whose style
was measured therefore changed colour on the way in even when it had a fill,
which is the general form of the complaint.

`inkPair(r, L)` is the one rule now, and the drawing, the editor and the
editor's rim all ask it. Where there is nothing inside the letters the editor
draws them the way the page does - a real stroke on the outline, artwork
showing through - and `-webkit-text-stroke` is right for exactly this case:
the reason it is banned everywhere else is that it eats into the fill, and
here there is no fill to eat. The caret takes the rim's colour so it can still
be found.

## The squiggle

Every word in that box is a sound effect, a name, or a line the copy editor
has already been over, and the browser's dictionary knows none of them - so
the red underline was on almost every block, drawn across artwork at whatever
size the letters are.
"""
import os
import re

import pytest

from where import PKG                                       # noqa: E402


def _js(name):
    return open(os.path.join(str(PKG), "static", "js", name),
                encoding="utf8").read()


def _body(js, head, end="\n}"):
    assert head in js, head
    return js.split(head)[1].split(end)[0]


def _code(text):
    """The code, with its prose taken out.

    Every guard in this suite that reads source has now been fooled once by
    the comment explaining the thing it forbids. This one bans `st.fg` in a
    function whose comment is about `st.fg`.
    """
    out = []
    for line in text.splitlines():
        line = line.split("//", 1)[0]
        out.append(line)
    body = "\n".join(out)
    while "/*" in body:
        a = body.index("/*")
        b = body.find("*/", a + 2)
        if b < 0:
            break
        body = body[:a] + body[b + 2:]
    return body


# ------------------------------------------------------------- one rule

def test_there_is_one_place_the_fill_and_the_rim_are_worked_out():
    js = _js("typesetting.js")
    assert "function inkPair(" in js, "the pair is still worked out per caller"
    body = _code(_body(js, "function inkPair(r, L, ss){"))
    # THE LIVE STYLE FIRST, the saved override second.
    #
    # This line used to read `ov.fg||st.fg||L.fg` - the override first - on
    # the grounds that the exporter reads `style_of`, so the preview ought
    # to read the same two fields in the same order. But `r.style` is not
    # one of those two fields: the server never sends it and nothing but
    # this browser writes it. It is the PANEL as it stands right now, and
    # `layout_override` is the last answer the server gave back. Reading
    # the server's answer first meant a colour picked on a block that had
    # ever been saved went on painting the old one until the round trip
    # landed - 660ms measured against a 4ms redraw, and forever when the
    # request never landed. lee: *"the color doesnt change until i change
    # page and go back or reload the page"*.
    #
    # `pick` and `num` here, and `styleNow` on the panel, have always read
    # them this way round for exactly this reason. These two lines were the
    # only place in the file that did not.
    flat = body.replace(" ", "")
    assert "pick(st,ov,'fg')" in flat, body
    assert "pick(st,ov,'edge')" in flat, body
    assert "ov.fg||st.fg" not in flat, \
        "the fill reads the server's answer before the panel's again"
    assert "hollow" in body and "rim" in body


@pytest.mark.parametrize("fn,asks", [
    ("function placeEditor(ta, r){", "inkPair("),
    # the mirror asks `runStyle`, which asks `inkPair` - same one place,
    # one hop further, so a RANGE's own colours rank the same way
    ("function editInkMirror(ta, r){", "runStyle(")])
def test_the_editor_and_its_rim_both_ask_it(fn, asks):
    body = _code(_body(_js("typesetting.js"), fn))
    assert asks in body, f"{fn} still has its own copy"


def test_the_editor_no_longer_borrows_the_rim_for_the_fill():
    js = _js("typesetting.js")
    assert "const inkOf=" not in js, "the borrowing is still there"
    body = _code(_body(js, "function placeEditor(ta, r){"))
    assert "st.fg" not in body, \
        "the editor still reads the sent colour ahead of the measured one"


def test_nothing_inside_is_typed_into_as_nothing_inside():
    """The page's own hollow letterform, under the caret: the box itself
    draws NO stroke - a CSS stroke is centred, half of it goes inward, and
    with nothing behind it that half is the see-through middle, so clicking
    a hollow block filled its letters with the rim's colour, usually white.
    lee: *"when i clcik a transparent box, it ussly get a white fill"*. The
    rim comes from `editInkMirror`, which draws it through `hollowInk`'s
    masks exactly as the page does."""
    body = _code(_body(_js("typesetting.js"), "function placeEditor(ta, r){"))
    assert re.search(r"webkitTextStroke\s*=\s*''", body), \
        "the box types in a centred stroke again - the white fill"
    assert "editInkMirror(ta, r)" in body, "nothing draws the rim at all"
    assert re.search(r"caretColor\s*=\s*hole\s*\?", body), \
        "the caret is invisible in a block with no fill"
    # ...through `inkRun`, which is the ONE place the five ink layers are
    # built now - the mirror had its own copy of them until the page and
    # the box had disagreed four separate times.
    mirror = _code(_body(_js("typesetting.js"),
                         "function editInkMirror(ta, r){"))
    assert "inkRun(" in mirror, "the mirror builds its own ink again"
    ink = _code(_body(_js("typesetting.js"), "function inkRun(host, txt, S, ctx){"))
    assert "hollowInk(" in ink, \
        "the ink does not use the page's masked rim"


def test_a_fill_gradient_stays_while_you_type():
    """lee: *"some of teh affcets dont stay when i clcik on it"*. The box
    paints its own fill gradient (clipped to the letters), and every effect
    that paints AROUND the letters lives in the mirror UNDER it - one
    element cannot layer a ring over a background without covering it."""
    body = _code(_body(_js("typesetting.js"), "function placeEditor(ta, r){"))
    assert "linear-gradient" in body, "the gradient vanishes on click"
    assert re.search(r"backgroundClip\s*=\s*'text'", body), body
    assert re.search(r"textShadow\s*=\s*''", body), \
        "the box carries a text-shadow again - it would paint over the " \
        "gradient the moment both are set"


def test_the_mirror_follows_every_keystroke_and_leaves_with_the_box():
    """The rim is redrawn on the CHANGE, before the debounced server
    preview - waiting for that would leave the ink a word behind the caret.

    The keystroke used to arrive as an `input` listener on the
    contenteditable; it arrives as the editor's own `changed` hook now
    (`tbMount`), which is the same moment by a different name."""
    js = _js("typesetting.js")
    hook = js.split("changed(){")[1].split("},")[0]
    assert "editInkMirror(ta, r)" in hook.split("setTimeout")[0], \
        "the mirror waits for the debounced server preview - the rim runs " \
        "a word behind the caret"
    close = _body(js, "function closeCanvasEdit(commit){")
    assert "_rim" in close, "the mirror outlives the box it mirrors"


def test_the_rings_of_shadow_copies_are_gone_for_good():
    """`editShadow`, `glowShadows` and `shadowShadows` faked every effect as
    rings of text-shadow copies. The rings were uncalibratable (overlapping
    tails add up) and could not layer (a ring paints over the element's own
    background, which is where a fill gradient lives) - both measured, both
    reported by lee. The mirror draws the export's own construction instead;
    a ring creeping back in means one of those two bugs is on its way back."""
    js = _js("typesetting.js")
    for gone in ("function editShadow(", "function glowShadows(",
                 "function shadowShadows("):
        assert gone not in js, "%s is back" % gone


# ------------------------------------------- what the page draws, hollow

def test_a_hollow_block_is_previewed_at_the_width_it_is_drawn_at():
    """The back-and-front pair works because the clean fill covers the inner
    half of a doubled stroke. With no fill nothing covers it.

    ## The doubled stroke came BACK, and this is the interesting part

    The first answer was to halve it: one span at the real width, no fill. That
    is a stroke CENTRED on the outline, so half of it still went inward - and
    measured against `/render/0` the editor drew a solid letter where the page
    draws a hollow one, because PIL grows a stroke OUTWARD. 0.41 of what the
    effect changed. lee: *"the preiew in the editor donst match what is
    exprted fix that"*.

    So the width is doubled again and the glyph body is MASKED OUT of it, which
    leaves the outward half alone - the shape PIL draws. CSS cannot do that;
    `typesetting.hollowInk` draws it in SVG. What this test guards is that the
    doubling never comes back WITHOUT the mask, which is the version that fills
    the letter in.
    """
    body = _code(_body(_js("typesetting.js"),
                       "function inkRun(host, txt, S, ctx){"))
    assert "hole" in body, "the hollow case is not told apart"
    head = body.split("if(S.sw>0){")[0]
    assert "hollowInk(" in head, "the hollow branch draws it some other way"
    assert "webkitTextStroke" not in head, \
        "the hollow rim is a centred CSS stroke again"

    ink = _code(_body(_js("typesetting.js"), "function hollowInk(",
                      "\nfunction "))
    assert re.search(r"sw\s*\*\s*2", ink), \
        "the rim is not stroked at twice the width"
    assert "mask" in ink, "...and nothing is masked out of it"


# ------------------------------------------------------------ the squiggle

@pytest.mark.parametrize("attr,want", [
    ("spellcheck", "false"),
    ("autocorrect", "off"),
    ("autocapitalize", "off"),
    ("autocomplete", "off"),
    ("data-gramm", "false")])
def test_nothing_underlines_or_rewrites_the_words_in_the_box(attr, want):
    """No red squiggle under a sound effect, and no phone keyboard
    "helping" - a typesetter's box is the last place a machine should be
    changing what was typed. lee: *"remove teh red spellcheck on teh box"*.

    Asked of the ELEMENT and not of the source. The editor mounts a child
    of its own and these ride on that (`tbMount`), so a grep of
    `editOnCanvas` now proves nothing either way - and the element is the
    thing the browser actually reads.
    """
    body = _code(_body(_js("textbox.js"), "function tbMount(host, r, hooks){"))
    assert attr in body, \
        "%s is no longer set on the element the editor mounts" % attr
    assert "'" + want + "'" in body or '"' + want + '"' in body
