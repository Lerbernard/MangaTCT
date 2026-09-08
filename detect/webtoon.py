# -*- coding: utf-8 -*-
"""Balloon finders trained on WEBTOONS, for manhwa and manhua.

Every other route in this package was measured on Japanese manga and is
guarded to it (`Project.TWO_MEDIA`), for a reason written out there: a
manhwa is one tall column of colour with no panels across it, and none of
the numbers swept on manga fragments transfer to it. That left a webtoon
with exactly one finder - comic-text-detector - and no choice at all.

lee: *"we to find and use detector that are good for manwa and mnahua not
the same ones at teh manga"*.

So these two are the opposite: YOLOv8 detectors trained on webtoon pages,
one on Korean and one on Chinese, published with ImageTrans
(`xulihang/balloon-dataset`). Both answer `{0: balloon, 1: other}`.

MEASURED, on lee's own chapter: 22 tiles, every balloon and caption on them
hand-checked - 33 of them - against the boxes each route drew.

    route                 missed  junk  s/page
    comic-text-detector        1     2     2.8
    webtoon KO                 1     0     2.8
    webtoon ZH                 5     1     2.8
    AnimeText YOLO12-L         1     3     4.7

The yolo pass is a fifth of a second; the 2.8 is comic-text-detector's
segmentation underneath, which this route needs anyway and which the plain
route spends the same on. So the webtoon models are FREE against what a
webtoon runs today, and better: nothing is missed but one clipped balloon on
a tile edge, and nothing stray at all.

WHAT EACH ONE GETS WRONG, since the counts are close enough to hide it.
comic-text-detector's one miss is a balloon cut by the tile edge. AnimeText
finds everything and then cuts a four-line caption into four boxes, which is
three separate translations of one sentence. webtoon ZH's five are not
misses of the same kind: it FINDS the balloon and draws the box too small,
losing a line or half a line off the writing inside - the worst failure of
the four, because a short box reads as a found one.

The pair is NOT a language split, and it is worth saying so plainly because
the names invite the opposite reading. The Korean model is not the Korean
one: on this Korean chapter it is the best of the four and the Chinese model
is the worst, and on raw box counts the Chinese model finds MORE. A balloon
is a balloon whichever script is inside it. The second is offered because on
a page where the first misses a balloon it is a free opinion.

PAINTED SOUNDS ARE NOT SOMETHING THESE MODELS CAN FIND, and that is not a
threshold anybody can move: they answer balloon or not-balloon. On ten pages
of lee's own chapter, with the sound effects asked for, they found none of
the six. So the balloons stay theirs and the rest comes from the model that
was already being run underneath them - see `FILL`.

TWO WAYS TO DO THAT, both built and measured, because lee asked for both:
*"both both and evalue them against eacother"*. Same ten pages, 16 places
with writing on them and 6 painted sounds, hand-checked:

    what is added            writing 16   sfx 6 (whole)   stray   s/page
    nothing (balloons only)        14           0            0      2.8
    A: only the sfx                14           1  (3 hit)   0      4.7
    B: everything not covered      15           2  (4 hit)   1      4.9
    comic-text-detector alone      15           4  (5 hit)   1     19.9

B WON, and the reason is worth writing down because it is not the half a
second. A filters comic-text-detector's boxes by `kind == sfx` - and the
kind is the least trustworthy thing that model produces. Of the five sound
effects it found on these pages it called three `sfx` and the rest `bubble`
or `freefloat`; the big one on 006 came back `bubble`, so A threw it away
and B kept it. **Do not filter on the field that is wrong.** B also picks up
writing with no balloon round it, which is how it gets the white-on-dark
narration panel on 007 that every balloon model misses by construction.

What B costs is one stray box on ten pages, inherited from the model it is
borrowing from, and it is a box somebody deletes in one click.

The remaining gap to comic-text-detector - two whole sound effects - is
CRAFT, which is 93% of that route's run. Four times the time for two boxes
is not the trade this route exists to make; `craft_x`/`craft_y` are one line
away for a chapter where it is.

WHAT THEY FIND IS A BALLOON, not a block of writing, and the rest of this
app works in blocks: `bbox` is the ink, `polygon` is the shape round it. So
comic-text-detector's segmentation supplies the ink - the same "if needed"
mask `dbcoo.detect_animetext` uses it for - and each balloon is tightened
onto the writing actually inside it. A balloon with no ink in it is not a
box; it is a bubble somebody drew empty, and there is nothing to translate.
"""
from __future__ import annotations

