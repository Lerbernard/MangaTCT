"""Local editor server. Stdlib only — this is a desktop tool, not a service.

    python -m mangatl.editor --input chapter/ --output out/

Opens http://127.0.0.1:8765 . Detection runs over the folder in the background;
you correct the boxes, run OCR and translation, edit the English, and export a
folder of typeset pages.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from collections import OrderedDict
import mimetypes
import os
import posixpath
import re
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from . import inpaint as inpaint_mod
from . import userdata
from . import render as render_mod
from . import typeset as typeset_mod
from .detect import classical
from .interactive import region_from_box
from .order import assign_order
from . import kinds as _kinds
from . import project as project_mod
from .project import (KIND_GROUPS, Project, read_sfx_axis, region_from_record,
                      region_record, token_state)
from .score import text_likeness
from .models import Page

STATIC = os.path.join(os.path.dirname(__file__), "static")
PROJECT: Project | None = None


# --------------------------------------------------------------------- helpers

def _typeset_cfg(p: Project) -> typeset_mod.TypesetConfig:
    s = p.settings
    # A sub-type's face travels on its own record — it is part of what that
    # sub-type is — so it is folded in here rather than relied on having been
    # copied into `fonts` by the browser. The browser does copy it, and a
    # setting that only works when the page that wrote it is still open is
    # not a setting.
    fonts = {k: v for k, v in (s.get("fonts") or {}).items() if v}
    for sub in (s.get("custom_kinds") or []):
        if isinstance(sub, dict) and sub.get("key") and sub.get("font"):
            fonts.setdefault(sub["key"], sub["font"])
    cfg = typeset_mod.TypesetConfig(
        font_path=s.get("font") or "",
        fonts=fonts,
        uppercase=bool(s.get("uppercase")),
        # Off unless the project says otherwise: the face you picked is the
        # face the words are set in. See `TypesetConfig.substitutes`.
        substitutes=bool(s.get("substitutes")),
        min_font=int(s.get("min_font", 12)),
        max_font=int(s.get("max_font", 34)),
    )
    if not cfg.font_path:
        cfg.font_path = typeset_mod.default_font_path()
    return cfg


_render_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_preview_lock = threading.Lock()
# One page's JPEG is well under a megabyte, and holding a whole chapter of
# them is what makes flicking back and forth instant instead of a wait per
# page. Anything past this stays fast anyway — the plate it is built from is
# on disk (see _plate_disk_path).
RENDER_CACHE_MAX = 96

# Bumped whenever something invalidates the rendered pages for a reason the
# stamp below cannot see. It rides along in the key the browser is given, so
# clearing the server's cache also stops the browser reusing its own copy.
# It starts from the clock rather than zero so that keys never outlive the run
# that made them: a restart costs one re-fetch per page off a warm server, and
# in exchange nothing the browser kept from last time can ever be shown.
_render_epoch = int(time.time())


def _invalidate_renders() -> None:
    global _render_epoch
    _render_epoch += 1
    _render_cache.clear()


def _touch(cache: OrderedDict, key) -> None:
    """Mark an entry as the most recently used one.

    Another thread trimming the same cache can drop the key between the lookup
    and the move — the entry going missing is exactly what a cache is allowed
    to do, so it is not worth an exception reaching a page view.
    """
    try:
        cache.move_to_end(key)
    except KeyError:
        pass


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _render_stamp(p: Project, i: int, mode: str) -> tuple:
    """Everything that can change what a rendered page looks like.

    Cleaning and typesetting a page takes over a second, and it was being redone
    on every single view — so paging back and forth meant waiting each time.
    """
    st = p.pages[i]
    s = p.settings
    # Only the inputs. `layout` is computed output that rendering writes back,
    # so including it would change the key every time and never hit.
    # The ACTIVE boxes: a hidden group is not drawn on any of the three
    # views, so putting one away has to change the key or the old picture
    # stays on screen.
    inputs = [{k: v for k, v in (r or {}).items() if k != "layout"}
              for r in st.active]
    cc = getattr(st, "custom_clean", "") or ""
    ov = getattr(st, "paint_overlay", "") or ""
    ovr = getattr(st, "paint_over", "") or ""
    base = (i, mode, st.name, st.width, st.height,
            _page_fingerprint(p, i), cc, _mtime(cc),
            ov, _mtime(ov), ovr, _mtime(ovr),
            json.dumps(inputs, sort_keys=True, default=str),
            s.get("ai_clean") or "off", s.get("clean_url") or "")
    if mode != "typeset":
        # The scan and the cleaned plate carry no text, so the typesetting
        # settings cannot change what they look like. Including them meant a
        # change of font threw away the cleaned page and made it again from
        # scratch — a call out to the hosted cleaner, seconds of blank canvas —
        # to arrive at the identical image. The editor only ever asks for those
        # two, which is why picking a font now costs nothing.
        return base
    return base + (
        s.get("font"), json.dumps(s.get("fonts") or {}, sort_keys=True),
        s.get("min_font"), s.get("max_font"), s.get("uppercase"),
        # ...and whether the typesetter may stand something else in, which
        # changes what is drawn as surely as the face does.
        s.get("substitutes"))


def _render_key(p: Project, i: int) -> str:
    """A short token the browser can hang on the image URL.

    The URL used to end in the current clock, which meant every single page
    view re-downloaded the image even when nothing about it had changed. This
    changes exactly when the page's appearance can have changed, so going back
    to a page you have already seen costs nothing at all.
    """
    h = hashlib.sha1(repr(_render_stamp(p, i, "")).encode("utf-8"))
    return f"{_render_epoch}-{h.hexdigest()[:16]}"


_fingerprints: "OrderedDict[tuple, str]" = OrderedDict()


def _page_fingerprint(p: Project, i: int) -> str:
    """What is actually IN this page's file.

    Everything that names a picture — the URL the browser caches under, the
    rendered-page cache, the cleaned-plate cache — used to be built out of the
    page's NAME and its width and height. For one chapter that is enough. For
    the next one it is not:

        lee: *"wheni uploaded a new chnater the old chapter is showing up as
        teh new chnapeter this shoud neveer happen"*

    Chapters are numbered the same way every time — `001.png`, `002.png` — and
    scanned at the same size, so page 1 of the new chapter had the same name,
    the same width and the same height as page 1 of the old one. Identical key,
    and the browser answered from its own cache with a picture it had been told
    was immutable. It was: it was just a picture of a different chapter.

    So the key is the file's contents. Two different pictures cannot share one,
    whatever they are called.

    Hashing a few megabytes is a few milliseconds and only happens once per
    file: the answer is kept against the file's size and modification time,
    which is what changes when the file does.
    """
    st = p.pages[i]
    try:
        info = os.stat(st.path)
        ident = (st.path, info.st_size, info.st_mtime_ns)
    except OSError:
        # No file to read — a project state pointing at pages that have moved.
        # The name is all there is, and it is better than raising here.
        return hashlib.sha1(
            f"{st.name}|{st.width}x{st.height}".encode("utf-8")).hexdigest()[:16]
    got = _fingerprints.get(ident)
    if got:
        _touch(_fingerprints, ident)
        return got
    h = hashlib.sha1()
    try:
        with open(st.path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        h.update(f"{st.name}|{st.width}x{st.height}".encode("utf-8"))
    key = h.hexdigest()[:16]
    _fingerprints[ident] = key
    while len(_fingerprints) > 600:
        _fingerprints.popitem(last=False)
    return key


def _scan_key(p: Project, i: int) -> str:
    """A token for the ORIGINAL scan of a page.

    The scan is the one thing in a project that editing cannot alter, so this
    is the page's own contents and nothing that happens to it afterwards.
    """
    return _page_fingerprint(p, i)


_plate_cache: "OrderedDict[tuple, np.ndarray]" = OrderedDict()


def _plate_stamp(p: Project, i: int) -> tuple:
    """Identity of the fully-cleaned plate — geometry, not eye toggles."""
    geo = tuple((r.get("id"), tuple(r.get("bbox") or ()), r.get("kind"))
                for r in p.pages[i].regions)
    # The cleaning method is part of the plate's identity — switching between
    # local and AI must rebuild it. So is the TOKEN, by its fingerprint: a
    # wrong token and a right one produce completely different pages, and
    # without this, pasting the real token in left every plate built during the
    # 401s sitting in the cache, so nothing changed and nothing was re-sent.
    tok = p.settings.get("clean_token") or ""
    ai = (p.settings.get("ai_clean") or "off", p.settings.get("clean_url") or "",
          hashlib.sha1(tok.encode("utf-8")).hexdigest()[:12] if tok else "",
          # ...and the CLEANER'S OWN VERSION. A plate is cached on disk and
          # reused forever, and none of the keys above change when the cleaning
          # code does — so every improvement shipped invisible, the old plate
          # answering for the new build. lee: *"nothing vhanged"*. Bump
          # inpaint.ALGO and every plate made by the old code retires itself.
          getattr(inpaint_mod, "ALGO", ""))
    return (i, p.pages[i].name, _page_fingerprint(p, i),
            getattr(p.pages[i], "custom_clean", "") or "", geo, ai)


def _page_file_stem(p: Project, i: int) -> str:
    """A per-page file name tied to the page itself, not its position.

    Naming these files by index meant that after a reorder, saving page 1's
    strokes overwrote the file page 3's record still pointed at.
    """
    base = os.path.splitext(p.pages[i].name)[0]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base) or f"{i:03d}"


def _ai_clean_cache_dir(p: Project) -> str:
    d = os.path.join(p.output_dir, "ai_clean_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _plate_disk_path(p: Project, i: int) -> str:
    """Where a finished clean plate is kept between runs.

    Only six plates fit in memory and none of them survived closing the app,
    so the first visit to every page after a restart re-ran the whole
    inpainter — the wait the person kept hitting when they moved to a page for
    the first time. The name is the plate's own identity, so a plate is only
    ever reused for exactly the page, boxes and cleaning method that produced
    it, and changing any of those simply misses and rebuilds.
    """
    d = os.path.join(p.output_dir, "plate_cache")
    os.makedirs(d, exist_ok=True)
    key = hashlib.sha1(repr(_plate_stamp(p, i)).encode("utf-8")).hexdigest()
    return os.path.join(d, key + ".png")


def _prune_cache_dir(d: str, keep: int) -> None:
    """Keep the newest `keep` files and drop the rest, quietly."""
    try:
        files = [os.path.join(d, f) for f in os.listdir(d)]
        files = [f for f in files if os.path.isfile(f)]
        if len(files) <= keep:
            return
        files.sort(key=_mtime, reverse=True)
        for f in files[keep:]:
            try:
                os.remove(f)
            except OSError:
                pass
    except OSError:
        pass


# What the hosted cleaner last said when it would not clean. lee ran a Clean,
# watched the pages come back smeared, and was told nothing: every failure was
# caught here, remembered in a variable nothing read, and replaced with a Telea
# fill that looks like a bad clean rather than like no clean at all. The counter
# is what makes the sentence honest — "17 spots" is the difference between a
# flaky call and an endpoint that is refusing everything.
#
# `used` counts the regions the model actually cleaned (a fresh answer or a
# cached one). Zero of those and zero failures means nothing was ever sent —
# which is its own thing worth saying, because on "AI for hard areas" a flat
# white bubble never reaches the model at all, so the endpoint sits idle and the
# page looks exactly as it did before.
_AI_CLEAN_FAIL = {"n": 0, "msg": "", "url": "", "used": 0, "cached": 0}


def _clean_error_text(e: Exception) -> str:
    """The failure in words the person can act on.

    `HTTPError 401` is the one that matters: the token in Settings is not the
    token the deployed function compares against, and no amount of re-running
    will change that. Everything else keeps its type and message.
    """
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 401:
            return "the cleaner refused the token (401)"
        if e.code == 404:
            return "there is nothing at that cleaner address (404)"
        if e.code in (429, 503):
            return f"the cleaner was too busy to answer ({e.code})"
        return f"the cleaner answered {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"the cleaner could not be reached ({e.reason})"
    return f"{type(e).__name__}: {e}"


def clean_warning(p: Project) -> str:
    """One sentence for the bar, or "" while the cleaner is behaving.

    Reads the failure AND the setting that most often causes it, because "the
    cleaner refused the token" is only half an instruction if the token being
    sent is still the example out of the deploy file.
    """
    f = _AI_CLEAN_FAIL
    if not f["n"]:
        return ""
    n = f["n"]
    where = f"{n} spot{'' if n == 1 else 's'}"
    msg = (f"AI cleaning did not run — {f['msg']}. {where} "
           f"{'was' if n == 1 else 'were'} filled in with the plain local "
           f"method instead.")
    tok = p.settings.get("clean_token") or ""
    if not tok:
        msg += " No cleaner token is saved (Settings ▸ Page cleaning)."
    elif _token_is_placeholder(tok):
        msg += (" The saved token is still the CHANGE-ME example from the"
                " deploy file — paste the real one into Settings ▸ Page cleaning.")
    return msg


def _token_state(tok: str | None) -> str:
    """"", "set" or "placeholder" — see project.token_state, which is where the
    one definition lives so the settings screen and this warning agree."""
    return token_state(tok)


def _token_is_placeholder(tok: str) -> bool:
    """The example token that ships in the comment of every *_clean_modal.py.

    Saved, non-empty, and rejected by the endpoint every single time — which is
    exactly the state that read as "(saved)" in the settings field.
    """
    return _token_state(tok) == "placeholder"


def clear_clean_warning() -> None:
    _AI_CLEAN_FAIL.update(n=0, msg="", url="", used=0, cached=0)
    _CLEAN_TALLY.clear()


# How the boxes cleaned in this run were cleaned. Same reason as the warning
# above: every question so far about whether the model was doing the hard
# regions has been settled by looking at the page and guessing.
_CLEAN_TALLY: dict = {}


def _tally_clean(stats: dict) -> None:
    for k, v in (stats or {}).items():
        _CLEAN_TALLY[k] = _CLEAN_TALLY.get(k, 0) + int(v)


def clean_report(p: Project) -> str:
    """"18 boxes: 12 filled flat, 6 by the AI." — or "" if nothing was cleaned.

    The words are the person's, not the code's: `flat fill` is a pale bubble
    filled with its own colour, `neural` is the hosted model, `fell back` is a
    region the model was asked for and did not deliver.
    """
    t = {k: v for k, v in _CLEAN_TALLY.items() if v}
    built = t.pop("built", 0)
    own = t.pop("own", 0)
    # A page built in this run is materialised again straight afterwards (the
    # background warm-up), and that second visit reuses the plate it just made.
    # Only pages that were NEVER built in this run were genuinely reused.
    reused = max(0, t.pop("reused", 0) - built)
    # "core only" is not a way of cleaning a box, it is something that ALSO
    # happened to a box cleaned some other way — the halo could not be trusted
    # there, so only the letter strokes went. Counting it as a route inflated
    # the total and listed it beside the routes as though it were one: lee's
    # page reported *"Cleaned 13 boxes: 6 filled flat, 4 cleaned by the AI, 3
    # core only"* when ten boxes were cleaned and three of those ten were done
    # strokes-only.
    core = t.pop("core only", 0)
    total = sum(v for k, v in t.items() if k not in ("skipped", "kept"))
    yours = (f" {own} page{'' if own == 1 else 's'} "
             f"{'uses' if own == 1 else 'use'} your own cleaned file and "
             f"{'was' if own == 1 else 'were'} left alone." if own else "")
    if not total:
        if reused:
            return (f"{reused} page{'' if reused == 1 else 's'} "
                    f"{'was' if reused == 1 else 'were'} already cleaned, so "
                    f"the finished plate was reused." + yours)
        return yours.strip()
    NAMES = {"flat fill": "filled flat (plain bubbles)",
             "pattern copy": "copied from the surrounding tone",
             "neural": "cleaned by the AI",
             "telea": "cleaned locally",
             "fell back": "left to the local fill because the AI would not run"}
    bits = [f"{v} {NAMES.get(k, k)}" for k, v in sorted(
        t.items(), key=lambda kv: -kv[1]) if k not in ("skipped", "kept")]
    msg = f"Cleaned {total} box{'' if total == 1 else 'es'}: " + ", ".join(bits) + "."
    if core:
        msg += (f" {core} of {'them' if core > 1 else 'those'} had only the "
                f"letter strokes erased — the typesetting there was hard to tell "
                f"from the artwork, so the halo round it was left alone.")
    if t.get("skipped"):
        msg += (f" {t['skipped']} box{'' if t['skipped'] == 1 else 'es'} had "
                f"nothing recorded to erase.")
    if t.get("kept"):
        # The commonest reason for "why is this text still there" that is not a
        # bug at all: the eye in Cleaning per bubble is closed on that box.
        n = t["kept"]
        msg += (f" {n} box{'' if n == 1 else 'es'} "
                f"{'is' if n == 1 else 'are'} set to KEEP the original text "
                f"(the eye in Cleaning per bubble).")
    if reused:
        msg += (f" {reused} page{'' if reused == 1 else 's'} "
                f"{'was' if reused == 1 else 'were'} already cleaned and reused.")
    msg += yours
    # Which build did this. Three rounds of "nothing changed" went by without a
    # way to tell a fix that did not work from a fix that was not running.
    msg += f" [cleaner {getattr(inpaint_mod, 'ALGO', '?')}]"
    c = _AI_CLEAN_FAIL.get("cached") or 0
    if c and t.get("neural"):
        msg += (f" {c} of the AI's answers came back from its cache rather than"
                f" the endpoint — same picture, no second charge.")
    return msg


def clean_note(p: Project) -> str:
    """What to say when AI cleaning was ON and the model was never asked.

    "AI for hard areas" hands the model only what the local flat fill cannot do
    — tone, gradients, art. A page of plain white balloons therefore sends
    nothing, the endpoint stays idle, and the page looks untouched. That is
    correct behaviour and completely indistinguishable, from the outside, from a
    cleaner that is broken.
    """
    f = _AI_CLEAN_FAIL
    if f["n"] or f["used"]:
        return ""
    if not _CLEAN_TALLY.get("built"):
        # Nothing was rebuilt: every page already had its plate, so of course
        # nothing was sent. Reporting that as "the AI did not run" is how a
        # working cleaner came to look broken the moment it started working —
        # the second press of Clean reuses the plates the first one made.
        return ""
    mode = (p.settings.get("ai_clean") or "off").strip()
    if mode not in ("hard", "all") or not (p.settings.get("clean_url") or "").strip():
        return ""
    if mode == "hard":
        return ("AI cleaning was on but nothing was sent to it — every region "
                "was a flat bubble, which the local fill does better. Choose "
                "\u201cAI for the whole page\u201d if you want the model on all "
                "of them.")
    return ("AI cleaning was on but nothing was sent to it — this page had "
            "nothing left to clean.")


def _deploy_dirs() -> list[str]:
    """Where the `*_clean_modal.py` scripts are looked for: beside the code, one
    level up, and wherever the editor was started. Its own function so a test can
    point it somewhere with nothing real in it."""
    here = os.path.dirname(os.path.abspath(__file__))
    return [here, os.path.dirname(here), os.getcwd()]


def _deploy_files() -> list[dict]:
    """What the local `*_clean_modal.py` deploy scripts say, without quoting the
    secret in them.

    Each entry: the file name, the Modal app it deploys, and the sha1 of its
    `CLEAN_TOKEN` — enough to answer "is the token I saved the token that file
    bakes in?" with a boolean, which is the question that matters and the only
    one that can be answered without printing either value.
    """
    import glob as _glob
    seen, out = set(), []
    for d in _deploy_dirs():
        for fp in sorted(_glob.glob(os.path.join(d, "*_clean_modal.py"))):
            name = os.path.basename(fp)
            if name in seen:
                continue
            seen.add(name)
            try:
                src = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = re.search(r'^CLEAN_TOKEN\s*=\s*["\']([^"\']+)["\']', src, re.M)
            if not m:
                continue
            app = re.search(r'modal\.App\(\s*["\']([^"\']+)["\']', src)
            model = re.search(r'^MODEL\s*=\s*["\']([^"\']+)["\']', src, re.M)
            app_name = app.group(1) if app else ""
            # `modal.App("mangatl-clean-" + MODEL)` — the deployed name is the
            # literal plus the model word, and the URL is built from it.
            if app and re.search(r'modal\.App\([^)]*\+\s*MODEL', src) and model:
                app_name += model.group(1)
            out.append({"file": name, "app": app_name,
                        "sha": hashlib.sha1(
                            m.group(1).encode("utf-8")).hexdigest()})
    return out


def clean_selftest(p: Project) -> dict:
    """Ask the configured cleaner one tiny question and report what came back.

    This exists because "the token is the same in the app and in the code" and
    "the endpoint answers 401" were both true at the same time, and nothing in
    the editor could tell the two possible causes apart. It compares the saved
    token against each local deploy file by hash, then makes one real call with
    the cache bypassed, and says which of the two it is:

    * saved token does NOT match the file → the wrong string is in Settings;
    * saved token DOES match the file, and the endpoint still refuses → the
      DEPLOYED image was built from an older copy of that file. Redeploy.

    Nothing here prints a token; only lengths, booleans and app names.
    """
    import tempfile
    s = p.settings
    url = (s.get("clean_url") or "").strip()
    tok = (s.get("clean_token") or "").strip()
    files = _deploy_files()
    mine = hashlib.sha1(tok.encode("utf-8")).hexdigest() if tok else ""
    for f in files:
        f["same_token"] = bool(mine) and f["sha"] == mine
        f["url_matches"] = bool(f["app"]) and f["app"] in url
        f.pop("sha", None)
    # "mangatl-clean" is a substring of "mangatl-clean-lama", so plain
    # containment says the manga app is deployed at the lama app's address. Only
    # the longest name that appears in the URL is the one it names.
    hit = max((len(f["app"]) for f in files if f["url_matches"]), default=0)
    for f in files:
        f["url_matches"] = f["url_matches"] and len(f["app"]) == hit
    res = {"url": url, "mode": (s.get("ai_clean") or "off").strip(),
           "token": {"len": len(tok), "state": token_state(tok)},
           "files": files, "ok": False, "error": "", "hint": ""}
    if not url:
        res["error"] = "No cleaner address is saved."
        res["hint"] = "Paste the endpoint URL your deploy printed."
        return res
    if not tok:
        res["error"] = "No cleaner token is saved."
        res["hint"] = "Paste CLEAN_TOKEN from your deploy file."
        return res

    img = np.full((64, 64, 3), 235, np.uint8)
    cv2.rectangle(img, (20, 20), (44, 44), (30, 30, 30), -1)
    mask = np.zeros((64, 64), np.uint8)
    cv2.rectangle(mask, (18, 18), (46, 46), 255, -1)
    before = _AI_CLEAN_FAIL["n"]
    with tempfile.TemporaryDirectory() as tmp:      # never the real cache
        try:
            _ai_clean_call(url, tok, tmp, img, mask, strict=True)
            res["ok"] = True
        except Exception as e:
            res["error"] = _clean_error_text(e)
        finally:
            # a self-test is not a run; it must not leave a warning behind
            _AI_CLEAN_FAIL["n"] = before
    named = [f for f in files if f["url_matches"]] or files
    match = [f for f in named if f["same_token"]]
    if res["ok"]:
        res["hint"] = "The cleaner answered. AI cleaning will run."
    elif "401" in res["error"]:
        if match:
            res["hint"] = (
                f"The saved token matches {match[0]['file']}, so the string is "
                f"right and the DEPLOYED copy is out of date — it still checks "
                f"the token it was built with. Run "
                f"`python -m modal deploy {match[0]['file']}` and test again.")
        elif named:
            res["hint"] = (
                f"The saved token is not the one in {named[0]['file']} — copy "
                f"CLEAN_TOKEN from that file, with no quotes or trailing "
                f"spaces, and save again.")
        else:
            res["hint"] = ("The endpoint refused the token. Copy CLEAN_TOKEN "
                           "out of the deploy script for that app.")
    elif res["error"]:
        res["hint"] = "Check the address, then that the app is deployed."
    if res["ok"] and named and not any(f["url_matches"] for f in files):
        res["hint"] += " (The address does not look like any of your apps.)"
    return res


def _ai_clean_call(url: str, token: str, cache_dir: str,
                   img: np.ndarray, mask: np.ndarray,
                   strict: bool = False) -> np.ndarray:
    """POST the page + text mask to the hosted manga cleaner, return the
    cleaned image. The result is CACHED on disk by the exact (image, mask)
    content, so revisiting or re-rendering a page never calls the API again —
    it only runs when the boxes (and therefore the mask) actually change. On
    any failure it falls back to a local inpaint so a run never breaks."""
    import hashlib
    # The token is in the key for the same reason it is in the plate stamp: the
    # answer to this exact (image, mask, url) is different when the token is
    # accepted than when it is refused.
    key = hashlib.sha1(img.tobytes() + mask.tobytes()
                       + url.encode("utf-8")
                       + token.encode("utf-8")).hexdigest()
    fp = os.path.join(cache_dir, key + ".png")
    if os.path.exists(fp):
        cached = cv2.imread(fp)
        if cached is not None and cached.shape[:2] == img.shape[:2]:
            _AI_CLEAN_FAIL["used"] += 1     # the model's answer, from the cache
            _AI_CLEAN_FAIL["cached"] += 1
            return cached

    try:
        import base64
        import json as _json
        import urllib.request
        body = _json.dumps({
            "token": token,
            "image": base64.b64encode(cv2.imencode(".png", img)[1]).decode(),
            "mask": base64.b64encode(cv2.imencode(".png", mask)[1]).decode(),
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        # A page whose cleaner hangs holds that page's build for this long,
        # and anything waiting on the same page waits with it. Three minutes
        # was long enough that it read as the app being dead.
        with urllib.request.urlopen(req, timeout=CLEAN_TIMEOUT) as resp:
            data = resp.read()
        out = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if out is None or out.shape[:2] != img.shape[:2]:
            raise ValueError("cleaner returned an unusable image")
        cv2.imwrite(fp, out)
        clear_clean_warning()          # it is working again; drop the old news
        _AI_CLEAN_FAIL["used"] += 1
        return out
    except Exception as e:
        traceback.print_exc()
        # never break a run over the network: fall back to the local fill
        globals()["_LAST_AI_CLEAN_ERROR"] = f"{type(e).__name__}: {e}"
        _AI_CLEAN_FAIL["n"] += 1
        _AI_CLEAN_FAIL["msg"] = _clean_error_text(e)
        _AI_CLEAN_FAIL["url"] = url
        if strict:
            # ...unless the caller has its own, better fallback and needs to
            # know. A whole-page run must not stop for a flaky endpoint; a
            # single healed spot has a local method that is BETTER than Telea,
            # so quietly handing it Telea instead would be a downgrade.
            raise
        return cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)


def _make_cleaner(p: Project, strict: bool = False):
    """Returns (neural_fn or None, neural_all). Off / no URL -> (None, False).

    `strict` makes the returned callable RAISE when the endpoint fails rather
    than substituting a local Telea fill. See `_ai_clean_call`.
    """
    s = p.settings
    mode = (s.get("ai_clean") or "off").strip()
    url = (s.get("clean_url") or "").strip()
    # Stripped here as well as on save: a project.json written before the save
    # started stripping still has the pasted whitespace in it, and a 401 caused
    # by a trailing newline is indistinguishable from a wrong token.
    token = (s.get("clean_token") or "").strip()
    if mode not in ("hard", "all") or not url:
        return None, False
    cache_dir = _ai_clean_cache_dir(p)

    def neural(img, mask):
        return _ai_clean_call(url, token, cache_dir, img, mask, strict)

    return neural, (mode == "all")


def own_plate_path(p: Project, i: int) -> str:
    """The cleaned file the person uploaded for this page, or "".

    One definition, because four different things now have to agree about it:
    building the page, the Clean step, the background warm-up, and what the
    panel says. A path that was recorded and has since been deleted is not a
    plate, so the check is `exists`, not truthiness.
    """
    cc = getattr(p.pages[i], "custom_clean", "") or ""
    return cc if cc and os.path.exists(cc) else ""


def clean_page(p: Project, i: int, page, include_paint: bool = True) -> None:
    """Produce page.clean_plate — the person's own plate if they gave one.

    A page with its own cleaned file is not cleaned at all: the file IS the
    plate, always, and nothing is inpainted, sent to the hosted cleaner, or
    pasted back over it. lee: *"if i uploade my own file it shoud exclude that
    page from cleaing and shoud alway use the uploadd page as a cleneed page"*.
    That includes the per-bubble eyes — an eye says which bubbles the cleaner
    should erase, and on this page the cleaner never runs.

    Only the page it was uploaded for: everything else keeps the automatic
    cleaning.

    The expensive inpainting runs once with EVERY bubble cleaned and is
    cached; an eye toggle then just pastes the original pixels back over
    that bubble (or removes them) — instant, instead of re-inpainting the
    whole page for each click.
    """
    cc = own_plate_path(p, i)
    custom = None
    if cc:
        img = cv2.imread(cc)
        if img is not None:
            if img.shape[:2] != page.image.shape[:2]:
                img = cv2.resize(img, (page.image.shape[1], page.image.shape[0]),
                                 interpolation=cv2.INTER_LANCZOS4)
            custom = img
    if custom is not None:
        page.clean_plate = custom
        _composite_paint(p, i, page, include_paint)
        return

    key = _plate_stamp(p, i)
    full = _plate_cache.get(key)
    if full is not None:
        # Already built, in memory. Nothing is sent to the model for this page —
        # which is the whole point of the cache, and must not be reported as the
        # model having failed to run.
        _tally_clean({"reused": 1})
    if full is None:
        fp = _plate_disk_path(p, i)
        if os.path.exists(fp):
            got = cv2.imread(fp)
            if got is not None and got.shape[:2] == page.image.shape[:2]:
                full = got
                os.utime(fp, None)          # touch: it is still in use
                _tally_clean({"reused": 1})
        if full is None:
            saved = [(r, bool(getattr(r, "skip_clean", False)))
                     for r in page.regions]
            before = _AI_CLEAN_FAIL["n"]
            try:
                for r, _ in saved:
                    r.skip_clean = False
                # strict: a refusal has to REACH the inpainter, so it can
                # repair that one region locally at the right size. Non-strict,
                # `_ai_clean_call` answered with a Telea fill over the model's
                # own generous mask, and the page came back smeared with no
                # way for anything downstream to know it had happened.
                neural, neural_all = _make_cleaner(p, strict=True)
                inpaint_mod.inpaint_page(page, neural=neural,
                                         neural_all=neural_all)
            finally:
                for r, v in saved:
                    r.skip_clean = v
            _tally_clean(getattr(page, "clean_stats", None) or {})
            _tally_clean({"built": 1})     # a plate actually made, here, now
            # ...and the one place the cleaning fee belongs, for exactly that
            # reason. lee: *"the clenning fee shud be a flat fee per page"*. A
            # plate that came out of the cache never reaches this line, nor
            # does a page with a cleaned file of its own, and neither of them
            # cost anything to produce — so neither is charged for. Cleaning
            # reached through Export, Typeset or the background page-builder is
            # charged the same as pressing Clean, because it is the same work.
            #
            # The fee is for the HOSTED cleaner, so it is charged when the
            # hosted cleaner actually did some of this page. A chapter filled
            # flat on this machine is somebody's own CPU and is free, exactly
            # as Typeset and Export are — charging a fee for it would be
            # charging for nothing, and it would be charged silently, because
            # the page-builder cleans pages nobody asked it to.
            try:
                from . import coins
                if int((getattr(page, "clean_stats", None) or {}).get(
                        "neural", 0) or 0) > 0:
                    coins.flat(coins.quote_page("clean"), "clean",
                               getattr(p.pages[i], "name", ""))
            except Exception:
                traceback.print_exc()
            full = page.clean_plate
            # A plate built while the cleaner was refusing is NOT this page's
            # plate — it is the local fallback wearing its name. Caching it is
            # how "click Clean again" came to do nothing at all: the second
            # press found the smeared plate on disk, reused it in a few
            # milliseconds, and never called the endpoint, so fixing the token
            # changed nothing and Modal showed no activity. Leave it uncached
            # and the next press actually retries.
            if _AI_CLEAN_FAIL["n"] > before:
                return _finish_plate(p, i, page, full, include_paint)
            try:
                # Level 1: the plate is written once and read many times, and
                # squeezing it harder costs more than it ever saves back.
                cv2.imwrite(fp, full, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                _prune_cache_dir(os.path.dirname(fp), max(80, 3 * len(p.pages)))
            except Exception:
                pass                        # a cache that cannot write is fine
        _plate_cache[key] = full.copy()
        _touch(_plate_cache, key)
        while len(_plate_cache) > 6:
            _plate_cache.popitem(last=False)

    return _finish_plate(p, i, page, full, include_paint)


def _finish_plate(p: Project, i: int, page, full, include_paint: bool) -> None:
    """Put back the bubbles whose eye is closed, then the touch-up strokes.

    Split out of `clean_page` so a plate that must not be cached can still take
    exactly the same last two steps as one that is.
    """
    plate = full.copy()
    H, W = plate.shape[:2]
    PADB = 16                       # covers the dilation around the glyphs
    keep = [r for r in page.regions if getattr(r, "skip_clean", False)]
    if keep:
        # What the OTHER boxes had erased. Restoring one bubble's original text
        # used to paste back a RECTANGLE — its box plus 16 pixels — and boxes on
        # a page touch and overlap all the time, so closing the eye on one
        # brought its neighbour's Japanese back with it. lee: *"wheni lcick the
        # yey on region 3 region 2 cleans, and this happnes with other boxes"*.
        #
        # A region's own writing is a mask, not a rectangle. Paste back exactly
        # that, and never over a pixel another box is having cleaned.
        others = np.zeros((H, W), np.uint8)
        for r in page.regions:
            if getattr(r, "skip_clean", False) or r.text_mask is None:
                continue
            m = (r.text_mask > 0).astype(np.uint8)
            area = r.place_mask()
            if area is not None:
                m[~(area > 0)] = 0
            others |= cv2.dilate(m, np.ones((PADB + 1, PADB + 1), np.uint8))

        for r in keep:
            m = None
            if r.text_mask is not None and (r.text_mask > 0).any():
                m = (r.text_mask > 0).astype(np.uint8)
                area = r.place_mask()
                if area is not None:
                    m[~(area > 0)] = 0
                m = cv2.dilate(m, np.ones((PADB + 1, PADB + 1), np.uint8))
            if m is None or not m.any():
                # nothing was recorded for this box — fall back to its rectangle
                m = np.zeros((H, W), np.uint8)
                x, y, w, h = r.bbox
                m[max(0, y - PADB):min(H, y + h + PADB),
                  max(0, x - PADB):min(W, x + w + PADB)] = 1
            m[others > 0] = 0        # another box's clean is not ours to undo
            plate[m > 0] = page.image[m > 0]
    page.clean_plate = plate
    _composite_paint(p, i, page, include_paint)


def _composite_paint(p: Project, i: int, page, include_paint: bool) -> None:
    """Alpha-composite the touch-up overlay onto the plate.

    The editor's Cleaned view asks for the bare plate (it draws the editable
    strokes itself); the Translated view and the export get them baked in.
    """
    if not include_paint:
        return
    ov = getattr(p.pages[i], "paint_overlay", "") or ""
    if not ov or not os.path.exists(ov):
        return
    o = cv2.imread(ov, cv2.IMREAD_UNCHANGED)
    if o is None or o.ndim != 3 or o.shape[2] != 4             or o.shape[:2] != page.clean_plate.shape[:2]:
        return
    a = o[:, :, 3:4].astype(np.float32) / 255.0
    page.clean_plate = (page.clean_plate.astype(np.float32) * (1.0 - a)
                        + o[:, :, :3].astype(np.float32) * a).astype(np.uint8)


def _composite_over(p: Project, i: int, img):
    """Paint that sits ABOVE the typesetting, laid on after the text is drawn.

    The other overlay goes onto the plate before anything is typeset; this one
    is the last thing that happens to the page. Two bands is the whole model —
    a drawing is either under all the text or over all of it — which is what
    lee asked for when offered the choice against a free interleave.
    """
    ov = getattr(p.pages[i], "paint_over", "") or ""
    if not ov or not os.path.exists(ov):
        return img
    o = cv2.imread(ov, cv2.IMREAD_UNCHANGED)
    if o is None or o.ndim != 3 or o.shape[2] != 4 or o.shape[:2] != img.shape[:2]:
        return img
    a = o[:, :, 3:4].astype(np.float32) / 255.0
    return (img.astype(np.float32) * (1.0 - a)
            + o[:, :, :3].astype(np.float32) * a).astype(np.uint8)


# One lock PER PAGE, not one for the whole editor.
#
# Building a page materialises it, writes layouts back and mutates the shared
# project, so two builds of the SAME page must not overlap. Two builds of two
# DIFFERENT pages have nothing to say to each other — and a single global lock
# meant they queued anyway. That is not a nicety either: a page whose hosted
# clean is slow holds the lock for as long as the network takes, and every
# other request in the editor waits behind it. From the outside the whole app
# stops answering, the browser gives up on everything it had asked for, and the
# log fills with connections aborted mid-answer.
# lee: *"the page is stuck"*, with a hundred ConnectionAbortedErrors under it.
# How long to wait on the hosted cleaner for one page.
CLEAN_TIMEOUT = 75

_page_locks: "dict[int, threading.RLock]" = {}
_locks_lock = threading.Lock()


def _page_lock(i: int) -> "threading.RLock":
    with _locks_lock:
        lk = _page_locks.get(i)
        if lk is None:
            lk = _page_locks[i] = threading.RLock()
        return lk


def render_index(p: Project, i: int, mode: str = "original",
                 paint: bool = True) -> bytes:
    """Three views of a page.

    original  the scan as it came in
    clean     source text erased, nothing added — shows what the inpainter did
    typeset   the finished page
    """
    key = _render_stamp(p, i, mode) + (bool(paint),)
    hit = _render_cache.get(key)
    if hit is not None:
        _touch(_render_cache, key)
        return hit

    # Building a page materialises it, writes layouts back and mutates the
    # shared project. The server answers on threads and a background warm-up
    # walks the whole chapter, so two of those overlapping is a real
    # possibility now — one at a time, and the warm-up drops the lock between
    # pages so a person clicking never waits more than the page in flight.
    with _page_lock(i):
        hit = _render_cache.get(key)
        if hit is not None:
            _touch(_render_cache, key)
            return hit
        page = p.materialize(i)
        if mode == "original" or not page.regions:
            img = page.image
        else:
            clean_page(p, i, page, include_paint=(paint or mode != "clean"))
            if mode == "clean":
                img = page.clean_plate
            else:
                cfg = _typeset_cfg(p)
                typeset_mod.typeset_page(page, cfg)
                img = _composite_over(p, i, render_mod.render_page(page, cfg))
                p.commit(i, page)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        out = buf.tobytes() if ok else b""
        _render_cache[key] = out
        _touch(_render_cache, key)
        while len(_render_cache) > RENDER_CACHE_MAX:
            _render_cache.popitem(last=False)
    return out


_page_cache: dict = {}


def cached_page(p: Project, i: int):
    """Materialising rebuilds every mask, which is wasted work when the same
    page is being edited repeatedly. Cache it and drop the entry whenever the
    regions change."""
    key = (i, len(p.pages[i].regions),
           tuple(getattr(p.pages[i], "hidden_kinds", ()) or ()))
    hit = _page_cache.get(i)
    if hit and hit[0] == key:
        return hit[1]
    page = p.materialize(i)
    clean_page(p, i, page)
    _page_cache.clear()
    _page_cache[i] = (key, page)
    return page


def invalidate_page(i: int) -> None:
    _page_cache.pop(i, None)


# How far from a stored outline a brush stroke counts as mending it. A drawn
# balloon edge is a few pixels wide and a person painting one back does not
# trace it to the pixel; the leak they are closing is on the line itself.
REPAIR_REACH = 14


def _unfreeze_repaired_balloons(p: Project, i: int, overlay: bytes) -> int:
    """Forget the stored shape of every balloon the new paint has touched.

    A balloon is found once and then kept as a POLYGON in the box's record;
    every page build rebuilds the shape from it, and `find_balloons` skips
    anything that already has one. That is right almost always — a shape found
    once should not wander — and it is exactly wrong after the artwork it was
    read from has been mended.

    lee: the cleaner rubbed a piece out of a balloon's edge, the run of paper
    joined the balloon next to it, and the fitter started typesetting into a
    shape twice the size. He painted the edge back and nothing changed,
    because the wrong shape was already frozen into the record — *"the
    typeseetting is not registerng that and is still typessting as if the box
    was open"*.

    So paint that lands on or near a stored outline drops that outline, and
    the next page build looks again — at `Project.repaired`, which is the scan
    with his strokes on it. Two guards:

    * only where the paint actually reaches the outline, so mending one
      balloon does not re-open the question for every box on the page;
    * never a box drawn or tightened by hand. That shape is a decision, not a
      reading, and no amount of painting makes it a guess again.

    Returns how many were forgotten.
    """
    if not overlay:
        return 0
    try:
        buf = np.frombuffer(overlay, np.uint8)
        o = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    except Exception:
        return 0
    if o is None or o.ndim != 3 or o.shape[2] != 4:
        return 0
    painted = (o[:, :, 3] > 0).astype(np.uint8)
    if not painted.any():
        return 0
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (2 * REPAIR_REACH + 1,) * 2)
    reach = cv2.dilate(painted, k) > 0
    H, W = o.shape[:2]
    done = 0
    for rec in p.pages[i].regions:
        if rec.get("manual"):
            continue
        poly = rec.get("polygon") or []
        if len(poly) < 3:
            continue
        pts = np.array(poly, dtype=np.int32)
        if project_mod._is_a_box(pts):
            continue                      # a rectangle is not a drawn outline
        line = np.zeros((H, W), np.uint8)
        cv2.polylines(line, [pts.reshape(-1, 1, 2)], True, 255, 1)
        if not (reach & (line > 0)).any():
            continue
        rec["polygon"] = []
        rec["bubble_bbox"] = None
        done += 1
    return done


def _hidden_rows(pg) -> list:
    """The boxes put away one at a time, as little as the list needs to draw a
    row with a closed eye on it.

    Not the whole record. A hidden box takes no part in the page's work, and
    handing the browser a full region for one is how something downstream ends
    up treating it as work: `regions` is the page, this is a way back.
    """
    ids = [int(v) for v in (getattr(pg, "hidden_ids", []) or [])]
    if not ids:
        return []
    want = set(ids)
    out = []
    for rec in pg.regions:
        try:
            rid = int(rec.get("id", -1))
        except (TypeError, ValueError):
            continue
        if rid not in want:
            continue
        out.append({"id": rid, "order": int(rec.get("order") or 0),
                    "kind": str(rec.get("kind") or ""),
                    "bbox": [int(v) for v in (rec.get("bbox") or [0, 0, 0, 0])],
                    "src_text": rec.get("src_text") or "",
                    "dst_text": rec.get("dst_text") or "",
                    # ...and the three that only decide how the row LOOKS. A
                    # hidden row is drawn in its own place in the list now,
                    # greyed rather than moved — lee: *"it shoud stay inplace
                    # instad of going to teh bottom, and just grey out"* — and
                    # "the same row, greyed" cannot be drawn out of a record
                    # with the score and the link missing from it.
                    "confidence": float(rec.get("confidence") or 0.0),
                    "own_text": bool(rec.get("own_text")),
                    "link": rec.get("link")})
    out.sort(key=lambda r: r["order"])
    return out


def layout_preview(p: Project, i: int, rid: int, override: dict) -> dict:
    """Where the lines would land, without rendering or saving anything.

    This is what makes live editing possible: the browser draws the text
    itself and only needs the positions, so there is no image round-trip on
    every keystroke.
    """
    page = cached_page(p, i)
    region = next((r for r in page.regions if r.id == rid), None)
    if region is None:
        return {"error": "no such region"}

    cfg = _typeset_cfg(p)
    # The server answers on threads, and this block temporarily swaps the
    # shared region's override. Two requests interleaving here is what made
    # text spring away from its box: one thread computed with the other's
    # half-restored state. One lock, no interleaving.
    with _preview_lock:
        saved = region.layout_override
        try:
            override = dict(override or {}, locked=True)
            # Emptying a box keeps the box, at the size it was — and the size
            # it was is on the stored record, not on the override, unless the
            # person had dragged the frame themselves. Without this the block
            # snapped to its bbox the moment the last character went, so the
            # thing left on screen to click was not the thing you emptied.
            if ("lines" in override
                    and not any(str(x).strip()
                                for x in (override.get("lines") or []))
                    and not override.get("frame")):
                rec = next((r for r in p.pages[i].regions
                            if r["id"] == rid), None)
                fr = ((rec or {}).get("layout") or {}).get("frame")
                if fr and len(fr) == 4:
                    override["frame"] = [int(v) for v in fr]
            region.layout_override = override
            # Half of a split line is typeset into the balloon divided the way
            # the page divides it — the preview has to answer the same shape
            # typeset_page does, or editing one bubble would re-typeset it
            # differently from the page it sits on. That holds for a hand edit
            # as much as for a fresh fit, so the share is worked out first and
            # both paths get it.
            share = typeset_mod.share_masks(page.regions, cfg).get(region.id)
            lay = typeset_mod.layout_from_override(region, cfg, share)
            if lay is None:
                # nothing hand-placed: fit it to the bubble and keep it in
                # there.
                lay = typeset_mod.fit_region(region, cfg, share)
                # A sound effect is laid out along its own axis and is not
                # pulled back inside the region — clamping it there is what
                # squared a leaning effect back up. Everything else is
                # contained, then handed the box it occupies, exactly as
                # `typeset_page` does it, so the preview and the page agree.
                if _kinds.family_of(region.kind) != "sfx":
                    lay = typeset_mod.enforce_bounds(region, lay, cfg, share)
                    lay = typeset_mod.anchor_to_frame(lay, cfg)
        finally:
            region.layout_override = saved

    # Hand the browser the colours too, so its preview matches the export.
    base = page.clean_plate if page.clean_plate is not None else page.image
    fg, edge, stroke = render_mod._ink_colours(
        base, region, lay, typeset_mod.on_art(region),
        orig=page.image)
    o = override or {}
    fg = render_mod.hex_rgb(o.get("fg")) or fg
    edge = render_mod.hex_rgb(o.get("edge")) or edge
    return {"lines": lay.lines, "font_size": int(lay.font_size),
            "leading": round(float(lay.leading), 3),
            "lspace": float(o.get("lspace") or 0),
            "shadow": (o.get("shadow")
                       if render_mod.hex_rgb(o.get("shadow")) else ""),
            "sh_dist": float(o.get("sh_dist") or 2),
            "sh_blur": float(o.get("sh_blur") or 3),
            "curve": float(o.get("curve") or 0),
            "glow": (o.get("glow")
                     if render_mod.hex_rgb(o.get("glow")) else ""),
            "glow_size": float(o.get("glow_size") or 6),
            "iglow": (o.get("iglow")
                      if render_mod.hex_rgb(o.get("iglow")) else ""),
            "iglow_size": float(o.get("iglow_size") or 5),
            "opacity": (100 if o.get("opacity") in (None, "")
                        else max(0, min(100, int(o["opacity"])))),
            "origins": [[int(a), int(b)] for a, b in lay.line_origins],
            "fit_ok": bool(lay.fit_ok),
            "kind": region.kind,
            "fg": f"rgb({fg[0]},{fg[1]},{fg[2]})",
            "edge": f"rgb({edge[0]},{edge[1]},{edge[2]})",
            "stroke": (int(override["stroke"])
                       if (override or {}).get("stroke") not in (None, "")
                       else int(stroke)),
            "rotate": float(getattr(lay, "rotate", 0.0)),
            "fg1": (o.get("fg1")
                    if render_mod.hex_rgb(o.get("fg1")) else ""),
            "fg2": (o.get("fg2")
                    if render_mod.hex_rgb(o.get("fg2")) else ""),
            "grad_angle": float(o.get("grad_angle") or 0),
            # ...and the same three for the OUTLINE, which can carry a gradient
            # of its own. lee: *"can you make it so that i can add gradient to
            # the ouline of the text"*.
            "edge1": (o.get("edge1")
                      if render_mod.hex_rgb(o.get("edge1")) else ""),
            "edge2": (o.get("edge2")
                      if render_mod.hex_rgb(o.get("edge2")) else ""),
            "edge_angle": float(o.get("edge_angle") or 0),
            "frame": list(getattr(lay, "frame", None) or []),
            # See project.py: a divided speech keeps its own line positions.
            "fixed": bool(getattr(lay, "fixed", False)),
            "font": lay.font_path or cfg.font_path}


def do_typeset(p: Project, i: int, reset: bool = True) -> None:
    """Lay out the typesetting and store it, so it can be reviewed and edited
    before anything is written to disk.

    Pressing Typeset means "lay this page out again", and it means it: every
    hand correction goes, and so does every text box put there by hand.
    lee: *"when i re typseet a page any custom chnages to text boxes or custom
    text box dshoud be removed"*. Without that there was no way back to a
    clean layout short of undoing each block one at a time — the button that
    was supposed to be the reset was the one thing that could not reset.

    `reset=False` is for the re-typeset that follows NEW WORDS ARRIVING — a
    translation file uploaded, a model's reply pasted in. Nobody pressed
    Typeset there, so nothing of lee's is thrown away: the boxes he drew
    himself stay where they are, saying what they say. Sweeping them up as
    part of a courtesy re-typeset would delete work he never asked to lose.
    """
    # Boxes somebody drew themselves, holding words of their own rather than
    # a translation of anything on the page.
    own = [r for r in p.pages[i].regions if r.get("own_text")]
    if own:
        p.pages[i].regions = [r for r in p.pages[i].regions
                              if not r.get("own_text")]
        invalidate_page(i)
    if reset:
        # …and every hand correction, not just the placement keys
        # `clear_fitting` drops: the font chosen for one block, its colours,
        # its glow. Typeset is the way back to what the fitter would have done.
        for r in p.pages[i].regions:
            if r.get("layout_override"):
                r["layout_override"] = None

    def restore():
        """The hand-drawn boxes back where they were, in page order."""
        if reset or not own:
            return
        p.pages[i].regions = sorted(p.pages[i].regions + own,
                                    key=lambda r: int(r.get("order") or 0))
        invalidate_page(i)

    page = p.materialize(i)
    # Which blocks had typesetting on them a moment ago and have no words now.
    # `materialize` builds every region fresh and carries no layout — every
    # stage re-fits — so the stored record is the only thing that knows there
    # is something on the page to take away.
    # lee: *"the etxt box still rejexcts me deleteing all teh text"*.
    emptied = {r["id"]: (r.get("layout") or {}) for r in p.pages[i].active
               if not str(r.get("dst_text") or "").strip()
               and (r.get("layout") or {}).get("lines")}
    # Nothing to typeset AND nothing to un-typeset. The second half matters:
    # deleting the words from the last box on a page left this guard looking
    # at a page with no text at all, so it returned and the typesetting stayed.
    if not any(r.dst_text for r in page.regions) and not emptied:
        return restore()
    clean_page(p, i, page)
    # redo: pressing Typeset lays the page out again, hand corrections and
    # all. Anything else (a preview, an export) typesets the page as it stands.
    cfg = _typeset_cfg(p)
    typeset_mod.typeset_page(page, cfg, redo=True)
    for r in page.regions:
        if r.id in emptied:
            r.layout = typeset_mod.empty_layout_for(r, cfg, emptied[r.id])
    _commit_keep_proofread(p, i, page)
    restore()
    invalidate_page(i)
    p.pages[i].typeset = True
    p.pages[i].cleaned = True


MAX_POINTS = 4          # boxes are rectangles: four corners, no more
MIN_POINTS = 4


def _project_name(p: Project) -> str:
    """What to call this chapter's file.

    The series title if there is one — it is what the person would type
    themselves — then whatever the file was called last time, then the folder
    the pages came from.
    """
    title = (getattr(p.ctx, "title", "") or "").strip()
    if title:
        return re.sub(r'[\\/:*?"<>|]+', "-", title)[:60].strip(" .-") or "chapter"
    for d in (p.settings.get("project_file") or "",):
        if d:
            return os.path.splitext(os.path.basename(d))[0] or "chapter"
    stem = os.path.basename((p.input_dir or p.output_dir or "").rstrip("/\\"))
    # The upload folder is called `input` for every project ever made, which
    # is not a name for anything. Its parent is the project.
    if stem.lower() in ("", "input", "strip"):
        stem = os.path.basename(os.path.abspath(p.output_dir).rstrip("/\\"))
    return stem or "chapter"


def _project_dir(p: Project) -> str:
    """Where the last Save put the file, for the next dialog to start in."""
    at = p.settings.get("project_file") or ""
    d = os.path.dirname(at)
    return d if d and os.path.isdir(d) else ""


def _adopt(p: Project, state: dict, src: str = "") -> dict:
    """Take on a project that has just been unpacked into our own folder.

    The state is written where `load` looks for it and read back through the
    ordinary loader, so a bundle goes through every migration an old
    project.json goes through — nothing gets a second, quietly different way
    into the app.
    """
    with open(p.state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
    p.pages = []
    p._img_cache.clear()
    p.load()
    if src:
        p.settings["project_file"] = src
    p.save()
    _page_cache.clear()
    _invalidate_renders()
    _kinds.use(p.settings.get("custom_kinds") or [])
    warm_pages(p, 0)
    return {"pages": len(p.pages), "path": src,
            "name": _project_name(p)}


def export_root(p: Project) -> str:
    """Where exported pages go: <destination>/<folder name>."""
    dest = p.settings.get("export_dir") or p.output_dir
    name = (p.settings.get("export_name") or "pages").strip() or "pages"
    name = os.path.basename(name.replace("\\", "/").rstrip("/")) or "pages"
    return os.path.join(os.path.abspath(os.path.expanduser(dest)), name)


# Kinds that cannot have a balloon: writing brushed onto the artwork, and
# sound effects. Calling a box one of these is a statement that there is no
# balloon round it.
# The two families that never have a balloon: writing lying on the artwork,
# and a drawn sound. A sub-type is unballooned when its FAMILY is — a box's
# geometry is decided by which of the three it is, never by which sub-type.
NO_BALLOON_KINDS = ("freefloat", "sfx")


def _no_balloon(kind: str) -> bool:
    return _kinds.family_of(kind or "") in NO_BALLOON_KINDS


def _kind_changed(rec: dict, was: str) -> None:
    """Make a change of box type actually change the typesetting.

    lee: *"i changed teh bubble to outside buuble an it still typeseete the
    same"*. He was right and the reason is worth writing down. A chapter is
    held as GEOMETRY — masks are rebuilt on every load — and the balloon a
    region was given is stored as its `polygon`. Calling the box "outside text"
    only rewrote `kind`; the panel-shaped polygon the balloon finder had handed
    it was still sitting in the record, so the page came back with exactly the
    same placement area and typeset exactly the same. The label said one thing
    and the geometry said another, and the geometry won.

    So when a box is called something that cannot have a balloon, the balloon
    goes with it: the polygon returns to a plain rectangle round the writing,
    which is what "no balloon" is written as everywhere else in the project
    (see project.region_from_record). The next load finds no outline, does not
    go looking for one, and gives the region the empty paper around its writing
    instead.

    Pressing Typeset then lays the page out again from geometry that has
    actually changed, which is the other half of what he asked for.
    """
    from .typeset import FITTING_KEYS
    if _no_balloon(rec.get("kind")):
        x, y, w, h = (int(v) for v in rec["bbox"])
        rec["polygon"] = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        rec["bubble_bbox"] = [x, y, w, h]
    # The placement is dropped either way, whichever direction the kind moved,
    # so Typeset lays the region out again instead of keeping a fit measured
    # against a shape it no longer has. The typesetting already on the page STAYS
    # until then: emptying the bubble the moment somebody changes a label would
    # blank the page in front of them.
    ov = rec.get("layout_override") or {}
    left = {k: v for k, v in ov.items() if k not in FITTING_KEYS}
    rec["layout_override"] = left or None


def drop_plate(p: Project, i: int) -> None:
    """Throw away this page's finished plate so the next clean rebuilds it.

    The plate cache exists so that MOVING to a page is instant. Pressing Clean
    is not moving to a page — it is asking for the work to be done — so the
    step drops the plate first. lee, looking at "37 pages were already cleaned,
    so the finished plate was reused": *"if i clcik it again it shoud redo it"*.

    The per-region cache of the model's own answers is left alone on purpose:
    it is keyed by the exact crop, mask, address and token, so a hit is the
    same picture the endpoint would send back, for free. The page really is
    re-cleaned; what is skipped is paying twice for an identical answer.
    """
    key = _plate_stamp(p, i)
    _plate_cache.pop(key, None)
    try:
        fp = _plate_disk_path(p, i)
        if os.path.exists(fp):
            os.remove(fp)
    except OSError:
        pass


def do_clean(p: Project, i: int, force: bool = False) -> None:
    """Produce (and cache) the cleaned plate for one page. Its own pipeline
    step so the expensive AI cleaning can be run and cached up front, before
    typesetting — the plate is reused from cache afterwards.

    `force` is the Clean button: redo the page rather than reuse it.
    """
    if own_plate_path(p, i):
        # Excluded. Not "cleaned and then overwritten" — never cleaned: the
        # plate is thrown away neither on disk nor in memory, no mask is built,
        # and nothing goes to the hosted cleaner (which is what this step
        # actually costs). It still counts as DONE, or the Clean step would sit
        # at 22/23 for ever and Typeset would stay locked behind it.
        p.pages[i].cleaned = True
        _tally_clean({"own": 1})
        return
    if force:
        drop_plate(p, i)
    page = p.materialize(i)
    clean_page(p, i, page)
    p.pages[i].cleaned = True


def _commit_keep_proofread(p: Project, i: int, page) -> None:
    """commit() rebuilds records via region_record(), which drops the
    editor-only 'proofread' flag. Any stage that re-commits a page (typeset,
    export) must go through here or it silently un-proofreads the page."""
    proofed = {r["id"] for r in p.pages[i].regions if r.get("proofread")}
    p.commit(i, page)
    for r in p.pages[i].regions:
        if r["id"] in proofed:
            r["proofread"] = True


EXPORT_MODES = ("full", "clean", "boxes")


def export_page(p: Project, i: int, mode: str = "full") -> str:
    """Write one page out. Three things can be written.

    `full` is the finished page: clean the art, lay the English out, draw it.

    `clean` is the cleaned plate bare — the raws with the Japanese erased,
    ready to hand to someone else to typeset (or to keep as the art). It is the
    same plate the typesetting would have been drawn on, so it costs nothing
    extra: skip the typesetting and the drawing and save what is already there.

    `boxes` is the ORIGINAL art with the boxes drawn on, exactly as the editor
    draws them — the same colours per text type, the same faint balloons, the
    same reading-order numbers. It is a check sheet, not a page of the book, so
    nothing is cleaned and nothing is laid out; it reads the stored records and
    copies the picture, which is why it is instant.

    Only the finished page is the export, so only `full` ticks the Export step.
    """
    if mode not in EXPORT_MODES:
        raise ValueError(f"unknown export mode: {mode!r}")
    stem = os.path.splitext(p.pages[i].name)[0]
    out = os.path.join(export_root(p), f"{stem}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    if mode == "boxes":
        # No materialize, no clean, no typeset: the boxes are already known and
        # the picture they belong on is the page as it arrived.
        cv2.imwrite(out, render_mod.box_sheet(
            p.image(i), p.pages[i].active,
            p.settings.get("custom_kinds") or []))
        return out

    page = p.materialize(i)
    clean_page(p, i, page)
    typeset = mode == "full"
    if typeset:
        cfg = _typeset_cfg(p)
        typeset_mod.typeset_page(page, cfg)
        img = _composite_over(p, i, render_mod.render_page(page, cfg))
    else:
        img = page.clean_plate if page.clean_plate is not None else page.image
    cv2.imwrite(out, img)
    if typeset:
        _commit_keep_proofread(p, i, page)
        p.pages[i].exported = True
    p.pages[i].cleaned = True
    return out


# ------------------------------------------------------------------ background

def warm_ocr(p: Project) -> None:
    """Load the OCR model in the background, once.

    The model takes long to load, and paying for that inside the first
    "Read text" made the whole feature feel slow. Loading starts as soon as
    the app does; by the time anyone presses the button it is usually ready.
    """
    def worker():
        try:
            from .ocr import get_engine
            get_engine(p.source_code, p.settings.get("ocr_engine") or "auto")
        except Exception:
            pass                     # missing engine reports itself on use
    threading.Thread(target=worker, daemon=True).start()


_warm = {"gen": 0, "running": False, "done": 0, "total": 0, "at": -1}


def _hosted_cleaning(p: Project) -> bool:
    return ((p.settings.get("ai_clean") or "off").strip() in ("hard", "all")
            and bool((p.settings.get("clean_url") or "").strip()))


def _worth_warming(p: Project, i: int, hosted: bool | None = None) -> bool:
    """Whether building this page ahead of time is free enough to just do.

    Building ahead is only a kindness while it stays local. With the hosted
    cleaner switched on, cleaning a page that has never been cleaned means a
    call out to the network — so a page nobody has run Clean over is left
    alone, and pressing Clean is still the thing that spends that. Everything
    already done, or cheap to redo, gets built.
    """
    if not p.pages[i].regions:
        return True                     # nothing to clean: just the scan
    if own_plate_path(p, i):
        return True                     # your file, read off disk: costs nothing
    if getattr(p.pages[i], "cleaned", False):
        return True                     # already paid for, cached on disk
    if not (_hosted_cleaning(p) if hosted is None else hosted):
        return True                     # local cleaning: ours to spend
    return os.path.exists(_plate_disk_path(p, i))


def warm_pages(p: Project, start: int = 0) -> None:
    """Build every page's view up front, in the background.

    Moving to a page for the first time meant waiting for it to be cleaned and
    typeset right then, because nothing had ever asked for it. So ask for it
    early: work outwards from the page being looked at, filling the plate cache
    on disk and the rendered images in memory, and by the time anyone clicks
    through, the page is already made.

    It is deliberately a bad citizen of nothing: it yields to any real job, it
    takes the render lock one page at a time so a click never queues behind
    more than the page in flight, and starting a new warm-up simply retires the
    old one.
    """
    if not p.pages:
        return
    _warm["gen"] += 1
    mine = _warm["gen"]
    order = sorted(range(len(p.pages)),
                   key=lambda i: (abs(i - start), i < start))
    hosted = _hosted_cleaning(p)
    order = [i for i in order if _worth_warming(p, i, hosted)]

    def worker():
        _warm.update(running=True, done=0, total=len(order), at=-1)
        try:
            for n, i in enumerate(order, 1):
                while p.job.get("running") and _warm["gen"] == mine:
                    time.sleep(0.4)         # a real job always goes first
                if _warm["gen"] != mine:
                    return                  # a newer warm-up took over
                _warm["at"] = i
                try:
                    if p.pages[i].regions:
                        render_index(p, i, "clean", paint=False)
                    else:
                        render_index(p, i, "original")
                except Exception:
                    traceback.print_exc()   # one bad page stops nothing
                _warm["done"] = n
                time.sleep(0.02)            # let waiting requests through
        finally:
            if _warm["gen"] == mine:
                _warm.update(running=False, at=-1)

    threading.Thread(target=worker, daemon=True).start()


def _where(e: BaseException) -> str:
    """" (file.py:123 in func)" for the deepest frame of our own code.

    The deepest frame overall is often inside numpy or OpenCV, which names a
    library file nobody here can act on; the deepest frame belonging to this
    package is the line that asked for it, which is the one worth printing.
    """
    try:
        frames = traceback.extract_tb(e.__traceback__)
        if not frames:
            return ""
        here = os.path.dirname(os.path.abspath(__file__))
        mine = [f for f in frames
                if os.path.dirname(os.path.abspath(f.filename)) == here]
        f = (mine or frames)[-1]
        return f" ({os.path.basename(f.filename)}:{f.lineno} in {f.name})"
    except Exception:
        return ""


# --- the queue --------------------------------------------------------------
#
# lee: *"add a buttion with a queue fro the loading bar so if somethin gis
# happeningfro exmaple cleeening and i click typeseete it shod be added to teh
# queue"*.
#
# Every long action in the app comes through `run_job`, and it used to start a
# thread there and then. Two of them at once share one `p.job`, so the bar
# reported whichever wrote last and the two runs trampled each other's pages —
# in practice you had to sit and wait before pressing anything else.
#
# Now `run_job` puts the work in a line and one dispatcher takes it off, one at
# a time, in order. Waiting work can be moved and dropped; the one that is
# already running is stopped the way it always was, with Cancel.
_QUEUE: list[dict] = []            # waiting, in order — [0] goes next
_Q_LOCK = threading.Lock()
_Q_SEQ = {"n": 0}
_Q_RUN = {"on": False, "qid": 0, "thread": None}


def queue_state() -> dict:
    """What the button shows: the count, and what is in the line."""
    with _Q_LOCK:
        return {"waiting": [{"qid": q["qid"], "label": q["label"],
                             "pages": len(q["indices"])} for q in _QUEUE],
                "count": len(_QUEUE), "running_qid": _Q_RUN["qid"]}


def queue_move(qid: int, dir: int) -> bool:
    """Move one waiting item up (-1) or down (+1). The running one cannot move."""
    with _Q_LOCK:
        at = next((k for k, q in enumerate(_QUEUE) if q["qid"] == qid), -1)
        to = at + (1 if dir > 0 else -1)
        if at < 0 or to < 0 or to >= len(_QUEUE):
            return False
        _QUEUE[at], _QUEUE[to] = _QUEUE[to], _QUEUE[at]
        return True


def queue_drop(qid: int) -> bool:
    """Take one waiting item out of the line. Never touches what is running —
    that is Cancel's job, and it has to stop mid-page rather than not start."""
    with _Q_LOCK:
        at = next((k for k, q in enumerate(_QUEUE) if q["qid"] == qid), -1)
        if at < 0:
            return False
        _QUEUE.pop(at)
        return True


