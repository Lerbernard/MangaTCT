"""The story is a thing you can switch off.

lee: *"add a story setting that allow the user ti turn the story thing off,
and to tun what the ai detects with check boxes"*.

The synopsis, the character sheet and the glossary are what keep chapter 4
calling her what chapter 3 called her. Some projects want none of it - a
one-shot, a gag strip, a script somebody else already wrote - and until now
the only way to have none of it was to leave three sheets empty and still pay
to send them.

**Off means neither sent nor added to.** Both halves matter: sending sheets
nobody keeps is paying for nothing, and filling in sheets nobody reads is
paying for nothing twice. Nothing is DELETED either way, so the switch can be
switched back.
"""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from mangatl.models import Page, TextRegion
from mangatl.translate import SeriesContext, build_payload, translate_page


def _page():
    p = Page(image=np.full((100, 100, 3), 255, np.uint8))
    p.regions = [TextRegion(id=0, bbox=(0, 0, 10, 10), src_text="そうか")]
    return p


def _ctx(**kw):
    c = SeriesContext(synopsis="A story.",
                      glossary={"タレル": "Tarel (the copper coin)"},
                      characters={"Leonora": "she/her - the Saint"})
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _reply(**extra):
    # The translation NAMES Ada, so a character addition for her is properly
    # evidenced and would really land on the sheet. Proposing a name the page
    # never writes down would be refused by `merge_characters` whatever these
    # switches said, and a test written that way passes with the switch
    # removed - which is exactly how a mutant found it.
    body = {"regions": [{"id": 0, "translation": "I see, Ada.",
                         "compact": "I see, Ada.",
                         "speaker": "Aeda", "confidence": 0.9}],
            "page_notes": "",
            "glossary_additions": {"ザルドネ": "Zaldone (the kingdom)"},
            "character_additions": {"Ada": "she/her - a healer"}}
    body.update(extra)
    text = json.dumps(body)
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])))


# ------------------------------------------------------------ what is sent

def test_a_project_with_a_story_sends_all_three_sheets():
    got = build_payload(_page(), _ctx())
    assert got["series_context"] == "A story."
    assert got["glossary"] and got["characters"]
    assert "do_not_return" not in got


def test_switching_the_story_off_sends_none_of_them():
    """Not empty ones - absent. An empty object is still bytes on the wire and
    still a thing the model reads as "this project has no characters", which
    is a different statement from not being asked."""
    got = build_payload(_page(), _ctx(story=False))
    for k in ("series_context", "glossary", "characters"):
        assert k not in got, k
    # ...and the page itself is still all there.
    assert got["regions"] and got["medium"]


def test_the_model_is_told_what_not_to_bother_returning():
    """A model asked for `character_additions` and then quietly ignored is a
    model spending OUTPUT tokens on an answer nobody reads - and output is the
    expensive side of the bill."""
    assert build_payload(_page(), _ctx(story=False))["do_not_return"] == \
        ["character_additions", "glossary_additions"]
    assert build_payload(_page(), _ctx(learn_terms=False))["do_not_return"] == \
        ["glossary_additions"]
    assert build_payload(_page(), _ctx(learn_characters=False))["do_not_return"] == \
        ["character_additions"]
    assert build_payload(_page(), _ctx(name_speakers=False))["do_not_return"] == \
        ["speaker"]


def test_the_switches_sit_in_the_cacheable_half_of_the_payload():
    """They do not change during a run, so the bytes are identical on every
    page and the prompt cache keeps them. A switch below `regions` would end
    the cached prefix at the top of the payload instead of the bottom."""
    keys = list(build_payload(_page(), _ctx(story=False)).keys())
    assert keys.index("do_not_return") < keys.index("regions")
    assert keys.index("do_not_return") < keys.index("previous_page_tail")


def test_the_prompt_explains_the_field_it_sends():
    """A rule the model is never told about is a rule it cannot follow."""
    from mangatl import translate
    assert "do_not_return" in translate.SYSTEM


# --------------------------------------------------------- what comes back

def test_with_the_story_off_nothing_is_added_to_anything():
    ctx = _ctx(story=False)
    before = (dict(ctx.glossary), dict(ctx.characters))
    translate_page(_page(), ctx, client=_reply())
    assert (ctx.glossary, ctx.characters) == before


def test_the_sheets_are_not_deleted_by_switching_it_off():
    """The difference between a switch and a delete. Somebody who turns it off
    to save a few coins on one chapter must find their cast where they left
    it."""
    ctx = _ctx(story=False)
    translate_page(_page(), ctx, client=_reply())
    assert ctx.characters == {"Leonora": "she/her - the Saint"}
    assert ctx.glossary == {"タレル": "Tarel (the copper coin)"}


def test_each_tick_is_independent():
    """A series with a big cast wants the character sheet and not the
    glossary. One switch for both would make that unsayable."""
    ctx = _ctx(learn_terms=False)
    translate_page(_page(), ctx, client=_reply())
    assert "ザルドネ" not in ctx.glossary
    assert "Ada" in ctx.characters           # ...and the other one still ran

    ctx = _ctx(learn_characters=False)
    translate_page(_page(), ctx, client=_reply())
    assert "Ada" not in ctx.characters
    assert "ザルドネ" in ctx.glossary


def test_a_speaker_nobody_asked_for_is_dropped_even_if_it_arrives():
    """The switch is about what is KEPT, and a rule enforced only by asking
    the model politely is not enforced."""
    page = _page()
    translate_page(page, _ctx(name_speakers=False), client=_reply())
    assert page.regions[0].speaker is None
    # ...and with it on, the same reply names the speaker.
    page2 = _page()
    translate_page(page2, _ctx(), client=_reply())
    assert page2.regions[0].speaker == "Aeda"


def test_with_no_sheet_there_is_no_complaint_about_the_sheet():
    """"is not named anywhere" is a complaint measured against a character
    sheet. With the story off there is no sheet, so the complaint is about
    nothing and would appear on every line of every page."""
    page = _page()
    translate_page(page, _ctx(story=False), client=_reply())
    assert "not named anywhere" not in (page.regions[0].flagged or "")


def test_the_words_still_arrive_with_everything_off():
    """The point of the switch is to stop the bookkeeping, not the
    translation."""
    page = _page()
    translate_page(page, _ctx(story=False, name_speakers=False),
                   client=_reply())
    assert page.regions[0].dst_text == "I see, Ada."


# ------------------------------------------------------------ and the wiring

def test_an_old_project_keeps_its_story(tmp_path):
    """All four default ON, and a project.json written before they existed has
    no key at all. Reading a missing key as "off" would silently strip the
    character sheet out of every chapter already in progress."""
    import shutil
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "proj")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for k in ("story", "learn_characters", "learn_terms", "name_speakers"):
        assert p.settings[k] is True, k
        del p.settings[k]                       # as an older file would have it
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.story and p.ctx.learn_characters
    assert p.ctx.learn_terms and p.ctx.name_speakers


def test_the_settings_reach_the_context(tmp_path):
    import shutil
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "proj2")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.settings.update({"story": False, "learn_terms": False})
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.story is False and p.ctx.learn_terms is False
    assert p.ctx.learn_characters is True


def test_the_screen_has_a_switch_for_each_of_them():
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'data-sec="story"' in html
    for k in ("story", "learn_characters", "learn_terms", "name_speakers"):
        assert f'id="{k}"' in html, k
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "STORY_SWITCHES" in js
    # Read with `!== false`, never `!!`: a project.json that predates the
    # setting has no key, and `!!undefined` switches the story off.
    assert "proj.settings[k] !== false" in js
