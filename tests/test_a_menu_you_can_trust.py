"""The menu offers what can be PAID FOR and what the key can REACH.

lee opened Settings, chose `gemini-2.5-flash` out of the menu, and got a 404:
the model was not enabled on his Google project. The cause was not the model.
`/api/models` answered `coins.models_for(back)` — the models this app can
PRICE — and never asked the provider what the key could actually see.

Both halves are needed, and each one alone is a different fault:

* offer what cannot be priced, and the step silently runs at the top rate
* offer what cannot be reached, and you get the 404
"""
import pytest

from mangatl import coins, editor
from mangatl.project import SERVICES


@pytest.fixture(autouse=True)
def _cold():
    editor._MENU_CACHE.clear()
    yield
    editor._MENU_CACHE.clear()


def _reach(monkeypatch, names):
    seen = []

    def fake(url, key, **kw):
        seen.append((url, key))
        return list(names)
    monkeypatch.setattr("mangatl.translate.list_models", fake)
    return seen


# --------------------------------------------------------------- the crossing

def test_the_menu_is_the_priced_list_crossed_with_the_reachable_one(monkeypatch):
    _reach(monkeypatch, ["gemini-3.6-flash", "gemini-2.5-pro", "some-other"])
    got = editor.model_menu("gemini", "http://x", "KEY")
    assert got == ["gemini-3.6-flash", "gemini-2.5-pro"]
    # in the price table's order, which is newest first — not the provider's
    assert got == [m for m in coins.models_for("gemini") if m in got]


def test_a_model_the_key_cannot_reach_is_not_offered(monkeypatch):
    """lee's 404, at the menu instead of four minutes into a chapter."""
    _reach(monkeypatch, ["gemini-3.6-flash"])
    assert "gemini-2.5-flash" not in editor.model_menu("gemini", "u", "KEY")


def test_a_model_that_cannot_be_priced_is_not_offered(monkeypatch):
    """It would put the step on the top of the range the moment it was chosen,
    and the person choosing it would have no way to know."""
    _reach(monkeypatch, ["gemini-3.6-flash", "gemini-experimental-0918"])
    for m in editor.model_menu("gemini", "u", "KEY"):
        assert coins.priced(m, "gemini"), m


def test_an_empty_crossing_leaves_the_priced_list_standing(monkeypatch):
    """A key with no listing permission, a provider answering an unexpected
    shape, a network that is down. None of those mean the person has no
    models, and an empty menu is a step nobody can configure — which is worse
    than the fault it was trying to report."""
    _reach(monkeypatch, [])
    assert editor.model_menu("gemini", "u", "KEY") == coins.models_for("gemini")
    _reach(monkeypatch, ["nothing-we-have-ever-heard-of"])
    assert editor.model_menu("gemini", "u", "KEY") == coins.models_for("gemini")


def test_read_text_only_offers_models_that_can_see_a_picture(monkeypatch):
    """A text-only model chosen for OCR is the same 404 one step later,
    arriving through a different door."""
    _reach(monkeypatch, [])
    ocr = editor.model_menu("openrouter", "u", "KEY", step="ocr")
    every = editor.model_menu("openrouter", "u", "KEY", step="translate")
    assert "deepseek/deepseek-v4-flash" in every
    assert "deepseek/deepseek-v4-flash" not in ocr
    for m in ocr:
        assert coins.sees(m), m


# ------------------------------------------------------- and what it asks for

def test_nothing_is_asked_for_when_there_is_no_key(monkeypatch):
    """All three services refuse `GET /models` without one, so the request
    could only ever time out — three times, every time Settings opened."""
    seen = _reach(monkeypatch, ["gemini-3.6-flash"])
    assert editor.model_menu("gemini", "u", "") == coins.models_for("gemini")
    assert seen == []


def test_the_answer_is_remembered_for_a_while(monkeypatch):
    seen = _reach(monkeypatch, ["gemini-3.6-flash"])
    for _ in range(4):
        editor.model_menu("gemini", "u", "KEY")
    assert len(seen) == 1, seen
    # ...per key and address, not per step: two steps on one service ask once
    # between them, and a key that changes asks again.
    editor.model_menu("gemini", "u", "KEY", step="ocr")
    assert len(seen) == 1
    editor.model_menu("gemini", "u", "ANOTHER")
    assert len(seen) == 2