def queue_clear() -> int:
    """Drop everything waiting. What is already RUNNING is not touched — that
    is Cancel's job, and it has to interrupt a page rather than decline to
    start one."""
    with _Q_LOCK:
        n = len(_QUEUE)
        _QUEUE.clear()
        return n


# The steps that cost money, and nothing else does. Find text, Typeset and
# Export run on this machine: they are somebody's own CPU and they are free.
PAID_STEPS = ("ocr", "translate", "proofread", "clean")


def step_engine(p: Project, step: str) -> tuple:
    """(model, backend) this step will really run on.

    Asked by pointing the context at the step and reading back what it chose,
    rather than by working the override rules out a second time here. One set
    of rules means the price cannot end up quoted against a model the step was
    never going to use.
    """
    _ctx_from_settings(p, step if step in AI_STEPS else "")
    return (getattr(p.ctx, "model", "") or "",
            getattr(p.ctx, "backend", "") or "")


def quote_run(p: Project, step: str, indices) -> int:
    """Coins a whole run is expected to cost, at today's models.

    The run, rounded up once — not the pages rounded up and added. At a
    hundred coins to the dollar one page of translation costs well under a
    coin, so rounding each page would make a two-box page and a six-box page
    both cost 1, and the per-box price lee asked for would only exist on the
    very biggest pages.

    This is the PRICE, not an estimate of one: it is what the button says and
    what leaves the purse when the button is pressed. See `_charge`.
    """
    return run_price(p, step, indices)[0]


