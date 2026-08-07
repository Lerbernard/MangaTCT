"""Chapter-level project state.

Regions are held as geometry (a polygon plus metadata), never as bitmaps — a
40-page chapter with eight bubbles a page would otherwise sit on close to a
gigabyte of masks. Masks are rebuilt from the polygon on demand, for the page
being edited or exported.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import cv2
import numpy as np

# How long a coalescing save waits for the next edit before writing. Long
# enough that a run of presses is one write, short enough that closing the
# window a moment after an edit still has it on disk.
SAVE_DELAY = 0.4

from . import kinds as _kinds
from .detect import classical
from .order import assign_order
from .pipeline import load_page
from .score import score_regions
from .translate import SeriesContext
from .models import Page, TextRegion

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
    alphabetical order puts 100 between 10 and 11 — page 2 of the chapter ends
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


# The three steps that call a model. Named here as well as in `editor` because
# this is where their settings live; `editor.AI_STEPS` is the same three and a
# test says so.
AI_STEPS = ("ocr", "translate", "proofread")


def migrate_engine(settings: dict, saved: dict) -> bool:
    """Carry an old project's one engine onto its three steps.

    A project.json written before the per-step boxes existed has `backend`,
    `model`, `base_url` and `api_key` and nothing per step — and the screen
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


def migrate_keys(settings: dict, saved: dict) -> bool:
    """Lift a project's per-step keys into the one box per service.

    A key is a fact about the provider, not about the step. Three boxes meant
    typing the same Google key twice and meant it could be right in one and
    stale in the other, with nothing on screen saying which of the two a run
    would use.

    Only onto services the file left EMPTY, so a service key that has been
    changed since is never overwritten by a per-step leftover — the whole point
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
        # values merged over the defaults, and the default is empty — so a
        # non-empty one here can only have come from the file, which makes
        # this the same question as asking `saved`. It was asked both ways
        # until a mutant showed the two were indistinguishable.
        if str(settings.get(f"key_{back}") or "").strip():
            continue
        settings[f"key_{back}"] = key
        moved = True
    return moved


def region_record(r: TextRegion) -> dict:
    return {
        "id": int(r.id), "bbox": [int(v) for v in r.bbox],
        "bubble_bbox": [int(v) for v in r.bubble_bbox] if r.bubble_bbox else None,
        "polygon": [[int(a), int(b)] for a, b in (r.polygon or [])],
        "kind": str(r.kind), "order": int(r.order),
        "link": int(getattr(r, "link", 0) or 0),
        "box_group": int(getattr(r, "box_group", 0) or 0),
        "src_text": r.src_text, "src_vertical": bool(r.src_vertical),
        "angle": round(float(getattr(r, "angle", 0.0) or 0.0), 2),
        "sfx_vertical": bool(getattr(r, "sfx_vertical", False)),
        "sfx_len": round(float(getattr(r, "sfx_len", 0.0) or 0.0), 4),
        "sfx_wid": round(float(getattr(r, "sfx_wid", 0.0) or 0.0), 4),
        "dst_text": r.dst_text, "dst_compact": r.dst_compact,
        "speaker": r.speaker, "confidence": float(r.confidence),
        "flagged": r.flagged, "manual": bool(getattr(r, "manual", False)),
        "own_text": bool(getattr(r, "own_text", False)),
        "skip_clean": bool(getattr(r, "skip_clean", False)),
        # How this box was cleaned, so the question can be asked of a BOX
        # rather than of a whole chapter. Not restored on the way in
        # (region_from_record leaves it empty): it is a fact about the last
        # run, and a stale answer is worse than none.
        "clean_route": str(getattr(r, "clean_route", "") or ""),
        "clean_core": bool(getattr(r, "clean_core", False)),
        "draw_box": getattr(r, "draw_box", None),
        "layout_override": r.layout_override,
        "layout": ({"lines": r.layout.lines,
                    "font_size": int(r.layout.font_size),
                    "leading": round(float(r.layout.leading), 3),
                    "origins": [[int(a), int(b)] for a, b in r.layout.line_origins],
                    "fg": r.layout.fg, "edge": r.layout.edge,
                    "stroke": int(r.layout.stroke),
                    "font": r.layout.font_path or "",
                    "rotate": float(getattr(r.layout, "rotate", 0.0)),
                    "frame": list(getattr(r.layout, "frame", None) or []),
                    # Two blocks in one box — a speech shared between the
                    # lobes of a double balloon — so the browser must use the
                    # origins above rather than spacing them down the frame.
                    "fixed": bool(getattr(r.layout, "fixed", False)),
                    "fit_ok": bool(r.layout.fit_ok),
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
    the typesetting has to fit inside — so it must not be loaded back as one.
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

    Masks are not saved — a chapter is held as geometry — so the balloon has
    to be found again on the way back in. It was only ever looked for at
    detection, which left two ways to end up typesetting into a rectangle: a
    region saved before the balloon finder could see it, and a box the person
    drew or tightened by hand. The box says which balloon the words belong to.
    It is not the shape they have to fit.

    Anything that already carries a real outline is left alone, so a balloon
    found once is not searched for again, and a region with no balloon to find
    costs one look and then falls back to its box.

    Whatever is still left with nothing then gets the empty paper around its
    writing instead of the bare box — see `give_room`. That is the writing with
    no balloon at all: a caption printed straight onto a blank panel. It used
    to typeset at 12pt in the tall narrow column the Japanese was set in.
    """
    from .detect.balloon import attach_balloons, give_room
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    got = attach_balloons(gray, regions)
    give_room(gray, regions)
    return got


