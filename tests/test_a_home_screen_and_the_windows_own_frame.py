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
    api._frameless = True
    w = _Win()
    api._win = w
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


def test_the_api_object_holds_nothing_pywebview_would_walk_into():
    """lee: *"the app is crashing when opening"* - pages of `[pywebview]
    Error while processing win.native.AccessibilityObject.Bounds.Empty.Empty
    ... maximum recursion depth exceeded`. pywebview builds the page's
    `pywebview.api` by walking every PUBLIC attribute of the object and
    recursing into any that is itself an object; `api.win` was the window,
    whose `.native` is a WinForms object graph with no bottom. So: the
    window and the flag are underscored, and the walk pywebview does (the
    same rule it uses, run here over an object shaped like the real one)
    finds exactly the verbs and nothing to recurse into."""
    import inspect

    class Bottomless:                    # `.native`: every attribute is another one
        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return Bottomless()

        def __dir__(self):
            return ["Bounds", "Empty", "Parent"]

    class Win:
        native = Bottomless()
        def minimize(self): pass

    api = W.Api()
    api._win = Win()
    api._frameless = True
    seen, functions = [], {}

    def walk(obj, base="", depth=0):     # pywebview's get_functions, in short
        assert depth < 5, "walked into " + base
        if id(obj) in seen:
            return
        seen.append(id(obj))
        for name in dir(obj):
            if name.startswith("_"):
                continue
            attr = getattr(obj, name)
            full = base + "." + name if base else name
            if inspect.ismethod(attr) or inspect.isfunction(attr):
                functions[full] = True
            elif inspect.isclass(attr) or (not callable(attr) and hasattr(attr, "__module__")):
                walk(attr, full, depth + 1)
    walk(api)
    assert set(functions) == {"state", "minimize", "toggle_maximize", "close", "hit", "focus"}
    assert not [n for n in vars(api) if not n.startswith("_")], \
        "every attribute on the Api object is private"


def test_the_native_drag_is_release_capture_then_nc_lbutton_down(monkeypatch):
    """...with WHERE THE MOUSE IS in lParam. Sent as 0, a move by the bar still
    worked, but a resize starts from that point: every edge did nothing on
    the real window and the window stopped answering."""
    import ctypes as real_ctypes
    calls = []

    def cursor(pt):
        pt[0], pt[1] = 1678, 580
    user32 = types.SimpleNamespace(ReleaseCapture=lambda: calls.append("release"),
                                   GetCursorPos=cursor,
                                   SendMessageW=lambda h, m, w, l: calls.append(("send", m, w.value, l)))
    fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=user32),
                                        c_long=real_ctypes.c_long,
                                        c_void_p=lambda v: v, c_size_t=lambda v: types.SimpleNamespace(value=v),
                                        c_ssize_t=lambda v: v)
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    win = types.SimpleNamespace(native=types.SimpleNamespace())      # no BeginInvoke: run inline
    assert W._begin_native_drag(win, 77, 17) is True
    assert calls == ["release", ("send", 0xA1, 17, (580 << 16) | 1678)]


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
    assert isinstance(kw["js_api"], W.Api) and kw["js_api"]._win is made[0]
    assert dressed == [True], "rounded corners asked for on the frameless window"
    assert kept == [1], "maximise stops at the taskbar"
    # ...and with --frame the system frame stays, and none of that happens
    made.clear(); dressed.clear(); kept.clear()
    assert W.main(["--port", "1", "--frame"]) == W.EXIT_CLOSED
    assert made[0].kw["frameless"] is False and dressed == [False] and kept == []


