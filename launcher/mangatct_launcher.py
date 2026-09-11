"""MangaTCT for Windows - the small program that starts the big one.

lee: *"lets go with teh doenload option, i still want to be able to send out
update and keep suporting teh app"*.

This is `MangaTCT.exe`. It is not the editor; it is the thing that keeps the
editor current and starts it. The editor is Python and stays Python - what
the installer puts on the disk is a Python runtime with every package the app
needs already installed, the model weights, and one version of the app's
source. This program's job, every time somebody double-clicks the icon:

    1. look for a newer version, quietly, and fetch it if there is one;
    2. pick the newest version that is complete, and if its requirements
       changed, bring the runtime up to them;
    3. start the editor on a free port, wait until it answers, and show it -
       in a window of its own (`mangatl.window`, WebView2), or in the
       browser if that window cannot open or `--browser` was asked for;
    4. and if the editor ends asking to be started again (exit code
       `EDITOR_RESTART` - Settings > Updates > Restart now), do all of this
       once more, which is how a fetched version is switched to without the
       person finding the icon.

The app's Settings page has an Updates section that talks to the same code:
the app zip carries a copy of this file (`mangatl/launcher/`), so *Check
now* and *Download* there are `check_for_update` below, run by the editor,
writing the same `update.json` and `state.json`. `state.json` also holds
`auto_update`: when a person turns automatic downloads off there, the
checks here still happen but only SAY that a version exists ("offered");
the download waits for the button.

WHY A LAUNCHER AND NOT AN INSTALLER PER VERSION. An update to the app is a
zip of Python files a few megabytes big. Making people download a gigabyte
installer for a bug fix is how people stop updating, and a person on an old
version is a person whose bug report cannot be acted on. So the big thing
(runtime + models) is installed once and the small thing (the app) is
swapped by this program, with the previous version kept on disk so a bad
release is one restart away from undone.

WHAT IT REFUSES TO DO. It never switches versions while the editor is
running - a chapter open in the browser is a chapter somebody is working on.
The check at start happens BEFORE the editor starts, so a version fetched
then is used then; the check that repeats every few hours while the editor
runs writes the new version beside the current one, marked complete only
after its checksum matched, tells the header pill, and leaves the switch to
the next start. It never deletes the version that is running. And it never
talks to anything but the release channel, over HTTPS, and takes nothing
from it that does not match the checksum the manifest promised.

Everything lives under one folder, `%LOCALAPPDATA%\\MangaTCT` (`HOME` here):

    MangaTCT.exe            this program, put there by the installer
    runtime\\python\\         Python + every package, built by the release job
    app\\1.0.0\\mangatl\\...   one folder per app version; `.complete` inside
                            a folder means its checksum matched
    models\\                 the weights; MANGATL_WEIGHTS points here
    logs\\                   launcher.log and one editor log per day
    state.json              what is installed and when we last looked
    update.json             what the editor's header pill reads

The person's own things - fonts they uploaded, preferences, API keys - are
NOT here. They are in `~/.mangatl`, where the editor has always kept them,
so uninstalling this folder loses nothing of theirs.

Standard library only, on purpose: this file is frozen into an exe and every
import is weight, and a launcher that needs the packages it is supposed to
be installing cannot recover from a broken runtime.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

#: Bumped when THIS file changes in a way an installed copy should hear about;
#: the manifest carries the launcher version each release shipped, and the
#: app's Updates section offers the installer when the one running is older.
#: (1.0.2's launcher - the own window, the mark - shipped still saying 1.0.0;
#: from here on the number moves with the file.)
LAUNCHER_VERSION = "1.0.3"

#: The editor's exit code that means "start me again": Settings > Updates >
#: Restart now, after a version was fetched. Anything else ends the session.
EDITOR_RESTART = 75

#: Where the manifest is: a plain file on the project's own repository, main
#: branch. No API, no token, no rate limit worth mentioning, and GitHub's CDN
#: caches it about five minutes, which is exactly right for "is there a new
#: version". lee: *"we alredy have a github repo, we dont need a newone"*.
#:
#: THE REPOSITORY HAS TO BE PUBLIC for this to answer, and for the Release
#: assets it points at to download. That is not an extra ask: the app is
#: GPL-3.0 and every copy handed out already comes with the offer of its
#: source. See `docs/releasing.md`.
#:
#: Overridable, which is how a release is rehearsed on one machine before the
#: channel moves.
MANIFEST_URL = os.environ.get(
    "MANGATCT_MANIFEST",
    "https://raw.githubusercontent.com/Lerbernard/MangaTCT/main/manifest.json")

#: How long a start may wait on the network before giving up and starting
#: what is already installed. Nobody should wait on GitHub to open a chapter.
CHECK_TIMEOUT = 4.0

#: Versions kept on disk besides the current one. One is enough to undo a
#: bad release; more is disk spent on nothing.
KEEP_OLD = 1

#: How often a running editor's launcher looks at the channel again. Long,
#: because a person who leaves the app open for a week should still hear
#: about a fix, and short enough for nothing else.
RECHECK_EVERY = 6 * 3600

#: How long the editor is given to answer after it is started. The first
#: start of a session imports torch and loads the models; on a slow disk
#: that is over a minute.
EDITOR_WAIT = 180.0

COMPLETE = ".complete"


# ---------------------------------------------------------------- folders

def home() -> str:
    """`%LOCALAPPDATA%\\MangaTCT`, or wherever `MANGATCT_HOME` points."""
    env = os.environ.get("MANGATCT_HOME")
    if env:
        return env
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "MangaTCT")


def paths(root: str | None = None) -> dict:
    r = root or home()
    return {
        "root": r,
        "runtime": os.path.join(r, "runtime"),
        "python": os.path.join(r, "runtime", "python",
                               "python.exe" if os.name == "nt" else "bin/python3"),
        "app": os.path.join(r, "app"),
        "models": os.path.join(r, "models"),
        "logs": os.path.join(r, "logs"),
        "state": os.path.join(r, "state.json"),
        "update": os.path.join(r, "update.json"),
    }


def ensure_dirs(p: dict) -> None:
    for k in ("root", "app", "models", "logs"):
        os.makedirs(p[k], exist_ok=True)


# ------------------------------------------------------------------ logging

_LOG_LOCK = threading.Lock()
_LOG_FILE: str | None = None


def log(msg: str) -> None:
    line = "%s  %s" % (_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    with _LOG_LOCK:
        try:
            if _LOG_FILE:
                with open(_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            pass
    if os.environ.get("MANGATCT_VERBOSE"):
        print(line, file=sys.stderr)


def start_log(p: dict) -> None:
    global _LOG_FILE
    _LOG_FILE = os.path.join(p["logs"], "launcher.log")
    try:
        if os.path.getsize(_LOG_FILE) > 2_000_000:
            os.replace(_LOG_FILE, _LOG_FILE + ".1")
    except OSError:
        pass


# -------------------------------------------------------------- versions

def parse_version(v: str) -> tuple:
    """Same rule as `mangatl/version.py`, copied rather than imported because
    this file must run before any app version is on the disk."""
    v = (v or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    try:
        parts = tuple(int(x) for x in v.split("."))
    except ValueError:
        return (-1,)
    return parts + (0,) * (3 - len(parts)) if len(parts) < 3 else parts


def is_version(name: str) -> bool:
    return parse_version(name) != (-1,) and name.count(".") == 2 \
        and not name.endswith((".tmp", ".part"))


def installed_versions(p: dict) -> list[str]:
    """Every app version on disk whose checksum matched, newest first."""
    if not os.path.isdir(p["app"]):
        return []
    out = [d for d in os.listdir(p["app"])
           if is_version(d)
           and os.path.isfile(os.path.join(p["app"], d, COMPLETE))
           and os.path.isdir(os.path.join(p["app"], d, "mangatl"))]
    return sorted(out, key=parse_version, reverse=True)


def current_version(p: dict) -> str | None:
    got = installed_versions(p)
    return got[0] if got else None


def app_dir(p: dict, version: str) -> str:
    return os.path.join(p["app"], version)


# ------------------------------------------------------------------ state

def read_json(fp: str, default):
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(fp: str, obj) -> None:
    """Whole file or nothing: written beside and renamed over, so a reader -
    the editor reads `update.json` while we write it - never sees half."""
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, fp)


def read_state(p: dict) -> dict:
    return read_json(p["state"], {}) or {}


def write_state(p: dict, **changes) -> dict:
    st = read_state(p)
    st.update(changes)
    write_json(p["state"], st)
    return st


def say_update(p: dict, available: str | None, state: str = "ready",
               notes: str = "", percent: int | None = None) -> None:
    """The one line the editor's header pill and Updates section read.
    `None` clears it. `state` is one of:

        offered      the channel has it; automatic downloads are off
        downloading  on its way (`percent` when the editor is the one fetching)
        ready        unpacked beside the running version; next start runs it
    """
    if not available:
        try:
            os.remove(p["update"])
        except OSError:
            pass
        return
    d = {"available": available, "state": state, "notes": notes}
    if percent is not None:
        d["percent"] = int(percent)
    write_json(p["update"], d)


def auto_update(p: dict) -> bool:
    """Whether a newer version is fetched without being asked. On unless the
    person turned it off in Settings > Updates."""
    return bool(read_state(p).get("auto_update", True))


# --------------------------------------------------------------- network

def fetch_manifest(url: str = MANIFEST_URL, timeout: float = CHECK_TIMEOUT) -> dict | None:
    """The release channel's word, or None when it cannot be had in time.
    None is not an error: it means "start what you have"."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "MangaTCT-launcher/" + LAUNCHER_VERSION,
        "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d if isinstance(d, dict) else None
    except (urllib.error.URLError, OSError, ValueError, socket.timeout) as e:
        log("manifest: not reachable (%s)" % e)
        return None


