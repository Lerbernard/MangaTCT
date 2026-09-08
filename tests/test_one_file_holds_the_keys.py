# -*- coding: utf-8 -*-
"""Four keys, one file, every chapter.

lee, three messages in a row::

    they key shoud be in the .env file and all teh project shoud use them
    also all the key i need to put ius claude gemini open router and clenner
    make evrything that needs ai read from teh .env

So: a `.env` beside the fonts and the prefs, holding `MANGATL_ANTHROPIC_KEY`,
`MANGATL_GEMINI_KEY`, `MANGATL_OPENROUTER_KEY` and `MANGATL_CLEAN_TOKEN`, read
by every chapter, and beating whatever a chapter has saved in itself.

**Why it BEATS rather than fills in.** A project.json can hold the literal
word `set` in a key field - the mask, handed back by a `.tct` import and saved
over the key it stood in for. lee's own live chapter holds five. A `.env` that
only filled empty fields would lose to that string and the call would go out
with `set` as its key, which is the error he has already read once. So the
file wins outright, and the test at the bottom of this module is that exact
chapter.

**Why the process environment is only half trusted.** The generic names are
read out of the FILE - somebody who keeps an `ANTHROPIC_API_KEY` line in a
`.env` for their own scripts should not need a second copy under a second
name. They are NOT read out of the environment: `GOOGLE_API_KEY` is exported
on a lot of machines for a lot of reasons, and a chapter quietly spending
whatever that one pays for, with nothing on screen saying so, is worse than a
chapter that says no key is set. `MANGATL_*` is read from both, because that
name can only ever have been set for this app.
"""
import os

import pytest