def _page_list(p: Project, arg: str, whole: bool = False) -> list:
    """A comma-separated list of page numbers from a query string.

    `whole` makes an empty argument mean the whole chapter; without it, empty
    means nothing at all. The two are different questions — "price the pages
    this run would touch" defaults to all of them, "price the page I am
    looking at" defaults to none — and rolling them into one default is how a
    dialog comes to quote a chapter beside the words "This page only".
    """
    out = []
    for piece in str(arg or "").split(","):
        piece = piece.strip()
        if piece.lstrip("-").isdigit() and 0 <= int(piece) < len(p.pages):
            out.append(int(piece))
    if out or not whole:
        return out
    return list(range(len(p.pages)))


def run_price(p: Project, step: str, indices) -> tuple:
    """(coins this run will cost, the model, the backend). 0 for a free step."""
    if step not in PAID_STEPS:
        # Not about money. `step_engine` rewrites `p.ctx` from the settings,
        # and a Typeset or Export run has no business doing that to a context
        # the paid steps are reading.
        return (0, "", "")
    from . import coins
    model, backend = step_engine(p, step)
    # The boxes of CONTEXT this run really sends, asked of the same function
    # that builds the payload. Not the chapter's size: a full-chapter run sends
    # no context at all, and charging it the whole chapter anyway was about a
    # hundred thousand imaginary input tokens on a twenty-three page quote.
    ctx = context_boxes(p, step, indices)
    return (coins.quote(step, [page_boxes(p, i) for i in indices],
                        model, backend, ctx), model, backend)


@contextlib.contextmanager
def _charge(p: Project, step: str, indices):
    """Take the price of the run when it STARTS, and give back what it did not
    use if it stops early.

    lee: *"make teh edit remove the coins when the person click teh button and
    if they cancel teh job it shoud refund them the amount for teh pages that
    werent done"*.

    So the number on the button is the number that leaves the purse, at the
    moment the button is pressed — not a total that assembles itself over the
    next four minutes while the count drifts down and nobody knows where it
    will land. A run that is cancelled, or that falls over, gives back the
    price of the pages it never reached; a run that finishes gives back
    nothing, because it did all of it.

    The tokens are still METERED underneath, and what the run really came to
    goes in the ledger beside what was charged. Nobody is billed on it — the
    quote is the price and a promise kept is worth more than a few coins
    either way — but a quote that is drifting away from the truth is a thing
    to know about, and this is where it shows.
    """
    if step not in PAID_STEPS:
        yield None
        return
    from . import coins
    where = _run_label(p, indices)
    boxes = [page_boxes(p, i) for i in indices]
    ctx = context_boxes(p, step, indices)
    # The estimate learns from the meter, and this run is about to write a
    # meter line. Held still across the whole of it, or the refund would be
    # priced against evidence the charge never saw and the two would not add
    # back up — see `coins.steady`.
    with coins.steady():
        _price, model, backend = run_price(p, step, indices)
        # One id for the charge and for the refund that may follow it. On an
        # account the charge is a request that can time out after arriving,
        # and the id is what stops the retry paying twice; it is also what the
        # refund is measured against, so nothing can be given back that was
        # never taken.
        run = coins.new_run()
        coins.spend(_price, step, where, model, run=run)
        p.job["spent"] = _price
        with coins.charging(step, where, model, backend) as bill:
            try:
                yield bill
            finally:
                # The pages it never got to, priced the same way the whole run was
                # priced. Rounded up like everything else, which means the refund
                # can be a coin more than the share of the price those pages made
                # up — rounding a refund the other way is rounding in the seller's
                # favour, and this is the seller's own app.
                done = int(p.job.get("done") or 0)
                # Priced with the same context total the run was priced with, or
                # the refund is worked out against a different sum than the charge
                # and the two do not add back up. The context a run sends is fixed
                # when the run starts — it is the same set on every page, which is
                # what lets it sit in the cache — so this is the run's number and
                # not the unfinished tail's.
                back = coins.quote(step, boxes[done:], model, backend, ctx)
                if back:
                    coins.credit(back, "%s refund — %d page%s not done"
                                 % (step, len(boxes) - done,
                                    "" if len(boxes) - done == 1 else "s"),
                                 run=run)
                    p.job["spent"] = max(0, _price - back)
                # What it really cost, for the record and for tuning the estimate.
                # A ledger line that moves no money: nobody is billed on it.
                p.job["cost"] = bill.coins
                if bill.calls:
                    # `boxes`, `pages`, `ctx`, `backend` and `step` are what turn
                    # this from a receipt into evidence. "It used 44,870 tokens"
                    # cannot be compared with what was predicted unless the size
                    # of the thing that used them is written down beside it — and
                    # `coins.drift` is the reader.
                    coins.note("%s cost" % step, where, model, coins=bill.coins,
                               tin=bill.tin, tout=bill.tout, cached=bill.cached,
                               calls=bill.calls, charged=p.job["spent"],
                               step=step, backend=backend, ctx=ctx,
                               boxes=sum(boxes[:done]), pages=done)


def key_for(p: Project, backend: str, step: str = "") -> str:
    """The key a call to this service will be made with.

    **The service box wins.** It is the answer; a per-step box is a leftover
    from when there were three of them, and is only reached for when the
    service box is empty — so a key that has been moved cannot be
    countermanded by a stale copy nobody can see on screen.

    And only on the SAME service. A per-step key is a key for whatever provider
    that step was pointed at when it was typed; handing it to a different one
    because the step has since been switched means sending Google a Claude key
    and reading the provider's own wording about it halfway down the editor.
    """
    back = (backend or "").strip().lower()
    if not back:
        return ""
    ours = str(p.settings.get(f"key_{back}") or "").strip()
    if ours:
        return ours
    for s in ((step,) if step else AI_STEPS):
        if not s:
            continue
        if (p.settings.get(f"{s}_backend") or "").strip().lower() != back:
            continue
        old = str(p.settings.get(f"{s}_key") or "").strip()
        if old:
            return old
    return ""


