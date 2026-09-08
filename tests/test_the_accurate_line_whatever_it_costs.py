"""Length is not a constraint on the translation any more.

lee: **"for fits_chars i wan the most accurate transaltion no matter the leght
of the of it so i dont want to shrink or expand teh translation to fit
anythng"**.

There were three length budgets and all three are gone:

    src_char_count   with "aim under about 1.6 times it"
    fits_chars       how much THAT balloon holds at a comfortable type size
    the target notes Spanish/Portuguese/French each carried "runs 20% longer
                     than English, so keep lines tight"

...and the proofreader's *"Never make a line meaningfully longer — it has to
fit the same bubble"*, which was the same instruction wearing a copy editor's
coat.

**Both halves had to go.** Taking out the RULE and leaving the NUMBERS would
have been the worse half of the job: a budget sitting in the payload with
nothing said about it is still a budget, and a model that can see how much room
it has will translate down to it.

What is left is one rule saying the opposite, and one note. The note is
`too_long`, and it moved from `comfort_size` to the project's FLOOR - so it no
longer means "this will come out small", which is now the correct answer, and
means "this will not go in at any size the project allows", which the
typesetter cannot solve. On lee's own chapter that is 141 of 220 lines flagged
before and none after, which is also what stops the proofread report being one
flag wide.
"""
import re

import pytest

from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _r(w=300, h=160, src="よろしくお願いします"):
    r = TextRegion(id=1, bbox=(0, 0, w, h), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, w, h), kind="bubble", order=0)
    r.src_text = src
    return r


def _page(rs):
    p = Page(image=None, source_path="t.png")
    p.regions = list(rs)
    return p


def _flat(fn, *a, **k):
    return re.sub(r"\s+", " ", fn(*a, **k))


# ------------------------------------------------------------- the translator

def test_the_rule_says_length_is_not_the_models_problem():
    flat = _flat(T.build_system, "manga", "en", "Japanese")
    assert "LENGTH IS NOT A CONSTRAINT ON YOU" in flat
    assert "Never cut a word, a qualifier or a nuance to make a line shorter" \
        in flat
    assert "never pad one out to fill a balloon" in flat


def test_it_says_who_the_balloon_belongs_to():
    """The reason it is not the model's problem, which is the part that makes
    the rule believable: somebody else already solves it."""
    flat = _flat(T.build_system, "manga", "en", "Japanese")
    assert "the balloon is the typesetter's problem" in flat
    assert "the type is set smaller" in flat


def test_and_it_says_which_way_the_trade_goes():
    flat = _flat(T.build_system, "manga", "en", "Japanese")
    assert "A line that fits and does not say what the page says is the " \
        "worst line on the page" in flat


def test_natural_is_still_a_constraint_and_is_not_the_same_one():
    """Without this the rule reads as a licence to pad. The shortest wording
    that carries the WHOLE meaning is right because that is how people talk,
    not because of the space."""
    flat = _flat(T.build_system, "manga", "en", "Japanese")
    assert "Being NATURAL is still a constraint" in flat
    assert "Do not translate long" in flat


def test_no_budget_survives_anywhere_in_the_prompt():
    for medium, src in (("manga", "Japanese"), ("manhwa", "Korean"),
                        ("manhua", "Chinese")):
        sys = T.build_system(medium, "en", src)
        for gone in ("src_char_count", "fits_chars", "1.6 times",
                     "comfortable reading size", "Text must be SHORT",
                     "Cut WORDS"):
            assert gone not in sys, (medium, gone)


def test_no_target_language_is_told_to_keep_its_lines_tight():
    """Spanish, Portuguese and French each carried a per-language version of
    the same instruction, which is how a rule survives being deleted."""
    for tgt in ("en", "es", "pt", "fr"):
        sys = T.build_system("manga", tgt, "Japanese")
        assert "keep lines tight" not in sys, tgt
        assert "disciplined about length" not in sys, tgt
        assert "longer than English" not in sys, tgt