from mangatl import editor, project as project_mod, userdata
from mangatl.project import Project


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A `.env` of our own, and a writer for it."""
    path = tmp_path / "keys.env"
    monkeypatch.setenv("MANGATL_ENV", str(path))
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))

    def write(text):
        path.write_text(text, encoding="utf-8")
        return str(path)
    write.path = str(path)
    return write


@pytest.fixture
def proj(tmp_path):
    return Project(None, str(tmp_path / "out"))


# ------------------------------------------------------------------- reading

def test_the_four_keys_lee_named(env, proj):
    """Claude, Gemini, OpenRouter, cleaner. His list, in one file."""
    env("MANGATL_ANTHROPIC_KEY=ant-one\n"
        "MANGATL_GEMINI_KEY=gem-two\n"
        "MANGATL_OPENROUTER_KEY=or-three\n"
        "MANGATL_CLEAN_TOKEN=clean-four\n")
    assert editor.key_for(proj, "anthropic") == "ant-one"
    assert editor.key_for(proj, "gemini") == "gem-two"
    assert editor.key_for(proj, "openrouter") == "or-three"
    assert editor.clean_token_for(proj) == "clean-four"
    # ...and nothing else answers, so a fifth service cannot be picked up by
    # accident from a name that happens to be in the file.
    assert editor.key_for(proj, "openai") == ""


def test_every_chapter_reads_the_same_file(env, tmp_path):
    """"all teh project shoud use them" - two chapters, one key."""
    env("MANGATL_GEMINI_KEY=shared\n")
    a = Project(None, str(tmp_path / "chapter1"))
    b = Project(None, str(tmp_path / "chapter2"))
    assert editor.key_for(a, "gemini") == "shared"
    assert editor.key_for(b, "gemini") == "shared"


def test_the_file_beats_what_the_chapter_saved(env, proj):
    """The rule that makes one file worth having."""
    proj.settings["key_gemini"] = "the-old-one"
    env("MANGATL_GEMINI_KEY=the-new-one\n")
    assert editor.key_for(proj, "gemini") == "the-new-one"


def test_the_chapter_still_answers_when_the_file_does_not(env, proj):
    """Nothing that was working stops working."""
    env("MANGATL_GEMINI_KEY=only-gemini\n")
    proj.settings["key_anthropic"] = "typed-in-here"
    assert editor.key_for(proj, "anthropic") == "typed-in-here"


def test_the_masked_word_never_beats_the_file(env, proj):
    """lee's live chapter, and the reason for the precedence.

    Five of its key fields hold the three-letter word `set` - the MASK, saved
    back as if it were a secret. Not one of them may be reached for while the
    file has a real answer, and `set` must never be handed to a provider.
    """
    for k in ("key_anthropic", "key_openrouter", "ocr_key",
              "translate_key", "proofread_key"):
        proj.settings[k] = project_mod.MASK
    env("MANGATL_ANTHROPIC_KEY=real-claude-key\n"
        "MANGATL_OPENROUTER_KEY=real-or-key\n")
    assert editor.key_for(proj, "anthropic") == "real-claude-key"
    assert editor.fallback_key(proj) == "real-or-key"


def test_the_fallback_reads_the_file_too(env, proj):
    """The OpenRouter key is what catches a refusal, so it is the one that
    must not be the stale copy. It read `p.settings` directly for one edit."""
    env("MANGATL_OPENROUTER_KEY=catch-me\n")
    proj.settings["key_openrouter"] = "stale"
    assert editor.fallback_key(proj) == "catch-me"


# -------------------------------------------------------------------- names

def test_the_names_other_tools_use(env, proj):
    """A `.env` somebody already keeps should just work."""
    env("ANTHROPIC_API_KEY=a\nGEMINI_API_KEY=g\nOPENROUTER_API_KEY=o\n")
    assert editor.key_for(proj, "anthropic") == "a"
    assert editor.key_for(proj, "gemini") == "g"
    assert editor.key_for(proj, "openrouter") == "o"


def test_our_own_name_wins_inside_the_file(env, proj):
    """Both spellings present is a file somebody edited twice. The one this
    app writes is the one it means."""
    env("GEMINI_API_KEY=theirs\nMANGATL_GEMINI_KEY=ours\n")
    assert editor.key_for(proj, "gemini") == "ours"


def test_a_generic_name_in_the_shell_is_not_a_key(env, proj, monkeypatch):
    """`GOOGLE_API_KEY` is exported on half the machines in the world."""
    monkeypatch.setenv("GOOGLE_API_KEY", "somebody-elses-quota")
    env("")
    assert editor.key_for(proj, "gemini") == ""


def test_our_own_name_in_the_shell_is_a_key(env, proj, monkeypatch):
    """...but this one can only have been set for this app."""
    monkeypatch.setenv("MANGATL_GEMINI_KEY", "deliberate")
    env("")
    assert editor.key_for(proj, "gemini") == "deliberate"


def test_the_file_beats_the_shell(env, proj, monkeypatch):
    """The file is the thing you can open and look at."""
    monkeypatch.setenv("MANGATL_GEMINI_KEY", "exported")
    env("MANGATL_GEMINI_KEY=in-the-file\n")
    assert editor.key_for(proj, "gemini") == "in-the-file"


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("text,want", [
    ("MANGATL_GEMINI_KEY=plain", "plain"),
    ('MANGATL_GEMINI_KEY="quoted"', "quoted"),
    ("MANGATL_GEMINI_KEY='single'", "single"),
    ("export MANGATL_GEMINI_KEY=exported", "exported"),
    ("MANGATL_GEMINI_KEY = spaced ", "spaced"),
    ('MANGATL_GEMINI_KEY=" padded "', "padded"),
    ("﻿MANGATL_GEMINI_KEY=bom", "bom"),
    ("MANGATL_GEMINI_KEY=crlf\r\n", "crlf"),
    ("mangatl_gemini_key=lower", "lower"),
    ("# MANGATL_GEMINI_KEY=commented\nMANGATL_GEMINI_KEY=real", "real"),
    ("MANGATL_GEMINI_KEY=has#hash", "has#hash"),
    ("no equals here\nMANGATL_GEMINI_KEY=after", "after"),
])
def test_the_ways_a_line_can_be_written(env, proj, text, want):
    """Every one of these is a file somebody typed into Notepad.

    The BOM case is the one that would have been hardest to see: Notepad wrote
    it for years, and it breaks the FIRST key in the file while every key
    under it works.
    """
    env(text)
    assert editor.key_for(proj, "gemini") == want


def test_the_file_says_what_it_says_and_the_key_is_stripped(env, proj):
    """Two jobs, kept apart. `parse_env` reports the file verbatim; `env_key`
    is what actually goes to a provider, and a key with a space on the end of
    it is a paste error every time - answered with "please pass a valid API
    key", which reads like a WRONG key rather than a padded one."""
    path = env('MANGATL_GEMINI_KEY=" padded "\n')
    raw = userdata.parse_env(open(path, encoding="utf-8").read())
    assert raw["MANGATL_GEMINI_KEY"] == " padded "
    assert editor.key_for(proj, "gemini") == "padded"


def test_a_file_that_is_not_there(env, proj, monkeypatch):
    """No `.env` is the normal state of a fresh install, not an error."""
    monkeypatch.setenv("MANGATL_ENV", str(env.path) + "-nope")
    assert userdata.load_env() == {}
    assert editor.key_for(proj, "gemini") == ""


def test_an_empty_value_is_not_a_key(env, proj):
    """`NAME=` reads as "I have not filled this in yet"."""
    env("MANGATL_GEMINI_KEY=\n")
    assert editor.key_for(proj, "gemini") == ""


