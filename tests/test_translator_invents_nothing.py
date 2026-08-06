"""The translator names nobody the page does not name, and the proofreader
makes the page agree with itself.

lee: *"the trnaslataor should not be making up charactwrs only named characters
shoud be in the character list and don't create charaters and making up names,
try to keep to raw translation as much as posible and teh proffreeder shoud make
sure everything is conststant"*.

Three rules, three places. The sheet already refused unnamed bit parts; what it
did not say was that a name has to be PRINTED — nothing stopped a name being
coined from the artwork. The translator now has a stated bias toward what is
written rather than what could be inferred, and the proofreader has consistency
as an explicit job with a stated tie-breaker.

Prompts cannot be unit-tested for behaviour without calling the model, and there
is no key in this container. What is locked here is that the instructions are
present, unambiguous and cannot be quietly dropped — which is the failure mode
that matters: a prompt rule deleted in an edit and nobody noticing for a
chapter.
"""
from pathlib import Path
from where import PKG

SRC = (PKG
       / "translate.py").read_text(encoding="utf8")


def _flat(s):
    """One line, single-spaced — the prompt is wrapped for reading."""
    return " ".join(s.split())


def _system():
    from mangatl.translate import build_system
    return _flat(build_system("manga", "en", "ja"))


def _proofread():
    from mangatl.translate import build_proofread_system
    return _flat(build_proofread_system("manga", "en", "ja"))


def test_a_name_has_to_be_printed_on_the_page():
    s = _system()
    assert "A name has to be PRINTED ON THE PAGE" in s
    assert "Never invent one, never guess one from the art" in s
    assert "never coin a label to stand in for a name" in s
    assert "an unnamed speaker stays unnamed" in s
    assert "If nobody says who is speaking, the speaker is null" in s
    # and the older rule it builds on is still there
    assert "character_additions ONLY a NAMED, recurring" in s


def test_the_translation_stays_close_to_what_is_written():
    s = _system()
    assert "Translate what is written" in s
    assert "no added adjectives, no invented names" in s
    assert "keep the ambiguity rather than choosing for the reader" in s


def test_the_proofreader_is_told_to_make_the_page_agree_with_itself():
    s = _proofread()
    assert "CONSISTENCY across the whole page" in s
    assert "One person, one name, one spelling" in s
    assert "One term, one rendering" in s
    # a rule with no tie-breaker is a coin toss
    assert "the FIRST use on the page decides" in s
    assert "Do not invent." in s


def test_none_of_it_can_be_dropped_without_the_tests_noticing():
    """The guard: these three paragraphs are the whole of the instruction, and
    a prompt loses a rule silently."""
    for phrase in ("PRINTED ON THE PAGE",
                   "Translate what is written",
                   "CONSISTENCY across the whole page",
                   "Do not invent."):
        assert SRC.count(phrase) == 1, \
            f"{phrase!r} appears {SRC.count(phrase)} times, not once"
