"""The Claude or Google key first; the OpenRouter key when that fails.

lee: *"it shoud try to use the claude or google key first and it it sondt
work use teh open router key next"*.

Two ways for the first key to "not work", answered in two places:

* it is MISSING - known before any page runs, so `_ctx_from_settings`
  crosses the step over to OpenRouter on the spot, with the same model under
  the reseller's name;
* it is REFUSED by the provider - known only when a page fails, so
  `or_openrouter` catches the refusal, leaves a memo on the project, and
  runs the page again; every later page reads the memo and goes straight
  through the second door.

A step pointed at a local address is left alone: no key was ever the plan.
OpenRouter refusing is the end of the line - there is no third key.
"""
import shutil

import pytest

from mangatl import editor
from mangatl.editor import (_ctx_from_settings, fallback_key, needs_key,
                            openrouter_id, or_openrouter)
from mangatl.project import Project

import tempfile
ROOT = tempfile.mkdtemp(prefix="aside-")


@pytest.fixture
def p():
    shutil.rmtree(ROOT, ignore_errors=True)
    proj = Project(None, ROOT)
    yield proj
    shutil.rmtree(ROOT, ignore_errors=True)


# ------------------------------------------------------- the reseller's name

def test_the_model_keeps_its_identity_under_the_resellers_name():
    assert openrouter_id("anthropic", "claude-sonnet-5") == \
        "anthropic/claude-sonnet-5"
    assert openrouter_id("gemini", "gemini-3.7-flash") == \
        "google/gemini-3.7-flash"


def test_a_name_that_already_carries_its_maker_passes_through():
    assert openrouter_id("anthropic", "anthropic/claude-sonnet-5") == \
        "anthropic/claude-sonnet-5"


# --------------------------------------------------------- the missing key

def test_a_missing_google_key_crosses_to_openrouter(p):
    p.settings.update({"translate_backend": "gemini",
                       "translate_model": "gemini-3.7-flash",
                       "key_openrouter": "sk-or-x"})
    _ctx_from_settings(p, "translate")
    assert p.ctx.backend == "openrouter"
    assert p.ctx.model == "google/gemini-3.7-flash"
    assert p.ctx.api_key == "sk-or-x"


def test_the_companys_own_key_is_tried_first(p):
    p.settings.update({"translate_backend": "gemini",
                       "translate_model": "gemini-3.7-flash",
                       "key_gemini": "AIza-real",
                       "key_openrouter": "sk-or-x"})
    _ctx_from_settings(p, "translate")
    assert p.ctx.backend == "gemini"
    assert p.ctx.api_key == "AIza-real"


def test_with_no_openrouter_key_nothing_crosses(p):
    p.settings.update({"translate_backend": "anthropic",
                       "translate_model": "claude-sonnet-5"})
    _ctx_from_settings(p, "translate")
    assert p.ctx.backend == "anthropic"
    assert p.ctx.api_key == ""


def test_a_local_address_is_left_alone(p):
    """A base_url means somebody runs this model themselves - no key was
    ever the plan, and OpenRouter has no business in the middle."""
    p.settings.update({"translate_backend": "gemini",
                       "translate_model": "whatever",
                       "translate_base_url": "http://localhost:1234/v1",
                       "key_openrouter": "sk-or-x"})
    _ctx_from_settings(p, "translate")
    assert p.ctx.backend == "gemini"
    assert p.ctx.base_url == "http://localhost:1234/v1"


def test_needs_key_lets_a_run_start_on_the_fallback_alone(p):
    p.settings.update({"translate_backend": "anthropic",
                       "translate_model": "claude-sonnet-5",
                       "key_openrouter": "sk-or-x"})
    assert needs_key(p, "translate") == ""


def test_needs_key_still_blocks_with_no_key_anywhere(p):
    p.settings.update({"translate_backend": "anthropic",
                       "translate_model": "claude-sonnet-5"})
    assert "key" in needs_key(p, "translate")


# --------------------------------------------------------- the refused key

def _refusal():
    return RuntimeError(
        "the translation step's key was refused by the provider (HTTP 401)")


def test_a_refusal_runs_the_page_again_through_openrouter(p):
    p.settings.update({"translate_backend": "gemini",
                       "translate_model": "gemini-3.7-flash",
                       "key_gemini": "AIza-bad",
                       "key_openrouter": "sk-or-x"})
    calls = []

    def fn():
        _ctx_from_settings(p, "translate")
        calls.append((p.ctx.backend, p.ctx.model, p.ctx.api_key))
        if len(calls) == 1:
            raise _refusal()
        return "ok"

    assert or_openrouter(p, "translate", fn) == "ok"
    assert calls[0] == ("gemini", "gemini-3.7-flash", "AIza-bad")
    assert calls[1] == ("openrouter", "google/gemini-3.7-flash", "sk-or-x")


def test_the_memo_holds_for_the_pages_that_follow(p):
    p.settings.update({"translate_backend": "gemini",
                       "translate_model": "gemini-3.7-flash",
                       "key_gemini": "AIza-bad",
                       "key_openrouter": "sk-or-x"})
    boom = [True]

    def fn():
        _ctx_from_settings(p, "translate")
        if boom[0] and p.ctx.backend != "openrouter":
            raise _refusal()
        return p.ctx.backend

    assert or_openrouter(p, "translate", fn) == "openrouter"
    boom[0] = False
    # page two: no refusal needed, the memo already routes it
    _ctx_from_settings(p, "translate")
    assert p.ctx.backend == "openrouter"


def test_openrouter_refusing_is_the_end_of_the_line(p):
    """No third key, and no loop: a step already ON OpenRouter that gets a
    refusal surfaces it."""
    p.settings.update({"translate_backend": "openrouter",
                       "translate_model": "google/gemini-3.7-flash",
                       "key_openrouter": "sk-or-bad"})

    def fn():
        raise _refusal()

    with pytest.raises(RuntimeError):
        or_openrouter(p, "translate", fn)


def test_a_page_error_that_is_not_about_the_key_is_untouched(p):
    p.settings.update({"key_openrouter": "sk-or-x"})

    def fn():
        raise RuntimeError("the model refused this page: content")

    with pytest.raises(RuntimeError, match="refused this page"):
        or_openrouter(p, "translate", fn)
    assert "translate" not in getattr(p, "_openrouter_instead", set())


def test_a_failed_crossing_wipes_the_memo(p):
    """OpenRouter also failing must not pin the step there: a key fixed in
    Settings should be tried first again on the next run."""
    p.settings.update({"translate_backend": "gemini",
                       "translate_model": "g", "key_gemini": "k",
                       "key_openrouter": "sk-or-x"})

    def fn():
        raise _refusal()

    with pytest.raises(RuntimeError):
        or_openrouter(p, "translate", fn)
    assert "translate" not in p._openrouter_instead


def test_the_fallback_key_is_read_where_the_keys_live(p):
    p.settings["key_openrouter"] = "  sk-or-x  "
    assert fallback_key(p) == "sk-or-x"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
