"""A second opinion on every balloon - and a better shape for the typesetter.

lee: *"try the recomendation and sjwo some exmapke and evaluate it"*, then
*"alright add it"*, then *"ok it it good enought to use it more than just a
warning, espaesialy with the typesetter for bubble"*, then the scope drawn
exactly: *"it should only help the typesetter on bubble text"*. The
recommendation came out of the wheel audit (2026-08-30): the one thing the
field has that this app did not is a model that segments SPEECH BALLOONS as
shapes - and our most persistent bug family is a saved outline that is not
the balloon (an outline tracing a character, a loose rectangle, handwriting
filed as a bubble).

## What this is, and pointedly is not

A HELPER FOR THE TYPESETTER, and for nothing else. Measured on lee's own
chapter before it was built: 142 outlines against the model's balloons -
median disagreement 2.4% of the outline, and the model's own rims only reach
median IoU 0.896 (the documented "wavy edges"). A shape that loose must not
overwrite a sound outline the detector fitted to the ink - and it must not
go anywhere near the CLEANER, whose masks come from `polygon` and whose
every past adjustment moved something else. So on a FLAGGED box - one whose
outline the measurement says is broken - the model's balloon is written to
`fit_poly`, a field only `typeset.share_masks` reads: the words go where the
balloon is, the eraser keeps reading the outline it always read, and
`polygon` is never touched by this module at all.

Scoped to the bubble family, because only a balloon-claiming box can be
wrong about its balloon; an aside is handwriting on artwork and correctly
overlaps no balloon at all. With that scope and `SPILL_FLAG = 0.20`, the
trial chapter raised exactly three flags - a saved outline tracing a
character instead of its balloons (page 005), a loose rectangle (019), and
wall-writing misfiled as a bubble (014) - and zero false alarms. The first
two now typeset into the model's balloon; the third has no balloon to fit
to and stays a flag, which is right - its problem is its KIND.

## Where and when it runs

* at the end of `Project.detect`, on the boxes it just made - the door;
* once per chapter per app run, in `warm_pages`' background sweep, for
  chapters opened with boxes already on them - after the plates and the
  finished pages. Both places do the same thing: a fit that cannot touch
  the cleaner has no cost that depends on where it happens.

Either way it costs about a second a page on CPU (`m109seg.pt`, 23MB,
already beside the app), and `_page_print` remembers what it has checked so
an unchanged page is never checked twice in one run. The print is held in
memory rather than on the record: `PageState(**p)` is strict, so a new
stored field would break opening the chapter in an older build - one
re-sweep per app start is cheaper than that.

The model file missing, ultralytics missing, or
`settings["balloon_check"] = "off"` all mean the same thing: no check, no
flags, no error. An advisory that cannot run must cost nothing.
"""
from __future__ import annotations

import hashlib
import os
import threading

import cv2
import numpy as np

from . import kinds as _kinds

WEIGHTS_NAME = "m109seg.pt"
SPILL_FLAG = 0.20          # flagged past this; 019's loose rectangle was 0.21
NO_BALLOON = 0.90          # past this the box overlaps no balloon worth naming
CONF = 0.25
IMGSZ = 1024

# The sentences this module owns. Re-checks strip and re-add them, so a
# page checked twice carries one opinion - and nothing else that writes flags
# uses these words, so nothing else's flag is ever stripped.
OFF_BALLOON = "the outline runs off its balloon"
NOT_A_BALLOON = "no balloon here - the outline may be artwork, or this box wants another kind"
FITTED = "typesetting fitted to the balloon the model sees"

# For a FIT, the model's balloon must actually be where the writing is: this
# share of the box's own rectangle has to sit inside it. Without this, a
# broken outline next to somebody else's balloon would be "fixed" onto that
# balloon - a worse page than the broken one, delivered silently.
FIT_HOLDS = 0.60
# ...and a balloon holding this much of ANOTHER box too is a shared balloon -
# a real one, or a double bubble the model reads as one connected shape - and
# its division belongs to `typeset.share_masks`, not to this.
SHARED_HOLDS = 0.30

_lock = threading.Lock()
_model = None
_model_path = ""
_done: dict[tuple[str, int], str] = {}     # (output_dir, page) -> print


def weights_path(p) -> str:
    """Named in settings, or `m109seg.pt` beside the other checkpoints."""
    named = str(p.settings.get("balloon_weights") or "").strip()
    if named:
        return named if os.path.isfile(named) else ""
    fp = os.path.join(p._weights_dir(), WEIGHTS_NAME)
    return fp if os.path.isfile(fp) else ""


