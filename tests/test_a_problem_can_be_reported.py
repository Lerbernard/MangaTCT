"""Report a problem: what a support message starts with, gathered on screen.

lee: *"i still want to be able to send out update and keep suporting teh
app"*. Supporting it means the first message says the version, the machine
and what the log said - and never a key.
"""
import json
import os

import pytest

from where import PKG, EDITOR_HTML, JS

from mangatl import editor as E
from mangatl import version as V
from mangatl.project import Project


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    return Project(None, str(tmp_path / "p"))


def test_the_report_carries_the_facts_and_no_values(proj, monkeypatch):
    monkeypatch.delenv("MANGATL_LOG_FILE", raising=False)
    monkeypatch.setenv("MANGATL_LAUNCHER", "1.0.0")
    d = E._diagnostics(proj)
    assert d["version"] == V.__version__ and d["channel"] == V.CHANNEL
    assert d["launcher"] == "1.0.0"
    assert d["python"] and d["os"]
    assert "opencv" in d["machine"] and "cores" in d["machine"]
    assert d["chapter"]["pages"] == 0 and d["chapter"]["medium"]
    assert set(d["keys_present"]) == {"anthropic", "gemini", "openrouter", "clean"}
    assert all(isinstance(v, bool) for v in d["keys_present"].values())
    assert d["log"] == [], "no launcher, no log file"
    assert d["support"] == V.SUPPORT
    blob = json.dumps(d)
    for never in ("env_path", "MANGATL_ANTHROPIC_KEY=", "sk-"):
        assert never not in blob


def test_the_log_tail_is_the_last_lines_with_keys_scrubbed(proj, tmp_path, monkeypatch):
    fp = tmp_path / "editor-2026-09-08.log"
    lines = ["line %d" % i for i in range(300)]
    # Built rather than written out: a literal key-shaped string here trips
    # the repo's own secret scan (tests/test_the_workflows.py), which is that
    # scan doing exactly its job.
    fake = "sk-" + "ant-" + "api03-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    lines.append("auth failed for %s on read" % fake)
    lines.append("Authorization: Bearer AbCdEfGhIjKlMnOpQrStUv.xyz")
    lines.append("key %s rejected" % ("AIza" + "SyDeoXBP0E1h3iQAq3pZ-txdOBYjWekjfHE"))
    fp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("MANGATL_LOG_FILE", str(fp))
    tail = E._log_tail()
    assert len(tail) == 80
    assert tail[0] == "line 223" and tail[-4] == "line 299"
    assert tail[-3] == "auth failed for <key> on read"
    assert tail[-2] == "Authorization: <key>"
    assert tail[-1] == "key <key> rejected"
    assert E._diagnostics(proj)["log"] == tail
    monkeypatch.setenv("MANGATL_LOG_FILE", str(tmp_path / "gone.log"))
    assert E._log_tail() == []


def test_the_route_and_the_version_route_carry_the_support_links():
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'if path == "/api/diagnostics":' in src
    assert '"support": _v.SUPPORT' in src
    assert V.SUPPORT["guide"].startswith("https://")
    assert set(V.SUPPORT) == {"discord", "email", "guide", "download"}


def test_the_help_section_is_under_file_and_says_what_it_sends():
    html = EDITOR_HTML.read_text(encoding="utf-8")
    rail = html[html.index('<nav id="fileNav">'):html.index("</nav>", html.index('<nav id="fileNav">'))]
    assert "Report a problem" in rail and "Guide" in rail
    assert 'data-sec="help"' in rail
    sec = html[html.index('data-sec="help">'):html.index('data-sec="save">')]
    assert 'id="diagText"' in sec and "readonly" in sec
    assert "never a key" in sec
    assert "Read it before you" in sec and "send it" in sec
    assert "GNU GPL" in sec, "the source offer goes where the person is"
    js = JS.joinpath("project.js").read_text(encoding="utf-8")
    for fn in ("async function openHelp()", "function copyDiag()", "function openGuide()"):
        assert fn in js, fn
    body = js[js.index("async function openHelp()"):js.index("async function copyDiag()")]
    assert "api('/api/diagnostics')" in body
    assert "mailto:" in body and "Ask on Discord" in body
    assert "if(_support.discord)" in body and "if(_support.email)" in body, \
        "a door that does not exist yet is not shown"


def test_the_launcher_tells_the_editor_where_its_log_is():
    src = (PKG / "launcher" / "mangatct_launcher.py").read_text(encoding="utf-8")
    assert 'env["MANGATL_LOG_FILE"] = logfp' in src