import json
import os
import time

import cv2
import numpy as np

from ..models import Page, TextRegion

#: WHERE THE LAST PAGE'S TIME WENT, for the slow-page line to carry.
#:
#: lee: *"koren detector is taking 13 second per page"*. Thirteen is under the
#: twenty this app logs a page at, so there was nothing on record at all - and
#: "thirteen seconds" cannot be acted on, while "mask 11.4s, boxes 1.2s" names
#: the model to go and look at. The two halves of this route are a fixed cost
#: that does not care how tall the page is (comic-text-detector's segmentation,
#: one pass at 1024) and a cost that scales with height (one small pass per
#: tile), and knowing which is which is the whole diagnosis.
#:
#: A module global rather than a return value, because `detect` hands back
#: regions and threading a timing through it would put this in six signatures.
#: Written by every call, read by `project._say_page_cost` right after.
LAST_SPLIT = ""

#: Both published models take a 640 square and overlap their tiles by a
#: fifth. Read from the model's own `model.json` when one is beside it, so a
#: newer export cannot silently be run at the wrong size.
SIDE = 640
OVERLAP = 20.0
#: Below this the box is a guess. Swept on lee's chapter: 0.30 keeps the
#: quiet balloons on a dark panel and admits nothing from the artwork.
CONF = 0.30
NMS = 0.45
#: A balloon has to hold this share of ink to be a box worth making, as a
#: fraction of its own area. A drawn-but-empty bubble sits under it.
MIN_INK = 0.002

_SESS: dict = {}


def why_not(path: str) -> str:
    """Why this finder cannot run, in a sentence somebody can act on."""
    if not path:
        return "no webtoon detector weights are set"
    if not os.path.isfile(path):
        return "webtoon detector weights are not at %s" % path
    try:
        import onnxruntime  # noqa: F401,F811
    except Exception:
        return ("onnxruntime is not installed -- run "
                "`pip install onnxruntime`")
    return ""


def _sess(path: str):
    """The loaded model, and the size and overlap it was exported for."""
    if path not in _SESS:
        import onnxruntime as ort
        s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        side, ov = SIDE, OVERLAP
        # ImageTrans ships a `model.json` beside the file. Believed when it
        # is there, because a model exported at another size run at 640 is
        # not wrong in a way anything downstream can see - it just finds
        # less, quietly.
        cfg = os.path.join(os.path.dirname(path), "model.json")
        try:
            if os.path.isfile(cfg):
                d = json.load(open(cfg))
                side = int(d.get("height") or side)
                ov = float(str(d.get("height_overlap", ov)) or ov)
        except (OSError, ValueError):
            pass
        _SESS[path] = (s, side, ov)
    return _SESS[path]


def pieces(img: np.ndarray, path: str, conf: float = CONF) -> list:
    """Every balloon on the page, as [x0, y0, x1, y1].

    A webtoon page is many times taller than the model's square input, so it
    is cut into tiles down its length with the model's own overlap and each
    box is put back where it came from. The overlap is what stops a balloon
    that straddles a tile edge being found twice at half height; the
    non-maximum pass after it is what settles the two halves.
    """
    if img is None or not len(img):
        return []
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    s, side, ov = _sess(path)
    ih, iw = img.shape[:2]
    step = max(1, int(side * (1 - ov / 100.0)))
    tops = list(range(0, max(1, ih - side + step), step)) or [0]
    name = s.get_inputs()[0].name
    boxes, scores = [], []
    for top in tops:
        tile = img[top:top + side, 0:iw]
        if tile.shape[0] < 8:
            continue
        # letterboxed into the square, so nothing is stretched: a stretched
        # balloon is a shape the model was not trained on.
        r = min(side / tile.shape[1], side / tile.shape[0])
        rw, rh = max(1, int(tile.shape[1] * r)), max(1, int(tile.shape[0] * r))
        pad = np.zeros((side, side, 3), np.uint8)
        pad[:rh, :rw] = cv2.resize(tile, (rw, rh))
        blob = (pad[:, :, ::-1].transpose(2, 0, 1)[None]
                .astype(np.float32) / 255.0)
        pred = np.squeeze(s.run(None, {name: blob})[0]).T
        if pred.ndim != 2 or pred.shape[1] < 5:
            continue
        best = pred[:, 4:].max(1)
        for (cx, cy, w, h), sc in zip(pred[best > conf, :4], best[best > conf]):
            boxes.append([(cx - w / 2) / r, (cy - h / 2) / r + top,
                          (cx + w / 2) / r, (cy + h / 2) / r + top])
            scores.append(float(sc))
    if not boxes:
        return []
    rects = [[int(b[0]), int(b[1]), int(b[2] - b[0]), int(b[3] - b[1])]
             for b in boxes]
    idx = cv2.dnn.NMSBoxes(rects, scores, conf, NMS)
    keep = [int(i) for i in np.array(idx).reshape(-1)] if len(idx) else []
    out = []
    for i in keep:
        b = boxes[i]
        out.append([max(0, int(b[0])), max(0, int(b[1])),
                    min(iw, int(b[2])), min(ih, int(b[3]))])
    return out


