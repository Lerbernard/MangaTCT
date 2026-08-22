"""Three main box types, and sub-types under them.

lee: *"revamp the box type, there need to be 3 main box type, boubble box,
outide box and sfx box, they need to have sub categories, so ttought boubles
shoud be a sub category of the the bubble type same as anfry bubbles ... each
bubble shoud have a default that is regualt speach for bubble, outiuside text
or free floating box and sound effect for the shoud efct box"*.

Before this there were six flat types in one menu - speech, open typesetting,
SFX, caption, thought, burst - in six unrelated colours, with up to ten more
that could be added anywhere in the same list. Nothing said that a thought
balloon and a burst are both BALLOONS, and the colours actively said they were
not: thought was blue and burst was pink.

What this file pins:

* the three families, and that every kind belongs to exactly one;
* each family's default sub-type, which cannot be removed, and whose key is
  the family's own name - so every box already on disk still reads;
* ten more per family, which is the ceiling lee asked for after seeing five;
* colour lives on the SUB-TYPE and never leaves its family;
* Find text only ever produces the three defaults;
* the browser and the exported box sheet draw them in the same colours.

The behaviour that used to be attached to a built-in type still is, because
those types are sub-types now with the same keys: a burst is still set larger,
and a box that has no balloon still has none.
"""
import numpy as np
import pytest

from mangatl import kinds as K
from mangatl import render, typeset
from mangatl.models import TextRegion
from mangatl.project import KIND_GROUPS, group_of
from where import PKG

cv2 = pytest.importorskip("cv2")

FAMILIES = ("bubble", "freefloat", "sfx")


@pytest.fixture(autouse=True)
def _fresh():
    """Every test gets the sub-types a new project starts with, and none of
    them leaves its own list behind for the next one."""
    was = K.known()
    K.use(K.migrate([], seed=True))
    yield
    K.use(was)


# ------------------------------------------------------------ the three

def test_there_are_three_main_types():
    assert K.FAMILIES == FAMILIES
    assert typeset.KINDS == FAMILIES
    assert tuple(KIND_GROUPS) == FAMILIES


def test_each_one_has_a_default_that_is_its_own_key():
    """The default's key IS the family's name. That is not tidiness: it is why
    every box already stored on disk still reads, and why a project made
    before families existed needs nothing rewritten."""
    for f in FAMILIES:
        assert K.is_family(f)
        assert K.family_of(f) == f
        assert K.kind_label(f) == K.DEFAULT_LABELS[f]
    assert K.DEFAULT_LABELS["bubble"] == "Regular speech"


def test_every_kind_belongs_to_exactly_one_family():
    subs = K.known()
    for s in subs:
        assert K.family_of(s["key"]) in FAMILIES
    for f in FAMILIES:
        mine = {s["key"] for s in K.subs_of(f)}
        for g in FAMILIES:
            if g != f:
                assert not (mine & {s["key"] for s in K.subs_of(g)})


def test_a_kind_nobody_recognises_is_a_balloon():
    """A box pointing at a sub-type that has since been deleted still has to
    draw, still has to be cleaned and still has to obey the switch that puts
    its family away. Balloon is where being wrong costs least."""
    assert K.family_of("ck_gone_for_ever") == "bubble"
    assert group_of("") == "bubble"


# ------------------------------------------------------------ how many

def test_ten_of_your_own_per_family():
    """lee asked for five, then for ten: *"incrrase teh limiti to 10 cunstum
    bubble"*."""
    assert K.SUBS_PER_FAMILY == 10
    over = [{"key": f"k{i}", "label": f"K{i}", "family": "bubble"}
            for i in range(30)]
    got = K.migrate(over)
    for f in FAMILIES:
        assert len(K.subs_of(f, got)) <= K.SUBS_PER_FAMILY


