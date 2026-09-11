"""MangaTCT in a window of its own.

lee: *"make it run on its own app insted of teh browser"* - and, in the same
breath, *"keep a version of this for the future if we want to host it
instead"*. So the editor is still a web page served on 127.0.0.1 and nothing
about it changed; what changed is what shows it. This module opens a native
window whose whole content is that page, using the WebView2 engine Windows
already has (Edge's), so nothing new ships and the page runs exactly as it
does in Edge. The browser is still there - `MangaTCT.exe --browser`, or the
*Open in browser* button on the launcher - which is also what a hosted copy
would be.

    python -m mangatl.window --port 8765

It is its own PROCESS, started by the launcher after the editor answers and
watched by it: the window closing is how the person quits, so when this
process ends the launcher stops the editor. The launcher itself stays
standard-library and knows nothing about webviews; this file, being part of
the app, is updated with the app.

What is deliberately done here, and why:

* the window remembers its size, place and whether it was maximised, in
  `~/.mangatl/window.json` - a window that opens 800x600 every morning on a
  4K screen is a window somebody fights every morning;
* `private_mode=False` with a storage path of ours: the editor keeps
  preferences in localStorage, and a private webview would forget them at
  every start;
* downloads are allowed (the editor hands out zips, `.tct` files and
  translation JSON) and arrive through a Save As dialog, which is better than
  a browser's silent drop into Downloads;
* links that open a new tab - Buy coins, the guide, Discord - go to the
  person's real browser, because a second webview with no address bar is not
  where anyone wants to read a website;
* the browser's own accelerator keys (F5, Ctrl+P...) stay off, so a stray
  refresh cannot reload a chapter mid-edit; the editor's own shortcuts are
  JavaScript and still arrive;
* if there is no WebView2 runtime (rare - Windows 10 has shipped it since
  2022 and Windows 11 always had it) or pywebview is not installed, this
  exits with a code the launcher understands, and the launcher opens the
  browser instead. Nothing here is allowed to be the reason the app does not
  open;
* THE WINDOW HAS NO FRAME OF ITS OWN. lee: *"instead of having a separate
  top bar like this, integrate it with the app"*. The page's own top bar is
  the title bar: it carries the window buttons, and dragging its empty part
  moves the window. Both are done the way Windows wants them done - the
  page tells this process which part of the frame the mouse went down on
  (`Api.hit`, a WM_NCHITTEST code) and Windows runs its own move or resize
  loop, so dragging is smooth and Aero snap works. `MANGATCT_FRAME=1` or
  `--frame` keeps the system frame, for the day something needs it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import userdata

TITLE = "MangaTCT"
GEOMETRY = "window.json"
MIN_SIZE = (960, 640)
DEFAULT_SIZE = (1440, 900)
#: The editor's own page background (static/css/editor.css `--bg`), painted
#: before the page arrives so the first frame is not a white flash.
BACKGROUND = "#101216"
#: Groups the window under its own taskbar entry instead of python.exe's.
APP_ID = "LMBTechnology.MangaTCT"

#: The frame the page draws: WM_NCHITTEST codes for `Api.hit`. 2 is the
#: caption (move); 10-17 the eight edges and corners (resize).
HTCAPTION = 2
HIT_CODES = {2, 10, 11, 12, 13, 14, 15, 16, 17}
WM_NCLBUTTONDOWN = 0xA1

#: Exit codes the launcher reads. Anything else is a crash.
EXIT_CLOSED = 0          # the person closed the window
EXIT_NO_WEBVIEW = 3      # pywebview is not installed in this runtime
EXIT_NO_RUNTIME = 4      # no WebView2 on this Windows
EXIT_BAD_ARGS = 2


# ---------------------------------------------------------------- geometry

def geometry_path() -> str:
    return os.path.join(userdata.user_dir(), GEOMETRY)


def load_geometry() -> dict:
    """What the window was last time, or nothing. Anything off - a corrupt
    file, a size smaller than the minimum, a position on a monitor that has
    since been unplugged - is answered by ignoring it, never by refusing to
    open."""
    try:
        with open(geometry_path(), encoding="utf8") as fh:
            g = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(g, dict):
        return {}
    out = {}
    try:
        w, h = int(g.get("width", 0)), int(g.get("height", 0))
        if w >= MIN_SIZE[0] and h >= MIN_SIZE[1] and w <= 20000 and h <= 20000:
            out["width"], out["height"] = w, h
        if "x" in g and "y" in g:
            x, y = int(g["x"]), int(g["y"])
            if -10000 < x < 20000 and -10000 < y < 20000:
                out["x"], out["y"] = x, y
        out["maximized"] = bool(g.get("maximized", False))
    except (TypeError, ValueError):
        return {}
    return out


def save_geometry(g: dict) -> None:
    try:
        os.makedirs(userdata.user_dir(), exist_ok=True)
        tmp = geometry_path() + ".tmp"
        with open(tmp, "w", encoding="utf8") as fh:
            json.dump(g, fh, indent=1)
        os.replace(tmp, geometry_path())
    except OSError:
        pass


def _on_screen(g: dict, screens) -> dict:
    """Drop a remembered position that no screen contains any more. The
    size is kept; the OS puts an unplaced window somewhere sensible."""
    if "x" not in g or not screens:
        return g
    x, y = g["x"], g["y"]
    for s in screens:
        sx, sy = getattr(s, "x", 0), getattr(s, "y", 0)
        if sx - 8 <= x < sx + s.width and sy - 8 <= y < sy + s.height:
            return g
    g = dict(g)
    g.pop("x", None)
    g.pop("y", None)
    return g


# ------------------------------------------------------------------ the run

def parse(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m mangatl.window")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--title", default=TITLE)
    ap.add_argument("--debug", action="store_true",
                    help="devtools, context menu and F12 on")
    ap.add_argument("--frame", action="store_true",
                    help="keep the system title bar instead of the app's own")
    return ap.parse_args(argv)


def want_frame(a: argparse.Namespace) -> bool:
    """The system frame, only when asked for. Off Windows the page's own
    buttons cannot drive the window, so the frame stays there too."""
    if a.frame or os.environ.get("MANGATCT_FRAME"):
        return True
    return sys.platform != "win32"


class Api:
    """What the page may ask of its window: `window.pywebview.api.*`.

    Five verbs and one question, and all but one of them is something the
    system frame used to do - now the page's top bar does it. `hit` is the
    move and the resize both: told which part of a frame the mouse went
    down on, Windows runs the drag itself. `focus` is the odd one: the page
    asking to be brought back to the front after a sign-in in the browser."""

    def __init__(self):
        self.win = None
        self.frameless = False

    def state(self) -> dict:
        return {"frameless": bool(self.frameless), "maximized": _is_maximized(self.win)}

    def minimize(self) -> None:
        if self.win is not None:
            self.win.minimize()

    def toggle_maximize(self) -> bool:
        if self.win is None:
            return False
        if _is_maximized(self.win):
            self.win.restore()
            return False
        self.win.maximize()
        return True

    def close(self) -> None:
        if self.win is not None:
            self.win.destroy()

    def focus(self) -> bool:
        """Come to the front. Asked once a sign-in made in the browser has
        reached the app, so the person is not left looking at a tab that
        says "go back to the app". Windows only lets a process take the
        foreground when it is allowed to; when it is not, the taskbar entry
        flashes instead, which is the right thing to happen."""
        if self.win is None or sys.platform != "win32":
            return False
        hwnd = _hwnd_of(self.win)
        if not hwnd:
            return False
        try:
            import ctypes
            u = ctypes.windll.user32
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, 9)               # SW_RESTORE
            return bool(u.SetForegroundWindow(hwnd))
        except Exception:
            return False

    def hit(self, code: int) -> bool:
        """The mouse went down on the frame at `code` (WM_NCHITTEST): hand
        the drag to Windows. Sent to the form's own thread, because that is
        the thread the sizing loop has to run on."""
        try:
            code = int(code)
        except (TypeError, ValueError):
            return False
        if code not in HIT_CODES or sys.platform != "win32" or self.win is None:
            return False
        hwnd = _hwnd_of(self.win)
        if not hwnd:
            return False
        return _begin_native_drag(self.win, hwnd, code)


def _begin_native_drag(win, hwnd: int, code: int) -> bool:
    """ReleaseCapture, then WM_NCLBUTTONDOWN with the hit code - the oldest
    trick for a borderless window, and the one the shell itself uses."""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        def go():
            user32.ReleaseCapture()
            user32.SendMessageW(ctypes.c_void_p(hwnd), WM_NCLBUTTONDOWN,
                                ctypes.c_size_t(code), ctypes.c_ssize_t(0))
        native = getattr(win, "native", None)
        invoke = getattr(native, "BeginInvoke", None)
        if invoke is not None:
            try:
                from System import Action           # type: ignore
                invoke(Action(go))
                return True
            except Exception:
                pass
        go()
        return True
    except Exception:
        return False


def url_for(a: argparse.Namespace) -> str:
    return "http://%s:%d/" % (a.host, a.port)


def _own_taskbar_entry() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


# The window's own frame in the app's colours. WebView2 draws the page; the
# title bar round it is Windows', and by default it is white - a white strip
# over a dark app, which is the one thing that said "this is a browser in a
# box". DWM lets a window ask for the dark frame (Windows 10 1809+) and, on
# Windows 11, for the caption, border and title text in colours of its own.
# The colours are the editor's: `--bg` #101216 and its text.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
FRAME_BG = (0x10, 0x12, 0x16)
FRAME_FG = (0xE6, 0xE8, 0xEC)


def _colorref(rgb) -> int:
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def dress_the_frame(hwnd: int, frameless: bool = False) -> None:
    """Dark frame, app-coloured caption; and on a frameless window, rounded
    corners (Windows 11). Every call may fail on an older Windows and none
    of them matters if it does."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        attrs = [(DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
                 (DWMWA_CAPTION_COLOR, _colorref(FRAME_BG)),
                 (DWMWA_BORDER_COLOR, _colorref(FRAME_BG)),
                 (DWMWA_TEXT_COLOR, _colorref(FRAME_FG))]
        if frameless:
            attrs.append((DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND))
        for attr, value in attrs:
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                      ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def keep_off_the_taskbar(win) -> None:
    """A borderless WinForms window maximises over the taskbar unless told
    the screen's working area; told here, and again whenever it moves, so
    a second monitor gets its own."""
    try:
        native = win.native
        from System.Windows.Forms import Screen       # type: ignore
        native.MaximizedBounds = Screen.FromControl(native).WorkingArea
    except Exception:
        pass