def needs_key(p: Project, step: str) -> str:
    """"" if this step can be called, or the sentence saying what is missing.

    A step used to fall back to a project-wide engine when it had no key of
    its own, so a missing key was invisible and the run quietly happened
    somewhere else. There is no project-wide engine any more, and a step with
    no key is a step that cannot run — which is better, as long as it says so
    BEFORE the chapter starts instead of failing on page one with a provider's
    own wording about an invalid key.
    """
    if step not in AI_STEPS:
        return ""
    # `step_engine` answers (model, backend) — in that order, which is worth
    # writing out: reading it the other way round made this compare a MODEL
    # name against the list of providers that need a key, so every step looked
    # as though it were local and nothing was ever asked for.
    _model, back = step_engine(p, step)
    if back not in NEEDS_KEY:
        return ""                      # local, and local wants no key
    if key_for(p, back, step):
        return ""
    label = {"ocr": "Read text", "translate": "Translate",
             "proofread": "Proofread"}.get(step, step)
    service = dict(SERVICES).get(back, back)
    # Names the SERVICE, not the step. One key serves all three steps now, so
    # "put a key next to Translate" would send somebody looking for a box that
    # is not there any more.
    return ("%s has no API key. Open Settings \u203a API keys and put your "
            "%s key in, or point that step at a model you run yourself."
            % (label, service))


def afford_run(p: Project, step: str, indices) -> str:
    """"" if this run can be paid for, or the sentence saying why not.

    Asked BEFORE anything starts, because the whole price is taken up front:
    there is no such thing any more as a run that pays for the pages it can
    manage and stops. Fewer pages is a smaller price, and the dialog that
    started this shows both.
    """
    from . import coins
    price, _model, _backend = run_price(p, step, indices)
    if price <= 0 or coins.can_afford(price):
        return ""
    return ("not enough TCT Coins — this needs %s and there %s %s. "
            "Run fewer pages, or buy more coins."
            % (coins.show(price),
               "is" if coins.balance() == 1 else "are",
               coins.show(max(0, coins.balance()))))


def _run_label(p: Project, indices) -> str:
    """What the ledger calls this run: the page, or how many of them."""
    idx = list(indices or [])
    if len(idx) == 1:
        try:
            return p.pages[idx[0]].name
        except Exception:
            return ""
    return "%d pages" % len(idx)


def page_boxes(p: Project, i: int) -> int:
    """How many text boxes are on this page — which is what its AI steps cost.

    lee: *"make teh coin system be dynamic and per text box in a page so if a
    page has 1 0r 2 tet box it shoiukd be cheaper than a page that has 5-6 text
    boxes"*. A page nobody has run Find text on yet counts 0, and a quote of 0
    is right: there is nothing on it to send.
    """
    try:
        return len(p.pages[i].regions or [])
    except Exception:
        return 0


def _run_one(p: Project, item: dict) -> None:
    label, indices, fn = item["label"], item["indices"], item["fn"]
    step = item.get("step") or ""
    p.job.update(running=True, label=label, done=0,
                 total=len(indices), error="", cancel=False, cancelled=False,
                 spent=0)
    # A warning belongs to the run being watched. Clearing it here means the
    # bar reports what THIS run met, not what some run last Tuesday met.
    clear_clean_warning()
    try:
        with _charge(p, step, indices):
            for n, i in enumerate(indices, 1):
                if p.job.get("cancel"):        # stop requested between pages
                    p.job["cancelled"] = True
                    break
                fn(i)
                p.job["done"] = n
                # Each page as it is finished, not the lot at the end. A run that
                # fell over on page 12 of 23 used to take pages 1-11 with it: the
                # only write was after the loop, and an exception jumps over it —
                # so eleven pages of translation lived in memory and nowhere else,
                # and the next time the project was read off disk they had never
                # happened. lee: *"sometime when i reload the page i lose some
                # profreading or tranaltiong"*.
                #
                # `save_soon` and not `save`: it coalesces, so twenty pages in a
                # row still cost one write, and it happens off this thread.
                p.save_soon()
    except Exception as e:
        # Say WHERE. A bare type and message in the red bar leaves the person
        # reading it with nothing to report and nothing to look at, so the
        # innermost frame that is ours goes in with it.
        p.job["error"] = f"{type(e).__name__}: {e}{_where(e)}"
        traceback.print_exc()
    finally:
        # Whatever got done is on disk before anything else happens — the run
        # that finished, the run that was cancelled, and above all the run that
        # raised. This is the write the `except` above used to skip.
        try:
            p.save()
        except Exception:
            traceback.print_exc()
        p.job["running"] = False
        p.job["cancel"] = False
        # Whatever the step changed, the pages now look different — get them
        # all rebuilt before anyone clicks on one.
        try:
            warm_pages(p, indices[0] if indices else 0)
        except Exception:
            pass


def _dispatch() -> None:
    """Take work off the line until there is none. One at a time, in order.

    Each item carries its own project, so a dispatcher started for one and
    still going round when another has replaced it reports into the right one
    either way. That is not a nicety: this module holds one global queue and
    the editor is handed a new project whenever one is opened — a dispatcher
    that captured the project it started with would write its progress into a
    project nobody is looking at any more.

    Exactly one dispatcher runs at a time and it owns the `on` flag. It puts
    that flag down on the way out; leaving it set would mean every later action
    joined the line and nothing ever ran it, which from outside is
    indistinguishable from the app being dead.
    """
    while True:
        with _Q_LOCK:
            if not _QUEUE:
                _Q_RUN.update(on=False, qid=0)
                return
            item = _QUEUE.pop(0)
            _Q_RUN["qid"] = item["qid"]
        p = item["project"]
        try:
            _run_one(p, item)
        except Exception:
            traceback.print_exc()      # one bad job must not end the queue
        # A run that ENDED IN AN ERROR stops the line. Carrying on would run
        # the next step over pages the last one left half-finished, and the red
        # bar would be replaced by a green one before anybody read it.
        if p.job.get("error"):
            # Clearing the line and putting the flag down must happen together.
            # Two separate turns of the lock leave a gap in the middle where an
            # action arriving sees the flag still up, joins a line that is
            # about to be abandoned, and waits for a dispatcher that has
            # already decided to go home.
            with _Q_LOCK:
                dropped = len(_QUEUE)
                _QUEUE.clear()
                _Q_RUN.update(on=False, qid=0)
            if dropped:
                p.job["error"] += (f" — {dropped} queued "
                                   f"action{'s' if dropped != 1 else ''} dropped")
            return


def run_job(p: Project, label: str, indices: list[int], fn,
            step: str = "") -> int:
    """Put one action in the line. Returns its queue id.

    It starts at once when nothing else is running, which is what it always did
    and what it looks like from the outside.

    `step` is what the run COSTS — one of `PAID_STEPS`, or "" for the ones that
    run on this machine and are free. It is carried on the queue item rather
    than guessed from the label, because the label is prose that gets reworded
    and a price must not depend on the wording of a progress bar.
    """
    with _Q_LOCK:
        _Q_SEQ["n"] += 1
        qid = _Q_SEQ["n"]
        _QUEUE.append({"qid": qid, "label": label, "project": p,
                       "indices": list(indices), "fn": fn, "step": step})
        # The flag is a CLAIM, and a claim is only good while whoever made it
        # is still there. Trusting the flag alone means that any way at all of
        # leaving it set on the way out — a raise between two turns of the
        # lock, a thread that died — strands everything queued behind it for
        # ever, and from outside that is a Clean that finished and a Translate
        # that simply never began. lee: *"i hit clean and had translate in teh
        # queue but when clean ws done nothing happend"*.
        alive = _Q_RUN.get("thread")
        if _Q_RUN["on"] and alive is not None and alive.is_alive():
            return qid                 # the dispatcher will get to it
        t = threading.Thread(target=_dispatch, daemon=True)
        _Q_RUN.update(on=True, thread=t)
    t.start()
    return qid


def _is_generic_speaker(name: str) -> bool:
    """True for an unnamed bit part ("Guard A", "Crowd"), so it is kept off the
    running character sheet. One definition, shared with the translator."""
    from .translate import is_generic_speaker
    return is_generic_speaker(name)


def do_ocr(p: Project, i: int) -> None:
    """Read the Japanese out of every bubble with the vision model.

    The whole page goes to the model at once — outlined and numbered — so each
    line is read WITH the surrounding dialogue as context (which is what lets it
    tell 居たぞ from 口はたぞ, or rebuild a broken name). It is prompted to
    transcribe only what is printed and to leave a region empty rather than
    invent a plausible line, so it does not hallucinate text into the page.
    """
    from .ocr import page_label_tiles, looks_like_garbage
    from .translate import read_page_ocr
    page = p.materialize(i)
    regs = page.regions
    if not regs:
        return

    def say(msg: str) -> None:
        try:
            if p.job.get("running"):
                p.job["label"] = msg
        except Exception:
            pass

    _ctx_from_settings(p, "ocr")
    say("Reading text — sending the page to the AI reader…")
    detail = p.settings.get("ocr_detail") or "auto"
    tiles = page_label_tiles(page, detail=detail)

    def tick(n: int, total: int) -> None:
        if total > 1:
            say(f"Reading text — AI reader, piece {n} of {total}…")

    try:
        texts = read_page_ocr(page, p.ctx, tiles, progress=tick)
    except Exception as e:
        for r in regs:
            if not (getattr(r, "locked", False) and r.src_text):
                r.src_text, r.ocr_ok = r.src_text or "", False
                r.flagged = f"AI read failed: {e}"
        p.commit(i, page)
        raise
    for r in regs:
        # A hand-corrected, locked line is never overwritten by a re-read.
        if getattr(r, "locked", False) and r.src_text:
            continue
        t = (texts.get(r.id) or "").strip()
        r.src_text = t
        if not t:
            r.ocr_ok, r.flagged = False, "ocr: no text read"
        else:
            r.ocr_ok = True
            r.flagged = looks_like_garbage(t, r)
    p.commit(i, page)


def chapter_context(p: Project, indices=None):
    """The rest of the chapter, as lines the model can read.

    **Every other page**, not a window around the run. A window of two cannot
    see a name settled six pages back, or a term agreed at the front of a long
    re-run — and those are exactly the things a reader notices when they drift.
    lee, on the narrowed version: *"undo these chnages"*.

    **Finished translation where there is one, source text otherwise.** The
    "finished translations only" rule sounded careful and was quietly the worst
    part: on a chapter nobody has started, it means the context is EMPTY. The
    model translates page 12 with no idea what happens on 11 or 13, which is
    the case the context exists for. Source text is not as good as a finished
    line, but it is the story, and it is what a human translator would read.

    **Not the pages being translated.** Their text is what is about to be
    replaced.

    The one thing that stayed from the narrow version, because it costs nothing
    in quality: the answer is for the RUN, not for each page, so it is
    byte-identical on every page and sits inside the prompt cache — see
    `translate._base_payload`, which puts it above `characters` for that
    reason. What the synopsis, the character sheet and the glossary carry are
    the DURABLE facts: they say who Ada is, not what she said four pages ago.
    That is this.
    """
    skip = {int(i) for i in (indices or [])}
    out = []
    for k in range(len(p.pages)):
        if k in skip:
            continue
        st = p.pages[k]
        lines = []
        for r in sorted(st.regions, key=lambda r: r.get("order", 0)):
            t = (r.get("dst_text") or "").strip() or (r.get("src_text") or "").strip()
            if t:
                lines.append(t)
        if lines:
            out.append({"page": k + 1, "lines": lines})
    return out


def run_context(p: Project, indices):
    """The context a run of these pages will be sent, or None for none at all.

    **One decision, asked by two places.** `/api/translate_all` asks it to know
    what to SEND; `context_boxes` asks it to know what to CHARGE. Written out
    twice they drift apart, and drift here is silent in both directions: charge
    for context that is not sent and every subset run is overpriced, send
    context that is not charged for and the app pays the difference. Neither
    shows up anywhere except on a bill nobody reads until it is large.

    A full-chapter run gets nothing. Every page is being translated, so there
    is nothing to be consistent WITH that is not already in the run — and the
    old price pretended otherwise, quoting lee's twenty-three page chapter for
    a hundred thousand input tokens it never sent.
    """
    idx = sorted({int(i) for i in (indices or [])})
    if not idx or len(idx) >= len(p.pages):
        return None
    return chapter_context(p, idx)


def context_boxes(p: Project, step: str, indices) -> int:
    """Boxes of context a run of these pages really sends. Counted, not assumed.

    The count comes from `run_context` itself rather than from the chapter's
    size, so there is no arithmetic here that can disagree with the payload.
    Only translation sends any; the other steps are handed one page and asked
    about that page.
    """
    if step != "translate":
        return 0
    return sum(len(e.get("lines") or []) for e in (run_context(p, indices) or []))


def do_translate(p: Project, i: int, chapter: list | None = None) -> None:
    from .translate import translate_page
    _ctx_from_settings(p, "translate")
    page = p.materialize(i)
    if any(r.src_text.strip() for r in page.regions):
        translate_page(page, ctx=p.ctx, chapter=chapter)
    # New wording, so any remark the proofreader left about the old wording is
    # about text that no longer exists.
    p.pages[i].note = ""
    p.pages[i].note_ids = []
    p.commit(i, page)


# The three steps that call a model, and the settings key each one's override
# lives under. One chapter can now be read by a cheap vision model, translated
# by a mid-tier one and proofread by the best one available — which is where
# nearly all the cost is, because reading and translating run on every page
# while the expensive judgement only has to happen once at the end.
AI_STEPS = ("ocr", "translate", "proofread")

# Providers that will not answer without one. All three of them, now that the
# services this app offers are Claude, Gemini and OpenRouter and nothing else:
# every one is somebody's paid endpoint.
NEEDS_KEY = ("anthropic", "gemini", "openrouter")

# The three services, in the order the menus list them. `project.SERVICES` and
# the `SERVICES` in `static/js/project.js` are this same list, held together by
# a test — a service the screen offers and the server does not know is a step
# nobody can run, and it fails at the provider rather than at the menu.
SERVICES = (("anthropic", "Claude API"),
            ("gemini", "Google AI Studio"),
            ("openrouter", "OpenRouter"))

# Claude has no /models endpoint on the key the app uses, so the suggestion
# list for that provider is written down. Everything else is asked.
CLAUDE_MODELS = ("claude-sonnet-5", "claude-haiku-4-5-20251001",
                 "claude-opus-4-8")


# How long a provider's answer about what it can reach is worth reusing.
# Long enough that opening Settings three times is one request, short enough
# that a key that has just been given access does not stay locked out for the
# afternoon. Cleared outright when the settings are saved, which is when it
# would otherwise be most wrong.
MENU_TTL = 15 * 60

# ...and how long to wait for it. The Settings screen is WAITING on this, so a
# provider that will not answer must not hold the menu open for twenty seconds:
# the answer when nothing comes back is "the priced list", which is a perfectly
# good menu. This is a call that only ever HELPS.
MENU_TIMEOUT = 6

# (address, key hash) -> (when, names). Keyed on the KEY and not on the step,
# because the question is about the key: two steps on the same service ask it
# once between them, and a key that is changed asks again.
_MENU_CACHE: dict = {}


def _menu_key(url: str, key: str) -> tuple:
    import hashlib
    return (url or "", hashlib.sha256((key or "").encode()).hexdigest()[:16])


def _reachable(back: str, url: str, key: str) -> list:
    """What this key can actually reach, asked of the provider and remembered.

    Nothing is asked when there is no key. All three services refuse
    `GET /models` without one, so the request could only ever time out — three
    times, every time Settings was opened.
    """
    if not key:
        return []
    ck = _menu_key(url, key)
    hit = _MENU_CACHE.get(ck)
    if hit and time.time() - hit[0] < MENU_TTL:
        return hit[1]
    from . import translate as translate_mod
    if not url:
        url = (translate_mod.LOCAL_PRESETS.get(back) or {}).get("base_url", "")
    names = (translate_mod.list_models(url, key, timeout=MENU_TIMEOUT)
             if url else [])
    _MENU_CACHE[ck] = (time.time(), names)
    return names


# An OpenRouter id can carry a VARIANT after a colon — `:free`, `:nitro`,
# `:floor`. Each is a different price for the same model and none of them is
# the price in the table, so they are not offered: a `:free` variant quoted at
# the paid rate overcharges, and a `:nitro` one quoted at the standard rate is
# a bill this app eats.
VARIANT = ":"


def model_menu(back: str, url: str, key: str, step: str = "") -> list:
    """The models this step may be put on: reachable AND priceable.

    Both halves are needed and each one alone is a different fault.

    * Offer what the app cannot PRICE and the step silently runs at the top of
      the range, which is an eightfold difference nobody would guess from
      looking at the number.
    * Offer what the key cannot REACH and you get lee's 404:
      `gemini-2.5-flash` sat in the menu looking available and was not enabled
      on his Google project.

    **It starts from what the key can reach, not from a list written here.**
    That is the fix for the second bug lee found — an OpenRouter menu holding
    exactly one model. The old version intersected the provider's listing with
    the ten slugs written into `coins.RATES`, so a key that could reach two
    hundred models was offered the one that happened to be on both lists. The
    ten are a price table, not a catalogue, and a catalogue is not something
    this app can keep up to date.

    Pricing does not need the catalogue either: `coins.priced` reads through
    the vendor prefix, so `google/gemini-2.5-pro` is priced by the same entry
    as `gemini-2.5-pro`. Anything the table cannot price is left out, which is
    the half of the crossing that still matters.

    **Read text only offers models that can see a picture.** A text-only model
    chosen for OCR is the same 404 one step later, arriving through a different
    door.

    If the crossing comes out EMPTY the written-down list stands. A key with no
    listing permission, a provider answering an unexpected shape, a network
    that is down — none of those mean the person has no models, and an empty
    menu is a step nobody can configure, which is worse than the fault it was
    trying to report.
    """
    from . import coins

    free = (back or "").strip().lower() in coins.FREE_BACKENDS

    def usable(m):
        # The variant rule is about PRICE, so it only applies where there is
        # one. A local tag is full of colons — `qwen2.5:14b-instruct` — and
        # costs nothing whichever one you pick.
        if not free and VARIANT in m:
            return False
        return (coins.priced(m, back)
                and coins.vendor_free(m) not in coins.RETIRED
                and (step != "ocr" or coins.sees(m)))

    known = [m for m in coins.models_for(back) if usable(m)]
    offer = [m for m in _reachable(back, url, key) if usable(m)]
    if not offer:
        return known
    # The table's order first, because it is newest-first and hand-kept, then
    # everything else by name. A menu sorted purely alphabetically opens on the
    # oldest model in the range, which is the one nobody wants and the one that
    # gets picked by accident.
    rank = {m: i for i, m in enumerate(coins.models_for(back))}
    return sorted(offer, key=lambda m: (rank.get(m, len(rank)), m))


# The last resort, for a project.json old enough to be missing the keys
# entirely. Every project made since carries its own — `Project.settings` is
# where the defaults live and where the screen reads them from, and these have
# to agree with those, which a test holds.
#
# They exist at all because a step with no model would be a step the price
# screen could not name, and naming what each step will run on is the whole
# point of these three boxes. lee: *"the coins shou look at what ai is in each
# of teh step to use to bill"*.
STEP_DEFAULTS = {
    "ocr": ("gemini", "gemini-3.5-flash-lite"),
    "translate": ("gemini", "gemini-3.6-flash"),
    "proofread": ("anthropic", "claude-sonnet-5"),
}


def _ctx_from_settings(p: Project, step: str = "") -> None:
    """Point the context at the model this STEP will use.

    The step decides everything: which provider, which model, which address,
    which key. There is no project-wide engine sitting behind it any more —
    there were two of them, they answered the same question as these boxes,
    and a price quoted against the wrong one of the two is a price for a model
    the step was never going to call.

    A step nobody has configured falls back to `STEP_DEFAULTS`, which is a
    default and not a setting: it is the same for every project, so it cannot
    drift out of step with what the screen shows.
    """
    s = p.settings
    p.ctx.medium = s.get("medium") or "manga"
    p.ctx.source = s.get("source") or ""
    p.ctx.target = s.get("target") or "en"
    # Gemini's own safety thresholds, per project. "" is Google's default;
    # "OFF" turns the four configurable categories down as far as the API
    # allows. It is only ever sent to Google, and Google's protections against
    # core harms are not configurable and stay on regardless — a page can
    # still come back refused, and now it says so instead of failing on a
    # schema error two retries later.
    p.ctx.safety = "OFF" if s.get("gemini_safety_off") else ""
    # The story switches. Read on every step because they change what is SENT
    # as well as what is kept, and a setting toggled between two runs has to
    # bite on the second one. Default TRUE, so a project.json written before
    # they existed behaves exactly as it did.
    p.ctx.story = s.get("story", True) is not False
    p.ctx.learn_characters = s.get("learn_characters", True) is not False
    p.ctx.learn_terms = s.get("learn_terms", True) is not False
    p.ctx.name_speakers = s.get("name_speakers", True) is not False

    back, model = STEP_DEFAULTS.get(step, STEP_DEFAULTS["translate"])
    if step not in AI_STEPS:
        # Not an AI step, so there is nothing it will call. The context is
        # still filled in — plenty of code reads it — but with the defaults
        # rather than with some other step's engine.
        p.ctx.backend, p.ctx.model = back, model
        p.ctx.base_url, p.ctx.api_key = "", ""
        return
    p.ctx.backend = (s.get(f"{step}_backend") or "").strip() or back
    p.ctx.model = (s.get(f"{step}_model") or "").strip() or model
    p.ctx.base_url = (s.get(f"{step}_base_url") or "").strip()
    # One key per SERVICE. See `key_for` — the service box is the answer and
    # the step's own box is only a leftover to fall back on.
    p.ctx.api_key = key_for(p, p.ctx.backend, step)


def do_proofread(p: Project, i: int) -> None:
    """The AI re-reads the page's English against the Japanese: lines that do
    not make sense get fixed, and character names are rewritten to exactly
    what the settings sheet says. Works on the stored records directly —
    proofreading needs text, not masks — so flags survive.
    """
    from .translate import proofread_page, match_known
    from .models import TextRegion

    recs = p.pages[i].regions
    if not any((r.get("dst_text") or "").strip() for r in recs):
        return                                    # nothing translated yet

    _ctx_from_settings(p, "proofread")
    # The sheet may have been edited by hand in settings since this page was
    # translated — a name corrected, a person renamed. p.ctx.characters is
    # already current (/api/settings replaces it outright), but the speaker
    # labels stored on the regions still say what translation said. Snap them
    # to the sheet's spelling first, so the pronoun check reads the same name
    # the sheet is keyed by instead of missing it by one letter.
    sheet = getattr(p.ctx, "characters", None) or {}
    if sheet:
        for rec in recs:
            sp = (rec.get("speaker") or "").strip()
            if not sp or sp in sheet:
                continue
            canon = match_known(sp, sheet)
            if canon:
                rec["speaker"] = canon
    # What was said on the page before, so the proofreader can tell whether
    # this page's first line actually follows from it. Built the same way
    # translate_page builds it, speakers included.
    p.ctx.previous_page_tail = _page_tail(p, i - 1)
    page = Page(image=np.zeros((p.pages[i].height or 1,
                                p.pages[i].width or 1, 3), np.uint8))
    page.regions = [
        TextRegion(id=r["id"], bbox=tuple(r["bbox"]),
                   kind=r.get("kind", "bubble"), order=r.get("order", -1),
                   # speaker drives the pronoun check, link marks the halves
                   # of a split sentence — without them the proofreader is
                   # working blind on both
                   speaker=r.get("speaker") or None,
                   link=int(r.get("link") or 0),
                   src_text=r.get("src_text") or "",
                   dst_text=r.get("dst_text") or "")
        for r in recs]
    data = proofread_page(page, ctx=p.ctx) or {}

    by_id = {r.id: r for r in page.regions}
    changed: set[int] = set()
    flagged: set[int] = set()
    for rec in recs:
        tr = by_id.get(rec["id"])
        if tr is None or not (rec.get("dst_text") or "").strip():
            continue
        if tr.dst_text and tr.dst_text != rec["dst_text"]:
            changed.add(int(rec["id"]))
            # the wording changed: stale typesetting must not outrank it
            rec["dst_text"] = tr.dst_text
            rec["layout"] = None
            ov = dict(rec.get("layout_override") or {})
            for k in ("lines", "fit", "wrap", "snug"):
                ov.pop(k, None)
            rec["layout_override"] = ov or None
        # a spelling the enforcement pass would not decide by itself
        if tr.flagged:
            rec["flagged"] = tr.flagged
            flagged.add(int(rec["id"]))
        rec["proofread"] = True

    # What the proofreader could not fix belongs somewhere a person will read
    # it, and a page has no other place to put a remark of its own.
    # Set unconditionally: a clean re-run has to be able to CLEAR the previous
    # run's remark, or a note stays on screen after the thing it described has
    # been fixed.
    p.pages[i].note = str(data.get("page_notes") or "").strip()
    # WHICH boxes the remark is about. lee, on a note reading "replaced the
    # honorific Onee-sama": *"this shoud tell which region is the chnage done
    # to"*. The model's own prose may or may not name a region, and when it does
    # it uses ids the person never sees; this is the factual list — every box
    # whose wording this run actually changed, plus any it flagged — worked out
    # here rather than asked for.
    p.pages[i].note_ids = sorted(changed | flagged)
    invalidate_page(i)


