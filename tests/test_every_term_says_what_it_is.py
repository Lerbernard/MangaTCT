"""The glossary rule: a term that does not say what it is never reaches the sheet.

lee, looking at a panel where nine of eleven terms had an empty note: *"make it
so that the ai alway writes a discption"*.

The rule lives in `translate.merge_glossary` and nowhere else, so it is about
the SHEET rather than about one route into it. Before this, `ctx.glossary`
was written by a bare `.update()` in two places - the live translator and the
hand-typed reply upload - and only one of them could ever have been made to
check anything.
"""
import re

import pytest

from mangatl.translate import (gloss_name, gloss_note, gloss_value,
                               merge_glossary)


# ------------------------------------------------------- name, note and back

def test_the_two_halves_of_a_rendering():
    assert gloss_name("Tarel (the copper coin)") == "Tarel"
    assert gloss_note("Tarel (the copper coin)") == "the copper coin"
    # A dash does the same job, and the full-width brackets a Japanese
    # keyboard produces are the same brackets.
    assert gloss_name("Glow — the mercenary") == "Glow"
    assert gloss_note("Glow — the mercenary") == "the mercenary"
    assert gloss_note("巨門（the great gate）") == "the great gate"
    assert gloss_value("Tarel", "the copper coin") == "Tarel (the copper coin)"
    assert gloss_value("Tarel", "") == "Tarel"


def test_a_hyphen_inside_a_name_is_not_a_description():
    """The dash rule wants SPACES around the dash. Without that, "Half-Moon
    Gate" is a gate called "Half" described as "Moon Gate"."""
    assert gloss_name("Half-Moon Gate") == "Half-Moon Gate"
    assert gloss_note("Half-Moon Gate") == ""


def test_the_python_and_the_panel_split_a_name_the_same_way():
    """`gloss_name` / `gloss_note` are `glossName` / `glossNote` from
    `static/js/project.js`. If they disagree about where a name ends, the panel
    shows one thing and the rule enforces another - and the row a person just
    filled in reads back empty."""
    # Asked of the PACKAGE rather than of the working directory: pytest may
    # be run from anywhere, and a relative path here made this pass or fail on
    # which folder you happened to be standing in. See `where`.
    from where import JS
    js = (JS / "project.js").read_text(encoding="utf-8")
    for py, name in ((r"\s*[（(]|\s+[—–-]\s+", "glossName split"),
                     (r"[（(]([^)）]*)[)）]", "glossNote bracket"),
                     (r"\s+[—–-]\s+(.+)$", "glossNote dash")):
        assert py in js, name


# ------------------------------------------------------------- what gets in

def test_a_bare_name_is_refused():
    sheet = {}
    refused = merge_glossary(sheet, {"タレル": "Tarel"})
    assert sheet == {}
    assert refused and "Tarel" in refused[0]


def test_a_described_term_joins_the_sheet():
    sheet = {}
    assert merge_glossary(sheet, {"タレル": "Tarel (the copper coin)"}) == []
    assert sheet == {"タレル": "Tarel (the copper coin)"}


def test_a_description_fills_in_an_empty_row():
    """The way out for a glossary that already has nine bare terms on it. The
    prompt asks the model to re-propose anything it was GIVEN without a
    bracket, and this is what lets the answer land."""
    sheet = {"タレル": "Tarel"}
    assert merge_glossary(sheet, {"タレル": "Tarel (the copper coin)"}) == []
    assert sheet == {"タレル": "Tarel (the copper coin)"}


def test_a_description_never_re_words_one_that_is_already_there():
    """First sighting is canon, exactly as it is for the character sheet.
    Otherwise every page gets a vote and the sheet is whatever the last page
    happened to say."""
    sheet = {"タレル": "Tarel (the copper coin)"}
    assert merge_glossary(sheet, {"タレル": "Tarel (a small coin, copper)"}) == []
    assert sheet == {"タレル": "Tarel (the copper coin)"}


def test_filling_a_row_in_keeps_the_spelling_the_sheet_already_had():
    """The sheet is canon and a later page only extends it. A re-proposal is
    there to supply the missing NOTE, not to rename the thing."""
    sheet = {"ザルドネ": "Zaldone"}
    merge_glossary(sheet, {"ザルドネ": "Zaldon (the northern kingdom)"})
    assert sheet == {"ザルドネ": "Zaldone (the northern kingdom)"}


def test_nothing_at_all_is_not_a_refusal():
    """An empty proposal is not a term that failed the rule, it is no term."""
    sheet = {}
    assert merge_glossary(sheet, {"": "Tarel (a coin)", "x": ""}) == []
    assert merge_glossary(sheet, None) == []
    assert sheet == {}


# ------------------------------------------- and it is the sheet's rule, not a route's

def test_no_route_writes_the_glossary_behind_the_rule():
    """`ctx.glossary.update()` is how a bare term used to get in. There is no
    reason for it to exist anywhere now, and a test is cheaper than
    remembering."""
    from where import PKG
    for path in ("translate.py", "editor.py"):
        for n, line in enumerate(
                (PKG / path).read_text(encoding="utf-8").splitlines(), 1):
            # Prose about the rule may name it; code may not. A backtick is how
            # this codebase quotes an identifier it is talking ABOUT.
            if re.search(r"glossary\.update\(", line) and "`" not in line:
                raise AssertionError(f"{path}:{n}: {line.strip()}")


def test_the_prompt_asks_for_what_the_code_enforces():
    """A rule the model is never told about is a rule that shows up as a
    refusal it cannot act on."""
    from mangatl import translate
    both = translate.SYSTEM + translate.SCHEMA_HINT
    assert "Tarel (the copper coin)" in both
    assert "bracket" in both.lower()


# ------------------------------------------ and the refusal travels, like the sheet's

def test_a_refused_term_is_reported_the_way_a_refused_character_is():
    """`glossary_refused`, mirroring `characters_refused`. A rule that drops a
    proposal silently is a rule nobody can act on: the sheet stays empty, the
    model keeps proposing the same bare name, and the panel gives no reason."""
    import json as _json
    from types import SimpleNamespace

    import numpy as np

    from mangatl.models import Page, TextRegion
    from mangatl.translate import SeriesContext, translate_page

    page = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page.regions = [TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="タレル")]
    ctx = SeriesContext()
    reply = _json.dumps({
        "regions": [{"id": 0, "translation": "Tarel.", "compact": "Tarel.",
                     "speaker": None, "confidence": 0.9}],
        "page_notes": "", "character_additions": {},
        "glossary_additions": {"タレル": "Tarel",
                               "ザルドネ": "Zaldone (the northern kingdom)"},
    })
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])))

    data = translate_page(page, ctx, client=fake)
    assert "タレル" not in ctx.glossary
    assert ctx.glossary["ザルドネ"] == "Zaldone (the northern kingdom)"
    assert any("Tarel" in r for r in data.get("glossary_refused", []))

    # ...and a page where everything was described says nothing at all, so the
    # key is a report of something rather than a field that is always there.
    described = _json.dumps({
        "regions": [{"id": 0, "translation": "Tarel.", "compact": "Tarel.",
                     "speaker": None, "confidence": 0.9}],
        "page_notes": "", "character_additions": {},
        "glossary_additions": {"タレル": "Tarel (the copper coin)"},
    })
    quiet = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=described)])))
    page2 = Page(image=np.full((100, 100, 3), 255, np.uint8))
    page2.regions = [TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="タレル")]
    ctx2 = SeriesContext()
    assert "glossary_refused" not in translate_page(page2, ctx2, client=quiet)
    assert ctx2.glossary["タレル"] == "Tarel (the copper coin)"
