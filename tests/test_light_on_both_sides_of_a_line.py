# -*- coding: utf-8 -*-
"""A letterform that is only a line gets light on both sides of it.

lee, with a white COLLAPSE keylined in black over grey hatching: *"thses type
of sfx shodu also hVE OUTER glow of teh oposite color"* - and then, having
looked at the first version, which put one on every sound effect on the page:
*"the outerglow asked for was for teh traparent text only and it shou be small
and add soen iner glow too"*.

Three corrections in one sentence, and all three were right.

## Transparent text only

The first version asked *is this a sound effect over artwork*, which is a
question about the BOX. The question is about the LETTERS: a letter with a fill
has a fill to hold it off the page, and a letter that is only a line has a few
pixels of ink with the artwork on both sides of them. That is the block that
cannot be read on a busy panel, and it is the only one.

Asked of the drawn colour - a fill with no alpha - rather than of the `hollow`
flag, so a block somebody emptied by hand counts as much as one `inkstyle` read
that way. Both are letters with nothing inside them.

## Small

It went out at 0.07 of the type size at full strength, and the exporter
composites a glow twice because on artwork one pass of a Gaussian is a grey
breath. Full strength twice is not a light, it is a sticker: an opaque band six
pixels wide round every letter, which on a white page merged between the
letters into one slab. It is 0.035 now and 40% alpha, and the exporter
composites an automatic halo ONCE - the alpha is what says which.

## And an inner glow too

On a solid letter "inner" means light falling away from the edge into the body.
On a hollow one there is no body, only a line - so the outer glow lights the
paper outside it and the inner glow lights the hole inside it, and together
they are a soft band with the artist's line running down the middle of it.

## The colour

The opposite of the RIM, not of the fill: on a hollow block `_hollow_colours`
has already moved the ink onto the edge, so the rim IS the letter. A halo in
the rim's own colour is nothing at all.
"""
import os
import re

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import kinds as K, render as R                 # noqa: E402
from mangatl.models import Page, TextRegion                 # noqa: E402
from mangatl.typeset import TypesetConfig, fit_region       # noqa: E402
from where import PKG                                       # noqa: E402


SUBS = [{"key": "sfx_big", "family": "sfx"},
        {"key": "sfx_small", "family": "sfx"},
        {"key": "narration", "family": "bubble"}]

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


@pytest.fixture(autouse=True)
def kinds():
    was = K.known()
    K.use(SUBS)
    yield
    K.use(was)


def _page(kind="sfx_big", ov=None, art=True, hollow=True):
    """One word over hatched artwork, drawn as a line or filled in."""
    img = np.full((240, 720, 3), 150 if art else 252, np.uint8)
    if art:
        img[::3, :] = 90
    r = TextRegion(id=0, bbox=(30, 40, 660, 160),
                   polygon=[[30, 40], [690, 40], [690, 200], [30, 200]],
                   kind=kind, dst_text="COLLAPSE", src_text="x")
    r.text_mask = np.zeros((240, 720), np.uint8)
    r.text_mask[40:200, 30:690] = 255
    if hollow:
        r.layout_measured = {"hollow": True, "fg": "#101010"}
    p = Page(image=img)
    p.regions = [r]
    cfg = TypesetConfig()
    r.layout = fit_region(r, cfg)
    if ov is not None:
        r.layout_override = dict(ov)
    return p, r, cfg


def _differs(a, b):
    return int((np.abs(a.astype(int) - b.astype(int)).max(2) > 8).sum())


# --------------------------------------------------- what it decides

def test_a_letterform_that_is_only_a_line_gets_one():
    got = R.auto_halo(CLEAR, BLACK, 90)
    assert got, "no light on a hollow letterform"
    col, px = got
    assert col[:3] == (255, 255, 255), ("a dark line wants light", col)
    assert 0 < col[3] < 255, ("a halo nobody asked for must not shout", col)
    assert px > 0


def test_a_letter_with_a_fill_gets_nothing():
    """The correction. A fill holds the letters off the page by itself, and a
    halo on every sound effect was a halo lee had not asked for."""
    assert R.auto_halo(WHITE, BLACK, 90) is None
    assert R.auto_halo((10, 10, 10, 255), WHITE, 90) is None


def test_the_colour_is_the_opposite_of_the_LINE():
    """Not of the fill - there is no fill. On a hollow block the rim is the
    letter, so a halo in the rim's colour would be nothing at all."""
    assert R.auto_halo(CLEAR, BLACK, 90)[0][:3] == (255, 255, 255)
    assert R.auto_halo(CLEAR, WHITE, 90)[0][:3] == (0, 0, 0)
    assert R.auto_halo(CLEAR, (20, 30, 40, 255), 90)[0][:3] == (255, 255, 255)