# Kinds that cannot have a balloon: writing brushed onto the artwork, and sound
# effects. Kept here as well as in the editor because this is the door every
# page comes back through.
# The two families that never have a balloon: writing lying on the artwork,
# and a drawn sound. A sub-type is unballooned when its FAMILY is — a box's
# geometry is decided by which of the three it is, never by which sub-type.
NO_BALLOON_KINDS = ("freefloat", "sfx")


def _no_balloon(kind: str) -> bool:
    return _kinds.family_of(kind or "") in NO_BALLOON_KINDS


def region_from_record(rec: dict, img: np.ndarray) -> TextRegion:
    """Rebuild masks from the stored polygon."""
    H, W = img.shape[:2]
    poly = np.array(rec.get("polygon") or [], dtype=np.int32)
    # The LABEL wins over the geometry, always. Calling a box outside text says
    # there is no balloon round it, and a region saved while it was still
    # called speech has the old outline sitting in its record — lee changed the
    # type, saw it work, restarted, and got the panel back, because nothing
    # rewrites that outline except the moment of the change itself. Reading it
    # as a box here means the answer no longer depends on when it was saved.
    no_balloon = _no_balloon(rec.get("kind"))
    boxy = _is_a_box(poly) or no_balloon
    bubble = np.zeros((H, W), np.uint8)
    if not boxy:
        cv2.drawContours(bubble, [poly.reshape(-1, 1, 2)], -1, 255, cv2.FILLED)
    else:
        # This rectangle is also where the WRITING is read from, two lines
        # down. A region relabelled outside text still carries the old
        # balloon's `bubble_bbox`, and reading the writing out of that would
        # hand the cleaner a whole panel of artwork to erase — so once the
        # label says there is no balloon, the box round the writing is the
        # only rectangle left that means anything.
        x, y, w, h = (rec["bbox"] if no_balloon
                      else (rec["bubble_bbox"] or rec["bbox"]))
        bubble[y:y + h, x:x + w] = 255

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    glyph = ((gray <= INK) & (bubble > 0)).astype(np.uint8) * 255

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
        skip_clean=bool(rec.get("skip_clean", False)),
        link=int(rec.get("link", 0) or 0),
        box_group=int(rec.get("box_group", 0) or 0),
        order=rec.get("order", -1), src_text=rec.get("src_text", ""),
        src_vertical=rec.get("src_vertical", True),
        dst_text=rec.get("dst_text"), dst_compact=rec.get("dst_compact"),
        speaker=rec.get("speaker"), confidence=rec.get("confidence", 0.0),
        flagged=rec.get("flagged"),
        layout_override=rec.get("layout_override"),
        # A record written before the axis reader existed has none of these,
        # and loads as "never measured" rather than as "measured at zero".
        angle=float(rec.get("angle") or 0.0),
        sfx_vertical=bool(rec.get("sfx_vertical", False)),
        sfx_len=float(rec.get("sfx_len") or 0.0),
        sfx_wid=float(rec.get("sfx_wid") or 0.0),
    )
    r.manual = rec.get("manual", False)      # type: ignore[attr-defined]
    r.locked = rec.get("locked", False)      # type: ignore[attr-defined]
    # A text box somebody put on the page themselves. It stands for no writing
    # in the artwork, so there is nothing to read, nothing to translate and
    # nothing under it to erase — see the region endpoint in editor.py.
    r.own_text = bool(rec.get("own_text", False))   # type: ignore[attr-defined]
    # A block with typesetting is typeset again from scratch by whichever stage
    # asked for it, so its stored layout is not carried in. A block with NO
    # typesetting has nothing to derive one from, and its frame — the size the
    # person left the box at after deleting the words — is only in the record.
    lay = rec.get("layout") or {}
    if lay and not lay.get("lines") and lay.get("frame"):
        from .typeset import TextLayout
        r.layout = TextLayout(
            lines=[], font_size=int(lay.get("font_size") or 12),
            leading=float(lay.get("leading") or 1.2),
            line_origins=[], score=0.0,
            font_path=str(lay.get("font") or ""),
            fit_ok=True, frame=[int(v) for v in lay["frame"]])
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
    # off a picture of the entire page — a couple of dozen pixels of typesetting
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
    # uses this file instead of running the inpainter — per page, so page 3
    # can be hand-cleaned while 1, 2, 4 and 5 stay automatic.
    custom_clean: str = ""
    # What the proofreader could not fix by itself — an unclear pronoun, a
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
    # drawn and takes no part in any stage — it is not read, translated,
    # cleaned, typeset or exported — and it is NOT deleted: the boxes sit in
    # `regions` untouched and come back the moment the tick goes back on.
    hidden_kinds: list[str] = field(default_factory=list)
    # ...and the individual boxes put away one at a time, by id. Same rule in
    # every other respect: not drawn, not read, not cleaned, not typeset, not
    # exported, and not deleted. lee: *"add a eye button to the [row] in teh
    # original page thag allow me to hid a box, just like i can hide all the
    # sfx box — i shud be able to hide individual boxes"*.
    hidden_ids: list[int] = field(default_factory=list)
    # The next id to hand out on this page, and it only ever goes up.
    #
    # Ids used to be `max(existing) + 1`, which REUSES the number of a box you
    # deleted. Everything the editor holds about a box while it is in the air
    # is keyed by that number — the edit whose save has not come home, the
    # pending keystroke, the undo snapshot — so a box drawn after a delete
    # inherited the dead one's words. lee: *"when i deleet an text box and
    # create a new one it come back with teh same text as teh olde text box"*.
    #
    # 0 means "not written down yet": an old project.json has no counter, and
    # `next_region_id` starts it above whatever is on the page.
    next_id: int = 0

    def new_region_id(self) -> int:
        """A number no box on this page has ever had."""
        nxt = max(int(self.next_id or 0),
                  max((int(r.get("id", -1)) for r in self.regions),
                      default=-1) + 1)
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
        # follows — an empty one filters nothing out, so the guard could not be
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
        """The boxes that count — everything except a hidden group."""
        return [r for r in self.regions if self.shown(r)]

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
        # detected boxes in — a control that hides nothing.
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
            # error — nothing to translate, so it passes green. A page whose
            # every box is hidden is the same case: there is nothing to do.
            return "done" if self.detected else "pending"
        if self.n_translated == n:
            return "translated"
        if self.n_ocr:
            return "ocr"
        return "detected"


