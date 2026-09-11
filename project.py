"""Chapter-level project state.

Regions are held as geometry (a polygon plus metadata), never as bitmaps - a
40-page chapter with eight bubbles a page would otherwise sit on close to a
gigabyte of masks. Masks are rebuilt from the polygon on demand, for the page
being edited or exported.
"""
from __future__ import annotations

import dataclasses
import glob
import json
import os
import re
import shutil
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

# How long a coalescing save waits for the next edit before writing. Long
# enough that a run of presses is one write, short enough that closing the
# window a moment after an edit still has it on disk.
SAVE_DELAY = 0.4

from . import kinds as _kinds
from . import stopping as _stopping
from .detect import classical
# Imported up here rather than lazily like the detector itself, because
# `summary()` needs one number off it on every project read and a fallback copy
# of that number would be a second place for it to live. It costs the same
# imports `classical` above already made.
from .detect import comictext as _ctd
from .order import assign_order
from .pipeline import load_page
from . import coins as _coins
from . import imgio
from . import userdata as _userdata
from .score import score_regions
from .translate import SeriesContext
from .models import Page, TextRegion, turned_box

# Media the app used to offer, and what each one stood for. Kept only so that a
# project.json written back then still opens as the chapter it was, instead of
# being read as whatever `MEDIA.get(..., MEDIA["manga"])` falls back to. See
# `Project.load`.
MEDIA_GONE = {
    "comic": {"source": "English", "code": "en", "rtl": False},
}

IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "bmp")
INK = 128


def natural_key(path: str) -> list:
    """Sort key that reads runs of digits in a filename as numbers.

    A chapter arrives as `content_image_1 … content_image_105`, and plain
    alphabetical order puts 100 between 10 and 11 - page 2 of the chapter ends
    up ninety files down the list. For a book of pages that is a nuisance; for
    a webtoon strip that has to be JOINED BACK TOGETHER it is fatal, because
    the tiles are stacked in list order and the artwork comes out interleaved.

    The path itself is the last word, because reading digits as numbers makes
    `1.png` and `001.png` the same key and a folder can hold both. Two files
    that sort as equal come out in whatever order they happened to arrive in,
    which is not an order.
    """
    key = [(1, int(t), "") if t.isdigit() else (0, 0, t)
           for t in re.split(r"(\d+)", path.lower()) if t]
    return key + [(0, 0, path)]


def list_images(folder: str) -> list[str]:
    out: list[str] = []
    for e in IMAGE_EXTS:
        out += glob.glob(os.path.join(folder, f"*.{e}"))
        out += glob.glob(os.path.join(folder, f"*.{e.upper()}"))
    return sorted(set(out), key=natural_key)


# The steps that call a model. Named here as well as in `editor` because this
# is where their settings live; `editor.AI_STEPS` is the same list and a test
# says so.
#
# `find` is Find text's AI option and it joined the other three rather than
# borrowing the reader's service. It was wired to borrow at first, on the
# reasoning that the reader is already a vision step on a vision-capable model
# and a fourth menu is a fourth thing to leave set wrong. lee, looking at the
# new menu: *"what ai is it asking ? add on option to ai"* -- which is the
# answer to that reasoning. A step whose service you cannot see is a step you
# cannot trust the price of, and "it uses whatever Read text uses" is a fact
# you have to be told rather than one you can look at.
AI_STEPS = ("ocr", "translate", "proofread")


def migrate_engine(settings: dict, saved: dict) -> bool:
    """Carry an old project's one engine onto its three steps.

    A project.json written before the per-step boxes existed has `backend`,
    `model`, `base_url` and `api_key` and nothing per step - and the screen
    that set them is gone. lee: *"remove teh recomened tab and the translation
    engine"*. Copy them across so nothing anybody configured is lost, and only
    onto the steps the FILE left unset, so a project that did use the per-step
    boxes is untouched.

    `saved` is the settings as they were read off disk. `settings` is those
    merged over the defaults, which is why the two are needed: every step has
    a model in `settings` whether the file mentioned one or not.
    """
    model = str(saved.get("model") or "").strip()
    back = str(saved.get("backend") or "").strip()
    if not model:
        return False
    moved = False
    for step in AI_STEPS:
        if str(saved.get(f"{step}_model") or "").strip():
            continue                      # this step was set up on its own
        settings[f"{step}_model"] = model
        if back:
            settings[f"{step}_backend"] = back
        if saved.get("base_url"):
            settings[f"{step}_base_url"] = saved["base_url"]
        if saved.get("api_key"):
            settings[f"{step}_key"] = saved["api_key"]
        moved = True
    return moved


# The three services this app offers, in the order the menus list them. This
# is `editor.SERVICES` and the `SERVICES` in `static/js/project.js`, and a test
# holds all three in step: a service the screen offers and the server does not
# know is a step nobody can run, and it fails at the provider rather than at
# the menu, halfway through a chapter.
SERVICES = ("anthropic", "gemini", "openrouter")


# What the browser is told instead of a secret. Everything that holds a key or
# a token reports itself as this, or as "" when there is nothing saved.
MASK = "set"

# ...and this when the answer is coming out of the `.env` rather than out of
# this chapter. A separate word rather than `MASK` because the two mean
# different things to whoever is looking at the screen: "set" means you typed
# it here and it is safe to leave alone, "env" means typing here will not
# change anything, because `editor.key_for` reads the file first.
#
# It is a REPORT, exactly like `MASK`, and `drop_masked_secrets` refuses it as
# a value for the same reason: a `.tct` exported from a machine with a `.env`
# carries the word `env` in every key field, and importing that must not save
# three characters over a working key.
ENV = "env"


def secret_keys(settings: dict | None = None) -> list[str]:
    """Every settings key that holds a secret.

    Built from `AI_STEPS` and `SERVICES` rather than written out, because the
    written-out version has now been wrong twice: once when a fourth AI step
    sent its key to the browser in the clear, and once when the same step's key
    was left out of the strip-the-whitespace list on save.
    """
    out = ["api_key", "clean_token"]
    out += [f"{k}_key" for k in AI_STEPS]
    out += [f"key_{s}" for s in SERVICES]
    return [k for k in out if settings is None or k in settings]


def drop_masked_secrets(incoming: dict) -> list[str]:
    """Refuse to store the mask as if it were the secret it stands for.

    `MASK` is a REPORT that a key exists. It is never a key. But it goes out to
    the browser in the same field the key would live in, and anything that
    sends a whole settings object back -- a `.tct` import, a restored snapshot,
    a script -- hands it straight back, and then the field that said "(saved)"
    is saved: three characters long, and refused by every provider.

    lee, with Find text on AI::

        RuntimeError: the OCR step's key was refused by the provider
        (HTTP 400) - the key it has ends set.

    Ends `set` because it WAS `set`. The message was right and read like a
    wrong key rather than like no key at all.

    Edits `incoming` and returns the names it dropped, so a caller can say so.
    """
    dropped = []
    for k in secret_keys():
        v = incoming.get(k)
        if isinstance(v, str) and v.strip() in (MASK, ENV):
            incoming.pop(k, None)
            dropped.append(k)
    return dropped




def migrate_keys(settings: dict, saved: dict) -> bool:
    """Lift a project's per-step keys into the one box per service.

    A key is a fact about the provider, not about the step. Three boxes meant
    typing the same Google key twice and meant it could be right in one and
    stale in the other, with nothing on screen saying which of the two a run
    would use.

    Only onto services the file left EMPTY, so a service key that has been
    changed since is never overwritten by a per-step leftover - the whole point
    of moving them is that the service box is now the answer.

    The per-step keys are not deleted. An old project.json that has not been
    saved since this ran still works, because `editor.key_for` falls back to
    them; and a key is the one setting in here it would be genuinely rude to
    throw away on the strength of a migration.
    """
    moved = False
    for step in AI_STEPS:
        key = str(saved.get(f"{step}_key") or "").strip()
        back = str(saved.get(f"{step}_backend")
                   or settings.get(f"{step}_backend") or "").strip().lower()
        if not key or back not in SERVICES:
            continue
        # Already answered, and answered later. `settings` is the file's
        # values merged over the defaults, and the default is empty - so a
        # non-empty one here can only have come from the file, which makes
        # this the same question as asking `saved`. It was asked both ways
        # until a mutant showed the two were indistinguishable.
        if str(settings.get(f"key_{back}") or "").strip():
            continue
        settings[f"key_{back}"] = key
        moved = True
    return moved


def _fill_auto_glow(recs) -> None:
    """Write the automatic halo onto each record's LAYOUT, where the browser
    reads its colours from.

    lee, after the first ship: *"i exported the pages and the outer gow works
    but it just dont show in the editor"*. Both halves were right. The exporter
    works its colours out afresh every time it draws, so an exported page has
    always had the halo; the browser has no page to look at, so it typesets
    from `layout.fg`/`edge`/`stroke` - and nothing was writing `layout.glow`,
    which did not exist.

    Here rather than in `assign_colours`, which is the other candidate and runs
    at TYPESET time. That would leave every page typeset by an earlier build
    without a halo in the editor until it was laid out again, which is a
    migration nobody asked for and would not know to run. This runs on the way
    out of the door, so a chapter finished last week opens with it.

    It costs nothing to do here because it needs nothing off the artwork:
    `on_art` is unconditionally true for the sfx family, so the kind, the size
    and the edge colour - all three already on the record - are the whole
    input. `render.auto_glow_bits` is that one rule; this only calls it.

    A glow somebody CHOSE is not touched, and neither is a glow they turned
    off: `auto_glow_bits` reads the override first and answers None to both,
    and this leaves the field exactly as the save echoed it.

    Which is the one thing to be careful about here. `layout` is not only a
    record of the fit - a save echoes the whole style back into it, so
    `layout.glow` may already be there and may already be somebody's answer.
    Clearing it whenever there is no automatic halo threw that echo away and
    a chosen glow stopped surviving a reload. So the rule is stated as what it
    means rather than as a blank: **the layout's glow is the chosen one, or the
    automatic one, or nothing** - and `""` is how this app has always spelled
    the third.
    """
    from . import render as _render          # imported late: render needs us
    for rec in recs:
        lay = rec.get("layout")
        if not isinstance(lay, dict) or not lay.get("lines"):
            continue
        ov = rec.get("layout_override") or {}
        for key in ("glow", "iglow"):
            got = _render.auto_glow_bits(lay.get("fg") or "",
                                         lay.get("edge") or "",
                                         lay.get("font_size") or 0, ov, key)
            if got:
                lay[key] = _render._css(got[0])
                lay[key + "_size"] = int(got[1])
            elif _render.hex_rgb(ov.get(key)) is None:
                # Nobody chose one and there is none to work out - which is
                # also what a block that has stopped being hollow looks like,
                # so the answer has to be WRITTEN rather than merely not
                # written.
                lay[key] = ""


def region_record(r: TextRegion) -> dict:
    return {
        "id": int(r.id), "bbox": [int(v) for v in r.bbox],
        "bubble_bbox": [int(v) for v in r.bubble_bbox] if r.bubble_bbox else None,
        "polygon": [[int(a), int(b)] for a, b in (r.polygon or [])],
        # The typesetter's balloon, when the balloon check wrote one. Kept
        # apart from `polygon` on purpose: the cleaner reads `polygon` and
        # must never see this. lee: *"it should only help the typesetter on
        # bubble text"*.
        "fit_poly": ([[int(a), int(b)] for a, b in r.fit_poly]
                     if getattr(r, "fit_poly", None) else None),
        "kind": str(r.kind), "order": int(r.order),
        "link": int(getattr(r, "link", 0) or 0),
        "link_kind": str(getattr(r, "link_kind", "") or ""),
        "box_group": int(getattr(r, "box_group", 0) or 0),
        "src_text": r.src_text, "src_vertical": bool(r.src_vertical),
        "angle": round(float(getattr(r, "angle", 0.0) or 0.0), 2),
        "sfx_vertical": bool(getattr(r, "sfx_vertical", False)),
        "sfx_len": round(float(getattr(r, "sfx_len", 0.0) or 0.0), 4),
        "sfx_wid": round(float(getattr(r, "sfx_wid", 0.0) or 0.0), 4),
        "turn": round(float(getattr(r, "turn", 0.0) or 0.0), 2),
        "dst_text": r.dst_text, "dst_compact": r.dst_compact,
        "speaker": r.speaker, "confidence": float(r.confidence),
        "flagged": r.flagged, "manual": bool(getattr(r, "manual", False)),
        "own_text": bool(getattr(r, "own_text", False)),
        # ...and whether a PERSON chose this box's type. See the note in
        # `region_from_record`: without this line the flag dies on the first
        # commit and the reader relabels a box somebody had already fixed.
        "kind_by_hand": bool(getattr(r, "kind_by_hand", False)),
        # ...and the same question about the ANGLE, for the same reason. The
        # reading now fills in the lean of loose writing - see
        # `editor._apply_read_angles` - and it must not undo one somebody set
        # with the rotate handle.
        "angle_by_hand": bool(getattr(r, "angle_by_hand", False)),
        "skip_clean": bool(getattr(r, "skip_clean", False)),
        # How this box was cleaned, so the question can be asked of a BOX
        # rather than of a whole chapter. Not restored on the way in
        # (region_from_record leaves it empty): it is a fact about the last
        # run, and a stale answer is worse than none.
        "clean_route": str(getattr(r, "clean_route", "") or ""),
        "clean_core": bool(getattr(r, "clean_core", False)),
        "draw_box": getattr(r, "draw_box", None),
        "layout_override": r.layout_override,
        # Saved as well as the hand corrections, and separately from them, so
        # that opening a chapter does not have to read every page again to
        # know what its letters were drawn with. See
        # `models.TextRegion.layout_measured`.
        "layout_measured": getattr(r, "layout_measured", None),
        "layout": ({"lines": r.layout.lines,
                    "font_size": int(r.layout.font_size),
                    "leading": round(float(r.layout.leading), 3),
                    "origins": [[int(a), int(b)] for a, b in r.layout.line_origins],
                    "fg": r.layout.fg, "edge": r.layout.edge,
                    "stroke": int(r.layout.stroke),
                    "font": r.layout.font_path or "",
                    "rotate": float(getattr(r.layout, "rotate", 0.0)),
                    "frame": list(getattr(r.layout, "frame", None) or []),
                    # Two blocks in one box - a speech shared between the
                    # lobes of a double balloon - so the browser must use the
                    # origins above rather than spacing them down the frame.
                    "fixed": bool(getattr(r.layout, "fixed", False)),
                    "fit_ok": bool(r.layout.fit_ok),
                    # What this layout was fitted FROM. Without it on the
                    # record the page is fitted again on the way back in, and
                    # fitting is 2.6 of the 3 seconds a page costs. See
                    # `typeset.page_fit_key`.
                    "fit": str(getattr(r.layout, "fit", "") or ""),
                    "used_compact": bool(r.layout.used_compact)}
                   # An EMPTY block is still a block. Storing it only when it
                   # had lines threw away the frame of a box whose words had
                   # been deleted, so it came back the next time the project
                   # was opened at whatever size the fitter last chose rather
                   # than the size it was left at. A layout with neither lines
                   # nor a frame really is nothing, and stays nothing.
                   if r.layout and (r.layout.lines
                                    or getattr(r.layout, "frame", None))
                   else None),
        "locked": bool(getattr(r, "locked", False)),
    }


def _is_a_box(poly: np.ndarray) -> bool:
    """Is this "outline" just the four corners of a rectangle?

    A rectangle is what gets stored for a region nobody found a balloon for and
    for one the person drew or tightened by hand. It says where the WRITING is,
    which is not the same thing as where the balloon is, and a balloon is what
    the typesetting has to fit inside - so it must not be loaded back as one.
    """
    if poly.size < 6:
        return True
    pts = poly.reshape(-1, 2)
    if len(pts) > 4:
        return False
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    corners = {(int(x0), int(y0)), (int(x1), int(y0)),
               (int(x1), int(y1)), (int(x0), int(y1))}
    return all((int(a), int(b)) in corners for a, b in pts)


def find_balloons(img: np.ndarray, regions: list[TextRegion]) -> int:
    """Give every speech region that came back without one its balloon.

    **The BALLOON, and nothing else.** `attach_balloons` also renames a
    free-floating block to a bubble when it turns out to be inside one, which
    is right at detection and wrong here, because here is every reload. lee:
    *"boxes chaning type after i reload the projet"*, and it was exactly this:

        set a box to Outside text   ->  saved as freefloat
        open the page again         ->  `materialize` calls this
                                    ->  a balloon is found round it
                                    ->  it is a bubble now, and the next save
                                        writes that down

    Silent, and permanent after one save. It hit precisely the boxes somebody
    had corrected by hand, because those are the ones whose label disagrees
    with the pixels - which is what a correction IS.

    The rule is the one `region_from_record` already keeps for the outline
    three functions down: **the label wins over the geometry.** A kind on disk
    is a decision that has already been made, by a detector or by a person, and
    only a fresh Find text may make it again.

    Masks are not saved - a chapter is held as geometry - so the balloon has
    to be found again on the way back in. It was only ever looked for at
    detection, which left two ways to end up typesetting into a rectangle: a
    region saved before the balloon finder could see it, and a box the person
    drew or tightened by hand. The box says which balloon the words belong to.
    It is not the shape they have to fit.

    Anything that already carries a real outline is left alone, so a balloon
    found once is not searched for again, and a region with no balloon to find
    costs one look and then falls back to its box.

    Whatever is still left with nothing then gets the empty paper around its
    writing instead of the bare box - see `give_room`. That is the writing with
    no balloon at all: a caption printed straight onto a blank panel. It used
    to typeset at 12pt in the tall narrow column the Japanese was set in.
    """
    from .detect.balloon import attach_balloons, give_room
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    got = attach_balloons(gray, regions, rename=False)
    # ...and then hand back anything that is not this block's to have. The
    # search above is allowed to give a free block a balloon - a caption alone
    # in one needs it - but not a balloon another block is already typesetting
    # into. See `drop_borrowed_balloons`. It runs AFTER the search because the
    # search is where the borrowing happens, and before `give_room`, which is
    # what puts the block back on the paper around its own writing.
    drop_borrowed_balloons(regions)
    give_room(gray, regions)
    return got


# Kinds that cannot have a balloon: writing brushed onto the artwork, and sound
# effects. Kept here as well as in the editor because this is the door every
# page comes back through.
# The two families that never have a balloon: writing lying on the artwork,
# and a drawn sound. A sub-type is unballooned when its FAMILY is - a box's
# geometry is decided by which of the three it is, never by which sub-type.
NO_BALLOON_KINDS = ("freefloat", "sfx")


def _no_balloon(kind: str) -> bool:
    return _kinds.family_of(kind or "") in NO_BALLOON_KINDS


# How much of two shapes has to be the same before one of them is not a shape
# of its own. Two blocks handed shares of one balloon are DISJOINT - the
# detector takes a hairline off each - so anything approaching this number is
# not two shares, it is one shape held twice.
SAME_BALLOON = 0.9


def drop_borrowed_balloons(regions: list) -> int:
    """Take a balloon back off a block that cannot have one. Returns how many.

    `NO_BALLOON_KINDS` is the rule and it is old: writing lying on the artwork
    and a drawn sound have no balloon, and the ink's own footprint is where
    they belong. What was missing was anything that ENFORCED it on a chapter
    already saved, and one route wrote exactly that state to disk -
    `attach_balloons(rename=False)` handing a freefloat a balloon it was only
    ever offered so that it could be renamed a bubble. See the comment there.

    lee's page 005, where it cost him a line of dialogue: `あの…` is free text
    at the top right of the big balloon, and the saved polygon on it is the
    balloon - all 88 points of it, the same 88 the dialogue has. Both blocks
    typeset into the same paper and "Um..." is printed through the middle of
    the word Zarudone.

    **The test is that the shape is somebody ELSE'S, not that it is big.** A
    freefloat is perfectly entitled to a shape larger than its box - that is
    what `give_room` is for, and a caption on a blank panel needs it. What no
    block is entitled to is the shape a balloon-carrying block is already
    typesetting into. Two shares of one balloon are disjoint by construction,
    so an overlap anywhere near `SAME_BALLOON` can only be one shape counted
    twice.

    What it is handed back to is its own box, which is where `give_room` picks
    it up a moment later - and `give_room` will not grow it into paper another
    block has already taken, so it stays where its writing is.

    **Both halves of the state are repaired**, because they come apart.
    `region_from_record` already refuses to rebuild a MASK from a balloon
    polygon on a kind that cannot have one, so a chapter loads with the mask
    gone and the POLYGON still borrowed - and the polygon is what the editor
    draws as the box, so lee sees a piece of free text outlined as the whole
    balloon and can drag the balloon by it. The polygons are compared exactly:
    two of them are only ever identical because one `_apply` wrote both.
    """
    import numpy as np

    def pts(r):
        return [(int(round(a)), int(round(b)))
                for a, b in (getattr(r, "polygon", None) or [])]

    theirs = [r for r in regions if not _no_balloon(getattr(r, "kind", ""))
              and (getattr(r, "bubble_mask", None) is not None or pts(r))]
    if not theirs:
        return 0
    took = 0
    for r in regions:
        if not _no_balloon(getattr(r, "kind", "")):
            continue
        m = getattr(r, "bubble_mask", None)
        mine = (np.asarray(m) > 0) if m is not None else None
        shape = pts(r)
        if mine is None and len(shape) < 3:
            continue
        for q in theirs:
            if shape and shape == pts(q):
                break
            if mine is None or not mine.any():
                continue
            om = getattr(q, "bubble_mask", None)
            if om is None:
                continue
            other = np.asarray(om) > 0
            if other.shape != mine.shape:
                continue
            union = float((mine | other).sum())
            if union and float((mine & other).sum()) / union >= SAME_BALLOON:
                break
        else:
            continue
        _own_box_again(r)
        took += 1
    return took