def test_a_project_starts_with_some_already_made():
    """lee: *"add some preloaded custom bubble type"*. Three empty families
    means naming everything yourself before you can label anything."""
    for f in FAMILIES:
        assert K.subs_of(f), f
    labels = {s["label"] for s in K.known()}
    assert "Thought bubble" in labels
    assert "Whisper" in labels
    # ...and only the nine lee asked for: *"only these should be default"*.
    assert "Angry" not in labels
    assert len(K.PRELOAD_KEYS) == 9


def test_narration_is_in_two_families_and_they_are_two_things():
    """lee: *"naration type shiude be in both bubble and outside box as a pre
    loaded custum"*.

    A caption in a ruled box is a balloon - a closed shape with writing in it,
    cleaned and typeset like one. Narration lying straight on the artwork has
    no shape at all. Same voice, different piece of drawing, and it is the
    drawing that decides how the box behaves.
    """
    bub = {s["key"] for s in K.subs_of("bubble")}
    free = {s["key"] for s in K.subs_of("freefloat")}
    assert "narration" in bub
    assert any(k.startswith("narration") for k in free), free
    # ...and the two really do behave differently
    from mangatl.project import _no_balloon
    caption = "narration"
    on_art = next(k for k in free if k.startswith("narration"))
    assert not _no_balloon(caption)
    assert _no_balloon(on_art)


def test_the_types_that_were_built_in_keep_their_keys():
    """A page already labelled `thought` must still say Thought bubble."""
    have = {s["key"]: s for s in K.known()}
    for key in ("narration", "thought", "shout"):
        assert key in have, key
        assert K.family_of(key) == "bubble"


# ------------------------------------------------------------ the colours

def test_a_family_has_no_colour_of_its_own_its_default_carries_it():
    """lee: *"the main catheory shou not have a color but the defaut shoud
    have the color"*. The family key and its default's key are the same
    string, so this is the same statement twice - which is the point."""
    for f in FAMILIES:
        assert K.kind_colour(f) == K.FAMILY_COLOUR[f]


def test_a_sub_type_can_only_be_a_shade_of_its_own_family():
    """lee: *"only allow color with a color family for teh 5 user craeted
    boxex"*. A free colour picker made a green balloon possible, and then the
    colour on the page says the wrong family."""
    for f in FAMILIES:
        shades = K.family_shades(f)
        assert len(shades) == K.SUBS_PER_FAMILY
        for s in K.subs_of(f):
            assert s["color"] in shades, (f, s)


def test_a_colour_from_before_the_families_is_not_drawn():
    """An old project's sub-type could be any hue at all. Drawing it in that
    colour is a box that lies about which family it is in, so it is given one
    of its own family's shades instead."""
    got = K.migrate([{"key": "ck_x", "label": "X", "family": "sfx",
                      "color": "#00ff00"}])
    assert got[0]["color"] in K.family_shades("sfx")
    K.use(got)
    assert K.kind_colour("ck_x") in K.family_shades("sfx")


def test_no_two_sub_types_of_one_family_share_a_colour():
    for f in FAMILIES:
        cols = [s["color"] for s in K.subs_of(f)]
        assert len(set(cols)) == len(cols), (f, cols)


def test_every_colour_in_a_family_can_be_told_from_every_other():
    """Including the default. Ten shades of one exact hue differ only in how
    light they are, and the middle six of those are the same colour as far as
    a thin box outline on a page is concerned. lee: *"mak teh colors different
    eniught so its notivcelble of the subtypes"*."""
    def rgb(c):
        return [int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]

    for f in FAMILIES:
        cols = [K.FAMILY_COLOUR[f]] + K.family_shades(f)
        worst = min(sum((a - b) ** 2 for a, b in zip(rgb(x), rgb(y))) ** 0.5
                    for i, x in enumerate(cols) for y in cols[i + 1:])
        assert worst > 0.12, (f, round(worst, 3))


