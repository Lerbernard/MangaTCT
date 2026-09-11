"""Things that belong to the PERSON, not to a chapter.

A project is a folder of pages and the settings for translating them, and it is
thrown away when the chapter is finished. Two things do not belong there:

* **Fonts you uploaded.** Buying or finding a typesetting face and dropping it in
  is work you do once. Filing it under a chapter means doing it again for the
  next chapter, and losing it when that folder goes.
  lee: *"Allow uploading fonts in the setting and a way to remove the fonts
  that were uploaded - the fonts should presist to new projects"*.
* **The fonts you reached for last.** A list of four hundred faces with the one
  you always use somewhere in the middle is a search box, every time.
* **Your keys.** lee: *"they key shoud be in the .env file and all teh project
  shoud use them"*. A key is a thing you own, not a thing this chapter owns.
  Kept in a chapter it is copied into every chapter folder, goes stale in all
  of them at once when you roll it, and travels inside any `.tctp` you hand
  somebody. See `env_key` below.

So all three live beside the app instead: `~/.mangatl`, or wherever
`MANGATL_HOME` points. Outside the repo on purpose - the editor's own files get
replaced whenever a new version is copied over the top, and an uploaded font
must not be something a copy can take away.
"""
from __future__ import annotations

import json
import os
import time
import re

# How many "last used" faces are remembered. Five is what fits above the list
# without pushing the list itself off the screen, and past five "recent" stops
# meaning anything.
RECENT_MAX = 5

_PREFS_NAME = "prefs.json"


def user_dir() -> str:
    """The folder this person's own settings live in. Made on demand."""
    root = os.environ.get("MANGATL_HOME") or \
        os.path.join(os.path.expanduser("~"), ".mangatl")
    return os.path.abspath(root)


def fonts_dir() -> str:
    """Where uploaded faces are kept."""
    return os.path.join(user_dir(), "fonts")


def _ensure(d: str) -> str:
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def load_prefs() -> dict:
    """Never raises. A prefs file that has been hand-edited into nonsense is a
    reason to start again, not a reason the editor will not open."""
    try:
        with open(os.path.join(user_dir(), _PREFS_NAME), encoding="utf8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def save_prefs(d: dict) -> None:
    _ensure(user_dir())
    tmp = os.path.join(user_dir(), _PREFS_NAME + ".tmp")
    try:
        with open(tmp, "w", encoding="utf8") as fh:
            json.dump(d, fh, indent=1)
        os.replace(tmp, os.path.join(user_dir(), _PREFS_NAME))
    except OSError:
        pass


# --------------------------------------------------------------------- keys
#
# There are four, and lee named them: *"all the key i need to put ius claude
# gemini open router and clenner"*. Three are the AI services; the fourth is
# the page cleaner's token, which is not an API key but is the same kind of
# secret and lives in the same place for the same reason.
#
# WHAT EACH IS CALLED IN THE FILE. The first name is this app's own, and the
# one `write_env` writes. The rest are read as well, because they are what
# every other tool calls the same key - somebody who already has a `.env` for
# their own scripts should not have to keep a second copy of the same string
# under a different name.
ENV_NAMES: dict[str, tuple] = {
    "anthropic":  ("MANGATL_ANTHROPIC_KEY", "ANTHROPIC_API_KEY",
                   "CLAUDE_API_KEY"),
    "gemini":     ("MANGATL_GEMINI_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("MANGATL_OPENROUTER_KEY", "OPENROUTER_API_KEY"),
    "clean":      ("MANGATL_CLEAN_TOKEN", "CLEAN_TOKEN"),
}

_ENV_NAME = ".env"


def env_paths() -> list:
    """Every `.env` this app will read, best answer first.

    Three places, because the argument for one of them is not the argument for
    the others:

    1. `MANGATL_ENV`, if it is set. Somebody who names a file outright means
       that file and nothing else.
    2. `~/.mangatl/.env` - beside the fonts and the prefs. **The default**, and
       the one `env_path` writes, for the reason this module opens with: the
       app's own folder gets replaced whenever a new build is copied over the
       top, and a key must not be something a copy can take away.
    3. `<the app's own folder>/.env`. Read but never written. It is where
       somebody looking for a `.env` looks first, and refusing to read a file
       sitting right there with the right name in it would be its own kind of
       bug. Keep a key here and you are accepting that a rebuild can lose it,
       and that it is one careless `git add` from being published - which is
       why `.gitignore` names it.

    A name found in an earlier file wins; the files are not otherwise merged
    per-file, so two `.env`s each holding two different keys give you all
    four.
    """
    out = []
    named = (os.environ.get("MANGATL_ENV") or "").strip()
    if named:
        out.append(os.path.abspath(named))
    out.append(os.path.join(user_dir(), _ENV_NAME))
    out.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            _ENV_NAME))
    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def env_path() -> str:
    """The one that gets WRITTEN, and the one the screen names."""
    named = (os.environ.get("MANGATL_ENV") or "").strip()
    return os.path.abspath(named or os.path.join(user_dir(), _ENV_NAME))


