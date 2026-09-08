"""Open the operating system's own folder chooser.

The editor runs a local server, so the machine showing the browser is the
machine holding the files - a native dialog is both possible and much nicer
than typing a path.

Everything here runs in a subprocess. Tk has to own the main thread on macOS,
a wedged dialog must not take the server with it, and a missing toolkit should
be a shrug rather than a traceback. If nothing works the caller falls back to
a plain text field, which always works.

    python -m mangatl.pickdir [start_dir]      # prints the chosen path
"""
from __future__ import annotations

import os
import subprocess
import sys

TIMEOUT = 180          # a person browsing for a folder, not a machine

# The chapter file. Named here rather than imported from `bundle` so this
# module stays a leaf: it is spawned as a subprocess and must start fast.
PROJECT_EXT = ".tctp"

#: What every dialog this module opens is CALLED. One string, because on
#: Windows the title is the window's name in the taskbar and in Alt-Tab, and
#: three different sentences there are three windows that look like they belong
#: to three different programs.
APP_NAME = "MangaTCT Beta"


def _run(cmd: list[str], **kw) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=TIMEOUT, **kw)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or "").strip()


def _via_tk(start: str, mode: str = "dir") -> str:
    """Tk ships with Python on Windows and macOS."""
    return _run([sys.executable, "-m", "mangatl.pickdir", start or "", mode],
                env={**os.environ, "MANGATL_TK": "1"})


def _via_osascript(start: str, mode: str = "dir") -> str:
    what = ("file with prompt \"Open which project?\"" if mode == "open"
            else "file name with prompt \"Save the project as\""
            if mode == "save" else "folder with prompt \"Save the pages where?\"")
    return _run(["osascript", "-e", f"POSIX path of (choose {what})"])


def _via_zenity(start: str, mode: str = "dir") -> str:
    cmd = ["zenity", "--file-selection"]
    if mode == "dir":
        cmd += ["--directory", "--title=Save the pages where?"]
    elif mode == "save":
        cmd += ["--save", "--confirm-overwrite",
                "--title=Save the project as", f"--file-filter=*{PROJECT_EXT}"]
    else:
        cmd += ["--title=Open which project?", f"--file-filter=*{PROJECT_EXT}"]
    if start:
        tail = os.sep if mode == "dir" else ""
        cmd.append(f"--filename={start.rstrip(os.sep)}{tail}")
    return _run(cmd)


def _via_kdialog(start: str, mode: str = "dir") -> str:
    where = start or os.path.expanduser("~")
    if mode == "save":
        return _run(["kdialog", "--getsavefilename", where, f"*{PROJECT_EXT}"])
    if mode == "open":
        return _run(["kdialog", "--getopenfilename", where, f"*{PROJECT_EXT}"])
    return _run(["kdialog", "--getexistingdirectory", where])


def available() -> bool:
    """Can we show a native dialog at all?"""
    import shutil
    if sys.platform in ("win32", "darwin"):
        return True
    return any(shutil.which(x) for x in ("zenity", "kdialog"))


def _order():
    if sys.platform == "win32":
        return (_via_tk,)
    if sys.platform == "darwin":
        return (_via_osascript, _via_tk)
    return (_via_zenity, _via_kdialog, _via_tk)


def pick_directory(start: str = "") -> str:
    """Return the chosen folder, or "" if the person cancelled or we cannot ask."""
    for fn in _order():
        path = fn(start, "dir")
        if path and os.path.isdir(path):
            return path
    return ""


def pick_project(start: str = "", save: bool = False) -> str:
    """A `.tctp` to open, or a name to save one under. "" if cancelled.

    Saving asks for a name that does NOT have to exist yet, so unlike
    `pick_directory` there is nothing to check afterwards but that we were
    given something. The extension is added if the person did not type it -
    a project file called `chapter 3` is a project file nothing will open.
    """
    for fn in _order():
        path = fn(start, "save" if save else "open")
        if not path:
            continue
        if save:
            if not path.lower().endswith(PROJECT_EXT):
                path += PROJECT_EXT
            return path
        if os.path.isfile(path):
            return path
    return ""


