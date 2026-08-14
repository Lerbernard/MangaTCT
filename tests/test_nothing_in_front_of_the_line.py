"""Nothing stands in front of the line that does not stand in front of the raw.

lee, on a balloon that came out of the editor as *", The existence known as Kim
Jinwoo has probably ceased to exist."*: **"there isjat anything informt of th
text in the raw so there shoud be notjing in the transated"**.

## Where that comma came from

The model wrote `...—The existence known as Kim Jinwoo...`. Then:

1. `strip_added_dashes` looked at the dash. It was not at position 0 — three
   periods were in front of it — so it read as an INTERIOR dash and became
   `", "`, which is that rule working exactly as written.
2. `strip_added_ellipsis` ran immediately after, saw a leading ellipsis the
   Korean does not have, and took it away.

Two cleaners, each correct about the thing it was looking at, and a comma
standing on its own at the front of the line that neither of them was looking
at. The edge-dash rule was widened at the same time so the dash is recognised
as an edge dash and comes off cleanly — but that fixes the two steps that
happened to collide this week.

`strip_added_lead` is the rule lee actually stated, and it is a check on the
FINISHED LINE, not on a step. It runs last. Whatever a future cleaner leaves on
the front of a line, the answer is the same: the source draws it or it goes.

## What counts as being in front of the words

Punctuation. A quote and a bracket are not — they WRAP a line rather than
precede it — and `¿` and `¡` open a sentence in Spanish, which is one of the
targets. All of those are read past on both sides, which is what `_OPENERS`
already did for the ellipsis rule.
"""

import pytest

from mangatl.translate import (leads_with_a_mark, strip_added_dashes,
                               strip_added_ellipsis, strip_added_lead)

KO = "아마 김진우라는 존재는\n소멸했겠지."


def _clean(dst, src):
    """All three, in the order the translator runs them."""
    return strip_added_lead(
        strip_added_ellipsis(strip_added_dashes(dst, src), src), src)


def test_the_line_lee_sent():
    assert _clean("...—The existence known as Kim Jinwoo has probably "
                  "ceased to exist.", KO) == \
        "The existence known as Kim Jinwoo has probably ceased to exist."


def test_and_the_comma_on_its_own_if_it_ever_gets_there_again():
    """The point of checking the RESULT: this needs no theory about which step
    put the comma there."""
    assert strip_added_lead(", The existence known as Kim Jinwoo has "
                            "probably ceased to exist.", KO) == \
        "The existence known as Kim Jinwoo has probably ceased to exist."


@pytest.mark.parametrize("dst", [
    ", Well then", ". Well then", "; Well then", ": Well then",
    "! Well then", "? Well then", "— Well then", "– Well then",
    "… Well then", "...Well then", "- Well then", "、Well then",
    "，Well then", ",,, Well then", ",— Well then",
])
def test_a_mark_the_source_never_drew_comes_off(dst):
    assert strip_added_lead(dst, "그럼") == "Well then"


@pytest.mark.parametrize("src", [
    "…그럼",              # the page opens by trailing off
    "—그럼",              # ...or with a dash
    "- 영혼의 고향과 연결된 문",   # ...or a bullet, on a status window
    "、そうか",
    "!!! 진우야",
])
def test_a_mark_the_source_did_draw_is_the_source_s_business(src):
    assert strip_added_lead(", Well then", src) == ", Well then"


def test_a_quote_is_not_in_front_of_the_line_it_is_round_it():
    assert strip_added_lead('"Well then"', "그럼") == '"Well then"'
    assert strip_added_lead("「Well then」", "그럼") == "「Well then」"


def test_and_a_mark_inside_the_quote_still_comes_off():
    assert strip_added_lead('", Well then"', "그럼") == '"Well then"'


def test_spanish_opens_a_sentence_with_punctuation_and_that_is_allowed():
    """`es` is one of `translate.TARGETS`. Stripping these would be wrong in a
    way no English page would ever catch."""
    assert strip_added_lead("¿Y ahora qué?", "이제 어떡하지?") == "¿Y ahora qué?"
    assert strip_added_lead("¡Jinwoo!", "진우야!") == "¡Jinwoo!"


def test_a_line_that_is_only_punctuation_is_left_alone():
    """Erasing it would leave an empty balloon, which is worse than a mark."""
    assert strip_added_lead("...", "그럼") == "..."
    assert strip_added_lead("?!", "그럼") == "?!"


def test_nothing_in_the_middle_or_at_the_end_is_touched():
    assert strip_added_lead("Well, then... really?", "그럼") == \
        "Well, then... really?"


@pytest.mark.parametrize("dst,src", [("", "그럼"), ("   ", "그럼"),
                                     (None, "그럼")])
def test_an_empty_line_survives(dst, src):
    assert strip_added_lead(dst, src) == dst


def test_a_source_of_nothing_at_all_is_a_source_that_drew_nothing():
    assert strip_added_lead(", Well then", "") == "Well then"
    assert strip_added_lead(", Well then", None) == "Well then"


def test_the_question_it_asks_of_a_line():
    assert leads_with_a_mark(", hello")
    assert leads_with_a_mark('"...hello')
    assert leads_with_a_mark("- 영혼의 고향과 연결된 문")
    assert not leads_with_a_mark("hello")
    assert not leads_with_a_mark('"hello"')
    assert not leads_with_a_mark("¿hola?")
    assert not leads_with_a_mark("")


# --- and it has to be the LAST thing that runs -------------------------------

def _flat(fn):
    """The source with its wrapping taken out.

    What these three are about is the ORDER of three calls. Matching the
    wrapped text instead went red the first time a line was re-indented, which
    is how a test stops being read — the same lesson as
    `test_the_line_has_to_fit`.
    """
    import inspect
    import re
    return re.sub(r"\s+", " ", inspect.getsource(fn))


def test_it_runs_after_the_other_two_in_the_translator():
    from mangatl import translate
    assert "strip_added_lead( strip_added_ellipsis(" in \
        _flat(translate.translate_page)


def test_and_after_them_in_the_proofreader():
    from mangatl import translate
    assert "strip_added_lead( strip_added_ellipsis(" in \
        _flat(translate.proofread_page)


def test_and_on_text_pasted_in_from_a_file():
    """A translations file is very often a machine's."""
    from mangatl import editor
    assert "strip_added_lead( strip_added_ellipsis(" in \
        _flat(editor.set_translation)
