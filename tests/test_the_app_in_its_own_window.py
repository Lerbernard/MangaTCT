"""MangaTCT in a window of its own, and the browser kept for the day it is
hosted.

lee: *"make it run on its own app insted of teh browser"*, then *"keep a
version of this for the future if we want to host it instead"*.

Two things are under test. `mangatl/window.py`, which opens a WebView2 window
on the running editor - the page is untouched, only what shows it changed -
is tested against a stand-in for pywebview, because there is no WebView2 on
Linux and no display in CI. And the launcher, which starts that window as a
second process and falls back to the browser when it cannot: a runtime with
no pywebview, a Windows with no WebView2, a version of the app from before
the window existed, or `--browser` asked for outright.
"""
import json
import os
import subprocess
import sys
import types

import pytest

from where import PKG
from mangatl import window as W

sys.path.insert(0, str(PKG / "launcher"))
import mangatct_launcher as L  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    return tmp_path


# -------------------------------------------------------------- the module

def test_it_is_told_the_port_and_builds_the_editors_address():
    a = W.parse(["--port", "8765"])
    assert W.url_for(a) == "http://127.0.0.1:8765/"
    assert a.title == "MangaTCT" and a.debug is False
    with pytest.raises(SystemExit):
        W.parse([])


def test_the_window_remembers_where_it_was(home):
    assert W.load_geometry() == {}
    W.save_geometry({"width": 1500, "height": 950, "x": 40, "y": 30, "maximized": False})
    assert W.load_geometry() == {"width": 1500, "height": 950, "x": 40, "y": 30,
                                 "maximized": False}
    assert os.path.basename(W.geometry_path()) == "window.json"


def test_a_remembered_size_below_the_minimum_or_a_corrupt_file_is_ignored(home):
    W.save_geometry({"width": 300, "height": 200, "maximized": True})
    g = W.load_geometry()
    assert "width" not in g and g["maximized"] is True
    with open(W.geometry_path(), "w") as fh:
        fh.write("{not json")
    assert W.load_geometry() == {}
    with open(W.geometry_path(), "w") as fh:
        json.dump([1, 2], fh)
    assert W.load_geometry() == {}


def test_a_position_on_a_monitor_that_is_gone_is_dropped_and_the_size_kept():
    S = types.SimpleNamespace
    screens = [S(x=0, y=0, width=1920, height=1080)]
    g = {"width": 1400, "height": 900, "x": 2500, "y": 100, "maximized": False}
    out = W._on_screen(g, screens)
    assert "x" not in out and out["width"] == 1400
    assert W._on_screen(g, [S(x=1920, y=0, width=2560, height=1440)]) == g
    assert W._on_screen(g, []) == g, "no screens known: nothing to judge by"


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for fn in self.handlers:
            fn()


class FakeWindow:
    def __init__(self, **kw):
        self.kw = kw
        self.width, self.height = kw["width"], kw["height"]
        self.x, self.y = kw.get("x") or 100, kw.get("y") or 80
        self.native = types.SimpleNamespace(WindowState="Normal")
        self.events = types.SimpleNamespace(resized=FakeEvent(), moved=FakeEvent(),
                                            closing=FakeEvent(), shown=FakeEvent())


def fake_webview(monkeypatch, is_chromium=True):
    """pywebview, as far as `window.py` needs it, in memory."""
    wv = types.ModuleType("webview")
    wv.settings = {"ALLOW_DOWNLOADS": False, "OPEN_EXTERNAL_LINKS_IN_BROWSER": True}
    wv.screens = [types.SimpleNamespace(x=0, y=0, width=2560, height=1440)]
    made, started = [], []

    def create_window(title, url, **kw):
        w = FakeWindow(title=title, url=url, **kw)
        made.append(w)
        return w

    def start(**kw):
        started.append(kw)
        for w in made:                      # the person closes it
            w.events.closing.fire()

    wv.create_window, wv.start = create_window, start
    platforms = types.ModuleType("webview.platforms")
    winforms = types.ModuleType("webview.platforms.winforms")
    winforms.is_chromium = is_chromium
    platforms.winforms = winforms
    monkeypatch.setitem(sys.modules, "webview", wv)
    monkeypatch.setitem(sys.modules, "webview.platforms", platforms)
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", winforms)
    return wv, made, started