#: What comic-text-detector is allowed to add to a webtoon page.
#:
#: lee, having watched the two webtoon models find none of the six painted
#: sounds on ten pages of his own chapter: *"i wnat you to test teh 4 detector
#: ... adn have teh finded evrything including the big sfx"*.
#:
#: They cannot. They answer `{0: balloon, 1: other}` and there is no threshold
#: that turns that into a sound effect. So the balloons stay theirs and the
#: rest comes from the model that was already being run underneath them.
#:
#: "sfx"  - only the painted sounds.
#: "all"  - everything comic-text-detector found that the webtoon model did
#:          not already cover, which is the same thing plus writing with no
#:          balloon round it.
#: ""     - the balloons alone, which is what this route was.
FILL = "all"

#: How big a page CRAFT is allowed to look at, on THIS route, or 0 to leave it
#: out. It is the long side in pixels: `craft.CANVAS` is 2560, set for reading
#: small printed writing, and a page longer than that is scaled down to it
#: anyway.
#:
#: CRAFT is the best sound-effect finder in this app - it is the reason
#: comic-text-detector's card finds five of six on lee's chapter where the
#: block head alone finds one - and the reason it was not on this route is
#: cost: 93% of a comic-text-detector run. That cost is pixels. A painted
#: sound is the LARGEST thing on the page, so it survives being looked at
#: smaller, and dialogue is not CRAFT's job here anyway.
#:
#: Measured on lee's pages, CRAFT alone, seconds a page and pieces found:
#:
#:     canvas   003      004      005      006      007
#:       2560   4/9.0s   2/7.8s   2/5.9s   3/9.0s   24/5.9s
#:       1280   4/2.2s   3/2.0s   1/2.4s   2/1.7s   22/1.5s
#:        768   4/0.8s   1/0.8s   1/0.8s   1/0.6s   22/0.5s
#:
#: A quarter of the pixels is about a quarter of the seconds and the pieces
#: hold; a sixteenth starts losing them.
#:
#: 1600 IS BETTER THAN 2560, WHICH IS THE POINT. Run through the whole route
#: on the four pages of lee's ten that carry the six painted sounds:
#:
#:     canvas   003   004   005   006   sounds boxed   s/page
#:          0     0     1     1     1         3          4.5
#:       1280     1     1     1     1         4          7.2
#:       1600     1     1     1     2         5          8.9
#:       2560     0     2     1     1         4         14.1
#:
#: The full canvas is not just the expensive one, it is a worse one - it loses
#: the big sound on 003 that 1600 finds. CRAFT is scale-sensitive and these
#: sounds happen to be the size it likes at 1600.
#:
#: WHAT "BOXED" MEANS HERE, because five of six flatters it: the box lands on
#: the sound and is often only part of it - the top half of a two-character
#: sound on 003, the lower of the pair on 004. CRAFT answers character groups
#: and a sound drawn a third of a page high is not one. It is a great deal
#: better than nothing, which is what the balloon models have, and it is not
#: a solved problem.
CRAFT_CANVAS = 1600

