"""Sound effects come out bare.

lee: *"make it so that sfx never have these * on the bdeginning and end"* — with
a picture of a page typeset `*TURN*`.

The asterisks were not an accident and they were not the typesetter's. The
system prompt taught them: the rule about wordless bubbles gave `"*inhale*"`,
`"*pant* *pant*"`, `"*sniff*"` and `"*wheeze*"` as the examples to follow, and
the model followed them onto sound effects too. Wrapping a word in asterisks is
a CHAT convention for "this is a sound, not speech". No typesetter draws it.

So both ends are dealt with. The prompt no longer shows the form and says
plainly not to use it, and any pair that arrives anyway comes off at the door —
in `normalize_text`, which every path that takes text from a machine already
runs: the translator, the proofreader and an imported translations.json.

Only a matched PAIR with something between it comes off, which is what leaves a
censored word alone. "f***" and "sh*t" are typeset exactly like that.

What lee types himself is untouched. `normalize_text` is not on the hand-edit
path, and a person who types an asterisk into a box meant it.
"""
from pathlib import Path

import pytest

from mangatl.translate import build_system
from mangatl.typeset import normalize_text
from where import PKG

HTML = PKG / "static" / "editor.html"


# ------------------------------------------------------------------ at the door

@pytest.mark.parametrize("raw,want", [
    ("*TURN*", "TURN"),
    ("**TURN**", "TURN"),                 # one pair inside another
    ("*pant* *pant*", "pant pant"),       # two pairs, not one span
    ("*sniff*", "sniff"),
    ("*wheeze*...", "wheeze..."),
    ("HE *SLAMMED* IT", "HE SLAMMED IT"),
])
def test_a_starred_sound_is_typeset_bare(raw, want):
    assert normalize_text(raw) == want


@pytest.mark.parametrize("raw", ["f***", "sh*t", "2*3", "*", "**", "5 * 4"])
def test_an_unpaired_star_is_left_where_it_is(raw):
    """A censored word is typeset with its asterisks. Stripping edges rather
    than pairs would turn "f***" into "f"."""
    assert normalize_text(raw) == raw


def test_nothing_else_about_the_line_changes():
    assert normalize_text("*“Don’t…”*") == '"Don\'t..."'
    assert normalize_text("") == ""


# --------------------------------------------------------------- and at the top

def test_the_prompt_no_longer_teaches_the_starred_form():
    sys = build_system("manga", "en")
    for taught in ("*inhale*", "*pant*", "*sniff*", "*wheeze*"):
        assert taught not in sys, f"the prompt still offers {taught}"


def test_the_prompt_says_not_to_use_it():
    assert "asterisk" in build_system("manga", "en").lower()


# ------------------------------------------------------------- the whole way in

def test_a_translation_arrives_without_its_stars():
    """The proof that matters: text coming back from the model, through the
    real landing code, onto the region."""
    from types import SimpleNamespace

    import numpy as np

    from mangatl.models import Page, TextRegion
    from mangatl.translate import SeriesContext, translate_page

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [
        TextRegion(id=0, bbox=(0, 0, 40, 20), src_text="ゴロゴロ", kind="sfx"),
        TextRegion(id=1, bbox=(0, 40, 40, 20), src_text="すー…", kind="bubble"),
    ]
    reply = ('{"regions":[{"id":0,"translation":"*TURN*","confidence":0.9},'
             '{"id":1,"translation":"*pant* *pant*","confidence":0.9}],'
             '"page_notes":"","glossary_additions":{}}')
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])))

    translate_page(page, SeriesContext(), client=fake)

    assert [r.dst_text for r in page.regions] == ["TURN", "pant pant"]