def _page_tail(p: Project, i: int, n: int = 6) -> list:
    """The last few translated lines of page i, each tagged with its speaker."""
    if i < 0 or i >= len(p.pages):
        return []
    out = []
    for r in sorted(p.pages[i].regions, key=lambda r: r.get("order", 0)):
        t = (r.get("dst_text") or "").strip()
        if not t:
            continue
        sp = (r.get("speaker") or "").strip()
        out.append(f"{sp}: {t}" if sp else t)
    return out[-n:]


# ------------------------------------------------------------- proofread report
#
# The proofread, as something you can read away from the editor. Three sections,
# in this order on purpose: what still wants a human, then what only the whole
# chapter can see, then the script itself. Hunting the problems out of the script
# is the wrong way round — the problems are the short list and the script is the
# reference you check them against.
#
# The middle section is the point. Every other check in this program runs on one
# page, and a page cannot notice that it spells a name differently from page 30,
# or that it is the only page in the chapter that left an honorific attached.
# Here the whole chapter is in hand, so those are cheap.

_HONORIFICS = ("sama", "san", "chan", "kun", "senpai", "sensei", "dono",
               "nee", "nii", "tan", "senpai")


def _md_block(label: str, text: str, pad: str = "   ") -> list:
    """A labelled field that may hold several typeset lines.

    Bubbles break their text across lines and those breaks are worth keeping —
    but a bare newline inside a markdown list item silently swallows the break
    and runs the lines together. Continuations are indented and the line before
    each gets the two trailing spaces that make a hard break.
    """
    ls = str(text or "").split("\n")
    out = [f"{pad}- {label}: {ls[0]}"]
    for extra in ls[1:]:
        out[-1] += "  "
        out.append(f"{pad}  {extra}")
    return out


def _refs(where: list, cap: int = 6) -> str:
    """`p8 l9, p32 l3` — short enough to sit at the end of a line."""
    shown = ", ".join(f"p{a} l{b}" for a, b in where[:cap])
    return shown + (f" (+{len(where) - cap} more)" if len(where) > cap else "")