def test_it_is_small():
    """lee: *"it shou be small"*. Both halves of small - how far it reaches,
    and how much of it there is."""
    px = R.auto_halo(CLEAR, BLACK, 160)[1]
    assert px <= 8, ("a cloud, not a light", px)
    assert R.auto_halo(CLEAR, BLACK, 90)[0][3] <= 128


def test_it_grows_with_the_type():
    """A rim does not and a halo does: a rim is a pen and a pen has a width,
    and how much room a word needs round it is proportional to the word."""
    got = {s: R.auto_halo(CLEAR, BLACK, s)[1] for s in (14, 40, 100, 160)}
    sizes = sorted(got)
    assert all(got[a] <= got[b] for a, b in zip(sizes, sizes[1:])), got
    assert got[14] == R.GLOW_MIN, got
    assert got[160] > got[40], got


def test_both_sides_of_the_line_get_the_same_light():
    """One band, two halves. Asked for either side by name so that they can be
    turned off one at a time, and identical when neither has been."""
    a = R.auto_glow_bits(CLEAR, BLACK, 90, {}, "glow")
    b = R.auto_glow_bits(CLEAR, BLACK, 90, {}, "iglow")
    assert a == b, (a, b)


def test_a_glow_somebody_chose_is_left_alone():
    for key, chosen in (("glow", "#ff0000"), ("iglow", "#00ff00")):
        assert R.auto_glow_bits(CLEAR, BLACK, 90, {key: chosen}, key) is None
        # ...and only that one: the other side is still lit.
        other = "iglow" if key == "glow" else "glow"
        assert R.auto_glow_bits(CLEAR, BLACK, 90, {key: chosen}, other)


def test_turning_one_off_is_a_choice_and_is_kept():
    """`NO_FILL` is a colour, so it counts as chosen - which is the whole point
    of the × writing it rather than emptying the field."""
    for key in ("glow", "iglow"):
        assert R.auto_glow_bits(CLEAR, BLACK, 90, {key: R.NO_FILL}, key) is None


def test_a_size_somebody_set_wins():
    got = R.auto_glow_bits(CLEAR, BLACK, 90, {"glow_size": 3}, "glow")
    assert got and got[1] == 3, got
    # ...and zero is a size, not a missing one.
    assert R.auto_glow_bits(CLEAR, BLACK, 90, {"glow_size": 0}, "glow") is None


def test_either_spelling_of_a_colour_is_read():
    """`#rrggbbaa` is how a colour is STORED and `rgba(...)` is how the browser
    is sent one, and a layout that has been through a save carries the second.
    Reading only the first meant the halo the page drew never reached the
    editor - `hex_rgb` said `rgba(0,0,0,0)` was not a colour at all."""
    assert R.any_rgb("rgba(0,0,0,0)") == (0, 0, 0, 0)
    assert R.any_rgb("#00000000") == (0, 0, 0, 0)
    assert R.any_rgb("rgba(255,0,0,1)") == (255, 0, 0, 255)
    assert R.any_rgb("chartreuse") is None
    assert R.auto_halo("rgba(0,0,0,0)", "#101010", 90)


def test_nonsense_does_not_raise():
    for bad in ("wide", [], {}, float("nan")):
        R.auto_glow_bits(CLEAR, BLACK, 90, {"glow_size": bad}, "glow")
    assert R.auto_halo(None, BLACK, 90) is None
    assert R.auto_halo(CLEAR, None, 90) is None


# --------------------------------------------------- on the page

def test_the_light_reaches_the_rendered_page():
    p, _r, cfg = _page()
    with_it = R.render_page(p, cfg)
    p2, _r2, cfg2 = _page(ov={"glow": R.NO_FILL, "iglow": R.NO_FILL,
                              "locked": True})
    without = R.render_page(p2, cfg2)
    assert _differs(with_it, without) > 1500, _differs(with_it, without)


def test_a_filled_block_renders_the_same_either_way():
    """The guard on the other side, and the correction lee asked for: a letter
    with a fill must come out exactly as it did before any of this."""
    p, _r, cfg = _page(hollow=False)
    a = R.render_page(p, cfg)
    p2, _r2, cfg2 = _page(hollow=False,
                          ov={"glow": R.NO_FILL, "iglow": R.NO_FILL,
                              "locked": True})
    b = R.render_page(p2, cfg2)
    assert _differs(a, b) == 0, _differs(a, b)


def test_a_balloon_of_speech_is_untouched():
    p, _r, cfg = _page(kind="bubble", art=False, hollow=False)
    a = R.render_page(p, cfg)
    p2, _r2, cfg2 = _page(kind="bubble", art=False, hollow=False,
                          ov={"glow": R.NO_FILL, "locked": True})
    assert _differs(a, R.render_page(p2, cfg2)) == 0


