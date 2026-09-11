"""Local editor server. Stdlib only - this is a desktop tool, not a service.

    python -m mangatl.editor --input chapter/ --output out/

Opens http://127.0.0.1:8765 . Detection runs over the folder in the background;
you correct the boxes, run OCR and translation, edit the English, and export a
folder of typeset pages.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
from collections import OrderedDict
import mimetypes
import os
import posixpath
import re
import shutil
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from . import inpaint as inpaint_mod
from . import stopping as _stopping
from . import userdata
from . import render as render_mod
from . import typeset as typeset_mod
from .detect import classical
from .interactive import region_from_box
from .order import assign_order
from . import kinds as _kinds
from . import marks as _marks
from . import project as project_mod
from . import imgio
from .project import (KIND_GROUPS, Project, group_of, is_turned,
                      read_sfx_axis, region_from_record, region_record,
                      token_state, turned_box)
from .models import Page

STATIC = os.path.join(os.path.dirname(__file__), "static")
PROJECT: Project | None = None


# --------------------------------------------------------------------- helpers

def _typeset_cfg(p: Project) -> typeset_mod.TypesetConfig:
    s = p.settings
    # A sub-type's face travels on its own record - it is part of what that
    # sub-type is - so it is folded in here rather than relied on having been
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
# page. Anything past this stays fast anyway - the plate it is built from is
# on disk (see _plate_disk_path).
RENDER_CACHE_MAX = 96

# Bumped whenever something invalidates the rendered pages for a reason the
# stamp below cannot see. It rides along in the key the browser is given, so
# clearing the server's cache also stops the browser reusing its own copy.
# It starts from the clock rather than zero so that keys never outlive the run
# that made them: a restart costs one re-fetch per page off a warm server, and
# in exchange nothing the browser kept from last time can ever be shown.
_render_epoch = int(time.time())

# This RUN of the server, for the browser to notice a restart by. Not the
# epoch above: that moves on every invalidation, and a page that reloaded on
# each of those would be unusable.
_BOOT = f"{os.getpid()}-{int(time.time())}"


def _invalidate_renders() -> None:
    """The browser must ask again, and memory must rebuild. NOT the disk.

    For one morning (2026-08-30-a to -c) this also deleted every .jpg in the
    render_cache directory, on the reasoning that a picture declared wrong
    everywhere had to go from everywhere. The reasoning had the wrong
    culprit: the stale pictures lee kept seeing were drawn by OLDER BUILDS,
    which `RENDER_ALGO` retires precisely, and every one of this function's
    fifteen call sites changes something `_render_stamp` already reads - the
    words, the records, the active roster, the page's name and index and
    file, the overlay files' mtimes, the plate's mark. A change like that
    moves the KEY, so the old file on disk is not a wrong answer waiting to
    be served: it is unreachable garbage the pruner will get to.

    What the purge actually did was turn every small bump into a chapter
    rebuild. Hiding one heal stroke saves the overlay, bumps the epoch - and
    deleted 45 finished pages, which the warm-up then remade in front of him
    at seconds each. lee: *"this disnt happen before and its not fast it
    redoing it again"*. He was right on both counts.

    So: epoch (the browser's copies), memory (this run's copies), and the
    disk keeps what it has. A picture nothing can ask for hurts nobody.
    """
    global _render_epoch
    _render_epoch += 1
    _render_cache.clear()


def _touch(cache: OrderedDict, key) -> None:
    """Mark an entry as the most recently used one.

    Another thread trimming the same cache can drop the key between the lookup
    and the move - the entry going missing is exactly what a cache is allowed
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


def _plate_mark(path: str) -> float:
    """A number that moves when a plate is REBUILT, and at no other time.

    `_render_stamp` needs the plate's identity, and the file's modification
    time is it - but only because nothing touches the file except writing it.
    That was not true: `clean_page` used to touch a plate on every reuse, so
    the cache pruner could tell one still in use from an abandoned one. Reading
    the cache therefore changed the key of what was in it. The picture was
    rebuilt on the next visit, the browser's `v=` moved with it, and a page
    nobody had edited was re-rendered and re-downloaded every time it came
    round - and the copy kept on disk could never be read back at all, because
    by then the plate's time had moved on.

    lee: *"when i swithc only some section of teh page show up and i take sa
    while to get teh rest to show up"*. It was my own fix for
    `the-picture-and-the-plate-2026-08-29` that bought it.

    **A CACHE KEY MUST NOT BE CHANGED BY READING THE CACHE.** So the touch is
    gone, and the pruner keeps the most recently BUILT plates rather than the
    most recently read - which is the same set in practice: it keeps three per
    page and a chapter has one each.
    """
    return _mtime(path)


# Fields of a region record that CANNOT change the picture, and so have no
# business in the key of a cached picture.
#
# `layout` is computed output that rendering writes back - it was always
# excluded, and the other three are the same thing arriving later.
# `clean_route`, `clean_core` and `flagged` are the cleaner's REPORT: how each
# box was erased and what it wanted to say about it. They are read on the
# boxes panel and never drawn on the page.
#
# Leaving them in cost a page switch. A view of a cleaned page takes its plate
# off the disk without running the inpainter, so the report came back empty
# and the commit wrote the empty one down; the next view had the report again.
# The key flipped between two values on alternate renders and never matched
# twice, so every other look at every page rebuilt a picture that had not
# changed. lee: *"figure out a way to have the cleaned pages switch fataer for
# one page to another"*.
#
# The other half of that fix is in `_commit_keep_proofread`, which stops the
# report being thrown away at all. Both, because they answer different
# questions: one is what a page KEEPS, this one is what a PICTURE is.
_NOT_A_PICTURE = frozenset((
    "layout", "clean_route", "clean_core", "flagged", "proofread",
))

# WHICH BUILD DREW IT.
#
# The stamp below covers the words, the boxes, the plate and the settings -
# every INPUT to the picture. It does not cover the code that turns those
# inputs into pixels, and until the pictures lived only in memory it did not
# have to: a restart threw them all away, so a new build always drew its own.
#
# Keeping them on disk (2026-08-29, `_render_disk_path`) removed that. A
# picture drawn by Friday's typesetter now survives into Saturday's build and
# is served in preference to drawing it again, because every input still
# matches. lee got an export preview with the captions clipped and no SPLAAASH
# on it, beside a real export that was correct - the same page, one of them
# drawn months of fixes ago: *"so teh export preview is wrong in some places"*.
#
# So the build is part of the picture's identity, exactly as `inpaint.ALGO` is
# part of a plate's. BUMP THIS whenever a change would draw an existing page
# differently - the typesetter, the renderer, the compositor, the fitter.
# It costs one rebuild per page and it is the only thing standing between a
# fix and a cache that never heard about it.
RENDER_ALGO = "2026-08-31-a"   # gradient letters drawn in ramp colours


def _render_stamp(p: Project, i: int, mode: str) -> tuple:
    """Everything that can change what a rendered page looks like.

    Cleaning and typesetting a page takes over a second, and it was being redone
    on every single view - so paging back and forth meant waiting each time.
    """
    st = p.pages[i]
    s = p.settings
    # Only the inputs. `layout` is computed output that rendering writes back,
    # so including it would change the key every time and never hit.
    # The ACTIVE boxes: a hidden group is not drawn on any of the three
    # views, so putting one away has to change the key or the old picture
    # stays on screen.
    inputs = [{k: v for k, v in (r or {}).items() if k not in _NOT_A_PICTURE}
              for r in st.active]
    cc = getattr(st, "custom_clean", "") or ""
    ov = getattr(st, "paint_overlay", "") or ""
    ovr = getattr(st, "paint_over", "") or ""
    base = (RENDER_ALGO,
            i, mode, st.name, st.width, st.height,
            _page_fingerprint(p, i), cc, _mtime(cc),
            ov, _mtime(ov), ovr, _mtime(ovr),
            json.dumps(inputs, sort_keys=True, default=str),
            s.get("ai_clean") or "off", cleaner_endpoint(p, token=False)[0],
            # ...and WHETHER IT HAS BEEN CLEANED, because that is now the
            # difference between two different pictures rather than between a
            # picture and the same picture built more slowly. Without it, the
            # view you had open before pressing Clean is the view you keep.
            bool(st.cleaned),
            # ...and WHICH PLATE, which is not the same question and is the one
            # that was missing. `cleaned` is a flag that goes false to true
            # ONCE. Clean a page a second time and it is already true, so
            # nothing above changes, so this key does not change - and the
            # picture the cache and the browser both answer with is the one
            # built from the plate that has just been replaced.
            #
            # lee, on page 009 after a re-clean: *"the clenner is working but
            # teh page is not showing it, i even tried to re clean"*. He was
            # right twice over - the plate on disk was clean and the picture
            # was the old one. That page had been cleaned by a build whose
            # cleaner read a black balloon inside out; this build retires that
            # plate (`inpaint.ALGO`) and makes a good one, and the picture went
            # on being the bad one because the only thing the key knew about
            # cleaning was a boolean that had been true for a week.
            #
            # THE PICTURE IS MADE FROM THE PLATE, so the plate's identity
            # belongs in the picture's. Its file time answers for its contents:
            # it moves when a plate is written for any reason at all - a
            # re-clean, a bumped `ALGO`, a moved box, a different eraser - and
            # a plate nothing rebuilt keeps its time and its key, so this costs
            # nothing on a page that has not changed. Narrower than bumping the
            # render epoch, which would throw away every OTHER page in the
            # chapter every time one was cleaned.
            _plate_mark(_plate_disk_path(p, i)))
    if mode != "typeset":
        # The scan and the cleaned plate carry no text, so the typesetting
        # settings cannot change what they look like. Including them meant a
        # change of font threw away the cleaned page and made it again from
        # scratch - a call out to the hosted cleaner, seconds of blank canvas -
        # to arrive at the identical image. The editor only ever asks for those
        # two, which is why picking a font now costs nothing.
        return base
    return base + (
        s.get("font"), json.dumps(s.get("fonts") or {}, sort_keys=True),
        s.get("min_font"), s.get("max_font"), s.get("uppercase"),
        # ...and whether the typesetter may stand something else in, which
        # changes what is drawn as surely as the face does.
        s.get("substitutes"))


def _render_key(p: Project, i: int, mode: str = "") -> str:
    """A short token the browser can hang on the image URL.

    The URL used to end in the current clock, which meant every single page
    view re-downloaded the image even when nothing about it had changed. This
    changes exactly when the page's appearance can have changed, so going back
    to a page you have already seen costs nothing at all.
    """
    h = hashlib.sha1(repr(_render_stamp(p, i, mode)).encode("utf-8"))
    return f"{_render_epoch}-{h.hexdigest()[:16]}"


_fingerprints: "OrderedDict[tuple, str]" = OrderedDict()


def _page_fingerprint(p: Project, i: int) -> str:
    """What is actually IN this page's file.

    Everything that names a picture - the URL the browser caches under, the
    rendered-page cache, the cleaned-plate cache - used to be built out of the
    page's NAME and its width and height. For one chapter that is enough. For
    the next one it is not:

        lee: *"wheni uploaded a new chnater the old chapter is showing up as
        teh new chnapeter this shoud neveer happen"*

    Chapters are numbered the same way every time - `001.png`, `002.png` - and
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
        # No file to read - a project state pointing at pages that have moved.
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
    """Identity of the fully-cleaned plate - geometry, not eye toggles."""
    # THE FAMILY, NOT THE KIND, and this one cost lee a chapter of cleaned
    # pages: *"can you check on the clenned text disapearing? cleaned pages i
    # mean"*.
    #
    # A plate is cached on disk against this stamp, so anything in here that
    # changes throws the plate away and the page comes back looking uncleaned.
    # That is right when the change could have altered the plate and wrong
    # otherwise - and the sub-type never can. Every place the cleaner looks at
    # a kind it asks `family_of` first: three in `inpaint.py` and
    # `project._no_balloon`. Not one of them branches on the sub-type.
    #
    # It went unnoticed for as long as a box's kind WAS its family. Read text
    # labels sub-types now, so a chapter cleaned and then re-read had every
    # `sfx` become `sfx_big` and every plate on disk orphaned by a relabel that
    # could not have changed a pixel of it.
    #
    # Asked with the project's OWN sub-type list rather than the module global,
    # so the stamp cannot depend on whether `kinds.use()` has run yet - a stamp
    # that answers differently before and after a load is the same bug again.
    subs = p.settings.get("custom_kinds") or []
    geo = tuple((r.get("id"), tuple(r.get("bbox") or ()),
                 _kinds.family_of(r.get("kind") or "", subs))
                for r in p.pages[i].regions)
    # The cleaning method is part of the plate's identity - switching between
    # local and AI must rebuild it. So is the TOKEN, by its fingerprint: a
    # wrong token and a right one produce completely different pages, and
    # without this, pasting the real token in left every plate built during the
    # 401s sitting in the cache, so nothing changed and nothing was re-sent.
    tok = clean_token_for(p)
    ai = (p.settings.get("ai_clean") or "off", cleaner_endpoint(p, token=False)[0],
          hashlib.sha1(tok.encode("utf-8")).hexdigest()[:12] if tok else "",
          # ...and the CLEANER'S OWN VERSION. A plate is cached on disk and
          # reused forever, and none of the keys above change when the cleaning
          # code does - so every improvement shipped invisible, the old plate
          # answering for the new build. lee: *"nothing vhanged"*. Bump
          # inpaint.ALGO and every plate made by the old code retires itself.
          getattr(inpaint_mod, "ALGO", ""),
          # ...and WHICH ERASER. Same argument again: switching the model with
          # the plates still on disk is the "nothing vhanged" bug wearing a new
          # hat - every page would answer with the old model's work.
          clean_model(p),
          # ...and whether the plate was READ afterwards. Turning the check off
          # is a different cleaner, and a page that kept its old plate would go
          # on showing the text the check had already taken off.
          bool(p.settings.get("clean_reread", True)))
    return (i, p.pages[i].name, _page_fingerprint(p, i),
            getattr(p.pages[i], "custom_clean", "") or "", geo, ai)


def _page_file_stem(p: Project, i: int) -> str:
    """A per-page file name tied to the page itself, not its position.

    Naming these files by index meant that after a reorder, saving page 1's
    strokes overwrote the file page 3's record still pointed at.
    """
    base = os.path.splitext(p.pages[i].name)[0]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base) or f"{i:03d}"


# The two erasers one deploy of `lama_clean_modal.py` serves. `lama` is the
# standard big-lama; `anime-lama` is the same architecture fine-tuned on
# anime and manga artwork.
#
# Measured on nine hard boxes off lee's own chapter 3 - sound effects and
# outside text over hatching and screentone, the app's own crops and masks -
# against five other erasers: anime-lama landed nearer the surrounding artwork
# on 6 of 9 at the same speed, and it and lama were the only two of seven that
# never drew something that had never been on the page. (`fcf` put a human
# face in a blank panel; `migan` a black blob; `manga` and `zits` mottle and
# streaks.) lee: *"anime lama is the shout, add it in the list"*.
CLEAN_MODELS = ("anime-lama", "lama")


def clean_model(p: Project) -> str:
    """Which eraser this project asks the endpoint for.

    Anything the settings do not recognise becomes the default rather than
    being sent on: a typo in a settings box should clean the page, not fail it.
    """
    # The measured one, always. There used to be a choice and there used to be
    # cards to make it with; lee: *"...ad only ai and the card make this the
    # deaflau clenner"*. A project.json carrying the other name from when there
    # was a choice gets the measured one anyway.
    return CLEAN_MODELS[0]


def _ai_clean_cache_dir(p: Project) -> str:
    d = os.path.join(p.output_dir, "ai_clean_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _render_disk_path(p: Project, key: tuple) -> str:
    """Where a finished picture is kept between runs.

    Beside the plates, and for the same reason: a rendered page is expensive to
    make and cheap to read, and until now the only copy lived in memory. A
    restart threw away the whole chapter and it was all built again, one
    three-second page at a time, in front of whoever turned to it.

    Keyed on `_render_stamp`, which already answers "is this the same picture" -
    the geometry, the words, the plate, the typesetting settings, the cleaner's
    version. So a file here can only be read by a request that would have built
    exactly it.
    """
    h = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()
    return os.path.join(p.output_dir, "render_cache", h + ".jpg")


def _render_from_disk(p: Project, i: int, key: tuple):
    fp = _render_disk_path(p, key)
    try:
        if not os.path.exists(fp):
            return None
        with open(fp, "rb") as fh:
            got = fh.read()
        # Touching it is safe here in a way it is not for a plate: nothing
        # keys on this file's time, only the pruner reads it. See
        # `_plate_mark` for the version of this that went wrong.
        os.utime(fp, None)
        return got or None
    except OSError:
        return None


def _render_to_disk(p: Project, i: int, key: tuple, data: bytes) -> None:
    fp = _render_disk_path(p, key)
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        tmp = fp + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, fp)          # whole or not at all
        # Two views of every page, plus a version or two of whichever page is
        # being worked on. Three per page covers that with room to spare, and
        # the oldest go first. A page is around 300KB, so a 200-page project
        # sits near 180MB - large, and much smaller than the plates beside it,
        # which are PNG.
        _prune_cache_dir(os.path.dirname(fp), max(60, 3 * len(p.pages)))
    except OSError:
        pass                         # a cache that cannot write is still fine


def _plate_disk_path(p: Project, i: int) -> str:
    """Where a finished clean plate is kept between runs.

    Only six plates fit in memory and none of them survived closing the app,
    so the first visit to every page after a restart re-ran the whole
    inpainter - the wait the person kept hitting when they moved to a page for
    the first time. The name is the plate's own identity, so a plate is only
    ever reused for exactly the page, boxes and cleaning method that produced
    it, and changing any of those simply misses and rebuilds.
    """
    d = os.path.join(p.output_dir, "plate_cache")
    os.makedirs(d, exist_ok=True)
    key = hashlib.sha1(repr(_plate_stamp(p, i)).encode("utf-8")).hexdigest()
    path = os.path.join(d, key + ".png")
    if not os.path.exists(path):
        _adopt_pre_family_plate(p, i, d, path)
    return path


def _plates_to_carry(p: Project) -> dict:
    """`{page index: its cleaned plate}` for every page that has one.

    What the bundle needs to stop throwing the cleaner's work away. Asked of
    the CACHE, not of the `cleaned` flag: the flag says a plate was made, the
    file says one is still there to carry.

    `_plate_disk_path` is the one authority on where a plate lives, so this
    goes through it rather than listing the folder - a plate found by
    listing might belong to a page as it was three edits ago.
    """
    out = {}
    for i in range(len(p.pages)):
        try:
            at = _plate_disk_path(p, i)
        except Exception:
            continue
        if at and os.path.isfile(at):
            out[i] = at
    return out


def _take_in_carried_plates(p: Project) -> int:
    """Move a bundle's plates into this machine's cache, re-keyed.

    The name a plate is cached under is a hash of everything that identifies
    it, and two of those things are not the same on the machine that opens
    the file: the hand-cleaned plate's absolute path, and the cleaning
    token's fingerprint when it comes from a different `.env`. A plate copied
    in under its old name would sit in the folder unread and the page would
    be cleaned again - which is the bug this whole path is here to fix, one
    step further along.

    So the plate arrives under its page's index and is written out under
    whatever `_plate_disk_path` asks for HERE, after the project has loaded
    and the stamp can be computed. Returns how many were taken in.
    """
    from . import bundle
    got = bundle.carried_plates(p.output_dir)
    n = 0
    for i, src in sorted(got.items()):
        if i >= len(p.pages):
            continue                      # a plate for a page that is not here
        try:
            shutil.copyfile(src, _plate_disk_path(p, i))
            n += 1
        except OSError:
            continue
    bundle.forget_plates(p.output_dir)
    return n


def _adopt_pre_family_plate(p: Project, i: int, d: str, path: str) -> None:
    """Give back a plate cleaned while the stamp still carried the sub-type.

    Fixing `_plate_stamp` to key on the FAMILY brought nearly every orphaned
    plate back on its own - a page whose boxes were all `bubble`, `freefloat`
    and `sfx` has the same stamp either way, because a family is its own
    family. Measured against lee's own chapter, 19 pages of 23.

    The other four are the pages he cleaned AFTER the reading had relabelled
    them. Those plates went to disk under `sfx_small` and `whisper`, and the
    corrected stamp asks for `sfx` and `bubble` - so the very change that
    rescued the nineteen orphans the four. Shipping that would have been a fix
    that took something away from the person it was for.

    So a miss looks once for the name the old stamp would have given, and if
    that plate is there, copies it under the new name. It is safe for exactly
    the reason the fix is right: every other thing in the stamp - the scan,
    the boxes, the eraser, the token - is identical, and the sub-type could
    never have changed a pixel of the plate. Copied, not moved: an old build
    reading the same folder still finds what it put there.

    It costs one `os.path.exists` on a miss, which is a miss that was about to
    re-run an inpainter.
    """
    try:
        subs = p.settings.get("custom_kinds") or []
        regions = p.pages[i].regions
        if not any(_kinds.family_of(r.get("kind") or "", subs)
                   != (r.get("kind") or "") for r in regions):
            return                      # nothing to translate back
        was = _plate_stamp(p, i)
        geo = tuple((r.get("id"), tuple(r.get("bbox") or ()), r.get("kind") or "")
                    for r in regions)
        old = was[:4] + (geo,) + was[5:]
        src = os.path.join(d, hashlib.sha1(
            repr(old).encode("utf-8")).hexdigest() + ".png")
        if os.path.exists(src):
            shutil.copyfile(src, path)
    except Exception:
        # A plate that cannot be adopted is a plate that gets rebuilt. Nothing
        # in here is allowed to be the reason a page fails to open.
        pass


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
# is what makes the sentence honest - "17 spots" is the difference between a
# flaky call and an endpoint that is refusing everything.
#
# `used` counts the regions the model actually cleaned (a fresh answer or a
# cached one). Zero of those and zero failures means nothing was ever sent -
# which is its own thing worth saying, because on "AI for hard areas" a flat
# white bubble never reaches the model at all, so the endpoint sits idle and the
# page looks exactly as it did before.
_AI_CLEAN_FAIL = {"n": 0, "msg": "", "url": "", "used": 0, "cached": 0,
                  # Set once the endpoint has said the token is wrong. See
                  # `_refused_for_good`.
                  "refused": ""}

# The HTTP answers that mean "and it will say the same thing next time".
#
# 401 and 403 are not flakes. They are the endpoint reading the token and
# rejecting it, and nothing about running the next region changes the token. A
# chapter with forty boxes on it therefore made forty round trips to be refused
# forty times, printed forty tracebacks, and buried the one sentence that says
# what to do about it under all of them. lee sent eight of those tracebacks in
# a row with no message between them.
CLEAN_FATAL = (401, 403)


def _refused_for_good(url: str, token: str) -> bool:
    """Has this exact (url, token) already been refused in this run?

    Keyed on both, so pasting a new token or pointing at a new address starts
    asking again immediately -- which is what a person does the second they
    read the warning, and being told "still refused" without the endpoint
    having been asked would be a lie.
    """
    return _AI_CLEAN_FAIL.get("refused") == _refusal_key(url, token)


def _refusal_key(url: str, token: str) -> str:
    import hashlib
    return hashlib.sha1(
        (url + "\x00" + token).encode("utf-8")).hexdigest()[:16]


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
    tok = clean_token_for(p)
    if not tok and not relay_ready():
        msg += " Sign in (the coin, top right) to use the AI cleaner."
    elif not tok:
        pass                        # the relay's own words are in f["msg"]
    elif _token_is_placeholder(tok):
        msg += (" The saved token is still the CHANGE-ME example from the"
                " deploy file — paste the real one into Settings ▸ Page cleaning.")
    elif "401" in (f["msg"] or ""):
        # A 401 with a real token saved has exactly two causes and the machine
        # can tell them apart WITHOUT another call: hash the token against
        # every local `*_clean_modal.py`. lee saw seven lines of "the cleaner
        # refused the token (401)" and one sentence that named neither cause.
        #
        # `clean_check` already does this and says the same two things; it just
        # has to be asked, and nothing on the screen said to ask it.
        msg += " " + _why_401(p, tok)
    return msg


def _why_401(p: Project, tok: str) -> str:
    """Which of the two 401s this is, from the files on this machine.

    The token is a string in a deploy file and a string in Settings. Either
    they differ - the wrong one is pasted - or they agree and the DEPLOYED
    image was built from an older copy of that file, in which case redeploying
    is the whole fix and re-pasting the token will never help.

    Hashes only; nothing here reads a token out loud.
    """
    url = (p.settings.get("clean_url") or "").strip()
    try:
        files = _deploy_files()
    except Exception:
        files = []
    mine = hashlib.sha1(tok.encode("utf-8")).hexdigest()
    # "mangatl-clean" is a substring of "mangatl-clean-lama", so plain
    # containment says the manga app is deployed at the lama app's address -
    # and then a token that is right for the wrong file reads as "matches, go
    # and redeploy". Only the LONGEST name that appears in the URL names it.
    # Same rule as `clean_check`, and it is here because a test drove the two
    # apart.
    named = [f for f in files if f.get("app") and f["app"] in url]
    if named:
        longest = max(len(f["app"]) for f in named)
        named = [f for f in named if len(f["app"]) == longest]
    else:
        named = files
    match = [f for f in named if f.get("sha") == mine]
    if match:
        return ("The saved token matches %s, so the string is right and the "
                "DEPLOYED copy is out of date — run `python -m modal deploy "
                "%s` and it will start working." % (match[0]["file"],
                                                    match[0]["file"]))
    if named:
        return ("The saved token does NOT match %s — copy CLEAN_TOKEN out of "
                "that file into Settings ▸ Page cleaning."
                % ", ".join(f["file"] for f in named[:2]))
    return ("Settings ▸ Page cleaning ▸ Test cleaner says which of the two it "
            "is: a token that does not match the deploy file, or a deployed "
            "copy built before the token changed.")


def _token_state(tok: str | None) -> str:
    """"", "set" or "placeholder" - see project.token_state, which is where the
    one definition lives so the settings screen and this warning agree."""
    return token_state(tok)


def _token_is_placeholder(tok: str) -> bool:
    """The example token that ships in the comment of every *_clean_modal.py.

    Saved, non-empty, and rejected by the endpoint every single time - which is
    exactly the state that read as "(saved)" in the settings field.
    """
    return _token_state(tok) == "placeholder"


def clear_clean_warning() -> None:
    _AI_CLEAN_FAIL.update(n=0, msg="", url="", used=0, cached=0, refused="")
    _CLEAN_TALLY.clear()
    _CLEAN_GIVEUP["on"] = False


# ONE PAGE PAYS FOR THE RETRIES, and the rest of the run believes it. Going
# back at a page the cleaner refused is worth a wait; going back at every page
# of a chapter when the endpoint is simply down is that wait times twenty-three,
# for an answer the first page already gave. A fatal refusal - a 401 or a 403 -
# has `_AI_CLEAN_FAIL["refused"]` for this; everything else, a dead host or a
# timeout, has this, set when a page runs out of goes and cleared with the rest
# of the run's news.
_CLEAN_GIVEUP = {"on": False}


# How the boxes cleaned in this run were cleaned. Same reason as the warning
# above: every question so far about whether the model was doing the hard
# regions has been settled by looking at the page and guessing.
_CLEAN_TALLY: dict = {}


def _tally_clean(stats: dict) -> None:
    for k, v in (stats or {}).items():
        _CLEAN_TALLY[k] = _CLEAN_TALLY.get(k, 0) + int(v)


def clean_report(p: Project) -> str:
    """"18 boxes: 12 filled flat, 6 by the AI." - or "" if nothing was cleaned.

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
    # happened to a box cleaned some other way - the halo could not be trusted
    # there, so only the letter strokes went. Counting it as a route inflated
    # the total and listed it beside the routes as though it were one: lee's
    # page reported *"Cleaned 13 boxes: 6 filled flat, 4 cleaned by the AI, 3
    # core only"* when ten boxes were cleaned and three of those ten were done
    # strokes-only.
    core = t.pop("core only", 0)
    # ...and neither is the second step. It is not a route a box took INSTEAD
    # of one of these; it is the cleaner going back over a box that still had
    # writing standing after the ordinary clean. Counted as a route it would
    # inflate the total and stand beside them as though it were an alternative
    # to the AI, which is the mistake "core only" already made once.
    again = t.pop("second pass", 0)
    # ...nor is the redraw, for the same reason: it is the model being asked to
    # draw a box's cleaned area again, as one piece, on a box two different
    # things had already painted.
    drew = t.pop("redrawn", 0)
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
    if again:
        msg += (f" {again} still had writing on {'them' if again > 1 else 'it'} "
                f"after that and {'were' if again > 1 else 'was'} cleaned a "
                f"second time — that is the pass for gold and other writing no "
                f"fixed shade of grey describes.")
    if drew:
        msg += (f" The AI then drew {drew} of {'them' if drew > 1 else 'those'} "
                f"again in one piece, so the artwork under the writing — a "
                f"panel line, a gradient — is redrawn rather than patched "
                f"twice. Answers that brought the words back were thrown away.")
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
    - tone, gradients, art. A page of plain white balloons therefore sends
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
        # working cleaner came to look broken the moment it started working -
        # the second press of Clean reuses the plates the first one made.
        return ""
    mode = (p.settings.get("ai_clean") or "off").strip()
    if mode not in ("hard", "all") or not cleaner_endpoint(p, token=False)[0]:
        return ""
    if mode == "hard":
        return ("AI cleaning was on but nothing was sent to it — every region "
                "was a flat bubble, which the local fill does better. Choose "
                "\u201cAI for the whole page\u201d if you want the model on all "
                "of them.")
    return ("AI cleaning was on but nothing was sent to it — this page had "
            "nothing left to clean.")