#: ...AND WHAT CRAFT IS TOLD A LETTER IS, on this route.
#:
#: Task #144. The "often only part of it" above was measured: on the 22
#: painted sounds of lee's chapter, CRAFT at its manga settings touched 82%
#: of them and covered nine tenths of only 41%. Cropped and looked at, the
#: misses were two settings and not the model:
#:
#:   `low_text`   CRAFT's floor for "this pixel is in a letter". 0.50 was set
#:                on printed manga type, where a glyph is a solid dark
#:                stroke. A painted webtoon sound is a gradient with a
#:                highlight down it and an outline round it, and at 0.50
#:                the region map falls apart into pieces on the way down
#:                the stroke - `타앗!` on page 049 came back as four crumbs.
#:   `craft_cap`  the share of the page a CRAFT group may cover before it is
#:                called a panel and dropped. 0.05 was right on a manga page
#:                of small panels; a webtoon strip is one panel wide and a
#:                shout drawn across it IS a twentieth of the page. The
#:                biggest sound on lee's 003 was being found and then thrown
#:                away for its size.
#:
#: Both swept together on lee's 22 sounds and the 44 on a second chapter
#: from another studio (227), the seg mask being blank on all of them so
#: CRAFT is the whole answer. Touched / nine-tenths covered / mean cover:
#:
#:     low   cap    lee (22)          227 (44)        stray sfx boxes
#:     0.50  0.05   82%  41%  61%     61%  23%  46%   lee 2, 227 8
#:     0.40  0.20   86%  55%  71%     64%  34%  48%
#:     0.30  0.45   91%  64%  79%     66%  43%  51%   lee 3, 227 10
#:     0.20  0.45   91%  59%  74%     -               fatter, not better
#:
#: The strays it adds are small (the biggest on lee's pages is 4.8% of a
#: page and it is on the drawing under a real sound); what it stops adding
#: is a rectangle round a cluster of balloons, because a box that grows onto
#: a balloon is now cut back off it - see `_clear_of_the_balloons`. What it
#: still misses is written in the task: a streaky glyph CRAFT sees a fifth of
#: (049), and the thin hand-lettered strokes of 227 that never fire at all.
#:
#: Route settings, not manhwa tuning, because they were measured at
#: `CRAFT_CANVAS` on this route and the plain comic-text-detector route runs
#: CRAFT at its own canvas, where the cap really is a panel.
CRAFT_LOW = 0.30
CRAFT_CAP = 0.45

#: Two boxes sharing this much of the SMALLER one are about the same writing.
#: Of the smaller, so that it catches a big box swallowing a balloon as well
#: as a small box sitting inside one - see `_covers`, where getting that
#: backwards put a box round two balloons that already had their own.
COVERED = 0.5


