"""The faces this app is allowed to hand to other people, and what each box
gets when nobody has said otherwise.

lee, after a report on what manga is typeset in: *"ok put all the fonts thatare
safe to put in the app for shipping and make the deafualt boxes use tehm"*.

## What went, and why

Two of the fonts in `fonts/` could not be redistributed, and they were the two
the app reached for first.

* **`CCWildWords.ttf`** - Comicraft's Wild Words. A paid font, $49 a style and
  $139 for the family. Its desktop licence forbids app integration and sharing
  outright; embedding in software is a separate, dearer licence sold by quote.
* **`AnimeAce.ttf`** and its Bold and Italic - Blambot's Anime Ace. Free to
  USE, including for work that earns, and the default face of most of
  scanlation. But Blambot prohibits redistribution under every free licence.
  Their paid **Embedding** licence covers software the end user cannot extract
  the font from, which a `.ttf` in a folder plainly is not; the tier that would
  apply is **Redistributive**, quote-only.
* **`Komika.ttf`** went for a different reason: widely described as free for
  commercial use, with no authoritative statement of its REDISTRIBUTION terms
  anywhere and a foundry long defunct. An unverifiable licence is not a
  licence.

Everything left is under the SIL Open Font License, which permits
redistribution inside software. `fonts/LICENSES.md` names each file.

Nothing is lost that we ever had: `_font_dirs()` searches the person's OWN
uploaded fonts before the bundled ones, and `default_font_path()` still names
Wild Words and Anime Ace first - so anybody who has licensed either gets it
back by adding it, and the app looks exactly as it did.

## And the defaults

`DEFAULT_FONTS` gives each kind a face rather than setting every box in one.
The choices follow professional practice as far as an open face can reach it:
speech in a comic face that HAS a true italic and bold, so thoughts and
whispers are the same face rather than a different one; asides in a
handwriting face; effects in a heavy display face.

`shout` was Comic Neue Bold, on the argument that a shout is the speech face
set larger. lee: *"use a more agressive forny for shouting"* - and rendered
beside the alternatives that argument does not survive: the bold of a light
comic face is the speech face a little darker. It is Luckiest Guy now, the
heaviest face in the folder. Two faces were considered and rejected, and the
test below pins both refusals: Bangers, because it is the SOUND EFFECT face and
a shout drawn in it stops reading as speech, and Anton, because a condensed
grotesque reads as a headline rather than a voice.

EVERY kind has an entry, including the ones whose answer repeats their
family's. Three were left to inherit at first, which was defensible in the code
and wrong on the screen - lee, looking at the Box Types panel: *"add a font for
all of these, these are the default ones"*, *"they dont all have to be
difrent"*. A person reading twelve rows wants twelve answers; a blank reads as
an oversight where a repeat reads as a decision.

The inheritance itself is still there and still matters, for the sub-types a
PERSON adds, which cannot be in the table.
"""
import os
import pathlib

import numpy as np
import pytest

from mangatl import typeset as T
from where import PKG

FONTS = PKG / "fonts"

# Every face that may be redistributed inside this app, by file.
SHIPPED = {
    "Anton-Regular.ttf", "Bangers-Regular.ttf", "Chewy-Regular.ttf",
    "ComicNeue-Bold.ttf", "ComicNeue-BoldItalic.ttf", "ComicNeue-Italic.ttf",
    "ComicNeue-Regular.ttf", "Gaegu-Bold.ttf", "Gaegu-Regular.ttf",
    "GochiHand-Regular.ttf", "Jua-Regular.ttf", "Kalam-Bold.ttf",
    "Kalam-Regular.ttf", "LuckiestGuy-Regular.ttf",
    "NanumPenScript-Regular.ttf", "PatrickHand-Regular.ttf",
}