# The page the browser lands on after handing a sign-in to the app (see
# `account.finish_handoff`). Plain on purpose: it is a tab the person is about
# to close, and it says the one thing they need - it worked, go back to the
# app - in the app's own colors.
def _handed_page(what: str, ok: bool) -> str:
    import html as _h
    head = "You are signed in" if ok else "That did not work"
    body = ("MangaTCT is signed in as <b>%s</b>. You can close this tab and go "
            "back to the app." % _h.escape(what)) if ok else \
           ("%s" % _h.escape(what))
    return ("<!doctype html><meta charset=utf-8><title>MangaTCT</title>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<style>body{margin:0;min-height:100vh;display:grid;place-items:center;"
            "background:#1b1c20;color:#e8e6df;font:15px/1.6 system-ui,sans-serif}"
            ".card{max-width:420px;padding:32px 36px;border:1px solid #33353c;"
            "border-radius:12px;background:#22242a}h1{font-size:20px;margin:0 0 10px}"
            "b{color:#fff}p{margin:0;color:#b9b7ae}</style>"
            "<div class=card><h1>%s</h1><p>%s</p></div>" % (head, body))


def _current_project(p: Project) -> dict:
    """What is open right now, for the Home screen's Continue card."""
    try:
        n = len(p.pages)
    except Exception:
        n = 0
    fp = str(p.settings.get("project_file") or "").strip()
    name = os.path.splitext(os.path.basename(fp))[0] if fp else ""
    return {"pages": n, "name": name or ("Current project" if n else ""),
            "path": fp, "medium": str(p.settings.get("medium") or "")}


def _update_state() -> dict:
    """What the launcher knows about a newer version, if a launcher started
    this process at all.

    The launcher and the editor are two programs and talk through one small
    file rather than a socket: the launcher writes `update.json` beside its
    own state - `{"available": "1.0.1", "state": "ready"}` - and names it in
    `MANGATL_UPDATE_FILE`. The editor reads it when the header asks and
    shows a line; the switch itself happens on the next start, in the
    launcher, where nothing of the person's is open. A checkout run by hand
    has no such file and says nothing.

    Read on demand and never cached, because the launcher rewrites it while
    the download runs and "downloading" should become "ready" on screen
    without a restart.
    """
    fp = (os.environ.get("MANGATL_UPDATE_FILE") or "").strip()
    if not fp or not os.path.isfile(fp):
        return {}
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    if not isinstance(d, dict) or not d.get("available"):
        return {}
    return {"update": {"available": str(d.get("available")),
                       "state": str(d.get("state") or "ready"),
                       "notes": str(d.get("notes") or "")}}


#: What a key looks like in a log line. Scrubbed before a log tail is put in
#: front of a person about to paste it into a chat.
_KEYISH = re.compile(r"(sk-ant-[0-9A-Za-z_\-]{8,}|sk-(?:or-)?[A-Za-z0-9]{16,}|"
                     r"AIza[0-9A-Za-z_\-]{20,}|Bearer\s+[A-Za-z0-9._\-]{12,})")


def _log_tail(n: int = 80) -> list[str]:
    """The last lines of the editor's own console, when a launcher is
    keeping one (`MANGATL_LOG_FILE`). A checkout run by hand has the
    console itself and gets nothing here."""
    fp = (os.environ.get("MANGATL_LOG_FILE") or "").strip()
    if not fp or not os.path.isfile(fp):
        return []
    try:
        with open(fp, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 64_000))
            lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return []
    return [_KEYISH.sub("<key>", ln) for ln in lines]


def _diagnostics(p) -> dict:
    """Everything a support message should start with, and nothing it must
    not carry: the version, the machine, the chapter's shape, which keys are
    PRESENT (never their value), and the tail of the log with anything
    key-shaped taken out. Shown to the person before they send it."""
    import platform
    from . import version as _v
    from .project import _machine_line
    try:
        from . import userdata as _ud
        keys = {k: bool(v) for k, v in (_ud.env_state() or {}).items()}
    except Exception:
        keys = {}
    routes = [k for k, _n in getattr(p, "ROUTE_NAMES", []) if p.settings.get(k)]
    return {
        "version": _v.__version__,
        "channel": _v.CHANNEL,
        "launcher": os.environ.get("MANGATL_LAUNCHER") or "",
        "python": platform.python_version(),
        "os": "%s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
        "machine": _machine_line(),
        "chapter": {"pages": len(p.pages), "medium": p.settings.get("medium"),
                    "source": p.settings.get("source"), "routes": routes,
                    "ocr": p.settings.get("ocr_reader"),
                    "models": {k: p.settings.get(k) for k in
                               ("ocr_model", "translate_model", "proofread_model")
                               if p.settings.get(k)}},
        "keys_present": keys,
        "log": _log_tail(),
        "support": _v.SUPPORT,
    }


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
    `CLEAN_TOKEN` - enough to answer "is the token I saved the token that file
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
            # `modal.App("mangatl-clean-" + MODEL)` - the deployed name is the
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
    url, tok, relayed = cleaner_endpoint(p)
    files = [] if relayed else _deploy_files()
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
           "relayed": relayed,
           "files": files, "ok": False, "error": "", "hint": ""}
    if not url or not tok:
        res["error"] = "The AI cleaner needs you signed in."
        res["hint"] = "Sign in with the coin at the top right, then test again."
        return res

    img = np.full((64, 64, 3), 235, np.uint8)
    cv2.rectangle(img, (20, 20), (44, 44), (30, 30, 30), -1)
    mask = np.zeros((64, 64), np.uint8)
    cv2.rectangle(mask, (18, 18), (46, 46), 255, -1)
    before = _AI_CLEAN_FAIL["n"]
    with tempfile.TemporaryDirectory() as tmp:      # never the real cache
        try:
            # ...with the eraser the project actually uses, so a Test
            # cleaner that passes is a test of the thing that will run.
            _ai_clean_call(url, tok, tmp, img, mask, strict=True,
                           model=clean_model(p))
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
                   strict: bool = False, *,
                   # WHICH ERASER, keyword-only and defaulted to the same one
                   # the endpoint falls back to. Keyword-only because the four
                   # positional arguments in front of it are the question
                   # being asked, and a fifth one that is easy to slot into
                   # the wrong place is how a mask ends up being read as a
                   # model name.
                   model: str = CLEAN_MODELS[0]) -> np.ndarray:
    """POST the page + text mask to the hosted manga cleaner, return the
    cleaned image. The result is CACHED on disk by the exact (image, mask)
    content, so revisiting or re-rendering a page never calls the API again -
    it only runs when the boxes (and therefore the mask) actually change. On
    any failure it falls back to a local inpaint so a run never breaks."""
    import hashlib
    # The token is in the key for the same reason it is in the plate stamp: the
    # answer to this exact (image, mask, url) is different when the token is
    # accepted than when it is refused.
    key = hashlib.sha1(img.tobytes() + mask.tobytes()
                       + url.encode("utf-8")
                       + token.encode("utf-8")
                       # ...and the MODEL, for the third time in this file and
                       # for the same reason: two erasers give two answers to
                       # one question, and a cache that cannot tell them apart
                       # hands back the one nobody asked for.
                       + model.encode("utf-8")).hexdigest()
    fp = os.path.join(cache_dir, key + ".png")
    if os.path.exists(fp):
        cached = imgio.imread(fp)
        if cached is not None and cached.shape[:2] == img.shape[:2]:
            _AI_CLEAN_FAIL["used"] += 1     # the model's answer, from the cache
            _AI_CLEAN_FAIL["cached"] += 1
            return cached

    # NO TOKEN AT ALL is the same shape of question, and it became a common
    # one the moment the address shipped built in (`project.CLEAN_URL`): a new
    # project has a cleaner to talk to and nothing to prove it with. The answer
    # is knowable here, so it is answered here - a 401 is what the endpoint
    # would say, and waiting three minutes a box to be told so is the only
    # thing a round trip would add. `clean_warning` names the missing token.
    if not token:
        # No token of their own and none from the relay: not signed in.
        _AI_CLEAN_FAIL["n"] += 1
        _AI_CLEAN_FAIL["msg"] = "nobody is signed in"
        if strict:
            raise RuntimeError(_AI_CLEAN_FAIL["msg"])
        return cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

    # Already refused this exact token at this exact address? Then the answer
    # is known and the round trip is waste. Straight to the local fill --
    # except under `strict`, where the caller has a better fallback of its own
    # and has to be told rather than quietly handed Telea.
    if _refused_for_good(url, token):
        _AI_CLEAN_FAIL["n"] += 1
        if strict:
            raise RuntimeError(_AI_CLEAN_FAIL["msg"]
                               or "the cleaner refused the token")
        return cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

    try:
        import base64
        import json as _json
        import urllib.request
        body = _json.dumps({
            "token": token,
            # WHICH ERASER. One deploy serves both now, so this is a setting
            # and not a redeploy. lee, after seven of them were measured on his
            # own chapter: *"anime lama is the shout, add it in the list"* -
            # anime-lama landed nearer the surrounding artwork on 6 of 9 hard
            # boxes at the same speed, and was one of only two that never drew
            # something that had never been on the page.
            #
            # An endpoint that has never heard of the field ignores it and
            # serves what it was deployed with, so an old deploy keeps working.
            "model": model,
            "image": base64.b64encode(cv2.imencode(".png", img)[1]).decode(),
            "mask": base64.b64encode(cv2.imencode(".png", mask)[1]).decode(),
        }).encode("utf-8")
        # The token in the body is what our own deploy reads; the same
        # string in the header is what the relay reads (an ID token, there).
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json",
                                     "Authorization": "Bearer " + token})
        # A page whose cleaner hangs holds that page's build for this long,
        # and anything waiting on the same page waits with it. Three minutes
        # was long enough that it read as the app being dead.
        with urllib.request.urlopen(req, timeout=CLEAN_TIMEOUT) as resp:
            data = resp.read()
        out = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if out is None or out.shape[:2] != img.shape[:2]:
            raise ValueError("cleaner returned an unusable image")
        imgio.imwrite(fp, out)
        clear_clean_warning()          # it is working again; drop the old news
        _AI_CLEAN_FAIL["used"] += 1
        return out
    except Exception as e:
        import urllib.error
        fatal = (isinstance(e, urllib.error.HTTPError)
                 and e.code in CLEAN_FATAL)
        # The traceback is for the failure nobody has diagnosed yet. A refused
        # token IS diagnosed -- `clean_warning` says which setting to change --
        # so printing the stack once is a courtesy and printing it once per box
        # buries the sentence that helps.
        if not fatal:
            traceback.print_exc()
        else:
            # Reached once per (url, token): the next call for the same pair
            # turns back at the top of this function and never gets here.
            print("mangatl: " + _clean_error_text(e) + " -- "
                  + "not asking again this run. " + url, flush=True)
        # never break a run over the network: fall back to the local fill
        globals()["_LAST_AI_CLEAN_ERROR"] = f"{type(e).__name__}: {e}"
        _AI_CLEAN_FAIL["n"] += 1
        _AI_CLEAN_FAIL["msg"] = _clean_error_text(e)
        _AI_CLEAN_FAIL["url"] = url
        if fatal:
            _AI_CLEAN_FAIL["refused"] = _refusal_key(url, token)
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
    url, token, _relayed = cleaner_endpoint(p)
    if mode not in ("hard", "all") or not url:
        return None, False
    cache_dir = _ai_clean_cache_dir(p)

    model = clean_model(p)

    def neural(img, mask):
        return _ai_clean_call(url, token, cache_dir, img, mask, strict,
                              model=model)

    return neural, (mode == "all")


def _make_reader(p: Project):
    """The thing that says where writing is - comic-text-detector's
    segmentation head, the one thing in the app that answers that question.

    The cleaner asks it twice, and they are two different questions:

      * of the SCAN, before anything is erased - what IS the writing here.
        A saved region carries no bitmap, so without this the mask is "the dark
        pixels in the box", and on a sound effect over screentone that is the
        screentone. See `inpaint._reader_ink`. lee, with the crop: *"see how i
        can see the lines of teh clenner that shoud not happen it should clenly
        fit with teh art"*.
      * of the FINISHED PLATE - what is still legible that no mask covered.
        lee: *"i also want to create a systhem that looks for thet text ain the
        boxes and tells teh clenner where they are"*. See `inpaint._reread`.

    The same weights the page was detected with, so there is nothing to set up
    and nothing to download: a project that can find its text can clean it with
    what found it. With no weights there is no reader and the cleaner behaves
    exactly as it did before. Two forward passes a page - about four seconds -
    and only on a page actually being cleaned, never on one answered from the
    cache.
    """
    if not p.settings.get("clean_reread", True):
        return None
    w = p.detector_weights()
    if not w:
        return None
    from .detect import comictext
    keep = comictext.tuning_for(getattr(p, "medium", "")).get("mask_thresh") \
        or comictext.SEG_KEEP

    def look(img):
        try:
            return comictext.page_text_mask(img, w, keep)
        except Exception:
            # A missing or unreadable weights file is a reason to skip the
            # check, not a reason to fail the clean: the page is still cleaned,
            # it is only the second opinion that is missing.
            traceback.print_exc()
            return None

    return look


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
    """Produce page.clean_plate - the person's own plate if they gave one.

    A page with its own cleaned file is not cleaned at all: the file IS the
    plate, always, and nothing is inpainted, sent to the hosted cleaner, or
    pasted back over it. lee: *"if i uploade my own file it shoud exclude that
    page from cleaing and shoud alway use the uploadd page as a cleneed page"*.
    That includes the per-bubble eyes - an eye says which bubbles the cleaner
    should erase, and on this page the cleaner never runs.

    Only the page it was uploaded for: everything else keeps the automatic
    cleaning.

    The expensive inpainting runs once with EVERY bubble cleaned and is
    cached; an eye toggle then just pastes the original pixels back over
    that bubble (or removes them) - instant, instead of re-inpainting the
    whole page for each click.
    """
    cc = own_plate_path(p, i)
    custom = None
    if cc:
        img = imgio.imread(cc)
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
        # Already built, in memory. Nothing is sent to the model for this page -
        # which is the whole point of the cache, and must not be reported as the
        # model having failed to run.
        _tally_clean({"reused": 1})
    if full is None:
        fp = _plate_disk_path(p, i)
        if os.path.exists(fp):
            got = imgio.imread(fp)
            if got is not None and got.shape[:2] == page.image.shape[:2]:
                full = got
                # NOT TOUCHED. The plate's file time is part of the key of
                # every picture built from it, so marking it as recently used
                # would throw those pictures away. See `_plate_mark`.
                _tally_clean({"reused": 1})
        if full is None and not _may_spend_the_cleaner(p):
            # THE BUTTON IS THE ONLY THING THAT GOES TO THE MODEL. lee: *"it
            # shoudnt rebuild everytime, it shoud ony go to the ai when i clcik
            # the button"*.
            #
            # `render_index` has said "looking at a page is not cleaning it"
            # for a long time, and it holds - but Typeset and Export call in
            # here directly, and so does anything else that wants a plate. On
            # a page whose last clean was refused there is no plate to find,
            # so every one of them rebuilt it and went back to the endpoint.
            # With the hosted cleaner on, a page nobody has successfully
            # cleaned is simply not cleaned: what everything downstream gets
            # is the scan, which is the honest picture of a page nothing was
            # erased from.
            page.clean_plate = page.image.copy()
            _composite_paint(p, i, page, include_paint)
            return
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
                # Two steps, and both of them inside here: the ordinary clean,
                # and then a second one over whatever it left standing. See
                # `inpaint.second_pass`. There is nothing to configure - a box
                # the first step cleaned is never touched by the second.
                inpaint_mod.inpaint_page(page, neural=neural,
                                         neural_all=neural_all,
                                         look=_make_reader(p))
            finally:
                for r, v in saved:
                    r.skip_clean = v
            _tally_clean(getattr(page, "clean_stats", None) or {})
            _tally_clean({"built": 1})     # a plate actually made, here, now
            # ...and the one place the cleaning fee belongs, for exactly that
            # reason. lee: *"the clenning fee shud be a flat fee per page"*. A
            # plate that came out of the cache never reaches this line, nor
            # does a page with a cleaned file of its own, and neither of them
            # cost anything to produce - so neither is charged for. Cleaning
            # reached through Export, Typeset or the background page-builder is
            # charged the same as pressing Clean, because it is the same work.
            #
            # The fee is for the HOSTED cleaner, so it is charged when the
            # hosted cleaner actually did some of this page. A chapter filled
            # flat on this machine is somebody's own CPU and is free, exactly
            # as Typeset and Export are - charging a fee for it would be
            # charging for nothing, and it would be charged silently, because
            # the page-builder cleans pages nobody asked it to.
            #
            # ...and it is charged for a plate that is KEPT.
            #
            # A plate built while the cleaner was refusing is NOT this page's
            # plate - it is the local fallback wearing its name. Caching it is
            # how "click Clean again" came to do nothing at all: the second
            # press found the smeared plate on disk, reused it in a few
            # milliseconds, and never called the endpoint, so fixing the token
            # changed nothing and Modal showed no activity. So it is thrown
            # away, and the page reads as not cleaned - the view shows the
            # scan rather than a half-model page dressed up as finished.
            #
            # Thrown away means BUILT AGAIN, and built again used to mean paid
            # for again: lee's page 001 changed picture while he looked at it
            # and was billed for every version, three visits, three fees. The
            # fee is for a page you got. A build nobody kept is not one, so it
            # costs nothing however many times it is attempted. lee: *"ill just
            # eat the extra cost , can you fx this thought ... 1 more every
            # time you open that page"*.
            #
            # The endpoint is not paid twice either: every answer it DID give
            # is cached inside `_ai_clean_call` by its own (image, mask), so a
            # rebuild only asks about the boxes that failed.
            full = page.clean_plate
            if _AI_CLEAN_FAIL["n"] > before:
                # ...but held on to while `do_clean` is still going back at it,
                # so that when none of the goes comes out whole the page shows
                # the BEST of them rather than the bare scan. lee: *"if teh
                # build failes after 4 trues still show teh nbest version fo teh
                # failes so we show shoeming"*. Best is fewest boxes refused -
                # the go the model did most of.
                if _KEEP_BEST["on"]:
                    n = _AI_CLEAN_FAIL["n"] - before
                    if _KEEP_BEST["fails"] is None or n < _KEEP_BEST["fails"]:
                        _KEEP_BEST.update(fails=n, plate=full.copy())
                return _finish_plate(p, i, page, full, include_paint)
            try:
                from . import coins
                if int((getattr(page, "clean_stats", None) or {}).get(
                        "neural", 0) or 0) > 0:
                    coins.flat(coins.quote_page("clean"), "clean",
                               getattr(p.pages[i], "name", ""))
            except Exception:
                traceback.print_exc()
            try:
                # Level 1: the plate is written once and read many times, and
                # squeezing it harder costs more than it ever saves back.
                imgio.imwrite(fp, full, [cv2.IMWRITE_PNG_COMPRESSION, 1])
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
        # used to paste back a RECTANGLE - its box plus 16 pixels - and boxes on
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
                # nothing was recorded for this box - fall back to its rectangle
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
    o = imgio.imread(ov, cv2.IMREAD_UNCHANGED)
    if o is None or o.ndim != 3 or o.shape[2] != 4             or o.shape[:2] != page.clean_plate.shape[:2]:
        return
    a = o[:, :, 3:4].astype(np.float32) / 255.0
    page.clean_plate = (page.clean_plate.astype(np.float32) * (1.0 - a)
                        + o[:, :, :3].astype(np.float32) * a).astype(np.uint8)


def _composite_over(p: Project, i: int, img):
    """Paint that sits ABOVE the typesetting, laid on after the text is drawn.

    The other overlay goes onto the plate before anything is typeset; this one
    is the last thing that happens to the page. Two bands is the whole model -
    a drawing is either under all the text or over all of it - which is what
    lee asked for when offered the choice against a free interleave.
    """
    ov = getattr(p.pages[i], "paint_over", "") or ""
    if not ov or not os.path.exists(ov):
        return img
    o = imgio.imread(ov, cv2.IMREAD_UNCHANGED)
    if o is None or o.ndim != 3 or o.shape[2] != 4 or o.shape[:2] != img.shape[:2]:
        return img
    a = o[:, :, 3:4].astype(np.float32) / 255.0
    return (img.astype(np.float32) * (1.0 - a)
            + o[:, :, :3].astype(np.float32) * a).astype(np.uint8)


# One lock PER PAGE, not one for the whole editor.
#
# Building a page materialises it, writes layouts back and mutates the shared
# project, so two builds of the SAME page must not overlap. Two builds of two
# DIFFERENT pages have nothing to say to each other - and a single global lock
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
                 paint: bool = True, commit: bool = True) -> bytes:
    """Three views of a page.

    original  the scan as it came in
    clean     source text erased, nothing added - shows what the inpainter did
    typeset   the finished page

    `commit=False` DRAWS WITHOUT WRITING ANYTHING DOWN.

    Building the typeset view lays the page out again and commits the result,
    which is right for the view somebody is working in - the layout it just
    computed is the layout that belongs on the record. It is wrong for a view
    that appears BY ITSELF: the editor now settles into this picture a moment
    after every edit (`static/js/exactview.js`), and laying the page out again
    behind the person's back overwrites the thing they were doing.

    It cost four tests to find that out, all of them about an emptied box: an
    empty block is a decision, `typeset_page` fills it back in from the words,
    and a commit made that stick. lee's *"if i dlete all teh text from a text
    box its shoud accesp the edit"* has a test each in three files and every
    one of them caught this.

    The picture is identical either way. Only the write-back differs - as it
    already does on a cache hit, which returns before any of this.
    """
    key = _render_stamp(p, i, mode) + (bool(paint),)
    hit = _render_cache.get(key)
    if hit is not None:
        _touch(_render_cache, key)
        return hit
    # ...and then off the disk, which is the difference between a restart
    # costing nothing and costing the whole chapter again. A finished page is
    # three seconds to build and five milliseconds to read; it has no business
    # being built twice. See `_render_disk_path`.
    hit = _render_from_disk(p, i, key)
    if hit is not None:
        _render_cache[key] = hit
        _touch(_render_cache, key)
        return hit

    # Building a page materialises it, writes layouts back and mutates the
    # shared project. The server answers on threads and a background warm-up
    # walks the whole chapter, so two of those overlapping is a real
    # possibility now - one at a time, and the warm-up drops the lock between
    # pages so a person clicking never waits more than the page in flight.
    with _page_lock(i):
        hit = _render_cache.get(key)
        if hit is not None:
            _touch(_render_cache, key)
            return hit
        page = p.materialize(i)
        # LOOKING AT A PAGE IS NOT CLEANING IT.
        #
        # This used to inpaint on demand: opening the Image view on a page
        # nobody had cleaned built the plate right then. So browsing a chapter
        # quietly ran the cleaner - lee got seven "the cleaner refused the
        # token (401)" lines out of turning pages, and: *"if i move to teh
        # image tab and i havnt done teh clenneing it shud just show teh
        # unclened age not clen them until i clean teh page"*.
        #
        # It also showed the wrong picture. A view that cleans on sight cannot
        # show what a page looks like BEFORE cleaning, so there is no way to
        # judge whether the Clean step is worth running - and the Clean
        # button reads 7/67 while every page you open is cleaned.
        #
        # `cleaned` is set by the Clean step and by an uploaded plate, and
        # cleared whenever the text changes, so this follows the button.
        done = bool(p.pages[i].cleaned) or bool(own_plate_path(p, i))
        if mode == "original" or not page.regions:
            img = page.image
        elif mode == "clean" and not done:
            img = page.image             # nothing has been erased yet
        else:
            if done:
                clean_page(p, i, page,
                           include_paint=(paint or mode != "clean"))
            else:
                # The English still goes on - over the page as it came, which
                # is what it will look like until Clean runs. `clean_plate` is
                # what the typesetter draws onto, so it is the scan.
                page.clean_plate = page.image.copy()
            if mode == "clean":
                img = page.clean_plate
            else:
                cfg = _typeset_cfg(p)
                typeset_mod.typeset_page(page, cfg)
                img = _composite_over(p, i, render_mod.render_page(page, cfg))
                if commit:
                    p.commit(i, page)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        out = buf.tobytes() if ok else b""
        if out:
            _render_to_disk(p, i, key, out)
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
    # WHICH PROJECT, as well as which page. The key used to be the page number
    # and how many boxes are on it, which is a description of a page in the
    # abstract - so page 0 of one chapter with one box on it was a cache HIT
    # for page 0 of a different chapter with one box on it, and the second
    # chapter got handed the first one's artwork and the first one's words.
    #
    # It cannot happen while one project is open, which is why it went unseen.
    # It happens the moment two exist in one process, and what made it visible
    # was a test opening a second project to preview one region: the answer
    # came back laid out in the other project's sentence.
    key = (p.output_dir, i, len(p.pages[i].regions),
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
    anything that already has one. That is right almost always - a shape found
    once should not wander - and it is exactly wrong after the artwork it was
    read from has been mended.

    lee: the cleaner rubbed a piece out of a balloon's edge, the run of paper
    joined the balloon next to it, and the fitter started typesetting into a
    shape twice the size. He painted the edge back and nothing changed,
    because the wrong shape was already frozen into the record - *"the
    typeseetting is not registerng that and is still typessting as if the box
    was open"*.

    So paint that lands on or near a stored outline drops that outline, and
    the next page build looks again - at `Project.repaired`, which is the scan
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
                    # greyed rather than moved - lee: *"it shoud stay inplace
                    # instad of going to teh bottom, and just grey out"* - and
                    # "the same row, greyed" cannot be drawn out of a record
                    # with the score and the link missing from it.
                    "confidence": float(rec.get("confidence") or 0.0),
                    "own_text": bool(rec.get("own_text")),
                    "link": rec.get("link")})
    out.sort(key=lambda r: r["order"])
    return out