def detect_webtoon(page: Page, ctd_weights: str, onnx_path: str,
                   classify: bool = True, want_sfx: bool = True,
                   min_ink: float = MIN_INK, fill: str = None,
                   **tuning) -> list:
    """Balloons from the webtoon model, and what it has no class for from
    comic-text-detector.

    `ctd_weights` is not optional and not a second opinion: `inpaint` skips
    a region whose `text_mask` is None, so the cleaner needs the
    segmentation whatever found the box. It is the same arrangement
    `detect_animetext` makes with it, for the same reason - and now it is
    also where the sound effects come from. See `FILL`.

    CRAFT IS OFF in that call, deliberately. It is 93% of a
    comic-text-detector run - 9 to 108 seconds a page against 3.6 without it,
    measured on lee's own chapter - and what it buys here is two more painted
    sounds out of six. That is a different trade from the one this route
    exists to make, and it is one line away for anybody who wants it.

    `want_sfx` is passed on rather than ignored now. The webtoon models still
    have nothing to say about a painted sound; the model underneath them does.
    """
    from . import comictext as CT

    global LAST_SPLIT
    LAST_SPLIT = ""
    fill = FILL if fill is None else fill
    img = page.image
    if img is not None and img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    t0 = time.time()
    extra = []
    if fill:
        # ONE forward pass for both jobs. `detect_comictext` computes the
        # segmentation it needs and leaves it on the page as `seg_mask`, so
        # asking it for boxes costs the mask this route was buying anyway
        # plus its own grouping - about a second and a half.
        # CRAFT is left OUT unless `CRAFT_CANVAS` says otherwise - see there.
        # Dropped from the tuning rather than passed as None beside it,
        # because `**tuning` and an explicit `craft_x=` are the same keyword
        # twice and that is a TypeError, not an override.
        quiet = {k: v for k, v in tuning.items()
                 if k not in ("craft_x", "craft_y")}
        # ...and only when the person actually asked for sound effects. It
        # is the tick in Find text, it is already a deliberate ask, and it is
        # the only thing on the page CRAFT is here for: dialogue is found
        # without it. A chapter run with the box unticked pays nothing.
        # The canvas is CRAFT's module global, and it is a MANGA number
        # there (2560, measured on a manga chapter - see `craft.CANVAS`).
        # 1600 is the webtoon answer, so it is set for this call and put
        # back after: left at 1600 it leaked into every later manga page
        # in the same process, and into the test that holds the manga
        # figure to its measurement.
        was = None
        if CRAFT_CANVAS and want_sfx:
            from . import craft as _craft
            was = (_craft, _craft.CANVAS)
            _craft.CANVAS = CRAFT_CANVAS
            quiet["craft_x"] = tuning.get("craft_x")
            quiet["craft_y"] = tuning.get("craft_y")
            # ...and the two numbers measured for painted sounds, see
            # `CRAFT_LOW`. None leaves comic-text-detector's own.
            if CRAFT_LOW is not None:
                quiet["craft_low"] = CRAFT_LOW
            if CRAFT_CAP is not None:
                quiet["craft_cap"] = CRAFT_CAP
        try:
            extra = CT.detect_comictext(page, ctd_weights, classify=classify,
                                        want_sfx=want_sfx, **quiet)
        finally:
            if was is not None:
                was[0].CANVAS = was[1]
        tmask = getattr(page, "seg_mask", None)
    else:
        tmask = None
    if tmask is None:
        tmask = CT.page_text_mask(
            img, ctd_weights, tuning.get("mask_thresh") or CT.SEG_KEEP)
    t_mask = time.time()
    boxes = pieces(img, onnx_path)
    t_boxes = time.time()
    out = []
    for (x0, y0, x1, y1) in boxes:
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        sub = tmask[y0:y1, x0:x1] if tmask is not None else None
        if sub is None or not sub.size:
            continue
        ys, xs = np.nonzero(sub)
        if not len(ys) or len(ys) < min_ink * w * h:
            continue                      # a balloon drawn with nothing in it
        # THE BOX IS THE MODEL'S, NOT THE MASK'S.
        #
        # It was the mask's first - the ink bounds inside the balloon - on
        # the ordinary rule that `bbox` is the writing and the balloon is
        # the shape round it. Drawn on lee's page 47 that was visibly wrong:
        # the tightened boxes clipped the top line and the right-hand edge
        # off every caption, while the model's own rectangle wrapped all
        # three lines. comic-text-detector's segmentation is the one thing
        # in this route that was NOT trained on webtoons, and it is patchy
        # on colour art - which is the whole reason these models are here.
        #
        # So the mask keeps the job it is needed for, which is telling the
        # cleaner what ink to erase, and loses the one it was bad at. The
        # ink still has to EXIST - a balloon with none in it is a bubble
        # somebody drew empty - it just does not get to move the corners.
        bx0, by0, bx1, by1 = x0, y0, x1, y1
        # PAGE-SIZED, not a crop. `TextRegion.place_mask` reads
        # `text_mask.shape` as the page's own shape, and `balloon` compares
        # it against page-sized label images - a cropped mask does not fail
        # a check, it raises a broadcast error four calls away from here.
        ink = np.zeros(tmask.shape[:2], np.uint8)
        ink[y0:y1, x0:x1] = (sub > 0).astype(np.uint8) * 255
        r = TextRegion(id=0, bbox=(bx0, by0, bx1 - bx0, by1 - by0),
                       kind="bubble", text_mask=ink)
        r.bubble_bbox = (x0, y0, w, h)
        r.polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        r.confidence = 0.9
        out.append(r)
    got = _one_box_per_writing(_reach_the_last_line(out, tmask))
    added = _fill_in(got, extra, fill)
    LAST_SPLIT = ("mask %.1fs  boxes %.1fs  ink %.1fs  %d tiles  +%d %s"
                  % (t_mask - t0, t_boxes - t_mask, time.time() - t_boxes,
                     _tiles(img), added, fill or "none"))
    return got


