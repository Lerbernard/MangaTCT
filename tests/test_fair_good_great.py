# -*- coding: utf-8 -*-
"""Three words instead of a bar, and one on every choice.

lee: *"remove teh blue bar and the number and create a new ratting system,
fair, good and great and every chois that the use can make like teh ai ,
reader, detector shoud get one of those ratings"*, and then *"fair beigng the
worst and great being teh best"*.

## Why the number had to go

The detector cards carried a bar and a percentage: 92, 96, 96, 95. A bar
invites the comparison the numbers cannot carry — the whole spread between the
best card and the worst is a third of a mistake per page, and it was drawn as
a bar four fifths full against a bar filled to the end.

## Why it had to go on the other two

The reader and the model are choices as well, and they had nothing beside
them. An empty space where the neighbouring control has a rating does not read
as *"nobody has counted this"*, it reads as *"nobody has an opinion about
this"* — which is worse than either the count or the judgement would have been.

## The three sources, kept apart

They are not the same kind of answer, and each word carries where it came from
in its own tooltip:

* the **detector** is COUNTED — 226 hand-checked sites, missed and stray.
* the **reader** is a JUDGEMENT, whose argument is the sentence already on the
  card.
* the **model** is the MAKER'S OWN TIER, read off the name. `lite`, `mini` and
  `haiku` are what the makers call their small models; `opus` and `pro` what
  they call their large ones. That is a published fact about the model and not
  a measurement of anything this app does, and the tooltip says so.

*"A rating whose formula is a secret is a rating nobody can argue with, which
is the opposite of useful"* — `rateRoutes`, and it is why none of the three is
one.
"""
import re

import pytest

from where import PKG


