"""Each AI step asks two questions: the company, then the model.

lee: *"for te ai for teh trasnlationa dn profredding i just wan the ai
compay and teh ai model"*, then *"for the translation sinatsd of otrher it
shodu be open deepsek quwen etc"* - so the company menu names the makers
themselves. Claude and Google are their own services; every other maker is
bought through OpenRouter, and the model menu narrows to that maker.

The company menu is NOT a stored setting: what is saved is the same
backend/model pair every old project already carries, so nothing migrates
and nothing can be lost by opening a chapter in the new screen.
"""
import re

import pytest

from where import EDITOR_HTML, JS, PKG

HTML = EDITOR_HTML.read_text(encoding="utf-8")
PJS = (JS / "project.js").read_text(encoding="utf-8")


def test_each_step_asks_company_then_model():
    for step in ("ocr", "translate", "proofread"):
        at = HTML.index(f'id="{step}_company"')
        assert "AI company" in HTML[at - 700:at], step
        assert "AI model" in HTML[at:at + 1400], step


def test_the_companies_are_the_makers_themselves():
    """Not "Other". lee named three, and then trimmed the tail of the list -
    *"remove thses from the lists"* - so Mistral, Meta, xAI and the catch-all
    "Any provider" came off it."""
    for step in ("ocr", "translate", "proofread"):
        at = HTML.index(f'id="{step}_company"')
        menu = HTML[at:HTML.index("</select>", at)]
        for co in ('value="claude"', 'value="google"', 'value="openai"',
                   'value="deepseek"', 'value="qwen"'):
            assert co in menu, (step, co)
        for gone in ('value="mistralai"', 'value="meta-llama"',
                     'value="x-ai"', 'value="*"'):
            assert gone not in menu, (step, gone)


def test_a_project_on_a_maker_that_left_the_menu_still_says_which():
    """Otherwise a chapter already running on Mistral opens a menu with
    nothing selected, which reads as "no model chosen" for a step that has
    one. `syncCompany` puts the answer back for as long as it IS the
    answer."""
    body = PJS.split("function syncCompany(step)", 1)[1].split("\n}", 1)[0]
    assert "createElement('option')" in body
    assert "co.options" in body


def test_claude_and_google_are_their_own_services():
    """`pickCompany` writes the backend: the two direct services by name,
    everyone else through OpenRouter."""
    at = PJS.index("const COMPANY_BACKEND")
    assert "claude: 'anthropic'" in PJS[at:at + 120]
    assert "google: 'gemini'" in PJS[at:at + 120]
    at = PJS.index("async function pickCompany")
    assert "|| 'openrouter'" in PJS[at:at + 400]


def test_what_is_saved_is_the_pair_it_always_was():
    """The backend travels as a hidden input with the same id, so
    `saveSettings` and every server path read exactly what they always
    read - and the company menu is derived from it on load."""
    for step in ("ocr", "translate", "proofread"):
        assert f'<input id="{step}_backend" type="hidden"' in HTML, step
    assert "function companyOf" in PJS
    assert "syncCompany" in PJS


def test_the_maker_menu_narrows_to_the_company():
    """On OpenRouter the old maker filter still does the narrowing - locked
    off screen, because the company menu is the one asking now."""
    for step in ("ocr", "translate", "proofread"):
        m = re.search(rf'id="{step}_vendor" data-locked="1"', HTML)
        assert m, step
    assert "ven.dataset.locked ? 'none' : ''" in PJS


def test_the_screen_is_named_for_what_it_sets():
    assert ">AI models</h2>" in HTML
    assert 'onclick="setSettingsTab(\'translation\')">AI models<' in HTML
    t = (PKG / "translate.py").read_text(encoding="utf-8")
    assert "Settings → AI models" in t


def test_the_nav_walks_the_pipeline():
    order = [HTML.index(f'data-sec="{k}" onclick="setSettingsTab')
             for k in ("language", "detection", "translation",
                       "cleaning", "fonts")]
    assert order == sorted(order)


def test_the_odd_endpoint_box_is_off_the_screen_but_not_gone():
    for step in ("ocr", "translate", "proofread"):
        assert f'<input id="{step}_base_url" type="hidden"' in HTML, step


def test_there_are_no_key_boxes_left_on_the_page():
    """lee: *"remove tehh keys they shoud happen in te backend and remove teh
    text"*. The keys are still READ from a project that carries them - nothing
    that was working stops - there is just nowhere to type one."""
    assert "API KEYS" not in HTML
    for svc in ("anthropic", "gemini", "openrouter"):
        assert f'id="key_{svc}"' not in HTML, svc
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert "def key_for(" in src, "reading them is unchanged"


def test_the_button_strips_are_gone_again():
    """lee tried them and asked for the menus back: *"im not liking the
    button back to drop downs pls"*."""
    assert "segify" not in PJS
    assert "buildSegs" not in PJS
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".seg button" not in css


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