def _fill_in(got: list, extra: list, fill: str) -> int:
    """Put comic-text-detector's boxes in beside the balloons, and say how
    many went in.

    A BALLOON THE WEBTOON MODEL FOUND IS THE WEBTOON MODEL'S. It is better at
    them - that is the whole reason this route exists - so anything from the
    other model that lands on one is cut back off it, or dropped, never
    merged: two boxes on one balloon is two translations of one line, and
    taking the union of a tight box and a loose one gives the loose one. See
    `_clear_of_the_balloons` for the cut.

    Appended and then re-sorted into reading order, because a sound effect
    halfway down the page belongs where it is on the page and not after every
    balloon on it.
    """
    if not extra or not fill:
        return 0
    from .. import kinds as _kinds
    keep = []
    for r in extra:
        if fill == "sfx" and _kinds.family_of(r.kind or "") != "sfx":
            continue
        box = _clear_of_the_balloons(r.bbox, [g.bbox for g in got])
        if box is None:
            continue
        if tuple(box) != tuple(int(v) for v in r.bbox):
            _reshape(r, box)
        keep.append(r)
    got.extend(keep)
    got.sort(key=lambda r: (int(r.bbox[1]), int(r.bbox[0])))
    for n, r in enumerate(got):
        r.id = n
    return len(keep)


#: A sound-effect box that runs over a balloon keeps the part of itself that
#: lies clear of the balloon - if that part is at least this share of what
#: the box was. Under it, the box was mostly the balloon, and goes.
CARVE_KEEP = 0.4


def _clear_of_the_balloons(box, balloons: list):
    """Where an incoming box may stand once the balloons have had their say:
    the box itself, a piece of it, or nowhere (None).

    Dropping any box that covers a balloon was the whole rule, and it is
    right about the two cases it was written for - a small box INSIDE a
    balloon, and a block drawn round a cluster of them. But the sound-effect
    pass grows its boxes to the strokes they hold (`_grow_to_the_stroke`),
    and on a webtoon the strokes run into the balloon next door: 227's page
    13 has `우아악!` painted the height of the panel, and the box round it
    took in the balloon above. Covers a balloon, dropped - and the biggest
    sound effect on the page came off the run with nothing on it.

    So a box that covers a balloon is CUT round it first. Of the four strips
    left when the balloon's rectangle is taken out - above, below, left,
    right - the biggest stays if it is still `CARVE_KEEP` of the original;
    the two old cases end up under that line (a box inside a balloon has no
    strip worth the name) and are dropped exactly as before. The cut is
    repeated for every balloon the box covers, always measured against the
    box as it came in, so a block round three balloons cannot survive by
    shedding them one at a time.
    """
    x, y, w, h = [int(v) for v in box]
    area = max(1, w * h)
    for b in balloons:
        if not _covers((x, y, w, h), b):
            continue
        bx, by, bw, bh = [int(v) for v in b]
        strips = [(x, y, w, by - y),                        # above
                  (x, by + bh, w, y + h - (by + bh)),       # below
                  (x, y, bx - x, h),                        # left
                  (bx + bw, y, x + w - (bx + bw), h)]       # right
        strips = [s for s in strips if s[2] > 0 and s[3] > 0]
        if not strips:
            return None
        x, y, w, h = max(strips, key=lambda s: s[2] * s[3])
        if w * h < CARVE_KEEP * area:
            return None
    return (x, y, w, h)


def _reshape(r, box) -> None:
    """Move a region onto a cut-down box, and everything on it that says
    where it is: the ink mask loses what fell outside, and the outline, if
    it had one, becomes the new rectangle."""
    x, y, w, h = box
    r.bbox = (x, y, w, h)
    r.bubble_bbox = (x, y, w, h)
    m = getattr(r, "text_mask", None)
    if m is not None:
        cut = np.zeros_like(m)
        cut[y:y + h, x:x + w] = m[y:y + h, x:x + w]
        r.text_mask = cut
    if getattr(r, "polygon", None):
        r.polygon = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _covers(a, b) -> bool:
    """Are these two boxes about the same writing, whichever way round?

    THE SHARE IS OF THE SMALLER ONE, and that is the whole of this. It was of
    the INCOMING box's own area, which settles a small box landing inside a
    big balloon and gets the other direction exactly backwards: a
    comic-text-detector block drawn round a CLUSTER of balloons shares only a
    little of its own large area with any one of them, so it passed the test
    and was added - and lee got a box round two balloons that already had
    boxes. *"the big box should not hapen"*.

    Asking about the smaller box answers both at once. A big box that swallows
    a balloon shares most of THAT balloon; a small box inside a balloon shares
    most of ITSELF. Either way the two are about the same writing and the
    balloon model's answer is the one that stays.
    """
    ax, ay, aw, ah = [int(v) for v in a]
    bx, by, bw, bh = [int(v) for v in b]
    share = (max(0, min(ax + aw, bx + bw) - max(ax, bx))
             * max(0, min(ay + ah, by + bh) - max(ay, by)))
    return share >= COVERED * max(1, min(aw * ah, bw * bh))


