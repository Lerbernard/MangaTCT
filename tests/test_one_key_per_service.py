"""A key is a fact about the provider, not about the step.

The same Google key that reads the page translates it. Three boxes meant
typing it twice and, worse, meant a key could be right in one and stale in the
other with nothing on screen to say which of the two a run would use.
"""
import json
import shutil

import pytest

from mangatl import editor
from mangatl.project import Project, SERVICES, migrate_keys


def _proj(tmp_path):
    root = str(tmp_path / "proj")
    shutil.rmtree(root, ignore_errors=True)
    return Project(None, root)


# ---------------------------------------------------------------- key_for

def test_the_service_box_is_the_answer(tmp_path):
    p = _proj(tmp_path)
    p.settings["key_gemini"] = "SERVICE"
    assert editor.key_for(p, "gemini") == "SERVICE"


def test_a_leftover_step_key_is_only_reached_for_when_the_box_is_empty(tmp_path):
    """So a key that has been moved cannot be countermanded by a stale copy
    nobody can see on screen."""
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_key": "OLD"})
    assert editor.key_for(p, "gemini") == "OLD"
    p.settings["key_gemini"] = "NEW"
    assert editor.key_for(p, "gemini") == "NEW"


def test_a_leftover_key_is_only_used_on_the_service_it_was_typed_for(tmp_path):
    """A per-step key belongs to whatever provider that step was pointed at
    when it was typed. Handing it to a different one because the step has since
    been switched is sending Google a Claude key."""
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "anthropic", "translate_key": "ANT"})
    assert editor.key_for(p, "anthropic") == "ANT"
    assert editor.key_for(p, "gemini") == ""


def test_no_key_at_all_is_an_empty_string(tmp_path):
    p = _proj(tmp_path)
    for svc in SERVICES:
        assert editor.key_for(p, svc) == ""
    assert editor.key_for(p, "") == ""


def test_every_step_on_a_service_shares_its_key(tmp_path):
    p = _proj(tmp_path)
    p.settings["key_gemini"] = "ONE"
    for step in editor.AI_STEPS:
        p.settings[f"{step}_backend"] = "gemini"
        assert editor.key_for(p, "gemini", step) == "ONE", step


# --------------------------------------------------------------- the migration

def test_an_old_project_has_its_step_keys_lifted(tmp_path):
    saved = {"translate_backend": "gemini", "translate_key": "G",
             "proofread_backend": "anthropic", "proofread_key": "A"}
    settings = dict(saved)
    assert migrate_keys(settings, saved) is True
    assert settings["key_gemini"] == "G"
    assert settings["key_anthropic"] == "A"


def test_a_service_key_that_has_been_changed_since_is_never_overwritten(tmp_path):
    """The whole point of moving them is that the service box is now the
    answer. A migration that could undo an edit is a migration that runs every
    load and quietly puts the old key back."""
    saved = {"translate_backend": "gemini", "translate_key": "OLD",
             "key_gemini": "CURRENT"}
    settings = dict(saved)
    assert migrate_keys(settings, saved) is False
    assert settings["key_gemini"] == "CURRENT"


def test_a_step_on_a_service_this_app_no_longer_offers_is_left_alone():
    saved = {"translate_backend": "groq", "translate_key": "G"}
    settings = dict(saved)
    assert migrate_keys(settings, saved) is False
    assert not any(k.startswith("key_") for k in settings)


def test_an_old_project_json_that_has_not_been_saved_since_still_works(tmp_path):
    """Read off disk, migrated on load, and the run finds its key either way -
    the per-step boxes are not deleted, because a key is the one setting in
    here it would be rude to throw away on the strength of a migration."""
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_key": "FROMDISK"})
    p.save()
    raw = json.load(open(p.state_path, encoding="utf-8"))
    assert raw["settings"]["translate_key"] == "FROMDISK"
    again = Project(None, p.output_dir)
    assert again.settings["key_gemini"] == "FROMDISK"
    assert editor.key_for(again, "gemini") == "FROMDISK"


# ------------------------------------------------------------- and on screen

def test_a_run_with_no_key_says_which_service_to_put_one_in(tmp_path):
    """One key serves all three steps now, so "put a key next to Translate"
    would send somebody looking for a box that is not there any more."""
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "translate_key": "",
                       "translate_model": "gemini-3.6-flash"})
    said = editor.needs_key(p, "translate")
    assert "Google AI Studio" in said
    assert "API keys" in said
    p.settings["key_gemini"] = "K"
    assert editor.needs_key(p, "translate") == ""


def test_the_context_a_run_uses_is_pointed_at_the_service_key(tmp_path):
    p = _proj(tmp_path)
    p.settings.update({"translate_backend": "gemini", "key_gemini": "SERVICE",
                       "translate_key": "STALE"})
    editor._ctx_from_settings(p, "translate")
    assert p.ctx.api_key == "SERVICE"


def test_a_key_is_never_sent_back_to_the_browser(tmp_path):
    """Masked the same way the per-step ones were: "set" or nothing."""
    p = _proj(tmp_path)
    p.settings["key_openrouter"] = "sk-or-secret"
    p.save()
    blob = json.dumps(p.summary())
    assert "sk-or-secret" not in blob
    assert p.summary()["settings"]["key_openrouter"] == "set"
    # ...and the ones nobody has typed come back empty rather than absent, so
    # the screen can tell "saved" from "not set" without guessing.
    assert p.summary()["settings"]["key_gemini"] == ""