# --------------------------------------------- and it reaches the EDITOR

def _rec(fg="rgba(0,0,0,0)", edge="#101010", size=90, ov=None):
    return {"id": 1, "kind": "sfx_big", "order": 0, "bbox": [10, 10, 200, 60],
            "layout_override": ov,
            "layout": {"lines": ["COLLAPSE"], "font_size": size,
                       "leading": 1.1, "origins": [[100, 40]],
                       "fg": fg, "edge": edge, "stroke": 4,
                       "font": "", "rotate": 0.0, "frame": [],
                       "fixed": False, "fit_ok": True}}


def _page_state(recs):
    from mangatl.project import PageState
    ps = PageState("p0.png", "p0")
    ps.regions = recs
    return ps


def test_the_boxes_the_browser_is_handed_carry_both_halves():
    """lee: *"i exported the pages and the outer gow works but it just dont
    show in the editor"*. The exporter works its colours out afresh every time
    it draws; the browser has no page to look at and typesets from the layout.

    Filled on the way out of the door rather than at typeset time, so a chapter
    finished last week opens with it instead of needing to be laid out again.
    """
    lay = _page_state([_rec()]).active[0]["layout"]
    assert lay.get("glow", "").startswith("#ffffff"), lay.get("glow")
    assert lay.get("iglow", "").startswith("#ffffff"), lay.get("iglow")
    assert int(lay.get("glow_size") or 0) > 0
    assert int(lay.get("iglow_size") or 0) > 0


def test_a_filled_block_is_handed_nothing():
    lay = _page_state([_rec(fg="#000000")]).active[0]["layout"]
    assert lay.get("glow") == "", lay
    assert lay.get("iglow") == "", lay


def test_a_glow_that_was_chosen_is_left_exactly_as_it_was():
    """`layout` is not only a record of the fit - a save echoes the whole style
    back into it. Clearing it whenever there is no automatic halo threw that
    echo away, and a chosen glow stopped surviving a reload."""
    for chosen in ("#ff0000", R.NO_FILL):
        rec = _rec(ov={"glow": chosen})
        rec["layout"]["glow"] = chosen
        assert _page_state([rec]).active[0]["layout"]["glow"] == chosen


def test_a_stale_halo_is_taken_off_again():
    rec = _rec()
    ps = _page_state([rec])
    assert ps.active[0]["layout"].get("glow")
    rec["layout"]["fg"] = "#000000"            # filled in since
    assert ps.active[0]["layout"].get("glow") == "", ps.active[0]["layout"]


def test_the_preview_endpoint_says_the_same(tmp_path):
    from mangatl import editor
    from mangatl.project import Project
    import shutil

    root = str(tmp_path / "g")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((240, 720, 3), 150, np.uint8)
    img[::3, :] = 90
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "sfx_big", "order": 0,
        "bbox": [30, 40, 660, 160],
        "polygon": [[30, 40], [690, 40], [690, 200], [30, 200]],
        "src_text": "x", "dst_text": "COLLAPSE", "confidence": 0.9,
        "layout_measured": {"hollow": True, "fg": "#101010"}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True

    ans = editor.layout_preview(p, 0, 1, {})
    assert ans.get("glow"), ("no outer light in the preview", ans.get("error"))
    assert ans.get("iglow"), "no inner light in the preview"
    assert float(ans["glow_size"]) > 0 and float(ans["iglow_size"]) > 0
    # ...and both report that nobody chose them, so a save of anything else
    # does not write them down. See `test_a_colour_nobody_chose.py`.
    assert ans["glow_set"] == "" and ans["iglow_set"] == ""


# --------------------------------------------- the × still means off

def test_the_clear_button_writes_a_colour_rather_than_emptying_the_field():
    src = open(os.path.join(str(PKG), "static", "js",
                            "typesetting-edit.js"), encoding="utf-8").read()
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    body = src.split("function clearGlow(id){")[1].split("\n}")[0]
    assert "NO_FILL" in body, body
    m = re.search(r"const CAN_BE_EMPTY = \[([^\]]*)\]", src)
    assert m and "lyGlow" in m.group(1), m and m.group(1)


def test_the_preview_reads_eight_digit_colours():
    """An automatic halo comes back with an alpha under full, and a
    six-digit-only test threw away every glow the page draws for itself."""
    src = open(os.path.join(str(PKG), "static", "js", "typesetting.js"),
               encoding="utf-8").read()
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    for name in ("glOn", "igOn"):
        m = re.search(name + r"\s*=\s*([^;\n]+)", src)
        assert m, name
        assert "{2})?" in m.group(1), (name, m.group(1))
        assert "noInk" in m.group(1), (name, m.group(1))
