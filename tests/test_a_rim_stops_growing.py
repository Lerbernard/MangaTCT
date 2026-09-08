# -*- coding: utf-8 -*-
"""How thick a rim gets, and which way round a balloon is.

## The rim

lee: *"the outlint to text ratio is too nig make it so that taxt over a
certain size get a samller ratio"*, and on which blocks: *"that shoud only
apply for the other sfx"*, *"ot the big ones"*.

`font_size // 7` is not merely too thick, it is the wrong SHAPE, and his own
chapter says so. Every keyline `inkstyle` measured off the writing the artist
drew by hand, by point size::

    144 -> 4    57 -> 4    36 -> 3    19 -> 3    14 -> 4
    134 -> 4    55 -> 4    20 -> 3    18 -> 4    13 -> 3
                48 -> 4               17 -> 4    12 -> 3
                46 -> 4

Three or four pixels from 12pt to 144pt. A twelvefold range of type and one
nib - which is the rule `_measured_width` already states, *a pen has a width*,
and which had never reached the automatic path. At 144pt the old rule asks for
twenty where the artist drew four.

It stays a RATIO rather than becoming the flat 4 those numbers alone suggest,
because a rim is in page pixels: lee's scans are 960 wide, and the same page
at 2000 would want a proportionally thicker line.

## The polarity

lee, with a balloon of black Japanese that came back as white letters on white
paper: *"also can you check what happend heer"*.

`original_tone` infers which way round a balloon is from its NEIGHBOURHOOD -
which population the text box has more of than the balloon around it. That
needs the balloon to be a balloon. The shape attached to `019.jpg` id1 is a
258x292 rectangle with a ragged bite out of one corner, three of its sides the
panel's own edge, most of it hatched artwork. Outside is full of dark, so the
dark class wins outside, so the light class must be the writing: +1, white on
dark, on a bright white balloon.

`inkstyle` measured the same writing at `#020202`.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import kinds as K, render as R                 # noqa: E402
from mangatl.models import TextLayout, TextRegion           # noqa: E402
from mangatl.typeset import (OUTLINE_ON_ART, RIM_KNEE,      # noqa: E402
                             RIM_SLOW)


SUBS = [{"key": "sfx_big", "family": "sfx"},
        {"key": "sfx_small", "family": "sfx"},
        {"key": "narration", "family": "bubble"},
        {"key": "aside", "family": "freefloat"}]


@pytest.fixture
def kinds():
    was = K.known()
    K.use(SUBS)
    yield K
    K.use(was)


def _r(kind="sfx", measured=None):
    return TextRegion(id=1, bbox=[0, 0, 10, 10], kind=kind,
                      layout_measured=measured)


# ----------------------------------------------------------------- the rim

def test_a_sound_effects_rim_stops_growing(kinds):
    got = {s: R.rim_for(_r(), s) for s in (12, 28, 46, 55, 72, 105, 144)}
    assert got[28] == 4, got                 # the knee, where the two agree
    assert got[144] <= 8, ("a rim that still balloons", got)
    # ...and it never goes DOWN as the type goes up.
    sizes = sorted(got)
    assert all(got[a] <= got[b] for a, b in zip(sizes, sizes[1:])), got


def test_it_tracks_what_the_artist_actually_drew(kinds):
    """The measurement is 4 at every size he drew. Two pixels either side of
    that is the whole allowance - it is a rule for pages nobody has measured,
    not a licence to invent a rim."""
    for size in (46, 48, 55, 57):
        assert abs(R.rim_for(_r(), size) - 4) <= 1, size


def test_small_type_is_left_alone(kinds):
    """Below the knee nothing changes: the complaint was about big text."""
    for size in (8, 12, 20, 28):
        assert R.rim_for(_r(), size) == size // 7, size


def test_a_big_sound_is_no_longer_the_exception(kinds):
    """It was: lee's own *"ot the big ones"*, on the reasoning that an impact
    effect is the one place a heavy rim is the drama rather than a mistake. He
    looked at the result and took it back - *"the big sfx shoud also use rim
    now"* - and he is right.

    A big sound is where `size // 7` is at its WORST, precisely because it is a
    ratio: the block with the largest type gets the heaviest keyline, and 144pt
    asks for twenty pixels where this chapter's artist drew four. The exemption
    was a defence of the single case the measurement most flatly contradicts.
    """
    assert R.rim_for(_r("sfx_big"), 144) < 144 // 7
    # ...and it is the SAME rule the other sounds take, not a third one.
    for size in (12, 28, 46, 72, 144):
        assert R.rim_for(_r("sfx_big"), size) == R.rim_for(_r("sfx"), size), size


def test_and_a_measured_big_sound_still_keeps_what_was_measured(kinds):
    """None of this reaches a block somebody has read off the page.
    `_measured_width` runs after `rim_for`, and a big sound takes the whole
    measurement - see `measured_for`."""
    from mangatl.models import TextLayout as TL
    r = _r("sfx_big", {"hollow": True, "rim": 2})
    lay = TL(lines=["x"], font_size=144, leading=1.1, line_origins=[(0, 0)])
    assert R._measured_width(r, lay, 7) == 2


def test_dialogue_keeps_the_old_rule(kinds):
    """*"that shoud only apply for the other sfx"*. And a block inside a
    balloon never reaches here at all - it takes the hairline branch."""
    for kind in ("bubble", "narration", "freefloat", "aside"):
        assert R.rim_for(_r(kind), 144) == 144 // 7, kind


def test_an_unregistered_sub_type_keeps_the_old_rule():
    """The safe direction: with no registry loaded an unknown sub-type reads
    as a bubble, so nothing is thinned that nobody could check."""
    was = K.known()
    try:
        K.use([])
        assert R.rim_for(_r("sfx_small"), 144) == 144 // 7
    finally:
        K.use(was)
    # ...but the family's own default is answered without any registry.
    assert R.rim_for(_r("sfx"), 144) < 144 // 7


def test_the_knee_is_where_the_two_rules_agree():
    """28, not a round number: it is the size at which `size // 7` and the
    measured 4 are the same, so the curve has no step in it."""
    assert RIM_KNEE // 7 == 4
    assert RIM_SLOW > 7, "past the knee it has to grow SLOWER, not faster"


def test_the_floor_still_holds(kinds):
    """`OUTLINE_ON_ART` is the floor and this cannot go under it - a single
    pixel reads as a smudge at page size."""
    from mangatl.models import TextLayout as TL
    img = np.full((80, 200, 3), 255, np.uint8)
    r = _r()
    lay = TL(lines=["x"], font_size=9, leading=1.1, line_origins=[(100, 40)])
    _fg, _edge, w = R._ink_colours(img, r, lay, True, orig=img)
    assert w >= OUTLINE_ON_ART


# ------------------------------------------------------------ the polarity

def _page_and_layout():
    lay = TextLayout(lines=["x"], font_size=25, leading=1.11,
                     line_origins=[(100, 40)])
    return np.full((80, 200, 3), 240, np.uint8), lay


def test_a_measured_dark_ink_withdraws_a_light_on_dark_verdict(monkeypatch):
    """It does not REVERSE it - the background is left to decide, which is
    what gets both of lee's pages right."""
    img, lay = _page_and_layout()
    monkeypatch.setattr(R, "original_tone", lambda *a, **k: 1)
    r = _r("bubble", {"fg": "#020202"})
    fg, edge, _w = R._ink_colours(img, r, lay, False, orig=img)
    assert R._css(fg) == "#000000", "a bright balloon still got white letters"
    assert R._css(edge) == "#ffffff"