def sha256_of(fp: str) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: str, sha256: str, size: int | None = None,
             progress=None, timeout: float = 30.0) -> bool:
    """Fetch `url` to `dest`, resumable, and keep it only if its sha256 is
    the one promised. Returns True when `dest` is good.

    Resumable because the runtime is hundreds of megabytes and a laptop lid
    closes: a `.part` that is already there is continued with a Range
    request, and thrown away if the server will not honor it.
    """
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if size and have > size:
        have = 0
    headers = {"User-Agent": "MangaTCT-launcher/" + LAUNCHER_VERSION}
    if have:
        headers["Range"] = "bytes=%d-" % have
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resumed = r.status == 206
            total = size or (have if resumed else 0) + int(
                r.headers.get("Content-Length") or 0)
            mode = "ab" if (have and resumed) else "wb"
            if not resumed:
                have = 0
            with open(part, mode) as f:
                done = have
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except (urllib.error.URLError, OSError, socket.timeout) as e:
        log("download %s: %s" % (os.path.basename(dest), e))
        return False
    got = sha256_of(part)
    if sha256 and got.lower() != sha256.lower():
        log("download %s: checksum %s, wanted %s - discarded"
            % (os.path.basename(dest), got[:12], (sha256 or "?")[:12]))
        try:
            os.remove(part)
        except OSError:
            pass
        return False
    os.replace(part, dest)
    return True