# ...and the ones that may not, by name, so putting one back goes red.
FORBIDDEN = {
    "CCWildWords.ttf": "Comicraft, paid; desktop licence forbids app use",
    "AnimeAce.ttf": "Blambot; free to use, redistribution prohibited",
    "AnimeAce-Bold.ttf": "Blambot; free to use, redistribution prohibited",
    "AnimeAce-Italic.ttf": "Blambot; free to use, redistribution prohibited",
    "Komika.ttf": "Apostrophic Labs; redistribution terms unverifiable",
}


# ----------------------------------------------------------- what is in there

def test_nothing_in_the_fonts_folder_is_one_we_may_not_hand_on():
    here = {p.name for p in FONTS.iterdir() if p.suffix.lower() in
            (".ttf", ".otf")}
    bad = sorted(here & set(FORBIDDEN))
    assert not bad, "\n".join("%s - %s" % (n, FORBIDDEN[n]) for n in bad)


def test_and_the_ones_that_are_there_are_the_ones_we_meant():
    here = {p.name for p in FONTS.iterdir() if p.suffix.lower() in
            (".ttf", ".otf")}
    assert here == SHIPPED, (sorted(here - SHIPPED), sorted(SHIPPED - here))


def test_every_shipped_face_can_actually_be_typeset_with():
    """Shipping a file that cannot draw is a menu entry that produces an empty
    balloon."""
    for name in sorted(SHIPPED):
        p = str(FONTS / name)
        assert T.usable_font(p), name
        assert T.can_typeset(p), name


def test_the_folder_says_where_each_of_them_came_from():
    """A licence nobody wrote down is one nobody can check. The next person to
    add a face needs to see the question being asked."""
    lic = FONTS / "LICENSES.md"
    assert lic.exists(), "fonts/LICENSES.md is missing"
    text = lic.read_text(encoding="utf-8")
    for name in sorted(SHIPPED):
        stem = name.split("-")[0]
        assert stem in text, name
    for name in FORBIDDEN:
        assert name in text, "%s left without saying why" % name


# ------------------------------------------------------------- what they get

def _cfg(font=""):
    return T.TypesetConfig(font_path=font)


@pytest.mark.parametrize("kind,face", [
    ("bubble",         "ComicNeue-Bold"),
    ("thought",        "ComicNeue-Italic"),
    ("whisper",        "ComicNeue-Regular"),
    ("narration",      "ComicNeue-Regular"),
    ("freefloat",      "ComicNeue-Regular"),
    ("narration_free", "ComicNeue-Regular"),
    # Comic Neue since 2026-08-28. lee, with the Box types panel in
    # front of him: *"make thses teh defualts"*, and the Aside row on
    # it reads Comic Neue Regular.
    ("aside",          "ComicNeue-Regular"),
    ("sign",           "ComicNeue-Regular"),
    # Chewy since 2026-08-28. lee: *"the shoudt we have bnow is too
    # agressive can yu find something in getween those too"* - between
    # Luckiest Guy and Comic Neue Bold, and Chewy is that middle.
    ("shout",          "Bangers-Regular"),
    ("sfx",            "Bangers-Regular"),
    ("sfx_big",        "Bangers-Regular"),
    ("sfx_small",      "Kalam-Regular"),
])
def test_each_kind_gets_its_own_face_out_of_the_box(kind, face):
    got = os.path.basename(T.font_for(_cfg(), kind))
    assert got.startswith(face), (kind, got)


# --------------------------------------------------------- and one that shouts

def _ink(face, word="SHOUT", size=80):
    """How much of the word's own bounding box is ink, at a fixed size.

    A weight measurement that does not depend on the font's declared style
    name, which nothing enforces. Rasterise, crop to the ink, take the black
    fraction. Comic Neue Bold is 0.35 by this measure and Luckiest Guy 0.64.
    """
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(str(FONTS / face), size)
    im = Image.new("L", (900, 240), 255)
    ImageDraw.Draw(im).text((20, 20), word, font=f, fill=0)
    a = np.array(im)
    ys, xs = np.where(a < 128)
    return float((a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] < 128).mean())