def test_the_language_notes_themselves_are_still_there():
    """Only the length sentence came off - tú/usted and tu/vous are about
    register and have nothing to do with how wide a balloon is."""
    assert "tú or usted" in T.build_system("manga", "es", "Japanese")
    assert "tu or vous" in T.build_system("manga", "fr", "Japanese")
    assert "você or o senhor" in T.build_system("manga", "pt", "Japanese")


# ------------------------------------------------------------ the proofreader

def test_the_copy_editor_is_not_allowed_to_shorten_either():
    flat = _flat(T.build_proofread_system, "manga", "en")
    assert "Length is not yours to police" in flat
    assert "the page wins" in flat
    assert "the typesetter sets smaller type" in flat
    assert "Do not pad one out either" in flat


def test_the_old_proofread_rule_is_gone():
    t = T.build_proofread_system("manga", "en")
    assert "Never make a line meaningfully longer" not in t


def test_the_proofreader_is_not_handed_a_budget_either():
    """It never was, and now there is no argument for giving it one.

    The proofreader is only sent boxes that already have English in them, so
    the fixture has to have some."""
    r = _r()
    r.dst_text = "Nice to meet you."
    body = T.build_proofread_payload(_page([r]), T.SeriesContext())
    assert "fits_chars" not in body["regions"][0]
    assert "src_char_count" not in body["regions"][0]


# ----------------------------------------------------------------- the payload

def test_neither_number_travels_with_a_region():
    got = T.build_payload(_page([_r()]), T.SeriesContext())["regions"][0]
    assert "fits_chars" not in got
    assert "src_char_count" not in got


def test_what_a_region_still_carries():
    """Everything that is about the WRITING rather than about the room."""
    got = T.build_payload(_page([_r()]), T.SeriesContext())["regions"][0]
    for want in ("id", "panel", "kind", "text"):
        assert want in got, want


def test_the_budget_cannot_come_back_by_settings():
    """A project set in tiny type used to get a bigger budget than one set in
    large. There is no number to differ any more."""
    small, big = T.SeriesContext(), T.SeriesContext()
    small.min_font, small.max_font = 8, 12
    big.min_font, big.max_font = 24, 48
    a = T.build_payload(_page([_r()]), small)["regions"][0]
    b = T.build_payload(_page([_r()]), big)["regions"][0]
    assert a == b


# -------------------------------------------------------------- and the note

def test_the_note_is_taken_at_the_floor_and_not_at_a_comfortable_size():
    assert not hasattr(T, "comfort_size"), \
        "the comfortable size was the budget, and the budget is gone"
    assert not hasattr(T, "COMFORT_FONT")


def test_a_line_that_only_comes_out_small_is_no_longer_a_fault():
    """133 characters in a 300x300 balloon - the case the old note was tuned
    on, page 067, where the typesetter dropped to 21px and set it."""
    assert T.too_long("x" * 133, _r(w=300, h=300), 11) == ""


def test_a_line_that_will_not_go_in_at_any_allowed_size_still_is():
    r = _r(w=100, h=60)
    room = T.fits_chars(r, 11)
    assert room, "the fixture measures nothing and so proves nothing"
    assert "holds ~" in T.too_long("x" * (room * 4), r, 11)


def test_the_two_places_a_line_is_checked_both_use_the_floor():
    from where import PKG
    src = (PKG / "translate.py").read_text(encoding="utf-8")
    calls = [ln.strip() for ln in src.splitlines() if "too_long(r.dst_text" in ln]
    assert len(calls) == 2, calls
    assert src.count('getattr(ctx, "min_font", 12)))') == 2, \
        "one of the two is budgeting against something else"


def test_nothing_still_calls_the_comfortable_size():
    from where import PKG
    src = (PKG / "translate.py").read_text(encoding="utf-8")
    live = [ln for ln in src.splitlines()
            if "comfort_size(" in ln and not ln.lstrip().startswith("#")]
    assert not live, live


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