def test_the_answer_stops_being_worth_reusing(monkeypatch):
    """Fifteen minutes, not for ever. A key that has just been given access to
    a model must not stay locked out of the menu for the afternoon — and the
    reason the window can be this long at all is that saving the settings
    clears the whole cache anyway."""
    seen = _reach(monkeypatch, ["gemini-3.6-flash"])
    editor.model_menu("gemini", "u", "KEY")
    assert len(seen) == 1
    monkeypatch.setattr(editor, "MENU_TTL", 0)
    editor.model_menu("gemini", "u", "KEY")
    assert len(seen) == 2, "a stale answer was reused for ever"


def test_the_key_itself_is_never_the_cache_key(monkeypatch):
    """It is hashed. A dict of live API keys in a module global is a dict of
    live API keys in every traceback and every heap dump."""
    _reach(monkeypatch, ["gemini-3.6-flash"])
    editor.model_menu("gemini", "u", "sk-secret-value")
    assert "sk-secret-value" not in repr(editor._MENU_CACHE)


def test_saving_the_settings_forgets_what_the_old_key_could_reach(monkeypatch):
    """The moment the cache would otherwise be most wrong."""
    seen = _reach(monkeypatch, ["gemini-3.6-flash"])
    editor.model_menu("gemini", "u", "KEY")
    editor._MENU_CACHE.clear()
    editor.model_menu("gemini", "u", "KEY")
    assert len(seen) == 2
    src = (__import__("pathlib").Path(editor.__file__)).read_text("utf-8")
    assert "_MENU_CACHE.clear()" in src


# -------------------------------------------------------------- three services

def test_three_services_and_the_screen_agrees_with_the_server():
    """A service the screen offers and the server does not know is a step
    nobody can run, and it fails at the provider rather than at the menu."""
    import re
    from where import PKG
    assert SERVICES == tuple(s for s, _ in editor.SERVICES)
    assert set(SERVICES) == set(coins.FAMILIES)
    assert set(SERVICES) == set(editor.NEEDS_KEY)
    js = (PKG / "static" / "js" / "project.js").read_text("utf-8")
    m = re.search(r"const SERVICES = \[([^\]]*)\]", js)
    assert m, "project.js must name the services it offers"
    assert [s.strip().strip("'\"") for s in m.group(1).split(",")] == \
        list(SERVICES)


def test_the_gone_services_are_gone_from_the_menus():
    """OpenAI, Groq, Cerebras and Ollama. Each was a menu with nothing behind
    it that anybody here had priced or tested."""
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text("utf-8")
    for dead in ("openai", "groq", "cerebras", "ollama"):
        assert f'<option value="{dead}"' not in html, dead


def test_an_old_project_on_a_gone_service_is_still_priced():
    """It is on disk and somebody may still run it. An UNPRICED model is
    charged at the top of the range, which is the wrong way for this to fail."""
    for m in ("gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"):
        assert coins.priced(m), m
        assert coins.rate_for(m) != coins.UNKNOWN, m


# --------------------------------------------------------- the ten OpenRouter slugs

def test_openrouter_costs_what_the_provider_costs():
    """OpenRouter does not mark tokens up — the slug's rate is the provider's
    own published rate, and its money comes off the top-up instead. So a rate
    change that misses one of the two is caught here rather than charged."""
    for slug in coins.models_for("openrouter"):
        direct = coins.vendor_free(slug)
        if coins.priced(direct) and coins._prefix(direct):
            assert coins.rate_for(slug) == coins.rate_for(direct), slug


def test_the_anthropic_slugs_are_written_out_and_not_guessed():
    """They carry DOTS where the direct ids carry dashes — `claude-haiku-4.5`
    against `claude-haiku-4-5` — so the prefix matcher lands them on the
    `claude-haiku-4` entry and prices them right today by luck. One price
    change and it would be wrong, and quiet."""
    assert "anthropic/claude-haiku-4.5" in coins.RATES
    assert "anthropic/claude-sonnet-5" in coins.RATES
    assert coins.rate_for("anthropic/claude-haiku-4.5") == \
        coins.rate_for("claude-haiku-4-5")


def test_ten_of_them():
    assert len(coins.models_for("openrouter")) == 10