def _chapter_audit(p: Project, said: list) -> list:
    """Checks that only exist once every page is in hand. `said` is a list of
    (page number, line number, region, English) across the whole chapter."""
    import re as _re
    from .translate import (canon_name, match_known, observed_lowercase,
                            _COMMON_CAPS, _TITLE_WORDS)

    out: list[str] = []
    lower = observed_lowercase([t for _, _, _, t in said])

    # One person, two spellings. Folded the same way the enforcement pass folds
    # them, so this catches drift in names the character sheet never knew about
    # — which is most of the ones that drift.
    forms: dict = {}
    for pg, ln, _r, t in said:
        for w in _re.findall(r"[A-Za-z]+", t):
            lw = w.lower()
            if (len(w) < 3 or not w[:1].isupper()
                    or lw in _COMMON_CAPS or lw in _TITLE_WORDS or lw in lower):
                continue
            c = canon_name(w)
            if c:
                forms.setdefault(c, {}).setdefault(lw, [w, []])[1].append((pg, ln))
    drift = {c: d for c, d in forms.items() if len(d) > 1}
    if drift:
        out.append("**The same name spelled more than one way.** The reading "
                   "order decides which is right; the report will not guess.")
        out.append("")
        for c in sorted(drift):
            bits = sorted(drift[c].values(), key=lambda v: -len(v[1]))
            out.append("- " + " · ".join(
                f"**{surf}** ×{len(where)} ({_refs(where, 4)})"
                for surf, where in bits))
        out.append("")

    # A Japanese honorific left welded to a name in the English. Only worth
    # raising when the chapter has clearly decided NOT to keep them — if every
    # other line does the same thing, it is the house style, not a mistake.
    pat = _re.compile(r"\b([A-Z][A-Za-z]+)[-‐‑‒–]("
                      + "|".join(_HONORIFICS) + r")\b", _re.I)
    leaks = [(pg, ln, m.group(0))
             for pg, ln, _r, t in said for m in pat.finditer(t)]
    if leaks and len(leaks) <= max(3, len(said) // 20):
        out.append("**A Japanese honorific left on a name**, in a chapter that "
                   "drops them everywhere else.")
        out.append("")
        for pg, ln, hit in leaks[:12]:
            out.append(f"- p{pg} l{ln} — `{hit}`")
        out.append("")

    # A speaker label the sheet cannot account for. The pronoun check is keyed
    # by the sheet, so these lines were proofread without one.
    sheet = getattr(p.ctx, "characters", None) or {}
    if sheet:
        unknown: dict = {}
        for pg, ln, r, _t in said:
            sp = (r.get("speaker") or "").strip()
            if sp and not match_known(sp, sheet):
                unknown.setdefault(sp, []).append((pg, ln))
        if unknown:
            out.append("**Speakers the character sheet does not have.** Their "
                       "lines got no pronoun check — add them in Settings and "
                       "proofread again, or leave them if they are extras.")
            out.append("")
            for sp in sorted(unknown, key=lambda s: -len(unknown[s])):
                out.append(f"- **{sp}** ×{len(unknown[sp])} "
                           f"({_refs(unknown[sp], 4)})")
            out.append("")

    # Read but never translated. Easy to miss in the script, where the page just
    # is not there.
    miss = []
    for i, st in enumerate(p.pages):
        n = sum(1 for r in st.regions
                if (r.get("src_text") or "").strip()
                and not (r.get("dst_text") or "").strip())
        if n:
            miss.append(f"- Page {i + 1} — {st.name}: {n} line"
                        f"{'' if n == 1 else 's'} read but not translated")
    if miss:
        out.append("**Text that never got translated.**")
        out.append("")
        out += miss
        out.append("")
    return out


def proofread_report(p: Project) -> dict:
    """The markdown report, plus the counts the toast reports."""
    todo: list[str] = []
    body: list[str] = []
    said: list = []
    done = blank = total = 0

    for i, st in enumerate(p.pages):
        regs = sorted(st.regions, key=lambda r: r.get("order", 0))
        regs = [r for r in regs if (r.get("dst_text") or "").strip()]
        if not regs:
            blank += 1
            continue
        total += len(regs)
        pf = all(r.get("proofread") for r in regs)
        done += 1 if pf else 0
        body.append(f"### Page {i + 1} — {st.name}"
                    + ("" if pf else "   *(not proofread yet)*"))
        body.append("")
        note = str(getattr(st, "note", "") or "").strip()
        if note:
            body.append(f"> **Proofreader:** {note}")
            body.append("")
            todo.append(f"- **Page {i + 1}** — {note}")
        for n, r in enumerate(regs, 1):
            sp = (r.get("speaker") or "").strip()
            en = r.get("dst_text", "") or ""
            said.append((i + 1, n, r, en))
            # The region id is printed because the proofreader's own notes talk
            # in ids ("region 4"), while the script counts lines down the page.
            # Without both numbers a note cannot be traced to the line it is
            # about.
            body.append(f"{n}. [{r.get('kind') or 'bubble'}]"
                        + (f" **{sp}**" if sp else "")
                        + f" · region {r.get('id')}")
            body += _md_block("JP", r.get("src_text", "") or "")
            body += _md_block("EN", en)
            fl = str(r.get("flagged") or "").strip()
            if fl:
                body.append(f"   - ⚠ {fl}")
                todo.append(f"- **Page {i + 1}**, line {n} (region "
                            f"{r.get('id')}{', ' + sp if sp else ''}) — {fl}\n"
                            f"  - {en}")
        body.append("")

    audit = _chapter_audit(p, said)
    name = os.path.basename(
        (p.input_dir or p.output_dir).rstrip("/\\")) or "chapter"

    lines = [f"# Proofread report — {name}", ""]
    lines.append(f"{total} translated line{'' if total == 1 else 's'} across "
                 f"{done} proofread page{'' if done == 1 else 's'}."
                 + (f" {blank} page{'' if blank == 1 else 's'} had no "
                    f"translated text and {'is' if blank == 1 else 'are'} not "
                    f"listed below." if blank else ""))
    lines.append("")
    if todo:
        lines += ["## Still wants a look", "",
                  "What could not be settled on the page it appears on — a "
                  "pronoun with no clear owner, a name one letter from somebody "
                  "on the sheet, a line whose original looks misread. Flags "
                  "raised earlier in the pipeline (reading, translating) are "
                  "carried through here too.", ""]
        lines += todo
        lines.append("")
    else:
        lines += ["Nothing was left flagged.", ""]
    if audit:
        lines += ["## Across the whole chapter", "",
                  "Things no single page can see, because each page is "
                  "proofread on its own and looks consistent with itself.", ""]
        lines += audit
    lines += ["## Script", ""]
    lines += body
    return {"name": name, "flags": len(todo),
            "audit": max(0, len(audit)), "text": "\n".join(lines)}


def set_translation(rec: dict, text: str) -> None:
    """Put new words in a box and throw away what was true of the old ones.

    lee: a translation file *"should override current text"*. Overriding is
    more than assigning the string — the layout was computed for the old
    wording, the proofread tick was given to the old wording, and any lines
    typed by hand into the override ARE the old wording. All of that goes.
    What survives is the styling: the face, the colours, the frame somebody
    dragged to where they wanted it.
    """
    # Same door the model's own output comes through: a translations file is
    # very often a machine's, and an ellipsis on the front of a line the
    # Japanese does not open with is a pause the page never drew.
    from .translate import strip_added_ellipsis
    rec["dst_text"] = strip_added_ellipsis(
        typeset_mod.normalize_text(str(text or "").strip()),
        str(rec.get("src_text") or ""))
    rec.pop("proofread", None)              # new text: nobody has read it yet
    # A box lee drew himself has no detection to fall back on: its frame is
    # the only record of where it is, so dropping the layout outright would
    # lose the box. Keep the frame, drop the typesetting.
    keep = None
    if rec.get("own_text"):
        keep = list((rec.get("layout") or {}).get("frame") or []) or None
    rec["layout"] = ({"lines": [], "frame": keep,
                      "font_size": (rec.get("layout") or {}).get("font_size"),
                      "leading": (rec.get("layout") or {}).get("leading")}
                     if keep else None)
    ov = rec.get("layout_override")
    if isinstance(ov, dict):
        for k in ("lines", "fit", "wrap", "snug"):
            ov.pop(k, None)
        if not ov:
            rec["layout_override"] = None


def import_translation(p: Project, text: str) -> dict:
    """A filled-in template back in. Returns what landed and what did not.

    Lines find their boxes by page name and the number printed on the box
    sheet, not by region id — the id is an internal thing a person filling in
    a text file should never have to look at, and the numbers are what they
    can see on the page in front of them.
    """
    from . import manual
    pairs = manual.read(text)
    if not pairs:
        return {"pages": 0, "regions": 0, "missing": [],
                "error": "Nothing to import — no filled-in blocks in that file."}

    # page name -> index, forgiving about case and about a path having been
    # pasted in place of the bare name.
    by_name: dict[str, int] = {}
    for i, st in enumerate(p.pages):
        for key in (st.name, os.path.basename(st.name),
                    os.path.splitext(os.path.basename(st.name))[0]):
            by_name.setdefault(str(key).lower(), i)

    missing: list[str] = []
    touched: set[int] = set()
    n_regions = 0
    for name, n, eng in pairs:
        i = by_name.get(str(name).lower())
        if i is None:
            i = by_name.get(os.path.basename(str(name)).lower())
        if i is None:
            missing.append(f"{name} #{n}: no such page")
            continue
        rows = dict(manual._boxes(p.pages[i]))
        rec = rows.get(n)
        if rec is None:
            missing.append(f"{name} #{n}: page has no box {n}")
            continue
        set_translation(rec, eng)
        n_regions += 1
        touched.add(i)

    if not n_regions:
        return {"pages": 0, "regions": 0, "missing": missing,
                "error": "None of those labels matched a box on this chapter."}
    p.save()
    _page_cache.clear()
    _invalidate_renders()
    if touched:
        run_job(p, "Laying out text", sorted(touched),
                lambda i: do_typeset(p, i, reset=False))
    return {"pages": len(touched), "regions": n_regions, "missing": missing,
            "typeset_started": len(touched)}


# --------------------------------------------------------------------- routing

class Handler(BaseHTTPRequestHandler):
    server_version = "mangatl"

    def log_message(self, *a):  # quiet
        pass

    # -- plumbing

    # The client having gone is not an error. A browser abandons requests all
    # the time — a page reload, a fetch superseded by the next one, a tab
    # closed — and the answer is then written to a socket nobody is holding.
    # It used to raise, print a full traceback, and then the handler's own
    # `except` tried to write a 500 down the SAME dead socket, which raised
    # again and took the connection thread out noisily. Two tracebacks a piece,
    # tens of them a minute, burying anything real that happened to be in the
    # log. lee's paste of it is 300 lines of this and nothing else.
    GONE = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)

    def _send(self, code: int, body: bytes, ctype: str,
              cache: str = "no-store", filename: str = "") -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            if filename:
                # A file to keep, not a page to look at. Without this the
                # browser shows the template as a wall of text and the person
                # has to save it themselves.
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)
        except self.GONE:
            # Whoever asked is not there to be told. Mark the connection so
            # nothing else tries to write to it and let the request end.
            self.close_connection = True
            self._client_gone = True

    # A page image whose URL carries the key from _render_key names exactly
    # one picture forever: if the page changes, so does the URL. Everything
    # else on this server stays no-store, because everything else is live.
    IMMUTABLE = "public, max-age=31536000, immutable"

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _static(self, rel: str) -> None:
        rel = posixpath.normpath(rel).lstrip("/")
        path = os.path.join(STATIC, rel)
        if not os.path.abspath(path).startswith(os.path.abspath(STATIC)) \
                or not os.path.isfile(path):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # -- GET
    def do_GET(self):
        p = PROJECT
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        try:
            if path in ("/", "/index.html"):
                return self._static("editor.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/project":
                return self._json(p.summary())
            if path == "/api/queue":
                return self._json({"ok": True, **queue_state()})

            if path == "/api/coins":
                # The purse, and what this chapter would cost at today's
                # models. The prices go with the balance in one answer because
                # they are read together — the panel shows both — and because
                # a price quoted from a different moment than the balance is
                # how a screen comes to say you can afford something you
                # cannot.
                from . import coins
                # `pages` picks a subset — the pages a scoped run would touch —
                # and `page` prices one on its own for "This page only".
                #
                # Priced HERE and not on the screen, both of them. A price is
                # whole coins rounded up once over the run, so it cannot be
                # assembled out of per-page numbers the screen adds together:
                # twenty-three pages rounded up one at a time is twenty-three
                # coins whatever is on them, which is the flat rate lee
                # explicitly did not want.
                idx = _page_list(p, q.get("pages", [""])[0], whole=True)
                one = _page_list(p, q.get("page", [""])[0])
                # Which steps are running a model nobody has priced. They
                # are charged at the dearest rate on the list, which is the
                # right fallback and an eightfold difference nobody would
                # guess from the number — so it is said out loud.
                unpriced = sorted(
                    s for s in PAID_STEPS if s != "clean"
                    and not coins.priced(*step_engine(p, s)))
                return self._json({
                    **coins.state(),
                    "prices": {s: quote_run(p, s, idx) for s in PAID_STEPS},
                    "one": {s: quote_run(p, s, one) for s in PAID_STEPS},
                    "unpriced": unpriced,
                    "models": {s: step_engine(p, s)[0] for s in PAID_STEPS
                               if s != "clean"},
                    "pages": len(idx),
                    "boxes": sum(page_boxes(p, i) for i in idx),
                })

            if path == "/api/job":
                # The job's own error stops a run; a cleaner that refuses does
                # not — the run finishes, page after page, quietly worse. The
                # warning rides along with the job so the same bar says both.
                j = dict(p.job)
                if (p.job.get("label") or "") == "Cleaning" \
                        and not p.job.get("running"):
                    r = clean_report(p)
                    if r:
                        j["info"] = r
                w = clean_warning(p)
                if w:
                    j["warn"] = w                     # something actually failed
                elif (p.job.get("label") or "") == "Cleaning" \
                        and not p.job.get("running"):
                    # "Nothing was sent to the model" is NOT a fault: on "AI for
                    # hard areas" a page of plain bubbles has nothing hard on it,
                    # and a page whose plate was already built is not sent again.
                    # It went in the warning channel at first and read as a
                    # breakage — lee, with a working token: *"its saying the ai
                    # did not run"*. It is a remark, so it goes with the remarks.
                    note = clean_note(p)
                    if note:
                        j["info"] = ((j.get("info", "") + " ") + note).strip()
                # The queue rides along with the job so the button on the bar
                # updates from the same poll the bar already makes.
                j["queue"] = queue_state()
                return self._json(j)
            if path == "/api/warm":
                # How far the background page-builder has got. The pages tab
                # uses it to say which pages are ready without asking for one.
                return self._json(dict(_warm))
            if path == "/api/exported":
                d = export_root(p)
                names = sorted(os.listdir(d)) if os.path.isdir(d) else []
                if not p.settings.get("exported"):
                    # Files left in the folder by an earlier chapter are not
                    # this one's results.
                    names = []
                return self._json({"dir": d, "files": [
                    {"name": n, "index": next(
                        (i for i, s2 in enumerate(p.pages)
                         if os.path.splitext(s2.name)[0] == os.path.splitext(n)[0]),
                        -1)}
                    for n in names if n.lower().endswith((".png", ".jpg"))]})

            if path == "/api/translations_json":
                # Everything translated, as plain JSON — one entry per region
                # with its Japanese and English, in reading order.
                pages = []
                for i, st in enumerate(p.pages):
                    regs = [{
                        "id": r["id"], "order": r.get("order"),
                        "kind": r.get("kind"),
                        "japanese": r.get("src_text", ""),
                        "english": r.get("dst_text", ""),
                        "speaker": r.get("speaker"),
                    } for r in sorted(st.active,
                                      key=lambda r: r.get("order", 0))]
                    pages.append({"page": i + 1, "name": st.name, "regions": regs})
                return self._json({"pages": pages})

            if path == "/api/proofread_report":
                return self._json(proofread_report(p))

            if path == "/api/translation_template":
                # The file to translate into by hand. lee: *"a manual
                # translation mode that allows download a txt template with
                # the boxes labeled"*. `pages=` takes 1-based page numbers so
                # a person can do the chapter a few pages at a time.
                from . import manual
                idxs = None
                raw = (q.get("pages") or [""])[0].strip()
                if raw:
                    idxs = []
                    for part in raw.replace(" ", "").split(","):
                        try:
                            n = int(part)
                        except ValueError:
                            continue
                        if 1 <= n <= len(p.pages):
                            idxs.append(n - 1)
                stem = os.path.basename(
                    (p.input_dir or p.output_dir).rstrip("/\\")) or "chapter"
                if (q.get("fmt") or ["txt"])[0].lower() == "json":
                    data = json.dumps(manual.template_json(p, idxs),
                                      ensure_ascii=False, indent=2)
                    return self._send(200, data.encode("utf-8"),
                                      "application/json; charset=utf-8",
                                      filename=f"{stem}-translation.json")
                return self._send(200, manual.template(p, idxs).encode("utf-8"),
                                  "text/plain; charset=utf-8",
                                  filename=f"{stem}-translation.txt")

            if path == "/api/export_zip":
                import io
                import zipfile
                d = export_root(p)
                if not os.path.isdir(d):
                    return self._json({"error": "nothing exported yet"}, 404)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for fn in sorted(os.listdir(d)):
                        if fn.lower().endswith((".png", ".jpg")):
                            z.write(os.path.join(d, fn), fn)
                data = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="'
                                 f'{os.path.basename(d)}.zip"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)

            if path == "/api/project_file":
                # The whole chapter in one file. lee: *"when ii load this
                # project file it shoud be excaty as it it now"* — so it
                # carries the pages, the boxes, both languages, the layouts,
                # the paint, the hand-cleaned plates, the custom box types and
                # the faces it typesets in, which live outside the project
                # folder and would otherwise be the one thing that did not
                # travel. See bundle.py.
                from . import bundle
                p.save()
                data = bundle.write(p._state(), p.output_dir)
                return self._send(200, data, "application/zip",
                                  filename=_project_name(p) + bundle.EXT)

            if path == "/api/can_browse":
                from .pickdir import available
                return self._json({"ok": available()})

            if path == "/api/suggest_dirs":
                home = os.path.expanduser("~")
                cands = [p.output_dir, home,
                         os.path.join(home, "Desktop"),
                         os.path.join(home, "Downloads"),
                         os.path.join(home, "Documents")]
                return self._json({"dirs": [c for c in cands if os.path.isdir(c)],
                                   "current": p.settings.get("export_dir")
                                   or p.output_dir,
                                   "name": p.settings.get("export_name")
                                   or "pages"})

            if path.startswith("/exported/"):
                fn = os.path.basename(urllib.parse.unquote(path[len("/exported/"):]))
                fp = os.path.join(export_root(p), fn)
                if not os.path.isfile(fp):
                    return self._send(404, b"not found", "text/plain")
                with open(fp, "rb") as fh:
                    return self._send(200, fh.read(), "image/png")

            if path == "/fontfile":
                # Serve one specific font for the live preview. Only fonts the
                # app itself offers can be fetched — this is not a file reader.
                fp = (q.get("p") or [""])[0]
                cfg = _typeset_cfg(p)
                ok = {f["path"] for f in find_fonts()}
                ok |= {v for v in ([cfg.font_path]
                                   + list((cfg.fonts or {}).values())) if v}
                if fp not in ok or not os.path.isfile(fp):
                    return self._send(404, b"no font", "text/plain")
                with open(fp, "rb") as fh:
                    return self._send(200, fh.read(), "font/ttf")

            if path == "/fontsample":
                # A tiny PNG of the word "sample" rendered IN the font, made
                # server-side with the actual file. The font dropdowns show
                # this image, so the preview can't fail on browser font
                # loading (which was unreliable across setups).
                fp = (q.get("p") or [""])[0]
                cfg = _typeset_cfg(p)
                ok = {f["path"] for f in find_fonts()}
                ok |= {v for v in ([cfg.font_path]
                                   + list((cfg.fonts or {}).values())) if v}
                if fp not in ok or not os.path.isfile(fp):
                    return self._send(404, b"no font", "text/plain")
                png = _font_sample_png(fp, (q.get("t") or ["sample"])[0])
                if png is None:
                    return self._send(404, b"no sample", "text/plain")
                return self._send(200, png, "image/png")

            m = re.fullmatch(r"/font/([a-z]+)", path)
            if m:
                cfg = _typeset_cfg(p)
                fp = typeset_mod.font_for(cfg, m.group(1))
                if not fp or not os.path.isfile(fp):
                    return self._send(404, b"no font", "text/plain")
                with open(fp, "rb") as fh:
                    return self._send(200, fh.read(), "font/ttf")

            if path.startswith("/font/"):
                kind = path[len("/font/"):] or "bubble"
                cfg = _typeset_cfg(p)
                fp = typeset_mod.font_for(cfg, kind) or cfg.font_path
                if not os.path.isfile(fp):
                    return self._send(404, b"no font", "text/plain")
                with open(fp, "rb") as fh:
                    return self._send(200, fh.read(), "font/ttf")

            if path == "/api/fonts":
                # `recent` is sent with the list, not asked for separately: the
                # picker needs both to draw one menu, and two round trips means
                # the list can render before the recents and jump.
                return self._json({"fonts": find_fonts(),
                                   "recent": userdata.recent_fonts(),
                                   "uploaded": userdata.uploaded_fonts()})

            if path == "/api/translate_request":
                # The exact request the translator would send, as a download —
                # so it can be run through any AI of the person's choosing.
                from .translate import (build_system, SCHEMA_HINT,
                                        MEDIA, TARGETS)
                s = p.settings
                p.ctx.medium = s.get("medium") or "manga"
                p.ctx.source = s.get("source") or ""
                p.ctx.target = s.get("target") or "en"
                ctx = p.ctx
                from .translate import source_language
                idxs = range(len(p.pages))
                if q.get("pages"):
                    idxs = [int(v) for v in q["pages"][0].split(",")
                            if v.strip().isdigit() and int(v) < len(p.pages)]
                pages = []
                for i in idxs:
                    st = p.pages[i]
                    regs = [r for r in sorted(
                                st.regions, key=lambda r: r.get("order", 0))
                            if (r.get("src_text") or "").strip()]
                    if not regs:
                        continue
                    pages.append({"page_index": i, "page_name": st.name,
                                  "request": {
                        "medium": ctx.medium,
                        "source_language": source_language(
                            ctx.medium, s.get("source") or ""),
                        "target_language": TARGETS.get(ctx.target, "English"),
                        "series_context": ctx.synopsis,
                        "glossary": ctx.glossary,
                        "characters": dict(getattr(ctx, "characters", {}) or {}),
                        "previous_page_tail": [],
                        "keep_honorifics": ctx.honorifics,
                        "regions": [{"id": r["id"],
                                     "panel": r.get("panel"),
                                     "kind": r["kind"],
                                     "text": r["src_text"],
                                     "src_char_count": len(r["src_text"])}
                                    for r in regs],
                    },
                    "response": None})
                return self._json({
                    "how_to_use": (
                        "For each entry in pages: send 'system' as the system "
                        "prompt, and the page's 'request' object (as JSON) "
                        "followed by 'response_schema' as the user message. "
                        "The AI must answer with JSON matching the schema. "
                        "Put each answer into that page's 'response' slot, "
                        "then upload this same file back with 'Add the AI's "
                        "reply' in the Translate popup — or paste a single "
                        "page's answer there directly. previous_page_tail is "
                        "the last few translated lines of the page before, "
                        "for continuity — fill it in as you go if you like. "
                        "characters is the running character sheet (pronouns "
                        "and voice per name); carry each page's "
                        "character_additions into the next page's request so "
                        "pronouns stay consistent to the last page."),
                    "system": build_system(ctx.medium, ctx.target),
                    "response_schema": SCHEMA_HINT,
                    "pages": pages,
                })

            m = re.fullmatch(r"/api/page/(\d+)", path)
            if m:
                i = int(m.group(1))
                # Viewing a page must not detect anything. This was the last
                # place detection still happened on its own.
                return self._json({
                    "index": i, "name": p.pages[i].name,
                    "width": p.pages[i].width, "height": p.pages[i].height,
                    "regions": p.pages[i].active,
                    # which of the three groups this page has boxes for, and
                    # which of them are put away — the switches in the Current
                    # page card are built from exactly these two lists
                    "kinds": p.pages[i].groups_present,
                    "hidden": list(getattr(p.pages[i], "hidden_kinds", []) or []),
                    # The boxes put away one at a time. They are NOT in
                    # `regions` — a hidden box takes no part in the page's work
                    # — but the list has to be able to show a closed eye you
                    # can click again, so it gets the little it needs to draw
                    # the row and nothing else.
                    "hidden_ids": [int(v) for v in
                                   (getattr(p.pages[i], "hidden_ids", []) or [])],
                    "hidden_rows": _hidden_rows(p.pages[i]),
                    "hidden_boxes": len(p.pages[i].hidden),
                    "custom_clean": bool(getattr(p.pages[i], "custom_clean", "")),
                    "note": getattr(p.pages[i], "note", "") or "",
                    "note_ids": [int(v) for v in
                                 (getattr(p.pages[i], "note_ids", []) or [])],
                    "paint_layers": getattr(p.pages[i], "paint_layers", []) or [],
                    # what to hang on the image URL so the browser reuses its
                    # copy until the page genuinely changes
                    "vkey": _render_key(p, i),
                    # …and the same for the untouched scan, which cleaning and
                    # typesetting cannot change. Hanging the render key on it too
                    # threw the original out of the browser's cache every time
                    # a page was cleaned, so the side-by-side pane re-downloaded
                    # a whole scan on every page turn and held the editing pane
                    # back while it did.
                    "ikey": _scan_key(p, i),
                })

            m = re.fullmatch(r"/img/(\d+)", path)
            if m:
                i = int(m.group(1))
                img = p.image(i)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                keyed = bool(q.get("v"))
                return self._send(200, buf.tobytes(), "image/jpeg",
                                  self.IMMUTABLE if keyed else "no-store")

            m = re.fullmatch(r"/render/(\d+)", path)
            if m:
                i = int(m.group(1))
                mode = q.get("mode", ["typeset"])[0]
                if mode not in ("original", "clean", "typeset"):
                    mode = "typeset"
                paint = q.get("paint", ["1"])[0] != "0"
                keyed = bool(q.get("v"))
                return self._send(200, render_index(p, i, mode, paint=paint),
                                  "image/jpeg",
                                  self.IMMUTABLE if keyed else "no-store")

            return self._send(404, b"not found", "text/plain")
        except Exception as e:
            if getattr(self, "_client_gone", False):
                return                 # they left; there is nobody to tell
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # -- POST
    def do_POST(self):
        p = PROJECT
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/project_upload":
                # A project file the BROWSER hands over, for when the machine
                # cannot show a file dialog — a headless install, or the
                # editor reached from another computer on the desk. The zip
                # arrives as the raw body rather than base64 inside JSON: a
                # chapter is a hundred megabytes and base64 is a third again
                # on top of that, in memory, twice.
                from . import bundle
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    state = bundle.read(raw, p.output_dir)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json(_adopt(p, state))

            body = self._body()

            if path == "/api/warm":
                # The browser says which page is on screen so the warm-up
                # builds outwards from there — the next page you are going to
                # ask for is the next one it makes.
                try:
                    start = int(body.get("from") or 0)
                except (TypeError, ValueError):
                    start = 0
                start = max(0, min(start, len(p.pages) - 1)) if p.pages else 0
                if not _warm["running"] or body.get("force"):
                    warm_pages(p, start)
                return self._json({"ok": True, "total": len(p.pages)})

            if path == "/api/job/cancel":
                # Ask the running job to stop; it checks between pages.
                if p.job.get("running"):
                    p.job["cancel"] = True
                return self._json({"ok": True})

            if path == "/api/queue":
                # Move a waiting action up or down the line, or drop it. What
                # is RUNNING is not in the line: it is stopped with Cancel,
                # which has to interrupt a page rather than decline to start.
                ok = False
                if "cancel" in body:
                    ok = queue_drop(int(body.get("cancel") or 0))
                elif "clear" in body:
                    ok = queue_clear() > 0
                elif "move" in body:
                    m = body.get("move") or {}
                    ok = queue_move(int(m.get("qid") or 0),
                                    1 if int(m.get("dir") or 0) > 0 else -1)
                return self._json({"ok": ok, **queue_state()})

            if path == "/api/translation_import":
                # The filled-in template back. TXT or JSON, whichever it is —
                # and whatever is in it wins over what the box says now.
                return self._json(import_translation(p, body.get("text") or ""))

            if path == "/api/translate_response":
                # The other half of "use your own AI": the reply comes back
                # here. Accepts the whole request file with 'response' slots
                # filled in, a list of page answers, or one page's answer.
                from .translate import _extract_json
                data = body.get("data")
                if isinstance(data, str):
                    try:
                        data = _extract_json(data)
                    except Exception as e:
                        return self._json(
                            {"error": f"Could not read that as JSON: {e}"})
                fallback = body.get("fallback_page")
                if isinstance(data, dict) and isinstance(data.get("pages"), list):
                    entries = data["pages"]
                elif isinstance(data, list):
                    entries = data
                elif isinstance(data, dict):
                    entries = [data]
                else:
                    return self._json({"error": "Unrecognised reply format."})
                n_pages = n_regions = 0
                missing = []
                gloss = {}
                char_adds: dict = {}
                touched: set[int] = set()
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    resp = e.get("response") if isinstance(e.get("response"),
                                                           dict) else e
                    if not isinstance(resp, dict):
                        continue                 # template slot left empty
                    items = resp.get("regions")
                    if not isinstance(items, list):
                        continue
                    idx = e.get("page_index", resp.get("page_index", fallback))
                    try:
                        idx = int(idx)
                    except (TypeError, ValueError):
                        continue
                    if not 0 <= idx < len(p.pages):
                        continue
                    recs = {r["id"]: r for r in p.pages[idx].regions}
                    n = 0
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        try:
                            rid = int(item.get("id"))
                        except (TypeError, ValueError):
                            continue
                        r = recs.get(rid)
                        if r is None:
                            missing.append(f"page {idx + 1} id {rid}")
                            continue
                        # An uploaded reply REPLACES the current translation:
                        # the stale layout goes, and hand-edited LINES are
                        # dropped from the override (they are the old
                        # wording) — styling survives. Same rule as a
                        # hand-written translation file coming in.
                        set_translation(r, item.get("translation"))
                        if item.get("speaker") is not None:
                            r["speaker"] = str(item["speaker"])
                        # Only judge confidence when the AI actually gave one —
                        # a missing field is not a bad translation.
                        if item.get("confidence") not in (None, ""):
                            try:
                                conf = float(item["confidence"])
                                r["confidence"] = conf
                                if conf < 0.5:
                                    r["flagged"] = ((r.get("flagged") or "")
                                        + " low translation confidence").strip()
                            except (TypeError, ValueError):
                                pass
                        n += 1
                    if n:
                        n_pages += 1
                        n_regions += n
                        touched.add(idx)
                    g = resp.get("glossary_additions")
                    if isinstance(g, dict):
                        gloss.update({str(k): str(v) for k, v in g.items()})
                    ch = resp.get("character_additions")
                    if isinstance(ch, dict):
                        # Held back until every page in the upload has landed —
                        # a character named on page 3 is evidence for page 2.
                        char_adds.update({str(k): str(v) for k, v in ch.items()})
                if not n_regions:
                    return self._json({"error":
                        "No matching regions found in that reply. Check the "
                        "'regions' list and its ids."})
                # Same gate the live translator uses, for the glossary as well
                # as the sheet: a term only joins if it says what it is, and a
                # name only joins if the story writes it down somewhere.
                from .translate import (name_evidence, unevidenced,
                                        match_known, merge_characters,
                                        merge_glossary)
                gloss_refused = merge_glossary(p.ctx.glossary, gloss)
                texts = []
                for idx in touched:
                    for r in p.pages[idx].regions:
                        texts.append(str(r.get("dst_text") or ""))
                        texts.append(str(r.get("src_text") or ""))
                evidence = name_evidence(p.ctx, texts)
                for idx in touched:
                    for r in p.pages[idx].regions:
                        sp = str(r.get("speaker") or "")
                        if not sp or _is_generic_speaker(sp):
                            continue
                        # snap a loose spelling of a known person back first —
                        # the sheet counts as evidence, so this never fires if
                        # it is left inside the unevidenced() branch
                        known = match_known(sp, p.ctx.characters or {})
                        if known:
                            r["speaker"] = known
                            continue
                        if unevidenced(sp, evidence):
                            r["flagged"] = ((r.get("flagged") or "")
                                            + f' speaker "{sp}" is not named anywhere'
                                            ).strip()
                refused = merge_characters(p.ctx.characters, char_adds,
                                           evidence, _is_generic_speaker)
                p.save()
                _page_cache.clear()
                _invalidate_renders()
                # …and the pages re-typeset themselves, so the new text is
                # what shows — no stale typesetting left behind.
                if touched:
                    run_job(p, "Laying out text", sorted(touched),
                            lambda i: do_typeset(p, i, reset=False))
                return self._json({"pages": n_pages, "regions": n_regions,
                                   "missing": missing,
                                   "characters_refused": refused,
                                   "glossary_refused": gloss_refused,
                                   "typeset_started": len(touched)})

            if path == "/api/upload":
                import base64
                ok, problems, added_idx = 0, [], []
                for f in body.get("files", []):
                    name = f.get("name", "?")
                    try:
                        raw = base64.b64decode(f["data"].split(",")[-1])
                        idx = p.add_uploaded(name, raw)
                        if idx >= 0:
                            added_idx.append(idx)
                            ok += 1
                        else:
                            problems.append(f"{name}: not a readable image")
                    except Exception as e:
                        problems.append(f"{name}: {type(e).__name__}: {e}")
                p.save()
                return self._json({"added": ok, "pages": len(p.pages),
                                   "indices": added_idx,
                                   "problems": problems[:5]})

            if path == "/api/upload_done":
                # Detection is not automatic: the person chooses what to look
                # for, so loading files just loads files.
                #
                # The one thing that does happen by itself is putting a webtoon
                # back together. A manhwa is drawn as a single strip and served
                # as tiles cut every N pixels by something that has never
                # looked at the artwork — through balloons, through faces and
                # through the middle of the typesetting. Those tiles are not
                # pages, and there is nothing useful to be done with them until
                # they are joined back up, so it happens here rather than being
                # offered as a button nobody would know to press. Settings ▸
                # Language & direction turns it off.
                report = p.restitch_if_sliced()
                warm_pages(p, 0)
                return self._json({"pages": len(p.pages), "detecting": 0,
                                   "strip": report or None})

            if path == "/api/reset":
                from .translate import SeriesContext
                keep = dict(p.settings) if body.get("keep_settings") else None
                # The SERIES CONTENT always clears on a new project — the
                # synopsis, character names, glossary and custom bubble types
                # belong to the story just finished. The technical translation
                # config (backend, model, target, honorifics) carries over so
                # the next chapter does not have to be reconfigured. Export
                # first to keep a series' content for its next chapter.
                old = p.ctx
                p.settings.pop("exported", None)     # a new chapter has not
                p.clear()
                p.ctx = SeriesContext(
                    honorifics=old.honorifics, medium=old.medium,
                    target=old.target, source=old.source,
                    backend=old.backend, base_url=old.base_url,
                    model=old.model, api_key=old.api_key)
                if keep:
                    # Keep how things are configured, but forget where the last
                    # chapter was written and drop the custom bubble types,
                    # which are part of the story's content.
                    keep["export_name"] = "pages"
                    keep["export_dir"] = ""
                    keep.pop("custom_kinds", None)
                    keep.pop("exported", None)
                    p.settings.pop("custom_kinds", None)
                    p.settings.update(keep)
                p.save()
                return self._json({"ok": True})

            if path == "/api/font":
                # Adding, removing, or saying which face was just reached for.
                # All three answer with the same thing — the whole font list —
                # so the browser never has to work out what changed.
                what = body.get("do") or "add"
                err = ""
                if what == "add":
                    import base64
                    for f in (body.get("files") or []):
                        try:
                            userdata.add_font(
                                f.get("name") or "font.ttf",
                                base64.b64decode(f.get("data") or ""))
                        except Exception as e:
                            err = f'{f.get("name") or "that file"}: {e}'
                elif what == "remove":
                    if not userdata.remove_font(body.get("path") or ""):
                        err = "that font is not one of the uploaded ones"
                elif what == "used":
                    userdata.note_font_used(body.get("path") or "")
                if what in ("add", "remove"):
                    # the bundled-folder list is cached for the life of the
                    # process, and a new folder full of faces has just appeared
                    typeset_mod._font_dirs.cache_clear()
                return self._json({"ok": not err, "error": err,
                                   "fonts": find_fonts(),
                                   "recent": userdata.recent_fonts(),
                                   "uploaded": userdata.uploaded_fonts()})

            if path == "/api/models":
                # The names this key can actually use, asked of the provider.
                # Typing a model name by hand is how a chapter dies halfway
                # through with a 404 — providers retire models, and there is
                # nothing in the editor that would tell you.
                step = body.get("step") or ""
                was = (p.ctx.backend, p.ctx.base_url, p.ctx.model,
                       p.ctx.api_key)
                try:
                    _ctx_from_settings(p, step if step in AI_STEPS else "")
                    # a step with no model of its own still has a provider
                    for key, attr in ((f"{step}_backend", "backend"),
                                      (f"{step}_base_url", "base_url")):
                        v = (p.settings.get(key) or "").strip()
                        if v:
                            setattr(p.ctx, attr, v)
                    back, url = p.ctx.backend, p.ctx.base_url
                    # Priced AND reachable — the crossing is the whole point,
                    # and `model_menu` is where it is explained. Offering only
                    # the priced list is what put `gemini-2.5-flash` in front
                    # of lee on a project it was not enabled for.
                    from . import coins
                    names = model_menu(back, url, key_for(p, back, step), step)
                finally:
                    (p.ctx.backend, p.ctx.base_url, p.ctx.model,
                     p.ctx.api_key) = was
                # The answer is written only after the context has been given
                # back. Returning from inside the `try` sent the reply first
                # and restored afterwards, so whatever the editor did next on
                # seeing the list raced the restore and could run on the
                # step's provider instead of the project's.
                return self._json({"models": names,
                                   "priced": [n for n in names
                                              if coins.priced(n, back)]})

            if path == "/api/clean_test":
                # One real call, cache bypassed, with the answer in words —
                # so a 401 can be told apart from a stale deployment without
                # running a whole Clean and without reading the Modal log.
                return self._json(clean_selftest(p))

            if path == "/api/coins":
                # Putting coins in. One endpoint, one direction: there is no
                # way to spend from here and no way to set a balance outright,
                # so the only thing this can do is what a payment would do
                # once there is something to take a payment with.
                from . import account, coins
                add = int(body.get("coins") or 0)
                if add <= 0:
                    return self._json({"error": "how many coins?"}, 400)
                if account.signed_in():
                    # On an account there is no such thing as adding coins from
                    # the machine the app runs on. That is not a restriction
                    # this route imposes — the security rules forbid a client
                    # writing a balance at all — and saying so here is only
                    # saying it before the round trip.
                    return self._json({"error": "Coins are bought on the "
                                       "website. Open Buy coins."}, 400)
                coins.credit(add, str(body.get("what") or "top-up"))
                return self._json({"ok": True, **coins.state()})

            if path == "/api/account":
                # Signing in, from the editor. The password goes to Google and
                # nowhere else — it is not stored, not logged, and not put in
                # the project file. What comes back and is kept is a refresh
                # token, in the person's own folder, 0600.
                from . import account
                do = str(body.get("do") or "")
                try:
                    if do == "signin":
                        account.sign_in(str(body.get("email") or ""),
                                        str(body.get("password") or ""))
                    elif do == "signup":
                        account.sign_up(str(body.get("email") or ""),
                                        str(body.get("password") or ""),
                                        str(body.get("username") or ""))
                    elif do == "signout":
                        account.sign_out()
                    elif do == "name":
                        account.claim_username(str(body.get("username") or ""))
                    elif do == "reset":
                        account.reset_password(str(body.get("email") or ""))
                    else:
                        return self._json({"error": "do what?"}, 400)
                except account.AccountError as e:
                    return self._json({"error": str(e), "code": e.code}, 400)
                from . import coins
                return self._json({"ok": True, **coins.state()})

            if path == "/api/settings":
                new = body.get("settings") or {}
                # A token pasted out of a file or a browser comes with whatever
                # the copy picked up — a trailing newline, a leading space, the
                # quotes around the literal. The endpoint compares the string
                # exactly, so an invisible character is a 401 that looks like
                # "but it's the same token". Strip both, and the quotes, once,
                # here, so what is stored is what was meant.
                # ...and the same for every API key, which arrives the same
                # way and fails the same way. A key pasted with a trailing
                # newline comes back "Please pass a valid API key", which reads
                # as a wrong key rather than as a key with a newline on it.
                # lee: *"RuntimeError: OCR server returned 400 ... Please pass a
                # valid API key"* with the key filled in.
                for k in ("clean_token", "clean_url", "api_key", "base_url",
                          "ocr_key", "translate_key", "proofread_key",
                          "ocr_base_url", "translate_base_url",
                          "proofread_base_url",
                          "key_anthropic", "key_gemini", "key_openrouter"):
                    if isinstance(new.get(k), str):
                        new[k] = new[k].strip().strip('"').strip("'").strip()
                bad = []
                for label, fp in ([("default", new.get("font"))]
                                  + list((new.get("fonts") or {}).items())):
                    # can_typeset, not usable_font: a symbol or icon face opens
                    # perfectly and has no alphabet, and choosing one used to
                    # empty every bubble on the page with nothing said.
                    if fp and not typeset_mod.can_typeset(fp):
                        bad.append(label)
                        # A refused font leaves the working one in place. It
                        # used to clear the setting instead, so one bad pick
                        # ALSO threw away the font that was typesetting the
                        # chapter, and the page changed twice over.
                        if label == "default":
                            new["font"] = p.settings.get("font") or ""
                        else:
                            had = (p.settings.get("fonts") or {}).get(label)
                            if had:
                                new.setdefault("fonts", {})[label] = had
                            else:
                                new.get("fonts", {}).pop(label, None)
                p.settings.update(new)
                if "custom_kinds" in new:
                    # Sub-types arrive from the browser, so what is stored is
                    # checked here rather than trusted: every one lands in a
                    # real family, in a colour that family issues, and no
                    # family goes over its five. The editor's own lookups read
                    # the checked list, not the one that was posted.
                    p.settings["custom_kinds"] = _kinds.migrate(
                        p.settings.get("custom_kinds"))
                    _kinds.use(p.settings["custom_kinds"])
                if any(k.startswith("key_") or k.endswith("_base_url")
                       for k in new):
                    # A key or an address has just changed, so what the
                    # provider said it could reach was said about a different
                    # key. Cached for fifteen minutes, and this is the moment
                    # it would otherwise be most wrong.
                    _MENU_CACHE.clear()
                if "clean_token" in new or "clean_url" in new:
                    # He has just changed the thing the warning complains
                    # about; the next call gets to speak for itself.
                    clear_clean_warning()
                if "title" in body:
                    p.ctx.title = str(body["title"] or "").strip()
                if "synopsis" in body:
                    p.ctx.synopsis = body["synopsis"]
                if "glossary" in body:
                    p.ctx.glossary = body["glossary"]
                if "characters" in body:
                    # The character sheet, edited by hand in settings. This
                    # REPLACES the sheet (unlike character_additions from a
                    # translation reply, which only fills gaps) — the human
                    # editing it is the authority.
                    p.ctx.characters = {
                        str(k).strip(): str(v).strip()
                        for k, v in (body["characters"] or {}).items()
                        if str(k).strip()}
                p.save()
                safe = dict(p.settings)
                safe["api_key"] = "set" if safe.get("api_key") else ""
                for k in AI_STEPS:                    # per-step keys, masked
                    safe[f"{k}_key"] = "set" if safe.get(f"{k}_key") else ""
                for svc, _label in SERVICES:          # service keys, masked
                    safe[f"key_{svc}"] = "set" if safe.get(f"key_{svc}") else ""
                safe["clean_token"] = _token_state(safe.get("clean_token"))
                return self._json({"ok": True, "settings": safe,
                                   "bad_fonts": bad})

            if path == "/api/detect_all":
                # An explicit page list means exactly those pages; otherwise
                # the whole chapter. This branch used to ignore both the list
                # and the chosen kinds, so "this page only" swept all forty
                # pages and the free-text option silently did nothing.
                idx = body.get("pages") or list(range(len(p.pages)))
                kinds = body.get("kinds") or ["bubble"]
                run_job(p, "Detecting", idx, lambda i: p.detect(i, kinds))
                return self._json({"started": len(idx)})

            if path == "/api/ocr_all":
                idx = body.get("pages") or list(range(len(p.pages)))
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts — the price is taken when
                # the button is pressed, so there is no longer such a thing as
                # one that pays for what it can and stops.
                short = needs_key(p, "ocr") or afford_run(p, "ocr", idx)
                if short:
                    return self._json({"error": short}, 402)
                run_job(p, "Reading text", idx, lambda i: do_ocr(p, i), step="ocr")
                return self._json({"started": len(idx)})

            m = re.fullmatch(r"/api/page/(\d+)/heal", path)
            if m:
                # The healing brush: the client sends a small crop of the
                # page and a mask of the painted spot, the AI cleaner redraws
                # what was under the mask, and the patch goes back.
                import base64
                img_b = base64.b64decode((body.get("image") or "").split(",")[-1])
                msk_b = base64.b64decode((body.get("mask") or "").split(",")[-1])
                img = cv2.imdecode(np.frombuffer(img_b, np.uint8),
                                   cv2.IMREAD_COLOR)
                msk = cv2.imdecode(np.frombuffer(msk_b, np.uint8),
                                   cv2.IMREAD_GRAYSCALE)
                if img is None or msk is None or img.shape[:2] != msk.shape[:2]:
                    return self._json({"error": "bad heal payload"}, 400)
                msk = ((msk > 127).astype(np.uint8)) * 255
                # a touch of dilation so the fill reaches past soft edges
                msk = cv2.dilate(msk, np.ones((3, 3), np.uint8))
                # There is ONE healing brush and it is the AI one: the spot
                # goes to the configured cleaner, which REDRAWS what was
                # underneath. That is the only thing that can put back artwork
                # which was never anywhere else on the page.
                #
                # The other brush stood here — a local fill that copied real
                # pixels in from the surroundings, and fell in behind this one
                # whenever the endpoint was down. lee, having used it:
                # *"remoev teh regualr healing brush, its ass"*. So it is gone,
                # and with it the silent fallback: a cleaner that is not set up
                # or not answering now SAYS so, rather than handing back the
                # other brush's work under this brush's name.
                #
                # strict=True so a dead endpoint raises here instead of quietly
                # returning `_ai_clean_call`'s own Telea fill.
                neural, _all = _make_cleaner(p, strict=True)
                if neural is None:
                    return self._json({"error": clean_warning(p) or (
                        "The healing brush needs the AI cleaner. Turn it on "
                        "in Settings \u25b8 Page cleaning and give it an "
                        "address.")}, 400)
                clear_clean_warning()
                try:
                    # the model reconstructs, so a generous mask costs nothing
                    # and a tight one leaves a rim (cf NEURAL_PAD)
                    msk = cv2.dilate(msk, np.ones((5, 5), np.uint8))
                    out = neural(img, msk)
                except Exception:
                    traceback.print_exc()
                    out = None
                if out is None or out.shape != img.shape:
                    return self._json({"error": clean_warning(p) or (
                        "The AI cleaner did not answer.")}, 502)
                # Feather the seam so the patch melts into its surroundings.
                # Grow first, THEN blur: blurring the mask itself puts the
                # ramp half inside the fill, so the outer half of every
                # erased stroke bleeds back through (same fix as _feather).
                a = cv2.dilate(msk, np.ones((5, 5), np.uint8))
                a = cv2.GaussianBlur(a.astype(np.float32) / 255.0,
                                     (0, 0), 1.6)[:, :, None]
                out = (img.astype(np.float32) * (1 - a)
                       + out.astype(np.float32) * a).astype(np.uint8)
                ok, buf = cv2.imencode(".png", out)
                if not ok:
                    return self._json({"error": "encode failed"}, 500)
                return self._json({"how": "ai",
                                   "patch": "data:image/png;base64,"
                                   + base64.b64encode(buf.tobytes()).decode()})

            m = re.fullmatch(r"/api/page/(\d+)/rename", path)
            if m:
                i = int(m.group(1))
                why = p.rename_page(i, str(body.get("name") or ""))
                if why:
                    return self._json({"error": why}, 400)
                # The page is the same picture under a new name, but every
                # cache here is keyed by that name, so what is cached is filed
                # under one that no longer exists.
                _page_cache.clear()
                _invalidate_renders()
                _plate_cache.clear()
                return self._json({"ok": True, "name": p.pages[i].name})

            m = re.fullmatch(r"/api/pages/reorder", path)
            if m:
                order = body.get("order")
                n = len(p.pages)
                if (not isinstance(order, list) or len(order) != n
                        or sorted(order) != list(range(n))):
                    return self._json({"error": "bad order"}, 400)
                p.pages = [p.pages[k] for k in order]
                p.save()
                _page_cache.clear()
                _invalidate_renders()
                _plate_cache.clear()
                return self._json({"ok": True})

            # A text block, as a picture. What comes back is a PNG of just
            # that block's typesetting — cropped to what it actually covers —
            # and where on the page it goes, so the browser can drop it into
            # the paint stack as an ordinary image layer.
            # lee: *"allow me to turn text layer into image layers"*.
            m = re.fullmatch(r"/api/page/(\d+)/region/(\d+)/rasterise", path)
            if m:
                import base64
                i, rid = int(m.group(1)), int(m.group(2))
                if not (0 <= i < len(p.pages)):
                    return self._json({"error": "no such page"}, 404)
                # Built the way the rendered page is built: `materialize`
                # carries no layout — every stage re-fits — so a page taken
                # straight from the cache has nothing on it to draw.
                page = p.materialize(i)
                if not page.regions:
                    return self._json({"error": "nothing to draw"}, 400)
                clean_page(p, i, page)
                cfg = _typeset_cfg(p)
                typeset_mod.typeset_page(page, cfg)
                reg = next((r for r in page.regions if r.id == rid), None)
                if reg is None or not (reg.layout and reg.layout.lines):
                    return self._json({"error": "nothing to draw"}, 400)
                bgra = render_mod.render_page(page, cfg, only={rid}, bare=True)
                ys, xs = np.nonzero(bgra[:, :, 3])
                if xs.size == 0:
                    return self._json({"error": "nothing to draw"}, 400)
                x0, y0 = int(xs.min()), int(ys.min())
                x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
                crop = bgra[y0:y1, x0:x1]
                ok, buf = cv2.imencode(".png", crop)
                if not ok:
                    return self._json({"error": "could not encode"}, 500)
                return self._json({
                    "png": "data:image/png;base64,"
                           + base64.b64encode(buf.tobytes()).decode(),
                    "x": x0, "y": y0,
                    "w": int(x1 - x0), "h": int(y1 - y0),
                    "name": (reg.dst_text or "").strip()[:40]})

            m = re.fullmatch(r"/api/page/(\d+)/paint", path)
            if m:
                # Touch-up strokes travel as a rendered overlay (what the
                # views composite) plus the editable list (what the person
                # gets back when they return to the page).
                import base64
                i = int(m.group(1))
                d = os.path.join(p.output_dir, "paint")
                os.makedirs(d, exist_ok=True)
                dest = os.path.join(d, _page_file_stem(p, i) + ".png")
                # Two overlays: what goes UNDER the typesetting (baked into the
                # plate before it is typeset) and what goes OVER it (composited
                # after). One file each, so a page with nothing above the text
                # costs nothing extra.
                over_dest = os.path.join(d, _page_file_stem(p, i) + "_over.png")
                lays = body.get("layers")
                lays = lays if isinstance(lays, list) else []
                # Decode first, compare, and only then write. Opening a page
                # re-saves its overlay once, to repair one written before the
                # browser learnt to wait for its layers to decode — and a save
                # that changes nothing must cost nothing, because writing the
                # file bumps the render epoch and that throws away every
                # rendered page in the chapter, not just this one.
                want = {}
                for key, path_, attr in (("overlay", dest, "paint_overlay"),
                                         ("overlay_over", over_dest,
                                          "paint_over")):
                    data = (body.get(key) or "")
                    want[key] = (base64.b64decode(data.split(",")[-1])
                                 if data else b"")
                same = (lays == (p.pages[i].paint_layers or []))
                for key, path_, attr in (("overlay", dest, "paint_overlay"),
                                         ("overlay_over", over_dest,
                                          "paint_over")):
                    if not same:
                        break
                    now = getattr(p.pages[i], attr, "") or ""
                    if want[key]:
                        try:
                            with open(path_, "rb") as fh:
                                same = now == path_ and fh.read() == want[key]
                        except OSError:
                            same = False
                    else:
                        same = not now and not os.path.exists(path_)
                if same:
                    return self._json({"ok": True, "unchanged": True})

                for key, path_, attr in (("overlay", dest, "paint_overlay"),
                                         ("overlay_over", over_dest,
                                          "paint_over")):
                    if want[key]:
                        with open(path_, "wb") as fh:
                            fh.write(want[key])
                        setattr(p.pages[i], attr, path_)
                    else:
                        setattr(p.pages[i], attr, "")
                        if os.path.exists(path_):
                            os.remove(path_)
                p.pages[i].paint_layers = lays
                # Mending the artwork has to be allowed to change the shape it
                # is read off. See _unfreeze_repaired_balloons.
                redone = _unfreeze_repaired_balloons(p, i, want["overlay"])
                p.save()
                _page_cache.clear()
                _invalidate_renders()
                return self._json({"ok": True, "balloons_redone": redone})

            m = re.fullmatch(r"/api/page/(\d+)/clean_plate", path)
            if m:
                import base64
                i = int(m.group(1))
                if body.get("clear"):
                    old = getattr(p.pages[i], "custom_clean", "")
                    p.pages[i].custom_clean = ""
                    # It was never cleaned — it was excluded. Going back to
                    # automatic means there is now real work to do on it, and
                    # leaving the flag up would show the Clean step finished
                    # over a page that has no plate.
                    p.pages[i].cleaned = False
                    if old and os.path.exists(old):
                        os.remove(old)
                    p.save(); _page_cache.clear(); _invalidate_renders()
                    return self._json({"ok": True, "custom": False})
                data = body.get("data") or ""
                raw = base64.b64decode(data.split(",")[-1])
                d = os.path.join(p.output_dir, "custom_clean")
                os.makedirs(d, exist_ok=True)
                dest = os.path.join(d, _page_file_stem(p, i) + ".png")
                with open(dest, "wb") as fh:
                    fh.write(raw)
                if cv2.imread(dest) is None:
                    os.remove(dest)
                    return self._json({"error": "not a readable image"}, 400)
                p.pages[i].custom_clean = dest
                # Cleaning this page is done, in the only sense it will ever
                # be: the plate exists and no cleaner will touch it.
                p.pages[i].cleaned = True
                p.save(); _page_cache.clear(); _invalidate_renders()
                return self._json({"ok": True, "custom": True})

            m = re.fullmatch(r"/api/page/(\d+)/redo", path)
            if m:
                i = int(m.group(1))
                steps = body.get("steps") or ["ocr", "translate", "typeset"]

                def redo(idx: int, steps=steps):
                    if "detect" in steps:
                        p.detect(idx, body.get("kinds") or ["bubble"])
                    if "ocr" in steps:
                        do_ocr(p, idx)
                    if "translate" in steps:
                        do_translate(p, idx)
                    if "typeset" in steps:
                        do_typeset(p, idx)

                run_job(p, "Redoing page", [i], redo)
                return self._json({"started": 1, "steps": steps})

            if path == "/api/translate_all":
                idx = body.get("pages") or list(range(len(p.pages)))
                # The one decision about context, asked here for what to send
                # and asked by `context_boxes` for what to charge. See
                # `run_context`.
                chap = run_context(p, idx)
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts — the price is taken when
                # the button is pressed, so there is no longer such a thing as
                # one that pays for what it can and stops.
                short = needs_key(p, "translate") or afford_run(p, "translate", idx)
                if short:
                    return self._json({"error": short}, 402)
                run_job(p, "Translating", idx,
                        lambda i: do_translate(p, i, chap), step="translate")
                return self._json({"started": len(idx)})

            if path == "/api/proofread_all":
                idx = body.get("pages") or list(range(len(p.pages)))
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts — the price is taken when
                # the button is pressed, so there is no longer such a thing as
                # one that pays for what it can and stops.
                short = needs_key(p, "proofread") or afford_run(p, "proofread", idx)
                if short:
                    return self._json({"error": short}, 402)
                run_job(p, "Proofreading", idx, lambda i: do_proofread(p, i),
                        step="proofread")
                return self._json({"started": len(idx)})

            if path == "/api/clean_all":
                idx = body.get("pages") or list(range(len(p.pages)))
                # Pressing Clean means "clean these pages", not "make sure a
                # plate exists": it rebuilds. Everything else that needs a
                # plate — opening a page, typesetting, exporting — still reuses.
                #
                # A page with its own cleaned file stays in the list and is
                # skipped by `do_clean` — it costs one dictionary lookup and is
                # reported at the end as left alone. Filtering it out here
                # instead would drop it before `_run_one` clears the tally, and
                # the report would never mention it.
                own = sum(1 for k in idx if own_plate_path(p, k))
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts — the price is taken when
                # the button is pressed, so there is no longer such a thing as
                # one that pays for what it can and stops.
                short = needs_key(p, "clean") or afford_run(p, "clean", idx)
                if short:
                    return self._json({"error": short}, 402)
                run_job(p, "Cleaning", idx, lambda i: do_clean(p, i, force=True),
                        step="clean")
                return self._json({"started": len(idx), "own": own})

            if path == "/api/typeset_all":
                idx = body.get("pages") or list(range(len(p.pages)))
                run_job(p, "Laying out text", idx, lambda i: do_typeset(p, i))
                return self._json({"started": len(idx)})

            if path == "/api/pick_dir":
                from .pickdir import pick_directory
                start = body.get("start") or p.settings.get("export_dir") \
                    or p.output_dir
                chosen = pick_directory(start)
                return self._json({"path": chosen})

            if path == "/api/pick_project":
                # Save as, and Open. The machine showing the browser is the
                # machine holding the files, so this is the real dialog rather
                # than a path typed into a box — and a browser cannot offer one
                # for a file it is not downloading.
                from .pickdir import pick_project
                start = body.get("start") or _project_dir(p) or p.output_dir
                return self._json(
                    {"path": pick_project(start, save=bool(body.get("save")))})

            if path == "/api/project_save":
                # Save, and Save as. Written by the SERVER, to a path on this
                # machine, so pressing Save twice overwrites the same file
                # instead of filling Downloads with (1), (2), (3).
                from . import bundle
                dest = str(body.get("path") or
                           p.settings.get("project_file") or "").strip()
                if not dest:
                    return self._json({"error": "no file chosen"}, 400)
                if not dest.lower().endswith(bundle.EXT):
                    dest += bundle.EXT
                p.save()
                try:
                    data = bundle.write(p._state(), p.output_dir)
                    tmp = dest + ".part"
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                    os.replace(tmp, dest)
                except OSError as e:
                    return self._json({"error": f"could not write it: {e}"}, 500)
                # Remembered so Save has somewhere to go next time.
                p.settings["project_file"] = dest
                p.save_soon()
                return self._json({"path": dest, "bytes": len(data)})

            if path == "/api/project_open":
                # Opening one REPLACES what is open, the way starting a new
                # chapter does. Anything half-done in the folder goes with it,
                # which is why the file is checked for being a project before
                # a single thing is deleted — see `bundle.read`.
                from . import bundle
                src = str(body.get("path") or "").strip()
                if not src or not os.path.isfile(src):
                    return self._json({"error": "no such file"}, 400)
                try:
                    with open(src, "rb") as fh:
                        state = bundle.read(fh.read(), p.output_dir)
                except (OSError, ValueError) as e:
                    return self._json({"error": str(e)}, 400)
                return self._json(_adopt(p, state, src))

            if path == "/api/export":
                if body.get("dir"):
                    p.settings["export_dir"] = body["dir"]
                if body.get("name"):
                    p.settings["export_name"] = body["name"]
                try:
                    os.makedirs(export_root(p), exist_ok=True)
                except OSError as e:
                    return self._json({"error": f"cannot write there: {e}"}, 400)
                p.save()
                idx = body.get("pages") or list(range(len(p.pages)))
                mode = (body.get("mode") or "full").strip()
                if mode not in EXPORT_MODES:
                    mode = "full"
                label = {"full": "Exporting",
                         "clean": "Exporting cleaned art",
                         "boxes": "Exporting the boxes"}[mode]
                # This project has exported. Remembered on the project, not
                # worked out from what is in the folder: the export folder is a
                # place on disk that outlives the chapter, so a brand new
                # project pointed at it would otherwise "have results" made by
                # the last one.
                # lee: *"teh resulat page is still avalable in a new project"*.
                p.settings["exported"] = True
                p.save()
                run_job(p, label, idx, lambda i: export_page(p, i, mode))
                return self._json({"started": len(idx), "dir": export_root(p)})

            m = re.fullmatch(r"/api/page/(\d+)/hidden", path)
            if m:
                # Put a whole group of boxes away, or bring it back. Nothing is
                # deleted: the boxes stay in the record and simply stop being
                # part of the page's work until the tick goes back on.
                i = int(m.group(1))
                want = [g for g in KIND_GROUPS
                        if g in (body.get("groups") or [])]
                every = bool(body.get("all"))
                # The choice sticks, so the next group he puts away goes the
                # same way without being asked again.
                p.settings["hide_all_pages"] = every
                for k in (range(len(p.pages)) if every else [i]):
                    # ...and a group switch clears the per-box eyes inside the
                    # groups it moved — see PageState.hide_group.
                    p.pages[k].hide_group(want)
                    invalidate_page(k)
                _invalidate_renders()
                p.save()
                return self._json({
                    "regions": p.pages[i].active,
                    "hidden": list(p.pages[i].hidden_kinds),
                    "hidden_ids": [int(v) for v in
                                   (p.pages[i].hidden_ids or [])],
                    "hidden_rows": _hidden_rows(p.pages[i]),
                    "kinds": p.pages[i].groups_present,
                    "hidden_boxes": len(p.pages[i].hidden),
                    "pages": len(p.pages) if every else 1})

            m = re.fullmatch(r"/api/page/(\d+)/detect", path)
            if m:
                i = int(m.group(1))
                p.detect(i, body.get("kinds")); p.save()
                return self._json({"regions": p.pages[i].active})

            m = re.fullmatch(r"/api/page/(\d+)/ocr", path)
            if m:
                i = int(m.group(1)); do_ocr(p, i); p.save()
                return self._json({"regions": p.pages[i].active})

            m = re.fullmatch(r"/api/page/(\d+)/translate", path)
            if m:
                i = int(m.group(1)); do_translate(p, i); p.save()
                return self._json({"regions": p.pages[i].active})

            m = re.fullmatch(r"/api/page/(\d+)/layout_preview", path)
            if m:
                i = int(m.group(1))
                return self._json(layout_preview(
                    p, i, int(body["region_id"]), body.get("layout") or {}))

            m = re.fullmatch(r"/api/page/(\d+)/typeset", path)
            if m:
                i = int(m.group(1)); do_typeset(p, i); p.save()
                return self._json({"regions": p.pages[i].active})

            m = re.fullmatch(r"/api/page/(\d+)/region", path)
            if m:
                i = int(m.group(1))
                img = p.image(i)
                page = Page(image=img, source_path=p.pages[i].name)
                # A text box of your own, put where you want it. lee: *"add a
                # way to allow me to add text boxes independently of teh
                # boxes"*.
                #
                # Every other box on the page stands for writing that is
                # already there: it is found on the artwork, read, translated,
                # and the original is erased under the English. This one stands
                # for nothing — it is a place on the page where you want words
                # that were never in the art. So the rectangle is kept exactly
                # as drawn (there is no ink to tighten onto), nothing under it
                # is erased, and the reader and the translator leave it alone,
                # because there is no Japanese for either of them to work from.
                own = bool(body.get("own_text"))
                r = region_from_box(
                    page, int(body["x"]), int(body["y"]),
                    int(body["w"]), int(body["h"]),
                    kind=body.get("kind", "freefloat" if own else "bubble"),
                    rid=p.pages[i].new_region_id(),
                    snap=False if own else bool(body.get("snap", True)),
                    # Snapping off: the drawn box tightens onto the typesetting
                    # it contains rather than keeping the rough gesture.
                    tighten=(False if own
                             else not bool(body.get("snap", True))),
                )
                r.manual = True                       # type: ignore[attr-defined]
                if own:
                    r.src_text = ""
                    r.dst_text = str(body.get("text") or "")
                    r.skip_clean = True               # type: ignore[attr-defined]
                    r.confidence = 1.0
                rec = region_record(r)
                if own:
                    rec["own_text"] = True
                    # Typeset before it is answered for, and BEFORE it joins
                    # the page. The whole point of putting one of these down is
                    # to type into it, and a box with no layout shows "not laid
                    # out yet" instead of the typesetting controls.
                    #
                    # ONE region, not the page. It used to materialise the
                    # page, clean it and typeset the whole thing, which on a
                    # page whose plate is not built yet means an inpainting
                    # pass — seconds of nothing while a box you drew waits to
                    # appear. lee: *"it works but it very slow to show up"*.
                    # Nothing about laying out one box needs the cleaned plate:
                    # the shape it letters into comes from its own geometry,
                    # and the plate is what it will be DRAWN on later.
                    #
                    # Done here rather than after `regions.append` for a plain
                    # reason: `reorder` renumbers and re-sorts, so the record
                    # that had just been appended was no longer the last one,
                    # and writing the typeset copy back to the end of the list
                    # overwrote somebody ELSE's box and left two boxes carrying
                    # the same id.
                    try:
                        one = region_from_record(rec, img)
                        one.dst_text = r.dst_text
                        # No outline. It is not sitting on artwork that has to
                        # be pushed away from — it is words you asked for, on
                        # the page you chose, and a stroke round them is a
                        # decision you can make yourself in the panel.
                        # lee: *"the text created by the text box creator
                        # sould not have any outline by deafult"*.
                        one.layout_override = {"stroke": 0}
                        cfg2 = _typeset_cfg(p)
                        one.layout = typeset_mod.fit_region(one, cfg2)
                        if one.layout:
                            if not one.layout.font_path:
                                one.layout.font_path = (
                                    typeset_mod.font_for(cfg2, one.kind)
                                    or cfg2.font_path)
                            one.layout.stroke = 0
                            one.layout = typeset_mod.anchor_to_frame(
                                one.layout, cfg2)
                        typeset = region_record(one)
                        typeset["own_text"] = True
                        rec = typeset
                    except Exception:
                        pass          # untypeset is recoverable; a 500 is not
                # Keep the rectangle exactly as drawn so "Box as-is" can
                # always restore it, even after snapping changed the shape.
                rec["draw_box"] = [int(body["x"]), int(body["y"]),
                                   int(body["w"]), int(body["h"])]
                p.pages[i].regions.append(rec)
                reorder(p, i)
                if own:
                    invalidate_page(i)
                # `save_soon`, not `save`: this is the endpoint every arrow
                # press, kind change and typesetting nudge goes through, and
                # writing half a megabyte of JSON before answering put the
                # whole of that on the far side of the click.
                # lee: *"it works but very slow"*.
                p.save_soon()
                return self._json({"region": rec, "regions": p.pages[i].active})

            # Undo for a deleted box. The client hands back the WHOLE record it
            # held before the delete — text, shape, polygon, typesetting, link —
            # so the box returns as it was rather than being redrawn from a
            # rectangle. ("region/restore" cannot collide with the numeric
            # region route below.)
            m = re.fullmatch(r"/api/page/(\d+)/region/restore", path)
            if m:
                i = int(m.group(1))
                rec = body.get("region")
                if not isinstance(rec, dict) or "bbox" not in rec:
                    return self._json({"error": "no region to restore"}, 400)
                rec = dict(rec)
                recs = p.pages[i].regions
                # An id is never handed out twice on a page, so the number
                # this box had is still its own — unless the record came from
                # somewhere else entirely (another page, an older project).
                # Position is what matters here.
                if any(q["id"] == rec.get("id") for q in recs):
                    rec["id"] = p.pages[i].new_region_id()
                want = rec.get("order")
                if isinstance(want, int) and want >= 0:
                    # Everything at or after the old slot shifts down, so the
                    # box lands back on its own number instead of at the end.
                    for q in recs:
                        if isinstance(q.get("order"), int) and q["order"] >= want:
                            q["order"] += 1
                recs.append(rec)
                reorder(p, i)
                # `save_soon`, not `save`: this is the endpoint every arrow
                # press, kind change and typesetting nudge goes through, and
                # writing half a megabyte of JSON before answering put the
                # whole of that on the far side of the click.
                # lee: *"it works but very slow"*.
                p.save_soon()
                return self._json({"region": rec, "regions": p.pages[i].active})

            m = re.fullmatch(r"/api/page/(\d+)/region/(\d+)/split", path)
            if m:
                i, rid = int(m.group(1)), int(m.group(2))
                recs = p.pages[i].regions
                rec = next((r for r in recs if r["id"] == rid), None)
                if rec is None:
                    return self._json({"error": "no such region"}, 404)
                page = Page(image=p.image(i), source_path=p.pages[i].name)
                kids = classical.detect_within(
                    page, rec["bubble_bbox"] or rec["bbox"])
                if len(kids) < 2:
                    return self._json({"error":
                        "nothing to split — only one bubble found in that box",
                        "regions": p.pages[i].active})
                nid = p.pages[i].new_region_id()
                recs.remove(rec)
                # Splitting one box into pieces = one run of text spread across
                # them, so link the pieces (translator reads a link group as one
                # continuous line). A fresh id so only these pieces share it.
                link_id = max([(q.get("link") or 0) for q in recs],
                              default=0) + 1
                for k, r in enumerate(kids):
                    r.id = nid + k
                    rr = region_record(r)
                    rr["link"] = link_id
                    recs.append(rr)
                reorder(p, i)
                p.save()
                return self._json({"split": len(kids),
                                   "regions": p.pages[i].active})

            m = re.fullmatch(r"/api/page/(\d+)/region/(\d+)", path)
            if m:
                i, rid = int(m.group(1)), int(m.group(2))
                recs = p.pages[i].regions
                rec = next((r for r in recs if r["id"] == rid), None)
                if rec is None:
                    return self._json({"error": "no such region"}, 404)

                if body.get("resnap"):
                    img = p.image(i)
                    page = Page(image=img, source_path=p.pages[i].name)
                    bb = body.get("bbox") or rec["bubble_bbox"] or rec["bbox"]
                    nr = region_from_box(page, *[int(v) for v in bb],
                                         kind=rec.get("kind", "bubble"), rid=rid,
                                         snap=bool(body.get("snap", True)))
                    nr.manual = True                  # type: ignore[attr-defined]
                    keep = {k: rec.get(k) for k in
                            ("src_text", "dst_text", "dst_compact", "speaker",
                             "draw_box", "link", "box_group")}
                    new = region_record(nr)
                    new.update({k: v for k, v in keep.items() if v})
                    if not body.get("snap", True):
                        # an explicit manual box becomes the new reference
                        new["draw_box"] = [int(v) for v in bb]
                    recs[recs.index(rec)] = new
                    rec = new
                elif "polygon" in body:
                    pts = [[int(a), int(b)] for a, b in body["polygon"]]
                    if len(pts) != 4:
                        return self._json(
                            {"error": "a box has four corners"}, 400)
                    xs = [a for a, _ in pts]; ys = [b for _, b in pts]
                    bb = (min(xs), min(ys), max(xs) - min(xs) + 1,
                          max(ys) - min(ys) + 1)
                    if bb[2] < 6 or bb[3] < 6:
                        return self._json({"error": "shape too small"}, 400)
                    rec["polygon"] = pts
                    rec["bubble_bbox"] = list(bb)
                    rec["bbox"] = list(bb)
                    _page_cache.clear()
                    # the ink inside the new shape becomes the text to erase
                    page = p.materialize(i)
                    nr = next((q for q in page.regions if q.id == rid), None)
                    if nr is not None:
                        p.commit(i, page)
                        rec = next(q for q in p.pages[i].regions
                                   if q["id"] == rid)

                elif "layout" in body:
                    # A hand edit to the typesetting. Storing it locked means the
                    # automatic fitter will not quietly undo it later.
                    lay = body["layout"] or {}
                    # The frame it had BEFORE this edit. Emptying a box needs
                    # it, and by the time the new layout has been previewed
                    # the old one is gone.
                    was_frame = list((rec.get("layout") or {}).get("frame")
                                     or [])
                    if lay.get("reset"):
                        rec["layout_override"] = None
                    else:
                        rec["layout_override"] = {
                            "lines": [str(x) for x in (lay.get("lines") or [])],
                            "font_size": int(lay.get("font_size") or 0) or None,
                            "leading": float(lay.get("leading") or 1.12),
                            "lspace": float(lay.get("lspace") or 0),
                            "shadow": str(lay.get("shadow") or ""),
                            "sh_dist": float(lay.get("sh_dist") or 2),
                            "sh_blur": float(lay.get("sh_blur") or 3),
                            "curve": max(-180.0, min(180.0, float(
                                lay.get("curve") or 0))),
                            "glow": str(lay.get("glow") or ""),
                            "glow_size": float(lay.get("glow_size") or 6),
                            "iglow": str(lay.get("iglow") or ""),
                            "iglow_size": float(lay.get("iglow_size") or 5),
                            # 100 is "no transparency", and it has to survive
                            # being sent as 0 — hence the explicit test rather
                            # than `or 100`.
                            "opacity": (100 if lay.get("opacity") in (None, "")
                                        else max(0, min(100,
                                                 int(lay["opacity"])))),
                            "dx": int(lay.get("dx") or 0),
                            "dy": int(lay.get("dy") or 0),
                            "rotate": float(lay.get("rotate") or 0),
                            "font": str(lay.get("font") or ""),
                            "fg": str(lay.get("fg") or ""),
                            "edge": str(lay.get("edge") or ""),
                            "fg1": str(lay.get("fg1") or ""),
                            "fg2": str(lay.get("fg2") or ""),
                            "grad_angle": float(lay.get("grad_angle") or 0),
                            "edge1": str(lay.get("edge1") or ""),
                            "edge2": str(lay.get("edge2") or ""),
                            "edge_angle": float(lay.get("edge_angle") or 0),
                            # Which edge the lines hang from, and whether this
                            # block is set in capitals. Everything used to be
                            # centred and the capitals switch was a project
                            # setting — a caption ranged left, or one shout in
                            # capitals on a page that is not, could not be
                            # asked for at all.
                            "align": (str(lay.get("align") or "center")
                                      if str(lay.get("align") or "center")
                                      in ("left", "center", "right")
                                      else "center"),
                            "caps": bool(lay.get("caps")),
                            "frame": [int(v) for v in (lay.get("frame") or [])],
                            "wrap": bool(lay.get("wrap")),
                            "snug": bool(lay.get("snug")),
                            "fit": bool(lay.get("fit")),
                            "stroke": (None if lay.get("stroke") in (None, "")
                                       else int(lay["stroke"])),
                            "locked": True,
                        }
                    # Only this region changed. Re-laying out the whole page
                    # (and re-inpainting it) on every keystroke is what made
                    # editing feel slow.
                    rec["layout"] = layout_preview(
                        p, i, rid, rec.get("layout_override") or {})
                    # Resizing re-wraps (and with fit, re-sizes) the words.
                    # Store the result as the new breaks and size, or the
                    # next edit would undo them.
                    ov_now = rec.get("layout_override")
                    if ov_now and (rec["layout"] or {}).get("lines"):
                        ov_now["lines"] = list(rec["layout"]["lines"])
                        if ov_now.get("fit") and rec["layout"].get("font_size"):
                            ov_now["font_size"] = int(rec["layout"]["font_size"])
                        # A snugged or fitted box's computed frame is the
                        # real one — store it, or the old height comes back.
                        # (Minus the text nudge, which the layout re-adds.)
                        fr = rec["layout"].get("frame")
                        if fr and (ov_now.get("wrap") or ov_now.get("fit")):
                            ddx = int(ov_now.get("dx") or 0)
                            ddy = int(ov_now.get("dy") or 0)
                            ov_now["frame"] = [int(fr[0]) - ddx,
                                               int(fr[1]) - ddy,
                                               int(fr[2]), int(fr[3])]
                        ov_now["wrap"] = False
                        ov_now["snug"] = False
                        ov_now["fit"] = False
                    rec["flagged"] = None if rec.get("layout_override") \
                        else rec.get("flagged")
                    # Deleting every character from a box means the box has no
                    # words, not "lay these words out again with none of them".
                    # The words themselves were left standing, so the next
                    # Typeset — which deliberately throws hand corrections
                    # away and fits from `dst_text` — put the old typesetting
                    # straight back. lee: *"the text still revert to the last
                    # state when i remove all the text"*.
                    #
                    # The box stays: same frame, same size, still there to
                    # click and type into again. What goes is the sentence.
                    ov_now = rec.get("layout_override") or {}
                    if ("lines" in ov_now
                            and not any(str(x).strip()
                                        for x in (ov_now.get("lines") or []))):
                        rec["dst_text"] = ""
                        rec["dst_compact"] = None
                        rec.pop("proofread", None)
                        # ...and the frame it was left at, which is what makes
                        # it the same box afterwards.
                        if len(was_frame) == 4 and not ov_now.get("frame"):
                            ov_now["frame"] = [int(v) for v in was_frame]
                            rec["layout"] = layout_preview(p, i, rid, ov_now)
                    # A text box somebody put on the page themselves has TWO
                    # rectangles: the region, drawn once and never moved again,
                    # and the typesetting frame, which is what the handles
                    # actually drag. On every other box they mean different
                    # things — the region is where the Japanese was, the frame
                    # is where the English goes — but on this one there is no
                    # Japanese, and the two coming apart is a box left sitting
                    # empty where you first drew it while the words are
                    # somewhere else entirely.
                    # lee: *"the etxt box still crated a new box"*.
                    #
                    # So for these the region FOLLOWS the frame. One rectangle,
                    # wherever you last put it.
                    if rec.get("own_text"):
                        fr = (rec.get("layout") or {}).get("frame")
                        if fr and len(fr) == 4:
                            x0, y0, w0, h0 = (int(v) for v in fr)
                            rec["bbox"] = [x0, y0, max(1, w0), max(1, h0)]
                            rec["polygon"] = [[x0, y0], [x0 + w0, y0],
                                              [x0 + w0, y0 + h0], [x0, y0 + h0]]
                            rec["bubble_bbox"] = None
                            rec["draw_box"] = list(rec["bbox"])
                else:
                    if "skip_clean" in body:
                        rec["skip_clean"] = bool(body["skip_clean"])
                        _page_cache.clear()
                    if "hidden" in body:
                        # One box put away, or brought back. Same rule as a
                        # whole group: it stays in the record and stops being
                        # part of the page's work until the eye opens again.
                        pg = p.pages[i]
                        ids = [int(v) for v in (pg.hidden_ids or [])
                               if int(v) != rid]
                        if bool(body["hidden"]):
                            ids.append(rid)
                        pg.hidden_ids = ids
                        invalidate_page(i)
                        _invalidate_renders()
                    was_kind = rec.get("kind")
                    for k in ("src_text", "dst_text", "dst_compact", "speaker",
                              "kind", "locked"):
                        if k in body:
                            rec[k] = body[k]
                    if rec.get("kind") != was_kind:
                        _kind_changed(rec, was_kind)
                        _page_cache.clear()
                    if "angle" in body:
                        # Correcting the reading by hand: a straight effect the
                        # reader leaned, or a lean it refused to commit to.
                        rec["angle"] = max(-89.0, min(
                            89.0, float(body.get("angle") or 0.0)))
                        rec["sfx_len"] = rec.get("sfx_len") or 1.0
                        rec["sfx_wid"] = rec.get("sfx_wid") or 1.0
                    elif rec.get("kind") == "sfx" and was_kind != "sfx" \
                            and not rec.get("sfx_len"):
                        # Calling a box a sound effect is the moment to read
                        # its angle — and the page still has the Japanese on
                        # it, which by typeset time it will not.
                        page = p.materialize(i)
                        nr = next((q for q in page.regions if q.id == rid), None)
                        if nr is not None:
                            img = p.image(i)
                            gray = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                                    if img.ndim == 3 else img)
                            if read_sfx_axis(nr, gray):
                                rec.update({
                                    "angle": round(float(nr.angle), 2),
                                    "sfx_vertical": bool(nr.sfx_vertical),
                                    "sfx_len": round(float(nr.sfx_len), 4),
                                    "sfx_wid": round(float(nr.sfx_wid), 4)})
                        _page_cache.clear()
                    if "link" in body:
                        rec["link"] = int(body["link"] or 0)
                    if "dst_text" in body:
                        rec.pop("proofread", None)   # edited text: unread again
                    if "order" in body:
                        # the human sets the number: pull the region out,
                        # slot it back in at the asked-for position, renumber
                        lst = sorted(p.pages[i].regions,
                                     key=lambda x: x.get("order", 0))
                        lst = [x for x in lst if x["id"] != rid]
                        pos = max(0, min(len(lst), int(body["order"])))
                        lst.insert(pos, rec)
                        for n, x in enumerate(lst):
                            x["order"] = n
                        p.pages[i].regions = lst
                    if "dst_text" in body or "dst_compact" in body:
                        # New words, so the old typesetting is not this text's
                        # typesetting. The line breaks and the fitted size were
                        # computed FOR the previous wording, and leaving them
                        # is how a bubble ends up showing the sentence you
                        # replaced — lee: *"make sure that all the etxt are
                        # sync so if i chnage the text in one spot everywhere
                        # else that text is ghsoukd chnage"*. Proofreading has
                        # always done this when IT changed a line; an edit by
                        # hand is the same event.
                        #
                        # Only the fitting is dropped. Everything the person
                        # chose about how it looks — colour, outline, glow,
                        # rotation — is dressing and survives.
                        #
                        # ...and on a box you drew yourself, so does the BOX.
                        # A bubble's frame is derived — the fitter reads it off
                        # the balloon — so throwing it away costs nothing and
                        # it comes back the same. A text box has no balloon:
                        # its frame is the rectangle you dragged, and it is the
                        # only record of it. Dropping the whole layout sent the
                        # words back to whatever size the fitter chose, which
                        # is lee, typing into one: *"the new text box ... reset
                        # in size when i clcik off teh tab and come back"*.
                        keep = None
                        if rec.get("own_text"):
                            keep = list((rec.get("layout") or {}).get("frame")
                                        or []) or None
                        rec["layout"] = ({"lines": [], "frame": keep,
                                          "font_size": (rec.get("layout") or {})
                                          .get("font_size"),
                                          "leading": (rec.get("layout") or {})
                                          .get("leading")}
                                         if keep else None)
                        ov = dict(rec.get("layout_override") or {})
                        for key in ("lines", "fit", "wrap", "snug"):
                            ov.pop(key, None)
                        rec["layout_override"] = ov or None
                # A layout-only edit does not move a single mask, so the
                # cached page it would otherwise throw away is still exactly
                # right — and rebuilding it is what made the first press after
                # a save take seconds.
                reorder(p, i, stale=("layout" not in body))
                # `save_soon`, not `save`: this is the endpoint every arrow
                # press, kind change and typesetting nudge goes through, and
                # writing half a megabyte of JSON before answering put the
                # whole of that on the far side of the click.
                # lee: *"it works but very slow"*.
                p.save_soon()
                return self._json({
                    "region": rec, "regions": p.pages[i].active,
                    # The eye needs both halves back or it cannot draw itself:
                    # a box that has just been put away is no longer in
                    # `regions`, and the row that replaces it comes from here.
                    "hidden_ids": [int(v) for v in
                                   (p.pages[i].hidden_ids or [])],
                    "hidden_rows": _hidden_rows(p.pages[i]),
                    "hidden_boxes": len(p.pages[i].hidden)})

            return self._send(404, b"not found", "text/plain")
        except Exception as e:
            if getattr(self, "_client_gone", False):
                return                 # they left; there is nobody to tell
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_DELETE(self):
        p = PROJECT
        path = urllib.parse.urlparse(self.path).path

        m = re.fullmatch(r"/api/page/(\d+)", path)
        if m:
            ok = p.remove_page(int(m.group(1)))
            return self._json({"ok": ok, "pages": len(p.pages)})

        m = re.fullmatch(r"/api/page/(\d+)/region/(\d+)", path)
        if not m:
            return self._send(404, b"not found", "text/plain")
        i, rid = int(m.group(1)), int(m.group(2))
        p.pages[i].regions = [r for r in p.pages[i].regions if r["id"] != rid]
        reorder(p, i)
        p.save_soon()
        return self._json({"regions": p.pages[i].active})


