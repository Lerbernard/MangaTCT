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
    assert editor.model_menu("gemini", "u", "KEY") == coins.offered("gemini")
    _reach(monkeypatch, ["nothing-we-have-ever-heard-of"])
    assert editor.model_menu("gemini", "u", "KEY") == coins.offered("gemini")


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
    assert editor.model_menu("gemini", "u", "") == coins.offered("gemini")
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


# ----------------------------------------------------------- the OpenRouter slugs

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


def test_every_openrouter_slug_is_written_out_and_every_vendor_is_stocked():
    """This used to be `len(...) == 10`, and every model lee asked for broke
    it without anything being wrong. A count is not a decision; these two are.

    First: the slug is an EXACT key, never prefix-matched. `qwen/qwen3.7-max`
    would happily land on a `qwen/qwen3.7` entry and be priced by luck, and
    the day the two prices part it is wrong and quiet — the same trap the
    Anthropic dotted slugs are held to just above.

    Second: every prefix in the openrouter family list actually stocks
    something. A vendor whose models are all dropped leaves a prefix behind
    that matches nothing, and the menu just gets quietly shorter.
    """
    slugs = coins.models_for("openrouter")
    for slug in slugs:
        assert slug in coins.RATES, slug
    for vendor in coins.FAMILIES["openrouter"]:
        assert any(s.startswith(vendor) for s in slugs), vendor


# ------------------------- and the bug lee found: a menu with one model in it

def test_the_menu_is_not_limited_to_the_slugs_written_down_here(monkeypatch):
    """lee, with a screenshot of an OpenRouter menu holding exactly one model:
    *"the other options are not showing up"*.

    The old crossing intersected the provider's listing with the ten slugs
    written into `coins.RATES`, so a key that could reach two hundred models
    was offered the one that happened to be on both lists. The ten are a PRICE
    TABLE, not a catalogue, and a catalogue is not a thing this app can keep up
    to date.
    """
    reach = ["google/gemini-2.5-flash", "google/gemini-2.5-pro",
             "google/gemini-3.1-pro", "anthropic/claude-haiku-4-5"]
    _reach(monkeypatch, reach)
    got = editor.model_menu("openrouter", "u", "KEY", "translate")
    assert sorted(got) == sorted(reach), got
    # ...and only two of those four are written into the table, which is the
    # whole point: the other two are priced through their maker's entry.
    assert len([m for m in reach if m in coins.RATES]) == 2


def test_a_model_nobody_can_price_is_still_kept_out(monkeypatch):
    """The half of the crossing that still matters. An unpriced model is
    charged at the top of the range the moment it is chosen."""
    _reach(monkeypatch, ["google/gemini-2.5-pro", "mistralai/mistral-large",
                         "x-ai/grok-3", "deepseek/deepseek-chat"])
    assert editor.model_menu("openrouter", "u", "KEY") == \
        ["google/gemini-2.5-pro"]


def test_a_retired_model_is_not_offered_under_its_slug_either(monkeypatch):
    """`claude-opus-4` is priced — somebody may still be on it — and not
    offered. Arriving with a vendor in front of it does not change that."""
    _reach(monkeypatch, ["anthropic/claude-opus-4", "anthropic/claude-opus-5"])
    assert editor.model_menu("openrouter", "u", "KEY") == \
        ["anthropic/claude-opus-5"]


def test_a_priced_variant_of_a_model_is_not_offered(monkeypatch):
    """OpenRouter sells the same model at several prices — `:free`, `:nitro`,
    `:floor` — and none of them is the price in the table. Quoting a `:free`
    variant at the paid rate overcharges; quoting a `:nitro` one at the
    standard rate is a bill this app eats."""
    _reach(monkeypatch, ["google/gemini-2.5-pro", "google/gemini-2.5-pro:free",
                         "google/gemini-2.5-pro:nitro"])
    assert editor.model_menu("openrouter", "u", "KEY") == \
        ["google/gemini-2.5-pro"]