def _own_box_again(r) -> None:
    """Back to the block's own box - the state a region has before any balloon
    is found for it, so everything downstream behaves as it would on a page
    where none ever was."""
    x, y, w, h = [int(v) for v in r.bbox]
    r.bubble_mask = None
    r.bubble_bbox = (x, y, w, h)
    r.polygon = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def is_turned(rec: dict) -> bool:
    """Is this a box somebody turned? Only those may be, and only they follow.

    It was hand-drawn boxes only -- lee: *"only teh ser shoud be able to
    rotate them the detector boxes shoud be normal"* -- on the reasoning
    that a detected outline came off the artwork. He asked for the other
    thing: *"alowm me to be able to rotate every box"*, and he is right. A
    detector can be wrong about the ANGLE as easily as about the edges, and
    it is the same person fixing both.

    Off `turn` and not `angle`: a sound effect drawn by hand is given an angle
    the moment it is drawn - the axis its artwork runs along - and reading that
    as a turn would have leant every one of them.
    """
    return abs(float(rec.get("turn") or 0.0)) > 0.01


# How black a balloon has to be before "the writing is the dark pixels" stops
# being true of it, and how light a pixel has to be to count as writing when it
# does. Read off lee's page 009: the balloon is 84% dark and its writing is
# 7% light, which is not a close call in either direction. A white balloon on
# the same page is 10% dark.
DARK_GROUND = 0.60
PAPER = 255 - INK


def _writing_in(gray: np.ndarray, bubble: np.ndarray,
                balloon: bool = False) -> np.ndarray:
    """The WRITING inside a balloon, whichever way round it is drawn.

    This used to be one line - `gray <= INK` - which says *ink is dark*. It is,
    almost everywhere: a manga page is black on white and the exceptions are
    rare enough to go unnoticed for a long time.

    lee's page 009 is one of them. A solid black balloon with white Japanese in
    it, and that line marked the BALLOON as writing and the LETTERS as clean:
    24,164 pixels of "ink" in a balloon of 26,758. So the cleaner was asked to
    erase ninety per cent of the balloon and to keep the letters, `_flat_from`
    had not one pixel of background left to sample - the ink grown by twelve
    covered everything - and the box fell through to Telea, which filled the
    hole from the dotted screentone outside it. lee, on the result: *"why is
    teh typeseeting so bad"*. It was not the typesetting.

    THE WRITING IS THE MINORITY, and that is the whole rule. A balloon is
    mostly ground with a little writing on it, so if the dark pixels are most
    of the balloon then dark is the ground and the writing is what stands out
    of it. Asked only of a genuinely black balloon - 60% and up, against 10%
    for a white one on the same page - because the two populations are nowhere
    near each other and a rule that fires in between would be guessing.

    ASKED OF A BALLOON AND OF NOTHING ELSE, which is what `balloon` is for. A
    balloon is a shape whose ground is one colour; the rectangle that stands in
    where there is no balloon is a box round leaning writing, and a box round a
    heavy sound effect really can be more ink than paper. Left to the fraction
    alone this rule flipped one of those inside out - caught by its own test
    before it went anywhere, which is the argument for writing the test that
    states the boundary rather than the one that states the case.
    """
    inside = bubble > 0
    n = int(inside.sum())
    dark = (gray <= INK) & inside
    if balloon and n and int(dark.sum()) > DARK_GROUND * n:
        return ((gray >= PAPER) & inside).astype(np.uint8) * 255
    return dark.astype(np.uint8) * 255


# How much of a saved outline has to BE the field before the outline is taken
# as the field and handed back untouched, and how little may be left before the
# reading is not believed at all. Between the two the outline is read; outside
# them it stands. See `_one_ground`.
OUTLINE_IS_THE_FIELD = 0.90
GROUND_KEEPS = 0.34


def _one_ground(gray: np.ndarray, bubble: np.ndarray,
                glyph: np.ndarray) -> np.ndarray:
    """The part of a saved outline that is the ground the writing sits on.

    A balloon is a field of ONE TONE with a rim drawn round it, and the words
    go in the field. An outline that also covers the artwork outside the rim is
    not saying "the words may go there" - it is wrong, and the fitter cannot
    know that: it measures the room it is given and fills it, so the block
    drifts into whichever part of the shape is roomiest.

    lee, with page 009 - a black balloon with the English sitting low and
    crowding the bottom-left curve: *"the position of teh text iide is too low
    and too close to tehe edge at teh bottom left"*. The outline saved for that
    box follows the balloon along the top and right and then runs out as a
    straight-edged rectangle across the screentone at the bottom-left, down to
    the corner. Page 019's is a rectangle a third bigger than its balloon in
    every direction. Nothing rewrites a saved outline, so a chapter carries
    whatever an older build wrote for ever.

    So the outline is READ against the page rather than trusted: take the run
    of ground the writing is standing in - the same walk out from the ink, over
    one tone, stopped by drawn edges, that found the balloon in the first place
    (`detect.balloon._free_labels`) - and keep the part of the outline that is
    in it. Whichever way round the balloon is drawn: the polarity is chosen the
    way `_writing_in` chooses it, and for the same reason.

    THE WRITING IS ALWAYS ITS OWN GROUND. It is union'd back in and the holes
    are filled, because the run stops at the ink and a placement area with the
    letters punched out of it is the tall-narrow-column bug that `place_mask`
    exists to avoid.

    Measured over lee's 137 balloon outlines: 134 come back untouched and the
    three that move are the three that are wrong - 003#6 loses the tree its
    corner covered, 019#1 loses a third of a panel, 009#4 loses the screentone
    lobe hanging off its bottom-left. Not one of the 137 loses a letter.

    Nothing is written back. The outline on disk is what lee drew and what he
    sees; this is only where the English is allowed to go, worked out from the
    page in front of him on every load - the same arrangement, and the same
    reason, as `balloon.room_around`.
    """
    inside = bubble > 0
    n = int(inside.sum())
    if not n or not (glyph > 0).any():
        return bubble
    ys, xs = np.nonzero(inside)
    pad = 8
    y0, y1 = max(0, int(ys.min()) - pad), min(gray.shape[0], int(ys.max()) + pad + 1)
    x0, x1 = max(0, int(xs.min()) - pad), min(gray.shape[1], int(xs.max()) + pad + 1)
    win = (slice(y0, y1), slice(x0, x1))
    g = gray[win]
    # ...on the negative when the writing is standing on a dark field, which is
    # the same question `_writing_in` asks one line further down and has to be
    # answered the same way. A rule that read one of them upright and the other
    # inverted would cut the balloon in half.
    if int(((gray <= INK) & inside).sum()) > DARK_GROUND * n:
        g = 255 - g
    from .detect.balloon import BalloonConfig, _free_labels, _surrounding_label
    cnt, labels = _free_labels(g, BalloonConfig())
    if cnt <= 1:
        return bubble
    lab = _surrounding_label(labels, glyph[win])
    if lab <= 0:
        return bubble                     # no run to read: leave the outline
    run = ((labels == lab) & inside[win]).astype(np.uint8)
    field = _no_holes(run) & inside[win]
    if int(field.sum()) >= OUTLINE_IS_THE_FIELD * n:
        # THE OUTLINE IS THE FIELD, which is what almost every outline is, and
        # then it is returned untouched rather than nearly untouched. The walk
        # stops a pixel or two short of a drawn rim and leaves a letter that
        # runs off the edge of the outline standing outside it, so the answer
        # here is a placement area a fraction smaller with a nick or two in
        # it - a worse shape than the one it was given, arrived at by
        # measuring something that was not wrong. 131 of lee's 137 come back
        # through this line.
        return bubble
    keep = _no_holes((field | _standing_on(glyph[win] > 0, field)).astype(np.uint8))
    keep = keep & inside[win]
    if int(keep.sum()) < GROUND_KEEPS * n:
        return bubble
    out = np.zeros(gray.shape[:2], np.uint8)
    out[win][keep] = 255
    return out


def _standing_on(ink: np.ndarray, field: np.ndarray) -> np.ndarray:
    """The marks that are standing ON this field, and not the ones beside it.

    The writing has to be union'd back into its own field - the walk stops at
    ink, so the letters are holes in it - but "the writing" here is whatever
    `_writing_in` read out of the WHOLE outline, and an outline that runs off
    its balloon has marks in it that are not writing at all. Two kinds, and
    they are different mistakes:

    * artwork out in the lobe, which is nothing to do with this box;
    * THE RIM, which on an outline that crosses it is read as writing every
      time, because a rim is exactly the tone the writing is - a white rim
      round a black balloon is white, like the words in it.

    Union either one in and the lobe comes back a mark at a time, the rim
    dragging in whatever it encloses. So a mark counts as this field's when it
    is standing INSIDE the field's own outline rather than merely against it:
    the writing is surrounded by its ground, the rim surrounds it. Asked mark
    by mark, because a letter is the unit that is either on the balloon or not,
    and by majority, because a letter that runs off the edge of the outline is
    still that balloon's letter.
    """
    if not ink.any() or not field.any():
        return np.zeros(field.shape[:2], bool)
    home = _no_holes(cv2.dilate(field.astype(np.uint8),
                                np.ones((3, 3), np.uint8), iterations=2))
    n, lab = cv2.connectedComponents(ink.astype(np.uint8), 8)
    if n <= 1:
        return np.zeros(field.shape[:2], bool)
    whole = np.bincount(lab.ravel(), minlength=n).astype(float)
    at_home = np.bincount(lab[home].ravel(), minlength=n).astype(float)
    keep = np.zeros(n, bool)
    keep[1:] = at_home[1:] > 0.5 * np.maximum(1.0, whole[1:])
    return keep[lab]


def _no_holes(m: np.ndarray) -> np.ndarray:
    """Everything the shape encloses, filled in."""
    h, w = m.shape[:2]
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = m
    seed = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(pad, seed, (0, 0), 255)
    return (m > 0) | (pad[1:-1, 1:-1] == 0)


