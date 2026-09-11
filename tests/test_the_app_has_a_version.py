"""The app knows what version it is, and says so in one place.

lee: *"also kkeep track of vesion ad thsi is v1.0.0"*.

`version.py` is the source. The header pill, `/api/version`, the chapter
bundle and the release tooling all read it; nothing else spells a number.
"""
import json
import os
import re

import pytest

from where import PKG, JS, CSS

from mangatl import version as V


def test_it_is_one_point_something():
    """1.0.0 shipped on 2026-09-10; every number since is a release tag."""
    assert V.parse(V.__version__) >= (1, 0, 0)
    assert re.fullmatch(r"\d+\.\d+\.\d+", V.__version__), "plain semver"
    assert V.CHANNEL == "beta"


def test_versions_compare_as_numbers_not_strings():
    assert V.parse("1.2.10") > V.parse("1.2.9")
    assert V.parse("v1.0.1") == (1, 0, 1)
    assert V.parse("1.0.1-beta") == (1, 0, 1)
    assert V.parse("1.1") == (1, 1, 0)
    assert V.parse("garbage") < V.parse("0.0.0")
    assert V.newer("1.0.1", "1.0.0")
    assert not V.newer("1.0.0", "1.0.0")
    assert not V.newer("0.9.9", "1.0.0")
    assert not V.newer("", "1.0.0"), "an empty manifest is not an update"


def test_the_route_answers_from_the_one_source(tmp_path, monkeypatch):
    from mangatl import editor as E
    monkeypatch.delenv("MANGATL_UPDATE_FILE", raising=False)
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'if path == "/api/version":' in src
    assert "_v.__version__" in src and "_v.CHANNEL" in src
    assert E._update_state() == {}, "no launcher, nothing to say"


def test_the_launcher_speaks_through_one_file(tmp_path, monkeypatch):
    from mangatl import editor as E
    fp = tmp_path / "update.json"
    monkeypatch.setenv("MANGATL_UPDATE_FILE", str(fp))
    assert E._update_state() == {}, "named but not written yet"
    fp.write_text(json.dumps({"available": "1.0.1", "state": "downloading"}))
    assert E._update_state() == {"update": {"available": "1.0.1",
                                            "state": "downloading",
                                            "notes": ""}}
    fp.write_text(json.dumps({"available": "1.0.1", "state": "ready",
                              "notes": "https://x/notes"}))
    assert E._update_state()["update"]["state"] == "ready"
    fp.write_text("not json")
    assert E._update_state() == {}, "a half-written file is not an error"
    fp.write_text(json.dumps({"available": ""}))
    assert E._update_state() == {}


def test_the_pill_shows_the_number_and_the_waiting_update():
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    assert "async function showVersion()" in js
    body = js[js.index("async function showVersion()"):]
    body = body[:body.index("\nasync function loadProject")]
    assert "api('/api/version')" in body
    assert "pill.textContent=(v.channel?v.channel+' ':'')+v.version" in body
    assert "hasupdate" in body
    # The switch is the launcher's, on a restart - which Settings > Updates
    # can now ask for, so the pill points there and leads there.
    assert "Restart now" in body and "Settings > Updates" in body
    assert "setSettingsTab('updates')" in body, "clicking the pill opens the Updates section"
    assert "showVersion();" in js[js.index("async function loadProject"):][:200]
    css = CSS.joinpath("editor.css").read_text(encoding="utf-8")
    assert ".brand .betapill.hasupdate::after" in css


def test_the_chapter_bundle_says_which_app_wrote_it():
    src = (PKG / "bundle.py").read_text(encoding="utf-8")
    assert '"app": __version__' in src


def test_weights_can_live_outside_the_app_folder(tmp_path, monkeypatch):
    """The launcher replaces the app folder on every update; half a gigabyte
    of checkpoints stays put in a folder it names."""
    from mangatl.project import Project
    p = Project(None, str(tmp_path / "proj"))
    p.settings["weights"] = ""
    monkeypatch.delenv("MANGATL_WEIGHTS", raising=False)
    assert p._weights_dir() == str(PKG)
    w = tmp_path / "models"; w.mkdir()
    monkeypatch.setenv("MANGATL_WEIGHTS", str(w))
    assert p._weights_dir() == str(w)
    monkeypatch.setenv("MANGATL_WEIGHTS", str(tmp_path / "nope"))
    assert p._weights_dir() == str(PKG), "a folder that is not there is ignored"
    # ...and a path the person typed still wins over both
    (w / "comictextdetector.pt.onnx").write_bytes(b"x")
    p.settings["weights"] = str(w / "comictextdetector.pt.onnx")
    monkeypatch.setenv("MANGATL_WEIGHTS", str(tmp_path / "other"))
    assert p._weights_dir() == str(w)
