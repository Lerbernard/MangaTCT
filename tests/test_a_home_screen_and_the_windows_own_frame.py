"""Home, and a window whose frame is the app's own top bar.

lee: *"instead of having a separate top bar like this, integrate it with the
app; also have a landing page, a home page that I can log in to the app and
view projects to load, like Photoshop has, and make clicking the logo go to
the home page"*.

The window half: `window.py` opens frameless on Windows and hands the page
an API - the three buttons, and `hit`, which tells Windows which part of a
frame the mouse went down on so Windows runs the move or resize itself. The
page half: `chrome.js` draws the buttons and the drag strip only once the
window says it is frameless; `home.js` draws the first screen from
/api/home, and the mark at the top left is the way back to it.
"""
import argparse
import json
import os
import sys
import threading
import types
import urllib.request

import pytest

from where import PKG
from mangatl import editor, userdata, window as W

HTML = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
CHROME = (PKG / "static" / "js" / "chrome.js").read_text(encoding="utf-8")
HOME = (PKG / "static" / "js" / "home.js").read_text(encoding="utf-8")
VIEW = (PKG / "static" / "js" / "view.js").read_text(encoding="utf-8")
BOOT = (PKG / "static" / "js" / "boot.js").read_text(encoding="utf-8")
CSS = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")


# --------------------------------------------------------------- the window

def _args(**kw):
    a = argparse.Namespace(port=1, host="127.0.0.1", title="x", debug=False, frame=False)
    a.__dict__.update(kw)
    return a


def test_the_frame_is_off_on_windows_and_kept_where_asked(monkeypatch):
    monkeypatch.delenv("MANGATCT_FRAME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert W.want_frame(_args()) is False, "the page's bar is the title bar"
    assert W.want_frame(_args(frame=True)) is True
    monkeypatch.setenv("MANGATCT_FRAME", "1")
    assert W.want_frame(_args()) is True
    monkeypatch.delenv("MANGATCT_FRAME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert W.want_frame(_args()) is True, "off Windows the page cannot drive the window"


class _Win:
    def __init__(self):
        self.native = types.SimpleNamespace(WindowState="Normal", Handle=types.SimpleNamespace(ToInt64=lambda: 77))
        self.calls = []

    def minimize(self): self.calls.append("min")
    def maximize(self): self.calls.append("max"); self.native.WindowState = "Maximized"
    def restore(self): self.calls.append("restore"); self.native.WindowState = "Normal"
    def destroy(self): self.calls.append("close")


def test_the_page_api_is_the_three_buttons_and_the_frame_hit(monkeypatch):
    api = W.Api()
    api.frameless = True
    w = _Win()
    api.win = w
    assert api.state() == {"frameless": True, "maximized": False}
    api.minimize(); assert w.calls[-1] == "min"
    assert api.toggle_maximize() is True and w.calls[-1] == "max"
    assert api.state()["maximized"] is True
    assert api.toggle_maximize() is False and w.calls[-1] == "restore"
    api.close(); assert w.calls[-1] == "close"
    # hit: only the frame's own codes, only on Windows, and through the form's thread
    monkeypatch.setattr(sys, "platform", "win32")
    sent = []
    monkeypatch.setattr(W, "_begin_native_drag", lambda win, hwnd, code: sent.append((hwnd, code)) or True)
    assert api.hit(2) is True and sent == [(77, 2)]
    assert api.hit("17") is True and sent[-1] == (77, 17)
    assert api.hit(3) is False and api.hit("x") is False and api.hit(None) is False
    monkeypatch.setattr(sys, "platform", "linux")
    assert api.hit(2) is False
    assert W.HTCAPTION == 2 and W.HIT_CODES == {2, 10, 11, 12, 13, 14, 15, 16, 17}
    assert W.WM_NCLBUTTONDOWN == 0xA1


def test_the_native_drag_is_release_capture_then_nc_lbutton_down(monkeypatch):
    calls = []
    user32 = types.SimpleNamespace(ReleaseCapture=lambda: calls.append("release"),
                                   SendMessageW=lambda h, m, w, l: calls.append(("send", m, w.value)))
    fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=user32),
                                        c_void_p=lambda v: v, c_size_t=lambda v: types.SimpleNamespace(value=v),
                                        c_ssize_t=lambda v: v)
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    win = types.SimpleNamespace(native=types.SimpleNamespace())      # no BeginInvoke: run inline
    assert W._begin_native_drag(win, 77, 17) is True
    assert calls == ["release", ("send", 0xA1, 17)]


