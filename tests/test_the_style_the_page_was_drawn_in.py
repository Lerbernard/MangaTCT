# -*- coding: utf-8 -*-
"""A measurement is not a hand correction, and it needed its own field to
prove it.

lee, over page 001 of his chapter, where `ザァァ` is drawn in solid black with
a thin white keyline and came back as white letters inside a twenty-pixel
black rim: *"i feel like all the copy style chnages that we worked on is not
live"*.

It was not. Not once, on any chapter, since the day the measurement was
written.

## What was happening

`inkstyle.measure_page` read the original letters and wrote what it found -
the ink colour, the keyline colour, its width - into `layout_override`. That
field means *"things somebody set by hand"*, and `do_typeset` empties it,
deliberately and correctly: lee: *"when i re typseet a page any custom chnages
to text boxes or custom text box dshoud be removed"*.

The measurement ran in exactly one place: the end of the read. Typeset always
comes after the read. **So the first press of Typeset deleted the answer,
every time.** What shipped instead was the fallback in `_ink_colours` - white
letters, a black rim, and a rim of about a seventh of the point size. Every
sound effect in lee's chapter carries it: 144→20, 134→19, 105→15, 92→13,
77→11, 36→5. A rim proportional to the size is the exact thing the
measurement exists to stop; a pen has a width.

`render._hollow_colours` had already written down what was wrong, a month
before it cost anything: *"that is the MEASURED ink colour, not somebody's
choice, and there is nothing in the record to tell the two apart."*

## What it is now

Two fields, and `style_of` ranks them: **what somebody set** beats **what the
original was drawn with** beats **the automatic choice**. Typeset clears the
first and refreshes the second, which is what each of them deserves.

And the measurement moved to Typeset, because "the last moment before
cleaning" was never true - cleaning writes a plate, and the page on disk keeps
the Japanese for ever. Measured on lee's chapter months after it was read, all
sixteen regions answer, with no key, no coins and no call.
"""
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import render as R                            # noqa: E402
from mangatl.models import TextRegion                      # noqa: E402


def _r(override=None, measured=None, kind="sfx_big"):
    """A big drawn sound unless a test says otherwise.

    `sfx_big` is the one kind that takes the WHOLE measurement - see
    `render.measured_for`, and `test_only_a_big_sound_gets_the_whole_look`
    below for the rest of the scale. Everything in this module about colour
    is about a block entitled to a measured colour; a bubble is not one.
    """
    return TextRegion(id=1, bbox=[0, 0, 10, 10], kind=kind,
                      layout_override=override, layout_measured=measured)


W = (255, 255, 255, 255)
B = (0, 0, 0, 255)


def hexes(pair):
    return tuple("#%02x%02x%02x" % c[:3] for c in pair)


# ------------------------------------------------------------- style_of

def test_nothing_set_and_nothing_measured():
    assert R.style_of(_r()) == {}


def test_the_measurement_is_read():
    assert R.style_of(_r(measured={"fg": "#020202"})) == {"fg": "#020202"}


def test_a_hand_choice_beats_the_measurement():
    got = R.style_of(_r(override={"fg": "#ff0000"},
                        measured={"fg": "#020202", "stroke": 4}))
    assert got == {"fg": "#ff0000", "stroke": 4}, got


def test_an_emptied_control_is_not_a_choice():
    """A field cleared in the panel comes back as "" or null, and "" is not a
    colour. Letting it through would hide the measurement behind nothing."""
    got = R.style_of(_r(override={"fg": "", "edge": None},
                        measured={"fg": "#020202", "edge": "#ffffff"}))
    assert got == {"fg": "#020202", "edge": "#ffffff"}, got


# ------------------------------------------------- how much of it applies

def _kinds_loaded():
    from mangatl import kinds as K
    was = K.known()
    K.use([{"key": "sfx_big", "family": "sfx"},
           {"key": "sfx_small", "family": "sfx"},
           {"key": "narration", "family": "bubble"},
           {"key": "shout", "family": "bubble"},
           {"key": "aside", "family": "freefloat"}])
    return K, was