def test_a_shout_is_between_the_two_faces_lee_named():
    """It was *"use a more agressive forny for shouting"* and a bar of one and
    a half times the speech face's ink. He withdrew that: *"the shoudt we have
    bnow is too agressive can yu find something in getween those too"* -
    between Luckiest Guy and Comic Neue Bold - and then, having seen the whole
    folder side by side, *"use jua bold isnstad"*.

    So the requirement is literally an INTERVAL now, and the old bar is inside
    the half of it that has been ruled out: Luckiest Guy is 1.81 times the
    speech face and 1.5 is nearer to that than to anything he would call
    restrained.

    Ink over the word's own bounding box, at a fixed size - a measurement that
    does not trust the file name, since a face called Bold is only bold
    because somebody typed it into the name table::

        Comic Neue Regular  0.232   0.65x
        Comic Neue Bold     0.354   1.00x   the speech face, the quiet end
        Gochi Hand          0.367   1.04x
        Jua                 0.440   1.24x   here
        Chewy               0.552   1.56x
        Bangers             0.596   1.68x   the sound effect face
        Luckiest Guy        0.642   1.81x   the loud end, withdrawn
        Anton               0.659   1.86x   the signage face

    A shout is announced by the BURST it sits in before it is read, so the
    face only has to sound raised. A fifth heavier and full width with the
    speech face is the same voice louder; the loud end is a different kind of
    page.
    """
    speech = _ink(T.DEFAULT_FONTS["bubble"])
    shout = _ink(T.DEFAULT_FONTS["shout"])
    assert shout > speech * 1.15, ("a shout has to look raised", shout, speech)
    assert shout < _ink("LuckiestGuy-Regular.ttf"), \
        ("still as heavy as the one he called too aggressive", shout)


def test_the_shout_face_is_the_sound_effect_face_on_purpose():
    """It used to be forbidden, and the reason was good: *"then a character
    shouting and a door slamming are drawn identically, and the page loses the
    one distinction typesetting exists to carry"*. It is why Bangers was
    refused when Chewy and then Jua were chosen over it.

    lee chose it anyway, with that cost in front of him and the whole folder
    set side by side: *"acculy use bangers tregulat for shout boxes"*. His
    app, his call - a preference is not a defect - so this records the
    decision instead of guarding against it.

    What is left telling a reader which is which is the BURST drawn round the
    one of them, and that is a real distinction: it is drawn by the artist
    rather than chosen by us.

    Kept as a test rather than as a comment so that whoever next reads
    `DEFAULT_FONTS` and takes this for an oversight finds the answer before
    changing it.
    """
    assert T.DEFAULT_FONTS["shout"] == T.DEFAULT_FONTS["sfx"]
    # ...and it is still not the SPEECH face, which is the distinction whose
    # loss would leave the type saying nothing at all.
    assert T.DEFAULT_FONTS["shout"] != T.DEFAULT_FONTS["bubble"]


def test_the_shout_face_is_one_we_may_ship():
    """Said out loud because the aggressive faces are exactly the ones with the
    licence problem - the whole reason the two best answers left this folder."""
    assert T.DEFAULT_FONTS["shout"] in SHIPPED
    assert T.DEFAULT_FONTS["shout"] not in FORBIDDEN


def test_every_row_of_the_box_types_panel_has_a_face():
    """No blanks. The panel lists one row per preloaded kind, and lee is
    reading it as a list of defaults - a row with nothing in it is a question,
    not an answer."""
    from mangatl import kinds as K
    missing = [k for k in K.PRELOAD_KEYS if k not in T.DEFAULT_FONTS]
    assert not missing, missing
    for k in K.PRELOAD_KEYS:
        got = T.font_for(_cfg(), k)
        assert got and T.usable_font(got), (k, got)


