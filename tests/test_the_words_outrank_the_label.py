"""A sentence in a box marked "sfx" is speech that was boxed wrong.

lee, with a screenshot of `焼き菓子が` / `ターレル銅貨三枚` outlined in the sound
effect's purple: *"can you look into why this si beihng found asa sound
effact"*. It could not be reproduced from a description, and then it turned up
by itself: he sent back a Translate request exported off his own 23-page
chapter, and page 017 carries two of them.

    017 id6   そんなので足りるかよ                         marked sfx
    017 id8   と…当然ですねっ私にはそれくらい価値が…       marked sfx

The second is dialogue inside a drawn balloon and the label is simply wrong.
The FIRST is more interesting, and it is why this is a prompt rule and not a
relabelling pass: it is a brush-script shout painted straight onto the artwork
with nothing drawn round it. In a scheme whose three families are bubble,
freefloat and sfx, a painted shout genuinely looks like paint - the detector
is not being stupid, it is answering "is this drawn or is this typeset", which
is the only question the pixels can answer. What it cannot know is that a drawn
shout is still something a person said.

**So nothing here moves a box.** lee's rule stands: *"make it so that read text
only read teh etxt and not modify boxes exapt for removing boxes with no text
or remoeving boxes with only symobos"*. The `speech_in_sfx` pass that used to
rename these came out that day and stays out.

What changes is one line of the translator's instructions, and it matters
because the instruction above it is load-bearing in the wrong direction:
*"Sound effects: render as a comic SFX ("CRASH", "THUD"), not a sentence."*
Read literally, a mislabelled box does not merely lose its punctuation - a
whole line of dialogue is compressed into one shouted word to satisfy a label.
"""
import pytest

from mangatl.translate import build_system


def _rule(t: str) -> str:
    at = t.index("THE WORDS OUTRANK THE LABEL")
    return " ".join(t[at:t.index("\n- ", at)].split())


def test_the_translator_is_told_which_of_the_two_to_believe():
    assert "THE WORDS OUTRANK THE LABEL" in build_system(target="English")


def test_it_names_what_a_sentence_looks_like():
    """"Translate it properly" is not an instruction. A subject, a verb,
    particles and a name are things the model can look for."""
    r = _rule(build_system(target="English"))
    for word in ("subject", "verb", "particles", "name"):
        assert word in r, word


def test_it_says_what_to_do_and_not_only_what_it_is():
    r = _rule(build_system(target="English"))
    assert "translate it as speech" in r.lower()
    assert "punctuated" in r


def test_it_explains_the_painted_shout_rather_than_calling_it_a_mistake():
    """The detector is right about the pixels and wrong about the meaning, and
    a rule that says "the label is wrong" invites the model to distrust every
    label it is given."""
    r = _rule(build_system(target="English"))
    assert "drawn" in r.lower()
    assert "still something a person said" in r


def test_it_refuses_the_specific_damage():
    """Not "be careful" - the exact failure, named. A sentence squeezed into
    CRASH is the thing the rule above it would otherwise produce."""
    r = _rule(build_system(target="English"))
    assert "CRASH" in r
    assert "Never squeeze a sentence" in r


def test_it_does_not_run_the_other_way():
    """A gasp in an ordinary bubble is still a sound - that is the WORDLESS
    SOUND rule further down, and this one must not cancel it. Both rules say
    the same thing from opposite ends: read the writing, not the rectangle."""
    t = build_system(target="English")
    r = _rule(t)
    assert "does not run the other way" in r
    assert "WORDLESS SOUND" in t


def test_it_sits_with_the_sound_effect_rule_it_qualifies():
    """Immediately after it, so the model reads the exception with the rule
    rather than four bullets later with the punctuation advice in between."""
    t = build_system(target="English")
    assert t.index("render as a comic SFX") < t.index("THE WORDS OUTRANK")
    between = t[t.index("render as a comic SFX"):t.index("THE WORDS OUTRANK")]
    # The one bullet marker in between is the one that STARTS this rule.
    assert between.count("\n- ") == 1, "another rule got in between the two"


def test_no_pass_renames_the_box_on_what_was_read():
    """The other half of the fix is that there ISN'T one. `speech_in_sfx` was
    removed at lee's word and this is the reason it did not come back."""
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert "def speech_in_sfx(" not in src
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    assert "_relabel(" not in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
