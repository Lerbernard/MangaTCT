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

So both live beside the app instead: `~/.mangatl`, or wherever `MANGATL_HOME`
points. Outside the repo on purpose - the editor's own files get replaced
whenever a new version is copied over the top, and an uploaded font must not be
something a copy can take away.
"""
from __future__ import annotations

import json
import os
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