# The three groups the person deals in. One table, because what you can ask
# Find text to look for and what you can hide afterwards are the same question
# asked twice — "which of these three kinds of writing am I working with".
#
# A narration caption used to answer to the box for text outside bubbles, on the
# grounds that it stands outside a speech balloon. lee moved it: *"rename the
# firts check box to speach and nataion bubble"*. A caption is a box with
# dialogue in it — it is read in the reading order, translated as speech and
# typeset like speech — and grouping it with the loose text lying on the
# artwork put it with the one group whose boxes are the least like it.
#
# Anything the model invents a name for that is in none of the groups is kept:
# a box is worth more than a tidy vocabulary. The same rule holds for hiding —
# a custom text type is never hidden by these three.
# The three families, and the sub-types each one covers. The sub-types are no
# longer a fixed list — a person adds, renames and deletes their own — so this
# is only the SHAPE of the thing: which families exist, and what each one's
# undeletable default is called. `kinds.subs_of` answers the rest, from the
# open project. See kinds.py.
KIND_GROUPS = {f: (f,) for f in _kinds.FAMILIES}


def group_of(kind: str) -> str:
    """Which of the three families a kind belongs to.

    Never "" now. Every kind belongs to a family, including one whose sub-type
    has since been deleted — a box pointing at a sub-type that is gone still
    has to draw, still has to be cleaned, and still has to obey the switch
    that puts its family away.
    """
    return _kinds.family_of(kind or "")


