"""Updates, from inside the app: Settings > Updates.

lee: *"when i download 1.2 it dont update 1.2 it reinstalls everything, also
add an updates tab in the settings that downloads the update automatically"*.

Two things were true at once. The launcher already fetched every new app
version by itself - at start and every six hours - and installed it on the
next start; nothing in the app said so except a dot on the version pill. And
the launcher's own exe (the little program, plus the Python runtime) could
only change through the full installer, which copies the whole runtime
again and, in 1.0.2, could not close the running app first.

So this module gives the app a place where all of that is visible and
pressable, and does it with the launcher's own code rather than a second
copy of it: the app zip carries `launcher/mangatct_launcher.py` as
`mangatl.launcher.mangatct_launcher`, so `check_for_update` here IS the
launcher's - same manifest, same checksum rule, same `app\\<version>\\`
folder beside the running one, same `update.json` the pill reads.

What the section can do:

* **Check now** - fetch the manifest and, when automatic downloads are on,
  the app zip, with a percentage while it comes;
* **Download updates automatically** - a switch kept in the launcher's
  `state.json` (`auto_update`), read by the launcher at every check. Off
  means "tell me, and I will press Download";
* **Restart now** - once a version is unpacked, the editor ends with the
  exit code the launcher (1.0.3+) takes as "start me again", and the new
  version is up in the same window a few seconds later. An older launcher
  ends the session instead, and the button says so;
* **Get the new setup** - when the manifest's installer carries a newer
  launcher than the one running, the installer is downloaded (checksum
  checked, to the temp folder, so it carries no mark-of-the-web and
  SmartScreen has nothing to say) and run silently with `/relaunch=1`; the
  installer stops what is running, puts the new launcher and runtime in
  place, and starts MangaTCT again.

A checkout run by hand (no launcher, no `MANGATL_UPDATE_FILE`) has none of
this: `state()` says `launched: False` and the section says updates come
from git.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time

from . import version as V

try:                                    # the copy that rides in the app zip
    from .launcher import mangatct_launcher as L
except Exception:                       # pragma: no cover - a zip without it
    L = None

#: The first launcher that starts the editor again on `EDITOR_RESTART`.
RESTARTS_FROM = (1, 0, 3)
#: How long a fetched manifest is trusted before Check now asks again.
MANIFEST_FRESH = 300.0

_LOCK = threading.Lock()
_BUSY = {"what": ""}            # "check" | "install" | "" - one job at a time
_PROGRESS = {"percent": None}   # of the job above, when it downloads
_MANIFEST = {"at": 0.0, "data": None}
_LAST = {"error": "", "checked": 0.0}
_EXIT = {"code": None}          # set when the process is about to end


# --------------------------------------------------------------- where

def home() -> str | None:
    """The launcher's folder (`%LOCALAPPDATA%\\MangaTCT`), known from the
    file the launcher told us to read, or None when no launcher started
    this process."""
    fp = (os.environ.get("MANGATL_UPDATE_FILE") or "").strip()
    return os.path.dirname(fp) if fp else None


def paths() -> dict | None:
    h = home()
    if not h or L is None:
        return None
    return L.paths(h)


def launcher_version() -> str:
    return (os.environ.get("MANGATL_LAUNCHER") or "").strip()


def can_restart() -> bool:
    """Whether the launcher that started us knows `EDITOR_RESTART`."""
    v = launcher_version()
    return bool(v) and L is not None and L.parse_version(v) >= RESTARTS_FROM


def manifest_url() -> str:
    return L.MANIFEST_URL if L is not None else ""


# ------------------------------------------------------------- reading

def _manifest(fresh: bool = False) -> dict | None:
    if not fresh and _MANIFEST["data"] and time.time() - _MANIFEST["at"] < MANIFEST_FRESH:
        return _MANIFEST["data"]
    m = L.fetch_manifest(manifest_url()) if L is not None else None
    if m is not None:
        _MANIFEST.update(at=time.time(), data=m)
    return m


def _installer_offer(m: dict | None, p: dict) -> dict | None:
    """The installer, when it carries a newer launcher than the one running
    (or the running one is below what the app needs). None otherwise."""
    if not m:
        return None
    inst = m.get("installer") or {}
    shipped = str((m.get("launcher") or {}).get("version") or "")
    mine = launcher_version()
    if not inst.get("url") or not inst.get("sha256") or not shipped or not mine:
        return None
    if L.parse_version(shipped) <= L.parse_version(mine):
        return None
    minimum = str(m.get("minimum_launcher") or "0.0.0")
    return {"version": str(inst.get("version") or shipped),
            "launcher": shipped,
            "size": int(inst.get("size") or 0),
            "required": L.parse_version(mine) < L.parse_version(minimum)}


def state(fresh: bool = False) -> dict:
    """Everything the Updates section shows. Never raises, never blocks on
    the network unless `fresh` (Check now does that from a thread)."""
    out = {"launched": False, "version": V.__version__, "channel": V.CHANNEL,
           "launcher": launcher_version()}
    p = paths()
    if p is None:
        return out
    out["launched"] = True
    out["auto"] = L.auto_update(p)
    out["can_restart"] = can_restart()
    out["busy"] = _BUSY["what"]
    out["percent"] = _PROGRESS["percent"] if _BUSY["what"] else None
    out["problem"] = _LAST["error"]     # not "error": the client toasts that
    st = L.read_state(p)
    out["last_check"] = float(st.get("last_check") or _LAST["checked"] or 0)
    out["channel_version"] = str(st.get("channel_version") or "")
    u = L.read_json(p["update"], {}) or {}
    if isinstance(u, dict) and u.get("available"):
        out["update"] = {"available": str(u["available"]),
                         "state": str(u.get("state") or "ready"),
                         "notes": str(u.get("notes") or ""),
                         "percent": u.get("percent")}
    have = L.installed_versions(p)
    out["installed"] = have
    m = _manifest(fresh) if (fresh or _MANIFEST["data"]) else None
    inst = _installer_offer(m, p)
    if inst:
        out["installer"] = inst
    return out


# --------------------------------------------------------------- doing

def _begin(what: str) -> bool:
    with _LOCK:
        if _BUSY["what"]:
            return False
        _BUSY["what"] = what
        _PROGRESS["percent"] = None
        _LAST["error"] = ""
        return True


def _end() -> None:
    with _LOCK:
        _BUSY["what"] = ""
        _PROGRESS["percent"] = None


def _progress_to(p: dict, ver: str, notes: str):
    def progress(done, total):
        pct = int(100 * done // total) if total else 0
        _PROGRESS["percent"] = pct
        try:
            L.say_update(p, ver, "downloading", notes, percent=pct)
        except Exception:
            pass
    return progress


def check(force: bool = False, wait: bool = False) -> dict:
    """Ask the channel, and fetch what it has when automatic downloads are
    on or `force` (the Download button). Runs in a thread; `state()` shows
    it going. Returns the state as it stands when this returns."""
    p = paths()
    if p is None:
        return state()
    if not _begin("check"):
        return state()

    def work():
        try:
            m = _manifest(fresh=True)
            if m is None:
                _LAST["error"] = "The update server did not answer. Check the connection and try again."
                return
            app = m.get("app") or {}
            ver = str(app.get("version") or "")
            notes = str(app.get("notes") or "")
            L.check_for_update(p, m, progress=_progress_to(p, ver, notes), force=force)
            _LAST["checked"] = time.time()
        except Exception as e:      # a failed check is a line, not a crash
            _LAST["error"] = "The check failed: %s" % e
        finally:
            _end()

    t = threading.Thread(target=work, daemon=True)
    t.start()
    if wait:
        t.join()
    return state()


def set_auto(on: bool) -> dict:
    p = paths()
    if p is not None:
        L.write_state(p, auto_update=bool(on))
    return state()


def _leave(code: int, after: float = 0.4) -> None:
    """End this process with `code` once the reply has gone out. `os._exit`
    because the server's threads would otherwise hold the process open,
    and there is nothing of the person's in memory that is not on disk."""
    _EXIT["code"] = code

    def bye():
        time.sleep(after)
        os._exit(code)
    threading.Thread(target=bye, daemon=True).start()