# ------------------------------------------------------------------- where

def test_the_three_places_a_file_may_be(env, monkeypatch, tmp_path):
    """Named, home, app folder - in that order, and no duplicates."""
    monkeypatch.setenv("MANGATL_ENV", str(tmp_path / "named.env"))
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    got = [os.path.normcase(p) for p in userdata.env_paths()]
    assert len(got) == 3 and len(set(got)) == 3, got
    assert got[0] == os.path.normcase(str(tmp_path / "named.env"))
    assert got[1] == os.path.normcase(str(tmp_path / "home" / ".env"))
    assert os.path.normcase(os.path.dirname(userdata.__file__)) == \
        os.path.normcase(os.path.dirname(got[2])), \
        "the third place is beside the app itself"


def test_the_app_folder_is_read_too(env, proj, monkeypatch, tmp_path):
    """It is where somebody looking for a `.env` looks first, and refusing to
    read a file sitting right there with the right name in it would be its own
    kind of bug."""
    beside = tmp_path / "app" / ".env"
    beside.parent.mkdir(parents=True)
    beside.write_text("MANGATL_GEMINI_KEY=beside-the-app\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "env_paths",
                        lambda: [env.path, str(beside)])
    env("")
    assert editor.key_for(proj, "gemini") == "beside-the-app"


def test_the_named_file_wins_over_the_others(env, proj, monkeypatch, tmp_path):
    """Somebody who names a file outright means that file."""
    other = tmp_path / "other.env"
    other.write_text("MANGATL_GEMINI_KEY=other\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "env_paths",
                        lambda: [env.path, str(other)])
    env("MANGATL_GEMINI_KEY=named\n")
    assert editor.key_for(proj, "gemini") == "named"


def test_two_files_between_them(env, proj, monkeypatch, tmp_path):
    """Two `.env`s each holding a different key give you both of them, rather
    than the first file being the only one anybody reads."""
    other = tmp_path / "other.env"
    other.write_text("MANGATL_CLEAN_TOKEN=from-the-second\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "env_paths",
                        lambda: [env.path, str(other)])
    env("MANGATL_GEMINI_KEY=from-the-first\n")
    assert editor.key_for(proj, "gemini") == "from-the-first"
    assert editor.clean_token_for(proj) == "from-the-second"


def test_a_half_written_file_does_not_switch_the_other_one_off(
        env, proj, monkeypatch, tmp_path):
    """`NAME=` means "I have not filled this in yet", not "there is no key"."""
    other = tmp_path / "other.env"
    other.write_text("MANGATL_GEMINI_KEY=the-real-one\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "env_paths",
                        lambda: [env.path, str(other)])
    env("MANGATL_GEMINI_KEY=\n")
    assert editor.key_for(proj, "gemini") == "the-real-one"


def test_the_app_never_ships_a_dot_env(env):
    """The app folder is READ but never written, and nothing in the build may
    put a file there - `.gitignore` names it, and this is the other half."""
    from where import PKG
    assert not os.path.exists(os.path.join(str(PKG), ".env")), \
        "a .env has appeared inside the app folder"
    for d in (str(PKG), os.path.dirname(str(PKG))):
        ignore = os.path.join(d, ".gitignore")
        if os.path.isfile(ignore):
            assert ".env" in open(ignore, encoding="utf8").read()
            break
    else:
        raise AssertionError("no .gitignore found to check")


# ------------------------------------------------------------------ writing

def test_writing_keeps_the_rest_of_the_file(env):
    """A `.env` is a file the person owns and may have their own lines in."""
    path = env("# my notes\nSOMETHING_ELSE=mine\n\nMANGATL_GEMINI_KEY=old\n")
    userdata.write_env({"gemini": "new"}, path)
    got = open(path, encoding="utf-8").read()
    assert "# my notes" in got
    assert "SOMETHING_ELSE=mine" in got
    assert "MANGATL_GEMINI_KEY=new" in got
    assert "old" not in got


def test_writing_keeps_the_spelling_the_file_uses(env):
    """A file on `GEMINI_API_KEY` goes on using it rather than sprouting a
    second name for the same key, which is two keys to keep in step."""
    path = env("GEMINI_API_KEY=old\n")
    userdata.write_env({"gemini": "new"}, path)
    got = open(path, encoding="utf-8").read()
    assert "GEMINI_API_KEY=new" in got
    assert "MANGATL_GEMINI_KEY" not in got