def test_a_local_tag_full_of_colons_is_still_offered(monkeypatch):
    """`qwen2.5:14b-instruct` is a name, not a price variant. A model you run
    yourself costs nothing whichever tag you pick, so the rule that keeps
    variants out has nothing to protect here."""
    _reach(monkeypatch, ["qwen2.5:14b-instruct", "llama3.2:3b"])
    got = editor.model_menu("ollama", "http://localhost:11434/v1", "KEY")
    assert got == ["llama3.2:3b", "qwen2.5:14b-instruct"], got


def test_the_menu_still_opens_on_something_current(monkeypatch):
    """The price table's order first — it is newest-first and hand-kept — then
    whatever else the key can reach, by name. Sorted purely alphabetically the
    menu opens on the oldest model in the range, which is the one nobody wants
    and the one that gets picked by accident."""
    _reach(monkeypatch, ["google/gemini-2.5-flash-lite", "anthropic/claude-opus-5",
                         "google/gemini-3.6-flash"])
    got = editor.model_menu("openrouter", "u", "KEY")
    assert got[0] == "google/gemini-2.5-flash-lite"   # first in the table
    assert got[-1] == "anthropic/claude-opus-5"       # not in the table at all


# --------------------------- only what the API can actually be asked to do

def test_a_provider_list_is_not_a_list_of_translators(monkeypatch):
    """lee, with a screenshot of a menu holding `gemini-2.5-flash-preview-tts`,
    `gemini-3-pro-image` and `gemini-2.5-flash-native-audio-latest`: *"only
    keep the models that my api can aculy use"*.

    Every one of those answers `GET /models`, and not one of them can be
    handed a page and asked for JSON back.
    """
    _reach(monkeypatch, [
        "gemini-3.6-flash",
        "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-2.5-flash-native-audio-preview-12-2025",
        "gemini-3-pro-image", "gemini-3-pro-image-preview",
        "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image",
        "gemini-3.1-pro-preview-customtools", "gemini-3-flash-preview",
        "text-embedding-004",
    ])
    assert editor.model_menu("gemini", "u", "KEY") == ["gemini-3.6-flash"]


def test_a_preview_is_not_something_to_point_a_chapter_at(monkeypatch):
    """It is withdrawn without notice, which is the 404 this whole menu exists
    to prevent."""
    assert coins.usable_model("gemini-3-flash-preview") is False
    assert coins.usable_model("gemini-3-flash") is True


def test_the_word_has_to_be_a_whole_word():
    """Matched between the dashes, not as a substring: this list is going to
    grow, and a substring match on "live" would one day strike out a model
    called `deliverance`."""
    assert coins.usable_model("gemini-3.6-flash") is True
    assert coins.usable_model("claude-sonnet-5") is True
    assert coins.usable_model("some-audio-model") is False
    # ...and a vision model is the one thing Read text cannot do without.
    assert coins.usable_model("gemini-3.6-flash-vision") is True


# ------------------------------------------------------- and not too old

def test_one_generation_behind_is_the_limit():
    """lee: *"dont go for models taht are too old i generation behind shiud be
    teh limit like gpt 4, gmeini 2 etc"*.

    The whole of the newest major, plus the LAST minor of the one before it.
    Gemini keeps 3.x and 2.5 and drops 2.0, which is the line lee drew.
    """
    for ok in ("gemini-3.6-flash", "gemini-3-flash", "gemini-2.5-pro",
               "claude-opus-5", "claude-haiku-4-5"):
        assert coins.current_enough(ok), ok
    for old in ("gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-1.5-pro",
                "claude-opus-4", "claude-3-5-haiku"):
        assert not coins.current_enough(old), old