def test_the_families_never_reach_into_each_other():
    """Whatever spread a family is given, no colour of one may be mistakable
    for a colour of another - that is the whole reason the colour is worth
    looking at."""
    def rgb(c):
        return [int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]

    groups = {f: [K.FAMILY_COLOUR[f]] + K.family_shades(f) for f in FAMILIES}
    for a in FAMILIES:
        for b in FAMILIES:
            if a >= b:
                continue
            worst = min(sum((x - y) ** 2 for x, y in zip(rgb(p), rgb(q))) ** 0.5
                        for p in groups[a] for q in groups[b])
            assert worst > 0.12, (a, b, round(worst, 3))


def test_the_editor_draws_them_in_the_same_colours():
    """The page in the browser and the exported box sheet are two drawings of
    one thing. Different colours in each is worse than no colour at all."""
    import json
    import re
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "frames.js").read_text(encoding="utf8")
    block = re.search(r"const KIND_COLORS=\{(.*?)\};", js, re.S).group(1)
    got = dict(re.findall(r"(\w+):'(#\w{6})'", block))
    assert got == {f: K.FAMILY_COLOUR[f] for f in FAMILIES}

    shades = re.search(r"const FAMILY_SHADES=\{(.*?)\n\};", js, re.S).group(1)
    for f in FAMILIES:
        row = re.search(rf"{f}:\[(.*?)\],", shades, re.S).group(1)
        assert re.findall(r"'(#\w{6})'", row) == K.family_shades(f), f
    n = re.search(r"const SUBS_PER_FAMILY=(\d+)", js).group(1)
    assert int(n) == K.SUBS_PER_FAMILY


# ------------------------------------------------------- what Find text says

def test_find_text_only_ever_produces_the_three_defaults():
    """lee: *"teh find text shoud only use teh 3 defasut boxes"*. A detector
    can measure that something is a closed shape with writing in it; it cannot
    know that this one is a thought and that one is angry."""
    for said in ("bubble", "freefloat", "sfx", "narration", "anything"):
        assert K.detected_kind(said) in FAMILIES
    assert K.detected_kind("narration") == "bubble"


def test_the_find_text_ticks_are_about_families():
    """Three ticks in the dialog, three families - and a box answers to the
    tick for the family it is in, however finely it has been labelled since."""
    from mangatl.project import only_kinds

    def _r(kind):
        return TextRegion(id=0, bbox=(10, 10, 30, 30), kind=kind)

    caption, aside, boom = _r("narration"), _r("aside"), _r("sfx_big")
    assert only_kinds([caption, aside, boom], ["bubble"]) == [caption]
    assert only_kinds([caption, aside, boom], ["freefloat"]) == [aside]
    assert only_kinds([caption, aside, boom], ["sfx"]) == [boom]
    assert only_kinds([caption, aside, boom], []) == [caption, aside, boom]


# ------------------------------------------------ what each family does

def test_the_two_families_that_have_no_balloon_still_have_none():
    """The one distinction that changes the geometry, and the only one - and
    it is decided by the FAMILY, never by the sub-type."""
    from mangatl.project import NO_BALLOON_KINDS, _no_balloon
    assert set(NO_BALLOON_KINDS) == {"freefloat", "sfx"}
    assert not _no_balloon("bubble")
    assert not _no_balloon("thought")        # a sub-type of balloon
    assert _no_balloon("sfx_big")            # ...and one of sound effect
    assert _no_balloon("sign")               # ...and one of outside text