def reorder(p: Project, i: int, stale: bool = True) -> None:
    """Keep reading order sane after the region set changes.

    `stale=False` says the GEOMETRY did not move — a colour, a font, a line
    gap, capitals. The cached page is built from masks and a cleaned plate,
    and neither depends on any of that, so dropping it made the next keystroke
    rebuild the whole page: materialize, find the balloons, clean the plate.
    That is the seconds-long pause on the first press after a save — lee: *"the
    letter gap take a long time to work the first time"*.

    Every add, delete, move and resize passes through here, so it is also the
    right place to drop the cached page whose masks just went stale.

    Order is STICKY: when every region already has an order (including one a
    human just set by hand), it is only compacted — moving or editing a
    bubble no longer reshuffles the whole page's numbers. Geometry decides
    only when regions arrive without an order (fresh detection, splits).
    """
    if stale:
        invalidate_page(i)
    recs = p.pages[i].regions
    if not recs:
        return
    fresh = [r for r in recs
             if not isinstance(r.get("order"), int) or r["order"] < 0]
    if not fresh:
        for n, r in enumerate(sorted(recs, key=lambda r: r["order"])):
            r["order"] = n
        return

    # The real page image lets ordering see panel borders (keeps the reading
    # order inside panels). Fall back to a blank canvas if it can't be loaded —
    # ordering then uses geometry only, exactly as before.
    try:
        img = p.image(i)
    except Exception:
        img = np.zeros((p.pages[i].height or 1,
                        p.pages[i].width or 1, 3), np.uint8)
    page = Page(image=img)
    from .models import TextRegion
    tmp = [TextRegion(id=r["id"], bbox=tuple(r["bbox"]),
                      bubble_bbox=(tuple(r["bubble_bbox"])
                                   if r.get("bubble_bbox") else None))
           for r in recs]
    page.regions = tmp
    assign_order(page, rtl=p.rtl)
    grank = {t.id: t.order for t in tmp}

    fresh_ids = {id(r) for r in fresh}
    established = [r for r in recs if id(r) not in fresh_ids]
    if established:
        # The page already has an order — quite possibly one a human arranged
        # by hand. Adding a box must NOT reshuffle it: the existing regions
        # keep their exact sequence, and each new box is only SLOTTED IN at
        # the place geometry suggests (before the first existing region that
        # reads after it, else at the end).
        seq = sorted(established, key=lambda r: r["order"])
        for f in sorted(fresh, key=lambda r: grank.get(r["id"], 10**9)):
            gf = grank.get(f["id"], 10**9)
            idx = len(seq)
            for k, e in enumerate(seq):
                if grank.get(e["id"], -1) > gf:
                    idx = k
                    break
            seq.insert(idx, f)
        for n, r in enumerate(seq):
            r["order"] = n
        recs.sort(key=lambda r: r["order"])
        return

    # a page of nothing but fresh regions: geometry decides everything
    for r in recs:
        r["order"] = grank.get(r["id"], -1)
    recs.sort(key=lambda r: r["order"])