def parse_env(text: str) -> dict:
    """`NAME=value` lines into a dict. Never raises.

    A hand-edited file is the normal case here - the person opens it in
    Notepad and pastes a key in - so every way that can go slightly wrong is
    absorbed rather than reported:

    * `export NAME=value`, which is what a shell `.env` looks like.
    * Quotes round the value, which is what most `.env` files look like.
      Whatever is between them is kept verbatim, spaces included - this
      function's job is to say what the file SAYS. `env_key` strips it before
      anybody sends it anywhere, because a key with a space on the end of it
      is a paste error every single time, and the provider's answer to one is
      "please pass a valid API key", which reads like a wrong key rather than
      like a key with a space on it. lee has read that sentence once already.
    * A UTF-8 BOM on the first line - Notepad's own default for years, and it
      would otherwise make the FIRST key alone unreadable while every key
      under it worked.
    * `#` comments, blank lines, and lines with no `=` at all.

    What is NOT absorbed: a `#` inside a value. A key may contain one, and
    nothing about `sk-ant-...#...` says "comment starts here".
    """
    out: dict = {}
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.lstrip("﻿").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[7:].strip()
        if not name:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[name.upper()] = val
    return out


def _read_env(path: str) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return parse_env(fh.read())
    except Exception:
        return {}


def load_env(path: str = "") -> dict:
    """Everything the `.env`s say, upper-cased names, best answer first.

    `{}` when there is no file anywhere, which is the normal state of a fresh
    install rather than an error.
    """
    if path:
        return _read_env(path)
    out: dict = {}
    for p in env_paths():
        for k, v in _read_env(p).items():
            # An EMPTY line does not answer for anything. `NAME=` means "I
            # have not filled this in yet", and letting one in the first file
            # stop the second file being read would make a half-written `.env`
            # silently switch the other one off.
            if str(v or "").strip():
                out.setdefault(k, v)
    return out


def env_key(service: str) -> str:
    """The key for one service, or `""`.

    Two rules, and the second is the one worth reading:

    **The FILE wins over the process environment.** That is the opposite of
    what a dotenv loader usually does, and it is deliberate. The file is the
    thing lee edits and can see; an exported variable is not, and having one
    quietly beat the file would be unexplainable from the screen.

    **Only OUR OWN names are read from the process environment.** The generic
    names - `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY` - are
    read from the FILE only. They are in `ENV_NAMES` so that a `.env` somebody
    already keeps for their own scripts works unchanged, and that is a file
    they pointed this app at. A shell profile is not: `GOOGLE_API_KEY` is
    exported on a great many machines for a great many reasons, and a key
    picked up from one of them would spend somebody's quota from a project
    that never mentioned it, with nothing on screen saying where it came from.
    `MANGATL_GEMINI_KEY=... mangatl` still works, because that name can only
    have been set for this.
    """
    names = ENV_NAMES.get((service or "").strip().lower())
    if not names:
        return ""
    got = load_env()
    for n in names:
        v = str(got.get(n) or "").strip()
        if v:
            return v
    for n in names:
        if not n.startswith("MANGATL_"):
            continue
        v = str(os.environ.get(n) or "").strip()
        if v:
            return v
    return ""