def restart() -> dict:
    """Start again, into the version that is waiting. With a launcher that
    knows the code this is a restart; with an older one it is a quit, and
    the next start from the icon runs the new version."""
    p = paths()
    if p is None:
        return {"ok": False, "error": "Not started by the launcher."}
    code = L.EDITOR_RESTART if can_restart() else 0
    _leave(code)
    return {"ok": True, "restarting": code == L.EDITOR_RESTART}


def _setup_args(exe: str) -> list[str]:
    """Inno Setup, silently: no wizard, no reboot, stop what is running
    (the installer's own PrepareToInstall does the stopping), and start
    MangaTCT again when done (`/relaunch=1` is ours, read in the .iss)."""
    return [exe, "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS", "/relaunch=1"]


def install_setup(wait: bool = False) -> dict:
    """Fetch this release's installer and hand over to it. The installer
    stops the app, replaces launcher and runtime, and starts MangaTCT."""
    p = paths()
    if p is None:
        return {"ok": False, "error": "Not started by the launcher."}
    m = _manifest()
    offer = _installer_offer(m, p)
    inst = (m or {}).get("installer") or {}
    if not offer or not inst.get("url"):
        return {"ok": False, "error": "There is no newer setup to get."}
    if not _begin("install"):
        return {"ok": False, "error": "Something is already downloading."}

    def work():
        try:
            dest = os.path.join(tempfile.gettempdir(),
                                "MangaTCT-Setup-%s.exe" % offer["version"])

            def progress(done, total):
                _PROGRESS["percent"] = int(100 * done // total) if total else 0
            ok = L.download(inst["url"], dest, str(inst["sha256"]),
                            inst.get("size"), progress)
            if not ok:
                _LAST["error"] = "The setup could not be downloaded, or did not match its checksum. Nothing was changed."
                return
            if sys.platform == "win32":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                subprocess.Popen(_setup_args(dest), close_fds=True, creationflags=flags)
                _leave(0, after=1.0)
            else:                       # nowhere to run it; the file is proof enough
                _LAST["error"] = "Setup downloaded to %s; it runs on Windows." % dest
        except Exception as e:
            _LAST["error"] = "The setup could not be started: %s" % e
        finally:
            _end()

    t = threading.Thread(target=work, daemon=True)
    t.start()
    if wait:
        t.join()
    return {"ok": True, **state()}