def test_a_measured_light_ink_leaves_the_verdict_standing(monkeypatch):
    """The case `original_tone` exists for: a balloon of hatching whose
    average is nowhere near black, carrying white typesetting."""
    img, lay = _page_and_layout()
    monkeypatch.setattr(R, "original_tone", lambda *a, **k: 1)
    r = _r("bubble", {"fg": "#f2f2f2"})
    fg, _edge, _w = R._ink_colours(img, r, lay, False, orig=img)
    assert R._css(fg) == "#ffffff"


def test_nothing_measured_changes_nothing(monkeypatch):
    img, lay = _page_and_layout()
    monkeypatch.setattr(R, "original_tone", lambda *a, **k: 1)
    fg, _edge, _w = R._ink_colours(img, _r("bubble"), lay, False, orig=img)
    assert R._css(fg) == "#ffffff"


def test_a_dark_background_still_wins(monkeypatch):
    """*"a decidedly dark background always gets white typesetting with a
    black edge - the one thing lee has asked for every time this has come
    up."* The black balloon on 009, where the measurement is the one that is
    wrong."""
    img = np.full((80, 200, 3), 12, np.uint8)
    lay = TextLayout(lines=["x"], font_size=25, leading=1.11,
                     line_origins=[(100, 40)])
    monkeypatch.setattr(R, "original_tone", lambda *a, **k: 1)
    r = _r("bubble", {"fg": "#020202"})
    fg, _edge, _w = R._ink_colours(img, r, lay, False, orig=img)
    assert R._css(fg) == "#ffffff"