def _region(kind, w=400, h=300, text="HELLO"):
    r = TextRegion(id=1, bbox=(20, 20, w, h), kind=kind)
    r.dst_text = text
    mask = np.zeros((h + 60, w + 60), np.uint8)
    cv2.ellipse(mask, (20 + w // 2, 20 + h // 2), (w // 2, h // 2),
                0, 0, 360, 255, -1)
    r.bubble_mask = mask
    r.text_mask = mask
    return r


def _cfg():
    return typeset.TypesetConfig(font_path=typeset.default_font_path(),
                                 min_font=10, max_font=40)


def _size(kind, cfg, **kw):
    return typeset.fit_region(_region(kind, **kw), cfg).font_size


def test_a_burst_is_still_set_larger_than_speech():
    """The size a type is set at hangs off the SUB-TYPE, not the family: it is
    a burst that is shouted, and a burst is one kind of balloon among
    several."""
    cfg = _cfg()
    assert _size("shout", cfg) > _size("bubble", cfg)


@pytest.mark.parametrize("kind", ["thought", "narration"])
def test_the_rest_are_set_at_normal_size(kind):
    """Told apart by the FACE, not the size - which is what a sub-type's own
    font is for, and what a typesetter does."""
    cfg = _cfg()
    assert _size(kind, cfg) == _size("bubble", cfg)


def test_a_burst_still_fits_its_balloon():
    """A bigger ceiling is permission, not an instruction."""
    cfg = _cfg()
    text = "THIS IS A LINE OF DIALOGUE THAT HAS TO FIT"
    tight = typeset.fit_region(_region("shout", w=260, h=170, text=text), cfg)
    assert tight.fit_ok, "the shout was allowed to overflow"
    assert tight.font_size == typeset.fit_region(
        _region("bubble", w=260, h=170, text=text), cfg).font_size


# ------------------------------------------------------------ in the editor

def test_each_main_type_has_its_own_font_row():
    """Three rows, one per family. A sub-type's face is set beside it under
    Box types and travels on its own record - it is part of what that sub-type
    is, not a setting off in another section."""
    from pathlib import Path
    html = (PKG / "static"
            / "editor.html").read_text(encoding="utf8")
    for f in FAMILIES:
        want = 'id="font"' if f == "bubble" else f'id="font_{f}"'
        assert want in html, f
    # ...and the sub-types no longer have one
    for gone in ("font_narration", "font_thought", "font_shout"):
        assert f'id="{gone}"' not in html, gone


def test_the_names_on_screen_are_the_ones_in_the_guides():
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "frames.js").read_text(encoding="utf8")
    for word in ("Bubble text", "Freefloat text", "Sound effect",
                 "Regular speech"):
        assert word in js, word


def test_the_type_is_named_once():
    """Two tables of labels in two files is two of them going stale."""
    from pathlib import Path
    root = PKG / "static" / "js"
    say = [f.name for f in root.glob("*.js")
           if "function kindLabel(" in f.read_text(encoding="utf8")]
    assert say == ["panels.js"], say


def test_one_two_and_three_are_the_three_main_types():
    """lee: *"the 1,2,3 shodu be the deahut shortcuts with teh defaut
    bubble"*. They are the only keys that mean the same thing on every page of
    every project, which is what makes them worth learning.

    4 upwards used to be the sub-types of the family the box was already in,
    and are now nothing at all: the same key did a different thing depending on
    what was selected, and nothing on screen numbered them. lee: *"only 1,2,3
    shud work to swith box types"*. Sub-types are still a menu away, written
    out. See `test_box_type_families.py`."""
    from pathlib import Path
    root = PKG / "static" / "js"
    ops = (root / "region-ops.js").read_text(encoding="utf8")
    assert "return (n >= 1 && n <= 3) ? KIND_FAMILIES[n - 1] : null;" in ops
    assert "subsOf(familyOf(" not in ops, \
        "picking a sub-type by key number is gone"
    panels = (root / "panels.js").read_text(encoding="utf8")
    assert "const KIND_ORDER = KIND_FAMILIES;" in panels


def test_the_panel_offers_a_main_type_and_a_sub_type():
    """lee: *"add a nothet drop down for the subcategories in the Text on this
    page tab"*."""
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "panels.js").read_text(encoding="utf8")
    assert "function kindSelects(" in js
    assert "<label>Main type</label>" in js
    assert "<label>Sub-type</label>" in js
    # ...and both places that used to have one flat Kind menu use it
    assert js.count("${kindSelects(") == 2


# ------------------------------------------------------------- linked pairs

@pytest.mark.parametrize("group", [1, 2, 3, 7, 40])
def test_every_link_is_the_same_colour(group):
    assert render.link_colour(group) == render.LINK_COLOUR