def _js():
    return (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")


def _html():
    return (PKG / "static" / "editor.html").read_text(encoding="utf-8")


def _css():
    return (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")


def _fn(js, head, end="\n}"):
    assert head in js, head
    return js.split(head)[1].split(end)[0]


def _list(js, name):
    m = re.search(r"const %s = \[([^\]]*)\]" % name, js)
    assert m, name
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


# ------------------------------------------------------------- the words

def test_there_are_three_of_them_and_they_are_in_order():
    m = re.search(r"const RATE_WORDS = \[([^\]]*)\]", _js())
    assert m, "the words are not written down anywhere"
    got = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    assert got == ["Fair", "Good", "Great"], got


def test_the_bar_and_the_number_are_gone():
    html, css, js = _html(), _css(), _js()
    for gone in ('class="rate"', 'class="score"'):
        assert gone not in html, gone
    assert ".rate u{" not in css.replace(" ", ""), "the bar still has a fill"
    assert "'%'" not in js.split("function rateRoutes(")[1].split("\n}")[0], \
        "a width in per cent is still being written"


def test_every_card_on_the_page_has_a_slot_for_one():
    """Six detectors and two readers. The readers had nothing at all.

    Six, and four on screen: two of the detector cards were measured on manga
    and two on webtoons, and the group shows the ones that belong to the
    format being worked on. See `ROUTE_MEDIA` in project.js."""
    assert _html().count('class="rating"') == 8


def test_the_chip_is_built_in_one_place():
    js = _js()
    assert "function rate3(" in js
    for caller in ("function rateRoutes(", "function syncReaderCards("):
        body = _fn(js, caller)
        assert "rate3(" in body, caller


def test_an_unknown_word_does_not_reach_the_class_name():
    """The class is what colours it, and a word that is not one of the three
    would leave a chip with no colour and no border rather than an obvious
    mistake."""
    body = _fn(_js(), "function rate3(word, why){")
    assert "RATE_WORDS.includes(word)" in body, body


# ------------------------------------------------------ what is counted

@pytest.mark.parametrize("missed, junk, want", [
    (5, 13, "Good"),        # comic-text-detector, 92
    (6, 4, "Great"),        # DB++ / COO, 96
    (7, 3, "Great"),        # Manga109, 96
    (11, 0, "Great"),       # AnimeText, 95
])
def test_the_detector_cards_land_where_their_counts_put_them(missed, junk, want):
    """The arithmetic is `(226 - missed - junk) / 226`, and the thresholds are
    written into the tooltip so they can be argued with."""
    score = round(100 * (226 - missed - junk) / 226)
    got = "Great" if score >= 95 else "Good" if score >= 85 else "Fair"
    assert got == want, (score, got)


def test_the_thresholds_are_absolute_and_not_relative_to_the_best_card():
    """A rating that moves when a new model is added told you something about
    the list rather than about the thing."""
    body = _fn(_js(), "function rateOfScore(pct){")
    assert "95" in body and "85" in body, body
    assert "Math.max" not in body, "the scale is being set by the other cards"


def test_the_count_is_still_on_the_card_where_somebody_can_check_it():
    body = _fn(_js(), "function rateRoutes(){")
    assert "226" in body and "missed" in body and "stray" in body, body


# ------------------------------------------------- the maker's own tier

@pytest.mark.parametrize("model, want", [
    ("claude-opus-5", "Great"),
    ("claude-fable-5", "Great"),
    ("gemini-3.1-pro", "Great"),
    ("google/gemini-3-pro", "Great"),
    ("claude-sonnet-5", "Good"),
    ("gemini-3.7-flash", "Good"),
    ("deepseek-chat", "Good"),
    ("claude-haiku-4-5", "Fair"),
    ("anthropic/claude-haiku-4.5", "Fair"),
    ("gemini-2.5-flash-lite", "Fair"),
    ("google/gemini-3.1-flash-lite", "Fair"),
    ("gpt-5-mini", "Fair"),
])
def test_a_model_is_read_at_the_tier_its_maker_named_it(model, want):
    """`flash-lite` must not be caught by `flash`, which is why the small end
    is asked first - and `gemini` must not be caught by `mini`, which is why
    the id is cut into WORDS. The first version matched substrings and rated
    every Gemini model on earth Fair.

    The two lists are read out of the source and the four lines applied here,
    rather than the rule being written down twice."""
    js = _js()
    small = _list(js, "RATE_SMALL")
    big = _list(js, "RATE_BIG")
    words = [w for w in re.split(r"[^a-z0-9]+", model.lower()) if w]
    got = ("Fair" if any(w in small or re.fullmatch(r"\d+b", w) for w in words)
           else "Great" if any(w in big for w in words) else "Good")
    assert got == want, (model, got, words)


def test_the_small_end_is_asked_first():
    body = _fn(_js(), "function rateOfModel(id){")
    assert body.index("'Fair'") < body.index("'Great'"), \
        "'flash-lite' will be caught by 'flash'"


def test_the_tier_is_a_whole_word_and_not_a_run_of_letters():
    """`gemini` has `mini` in it. Every Gemini model on earth was Fair."""
    body = _fn(_js(), "function rateOfModel(id){")
    assert ".split(" in body, "the id is still matched as one string"
    assert "includes(t)" in body, body


def test_every_row_of_every_model_menu_carries_one():
    body = _fn(_js(), "function drawModels(step, names, priced){")
    assert "rateOfModel(" in body, "the menu rows have no rating"
    assert "tier(have)" in body, \
        "a model that is set but no longer offered lost its rating"


def test_the_menu_says_the_word_is_about_the_NAME():
    """A word beside a model that looks like a score of this app's work on
    these pages would be a claim nobody has measured."""
    html = _html()
    m = re.search(r'<label class="sublab" title="([^"]*)">AI model</label>',
                  html)
    assert m, "the AI model label carries no explanation"
    tip = m.group(1).lower()
    assert "maker" in tip and "name" in tip
    assert "not a measurement" in tip, tip
    assert html.count('>AI model</label>') == 3, "one step was left out"


# ------------------------------------------------------- the judgement

def test_the_reader_cards_say_which_is_which():
    body = _fn(_js(), "function syncReaderCards(){")
    assert "'Great'" in body, "the AI reader has no rating"
    assert "'Good'" in body and "'Fair'" in body, \
        "the offline reader is rated the same in both languages"


def test_and_that_the_offline_one_depends_on_the_language():
    """"On this computer" is a different program per language - manga-ocr
    reads Japanese and nothing else, easyocr is a general engine having a go
    at comics - so one word for both would be wrong on one of them."""
    body = _fn(_js(), "function syncReaderCards(){")
    assert re.search(r"ja \? 'Good' : 'Fair'", body), body


def test_the_reader_word_does_not_pretend_to_be_a_count():
    body = _fn(_js(), "function syncReaderCards(){")
    assert body.count("A judgement, not a count") >= 2, body


# ------------------------------------------------------------- the chip

@pytest.mark.parametrize("word", ["great", "good", "fair"])
def test_each_word_has_a_colour_of_its_own(word):
    css = _css()
    assert ".rate3." + word in css, word


def test_the_chip_beats_the_card_title_on_specificity():
    """`.cards .card b` is the card's NAME and would otherwise set this at
    13.5px - the chip is a `<b>` too."""
    css = _css()
    assert ".cards .card .rate3" in css, \
        "the chip will be drawn at the card title's size"