# ----------------------------------------------------------- the app zip

def install_app_zip(p: dict, zip_path: str, version: str) -> bool:
    """Unpack a verified app zip into `app/<version>` and mark it complete.

    The zip holds a top-level `mangatl/` package (the source) and beside it
    `requirements.txt`, which is what the runtime is checked against.
    Unpacked into `<version>.tmp` and renamed in one move, so a crash
    halfway leaves a `.tmp` that is ignored and cleaned, never a version
    that is half there and looks whole.
    """
    tmp = app_dir(p, version) + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if not any(n.startswith("mangatl/") for n in names):
                log("app zip %s has no mangatl/ in it" % version)
                return False
            for n in names:
                # zip-slip guard: nothing may land outside tmp
                target = os.path.realpath(os.path.join(tmp, n))
                if not target.startswith(os.path.realpath(tmp) + os.sep) \
                        and target != os.path.realpath(tmp):
                    log("app zip %s: refused path %s" % (version, n))
                    return False
            z.extractall(tmp)
    except (zipfile.BadZipFile, OSError) as e:
        log("app zip %s: %s" % (version, e))
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    final = app_dir(p, version)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    with open(os.path.join(final, COMPLETE), "w") as f:
        f.write(_dt.datetime.now().isoformat())
    return True


def requirements_hash(version_dir: str) -> str:
    fp = os.path.join(version_dir, "requirements.txt")
    return sha256_of(fp) if os.path.isfile(fp) else ""


def prune_old(p: dict, running: str) -> None:
    """Keep the running version, the newest KEEP_OLD besides it, and drop the
    rest - plus any `.tmp`/`.part` a crash left behind."""
    if not os.path.isdir(p["app"]):
        return
    keep = set([running] + [v for v in installed_versions(p) if v != running][:KEEP_OLD])
    for d in os.listdir(p["app"]):
        full = os.path.join(p["app"], d)
        if d in keep:
            continue
        if d.endswith(".tmp") or (is_version(d) and d not in keep):
            log("pruning %s" % d)
            shutil.rmtree(full, ignore_errors=True)
        elif d.endswith(".part"):
            try:
                os.remove(full)
            except OSError:
                pass


# ------------------------------------------------------------- the check

