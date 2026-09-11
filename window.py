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
  open.
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
    return ap.parse_args(argv)


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
    win = webview.create_window(
        a.title, url_for(a), width=width, height=height,
        x=g.get("x"), y=g.get("y"), maximized=g.get("maximized", False),
        min_size=MIN_SIZE, background_color=BACKGROUND,
        text_select=True, zoomable=True)

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