def test_a_kind_somebody_added_themselves_takes_its_family_s_face():
    """The inheritance is still load-bearing, just not for the shipped kinds
    any more: a sub-type a person invents cannot be in `DEFAULT_FONTS`, and it
    should be typeset in its family's face rather than dropping to the project
    default - which on a page of effects is a different face again.

    This also pins the thing that broke first. `kinds.family_of` answers from
    the PROJECT's sub-type settings, so it needs to be told about the sub-type
    for the family step to work at all.
    """
    was = T._kinds.known()
    T._kinds.use([{"key": "yelling", "family": "sfx", "label": "Yelling"}])
    try:
        assert T._kinds.family_of("yelling") == "sfx"
        # Nothing set anywhere: it lands on the SFX default, not the speech one.
        assert os.path.basename(T.font_for(_cfg(), "yelling")) == \
            "Bangers-Regular.ttf"
        # ...and a face chosen for the family reaches it too.
        loud = str(FONTS / "LuckiestGuy-Regular.ttf")
        cfg = T.TypesetConfig(font_path="", fonts={"sfx": loud})
        assert T.font_for(cfg, "yelling") == loud
    finally:
        T._kinds.use(was)


def test_the_app_registers_a_project_s_sub_types_when_it_opens_one():
    """The test above works because `kinds.use()` has been called, and the
    reason that is fair is that the app does it - on load, on save, and when
    the sub-types are edited.

    Written down because the first version of the test above did NOT call it,
    found that a made-up sub-type came back as "bubble", and concluded there
    was a gap in `font_for`. There is no gap. `family_of` reads the open
    project's sub-types from a module global, and every path that opens or
    changes a project fills it in.
    """
    import pathlib as _pl
    for mod in ("project.py", "editor.py"):
        src = (PKG / mod).read_text(encoding="utf-8")
        assert "_kinds.use(" in src, mod


def test_a_project_that_chose_a_face_keeps_it_everywhere():
    """`DEFAULT_FONTS` sits after the project's own font, not before it. A
    person who picked one face for their whole chapter picked it for the sound
    effects too, and having the app overrule that would be worse than a plain
    default."""
    mine = str(FONTS / "Chewy-Regular.ttf")
    cfg = _cfg(mine)
    for kind in ("bubble", "sfx", "aside", "thought"):
        assert T.font_for(cfg, kind) == mine, kind


def test_a_face_that_is_no_longer_there_falls_through_to_one_that_is():
    """The case this had to survive: a saved project naming
    `...\\fonts\\AnimeAce.ttf`, which is exactly what lee's does, on the day
    that file stops existing. A dead path must never reach the renderer - a
    block set in a font that cannot be opened draws nothing at all, which is
    the one outcome worse than the wrong face."""
    gone = str(FONTS / "AnimeAce.ttf")
    assert not os.path.exists(gone), "fixture assumes the file is gone"
    cfg = T.TypesetConfig(font_path=gone,
                          fonts={"sfx": str(FONTS / "CCWildWords.ttf"),
                                 "freefloat": gone})
    for kind in ("bubble", "sfx", "freefloat", "aside"):
        got = T.font_for(cfg, kind)
        assert got and T.usable_font(got), (kind, got)


def test_and_a_licensed_copy_still_wins_when_somebody_has_one():
    """The arrangement that costs nothing: the preference list still names Wild
    Words and Anime Ace FIRST, and `_font_dirs()` looks in the person's own
    uploaded folder before the bundled one. Anybody who has bought either gets
    the app they had."""
    import inspect
    src = inspect.getsource(T.default_font_path)
    assert "CCWildWords.ttf" in src and "AnimeAce.ttf" in src, \
        "a licensed copy would no longer be picked up"
    dirs = T._font_dirs()
    from mangatl.userdata import fonts_dir
    assert os.path.abspath(fonts_dir()) == dirs[0], \
        "the bundled folder is searched before the person's own"