def check_for_update(p: dict, manifest: dict | None, progress=None,
                     force: bool = False) -> str | None:
    """If the channel has a newer app than anything on disk, fetch it and
    unpack it beside the current version. Returns the version fetched, or
    None. Never touches the version that is running.

    With automatic downloads off (`auto_update`), a newer version is only
    written down as "offered" - unless `force`, which is the Download button
    in Settings > Updates."""
    if not manifest:
        return None
    app = manifest.get("app") or {}
    ver = str(app.get("version") or "")
    if not ver or not is_version(ver):
        return None
    have = installed_versions(p)
    if have and parse_version(ver) <= parse_version(have[0]):
        say_update(p, None)
        write_state(p, last_check=time.time(), channel_version=ver)
        return None
    if ver in have:
        return None
    url, sha, size = app.get("url"), app.get("sha256"), app.get("size")
    if not url or not sha:
        log("manifest names %s but no url/sha256" % ver)
        return None
    if not force and not auto_update(p):
        log("%s is on the channel; automatic downloads are off" % ver)
        say_update(p, ver, "offered", app.get("notes") or "")
        write_state(p, last_check=time.time(), channel_version=ver)
        return None
    say_update(p, ver, "downloading", app.get("notes") or "")
    dest = os.path.join(p["app"], "mangatct-app-%s.zip" % ver)
    ok = download(url, dest, sha, size, progress)
    if ok:
        ok = install_app_zip(p, dest, ver)
    try:
        os.remove(dest)
    except OSError:
        pass
    if not ok:
        say_update(p, None)
        return None
    log("fetched %s" % ver)
    say_update(p, ver, "ready", app.get("notes") or "")
    write_state(p, last_check=time.time(), channel_version=ver)
    return ver


# ------------------------------------------------------------ the models

def models_wanted(version_dir: str) -> list[dict]:
    """The weights this version of the app expects, from its own
    `models.json` (a copy of `tools/models.json` at release time)."""
    d = read_json(os.path.join(version_dir, "models.json"), {}) or {}
    return [m for m in d.get("models", []) if m.get("name") and m.get("url")]


def model_present(p: dict, m: dict) -> bool:
    fp = os.path.join(p["models"], m["name"])
    if not os.path.isfile(fp):
        return False
    size = m.get("size")
    return not size or os.path.getsize(fp) == int(size)


def fetch_model(p: dict, m: dict, progress=None) -> bool:
    """One weight file, from its publisher, checked against the sum every
    measurement was made on. Some arrive inside a zip (`inside` names the
    member); the sum is always of the file that lands in `models/`."""
    dest = os.path.join(p["models"], m["name"])
    if not m.get("inside"):
        return download(m["url"], dest, m.get("sha256"), m.get("size"), progress)
    zpath = dest + ".zip"
    if not download(m["url"], zpath, None, None, progress):
        return False
    try:
        with zipfile.ZipFile(zpath) as z:
            with z.open(m["inside"]) as src, open(dest + ".part", "wb") as out:
                shutil.copyfileobj(src, out)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        log("model %s: %s" % (m["name"], e))
        return False
    finally:
        try:
            os.remove(zpath)
        except OSError:
            pass
    got = sha256_of(dest + ".part")
    if m.get("sha256") and got.lower() != m["sha256"].lower():
        log("model %s: checksum %s, wanted %s - discarded" % (m["name"], got[:12], m["sha256"][:12]))
        os.remove(dest + ".part")
        return False
    os.replace(dest + ".part", dest)
    return True