ALL = {"fg": "#646464", "edge": "#ECECEC", "stroke": 4,
       "glow": "#CECECE", "hollow": True, "rim": 2}


def test_only_a_big_sound_gets_the_whole_look():
    """lee: *"the fimd formatting and copy it should only work for big sfx
    boxe, everything else shoud get teh white fill and black outine or teh
    inverse"*.

    His own chapter is the argument. `020.jpg` id6 is free text on a dark
    panel and measured `#646464` - mid-grey on near-black, barely legible.
    `009.jpg` id4 is a BLACK balloon whose Japanese was white, measured
    `#020202` with a `#ECECEC` keyline: black letters on black paper, so all
    that reaches the page is the outline.
    """
    K, was = _kinds_loaded()
    try:
        got = {k: R.measured_for(_r(measured=dict(ALL), kind=k))
               for k in ("sfx_big", "sfx", "sfx_small", "bubble",
                         "freefloat", "narration", "shout", "aside")}
    finally:
        K.use(was)
    assert got["sfx_big"] == ALL, "a big drawn sound takes all of it"
    line = {"stroke": 4, "hollow": True, "rim": 2}
    assert got["sfx"] == line, "a drawn sound keeps the LINE"
    assert got["sfx_small"] == line
    for k in ("bubble", "freefloat", "narration", "shout", "aside"):
        assert got[k] == {}, (k, got[k])


def test_a_small_sound_keeps_the_rim_it_was_drawn_with():
    """The half that is not a palette. *A pen has a width*: `のびー` has a
    two-pixel rim and the rule of thumb put a fourteen-pixel one round
    STRETCH. Losing that to fix the colours would undo the "it's too small"
    work."""
    K, was = _kinds_loaded()
    try:
        r = _r(measured={"fg": "#020202", "stroke": 4}, kind="sfx_small")
        assert R.stroke_for(r, 11) == 4, "the measured rim went"
        assert hexes(R.colours_for(r, W, B)) == ("#ffffff", "#000000"), \
            "a small sound took a measured colour"
    finally:
        K.use(was)


def test_a_hand_colour_still_applies_to_anything():
    """None of the scoping touches an override. Somebody who sets a colour on
    a bubble has said what they want."""
    K, was = _kinds_loaded()
    try:
        r = _r(override={"fg": "#ff0000"}, measured=dict(ALL), kind="bubble")
        assert R.style_of(r) == {"fg": "#ff0000"}
        assert hexes(R.colours_for(r, W, B))[0] == "#ff0000"
    finally:
        K.use(was)


def test_an_unregistered_sub_type_takes_nothing():
    """The safe direction, and it is the one `kinds.family_of` already
    chooses: an unknown sub-type is a bubble, so the block is typeset in the
    pair that can be read rather than in a colour nobody could check."""
    K, was = _kinds_loaded()
    try:
        K.use([])
        assert R.measured_for(_r(measured=dict(ALL), kind="sfx_small")) == {}
    finally:
        K.use(was)
    # ...except the family's own default, whose key IS the family name and
    # which `family_of` answers without any registry at all.
    assert R.measured_for(_r(measured=dict(ALL), kind="sfx")) == \
        {"stroke": 4, "hollow": True, "rim": 2}


def test_a_block_that_was_never_measured():
    assert R.measured_for(_r(kind="sfx_big")) == {}


# --------------------------------------------------- the pair stays a pair

def test_the_measured_width_is_used():
    assert R.stroke_for(_r(measured={"stroke": 4}), 20) == 4


def test_a_hand_width_still_wins():
    assert R.stroke_for(_r(override={"stroke": 9}, measured={"stroke": 4}),
                        20) == 9


def test_a_measured_fill_does_not_leave_an_invisible_edge():
    """`_ink_colours` hands back a PAIR and says so - *"the edge is the
    opposite colour"*. The measurement writes a fill for every region it can
    read and an edge only where it finds a keyline, so on lee's `ザブン` the
    measured black fill met the automatic black edge: black letters inside an
    eleven-pixel black rim. A blob, and worse than what he had."""
    assert hexes(R.colours_for(_r(measured={"fg": "#020202"}), W, B)) == \
        ("#020202", "#ffffff")