def test_on_windows_the_window_is_made_frameless_with_the_api(monkeypatch, tmp_path):
    from test_the_app_in_its_own_window import fake_webview
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    monkeypatch.delenv("MANGATCT_FRAME", raising=False)
    wv, made, started = fake_webview(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(W, "_own_taskbar_entry", lambda: None)
    dressed = []
    monkeypatch.setattr(W, "dress_the_frame", lambda hwnd, frameless=False: dressed.append(frameless))
    kept = []
    monkeypatch.setattr(W, "keep_off_the_taskbar", lambda win: kept.append(1))
    monkeypatch.setattr(W, "_hwnd_of", lambda win: 5)

    def start(**kw):
        made[0].events.shown.fire()
        made[0].events.closing.fire()
    wv.start = start
    assert W.main(["--port", "1"]) == W.EXIT_CLOSED
    kw = made[0].kw
    assert kw["frameless"] is True and kw["easy_drag"] is False
    assert isinstance(kw["js_api"], W.Api) and kw["js_api"].win is made[0]
    assert dressed == [True], "rounded corners asked for on the frameless window"
    assert kept == [1], "maximise stops at the taskbar"
    # ...and with --frame the system frame stays, and none of that happens
    made.clear(); dressed.clear(); kept.clear()
    assert W.main(["--port", "1", "--frame"]) == W.EXIT_CLOSED
    assert made[0].kw["frameless"] is False and dressed == [False] and kept == []


# ------------------------------------------------------------------ the page

def test_the_bar_carries_the_window_buttons_and_the_drag_strip():
    assert 'id="winctl" hidden' in HTML
    for b in ("wbMin", "wbMax", "wbClose"):
        assert 'id="%s"' % b in HTML
    assert 'id="tbDrag"' in HTML
    assert "window.addEventListener('pywebviewready'" in CHROME
    assert "if(st && st.frameless) wireChrome();" in CHROME, "only once the window says so"
    assert "api.hit(code)" in CHROME and "caption: 2" in CHROME and "bottomright: 17" in CHROME
    assert "drag.addEventListener('dblclick', () => winCtl('max'))" in CHROME
    assert ".wbtn.close:hover{background:#c42b1c" in CSS, "Windows' red"
    assert "html.framed #top" in CSS and "#winEdges" in CSS
    assert '<script src="/static/js/chrome.js">' in HTML


def test_the_mark_goes_home_and_home_is_the_first_screen():
    assert 'class="brand" href="#home" title="Home" onclick="goHome(event)"' in HTML
    assert 'id="home"' in HTML and 'id="homeRecent"' in HTML and 'id="homeAcct"' in HTML
    assert "setTab('home', 1)" in HOME
    assert "const isHome = t==='home';" in VIEW
    assert "setTab('home')" in BOOT and "showPicker(true)" not in BOOT.split("loadProject()")[1]
    assert 'onclick="homeNew()"' in HTML and 'onclick="homeOpen()"' in HTML


# ---------------------------------------------------------------- recents

def test_recent_projects_are_kept_newest_first_and_once(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    a = tmp_path / "a.tctp"; b = tmp_path / "b.tctp"
    a.write_bytes(b"x"); b.write_bytes(b"x")
    userdata.note_project(str(a), 12, "manga")
    userdata.note_project(str(b), 3, "manhwa")
    got = userdata.recent_projects()
    assert [r["name"] for r in got] == ["b", "a"]
    assert got[0]["pages"] == 3 and got[0]["medium"] == "manhwa" and got[0]["exists"]
    userdata.note_project(str(a), 13, "manga")          # again: moves up, once
    assert [r["name"] for r in userdata.recent_projects()] == ["a", "b"]
    b.unlink()
    assert userdata.recent_projects()[1]["exists"] is False, "listed, and said to be gone"
    userdata.forget_project(str(b))
    assert [r["name"] for r in userdata.recent_projects()] == ["a"]
    for i in range(20):
        userdata.note_project(str(tmp_path / ("c%d.tctp" % i)), 1, "")
    assert len(userdata.recent_projects()) == userdata.RECENT_PROJECTS


@pytest.fixture
def serving(tmp_path, monkeypatch):
    from mangatl.project import Project
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    p = Project(None, str(tmp_path / "out"))
    was, editor.PROJECT = editor.PROJECT, p
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield p, "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _get(base, route):
    with urllib.request.urlopen(base + route) as r:
        return json.load(r)


def _post(base, route, body):
    req = urllib.request.Request(base + route, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def test_the_home_route_says_who_what_is_open_and_what_was(serving, tmp_path):
    p, base = serving
    userdata.note_project(str(tmp_path / "old.tctp"), 9, "manhua")
    h = _get(base, "/api/home")
    assert h["version"] and h["channel"]
    assert "signed_in" in h["account"] and "configured" in h["account"]
    assert h["current"] == {"pages": 0, "name": "", "path": "", "medium": p.settings.get("medium") or ""} \
        or h["current"]["pages"] == 0
    assert h["recent"][0]["name"] == "old" and h["recent"][0]["exists"] is False
    got = _post(base, "/api/home", {"do": "forget", "path": str(tmp_path / "old.tctp")})
    assert got["ok"] and got["recent"] == []


def test_the_account_route_is_the_websites_page_without_a_token(serving, monkeypatch):
    p, base = serving
    from mangatl import account
    monkeypatch.setattr(account, "signed_in", lambda: False)
    v = _get(base, "/api/account")
    assert v["icons"] == list(account.ICONS) and v["ledger"] == [] and v["packs"] == {}
    assert "token" not in json.dumps(v).lower().replace("tokens", "")
    # signed in: the receipt comes from the function, packs beside it
    monkeypatch.setattr(account, "signed_in", lambda: True)
    monkeypatch.setattr(account, "state", lambda: {"configured": True, "signed_in": True,
                                                    "email": "a@b.c", "username": "lee",
                                                    "photo": "cat", "balance": 12})
    monkeypatch.setattr(account, "ledger", lambda n=50: {"rows": [{"kind": "credit", "what": "welcome",
                                                                     "coins": 100, "at": 1, "page": ""}],
                                                          "packs": {"pack1": "small"}})
    v = _get(base, "/api/account")
    assert v["ledger"][0]["what"] == "welcome" and v["packs"] == {"pack1": "small"}
    assert v["account"]["photo"] == "cat"


def test_the_account_page_draws_what_the_website_draws():
    js = (PKG / "static" / "js" / "coins.js").read_text(encoding="utf-8")
    body = js[js.index("const ACCT_ICONS"):]
    for must in ("Everything that moved", "How people see you", "acctSaveName()", "acctSetPic(",
                 "Free coins for signing up", "walletSignOut()", "buyCoins()"):
        assert must in body, must
    assert "const ACCT_ICONS = ['fox','cat','moon','star','bolt','leaf','wave','ink','panel','brush'];" in js
    assert "(n * 36 + 20) % 360" in js, "the same picture, drawn the same way as the site"
    fn = (PKG / "firebase" / "functions" / "index.js").read_text(encoding="utf-8")
    assert "export const ledgerLines = onCall(" in fn and "orderBy('at', 'desc').limit(n)" in fn
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'elif do == "photo":' in src


def test_the_picture_is_written_the_way_the_website_writes_it(monkeypatch, tmp_path):
    from mangatl import account
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path))
    monkeypatch.setattr(account, "config", lambda: {"projectId": "mangatctproject", "apiKey": "k"})
    monkeypatch.setattr(account, "_read", lambda: {"uid": "u1", "refreshToken": "r", "idToken": "t",
                                                   "expires": 9e12})
    monkeypatch.setattr(account, "token", lambda force=False: "ID")
    written = []
    monkeypatch.setattr(account, "_write", lambda d: written.append(d))
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake_open(req, timeout=0):
        seen["url"] = req.full_url; seen["method"] = req.get_method()
        seen["body"] = json.loads(req.data); seen["auth"] = req.get_header("Authorization")
        return R()
    monkeypatch.setattr(account.urllib.request, "urlopen", fake_open)
    assert account.set_photo("moon") == {"photo": "moon"}
    assert seen["method"] == "PATCH" and seen["auth"] == "Bearer ID"
    assert seen["url"].endswith("/documents/users/u1?updateMask.fieldPaths=photo")
    assert seen["body"] == {"fields": {"photo": {"stringValue": "moon"}}}
    assert written and written[0]["photo"] == "moon"
    with pytest.raises(account.AccountError):
        account.set_photo("dragon")
