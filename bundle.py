"""A chapter in one file - the `.tctp` bundle, and the `.tct` series file.

lee: *"can you creat custo file that end with .tct and .tctp?"*, and when
asked what each should hold: the project one carries **the whole chapter,
pages included**, and the other is *"just a rename of the json file we already
have withthe spory synopsis and charatter and places"*.

So there are two, and they are different kinds of thing:

**`.tct` - the series.** The settings and the story bible: fonts, sizes, the
translation engine, the custom box types, the synopsis, the characters, the
glossary. It is JSON, byte for byte the file "Export everything" already
wrote, under a name of its own. Small, readable, and the thing you carry from
chapter one to chapter two. It is written by the browser, which is where those
values live; nothing in this module touches it beyond knowing the extension.

**`.tctp` - the chapter.** A zip holding everything that cannot be worked out
again:

    mangatct.json     what this is, and which version wrote it
    project.json      the state - every box, the Japanese, the English, the
                      layouts, the paint layers, the custom box types, the
                      settings and the story bible
    input/            the pages themselves, and under `tiles/` the slices a
                      webtoon arrived as, which are the only copy of the
                      original scan
    paint/            the touch-up strokes somebody drew
    custom_clean/     plates somebody cleaned by hand
    fonts/            every face the chapter typesets in

lee: *"make it so tht everything is save including kayers custom boxes fonts
besicaly everything when ii load this project file it shoud be excaty as it it
now"*. The fonts are the part that is easy to miss: a face you uploaded lives
in `~/.mangatl/fonts`, deliberately OUTSIDE any chapter so it survives the
chapter - which means it is not in the project folder and would not travel.
A bundle carries the faces the chapter actually uses, and installs any that
are missing when it is opened.

Not in it: `plate_cache/` and `ai_clean_cache/`. Both are things the app makes
for itself and can make again, and together they are usually larger than the
chapter. A bundle is what you cannot rebuild.

**Paths go in relative and come out absolute.** A project.json holds absolute
paths - `C:\\Users\\leema\\...\\input\\p001.png` - and a file whose whole point
is to open on another machine cannot carry those. They are rewritten to
`input/p001.png` on the way in and back to wherever the bundle was opened on
the way out. Nothing else about the state is touched, so a bundle written by
this version opens in this version exactly as the folder it came from.
"""
from __future__ import annotations

import io
import json
import os
import posixpath
import shutil
import zipfile

# Bumped when the LAYOUT of the bundle changes - a folder renamed, a field
# rewritten differently. Not when the project state gains a field: that is
# `project.json`'s own business and it has always been tolerant of both
# directions.
FORMAT = 1

EXT = ".tctp"                 # the chapter
MANIFEST = "mangatct.json"
STATE = "project.json"

# What is carried, and where it lands. Anything else in the project folder is
# either derived (the two caches) or output (the exported pages).
CARRIED = ("input", "paint", "custom_clean")

# The fields of a page that name a file. Each is rewritten on the way in and
# on the way out; the folder is the one it is kept in.
PAGE_FILES = (("path", "input"),
              ("custom_clean", "custom_clean"),
              ("paint_overlay", "paint"),
              ("paint_over", "paint"))


FONTS = "fonts"

#: The CLEANED PAGES, one per page index.
#:
#: The two caches were left out on the rule that a bundle is what you cannot
#: rebuild - and a plate is rebuildable, so out it went. That rule missed what
#: rebuilding one COSTS. An AI clean is coins and minutes a page; a local one
#: is minutes. lee, opening a chapter he had cleaned: *"teh clened pages didnt
#: survive teh closinga and opeing a tctp file"*, and then the half that names
#: the fault exactly - *"the manual fixes survide butr teh automated one
#: didnt"*. His hand-cleaned plates and his paint were carried; the cleaner's
#: own work was thrown away and silently re-run.
#:
#: Kept by PAGE INDEX and not by the name the cache uses. That name is a hash
#: of everything that identifies a plate - the scan, the boxes, the eraser,
#: the token, the cleaner's version - and two of those (the hand-cleaned
#: plate's path, and the token when it comes from a different machine's
#: `.env`) are not the same on the machine that opens the file. So the plate
#: travels under a name that cannot go stale, and the app re-keys it into its
#: own cache on the way in: see `editor._adopt`.
PLATES = "plates"