def test_a_light_measured_fill_turns_the_other_way():
    assert hexes(R.colours_for(_r(measured={"fg": "#f8f8f8"}), B, W)) == \
        ("#f8f8f8", "#000000")


def test_an_edge_that_already_reads_is_left_alone():
    """Only the invisible case is touched. Anything else is a decision
    somebody or something else made, and turning it over would be inventing
    one."""
    assert hexes(R.colours_for(_r(measured={"fg": "#020202"}), W, W)) == \
        ("#020202", "#ffffff")
    assert hexes(R.colours_for(_r(measured={"fg": "#ff0000"}), W, B)) == \
        ("#ff0000", "#000000")


def test_a_hand_fill_does_not_move_the_halo():
    """Somebody who picks a red fill and leaves the halo alone has changed
    nothing about what is behind the letters, and the halo is there to hold
    them off it. `#ff0000` against `#000000` is far enough apart to read."""
    assert hexes(R.colours_for(_r(override={"fg": "#ff0000"}), W, B)) == \
        ("#ff0000", "#000000")


def test_naming_both_gets_both():
    """Two colours a hair apart is a thing somebody may want, and only they
    can say so."""
    assert hexes(R.colours_for(
        _r(override={"fg": "#020202", "edge": "#000000"}), W, B)) == \
        ("#020202", "#000000")


def test_a_measured_pair_comes_through_whole():
    assert hexes(R.colours_for(
        _r(measured={"fg": "#020202", "edge": "#f6f6f6"}), W, B)) == \
        ("#020202", "#f6f6f6")


# ------------------------------------------------------------- hollow

def test_a_measured_hollow_still_hollows():
    """The rim IS the letterform, so the fill goes to nothing and the line
    takes the ink colour. It read `layout_override` and would have stopped
    working the moment the measurement moved out of it."""
    fg, edge = R._hollow_colours(_r(measured={"hollow": True}), B, W)
    assert fg[3] == 0, "a hollow letter has nothing inside it"
    assert edge[:3] == B[:3] and edge[3] == 255


def test_a_measured_rim_width_is_used():
    assert R._measured_width(_r(measured={"hollow": True, "rim": 2}), None,
                             14) == 2


# ------------------------------------------------- and it survives Typeset

def test_typeset_keeps_the_measurement_and_drops_the_hand_edits():
    """The whole point. Typeset means "put this page back to what the fitter
    would do" - and what the fitter would do includes drawing the letters the
    way the page draws them."""
    import inspect

    from mangatl import editor
    src = inspect.getsource(editor.do_typeset)
    assert 'r["layout_override"] = None' in src, \
        "Typeset no longer clears the hand corrections"
    assert "_measure_ink" in src, "Typeset does not measure the page"
    at_clear = src.index('r["layout_override"] = None')
    at_measure = src.index("_measure_ink(")
    assert at_clear < at_measure, \
        "the measurement has to come after the clearing, or it is cleared"
    at_clean = src.index("clean_page(")
    assert at_measure < at_clean, \
        "measure the ORIGINAL page, before the cleaner is asked for a plate"


def test_the_record_carries_it_both_ways():
    """A chapter is geometry on disk; a measurement nobody stores is a
    measurement taken again on every open."""
    from mangatl.project import region_record, region_from_record
    r = _r(measured={"fg": "#020202", "stroke": 4})
    rec = region_record(r)
    assert rec["layout_measured"] == {"fg": "#020202", "stroke": 4}
    page = np.full((40, 40, 3), 255, np.uint8)
    back = region_from_record(rec, page)
    assert back.layout_measured == {"fg": "#020202", "stroke": 4}


def test_a_chapter_written_before_the_field_existed():
    """No key in the record is "never measured", which is true, and which the
    next Typeset settles without asking anybody for anything."""
    from mangatl.project import region_from_record
    page = np.full((40, 40, 3), 255, np.uint8)
    back = region_from_record({"id": 1, "bbox": [0, 0, 10, 10],
                               "bubble_bbox": [0, 0, 10, 10],
                               "kind": "bubble"}, page)
    assert back.layout_measured is None
    assert R.style_of(back) == {}