def _css_rgba(c) -> str:
    """An (r, g, b, a) colour as CSS the browser can use directly.

    Always `rgba`, never `rgb`, because the alpha is the point: writing drawn
    as a hollow outline has NO fill, and the preview draws these strings into
    `color` and `-webkit-text-stroke`. There is no flag to carry "no fill"
    across - a colour with a zero alpha carries it, and every other colour
    goes through the same line unharmed.
    """
    r, g, b = (int(v) for v in c[:3])
    a = (int(c[3]) if len(c) > 3 else 255) / 255.0
    return "rgba(%d,%d,%d,%s)" % (r, g, b, ("%.3f" % a).rstrip("0").rstrip("."))



def _clean_spans(v):
    """Character-range styles, sanitized: offsets as ints, styles cut to
    the paint-only keys `render.SPAN_KEYS` allows, junk dropped. Offsets
    index the flat text of the block's lines joined with newlines."""
    if not isinstance(v, list):
        return []
    numeric = {"grad_angle", "edge_angle", "glow_size", "iglow_size",
               "sh_dist", "sh_blur", "opacity", "font_size"}
    out = []
    for sp in v[:200]:
        if not isinstance(sp, dict):
            continue
        try:
            s0, e0 = int(sp.get("s")), int(sp.get("e"))
        except (TypeError, ValueError):
            continue
        st = sp.get("st") or {}
        if not isinstance(st, dict) or s0 < 0 or e0 <= s0:
            continue
        keep = {}
        for k in render_mod.SPAN_KEYS:
            val = st.get(k)
            if val in (None, ""):
                continue
            try:
                if k in numeric:
                    keep[k] = float(val)
                elif k == "stroke":
                    keep[k] = int(val)
                else:
                    keep[k] = str(val)
            except (TypeError, ValueError):
                continue
        # A SIZE and a FACE are not paint, and neither is free to be
        # anything: a size outside what the panel's stepper can reach is a
        # typo or a bad client, and a face has to be one this app offers -
        # the same list `/fontfile` will serve the preview from, so the two
        # renderers cannot be pointed at different files.
        if "font_size" in keep and not 1.0 <= keep["font_size"] <= 400.0:
            keep.pop("font_size")
        if "opacity" in keep:
            keep["opacity"] = max(0.0, min(100.0, keep["opacity"]))
        if "font" in keep and not _font_is_offered(keep["font"]):
            keep.pop("font")
        if keep:
            out.append({"s": s0, "e": e0, "st": keep})
    return out