def ensure_models(p: dict, version_dir: str, progress=None) -> str:
    """Fetch what is missing. Returns "" or the reason a REQUIRED one could
    not be had; a recommended one that fails is logged and the editor greys
    the route that wanted it, which is what it does for a missing file
    anyway."""
    wanted = models_wanted(version_dir)
    missing = [m for m in wanted if not model_present(p, m)]
    for n, m in enumerate(missing, 1):
        label = "Downloading %s (%d of %d)…" % (m.get("what") or m["name"], n, len(missing))
        if progress:
            progress(label)
        ok = fetch_model(p, m, progress=(lambda d, t, _l=label: progress(
            "%s %d%%" % (_l, 100 * d // t if t else 0))) if progress else None)
        if ok:
            log("model %s fetched" % m["name"])
            continue
        if m.get("tier") == "required":
            return ("%s could not be downloaded from %s. MangaTCT cannot find "
                    "text without it. Check the connection and start again."
                    % (m["name"], m["url"].split("/")[2]))
        log("model %s not fetched; its route stays off until it is" % m["name"])
    return ""


# ----------------------------------------------------------- the runtime

def runtime_ok(p: dict) -> bool:
    return os.path.isfile(p["python"])


def pip_sync(p: dict, version_dir: str, progress=None) -> bool:
    """Bring the runtime's packages up to this version's requirements.

    Only runs when the requirements file's hash is not the one the runtime
    was last synced to - a bug-fix release with the same requirements starts
    with no pip at all. `--no-warn-script-location` and friends keep pip
    quiet; its output goes to the launcher log where a support message can
    find it.
    """
    want = requirements_hash(version_dir)
    st = read_state(p)
    if not want or st.get("requirements_sha256") == want:
        return True
    req = os.path.join(version_dir, "requirements.txt")
    cmd = [p["python"], "-m", "pip", "install", "--no-warn-script-location",
           "--disable-pip-version-check", "-r", req]
    extra = os.path.join(version_dir, "requirements-index.txt")
    if os.path.isfile(extra):
        # e.g. `--extra-index-url https://download.pytorch.org/whl/cpu`
        with open(extra, encoding="utf-8") as f:
            cmd += [tok for tok in f.read().split() if tok]
    log("pip: " + " ".join(cmd))
    if progress:
        progress("Updating the app's packages…")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=_no_window(), timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as e:
        log("pip failed to run: %s" % e)
        return False
    log("pip exit %d\n%s" % (r.returncode, (r.stdout or "")[-4000:] + (r.stderr or "")[-4000:]))
    if r.returncode != 0:
        return False
    write_state(p, requirements_sha256=want)
    return True


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# ------------------------------------------------------------- the editor

def free_port(prefer: int = 8765) -> int:
    for port in [prefer] + list(range(8766, 8800)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def editor_env(p: dict) -> dict:
    env = dict(os.environ)
    env["MANGATL_WEIGHTS"] = p["models"]
    env["MANGATL_UPDATE_FILE"] = p["update"]
    env["MANGATL_LAUNCHER"] = LAUNCHER_VERSION
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Every core for the detectors. ultralytics sets this to 1 at import when
    # nobody has, and PyTorch then runs Find text on one core of twenty. The
    # app sets it too (`mangatl/cores.py`); this is the same line from the
    # outside, for an app version from before it did.
    env.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 1))
    return env


def output_dir() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"),
                        "MangaTCT")


def start_editor(p: dict, version: str, port: int) -> subprocess.Popen:
    vdir = app_dir(p, version)
    logfp = os.path.join(p["logs"], "editor-%s.log" % _dt.date.today().isoformat())
    out = open(logfp, "a", encoding="utf-8", errors="replace")
    out.write("\n==== MangaTCT %s  launcher %s  %s\n" % (
        version, LAUNCHER_VERSION, _dt.datetime.now().isoformat()))
    out.flush()
    cmd = [p["python"], "-m", "mangatl.editor", "--port", str(port),
           "--no-browser", "--output", os.path.join(output_dir(), "out")]
    log("starting %s on %d" % (version, port))
    env = editor_env(p)
    # ...and the editor is told where its own console is going, so Report a
    # problem can show the last lines of it.
    env["MANGATL_LOG_FILE"] = logfp
    return subprocess.Popen(cmd, cwd=vdir, env=env, stdout=out,
                            stderr=subprocess.STDOUT, creationflags=_no_window())


def wait_for_editor(port: int, proc: subprocess.Popen, timeout: float = EDITOR_WAIT) -> bool:
    url = "http://127.0.0.1:%d/api/version" % port
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError, socket.timeout):
            pass
        time.sleep(0.5)
    return False


# ------------------------------------------------------------- the window
#
# lee: *"make it run on its own app insted of teh browser"*, and *"keep a
# version of this for the future if we want to host it instead"*. The window
# is `python -m mangatl.window` - part of the APP, not of this launcher, so it
# updates with the app and this file stays standard library. It is a second
# process: closing the window is how the person quits, and this launcher,
# which owns the editor, is what notices and stops it. The browser stays one
# flag away (`--browser`, or MANGATCT_BROWSER=1), and is what a copy hosted
# somewhere would be.

#: How long the window process is given to prove it is alive. A missing
#: WebView2 or pywebview exits at once with a code from `mangatl.window`;
#: a window that is still running after this long is a window.
WINDOW_GRACE = 4.0

#: What the exit codes mean, from `mangatl.window`. Logged in words so the
#: launcher log says why the browser opened instead.
WINDOW_EXITS = {3: "pywebview is not installed in the runtime",
                4: "this Windows has no WebView2 runtime"}


def want_window(argv=None) -> bool:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--browser" in argv or "--no-window" in argv:
        return False
    return os.environ.get("MANGATCT_BROWSER", "") not in ("1", "true", "yes")


def start_window(p: dict, version: str, port: int) -> subprocess.Popen | None:
    """The app's own window on the running editor, or None if it could not
    be started at all. A process that starts and then exits within
    `WINDOW_GRACE` is reported by `window_alive`."""
    vdir = app_dir(p, version)
    if not os.path.isfile(os.path.join(vdir, "mangatl", "window.py")):
        log("%s has no window module; browser it is" % version)
        return None
    cmd = [p["python"], "-m", "mangatl.window", "--port", str(port)]
    try:
        logfp = os.path.join(p["logs"], "window-%s.log" % _dt.date.today().isoformat())
        out = open(logfp, "a", encoding="utf-8", errors="replace")
        return subprocess.Popen(cmd, cwd=vdir, env=editor_env(p), stdout=out,
                                stderr=subprocess.STDOUT, creationflags=_no_window())
    except OSError as e:
        log("window did not start: %r" % e)
        return None


def window_alive(proc: subprocess.Popen | None, grace: float = WINDOW_GRACE) -> bool:
    """True once the window has outlived its grace period. A quick exit is
    read for its meaning and logged."""
    if proc is None:
        return False
    end = time.time() + grace
    while time.time() < end:
        code = proc.poll()
        if code is not None:
            log("window exited %d: %s" % (code, WINDOW_EXITS.get(code, "see logs\\window-*.log")))
            return False
        time.sleep(0.1)
    return True


def stop_window(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def stop_editor(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def restart_wanted(proc: subprocess.Popen | None) -> bool:
    """Did the editor end asking to be started again? (Settings > Updates >
    Restart now: the version fetched beside the running one is switched to
    by the next pass, exactly as a start from the icon would.)"""
    return proc is not None and proc.returncode == EDITOR_RESTART


# ------------------------------------------------------------- the start

class Startup:
    """What a start decided, for the window to show and the tests to read."""

    def __init__(self):
        self.version = None
        self.port = None
        self.proc = None
        self.fetched = None
        self.error = ""
        self.fell_back = False
        self.window = None       # the window process, when there is one
        self.shown_in = ""       # "window" or "browser" - what the person got


def choose_and_prepare(p: dict, progress=None) -> tuple[str | None, bool, str]:
    """Pick the newest complete version whose requirements the runtime can
    meet. Returns (version, fell_back, error)."""
    if not runtime_ok(p):
        return None, False, ("The Python runtime is missing from %s. "
                             "Reinstall MangaTCT." % p["runtime"])
    have = installed_versions(p)
    if not have:
        return None, False, ("No version of the app is installed under %s. "
                             "Reinstall MangaTCT." % p["app"])
    for i, v in enumerate(have):
        if pip_sync(p, app_dir(p, v), progress):
            return v, i > 0, ""
        log("%s: requirements could not be met; trying the previous version" % v)
    return None, True, ("The app's packages could not be installed. Check the "
                        "connection and start MangaTCT again, or see logs\\launcher.log.")


def run(p: dict | None = None, manifest_url: str | None = None,
        progress=None, open_browser=True, window=True) -> Startup:
    """The whole start, without the launcher's own little window.
    `progress(text)` is told what is happening; that window draws it.

    `window`: show the editor in its own window (`mangatl.window`); when it
    cannot, or when False, `open_browser` says whether the browser is opened
    instead. Tests pass both False and read `s.port`."""
    p = p or paths()
    manifest_url = manifest_url or MANIFEST_URL
    ensure_dirs(p)
    start_log(p)
    s = Startup()
    log("launcher %s starting in %s" % (LAUNCHER_VERSION, p["root"]))

    # 1. the channel - bounded, and never a reason not to start
    if progress:
        progress("Checking for updates…")
    m = fetch_manifest(manifest_url)
    try:
        s.fetched = check_for_update(
            p, m, progress=(lambda d, t: progress("Downloading update… %d%%" % (100 * d // t if t else 0)))
            if progress else None)
    except Exception as e:      # an update must never stop a start
        log("update check failed: %r" % e)

    # 2. which version, and can the runtime run it
    v, fell_back, err = choose_and_prepare(p, progress)
    s.version, s.fell_back, s.error = v, fell_back, err
    if not v:
        log("cannot start: " + err)
        return s
    write_state(p, app=v)
    prune_old(p, v)

    # 2b. the weights - fetched once, kept across versions
    err = ensure_models(p, app_dir(p, v), progress)
    if err:
        s.error = err
        log("cannot start: " + err)
        return s
    # A start switches to everything it can use, so nothing is "waiting"
    # once one has happened: what was fetched is running, or could not be
    # prepared and must not be advertised as ready. The watcher below
    # writes the line again if something new arrives mid-session.
    say_update(p, None)

    # 3. the editor
    s.port = free_port()
    if progress:
        progress("Starting MangaTCT %s…" % v)
    s.proc = start_editor(p, v, s.port)
    if not wait_for_editor(s.port, s.proc):
        s.error = ("MangaTCT did not start. The last lines of logs\\editor-%s.log "
                   "say why." % _dt.date.today().isoformat())
        log(s.error)
        stop_editor(s.proc)
        return s
    log("up at %d" % s.port)
    if window:
        if progress:
            progress("Opening MangaTCT %s…" % v)
        s.window = start_window(p, v, s.port)
        if window_alive(s.window):
            s.shown_in = "window"
        else:
            s.window = None
    if not s.window and open_browser:
        import webbrowser
        webbrowser.open("http://127.0.0.1:%d" % s.port)
        s.shown_in = "browser"
    threading.Thread(target=watch_for_updates, args=(p, manifest_url, s.proc),
                     daemon=True).start()
    return s


def watch_for_updates(p: dict, manifest_url: str, proc: subprocess.Popen,
                      every: float = RECHECK_EVERY) -> None:
    """While the editor runs, look again now and then. A version fetched here
    is NOT switched to - see the module docstring - it is put beside the
    current one and the header pill says it is waiting."""
    while proc.poll() is None:
        for _ in range(int(every)):
            if proc.poll() is not None:
                return
            time.sleep(1)
        try:
            check_for_update(p, fetch_manifest(manifest_url))
        except Exception as e:
            log("recheck failed: %r" % e)


# ----------------------------------------------------------------- window

def icon_files() -> tuple[str, str]:
    """(icon.ico, icon.png) - inside the frozen exe when there is one, beside
    the source tree when there is not. Either may be missing; callers cope."""
    bases = []
    if getattr(sys, "_MEIPASS", ""):
        bases.append(sys._MEIPASS)                       # type: ignore[attr-defined]
    bases.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))
    for b in bases:
        ico, png = os.path.join(b, "icon.ico"), os.path.join(b, "icon.png")
        if os.path.isfile(ico) or os.path.isfile(png):
            return ico, png
    return "", ""


def wear_the_mark(root) -> None:
    """The MangaTCT mark on the launcher's window - title bar and taskbar.
    Tk stamps its own feather on any window that does not set one, which is
    what lee saw and sent. Never allowed to matter: a missing file, an old
    Tk - the window is the point, the picture on it is not."""
    ico, png = icon_files()
    if sys.platform == "win32" and os.path.isfile(ico):
        try:
            root.iconbitmap(default=ico)
            return
        except Exception:
            pass
    if os.path.isfile(png):
        try:
            import tkinter
            root._mangatct_icon = tkinter.PhotoImage(file=png)
            root.iconphoto(True, root._mangatct_icon)
        except Exception:
            pass


def dark_frame(root) -> None:
    """The launcher window's title bar in the dark, like the app's. Windows
    draws it white unless asked; the ask is one DWM attribute, and the same
    two colours `mangatl/window.py` gives the app window. Nothing here may
    fail loudly - an older Windows simply keeps its own frame."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        dwm = ctypes.windll.dwmapi
        for attr, value in ((20, 1), (35, 0x161210), (34, 0x161210), (36, 0xECE8E6)):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                      ctypes.byref(v), ctypes.sizeof(v))
        # the frame is repainted on the next show; a withdraw/deiconify is the
        # cheap way to ask for one before the person sees the white
        root.withdraw()
        root.deiconify()
    except Exception:
        pass


def mark_image(root, size: int = 32):
    """The mark as a Tk image `size` pixels square, for beside the name; None
    when it cannot be had. Tk shrinks only by whole factors, so 512 comes
    down to 32 by sixteen."""
    _, png = icon_files()
    if not os.path.isfile(png):
        return None
    try:
        import tkinter
        im = tkinter.PhotoImage(file=png)
        f = max(1, im.width() // size)
        im = im.subsample(f, f) if f > 1 else im
        root._mangatct_mark = im
        return im
    except Exception:
        return None


def main(argv=None) -> int:
    """A small window: the version, the address, Open and Quit. Closing it
    stops the editor - the window IS the app as far as Windows is
    concerned, and a server left running with no window is a mystery
    process in Task Manager."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv or "--help" in argv:
        # The release job runs the freshly built exe once with this, to prove
        # it starts at all. A windowed exe has no console to print to; the
        # exit code is the answer.
        print("MangaTCT launcher %s" % LAUNCHER_VERSION)
        return 0
    if "--headless" in argv:
        while True:
            s = run(progress=lambda t: print(t, file=sys.stderr),
                    open_browser="--no-browser" not in argv, window=want_window(argv))
            if not s.proc:
                print(s.error, file=sys.stderr)
                return 1
            try:
                s.proc.wait()
            except KeyboardInterrupt:
                stop_editor(s.proc)
            stop_window(s.window)
            if not restart_wanted(s.proc):
                return 0
            log("the editor asked to be started again")

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("MangaTCT")
    root.resizable(False, False)
    wear_the_mark(root)
    dark_frame(root)
    frame = ttk.Frame(root, padding=18)
    frame.grid()
    mark = mark_image(root)
    # The mark beside the name (a leading space is the gap: ttk has no
    # image-to-text padding of its own).
    title = ttk.Label(frame, text=" MangaTCT" if mark else "MangaTCT",
                      font=("Segoe UI", 14, "bold"), image=mark, compound="left")
    title.grid(row=0, column=0, columnspan=2, sticky="w")
    status = tk.StringVar(value="Starting…")
    ttk.Label(frame, textvariable=status, wraplength=360).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(6, 12))
    state = {"s": None}

    def open_it():
        if state["s"] and state["s"].port:
            import webbrowser
            webbrowser.open("http://127.0.0.1:%d" % state["s"].port)

    def open_logs():
        try:
            os.startfile(paths()["logs"])      # type: ignore[attr-defined]
        except Exception:
            pass

    def quit_it():
        if state["s"]:
            stop_window(state["s"].window)
            if state["s"].proc:
                stop_editor(state["s"].proc)
        root.destroy()

    b_open = ttk.Button(frame, text="Open in browser", command=open_it, state="disabled")
    b_open.grid(row=2, column=0, sticky="w")
    ttk.Button(frame, text="Quit", command=quit_it).grid(row=2, column=1, sticky="e", padx=(12, 0))
    ttk.Button(frame, text="Open logs folder", command=open_logs).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
    root.protocol("WM_DELETE_WINDOW", quit_it)

    def progress(text):
        root.after(0, status.set, text)

    def go():
        # One session per pass; another pass when the editor ends asking
        # for one (Restart now, after an update was fetched). A start that
        # failed leaves this window up with the reason on it.
        while True:
            how = go_once()
            if how == "again":
                root.after(0, root.deiconify)
                root.after(0, b_open.config, {"state": "disabled"})
                continue
            if how == "ended":
                root.after(0, root.destroy)
            return

    def go_once() -> str:
        """One session: "again" when the editor asked to be started again,
        "ended" when it ended any other way, "failed" when it never
        started."""
        s = run(progress=progress, window=want_window(argv))
        state["s"] = s

        def done():
            if s.proc and s.port:
                line = "MangaTCT %s is running at http://127.0.0.1:%d" % (s.version, s.port)
                if s.fetched and s.fetched == s.version:
                    line += "\nUpdated to %s just now." % s.fetched
                if s.fell_back:
                    line += ("\n(Started an earlier version - the newest could not "
                             "be prepared. See logs\\launcher.log.)")
                status.set(line)
                b_open.config(state="normal")
                title.config(text=("%sMangaTCT %s" % (" " if mark else "", s.version)))
                # The app has its own window now; this one would only be a
                # second MangaTCT on the taskbar. It comes back if the app's
                # window goes away while the editor is still running, with
                # the browser button on it - the browser is always there.
                if s.window is not None:
                    root.withdraw()
            else:
                status.set(s.error or "MangaTCT could not start.")
        root.after(0, done)

        if s.proc and s.window is not None:
            # Two things can end a session: the person closing the window,
            # which is quitting, or the window dying on its own, which is
            # not - then the launcher shows itself again and the editor,
            # still running, is one click away in the browser.
            def watch_window():
                s.window.wait()
                if s.proc.poll() is None:
                    if s.window.returncode == 0:
                        stop_editor(s.proc)
                    else:
                        log("window ended with %d while the editor runs" % s.window.returncode)
                        root.after(0, root.deiconify)
                        root.after(0, status.set,
                                   "The MangaTCT window closed unexpectedly. The editor is "
                                   "still running - open it in the browser, or quit.")
            threading.Thread(target=watch_window, daemon=True).start()

        if not s.proc:
            return "failed"
        s.proc.wait()
        stop_window(s.window)
        if restart_wanted(s.proc):
            log("the editor asked to be started again")
            return "again"
        return "ended"

    threading.Thread(target=go, daemon=True).start()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