def _engine_present() -> bool:
    """Is the thing that runs the model installed? Its own function so a test
    that has stubbed `_balloons` can say so and be believed. CI installs five
    packages and ultralytics is not one of them, and for three weeks that
    turned nine tests about the CHECK into nine tests about the runner."""
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return False
    return True


def available(p) -> bool:
    if str(p.settings.get("balloon_check") or "").strip().lower() == "off":
        return False
    if not weights_path(p):
        return False
    return _engine_present()


def _balloons(img: np.ndarray, path: str) -> list:
    """Every balloon the model sees on this page, one mask each.

    INSTANCES, not a union: a double bubble is one connected white shape and
    the model reads it as one balloon, and the fit below must be able to see
    that that one balloon holds two boxes - lee, on page 022: *"thesy hsoud
    stil be detected as two seperate ballons not merge into one"*. The check
    never merges his boxes (detection is untouched); what it must never do
    is hand a merged shape to either box's fitter, and telling instances
    apart is how it refuses to.
    """
    global _model, _model_path
    with _lock:
        if _model is None or _model_path != path:
            from ultralytics import YOLO
            _model, _model_path = YOLO(path), path
        from . import cores
        cores.claim()            # ultralytics just set OMP to 1; undo it
        res = _model(img, verbose=False, conf=CONF, imgsz=IMGSZ)[0]
    h, w = img.shape[:2]
    out = []
    if res.masks is None:
        return out
    names = getattr(_model, "names", {}) or {}
    for j, cls in enumerate(res.boxes.cls.tolist()):
        if names.get(int(cls)) != "balloon":
            continue
        mk = res.masks.data[j].cpu().numpy()
        mk = (cv2.resize(mk, (w, h)) > 0.5).astype(np.uint8) * 255
        if np.count_nonzero(mk):
            out.append(mk)
    return out


def _page_print(p, i: int) -> str:
    """What was checked: the balloon-claiming geometry, and which weights."""
    subs = p.settings.get("custom_kinds") or []
    bits = []
    for r in p.pages[i].active:
        if _kinds.family_of(str(r.get("kind") or ""), subs) != "bubble":
            continue
        bits.append((int(r.get("id") or 0), str(r.get("kind") or ""),
                     tuple(tuple(int(a) for a in pt)
                           for pt in (r.get("polygon") or ())),
                     tuple(tuple(int(a) for a in pt)
                           for pt in (r.get("fit_poly") or ()))))
    fp = weights_path(p)
    try:
        stamp = os.path.getmtime(fp) if fp else 0
    except OSError:
        stamp = 0
    return hashlib.sha1(repr((sorted(bits), fp, stamp))
                        .encode("utf-8")).hexdigest()[:12]


def wants(p, i: int) -> bool:
    """Is there anything for the check to do on this page, this run?"""
    if not available(p) or not p.pages[i].detected:
        return False
    return _done.get((p.output_dir, i)) != _page_print(p, i)


def _strip(flag) -> str:
    """This module's own past opinions, removed; everyone else's kept."""
    parts = [s.strip() for s in str(flag or "").split(";")]
    keep = [s for s in parts
            if s and OFF_BALLOON not in s and NOT_A_BALLOON not in s
            and FITTED not in s]
    return "; ".join(keep)