def env_state() -> dict:
    """Which of the four are set, for the screen. Never a key, only a boolean."""
    return {k: bool(env_key(k)) for k in ENV_NAMES}


def write_env(values: dict, path: str = "") -> str:
    """Save keys, keeping every other line of the file exactly as it was.

    A `.env` is a file a person owns and may have their own lines in. This
    rewrites only the names it is given: an existing line for one of them is
    replaced in place, keeping its position and its spelling (so a file using
    `GEMINI_API_KEY` goes on using it rather than sprouting a second name for
    the same key), and anything missing is appended under a heading.

    `values` is keyed by service - `anthropic`, `gemini`, `openrouter`,
    `clean`. A value of `""` REMOVES that key rather than writing an empty
    one, because an empty `NAME=` reads as "set to nothing" at every other
    line of this module and "not set" is what was meant.
    """
    path = path or env_path()
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().replace("\r\n", "\n").split("\n")
    except OSError:
        lines = []
    todo = {k: v for k, v in values.items() if k in ENV_NAMES}
    done: set = set()
    out: list = []
    for raw in lines:
        bare = raw.lstrip("﻿").strip()
        name = bare.partition("=")[0].strip()
        if name.startswith("export "):
            name = name[7:].strip()
        which = ""
        if "=" in bare and not bare.startswith("#"):
            for svc, names in ENV_NAMES.items():
                if name.upper() in names and svc in todo:
                    which = svc
                    break
        if not which:
            out.append(raw)
            continue
        val = str(todo[which] or "").strip()
        done.add(which)
        if val:
            out.append(f"{name}={val}")
        # else: the line is dropped, which is how a key is removed.
    add = [(s, str(todo[s] or "").strip()) for s in todo
           if s not in done and str(todo[s] or "").strip()]
    if add:
        while out and not out[-1].strip():
            out.pop()
        if out:
            out.append("")
        out.append("# mangatl")
        for svc, val in add:
            out.append(f"{ENV_NAMES[svc][0]}={val}")
    _ensure(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out).rstrip("\n") + "\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)          # no-op on Windows, right everywhere else
    except OSError:
        pass
    return path


# ------------------------------------------------------------ recent projects

RECENT_PROJECTS = 12


def recent_projects() -> list:
    """Chapters opened or saved as a `.tctp`, newest first, for the Home
    screen. Each is `{path, name, pages, medium, at}`; a file that has since
    gone is still listed, with `exists: False`, so the person can see what
    happened to it and take it off the list."""
    out = []
    for r in load_prefs().get("recent_projects") or []:
        if not isinstance(r, dict) or not r.get("path"):
            continue
        r = dict(r)
        r["exists"] = os.path.isfile(r["path"])
        out.append(r)
    return out


def note_project(path: str, pages: int = 0, medium: str = "") -> list:
    """Put a chapter at the top of the list (once: the same path moves up)."""
    path = os.path.abspath(str(path or ""))
    if not path:
        return recent_projects()
    prefs = load_prefs()
    key = os.path.normcase(path)
    rest = [r for r in (prefs.get("recent_projects") or [])
            if isinstance(r, dict) and os.path.normcase(str(r.get("path") or "")) != key]
    name = os.path.splitext(os.path.basename(path))[0]
    prefs["recent_projects"] = ([{"path": path, "name": name, "pages": int(pages or 0),
                                  "medium": str(medium or ""), "at": time.time()}]
                                + rest)[:RECENT_PROJECTS]
    save_prefs(prefs)
    return recent_projects()


