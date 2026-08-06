"""Dashes the Japanese never had do not reach the page.

Asked to carry one sentence across two balloons, the model closes the first
with an em-dash and opens the second with another. lee's page read

    MY HARD WORK PAID OFF TOO—
    —SO TAKE CARE NOW!

with nothing resembling a dash anywhere in the Japanese. Both prompts now
forbid it, but a prompt is a request; this is the part that holds. An edge
dash comes off unless the source earned it.

The awkward case is ー. On its own it is the ordinary long-vowel mark and turns
up in perfectly everyday words, so it cannot count as a dash — but a run of
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


def test_a_dash_in_the_middle_of_a_line_is_left_alone():
    """Inside a line the dash is doing a job, and removing it leaves a hole."""
    assert strip_added_dashes("WAIT—WHAT DID YOU SAY?",
                              "まって何て言った") == "WAIT—WHAT DID YOU SAY?"


def test_a_dash_the_source_earned_is_kept():
    """The rule is about dashes the model invented, not dashes it translated."""
    assert strip_added_dashes("HOLD ON—", "まって—") == "HOLD ON—"
    assert strip_added_dashes("—AND THEN?", "〜それで") == "—AND THEN?"
    assert strip_added_dashes("NOOO—", "やめてーー") == "NOOO—"


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