def _font_is_offered(fp: str) -> bool:
    """Is this one of the faces the app itself offers? The span's face
    arrives from the browser, so it is checked against the list rather than
    opened on trust."""
    if not fp:
        return False
    try:
        ok = {f["path"] for f in find_fonts()}
    except Exception:
        return False
    p = PROJECT
    if p is not None:
        try:
            cfg = _typeset_cfg(p)
            ok |= {v for v in ([cfg.font_path]
                               + list((cfg.fonts or {}).values())) if v}
        except Exception:
            pass
    return fp in ok


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
            # Emptying a box keeps the box, at the size it was - and the size
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
            # the page divides it - the preview has to answer the same shape
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
                # pulled back inside the region - clamping it there is what
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
    # THE SAME THREE CALLS THE EXPORTER MAKES, and the override this preview
    # is about handed to each of them.
    #
    # It used to be `hex_rgb(o.get("fg")) or fg`, worked out here - which knew
    # about a hand edit and nothing about `layout_measured`. So the measured
    # style was on the page and gone the moment a box was selected, because
    # selecting one asks this endpoint and the answer it gives becomes
    # `r.style`, which the preview prefers over everything.
    # lee: *"the changes ate only appkied when i select a box"*.
    #
    # The override goes in as an ARGUMENT rather than onto the region, because
    # the region's own was put back a few lines above (the lock, and the
    # `finally`) - and it has to be, this is a shared object on a threaded
    # server.
    fg, edge = render_mod.colours_for(region, fg, edge, o)
    stroke = render_mod.stroke_for(region, stroke, o)
    fg, edge = render_mod._hollow_colours(region, fg, edge, o)
    # The light a letterform with nothing inside it gets on both sides of its
    # line, worked out here so the browser previews the page it is going to get
    # rather than a barer one. Same call, same arguments as `render_page`.
    _glow = render_mod.auto_glow(region, lay, fg, edge, o)
    _iglow = render_mod.auto_glow(region, lay, fg, edge, o, key="iglow")
    return {"lines": lay.lines, "font_size": int(lay.font_size),
            "leading": round(float(lay.leading), 3),
            "lspace": float(o.get("lspace") or 0),
            "shadow": (o.get("shadow")
                       if render_mod.hex_rgb(o.get("shadow")) else ""),
            "sh_dist": float(o.get("sh_dist") or 2),
            "sh_blur": float(o.get("sh_blur") or 3),
            "curve": float(o.get("curve") or 0),
            # What the page is DRAWN with, automatic halo included...
            "glow": (o.get("glow") if render_mod.hex_rgb(o.get("glow"))
                     else (render_mod._css(_glow[0]) if _glow else "")),
            "glow_size": (float(_glow[1]) if _glow
                          else float(o.get("glow_size") or 6)),
            # ...and what somebody chose, which is what a save may send back.
            # The well shows the first and reports the second; see
            # `panels.wellChosen` and the `fg_set` note below.
            "glow_set": (o.get("glow")
                         if render_mod.hex_rgb(o.get("glow")) else ""),
            "iglow": (o.get("iglow") if render_mod.hex_rgb(o.get("iglow"))
                      else (render_mod._css(_iglow[0]) if _iglow else "")),
            "iglow_size": (float(_iglow[1]) if _iglow
                           else float(o.get("iglow_size") or 5)),
            "iglow_set": (o.get("iglow")
                          if render_mod.hex_rgb(o.get("iglow")) else ""),
            "opacity": (100 if o.get("opacity") in (None, "")
                        else max(0, min(100, int(o["opacity"])))),
            "origins": [[int(a), int(b)] for a, b in lay.line_origins],
            "fit_ok": bool(lay.fit_ok),
            "kind": region.kind,
            # `rgba`, because a hollow letterform has no fill and CSS needs to
            # be told so in a colour rather than in a flag: the browser reads
            # these straight through as `color` and `-webkit-text-stroke`.
            "fg": _css_rgba(fg),
            "edge": _css_rgba(edge),
            # ...AND WHICH OF THE TWO SOMEBODY ACTUALLY CHOSE.
            #
            # The pair above is what the page is DRAWN in, and most of the time
            # nobody chose it: `_ink_colours` reads the artwork and decides
            # which way round the block goes. The browser needs those to draw
            # its preview - but it also puts them in the side panel's colour
            # wells, where a colour stops being a readout and becomes the
            # control, because the next save sends whatever is standing in the
            # well.
            #
            # So touching any field at all - the outer glow's size, say - wrote
            # the automatic pair into the override as though it had been
            # picked, and from that moment the page could not change its mind
            # about the block: `colours_for`'s rule for an edge nobody set
            # stops applying, and `_ink_colours` is not consulted again.
            # lee: *"when changing the outerglow number, the outline color also
            # switches"*.
            #
            # Every other colour on this answer already reports the OVERRIDE
            # rather than the result. These two could not, because the preview
            # needs the drawn colour to draw with - so they say both. `o` is
            # the override alone, deliberately: a MEASURED ink is a finding,
            # not a choice, and promoting one to a hand edit is the same bug
            # `_hollow_colours` already refuses to commit.
            "fg_set": (o.get("fg") if render_mod.hex_rgb(o.get("fg")) else ""),
            "edge_set": (o.get("edge")
                         if render_mod.hex_rgb(o.get("edge")) else ""),
            # `stroke_for` above has already ranked the hand edit over the
            # measurement over the automatic; doing it again here with only
            # the first of the three was the same divergence one line lower.
            "stroke": int(stroke),
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
    clean layout short of undoing each block one at a time - the button that
    was supposed to be the reset was the one thing that could not reset.

    `reset=False` is for the re-typeset that follows NEW WORDS ARRIVING - a
    translation file uploaded, a model's reply pasted in. Nobody pressed
    Typeset there, so nothing of lee's is thrown away: the boxes he drew
    himself stay where they are, saying what they say. Sweeping them up as
    part of a courtesy re-typeset would delete work he never asked to lose.
    """
    # Boxes somebody drew themselves, holding words of their own rather than
    # a translation of anything on the page.
    own = [r for r in p.pages[i].regions if r.get("own_text")]
    if own:
        p.pages[i].remember_ids()          # ...before their numbers leave with them
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
    # `materialize` builds every region fresh and carries no layout - every
    # stage re-fits - so the stored record is the only thing that knows there
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
    # WHAT THE ORIGINAL LETTERS WERE PAINTED WITH, measured again, here.
    #
    # `inkstyle.measure_page` writes its answer into `layout_override` - and
    # `reset` above has just emptied every one of those, which is right for a
    # hand correction and wrong for this. A measurement is a fact about the
    # artwork, not something somebody typed, and it was being thrown away as
    # if it were.
    #
    # It ran in exactly one place, at the end of the read. Typeset always
    # comes after the read. So the FIRST press of Typeset deleted the answer,
    # every time, and no chapter has ever been typeset in the measured style:
    # what shipped was the fallback - white letters, a black rim, and a rim of
    # about a seventh of the point size. On lee's chapter every sound effect
    # bears it: 144→20, 134→19, 105→15, 92→13, 77→11, 36→5. A rim
    # proportional to the size is the exact thing the measurement exists to
    # stop; a pen has a width.
    #
    # lee, over his page 001: *"i feel like all the copy style chnages that we
    # worked on is not live"*. It was not. His `ザァァ` is black with a 4px
    # white keyline and came out white with a 20px black one - inverted, and
    # five times the rim.
    #
    # HERE rather than at the read, because "the last moment before cleaning"
    # was never true. Cleaning writes a PLATE; `input/001.jpg` keeps the
    # Japanese for ever. Measured on his chapter months after it was read, all
    # sixteen regions answer. And it costs nothing: no key, no coins, no call.
    #
    # Before `clean_page` so it is the original page being read, and it only
    # ever fills blanks, so a colour somebody chose is still theirs.
    try:
        from .inkstyle import measure_page as _measure_ink
        if getattr(p, "ink_seen", None) is None:
            p.ink_seen = {}
        _measure_ink(page, p.ink_seen)
    except Exception:
        pass                     # a colour is a nicety; the words are the job
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

    The series title if there is one - it is what the person would type
    themselves - then whatever the file was called last time, then the folder
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
    project.json goes through - nothing gets a second, quietly different way
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
    # THE CLEANED PAGES, re-keyed into this machine's cache. Only now: the
    # name a plate is cached under is computed from the loaded project, and
    # `_kinds.use` above has to have run or the stamp asks about sub-types
    # this build has not heard of yet.
    _take_in_carried_plates(p)
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
# and a drawn sound. A sub-type is unballooned when its FAMILY is - a box's
# geometry is decided by which of the three it is, never by which sub-type.
NO_BALLOON_KINDS = ("freefloat", "sfx")


def _no_balloon(kind: str) -> bool:
    return _kinds.family_of(kind or "") in NO_BALLOON_KINDS


def _kind_changed(rec: dict, was: str) -> None:
    """Make a change of box type actually change the typesetting.

    lee: *"i changed teh bubble to outside buuble an it still typeseete the
    same"*. He was right and the reason is worth writing down. A chapter is
    held as GEOMETRY - masks are rebuilt on every load - and the balloon a
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


def _region_kind_changed(r, was: str) -> None:
    """`_kind_changed`, for a REGION on a materialised page rather than a
    record on disk.

    Same rule and the same reason - a box called outside text still carrying a
    balloon's polygon typesets into the balloon's shape, which is what lee saw:
    *"i changed teh bubble to outside buuble an it still typeseete the same"*.
    The two are separate functions because they work on separate things: the
    endpoint edits a stored record and `label_page_kinds` edits a live page on
    its way to being committed.

    Reached only when a family actually moved, which for the labeller means the
    sound-effect-against-outside-text correction and nothing else.
    """
    from .typeset import FITTING_KEYS as _FK
    if _no_balloon(getattr(r, "kind", "")):
        x, y, w, h = (int(v) for v in r.bbox)
        r.polygon = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        r.bubble_bbox = (x, y, w, h)
        # ...and the mask built from the OLD polygon, which is still in memory
        # and would otherwise be what this page is typeset against if anything
        # reached for it before the commit and reload.
        r.bubble_mask = None
    ov = dict(getattr(r, "layout_override", None) or {})
    for k in list(ov):
        if k in _FK:
            ov.pop(k, None)
    r.layout_override = ov or None
    r.layout = None


def drop_plate(p: Project, i: int) -> None:
    """Throw away this page's finished plate so the next clean rebuilds it.

    The plate cache exists so that MOVING to a page is instant. Pressing Clean
    is not moving to a page - it is asking for the work to be done - so the
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


CLEAN_TRIES = 4        # goes at one page before the endpoint is given up on
CLEAN_WAIT = 3.0       # seconds between them, so a busy endpoint can catch up


def do_clean(p: Project, i: int, force: bool = False) -> None:
    """Produce (and cache) the cleaned plate for one page. Its own pipeline
    step so the expensive AI cleaning can be run and cached up front, before
    typesetting - the plate is reused from cache afterwards.

    `force` is the Clean button: redo the page rather than reuse it.

    THE WHOLE PAGE, HERE, IN THE JOB. A flaky endpoint refuses a box or two
    and the plate that comes back is part model and part local fallback -
    which `clean_page` then declines to cache, correctly, so that pressing
    Clean again really retries. What used to do the retrying was the
    background page-builder, silently, at whatever moment the render cache
    turned over: the page changed under lee while he looked at it, and each
    attempt was charged again. lee: *"teh ai attemsp shoud happen in teh
    timmer not in the background and it shoud deliver the proper clen page
    even if it takes longer"*.

    So the retries happen here, where the progress bar is, and they are cheap:
    `_ai_clean_call` caches every answer the endpoint DID give by the content
    of its own (image, mask), so a second go only asks about the boxes that
    failed. What stops it is a refusal that waiting cannot mend - a 401 or a
    403 sets `refused` and every later call turns back at the top of
    `_ai_clean_call` - and the page is left NOT cleaned, so the view shows the
    scan instead of a half-model page dressed up as finished.
    """
    if own_plate_path(p, i):
        # Excluded. Not "cleaned and then overwritten" - never cleaned: the
        # plate is thrown away neither on disk nor in memory, no mask is built,
        # and nothing goes to the hosted cleaner (which is what this step
        # actually costs). It still counts as DONE, or the Clean step would sit
        # at 22/23 for ever and Typeset would stay locked behind it.
        p.pages[i].cleaned = True
        _tally_clean({"own": 1})
        return
    if force:
        drop_plate(p, i)
    tries = CLEAN_TRIES if _hosted_cleaning(p) else 1
    if _CLEAN_GIVEUP["on"]:
        tries = 1                      # an earlier page already waited it out
    was = _MAY_CLEAN["on"]
    _MAY_CLEAN["on"] = True
    _KEEP_BEST.update(on=True, fails=None, plate=None)
    try:
        _do_clean_tries(p, i, tries)
    finally:
        _MAY_CLEAN["on"] = was
        _KEEP_BEST.update(on=False, fails=None, plate=None)


def _do_clean_tries(p: Project, i: int, tries: int) -> None:
    """The goes themselves. Split out so `do_clean` can put the permission to
    spend the cleaner up and take it down again in one place."""
    for go in range(tries):
        before = _AI_CLEAN_FAIL["n"]
        page = p.materialize(i)
        clean_page(p, i, page)
        _keep_the_clean_report(p, i, page)
        if _AI_CLEAN_FAIL["n"] <= before:
            p.pages[i].cleaned = True      # whole, and kept
            return
        if _AI_CLEAN_FAIL.get("refused") or p.job.get("cancel"):
            break                          # the token, or the person: waiting
        if go + 1 >= tries:                # will not mend either
            if tries > 1:
                _CLEAN_GIVEUP["on"] = True
            break
        _say_job(p, "Cleaning %s — the cleaner refused a box, going again (%d)"
                 % (getattr(p.pages[i], "name", ""), go + 2))
        drop_plate(p, i)
        time.sleep(CLEAN_WAIT)
    # Out of goes, and none of them whole. What the person gets is the best of
    # them - the go the endpoint refused fewest boxes on - because a page with
    # most of its Japanese off is worth more than a page with none of it off,
    # and pressing Clean again is how they ask for another try. It is stored
    # like any other plate so that nothing downstream rebuilds it, and it was
    # not billed: see `clean_page`.
    best = _KEEP_BEST.get("plate")
    if best is None:
        p.pages[i].cleaned = False
        return
    _store_plate(p, i, best)
    p.pages[i].cleaned = True
    _say_job(p, "Cleaning %s — the cleaner refused %d box%s; keeping the best "
             "of %d goes" % (getattr(p.pages[i], "name", ""),
                             _KEEP_BEST["fails"],
                             "" if _KEEP_BEST["fails"] == 1 else "es", tries))


def _store_plate(p: Project, i: int, full) -> None:
    """Put a finished plate in the caches, exactly where `clean_page` puts one.

    Split out because the one caller that does not build it in `clean_page` is
    `do_clean` keeping the best of several goes, and two ways of writing the
    same cache is two ways of getting the key wrong.
    """
    key = _plate_stamp(p, i)
    fp = _plate_disk_path(p, i)
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        imgio.imwrite(fp, full, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        _prune_cache_dir(os.path.dirname(fp), max(80, 3 * len(p.pages)))
    except Exception:
        pass                        # a cache that cannot write is fine
    _plate_cache[key] = full.copy()
    _touch(_plate_cache, key)
    while len(_plate_cache) > 6:
        _plate_cache.popitem(last=False)


def _say_job(p: Project, msg: str) -> None:
    """Put a line in the running job's label, if there is one to put it in."""
    try:
        if p.job.get("running"):
            p.job["label"] = msg
    except Exception:
        pass


def _keep_the_clean_report(p: Project, i: int, page) -> None:
    """Copy back what the cleaner said about each box, and nothing else.

    `inpaint_page` writes `clean_route` on every region and appends to
    `flagged` when it falls back, copies a pattern, drops to the letter cores
    on a dark panel, or finds the typesetting STILL VISIBLE after two goes.
    None of it used to be committed: it was written onto the materialised page
    and thrown away with it. Measured on lee's chapter, `clean_route` was empty
    on all 134 regions and there was not one clean flag, on a chapter with
    three boxes that had visibly kept their text.

    **Two fields by id, and not `commit()`.** The first version of this called
    `_commit_keep_proofread`, which writes the whole page back - and
    `materialize` runs the balloon finder over `repaired(i)` on the way in. So
    cleaning a page rewrote every region's `polygon` and `bubble_bbox` from a
    balloon found on the CLEANED plate, where the ink that defines an interior
    has just been erased. The next clean then worked from that geometry and
    wrote it again. lee, after a chapter run: *"we regreesse in a lot of ways
    with the clening"*.

    Nothing the cleaner learns is geometry. It is two strings per box, and two
    strings per box is exactly what comes back.
    """
    said = {r.id: (str(getattr(r, "clean_route", "") or ""),
                   getattr(r, "flagged", None))
            for r in page.regions}
    for rec in p.pages[i].regions:
        got = said.get(rec.get("id"))
        if got is None:
            continue                 # hidden, or not on the page that was built
        rec["clean_route"], rec["flagged"] = got


def _commit_keep_proofread(p: Project, i: int, page) -> None:
    """commit() rebuilds records via region_record(), which drops the
    editor-only 'proofread' flag. Any stage that re-commits a page (typeset,
    export) must go through here or it silently un-proofreads the page.

    AND THE CLEAN REPORT, for the same reason and with a second cost on top.
    `clean_route` says how each box was erased, and it is written by
    `inpaint_page` - which only runs when a plate is actually built. Look at a
    cleaned page again and the plate comes off the disk, the inpainter never
    runs, and the freshly materialised regions carry nothing; committing them
    wrote that nothing over the report a real clean had recorded.

    So the report disappeared on the first re-view of every page - which is
    exactly the failure `_keep_the_clean_report` was written to end, arriving
    again by another door.

    The second cost is speed, and it is the one that was noticed. `clean_route`
    is part of the region record, the region records are part of the rendered
    page's cache key, and a value that flips to empty and back on alternate
    renders is a key that never matches twice. lee: *"figure out a way to have
    the cleaned pages switch fataer for one page to another"* - and the answer
    was not a bigger cache. It was that the cache was being missed on purpose
    by a field that had no business changing.
    """
    keep = {r["id"]: (r.get("proofread"), r.get("clean_route"),
                      r.get("clean_core"))
            for r in p.pages[i].regions}
    p.commit(i, page)
    for r in p.pages[i].regions:
        was = keep.get(r["id"])
        if not was:
            continue
        if was[0]:
            r["proofread"] = True
        # Only where the fresh page has nothing to say. A page that really was
        # just cleaned has the new report on it and the new report wins.
        if was[1] and not r.get("clean_route"):
            r["clean_route"] = was[1]
        if was[2] and not r.get("clean_core"):
            r["clean_core"] = was[2]


EXPORT_MODES = ("full", "clean", "boxes")


def export_page(p: Project, i: int, mode: str = "full") -> str:
    """Write one page out. Three things can be written.

    `full` is the finished page: clean the art, lay the English out, draw it.

    `clean` is the cleaned plate bare - the raws with the Japanese erased,
    ready to hand to someone else to typeset (or to keep as the art). It is the
    same plate the typesetting would have been drawn on, so it costs nothing
    extra: skip the typesetting and the drawing and save what is already there.

    `boxes` is the ORIGINAL art with the boxes drawn on, exactly as the editor
    draws them - the same colours per text type, the same faint balloons, the
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
        imgio.imwrite(out, render_mod.box_sheet(
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
    imgio.imwrite(out, img)
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

#: The detector checkpoints, loading. `route` is the name to SAY while it is -
#: "Loading DB++ / COO", not "1 of 30", because those are the same fifteen
#: seconds told two ways and only one of them is true.
_models = {"running": False, "route": "", "done": ""}


_models_thread: threading.Thread | None = None


def warm_models(p: Project, wait: bool = False) -> None:
    """Load the picked route's checkpoints off the main path.

    Started when a card is picked, and again when a run begins - a chapter
    opened straight into Find text has picked nothing this session, and that
    is exactly the run where page one used to cost 54 seconds.

    ONE loader at a time, and a run WAITS for one already in flight rather
    than starting its own. The module-level caches these fill are plain dicts
    with no lock: two threads reading the same 116MB checkpoint at once would
    both do it, which is the wait this exists to remove, doubled. Picking a
    card and pressing Find text a second later is not a rare way to use this -
    it is the obvious one.

    The run's wait is not a stall, it is the load moved somewhere honest. The
    bar says "Loading DB++ / COO" while it happens, instead of "1 of 30".
    """
    global _models_thread
    t = _models_thread
    if t is None or not t.is_alive():
        _models.update(running=True, route=p.route_name(), done="")

        def go():
            try:
                _models["done"] = p.warm_models()
            finally:
                _models["running"] = False

        t = _models_thread = threading.Thread(target=go, daemon=True)
        t.start()
    if wait:
        t.join()


def _hosted_cleaning(p: Project) -> bool:
    return ((p.settings.get("ai_clean") or "off").strip() in ("hard", "all")
            and bool(cleaner_endpoint(p, token=False)[0]))


# Set while `do_clean` is running - the Clean button, and the Clean step of a
# pipeline run. Everything else that wants a plate gets one that already
# exists, or the scan. See `clean_page`.
_MAY_CLEAN = {"on": False}
# ...and the best of the goes it makes, kept in case none of them comes out
# whole. `fails` is how many boxes the endpoint refused on that go.
_KEEP_BEST = {"on": False, "fails": None, "plate": None}


def _may_spend_the_cleaner(p: Project) -> bool:
    """May THIS call build a plate that goes to the hosted cleaner?

    Local cleaning is somebody's own CPU and always allowed - it is free, it is
    fast, and refusing it would leave a page uncleaned for no reason at all.
    The hosted cleaner costs money and time, so it is spent by the one action
    that asks for it.
    """
    return _MAY_CLEAN["on"] or not _hosted_cleaning(p)


def _worth_warming(p: Project, i: int, hosted: bool | None = None) -> bool:
    """Whether building this page ahead of time is free enough to just do.

    Building ahead is only a kindness while it stays local. With the hosted
    cleaner switched on, cleaning a page that has never been cleaned means a
    call out to the network - so a page nobody has run Clean over is left
    alone, and pressing Clean is still the thing that spends that. Everything
    already done, or cheap to redo, gets built.

    THE FILE ON DISK, AND NOT THE `cleaned` FLAG. `cleaned` is a claim that
    Clean has been pressed; the plate file is the fact that its answer was
    worth keeping. They come apart on exactly the page that hurts: a plate
    built while the hosted cleaner refused a box is deliberately not cached -
    so that pressing Clean again really retries - and the flag is set all the
    same. Warming then rebuilt that page from scratch every time the render
    cache turned over, which on a 23-page chapter is constantly. Each rebuild
    called the endpoint again, refused a different subset of boxes, and
    produced a visibly different page; each one was charged the per-page fee.
    lee, watching it happen: *"when i firt didi te clean it didi not look like
    thsi after a while it turn into this what happened"*, and then: *"teh ai
    attemsp shoud happen in teh timmer not in the background"*.
    """
    if not p.pages[i].regions:
        return True                     # nothing to clean: just the scan
    if own_plate_path(p, i):
        return True                     # your file, read off disk: costs nothing
    if not (_hosted_cleaning(p) if hosted is None else hosted):
        return True                     # local cleaning: ours to spend
    return os.path.exists(_plate_disk_path(p, i))


_looking = 0
_looking_lock = threading.Lock()


@contextlib.contextmanager
def _someone_is_looking():
    """A page view is in flight, so the warm-up is not the important thing.

    The warm-up already yields to a real job, and takes the render lock one
    page at a time so that a click never queues behind more than the page in
    flight. One page in flight is still up to three seconds, and clicking
    through a chapter meets a fresh one every time - lee: *"when i swtitch too
    fast it not just lages and pauses for a while"*.

    So it yields to a PERSON as well. Held across the render rather than only
    while queued, because the warm-up's next page must not start while
    somebody is waiting for this one either.
    """
    global _looking
    with _looking_lock:
        _looking += 1
    try:
        yield
    finally:
        with _looking_lock:
            _looking -= 1


def _wait_for_the_person(gen: int) -> bool:
    """Stand aside while pages are being asked for. False if we were retired.

    Capped, so that a request which never finishes - a browser that went away
    mid-download - cannot stop the chapter being built for the rest of the
    session.
    """
    for _ in range(200):                    # ten seconds, then carry on anyway
        if _warm["gen"] != gen:
            return False
        if not _looking:
            return True
        time.sleep(0.05)
    return _warm["gen"] == gen


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
    order = sorted(range(len(p.pages)),
                   key=lambda i: (abs(i - start), i < start))
    hosted = _hosted_cleaning(p)
    order = [i for i in order if _worth_warming(p, i, hosted)]

    # ONLY THE PAGES THAT NEED BUILDING. The browser nudges this on every
    # page change so the builder works outwards from where the person is -
    # and once the chapter was fully built, that nudge STARTED A NEW WARM-UP,
    # counted all 46 jobs again, and the bar flashed up over a walk that was
    # pure cache hits. lee: *"when i swithc fast thsi show up for a few
    # second and complets fast"*. A key lookup per page says whether there is
    # any work at all; none means no worker, no counter, no bar.
    def _built(i, mode, paint=True):
        key = _render_stamp(p, i, mode) + (bool(paint),)
        return (key in _render_cache
                or os.path.exists(_render_disk_path(p, key)))

    order = [i for i in order
             if not (_built(i, "clean", paint=False) if p.pages[i].regions
                     else _built(i, "original"))]

    # BOTH SWEEPS ARE THE JOB, so both are counted.
    #
    # `total` used to be the plates alone. The bar reached "23 of 23" at the
    # end of the first sweep and then sat there, full and still saying
    # `running`, for the whole of the second - which is the expensive one, three
    # seconds a page. lee photographed it: *"Preparing pages 23 of 23  100%"*,
    # stuck. It was not stuck, it was counting the wrong job.
    finish = [i for i in range(len(p.pages))
              if p.pages[i].regions and p.pages[i].typeset
              and _worth_warming(p, i, hosted)
              and not _built(i, "typeset")]
    finish.sort(key=lambda i: (abs(i - start), i < start))
    # ...and the balloon check for pages that came in the door already boxed -
    # a reopened chapter never passes through `Project.detect`, so its second
    # opinion happens here. `wants` remembers per run, so the second opening
    # of the same chapter in one session costs a hash, not a model.
    from . import balloonck
    lookat = ([i for i in range(len(p.pages)) if balloonck.wants(p, i)]
              if balloonck.available(p) else [])
    if not order and not finish and not lookat:
        return                    # the chapter is built; the nudge was free
    _warm["gen"] += 1
    mine = _warm["gen"]

    def worker():
        _warm.update(running=True, done=0,
                     total=len(order) + len(finish) + len(lookat), at=-1)
        done = 0
        try:
            for i in order:
                while p.job.get("running") and _warm["gen"] == mine:
                    time.sleep(0.4)         # a real job always goes first
                if not _wait_for_the_person(mine):
                    return                  # a newer warm-up took over
                _warm["at"] = i
                try:
                    if p.pages[i].regions:
                        # THE PLATE FIRST, for the whole chapter. It is what
                        # the editor draws on - `frames.js:pageUrl` asks for
                        # `mode=clean&paint=0` even when the view on screen is
                        # the finished page - so it is what somebody clicking
                        # Next is waiting for, and nothing else may get in
                        # front of it.
                        render_index(p, i, "clean", paint=False)
                    else:
                        render_index(p, i, "original")
                except Exception:
                    traceback.print_exc()   # one bad page stops nothing
                done += 1
                _warm["done"] = done
                time.sleep(0.02)            # let waiting requests through
            # ...and THEN the finished pages, in the same order, on whatever
            # time is left.
            #
            # This used to say `clean` only, and gave the reason: nothing read
            # the finished page, so warming it would double the work to fill a
            # cache nobody looked in. That stopped being true when the Image
            # view learnt to settle into the exported page
            # (`static/js/exactview.js`) - which costs three seconds a page to
            # build, and was building it in front of him.
            #
            # A second sweep rather than one pass doing both, so that a chapter
            # of plates is never held up behind a chapter of typesetting: the
            # thing you are waiting for finishes first.
            for i in finish:
                while p.job.get("running") and _warm["gen"] == mine:
                    time.sleep(0.4)
                if not _wait_for_the_person(mine):
                    return
                _warm["at"] = i
                try:
                    # `commit=False`: the warm-up is nobody's edit. See
                    # `render_index`, and the four tests that found out what a
                    # background re-typeset does to an emptied box.
                    render_index(p, i, "typeset", commit=False)
                except Exception:
                    traceback.print_exc()
                done += 1
                _warm["done"] = done
                time.sleep(0.02)
            # LAST, because a flag is advisory and pictures are not: the
            # balloon check, for every page that arrived already boxed.
            # About a second a page, once per chapter per run.
            flagged = 0
            for i in lookat:
                while p.job.get("running") and _warm["gen"] == mine:
                    time.sleep(0.4)
                if not _wait_for_the_person(mine):
                    return
                _warm["at"] = i
                try:
                    flagged += balloonck.check_page(p, i)
                except Exception:
                    traceback.print_exc()
                done += 1
                _warm["done"] = done
                time.sleep(0.02)
            if flagged:
                p.save_soon()      # the flags are on the records; keep them
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
# reported whichever wrote last and the two runs trampled each other's pages -
# in practice you had to sit and wait before pressing anything else.
#
# Now `run_job` puts the work in a line and one dispatcher takes it off, one at
# a time, in order. Waiting work can be moved and dropped; the one that is
# already running is stopped the way it always was, with Cancel.
_QUEUE: list[dict] = []            # waiting, in order - [0] goes next
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
    """Take one waiting item out of the line. Never touches what is running -
    that is Cancel's job, and it has to stop mid-page rather than not start."""
    with _Q_LOCK:
        at = next((k for k, q in enumerate(_QUEUE) if q["qid"] == qid), -1)
        if at < 0:
            return False
        _QUEUE.pop(at)
        return True


def _quiet_the_queue(p: Project, wait: float = 8.0) -> bool:
    """Empty the line and bring the running job to a stop, then wait for it.

    For the one caller that is about to take the pages away underneath it -
    `/api/reset`. Cancelling is not enough on its own: the flag is read
    between pages, so the job is still inside one when the call returns, and
    clearing the list at that moment is the crash this exists to prevent.

    Bounded, and it returns whether the job actually stopped: a reset must not
    hang because a page will not put itself down. A job that outlives the wait
    is a job that will raise in its own thread, which is where it already was.
    """
    queue_clear()
    if not p.job.get("running"):
        return True
    p.job["cancel"] = True
    end = time.monotonic() + wait
    while p.job.get("running") and time.monotonic() < end:
        time.sleep(0.05)
    stopped = not p.job.get("running")
    # AND PUT THE FLAG BACK DOWN. The job's own `finally` clears it, but only
    # for a job that was still running when we raised it: between the check
    # above and the line after it, the run can finish on its own, and then
    # nothing ever clears the True we just wrote. Every later job reads it
    # between pages and stops on page one - a whole session of runs that do
    # nothing, from one flag left standing.
    if stopped:
        p.job["cancel"] = False
    return stopped


def queue_clear() -> int:
    """Drop everything waiting. What is already RUNNING is not touched - that
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

    The run, rounded up once - not the pages rounded up and added. At a
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
    means nothing at all. The two are different questions - "price the pages
    this run would touch" defaults to all of them, "price the page I am
    looking at" defaults to none - and rolling them into one default is how a
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
    # A read that happens on this computer is not bought from anybody. Before
    # `step_engine`, deliberately: that call rewrites `p.ctx` from the AI
    # settings, and an offline read has no context to rewrite.
    if step == "ocr" and reading_offline(p):
        return (0, "", "")
    from . import coins
    model, backend = step_engine(p, step)
    # The boxes of CONTEXT this run really sends, asked of the same function
    # that builds the payload. Not the chapter's size: a full-chapter run sends
    # no context at all, and charging it the whole chapter anyway was about a
    # hundred thousand imaginary input tokens on a twenty-three page quote.
    ctx = context_boxes(p, step, indices)
    boxes = [page_boxes(p, i) for i in indices]
    # The words on each page, and the four settings the system prompt is built
    # from. Both are things the quote used to guess at and this function has
    # in its hand: the reply's size follows the source text, and the prompt's
    # size can be counted rather than remembered. See `coins.sys_tokens`.
    srcs = [page_src_chars(p, i) for i in indices]
    # ONE page, with its words in front of us: the exact strings the run
    # will send can be built and COUNTED instead of predicted - task #117.
    # The shape stays the answer for multi-page runs and the scope dialog,
    # which price pages nobody has built payloads for; and any trouble in
    # the building falls back to the shape rather than failing the price.
    price = None
    if len(list(indices)) == 1 and step in ("translate", "proofread")             and boxes and boxes[0] > 0:
        price = _counted_page_price(p, step, list(indices)[0], boxes[0],
                                    srcs[0], model, backend)
    if price is None:
        price = coins.quote(step, boxes, model, backend, ctx, srcs,
                            prompt_key(p), reading_detail(p))
    # ...plus the second turn Read text makes when it is also labelling the
    # boxes. Its own shape and added here rather than folded into "ocr",
    # because it is OFF unless somebody switched it on: quoting it always would
    # put a request most chapters never make on every read.
    #
    # Quoted separately and not left to `drift` to sort out. Under-quoting is
    # the one direction that hurts - this price is what a longer run is checked
    # against before each page, and the alternative to erring high is a run
    # that stops halfway because the purse cannot finish it.
    if step == "ocr" and labels_boxes(p):
        price += coins.quote("label", boxes, model, backend, 0, srcs,
                             prompt_key(p))

    return (price, model, backend)


def reading_detail(p: Project) -> str:
    """How finely the reader is set to cut a page up, resolved.

    Asked of `ocr.detail_for` so the price and the reader can never disagree
    about what an unset - or a misspelt - setting means.
    """
    try:
        from .ocr import detail_for as _df
        return _df(p.settings.get("medium"), p.settings.get("ocr_detail"))
    except Exception:
        return ""


def prompt_key(p: Project) -> tuple:
    """The four project settings a system prompt is built from.

    Handed to `coins` so it can build the real prompt and count it instead of
    reading a number somebody typed - which is how `translate.sys_in` came to
    say 2,086 against a real 4,600 and put an 18% hole in every quote.
    """
    c = getattr(p, "ctx", None)
    if c is None:
        return ()
    return (getattr(c, "medium", "manga") or "manga",
            getattr(c, "target", "en") or "en",
            getattr(c, "source", "") or "",
            bool(getattr(c, "honorifics", False)))


def labels_boxes(p: Project) -> bool:
    """Is Read text also going to say what kind each box is?

    One question, one answer, read from `do_ocr` and from the quote - so the
    page that is charged for a labelling turn is the page that makes one.

    OFF unless somebody switched it on. lee: *"also make it off by defualt"* -
    and he is right that this is the way round it belongs. It costs a request
    per page, and a setting that spends money without being asked for is one
    people find out about from their bill.
    """
    return bool(p.settings.get("label_kinds")) and not reading_offline(p)


def _counted_page_price(p: Project, step: str, i: int, boxes: int,
                        src_chars: float, model: str, backend: str):
    """One page's price from its REAL strings, or None to use the shape."""
    from . import coins
    try:
        from . import translate as T
        page = p.materialize(i)
        if step == "translate":
            chapter = run_context(p, [i])
            req = T.build_payload(page, p.ctx, chapter)
            if not req.get("regions"):
                return None
            user = (json.dumps(req, ensure_ascii=False, indent=1)
                    + "\n\n" + T.SCHEMA_HINT)
            system = T.build_system(p.ctx.medium, p.ctx.target,
                                    getattr(p.ctx, "source", ""),
                                    getattr(p.ctx, "honorifics", True))
        else:
            req = T.build_proofread_payload(page, p.ctx)
            if not req.get("regions"):
                return None
            user = (json.dumps(req, ensure_ascii=False, indent=1)
                    + "\n\n" + T.PROOFREAD_SCHEMA_HINT)
            system = T.build_proofread_system(p.ctx.medium, p.ctx.target,
                                              getattr(p.ctx, "source", ""))
        return coins.quote_counted(step, system, user, boxes, src_chars,
                                   model, backend, reading_detail(p))
    except Exception:
        return None


@contextlib.contextmanager
def _charge(p: Project, step: str, indices):
    """Take the price of the run when it STARTS, and give back what it did not
    use if it stops early.

    lee: *"make teh edit remove the coins when the person click teh button and
    if they cancel teh job it shoud refund them the amount for teh pages that
    werent done"* - and later: *"i want to get a very good extimate"*.

    HOW IT CHARGES NOW - a hold, then a settle:

    * When the button is pressed, the QUOTE times a measured headroom
      (`coins.hold`, 1.25x) leaves the purse, under one run id. The headroom
      is why a run can never outrun its own purse mid-chapter.
    * While it runs, every call is METERED (`coins.charging`).
    * When it ends - finished, cancelled, or fallen over - it SETTLES: the
      metered cost of the calls that actually happened is kept, and the rest
      of the hold comes back as one credit on the same run id. An estimate
      can now be wrong in either direction without anyone being overcharged,
      because the estimate stopped being the price - the meter is.
    * The settle never takes a second helping: if the meter somehow runs past
      the hold, the difference is written down (`over` on the meter line) and
      absorbed. Taking more than was shown at the button is the one direction
      this app does not round.
    * A run whose provider reported no usage at all falls back to the old
      arithmetic - the quote for the pages that ran - because a refund based
      on a meter that saw nothing would be refunding tokens that were bought.

    Cancelled pages need no special case any more: calls that never happened
    were never metered, so the settle gives their share back by construction.
    """
    if step not in PAID_STEPS:
        yield None
        return
    from . import coins
    where = _run_label(p, indices)
    boxes = [page_boxes(p, i) for i in indices]
    srcs = [page_src_chars(p, i) for i in indices]
    ctx = context_boxes(p, step, indices)
    # The estimate learns from the meter, and this run is about to write a
    # meter line. Held still across the whole of it, or the refund would be
    # priced against evidence the charge never saw and the two would not add
    # back up - see `coins.steady`.
    with coins.steady():
        _price, model, backend = run_price(p, step, indices)
        # One id for the hold and for the settle that follows it. On an
        # account the charge is a request that can time out after arriving,
        # and the id is what stops the retry paying twice; it is also what the
        # settle is measured against, so nothing can be given back that was
        # never taken.
        run = coins.new_run()
        reserve = coins.hold(_price)
        coins.spend(reserve, step, where, model, run=run)
        p.job["spent"] = reserve
        with coins.charging(step, where, model, backend) as bill:
            try:
                yield bill
            finally:
                done = int(p.job.get("done") or 0)
                metered = bill.coins
                if bill.calls and (bill.usd > 0 or bill.flat_coins):
                    # THE METER IS THE PRICE. Capped at the hold: the settle
                    # never takes a second helping, so a meter that somehow
                    # runs past the headroom is written down and absorbed
                    # rather than charged - see the docstring.
                    final = min(metered, reserve)
                else:
                    # Nothing verifiable was metered. The pages that ran were
                    # still bought, so they are kept at their quoted price -
                    # the old arithmetic - and only the unrun tail (and the
                    # headroom) comes back.
                    back_q = coins.quote(step, boxes[done:], model, backend,
                                         ctx, srcs[done:], prompt_key(p),
                                         reading_detail(p))
                    final = max(0, min(reserve, _price - back_q))
                give = reserve - final
                if give > 0:
                    undone = len(boxes) - done
                    coins.credit(give, "%s settle — held %s, used %s%s"
                                 % (step, coins.show(reserve),
                                    coins.show(final),
                                    (", %d page%s not run"
                                     % (undone, "" if undone == 1 else "s"))
                                    if undone > 0 else ""),
                                 run=run)
                p.job["spent"] = final
                # What it really cost, for the record and for tuning the estimate.
                # A ledger line that moves no money: nobody is billed on it.
                p.job["cost"] = metered
                if bill.calls:
                    # `boxes`, `pages`, `ctx`, `backend` and `step` are what turn
                    # this from a receipt into evidence. "It used 44,870 tokens"
                    # cannot be compared with what was predicted unless the size
                    # of the thing that used them is written down beside it - and
                    # `coins.drift` is the reader.
                    coins.note("%s cost" % step, where, model, coins=bill.coins,
                               tin=bill.tin, tout=bill.tout, cached=bill.cached,
                               # `think` ONLY where a reply said. Anthropic
                               # bills reasoning as output and reports it
                               # nowhere; writing its silence as `think: 0`
                               # told `coins.drift` the reasoning had been
                               # seen apart from the reply, and Opus 5's
                               # sixteen thousand thinking tokens on one read
                               # were filed under the visible reply, where the
                               # tight band would not correct for them. The
                               # run overshot its hold by 49 coins. A key that
                               # is absent falls to the combined ratio, which
                               # is the honest one for a provider that gives
                               # one number - see `coins.usage_extras`.
                               **({"think": bill.think} if bill.think_seen
                                  else {}),
                               # ...and how many of the calls the provider
                               # priced itself. Task #119: a receipt that
                               # cannot say whether it was settled on
                               # OpenRouter's `usage.cost` or on our table is
                               # a receipt nobody can check.
                               priced_direct=bill.priced_direct,
                               # ...and whether this read was sent with the
                               # model's thinking turned OFF. Two regimes of
                               # the same model on the same step are two
                               # different outputs, and `coins.drift` reads
                               # only the lines from the one it is quoting.
                               think_off=(step == "ocr"
                                          and coins.read_thinks_off(model)),
                               held=reserve, quoted=_price,
                               over=max(0, metered - reserve),
                               calls=bill.calls, charged=p.job["spent"],
                               step=step, backend=backend, ctx=ctx,
                               boxes=sum(boxes[:done]), pages=done,
                               # ...and the WORDS on those pages, because the
                               # reply's size follows the source text and not
                               # the box count. Without it `drift` compares a
                               # real bill against a prediction made from a
                               # different number than the quote used.
                               src=sum(srcs[:done]),
                               # WHICH MODE it read at. A read zoomed per box
                               # sends ten times the pictures a whole-page
                               # read does, so a drift correction that cannot
                               # see the mode is averaging two different
                               # prices - see `coins.pictures`.
                               detail=reading_detail(p),
                               # ...and whether this read also LABELLED, which
                               # is a second request a page and is metered onto
                               # the same bill as the read that made it.
                               #
                               # Without this the drift correction reads those
                               # tokens as the reader costing half again what
                               # its shape says, and `run_price` then adds the
                               # labelling on top of a shape already inflated
                               # by it - the same tokens charged twice, to
                               # exactly the people who switched it on.
                               # `coins.predicted` is the other half.
                               labelled=(step == "ocr" and labels_boxes(p)))


def clean_token_for(p: Project) -> str:
    """The cleaner's token - `.env` first, then the chapter.

    The fourth of the four lee named: *"all the key i need to put ius claude
    gemini open router and clenner"*. It is not an API key, but it is the same
    kind of secret with the same problem - copied into every chapter folder,
    stale in all of them the day the deploy is replaced - so it is answered
    from the same file, by the same rule.

    Stripped here as well as on save. A project.json written before the save
    started stripping still has the pasted whitespace in it, and a 401 caused
    by a trailing newline is indistinguishable from a wrong token.
    """
    return (userdata.env_key("clean")
            or str(p.settings.get("clean_token") or "").strip())


def cleaner_endpoint(p: Project, token: bool = True) -> tuple[str, str, bool]:
    """Where the AI cleaner is and what to sign the call with:
    `(url, token, relayed)`.

    A checkout with its own deploy - a URL (`MANGATL_CLEAN_URL` in the
    `.env`, or the chapter's `clean_url`) AND a token - calls it directly, as
    always. Everybody else goes through the project's relay, which holds the
    real token and address (lee: *"ther 4 key one for teh clner do tha
    too"*): the URL is `.../relay/clean`, the token is the person's ID token,
    and the relay swaps it for ours. Signed out with no deploy of their own:
    no url, and the local fill does the page.

    `token=False` answers the URL without fetching a token - for cache keys
    and gates, which are asked often and must not touch the network."""
    url = (str(userdata.load_env().get("MANGATL_CLEAN_URL") or "").strip()
           or str(p.settings.get("clean_url") or "").strip())
    tok = clean_token_for(p)
    if url and tok:
        return url, tok, False
    if relay_ready():
        t = relay_token() if token else "-"
        if t:
            return relay_url("clean"), ("" if t == "-" else t), True
    return url, tok, False


def key_for(p: Project, backend: str, step: str = "") -> str:
    """The key a call to this service will be made with.

    **The `.env` wins.** lee: *"they key shoud be in the .env file and all teh
    project shoud use them"*, and *"make evrything that needs ai read from teh
    .env"*. One file, every chapter, and rolling a key is one edit instead of
    one edit per chapter folder you still have on disk.

    It has to WIN rather than merely fill a gap, because of what is already
    sitting in those chapters. A project.json written before the guard existed
    can hold the literal word `set` - the MASK, handed back by a `.tct` import
    and saved over the key it was standing in for - and lee's own live chapter
    holds five of them. A `.env` that only filled gaps would lose to that
    string, and the call would go out with `set` as its key. Nothing that is
    not a real key gets to beat the file the person just edited.

    Below the `.env` the old order stands, so a chapter that was working
    before any of this goes on working. **The service box wins** over a
    per-step box, which is a leftover from when there were three of them - so
    a key that has been moved cannot be countermanded by a stale copy nobody
    can see on screen.

    And only on the SAME service. A per-step key is a key for whatever provider
    that step was pointed at when it was typed; handing it to a different one
    because the step has since been switched means sending Google a Claude key
    and reading the provider's own wording about it halfway down the editor.
    """
    back = (backend or "").strip().lower()
    if not back:
        return ""
    mine = userdata.env_key(back)
    if mine:
        return mine
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


OPENROUTER_VENDOR = {"anthropic": "anthropic", "gemini": "google"}


def openrouter_id(back: str, model: str) -> str:
    """The same model, the way OpenRouter names it.

    A reseller's id carries the maker - `anthropic/claude-sonnet-5` - and a
    direct service's does not. A model that already names its maker passes
    through untouched, so this is safe to apply twice.
    """
    v = OPENROUTER_VENDOR.get((back or "").strip().lower())
    m = (model or "").strip()
    return m if (not v or "/" in m) else f"{v}/{m}"


def fallback_key(p: Project) -> str:
    """The OpenRouter key, which any step may fall back on.

    Through `key_for` rather than off `p.settings` directly, so the `.env`
    reaches the fallback too. It did not, for one edit: every step read its
    own key from the file and the one that catches a refusal went on reading
    the chapter - which is the case that matters most, because it only runs
    when something has already gone wrong.
    """
    return key_for(p, "openrouter")


def _openrouter_ctx(p: Project) -> None:
    """Point the ALREADY BUILT context at OpenRouter, same model.

    lee: *"it shoud try to use the claude or google key first and it it
    sondt work use teh open router key next"*. This is the second half of
    that sentence: the model keeps its identity and only the door changes.
    """
    p.ctx.model = openrouter_id(p.ctx.backend, p.ctx.model)
    p.ctx.backend = "openrouter"
    p.ctx.base_url = ""
    p.ctx.api_key = fallback_key(p)


# What a provider sounds like when the KEY is the problem rather than the
# page: `translate._model_error`'s own sentence, the raw words the error was
# classified from, the Anthropic SDK's error type name, and the message an
# out-of-credit account gets. Any of these on a step whose service is Claude
# or Google means the primary key "doesn't work" - which is exactly when lee
# wants the OpenRouter key tried instead.
_KEY_TROUBLE = ("key was refused", "api key", "api_key", "unauthorized",
                "invalid authentication", "incorrect api key",
                "permission denied", "authentication_error",
                "credit balance")


def _key_trouble(e: BaseException) -> bool:
    low = str(e).lower()
    return any(w in low for w in _KEY_TROUBLE)


def or_openrouter(p: Project, step: str, fn):
    """Run the step; if the primary key is refused, cross to OpenRouter once.

    The crossing is remembered on the project for the rest of the session
    (`_openrouter_instead`), so page two goes straight through the door page
    one had to find - and `_ctx_from_settings` is what reads the memo, so the
    retry rebuilds its context the ordinary way rather than by side effect.
    """
    try:
        return fn()
    except Exception as e:
        if not _key_trouble(e):
            raise
        if not fallback_key(p):
            raise
        aside = getattr(p, "_openrouter_instead", None)
        if aside is None:
            aside = p._openrouter_instead = set()
        already = (p.settings.get(f"{step}_backend") or "").strip().lower()
        if step in aside or already == "openrouter":
            raise                     # OpenRouter itself said no: surface it
        aside.add(step)
        try:
            return fn()
        except Exception:
            # The fallback failed too. The memo is wiped so a key fixed in
            # Settings is tried first again on the next run.
            aside.discard(step)
            raise


def _steps_aside(step: str):
    """Decorator form of `or_openrouter`, for the three do_* steps."""
    def deco(fn):
        @functools.wraps(fn)
        def run(p, i, *a, **k):
            return or_openrouter(p, step, lambda: fn(p, i, *a, **k))
        return run
    return deco


#: The services the project's relay can call for a signed-in person who has
#: no key of their own. lee: *"the user shoud not have eth keys"*.
RELAYED = ("anthropic", "gemini", "openrouter")


def relay_ready() -> bool:
    """Can this editor send its AI calls through the relay? Signed in is the
    whole of it; whether the account has coins is the relay's answer, and
    it is given in the provider's own error shape when it is no."""
    from . import account
    try:
        return account.signed_in()
    except Exception:
        return False


def relay_url(backend: str) -> str:
    """The relay, for one provider: `.../relay/<backend>`. The OpenAI-shaped
    clients add `/chat/completions` and `/models`; Anthropic's SDK adds
    `/v1/messages`; the function takes both."""
    from . import account
    return account.function_url("relay") + "/" + (backend or "").strip().lower()


def relay_token() -> str:
    from . import account
    try:
        return account.token()
    except Exception:
        return ""


def needs_key(p: Project, step: str) -> str:
    """"" if this step can be called, or the sentence saying what is missing.

    A step used to fall back to a project-wide engine when it had no key of
    its own, so a missing key was invisible and the run quietly happened
    somewhere else. There is no project-wide engine any more, and a step with
    no key is a step that cannot run - which is better, as long as it says so
    BEFORE the chapter starts instead of failing on page one with a provider's
    own wording about an invalid key.
    """
    if step not in AI_STEPS:
        return ""
    # Reading on this computer asks nobody for anything. Without this, turning
    # the offline reader on would still be refused on a keyless machine - which
    # is the machine it exists for.
    if step == "ocr" and reading_offline(p):
        return ""
    # `step_engine` answers (model, backend) - in that order, which is worth
    # writing out: reading it the other way round made this compare a MODEL
    # name against the list of providers that need a key, so every step looked
    # as though it were local and nothing was ever asked for.
    _model, back = step_engine(p, step)
    if back not in NEEDS_KEY:
        return ""                      # local, and local wants no key
    if key_for(p, back, step):
        return ""
    # No key for the chosen service, but an OpenRouter key on file: the run
    # can still happen - `_ctx_from_settings` crosses over before page one -
    # so blocking it here would refuse a chapter that would have worked.
    if back in ("anthropic", "gemini") and fallback_key(p):
        return ""
    # No key of their own, but signed in: the relay calls with ours, paid in
    # coins. A person is never asked for a key.
    if back in RELAYED and relay_ready():
        return ""
    label = STEP_LABEL.get(step, step)
    service = dict(SERVICES).get(back, back)
    return ("%s needs %s, which runs on TCT Coins. Sign in (the coin, top "
            "right) to run it, or point that step at a model you run yourself."
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
    if price > 0 and coins.needs_signin():
        return ("Sign in (the coin, top right) to run this - TCT Coins live "
                "on your account.")
    # The HOLD is what actually leaves the purse when the button is pressed -
    # the estimate plus its headroom, returned at settle - so the hold is
    # what has to be affordable. Gating on the bare estimate would start a
    # run whose own hold bounces.
    if price <= 0 or coins.can_afford(coins.hold(price)):
        return ""
    return ("not enough TCT Coins — this needs %s (held as %s until the run "
            "settles) and there %s %s. Run fewer pages, or buy more coins."
            % (coins.show(price), coins.show(coins.hold(price)),
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
    """How many text boxes are on this page - which is what its AI steps cost.

    lee: *"make teh coin system be dynamic and per text box in a page so if a
    page has 1 0r 2 tet box it shoiukd be cheaper than a page that has 5-6 text
    boxes"*. A page nobody has run Find text on yet counts 0, and a quote of 0
    is right: there is nothing on it to send.
    """
    try:
        return len(p.pages[i].regions or [])
    except Exception:
        return 0


def page_src_chars(p: Project, i: int) -> int:
    """How much writing is on this page - the characters, not the boxes.

    What comes BACK from the translator is decided by this and not by the box
    count: a bubble holding one word and a bubble holding a sentence do not
    return the same size of reply. Measured over lee's chapter, adding this to
    the estimate took the reply's error from 20.6% to 2.3%. See
    `coins.Shape.per_src_char_out`.

    Zero on a page nobody has read yet, which is right and is handled: the
    quote falls back to `coins.SRC_CHARS_PER_BOX` for a page it cannot see
    the words of, which is the same answer it gave before this existed.
    """
    try:
        return sum(len((r.get("src_text") or ""))
                   for r in (p.pages[i].regions or []))
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
    # ...and the checkpoints start coming off the disk NOW, beside the run
    # rather than inside its first page. Picking a card starts this too, but a
    # chapter opened straight into Find text has picked nothing this session,
    # and that is exactly the run where page one used to cost 54 seconds.
    if item.get("warm"):
        warm_models(p, wait=True)
    # STOP MEANS STOP. lee: *"can you make stopping a proccess happen fast it
    # shoud cancel teh page it woirkingg on and stop not keep finishing it"*.
    #
    # The check below used to be the ONLY one, which made Stop mean "stop
    # after this page" -- and on a textured page a clean is the slowest thing
    # the app does. Handing the flag to `stopping` lets the per-region loops
    # inside `fn(i)` raise out of the middle of the page. Set here and cleared
    # in the `finally`, so there is one owner and nothing to leak.
    _stopping.watch(lambda: bool(p.job.get("cancel")))
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
                # only write was after the loop, and an exception jumps over it -
                # so eleven pages of translation lived in memory and nowhere else,
                # and the next time the project was read off disk they had never
                # happened. lee: *"sometime when i reload the page i lose some
                # profreading or tranaltiong"*.
                #
                # `save_soon` and not `save`: it coalesces, so twenty pages in a
                # row still cost one write, and it happens off this thread.
                p.save_soon()
    except _stopping.Stopped:
        # Not an error -- somebody changed their mind mid-page. The page that
        # was interrupted keeps whatever it had reached; see `stopping` for
        # why it is not rolled back.
        p.job["cancelled"] = True
    except Exception as e:
        # Say WHERE. A bare type and message in the red bar leaves the person
        # reading it with nothing to report and nothing to look at, so the
        # innermost frame that is ours goes in with it.
        p.job["error"] = f"{type(e).__name__}: {e}{_where(e)}"
        traceback.print_exc()
    finally:
        # Whatever got done is on disk before anything else happens - the run
        # that finished, the run that was cancelled, and above all the run that
        # raised. This is the write the `except` above used to skip.
        try:
            p.save()
        except Exception:
            traceback.print_exc()
        _stopping.clear()
        p.job["running"] = False
        p.job["cancel"] = False
        # Whatever the step changed, the pages now look different - get them
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
    the editor is handed a new project whenever one is opened - a dispatcher
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
            step: str = "", warm: bool = False) -> int:
    """Put one action in the line. Returns its queue id.

    It starts at once when nothing else is running, which is what it always did
    and what it looks like from the outside.

    `step` is what the run COSTS - one of `PAID_STEPS`, or "" for the ones that
    run on this machine and are free. It is carried on the queue item rather
    than guessed from the label, because the label is prose that gets reworded
    and a price must not depend on the wording of a progress bar.

    `warm` is whether to have the detector checkpoints in memory before the
    first page. Its own argument and NOT a value of `step`: `step` is the
    price, `tests/test_the_ai_find_pass_is_gone.py` holds Find text to having
    no price at all, and hanging a second meaning on it would have made a free
    run look chargeable to the one test guarding that.
    """
    with _Q_LOCK:
        _Q_SEQ["n"] += 1
        qid = _Q_SEQ["n"]
        _QUEUE.append({"qid": qid, "label": label, "project": p,
                       "indices": list(indices), "fn": fn, "step": step,
                       "warm": warm})
        # The flag is a CLAIM, and a claim is only good while whoever made it
        # is still there. Trusting the flag alone means that any way at all of
        # leaving it set on the way out - a raise between two turns of the
        # lock, a thread that died - strands everything queued behind it for
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


def symbol_only_boxes(regs) -> list:
    """The boxes the reader found nothing in but marks - and no others.

    lee: *"after read text happens if a box is only symboled with no text it
    shodu auto delete"*. What counts as a mark is `ocr.only_symbols`; what
    this adds is the three boxes that are NOT the app's to throw away, however
    they read:

    * a box somebody typed themselves (`own_text`) - there was never anything
      under it to read, so what the reader made of it says nothing at all;
    * a LOCKED box - locked is the word for "I have corrected this, leave it
      alone", and deleting it is the loudest possible way of not doing that;
    * a box that already has a translation. Re-reading a page that has been
      through the translator must not take the English with it - the reader
      having a worse turn than last time is not a reason to lose work.
    """
    from .ocr import only_symbols
    out = []
    for r in regs:
        if getattr(r, "own_text", False) or getattr(r, "locked", False):
            continue
        if (getattr(r, "dst_text", "") or "").strip():
            continue
        if only_symbols(r.src_text or ""):
            out.append(r)
    return out


# How much of the smaller box has to stand on the bigger one's ground before
# the two are talking about the same writing. A fragment of the same writing is
# drawn where the writing is; two boxes elsewhere on the page that happen to
# share words are two answers to two moments.
#
# This was briefly lowered to 0.35, on a reading of lee's page 017 that turned
# out to be wrong - see `read_twice_boxes` - and is back where it was.
READ_TWICE_IN = 0.6


def _fold_kana(s: str) -> str:
    """The comparison form of a reading: full width normalised.

    ONLY for comparing one reading against another - nothing written down ever
    goes through this, and no box's text is changed by it.

    ﾄﾞﾝ and ドン are the same writing in two encodings, and which one comes
    back is the reader's business rather than the page's.

    It does NOT fold katakana into hiragana. That was tried, to make one box's
    足リるかよ match another's 足りるかと - and those turned out to be two
    different characters shouting, so the thing it was built to catch was never
    a duplicate at all. キョロ and きょろ are two spellings a person may have
    chosen on purpose, and this is a function that DELETES a box."""
    import unicodedata
    return unicodedata.normalize("NFKC", s or "")


def _reading(r) -> str:
    """A box's reading with its spacing taken out, in comparison form. The
    reader breaks a line where the balloon breaks it, and where it breaks is
    not part of what is written."""
    return _fold_kana("".join((getattr(r, "src_text", "") or "").split()))


def _box_area(r) -> int:
    b = getattr(r, "bbox", None) or (0, 0, 0, 0)
    return max(0, int(b[2])) * max(0, int(b[3]))


def _sits_on(a, b) -> float:
    """How much of `a` is over `b`, as a share of `a`."""
    ax, ay, aw, ah = (int(v) for v in (getattr(a, "bbox", None) or (0, 0, 0, 0)))
    bx, by, bw, bh = (int(v) for v in (getattr(b, "bbox", None) or (0, 0, 0, 0)))
    w = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    h = max(0, min(ay + ah, by + bh) - max(ay, by))
    return (w * h) / float(aw * ah) if aw and ah else 0.0


def read_twice_boxes(regs) -> list:
    """Boxes whose reading is PART of an overlapping box's reading.

    lee: *"do this Substring dedupe after read"*, and again after it was taken
    out for a day: *"can you gring teh fix we had before"*.

    001's painted 今日 title survives detection as two overlapping boxes, 今
    inside 今日, because COO vouches for the small one past the kids-union
    rule. The pixels cannot settle that; the readings can. A box whose reading
    is inside an overlapping box's reading is the same writing answered twice.

    EXACT, and the match has to be exact for a reason lee gave. His page 017
    has そんなので足りるか in one box and 足りるかよ in the next, offset down
    the same column - which looked exactly like one shout read twice, so this
    was widened to let a character or two differ and the overlap it demanded
    was dropped to 0.35. They are two different people shouting over each
    other, Rofan and Glow, and the widened rule would have deleted Glow's
    line: *"everrything is working as entened the 2 016 and 017 are not
    mistakes"*. Both changes are out.

    The asymmetry is the whole point of keeping it narrow. A duplicate left on
    the page is one keypress from gone; a line deleted from under somebody is
    gone before they know it was there.

    It only ever REMOVES a box, which is what earns it a place in a step that
    reads. lee: *"make it so that read text only read teh etxt and not modify
    boxes exapt for removing boxes with no text or remoeving boxes with only
    symobos"* - a box holding no writing of its own is the third of those, not
    a fourth thing. The pass that RENAMED a box on what was read in it stayed
    out.

    Longest reading first, so a chain - 今 in 今日 in 今日は晴れ - resolves in
    one pass and every fragment dies into a box that is still standing rather
    than into one that is also on its way out. Equal readings keep the bigger
    box. An empty reading proves nothing either way; that is `empty_boxes`.

    The three boxes this never touches are the three `symbol_only_boxes` and
    `empty_boxes` never touch: one somebody typed, one they locked, and one
    that already carries a translation.
    """
    live = [r for r in (regs or [])]
    order = sorted(live, key=lambda r: (-len(_reading(r)), -_box_area(r)))
    dead, gone = [], set()
    for r in order:
        t = _reading(r)
        if not t:
            continue
        if getattr(r, "own_text", False) or getattr(r, "locked", False):
            continue
        if (getattr(r, "dst_text", "") or "").strip():
            continue
        for q in order:
            if q is r or id(q) in gone:
                continue
            u = _reading(q)
            if not u or len(u) < len(t):
                continue
            if t not in u:
                continue
            # Same reading in both: the bigger box is the one that stays.
            if len(u) == len(t) and _box_area(q) <= _box_area(r):
                continue
            if _sits_on(r, q) < READ_TWICE_IN:
                continue
            dead.append(r)
            gone.add(id(r))
            break
    return dead


def empty_boxes(regs) -> list:
    """The boxes the reader found NOTHING in - and no others.

    lee: *"i also want to add a fetur for read text that delets any boxes that
    no text is found in so if it return nothing then delete that box that
    probly mena that teh box was bad anyways"*.

    This is a reversal, and worth saying so plainly. `ocr.only_symbols` refuses
    to call empty "symbols only", and its docstring gives the reason: *"deleting
    a box because the reader had a bad turn is the one outcome this must never
    have"*. That reasoning still holds for a bad TURN. What lee is pointing at
    is a bad BOX -- the detector put a rectangle on something that was never
    writing, the reader looked and found nothing, and that is the best evidence
    anybody has that the box should not be there.

    Telling those two apart is the whole of this function. **At least one box
    on the page has to have read something.** A page where the reader came back
    empty on everything is an outage -- no key, no quota, a refusal, a dropped
    connection -- and on that page nothing is deleted. A page where nine boxes
    read and one did not is a bad box, and it goes.

    The three boxes that are not the app's to throw away are the same three
    `symbol_only_boxes` protects, for the same reasons: a box somebody typed
    themselves, a locked box, and a box that already carries a translation.
    """
    live = [r for r in regs
            if not getattr(r, "own_text", False)
            and not getattr(r, "locked", False)
            and not (getattr(r, "dst_text", "") or "").strip()]
    empty = [r for r in live if not (getattr(r, "src_text", "") or "").strip()]
    if not empty:
        return []
    if len(empty) == len(live):
        return []            # the reader had an outage, not a page of bad boxes
    return empty


@_steps_aside("ocr")
def _read_with_ai(p: Project, i: int, page, say, detail_for, page_label_tiles,
                  looks_like_garbage, read_page_ocr) -> None:
    """The vision model reads the labelled page. Was the body of `do_ocr`."""
    regs = page.regions
    _ctx_from_settings(p, "ocr")
    say("Reading text — sending the page to the AI reader…")
    # A close-up of each box, always. It is not a setting any more - lee:
    # *"make teh zoomed ... teh only option for the read text"* - because it
    # won on both formats it was ever scored on and cost a third fewer image
    # tokens doing it. `detail_for` holds the numbers.
    #
    # A project saved with an older `ocr_detail` is not consulted: a chapter
    # half-read on tiles and half on crops would be two different runs under
    # one name, and the tiles are the worse half.
    # ...at the detail somebody chose. It was hard-wired to a close-up per
    # box, which is the most accurate mode and also the dearest by a long way
    # - one picture a BOX rather than one a page. lee, on seeing what that
    # does to a bill: *"can you bring back teh 1, 4 and 9 cut"*.
    detail = detail_for(p.settings.get("medium"),
                        p.settings.get("ocr_detail"))
    tiles = page_label_tiles(page, detail=detail)
    # A crop per box is a dozen small pictures that all want the same system
    # prompt, so they ride in ONE turn. See `ocr.page_box_crops` for what it
    # costs (less than the page does) and `translate._ask_vision` for how.
    batch = len(tiles) if detail == "boxes" else 1

    def tick(n: int, total: int) -> None:
        if total > 1:
            say(f"Reading text — AI reader, piece {n} of {total}…")

    try:
        texts = read_page_ocr(page, p.ctx, tiles, progress=tick, batch=batch)
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


def label_page_kinds(p: Project, i: int, page, say) -> int:
    """Say what kind of box each one on this page is. Returns how many moved.

    lee: *"i want [it] to ... accura;y lables all the boxes with the sub types
    ... it shoud not creade or dleet boxes just labbles them"*.

    Everything this function is allowed to do is one assignment to `r.kind`, on
    a region that is already on the page. There is no branch here that adds a
    region, removes one, or touches anything else about it.

    Four things can stop a label, and they are checked in the order that costs
    least. `label_kinds` has already dropped an id that is not on the page, a
    type outside the vocabulary, and a type from another family - see there for
    why the code re-checks what the prompt already asks for. What is left here
    is the two this end knows about: a box somebody typed by hand, and a label
    that is the type the box already has.
    """
    from .kinds import labelling_vocabulary
    from .ocr import page_label_png
    from .translate import LABEL_SIDE, label_kinds
    regs = [r for r in page.regions if not getattr(r, "own_text", False)]
    if not regs:
        return 0
    # The vocabulary comes from the OPEN PROJECT's sub-types, which is what
    # makes both of lee's rules true at once: a sub-type somebody invented is
    # not offered because it is not one of ours, and a preload somebody deleted
    # is not offered because it is not in their list any more.
    vocab = labelling_vocabulary(p.settings.get("custom_kinds") or [])
    if not any(len(v) > 1 for v in vocab.values()):
        return 0            # every family down to its default: nothing to say
    _ctx_from_settings(p, "ocr")
    say("Reading text — labelling the boxes…")
    # The angle rides along with the labels. It is asked for in the same turn
    # and read out of the same reply, so a page that gets one gets the other -
    # and a reply that is useless for kinds can still be right about which way
    # a sound effect leans, which is why the two are counted apart.
    angles: dict = {}
    got = label_kinds(page, p.ctx, page_label_png(page, max_side=LABEL_SIDE),
                      vocab, angles=angles)
    turned = _apply_read_angles(page, angles)
    if not got:
        if turned:
            invalidate_page(i)
        return 0
    moved = 0
    for r in page.regions:
        want = got.get(r.id)
        if not want or want == getattr(r, "kind", ""):
            continue
        # A TYPE SOMEBODY CHOSE IS AN ANSWER, not a guess to be improved on.
        # lee picked this: a type you fixed by hand coming back wrong on every
        # re-read is worse than no labelling at all.
        if getattr(r, "kind_by_hand", False):
            continue
        was = getattr(r, "kind", "") or ""
        r.kind = want
        moved += 1
        # ...and if the FAMILY moved, this was the sound-effect-against-outside-
        # text correction and not a sub-type. Two things follow from that and
        # neither follows from a sub-type:
        #
        # The box says so in its notes, in the same words `translate._retype`
        # uses - it is the same decision, made a step earlier, and a person
        # reading the page should not have to know which pass made it.
        #
        # And the GEOMETRY goes with it. A region called outside text still
        # carrying a balloon polygon typesets into the balloon's shape, which
        # is `_kind_changed`'s whole reason for existing - lee: *"i changed teh
        # bubble to outside buuble an it still typeseete the same"*.
        if _kinds.family_of(want) != _kinds.family_of(was):
            r.flagged = ((getattr(r, "flagged", "") or "")
                         + " kind: read as %s rather than %s"
                         % (_kinds.family_of(want), was)).strip()
            _region_kind_changed(r, was)
    if moved or turned:
        # THE CACHE KEY CANNOT SEE THIS. `cached_page` keys on the page index,
        # the NUMBER of regions and the hidden families - and a relabel changes
        # none of the three while changing what the page looks like: a box's
        # colour comes from its kind, and a kind that has been hidden takes its
        # boxes off the page altogether. The region endpoint clears the cache
        # by hand on a kind change for exactly this reason.
        invalidate_page(i)
    if moved:
        say(f"Reading text — labelled {moved} box{'' if moved == 1 else 'es'}…")
    return moved


def _apply_read_angles(page, angles: dict) -> int:
    """Put the angles the reading gave onto the boxes. Returns how many moved.

    lee chose the rule when I put it to him: FILL THE GAPS ONLY.

    SOUND EFFECTS ONLY. It was outside text as well for one afternoon, until
    he saw a caption set on a slant: *"also make all teh freefloast text be
    start no more angle"*. A freefloat block is typeset level now
    (`typeset.fit_region`), so an angle on one would be a number nothing reads.

    A sound effect usually already has an angle, measured off the Japanese ink
    at Find text while the Japanese was still on the page. That is a better
    number than a model reading a 768px thumbnail, and it is not overwritten.
    The reading fills in the effects the measurement never reached: one drawn
    by hand since, or one whose ink the axis reader could not make out.
    `sfx_len`/`sfx_wid` are how that shows - `read_sfx_axis` sets all four
    together or none of them.

    And an angle set BY HAND is never touched, for the same reason a type set
    by hand is not: it is an answer, not a guess to improve on.
    """
    if not angles:
        return 0
    turned = 0
    for r in page.regions:
        deg = angles.get(r.id)
        if deg is None:
            continue
        fam = _kinds.family_of(getattr(r, "kind", "") or "")
        if fam != "sfx":
            continue                      # not this pass's business
        if (float(getattr(r, "sfx_len", 0.0) or 0.0) > 0
                and float(getattr(r, "sfx_wid", 0.0) or 0.0) > 0):
            continue                      # measured off the ink: leave it
        if getattr(r, "angle_by_hand", False):
            continue
        if abs(float(getattr(r, "angle", 0.0) or 0.0) - deg) < 0.05:
            continue                      # already says this
        r.angle = float(deg)
        turned += 1
    return turned


def _read_here(p: Project, page, say) -> None:
    """manga-ocr (or easyocr) reads each box, on this computer.

    No key, no network, no coins. `ocr.ocr_page` is the same call the command
    line has always made, so there is one offline reading path and not two -
    including the guards on it, which are the ones the AI path keeps too: a
    box holding somebody's OWN text stands for no writing in the artwork, and
    a locked, hand-corrected line is never overwritten by a re-read.

    AND THE CROP IS `prepare_crop`'S OWN, AT ITS OWN SIZE. lee: *"use teh best
    mangaocr setting for the manga orc version"* - so it was measured, all 225
    boxes of chapter 3 at three sizes, scored against the AI's crop-per-box
    read:

        half the crop      CER 0.072   125/189 identical
        the crop as it is  CER 0.059   136/189      <- this one
        twice the crop     CER 0.062   137/189

    Native wins, and it is the size the app already makes. Nothing to add: the
    model resizes to 224px inside itself whatever it is handed, so a bigger
    picture is pixels thrown away - which is also why every size took the same
    0.42s a box, and why the offline reader has no "reading detail" of its own.

    (Sound effects go the other way, better at half size, 0.366 against 0.538.
    Not acted on: that is improvement from a hopeless baseline, and sizing
    crops by box family for a reader that should not be reading paint at all
    is a rule to maintain in exchange for nothing.)

    AND THE CROP IS NOT PADDED. That is a separate question from its size -
    room AROUND the box rather than more pixels of it - and lee asked for it
    after one sound effect was fixed by a tenth: *"add the 10% for ecerything
    not just sfx aand test it"*. Tested, on all 32 transcribed boxes, every box
    found again on its own page and re-cut at six margins:

        margin   all boxes         dialogue          sound effects
          0%     0.078  25/32      0.049  22/27      0.233  3/5
          5%     0.087  21/32      0.060  18/27      0.233  3/5
         10%     0.076  24/32      0.046  21/27      0.233  3/5
         15%     0.151  18/32      0.069  17/27      0.595  1/5
         20%     0.155  16/32      0.080  15/27      0.557  1/5
         30%     0.213  14/32      0.094  14/27      0.857  0/5

    Ten per cent is not an improvement, it is the same number twice: one box
    gained (チラッ, misread as イラッ with no margin) and one lost, and every
    sound effect is untouched at any margin under fifteen. Past that it falls
    off a cliff, and the reason is in the readings - the neighbouring balloon
    arrives inside the crop and is read as part of the line: at 30% one box
    came back with the balloon above it appended whole.

    So: no padding, because a change that costs a constant should buy something
    measurable, and this one buys a coin toss. What the sweep DOES establish is
    that the drop past 15% is real and steep, which is worth knowing for
    anything that ever grows a reading crop for another reason.
    """
    from .ocr import get_engine, ocr_page
    lang = str(p.settings.get("source") or "ja")
    if str(lang).lower() == "auto":
        lang = "ja"
    name = p.settings.get("ocr_engine") or "auto"
    say("Reading text — starting the reader on this computer…")
    # Loaded BEFORE the say() below, because the first call downloads the
    # model and that is the slow part somebody is waiting through.
    engine = get_engine(lang, name)
    # ...and the second reader, for the boxes manga-ocr is worst at. Absent is
    # a normal state and not an error: with no checkpoint on the machine this
    # is "" and the page reads exactly as it did before `paintread` existed.
    paint = p.paint_weights() if lang == "ja" else ""
    n = sum(1 for r in page.regions if not getattr(r, "own_text", False))
    say(f"Reading text — reading {n} box{'' if n == 1 else 'es'} on this "
        f"computer…")
    ocr_page(page, engine=engine, lang=lang, engine_name=name,
             paint_weights=paint)


def reading_offline(p: Project) -> bool:
    """Is the Read text step set to the reader on this computer?

    One question, one place. `do_ocr` branches on it, `needs_key` stops asking
    for a key because of it, and `run_price` charges nothing for it - and if
    those three ever disagreed, somebody would be billed coins for a run that
    never left the machine.
    """
    return str(p.settings.get("ocr_reader") or "ai").lower() == "offline"


def do_ocr(p: Project, i: int) -> None:
    """Read the Japanese out of every bubble.

    Two readers, and the setting says which. The AI sends the whole page at
    once - outlined and numbered - so each line is read WITH the surrounding
    dialogue as context (which is what lets it tell 居たぞ from 口はたぞ, or
    rebuild a broken name). It is prompted to transcribe only what is printed
    and to leave a region empty rather than invent a plausible line.

    The offline reader is manga-ocr, which sees one box at a time and nothing
    else. It cannot use the page to settle a name - and it cannot file a line
    under the wrong box either, which is the mistake the labelled page makes.
    See `ocr` for the engines and `project`'s `ocr_reader` for the measurement.

    Everything after the reading - the two drops, the links, the ink - is the
    same either way. Those passes ask questions about the WORDS, and the words
    are words whoever read them.
    """
    from .inkstyle import measure_page
    from .ocr import detail_for, page_label_tiles, looks_like_garbage
    from .translate import link_sections, read_page_ocr
    page = p.materialize(i)
    regs = page.regions
    if not regs:
        return
    before = len(regs)

    def say(msg: str) -> None:
        try:
            if p.job.get("running"):
                p.job["label"] = msg
        except Exception:
            pass

    if reading_offline(p):
        _read_here(p, page, say)
    else:
        _read_with_ai(p, i, page, say, detail_for, page_label_tiles,
                      looks_like_garbage, read_page_ocr)
    # ...AND NOW THAT THERE ARE WORDS, THE BOXES THAT HAVE NONE.
    #
    # Those two drops, and nothing else. lee: *"make it so that read text only
    # read teh etxt and not modify boxes exapt for removing boxes with no text
    # or remoeving boxes with only symobos"*.
    #
    # Three passes stood here and were taken back out with that sentence: a
    # relabel that renamed a box from what was read in it (`readkinds`), a
    # demotion of a sound effect whose reading turned out to be a sentence,
    # and a drop of a box whose reading was part of an overlapping box's. Each
    # was measured and each worked; all three CHANGE a box rather than fill it
    # in, and this step is for filling boxes in. The reading is still there to
    # act on afterwards, by hand or from another pass, if any of them comes
    # back.
    #
    # lee:
    # *"if a box is only symboled with no text it shodu auto delete"*.
    #
    # BEFORE `link_sections`, deliberately: a dropped box must not first be
    # joined to its neighbour as the second half of a sentence. `!` under a
    # line of dialogue is exactly the shape that reads on, and linking it and
    # then deleting it leaves the line pointing at a box that is gone.
    #
    # `!== False` rather than `.get(..., True)` - a project.json written
    # before this setting existed has no key at all, and it should behave the
    # way lee asked for it to behave by default.
    if p.settings.get("drop_symbol_only") is not False:
        junk = symbol_only_boxes(regs)
        if junk:
            gone = {id(r) for r in junk}
            page.regions = [r for r in page.regions if id(r) not in gone]
            regs = page.regions
            n = len(junk)
            say(f"Reading text — removed {n} box{'' if n == 1 else 'es'} "
                f"with nothing but symbols in {'it' if n == 1 else 'them'}…")
    # ...and the boxes the reader found NOTHING in. See `empty_boxes` for why
    # that is a different question from the one above, and for the guard that
    # keeps a reader outage from emptying a page.
    if p.settings.get("drop_empty") is not False:
        blank = empty_boxes(regs)
        if blank:
            gone = {id(r) for r in blank}
            page.regions = [r for r in page.regions if id(r) not in gone]
            regs = page.regions
            n = len(blank)
            say(f"Reading text — removed {n} empty box"
                f"{'' if n == 1 else 'es'}…")
    # ...and the writing answered twice: a box whose reading is part of an
    # overlapping box's reading. lee: *"can you gring teh fix we had before"*.
    #
    # It belongs with the two drops above and not with the passes that came
    # out beside it: those RENAMED a box, this removes one that holds no
    # writing of its own. BEFORE `link_sections`, for the same reason the
    # other two are: a dropped box must not first be joined to its neighbour
    # as half of a sentence.
    if p.settings.get("drop_read_twice") is not False:
        twice = read_twice_boxes(regs)
        if twice:
            gone = {id(r) for r in twice}
            page.regions = [r for r in page.regions if id(r) not in gone]
            regs = page.regions
            n = len(twice)
            say(f"Reading text — removed {n} box{'' if n == 1 else 'es'} "
                f"that read as part of another…")
    # ...and now WHAT KIND of box each of the survivors is.
    #
    # lee: *"alos coun;t read text do the same thing after its done reading teh
    # text?"* - having first asked the proofreader for it. See
    # `translate.label_kinds` for why he was right about which step.
    #
    # AFTER the three drops, deliberately, and it is not only about spending
    # less: the labeller is shown the page with the surviving boxes outlined on
    # it, and a picture carrying boxes that are about to be deleted is a
    # picture that disagrees with the listing beside it.
    #
    # THIS IS THE SLOT `readkinds` USED TO OCCUPY, and that pass was taken out
    # at lee's request - *"make it so that read text only read teh etxt and not
    # modify boxes exapt for removing boxes with no text or remoeving boxes
    # with only symobos"*. Worth saying plainly rather than hoping nobody
    # notices, because the reasons it went do not reach this:
    #
    #   * `readkinds` renamed a box from WHAT WAS READ IN IT, so a mis-read
    #     changed a box's type. This reads the drawing and never the words.
    #   * It moved boxes between FAMILIES, which is what decides how a box is
    #     cleaned. This cannot: `label_kinds` drops any answer whose family
    #     differs from the box's own, and the prompt says so as well.
    #   * It had no idea whether a person had already chosen. This skips a box
    #     carrying `kind_by_hand`.
    #
    # It also cannot create or delete one. `label_kinds` returns
    # {existing id: type} and there is no other thing for it to say.
    if labels_boxes(p):
        try:
            label_page_kinds(p, i, page, say)
        except Exception as e:
            # A label is a nicety and the reading is the job - the same rule
            # `measure_page` below is under. A page whose types could not be
            # improved on still has every type it arrived with.
            say(f"Reading text — could not label the boxes ({e})")
    # Now that there are words, the one question the pixels could not answer:
    # are two sections of a balloon one sentence broken in two, or two things
    # said? The detector used to guess this and got lee's hot-spring balloon
    # wrong. See `translate.reads_on`.
    link_sections(regs)
    # ...and what the letters were PAINTED with, while they are still on the
    # page. This is the last moment: cleaning wipes the Japanese, and by the
    # time the typesetter runs there is nothing left to measure. lee: *"is it
    # posible to have teh ai laos look for color/formats"* - it is, and the
    # pixels answer it better than the reader would. See `inkstyle`.
    try:
        # The tally is kept on the PROJECT, so a chapter read in one run comes
        # out with one black in it rather than one per page. See `_snap`.
        if getattr(p, "ink_seen", None) is None:
            p.ink_seen = {}
        measure_page(page, p.ink_seen)
    except Exception:
        pass                     # a colour is a nicety; the words are the job
    p.commit(i, page)
    # A box set that changed has to be renumbered, or the reading order keeps
    # the gap the deleted box left and the cached overlay still has its
    # rectangle on it. Same call the delete button makes, for the same reason.
    if len(page.regions) != before:
        reorder(p, i)


def chapter_context(p: Project, indices=None):
    """The rest of the chapter, as lines the model can read.

    **Every other page**, not a window around the run. A window of two cannot
    see a name settled six pages back, or a term agreed at the front of a long
    re-run - and those are exactly the things a reader notices when they drift.
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
    byte-identical on every page and sits inside the prompt cache - see
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
    is nothing to be consistent WITH that is not already in the run - and the
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


def seed_sounds(p: Project) -> int:
    """Start a run knowing what this chapter has already called its sounds.

    `SeriesContext.sounds_seen` grows as a run goes, which is what stops page
    22 inventing a second word for page 21's sound. It lives in memory, like
    `terms_seen` and `names_seen` beside it - and unlike those two it has
    nowhere else to go. A term has the glossary and a name has the character
    sheet; a sound effect has never been written down anywhere, which is the
    whole reason it drifted.

    So the chapter itself is the record. Every page already on disk carries
    its Japanese and the English somebody settled on, and re-reading that
    costs nothing and asks nobody. It means:

    * re-translating ONE page sees the other twenty-two pages' sounds, rather
      than starting from an empty list and answering fresh;
    * closing the app and coming back loses nothing;
    * a page corrected BY HAND teaches the rest of the chapter, because the
      correction is in `dst_text` like any other answer.

    Returns how many it knew before anything ran, which is a fair thing for
    the run to be able to say.
    """
    from . import translate as translate_mod
    ctx = getattr(p, "ctx", None)
    if ctx is None:
        return 0
    have = getattr(ctx, "sounds_seen", None)
    if have is None:
        have = ctx.sounds_seen = {}
    # With the PROJECT'S OWN sub-type list rather than the module global, so
    # the answer cannot depend on whether `kinds.use()` has run yet - the same
    # care `_plate_stamp` takes, for the same reason. `sfx_big` is one of
    # lee's own, and an unregistered sub-type reads as a bubble.
    subs = p.settings.get("custom_kinds") or []
    for st in p.pages:
        for r in st.regions:
            if _kinds.family_of(r.get("kind") or "", subs) != "sfx":
                continue
            k = translate_mod.sound_key(r.get("src_text") or "")
            v = " ".join((r.get("dst_text") or "").split())
            if k and v and k not in have:
                have[k] = v
    return len(have)


@_steps_aside("translate")
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
# by a mid-tier one and proofread by the best one available - which is where
# nearly all the cost is, because reading and translating run on every page
# while the expensive judgement only has to happen once at the end.
AI_STEPS = ("ocr", "translate", "proofread")

# Providers that will not answer without one. All three of them, now that the
# services this app offers are Claude, Gemini and OpenRouter and nothing else:
# every one is somebody's paid endpoint.
NEEDS_KEY = ("anthropic", "gemini", "openrouter")

# The three services, in the order the menus list them. `project.SERVICES` and
# the `SERVICES` in `static/js/project.js` are this same list, held together by
# a test - a service the screen offers and the server does not know is a step
# nobody can run, and it fails at the provider rather than at the menu.
SERVICES = (("anthropic", "Claude API"),
            ("gemini", "Google AI Studio"),
            ("openrouter", "OpenRouter"))

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
    `GET /models` without one, so the request could only ever time out - three
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


# An OpenRouter id can carry a VARIANT after a colon - `:free`, `:nitro`,
# `:floor`. Each is a different price for the same model and none of them is
# the price in the table, so they are not offered: a `:free` variant quoted at
# the paid rate overcharges, and a `:nitro` one quoted at the standard rate is
# a bill this app eats.
VARIANT = ":"


def model_menu(back: str, url: str, key: str, step: str = "",
               elsewhere=()) -> list:
    """The models this step may be put on: reachable AND priceable.

    Both halves are needed and each one alone is a different fault.

    * Offer what the app cannot PRICE and the step silently runs at the top of
      the range, which is an eightfold difference nobody would guess from
      looking at the number.
    * Offer what the key cannot REACH and you get lee's 404:
      `gemini-2.5-flash` sat in the menu looking available and was not enabled
      on his Google project.

    **It starts from what the key can reach, not from a list written here.**
    That is the fix for the second bug lee found - an OpenRouter menu holding
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
    that is down - none of those mean the person has no models, and an empty
    menu is a step nobody can configure, which is worse than the fault it was
    trying to report.
    """
    from . import coins

    free = (back or "").strip().lower() in coins.FREE_BACKENDS
    # What the OTHER services can already run, with the keys this project
    # holds. Only OpenRouter cares - see below.
    direct = {coins.vendor_free(m) for m in (elsewhere or ())}

    def usable(m):
        # The variant rule is about PRICE, so it only applies where there is
        # one. A local tag is full of colons - `qwen2.5:14b-instruct` - and
        # costs nothing whichever one you pick.
        if not free and VARIANT in m:
            return False
        if not coins.priced(m, back) or coins.vendor_free(m) in coins.RETIRED:
            return False
        if step == "ocr" and not coins.sees(m):
            return False
        # A model you run yourself is a name you chose, not a range somebody
        # publishes: there is no modality to guess at and no generation to be
        # behind. Both rules are about a provider's catalogue.
        if not free and not (coins.usable_model(m) and coins.current_enough(m)):
            return False
        # **OpenRouter is for what your own keys cannot reach.** lee: *"exclue
        # teh molde that are usabe with teh keys that i have for example i cnat
        # use gemeini 2.5 flash with my goohle key so it shoud be in teh open
        # router"*.
        #
        # Asked of the KEYS, not of a table: a model your Google key can
        # already run is not a thing to buy through a reseller, and one it
        # cannot is exactly what the reseller is for. With no Google key at
        # all, nothing is subtracted - OpenRouter is then the only way to any
        # of it, which is the same rule reaching the opposite answer.
        if back == "openrouter" and coins.vendor_free(m) in direct:
            return False
        return True

    known = ([m for m in coins.models_for(back) if usable(m)] if free
             else coins.offered(back, step))
    offer = [m for m in _reachable(back, url, key) if usable(m)]
    if not offer:
        return known
    # The table's order first, because it is newest-first and hand-kept, then
    # everything else by name. A menu sorted purely alphabetically opens on the
    # oldest model in the range, which is the one nobody wants and the one that
    # gets picked by accident.
    rank = {m: i for i, m in enumerate(coins.models_for(back))}
    offer.sort(key=lambda m: (rank.get(m, len(rank)), m))
    # ...and then one model per price. Done HERE, after the reachable check,
    # so a price band is never emptied by trimming away the only model in it
    # this key can run. A local provider is left alone: nothing there has a
    # price to be a duplicate of.
    return offer if free else coins.one_per_price(offer)


# The last resort, for a project.json old enough to be missing the keys
# entirely. Every project made since carries its own - `Project.settings` is
# where the defaults live and where the screen reads them from, and these have
# to agree with those, which a test holds.
#
# They exist at all because a step with no model would be a step the price
# screen could not name, and naming what each step will run on is the whole
# point of these three boxes. lee: *"the coins shou look at what ai is in each
# of teh step to use to bill"*.
# What each step is CALLED, everywhere a person reads its name: the "no API
# key" note, and the refusal a provider sends back. One map, because those two
# said different things - the refusal said "the OCR step's key was refused" on
# a run of Translate, since `step_name` was only ever set by the AI find pass
# and every other step left it empty and took the "OCR" fallback. That pass is
# gone (lee: *"remoeve teh whole ai box deection and just keep what we have
# now"*), so the fallback was the only path left.
STEP_LABEL = {"ocr": "Read text", "translate": "Translate",
              "proofread": "Proofread"}

STEP_DEFAULTS = {
    "ocr": ("gemini", "gemini-3.5-flash-lite"),
    "translate": ("gemini", "gemini-3.7-flash"),
    "proofread": ("anthropic", "claude-sonnet-5"),
}


def _ctx_from_settings(p: Project, step: str = "") -> None:
    """Point the context at the model this STEP will use.

    The step decides everything: which provider, which model, which address,
    which key. There is no project-wide engine sitting behind it any more -
    there were two of them, they answered the same question as these boxes,
    and a price quoted against the wrong one of the two is a price for a model
    the step was never going to call.

    A step nobody has configured falls back to `STEP_DEFAULTS`, which is a
    default and not a setting: it is the same for every project, so it cannot
    drift out of step with what the screen shows.
    """
    s = p.settings
    p.ctx.medium = s.get("medium") or "manga"
    # What the typesetter will actually be allowed to set, so the translator
    # can be told how much each balloon holds. BOTH ends: the budget is taken
    # at `translate.comfort_size`, a fraction of the full size, because the
    # floor is a size the typesetter never reaches. See `translate.fits_chars`.
    try:
        p.ctx.min_font = int(s.get("min_font") or 12)
    except (TypeError, ValueError):
        p.ctx.min_font = 12
    try:
        p.ctx.max_font = int(s.get("max_font") or 34)
    except (TypeError, ValueError):
        p.ctx.max_font = 34
    p.ctx.source = s.get("source") or ""
    p.ctx.target = s.get("target") or "en"
    # Filters off, on every request rather than behind a switch. lee: *"remove
    # this no api shoud have a conetent filter"*, and again *"no ai shoud have
    # any content filter"*. The switch was turned on by everyone who ever found
    # it, because a chapter gets refused on ordinary drawn violence often
    # enough that a translator cannot work around it a page at a time.
    #
    # One value for every maker, because the client is what knows which of them
    # has a switch: `translate.takes_google_options` sends the thresholds to
    # Google's endpoint and through OpenRouter, and sends nothing to Claude or
    # OpenAI - not because those are left filtered on purpose, but because
    # neither publishes a per-request threshold to turn off.
    #
    # What it is NOT: Google's protections against core harms are not
    # configurable at any threshold and stay on. A page can still come back
    # refused, and `translate._refusal` is what says so plainly instead of
    # failing on a schema error two retries later.
    p.ctx.safety = "OFF"
    # The story switches. Read on every step because they change what is SENT
    # as well as what is kept, and a setting toggled between two runs has to
    # bite on the second one. Default TRUE, so a project.json written before
    # they existed behaves exactly as it did.
    p.ctx.story = s.get("story", True) is not False
    p.ctx.learn_characters = s.get("learn_characters", True) is not False
    p.ctx.learn_terms = s.get("learn_terms", True) is not False
    p.ctx.name_speakers = s.get("name_speakers", True) is not False
    # The one that was half-wired. `keep_honorifics` has been going into the
    # payload and into the PROOFREAD prompt since the day it was added, and the
    # translate prompt was never told - so the proofreader was policing a
    # decision the translator had never been asked to make, and lee's chapter
    # came back "Mr. Glow" with a rule about "Glow-san" sitting under it. See
    # `translate.HONORIFIC_NOTES`.
    p.ctx.honorifics = s.get("keep_honorifics", True) is not False
    # ...and OFF unless asked: it rewrites a label the person may have set by
    # hand. See `translate.RETYPE_KINDS`.
    p.ctx.retype_kinds = s.get("retype_kinds", False) is True

    back, model = STEP_DEFAULTS.get(step, STEP_DEFAULTS["translate"])
    if step not in AI_STEPS:
        # Not an AI step, so there is nothing it will call. The context is
        # still filled in - plenty of code reads it - but with the defaults
        # rather than with some other step's engine.
        p.ctx.backend, p.ctx.model = back, model
        p.ctx.base_url, p.ctx.api_key = "", ""
        return
    p.ctx.backend = (s.get(f"{step}_backend") or "").strip() or back
    p.ctx.model = (s.get(f"{step}_model") or "").strip() or model
    p.ctx.base_url = (s.get(f"{step}_base_url") or "").strip()
    # One key per SERVICE. See `key_for` - the service box is the answer and
    # the step's own box is only a leftover to fall back on.
    p.ctx.api_key = key_for(p, p.ctx.backend, step)
    # THE OPENROUTER CROSSING. lee: *"it shoud try to use the claude or
    # google key first and it it sondt work use teh open router key next"*.
    # Two ways for the first key to not work, handled in the same place:
    # it is MISSING (known now, before any page), or a provider REFUSED it
    # earlier this session and `or_openrouter` left the memo. A step pointed
    # at a local or odd address is left alone - no key was ever the plan.
    if (p.ctx.backend in ("anthropic", "gemini") and not p.ctx.base_url
            and fallback_key(p)
            and (not p.ctx.api_key
                 or step in getattr(p, "_openrouter_instead", ()))):
        _openrouter_ctx(p)
    # No key anywhere, signed in: through the relay, with the ID token where
    # the key goes. Per page, so a token that runs out mid-chapter is
    # refreshed by `account.token` before the next one.
    p.ctx.relayed = False
    if (not p.ctx.api_key and not p.ctx.base_url and p.ctx.backend in RELAYED
            and relay_ready()):
        tok = relay_token()
        if tok:
            p.ctx.base_url = relay_url(p.ctx.backend)
            p.ctx.api_key = tok
            p.ctx.relayed = True
    # ...and what to call this step if the provider refuses it. See
    # `translate._model_error`: without this the message names the reader
    # whichever step was actually running.
    p.ctx.step_name = STEP_LABEL.get(step, "")


@_steps_aside("proofread")
def do_proofread(p: Project, i: int) -> None:
    """The AI re-reads the page's English against the Japanese: lines that do
    not make sense get fixed, and character names are rewritten to exactly
    what the settings sheet says. Works on the stored records directly -
    proofreading needs text, not masks - so flags survive.
    """
    from .translate import proofread_page, match_known
    from .models import TextRegion

    recs = p.pages[i].regions
    if not any((r.get("dst_text") or "").strip() for r in recs):
        return                                    # nothing translated yet

    _ctx_from_settings(p, "proofread")
    # The sheet may have been edited by hand in settings since this page was
    # translated - a name corrected, a person renamed. p.ctx.characters is
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
                   # of a split sentence - without them the proofreader is
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
            # WHAT IT SAID BEFORE. lee: *"shwo the proofreading changes too in
            # the trnalation tab"*.
            #
            # The page note already says the proofreader had a remark and the
            # chips already say which boxes it touched, and neither of those
            # tells you what it DID. A copy editor's change is only reviewable
            # beside the line it replaced - "Take a look" against "Take a good
            # look" is the whole of the decision - and until now the old
            # wording was overwritten here and gone.
            #
            # It is a record of ONE run, so it is set on the way past and
            # cleared below when a later run leaves the line alone.
            rec["proofread_was"] = rec["dst_text"]
            # the wording changed: stale typesetting must not outrank it
            rec["dst_text"] = tr.dst_text
            rec["layout"] = None
            ov = dict(rec.get("layout_override") or {})
            for k in ("lines", "fit", "wrap", "snug"):
                ov.pop(k, None)
            rec["layout_override"] = ov or None
        else:
            # This run left the line alone, so any "was" on it belongs to an
            # earlier one and is a change nobody made today. Same reason the
            # page note is written unconditionally below.
            rec.pop("proofread_was", None)
        # What this run has to say about this box, and nothing older.
        #
        # Written UNCONDITIONALLY, the same reason the page note below is: a
        # proofread that finds nothing wrong has to be able to CLEAR the last
        # run's remark. It used to be set only when there was something to
        # say, so a note stayed on the box after the thing it described had
        # been fixed - and lee's chapter 3 report carried three sound effects
        # flagged by `half_a_sound`, a check that no longer exists in the app.
        rec["flagged"] = tr.flagged or None
        if tr.flagged:
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
    # it uses ids the person never sees; this is the factual list - every box
    # whose wording this run actually changed, plus any it flagged - worked out
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
# is the wrong way round - the problems are the short list and the script is the
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

    Bubbles break their text across lines and those breaks are worth keeping -
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
    """`p8 l9, p32 l3` - short enough to sit at the end of a line."""
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
    # - which is most of the ones that drift.
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

    # HONORIFICS, and WHICH WAY ROUND depends on what the project decided.
    #
    # This asked one question - "is an honorific left welded to a name?" - and
    # raised it whenever the answer was rare. On a project that KEEPS
    # honorifics that is exactly backwards, and lee's chapter 3 report is what
    # showed it: `keep_honorifics` was on, eight lines said Glow-san, and the
    # report called those eight the anomaly while saying nothing about the
    # three lines that had quietly dropped one.
    #
    # So the rare thing is only the anomaly when it disagrees with the
    # decision. Kept: a name whose Japanese carries an honorific and whose
    # English has none is the drift. Dropped: the old question, unchanged.
    pat = _re.compile(r"\b([A-Z][A-Za-z]+)[-‐‑‒–]("
                      + "|".join(_HONORIFICS) + r")\b", _re.I)
    if getattr(getattr(p, "ctx", None), "honorifics", True):
        # A KATAKANA name with an honorific on it, which is the case the sheet
        # is about - not 店主さん or お姉様, where the English rendering is a
        # word rather than a name and losing the suffix is not drift.
        ja_name = _re.compile(r"[ァ-ヶ][ァ-ヶー]+(さん|様|ちゃん|くん|殿)")
        lost = [(pg, ln, m.group(0), t)
                for pg, ln, _r, t in said
                for m in [ja_name.search(str(_r.get("src_text") or ""))]
                if m and not pat.search(t)]
        if lost:
            out.append("**A name that lost its honorific**, in a chapter that "
                       "keeps them.")
            out.append("")
            for pg, ln, hit, t in lost[:12]:
                out.append(f"- p{pg} l{ln} — `{hit}` — {t[:60]}")
            out.append("")
    else:
        leaks = [(pg, ln, m.group(0))
                 for pg, ln, _r, t in said for m in pat.finditer(t)]
        if leaks and len(leaks) <= max(3, len(said) // 20):
            out.append("**A Japanese honorific left on a name**, in a chapter "
                       "that drops them everywhere else.")
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
            # ...and what it said before the proofreader, on the lines the
            # proofreader changed. The report is the other place this gets
            # reviewed, and a copy edit read without the line it replaced is
            # not a thing anybody can agree or disagree with.
            was = str(r.get("proofread_was") or "").strip()
            if was and was != en.strip():
                body += _md_block("was", was)
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
    more than assigning the string - the layout was computed for the old
    wording, the proofread tick was given to the old wording, and any lines
    typed by hand into the override ARE the old wording. All of that goes.
    What survives is the styling: the face, the colours, the frame somebody
    dragged to where they wanted it.
    """
    # Same door the model's own output comes through: a translations file is
    # very often a machine's, and an ellipsis on the front of a line the
    # Japanese does not open with is a pause the page never drew.
    # ...and nothing else in front of it either. lee: *"there isjat anything
    # informt of th text in the raw so there shoud be notjing in the
    # transated"*. See `translate.strip_added_lead`.
    from .translate import strip_added_ellipsis, strip_added_lead
    src = str(rec.get("src_text") or "")
    rec["dst_text"] = strip_added_lead(
        strip_added_ellipsis(
            typeset_mod.normalize_text(str(text or "").strip()), src),
        src)
    rec.pop("proofread", None)              # new text: nobody has read it yet
    # ...and the proofreader's before-and-after went with it. "was X, now Y"
    # under a line that now says Z is a comparison against nothing.
    rec.pop("proofread_was", None)
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
    sheet, not by region id - the id is an internal thing a person filling in
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
    # the time - a page reload, a fetch superseded by the next one, a tab
    # closed - and the answer is then written to a socket nobody is holding.
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

    def _form_or_json(self) -> dict:
        """The body as a dict, whether it came as a form post or as JSON."""
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = str(self.headers.get("Content-Type") or "")
        if ctype.startswith("application/x-www-form-urlencoded"):
            got = urllib.parse.parse_qs(raw.decode("utf8", "replace"),
                                        keep_blank_values=True)
            return {k: v[-1] for k, v in got.items()}
        try:
            got = json.loads(raw or b"{}")
        except ValueError:
            got = {}
        return got if isinstance(got, dict) else {}

    def _wants_html(self) -> bool:
        """A browser navigating here (a form post) rather than a fetch."""
        return "text/html" in str(self.headers.get("Accept") or "")

    # Every route that names a page by number. `/api/page/7`, `/api/page/7/ocr`,
    # `/img/7`, `/render/7` - the number is always the first path segment after
    # the prefix.
    _NUMBERED = re.compile(r"/(?:api/page|img|render)/(\d+)(?:/.*)?")

    def _no_such_page(self, p, path: str) -> str:
        """"Page 121 is not there any more", or "" when it is.

        The browser holds a list of pages and the server holds another, and
        they come apart: a webtoon re-cut from 120 tiles into 66 pages, a page
        deleted, a project closed while its thumbnails were still arriving. The
        requests already in flight then ask for a page nobody has.

        Every one of those used to end the same way - `IndexError: list index
        out of range` in a toast, and a traceback in the console for each
        request still coming, which on a chapter is a screenful. It reads like
        the editor is broken. It is a page that has gone.

        So it is a 404 with a sentence in it. The browser already knows what to
        do with a page that is not there, and nobody has to read Python to find
        out which page it was.
        """
        m = self._NUMBERED.fullmatch(path)
        if not m:
            return ""
        i = int(m.group(1))
        if 0 <= i < len(p.pages):
            return ""
        if not p.pages:
            return "there are no pages open"
        return (f"page {i + 1} is not in this project any more "
                f"(there are {len(p.pages)})")

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
            gone = self._no_such_page(p, path)
            if gone:
                return self._json({"error": gone}, 404)
            if path in ("/", "/index.html"):
                return self._static("editor.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/project":
                return self._json(p.summary())
            if path == "/api/version":
                # What is running, for the header pill and for the launcher
                # that started it. One source: `version.py`.
                from . import version as _v
                return self._json({"version": _v.__version__,
                                   "channel": _v.CHANNEL,
                                   "support": _v.SUPPORT,
                                   **_update_state()})
            if path == "/api/diagnostics":
                return self._json(_diagnostics(p))
            if path == "/api/updates":
                # Settings > Updates. What the launcher knows, what the
                # channel has, and what is on its way. See `updates.py`.
                from . import updates
                return self._json(updates.state())
            if path == "/api/home":
                # The Home screen: who, what is open, what was opened before.
                from . import coins, version as _v
                return self._json({
                    "version": _v.__version__, "channel": _v.CHANNEL,
                    "account": coins.state(),
                    "current": _current_project(p),
                    "recent": userdata.recent_projects()})
            if path == "/api/account/hand":
                # The app asking whether the browser has handed the sign-in
                # over yet. `state` is the nonce it was given.
                from . import account
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                nonce = (q.get("state") or [""])[0]
                out = account.handoff_state(nonce)
                if out.get("done"):
                    from . import coins
                    out.update(coins.state())
                return self._json(out)
            if path == "/api/account":
                # Settings > Account, like the website's page: who, the
                # coins, the receipt, the picture. Never a token.
                from . import account, coins
                out = {"account": coins.state(), "icons": list(account.ICONS),
                       "ledger": [], "packs": {}}
                if account.signed_in():
                    try:
                        got = account.ledger(50)
                        out["ledger"] = got.get("rows") or []
                        out["packs"] = got.get("packs") or {}
                    except Exception as e:
                        out["ledger_problem"] = str(e)
                return self._json(out)
            if path == "/api/queue":
                return self._json({"ok": True, **queue_state()})

            if path == "/api/coins":
                # The purse, and what this chapter would cost at today's
                # models. The prices go with the balance in one answer because
                # they are read together - the panel shows both - and because
                # a price quoted from a different moment than the balance is
                # how a screen comes to say you can afford something you
                # cannot.
                from . import coins
                # `pages` picks a subset - the pages a scoped run would touch -
                # and `page` prices one on its own for "This page only".
                #
                # Priced HERE and not on the screen, both of them. A price is
                # whole coins rounded up once over the run, so it cannot be
                # assembled out of per-page numbers the screen adds together:
                # twenty-three pages rounded up one at a time is twenty-three
                # coins whatever is on them, which is the flat rate lee
                # explicitly did not want.
                t0 = time.time()
                idx = _page_list(p, q.get("pages", [""])[0], whole=True)
                one = _page_list(p, q.get("page", [""])[0])
                # Which steps are running a model nobody has priced. They
                # are charged at the dearest rate on the list, which is the
                # right fallback and an eightfold difference nobody would
                # guess from the number - so it is said out loud.
                unpriced = sorted(
                    s for s in PAID_STEPS if s != "clean"
                    and not coins.priced(*step_engine(p, s)))
                out = {
                    **coins.state(),
                    "prices": {s: quote_run(p, s, idx) for s in PAID_STEPS},
                    "one": {s: quote_run(p, s, one) for s in PAID_STEPS},
                    "unpriced": unpriced,
                    "models": {s: step_engine(p, s)[0] for s in PAID_STEPS
                               if s != "clean"},
                    "pages": len(idx),
                    "boxes": sum(page_boxes(p, i) for i in idx),
                }
                # How long the quote took, on the reply and in the log when
                # it is long: the run dialog waits on this for its prices,
                # and "the coins take a long time to show up" (lee) needs a
                # number before it can be chased.
                out["took_ms"] = int((time.time() - t0) * 1000)
                if out["took_ms"] > 800:
                    print("mangatl: coins quote took %d ms for %d pages"
                          % (out["took_ms"], len(idx)), flush=True)
                return self._json(out)

            if path == "/api/job":
                # The job's own error stops a run; a cleaner that refuses does
                # not - the run finishes, page after page, quietly worse. The
                # warning rides along with the job so the same bar says both.
                j = dict(p.job)
                # What the bar should say while the checkpoints are coming off
                # the disk. Not a page count: the run has not reached a page.
                if _models["running"]:
                    j["loading_model"] = _models["route"]
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
                    # breakage - lee, with a working token: *"its saying the ai
                    # did not run"*. It is a remark, so it goes with the remarks.
                    note = clean_note(p)
                    if note:
                        j["info"] = ((j.get("info", "") + " ") + note).strip()
                # The queue rides along with the job so the button on the bar
                # updates from the same poll the bar already makes.
                j["queue"] = queue_state()
                # ...and which RUN of the server this is. A browser tab opened
                # before a restart keeps executing the JavaScript it loaded
                # then - statics are no-store, but no header reaches into a
                # tab that never asks again. Three of today's fixes "did not
                # work" in exactly this way: the server was new, the tab was
                # old, and lee toggled a heal layer to flush by hand what the
                # new code would have flushed for him. The poll compares this
                # and reloads the page when it moves - see `poll()`.
                j["boot"] = _BOOT
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
                # Everything translated, as plain JSON - one entry per region
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
                # project file it shoud be excaty as it it now"* - so it
                # carries the pages, the boxes, both languages, the layouts,
                # the paint, the hand-cleaned plates, the custom box types and
                # the faces it typesets in, which live outside the project
                # folder and would otherwise be the one thing that did not
                # travel. See bundle.py.
                from . import bundle
                p.save()
                data = bundle.write(p._state(), p.output_dir,
                                    plates=_plates_to_carry(p))
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
                # app itself offers can be fetched - this is not a file reader.
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

            if path == "/marksample":
                # One mark, drawn the way the page will draw it, as a PNG.
                #
                # The picker cannot draw these itself: they are shapes in
                # `marks.py`, and a copy of them in JavaScript is the same
                # mistake as a copy of `DEFAULT_FONTS` there - two sets of
                # coordinates that agree until one is edited. So the picker
                # shows what the typesetter would actually stamp, from the
                # typesetter.
                #
                # Rendered against the CURRENT face, because that is what
                # decides whether a mark is drawn at all: Jua and Patrick Hand
                # have a heart of their own and keep it.
                ch = (q.get("c") or [""])[0]
                if not ch or ch not in typeset_mod.MARK_CHARS:
                    return self._send(404, b"no mark", "text/plain")
                png = _mark_sample_png(_typeset_cfg(p), ch)
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
                return self._json(fonts_answer())

            if path == "/api/translate_request":
                # THE EXACT REQUEST THE TRANSLATOR WOULD SEND, as a download,
                # so it can be run through any AI of the person's choosing.
                #
                # "Exact" is the whole promise, and for a long time it was not
                # true. This built its own region dicts out of the saved
                # records, beside `translate.build_payload` and drifting from
                # it, and lee's own 23-page export came back missing five
                # things the live run sends:
                #
                #   fits_chars   how much English that balloon holds - so a
                #                chapter translated this way was translated
                #                with nothing telling the model how long a line
                #                could be
                #   link         so a pair somebody had linked by hand arrived
                #                as two unrelated boxes
                #   previous_page_tail   hardcoded to [], so every page was
                #                translated with no memory of the one before it
                #   chapter_context, already_said, do_not_return
                #
                # There is one payload now and this asks for it. `build_payload`
                # is the only thing that decides what a request looks like, and
                # a divergence like the above cannot happen again without
                # changing the live run too.
                #
                # It costs a materialise per page - about three quarters of a
                # second - because `fits_chars` measures the BALLOON, and the
                # balloon's mask is not in the record. Reading it off
                # `bubble_bbox` instead was measured over 50 boxes and is wrong
                # by a median of five characters and by up to twenty on a
                # bubble: it would tell the model a balloon holds 48 where it
                # holds 28, which is worse than telling it nothing. This is a
                # button somebody presses once a chapter.
                from .translate import (build_payload, build_system,
                                        SCHEMA_HINT)
                # ...and the same settings the run itself reads. Setting three
                # fields by hand here is how `keep_honorifics`, the story
                # switches and the font sizes went missing from the file.
                _ctx_from_settings(p, "translate")
                ctx = p.ctx
                idxs = range(len(p.pages))
                if q.get("pages"):
                    idxs = [int(v) for v in q["pages"][0].split(",")
                            if v.strip().isdigit() and int(v) < len(p.pages)]
                idxs = list(idxs)
                chapter = run_context(p, idxs)
                pages = []
                for i in idxs:
                    # What was said on the page before, built the way
                    # `do_translate` builds it. On an untranslated chapter this
                    # is empty for every page, which is honest; on one being
                    # picked up again it is the continuity the live run has.
                    ctx.previous_page_tail = _page_tail(p, i - 1)
                    req = build_payload(p.materialize(i), ctx, chapter)
                    if not req["regions"]:
                        continue
                    pages.append({"page_index": i, "page_name": p.pages[i].name,
                                  "request": req, "response": None})
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
                    # which of them are put away - the switches in the Current
                    # page card are built from exactly these two lists
                    "kinds": p.pages[i].groups_present,
                    "hidden": list(getattr(p.pages[i], "hidden_kinds", []) or []),
                    # The boxes put away one at a time. They are NOT in
                    # `regions` - a hidden box takes no part in the page's work
                    # - but the list has to be able to show a closed eye you
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
                    # ...and one for the FINISHED page, which is a different
                    # picture and a different question. The key above is asked
                    # with no mode, so it says nothing about the font, the
                    # size or the colours - right for the clean plate, which
                    # they cannot change, and wrong for the view that shows
                    # the typesetting: hang that on `vkey` and a change of
                    # font leaves the browser reusing the picture from before
                    # it. See `_render_stamp`, which adds the typesetting
                    # settings for this mode and no other.
                    "tkey": _render_key(p, i, "typeset"),
                    # …and the same for the untouched scan, which cleaning and
                    # typesetting cannot change. Hanging the render key on it too
                    # threw the original out of the browser's cache every time
                    # a page was cleaned, so the side-by-side pane re-downloaded
                    # a whole scan on every page turn and held the editing pane
                    # back while it did.
                    "ikey": _scan_key(p, i),
                })

            # The page's CURRENT picture keys, and nothing else - cheap, no
            # build. The export preview asks this before every settle, because
            # the key it was handed at page load goes stale the moment
            # anything is edited: the URL is served as immutable, so a stale
            # key is not a wrong answer from the server, it is the browser
            # re-showing its old copy WITHOUT ASKING. lee, after a paint fix
            # and a nudge: *"wheni move something in the live view it dont
            # update inteh exported view"* - and the "differences" he was
            # comparing against the live view were all his own edits, frozen
            # at the moment the page was opened.
            m = re.fullmatch(r"/api/page/(\d+)/keys", path)
            if m:
                i = int(m.group(1))
                return self._json({"vkey": _render_key(p, i),
                                   "tkey": _render_key(p, i, "typeset")})

            # Where the artist drew nothing on this page. The splitter's line
            # snaps to these, because a row picked by eye off a preview a tenth
            # of the size is a row picked to the nearest thirty pixels.
            m = re.fullmatch(r"/api/page/(\d+)/gaps", path)
            if m:
                i = int(m.group(1))
                return self._json({"gaps": p.gaps_in(i),
                                   "height": p.pages[i].height,
                                   # The picture's own fingerprint, so the
                                   # dialog can name the file it is about to
                                   # show. Without it the preview asked for
                                   # `/img/3` - the same string every time -
                                   # and an <img> already holding that src does
                                   # not re-request when it is set to what it
                                   # already says. Cut a page, open the dialog
                                   # on the half, and you were looking at the
                                   # WHOLE page again. lee: *"its still showing
                                   # the previous uncut picure after i cut
                                   # it"*.
                                   "key": _scan_key(p, i),
                                   # Boxes come through a cut now; pictures
                                   # the size of the page do not. So "busy"
                                   # means PAINTED, and nothing else stops it.
                                   "busy": Project._painted(p.pages[i])})

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
                # `ro=1`: draw it, do not write it down. The editor's exact
                # view asks for the finished page on its own initiative and
                # must not lay the page out again while somebody is editing
                # it - see `render_index`.
                ro = q.get("ro", ["0"])[0] == "1"
                # ...and while this is in flight the warm-up stands aside. See
                # `_someone_is_looking`.
                with _someone_is_looking():
                    out = render_index(p, i, mode, paint=paint, commit=not ro)
                return self._send(200, out, "image/jpeg",
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
            gone = self._no_such_page(p, path)
            if gone:
                return self._json({"error": gone}, 404)
            if path == "/api/project_upload":
                # A project file the BROWSER hands over, for when the machine
                # cannot show a file dialog - a headless install, or the
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

            if path == "/api/account/hand":
                # The browser handing a sign-in to the app - see
                # `account.finish_handoff`. This is the one route a page that
                # is not the editor's own may post to, so it is the one that
                # checks who is posting: the nonce, and the Origin header the
                # browser sets on a cross-site post. The body is a form (a
                # top-level post from the site's sign-in page), or JSON when
                # a test speaks it.
                from . import account
                form = self._form_or_json()
                try:
                    got = account.finish_handoff(
                        str(form.get("state") or ""),
                        str(form.get("refreshToken") or ""),
                        str(form.get("idToken") or ""),
                        str(form.get("uid") or ""),
                        str(form.get("email") or ""),
                        origin=str(self.headers.get("Origin") or ""))
                except account.AccountError as e:
                    if self._wants_html():
                        return self._send(400, _handed_page(str(e), False).encode("utf8"),
                                          "text/html; charset=utf-8")
                    return self._json({"error": str(e), "code": e.code}, 400)
                who = account.who()
                if self._wants_html():
                    name = who.get("username") or who.get("email") or "you"
                    return self._send(200, _handed_page(name, True).encode("utf8"),
                                      "text/html; charset=utf-8")
                from . import coins
                return self._json({"ok": True, **coins.state()})

            body = self._body()

            if path == "/api/warm":
                # The browser says which page is on screen so the warm-up
                # builds outwards from there - the next page you are going to
                # ask for is the next one it makes.
                try:
                    start = int(body.get("from") or 0)
                except (TypeError, ValueError):
                    start = 0
                start = max(0, min(start, len(p.pages) - 1)) if p.pages else 0
                if not _warm["running"] or body.get("force"):
                    warm_pages(p, start)
                return self._json({"ok": True, "total": len(p.pages)})

            if path == "/api/models/warm":
                # LOAD THE CHECKPOINTS WHEN THE CARD IS PICKED.
                #
                # They used to load on whichever page happened to be first, in
                # the middle of a bar reading "1 of 30". lee timed that three
                # times and read it as a fifty-second page: DB++/COO is 54.28s
                # on page one of a fresh process and 9.63s by page three.
                #
                # In a thread, because picking a card must not block on a
                # 116MB read, and it answers straight away so the settings
                # page never waits for it either.
                warm_models(p)
                return self._json({"ok": True, "route": p.route_name(),
                                   "loading": bool(_models["running"])})

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
                # The filled-in template back. TXT or JSON, whichever it is -
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
                        # wording) - styling survives. Same rule as a
                        # hand-written translation file coming in.
                        set_translation(r, item.get("translation"))
                        if item.get("speaker") is not None:
                            r["speaker"] = str(item["speaker"])
                        # Only judge confidence when the AI actually gave one -
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
                        # Held back until every page in the upload has landed -
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
                        # snap a loose spelling of a known person back first -
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
                # what shows - no stale typesetting left behind.
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
                # looked at the artwork - through balloons, through faces and
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
                # NOTHING RUNNING WHEN THE PAGES GO. `clear()` empties the
                # page list, and a job already walking it holds an index into
                # the list it is emptying - so the next page it reaches raises
                # `IndexError: list index out of range` out of a worker
                # thread. The person sees a run that stops with no reason
                # given, and the queue is left saying nothing finished.
                #
                # Found from a test that only fails when another test has run
                # first: an export was still going when the reset landed. That
                # is a real order too - Export, then New project without
                # waiting - and it is the app's job to survive it, not the
                # person's job to wait.
                _quiet_the_queue(p)
                keep = dict(p.settings) if body.get("keep_settings") else None
                # The SERIES CONTENT always clears on a new project - the
                # synopsis, character names, glossary and custom bubble types
                # belong to the story just finished. The technical translation
                # config (backend, model, target, honorifics) carries over so
                # the next chapter does not have to be reconfigured. Export
                # first to keep a series' content for its next chapter.
                old = p.ctx
                p.settings.pop("exported", None)     # a new chapter has not
                # `clear()` forgets the PAGES; the FILES are a different thing.
                # Every chapter uploads into the same `input/` folder and until
                # this line nothing ever emptied it, so the next chapter landed
                # on top of the last one and anything that listed the folder
                # afterwards called every file in it a page. lee: *"soem pages
                # that wrere not i the folder are showing uo when i upload teh
                # foler"*.
                p.put_the_last_chapter_away()
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
                # A NEW CHAPTER IS A NEW CHAPTER, even in the same folder.
                # lee: *"unsettion page in a project and sarting a new
                # project, the same pages are automaticaly unselcetd , that
                # hsoud not happen"*. The browser remembers page ticks per
                # chapter, every chapter here lives in one folder, and his
                # new chapter's pages carry the same names as the old ones -
                # so the old deselections claimed them. AFTER the
                # keep_settings copy, which would put the old id straight
                # back.
                import uuid as _uuid
                p.settings["chapter_id"] = _uuid.uuid4().hex[:12]
                p.save()
                return self._json({"ok": True})

            if path == "/api/font":
                # Adding, removing, or saying which face was just reached for.
                # All three answer with the same thing - the whole font list -
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
                return self._json(dict(fonts_answer(),
                                       ok=not err, error=err))

            if path == "/api/models":
                # The names this key can actually use, asked of the provider.
                # Typing a model name by hand is how a chapter dies halfway
                # through with a 404 - providers retire models, and there is
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
                    # Priced AND reachable - the crossing is the whole point,
                    # and `model_menu` is where it is explained. Offering only
                    # the priced list is what put `gemini-2.5-flash` in front
                    # of lee on a project it was not enabled for.
                    from . import coins
                    # What the person's OWN keys can already reach, for the
                    # OpenRouter rule. Cached and never asked for without a
                    # key, so on a project with one service configured this
                    # costs nothing.
                    elsewhere = []
                    if back == "openrouter":
                        for svc, _label in SERVICES:
                            if svc == "openrouter":
                                continue
                            k = key_for(p, svc, step)
                            if k:
                                elsewhere += _reachable(svc, "", k)
                    names = model_menu(back, url, key_for(p, back, step), step,
                                       elsewhere)
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
                # One real call, cache bypassed, with the answer in words -
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
                    # this route imposes - the security rules forbid a client
                    # writing a balance at all - and saying so here is only
                    # saying it before the round trip.
                    return self._json({"error": "Coins are bought on the "
                                       "website. Open Buy coins."}, 400)
                coins.credit(add, str(body.get("what") or "top-up"))
                return self._json({"ok": True, **coins.state()})

            if path == "/api/account":
                # Signing in, from the editor. The password goes to Google and
                # nowhere else - it is not stored, not logged, and not put in
                # the project file. What comes back and is kept is a refresh
                # token, in the person's own folder, 0600.
                from . import account
                do = str(body.get("do") or "")
                try:
                    if do == "google":
                        # lee: *"sign in / sign up and login with google
                        # like in the website"*. The website's page, in the
                        # system browser, marked for this app; the page
                        # hands the sign-in back to `/api/account/hand`.
                        port = int(self.server.server_address[1])
                        got = account.begin_handoff(port, bool(body.get("making")))
                        if body.get("open", True):
                            threading.Thread(target=webbrowser.open,
                                             args=(got["url"],), daemon=True).start()
                        return self._json({"ok": True, **got})
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
                    elif do == "verify":
                        # The verification mail again. The hundred free coins
                        # wait on it - see `welcomeIfDue` in the functions.
                        account.send_verification()
                    elif do == "claim":
                        # "I clicked the link": a fresh token, and the server
                        # gives the coins on the same call if it is so.
                        account.claim_welcome()
                    elif do == "photo":
                        account.set_photo(str(body.get("photo") or ""))
                    else:
                        return self._json({"error": "do what?"}, 400)
                except account.AccountError as e:
                    return self._json({"error": str(e), "code": e.code}, 400)
                from . import coins
                return self._json({"ok": True, **coins.state()})

            if path == "/api/home":
                do = str(body.get("do") or "")
                if do == "forget":
                    return self._json({"ok": True,
                                       "recent": userdata.forget_project(str(body.get("path") or ""))})
                return self._json({"error": "do what?"}, 400)

            if path == "/api/updates":
                # Check now / Download / the automatic switch / Restart now /
                # Get the new setup. Everything long-running goes to a
                # thread and GET /api/updates watches it.
                from . import updates
                do = str(body.get("do") or "")
                if do == "check":
                    return self._json(updates.check(force=bool(body.get("force"))))
                if do == "auto":
                    return self._json(updates.set_auto(bool(body.get("on"))))
                if do == "restart":
                    return self._json(updates.restart())
                if do == "install":
                    return self._json(updates.install_setup())
                return self._json({"error": "do what?"}, 400)

            if path == "/api/settings":
                new = body.get("settings") or {}
                # A token pasted out of a file or a browser comes with whatever
                # the copy picked up - a trailing newline, a leading space, the
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
                # Built from the step and service lists rather than typed
                # out. The typed-out version was wrong the day a fourth AI
                # step existed: `find_key` was not in it, so that one key
                # alone kept its trailing newline.
                for k in (list(project_mod.secret_keys())
                          + ["clean_url", "base_url"]
                          + [f"{st}_base_url" for st in AI_STEPS]):
                    if isinstance(new.get(k), str):
                        new[k] = new[k].strip().strip('"').strip("'").strip()
                # ...and the mask is not a secret. It goes OUT in the same
                # field the key lives in, so anything that hands a whole
                # settings object back -- a .tct import, a restored snapshot,
                # a script -- would save the word "set" over a working key.
                # lee: *"the key it has ends set"*. It did.
                masked = project_mod.drop_masked_secrets(new)
                if masked:
                    print("mangatl: ignoring masked value for "
                          + ", ".join(masked), flush=True)
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
                    # translation reply, which only fills gaps) - the human
                    # editing it is the authority.
                    p.ctx.characters = {
                        str(k).strip(): str(v).strip()
                        for k, v in (body["characters"] or {}).items()
                        if str(k).strip()}
                p.save()
                safe = dict(p.settings)
                safe["api_key"] = project_mod.MASK if safe.get("api_key") else ""
                for k in AI_STEPS:                    # per-step keys, masked
                    safe[f"{k}_key"] = (project_mod.MASK
                                        if safe.get(f"{k}_key") else "")
                for svc, _label in SERVICES:          # service keys, masked
                    safe[f"key_{svc}"] = (project_mod.MASK
                                          if safe.get(f"key_{svc}") else "")
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
                # Absent is ON: the browser sends it, and anything that
                # does not know about it gets the run lee measured.
                nobig = body.get("no_big_sfx") is not False
                run_job(p, "Detecting", idx,
                        lambda i: p.detect(i, kinds, nobig), warm=True)
                return self._json({"started": len(idx)})

            if path == "/api/ocr_all":
                idx = body.get("pages") or list(range(len(p.pages)))
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts - the price is taken when
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
                # The other brush stood here - a local fill that copied real
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

            # Cutting a page up, by hand, at the rows the person picked.
            # lee: *"add page splitter that allow the user to splite the pages
            # manualy"*, then *"can you make it so that i can have multiple
            # cut lines"*. The automatic re-cut is deliberately narrow - a
            # sliced strip, untouched, and sure - and this is the way through
            # for every long page that is none of those things.
            m = re.fullmatch(r"/api/page/(\d+)/split", path)
            if m:
                i = int(m.group(1))
                # ONE ROW OR MANY. `at` is still accepted on its own, because
                # a caller from before this sends one number and there is no
                # reason to break it; `ats` is the list.
                at = body.get("ats")
                if at is None:
                    at = int(body.get("at") or 0)
                else:
                    try:
                        at = [int(a) for a in at]
                    except (TypeError, ValueError):
                        return self._json(
                            {"error": "the cut rows have to be whole "
                                      "numbers"}, 400)
                ok, why = p.split_page(i, at)
                if not ok:
                    return self._json({"error": why}, 400)
                # Everything here is filed by page index, and every index from
                # this one down has just moved.
                _page_cache.clear()
                _invalidate_renders()
                _plate_cache.clear()
                return self._json({"ok": True, "pages": len(p.pages),
                                   "index": i})

            # ...and putting two back together. lee: *"also add a page mergin
            # feature"*.
            m = re.fullmatch(r"/api/page/(\d+)/merge", path)
            if m:
                i = int(m.group(1))
                ok, why = p.merge_pages(i, int(body.get("count") or 2))
                if not ok:
                    return self._json({"error": why}, 400)
                _page_cache.clear()
                _invalidate_renders()
                _plate_cache.clear()
                return self._json({"ok": True, "pages": len(p.pages),
                                   "index": i})

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
            # that block's typesetting - cropped to what it actually covers -
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
                # carries no layout - every stage re-fits - so a page taken
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
                # browser learnt to wait for its layers to decode - and a save
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
                    # It was never cleaned - it was excluded. Going back to
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
                if imgio.imread(dest) is None:
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
                seed_sounds(p)
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts - the price is taken when
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
                # cannot be paid for never starts - the price is taken when
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
                # plate - opening a page, typesetting, exporting - still reuses.
                #
                # A page with its own cleaned file stays in the list and is
                # skipped by `do_clean` - it costs one dictionary lookup and is
                # reported at the end as left alone. Filtering it out here
                # instead would drop it before `_run_one` clears the tally, and
                # the report would never mention it.
                own = sum(1 for k in idx if own_plate_path(p, k))
                # A step with no key cannot run at all, and a run that
                # cannot be paid for never starts - the price is taken when
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
                # than a path typed into a box - and a browser cannot offer one
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
                    data = bundle.write(p._state(), p.output_dir,
                                        plates=_plates_to_carry(p))
                    tmp = dest + ".part"
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                    os.replace(tmp, dest)
                except OSError as e:
                    return self._json({"error": f"could not write it: {e}"}, 500)
                # Remembered so Save has somewhere to go next time.
                p.settings["project_file"] = dest
                p.save_soon()
                userdata.note_project(dest, len(p.pages), p.settings.get("medium") or "")
                return self._json({"path": dest, "bytes": len(data)})

            if path == "/api/project_open":
                # Opening one REPLACES what is open, the way starting a new
                # chapter does. Anything half-done in the folder goes with it,
                # which is why the file is checked for being a project before
                # a single thing is deleted - see `bundle.read`.
                from . import bundle
                src = str(body.get("path") or "").strip()
                if not src or not os.path.isfile(src):
                    return self._json({"error": "no such file"}, 400)
                try:
                    with open(src, "rb") as fh:
                        state = bundle.read(fh.read(), p.output_dir)
                except (OSError, ValueError) as e:
                    return self._json({"error": str(e)}, 400)
                got = _adopt(p, state, src)
                userdata.note_project(src, len(p.pages), p.settings.get("medium") or "")
                return self._json(got)

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
                    # groups it moved - see PageState.hide_group.
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
                # for nothing - it is a place on the page where you want words
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
                # A sound effect is drawn along an axis of its own, and the
                # English has to be set along the same one. `read_sfx_axis` is
                # what reads it, and it ran at detection and when a box was
                # RE-TYPED to sfx - never when a box ARRIVES as one, which is
                # every box the Add-sound-effect tool puts down. Those reached
                # the typesetter with `sfx_len` unset, took its "never
                # measured" branch, and were set dead straight across the box.
                # lee, on a leaning `티리스~`: *"i wnat you to have it also
                # check fro the thext dircetion and copy that too"*.
                #
                # Read HERE, at the moment the box is drawn, for the reason
                # detection reads it there: this is while the page still
                # carries the Korean. By typeset time the effect is painted out
                # and there is no angle left to take.
                if _kinds.family_of(getattr(r, "kind", "")) == "sfx":
                    try:
                        _g = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                              if img.ndim == 3 else img)
                        read_sfx_axis(r, _g)
                    except Exception:
                        pass      # straight is a worse answer, not a broken one
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
                    # pass - seconds of nothing while a box you drew waits to
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
                        # be pushed away from - it is words you asked for, on
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
                # A box you just drew is not one you have put away.
                #
                # `active` - which is what the reply carries and what the
                # client draws - leaves out every box whose GROUP is hidden. So
                # drawing a sound effect on a page whose sound effects are put
                # away appended the record, answered without it, and the box
                # was simply not there. Nothing said so; the group switch is in
                # another panel, and on these formats the detector makes no
                # sound effects at all, so the group is routinely away and the
                # only boxes in it are the ones drawn by hand. lee: *"i create
                # a sfx but its visulay not there an i have to clcik trhe sfx
                # button a lot for it to show up visulay"* - that button is the
                # group switch, and clicking it is what brought the box back.
                #
                # Drawing a box is as plain a statement as there is that you
                # want to see it, so it wins over a switch set earlier: the
                # group comes back out, on this page.
                if not p.pages[i].shown(rec):
                    g = group_of(rec.get("kind") or "")
                    if g:
                        p.pages[i].hidden_kinds = [
                            k for k in (p.pages[i].hidden_kinds or [])
                            if k != g]
                    invalidate_page(i)
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
            # held before the delete - text, shape, polygon, typesetting, link -
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
                # this box had is still its own - unless the record came from
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

            # ONE BOX, ONE COIN. Re-read the writing in a single box from
            # the image, or translate a single box's line - each sends that
            # box and nothing else. lee: *"add a read text and traslate
            # buuton to each box and it shoud jut send that box and text
            # with no extra context to the ai and make it cost 1 coin"*.
            #
            # The read uses WHATEVER READER THE PROJECT USES for its main
            # Read text step - the AI reader when the project reads with the
            # AI, the offline reader only when that is the engine. lee: *"it
            # should use teh ai if teh use had teh ai for the main read etxt
            # and not teh ocr"*.
            m = re.fullmatch(r"/api/page/(\d+)/region/(\d+)/(read|translate)",
                             path)
            if m:
                i, rid = int(m.group(1)), int(m.group(2))
                what = m.group(3)
                from . import coins
                # A read that happens on this computer is not bought from
                # anybody - the same rule `run_price` applies to the chapter
                # buttons, said here so one box costs what the same box
                # would inside a run. The button shows no coin for it either.
                paid = (what == "translate") or not reading_offline(p)
                if paid and not coins.can_afford(1):
                    return self._json(
                        {"error": "Not enough coins — this costs 1."}, 402)
                page = p.materialize(i)
                region = next((q for q in page.regions if q.id == rid), None)
                if region is None:
                    return self._json({"error": "no such region"}, 404)
                import copy as _copy
                sub = _copy.copy(page)
                sub.regions = [region]
                try:
                    if what == "read":
                        # The button IS the hand correction, so the lock that
                        # keeps a chapter-wide re-read off a fixed line does
                        # not apply to the line whose button was pressed.
                        was_locked = bool(getattr(region, "locked", False))
                        region.locked = False
                        try:
                            if reading_offline(p):
                                _read_here(p, sub, lambda _m: None)
                            else:
                                from .ocr import (detail_for,
                                                  page_label_tiles,
                                                  looks_like_garbage)
                                from .translate import read_page_ocr
                                _read_with_ai(p, i, sub, lambda _m: None,
                                              detail_for, page_label_tiles,
                                              looks_like_garbage,
                                              read_page_ocr)
                        finally:
                            region.locked = was_locked
                    else:
                        from .translate import (translate_page,
                                                SeriesContext)
                        _ctx_from_settings(p, "translate")
                        c0 = p.ctx
                        # The box and its text, nothing else: the model
                        # settings ride along, the story does not.
                        bare = SeriesContext(
                            medium=c0.medium, target=c0.target,
                            source=getattr(c0, "source", "") or "",
                            honorifics=getattr(c0, "honorifics", True),
                            min_font=c0.min_font, max_font=c0.max_font,
                            backend=c0.backend, base_url=c0.base_url,
                            model=c0.model, api_key=c0.api_key,
                            safety=getattr(c0, "safety", "") or "",
                            step_name=getattr(c0, "step_name", "") or "",
                            story=False, learn_characters=False,
                            learn_terms=False, name_speakers=False)
                        if not (region.src_text or "").strip():
                            return self._json(
                                {"error": "Nothing to translate — this box "
                                          "has no text read in it."}, 400)
                        translate_page(sub, ctx=bare)
                except Exception as e:
                    return self._json({"error": str(e)}, 502)
                if paid:
                    coins.spend(1, f"{what} one box", page=p.pages[i].name,
                                run=coins.new_run())
                p.commit(i, page)
                rec = next((q for q in p.pages[i].regions
                            if q["id"] == rid), None)
                if what == "translate" and rec is not None:
                    # New words: the old fitting was computed FOR the previous
                    # wording - same drop the hand-typed edit makes.
                    rec.pop("proofread", None)
                    rec.pop("proofread_was", None)
                    keep = None
                    if rec.get("own_text"):
                        keep = list((rec.get("layout") or {}).get("frame")
                                    or []) or None
                    rec["layout"] = ({"lines": [], "frame": keep,
                                      "font_size": (rec.get("layout") or {})
                                      .get("font_size"),
                                      "leading": (rec.get("layout") or {})
                                      .get("leading")} if keep else None)
                    ov = dict(rec.get("layout_override") or {})
                    for key in ("lines", "fit", "wrap", "snug"):
                        ov.pop(key, None)
                    rec["layout_override"] = ov or None
                _page_cache.clear()
                p.save_soon()
                return self._json({"regions": p.pages[i].active,
                                   "coins": coins.balance()})

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
                             "draw_box", "link", "box_group", "angle",
                             "turn")}
                    new = region_record(nr)
                    new.update({k: v for k, v in keep.items() if v})
                    if not body.get("snap", True):
                        # an explicit manual box becomes the new reference
                        new["draw_box"] = [int(v) for v in bb]
                    # Dragging a turned box's corner resizes it; it does not
                    # straighten it. Its outline is DERIVED from the rectangle,
                    # so it has to be derived again from the new one, or the box
                    # would spring back upright the moment it was touched.
                    if is_turned(new):
                        new["polygon"] = turned_box(new["bbox"], new["turn"])
                    recs[recs.index(rec)] = new
                    rec = new
                elif body.get("polygon") is not None:
                    # `"polygon" in body` was the test, and a caller sending
                    # `{"polygon": null}` to CLEAR one landed in here and tried
                    # to iterate None. Merging boxes did exactly that. Null
                    # means "this box has no polygon", which is the state a
                    # plain rectangle is already in, so there is nothing to do
                    # and nothing to fail at.
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
                    #
                    # A body carrying BOTH the words and the layout is a caller
                    # that has already decided the fitting - the special-
                    # characters picker appends ♥ to the text AND to the line
                    # it sits on. Sent as two saves they raced: the text edit
                    # drops the fitting (the `else` branch below), and when its
                    # drop landed second it popped the very line the ♥ was on,
                    # so the mark reached the output text and never the page.
                    # Taken here, together, the fitting drop never runs and
                    # the lines in this same body are the fitting.
                    if "dst_text" in body:
                        rec["dst_text"] = str(body["dst_text"] or "")
                        rec.pop("proofread", None)
                        rec.pop("proofread_was", None)
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
                            # which SHAPE the line bends along - see
                            # `render.arc_places`. Arch is the original
                            # circle; Sag is the panel's word for a
                            # negative arch, so it is not a stored kind.
                            "curve_kind": (str(lay.get("curve_kind")
                                               or "arch")
                                           if str(lay.get("curve_kind")
                                                  or "arch")
                                           in ("arch", "wave", "rise")
                                           else "arch"),
                            "glow": str(lay.get("glow") or ""),
                            "glow_size": float(lay.get("glow_size") or 6),
                            "iglow": str(lay.get("iglow") or ""),
                            "iglow_size": float(lay.get("iglow_size") or 5),
                            # 100 is "no transparency", and it has to survive
                            # being sent as 0 - hence the explicit test rather
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
                            # setting - a caption ranged left, or one shout in
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
                            # Part of the text, styled by itself - Photoshop
                            # fashion. Character ranges with their own
                            # paint-only style, drawn by `render._ink_layer`
                            # per distinct style through per-run masks.
                            # lee: *"allow teh user to modify spesifuica
                            # part of a text box"*.
                            "spans": _clean_spans(lay.get("spans")),
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
                        # real one - store it, or the old height comes back.
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
                    # Typeset - which deliberately throws hand corrections
                    # away and fits from `dst_text` - put the old typesetting
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
                        rec.pop("proofread_was", None)
                        # ...and the frame it was left at, which is what makes
                        # it the same box afterwards.
                        if len(was_frame) == 4 and not ov_now.get("frame"):
                            ov_now["frame"] = [int(v) for v in was_frame]
                            rec["layout"] = layout_preview(p, i, rid, ov_now)
                    # A text box somebody put on the page themselves has TWO
                    # rectangles: the region, drawn once and never moved again,
                    # and the typesetting frame, which is what the handles
                    # actually drag. On every other box they mean different
                    # things - the region is where the Japanese was, the frame
                    # is where the English goes - but on this one there is no
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
                        # SOMEBODY CHOSE THIS. The proofreader labels box types
                        # now, and lee asked that it *"shoud not"* touch one a
                        # person has set - a type you fixed by hand coming back
                        # wrong on every re-run is worse than no labelling at
                        # all. This endpoint is the only place a person can
                        # change a kind, so it is the only place that has to
                        # say so. See `translate.label_kinds`.
                        rec["kind_by_hand"] = True
                        _kind_changed(rec, was_kind)
                        _page_cache.clear()
                    if "angle" in body:
                        # Correcting the reading by hand: a straight effect the
                        # reader leaned, or a lean it refused to commit to.
                        rec["angle"] = max(-89.0, min(
                            89.0, float(body.get("angle") or 0.0)))
                        rec["sfx_len"] = rec.get("sfx_len") or 1.0
                        rec["sfx_wid"] = rec.get("sfx_wid") or 1.0
                        # SOMEBODY CHOSE THIS TOO, and the reading must leave
                        # it alone from here on - the same rule as the type
                        # above, arrived at the same way. See
                        # `editor._apply_read_angles`.
                        rec["angle_by_hand"] = True
                    if "turn" in body:
                        # TURNING a box, which is a different thing from the
                        # angle above and has its own field for that reason:
                        # `angle` is a reading of the artwork and this is a
                        # decision about the box, and a hand-drawn sound effect
                        # has both.
                        #
                        # lee: *"alow me to rotate boxes, only teh ser shoud be
                        # able to rotate them the detector boxes shoud be
                        # normal"*. A detected box's outline came off the
                        # artwork; turning it would be turning the drawing.
                        # EVERY box, not only one somebody drew: lee asked
                        # first for the opposite and then for this --
                        # *"alowm me to be able to rotate every box"*.
                        was_turn = float(rec.get("turn") or 0.0)
                        rec["turn"] = max(-89.0, min(
                            89.0, float(body.get("turn") or 0.0)))
                        # The turn is also stored as GEOMETRY, which is what
                        # makes the rest of the app follow it without being
                        # told: `_is_a_box` answers False for a tilted
                        # rectangle, so the region loads with a real placement
                        # area, and that area is what the fitter sets text into.
                        # `draw_box` keeps the upright original, so the turn can
                        # always be taken back.
                        rec["polygon"] = turned_box(rec["bbox"], rec["turn"])
                        if _kinds.family_of(rec.get("kind") or "") == "sfx":
                            # A sound effect's letters run along an axis of its
                            # own rather than in a block, so the way to turn
                            # them WITH the box - lee chose "the box and the
                            # text together" - is to turn that axis by as much.
                            rec["angle"] = max(-89.0, min(89.0, float(
                                rec.get("angle") or 0.0) + rec["turn"] - was_turn))
                        # No `invalidate_page` here: `reorder` at the end of
                        # this endpoint drops the cached page for anything but
                        # a layout-only edit, and a turn is not one.
                    # ...and not when an angle came WITH the change: that is a
                    # correction by hand, and reading the axis would undo it.
                    if "angle" not in body \
                            and _kinds.family_of(rec.get("kind") or "") == "sfx" \
                            and _kinds.family_of(was_kind or "") != "sfx" \
                            and not rec.get("sfx_len"):
                        # Calling a box a sound effect is the moment to read
                        # its angle - and the page still has the Japanese on
                        # it, which by typeset time it will not.
                        #
                        # THE FAMILY. This compared the strings until Read text
                        # began labelling sub-types: picking "Big / impact" off
                        # the menu made a box a sound effect without ever
                        # equalling "sfx", so its axis was never read and the
                        # effect was typeset straight when the artist had drawn
                        # it leaning.
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
                        # ...and the proofreader's before-and-after with it:
                        # a "was" under a line somebody has since retyped is
                        # a comparison against nothing.
                        rec.pop("proofread_was", None)
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
                        # replaced - lee: *"make sure that all the etxt are
                        # sync so if i chnage the text in one spot everywhere
                        # else that text is ghsoukd chnage"*. Proofreading has
                        # always done this when IT changed a line; an edit by
                        # hand is the same event.
                        #
                        # Only the fitting is dropped. Everything the person
                        # chose about how it looks - colour, outline, glow,
                        # rotation - is dressing and survives.
                        #
                        # ...and on a box you drew yourself, so does the BOX.
                        # A bubble's frame is derived - the fitter reads it off
                        # the balloon - so throwing it away costs nothing and
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
                # right - and rebuilding it is what made the first press after
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

        gone = self._no_such_page(p, path)
        if gone:
            return self._json({"error": gone}, 404)

        m = re.fullmatch(r"/api/page/(\d+)", path)
        if m:
            ok = p.remove_page(int(m.group(1)))
            return self._json({"ok": ok, "pages": len(p.pages)})

        m = re.fullmatch(r"/api/page/(\d+)/region/(\d+)", path)
        if not m:
            return self._send(404, b"not found", "text/plain")
        i, rid = int(m.group(1)), int(m.group(2))
        # The number goes on the record before the box carrying it goes, or
        # the next box drawn is handed it again. See `Page.note_ids`.
        p.pages[i].remember_ids()
        p.pages[i].regions = [r for r in p.pages[i].regions if r["id"] != rid]
        reorder(p, i)
        p.save_soon()
        return self._json({"regions": p.pages[i].active})