# ------------------------------------------------- the two sides agree

def test_the_browser_ranks_them_the_same_way():
    """`styleOf` in the browser draws the preview and `style_of` on the server
    draws the exported page. A difference between them is a page that does not
    look like what you were shown - so the two are held together here rather
    than left to drift."""
    from where import PKG
    js = open(os.path.join(str(PKG), "static", "js", "core.js"),
              encoding="utf8").read()
    assert "function styleOf(r)" in js, "the browser has no styleOf"
    body = js.split("function styleOf(r)")[1].split("\n}")[0]
    assert "measuredFor(r)" in body, "the preview ignores the measurement"
    assert "layout_override" in body, "the preview ignores the hand edits"
    # ...and in that order: measured laid down first, hand edits over the top.
    assert body.index("measuredFor") < body.index("layout_override"), body


def test_the_browser_scopes_it_the_same_way():
    """And the same scale, or the preview shows a colour on a bubble that the
    exported page will not draw."""
    from where import PKG
    js = open(os.path.join(str(PKG), "static", "js", "core.js"),
              encoding="utf8").read()
    assert "function measuredFor(r)" in js, "the browser has no measuredFor"
    body = js.split("function measuredFor(r)")[1].split("\nfunction ")[0]
    assert "BIG_SOUND" in body and "SHAPE_KEYS" in body, body
    assert "'sfx'" in body, "the browser does not ask about the family"
    # The two lists themselves, held to the server's.
    import re
    from mangatl import render as _R
    big = re.search(r"const BIG_SOUND = '([^']+)'", js)
    assert big and big.group(1) == _R.BIG_SOUND, (big, _R.BIG_SOUND)
    keys = re.search(r"const SHAPE_KEYS = \[([^\]]+)\]", js)
    assert keys, "the browser has no SHAPE_KEYS"
    got = tuple(x.strip().strip("'\"") for x in keys.group(1).split(","))
    assert got == tuple(_R.SHAPE_KEYS), (got, _R.SHAPE_KEYS)


def test_nothing_reads_the_override_alone_for_a_style():
    """Every place that used to ask `layout_override` about how a block is
    DRAWN goes through `style_of` now.

    Asked of the parsed module rather than of its text, because the text is
    mostly prose about this very field and a substring search reads the
    comments as if they were code.

    Two attribute reads are allowed and they are both inside `style_of`
    itself. `locked` is not a style - it is the record of somebody having
    edited this block - and `render_page` reads it directly for that reason.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(R))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for sub in ast.walk(node):
            named = (isinstance(sub, ast.Attribute)
                     and sub.attr == "layout_override")
            asked = (isinstance(sub, ast.Call)
                     and isinstance(sub.func, ast.Name)
                     and sub.func.id == "getattr"
                     and len(sub.args) > 1
                     and isinstance(sub.args[1], ast.Constant)
                     and sub.args[1].value == "layout_override")
            if named or asked:
                hits.append(node.name)
    # `hand_style` is the third, and it is the exception that proves the rule:
    # its whole job is level 1 ALONE. `style_of` answers "how is this drawn";
    # `hand_style` answers the narrower question that comes up in one place -
    # *did a PERSON say this, or did the measurement?* - which cannot be asked
    # of the ranking, because the ranking has already merged the two.
    # `_hollow_colours` is the caller: hollow may overrule the automatic fill
    # and rim, and may not overrule a hand choice.
    # `_spans_of` is the fourth, and it is not reading a style at all: spans
    # are RANGES of a block that carry their own style, they live in the
    # override because that is where a person's edits live, and there is no
    # measured or automatic answer for `style_of` to rank them against. What
    # each span's style then MEANS still goes through `style_of` - see the
    # spans branch of `render_page`, which merges `ov` with the span's own
    # keys and re-resolves every colour through `colours_for`.
    assert set(hits) <= {"style_of", "hand_style", "render_page",
                         "_spans_of"}, sorted(set(hits))
    assert hits.count("style_of") == 1, hits