def map_fonts(state: dict, fn) -> dict:
    """`state` with every place it names a font file passed through `fn`.

    There are more of them than there look to be. The project has a default
    face; each of the three families has one; every custom sub-type may name
    its own; and a single BOX may have been given one by hand, in its layout
    or in the override on top of it. Miss any one and a chapter opens in the
    right font except for the four boxes somebody set specially, which is a
    worse failure than opening in the wrong font throughout - nobody looks for
    it.
    """
    out = dict(state)
    s = dict(out.get("settings") or {})
    if s.get("font"):
        s["font"] = fn(s["font"])
    if isinstance(s.get("fonts"), dict):
        s["fonts"] = {k: (fn(v) if v else v) for k, v in s["fonts"].items()}
    if isinstance(s.get("custom_kinds"), list):
        s["custom_kinds"] = [
            ({**k, "font": fn(k["font"])}
             if isinstance(k, dict) and k.get("font") else k)
            for k in s["custom_kinds"]]
    out["settings"] = s
    pages = []
    for pg in out.get("pages") or []:
        pg = dict(pg)
        regions = []
        for r in pg.get("regions") or []:
            r = dict(r)
            for key in ("layout", "layout_override"):
                block = r.get(key)
                if not isinstance(block, dict):
                    continue
                if block.get("font"):
                    block = {**block, "font": fn(block["font"])}
                # ...AND A RANGE INSIDE THE BOX. Part of the text can be set
                # in a face of its own now (`layout_override.spans`), which
                # is one more place a font file is named and the newest one:
                # a chapter with a word in an uploaded face travelled with
                # the face left behind, and opened with that word in
                # whatever the default was. Same failure as a custom kind's
                # font and the same fix.
                spans = block.get("spans")
                if isinstance(spans, list) and any(
                        isinstance(sp, dict) and (sp.get("st") or {}).get("font")
                        for sp in spans):
                    block = {**block, "spans": [
                        ({**sp, "st": {**sp["st"],
                                       "font": fn(sp["st"]["font"])}}
                         if isinstance(sp, dict)
                         and (sp.get("st") or {}).get("font") else sp)
                        for sp in spans]}
                r[key] = block
            regions.append(r)
        pg["regions"] = regions
        pages.append(pg)
    out["pages"] = pages
    return out


def _rel(path: str, root: str, folder: str) -> str:
    """`path` as it is written inside the bundle: forward slashes, no drive.

    Kept relative to the folder it belongs to where it really is under it -
    which preserves `input/tiles/…` - and reduced to a bare filename where it
    is not, so a page that was picked up from somewhere else still travels.
    """
    if not path:
        return ""
    base = os.path.join(root, folder)
    try:
        inside = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except ValueError:                       # different drive on Windows
        inside = os.path.basename(path)
    if inside.startswith("..") or os.path.isabs(inside):
        inside = os.path.basename(path)
    return posixpath.join(folder, inside.replace("\\", "/"))


def _abs(rel: str, root: str) -> str:
    """Back to a real path under `root`, and never, ever outside it.

    A zip may name anything at all, and a bundle can arrive from anyone. Two
    ways out of a folder are refused here rather than checked for afterwards:

    * `..`, which walks upwards - the old and obvious one;
    * a segment with a colon in it, which on Windows walks SIDEWAYS.
      `os.path.join("C:/work", "D:", "evil")` is `"D:evil"` - the root is
      simply discarded, and a check that the result starts with the root is
      the check that lets it through on the machine most of this app's users
      are on.
    """
    if not rel:
        return ""
    parts = [q for q in rel.replace("\\", "/").split("/")
             if q not in ("", ".", "..") and ":" not in q]
    return os.path.join(root, *parts) if parts else ""


def pack_pages(state: dict, root: str) -> tuple[dict, dict]:
    """The state with every page path rewritten, AND the files to carry.

    THE FILES A BUNDLE CARRIES ARE THE FILES THE STATE NAMES.

    They used to be whatever happened to be lying under `input/`, `paint/`
    and `custom_clean/`, on the assumption that a page always lives in the
    project's own upload folder. Two ordinary chapters break it:

    * **A folder used in place.** `use_folder` points the project at pages
      where they already are and copies nothing (that is the whole point of
      it) - so `input/` is empty and the bundle came out with a manifest, a
      project.json and NOT ONE PAGE.
    * **A re-cut webtoon whose tiles came from somebody else's folder.**
      The stitched pages are written to `<project>/strip/`, which is not a
      carried folder, with exactly the same result. Manhwa and manhua are
      the formats that arrive that way.

    Both were silent: the file wrote, the zip opened, and the chapter came
    back with every box, every translation and no artwork.

    So the pages are collected BY NAME, from wherever they really are, and
    the folder walks in `write` stay on top of that for anything the state
    does not name (the `input/tiles/` slices, for one).

    Returns `(state, {name inside the bundle: real path})`.
    """
    out = dict(state)
    out["input_dir"] = "input"
    grabbed: dict[str, str] = {}
    pages = []
    for pg in state.get("pages") or []:
        pg = dict(pg)
        for field, folder in PAGE_FILES:
            if not pg.get(field):
                continue
            real = os.path.abspath(os.path.expanduser(str(pg[field])))
            name = _rel(str(pg[field]), root, folder)
            if os.path.isfile(real):
                # Two pages of the same name from different folders - which
                # is what re-cutting a chapter over another one leaves, and
                # what two source folders give straight away. Keep both:
                # the page that wants the second is not the page that wants
                # the first. Same rule as the faces below.
                n = 2
                while grabbed.get(name, real) != real:
                    head, tail = posixpath.split(name)
                    stem, ext = posixpath.splitext(tail)
                    name = posixpath.join(head, "%s-%d%s" % (stem, n, ext))
                    n += 1
                grabbed[name] = real
            pg[field] = name
        pages.append(pg)
    out["pages"] = pages
    return out, grabbed