def test_the_line_is_read_off_the_price_table_not_off_a_date():
    """The table is what gets updated when a range moves, so the rule cannot
    drift out of step with it. Adding a Gemini 4 should retire Gemini 2.5 with
    no other edit anywhere."""
    assert coins.current_enough("gemini-2.5-pro")
    with_four = dict(coins.RATES)
    with_four["gemini-4-pro"] = coins.RATES["gemini-3.1-pro"]
    import unittest.mock as mock
    # Which 3.x survives is read off the table as well, rather than written
    # down here — the day a 3.8 lands this test follows it instead of failing
    # for a reason that has nothing to do with what it is asking.
    last3 = max(coins._version(k)[2] for k in with_four
                if coins._version(k) and coins._version(k)[:2] == ("gemini", 3))
    with mock.patch.object(coins, "RATES", with_four):
        assert coins.current_enough("gemini-3.%d-flash" % last3)
        # ...and the minor below it goes. That is the half of the rule that
        # actually retires anything, and nothing else here was asking for it.
        assert not coins.current_enough("gemini-3.%d-flash" % (last3 - 1))
        assert not coins.current_enough("gemini-2.5-pro")


def test_a_model_too_old_to_offer_is_still_priced():
    """Somebody may have it set. An UNPRICED model is charged at the top of
    the range, which is the wrong way for "we stopped recommending this" to
    fail."""
    for old in ("gemini-2.0-flash", "claude-opus-4", "gpt-4o"):
        assert coins.priced(old), old
        # Asked as "did it MATCH an entry", not as "is the rate different from
        # UNKNOWN" — `claude-opus-4` really does cost what the unknown
        # fallback costs, and a test written the other way calls that a
        # failure.
        assert coins._prefix(old) is not None, old
        assert old not in coins.offered("anthropic"), old
        assert old not in coins.offered("gemini"), old


def test_the_gpt_4_family_is_written_off_rather_than_worked_out():
    """There is no GPT-5 in the table for GPT-4 to be a generation behind OF,
    so the rule cannot see it and the set says so instead."""
    for m in ("gpt-4o", "gpt-4.1", "gpt-4o-mini"):
        assert m in coins.RETIRED, m


# ------------------------------------------------------ one per price band

def test_two_models_at_the_same_price_are_one_choice():
    """`gemini-2.5-flash` and `gemini-3.5-flash-lite` cost exactly the same.
    Offering both asks somebody to decide something with no consequence they
    can see."""
    same = coins.rate_for("gemini-2.5-flash") == coins.rate_for("gemini-3.5-flash-lite")
    assert same, "the fixture for this test has stopped being true"
    got = coins.one_per_price(["gemini-3.5-flash-lite", "gemini-2.5-flash"])
    assert got == ["gemini-3.5-flash-lite"], "the first one wins"
    assert coins.one_per_price(["gemini-2.5-flash", "gemini-3.5-flash-lite"]) \
        == ["gemini-2.5-flash"]


def test_the_trim_happens_after_the_reachable_check(monkeypatch):
    """So a price band is never emptied by trimming away the only model in it
    this key can run. lee cannot use `gemini-3.5-flash-lite`; he must still be
    offered something at that price."""
    _reach(monkeypatch, ["gemini-2.5-flash"])
    assert editor.model_menu("gemini", "u", "KEY") == ["gemini-2.5-flash"]
    assert "gemini-2.5-flash" not in coins.offered("gemini"), \
        "and it is NOT what the written-down menu would have offered"
    # ...and it really does still happen. Both of these cost the same, so one
    # of them has to go — after the reachable check, not instead of it.
    _reach(monkeypatch, ["gemini-2.5-flash", "gemini-3.5-flash-lite"])
    editor._MENU_CACHE.clear()
    assert editor.model_menu("gemini", "u", "KEY") == ["gemini-3.5-flash-lite"]


def test_every_price_on_the_menu_is_a_different_price():
    for back in ("anthropic", "gemini"):
        rates = [coins.rate_for(m) for m in coins.offered(back)]
        assert len(rates) == len(set(rates)), back


# ------------------------------- openrouter is for what your keys cannot reach

def test_openrouter_drops_what_your_own_key_already_runs(monkeypatch):
    """lee: *"exclue teh molde that are usabe with teh keys that i have for
    example i cnat use gemeini 2.5 flash with my goohle key so it shoud be in
    teh open router"*.

    Asked of the KEYS, not of a table. A model your Google key can already run
    is not a thing to buy through a reseller.
    """
    _reach(monkeypatch, ["google/gemini-3.6-flash", "google/gemini-2.5-flash",
                         "deepseek/deepseek-v3.2"])
    direct = ["gemini-3.6-flash"]            # what his Google key really lists
    got = editor.model_menu("openrouter", "u", "KEY", "translate", direct)
    assert "google/gemini-3.6-flash" not in got, "he can already run that one"
    assert "google/gemini-2.5-flash" in got, "and this is what OpenRouter is FOR"
    assert "deepseek/deepseek-v3.2" in got