def test_a_double_click_on_the_bar_is_counted_by_the_window(monkeypatch):
    """On the real window two quick clicks on the bar did nothing. The first
    press hands the mouse to Windows' move loop, so the page never sees it
    let go and its `dblclick` never fires. The second press does reach the
    page, and `Api.hit` counts it: inside the system's double click time and
    distance it maximizes instead of starting another drag."""
    api = W.Api()
    api._frameless = True
    w = _Win()
    api._win = w
    monkeypatch.setattr(sys, "platform", "win32")
    drags = []
    monkeypatch.setattr(W, "_begin_native_drag", lambda win, hwnd, code: drags.append(code) or True)
    now, at = [100.0], [(500, 20)]
    monkeypatch.setattr(W, "_clock", lambda: now[0])
    monkeypatch.setattr(W, "_press_point", lambda: at[0] + (0.5, 4, 4))
    assert api.hit(2) is True and drags == [2] and w.calls == [], "one press is a drag"
    now[0] += 0.2
    assert api.hit(2) is True and drags == [2] and w.calls == ["max"], "two are a maximize"
    now[0] += 0.2
    assert api.hit(2) is True and drags == [2, 2], "a third press starts over"
    now[0] += 0.9
    assert api.hit(2) is True and drags == [2, 2, 2] and w.calls == ["max"], "too slow"
    now[0] += 0.1
    at[0] = (520, 20)
    assert api.hit(2) is True and drags == [2, 2, 2, 2] and w.calls == ["max"], "too far"
    now[0] += 0.1
    at[0] = (520, 21)
    assert api.hit(17) is True and drags[-1] == 17 and w.calls == ["max"], \
        "an edge is never a double click"

    def nowhere():
        raise OSError("no user32")
    monkeypatch.setattr(W, "_press_point", nowhere)
    assert api.hit(2) is True and api.hit(2) is True and w.calls == ["max"], \
        "where Windows cannot be asked, a press is a drag"


def test_maximized_stops_at_the_working_area_and_short_of_a_hiding_taskbar():
    """WM_GETMINMAXINFO wants the position relative to the MONITOR. And a
    window covering a whole monitor is a full-screen app to Windows, so a
    taskbar that hides itself - the working area is then the whole monitor -
    could never slide up over the maximized app."""
    # the taskbar along the bottom, always shown
    assert W.maximized_rect((0, 0, 3456, 2088), (0, 0, 3456, 2160)) == (0, 0, 3456, 2088)
    # lee's: it hides itself at the bottom, so the working area IS the monitor
    assert W.maximized_rect((0, 0, 3456, 2160), (0, 0, 3456, 2160), ("bottom",)) == \
        (0, 0, 3456, 2160 - W.AUTOHIDE_GAP)
    # on the left
    assert W.maximized_rect((48, 0, 1920, 1080), (0, 0, 1920, 1080)) == (48, 0, 1872, 1080)
    # a second monitor to the right: relative to IT, not to the desktop
    assert W.maximized_rect((1920, 0, 3840, 1040), (1920, 0, 3840, 1080)) == (0, 0, 1920, 1040)
    assert W.EDGES == ("left", "top", "right", "bottom"), "ABE_LEFT..ABE_BOTTOM"


def test_the_frame_windows_sizes_by_is_kept_and_hidden():
    """FormBorderStyle None takes WS_THICKFRAME away, and without it Windows
    ignored every edge the page sent and snapped nothing. The styles go back
    on; the frame they would draw is answered away."""
    for style in (0x40000, 0x80000, 0x20000, 0x10000):
        assert W.FRAME_STYLES & style
    src = (PKG / "window.py").read_text(encoding="utf-8")
    assert "if msg == WM_NCCALCSIZE and wparam:" in src
    assert "SetWindowSubclass" in src and "ABM_GETAUTOHIDEBAREX" in src
    assert "MaximizedBounds =" not in src, "WinForms' own bound is relative to the wrong thing"
    install = src.split("def _install_frame_hook")[1].split("def keep_off_the_taskbar")[0]
    assert "IsZoomed" in install and "_maximized_for(hwnd)" in install, \
        "a window that opened maximized is moved to where maximized ends now"


# ------------------------------------------------------------------ the page

def test_the_bar_carries_the_window_buttons_and_the_drag_strip():
    assert 'id="winctl" hidden' in HTML
    for b in ("wbMin", "wbMax", "wbClose"):
        assert 'id="%s"' % b in HTML
    assert 'id="tbDrag"' in HTML
    assert "window.addEventListener('pywebviewready'" in CHROME
    assert "if(st && st.frameless) wireChrome();" in CHROME, "only once the window says so"
    assert "api.hit(code)" in CHROME and "caption: 2" in CHROME and "bottomright: 17" in CHROME
    assert "addEventListener('dblclick'" not in CHROME, \
        "the page never sees a double click on its bar; Api.hit counts it"
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