# Names that read as comic / manga / manhwa / manhua typesetting. The editor
# shows only these (plus everything bundled in ./fonts) by default — a
# Windows font folder holds hundreds of office fonts nobody letters with.
_COMIC_HINTS = (
    "anime", "wild words", "wildwords", "komika", "manga", "manhwa", "manhua",
    "webtoon", "comic", "cartoon", "toon", "blambot", "badaboom",
    "digital strip", "digitalstrip", "webtypesetter", "letter-o-matic",
    "typesetomatic", "laffayette", "augie", "action man", "sequential",
    "bangers", "luckiest", "kalam", "patrick hand", "indie flower",
    "architects daughter", "shadows into light", "permanent marker",
    "marker", "felt", "balloon", "bubblegum", "creepster", "chewy",
    "boogaloo", "sniglet", "fredoka", "kablammo", "sfx",
    "anton", "gochi", "gaegu", "jua", "nanum", "baloo", "jibril",
    "patrickhand",
)


def _is_comic_font(name: str) -> bool:
    n = name.lower().replace("-", " ").replace("_", " ")
    # Comicraft's catalogue is all CC-prefixed (CC Wild Words, CC Astro City…)
    return n.startswith("cc") or any(k in n for k in _COMIC_HINTS)


_SAMPLE_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()


def _font_sample_png(fp: str, text: str = "sample") -> "bytes | None":
    """Render `text` in the font `fp` to a small transparent PNG (light ink
    on nothing), for the font-picker previews. Cached by (path, mtime, text)."""
    text = (text or "sample")[:24]
    try:
        key = (fp, os.path.getmtime(fp), text)
    except OSError:
        return None
    hit = _SAMPLE_CACHE.get(key)
    if hit is not None:
        _SAMPLE_CACHE.move_to_end(key)
        return hit
    try:
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(fp, 30)
        l, t, r, b = font.getbbox(text)
        w, h = max(1, r - l) + 8, max(1, b - t) + 8
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((4 - l, 4 - t), text, font=font,
                                 fill=(207, 213, 226, 255))
        import io
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
    except Exception:
        return None
    _SAMPLE_CACHE[key] = data
    if len(_SAMPLE_CACHE) > 600:
        _SAMPLE_CACHE.popitem(last=False)
    return data


def find_fonts() -> list[dict]:
    out, seen = [], set()
    # Faces the person uploaded come first and are always offered: they went to
    # the trouble of adding them, so nothing about the name is allowed to
    # decide they are not a typesetting font.
    for fp in userdata.uploaded_fonts():
        f = os.path.basename(fp)
        seen.add(f)
        out.append({"name": os.path.splitext(f)[0], "path": fp,
                    "bundled": True, "comic": True, "uploaded": True})
    mine = len(out)
    # The bundled fonts/ folder must be found no matter where the editor is
    # launched from, so resolve it relative to this file (…/mangatl/fonts)
    # first, then fall back to the launch directory. Using only getcwd() meant
    # starting from anywhere but the repo root hid every bundled font.
    here = os.path.dirname(os.path.abspath(__file__))
    bundled_candidates = []
    for cand in (os.path.join(os.path.dirname(here), "fonts"),  # repo root/fonts
                 os.path.join(here, "fonts"),                   # package/fonts
                 os.path.join(os.getcwd(), "fonts")):           # launch dir/fonts
        c = os.path.normcase(os.path.abspath(cand))
        if c not in bundled_candidates:
            bundled_candidates.append(c)
    bundled_set = set(bundled_candidates)
    roots = bundled_candidates + ["/usr/share/fonts",
             os.path.expanduser("~/Library/Fonts"), "C:\\Windows\\Fonts"]
    for root in roots:
        if not os.path.isdir(root):
            continue
        is_bundled = os.path.normcase(os.path.abspath(root)) in bundled_set
        for dirpath, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith((".ttf", ".otf")) and f not in seen:
                    seen.add(f)
                    name = os.path.splitext(f)[0]
                    out.append({"name": name,
                                "path": os.path.join(dirpath, f),
                                "bundled": is_bundled,
                                "comic": _is_comic_font(name)})
            if len(out) > 400:
                break
    # A to Z, all of them together. The list used to open with whatever the
    # person had uploaded, in the order they uploaded it, and then with five
    # comic-sounding prefixes bumped to the top of the rest — so the menu read
    # Mangaka, AnimeAce, ComicNeue, Komika, comic, comicbd, Anton, Bangers…
    # and there was no way to guess where any face would be. lee: *"the fonts
    # shoud be in aphabetical order with the new fonts"* — with, not above.
    #
    # Uploaded faces still survive the cap: they are the ones somebody went to
    # the trouble of adding, so the cap is applied to the rest before the two
    # are sorted together.
    rest = out[mine:][:max(0, 400 - mine)]
    return sorted(out[:mine] + rest, key=lambda d: d["name"].lower())


def main(argv=None) -> int:
    global PROJECT
    ap = argparse.ArgumentParser(prog="mangatl.editor")
    ap.add_argument("--input", default="", help="folder of page images "
                    "(optional — you can also pick files in the browser)")
    ap.add_argument("--output", default="out", help="folder for exported pages")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--font", default="")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)

    PROJECT = Project(a.input or None, a.output)
    # Small edits are written out a moment after they are made (see
    # Project.save_soon). Closing the editor in that moment must not be the
    # one thing that loses them.
    import atexit
    atexit.register(PROJECT.flush)
    if a.font:
        PROJECT.settings["font"] = a.font
    warm_ocr(PROJECT)
    warm_pages(PROJECT, 0)

    url = f"http://127.0.0.1:{a.port}"
    where = PROJECT.input_dir or "(no folder yet — choose one in the browser)"
    print(f"mangatl editor — {len(PROJECT.pages)} pages from {where}")
    print(f"exporting to {PROJECT.output_dir}")
    print(f"open {url}")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
