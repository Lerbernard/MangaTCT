"""Dashes the Japanese never had do not reach the page.

Asked to carry one sentence across two balloons, the model closes the first
with an em-dash and opens the second with another. lee's page read

    MY HARD WORK PAID OFF TOO—
    —SO TAKE CARE NOW!

with nothing resembling a dash anywhere in the Japanese. Both prompts now
forbid it, but a prompt is a request; this is the part that holds. An edge
dash comes off unless the source earned it.

The awkward case is ー. On its own it is the ordinary long-vowel mark and turns
up in perfectly everyday words, so it cannot count as a dash - but a run of
them is a drawn-out cry, and that is a dash.
"""
import pytest

from mangatl.translate import source_has_dash, strip_added_dashes


# ------------------------------------------------------- reading the source

@pytest.mark.parametrize("src", [
    "だからさ—",                 # em-dash
    "そうか―",                   # horizontal bar
    "まって─",                   # box-drawing light horizontal
    "うわあ━",                   # box-drawing heavy horizontal
    "ねえ〜",                     # wave dash
    "ねえ～",                     # its full-width twin
    "うわあーーー",               # a run of the long-vowel mark: a drawn-out cry
    "やめてーー",
])
def test_the_source_earned_its_dash(src):
    assert source_has_dash(src) is True


@pytest.mark.parametrize("src", [
    "",
    "ありがとう。",
    "コーヒーを一杯",             # ONE ー, in an ordinary word
    "スーパーマーケット",         # three of them, none adjacent
    "私の努力も報われた。",
])
def test_a_lone_long_vowel_mark_is_not_a_dash(src):
    assert source_has_dash(src) is False


def test_none_is_not_a_source():
    assert source_has_dash(None) is False


# ------------------------------------------------------ taking dashes back

def test_the_pair_lee_reported_comes_apart():
    """The two halves of one sentence, neither of which asked for a rule."""
    assert strip_added_dashes("MY HARD WORK PAID OFF TOO—",
                              "私の努力も報われた") == "MY HARD WORK PAID OFF TOO"
    assert strip_added_dashes("—SO TAKE CARE NOW!",
                              "気をつけてね") == "SO TAKE CARE NOW!"


@pytest.mark.parametrize("dst, want", [
    ("—HELLO", "HELLO"),
    ("HELLO—", "HELLO"),
    ("—HELLO—", "HELLO"),
    ("— HELLO", "HELLO"),
    ("HELLO —", "HELLO"),
    ("HELLO——", "HELLO"),
    ("–HELLO–", "HELLO"),          # en-dashes too
])
def test_edge_dashes_come_off(dst, want):
    assert strip_added_dashes(dst, "こんにちは") == want


def test_a_dash_in_the_middle_of_a_line_becomes_a_comma():
    """This used to leave it alone, on the grounds that it was doing a job.

    Measured over a chapter, the job it was doing was the model's own voice -
    "Legend of the Dragon 7-a game that..." out of Korean with no dash in it
    anywhere. A comma says the same thing and a comic font can draw it. A
    source with a real dash still exempts the whole line, which is the test
    below.
    """
    assert strip_added_dashes("WAIT—WHAT DID YOU SAY?",
                              "まって何て言った") == "WAIT, WHAT DID YOU SAY?"


def test_a_dash_the_source_earned_is_kept():
    """The rule is about dashes the model invented, not dashes it translated.

    At the TAIL and in the middle. The leading one is no longer part of this
    exemption - see the test below, which is lee's page 4.
    """
    assert strip_added_dashes("HOLD ON—", "まって—") == "HOLD ON—"
    assert strip_added_dashes("NOOO—", "やめてーー") == "NOOO—"


def test_a_dash_at_the_FRONT_goes_even_when_the_source_has_one():
    """lee's chapter, two source lines punctuated identically: page 4 came
    back "-Be resolute before pain." and page 25 came back with no dash at
    all. Nothing decided that - the leading dash survived on whichever page
    the model happened to type one.

    A dash at the front of a Korean or Japanese bubble marks speech arriving
    from off-panel. English typesetting has never used it: the balloon's tail
    says it, and so does the box type. So it comes off whichever mark the
    scan drew it with - the same rule `strip_added_ellipsis` already applies
    to a leading ellipsis.
    """
    assert strip_added_dashes("-Be resolute before pain.",
                              "-고통 앞에\n의연하라.") == "Be resolute before pain."
    assert strip_added_dashes("—AND THEN?", "〜それで") == "AND THEN?"
    # The plain hyphen is the one that was getting through: the class knew
    # `-` and `–`, and a scan letters its dashes with whatever the keyboard
    # has. Neither the source nor the English here has a long dash anywhere.
    assert strip_added_dashes("-WAIT", "まって") == "WAIT"
    # A word the speaker was cut off in the middle of keeps its hyphen. That
    # is why the TAIL wants a space in front of the dash and the FRONT does
    # not: no line begins with the hyphen of a hyphenated word.
    assert strip_added_dashes("Listen well-", "잘 들어") == "Listen well-"
    assert strip_added_dashes("half-year of waiting", "반 년") == \
        "half-year of waiting"


def test_an_ellipsis_is_never_touched():
    """The mark scanlation actually uses for a sentence carried across bubbles."""
    assert strip_added_dashes("I THOUGHT...", "思ったんだ") == "I THOUGHT..."
    assert strip_added_dashes("...IT WAS OVER", "終わったと") == "...IT WAS OVER"


def test_a_line_that_is_only_a_dash_is_not_emptied():
    """Better a stray mark than a bubble with nothing in it at all."""
    assert strip_added_dashes("—", "……") == "—"


def test_nothing_in_nothing_out():
    assert strip_added_dashes("", "こんにちは") == ""
    assert strip_added_dashes(None, "こんにちは") is None