def state_for_bundle(state: dict, root: str) -> dict:
    """The project state with every path written the way a bundle holds it."""
    return pack_pages(state, root)[0]


def state_from_bundle(state: dict, root: str) -> dict:
    """The same state with every path pointing at where it has just landed."""
    out = dict(state)
    out["input_dir"] = os.path.join(root, "input")
    pages = []
    for pg in state.get("pages") or []:
        pg = dict(pg)
        for field, _folder in PAGE_FILES:
            if pg.get(field):
                pg[field] = _abs(str(pg[field]), root)
        pages.append(pg)
    out["pages"] = pages
    return out


def without_secrets(state: dict) -> dict:
    """`state` with every API key and token taken out of the settings.

    A `.tctp` is the file you HAND SOMEBODY - that is what it is for - and a
    project's settings hold the Claude, Gemini, OpenRouter and cleaner
    credentials. They went into the zip in the clear, so sharing a chapter
    shared whatever those keys can spend.

    Taking them out costs the person who made the bundle nothing: keys live in
    `~/.mangatl/.env` and that file BEATS whatever a chapter has saved in it
    (see `test_one_file_holds_the_keys`), so your own bundle opens on your own
    machine with your own keys exactly as before. What changes is that
    somebody else's copy arrives with none.
    """
    s = state.get("settings")
    if not isinstance(s, dict):
        return state
    from .project import secret_keys
    gone = [k for k in secret_keys(s) if s.get(k)]
    if not gone:
        return state
    out = dict(state)
    out["settings"] = {k: ("" if k in gone else v) for k, v in s.items()}
    return out


def write(state: dict, root: str, plates: dict | None = None) -> bytes:
    """A `.tctp` for the project whose folder is `root`.

    Deflated, because a project.json is most of a megabyte of very repetitive
    JSON. The PNGs in it are already compressed and simply pass through.

    `plates` is `{page index: the cleaned plate's file}` - see `PLATES`. The
    caller works them out because the cache's naming belongs to `editor`, and
    a bundle that had to import it would be a bundle that could not be read
    without the whole app.
    """
    state = without_secrets(state)
    faces: dict[str, str] = {}          # name inside the bundle -> real path

    def take(path: str) -> str:
        real = os.path.abspath(os.path.expanduser(str(path)))
        if not os.path.isfile(real):
            # Not a file we can carry. It may be a face that was already
            # missing here, and rewriting it would only make the loss harder
            # to see. Left exactly as the project has it.
            return path
        name = os.path.basename(real)
        # Two faces of the same name from different folders. Keep both: the
        # boxes that use the second one are not the boxes that use the first.
        n = 2
        while faces.get(name, real) != real:
            stem, ext = os.path.splitext(os.path.basename(real))
            name = f"{stem}-{n}{ext}"
            n += 1
        faces[name] = real
        return posixpath.join(FONTS, name)

    state, grabbed = pack_pages(state, root)
    packed = map_fonts(state, take)
    buf = io.BytesIO()
    written: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        from .version import __version__
        z.writestr(MANIFEST, json.dumps(
            {"mangatct": FORMAT, "kind": "project", "app": __version__},
            ensure_ascii=False))
        z.writestr(STATE, json.dumps(packed, ensure_ascii=False))
        for name, real in sorted(faces.items()):
            z.write(real, posixpath.join(FONTS, name))
        # The pages, the hand-cleaned plates and the paint, from wherever
        # they actually are. See `pack_pages`.
        for name, real in sorted(grabbed.items()):
            z.write(real, name)
            written.add(name)
        # The cleaner's own work, one plate per page. See `PLATES`.
        for idx, real in sorted((plates or {}).items()):
            try:
                if real and os.path.isfile(real):
                    z.write(real, posixpath.join(PLATES, "%d.png" % int(idx)))
            except (OSError, TypeError, ValueError):
                continue
        # ...and whatever else is in the carried folders that nothing names -
        # `input/tiles/`, the slices a webtoon arrived as, being the one that
        # matters. A page already taken above is not written twice.
        for folder in CARRIED:
            d = os.path.join(root, folder)
            if not os.path.isdir(d):
                continue
            for dirpath, _dirs, files in os.walk(d):
                for fn in sorted(files):
                    full = os.path.join(dirpath, fn)
                    inside = os.path.relpath(full, d).replace("\\", "/")
                    at = posixpath.join(folder, inside)
                    if at in written:
                        continue
                    z.write(full, at)
                    written.add(at)
    return buf.getvalue()