def test_with_no_key_of_your_own_openrouter_offers_everything(monkeypatch):
    """The same rule reaching the opposite answer: nothing is subtracted,
    because there is no other way to any of it."""
    _reach(monkeypatch, ["google/gemini-3.6-flash", "deepseek/deepseek-v3.2"])
    got = editor.model_menu("openrouter", "u", "KEY", "translate", [])
    assert "google/gemini-3.6-flash" in got


def test_only_openrouter_subtracts(monkeypatch):
    """A direct service is not a reseller and has nothing to defer to."""
    _reach(monkeypatch, ["gemini-3.6-flash"])
    assert editor.model_menu("gemini", "u", "KEY", "translate",
                             ["gemini-3.6-flash"]) == ["gemini-3.6-flash"]


# -------------------------------------------- the range lee asked to be added

def test_gemini_3_7_flash_is_on_both_of_its_menus():
    """lee: *"google 3.7 flash is availbel add that to the list of goodle
    ais"*. It is sold two ways — straight from Google and resold through
    OpenRouter — and a model added to one menu and not the other is a model
    half the app cannot be pointed at."""
    assert "gemini-3.7-flash" in coins.offered("gemini")
    assert "google/gemini-3.7-flash" in coins.offered("openrouter")
    assert coins.rate_for("google/gemini-3.7-flash") == \
        coins.rate_for("gemini-3.7-flash"), "the reseller does not mark it up"


def test_the_launch_rate_is_not_what_gets_written_down():
    """lee: *"no promotianal rate us teh normal rate"*.

    Gemini 3.7 Flash opened at half price through 2026. Writing the discount
    down means every estimate in the app is half of what the chapter will
    actually cost from the day the promotion ends — and nothing would tell
    anybody, because the number would not change.
    """
    r = coins.rate_for("gemini-3.7-flash")
    assert (r.inp, r.out) == (1.50, 7.50)
    assert (r.inp, r.out) != (0.75, 3.75), "that is the introductory rate"


def test_3_7_takes_the_price_band_off_3_6():
    """They cost exactly the same, so `one_per_price` keeps whichever it meets
    first and the table's order is what decides. This is the one place in that
    block where the order of two lines carries a decision, which is why it is
    asked out loud rather than left to be noticed."""
    assert coins.rate_for("gemini-3.7-flash") == coins.rate_for("gemini-3.6-flash")
    assert "gemini-3.6-flash" not in coins.offered("gemini")
    assert "google/gemini-3.6-flash" not in coins.offered("openrouter")
    # ...but it is still PRICED. Somebody may have had it set since yesterday,
    # and an unpriced model is billed at the top of the range.
    assert coins.priced("gemini-3.6-flash")
    assert coins.rate_for("gemini-3.6-flash") != coins.UNKNOWN


def test_the_openai_and_qwen_ranges_reached_the_openrouter_menu():
    """lee: *"add some open ai and quen models to teh open router lsit"*.

    OpenAI is not one of this app's three services — there is no OpenAI key
    box on the settings screen — so OpenRouter is the only door these come
    through, and the slugs have to be written down for them to be priced.
    """
    menu = coins.offered("openrouter", "translate")
    for m in ("openai/gpt-5.6-sol", "openai/gpt-5.6-terra", "openai/gpt-5.6-luna",
              "qwen/qwen3.7-max", "qwen/qwen3.7-plus", "qwen/qwen3.7-flash"):
        assert m in menu, m
        assert coins.rate_for(m) != coins.UNKNOWN, m


