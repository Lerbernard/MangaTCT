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


# ------------------------------------------- and Read text asks it of sighted
#
# lee, at a Read text menu offering DeepSeek: *"for thsi only visin caplabel
# models hsoud show up"*. The MODEL menu was already filtered - `coins.offered`
# and `editor.model_menu` both ask `sees` when the step is ocr - and the
# COMPANY menu above it was not, so the way to a dead end was still one click
# from the top of the panel.


def test_the_makers_with_no_eyes_are_named_by_the_server():
    """Off `sees`, so `NO_SIGHT` stays the only list of blind models."""
    from mangatl import coins
    assert coins.blind_makers() == ["deepseek"]


def test_a_maker_with_one_sighted_model_stays():
    """Qwen's range is mixed - 3.7 Max is text-only, Flash and Plus read a
    page - and a maker is only blind when ALL of it is."""
    from mangatl import coins
    assert "qwen" not in coins.blind_makers()
    assert not coins.sees("qwen/qwen3.7-max")
    assert coins.sees("qwen/qwen3.7-flash")


def test_every_row_of_the_menu_is_a_maker_the_table_knows():
    """The join between a menu row and the price table. A row nothing matches
    can never be found blind, which is the failure this pairing exists to
    stop - so the two lists are checked against each other."""
    from mangatl import coins
    at = HTML.index('id="ocr_company"')
    menu = HTML[at:HTML.index("</select>", at)]
    rows = set(re.findall(r'<option value="([^"]+)"', menu))
    assert rows == set(coins.MAKER_MODELS)
    for maker, pre in coins.MAKER_MODELS.items():
        assert any(m.startswith(pre) for m in coins.RATES), maker


def test_the_answer_travels_with_the_project():
    """Sent rather than written into the browser, for the same reason
    `tall_aspect` is: a second copy of the list is a menu still offering a
    blind maker the day the first one changes."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert '"blind_makers": _coins.blind_makers()' in src
    assert "proj.blind_makers" in PJS


def test_only_read_text_drops_them():
    """Translate and proofread are text jobs: every maker still reads."""
    body = PJS.split("function syncCompany(step)", 1)[1].split("\n}\n", 1)[0]
    assert "step === 'ocr'" in body
    assert "blind.includes(o.value)" in body
    for step in ("translate", "proofread"):
        at = HTML.index(f'id="{step}_company"')
        assert 'value="deepseek"' in HTML[at:HTML.index("</select>", at)], step


def test_a_hidden_row_cannot_be_chosen_from_the_keyboard():
    """`hidden` alone still leaves the option reachable with the arrow keys in
    some browsers, and `[hidden]` is only a UA rule - one author `display`
    beats it. All three, or the row is only half gone."""
    body = PJS.split("function syncCompany(step)", 1)[1].split("\n}\n", 1)[0]
    for said in ("o.hidden = hide", "o.disabled = hide", "o.style.display"):
        assert said in body, said


def test_the_maker_a_step_is_actually_on_is_never_hidden():
    """Taking a step's own maker off its menu is the "no model chosen" bug
    two tests up, arriving from the other side: the menu would read empty for
    a project that has an answer."""
    body = PJS.split("function syncCompany(step)", 1)[1].split("\n}\n", 1)[0]
    assert "o.value !== now" in body


def test_the_button_strips_are_gone_again():
    """lee tried them and asked for the menus back: *"im not liking the
    button back to drop downs pls"*."""
    assert "segify" not in PJS
    assert "buildSegs" not in PJS
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".seg button" not in css


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