# The mark, drawn for this by tools/make_icon.py. Two files because Windows
# wants an `.ico` and everywhere else wants the PNG.
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _wear_our_own_icon(root) -> None:
    """Put the MangaTCT mark on the dialog.

    Tk stamps its own blue feather on any window that does not set one, so
    "Save the project as" opened wearing somebody else's logo - which lee
    noticed and photographed. It is only the title bar and the taskbar, and
    it is the only place in the app where the app is not the thing on screen.

    Never allowed to matter: a missing icon file, an old Tk that cannot read a
    PNG, a platform that ignores one of the two calls. The dialog is the
    point; the picture on it is not.
    """
    ico = os.path.join(_ICON_DIR, "icon.ico")
    png = os.path.join(_ICON_DIR, "icon.png")
    if sys.platform == "win32" and os.path.isfile(ico):
        try:
            root.iconbitmap(default=ico)
            return
        except Exception:
            pass
    if os.path.isfile(png):
        try:
            import tkinter
            # Held on the root: Tk keeps no reference of its own and a
            # PhotoImage that is garbage-collected takes the icon with it.
            root._mangatct_icon = tkinter.PhotoImage(file=png)
            root.iconphoto(True, root._mangatct_icon)
        except Exception:
            pass


def _sharp_on_a_scaled_screen() -> None:
    """Tell Windows this process draws its own pixels.

    A process that has not said so is DPI-UNAWARE, and on any display running
    above 100% - which is every laptop screen sold for years, and lee's - the
    system draws it at 96 dpi and then STRETCHES the finished bitmap up to
    size. Nothing crashes and nothing is out of place; the whole window is
    simply soft. Every letter, the folder icons, the thumbnails, the buttons.

    lee, with a screenshot of the save dialog beside his editor: *"why are
    these so low quality"*. It is the one window in this app the operating
    system draws rather than the browser, so it was the one window that
    looked blurred while everything around it was sharp.

    `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` is the modern call
    and the one that also copes with a second monitor at a different scale;
    the two below it are the fallbacks for Windows 8.1 and 8. It has to run
    BEFORE any window exists, which is why it is the first thing `_tk_main`
    does - before tkinter is even imported.

    Every call is wrapped: a machine that answers none of them gets the
    dialog it has always had, which is a soft dialog and not a missing one.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
    except Exception:
        return
    # -4 is PER_MONITOR_AWARE_V2 - a context HANDLE, not an enum, so it goes
    # in as a pointer-sized value.
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:                                   # Windows 8.1: 2 = per-monitor
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:                                   # Windows 8 and older: system-wide
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _tk_own_scaling(root) -> None:
    """...and Tk's OWN idea of how big a point is.

    Separate from the system's, and left at 72 dpi whatever the screen does.
    With the process now DPI-aware the window is no longer stretched, so
    without this the dialog would come back sharp and half the size it should
    be - a fix that trades one complaint for another. `tk scaling` is the
    screen's real dpi over 72. The file list and the title bar are the
    operating system's own controls and follow the system setting by
    themselves.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if dpi and dpi != 96:
            root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


def _tk_main() -> int:
    """Child process: show the Tk dialog and print the result."""
    # BEFORE tkinter is imported: a process's DPI awareness is fixed the
    # moment it draws anything, and Tk draws as soon as it is asked for a
    # root window.
    _sharp_on_a_scaled_screen()
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:
        return 1
    start = sys.argv[1] if len(sys.argv) > 1 else ""
    mode = sys.argv[2] if len(sys.argv) > 2 else "dir"
    root = tkinter.Tk()
    _tk_own_scaling(root)
    root.withdraw()
    _wear_our_own_icon(root)
    root.attributes("-topmost", True)      # otherwise it opens behind the browser
    kinds = [("MangaTCT project", f"*{PROJECT_EXT}"), ("All files", "*.*")]
    where = start or os.path.expanduser("~")
    # THE TITLE IS THE APP'S NAME, on all three. lee, with a crop of the folder
    # picker's title bar reading "Save the translated pages where?": *"this
    # should just say manga tct"*.
    #
    # On Windows this string is the WINDOW title - what the taskbar and Alt-Tab
    # show - and not a prompt inside the dialog. A window called "Save the
    # translated pages where?" is a window nobody can find again; the dialog
    # itself already says what it wants, because the operating system draws
    # "Select Folder" and a file-name box on it.
    if mode == "save":
        path = filedialog.asksaveasfilename(
            title=APP_NAME, initialdir=where,
            defaultextension=PROJECT_EXT, filetypes=kinds)
    elif mode == "open":
        path = filedialog.askopenfilename(
            title=APP_NAME, initialdir=where, filetypes=kinds)
    else:
        path = filedialog.askdirectory(title=APP_NAME, initialdir=where)
    root.destroy()
    if path:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(_tk_main())