def test_it_opens_the_editor_where_it_was_last_time_and_remembers_on_close(home, monkeypatch):
    W.save_geometry({"width": 1500, "height": 950, "x": 40, "y": 30, "maximized": False})
    wv, made, started = fake_webview(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    assert W.main(["--port", "8123"]) == W.EXIT_CLOSED
    w = made[0].kw
    assert w["url"] == "http://127.0.0.1:8123/" and w["title"] == "MangaTCT"
    assert (w["width"], w["height"], w["x"], w["y"]) == (1500, 950, 40, 30)
    assert w["min_size"] == W.MIN_SIZE and w["background_color"] == W.BACKGROUND
    assert w["text_select"] is True, "the editor has text fields"
    # what start was told
    st = started[0]
    assert st["private_mode"] is False, "localStorage holds the person's preferences"
    assert st["storage_path"].endswith("webview")
    assert st["icon"] and st["icon"].endswith("icon.ico")
    assert wv.settings["ALLOW_DOWNLOADS"] is True, "zips, .tct files and translation json"
    assert wv.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True, "Buy coins opens a real browser"
    # closing wrote the geometry back
    assert W.load_geometry() == {"width": 1500, "height": 950, "x": 40, "y": 30,
                                 "maximized": False}


def test_a_window_moved_and_resized_is_remembered_as_it_ended(home, monkeypatch):
    wv, made, started = fake_webview(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")

    def start(**kw):
        w = made[0]
        w.width, w.height, w.x, w.y = 1700, 1000, 10, 20
        w.events.resized.fire()
        w.events.moved.fire()
        w.events.closing.fire()
    wv.start = start
    W.main(["--port", "1"])
    assert W.load_geometry() == {"width": 1700, "height": 1000, "x": 10, "y": 20,
                                 "maximized": False}


def test_maximised_is_remembered_as_maximised_not_as_a_size(home, monkeypatch):
    wv, made, started = fake_webview(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")

    def start(**kw):
        w = made[0]
        w.native.WindowState = "Maximized"
        w.width, w.height = 2560, 1400          # what a maximised form reports
        w.events.resized.fire()
        w.events.closing.fire()
    wv.start = start
    W.main(["--port", "1"])
    g = W.load_geometry()
    assert g["maximized"] is True
    assert "width" not in g, "so un-maximising next time gives the old size, not the screen"


def test_no_pywebview_and_no_webview2_are_exit_codes_the_launcher_reads(home, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)       # import fails
    assert W.main(["--port", "1"]) == W.EXIT_NO_WEBVIEW
    fake_webview(monkeypatch, is_chromium=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(W, "_own_taskbar_entry", lambda: None)
    assert W.main(["--port", "1"]) == W.EXIT_NO_RUNTIME
    assert L.WINDOW_EXITS[W.EXIT_NO_WEBVIEW] and L.WINDOW_EXITS[W.EXIT_NO_RUNTIME]


def test_on_windows_the_edge_engine_is_asked_for_by_name(home, monkeypatch):
    """pywebview picks a GUI by itself; on Windows that must be WebView2 and
    never the old IE engine the editor does not run on."""
    wv, made, started = fake_webview(monkeypatch, is_chromium=True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(W, "_own_taskbar_entry", lambda: None)
    assert W.main(["--port", "1"]) == 0
    assert started[0]["gui"] == "edgechromium"


# ------------------------------------------------------------- the launcher

class FakeProc:
    def __init__(self, exits_with=None, after=0.0):
        self.code, self.after = exits_with, after
        self.t0 = __import__("time").time()
        self.terminated = False

    def poll(self):
        if self.code is None:
            return None
        return self.code if __import__("time").time() - self.t0 >= self.after else None

    def wait(self, timeout=None):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15


def test_the_flag_and_the_variable_keep_the_browser(monkeypatch):
    monkeypatch.delenv("MANGATCT_BROWSER", raising=False)
    assert L.want_window([]) is True
    assert L.want_window(["--browser"]) is False
    monkeypatch.setenv("MANGATCT_BROWSER", "1")
    assert L.want_window([]) is False


def test_a_window_that_dies_at_once_means_the_browser(monkeypatch):
    monkeypatch.setattr(L, "WINDOW_GRACE", 0.3)
    logged = []
    monkeypatch.setattr(L, "log", logged.append)
    assert L.window_alive(FakeProc(exits_with=4)) is False
    assert any("no WebView2" in m for m in logged)
    assert L.window_alive(FakeProc(exits_with=3)) is False
    assert L.window_alive(None) is False
    assert L.window_alive(FakeProc()) is True, "still running after the grace: a window"


def test_an_app_version_without_a_window_module_gets_the_browser(tmp_path, monkeypatch):
    p = L.paths(str(tmp_path / "MangaTCT"))
    L.ensure_dirs(p)
    vdir = L.app_dir(p, "0.9.0")
    os.makedirs(os.path.join(vdir, "mangatl"))
    logged = []
    monkeypatch.setattr(L, "log", logged.append)
    assert L.start_window(p, "0.9.0", 8765) is None
    assert any("no window module" in m for m in logged)


def test_the_start_prefers_the_window_and_falls_back_to_the_browser(tmp_path, monkeypatch):
    """`run` with everything but the last step stubbed: the editor is up,
    and what shows it is decided here. Window alive: no browser. Window
    dead: browser. `--browser`: no window started at all."""
    p = L.paths(str(tmp_path / "MangaTCT"))
    L.ensure_dirs(p)
    opened = []
    monkeypatch.setitem(sys.modules, "webbrowser",
                        types.SimpleNamespace(open=lambda u: opened.append(u)))
    monkeypatch.setattr(L, "start_log", lambda p: None)
    monkeypatch.setattr(L, "fetch_manifest", lambda u: None)
    monkeypatch.setattr(L, "check_for_update", lambda *a, **k: None)
    monkeypatch.setattr(L, "choose_and_prepare", lambda p, progress=None: ("1.0.0", False, ""))
    monkeypatch.setattr(L, "write_state", lambda *a, **k: None)
    monkeypatch.setattr(L, "prune_old", lambda *a, **k: None)
    monkeypatch.setattr(L, "ensure_models", lambda *a, **k: "")
    monkeypatch.setattr(L, "say_update", lambda *a, **k: None)
    monkeypatch.setattr(L, "free_port", lambda: 8765)
    monkeypatch.setattr(L, "start_editor", lambda p, v, port: FakeProc())
    monkeypatch.setattr(L, "wait_for_editor", lambda port, proc: True)
    monkeypatch.setattr(L, "watch_for_updates", lambda *a, **k: None)
    monkeypatch.setattr(L, "WINDOW_GRACE", 0.2)
    started = []

    def start_window(p, v, port, proc=None):
        started.append((v, port))
        return start_window.next
    monkeypatch.setattr(L, "start_window", start_window)

    start_window.next = FakeProc()                    # a window that lives
    s = L.run(p, manifest_url="x", open_browser=True, window=True)
    assert s.shown_in == "window" and s.window is not None and opened == []
    assert started == [("1.0.0", 8765)]

    start_window.next = FakeProc(exits_with=4)        # no WebView2
    s = L.run(p, manifest_url="x", open_browser=True, window=True)
    assert s.shown_in == "browser" and s.window is None
    assert opened == ["http://127.0.0.1:8765"]

    opened.clear()
    s = L.run(p, manifest_url="x", open_browser=True, window=False)   # --browser
    assert s.shown_in == "browser" and len(started) == 2, "no window was even tried"

    opened.clear()
    s = L.run(p, manifest_url="x", open_browser=False, window=False)  # the tests' way
    assert s.shown_in == "" and opened == []


def test_the_window_is_part_of_the_app_zip_and_the_runtime_proves_it():
    """The window updates with the app, so it ships in the app zip; the
    Windows build imports it and pywebview from the staged runtime before
    the installer is made."""
    sys.path.insert(0, str(PKG / "tools"))
    import release as R
    arcs = {arc for _, arc in R.files_for_zip()}
    assert "mangatl/window.py" in arcs
    assert "mangatl/static/icon.ico" in arcs, "the window's icon"
    ps = (PKG / "launcher" / "build_runtime.ps1").read_text(encoding="utf-8")
    assert "mangatl.window" in ps and "webview" in ps
    req = (PKG / "requirements.txt").read_text(encoding="utf-8")
    assert 'pywebview>=6.0; sys_platform == "win32"' in req, \
        "Windows only - the installer's platform, and where WebView2 already is"


def test_the_launcher_is_still_standard_library_only():
    """The window is the app's; the launcher only starts a process."""
    import ast
    src = (PKG / "launcher" / "mangatct_launcher.py").read_text(encoding="utf-8")
    assert "import webview" not in src
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert "webview" not in mods


# -------------------------------------------------------------- the mark

def test_the_launchers_own_window_wears_the_mark():
    """lee, with the launcher on screen wearing Tk's blue feather: *"use the
    logo everywhere"*. The mark rides inside the exe (PyInstaller `datas`), so
    it is there before any app version is on disk; the window sets it as its
    icon and shows it beside the name."""
    spec = (PKG / "launcher" / "MangaTCT.spec").read_text(encoding="utf-8")
    assert '"icon.ico"), ".")' in spec and '"icon.png"), ".")' in spec
    assert 'icon=os.path.join(root, "static", "icon.ico")' in spec, "the exe's own icon"
    src = (PKG / "launcher" / "mangatct_launcher.py").read_text(encoding="utf-8")
    assert "wear_the_mark(root)" in src and "mark_image(root)" in src
    assert "root.iconbitmap(default=ico)" in src
    ico, png = L.icon_files()
    assert ico.endswith("icon.ico") and png.endswith("icon.png")
    assert os.path.isfile(ico) and os.path.isfile(png)
    # ...and the same two files are what the app's own window and the folder
    # picker wear, so there is one mark, not three
    assert W._icon() == ico


def test_the_frame_is_dressed_in_the_apps_colours_once_the_window_shows(home, monkeypatch):
    """The title bar Windows draws round the page is white by default - the
    one thing left that said "a browser in a box". lee: *"make the window of
    the app actually look like it's part of the app"*. On `shown` the window
    asks DWM for the dark frame and for the caption in the editor's own
    background colour, and the launcher's little window asks the same."""
    wv, made, started = fake_webview(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(W, "dress_the_frame", lambda hwnd: calls.append(hwnd))
    monkeypatch.setattr(W, "_hwnd_of", lambda win: 4242)

    def start(**kw):
        made[0].events.shown.fire()
        made[0].events.closing.fire()
    wv.start = start
    W.main(["--port", "1"])
    assert calls == [4242]
    # COLORREF is 0x00BBGGRR; the editor's --bg #101216 is 0x161210
    assert W._colorref(W.FRAME_BG) == 0x161210
    assert W.DWMWA_USE_IMMERSIVE_DARK_MODE == 20 and W.DWMWA_CAPTION_COLOR == 35
    src = (PKG / "launcher" / "mangatct_launcher.py").read_text(encoding="utf-8")
    assert "dark_frame(root)" in src and "0x161210" in src, "the launcher's window, same colours"