def forget_project(path: str) -> list:
    prefs = load_prefs()
    key = os.path.normcase(os.path.abspath(str(path or "")))
    prefs["recent_projects"] = [r for r in (prefs.get("recent_projects") or [])
                                if isinstance(r, dict)
                                and os.path.normcase(str(r.get("path") or "")) != key]
    save_prefs(prefs)
    return recent_projects()


# ------------------------------------------------------------------ recents

def recent_fonts() -> list:
    """Most recently chosen first. Faces that have since been deleted are
    dropped on the way out rather than offered and then failing to load."""
    got = load_prefs().get("recent_fonts") or []
    return [p for p in got if isinstance(p, str) and os.path.isfile(p)]


def note_font_used(path: str) -> list:
    """Remember this face as the last one reached for.

    Moved to the front if it is already there, so using the same three faces
    all week does not push them out with duplicates of themselves.
    """
    path = (path or "").strip()
    if not path or not os.path.isfile(path):
        return recent_fonts()
    prefs = load_prefs()
    got = [p for p in (prefs.get("recent_fonts") or [])
           if isinstance(p, str) and os.path.normcase(p) !=
           os.path.normcase(path)]
    got.insert(0, path)
    prefs["recent_fonts"] = got[:RECENT_MAX]
    save_prefs(prefs)
    return recent_fonts()


# ------------------------------------------------------------------- fonts

_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


def safe_name(name: str) -> str:
    """A file name that cannot be a path.

    The name arrives from a browser, and a browser will happily hand over
    `../../.ssh/authorized_keys`. Only the last component is kept, and only the
    characters a font is ever actually named with.
    """
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = _SAFE.sub("_", name).lstrip(".") or "font"
    stem, ext = os.path.splitext(name)
    if ext.lower() not in (".ttf", ".otf"):
        ext = ".ttf"
    return (stem[:60] or "font") + ext


def uploaded_fonts() -> list:
    """Full paths of the faces this person has added, by name."""
    d = fonts_dir()
    try:
        names = sorted(f for f in os.listdir(d)
                       if f.lower().endswith((".ttf", ".otf")))
    except OSError:
        return []
    return [os.path.join(d, f) for f in names]


def add_font(filename: str, data: bytes) -> str:
    """Save an uploaded face and return its path.

    Refuses anything that is not a font the typesetter can actually set type in -
    a symbol face or an icon set opens perfectly and has no alphabet, and
    choosing one empties every balloon on the page. That check already exists
    for picking a font; it has to happen at the door as well, or the bad file
    sits in the list waiting to be picked.
    """
    from . import typeset as typeset_mod
    if not data:
        raise ValueError("that file was empty")
    _ensure(fonts_dir())
    dest = os.path.join(fonts_dir(), safe_name(filename))
    # A second upload of the same face replaces it rather than piling up
    # "Font.ttf", "Font (1).ttf", "Font (2).ttf" - the person is fixing a bad
    # copy, not collecting them.
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    if not typeset_mod.can_typeset(tmp):
        os.remove(tmp)
        raise ValueError("that file is not a font type can be set in")
    os.replace(tmp, dest)
    return dest


def remove_font(path: str) -> bool:
    """Delete an uploaded face. Only ever one of ours.

    The path comes from the browser, so it is checked against the uploaded
    folder itself rather than trusted - a delete endpoint that takes a path is
    a file remover if it does not.
    """
    path = os.path.abspath(path or "")
    d = os.path.abspath(fonts_dir())
    if os.path.normcase(os.path.dirname(path)) != os.path.normcase(d):
        return False
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    prefs = load_prefs()
    got = [p for p in (prefs.get("recent_fonts") or [])
           if os.path.normcase(p) != os.path.normcase(path)]
    prefs["recent_fonts"] = got
    save_prefs(prefs)
    return True