def test_the_one_of_them_that_cannot_see_is_kept_off_the_read_text_menu():
    """lee: *"make sure only taht suport iage eai show up in the red etx
    list"*.

    Qwen 3.7 Max is the trap in this batch: its two smaller siblings take
    pictures and it does not, so a rule written per-VENDOR would have offered
    it. `NO_SIGHT` names the model, not the maker.
    """
    assert not coins.sees("qwen/qwen3.7-max")
    assert coins.sees("qwen/qwen3.7-plus") and coins.sees("qwen/qwen3.7-flash")
    ocr = coins.offered("openrouter", "ocr")
    assert "qwen/qwen3.7-max" not in ocr
    assert "qwen/qwen3.7-plus" in ocr and "qwen/qwen3.7-flash" in ocr
    # ...and it is still offered for the steps that are only ever handed text.
    assert "qwen/qwen3.7-max" in coins.offered("openrouter", "translate")


def test_nothing_at_all_on_the_read_text_menu_is_blind():
    """The whole menu, not the models this batch happened to add — a slug put
    in tomorrow is caught by this and by nothing else."""
    for back in ("gemini", "anthropic", "openrouter"):
        for m in coins.offered(back, "ocr"):
            assert coins.sees(m), (back, m)


# ------------------------------------------------- the maker menu, on screen

def test_the_screen_has_a_maker_menu_beside_the_model_one():
    """lee: *"when its selected create s seperate drop down for the
    providers"*. A reseller's list is a hundred models from a dozen makers,
    and picking one out of a flat list of that is not a choice, it is a
    search."""
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    for step in ("ocr", "translate", "proofread"):
        assert f'id="{step}_vendor"' in html, step
        assert f"pickVendor(\'{step}\')" in html, step
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "function pickVendor" in js and "function vendorOf" in js


# ------------------------------------------ the mutation runner's own safety

def test_the_mutation_runner_refuses_to_start_on_a_leftover(tmp_path,
                                                            monkeypatch):
    """A run killed part-way never reaches its `finally`, and the mutant it
    was holding stays on disk. Everything measured afterwards is measured
    against it, silently — one such leftover sat in `static/editor.html` for
    an hour and turned the coin in the top bar into a plain yellow disc, and
    nothing said a word until a test that happened to look at the coin failed.
    """
    import importlib.util
    import io
    import contextlib
    from where import PKG

    spec = importlib.util.spec_from_file_location(
        "mutrun", PKG / "tools" / "mutate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # A mutant whose ORIGINAL is missing from the file and whose REPLACEMENT
    # is present — which is exactly what a killed run leaves behind.
    f = tmp_path / "left.py"
    f.write_text("the mutated line\n", encoding="utf-8")
    monkeypatch.setattr(mod, "PKG", tmp_path)
    monkeypatch.setattr(mod, "MUTANTS", [
        ("x-left-behind", "left.py", "the real line", "the mutated line", [])])
    monkeypatch.setattr(mod.sys, "argv", ["mutate.py"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = mod.main()
    assert rc == 2
    assert "REFUSING TO RUN" in out.getvalue()
    assert "x-left-behind" in out.getvalue()
    # ...and it did not touch the file on its way out.
    assert f.read_text(encoding="utf-8") == "the mutated line\n"


def test_the_runner_starts_when_the_files_are_clean(tmp_path, monkeypatch):
    """The other half: a guard that always refuses is a guard nobody can
    use."""
    import importlib.util
    import io
    import contextlib
    from where import PKG

    spec = importlib.util.spec_from_file_location(
        "mutrun2", PKG / "tools" / "mutate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = tmp_path / "clean.py"
    f.write_text("the real line\n", encoding="utf-8")
    monkeypatch.setattr(mod, "PKG", tmp_path)
    monkeypatch.setattr(mod, "MUTANTS", [
        ("x-fine", "clean.py", "the real line", "the mutated line", [])])
    monkeypatch.setattr(mod, "run", lambda tests: (False, ""))
    monkeypatch.setattr(mod.sys, "argv", ["mutate.py"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = mod.main()
    assert rc == 0
    assert "REFUSING" not in out.getvalue()
    # ...and it put the file back.
    assert f.read_text(encoding="utf-8") == "the real line\n"