def _tiles(img) -> int:
    """How many passes the box model made. It is the page's height over the
    step, so it is the half of this route that grows with the page - said out
    loud beside the timing because "0.2s a tile" and "eleven tiles" are two
    different things to do something about."""
    if img is None or not len(img):
        return 0
    step = max(1, int(SIDE * (1 - OVERLAP / 100.0)))
    return len(list(range(0, max(1, img.shape[0] - SIDE + step), step))) or 1


#: A line of writing this near the box, and under it, belongs to it - as a
#: fraction of that line's own height, so it scales with the type.
NEAR = 0.8
#: ...and only if the box is actually above or below it: this much of the
#: line's width has to sit within the box's columns.
UNDER = 0.5
#: A line the box cuts through is the box's if this much of the line's own
#: height is inside it. lee's two: 61% and 75% in; the screenshot he sent of
#: 022 shows the rule cutting through the lower third of `나는`.
STRADDLE = 0.2


def _reach_the_last_line(regions: list, tmask) -> list:
    """Grow each box over writing left just outside it.

    The models find a BALLOON, and on a caption plate that steps in behind a
    neighbour they draw the rectangle round the part of the plate they can
    see. On lee's page 47 that cost the third line of a three-line caption:
    the box stopped 9 pixels above it, and a translation of the first two
    lines is a wrong translation, not a short one.

    So the segmentation mask gets to push the corners OUT, never in - the
    reverse of the rule it used to be given, and for the reason written at
    the call site: the mask is patchy on colour art, and a mask that is
    missing ink can only fail to grow a box, while a mask that is missing
    ink WAS shrinking boxes onto the ink it did see.

    The danger is obvious - two captions stacked touching, and the second's
    first line is nine pixels from the first's last one. What keeps them
    apart is that a line already inside somebody else's box is not up for
    adoption. Only writing no model box claimed can be absorbed, so a
    neighbour that was found is a neighbour that is safe.
    """
    if tmask is None or not len(regions):
        return regions
    n, lab, stats, _c = cv2.connectedComponentsWithStats(
        (tmask > 0).astype(np.uint8), 8)
    boxes = [[int(v) for v in r.bbox] for r in regions]
    orphans = []
    straddlers = []
    for i in range(1, n):
        x, y, w, h, a = (int(stats[i, cv2.CC_STAT_LEFT]),
                         int(stats[i, cv2.CC_STAT_TOP]),
                         int(stats[i, cv2.CC_STAT_WIDTH]),
                         int(stats[i, cv2.CC_STAT_HEIGHT]),
                         int(stats[i, cv2.CC_STAT_AREA]))
        if a < 12:
            continue                       # speckle, not a stroke
        on = [k for k, (bx, by, bw, bh) in enumerate(boxes)
              if min(bx + bw, x + w) > max(bx, x)
              and min(by + bh, y + h) > max(by, y)]
        if len(on) == 1:
            bx, by, bw, bh = boxes[on[0]]
            if not (bx <= x and by <= y and x + w <= bx + bw
                    and y + h <= by + bh):
                straddlers.append((on[0], (x, y, w, h)))
            continue                       # this box is reading it
        if on:
            continue                       # two boxes are; not ours to move
        orphans.append((x, y, w, h))
    # THE LINE THE BOX CUTS THROUGH.
    #
    # lee, two screenshots of caption plates on his chapter, both with the
    # first line half in the box and half out: `나는……` on 022 and `지금까지`
    # on 007. The artist set the first line across the plate's top rule, the
    # model boxed the plate, and the rule above called the line "somebody's
    # already reading it" because the box touched it - so it was neither
    # adopted nor covered, and the reader was handed two lines of three.
    #
    # A line ONE box touches and does not hold is that box's line. It has to
    # be a line - no taller than the box, no wider than it by more than a
    # tenth, at least a fifth of its height actually inside - because on
    # colour art the mask marks the odd piece of drawing, and a piece of
    # drawing crossing the box edge must not drag the box out over it. And
    # it has to be one box's: a mark two boxes touch is between two
    # captions, and moving either box onto it is the merge this function
    # promises not to do.
    for k, (x, y, w, h) in straddlers:
        bx, by, bw, bh = boxes[k]
        if h > bh or w > bw * 1.1:
            continue                       # a shape, not a line
        if min(bx + bw, x + w) - max(bx, x) < UNDER * w:
            continue                       # not in this box's columns
        if min(by + bh, y + h) - max(by, y) < STRADDLE * h:
            continue                       # grazing it, not set across it
        nx, ny = min(bx, x), min(by, y)
        boxes[k] = [nx, ny, max(bx + bw, x + w) - nx, max(by + bh, y + h) - ny]
    changed = True
    while changed:
        changed = False
        for k, (bx, by, bw, bh) in enumerate(boxes):
            for o in list(orphans):
                x, y, w, h = o
                over = min(bx + bw, x + w) - max(bx, x)
                if over < UNDER * w:
                    continue               # not in this box's columns
                gap = max(by - (y + h), y - (by + bh))
                if gap > NEAR * h:
                    continue               # a different paragraph
                nx, ny = min(bx, x), min(by, y)
                boxes[k] = [nx, ny, max(bx + bw, x + w) - nx,
                            max(by + bh, y + h) - ny]
                bx, by, bw, bh = boxes[k]
                orphans.remove(o)
                changed = True
    for r, (x, y, w, h) in zip(regions, boxes):
        if tuple(r.bbox) == (x, y, w, h):
            continue
        r.bbox = (x, y, w, h)
        r.bubble_bbox = (x, y, w, h)
        r.polygon = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        # the ink of the line we just took in, or the cleaner erases the
        # first two lines of the caption and leaves the third under the
        # translation of all three.
        if r.text_mask is not None:
            r.text_mask[y:y + h, x:x + w] = (
                (tmask[y:y + h, x:x + w] > 0).astype(np.uint8) * 255)
    return regions


