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
  Windows only sizes and snaps a window that has a sizing frame, so the
  frame's styles are kept and the frame itself is hidden (`the frame hook`,
  below).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

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

#: The clock a double click on the bar is timed by; the tests replace it.
_clock = time.monotonic


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

    Six verbs and one question, and all but two of them are things the
    system frame used to do - now the page's top bar does them. `hit` is the
    move and the resize both: told which part of a frame the mouse went
    down on, Windows runs the drag itself. `focus` and `open_url` are the odd ones: the
    page asking to be brought back to the front after a sign-in in the browser,
    and asking for the website to be opened in front of it."""

    # UNDERSCORES, ON PURPOSE. pywebview builds `window.pywebview.api` by
    # walking every public attribute of this object and recursing into any
    # that is an object - and the window is an object whose `.native` is the
    # whole WinForms form, an object graph with no bottom. With `win` public
    # the walk went `win.native.AccessibilityObject.Bounds.Empty.Empty...`
    # until Python's recursion limit, once per attribute, and the app never
    # came up (lee: *"the app is crashing when opening"*). Names that start
    # with `_` are skipped by that walk.
    def __init__(self):
        self._win = None
        self._frameless = False
        self._last_press = None

    def state(self) -> dict:
        return {"frameless": bool(self._frameless), "maximized": _is_maximized(self._win)}

    def minimize(self) -> None:
        if self._win is not None:
            self._win.minimize()

    def toggle_maximize(self) -> bool:
        if self._win is None:
            return False
        if _is_maximized(self._win):
            self._win.restore()
            return False
        self._win.maximize()
        return True

    def close(self) -> None:
        if self._win is not None:
            self._win.destroy()

    def focus(self) -> bool:
        """Come to the front. Asked once a sign-in made in the browser has
        reached the app, so the person is not left looking at a tab that
        says "go back to the app". Windows only lets a process take the
        foreground when it is allowed to; when it is not, the taskbar entry
        flashes instead, which is the right thing to happen."""
        if self._win is None or sys.platform != "win32":
            return False
        hwnd = _hwnd_of(self._win)
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

    def open_url(self, url: str) -> bool:
        """Open a page of the website in the person's own browser, IN FRONT.
        lee: *"when i click sign in with google in teh app it signltly opnes teh
        tab but sindt make teh brwoser show up on top so i dont realize it
        oppened"*.

        Windows lets a program put another window in front only while it is
        the one being used. The editor's server opened the sign-in page before,
        and it never is, so the browser took the tab and stayed behind the app.
        This window IS the one that was just clicked, so it can hand that
        permission on - `AllowSetForegroundWindow(ASFW_ANY)` - before the shell
        opens the address, and a browser that was already running, which is
        what takes the tab, is allowed to come forward with it.

        Only https addresses: the page's scripts can call this, and nothing on
        it has any business opening a file or a program."""
        url = str(url or "")
        if not url.startswith("https://"):
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.AllowSetForegroundWindow(-1)     # ASFW_ANY
            except Exception:
                pass
            try:
                os.startfile(url)
                return True
            except (OSError, AttributeError):
                pass
        import webbrowser
        return bool(webbrowser.open(url))

    def hit(self, code: int) -> bool:
        """The mouse went down on the frame at `code` (WM_NCHITTEST): hand
        the drag to Windows. Sent to the form's own thread, because that is
        the thread the sizing loop has to run on."""
        try:
            code = int(code)
        except (TypeError, ValueError):
            return False
        if code not in HIT_CODES or sys.platform != "win32" or self._win is None:
            return False
        # A DOUBLE CLICK ON THE BAR is counted here, because the page cannot
        # count it. The first press has already handed the mouse to Windows'
        # move loop, so the page never sees that press let go and its
        # `dblclick` never fires - on the real window, two quick clicks on
        # the bar did nothing at all. The second press does reach the page,
        # and so arrives here: inside the system's own double click time and
        # distance, it maximizes (or restores) instead of starting a drag.
        if code == HTCAPTION and self._second_press():
            self.toggle_maximize()
            return True
        hwnd = _hwnd_of(self._win)
        if not hwnd:
            return False
        return _begin_native_drag(self._win, hwnd, code)

    def _second_press(self) -> bool:
        try:
            x, y, limit, dx, dy = _press_point()
        except Exception:
            return False
        now = _clock()
        last, self._last_press = self._last_press, (now, x, y)
        if last and now - last[0] <= limit and abs(x - last[1]) <= dx and abs(y - last[2]) <= dy:
            self._last_press = None              # a third press starts over
            return True
        return False


def _press_point():
    """Where the mouse is, and what Windows calls a double click there:
    `(x, y, seconds, dx, dy)`. Raises where there is no user32."""
    import ctypes
    u = ctypes.windll.user32
    pt = (ctypes.c_long * 2)()
    u.GetCursorPos(pt)
    return (pt[0], pt[1], u.GetDoubleClickTime() / 1000.0,
            u.GetSystemMetrics(36), u.GetSystemMetrics(37))     # SM_CX/CYDOUBLECLK


def _begin_native_drag(win, hwnd: int, code: int) -> bool:
    """ReleaseCapture, then WM_NCLBUTTONDOWN with the hit code and where the
    mouse is - the oldest trick for a borderless window, and the one the
    shell itself uses.

    WHERE THE MOUSE IS, in lParam, as the message says it should be. It went
    as 0 at first, and a move by the bar never noticed (Windows reads the
    cursor itself before a move), but a resize starts from that point: on
    the real window every edge and corner did nothing, and the window
    stopped answering until something else was clicked. With the point in
    it, all eight edges size and dragging to the top of the screen snaps."""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        def go():
            pt = (ctypes.c_long * 2)()
            user32.GetCursorPos(pt)
            where = ((pt[1] & 0xFFFF) << 16) | (pt[0] & 0xFFFF)
            user32.ReleaseCapture()
            user32.SendMessageW(ctypes.c_void_p(hwnd), WM_NCLBUTTONDOWN,
                                ctypes.c_size_t(code), ctypes.c_ssize_t(where))
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


# ----------------------------------------------------------- the frame hook
#
# FormBorderStyle None is what makes the window frameless, and it also takes
# away the styles Windows looks for before it will size a window or snap it.
# Without WS_THICKFRAME the page's eight edges sent their hit codes and
# Windows ignored every one: on the real window, not a pixel of resize at any
# edge or corner, and dragging to the top or the side of the screen snapped
# nothing. So the styles go back on, and the frame they would draw is taken
# off again by answering WM_NCCALCSIZE with "all of it is page" - the way
# Chromium, Electron and every other app that draws its own title bar does it.
#
# The same hook decides where a maximized window goes (WM_GETMINMAXINFO).
# WinForms' MaximizedBounds used to, and was wrong twice over. It wants the
# position relative to the MONITOR and was handed the working area in desktop
# coordinates, which on a second monitor puts the maximized window off to one
# side of it. And a window that covers a whole monitor is, to Windows, a
# full-screen app, so a taskbar that hides itself - lee's does - can no longer
# slide up over it: with the working area the size of the monitor, maximized
# covered the taskbar for good. Maximized now stops at the working area, and
# AUTOHIDE_GAP pixels short of any edge whose taskbar hides itself, which is
# enough for Windows to see an ordinary window and for the mouse to reach it.

GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
FRAME_STYLES = WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
WM_GETMINMAXINFO = 0x0024
WM_NCDESTROY = 0x0082
WM_NCCALCSIZE = 0x0083
#: SWP_FRAMECHANGED | NOSIZE | NOMOVE | NOZORDER | NOACTIVATE
SWP_FRAME_CHANGED = 0x0020 | 0x0001 | 0x0002 | 0x0004 | 0x0010
ABM_GETAUTOHIDEBAREX = 0x0000000B
AUTOHIDE_GAP = 2
#: ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM, in that order.
EDGES = ("left", "top", "right", "bottom")

_HOOKED: set = set()
_W32: dict = {}
_AUTOHIDE: dict = {}


def maximized_rect(work, monitor, autohide=()) -> tuple:
    """Where a maximized window goes, the way WM_GETMINMAXINFO wants it:
    `(x, y, width, height)` with x and y RELATIVE TO THE MONITOR. `work` and
    `monitor` are `(left, top, right, bottom)` in desktop coordinates;
    `autohide` names the edges of this monitor whose taskbar hides itself."""
    left, top, right, bottom = work
    if "left" in autohide:
        left += AUTOHIDE_GAP
    if "top" in autohide:
        top += AUTOHIDE_GAP
    if "right" in autohide:
        right -= AUTOHIDE_GAP
    if "bottom" in autohide:
        bottom -= AUTOHIDE_GAP
    return (left - monitor[0], top - monitor[1], right - left, bottom - top)


def _win32() -> dict:
    """The Win32 pieces the hook needs, made once. PRIVATE handles on the
    DLLs: the argument types set here stay here, and pywebview's own calls
    through `ctypes.windll` keep the conventions they were written for."""
    if _W32:
        return _W32
    import ctypes
    from ctypes import wintypes as wt

    class MINMAXINFO(ctypes.Structure):
        _fields_ = [("ptReserved", wt.POINT), ("ptMaxSize", wt.POINT),
                    ("ptMaxPosition", wt.POINT), ("ptMinTrackSize", wt.POINT),
                    ("ptMaxTrackSize", wt.POINT)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                    ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uCallbackMessage", wt.UINT),
                    ("uEdge", wt.UINT), ("rc", wt.RECT), ("lParam", wt.LPARAM)]

    LRESULT = ctypes.c_ssize_t
    SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
                                      ctypes.c_size_t, ctypes.c_size_t)
    user32 = ctypes.WinDLL("user32")
    comctl32 = ctypes.WinDLL("comctl32")
    shell32 = ctypes.WinDLL("shell32")
    comctl32.SetWindowSubclass.argtypes = [wt.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.SetWindowSubclass.restype = wt.BOOL
    comctl32.RemoveWindowSubclass.argtypes = [wt.HWND, SUBCLASSPROC, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.restype = wt.BOOL
    comctl32.DefSubclassProc.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    comctl32.DefSubclassProc.restype = LRESULT
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    user32.MonitorFromWindow.restype = wt.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
    shell32.SHAppBarMessage.argtypes = [wt.DWORD, ctypes.POINTER(APPBARDATA)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t

    def proc(hwnd, msg, wparam, lparam, uid, ref):
        try:
            if msg == WM_NCCALCSIZE and wparam:
                return 0                          # the whole window is page
            if msg == WM_GETMINMAXINFO:
                # WinForms first - it fills in the minimum size - then ours.
                result = comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
                try:
                    _fit_maximized(hwnd, lparam)
                except Exception:
                    pass
                return result
            if msg == WM_NCDESTROY:
                comctl32.RemoveWindowSubclass(hwnd, _W32["proc"], 1)
        except Exception:
            pass
        return comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)

    _W32.update(ctypes=ctypes, user32=user32, comctl32=comctl32, shell32=shell32,
                MINMAXINFO=MINMAXINFO, MONITORINFO=MONITORINFO, APPBARDATA=APPBARDATA,
                proc=SUBCLASSPROC(proc))           # kept here: Windows holds only a pointer
    return _W32


def _autohide_edges(monitor) -> tuple:
    """The edges of `monitor` with a taskbar that hides itself. Asked of the
    shell at most every two seconds per monitor: WM_GETMINMAXINFO arrives on
    every step of a resize, and each question is a message to Explorer."""
    now = _clock()
    seen = _AUTOHIDE.get(monitor)
    if seen and now - seen[0] < 2.0:
        return seen[1]
    w = _win32()
    ctypes = w["ctypes"]
    found = []
    for i, name in enumerate(EDGES):
        abd = w["APPBARDATA"]()
        abd.cbSize = ctypes.sizeof(abd)
        abd.uEdge = i
        abd.rc.left, abd.rc.top, abd.rc.right, abd.rc.bottom = monitor
        if w["shell32"].SHAppBarMessage(ABM_GETAUTOHIDEBAREX, ctypes.byref(abd)):
            found.append(name)
    _AUTOHIDE[monitor] = (now, tuple(found))
    return tuple(found)


def _maximized_for(hwnd):
    """`(monitor left, monitor top, x, y, width, height)` for the monitor the
    window is on - x and y relative to that monitor - or None."""
    w = _win32()
    ctypes = w["ctypes"]
    mon = w["user32"].MonitorFromWindow(hwnd, 2)           # MONITOR_DEFAULTTONEAREST
    mi = w["MONITORINFO"]()
    mi.cbSize = ctypes.sizeof(mi)
    if not mon or not w["user32"].GetMonitorInfoW(mon, ctypes.byref(mi)):
        return None
    r, k = mi.rcMonitor, mi.rcWork
    monitor = (r.left, r.top, r.right, r.bottom)
    return (r.left, r.top) + maximized_rect((k.left, k.top, k.right, k.bottom), monitor,
                                            _autohide_edges(monitor))


def _fit_maximized(hwnd, lparam) -> None:
    got = _maximized_for(hwnd)
    if got is None:
        return
    _, _, x, y, cx, cy = got
    mmi = _win32()["MINMAXINFO"].from_address(lparam)
    mmi.ptMaxPosition.x, mmi.ptMaxPosition.y = x, y
    mmi.ptMaxSize.x, mmi.ptMaxSize.y = cx, cy


def _install_frame_hook(hwnd: int) -> bool:
    """Subclass first, so the frame change below is already answered by the
    hook and no frame is ever drawn; then the styles; then tell Windows the
    frame changed."""
    if hwnd in _HOOKED:
        return True
    w = _win32()
    if not w["comctl32"].SetWindowSubclass(hwnd, w["proc"], 1, 0):
        return False
    _HOOKED.add(hwnd)
    u = w["user32"]
    u.SetWindowLongPtrW(hwnd, GWL_STYLE, u.GetWindowLongPtrW(hwnd, GWL_STYLE) | FRAME_STYLES)
    u.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FRAME_CHANGED)
    # A window that OPENED maximized - window.json remembers that - was
    # maximized before the hook was here to say where maximized ends, so it
    # took the whole monitor, over a taskbar that hides itself. Put it where
    # maximized means now; it stays maximized, and Restore still knows its
    # old size.
    if u.IsZoomed(w["ctypes"].c_void_p(hwnd)):
        got = _maximized_for(hwnd)
        if got is not None:
            mx, my, x, y, cx, cy = got
            u.SetWindowPos(hwnd, None, mx + x, my + y, cx, cy, 0x0004 | 0x0010)   # NOZORDER | NOACTIVATE
    return True


def keep_off_the_taskbar(win) -> None:
    """The frame hook on a frameless window: Windows sizes it and snaps it,
    and maximized it stops at the taskbar (see above). Done on the form's
    own thread, because a window can only be subclassed from the thread that
    made it. Called when the window is shown, and again when it moves in case
    the handle was not ready the first time; after that it is already done."""
    if sys.platform != "win32":
        return
    hwnd = _hwnd_of(win)
    if not hwnd or hwnd in _HOOKED:
        return

    def install():
        try:
            _install_frame_hook(hwnd)
        except Exception:
            pass
    try:
        invoke = getattr(getattr(win, "native", None), "Invoke", None)
        if invoke is not None:
            from System import Action                   # type: ignore
            invoke(Action(install))
        else:
            install()
    except Exception:
        pass


def _hwnd_of(win) -> int:
    try:
        return int(win.native.Handle.ToInt64())
    except Exception:
        return 0


def wait_for_the_editor(host: str, port: int, timeout: float) -> bool:
    """Until something is listening on the editor's port, or `timeout`.

    A launcher from 1.0.4 starts this window BESIDE the editor rather than
    after it, so the window's own start - Python, pywebview, pythonnet - runs
    while the editor is still importing, instead of queueing behind it. lee:
    *"optimaze the app make it faster and moother"*. The page must not be
    loaded before there is a server to load it from, so the window waits here,
    and only when the launcher says it started it early (MANGATCT_WINDOW_WAITS):
    run by hand, or by an older launcher, the editor is already up."""
    import socket
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def say_shown() -> None:
    """Leave the mark a 1.0.4 launcher waits for (MANGATCT_WINDOW_SHOWN): the
    window is on screen, so the launcher's own window can go now rather than
    after its four-second grace. Nothing to do when nobody is waiting."""
    path = os.environ.get("MANGATCT_WINDOW_SHOWN", "")
    if path:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
        except OSError:
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

    waits = os.environ.get("MANGATCT_WINDOW_WAITS", "")
    if waits:
        try:
            wait_for_the_editor(a.host, a.port, float(waits))
        except ValueError:
            pass

    g = _on_screen(load_geometry(), _screens(webview))
    width, height = g.get("width", DEFAULT_SIZE[0]), g.get("height", DEFAULT_SIZE[1])
    frameless = not want_frame(a)
    api = Api()
    api._frameless = frameless
    win = webview.create_window(
        a.title, url_for(a), width=width, height=height,
        x=g.get("x"), y=g.get("y"), maximized=g.get("maximized", False),
        min_size=MIN_SIZE, background_color=BACKGROUND,
        text_select=True, zoomable=True,
        frameless=frameless, easy_drag=False, js_api=api)
    api._win = win

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

    # While the window is being dragged or sized these fire for every step of
    # it, and each `remember` is five reads across into .NET - on the same
    # thread, and under the same lock, as the frame hook answering Windows for
    # that very drag. lee: *"optimaze the app make it faster and moother"*. So
    # it looks at most ten times a second. Nothing is lost by it: the size is
    # only WRITTEN on closing, and `closing` remembers once more first.
    last = {"at": 0.0}

    def remember_soon(*_):
        now = time.monotonic()
        if now - last["at"] >= 0.1:
            last["at"] = now
            remember()

    win.events.resized += remember_soon
    win.events.moved += remember_soon
    win.events.closing += closing

    def shown(*_):
        say_shown()
        dress_the_frame(_hwnd_of(win), frameless)
        if frameless:
            keep_off_the_taskbar(win)
    win.events.shown += shown
    if frameless:
        # Only until the hook is in. `keep_off_the_taskbar` asks the form for
        # its handle before it can see that it has nothing to do, and that was
        # a round trip into .NET on every step of every move for the life of
        # the window.
        win.events.moved += lambda *_: _HOOKED or keep_off_the_taskbar(win)
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