def test_it_is_read_off_the_measurement_and_not_off_the_style():
    """A bubble may not take a measured COLOUR - lee's rule - and this is not
    a colour: it is never drawn, it only says which way round the page is."""
    r = _r("bubble", {"fg": "#020202"})
    assert R.measured_for(r) == {}, "the scoping changed"
    assert R._measured_ink_is_dark(r) is True


# ------------------------------------- the three lee sent, all at once

def _at(bg, measured, halo, tone, monkeypatch, kind="sfx"):
    img = np.full((80, 200, 3), bg, np.uint8)
    lay = TextLayout(lines=["x"], font_size=25, leading=1.11,
                     line_origins=[(100, 40)])
    monkeypatch.setattr(R, "original_tone", lambda *a, **k: tone)
    r = TextRegion(id=1, bbox=[0, 0, 10, 10], kind=kind,
                   layout_measured=measured)
    fg, edge, _w = R._ink_colours(img, r, lay, halo, orig=img)
    return R._css(fg), R._css(edge)


def test_white_writing_comes_back_white(monkeypatch):
    """lee, with the TURN effect: *"can you look into the turn sfx thare are
    some sfx that are invernetd color"*. `クルッ` is drawn in WHITE with a fine
    black keyline over a dark garment and came back BLACK on white.

    Nothing was wrong with the arithmetic. An effect's box is a rectangle
    round writing that LEANS across artwork, so it takes in a great deal that
    is not the writing - a bright sleeve and a lit background as well as the
    dark cloth the strokes sit on. The neighbourhood test answered for the
    BOX, which is mostly light. The glyph pixels were not guessing."""
    assert _at(240, {"fg": "#f4f4f4"}, True, 0, monkeypatch) \
        == ("#ffffff", "#000000")


def test_black_writing_on_dark_art_comes_back_black(monkeypatch):
    """lee: *"fleinck to and a few more and teh freefloat text too"*. `ビクッ`
    is black with a fine white keyline over a grey cloak, and the loose
    narration the same over dark screentone; both came back white on black.

    *"A decidedly dark background always gets white typesetting"* was right
    about balloons and overreaching on artwork. Black letters on dark art are
    unreadable WITH NOTHING ROUND THEM, and on artwork there is always
    something round them - which is exactly how the original is drawn."""
    assert _at(12, {"fg": "#101010"}, True, 1, monkeypatch) \
        == ("#000000", "#ffffff")
    assert _at(12, {"fg": "#0a0a0a"}, True, 0, monkeypatch) \
        == ("#000000", "#ffffff")


def test_but_a_black_balloon_still_gets_white(monkeypatch):
    """Page 009, and the reason the override is scoped to `needs_halo`. Inside
    a balloon the edge is a hairline that holds nothing off anything, so black
    on black is black on black."""
    assert _at(12, {"fg": "#020202"}, False, 1, monkeypatch) \
        == ("#ffffff", "#000000")


def test_and_with_nothing_measured_the_background_still_decides(monkeypatch):
    """Every page that has not been through `measure_page` is untouched by any
    of this."""
    assert _at(12, None, True, 0, monkeypatch) == ("#ffffff", "#000000")
    assert _at(240, None, True, 0, monkeypatch) == ("#000000", "#ffffff")


def test_a_mid_grey_measurement_asserts_nothing(monkeypatch):
    """The light test ASSERTS a verdict where the dark test only withdraws
    one, so it is held to a stricter bar. A grey ink says nothing about which
    way round the page is, and is not allowed to speak."""
    assert R._measured_ink_is_light(
        TextRegion(id=1, bbox=[0, 0, 9, 9], layout_measured={"fg": "#9a9a9a"})) \
        is False
    assert _at(240, {"fg": "#9a9a9a"}, True, 0, monkeypatch) \
        == ("#000000", "#ffffff")