def _hwnd_of(win) -> int:
    try:
        return int(win.native.Handle.ToInt64())
    except Exception:
        return 0


def _icon() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "static", "icon.ico")
    return p if os.path.isfile(p) else None


def main(argv=None) -> int:
    a = parse(sys.argv[1:] if argv is None else argv)
    try:
        import webview
    except ImportError:
        print("pywebview is not installed; open the browser instead", file=sys.stderr)
        return EXIT_NO_WEBVIEW

    gui = None
    if sys.platform == "win32":
        # pywebview falls back to the old IE engine when WebView2 is absent,
        # silently. The editor does not run on that engine, so the check is
        # made here and the answer is "use the browser", not a blank window.
        try:
            from webview.platforms import winforms
            if not getattr(winforms, "is_chromium", False):
                print("no WebView2 runtime; open the browser instead", file=sys.stderr)
                return EXIT_NO_RUNTIME
        except Exception as e:      # pythonnet missing, clr load failed...
            print("webview cannot start here: %r" % e, file=sys.stderr)
            return EXIT_NO_RUNTIME
        gui = "edgechromium"

    _own_taskbar_entry()
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    g = _on_screen(load_geometry(), _screens(webview))
    width, height = g.get("width", DEFAULT_SIZE[0]), g.get("height", DEFAULT_SIZE[1])
    frameless = not want_frame(a)
    api = Api()
    api.frameless = frameless
    win = webview.create_window(
        a.title, url_for(a), width=width, height=height,
        x=g.get("x"), y=g.get("y"), maximized=g.get("maximized", False),
        min_size=MIN_SIZE, background_color=BACKGROUND,
        text_select=True, zoomable=True,
        frameless=frameless, easy_drag=False, js_api=api)
    api.win = win

    state = {"maximized": g.get("maximized", False)}

    def remember(*_):
        try:
            state["maximized"] = bool(_is_maximized(win))
            if not state["maximized"]:
                state.update(width=win.width, height=win.height, x=win.x, y=win.y)
        except Exception:
            pass

    def closing(*_):
        remember()
        keep = {"maximized": state["maximized"]}
        for k in ("width", "height", "x", "y"):
            if k in state:
                keep[k] = state[k]
        save_geometry(keep)

    win.events.resized += remember
    win.events.moved += remember
    win.events.closing += closing

    def shown(*_):
        dress_the_frame(_hwnd_of(win), frameless)
        if frameless:
            keep_off_the_taskbar(win)
    win.events.shown += shown
    if frameless:
        win.events.moved += lambda *_: keep_off_the_taskbar(win)
    webview.start(gui=gui, debug=a.debug, private_mode=False,
                  storage_path=os.path.join(userdata.user_dir(), "webview"),
                  icon=_icon())
    return EXIT_CLOSED


def _screens(webview):
    try:
        return list(webview.screens)
    except Exception:
        return []


def _is_maximized(win) -> bool:
    """WinForms says so directly; elsewhere a window the size of its screen
    is as good an answer as there is."""
    try:
        native = getattr(win, "native", None)
        st = getattr(native, "WindowState", None)
        if st is not None:
            return str(st) == "Maximized"
    except Exception:
        pass
    return False


if __name__ == "__main__":
    raise SystemExit(main())