def reorder(p: Project, i: int, stale: bool = True) -> None:
    """Keep reading order sane after the region set changes.

    `stale=False` says the GEOMETRY did not move - a colour, a font, a line
    gap, capitals. The cached page is built from masks and a cleaned plate,
    and neither depends on any of that, so dropping it made the next keystroke
    rebuild the whole page: materialize, find the balloons, clean the plate.
    That is the seconds-long pause on the first press after a save - lee: *"the
    letter gap take a long time to work the first time"*.

    Every add, delete, move and resize passes through here, so it is also the
    right place to drop the cached page whose masks just went stale.

    Order is STICKY: when every region already has an order (including one a
    human just set by hand), it is only compacted - moving or editing a
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
    # order inside panels). Fall back to a blank canvas if it can't be loaded -
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
        # The page already has an order - quite possibly one a human arranged
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
# shows only these (plus everything bundled in ./fonts) by default - a
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


def _squash(s: str) -> str:
    """A name with everything but its letters and digits taken out.

    `Dela Gothic One` and `DelaGothicOne-Regular` are the same family spelled
    the two ways this app has to deal with: a family is what somebody
    downloads and a file is what lands on the disk. Comparing them needs both
    sides flattened, and the hint list below is matched with the separators
    still in, so the two cannot share one normalisation.
    """
    return "".join(c for c in str(s or "").lower() if c.isalnum())


@functools.lru_cache(maxsize=1)
def _recommended_families() -> tuple:
    """Every family the Recommended fonts page names, flattened.

    THE PICKER MUST NOT HIDE WHAT THE APP JUST TOLD SOMEBODY TO DOWNLOAD.
    That is what it was doing: `fontpicks` sends you to Google Fonts for Dela
    Gothic One, Titan One, Caveat, Klee One, Bebas Neue and a dozen more, and
    not one of those names is in `_COMIC_HINTS` - so a face downloaded on the
    app's own advice, installed, and then looked for in the Box types picker
    was not there. lee: *"no add teh otehr fonst in teh fonts picker list in
    teh app"*.

    Read off `fontpicks.PICKS` rather than copied into the list above,
    because these are the same fact - "this app thinks this face is worth
    typesetting with" - and a second copy is the next thing to fall out of
    step. Adding a recommendation now adds it to the picker.
    """
    try:
        from . import fontpicks
    except Exception:
        return ()
    return tuple({_squash(p.family) for picks in fontpicks.PICKS.values()
                  for p in picks if len(_squash(p.family)) >= 4})


def _is_comic_font(name: str) -> bool:
    n = name.lower().replace("-", " ").replace("_", " ")
    # Comicraft's catalogue is all CC-prefixed (CC Wild Words, CC Astro City…)
    if n.startswith("cc") or any(k in n for k in _COMIC_HINTS):
        return True
    # ...and anything the app itself recommends. Matched on the flattened name
    # so `DelaGothicOne-Regular` finds `Dela Gothic One`; four characters is
    # the floor, so a three-letter family cannot sweep in half a font folder.
    flat = _squash(name)
    return any(fam in flat for fam in _recommended_families())


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
        # 30 is the size ASKED FOR, not the pixels handed to the face. A point
        # is not a size - Anton's capitals are 0.86 of its em and Nanum Pen
        # Script's are 0.56 - so a picker that drew every specimen at a flat 30
        # showed one face half the height of the next and made the list look
        # like a list of sizes. `typeset.px_for` is the same conversion the
        # typesetting itself goes through, so a specimen is now the size the
        # word will actually come out.
        font = ImageFont.truetype(fp, typeset_mod.px_for(fp, 30))
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


def _mark_sample_png(cfg, ch: str, size: int = 44) -> "bytes | None":
    """One mark as a small transparent PNG, for the picker.

    Drawn through `typeset.mark_glyph` - the same call the renderer makes - so
    the picker shows the shape that will land on the page rather than a second
    drawing of it. When the current face has its OWN glyph for the character
    (Jua and Patrick Hand both have a heart) `mark_glyph` returns None and the
    sample is the font's letter, which is again what the page will show.
    """
    try:
        from PIL import Image, ImageDraw
        path = typeset_mod.font_for(cfg, "bubble")
        got = typeset_mod.mark_glyph(path, size, ch)
        if got is not None:
            mask = got[2]
            img = Image.new("RGBA", (mask.width + 8, mask.height + 8),
                            (0, 0, 0, 0))
            img.paste((207, 213, 226, 255), (4, 4), mask)
        else:
            font = typeset_mod._font(path, size)
            l, t, r, b = font.getbbox(ch)
            if r <= l or b <= t:
                return None
            img = Image.new("RGBA", (r - l + 8, b - t + 8), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((4 - l, 4 - t), ch, font=font,
                                     fill=(207, 213, 226, 255))
        import io
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


def shipped_kind_fonts() -> dict:
    """The face each kind gets when NOTHING has been chosen for it, by path.

    The last link in the chain `typeset.font_for` walks, and the only one the
    browser cannot work out for itself: `DEFAULT_FONTS` is a table in the
    server's head, and the file it names has to be found on this machine before
    it is worth naming.

    Sent with the font list so the Box types panel can show the face a row
    would ACTUALLY typeset in. lee sent a screenshot of that panel listing
    `AnimeAce.ttf` and `CCWildWords.ttf` on nine rows - two files this app is
    no longer allowed to ship and that are not on his disk any more - and
    `ComicNeue-Bold` on the three family rows, where the real answers are Comic
    Neue Regular and Bangers. The panel was reading saved settings and its own
    first list entry; neither is what the page comes out in.

    Resolved against an EMPTY config on purpose. The project's own font is a
    step the browser already has and can apply itself; what it is missing is
    what lies past it, and asking with the project's font in hand would return
    that font twelve times and answer nothing.
    """
    from .typeset import TypesetConfig, font_for
    blank = TypesetConfig(font_path="")
    keys = list(_kinds.FAMILIES) + list(_kinds.PRELOAD_KEYS)
    out = {}
    for key in keys:
        try:
            got = font_for(blank, key)
        except Exception:
            got = ""
        if got:
            out[key] = got
    return out


def fonts_answer() -> dict:
    """EVERYTHING ABOUT FONTS, IN ONE REPLY, FROM EVERY FONT ENDPOINT.

    `takeFonts` in the browser has said this in its own comment since it was
    written - *"One answer, four lists. Every font endpoint returns all of them
    so nothing can be redrawn from a half-updated picture"* - and `/api/font`
    did not keep it. It answered with `fonts`, `recent` and `uploaded` and left
    out `defaults` and `marks`, and `takeFonts` takes what it is handed:

        KIND_DEFAULTS = f.defaults || {};
        MARK_LIB      = f.marks    || [];
        SERVER_STALE  = !('defaults' in f);

    So **picking a font in any dropdown** - which posts `do:used` to that
    endpoint - emptied the defaults table, emptied the marks picker, and raised
    the flag that means *the app is older than this page*. From then on every
    row of Box types fell through to the project's own font and read the same
    name twelve times, under a banner telling you to restart an app that was
    not out of date at all.

    lee sent exactly that screenshot: twelve rows of `ComicNeue-Bold` with the
    stale-server line above them.

    One function, so a reply cannot be half a reply. The two callers differ
    only in what they add to it - `/api/font` adds `ok` and `error` - and a
    third endpoint added later gets the contract by using it.
    """
    return {"fonts": find_fonts(),
            # `recent` travels with the list rather than being asked for
            # separately: the picker needs both to draw one menu, and two round
            # trips means the list can render before the recents and jump.
            "recent": userdata.recent_fonts(),
            "uploaded": userdata.uploaded_fonts(),
            "defaults": shipped_kind_fonts(),
            # HOW TALL EACH FACE'S CAPITALS ARE, so the browser can draw a
            # size the same way the server does. `typeset.px_for` turns a
            # point number into the number PIL is asked for; the preview has
            # to make the same conversion or the page and the screen disagree
            # about every block. See `typeset.CAP_REF`.
            #
            # Measured only for the faces the picker OFFERS - a face nobody
            # can choose is a file nobody needs opened - and cached, so this
            # costs once per process rather than once per reply.
            "caps": {f["path"]: typeset_mod.cap_ratio(f["path"])
                     for f in find_fonts()
                     if f.get("bundled") or f.get("uploaded") or f.get("comic")},
            "cap_ref": typeset_mod.CAP_REF,
            # `picks` and `sources` used to travel here, for a Fonts tab in
            # the editor. That page is on the website now
            # (`site/fonts.html`), so the payload went with it - an answer
            # nothing reads is a request nobody can see is wasted.
            # `fontpicks` itself stays: `_is_comic_font` reads it, because a
            # face this app recommends is a face the picker must offer.
            # ...and the marks that can go IN a line. Characters only: the
            # browser cannot draw the shapes and asks /marksample for a
            # picture of each. See `marks.PICKER`.
            "marks": [[g, [[c, n] for c, n in items]]
                      for g, items in _marks.PICKER]}


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
    # NORMCASE IS FOR COMPARING, NOT FOR KEEPING, and the difference cost lee
    # a whole panel. On Windows `os.path.normcase` LOWERCASES a path, and these
    # candidates were both the thing compared and the thing walked - so
    # `os.walk` yielded a lowercased `dirpath` and every font in the list was
    # stored as `c:\users\...\comicneue-bold.ttf`.
    #
    # `typeset._bundled` returns the real-case path, so the two never matched.
    # Box types compares them to name each row's face, found nothing, and
    # printed "Project default" twelve times. Invisible on Linux and macOS,
    # where `normcase` does nothing at all, which is why every test of it
    # passed here.
    #
    # So the list is walked with the REAL path and only the membership test is
    # normcased.
    for cand in (os.path.join(os.path.dirname(here), "fonts"),  # repo root/fonts
                 os.path.join(here, "fonts"),                   # package/fonts
                 os.path.join(os.getcwd(), "fonts")):           # launch dir/fonts
        c = os.path.abspath(cand)
        if os.path.normcase(c) not in {os.path.normcase(x)
                                       for x in bundled_candidates}:
            bundled_candidates.append(c)
    bundled_set = {os.path.normcase(c) for c in bundled_candidates}
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
    # comic-sounding prefixes bumped to the top of the rest - so the menu read
    # Mangaka, AnimeAce, ComicNeue, Komika, comic, comicbd, Anton, Bangers…
    # and there was no way to guess where any face would be. lee: *"the fonts
    # shoud be in aphabetical order with the new fonts"* - with, not above.
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