def looks_like_bundle(data: bytes) -> bool:
    """Is this a `.tctp`? Asked of the BYTES, not of the filename.

    A file is what is in it. Somebody renaming a zip of pages to `.tctp` and
    watching it wipe the chapter they had open is not a mistake worth making
    possible.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            # BOTH. A zip carrying a manifest and no state is not a project
            # anybody can open, and finding that out in `read` means finding
            # it out after the chapter that was open has been cleared away.
            if MANIFEST not in names or STATE not in names:
                return False
            man = json.loads(z.read(MANIFEST) or b"{}")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return False
    return isinstance(man, dict) and bool(man.get("mangatct"))


def read(data: bytes, root: str) -> dict:
    """Unpack a `.tctp` into `root` and return the state to load.

    Everything the bundle carries is cleared first - a chapter opened over
    another must not end up with half of each - and the two caches go with it,
    because a plate cached for the last chapter is a plate for a page that is
    no longer here. Nothing OUTSIDE those folders is touched.

    Raises ValueError if it is not a bundle, before anything is deleted.
    """
    if not looks_like_bundle(data):
        raise ValueError("that file is not a MangaTCT project")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        state = json.loads(z.read(STATE))
        os.makedirs(root, exist_ok=True)
        for folder in CARRIED + (PLATES, "plate_cache", "ai_clean_cache"):
            shutil.rmtree(os.path.join(root, folder), ignore_errors=True)
        for info in z.infolist():
            if info.is_dir():
                continue
            top = info.filename.replace("\\", "/").split("/")[0]
            if top not in CARRIED and top != PLATES:
                continue                     # the manifest and the state
            dest = _abs(info.filename, root)
            if not dest:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        state = map_fonts(state, lambda ref: _install_font(z, ref))
    return state_from_bundle(state, root)


def carried_plates(root: str) -> dict:
    """`{page index: the plate the bundle carried}`, waiting to be re-keyed.

    Read out of `<root>/plates`, where `read` puts them. The caller moves
    each one into the plate cache under the name THIS machine's stamp gives
    it and then calls `forget_plates`; see `editor._adopt` and `PLATES`.
    """
    d = os.path.join(root, PLATES)
    out = {}
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for fn in names:
        stem, ext = os.path.splitext(fn)
        if ext.lower() != ".png" or not stem.isdigit():
            continue
        out[int(stem)] = os.path.join(d, fn)
    return out


def forget_plates(root: str) -> None:
    """Drop the staging folder once its plates have been taken in."""
    shutil.rmtree(os.path.join(root, PLATES), ignore_errors=True)


def _install_font(z: zipfile.ZipFile, ref: str) -> str:
    """Put a carried face where this machine keeps faces, and say where.

    Into `~/.mangatl/fonts` rather than the project folder, because that is
    where the app looks and because an uploaded face is meant to outlive the
    chapter it arrived with - open a bundle from somebody else and their
    typesetting font is now yours to use on the next one.

    A face already installed under that name is NOT overwritten. If it is the
    same file there is nothing to do, and if it is a different one then two
    people have two faces called `typesetting.ttf`, and quietly replacing the
    one already on this machine would re-typeset every other chapter that uses
    it. The newcomer is installed beside it under a name of its own.
    """
    name = posixpath.basename(str(ref).replace("\\", "/"))
    inside = posixpath.join(FONTS, name)
    try:
        data = z.read(inside)
    except KeyError:
        return ref                      # nothing carried under that name
    from .userdata import fonts_dir
    d = fonts_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return ref
    stem, ext = os.path.splitext(name)
    dest, n = os.path.join(d, name), 2
    while os.path.exists(dest):
        try:
            with open(dest, "rb") as fh:
                if fh.read() == data:
                    return dest         # already have exactly this face
        except OSError:
            return ref
        dest = os.path.join(d, f"{stem}-{n}{ext}")
        n += 1
    try:
        with open(dest, "wb") as fh:
            fh.write(data)
    except OSError:
        return ref
    return dest