def test_writing_an_empty_value_removes_the_line(env, proj):
    """"Not set" and "set to nothing" read the same everywhere else, so only
    one of them is allowed to exist."""
    path = env("MANGATL_GEMINI_KEY=old\n")
    userdata.write_env({"gemini": ""}, path)
    assert "MANGATL_GEMINI_KEY" not in open(path, encoding="utf-8").read()
    assert editor.key_for(proj, "gemini") == ""


def test_writing_into_nothing(env, proj):
    """The first key, on a machine with no file yet."""
    path = str(env.path) + "-new"
    userdata.write_env({"gemini": "first", "clean": "tok"}, path)
    assert os.path.isfile(path)
    got = userdata.parse_env(open(path, encoding="utf-8").read())
    assert got["MANGATL_GEMINI_KEY"] == "first"
    assert got["MANGATL_CLEAN_TOKEN"] == "tok"


def test_writing_and_reading_agree(env, proj):
    """The round trip, through the same path the app uses."""
    userdata.write_env({"anthropic": "a", "gemini": "g",
                        "openrouter": "o", "clean": "c"}, env.path)
    assert editor.key_for(proj, "anthropic") == "a"
    assert editor.key_for(proj, "gemini") == "g"
    assert editor.key_for(proj, "openrouter") == "o"
    assert editor.clean_token_for(proj) == "c"


# ------------------------------------------------------------------- screen

def test_the_screen_says_which_keys_the_file_answers_for(env, proj):
    """A file nothing on screen mentions is a file you cannot tell is being
    read - and then a stale copy in a chapter gets blamed for a rolled key."""
    env("MANGATL_GEMINI_KEY=g\nMANGATL_CLEAN_TOKEN=c\n")
    s = proj.summary()
    assert s["env_keys"] == {"anthropic": False, "gemini": True,
                             "openrouter": False, "clean": True}
    assert s["env_path"].endswith("keys.env")


def test_the_screen_never_sees_a_key(env, proj):
    """Booleans and a path. The keys themselves stay on the server."""
    env("MANGATL_ANTHROPIC_KEY=secret-aaa\nMANGATL_GEMINI_KEY=secret-bbb\n"
        "MANGATL_OPENROUTER_KEY=secret-ccc\nMANGATL_CLEAN_TOKEN=secret-ddd\n")
    import json
    blob = json.dumps(proj.summary())
    for s in ("secret-aaa", "secret-bbb", "secret-ccc", "secret-ddd"):
        assert s not in blob, s


def test_a_key_from_the_file_reports_itself_as_env(env, proj):
    """Not "(saved)". The two mean different things to whoever is looking:
    "set" means you typed it here, "env" means typing here changes nothing."""
    env("MANGATL_GEMINI_KEY=g\nMANGATL_CLEAN_TOKEN=c\n")
    proj.settings["key_gemini"] = "still-in-the-chapter"
    s = proj.summary()["settings"]
    assert s["key_gemini"] == project_mod.ENV
    assert s["clean_token"] == project_mod.ENV


def test_the_placeholder_token_is_not_reported_while_the_file_answers(env,
                                                                     proj):
    """The CHANGE-ME example may well still be sitting in the chapter. It is
    not the token being sent, so saying so under the box points at the wrong
    string entirely."""
    proj.settings["clean_token"] = "CHANGE-ME-please"
    assert proj.summary()["settings"]["clean_token"] == "placeholder"
    env("MANGATL_CLEAN_TOKEN=the-real-one\n")
    assert proj.summary()["settings"]["clean_token"] == project_mod.ENV
    assert editor.clean_token_for(proj) == "the-real-one"


def test_the_word_env_is_never_saved_as_a_key(env, proj):
    """`ENV` is a REPORT, exactly like `MASK`. A `.tct` exported from a
    machine with a `.env` carries it in every key field, and importing that
    must not save three characters over a working key."""
    incoming = {"key_gemini": project_mod.ENV, "clean_token": project_mod.ENV,
                "key_anthropic": "a-real-one"}
    dropped = project_mod.drop_masked_secrets(incoming)
    assert set(dropped) == {"key_gemini", "clean_token"}
    assert incoming == {"key_anthropic": "a-real-one"}


def test_the_four_names_are_one_list(env):
    """`userdata.ENV_NAMES` and the list the screen draws are the same four.
    A key the file reads and the screen never mentions is a key nobody can
    tell is missing."""
    import re
    from where import PKG
    js = open(os.path.join(str(PKG), "static", "js", "project.js"),
              encoding="utf8").read()
    block = re.search(r"const ENV_KEYS = \[(.+?)\];", js, re.S)
    assert block, "the screen's list of keys has been renamed"
    named = set(re.findall(r"\['(\w+)'", block.group(1)))
    assert named == set(userdata.ENV_NAMES), named