#: Two boxes sharing this much of the smaller one are one piece of writing.
#: Measured on lee's page 47: a three-line caption came back as two boxes
#: offset diagonally, sharing 59% of the smaller. 0.40 joins those and
#: leaves two balloons that merely touch alone.
SAME_WRITING = 0.40


def _one_box_per_writing(regions: list, share: float = SAME_WRITING) -> list:
    """One box per piece of writing, however many times it was found.

    The page is read in overlapping tiles. The overlap is what stops a
    balloon on a tile edge coming back as two halves - but it also means a
    balloon found WHOLE in two tiles can survive the non-maximum pass when
    the two rectangles differ enough, and a model willing to call both a
    caption and most of a caption a balloon does the same thing inside one
    tile.

    Both shapes showed up on lee's chapter: page 15 returned the small
    trailing-dots balloon twice, byte for byte; page 47 returned a
    three-line caption as two rectangles offset diagonally, neither inside
    the other, each covering part of it. Drawn small they read as one box
    clipping the writing, which is exactly what they were mistaken for at
    first.

    They are JOINED rather than one being dropped, and that is the whole
    point: on page 47 neither box holds all three lines and their union
    does. Dropping either would have cut a line off the translation.
    Repeated to a fixed point, because joining two can bring a third within
    reach of the result.
    """
    boxes = [[int(v) for v in r.bbox] + [r] for r in regions]
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ax, ay, aw, ah, ar = boxes[i]
                bx, by, bw, bh, br = boxes[j]
                ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                oy = max(0, min(ay + ah, by + bh) - max(ay, by))
                if ox * oy < share * max(1, min(aw * ah, bw * bh)):
                    continue
                nx, ny = min(ax, bx), min(ay, by)
                nw = max(ax + aw, bx + bw) - nx
                nh = max(ay + ah, by + bh) - ny
                # the ink of both, or the cleaner would erase half a caption
                if ar.text_mask is not None and br.text_mask is not None:
                    ar.text_mask = np.maximum(ar.text_mask, br.text_mask)
                ar.bbox = (nx, ny, nw, nh)
                ar.bubble_bbox = (nx, ny, nw, nh)
                ar.polygon = [[nx, ny], [nx + nw, ny],
                              [nx + nw, ny + nh], [nx, ny + nh]]
                boxes[i] = [nx, ny, nw, nh, ar]
                boxes.pop(j)
                changed = True
                break
            if changed:
                break
    # reading order down the page, which is the order they arrived in
    return [b[4] for b in sorted(boxes, key=lambda b: (b[1], b[0]))]