def only_kinds(found, kinds):
    """The regions whose FAMILY the person actually ticked.

    The Find text dialog asks about the three main types, and a box belongs to
    one of them however finely it has been labelled since — so this is a
    question about families, not about kinds. It always was: a caption box
    used to answer to the balloon tick because a caption is a box with
    dialogue in it, and a caption is a sub-type of balloon now, which is the
    same answer arrived at from the model rather than from a list.
    """
    want = {k for k in (kinds or []) if k in _kinds.FAMILIES}
    if not want:
        return found
    return [r for r in found if group_of(r.kind) in want]


def token_state(tok: str | None) -> str:
    """What the settings screen may say about a saved cleaner token.

    "" — nothing saved. "set" — a real one. "placeholder" — the CHANGE-ME
    example that every *_clean_modal.py carries in its header comment.

    The third state exists because it cost a week. The field reported "(saved)"
    for anything non-empty, the example token IS non-empty, and so a project
    whose token had never actually been filled in looked exactly like a
    configured one — while the endpoint answered 401 to every call and the
    editor quietly drew a Telea smear instead of saying so.

    The token itself never leaves the server: only which of the three.
    """
    t = (tok or "").strip()
    if not t:
        return ""
    return "placeholder" if t.upper().startswith("CHANGE-ME") else "set"


