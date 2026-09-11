"""Settings > Updates: the launcher's updating, visible and pressable.

lee: *"when i download 1.2 it dont update 1.2 it reinstalls everything, also
add an updates tab in the settings that downloads the update automatically"*.

Two halves. The launcher's half is here with the same fixtures its own tests
use - a release channel on localhost, a home folder, a stub editor: the
automatic switch, the "offered" state it produces, the restart exit code
and the pass the launcher makes on it, the manifest's launcher entry. The
app's half is `mangatl.updates` driven through the editor's `/api/updates`,
against the same channel, with the process-ending calls stubbed.

The test's `L` is `launcher/mangatct_launcher.py` on the path, as the
launcher tests import it; the app's `updates.L` is the same file imported
as `mangatl.launcher.mangatct_launcher` - another module object, so the app
half patches THAT one's `MANIFEST_URL`.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request

import pytest

from where import PKG

sys.path.insert(0, str(PKG / "launcher"))
import mangatct_launcher as L  # noqa: E402
from test_the_launcher_keeps_the_app_current import (  # noqa: E402
    channel, home, install, app_zip, sha, STUB_EDITOR)

from mangatl import editor, updates  # noqa: E402

ISS = (PKG / "launcher" / "installer.iss").read_text(encoding="utf-8")
HTML = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
JS = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")


# --------------------------------------------------------- the launcher

def test_with_automatic_downloads_off_a_version_is_offered_not_fetched(home, channel):
    p = home
    install(p, "1.0.0")
    channel.publish("1.0.1")
    L.write_state(p, auto_update=False)
    assert L.check_for_update(p, L.fetch_manifest(channel.url("/manifest.json"))) is None
    assert L.installed_versions(p) == ["1.0.0"], "nothing came down"
    u = L.read_json(p["update"], {})
    assert u["available"] == "1.0.1" and u["state"] == "offered"
    assert not any(h.endswith(".zip") for h in channel.hits)
    # ...and the Download button is the same call, forced
    assert L.check_for_update(p, L.fetch_manifest(channel.url("/manifest.json")), force=True) == "1.0.1"
    assert L.installed_versions(p) == ["1.0.1", "1.0.0"]
    assert L.read_json(p["update"], {})["state"] == "ready"


def test_the_switch_is_on_unless_somebody_turned_it_off(home):
    assert L.auto_update(home) is True, "no state.json yet: on"
    L.write_state(home, auto_update=False)
    assert L.auto_update(home) is False
    L.write_state(home, auto_update=True)
    assert L.auto_update(home) is True


def test_a_percentage_rides_in_the_update_file_when_given(home):
    L.say_update(home, "1.0.1", "downloading", "", percent=42)
    assert L.read_json(home["update"], {})["percent"] == 42
    L.say_update(home, "1.0.1", "ready")
    assert "percent" not in L.read_json(home["update"], {})


def test_the_restart_code_is_the_one_the_editor_uses():
    assert L.EDITOR_RESTART == 75
    assert updates.RESTARTS_FROM == (1, 0, 3)
    assert L.parse_version(L.LAUNCHER_VERSION) >= updates.RESTARTS_FROM, \
        "the launcher shipping now knows the code"


class _Proc:
    def __init__(self, code):
        self.returncode = code


def test_only_the_restart_code_means_start_again():
    assert L.restart_wanted(_Proc(75))
    assert not L.restart_wanted(_Proc(0))
    assert not L.restart_wanted(_Proc(1))
    assert not L.restart_wanted(None)


#: An editor that, the first time it is started in a home, answers once and
#: then ends with the restart code - the second time it stays up.
RESTARTING_EDITOR = STUB_EDITOR.replace(
    "print(\"stub editor\", VERSION, \"on\", a.port, flush=True)",
    "import threading\n"
    "marker = os.path.join(os.path.dirname(os.environ['MANGATL_UPDATE_FILE']), 'restarted.once')\n"
    "if not os.path.exists(marker):\n"
    "    open(marker, 'w').close()\n"
    "    threading.Timer(3.0, lambda: os._exit(75)).start()\n"
    "print(\"stub editor\", VERSION, \"on\", a.port, flush=True)")


def test_the_launcher_makes_another_pass_when_the_editor_asks(home, channel, monkeypatch):
    """Headless, because the tk window is Windows' business: the editor
    ends with `EDITOR_RESTART`, and instead of ending the launcher starts
    the whole thing again - which is when a fetched version is switched to."""
    p = home
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mangatl/__init__.py", "")
        z.writestr("mangatl/editor.py", "VERSION = '1.0.0'\n" + RESTARTING_EDITOR)
        z.writestr("mangatl/version.py", "__version__ = '1.0.0'\n")
        z.writestr("requirements.txt", "numpy\n")
    fp = os.path.join(p["app"], "x.zip")
    with open(fp, "wb") as f:
        f.write(buf.getvalue())
    assert L.install_app_zip(p, fp, "1.0.0")
    monkeypatch.setattr(L, "MANIFEST_URL", channel.url("/manifest.json"))
    starts = []
    real = L.start_editor

    def counting(p_, version, port):
        starts.append(version)
        proc = real(p_, version, port)
        if len(starts) == 1:
            channel.publish("1.0.1")    # lands on the second pass's check
        if len(starts) == 2:
            threading.Timer(2.0, proc.terminate).start()     # end the test
        return proc
    monkeypatch.setattr(L, "start_editor", counting)
    code = L.main(["--headless", "--no-browser", "--browser"])
    assert code == 0
    assert starts == ["1.0.0", "1.0.1"], "a second pass, and it ran what the first fetched"


def test_the_manifest_names_the_launcher_it_ships(tmp_path):
    sys.path.insert(0, str(PKG / "tools"))
    import release as R
    assert R.launcher_version() == L.LAUNCHER_VERSION
    R.build_zip(str(tmp_path))
    R.build_manifest("https://example.test/download/", str(tmp_path))
    man = json.load(open(tmp_path / "manifest.json"))
    assert man["launcher"]["version"] == L.LAUNCHER_VERSION
    assert man["minimum_launcher"] == "1.0.0", "old launchers still run this app"
    assert "installer" not in man, "none was beside the zip"


def test_the_installer_stops_the_app_itself_and_can_start_it_again():
    """1.0.2's installer stopped at "Setup was unable to automatically close
    all applications". The .iss now stops whatever runs out of {app} before
    Setup looks, by exe path (python.exe is not ours alone), and starts the
    app again after a silent install the app itself asked for."""
    assert "function PrepareToInstall" in ISS
    assert "StopTheApp(ExpandConstant('{app}'))" in ISS
    assert "Get-Process" in ISS and "Stop-Process -Force" in ISS
    assert "$_.Path.StartsWith($app" in ISS, "by path, not by image name"
    code = ISS[ISS.index("[Code]"):]
    assert not re.search(r"^\s*Exec\('taskkill", code, re.M), "not by image name"
    assert "CurUninstallStepChanged" in ISS, "the uninstaller too"
    assert re.search(r'Filename: "\{app\}\\MangaTCT\.exe"; Flags: nowait skipifnotsilent; Check: Relaunch', ISS)
    assert "{param:relaunch|0}" in ISS
    assert "CloseApplications=yes" in ISS


def test_the_app_runs_the_installer_silently_and_asks_to_be_relaunched():
    args = updates._setup_args("C:\\t\\MangaTCT-Setup-1.0.3.exe")
    assert args[0].endswith(".exe")
    assert "/SILENT" in args and "/NORESTART" in args
    assert "/relaunch=1" in args, "what the .iss reads to start the app again"
    assert "/VERYSILENT" not in args, "a progress window is the one thing the person sees"


# ---------------------------------------------------------------- the app

@pytest.fixture
def launched(home, monkeypatch, tmp_path):
    """The editor as the launcher starts it: told where update.json is and
    which launcher it is under. Module state reset between tests."""
    p = home
    install(p, "1.0.0")
    monkeypatch.setenv("MANGATL_UPDATE_FILE", p["update"])
    monkeypatch.setenv("MANGATL_LAUNCHER", "1.0.3")
    monkeypatch.setattr(updates, "_BUSY", {"what": ""})
    monkeypatch.setattr(updates, "_PROGRESS", {"percent": None})
    monkeypatch.setattr(updates, "_MANIFEST", {"at": 0.0, "data": None})
    monkeypatch.setattr(updates, "_LAST", {"error": "", "checked": 0.0})
    left = []
    monkeypatch.setattr(updates, "_leave", lambda code, after=0.4: left.append(code))
    return p, left


@pytest.fixture
def serving(monkeypatch):
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def _get(base, route):
    with urllib.request.urlopen(base + route) as r:
        return json.load(r)


def _post(base, route, body):
    req = urllib.request.Request(base + route, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _settle(timeout=20.0):
    end = time.time() + timeout
    while updates._BUSY["what"] and time.time() < end:
        time.sleep(0.05)
    assert not updates._BUSY["what"], "still busy"


def test_a_checkout_run_by_hand_has_no_updates(monkeypatch):
    monkeypatch.delenv("MANGATL_UPDATE_FILE", raising=False)
    monkeypatch.delenv("MANGATL_LAUNCHER", raising=False)
    s = updates.state()
    assert s["launched"] is False and "update" not in s
    assert updates.restart()["ok"] is False
    assert updates.install_setup()["ok"] is False


def test_the_state_says_what_the_launcher_left(launched):
    p, _ = launched
    s = updates.state()
    assert s["launched"] and s["auto"] is True and s["can_restart"] is True
    assert s["launcher"] == "1.0.3" and s["installed"] == ["1.0.0"]
    assert "update" not in s and s["problem"] == ""
    L.say_update(p, "1.0.1", "ready", "notes")
    assert updates.state()["update"] == {"available": "1.0.1", "state": "ready",
                                         "notes": "notes", "percent": None}


def test_check_now_fetches_the_zip_with_a_percentage_and_the_pill_sees_it(launched, channel, monkeypatch, serving):
    p, _ = launched
    channel.publish("1.0.1")
    monkeypatch.setattr(updates.L, "MANIFEST_URL", channel.url("/manifest.json"))
    s = _post(serving, "/api/updates", {"do": "check"})
    assert s["busy"] == "check"
    _settle()
    s = _get(serving, "/api/updates")
    assert s["update"]["state"] == "ready" and s["update"]["available"] == "1.0.1"
    assert s["installed"] == ["1.0.1", "1.0.0"]
    assert s["last_check"] > 0 and s["busy"] == ""
    # what /api/version - the pill - reads is the same file
    v = _get(serving, "/api/version")
    assert v["update"]["available"] == "1.0.1"


def test_with_the_switch_off_check_now_only_offers_and_download_fetches(launched, channel, monkeypatch, serving):
    p, _ = launched
    channel.publish("1.0.1")
    monkeypatch.setattr(updates.L, "MANIFEST_URL", channel.url("/manifest.json"))
    s = _post(serving, "/api/updates", {"do": "auto", "on": False})
    assert s["auto"] is False and L.read_state(p)["auto_update"] is False
    _post(serving, "/api/updates", {"do": "check"})
    _settle()
    s = _get(serving, "/api/updates")
    assert s["update"]["state"] == "offered" and s["installed"] == ["1.0.0"]
    _post(serving, "/api/updates", {"do": "check", "force": True})
    _settle()
    s = _get(serving, "/api/updates")
    assert s["update"]["state"] == "ready" and s["installed"] == ["1.0.1", "1.0.0"]


def test_a_channel_that_does_not_answer_is_a_line_not_an_error(launched, monkeypatch, serving):
    monkeypatch.setattr(updates.L, "MANIFEST_URL", "http://127.0.0.1:1/nothing.json")
    _post(serving, "/api/updates", {"do": "check"})
    _settle()
    s = _get(serving, "/api/updates")
    assert "did not answer" in s["problem"]
    assert "error" not in s, "`error` is what the client toasts; this is not that"


def test_restart_now_ends_with_the_launchers_code_or_quits_under_an_old_one(launched, monkeypatch, serving):
    p, left = launched
    r = _post(serving, "/api/updates", {"do": "restart"})
    assert r == {"ok": True, "restarting": True} and left == [75]
    monkeypatch.setenv("MANGATL_LAUNCHER", "1.0.0")
    assert updates.state()["can_restart"] is False
    r = _post(serving, "/api/updates", {"do": "restart"})
    assert r == {"ok": True, "restarting": False} and left == [75, 0]


def test_the_new_setup_is_offered_only_when_it_carries_a_newer_launcher(launched, channel, monkeypatch):
    p, _ = launched
    body = b"MZ" + b"\0" * 5000
    channel.files["/MangaTCT-Setup-1.0.4.exe"] = body
    monkeypatch.setattr(updates.L, "MANIFEST_URL", channel.url("/manifest.json"))
    inst = {"version": "1.0.4", "url": channel.url("/MangaTCT-Setup-1.0.4.exe"),
            "sha256": sha(body), "size": len(body)}
    # same launcher as mine: nothing to offer
    channel.publish("1.0.4", installer=inst, launcher={"version": "1.0.3"}, minimum_launcher="1.0.0")
    updates.check(wait=True)
    assert "installer" not in updates.state()
    assert updates.install_setup()["ok"] is False
    # a newer one: offered, not required
    channel.publish("1.0.4", installer=inst, launcher={"version": "1.0.4"}, minimum_launcher="1.0.0")
    updates.check(wait=True)
    got = updates.state()["installer"]
    assert got == {"version": "1.0.4", "launcher": "1.0.4", "size": len(body), "required": False}
    # ...and required when the app needs more launcher than is running
    channel.publish("1.0.4", installer=inst, launcher={"version": "1.0.4"}, minimum_launcher="1.0.4")
    updates.check(wait=True)
    assert updates.state()["installer"]["required"] is True


def test_getting_the_setup_downloads_it_checks_it_and_hands_over(launched, channel, monkeypatch, tmp_path):
    p, left = launched
    body = b"MZ" + bytes(range(256)) * 40
    channel.files["/MangaTCT-Setup-1.0.4.exe"] = body
    monkeypatch.setattr(updates.L, "MANIFEST_URL", channel.url("/manifest.json"))
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))
    inst = {"version": "1.0.4", "url": channel.url("/MangaTCT-Setup-1.0.4.exe"),
            "sha256": sha(body), "size": len(body)}
    channel.publish("1.0.4", installer=inst, launcher={"version": "1.0.4"})
    updates.check(wait=True)
    ran = []
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates.subprocess, "Popen",
                        lambda args, **kw: ran.append((args, kw)))
    r = updates.install_setup(wait=True)
    assert r["ok"] is True
    assert ran and ran[0][0][0] == str(tmp_path / "MangaTCT-Setup-1.0.4.exe")
    assert "/relaunch=1" in ran[0][0]
    assert open(ran[0][0][0], "rb").read() == body
    assert left == [0], "the editor leaves; the installer stops the rest and starts it again"
    # a wrong checksum: nothing run, nothing left behind, and a line
    channel.files["/MangaTCT-Setup-1.0.4.exe"] = body + b"x"
    left.clear(); ran.clear()
    updates.install_setup(wait=True)
    assert not ran and not left
    assert "checksum" in updates.state()["problem"]


# --------------------------------------------------------------- the page

def test_settings_has_an_updates_section_with_the_switch_and_the_buttons():
    assert 'data-sec="updates"' in HTML
    assert re.search(r'<button class="setnav-btn" data-sec="updates"[^>]*>Updates</button>', HTML)
    sec = HTML[HTML.index('<section class="set-section" data-sec="updates">'):]
    sec = sec[:sec.index("</section>")]
    for must in ('id="updCheck"', 'id="updAct"', 'id="updAuto"', 'id="updSetupBtn"',
                 "Download updates automatically", "Check now", "Get the new setup"):
        assert must in sec, must
    # one line per control, no paragraphs (lee)
    hints = re.findall(r'<p class="sethint">(.*?)</p>', sec, re.S)
    assert all(len(" ".join(h.split())) < 120 for h in hints), hints
    assert "<p>" not in sec


def test_the_page_polls_while_something_downloads_and_names_every_state():
    body = JS[JS.index("function renderUpdates("):]
    body = body[:body.index("\nasync function refreshUpdates")]
    for state in ("'ready'", "'offered'", "'downloading'"):
        assert state in body, state
    assert "Restart now" in body and "Quit and start again" in body
    assert "You have the latest version." in body
    assert "setTimeout" in body and "refreshUpdates" in body
    assert "do:'check',force:!!force" in JS and "do:'auto'" in JS \
        and "do:'restart'" in JS and "do:'install'" in JS
    assert "if(name==='updates'" in (PKG / "static" / "js" / "view.js").read_text(encoding="utf-8")