def region_from_record(rec: dict, img: np.ndarray) -> TextRegion:
    """Rebuild masks from the stored polygon."""
    H, W = img.shape[:2]
    poly = np.array(rec.get("polygon") or [], dtype=np.int32)
    # The LABEL wins over the geometry, always. Calling a box outside text says
    # there is no balloon round it, and a region saved while it was still
    # called speech has the old outline sitting in its record - lee changed the
    # type, saw it work, restarted, and got the panel back, because nothing
    # rewrites that outline except the moment of the change itself. Reading it
    # as a box here means the answer no longer depends on when it was saved.
    no_balloon = _no_balloon(rec.get("kind"))
    boxy = _is_a_box(poly) or no_balloon
    bubble = np.zeros((H, W), np.uint8)
    if not boxy:
        cv2.drawContours(bubble, [poly.reshape(-1, 1, 2)], -1, 255, cv2.FILLED)
        # ...and fill the bays out of the writing, the same way the finder does
        # now - see `detect.balloon._no_bays_in_the_writing`. Here as well as
        # there because a project saved before that existed has the snaked
        # outline on disk, and nothing rewrites a polygon except a fresh detect.
        # lee's chapter 1 is one of those: page 067 came back with two words
        # standing in the bays.
        from .detect.balloon import _no_bays_in_the_writing
        cnts, _ = cv2.findContours(bubble, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            class _Box:
                bbox = tuple(rec.get("bbox") or ())
            bubble = _no_bays_in_the_writing(
                _Box(), bubble, max(cnts, key=cv2.contourArea))
    else:
        # This rectangle is also where the WRITING is read from, two lines
        # down. A region relabelled outside text still carries the old
        # balloon's `bubble_bbox`, and reading the writing out of that would
        # hand the cleaner a whole panel of artwork to erase - so once the
        # label says there is no balloon, the box round the writing is the
        # only rectangle left that means anything.
        x, y, w, h = (rec["bbox"] if no_balloon
                      else (rec["bubble_bbox"] or rec["bbox"]))
        bubble[y:y + h, x:x + w] = 255

    # A placement area with nothing in it is not a placement area.
    #
    # Every rectangle above is trusted to be on the page, and one of them was
    # not: a `bubble_bbox` left in the coordinates of a page that has since
    # been cut in half indexes off the bottom, numpy hands back an empty slice
    # without complaint, and the region ends up with an empty mask and an empty
    # `text_mask`. Nothing downstream reads that as an error - there is simply
    # nothing to erase - so the box goes uncleaned and unreported.
    #
    # `_region_moved` moves the balloon's box now, so this cannot be made
    # fresh. It can still be READ: nothing rewrites a saved record, and lee's
    # chapter has a plate in it that was cut in half before the fix existed.
    # The box round the writing is always on the page, and it is the right
    # answer here - a balloon nobody can find is a region with no balloon.
    if not bubble.any():
        x, y, w, h = (int(v) for v in rec["bbox"])
        bubble[max(0, y):y + h, max(0, x):x + w] = 255

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    glyph = _writing_in(gray, bubble, balloon=not boxy and bubble.any())
    if not boxy and bubble.any() and len(poly.reshape(-1, 2)) > 4:
        # ...and now READ the outline against the page. A saved outline that
        # covers artwork outside the balloon is a shape the fitter will
        # happily typeset into - see `_one_ground`. Asked of a real outline
        # only: the rectangle that stands in where there is no balloon is not
        # claiming to be a field of anything.
        #
        # FOUR CORNERS IS A RECTANGLE, leaning or not, which is why the count
        # is asked here and not left to `_is_a_box` - that one answers about
        # an UPRIGHT rectangle, and a box somebody turned comes through it as
        # an outline. It is still a box: it says where the writing is, it was
        # drawn by hand, and reading it against the page trimmed a fifth off
        # one. lee: *"only teh ser shoud be able to rotate them"* - and what
        # he rotated is his own box, not a balloon.
        was = bubble
        bubble = _one_ground(gray, bubble, glyph)
        if bubble is not was:
            # The writing is read out of the placement area, so a smaller one
            # is a smaller thing to erase. Ink out in the artwork was never
            # this box's to clean.
            glyph = _writing_in(gray, bubble, balloon=True)

    r = TextRegion(
        id=rec["id"], bbox=tuple(rec["bbox"]),
        # A rectangle is not a balloon. Leaving the placement area empty sends
        # the region back through the balloon finder on the way out of
        # `materialize`, and if there is still no balloon to find the fitter
        # falls back to the box rather than to a rectangle pretending to be a
        # bubble outline.
        text_mask=glyph, bubble_mask=None if boxy else bubble,
        bubble_bbox=tuple(rec["bubble_bbox"]) if rec.get("bubble_bbox") else None,
        polygon=rec.get("polygon"), kind=rec.get("kind", "bubble"),
        fit_poly=rec.get("fit_poly") or None,
        skip_clean=bool(rec.get("skip_clean", False)),
        link=int(rec.get("link", 0) or 0),
        link_kind=str(rec.get("link_kind", "") or ""),
        box_group=int(rec.get("box_group", 0) or 0),
        order=rec.get("order", -1), src_text=rec.get("src_text", ""),
        src_vertical=rec.get("src_vertical", True),
        dst_text=rec.get("dst_text"), dst_compact=rec.get("dst_compact"),
        speaker=rec.get("speaker"), confidence=rec.get("confidence", 0.0),
        flagged=rec.get("flagged"),
        layout_override=rec.get("layout_override"),
        # A chapter written before this field existed has none, and comes back
        # as "never measured" - which is true, and which the next Typeset
        # fixes without asking anybody for anything.
        layout_measured=rec.get("layout_measured"),
        # A record written before the axis reader existed has none of these,
        # and loads as "never measured" rather than as "measured at zero".
        angle=float(rec.get("angle") or 0.0),
        sfx_vertical=bool(rec.get("sfx_vertical", False)),
        sfx_len=float(rec.get("sfx_len") or 0.0),
        sfx_wid=float(rec.get("sfx_wid") or 0.0),
        turn=float(rec.get("turn") or 0.0),
    )
    r.manual = rec.get("manual", False)      # type: ignore[attr-defined]
    r.locked = rec.get("locked", False)      # type: ignore[attr-defined]
    # A text box somebody put on the page themselves. It stands for no writing
    # in the artwork, so there is nothing to read, nothing to translate and
    # nothing under it to erase - see the region endpoint in editor.py.
    r.own_text = bool(rec.get("own_text", False))   # type: ignore[attr-defined]
    # SOMEBODY CHOSE THIS BOX'S TYPE, so nothing that guesses at types may
    # overrule it. lee, on the reader labelling boxes: a type you set by hand
    # coming back wrong on every re-read is worse than no labelling at all.
    #
    # Carried on the MODEL rather than left as a key on the record, because
    # `commit()` rebuilds every record through `region_record()` and an
    # editor-only key does not survive that - which is exactly the trap
    # `_commit_keep_proofread` exists to work around for the `proofread` flag.
    r.kind_by_hand = bool(rec.get("kind_by_hand", False))  # type: ignore[attr-defined]
    r.angle_by_hand = bool(rec.get("angle_by_hand", False))  # type: ignore[attr-defined]
    # THE STORED LAYOUT IS CARRIED IN, and this used to say the opposite: *a
    # block with typesetting is typeset again from scratch by whichever stage
    # asked for it*. That was true and it was expensive - laying a page out is
    # 2.6 of the 3 seconds it takes to build one, and it was paid on every
    # render, every export and every restart to arrive at the layout already
    # written down here.
    #
    # What makes carrying it in safe is that it is STAMPED: `typeset_page`
    # keeps it only when the page's fit key still matches, and lays the whole
    # page out again otherwise. See `typeset.page_fit_key`. A layout with no
    # stamp - written by an older build - has no key and is refitted, which is
    # the old behaviour exactly.
    #
    # A block with NO typesetting has nothing to derive a layout from, and its
    # frame - the size the person left the box at after deleting the words -
    # is only in the record; that case was always restored and still is.
    lay = rec.get("layout") or {}
    if lay and not lay.get("lines") and lay.get("frame"):
        from .typeset import TextLayout
        r.layout = TextLayout(
            lines=[], font_size=int(lay.get("font_size") or 12),
            leading=float(lay.get("leading") or 1.2),
            line_origins=[], score=0.0,
            font_path=str(lay.get("font") or ""),
            fit_ok=True, frame=[int(v) for v in lay["frame"]],
            fit=str(lay.get("fit") or ""))
    elif lay and lay.get("lines") and lay.get("fit"):
        from .typeset import TextLayout
        r.layout = TextLayout(
            lines=[str(x) for x in lay.get("lines") or []],
            font_size=int(lay.get("font_size") or 12),
            leading=float(lay.get("leading") or 1.2),
            line_origins=[(int(a), int(b))
                          for a, b in (lay.get("origins") or [])],
            used_compact=bool(lay.get("used_compact", False)),
            fit_ok=bool(lay.get("fit_ok", True)), score=0.0,
            font_path=str(lay.get("font") or ""),
            fg=str(lay.get("fg") or "#000000"),
            edge=str(lay.get("edge") or "#ffffff"),
            stroke=int(lay.get("stroke") or 1),
            rotate=float(lay.get("rotate") or 0.0),
            frame=([int(v) for v in lay["frame"]]
                   if lay.get("frame") else None),
            fixed=bool(lay.get("fixed", False)),
            fit=str(lay.get("fit")))
    return r


def read_sfx_axis(r: TextRegion, gray: np.ndarray) -> bool:
    """Read one sound effect's own axis off the page it was drawn on.

    Returns whether anything was recorded. The footprint is kept as fractions
    of the box's sides (see TextRegion) rather than in pixels, so it still
    means something after the box has been dragged about.
    """
    H, W = gray.shape[:2]
    x, y, w, h = [int(v) for v in r.bbox]
    x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
    w, h = min(w, W - x), min(h, H - y)
    if w < 4 or h < 4:
        return False
    from .sfx import sfx_frame
    # The reader wants the ink inside the box, and this app carries its masks
    # at page size. Handing over the whole page squashes the effect down to
    # the size of its own box on the way in, and what comes back is measured
    # off a picture of the entire page - a couple of dozen pixels of typesetting
    # and an angle taken from them.
    tm = r.text_mask
    if tm is not None and tm.shape[:2] != (h, w):
        tm = tm[y:y + h, x:x + w]
    fr = sfx_frame(gray, (x, y, w, h), tm)
    r.angle = float(fr.tilt)
    r.sfx_vertical = bool(fr.vertical)
    r.sfx_len = float(min(1.2, max(0.2, fr.length / float(max(w, h)))))
    r.sfx_wid = float(min(1.5, max(0.2, fr.width / float(max(1, min(w, h))))))
    return True


def measure_sfx(page: Page) -> int:
    """Measure every sound effect on the page. Returns how many were read.

    This happens at detection and nowhere later, because it is the last moment
    the page still carries the Japanese: by typeset time the effect has been
    painted out, and there is nothing left to take an angle from.
    """
    todo = [r for r in page.regions if _kinds.family_of(r.kind) == "sfx"]
    if not todo:
        return 0
    img = page.image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return sum(1 for r in todo if read_sfx_axis(r, gray))


@dataclass
class PageState:
    path: str
    name: str
    width: int = 0
    height: int = 0
    detected: bool = False
    regions: list[dict] = field(default_factory=list)
    typeset: bool = False
    exported: bool = False
    cleaned: bool = False          # the clean plate has been produced/cached
    # A cleaned plate the person supplied for this page. When set, cleaning
    # uses this file instead of running the inpainter - per page, so page 3
    # can be hand-cleaned while 1, 2, 4 and 5 stay automatic.
    custom_clean: str = ""
    # What the proofreader could not fix by itself - an unclear pronoun, a
    # line whose source looks misread. A remark about the page as a whole,
    # which has nowhere else to live: region flags are per region.
    note: str = ""
    # Which boxes that remark is about: the ids the proofreader changed or
    # flagged on this run. A note saying *"replaced the honorific"* with no way
    # to tell WHERE means reading the whole page to find it.
    note_ids: list[int] = field(default_factory=list)
    # Touch-up strokes: a rendered RGBA overlay composited onto the plate,
    # plus the editable stroke list so they survive leaving the page.
    paint_overlay: str = ""
    # ...and the ones the person moved ABOVE the typesetting. Two bands, not a
    # free interleave: a drawing sits either under all the text or over all of
    # it. lee asked for exactly that when offered the choice.
    paint_over: str = ""
    paint_layers: list = field(default_factory=list)
    # Which of the three groups is put away on this page. A hidden group is not
    # drawn and takes no part in any stage - it is not read, translated,
    # cleaned, typeset or exported - and it is NOT deleted: the boxes sit in
    # `regions` untouched and come back the moment the tick goes back on.
    hidden_kinds: list[str] = field(default_factory=list)
    # ...and the individual boxes put away one at a time, by id. Same rule in
    # every other respect: not drawn, not read, not cleaned, not typeset, not
    # exported, and not deleted. lee: *"add a eye button to the [row] in teh
    # original page thag allow me to hid a box, just like i can hide all the
    # sfx box - i shud be able to hide individual boxes"*.
    hidden_ids: list[int] = field(default_factory=list)
    # The next id to hand out on this page, and it only ever goes up.
    #
    # Ids used to be `max(existing) + 1`, which REUSES the number of a box you
    # deleted. Everything the editor holds about a box while it is in the air
    # is keyed by that number - the edit whose save has not come home, the
    # pending keystroke, the undo snapshot - so a box drawn after a delete
    # inherited the dead one's words. lee: *"when i deleet an text box and
    # create a new one it come back with teh same text as teh olde text box"*.
    #
    # 0 means "not written down yet": an old project.json has no counter, and
    # `next_region_id` starts it above whatever is on the page.
    next_id: int = 0

    def remember_ids(self) -> None:
        """Remember the highest number on this page BEFORE a box carrying it
        is removed.

        The counter alone was not enough. It only ever moved when a box was
        made, so deleting the highest-numbered box let the floor drop back to
        it and the next box drawn took the dead one's number - the very thing
        `next_id` exists to stop. Merge hits that every single time, because a
        merge is deletes followed immediately by a create: two boxes go, the
        new one is handed one of their numbers, and the editor's pending edit
        and undo snapshot for the dead box are filed under it.

        A project.json written before the counter existed carries 0, so this
        is also what starts it - and it is called on the way OUT of a page's
        region list, which is the only moment the number is still there to be
        remembered.

        (Not `note_ids` - that name is taken, by the list of boxes a page's
        note is about.)
        """
        self.next_id = max(int(self.next_id or 0),
                           max((int(r.get("id", -1)) for r in self.regions),
                               default=-1) + 1)

    def new_region_id(self) -> int:
        """A number no box on this page has ever had."""
        self.remember_ids()
        nxt = int(self.next_id)
        self.next_id = nxt + 1
        return nxt

    def shown(self, rec: dict) -> bool:
        try:
            if int((rec or {}).get("id", -1)) in (self.hidden_ids or ()):
                return False
        except (TypeError, ValueError):
            pass
        g = group_of((rec or {}).get("kind") or "")
        return not (g and g in (self.hidden_kinds or ()))

    def hide_group(self, groups) -> None:
        """Put these groups away, and bring every individual box in the groups
        whose state CHANGED back out.

        lee: *"if i hid an individual sfx box and i use the main unhide tool to
        hide and unhide all the sfx it shoud allso unhide teh individual box"*.
        The group switch is the master control; using it is a statement about
        every box in that group, so the per-box choices inside it are spent.
        Groups the switch did not touch keep theirs.
        """
        want = [g for g in (groups or [])]
        # The symmetric difference, and no `if moved:` guard around what
        # follows - an empty one filters nothing out, so the guard could not be
        # told from its own absence.
        moved = set(want) ^ set(self.hidden_kinds or ())
        self.hidden_ids = [
            int(v) for v in (self.hidden_ids or [])
            if group_of(self._kind_of(int(v))) not in moved]
        self.hidden_kinds = want

    def _kind_of(self, rid: int) -> str:
        for r in self.regions:
            if int(r.get("id", -1)) == rid:
                return str(r.get("kind") or "")
        return ""

    @property
    def active(self) -> list[dict]:
        """The boxes that count - everything except a hidden group."""
        out = [r for r in self.regions if self.shown(r)]
        _fill_auto_glow(out)
        return out

    @property
    def hidden(self) -> list[dict]:
        return [r for r in self.regions if not self.shown(r)]

    @property
    def groups_present(self) -> list[str]:
        """Which of the three there are boxes for at all, hidden or not.

        This is what decides which switches the page offers: hiding a kind the
        page does not contain is a control that does nothing, and a page whose
        sound effects are hidden must keep offering the switch that brings them
        back."""
        # Not the text boxes somebody drew themselves. Those are typesetting on
        # the Image view, not writing found in the artwork, and one of them
        # made the page offer a "Outside text" switch for a group it has no
        # detected boxes in - a control that hides nothing.
        here = {group_of(r.get("kind") or "") for r in self.regions
                if not r.get("own_text")}
        return [g for g in KIND_GROUPS if g in here]

    # Every count below is about the WORK, so every one of them is about the
    # active boxes. Counting a hidden box would leave a page that is finished
    # sitting at "12 of 15 translated" for ever.
    @property
    def n_translated(self) -> int:
        return sum(1 for r in self.active if r.get("dst_text"))

    @property
    def n_ocr(self) -> int:
        return sum(1 for r in self.active if r.get("src_text"))

    @property
    def n_typeset(self) -> int:
        return sum(1 for r in self.active if r.get("layout"))

    @property
    def n_proofread(self) -> int:
        return sum(1 for r in self.active if r.get("proofread"))

    def status(self) -> str:
        n = len(self.active)
        if not n:
            # A page with no text once it has been checked is DONE, not an
            # error - nothing to translate, so it passes green. A page whose
            # every box is hidden is the same case: there is nothing to do.
            return "done" if self.detected else "pending"
        if self.n_translated == n:
            return "translated"
        if self.n_ocr:
            return "ocr"
        return "detected"


# The three groups the person deals in. One table, because what you can ask
# Find text to look for and what you can hide afterwards are the same question
# asked twice - "which of these three kinds of writing am I working with".
#
# A narration caption used to answer to the box for text outside bubbles, on the
# grounds that it stands outside a speech balloon. lee moved it: *"rename the
# firts check box to speach and nataion bubble"*. A caption is a box with
# dialogue in it - it is read in the reading order, translated as speech and
# typeset like speech - and grouping it with the loose text lying on the
# artwork put it with the one group whose boxes are the least like it.
#
# Anything the model invents a name for that is in none of the groups is kept:
# a box is worth more than a tidy vocabulary. The same rule holds for hiding -
# a custom text type is never hidden by these three.
# The three families, and the sub-types each one covers. The sub-types are no
# longer a fixed list - a person adds, renames and deletes their own - so this
# is only the SHAPE of the thing: which families exist, and what each one's
# undeletable default is called. `kinds.subs_of` answers the rest, from the
# open project. See kinds.py.
KIND_GROUPS = {f: (f,) for f in _kinds.FAMILIES}


def group_of(kind: str) -> str:
    """Which of the three families a kind belongs to.

    Never "" now. Every kind belongs to a family, including one whose sub-type
    has since been deleted - a box pointing at a sub-type that is gone still
    has to draw, still has to be cleaned, and still has to obey the switch
    that puts its family away.
    """
    return _kinds.family_of(kind or "")


#: `NO_SFX_MEDIA` and `detectable_kinds` used to live here: sound effects were
#: dropped from Find text on manhwa and manhua whatever the dialog said, so
#: that only a box a PERSON drew could be one.
#:
#: They are gone because the measurement under them is gone. The rule was
#: written on chapter 1: 82 sfx boxes, and of the 36 checked one at a time
#: **eighteen held no writing** -- sword blades, a face, two buildings,
#: clothing, a gold ornament, a leg, a bed, five thought-balloon tails. lee's
#: instruction followed from that number, and only from it:
#:
#:     *"shound affct shoud be sissable for the detector not the user
#:     only uswrs shoud be able to make sfx boxes for manhwa and manhua"*
#:
#: Everything built since was aimed at exactly those false positives -- the
#: character census (`_characters_in`: a box CRAFT reads no characters in is
#: art), the art veto, the stray-mark sweep. Re-measured on all 46 pages of
#: the chapter after them, every box cropped and looked at: **49 sound-effect
#: boxes, 47 hold real writing.** The two that do not are an architectural
#: ornament on page 22 and a gold braid on page 32 -- the same class as
#: before, 2 instead of 18. Four per cent, against the fifty the rule was
#: written for.
#:
#: Put to lee with that number, and he asked for the tick back. So this is
#: not a fourth answer to the old question, it is the same answer to a
#: different one: what was measured as unreliable has been measured again.
#: The Find text dialog's own tick decides, on every format, and it starts
#: UNTICKED -- so nothing appears on anybody's pages until they ask for it.
#: `only_kinds` is what enforces that tick, and always was.


#: How big a sound-effect box has to be before it is left off the run, as a
#: share of the page WIDTH, measured on the box's LONGEST SIDE.
#:
#: lee: *"i tested the clenner on them an the big one are always very bad while
#: the midium to small one always clean up nice so i wan to cut off the big
#: ones"*. So this is a CLEANING rule wearing a detection rule's clothes, and
#: that is worth being honest about. Nothing is wrong with these boxes AS
#: boxes -- measured over the 52 sound effects of a 46-page chapter, every one
#: of the sixteen biggest holds real writing, and the chapter's only two junk
#: boxes are its two SMALLEST. Size does not sort right from wrong. What it
#: sorts is what the cleaner can put back through the hole it makes.
#:
#: **Not a share of the page AREA**, which is what this was first written as.
#: lee: *"i domnt think ratio is a good ideo left go but set sizes insatd ...
#: because all the ages are not the same sizes"*. He is right and it is the
#: whole reason this constant reads the way it does: his pages are all 690
#: wide and run from 1591 to 3713 tall, because a webtoon is one strip cut
#: into pieces and where the cuts fall is arbitrary. Against the AREA, the
#: same effect is dropped on a short page and kept on a long one.
#:
#: Width is the stable dimension, so the bar is taken against it. As a
#: fraction rather than as raw pixels so that a chapter scanned at another
#: resolution behaves the same -- on lee's 690px pages this IS a set size, and
#: the number he picked is **300px**.
#:
#: The LONGEST side, not the height: 001#1 is 499x242, and wide-and-flat is
#: just as big a hole for the cleaner as tall-and-narrow.
BIG_SFX = 300 / 690      # 0.435 of the page width; 300px on lee's pages

#: ...AND A MANGA PAGE IS NOT ONE PANEL WIDE.
#:
#: lee, shown the tick in the dialog: *"can you swith teh manga version of this
#: to be something more appropriate to manga"*.
#:
#: The number above is a share of the PAGE, and it was measured on a webtoon,
#: where the page is a strip and **the strip is the panel**. So 0.435 of the
#: page means "an effect covering about two fifths of the panel it is drawn
#: in", which is the thing the cleaner actually chokes on: a hole that big in
#: one drawing.
#:
#: A manga page holds several panels across, so the same effect is a much
#: smaller share of the page and the bar walks straight past it. Measured over
#: the 23 pages of chapter 3 of 今日から悪女になります: **1 of 62 sound effects
#: reaches 0.435**. The tick is not doing the wrong thing on manga, it is
#: doing nothing.
#:
#: So the bar is re-expressed in the unit it was always about. Splitting those
#: pages into rows of near-white gutter and then into columns gives **75
#: panels, median width 0.56 of the page**, and 0.435 of a panel is
#:
#:     0.435 x 0.56 = 0.244 of the page width
#:
#: which catches ten of the 62 -- バチャバチャバチャ across a splash, ギョロ
#: ギョロ down a cloak, ザバボーン over water, ひゃああ over a face, ザァァ and
#: アアア over a fence. Cropped, every one of the ten is a painted effect laid
#: across drawn artwork, which is the case lee described; the four just under
#: the bar (0.214-0.239) are smaller effects on plainer ground.
#:
#: Measured on nothing but manga, so manga is the only thing it moves. Manhua
#: keeps the webtoon number because a manhua is read as a strip too.
BIG_SFX_BY_MEDIUM = {"manga": 0.244}


def big_sfx_share(medium: str | None) -> float:
    """How big a sound effect may be on THIS format. See `BIG_SFX_BY_MEDIUM`."""
    return BIG_SFX_BY_MEDIUM.get(medium or "", BIG_SFX)


def big_sfx(found, page_width: float, share: float = BIG_SFX):
    """Drop the sound-effect boxes too big for the cleaner to redraw well.

    Only sound effects. A caption plate or a wide balloon can cross most of a
    webtoon page and clean perfectly -- it is paper with type on it, which is
    the case the cleaner is best at.
    """
    if not page_width or share <= 0:
        return list(found)
    bar = share * page_width
    out = []
    for r in found:
        bb = getattr(r, "bbox", None) or (0, 0, 0, 0)
        big = max(bb[2], bb[3]) >= bar
        if big and group_of(getattr(r, "kind", "")) == "sfx":
            continue
        out.append(r)
    return out


def only_kinds(found, kinds):
    """The regions whose FAMILY the person actually ticked.

    The Find text dialog asks about the three main types, and a box belongs to
    one of them however finely it has been labelled since - so this is a
    question about families, not about kinds. It always was: a caption box
    used to answer to the balloon tick because a caption is a box with
    dialogue in it, and a caption is a sub-type of balloon now, which is the
    same answer arrived at from the model rather than from a list.
    """
    want = {k for k in (kinds or []) if k in _kinds.FAMILIES}
    if not want:
        return found
    return [r for r in found if group_of(r.kind) in want]


#: A page that took longer than this says so. A run that is behaving stays
#: quiet; the routes cost 2.9 to 14.3 s a page on the chapter they were
#: measured on, so this is comfortably above all four and well under the
#: 50 seconds lee timed.
SAY_PAGE_OVER = 20.0


def _say_page_cost(proj, page, t0, n, load=0.0):
    """One line for a page that took too long, naming the route and the size.

    Not a total: a total is what lee already has, and it cannot be acted on.
    Three things make this one actionable where a total is not.

    THE ROUTE says which of the four cards is spending it.

    THE SIZE says whether it is spending it reasonably - detection scales with
    AREA, so 960x1399 at 4.7s and 2880x4197 at 21.8s are the same speed, and a
    big scan taking a minute is arithmetic rather than a fault.

    THE LOAD is separate because of what lee's four numbers look like together:
    50, 58 and 60 seconds against 4.7, 9.9 and 12.7 measured here. That is not
    one pipeline being slow, and it is not a multiplier - it is the SAME 47
    seconds added to every route. A cost that does not care which detector ran
    belongs to something they all share, and getting the page off the disk is
    the first candidate.
    """
    import sys
    took = time.time() - t0
    # THE FIRST PAGE OF A PROCESS ALWAYS SAYS SO, however fast it was.
    #
    # lee: *"koren detector is taking 13 second per page"*. Thirteen is under
    # the bar, so a whole chapter ran and left nothing on record at all -
    # not the route, not the page size, not the machine line. The bar exists
    # so a run that behaves stays quiet, and one line at the top of a run is
    # not noise: it is the baseline every later line is read against, and it
    # is the only line there is when nothing is slow enough to complain.
    if took + load < SAY_PAGE_OVER and _say_page_cost._machine_said:
        return
    route = proj.route_name()
    im = getattr(page, "image", None)
    size = "%dx%d" % (im.shape[1], im.shape[0]) if im is not None else "?"
    # ...and WHERE IN THE ROUTE it went, when the route can say. "Thirteen
    # seconds" cannot be acted on; "mask 11.4s, boxes 1.2s" names the model
    # to go and look at. See `detect/webtoon.LAST_SPLIT`.
    split = ""
    try:
        from .detect import webtoon as _wt
        if proj.route_key() in ("webtoon_ko", "webtoon_zh") and _wt.LAST_SPLIT:
            split = "  [" + _wt.LAST_SPLIT + "]"
    except Exception:
        pass
    line = ("find text  %-14s %-11s %-22s load %5.1fs  detect %6.1fs  "
            "total %6.1fs  %d boxes%s"
            % (os.path.basename(getattr(page, "source_path", "") or "page"),
               size, route, load, took, took + load, n, split))
    if not _say_page_cost._machine_said:
        # To the CONSOLE as well as the file. lee pasted the console lines
        # back by hand, which means the console is what he actually reads -
        # a machine line that only lands in a file he has to hunt for is a
        # diagnosis nobody collects.
        print(_machine_line(), file=sys.stderr, flush=True)
    print(line, file=sys.stderr, flush=True)
    # SAID, now that it has been said. The flag used to be set inside the
    # file-writing block below, which returns early for a project with no
    # folder - so on one of those it was never set, and every page said the
    # machine line again. It did not show while only slow pages spoke; the
    # moment the FIRST page of a run always speaks, "the first" has to be a
    # thing this can actually tell.
    first, _say_page_cost._machine_said = \
        not _say_page_cost._machine_said, True
    # ...AND INTO A FILE, because the console is the one place lee never
    # looks - the app is started by a double-click on Windows and the window
    # behind it might as well not exist. `out/slow-pages.txt` sits in the
    # project folder, so it can be read after the run, sent, or looked at
    # over the bridge. Append rather than write: the pattern ACROSS a run is
    # the diagnosis (one slow page is a load, every page slow is the machine).
    out = getattr(proj, "output_dir", "")
    if not out:
        return
    try:
        with open(os.path.join(out, "slow-pages.txt"),
                  "a", encoding="utf-8") as f:
            if first:
                f.write(time.strftime("%H:%M:%S  ") + _machine_line() + "\n")
            f.write(time.strftime("%H:%M:%S  ") + line + "\n")
    except OSError:
        pass                     # a full disk must not fail the page


_say_page_cost._machine_said = False


def _machine_line() -> str:
    """One line about the machine, above the first slow page of a process.

    Why it exists: lee's pages showed comic-text-detector's forward pass at
    65-72 seconds against 2.5 on the machine it was measured on - a 27x gap on
    ONE runtime while his torch models ran at ordinary speed. Profiled, the
    cost is the mask decoder's ConvTranspose stack, which OpenCV runs through
    its own GEMM - fast under AVX2, and grim without it. Whether his CPU HAS
    AVX2 is therefore the whole diagnosis, and it is a fact about the machine
    that no amount of timing pages will surface on its own.

    The GEMM number is the calibration: it says how fast a core actually is
    at the exact kind of arithmetic a convolution spends its life in, in a
    unit that can be compared across machines.
    """
    bits = []
    try:
        bits += ["opencv %s" % cv2.__version__,
                 "threads %d" % cv2.getNumThreads(),
                 "cores %d" % (os.cpu_count() or 0)]
        # The one call that answers the question. A starred feature is one
        # this CPU actually has at runtime: "*AVX2" present means the fast
        # convolutions are available, absent means they are not and the
        # 27x is explained.
        if hasattr(cv2, "getCPUFeaturesLine"):
            feats = cv2.getCPUFeaturesLine()
            for name in ("AVX2", "AVX512-SKX", "AVX", "NEON"):
                if "*" + name in feats:
                    bits.append(name)
            bits.append("no-AVX2" if "*AVX2" not in feats else "")
            bits = [b for b in bits if b]
    except Exception:
        pass
    try:
        a = np.random.rand(512, 512).astype(np.float32)
        t0, n = time.time(), 0
        while time.time() - t0 < 0.3:
            a = a @ a * 0 + a       # keep values finite, keep the GEMM
            n += 1
        bits.append("gemm %.1f gflops"
                    % (n * 2 * 512 ** 3 / (time.time() - t0) / 1e9))
    except Exception:
        pass
    # The line carries its own advice when the version IS the diagnosis.
    # OpenCV 5.0's new dnn engine runs this app's detector 2.4x slower than
    # 4.11 - measured, same page, same machine: 5.7s against 2.5s - and every
    # number on the detector cards was measured on 4.x. A person staring at a
    # slow page should not need a second person to translate "opencv 5.0.0"
    # into the one command that fixes it.
    try:
        if int(cv2.__version__.split(".")[0]) >= 5:
            bits.append('(opencv 5 is 2.4x slower here - run: pip install '
                        '"opencv-contrib-python-headless>=4.8,<5")')
    except Exception:
        pass
    return "machine    " + "  ".join(bits)


def token_state(tok: str | None) -> str:
    """What the settings screen may say about a saved cleaner token.

    "" - nothing saved. "set" - a real one. "placeholder" - the CHANGE-ME
    example that every *_clean_modal.py carries in its header comment.

    The third state exists because it cost a week. The field reported "(saved)"
    for anything non-empty, the example token IS non-empty, and so a project
    whose token had never actually been filled in looked exactly like a
    configured one - while the endpoint answered 401 to every call and the
    editor quietly drew a Telea smear instead of saying so.

    The token itself never leaves the server: only which of the three.
    """
    t = (tok or "").strip()
    if not t:
        return ""
    return "placeholder" if t.upper().startswith("CHANGE-ME") else MASK


# The formats that are DELIVERED as one long strip and have to be cut into
# pages before anything else can run. Manga is not one of them: a manga chapter
# arrives as pages, and lee's arrive as a handful of tall composite pages that
# passed every one of `strip.looks_sliced`'s four tests by coincidence - same
# scanner, same settings, so same width and same height to the pixel.
#
# lee: *"the page fixing shoud only be allied if manhwa is selected"*, and then
# *"do it foe manhua too"*. Both are webtoon formats and both are delivered as
# a strip; manga is the one that is not, and manga is the one that was being
# re-cut behind his back.
STRIP_MEDIA = {"manhwa", "manhua"}

#: The thinnest a cut piece may be, in rows. A sliver is not a page, and a
#: click sixteen rows from the top of a strip is a mis-click rather than a
#: decision. It applies at the edges AND between two cuts: a fourteen-row page
#: in the middle of a chapter is the same mistake as one at the end of it.
SLIVER = 16


def _part_suffix(k: int, n: int = 1) -> str:
    """`a`, `b`, ... for the k-th of n pieces of a cut page.

    The letter is what makes `012a` and `012b` sort where `012` sorted, which
    is the only thing holding a chapter in reading order between the cut and
    `renumber_pages`. So it has to sort, and `a, b, ... z, aa` does NOT: `aa`
    comes before `b` in every sort there is. The width is fixed by how many
    pieces there are instead - one letter up to 26, two past it - which keeps
    `a`/`b` for the ordinary cut and stays in order for a page nobody should
    have cut into thirty.
    """
    width = 1
    while 26 ** width < max(1, int(n)):
        width += 1
    s, k = "", int(k)
    for _ in range(width):
        s = chr(ord("a") + k % 26) + s
        k //= 26
    return s


# The cleaner's address, built in.
#
# lee, having deployed it: *"make it built in the app and not a thing i have to
# add to the app"*. It is a PUBLIC address - the token beside it is what guards
# the endpoint - so the app can carry it and one less thing gets pasted into a
# new project. Anything typed into Settings still wins; this is only what an
# empty box means.
#
# The token is deliberately NOT here. Shipping that would let anyone holding a
# copy of the app spend the GPU time it pays for, which is a bill nobody can
# cap - see `test_nothing_that_ships_looks_like_a_key`, which is the guard that
# says so.
CLEAN_URL = ("https://leemarvinbernard--mangatl-clean-lama"
             "-cleaner-clean.modal.run")

class Project:
    def __init__(self, input_dir: str | None, output_dir: str):
        self.input_dir = os.path.abspath(input_dir) if input_dir else ""
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.state_path = os.path.join(self.output_dir, "project.json")
        # Saving is coalesced onto one background thread - see `save_soon`.
        self._save_lock = threading.RLock()   # held while writing the file
        self._dirty_lock = threading.Lock()   # held only to read/set the flag
        self._saver = None
        self._dirty = False
        self.pages: list[PageState] = []
        self.ctx = SeriesContext()
        self.settings = {
            "font": "", "fonts": {}, "uppercase": False,
            # ON. The typesetter may stand a covered character in for one
            # the chosen face has no glyph for. lee, of the switch: *"this
            # shoud be on by default"*.
            #
            # It went in OFF, because a silent swap is a silent edit to what
            # the page says, and lee wanted to SEE a face that was short of a
            # glyph rather than have it papered over. What that costs in
            # practice is a flag on every box holding a character no comic
            # face has ever carried - a music note, a heart, a full-width
            # bracket - which is most pages, and none of them are wrong. So
            # the default is the one that typesets, and turning it off is how
            # you ask to be told instead. See `TypesetConfig.substitutes`.
            "substitutes": True,
            # Translating by hand. With this on, the three steps that ask an
            # AI for words - Read text, Translate, Proofread - are greyed and
            # say so if pressed: the words are coming from a file or from the
            # panel instead. A MODE somebody chose, not a lock the app
            # imposed, which is the whole difference from the step gates lee
            # had removed. lee: *"the manual tranlat button should grey out
            # the read text translate and profread"*.
            "manual_translate": False,
            "min_font": 12, "max_font": 34, "compact_margin": 0.60,
            "medium": "manga", "target": "en", "ocr_engine": "auto",
            # Written out rather than left to be inferred. These two used to
            # default to "auto", which the screen showed as "Same as the source
            # material" - a phrase in the box where the answer should be.
            # lee: *"remove all instandt of same as ... it shud just pre fill
            # it with teh potion"*. "auto" is still READ, because old projects
            # are full of it, and it still means exactly this.
            "source": "ja",
            # HOW FINELY the page is cut up before it goes to the AI reader is
            # not a question any more. lee: *"make teh zoomed ... teh only
            # option for the read text ... it sho9ud just happen in teh
            # backgroud"*. A close-up of each box won on both formats it was
            # ever scored on - see `ocr.detail_for` for the numbers - and cost
            # a third fewer image tokens winning.
            #
            # The key stays, empty, and is written but never read. A project
            # saved by an older copy of the app has a word in it, and a key
            # that vanishes from the sheet is a key the next save deletes.
            "ocr_detail": "",
            # Whether Read text also says what KIND each box is - a thought
            # balloon, a burst, a caption box, a big or a small sound effect.
            # lee: *"alos coun;t read text do the same thing after its done
            # reading teh text?"*
            #
            # OFF by default. lee: *"also make it off by defualt"*, and it is
            # the way round this belongs: it is a REQUEST, not free - one more
            # turn per page, carrying a 768px picture and a 1,379-token prompt
            # - and a setting that spends money without being asked for is one
            # people find out about from their bill.
            #
            # It also CHANGES boxes, which is the other reason. Read text was
            # cut back to reading and two deletions at lee's own request:
            # *"make it so that read text only read teh etxt and not modify
            # boxes exapt for..."*. A pass that relabels every box on the page
            # belongs behind a switch somebody threw.
            #
            # Only consulted on the AI path. The offline reader's whole promise
            # is no key, no network and no coins, and quietly making a request
            # on its behalf would break it - so an offline chapter is read
            # offline and keeps the types the detector gave it. See
            # `editor.labels_boxes`, which is the one place both halves of that
            # question are asked.
            "label_kinds": False,
            # WHO reads: "ai" (the vision model) or "offline" (manga-ocr on
            # this computer, easyocr for Korean and Chinese). Picked on the
            # Read text dialog, on two cards, not on the settings screen -
            # lee: *"add a selecteabe tile for mangaorc and ai for the read
            # text like teh find text"*.
            #
            # The AI is the default and stays it. Measured on lee's chapter 3,
            # 23 pages, 225 boxes: reading a close-up per box, the AI and
            # manga-ocr agree on 96% of the dialogue. What each is FOR shows
            # in the other 4%: manga-ocr never files a line under the wrong
            # box, and the AI is the only one of the two that can read a
            # painted sound or settle a name from the rest of the page.
            "ocr_reader": "ai",
            "direction": "rtl",    # rtl | ltr ("auto" still read, see above)
            "detector": "comictext", "weights": "", "text_weights": "",
            "auto_kind": True,     # comic-text-detector: label each box bubble/outside/narration
            # Half of what came back as a sound effect on lee's chapter 1 had
            # no writing in it: 18 of 36 were boxes on sword blades, faces,
            # buildings, clothing and thought-balloon tails. Asking the second
            # detector before keeping one removes 16 of those 18 and costs one
            # real hand-drawn effect. See `comictext._seen_by`.
            #
            # It HAD a switch on the Settings page. lee: *"remove this"* - and
            # he is right, because sound effects are not offered at all on the
            # webtoons now, so on the format the veto was measured for the
            # switch controls something that is filtered out either way. The
            # setting is still read, so a project.json that turned it off is
            # still obeyed and turning it back into a tick is one line of HTML.
            "sfx_second_opinion": True,
            # There was an "ai_boxes" setting here - a pass that showed the
            # numbered page to the AI at Find text and let it judge the boxes.
            # It is gone; lee: "nvm remove it its pretty bad remove the ai".
            # Find text is measurement only again, and a project.json saved with
            # the old key simply carries a setting nothing reads. Nothing about
            # the AI READER or the translator changed - those are the useful
            # ones and they are untouched.
            # A webtoon does not arrive as pages. It is drawn as one strip and
            # the site that serves it slices that strip into tiles of a fixed
            # height, counting pixels and never looking at the artwork - on
            # lee's chapter 1, 38 of the 104 cuts went through the typesetting.
            # So when a chapter arrives looking like that it is joined back up
            # and cut again at the gutters, on upload, without being asked.
            # See `restitch_if_sliced` and `strip.py`.
            "restitch_strips": True,
            # How tall a page should be, as a MULTIPLE OF ITS WIDTH.
            #
            # These were 2400 and 6000 raw pixels, which meant nothing to
            # anybody looking at the box - lee: *"change teh value to be a more
            # understandable metrics"*. A multiple is the honest unit for both
            # of them. It reads as a shape rather than a measurement, it means
            # the same thing on a 690px strip and a 1600px one, and the ceiling
            # is genuinely about shape: the detector letterboxes a whole page
            # into 1024px, so what costs you text is how many times taller than
            # wide the page is, not how many pixels it has.
            #
            # 3.5 and 8.5 are 2400 and 6000 on lee's 690px-wide chapter, which
            # is where those two numbers came from in the first place.
            "strip_tall": 3.5,
            "strip_tall_max": 8.5,
            "export_dir": "", "export_name": "pages",
            "backend": "anthropic", "base_url": "",
            "model": "claude-sonnet-5", "api_key": "",
            # AI cleaning (hosted manga inpainter): off | hard | all
            "ai_clean": "off", "clean_url": CLEAN_URL, "clean_token": "",
            # ...and WHICH eraser the endpoint should use: one deploy of
            # `lama_clean_modal.py` serves both. See `editor.CLEAN_MODELS`.
            "clean_model": "anime-lama",
            # ...and whether the text detector is used WHILE cleaning: asked
            # what the writing is before erasing (`inpaint._reader_ink`), and
            # asked again of the finished plate to catch what was missed
            # (`inpaint._reread`). lee, with two crops of a cleaned balloon
            # that still plainly says what it said: *"can you fix the issue of
            # the text not fully getting clenned off boxes"*, and then, with a
            # sound effect whose box came back as a rebuilt rectangle of
            # screentone: *"see how i can see the lines of teh clenner"*. On by
            # default: it costs two forward passes on a page being cleaned and
            # needs nothing the project has not already got.
            "clean_reread": True,
            # The model each step runs on, and the WHOLE of what it runs on:
            # there is no project-wide engine behind these any more. There were
            # two of them - a "Claude model" menu and a "Translation engine"
            # menu - and between them they answered the same question these
            # keys answer. lee: *"remove teh recomened tab and the translation
            # engine and the coins shou look at what ai is in each of teh step
            # to use to bill"*. Two places to set one thing is two places for
            # them to disagree, and the coin price could only quote one of the
            # two.
            #
            # Reading and translating happen on every page and come set up for
            # Google AI Studio, because that is what they are worth doing on: a
            # cheap fast vision model reads every page and a mid-tier one
            # writes the English, which is where nearly all the cost of a
            # chapter is. lee: *"these shoud be teh default"*.
            #
            # Proofreading runs once at the end, so the good model only has to
            # be paid for there. lee: *"i wan to keep sonnet 5 for
            # proofrreding"*. It used to be left BLANK to mean "the project's
            # engine", and blank is no longer a thing that can mean anything -
            # a step with no model would be a step the price screen could not
            # name. See `editor.STEP_DEFAULTS`, which these have to agree with.
            # Find text's AI option. Same cheap vision model as the reader:
            # one call per page, and the rectangle it returns is measured
            # again against the ink either way.
            "ocr_model": "gemini-3.5-flash-lite", "ocr_backend": "gemini",
            "ocr_base_url": "", "ocr_key": "",
            "translate_model": "gemini-3.7-flash", "translate_backend": "gemini",
            "translate_base_url": "", "translate_key": "",
            "proofread_model": "claude-sonnet-5", "proofread_backend": "anthropic",
            "proofread_base_url": "", "proofread_key": "",
            # A box the reader found nothing in but marks - `!`, `……`, `?!`,
            # `♡` - is deleted when Read text finishes. lee: *"make it on by
            # defaut"*. See `editor.symbol_only_boxes` for the three kinds of
            # box this never touches whatever they read.
            "drop_symbol_only": True,
            # ...and a box whose reading is PART of an overlapping box's
            # reading is the same writing answered twice - 001's painted 今
            # inside 今日, 017's そんなので足りるかと over 足りるかよ. The
            # fragment goes and the box that holds all of it stays. See
            # `editor.read_twice_boxes`.
            #
            # This said "no switch on the settings page ... not a question
            # worth asking" and it was wrong, twice over. It ran on every read
            # with nowhere to stop it, and the sibling below ran the same way:
            # a comparison of three readers over one chapter lost a box on
            # page 005 that plainly reads 슈, because one reader gave up on it
            # and the drop took it at its word. Both switches are back on the
            # settings page. A pass that deletes somebody's work is always a
            # question worth asking.
            "drop_read_twice": True,
            # ...and a box the reader found NOTHING in at all. lee: *"if it
            # return nothing then delete that box that probly mena that teh
            # box was bad anyways"*. Guarded against a reader outage -- see
            # `editor.empty_boxes`, which deletes nothing on a page where
            # every box came back empty. That guard catches a reader that dies
            # on a WHOLE page and not one that shrugs at a single box, which
            # is what the switch is for.
            "drop_empty": True,
            # DBNet read both ways plus DB++/COO, instead of
            # comic-text-detector's own block head. OFF by default and off on
            # any machine without both checkpoints -- see `two_specialists`.
            # Measured on 23 pages of manga: 3 missed and 4 junk against 5 and
            # 13, at 9.9 s/page against 2.9. Nothing about it was measured on
            # a manhwa.
            "two_specialists": False,
            # One YOLO12 detector trained on AnimeText finds every box, COO
            # says which are paint, comic-text-detector supplies the ink. ON
            # by default - lee: *"make anime text teh default detector"* -
            # and still off without the 53MB checkpoint or off manga: the
            # `animetext` guard falls back to comic-text-detector, so a
            # machine without the file loses nothing. Measured on 23 pages:
            # every line of dialogue and every caption found, zero junk, at
            # 14.5 s/page. See `animetext`.
            "animetext": True,
            # A YOLOv8 trained on WEBTOON pages for the balloons, with
            # comic-text-detector for the ink. ON by default, which is how a
            # manhwa and a manhua get a different default route to a manga
            # without a per-format defaults table: `webtoon_ko()` asks
            # `why_not_webtoon_ko` asks the medium, so on a manga the flag is
            # set and the route is guarded off and AnimeText below wins, and
            # on a strip it is asked first and wins. The settings page reaches
            # the same answer the same way -- `ROUTE_MEDIA` in project.js.
            #
            # Off without the 12MB checkpoint, like the rest, so a machine
            # that has not downloaded it falls through to what it had.
            "webtoon_ko": True,
            # The same job trained on a Chinese chapter, as a second opinion.
            # NOT a language split: it finds slightly MORE on Korean pages
            # than the Korean one does. See `detect/webtoon.py`.
            "webtoon_zh": False,
            # THE REORDERED PIPELINE. Detect, read every box, THEN name it,
            # instead of asking a second neural net at detection time what a
            # box is. Free: the OCR runs on every region anyway, sound
            # effects included, and the answer was being thrown away. OFF by
            # default and manga only -- the rule is written from Japanese
            # typography and its thresholds have not been swept against real
            # OCR output. See `readkinds`.
            "kind_from_text": False,
            # The Manga109 YOLO26 segmenter for the boxes and the balloons,
            # DB++/COO for the paint, comic-text-detector's seg head for the
            # ink. OFF by default and off without the 23MB checkpoint -- see
            # `manga_segmenter`. Measured on the same 23 pages: 7 missed and 3
            # junk at 11 s/page, with ten more boxes of dialogue correctly
            # inside a balloon. Nothing about it was measured on a manhwa.
            "manga_segmenter": False,
            # THE STORY SWITCHES. lee: *"add a story setting that allow the
            # user ti turn the story thing off, and to tun what the ai detects
            # with check boxes"*.
            #
            # `story` off means the synopsis, the character sheet and the
            # glossary are neither sent with a page nor added to by the reply.
            # The sheets themselves are left alone - switching it back on
            # finds them as they were.
            #
            # All four default TRUE, which is what every project did before
            # they existed, so nothing changes for a chapter already in
            # progress.
            "story": True,
            "learn_characters": True, "keep_honorifics": True,
            "retype_kinds": False,
            "learn_terms": True,
            "name_speakers": True,
            # ONE KEY PER SERVICE, not one per step.
            #
            # A key is a fact about the provider, not about the step: the same
            # Google key that reads the page translates it. Three steps meant
            # typing the same key three times and, worse, meant a key could be
            # right in one box and stale in another with nothing on screen to
            # say which of the two a run would use. The per-step boxes above
            # are still READ - an old project.json that has not been saved
            # since still works, see `migrate_keys` - and nothing writes them.
            "key_anthropic": "", "key_gemini": "", "key_openrouter": "",
        }
        # A new project starts with the sub-types every project starts with -
        # the same list `load` brings an old one up to. Doing it only on load
        # meant a chapter you had just made had three families and nothing
        # under them until the editor was restarted.
        self.settings["custom_kinds"] = _kinds.migrate(None, seed=True)
        self.settings["kinds_seeded"] = True
        self.settings["kinds_seeded_keys"] = sorted(_kinds.PRELOAD_KEYS)
        _kinds.use(self.settings["custom_kinds"])
        self.job = {"running": False, "label": "", "done": 0, "total": 0,
                    "error": "", "cancel": False, "cancelled": False}
        self.lock = threading.Lock()
        self._img_cache: dict[int, np.ndarray] = {}
        self._img_lock = threading.RLock()
        self._load_or_scan()

    @property
    def medium(self) -> str:
        return self.settings.get("medium") or "manga"

    @property
    def rtl(self) -> bool:
        """Manga reads right-to-left; manhwa and manhua left-to-right.

        The medium sets the default, but some series break the rule - a
        Japanese webtoon reads left-to-right - so it can be overridden.
        """
        from .translate import MEDIA
        d = self.settings.get("direction") or "auto"
        if d == "rtl":
            return True
        if d == "ltr":
            return False
        return MEDIA.get(self.medium, MEDIA["manga"])["rtl"]

    @property
    def source_code(self) -> str:
        """What language the pages are written in - chosen explicitly, or
        the medium's usual one. Drives the OCR."""
        s = (self.settings.get("source") or "").strip()
        if s and s != "auto":
            return s
        from .translate import MEDIA
        return MEDIA.get(self.medium, MEDIA["manga"])["code"]

    # ------------------------------------------------------------- persistence
    def _load_or_scan(self) -> None:
        if os.path.exists(self.state_path):
            try:
                self.load()
                if self.pages:
                    return
            except Exception:
                # A state file that cannot be read is a state file that must
                # not be REPLACED. `rescan` on an empty input folder saves an
                # empty project, and that is how one unreadable key turns into
                # a lost chapter - which is exactly what happened when a
                # transient attribute was set on the series context and
                # written into the file. Say so, and leave the file alone.
                traceback.print_exc()
                print("project.json could not be read (%s). Leaving it where "
                      "it is rather than saving over it." % self.state_path)
                self.pages = []
                return
        self.rescan()

    def rescan(self) -> None:
        """Pick up the images in the input folder, keeping any work already
        done on pages we have seen before."""
        known = {p.path: p for p in self.pages}
        self.pages = []
        if not self.input_dir or not os.path.isdir(self.input_dir):
            self.save()
            return
        for p in list_images(self.input_dir):
            if p in known:
                self.pages.append(known[p])
                continue
            img = imgio.imread(p)
            h, w = (img.shape[:2] if img is not None else (0, 0))
            self.pages.append(PageState(path=p, name=os.path.basename(p),
                                        width=w, height=h))
        self.save()

    # ------------------------------------------------------------- input files
    def use_folder(self, path: str) -> int:
        """Point the project at a folder of pages already on this machine."""
        path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        self.input_dir = path
        self.pages = []
        self._img_cache.clear()
        self.rescan()
        return len(self.pages)

    def upload_dir(self) -> str:
        d = os.path.join(self.output_dir, "input")
        os.makedirs(d, exist_ok=True)
        return d

    def put_the_last_chapter_away(self) -> int:
        """Empty the upload folder before a new chapter is loaded into it.

        lee, having loaded a folder of manga: *"soem pages that wrere not i the
        folder are showing uo when i upload teh foler"* - his list held his
        `024.jpg … 039.jpg` AND a run of `page0xx` files, which are what the
        webtoon re-cut wrote there for the chapter before.

        Every chapter uploads into the same `input/` folder and nothing ever
        emptied it. `clear()` forgets the PAGES, which is a different thing
        from the FILES: anything that lists the folder afterwards - reopening
        the project, a re-cut, a rescan - finds every file every chapter ever
        put there and calls them all pages.

        So the folder is emptied when a chapter is put down, and emptied by
        MOVING: into `input-previous`, one generation, replacing the one before
        it. Deleting would be the tidy answer and the wrong one - the re-cut
        pages and the halves of anything you split exist nowhere else. Keeping
        every generation would be the safe answer and also the wrong one, on a
        chapter that is a third of a gigabyte.

        Returns how many files were moved.
        """
        d = os.path.join(self.output_dir, "input")
        if not os.path.isdir(d) or not os.listdir(d):
            return 0
        prev = os.path.join(self.output_dir, "input-previous")
        shutil.rmtree(prev, ignore_errors=True)
        try:
            shutil.move(d, prev)
        except OSError:
            return 0
        os.makedirs(d, exist_ok=True)
        return sum(len(f) for _r, _dirs, f in os.walk(prev))

    # --------------------------------------------------------- webtoon strips
    def strip_width(self) -> int:
        """How wide this chapter's pages are.

        Every tile of a sliced strip is the same width - `looks_sliced` will
        not say yes otherwise - so the first one that has a width is the
        chapter's width. Falls back to the width the two defaults were measured
        on, so a project with no pages still gets the numbers it expects.
        """
        for pg in self.pages:
            if pg.width:
                return int(pg.width)
        return 690

    def strip_heights(self) -> tuple[int, int]:
        """The target and the ceiling, in pixels, for THIS chapter.

        Stored as multiples of the page width and turned into pixels here,
        which is the only place that knows how wide the pages are.
        """
        w = self.strip_width()
        tall = float(self.settings.get("strip_tall") or 0) or 3.5
        top = float(self.settings.get("strip_tall_max") or 0) or 8.5
        # A ceiling under the target is somebody's typo, and taken literally it
        # marks every page as having run over. The target wins.
        top = max(top, tall)
        return max(600, int(round(w * tall))), max(1000, int(round(w * top)))

    def restitch_if_sliced(self, force: bool = False) -> dict:
        """Put a sliced webtoon back together and cut it at the gutters.

        Runs by itself when a chapter finishes loading, because the tiles a
        webtoon site serves are not pages: they are the strip chopped every
        so many pixels by something counting, straight through balloons and
        through the typesetting inside them. Half a word on one file and half on
        the next cannot be read, cannot be cleaned, and has nowhere to put the
        English.

        It does nothing unless `looks_sliced` is sure - see `strip.py` for how
        narrow that test is - and nothing at all once there is work on the
        pages. Having a chapter you had already found boxes on, cleaned and
        typeset rearranged underneath you would be far worse than the problem
        being solved.

        Returns {} when it did not run. Otherwise a report: how many pages
        before and after, and how many had to be cut through ink because no
        gutter existed within the ceiling.
        """
        from . import strip as _strip

        if not force and not self.settings.get("restitch_strips", True):
            return {}
        # ...and not unless the chapter IS a webtoon.
        #
        # `looks_sliced` is narrow, and it was still not narrow enough: lee's
        # manga chapter arrives as a handful of tall composite pages, uniform
        # in size because they came out of the same scanner at the same
        # settings, and that is four of the four tests. A chapter re-cut into
        # forty pages is not a small surprise.
        #
        # The format is the one fact that settles it, and the person has
        # already told us: lee, on the strip fixer, *"shoud only be applied if
        # manhwa is selected"*. A page format is not a strip and never was.
        if not force and not STRIP_MEDIA.intersection({self.medium}):
            return {}
        if any(pg.detected or pg.regions or pg.typeset or pg.cleaned
               for pg in self.pages):
            return {}
        tiles = [pg.path for pg in self.pages]
        sizes = [(pg.height, pg.width) for pg in self.pages]
        # Two signatures of a slicer. Tiles all one height is a slicer counting
        # pixels (every Korean site so far). Tiles of many heights whose seams
        # still run through the drawing is a slicer with some other rule - the
        # manhua in lee's `Manhua/` folder, 41 tiles from 828 to 2350px tall,
        # cut through a line of dialogue and a painted 符. lee: *"this dont
        # work for manhua"*. The second test reads the pictures, so it is
        # asked only when the first has said no.
        if not (_strip.looks_sliced(sizes)
                or _strip.looks_sliced_unevenly(sizes, tiles)):
            return {}

        target, ceiling = self.strip_heights()
        own = os.path.abspath(self.input_dir or "") == os.path.abspath(
            os.path.join(self.output_dir, "input"))
        if own:
            # The tiles are in our own upload folder, so the pages can replace
            # them where they stand and everything that reads `input_dir` -
            # rescan, adding more pages later - carries on unchanged. The tiles
            # move down into a sub-folder rather than being deleted:
            # `list_images` only looks at the top level, so they stop counting
            # as pages while staying exactly where they were put.
            out = self.input_dir
            keep = os.path.join(out, "tiles")
            os.makedirs(keep, exist_ok=True)
            moved = []
            for t in tiles:
                dest = os.path.join(keep, os.path.basename(t))
                try:
                    shutil.move(t, dest)
                except OSError:
                    continue
                moved.append(dest)
            tiles = moved
        else:
            # Somebody else's folder. Nothing in it is touched: the pages are
            # written beside the project and the project looks there instead.
            out = os.path.join(self.output_dir, "strip")
            shutil.rmtree(out, ignore_errors=True)

        rep = _strip.restitch(tiles, out, target=target, ceiling=ceiling)
        if len(rep.get("pages") or []) < 2:
            # It did not come back with a chapter. Put the tiles back and leave
            # the project exactly as it was found.
            if own:
                for name in rep.get("pages") or []:
                    try:
                        os.remove(os.path.join(out, name))
                    except OSError:
                        pass
                for t in tiles:
                    shutil.move(t, os.path.join(out, os.path.basename(t)))
                shutil.rmtree(os.path.join(out, "tiles"), ignore_errors=True)
            else:
                shutil.rmtree(out, ignore_errors=True)
            return {}

        rep["before"] = len(self.pages)
        self.input_dir = out
        self.pages = []
        self._img_cache.clear()
        self.rescan()
        rep["after"] = len(self.pages)
        return rep

    def add_uploaded(self, name: str, data: bytes) -> int:
        """Returns the index of the page, or -1 if the file was unusable."""
        """Store a file the browser sent us and add it as a page."""
        name = os.path.basename(name).replace("\\", "_")
        if not name.lower().endswith(tuple("." + e for e in IMAGE_EXTS)):
            return -1
        d = self.upload_dir()
        dest = os.path.join(d, name)
        if any(p.path == dest for p in self.pages):
            # Same filename as a page already loaded, but a different file:
            # keep both rather than silently replacing one with the other.
            stem, ext = os.path.splitext(name)
            n = 2
            while any(p.path == os.path.join(d, f"{stem} ({n}){ext}")
                      for p in self.pages):
                n += 1
            name = f"{stem} ({n}){ext}"
            dest = os.path.join(d, name)
        with open(dest, "wb") as fh:
            fh.write(data)
        img = imgio.imread(dest)
        if img is None:
            os.remove(dest)
            return -1
        # Appending must never discard pages already in the project - the
        # "Add files" button relies on that.
        if not self.input_dir:
            self.input_dir = d
        h, w = img.shape[:2]
        # Appended in the order they were sent. Re-sorting the whole list by
        # name here used to scatter newly added pages among the old ones, so
        # you would add three pages and be looking at something else.
        self.pages.append(PageState(path=dest, name=name, width=w, height=h))
        self._img_cache.clear()
        return len(self.pages) - 1

    def rename_page(self, i: int, name: str) -> str:
        """Give a page a new filename. Returns "" on success, or the reason.

        lee: *"if i right clcik on one of these tabs i shou dhave the option to
        rename the file"*.

        The FILE moves, not just the label - the name in the list is the name on
        disk and they must not come apart. The extension travels with it: what a
        page is called has nothing to do with what format it is in, and a page
        renamed to "cover.txt" is a page the reader can no longer open.

        Cache keys are built from the name (see `_scan_key`, `_page_fingerprint`
        in editor.py), so a rename drops this page's cached plate and it is
        rebuilt on the next look. That is correct rather than merely tolerable:
        the exported file is named after the page, so the old cache is under a
        name that no longer exists.
        """
        if not (0 <= i < len(self.pages)):
            return "no such page"
        pg = self.pages[i]
        stem = os.path.splitext((name or "").strip())[0].strip()
        if not stem:
            return "a page needs a name"
        # Anything a filesystem will not take, or would read as a path. Checked
        # on what was TYPED rather than on `os.path.basename` of it: basename
        # turns "art/cover" into "cover" and saves the page under a name nobody
        # asked for, which is a worse answer than saying no.
        if any(c in stem for c in '/\\:*?"<>|'):
            return 'a name cannot contain / \\ : * ? " < > |'
        # ".jpg" splits as a whole hidden filename with no extension, not as an
        # extension with nothing in front of it - so without this, renaming to
        # ".jpg" makes a hidden file called ".jpg.jpg". "." and ".." are the
        # same trap wearing a different hat.
        if stem.startswith("."):
            return "a name cannot start with a dot"
        new = stem + os.path.splitext(pg.name)[1]
        if new == pg.name:
            return ""
        dest = os.path.join(os.path.dirname(pg.path), new)
        if any(k != i and p.name == new for k, p in enumerate(self.pages)):
            return f"there is already a page called {new}"
        if os.path.exists(dest):
            return f"there is already a file called {new}"
        try:
            os.replace(pg.path, dest)
        except OSError as e:
            return f"could not rename it: {e}"
        pg.path, pg.name = dest, new
        self._img_cache.clear()
        self.save()
        return ""

    # ------------------------------------------------------ cutting by hand
    def gaps_in(self, i: int) -> list[int]:
        """The rows on one page where the artist drew nothing.

        The same measurement the automatic re-cut is made of, offered to a
        person cutting a page by hand so the line can snap to a real gutter
        instead of being eyeballed at a tenth of scale.
        """
        from . import strip as _strip

        if not (0 <= i < len(self.pages)):
            return []
        g = imgio.imread(self.pages[i].path, cv2.IMREAD_GRAYSCALE)
        if g is None:
            return []
        r = np.stack([g.min(1), g.max(1), g.std(1)], 1).astype(np.float32)
        flat = (r[:, 2] < _strip.FLAT_STD) \
            & ((r[:, 1] - r[:, 0]) < _strip.FLAT_RANGE)
        return _strip.gutters(flat)

    @staticmethod
    def _painted(pg) -> bool:
        """Strokes, or a plate the person supplied by hand.

        These are the two things on a page that are PICTURES the size of the
        page, made outside the editor's own geometry, and re-cutting them is a
        different job from re-cutting a list of rectangles. Everything else -
        boxes, the reading, the translation, the layout - is geometry, and
        geometry moves.
        """
        return bool(pg.paint_overlay or pg.paint_over or pg.paint_layers
                    or pg.custom_clean)

    @staticmethod
    def _region_moved(r: dict, dy: int, height: int):
        """One box, moved up by `dy` and kept inside a page `height` tall.

        Returns None when it belongs on the other half. Which half a box
        belongs to is decided by its CENTRE: a box straddling the cut has to go
        somewhere whole, and the half holding most of it is the half holding
        most of its writing. It is then clamped to that half rather than left
        hanging off the bottom, and the caller says how many that happened to.
        """
        x, y, w, h = [int(v) for v in (r.get("bbox") or (0, 0, 0, 0))]
        mid = y + h / 2 - dy
        if not (0 <= mid < height):
            return None
        out = dict(r)
        top = max(0, y - dy)
        bot = min(height, y - dy + h)
        if bot - top < 2:
            return None
        clipped = (y - dy < 0) or (y - dy + h > height)
        out["bbox"] = [x, top, w, bot - top]
        # ...and the BALLOON's box, which used to be left behind in the old
        # page's coordinates. On a region with no polygon that box IS the
        # placement area (`region_from_record`), so a caption plate 4056px down
        # a 4417px page went on saying 4056 after the page was cut in half -
        # 1848px off the bottom of a page 2208 tall. The mask came out empty,
        # there was nothing to erase, and the box was silently never cleaned.
        # lee, with a screenshot of an untouched gold plate: *"at no point shoud
        # a bubble not be cleneed"*.
        #
        # A balloon whose box lands wholly off this half is no longer this
        # region's balloon. Dropped rather than clamped to a sliver, so the
        # reader falls back to the box round the writing.
        bb = r.get("bubble_bbox")
        if bb:
            bx, by, bw, bh = [int(v) for v in bb]
            btop, bbot = max(0, by - dy), min(height, by - dy + bh)
            out["bubble_bbox"] = ([bx, btop, bw, bbot - btop]
                                  if bbot - btop >= 2 else None)
        poly = r.get("polygon") or []
        if poly:
            out["polygon"] = [[int(px), max(top, min(bot, int(py) - dy))]
                              for px, py in poly]
        for key in ("layout", "layout_override"):
            lay = r.get(key)
            if isinstance(lay, dict) and lay.get("frame"):
                fx, fy, fw, fh = [int(v) for v in lay["frame"]]
                lay = dict(lay)
                lay["frame"] = [fx, fy - dy, fw, fh]
                out[key] = lay
        return out, clipped

    def _carry_regions(self, src, dst, dy: int, height: int) -> int:
        """Move whichever of `src`'s boxes belong on `dst`, and say how many
        had to be clipped to fit."""
        clipped = 0
        for r in src.regions:
            got = self._region_moved(r, dy, height)
            if got is None:
                continue
            moved, cut = got
            clipped += 1 if cut else 0
            dst.regions.append(moved)
            if r.get("id") in (src.hidden_ids or []):
                dst.hidden_ids.append(r["id"])
        dst.hidden_kinds = list(src.hidden_kinds or [])
        dst.next_id = max(int(getattr(src, "next_id", 0) or 0),
                          max([int(r.get("id") or 0)
                               for r in dst.regions] or [0]) + 1)
        return clipped

    def renumber_pages(self) -> int:
        """Rename every page on disk `001`, `002`, ... in the order they are in.

        lee, on the splitter: *"wheni clcik splite it shoud rename every file
        from 1 - whatever so teh pages are properly numbered, only if teh tool
        is used"*.

        Cutting a page turns `012.jpg` into `012a.jpg` and `012b.jpg`, and
        joining two turns them into `012+.jpg`. Both are correct - they sort
        where the page they came from sorted - and after a few of them the
        chapter is `011.jpg, 012a.jpg, 012b+.jpg, 013.jpg`, which is a list
        nobody wants to read or export.

        **Only from the knife.** Nothing else in the app renames a person's
        files, and an editor that quietly renumbers a folder every time you
        open it is an editor you cannot trust with a folder.

        Two passes, through temporary names: `002.jpg` becoming `001.jpg` while
        another `001.jpg` is still there loses a page, and one chapter in ten
        is already numbered from 1.

        Returns how many were renamed.
        """
        moves = []
        for n, pg in enumerate(self.pages, 1):
            ext = os.path.splitext(pg.path)[1] or ".png"
            want = os.path.join(os.path.dirname(pg.path), f"{n:03d}{ext}")
            if os.path.abspath(want) != os.path.abspath(pg.path):
                moves.append((pg, want))
        if not moves:
            return 0
        held = []
        for k, (pg, want) in enumerate(moves):
            tmp = os.path.join(os.path.dirname(pg.path), f".renum{k}.tmp")
            try:
                shutil.move(pg.path, tmp)
            except OSError:
                # Put back what has already moved rather than leave the chapter
                # half renamed.
                for old, at in held:
                    shutil.move(at, old.path)
                return 0
            held.append((pg, tmp))
        for (pg, tmp), (_pg, want) in zip(held, moves):
            shutil.move(tmp, want)
            pg.path = want
            pg.name = os.path.basename(want)
        self._img_cache.clear()
        self.save()
        return len(moves)

    def split_page(self, i: int, at) -> tuple[bool, str]:
        """Cut one page at the rows the person chose.

        `at` is one row or a list of them. lee: *"can you make it so that i
        can have multiple cut lines"* - a 10,413-row webtoon is four or five
        pages long, and cutting it one row at a time meant reopening the
        dialog on a half whose panels had all moved, four times over, with a
        renumber and a reload between each. One pass, N+1 pages.

        lee: *"add page splitter that allow the user to splite the pages
        manualy"*. The automatic re-cut only runs on a chapter that arrived as
        a sliced strip, only before any work is done, and only when it is sure
        - three good rules that between them leave every other long page
        untouched. A page you can see is too long is not an argument to loosen
        any of them; it is an argument for a knife.

        The original is KEPT, in `split/` beside the chapter, exactly as the
        tiles are. Nothing a person handed the editor is deleted behind them.

        **The work on the page comes with it.** lee: *"also alow me to cut teh
        page after ive done so steps it"*. It used to refuse outright the
        moment there were boxes, which meant noticing a page was wrong after
        reading it cost you the reading. Boxes are geometry, and geometry
        moves: each one goes to the half its CENTRE is in, with everything
        measured from that half's top edge instead - the box, its outline, and
        the typesetting frame if it has one. The reading, the translation, the
        speaker, the type: all carried, none touched.

        What does NOT come with it is anything that is a PICTURE the size of
        the page - touch-up strokes and a hand-supplied clean plate. Re-cutting
        those is a different job, so a page carrying them is refused and says
        so. And the CLEANED and TYPESET flags come off both halves: the plate
        and the laid-out text are page-sized too, and they are the two things
        the app can simply make again.

        Returns (ok, why). `why` is empty when it worked.
        """
        if not (0 <= i < len(self.pages)):
            return False, "there is no such page"
        pg = self.pages[i]
        if self._painted(pg):
            return False, ("there are touch-up strokes or a clean plate of "
                           "your own on this page — those are pictures the "
                           "size of the page and cutting them is a different "
                           "job. Undo the painting, or cut before you paint")
        img = imgio.imread(pg.path)
        if img is None:
            return False, "that page cannot be read"
        h = img.shape[0]
        # ONE ROW OR MANY, and the rest of this does not care which. Sorted
        # and de-duplicated because two cuts on the same row is one cut, and
        # because the parts are only in reading order if the rows are.
        rows = sorted({int(a) for a in
                       (at if isinstance(at, (list, tuple, set)) else [at])})
        if not rows:
            return False, "no cut was asked for"
        # A sliver is not a page, and a cut at the very edge is a mis-click
        # rather than a decision. The same distance applies BETWEEN two cuts:
        # a fourteen-row page in the middle of a chapter is the same mistake
        # as a fourteen-row page at the end of one.
        for a in rows:
            if not (SLIVER <= a <= h - SLIVER):
                return False, (f"the cut has to be inside the page "
                               f"(1 to {h - 1})")
        for a, b in zip(rows, rows[1:]):
            if b - a < SLIVER:
                return False, (f"two cuts {b - a} rows apart leave a page "
                               f"nobody can read - keep them {SLIVER} apart")

        stem, ext = os.path.splitext(os.path.basename(pg.path))
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            ext = ".png"
        folder = os.path.dirname(pg.path)
        # The boundaries, top to bottom: the page's own top, every cut, and
        # the page's own bottom. N cuts make N+1 pages.
        edges = [0] + rows + [h]
        pieces = len(edges) - 1
        made = []
        for k in range(pieces):
            part = img[edges[k]:edges[k + 1]]
            name = f"{stem}{_part_suffix(k, pieces)}{ext}"
            n = 2
            while os.path.exists(os.path.join(folder, name)):
                name = f"{stem}{_part_suffix(k, pieces)}{n}{ext}"
                n += 1
            if not imgio.imwrite(os.path.join(folder, name), part):
                for done in made:
                    try:
                        os.remove(os.path.join(folder, done[0]))
                    except OSError:
                        pass
                return False, "the pieces could not be written"
            made.append((name, part.shape[1], part.shape[0]))

        keep = os.path.join(folder, "split")
        os.makedirs(keep, exist_ok=True)
        try:
            shutil.move(pg.path, os.path.join(keep, os.path.basename(pg.path)))
        except OSError:
            # Kept is better than tidy: if it will not move, leave it where it
            # is rather than lose it. It stops being a page either way.
            pass

        parts = [PageState(path=os.path.join(folder, name), name=name,
                           width=w, height=ph)
                 for name, w, ph in made]
        clipped = 0
        for k, part in enumerate(parts):
            part.detected = pg.detected
            # `edges[k]` is where this piece starts in the page it came from,
            # which is what every box on it has to be measured from now.
            clipped += self._carry_regions(pg, part, edges[k], part.height)
        # The plate and the laid-out text are page-sized pictures of a page
        # that no longer exists. Both are rebuilt from the boxes that just
        # moved, so they are dropped rather than carried wrong.
        for part in parts:
            part.cleaned = part.typeset = part.exported = False
        if pg.note:
            parts[0].note = pg.note
            for part in parts:
                part.note_ids = [r["id"] for r in part.regions
                                 if r.get("id") in (pg.note_ids or [])]
        self._last_split_clipped = clipped
        self.pages[i:i + 1] = parts
        self._img_cache.clear()
        self.save()
        # `012a` and `012b` sort where `012` sorted, which is right and is also
        # how a chapter ends up called 011, 012a, 012b, 013. lee asked for the
        # numbering to be put straight, and only ever from here.
        self.renumber_pages()
        return True, ""

    def merge_pages(self, i: int, count: int = 2) -> tuple[bool, str]:
        """Join a run of pages back into one, top to bottom.

        lee: *"also add a page mergin feature"*. The other half of the knife.
        A webtoon site's slicer cut a scene across two files, or the re-cut
        chose a gutter you would not have; either way the answer is to put them
        back together and, if you want, cut once where it should have gone.

        Widths can differ - two scans of the same book rarely agree to the
        pixel - so the joined page is as wide as its widest part and the
        narrower ones are CENTRED on paper the colour of their own top-left
        corner. Stretching them would change the artwork; jamming them left
        would put a step down one edge of the page.

        The originals are kept in `merged/` beside the chapter.

        Returns (ok, why).
        """
        n = max(2, int(count))
        if not (0 <= i and i + n <= len(self.pages)):
            return False, "there are not that many pages after this one"
        run = self.pages[i:i + n]
        # Boxes come with it, the same way they come through a cut. Pictures
        # the size of a page do not.
        painted = [pg.name for pg in run if self._painted(pg)]
        if painted:
            return False, ("there are touch-up strokes or a clean plate of "
                           "your own on " + ", ".join(painted[:2])
                           + " — those are pictures the size of the page and "
                             "joining them is a different job")
        parts = []
        for pg in run:
            img = imgio.imread(pg.path)
            if img is None:
                return False, f"{pg.name} cannot be read"
            parts.append(img)

        w = max(a.shape[1] for a in parts)
        laid = []
        for a in parts:
            if a.shape[1] == w:
                laid.append(a)
                continue
            pad = np.full((a.shape[0], w, 3), a[0, 0], np.uint8)
            off = (w - a.shape[1]) // 2
            pad[:, off:off + a.shape[1]] = a
            laid.append(pad)
        joined = np.vstack(laid)

        folder = os.path.dirname(run[0].path)
        stem, ext = os.path.splitext(os.path.basename(run[0].path))
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            ext = ".png"
        # Named after the FIRST page with a `+` on it, so it sorts where the
        # first one sorted and reads as "this one and the ones after it".
        name = f"{stem}+{ext}"
        k = 2
        while os.path.exists(os.path.join(folder, name)):
            name = f"{stem}+{k}{ext}"
            k += 1
        if not imgio.imwrite(os.path.join(folder, name), joined):
            return False, "the joined page could not be written"

        keep = os.path.join(folder, "merged")
        os.makedirs(keep, exist_ok=True)
        for pg in run:
            try:
                shutil.move(pg.path, os.path.join(keep,
                                                  os.path.basename(pg.path)))
            except OSError:
                pass

        one = PageState(path=os.path.join(folder, name), name=name,
                        width=joined.shape[1], height=joined.shape[0])
        # Each page's boxes move DOWN by everything stacked above it. `-y` is
        # the same shift a cut does in the other direction, so one helper
        # serves both and cannot disagree with itself.
        y = 0
        for k, pg in enumerate(run):
            self._carry_regions(pg, one, -y, one.height)
            one.detected = one.detected or pg.detected
            if pg.note and not one.note:
                one.note = pg.note
            y += laid[k].shape[0]
        one.note_ids = [r["id"] for r in one.regions
                        if any(r.get("id") in (pg.note_ids or []) for pg in run)]
        self.pages[i:i + n] = [one]
        self._img_cache.clear()
        self.save()
        self.renumber_pages()
        return True, ""

    def remove_page(self, i: int) -> bool:
        """Take a page out of the project. The source file is left alone."""
        if not (0 <= i < len(self.pages)):
            return False
        self.pages.pop(i)
        self._img_cache.clear()
        self.save()
        return True

    def clear(self) -> None:
        self.pages = []
        self._img_cache.clear()
        self.input_dir = ""
        self.save()

    def _state(self) -> dict:
        return {
            "input_dir": self.input_dir,
            "settings": self.settings,
            "context": self.ctx.__dict__,
            "pages": [asdict(p) for p in self.pages],
        }

    def save(self) -> None:
        """Write the project out, now, and completely.

        Through a temporary file: a chapter's project.json is most of a
        megabyte, and a crash or a power cut halfway through a direct write
        leaves a truncated file - which is not a lost edit, it is a lost
        chapter. `os.replace` is atomic, so the file on disk is always either
        the whole of the last save or the whole of this one.
        """
        with self._dirty_lock:
            self._dirty = False          # anything after this marks it again
        with self._save_lock:
            # Serialise BEFORE opening anything. A job thread editing a page
            # halfway through this raises rather than writing half a state, and
            # `_save_loop` marks it dirty again and comes back - so the file on
            # disk is never a torn one.
            data = json.dumps(self._state(), ensure_ascii=False)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, self.state_path)

    def save_soon(self) -> None:
        """Write it out in a moment, once, however many times this is called.

        Every small edit - a box renumbered, a type changed, one deleted, a
        line of typesetting nudged - used to serialise and write the whole
        project before the answer went back to the browser. On a real chapter
        that is half a megabyte of JSON, and if the project sits in a synced
        folder (OneDrive, Dropbox) the write also wakes the sync client and the
        virus scanner. lee: *"it works but very slow"*.

        Nothing about what is SAVED changes: the same whole-project write, off
        the request thread, and coalesced so twenty presses in a row cost one
        write instead of twenty. What is in memory is what the editor answers
        from, so nothing can be read stale; the file on disk is only for the
        next time the app starts.
        """
        # Its own small lock, never the one the write holds: marking an edit
        # must not wait behind half a megabyte going to disk, or one request in
        # every handful pays the whole cost after all.
        with self._dirty_lock:
            self._dirty = True
            if self._saver and self._saver.is_alive():
                return
            self._saver = threading.Thread(target=self._save_loop, daemon=True)
            self._saver.start()

    def _save_loop(self) -> None:
        while True:
            time.sleep(SAVE_DELAY)
            with self._dirty_lock:
                if not self._dirty:
                    self._saver = None
                    return
            try:
                self.save()
            except Exception:
                # A save that fails must not take the thread down and leave
                # every later edit unwritten; it is marked again and tried
                # again on the next turn round.
                with self._dirty_lock:
                    self._dirty = True
                time.sleep(SAVE_DELAY)

    def flush(self) -> None:
        """Make sure everything asked for is on disk. Cheap when it already is."""
        with self._dirty_lock:
            dirty = self._dirty
        if dirty:
            self.save()

    def load(self) -> None:
        with open(self.state_path, encoding="utf-8") as fh:
            d = json.load(fh)
        self.settings.update(d.get("settings") or {})
        # The one engine an old project was set up with, carried onto its three
        # steps. Read off the FILE, not off `self.settings`: the constructor
        # has already put a model in every step, and the `update` above leaves
        # those standing when the saved project names none - so every old
        # project would look as though it had answered already, and would
        # silently move onto somebody else's defaults.
        migrate_engine(self.settings, d.get("settings") or {})
        # ...and then the per-step keys onto the one box per service. After
        # `migrate_engine`, because a project old enough to need that one has
        # just had its single `api_key` put on all three steps and this is what
        # turns it into one service key.
        migrate_keys(self.settings, d.get("settings") or {})
        # "Same as the source material" is gone from both screens, so the two
        # boxes it stood in now hold a real answer. `auto` is what it saved, and
        # a project full of it is written out here - once, on load - as the
        # thing it always resolved to. Nothing changes about how the chapter
        # reads; the settings file just says it now.
        #
        # A medium the app no longer offers gets the same treatment first, and
        # it matters more: "comic" is gone, and `MEDIA.get(medium, MEDIA
        # ["manga"])` - which is what every reader of this setting does - would
        # quietly hand back Japanese and right-to-left for an English western
        # comic. So pin what the medium was ANSWERING for, THEN move it to one
        # that still exists.
        #
        # Read off the FILE, not off `self.settings`: the constructor has
        # already put "ja" and "rtl" in there for a new project, and the
        # `update` above leaves them standing when the saved project names
        # neither - so every old project would look as though it had answered
        # already. The same trap as `kinds_seeded` below.
        from .translate import MEDIA
        saved = d.get("settings") or {}
        was = MEDIA.get(self.settings.get("medium")) \
            or MEDIA_GONE.get(self.settings.get("medium") or "") \
            or MEDIA["manga"]
        if (saved.get("source") or "auto") == "auto":
            self.settings["source"] = was["code"]
        if (saved.get("direction") or "auto") == "auto":
            self.settings["direction"] = "rtl" if was["rtl"] else "ltr"
        if self.settings.get("medium") not in MEDIA:
            self.settings["medium"] = "manga"
        # Three families with sub-types under them, where there used to be six
        # flat types and a free list beside them. A project written before that
        # is brought up to date on every load - `migrate` is idempotent, so it
        # also re-checks that every sub-type's colour is still one its own
        # family issues. See kinds.py.
        # What is remembered is WHICH preloaded sub-types have been offered,
        # not whether seeding has happened at all - see kinds.migrate. The old
        # `kinds_seeded` flag was set by a build whose PRELOADED list was
        # empty, so a project stamped with it could never receive the ones
        # added since. An old project has no list, so nothing has been offered
        # to it and it gets the lot once.
        #
        # Read off the FILE, not off `self.settings`: the constructor puts a
        # full list there for a brand-new project, and the `update` above
        # leaves it standing when the saved project has none - so every old
        # project looked as though it had already been offered everything,
        # which is exactly the bug this replaced.
        offered = (d.get("settings") or {}).get("kinds_seeded_keys")
        self.settings["custom_kinds"] = _kinds.migrate(
            self.settings.get("custom_kinds"),
            offered=list(offered or ()))
        self.settings["kinds_seeded"] = True
        self.settings["kinds_seeded_keys"] = sorted(
            set(offered or ()) | set(_kinds.PRELOAD_KEYS))
        # A sub-type's face used to be a row in the Fonts section, keyed by the
        # type's name in `settings["fonts"]`. It travels on the sub-type's own
        # record now - it is part of what that sub-type IS - so a project that
        # set an italic for thought balloons keeps it.
        fonts = self.settings.get("fonts") or {}
        for sub in self.settings["custom_kinds"]:
            if not sub.get("font") and fonts.get(sub["key"]):
                sub["font"] = fonts[sub["key"]]
        _kinds.use(self.settings["custom_kinds"])
        # Only the fields this version HAS. A project.json written by a
        # different version carries keys the dataclass does not take, and
        # `SeriesContext(**saved)` raises on the first one - which `_load_or_
        # scan` swallows, so the chapter is then rescanned from an empty input
        # folder and SAVED over. A key nobody recognises is worth nothing; a
        # chapter is worth everything.
        _ctx = d.get("context") or {}
        _known = {f.name for f in dataclasses.fields(SeriesContext)}
        _drop = sorted(set(_ctx) - _known)
        if _drop:
            print("project.json holds context keys this version does not "
                  "know, ignoring them: %s" % ", ".join(_drop))
        self.ctx = SeriesContext(**{k: v for k, v in _ctx.items()
                                    if k in _known})
        self.pages = [PageState(**p) for p in d["pages"]]

    # ------------------------------------------------------------------ images
    def image(self, i: int) -> np.ndarray:
        # Two pages can now be built at the same time (see `_page_lock` in
        # editor.py), so this cache is reached from more than one thread. The
        # trim is the part that matters: `pop(next(iter(...)))` on a dict two
        # threads are both trimming raises, and the loading itself is worth
        # doing once rather than twice.
        with self._img_lock:
            if i not in self._img_cache:
                if len(self._img_cache) > 6:
                    self._img_cache.pop(next(iter(self._img_cache)), None)
                self._img_cache[i] = load_page(self.pages[i].path).image
            return self._img_cache[i]

    def repaired(self, i: int) -> np.ndarray:
        """The scan with the touch-up strokes that go UNDER the typesetting
        painted onto it - the page as it now stands.

        A balloon's shape is read off the drawn outline around the words, and
        that outline is part of the artwork, which a person is allowed to
        mend. lee: *"the clenner ... errased some of a side of a box, now the
        typesetting thinks the bubble is bigger than it accually is. i clenned
        the bubble and added the edge back but the typeseetting is not
        registerng that"*.

        Measured on a fixture of two balloons sharing a wall: nick the wall
        and the run of paper joins the neighbour, so the shape comes back
        50,578px against the 25,137 it should be. Paint the wall back and the
        search has to be looking at THIS picture to see it - the scan alone
        still has the hole.

        Only the under-text band. Paint that sits above the typesetting is
        drawn over the finished page and is not part of the artwork the words
        are laid into.
        """
        img = self.image(i)
        ov = getattr(self.pages[i], "paint_overlay", "") or ""
        if not ov or not os.path.exists(ov):
            return img
        o = imgio.imread(ov, cv2.IMREAD_UNCHANGED)
        if o is None or o.ndim != 3 or o.shape[2] != 4 \
                or o.shape[:2] != img.shape[:2]:
            return img
        a = o[:, :, 3:4].astype(np.float32) / 255.0
        return (img.astype(np.float32) * (1.0 - a)
                + o[:, :, :3].astype(np.float32) * a).astype(np.uint8)

    def materialize(self, i: int) -> Page:
        """A full Page with masks, built from stored geometry.

        A hidden group never reaches this, which is what makes "not considered
        for the next steps" true of every stage at once: reading, translating,
        proofreading, cleaning, typesetting, rendering and exporting all build
        their page here.
        """
        img = self.image(i)
        page = Page(image=img, source_path=self.pages[i].name)
        # The WRITING is read off the scan, not off the repair: painting over a
        # line of Japanese is a way of saying "leave this alone", and it must
        # not also mean "there was never anything here to erase". The BALLOON
        # is read off the repair, because the outline is artwork and mending it
        # is exactly what `repaired` exists for.
        page.regions = [region_from_record(r, img)
                        for r in self.pages[i].active]
        find_balloons(self.repaired(i), page.regions)
        return page

    def commit(self, i: int, page: Page, keep_hidden: bool = True) -> None:
        """Store a worked-on page back over the record.

        The page was built from the ACTIVE boxes, so writing it back verbatim
        would delete every hidden one - hiding a group would quietly destroy it
        on the next stage that ran. They are merged back in, in order.

        `keep_hidden=False` is for Find text, which is replacing the boxes on
        this page wholesale; keeping the old ones there would resurrect the
        boxes it just superseded.
        """
        recs = [region_record(r) for r in page.ordered()]
        if keep_hidden:
            done = {r["id"] for r in recs}
            back = [r for r in self.pages[i].hidden if r["id"] not in done]
            if back:
                recs = sorted(recs + back,
                              key=lambda r: int(r.get("order") or 0))
        self.pages[i].regions = recs

    # ------------------------------------------------------------------ stages
    #
    # There were three helpers here - _ai_ctx, _ai_mode and _can_ask - and every
    # one of them existed only to feed the AI box pass at Find text. That pass is
    # gone, so they are gone with it. The reader and the translator sync the
    # backend onto self.ctx themselves, in editor.py, and always did.

    def bubble_weights(self) -> str:
        """Where the colour-balloon model is, if it is anywhere.

        Set it explicitly if it lives somewhere odd; otherwise it is looked
        for beside the block head's weights under the names it is published
        with, so downloading the file next to the detector is the whole of the
        setup. An empty string means the pass does not run, which is what a
        machine that has never downloaded it should get.

        The big one first: the int8 build is four times faster (0.26s a page
        against 0.9) and it is the small one, so anybody who has both wanted
        the big one.
        """
        named = (self.settings.get("bubble_weights") or "").strip()
        if named:
            return named if os.path.isfile(named) else ""
        beside = self._weights_dir()
        if not beside:
            return ""
        for f in ("detector.onnx", "detector-v4-s_int8.onnx"):
            p = os.path.join(beside, f)
            if os.path.isfile(p):
                return p
        return ""

    #: The blank page the warm-up pushes through each net. Small on purpose:
    #: what is being paid for is the first pass existing at all, not its size,
    #: and 256 is enough for every one of these to build its graph.
    WARM_SIDE = 256

    #: What each card is called, for anything that has to SAY which route.
    #: The same words as the buttons in the settings page, because a message
    #: naming a route by its settings key is a message nobody can match to
    #: what they clicked.
    ROUTE_NAMES = (("webtoon_ko", "Webtoon balloons KO"),
                   ("webtoon_zh", "Webtoon balloons ZH"),
                   ("animetext", "AnimeText YOLO12-L"),
                   ("manga_segmenter", "Manga109 YOLO26"),
                   ("two_specialists", "DB++ / COO"))

    #: Which formats each card is offered on. The same table as `ROUTE_MEDIA`
    #: in project.js, and the same table as the `why_not_*` guards - said here
    #: because a flag being SET is not the same as its route being the one
    #: that runs. `webtoon_ko` ships on, so that a manhwa gets a webtoon
    #: default with no per-format defaults table; on a manga that flag is set
    #: and guarded off, and anything reading the flags alone would name a
    #: route that cannot run and warm a model nothing will call.
    #: (a method, because `ANIME_MEDIA` and `TWO_MEDIA` are further down the
    #: class body than this line and a dict literal here would read them
    #: before they exist.)
    def route_media(self) -> dict:
        return {"webtoon_ko": tuple(STRIP_MEDIA),
                "webtoon_zh": tuple(STRIP_MEDIA),
                "animetext": tuple(self.ANIME_MEDIA),
                "manga_segmenter": tuple(self.TWO_MEDIA),
                "two_specialists": tuple(self.TWO_MEDIA)}

    def route_here(self, key: str) -> bool:
        """Is this card on screen, and its route runnable, on this format?"""
        return self.medium in self.route_media().get(key, self.ANIME_MEDIA)

    def route_key(self) -> str:
        """Which route actually runs, as its settings key. "" is the plain one.

        NOT "which flag is set". Two can be set at once and mean it - see
        `webtoon_ko` in the defaults - and the one that runs is the first that
        this format offers, which is the order `_detect_measured` asks them
        in and the order the cards are in on screen.

        Nor "which flag is set on the right format": the checkpoint has to be
        on the machine too. Each route already has a predicate that asks its
        own `why_not` - `self.animetext()`, `self.webtoon_ko()` - and asking
        THOSE is what keeps this answer the same as the one the run makes. A
        name read off the flags alone is how a slow-page line comes to name a
        route that never ran.
        """
        for key, _name in self.ROUTE_NAMES:
            ask = getattr(self, key, None)
            if callable(ask) and ask():
                return key
        return ""

    def route_name(self) -> str:
        """Which detector card is on, in the words on the card."""
        key = self.route_key()
        return dict(self.ROUTE_NAMES).get(key, "comic-text-detector")

    def warm_models(self) -> str:
        """Load the picked route's checkpoints now, so no page pays for them.

        lee timed three cards and got 50, 58 and 60 seconds a page against
        estimates of 2.9, 9.9 and 12.7. Not one of them was slow: measured in
        a fresh process, DB++/COO is 54.28s on page ONE and 9.63s by page
        three. The models load on whichever page happens to be first, in the
        middle of a bar reading "1 of 30", so a fifteen-second load reads as a
        fifty-second page - and that is the conclusion he drew three times.

        So the loading moves to the moment the card is picked, where there is
        nothing to misread it as. Everything below is already cached for the
        life of the process by its own module; this only makes WHEN happen
        somewhere harmless.

        Quiet about failure on purpose. A warm-up that raises would turn
        picking a card into an error, and every one of these paths is asked
        again properly - with a sentence somebody can act on - by `why_not`.
        """
        name = self.route_name()
        # WHICH ROUTE RUNS, not which flags are set. `webtoon_ko` ships on so
        # that a strip gets a webtoon default, which means on a manga its flag
        # is set and its route is guarded off - and warming a model nothing
        # will call is exactly the fifteen seconds this whole method exists to
        # stop somebody paying.
        key = self.route_key()
        ctd = self.detector_weights()
        # A BLANK PAGE THROUGH EACH NET, not just the file off the disk.
        #
        # Loading alone got the first DB++/COO page from 54.28s to 20.06s
        # against 9.24s steady - so more than half of what was left is the
        # FIRST forward pass rather than the read: torch picking kernels,
        # OpenCV laying out its layers, allocators sizing themselves. All of
        # it happens once per process and none of it cares what is in the
        # image, so it can happen here on 256 pixels of white instead of on
        # page one of a chapter.
        blank = np.full((self.WARM_SIDE, self.WARM_SIDE, 3), 255, np.uint8)
        try:
            if ctd:
                from .detect import comictext as _ct
                _ct._get_net(ctd)
                _ct.page_text_mask(blank, ctd)
            if key == "animetext":
                from .detect import animetext as _at
                if not _at.why_not(self.animetext_weights()):
                    _at.pieces(blank, self.animetext_weights())
            if key == "manga_segmenter":
                from .detect import mangaseg as _ms
                if not _ms.why_not(self.m109_weights()):
                    _ms.pieces(blank, self.m109_weights())
            if key in ("webtoon_ko", "webtoon_zh"):
                from .detect import webtoon as _wt
                w = (self.webtoon_ko_weights() if key == "webtoon_ko"
                     else self.webtoon_zh_weights())
                if not _wt.why_not(w):
                    _wt.pieces(blank, w)
            # ...and the sound-effect model, which every route but the plain
            # one and the webtoon pair asks for. It is the 116MB one, and the
            # slowest of the lot, so the pair that has no use for it does not
            # pay fifteen seconds to load it: `detect_webtoon` takes `want_sfx`
            # and ignores it, because these models answer balloon or
            # not-balloon and have no class for a painted sound.
            elif key:
                from .detect import onomatopoeia as _oo
                if not _oo.why_not(self.coo_weights()):
                    _oo.pieces(blank, self.coo_weights())
        except Exception:
            return name
        return name

    #: Where comic-text-detector is called, in the order anybody would try.
    CTD_FILES = ("comictextdetector.pt.onnx", "comictextdetector.onnx",
                 "comictextdetector.pt")

    def detector_weights(self) -> str:
        """comic-text-detector, named in the settings or lying beside the app.

        THE FALLBACK IS THE POINT. lee: *"also the other detector are grey
        out"*, with `animetext.pt`, `m109seg.pt`, `dbpp_coo.dat` and
        `comictextdetector.pt.onnx` all sitting in the app's own folder. His
        "Model file" box was empty, and everything downstream anchors on it:
        `_beside` looks in `dirname(weights)`, an empty string has no dirname,
        so every route answered "comic-text-detector weights are needed" and
        greyed itself out - with the file it wanted one directory listing away.

        So an empty box now means LOOK, not GIVE UP. The app's own folder is
        where `get_models.py` downloads to and where every one of lee's
        checkpoints already is, which makes "put the file next to the app" the
        whole of the setup, exactly as `_beside` has always claimed.

        A NAMED file is still absolute: named and missing returns empty rather
        than quietly falling back, because a path somebody typed is a decision
        and silently ignoring it is how you end up running the wrong model.
        """
        named = (self.settings.get("weights") or "").strip()
        if named:
            return named if os.path.isfile(named) else ""
        for f in self.CTD_FILES:
            p = os.path.join(self._weights_dir(), f)
            if os.path.isfile(p):
                return p
        return ""

    def _weights_dir(self) -> str:
        """The folder every other checkpoint is looked for in.

        Deliberately NOT `dirname(detector_weights())`: a comic-text-detector
        path that is named and missing still says where the person keeps their
        models, and a machine that has the sound-effect model but not the
        detector should be told which one is absent rather than both.
        """
        named = (self.settings.get("weights") or "").strip()
        if named:
            return os.path.dirname(named)
        # The launcher keeps the weights OUTSIDE the app folder, because the
        # app folder is replaced on every update and half a gigabyte of
        # checkpoints should not be downloaded again for a bug fix. It says
        # where with `MANGATL_WEIGHTS`; a checkout run by hand has none set
        # and finds them beside the code, as it always has.
        env = (os.environ.get("MANGATL_WEIGHTS") or "").strip()
        if env and os.path.isdir(env):
            return env
        return os.path.dirname(os.path.abspath(__file__))

    def _beside(self, named: str, *files: str) -> str:
        """A weight file, named in the settings or lying beside the others.

        The same arrangement as `bubble_weights`, and for the same reason:
        downloading the file next to the detector should be the whole of the
        setup, and an empty string should mean "this machine has not got it"
        rather than an error.
        """
        got = (self.settings.get(named) or "").strip()
        if got:
            return got if os.path.isfile(got) else ""
        beside = self._weights_dir()
        if not beside:
            return ""
        for f in files:
            p = os.path.join(beside, f)
            if os.path.isfile(p):
                return p
        return ""

    def dbnet_weights(self) -> str:
        """manga-image-translator's DBNet. See `detect/dbtext.py`."""
        return self._beside("dbnet_weights", "detect-20241225.ckpt",
                            "detect.ckpt")

    def animetext_weights(self) -> str:
        """`deepghs/AnimeText_yolo`. See `detect/animetext.py`.

        `model.pt` last for the same reason `best.pt` is last below: it is
        what Hugging Face calls the file, so it is accepted, but a folder of
        checkpoints all called `model.pt` is unreadable.
        """
        return self._beside("animetext_weights", "animetext.pt",
                            "yolo12l_animetext.pt", "model.pt")

    def animetext(self) -> bool:
        """Is the AnimeText route on, and can it actually run?

        No `medium` guard of its own -- `why_not_animetext` asks that first
        and answers it in a sentence somebody can act on. A second copy here
        is a line that can never change the answer, and the mutation pass
        said so.
        """
        if not self.settings.get("animetext"):
            return False
        return not self.why_not_animetext()

    def why_not_animetext(self) -> str:
        """Why the AnimeText route cannot run, in a sentence, or empty."""
        if self.medium not in self.ANIME_MEDIA:
            return ("this route is offered on %s -- see Project.ANIME_MEDIA"
                    % ", ".join(self.ANIME_MEDIA))
        if not self.detector_weights():
            return "comic-text-detector weights are needed for the clean mask"
        from .detect import animetext as _at
        return _at.why_not(self.animetext_weights())

    # ---------------------------------------------- the two webtoon finders

    def webtoon_ko_weights(self) -> str:
        """The Korean webtoon balloon model. See `detect/webtoon.py`."""
        return self._beside("webtoon_ko_weights", "webtoon-ko.onnx",
                            "korean_webtoon.onnx")

    def webtoon_zh_weights(self) -> str:
        """The Chinese webtoon balloon model. See `detect/webtoon.py`."""
        return self._beside("webtoon_zh_weights", "webtoon-zh.onnx",
                            "chinese_webtoon.onnx")

    def webtoon_ko(self) -> bool:
        """Is the Korean webtoon route on, and can it actually run?"""
        if not self.settings.get("webtoon_ko"):
            return False
        return not self.why_not_webtoon_ko()

    def webtoon_zh(self) -> bool:
        """Is the Chinese webtoon route on, and can it actually run?"""
        if not self.settings.get("webtoon_zh"):
            return False
        return not self.why_not_webtoon_zh()

    def _why_not_webtoon(self, path: str) -> str:
        """The half both webtoon cards answer the same way."""
        if self.medium not in STRIP_MEDIA:
            return ("this was measured on webtoons -- it is offered on %s"
                    % " and ".join(sorted(STRIP_MEDIA)))
        if not self.detector_weights():
            return "comic-text-detector weights are needed for the clean mask"
        from .detect import webtoon as _wt
        return _wt.why_not(path)

    def why_not_webtoon_ko(self) -> str:
        """Why the Korean webtoon route cannot run, in a sentence, or empty."""
        return self._why_not_webtoon(self.webtoon_ko_weights())

    def why_not_webtoon_zh(self) -> str:
        """Why the Chinese webtoon route cannot run, in a sentence, or empty."""
        return self._why_not_webtoon(self.webtoon_zh_weights())

    def m109_weights(self) -> str:
        """The Manga109 YOLO26 segmenter. See `detect/mangaseg.py`.

        `best.pt` last and on purpose: it is what Hugging Face calls the file
        and what lands in Downloads, so it is accepted -- but a folder of
        checkpoints all called `best.pt` is a folder nobody can read, and the
        two names before it are what it should be renamed to.
        """
        return self._beside("m109_weights", "m109seg.pt",
                            "manga109-seg.pt", "best.pt")

    def manga_segmenter(self) -> bool:
        """Is the Manga109 route on, and can it actually run?

        The format is NOT checked twice. `why_not_manga_segmenter` asks it
        first and answers with a sentence somebody can act on; a second copy
        of the same guard here could never change an answer, and a line that
        cannot change an answer is a line that rots.
        """
        if not self.settings.get("manga_segmenter"):
            return False
        return not self.why_not_manga_segmenter()

    def why_not_manga_segmenter(self) -> str:
        """Why the Manga109 route cannot run, in a sentence, or empty."""
        if self.medium not in self.TWO_MEDIA:
            return ("this was measured on manga and only on manga -- see "
                    "Project.TWO_MEDIA")
        if not self.detector_weights():
            return "comic-text-detector weights are needed for the clean mask"
        from .detect import mangaseg, onomatopoeia
        return (mangaseg.why_not(self.m109_weights())
                or onomatopoeia.why_not(self.coo_weights()))

    def coo_weights(self) -> str:
        """The DB++ finetune on COO. See `detect/onomatopoeia.py`.

        `dbpp_coo.dat` first because that is what lee's copy is called; the
        published names follow.
        """
        return self._beside("coo_weights", "dbpp_coo.dat", "dbpp_coo.pth",
                            "DB_finetune_COO")

    def paint_weights(self) -> str:
        """TRBA+2D, the recogniser from the other half of the COO paper.

        The reader on this computer for writing that was PAINTED - see
        `paintread`. Found the same way every other checkpoint is: named in the
        settings, or lying beside the detector, so that downloading the file
        next to the others is the whole of the setup.

        Absent is not an error. With no file here the offline reader behaves
        exactly as it did before this existed, and says so on the sound-effect
        boxes it is least sure of.
        """
        from . import paintread
        return self._beside("paint_weights", *paintread.WEIGHT_NAMES)

    #: WHICH FORMATS THIS IS OFFERED ON, and it is one.
    #:
    #: lee: *"this htuff shoud only be for manga"*. Every number in the route
    #: came off 23 pages of Japanese -- DBNet's own training set is COMICS,
    #: the reaches were swept on manga fragments, the outside-text rule was
    #: checked against manga hand-set type, and 0.244 was derived from manga
    #: panel widths. A manhwa is one tall column of colour with no panels
    #: across it, and not one of those measurements would transfer.
    #:
    #: A guard rather than a warning, because the caption saying "measured on
    #: manga only" was one, and a warning is a thing somebody reads once.
    TWO_MEDIA = ("manga",)

    #: ...AND THE ONE ROUTE THAT EARNED A WIDER LIST.
    #:
    #: `TWO_MEDIA` above is a guard on numbers swept on manga fragments, and
    #: it still holds for DB++/COO and the Manga109 segmenter: measured on
    #: lee's own webtoon pages, the segmenter finds NOTHING at all (0 boxes
    #: on two pages that carry five balloons between them) and COO's answer
    #: is only ever a label for a box something else found.
    #:
    #: AnimeText is the one that transfers. On the same pages it found 3 and
    #: 5 boxes against comic-text-detector's 4 and 3, including a caption
    #: stack CTD missed - so it is offered on webtoons too, and lee picked it
    #: off the comparison sheet on that evidence. A guard is worth keeping
    #: where the measurement says keep it and worth widening where the
    #: measurement says widen it; what it is not worth is being uniform.
    ANIME_MEDIA = ("manga", "manhwa", "manhua")

    def two_specialists(self) -> bool:
        """Is the DBNet + COO route on, and can it actually run?

        A project setting and only that -- Find text does not ask. Off if a
        checkpoint is missing -- a tick nobody can honour
        should not quietly change what Find text does, and it should not fail
        the run either. `why_not_two_specialists` is how the dialog says which
        one is absent.
        """
        if self.medium not in self.TWO_MEDIA:
            return False
        if not self.settings.get("two_specialists"):
            return False
        # The route needs the sound-effect model and comic-text-detector, and
        # NOT the DBNet checkpoint any more -- see `_detect_measured`.
        # The same question the dialog asks, and not a second version of it.
        # It used to be "are both files here", which is not the whole of it:
        # the manga-text model rearranges its feature map with einops and the
        # sound-effect one unshrinks polygons with pyclipper, and a machine
        # with the weights and not the wheels crashed in the middle of the
        # run instead of quietly detecting the way it always had.
        return bool(self.coo_weights()) and not self.why_not_two_specialists()

    def why_not_two_specialists(self) -> str:
        """Why the route cannot run, in a sentence, or empty if it can."""
        if self.medium not in self.TWO_MEDIA:
            return ("this was measured on manga and only on manga -- see "
                    "Project.TWO_MEDIA")
        from .detect import onomatopoeia
        if not self.detector_weights():
            return "comic-text-detector weights are needed"
        return onomatopoeia.why_not(self.coo_weights())

    def _detect_measured(self, page: "Page", kinds: list, detector: str,
                         weights: str) -> list:
        """Find text the way it has always been found: by measuring.

        Lifted out of `detect` when the AI option arrived, so that the two
        ways of getting boxes are two expressions rather than two code paths
        with two ends. Everything after this -- the kinds filter, the
        sections, the numbering, the scoring, the order, the commit -- happens
        once, to whichever list came back.
        """
        found = []
        # TWO SPECIALISTS INSTEAD OF ONE GENERALIST.
        #
        # lee, after the head-to-head over 23 pages of Japanese: *"its very
        # ovious what needs to be doen these 2 are very realiable and better
        # at detecting each of their own secments"*, then *"add a setting in
        # teh editor and make it run in teh editor"*.
        #
        #     comic-text-detector alone   5 missed  13 junk   2.9 s/page
        #     DBNet both ways + DB++/COO  3 missed   4 junk   9.9 s/page
        #
        # It is asked FIRST and falls through if the weights are not there, so
        # a machine that has never downloaded them behaves exactly as before.
        # comic-text-detector still runs inside it for the clean mask -- see
        # `detect/dbcoo.py` -- so this is not a way of switching CTD off, and
        # the `weights` setting is required either way.
        # ...AND ANIMETEXT AHEAD OF EVERYTHING, WHEN IT IS ON.
        #
        # lee: *"impliment the animen text alone and maybe add ctd as a mask
        # if needed"*.
        #
        #     route                        missed  junk  models  s/page
        #     comic-text-detector alone         5    13     1      2.94
        #     CTD + COO + the rules             6     4     2      9.9
        #     Manga109 seg + COO + CTD mask     7     3     3     12.7
        #     AnimeText + COO + CTD mask       11     1     3     14.5
        #
        # Eleven reads worse than six and is not: six of the eleven are the
        # same six every route on this chapter misses, and the other five are
        # sound effects. It finds **every one of the 159 boxes somebody has to
        # translate** -- 130 of 130 lines of dialogue and 29 of 29 captions --
        # which nothing else here has done, with one junk box on 23 pages.
        #
        # DB++/COO is passed when its weights are on the machine and left out
        # when they are not. AnimeText has ONE class, so without it there is
        # no sound-effect family at all and painted type comes back as
        # dialogue -- 179 bubble boxes against 149. See `dbcoo.detect_animetext`.
        # THE WEBTOON FINDERS FIRST, because they are the only ones on this
        # page that were trained on one. Under a second against 20-26 s for
        # comic-text-detector on the same tile; see `detect/webtoon.py` for
        # the sweep and for why the pair is not a language split.
        if (self.webtoon_ko() or self.webtoon_zh()) and weights:
            from .detect import comictext as _ct
            from .detect import webtoon as _wt
            return _wt.detect_webtoon(
                page, weights,
                (self.webtoon_ko_weights() if self.webtoon_ko()
                 else self.webtoon_zh_weights()),
                classify=self.settings.get("auto_kind", True),
                want_sfx=("sfx" in kinds),
                **_ct.tuning_for(self.medium))
        if self.animetext() and weights:
            from .detect import comictext as _ct
            from .detect import dbcoo
            return dbcoo.detect_animetext(
                page, weights, self.animetext_weights(),
                self.coo_weights() if ("sfx" in kinds) else "",
                classify=self.settings.get("auto_kind", True),
                want_sfx=("sfx" in kinds),
                # The balloon model, for the clouds and the white-on-black
                # the ink fitter cannot fit. Empty when the machine has not
                # got it, and the route then simply names fewer bubbles.
                bubble_weights=self.bubble_weights(),
                **_ct.tuning_for(self.medium))
        # ...AND THE MANGA109 SEGMENTER FIRST OF ALL, WHEN IT IS ON.
        #
        # lee, shown what it does on his chapter: *"ok impliment it"*.
        #
        #     route                         missed  junk  s/page  bubble boxes
        #     comic-text-detector alone          5    13    2.94
        #     CTD + COO + the rules              6     4    7.5            132
        #     Manga109 seg + COO + CTD mask      7     3   11.0            142
        #
        # The numbers that matter are not in the missed column, where it is one
        # worse, but in the last two: it puts a drawn balloon round ten more
        # boxes of dialogue, because the balloon is a shape a model segmented
        # rather than a run of paper a Canny pass inferred. 009's ...調子狂うぜ
        # -- white type in a black balloon, one of the two this pipeline has
        # never got right -- comes back as dialogue.
        #
        # It costs 3.5 s a page for that, and it is a tick, off by default.
        if self.manga_segmenter() and weights:
            from .detect import comictext as _ct
            from .detect import dbcoo
            return dbcoo.detect_m109(
                page, weights, self.m109_weights(), self.coo_weights(),
                classify=self.settings.get("auto_kind", True),
                want_sfx=("sfx" in kinds),
                **_ct.tuning_for(self.medium))
        if self.two_specialists() and weights:
            from .detect import comictext as _ct
            from .detect import dbcoo
            # comic-text-detector for the writing, DB++/COO for the paint.
            # lee: *"run teh ctd foirsrt and dleeted all the sfx that it finds
            # and keep teh other stuff and run the sfx deetctor and have them
            # merge, if there are duplicates keep teh ctd boxes"*.
            #
            #     CTD alone     5 missed  13 junk  18 wrong  2.94 s/page
            #     CTD + COO     9 missed   4 junk  13 wrong  6.47 s/page
            #
            # Dialogue comes back byte-identical -- 113 bubble, 51 narration,
            # 17 outside text, the same boxes CTD gives today -- because this
            # only ever replaces the sfx family. See `dbcoo.detect_ctd_sfx`.
            return dbcoo.detect_ctd_sfx(
                page, weights, self.coo_weights(),
                classify=self.settings.get("auto_kind", True),
                want_sfx=("sfx" in kinds),
                **_ct.tuning_for(self.medium))
        if detector == "comictext" and weights:
            # comic-text-detector finds ALL text directly, already grouped into
            # tight non-overlapping blocks, so it ignores the bubble/free split.
            from .detect import comictext
            # The gap that ends one block of writing was once lee's slider. It
            # is gone: he asked for "the whole split box by distance" removed,
            # because a body of writing is ONE box however wide the paper is
            # between its columns. What is left is the model's own built-in.
            # ...and it is tuned per FORMAT. Every number was measured on
            # manga and is frozen there; manhwa and manhua carry their own
            # copies, so tuning either of those can never move a manga
            # chapter. lee: *"save what we ahve for find text for manga and now
            # we will modify it for manhwa"*. See `comictext.TUNING`.
            found = comictext.detect_comictext(
                page, weights,
                classify=self.settings.get("auto_kind", True),
                second_opinion=self.settings.get("sfx_second_opinion", True),
                bubble_weights=self.bubble_weights(),
                want_sfx=("sfx" in kinds),
                **comictext.tuning_for(self.medium))
        else:
            if "bubble" in kinds:
                if detector == "yolo" and weights:
                    from .detect import yolo
                    found = yolo.detect_hybrid(
                        page, weights,
                        text_weights=self.settings.get("text_weights") or "")
                else:
                    found = classical.detect_combined(page)

            # A CHECKPOINT BETWEEN THE PASSES, because this branch is the slow
            # one. lee: *"also stopping is taling a long time still"*. The
            # check at the top of the page only helps a page that has not
            # started; a machine on this path spends the best part of a minute
            # inside these three passes with no way out, and Stop looked hung.
            # There is no per-region loop to hang it on here - the passes each
            # read the whole page - so it goes between them.
            _stopping.check()

            if "freefloat" in kinds or "sfx" in kinds:
                from .detect import freetext as _ft

                # Read the writing that is typeset straight onto the drawing,
                # and read it FIRST.
                #
                # Every detector above is enclosure-first: it looks for a shape
                # that HOLDS glyphs. Manga typesets a large part of its text over
                # bare artwork, so that text is either missed outright - lee's
                # "it missed a bunch of pages in teh last page" - or found by
                # accident when a pale panel happens to enclose it, and then the
                # box is the whole panel, which is his box 5.
                #
                # It used to run last, after `detect_free_text`, and that is
                # what put three boxes round the shout on his page 39 and left
                # 私…っ outside the box on his page 38. `detect_free_text`
                # groups by closing the ink with a 13-pixel brush, which is
                # narrower than the space between two columns of Japanese, so
                # it hands back one box per column and the reader - which knows
                # the columns are one passage - then finds the passage already
                # taken and stands aside. Reading first puts one box round the
                # whole body of writing, and the stroke-cluster pass keeps only
                # what is left over.
                enclosed = list(found)
                found += _ft.read_the_writing(page, found)
                _stopping.check()

                # The stroke pass is shown the SAME page it was always shown -
                # the balloons blanked out, the writing on the art left alone -
                # and what it finds is matched against the reader's boxes
                # afterwards. Blanking the reader's writing out first changes
                # how it groups the ink that is left, which on page 10 turned
                # two toy rabbits into a text box. See not_already_read.
                kind = "sfx" if ("sfx" in kinds and "freefloat" not in kinds) \
                    else "freefloat"
                found += _ft.not_already_read(
                    _ft.detect_free_text(page, avoid=enclosed, kind=kind),
                    found)

                # A body of writing is ONE box. Anything the other passes left
                # sitting inside it - a box round a single kanji, a box round
                # the ruby beside it - is a piece of that body, not a text of
                # its own.
                found = _ft.absorb_fragments(found)

        return found

    def detect(self, i: int, kinds: list[str] | None = None,
               no_big_sfx: bool = True) -> None:
        """`kinds` picks what to look for: bubbles, free-floating text, or
        both. Detection is no longer automatic, so this is always a choice
        the person made.

        `no_big_sfx` leaves out the sound-effect boxes too big for the
        cleaner to put the artwork back through -- see `big_sfx`. On by
        default, and on for a caller that has not heard of it, because a
        run nobody configured should be the run lee measured.

        The DBNet + COO route is NOT a parameter here. lee: *"the setting
        should be in teh setting page not inthe fins text popup"* -- it is a
        chapter's worth of setup rather than a choice per run, so it is read
        from the project in one place. See `two_specialists`."""
        kinds = list(kinds or ["bubble"])
        # The LOAD is timed apart from the detecting. lee timed four routes -
        # 50, 58, 60 seconds against 4.7, 9.9 and 12.7 measured here - and the
        # gap is not a multiplier, it is the same 47 seconds added to each of
        # them. A constant that does not care which route ran is not in any of
        # the routes, and getting the page off the disk is the work they all
        # share. So it gets its own number rather than being folded into
        # theirs.
        _t_load = time.time()
        page = Page(image=self.image(i), source_path=self.pages[i].name)
        _t_load = time.time() - _t_load
        weights = self.detector_weights()
        detector = self.settings.get("detector")

        # ONE way of getting boxes: measurement.
        #
        # There were two AI passes here, built and removed in that order. The
        # first showed a numbered page to a model and let it judge boxes; lee
        # watched it and said *"nvm remove it its pretty bad remove the ai"*.
        # The second asked a model where the writing was in tiles down the page
        # and then snapped every rectangle onto the ink underneath, so a loose
        # answer could not put a box on the artwork -- and it is out too:
        # *"remoeve teh whole ai box deection and just keep what we have now"*.
        #
        # It is out because measurement caught up. On lee's chapter 1, all 67
        # pages: the double balloon comes apart, a sound-effect box covers the
        # whole stroke, 16 of the 23 captions come back as captions, the
        # coverage pass takes a second opinion from CRAFT before keeping a box,
        # and counted by eye over eight pages 29 of the 30 balloons, captions
        # and asides are boxed. Free, offline, no key, and the same answer
        # twice. `tests/test_the_ai_find_pass_is_gone.py` is the guard.
        #
        # What is given up, said plainly so nobody re-adds it by accident:
        # nothing labels a box by looking at the DRAWING. What a box IS comes
        # from measuring the paper round it -- a straight edge on three sides
        # is a caption, an enclosure is a balloon, bare artwork is outside text
        # -- which is `auto_kind`, and it is measurement and it is still on.
        # Kind is also one click on any box in the editor, and clicking it has
        # never moved a corner. Which was the whole problem with the AI.
        # Stop means stop, and DETECTION is the slowest step of the lot --
        # the routes run 3 to 14 s a page, so a Stop pressed here used to sit
        # there for the rest of the page with nothing to show for it. There is
        # no per-region loop to hang this on before the models have run, so it
        # goes at the top: the page that has not started does not start.
        _stopping.check()
        # WHAT THE PAGE COST, AND WHICH ROUTE SPENT IT.
        #
        # lee: *"ctd is taking 50 second per page, i timmed it"* and *"db++ and
        # coo took 58 seconds"*, against 4.7 and 6.5 measured on 23 pages of
        # manga on two cores. Both routes 10x, which is not a bug in either -
        # it is something about the page or the machine that neither of us can
        # see from a total. So the run reports its own: which route, how big
        # the page was, how long it took. Detection scales with AREA - the same
        # page at 3x is 21.8s on the same cores - so the size is half the
        # answer on its own.
        _t0 = time.time()
        found = self._detect_measured(page, kinds, detector, weights)
        _say_page_cost(self, page, _t0, len(found or []), _t_load)

        # And what the person actually asked for. The measuring detectors are
        # steered by `kinds` - ask for bubbles alone and the free-text passes
        # never run - but the finder that reads the whole page in one go is not:
        # comic-text-detector hands back every block on the page whatever was
        # ticked. It used to walk straight past the choice, which is why the
        # three boxes in the dialog had gone dead. Here they bite again, on
        # whatever came back, whichever way it was found.
        found = only_kinds(found, kinds)
        if no_big_sfx:
            im = page.image
            found = big_sfx(found,
                            im.shape[1] if im is not None else 0,
                            big_sfx_share(self.medium))

        # Find text produces only the three defaults. A detector can measure
        # that something is a closed shape with writing in it; it cannot know
        # that this one is a thought and that one is angry. `narration` was the
        # one exception and it was never a measurement - it is a decision about
        # what the writing IS, so it comes back as a balloon and the person
        # moves it to whatever sub-type they keep captions in.
        # lee: *"teh find text shoud only use teh 3 defasut boxes"*.
        for r in found:
            r.kind = _kinds.detected_kind(r.kind)

        # One balloon is one box, and inside it one section per clump of
        # writing. Blocks read out of the same enclosure are grouped here,
        # before anything is numbered, and the balloon is divided between them
        # by nearness. See detect.balloon.sections_in_one_balloon.
        if found:
            from .detect.balloon import sections_in_one_balloon
            img = page.image
            sections_in_one_balloon(
                cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img,
                found, rtl=self.rtl)

        for n, r in enumerate(found):
            r.id = n
        page.regions = found
        measure_sfx(page)
        score_regions(page.regions)
        assign_order(page, rtl=self.rtl)
        self.pages[i].detected = True
        self.pages[i].cleaned = False        # new text means it needs cleaning
        self.pages[i].width = page.w
        self.pages[i].height = page.h
        # Find text REPLACES this page's boxes, so the ones it superseded do
        # not come back, hidden or not.
        self.commit(i, page, keep_hidden=False)
        # ...and every new outline gets its second opinion at the door: a
        # balloon-claiming box whose outline is not where any balloon is
        # gets flagged before anything downstream trusts it, and one whose
        # writing sits inside a single model balloon gets that balloon as
        # its TYPESETTING shape (`fit_poly` - the cleaner never reads it;
        # lee: "it should only help the typesetter on bubble text"). About
        # a second on the 3-14s this step already costs, and silent when
        # the model or ultralytics is absent. See `balloonck` for the trial
        # it earned its place in.
        from . import balloonck
        balloonck.check_page(self, i, img=page.image)

    def summary(self) -> dict:
        return {
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "settings": {**self.settings,
                         "api_key": "set" if self.settings.get("api_key") else "",
                         # A token in the `.env` outranks the chapter's own -
                         # see `editor.clean_token_for` - so the screen has to
                         # report the one that will actually be SENT.
                         # Reporting the chapter's would print "still the
                         # CHANGE-ME example" under a box that cleans
                         # perfectly well, which is the same class of lie the
                         # third state was added to stop.
                         "clean_token": (ENV
                                         if _userdata.env_key("clean")
                                         else token_state(
                                             self.settings.get("clean_token"))),
                         **{f"{k}_key": ("set" if self.settings.get(f"{k}_key")
                                         else "")
                            # AI_STEPS, not a copy of it: a hardcoded list
                            # here meant a fourth step's key went to the
                            # browser in the clear the moment one was added.
                            for k in AI_STEPS},
                         **{f"key_{s}": (ENV if _userdata.env_key(s)
                                         else ("set"
                                               if self.settings.get(f"key_{s}")
                                               else ""))
                            for s in SERVICES}},
            # Which of the four secrets the `.env` answers for, and where that
            # file is. Booleans and a path; no secret is in here. lee:
            # *"they key shoud be in the .env file and all teh project shoud
            # use them"* - and a file nothing on screen mentions is a file you
            # cannot tell is being read, which is how a stale copy in a
            # chapter goes on being blamed for a key that was rolled.
            "env_keys": _userdata.env_state(),
            "env_path": _userdata.env_path(),
            # `title` was saved, written into every export and used to name
            # the files -- and never sent BACK, so the box in Settings read
            # empty on every reload and the name looked lost. It is story
            # context like the rest of this and it travels with it.
            "context": {"title": getattr(self.ctx, "title", "") or "",
                        "synopsis": self.ctx.synopsis,
                        "glossary": self.ctx.glossary,
                        "characters": dict(
                            getattr(self.ctx, "characters", {}) or {})},
            "job": self.job,
            # How many times taller than wide a page may be before Find text
            # starts mislabelling it. Sent rather than written into the
            # browser, because it is a fact about comic-text-detector's 1024
            # letterbox and it was measured next to the letterbox, in
            # `detect/comictext.py`. A second copy of the number would be a
            # second thing to keep in step.
            "tall_aspect": _ctd.TALL_ASPECT,
            # ...and how big a sound effect may be on THIS format, for the
            # same reason and by the same arrangement. The dialog used to say
            # "about two fifths of the page" in the markup, which was the
            # webtoon number written down twice. See `BIG_SFX_BY_MEDIUM`.
            "big_sfx_share": big_sfx_share(self.medium),
            # ...and which makers have nothing that can be shown a picture, so
            # the AI company menu on READ TEXT can leave them out. Sent for
            # the third time for the third time's reason: which models are
            # blind is `coins.NO_SIGHT`, the model menu is already filtered by
            # it server-side, and a copy of that list in JavaScript would be a
            # menu that goes on offering DeepSeek for a job it cannot do the
            # day the table changes. See `coins.blind_makers`.
            "blind_makers": _coins.blind_makers(),
            # WHICH comic-text-detector is actually being used, so the settings
            # page can say so under an empty "Model file" box. An empty box now
            # means "look beside the app" rather than "give up", and a box that
            # is empty because the file was found is indistinguishable on
            # screen from a box that is empty because nothing was.
            "detector_weights": self.detector_weights(),
            # WHICH chapter this is, beyond which folder it lives in. Every
            # chapter lee makes lives in the same output folder - "new
            # project" is /api/reset on it - so a browser remembering
            # anything per-chapter (the page ticks) needs more than the path
            # to tell two chapters apart. Stamped fresh by /api/reset; ""
            # for a project from before the stamp, which keys as it always
            # did.
            "chapter_id": self.settings.get("chapter_id") or "",
            # Whether the two-specialist route can run on THIS machine, so the
            # dialog can leave the row out rather than offer a tick that does
            # nothing. `partly` means one checkpoint is here and the other is
            # not, which is worth saying out loud -- somebody who downloaded
            # one file and stopped should be told which one is missing.
            "two_specialists": {
                "ready": bool(self.route_here("two_specialists")
                              and self.coo_weights()
                              and not self.why_not_two_specialists()),
                # `partly` is what puts a DISABLED row on screen with the
                # reason in it, and it is false on a manhwa on purpose: a
                # format this was never measured on should not be shown a
                # switch at all, where a manga missing one download should.
                "partly": self.route_here("two_specialists"),
                "on": bool(self.settings.get("two_specialists")),
                "why": self.why_not_two_specialists(),
            },
            # ...and the same three answers for the AnimeText route, which is
            # offered on all three formats and so asks `ANIME_MEDIA`. It asked
            # `TWO_MEDIA` here for as long as those were the same set, and
            # went on asking it after they stopped being - which showed as a
            # card missing from a manhwa whose route ran perfectly well on
            # one. The guard a row is drawn from has to be the guard the run
            # is decided by.
            "animetext": {
                "ready": bool(self.route_here("animetext")
                              and self.animetext_weights()
                              and not self.why_not_animetext()),
                "partly": self.route_here("animetext"),
                "on": bool(self.settings.get("animetext")),
                "why": self.why_not_animetext(),
            },
            # ...and for the two webtoon models, which are the other way
            # round: offered on a strip and guarded off a manga.
            "webtoon_ko": {
                "ready": bool(self.route_here("webtoon_ko")
                              and self.webtoon_ko_weights()
                              and not self.why_not_webtoon_ko()),
                "partly": self.route_here("webtoon_ko"),
                "on": bool(self.settings.get("webtoon_ko")),
                "why": self.why_not_webtoon_ko(),
            },
            "webtoon_zh": {
                "ready": bool(self.route_here("webtoon_zh")
                              and self.webtoon_zh_weights()
                              and not self.why_not_webtoon_zh()),
                "partly": self.route_here("webtoon_zh"),
                "on": bool(self.settings.get("webtoon_zh")),
                "why": self.why_not_webtoon_zh(),
            },
            # ...and the same three answers for the Manga109 route, which
            # needs one 23MB file instead of two large ones.
            "manga_segmenter": {
                "ready": bool(self.route_here("manga_segmenter")
                              and self.m109_weights()
                              and not self.why_not_manga_segmenter()),
                "partly": self.route_here("manga_segmenter"),
                "on": bool(self.settings.get("manga_segmenter")),
                "why": self.why_not_manga_segmenter(),
            },
            "pages": [{
                "index": i, "name": p.name, "width": p.width, "height": p.height,
                # `regions` is the count that counts: the work on this page.
                # `boxes` is everything stored, hidden included, so the browser
                # can say "9 text boxes, 3 hidden" without a second request.
                # A text box of your own is not one of them: it is typesetting
                # you added, with nothing under it to read and nothing to
                # translate, and counting it made the rail say a page had two
                # pieces of text when it had one.
                "regions": len([r for r in p.active if not r.get("own_text")]),
                "boxes": len(p.regions),
                "hidden_boxes": len(p.hidden),
                "kinds": p.groups_present,
                "hidden": list(p.hidden_kinds or []),
                "ocr": p.n_ocr,
                "translated": p.n_translated, "typeset": p.n_typeset,
                "proofread": p.n_proofread, "cleaned": bool(p.cleaned),
                # A page whose cleaned plate the person supplied. It is not
                # cleaned and never will be, so the Clean step has to count it
                # as done or it never reaches the end and Typeset stays locked.
                "custom_clean": bool(p.custom_clean),
                "status": p.status(), "exported": p.exported,
            } for i, p in enumerate(self.pages)],
        }