class Project:
    def __init__(self, input_dir: str | None, output_dir: str):
        self.input_dir = os.path.abspath(input_dir) if input_dir else ""
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.state_path = os.path.join(self.output_dir, "project.json")
        # Saving is coalesced onto one background thread — see `save_soon`.
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
            # face has ever carried — a music note, a heart, a full-width
            # bracket — which is most pages, and none of them are wrong. So
            # the default is the one that typesets, and turning it off is how
            # you ask to be told instead. See `TypesetConfig.substitutes`.
            "substitutes": True,
            # Translating by hand. With this on, the three steps that ask an
            # AI for words — Read text, Translate, Proofread — are greyed and
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
            # material" — a phrase in the box where the answer should be.
            # lee: *"remove all instandt of same as ... it shud just pre fill
            # it with teh potion"*. "auto" is still READ, because old projects
            # are full of it, and it still means exactly this.
            "source": "ja",
            # How finely a page is cut up before it goes to the AI reader:
            # page (one image, fastest) | auto (up to 4 pieces) | high (up to 9)
            "ocr_detail": "auto",
            "direction": "rtl",    # rtl | ltr ("auto" still read, see above)
            "detector": "comictext", "weights": "", "text_weights": "",
            "auto_kind": True,     # comic-text-detector: label each box bubble/outside/narration
            # There was an "ai_boxes" setting here — a pass that showed the
            # numbered page to the AI at Find text and let it judge the boxes.
            # It is gone; lee: "nvm remove it its pretty bad remove the ai".
            # Find text is measurement only again, and a project.json saved with
            # the old key simply carries a setting nothing reads. Nothing about
            # the AI READER or the translator changed — those are the useful
            # ones and they are untouched.
            # A webtoon does not arrive as pages. It is drawn as one strip and
            # the site that serves it slices that strip into tiles of a fixed
            # height, counting pixels and never looking at the artwork — on
            # lee's chapter 1, 38 of the 104 cuts went through the typesetting.
            # So when a chapter arrives looking like that it is joined back up
            # and cut again at the gutters, on upload, without being asked.
            # See `restitch_if_sliced` and `strip.py`.
            "restitch_strips": True,
            "strip_target": 2400,   # what a page should come out at
            "strip_max": 6000,      # past this a page is too tall to read from
            "export_dir": "", "export_name": "pages",
            "backend": "anthropic", "base_url": "",
            "model": "claude-sonnet-5", "api_key": "",
            # AI cleaning (hosted manga inpainter): off | hard | all
            "ai_clean": "off", "clean_url": "", "clean_token": "",
            # The model each step runs on, and the WHOLE of what it runs on:
            # there is no project-wide engine behind these any more. There were
            # two of them — a "Claude model" menu and a "Translation engine"
            # menu — and between them they answered the same question these
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
            # engine", and blank is no longer a thing that can mean anything —
            # a step with no model would be a step the price screen could not
            # name. See `editor.STEP_DEFAULTS`, which these have to agree with.
            "ocr_model": "gemini-3.5-flash-lite", "ocr_backend": "gemini",
            "ocr_base_url": "", "ocr_key": "",
            "translate_model": "gemini-3.6-flash", "translate_backend": "gemini",
            "translate_base_url": "", "translate_key": "",
            "proofread_model": "claude-sonnet-5", "proofread_backend": "anthropic",
            "proofread_base_url": "", "proofread_key": "",
            # THE STORY SWITCHES. lee: *"add a story setting that allow the
            # user ti turn the story thing off, and to tun what the ai detects
            # with check boxes"*.
            #
            # `story` off means the synopsis, the character sheet and the
            # glossary are neither sent with a page nor added to by the reply.
            # The sheets themselves are left alone — switching it back on
            # finds them as they were.
            #
            # All four default TRUE, which is what every project did before
            # they existed, so nothing changes for a chapter already in
            # progress.
            "story": True,
            "learn_characters": True,
            "learn_terms": True,
            "name_speakers": True,
            # ONE KEY PER SERVICE, not one per step.
            #
            # A key is a fact about the provider, not about the step: the same
            # Google key that reads the page translates it. Three steps meant
            # typing the same key three times and, worse, meant a key could be
            # right in one box and stale in another with nothing on screen to
            # say which of the two a run would use. The per-step boxes above
            # are still READ — an old project.json that has not been saved
            # since still works, see `migrate_keys` — and nothing writes them.
            "key_anthropic": "", "key_gemini": "", "key_openrouter": "",
        }
        # A new project starts with the sub-types every project starts with —
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

        The medium sets the default, but some series break the rule — a
        Japanese webtoon reads left-to-right — so it can be overridden.
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
        """What language the pages are written in — chosen explicitly, or
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
                pass
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
            img = cv2.imread(p)
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

    # --------------------------------------------------------- webtoon strips
    def restitch_if_sliced(self, force: bool = False) -> dict:
        """Put a sliced webtoon back together and cut it at the gutters.

        Runs by itself when a chapter finishes loading, because the tiles a
        webtoon site serves are not pages: they are the strip chopped every
        so many pixels by something counting, straight through balloons and
        through the typesetting inside them. Half a word on one file and half on
        the next cannot be read, cannot be cleaned, and has nowhere to put the
        English.

        It does nothing unless `looks_sliced` is sure — see `strip.py` for how
        narrow that test is — and nothing at all once there is work on the
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
        if any(pg.detected or pg.regions or pg.typeset or pg.cleaned
               for pg in self.pages):
            return {}
        tiles = [pg.path for pg in self.pages]
        if not _strip.looks_sliced([(pg.height, pg.width) for pg in self.pages]):
            return {}

        target = int(self.settings.get("strip_target") or _strip.TARGET_H)
        ceiling = int(self.settings.get("strip_max") or _strip.MAX_H)
        own = os.path.abspath(self.input_dir or "") == os.path.abspath(
            os.path.join(self.output_dir, "input"))
        if own:
            # The tiles are in our own upload folder, so the pages can replace
            # them where they stand and everything that reads `input_dir` —
            # rescan, adding more pages later — carries on unchanged. The tiles
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
        img = cv2.imread(dest)
        if img is None:
            os.remove(dest)
            return -1
        # Appending must never discard pages already in the project — the
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

        The FILE moves, not just the label — the name in the list is the name on
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
        # extension with nothing in front of it — so without this, renaming to
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
        leaves a truncated file — which is not a lost edit, it is a lost
        chapter. `os.replace` is atomic, so the file on disk is always either
        the whole of the last save or the whole of this one.
        """
        with self._dirty_lock:
            self._dirty = False          # anything after this marks it again
        with self._save_lock:
            # Serialise BEFORE opening anything. A job thread editing a page
            # halfway through this raises rather than writing half a state, and
            # `_save_loop` marks it dirty again and comes back — so the file on
            # disk is never a torn one.
            data = json.dumps(self._state(), ensure_ascii=False)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, self.state_path)

    def save_soon(self) -> None:
        """Write it out in a moment, once, however many times this is called.

        Every small edit — a box renumbered, a type changed, one deleted, a
        line of typesetting nudged — used to serialise and write the whole
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
        # those standing when the saved project names none — so every old
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
        # a project full of it is written out here — once, on load — as the
        # thing it always resolved to. Nothing changes about how the chapter
        # reads; the settings file just says it now.
        #
        # A medium the app no longer offers gets the same treatment first, and
        # it matters more: "comic" is gone, and `MEDIA.get(medium, MEDIA
        # ["manga"])` — which is what every reader of this setting does — would
        # quietly hand back Japanese and right-to-left for an English western
        # comic. So pin what the medium was ANSWERING for, THEN move it to one
        # that still exists.
        #
        # Read off the FILE, not off `self.settings`: the constructor has
        # already put "ja" and "rtl" in there for a new project, and the
        # `update` above leaves them standing when the saved project names
        # neither — so every old project would look as though it had answered
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
        # is brought up to date on every load — `migrate` is idempotent, so it
        # also re-checks that every sub-type's colour is still one its own
        # family issues. See kinds.py.
        # What is remembered is WHICH preloaded sub-types have been offered,
        # not whether seeding has happened at all — see kinds.migrate. The old
        # `kinds_seeded` flag was set by a build whose PRELOADED list was
        # empty, so a project stamped with it could never receive the ones
        # added since. An old project has no list, so nothing has been offered
        # to it and it gets the lot once.
        #
        # Read off the FILE, not off `self.settings`: the constructor puts a
        # full list there for a brand-new project, and the `update` above
        # leaves it standing when the saved project has none — so every old
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
        # record now — it is part of what that sub-type IS — so a project that
        # set an italic for thought balloons keeps it.
        fonts = self.settings.get("fonts") or {}
        for sub in self.settings["custom_kinds"]:
            if not sub.get("font") and fonts.get(sub["key"]):
                sub["font"] = fonts[sub["key"]]
        _kinds.use(self.settings["custom_kinds"])
        self.ctx = SeriesContext(**(d.get("context") or {}))
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
        painted onto it — the page as it now stands.

        A balloon's shape is read off the drawn outline around the words, and
        that outline is part of the artwork, which a person is allowed to
        mend. lee: *"the clenner ... errased some of a side of a box, now the
        typesetting thinks the bubble is bigger than it accually is. i clenned
        the bubble and added the edge back but the typeseetting is not
        registerng that"*.

        Measured on a fixture of two balloons sharing a wall: nick the wall
        and the run of paper joins the neighbour, so the shape comes back
        50,578px against the 25,137 it should be. Paint the wall back and the
        search has to be looking at THIS picture to see it — the scan alone
        still has the hole.

        Only the under-text band. Paint that sits above the typesetting is
        drawn over the finished page and is not part of the artwork the words
        are laid into.
        """
        img = self.image(i)
        ov = getattr(self.pages[i], "paint_overlay", "") or ""
        if not ov or not os.path.exists(ov):
            return img
        o = cv2.imread(ov, cv2.IMREAD_UNCHANGED)
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
        would delete every hidden one — hiding a group would quietly destroy it
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
    # There were three helpers here — _ai_ctx, _ai_mode and _can_ask — and every
    # one of them existed only to feed the AI box pass at Find text. That pass is
    # gone, so they are gone with it. The reader and the translator sync the
    # backend onto self.ctx themselves, in editor.py, and always did.

    def detect(self, i: int, kinds: list[str] | None = None) -> None:
        """`kinds` picks what to look for: bubbles, free-floating text, or
        both. Detection is no longer automatic, so this is always a choice
        the person made."""
        kinds = kinds or ["bubble"]
        page = Page(image=self.image(i), source_path=self.pages[i].name)
        weights = self.settings.get("weights") or ""
        detector = self.settings.get("detector")

        found = []
        if detector == "comictext" and weights:
            # comic-text-detector finds ALL text directly, already grouped into
            # tight non-overlapping blocks, so it ignores the bubble/free split.
            from .detect import comictext
            # The gap that ends one block of writing was once lee's slider. It
            # is gone: he asked for "the whole split box by distance" removed,
            # because a body of writing is ONE box however wide the paper is
            # between its columns. What is left is the model's own built-in.
            found = comictext.detect_comictext(
                page, weights,
                classify=self.settings.get("auto_kind", True))
        else:
            if "bubble" in kinds:
                if detector == "yolo" and weights:
                    from .detect import yolo
                    found = yolo.detect_hybrid(
                        page, weights,
                        text_weights=self.settings.get("text_weights") or "")
                else:
                    found = classical.detect_combined(page)

            if "freefloat" in kinds or "sfx" in kinds:
                from .detect import freetext as _ft

                # Read the writing that is typeset straight onto the drawing,
                # and read it FIRST.
                #
                # Every detector above is enclosure-first: it looks for a shape
                # that HOLDS glyphs. Manga typesets a large part of its text over
                # bare artwork, so that text is either missed outright — lee's
                # "it missed a bunch of pages in teh last page" — or found by
                # accident when a pale panel happens to enclose it, and then the
                # box is the whole panel, which is his box 5.
                #
                # It used to run last, after `detect_free_text`, and that is
                # what put three boxes round the shout on his page 39 and left
                # 私…っ outside the box on his page 38. `detect_free_text`
                # groups by closing the ink with a 13-pixel brush, which is
                # narrower than the space between two columns of Japanese, so
                # it hands back one box per column and the reader — which knows
                # the columns are one passage — then finds the passage already
                # taken and stands aside. Reading first puts one box round the
                # whole body of writing, and the stroke-cluster pass keeps only
                # what is left over.
                enclosed = list(found)
                found += _ft.read_the_writing(page, found)

                # The stroke pass is shown the SAME page it was always shown —
                # the balloons blanked out, the writing on the art left alone —
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
                # sitting inside it — a box round a single kanji, a box round
                # the ruby beside it — is a piece of that body, not a text of
                # its own.
                found = _ft.absorb_fragments(found)

        # The AI used to get a turn here: the page went out numbered and it
        # judged the boxes. lee, having watched it: "nvm remove it its pretty bad
        # remove the ai". So there is no turn. Find text is measurement, from the
        # first pass to the last, and it costs nothing and needs no network.
        #
        # Say plainly what that gives up, so nobody quietly re-adds it: nothing
        # now labels a box by looking at the DRAWING. A caption in a ruled box is
        # called a balloon because a rule was measured round it, and a sound
        # effect brushed onto bare artwork is called freefloat unless
        # comic-text-detector's own kind head says otherwise (that is
        # `auto_kind`, which is measurement too and is still on). The kind is
        # also a thing lee can set on any box by hand in the editor in one click,
        # which is the whole reason this is an acceptable trade — and unlike the
        # AI, clicking it never moved a corner.

        # And what the person actually asked for. The measuring detectors are
        # steered by `kinds` — ask for bubbles alone and the free-text passes
        # never run — but the finder that reads the whole page in one go is not:
        # comic-text-detector hands back every block on the page whatever was
        # ticked. It used to walk straight past the choice, which is why the
        # three boxes in the dialog had gone dead. Here they bite again, on
        # whatever came back, whichever way it was found.
        found = only_kinds(found, kinds)

        # Find text produces only the three defaults. A detector can measure
        # that something is a closed shape with writing in it; it cannot know
        # that this one is a thought and that one is angry. `narration` was the
        # one exception and it was never a measurement — it is a decision about
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
                found)

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

    def summary(self) -> dict:
        return {
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "settings": {**self.settings,
                         "api_key": "set" if self.settings.get("api_key") else "",
                         "clean_token": token_state(
                             self.settings.get("clean_token")),
                         **{f"{k}_key": ("set" if self.settings.get(f"{k}_key")
                                         else "")
                            for k in ("ocr", "translate", "proofread")},
                         **{f"key_{s}": ("set" if self.settings.get(f"key_{s}")
                                         else "")
                            for s in SERVICES}},
            "context": {"synopsis": self.ctx.synopsis,
                        "glossary": self.ctx.glossary,
                        "characters": dict(
                            getattr(self.ctx, "characters", {}) or {})},
            "job": self.job,
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