def _fit_poly(balloons, rec, others):
    """The one balloon that holds THIS box alone, as a polygon - or None.

    Three refusals, each a page that must not be made:

    * no balloon holds `FIT_HOLDS` of the box's own rectangle - the writing
      is not in any balloon, so there is nothing sound to fit to;
    * the winning balloon also holds a neighbour's box (`SHARED_HOLDS`) - a
      double bubble is one connected shape and the model reads it as one
      balloon, and handing that merged shape to either box's fitter puts one
      block's words over the other's. The app's own share-cutting owns
      shared balloons; this stands aside for it;
    * the contour degenerates (fewer than three corners after simplifying).

    The winning contour is simplified by a couple of pixels; the model's
    rims are wavy by about that much and the fitter's own gutter absorbs
    the rest.
    """
    x, y, w, h = (int(v) for v in (rec.get("bbox") or (0, 0, 0, 0)))
    if w < 2 or h < 2 or not balloons:
        return None
    shape = balloons[0].shape

    def held(bb, mk):
        bx, by, bw, bh = (int(v) for v in bb)
        if bw < 2 or bh < 2:
            return 0.0
        box = np.zeros(shape, np.uint8)
        box[max(0, by):by + bh, max(0, bx):bx + bw] = 255
        n = int(np.count_nonzero(box))
        return (int(np.count_nonzero(cv2.bitwise_and(box, mk))) / n
                if n else 0.0)

    best, best_share = None, 0.0
    for mk in balloons:
        s = held((x, y, w, h), mk)
        if s > best_share:
            best, best_share = mk, s
    if best is None or best_share < FIT_HOLDS:
        return None
    for ob in others:
        if held(ob, best) >= SHARED_HOLDS:
            return None                    # somebody else's box is in here too
    cs, _ = cv2.findContours(best, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = cv2.approxPolyDP(max(cs, key=cv2.contourArea), 2.0, True)
    if len(c) < 3:
        return None
    return [[int(a), int(b)] for a, b in c.reshape(-1, 2)]


def check_page(p, i: int, img: "np.ndarray | None" = None) -> int:
    """Give every broken balloon outline a better shape for the TYPESETTER.

    Returns how many boxes were flagged or fitted. Never raises past itself,
    never touches a box outside the bubble family or one that is hidden
    (`active` is the roster everything else plays from) - and NEVER touches
    `polygon`. lee: *"it should only help the typesetter on bubble text"* -
    the cleaner's masks come from `polygon` and every past change to them
    moved something else, so the better shape goes in `fit_poly`, which only
    `typeset.share_masks` reads. The plate stamp keys on (id, bbox, family)
    and the cleaner never reads this field, so nothing already cleaned is
    retired by it.

    Three outcomes per box, decided by SPILL - the share of the outline
    outside every balloon the model sees:

    * under `SPILL_FLAG`: sound. Any old opinion of ours comes down, and a
      stale `fit_poly` comes off - the person fixed the outline, and the
      outline they fixed is the one that should rule.
    * past it, and one balloon holds this box alone: `fit_poly` is written,
      the stored layout is dropped (it was fitted in the wrong shape), and
      the flag says what happened rather than that something is wrong.
    * past it with no balloon to fit to, or a balloon shared with another
      box (whose cut belongs to `share_masks`): the flag alone.
    """
    if not available(p):
        return 0
    mark = _page_print(p, i)
    if _done.get((p.output_dir, i)) == mark:
        return 0
    try:
        if img is None:
            img = p.image(i)
        balloons = _balloons(img, weights_path(p))
        h, w = img.shape[:2]
        union = np.zeros((h, w), np.uint8)
        for mk in balloons:
            union[mk > 0] = 255
        subs = p.settings.get("custom_kinds") or []

        def fam(r):
            return _kinds.family_of(str(r.get("kind") or ""), subs)

        bubbly = [r for r in p.pages[i].active if fam(r) == "bubble"]
        flagged = 0
        for r in bubbly:
            was = _strip(r.get("flagged"))
            note = ""
            poly = r.get("polygon")
            spill = 0.0
            if poly and len(poly) >= 3:
                ours = np.zeros((h, w), np.uint8)
                cv2.fillPoly(ours, [np.array(poly, np.int32)
                                    .reshape(-1, 1, 2)], 255)
                n = int(np.count_nonzero(ours))
                out = int(np.count_nonzero(
                    cv2.bitwise_and(ours, cv2.bitwise_not(union))))
                spill = out / n if n else 0.0
            if spill >= SPILL_FLAG:
                others = [o.get("bbox") for o in bubbly
                          if o is not r and o.get("bbox")]
                fixed = _fit_poly(balloons, r, others)
                if fixed is not None:
                    if r.get("fit_poly") != fixed:
                        r["fit_poly"] = fixed
                        r.pop("layout", None)  # fitted in the wrong shape
                    note = "%s (outline %d%% outside)" % (
                        FITTED, round(spill * 100))
                elif spill >= NO_BALLOON:
                    note = NOT_A_BALLOON
                else:
                    note = "%s (%d%% outside)" % (OFF_BALLOON,
                                                  round(spill * 100))
            elif r.get("fit_poly"):
                # The outline is sound again - the person fixed it, or a
                # re-detect replaced it - so the outline rules and the
                # borrowed shape comes off, with the fit made inside it.
                r["fit_poly"] = None
                r.pop("layout", None)
            if note:
                flagged += 1
                r["flagged"] = ("%s; %s" % (was, note)) if was else note
            else:
                r["flagged"] = was or None
        # Recomputed, not `mark`: a fit moved geometry this print covers, and
        # remembering the one from BEFORE would send the next sweep back in.
        _done[(p.output_dir, i)] = _page_print(p, i)
        return flagged
    except Exception:
        # An advisory that cannot run must cost nothing - and must not
        # pretend it ran: no mark, so the next sweep tries again.
        import traceback
        traceback.print_exc()
        return 0
