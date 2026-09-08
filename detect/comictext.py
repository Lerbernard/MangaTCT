"""Manga/comic text-block detection via dmMaze's comic-text-detector.

This runs the model's ONNX export with OpenCV's DNN module and reads its two
useful outputs directly: the YOLO text-BLOCK boxes and the text segmentation
mask. Text is detected DIRECTLY and already grouped into blocks by the model,
so none of the bubble-detect / dedup / separate / merge heuristics are needed -
each block is a tight, non-overlapping TextRegion.

Deliberately dependency-light: OpenCV + numpy only (no torch, shapely or
pyclipper), so it installs cleanly anywhere the rest of the app already runs.
The DBNet "lines" output is ignored; the block boxes plus the mask are enough
to build regions.

Model: `comictextdetector.pt.onnx` from the manga-image-translator releases
(beta-0.2.1). Point the detector's model-path setting at that file.
"""
from __future__ import annotations

import copy
import os
import sys
import time as _time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from ..models import Page, TextRegion
from .. import kinds as _kinds

INPUT = 1024            # the size the model was exported at
from . import balloon as _BL

PAD = 8                 # breathing room around each block so nothing clips
INK = 128

# How many times taller than wide a page may be before Find text is worth
# warning about. lee: *"somthing i notice is that when the pages are smaller
# teh issies are gone ... if the page exide a cerain lenght can you give a
# warning"*.
#
# He is describing something this file does by construction. `_letterbox` fits
# the page into a 1024 square by its LONG side, so what the model actually sees
# is the page at `1024 / max(h, w)`, and on a strip that is the height. Which
# makes the ASPECT the thing to warn on and not the height: a 690x4140 page and
# a 1400x8400 one both arrive 170 pixels wide, and their writing -- which is
# drawn relative to the page width -- both arrive the same number of pixels
# tall. A page twice as wide may be twice as long for free.
#
# MEASURED, twice, because the obvious measurement was wrong.
#
# First: run all 55 pages of two chapters whole, then in halves, and count what
# the halves find that the whole page did not. That says 12% at aspect 2 rising
# to 75% past 6, which looks like a clean answer and is an artifact. Split by
# kind, the DIALOGUE misses do not move with aspect at all (0.9, 1.5, 0.7, 0.4,
# 1.2 per page up the bands). The whole rise is sound effects, and cropping
# them shows what they are: page 004's fifteen "missed" boxes are fifteen
# copies of the 짭툰.com watermark. Tall pages in this chapter are scenery with
# the site stamp down them. That is not a detector getting worse.
#
# Second, controlled: take 11 pages Find text already reads and pad WHITE SPACE
# under them, to aspect 3, 4, 5, 6, 8 and 10. Nothing about the artwork, the
# writing, or the writing's size in page pixels changes -- only the number the
# letterbox divides by. Then:
#
#     aspect     3     4     5     6     8    10
#     boxes     49    58    57    52    39    39     (53 at the page's own size)
#     relabelled 14%   17%   15%   34%   29%   26%
#
# **Recall is not what goes.** A box that was there is still there at aspect 8.
# What goes is the page's box list and the labels on it: past 6 the page loses
# about a quarter of its boxes and a third of what survives comes back a
# different kind. That is exactly what lee is looking at -- his complaints were
# sound effects called outside text and one balloon boxed as two, not writing
# that vanished -- and it is why the warning says what it says.
TALL_ASPECT = 6.0


def too_tall(w: int, h: int) -> bool:
    """Is this page long enough that Find text will start mislabelling it?"""
    return bool(w) and bool(h) and (max(w, h) / float(min(w, h) or 1)
                                    > TALL_ASPECT)

_nets: dict = {}


# One worker, for the life of the process, to run the second detector beside
# the first. One and not more: a page runs one CRAFT and the pool exists to
# overlap it with the block head, not to run pages in parallel -- Find text
# over a chapter is a loop in `Project.detect_all` and it stays one.
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="craft")

#: Say nothing about a page that took less than this. A run that is behaving
#: should not talk, and a run that is not should say so on every page.
#:
#: Above the FIRST page of a run as well as the rest: CRAFT's weights load on
#: page one and that alone is about 15 seconds, so a lower bar would make
#: every healthy run open with a warning about itself.
SAY_OVER = 20.0


def _say_timing(page, t0, t_net, t_craft, n, craft_on):
    """One line a page, and only when a page was slow.

    The whole point is that it is a SPLIT. "50 seconds" cannot be acted on;
    "net 3.1s, craft 44.8s" names the file to go and look at. The page size
    is in it because this scales with area - 960x1399 is 4.7s here and
    2880x4197 is 21.8s on the same two cores, so a big scan is not a bug.
    """
    done = _time.time()
    if done - t0 < SAY_OVER:
        return
    im = getattr(page, "image", None)
    size = "%dx%d" % (im.shape[1], im.shape[0]) if im is not None else "?"
    name = os.path.basename(getattr(page, "source_path", "") or "page")
    print("find text  %-14s %-11s net %5.1fs  craft %5.1fs  rest %5.1fs "
          " total %5.1fs  %d boxes%s"
          % (name, size, t_net - t0, t_craft - t_net, done - t_craft,
             done - t0, n, "" if craft_on else "  (no craft)"),
          file=sys.stderr, flush=True)


def _all_the_cores():
    """OpenCV runs on every core it can see, every time this net is used.

    lee's machine line: `opencv 5.0.0  threads 1  cores 20`. ONE thread of
    twenty, and the forward pass took 65 seconds where this container's two
    cores take 2.5. Nothing in this codebase caps OpenCV's threads, so some
    import lowered it behind our backs - which is why this is asked again on
    EVERY call rather than once at startup: whoever set it to 1 can set it to
    1 again, and the page after they do should not cost a minute.

    Measured on opencv 5.0.0.93, this exact model, one page: 10.27s on one
    thread, 5.57s on two. It scales almost linearly, so on twenty cores the
    same reclaim is roughly the difference between a minute and seconds.
    """
    want = os.cpu_count() or 1
    if cv2.getNumThreads() < want:
        cv2.setNumThreads(want)


def _get_net(path: str):
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(
            "comic-text-detector model not found: "
            f"{path!r}. Download comictextdetector.pt.onnx from the "
            "manga-image-translator beta-0.2.1 release and point the "
            "detector model path at it.")
    _all_the_cores()
    if path not in _nets:
        _nets[path] = cv2.dnn.readNetFromONNX(path)
    return _nets[path]


def _letterbox(im: np.ndarray, new: int = INPUT):
    """Resize keeping aspect, pad bottom/right to a square - matches the
    comic-text-detector preprocessing so the output coordinates map back
    cleanly."""
    h, w = im.shape[:2]
    r = min(new / h, new / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    dw, dh = new - nw, new - nh
    if (w, h) != (nw, nh):
        im = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_LINEAR)
    im = cv2.copyMakeBorder(im, 0, dh, 0, dw, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    return im, dw, dh


def _decode_blocks(pred: np.ndarray, conf_thresh: float, nms_thresh: float):
    """YOLOv5-style decode: (N, 5+nc) -> list of (x1,y1,x2,y2,conf). Uses
    OpenCV NMS so there is no torch dependency."""
    if pred is None:
        return []
    pred = np.asarray(pred)
    if pred.ndim == 3:
        pred = pred[0]
    # some exports give (5+nc, N); the attribute dim is the small one (<=16),
    # so flip only when the columns are the many boxes and rows the few attrs.
    if pred.ndim == 2 and pred.shape[1] > 16 and pred.shape[0] <= 16:
        pred = pred.T
    if pred.ndim != 2 or pred.shape[1] < 6:
        return []
    obj = pred[:, 4]
    pred = pred[obj > conf_thresh]
    if pred.shape[0] == 0:
        return []
    cls_conf = pred[:, 5:] * pred[:, 4:5]
    conf = cls_conf.max(1)
    keep = conf > conf_thresh
    pred, conf = pred[keep], conf[keep]
    if pred.shape[0] == 0:
        return []
    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    rects = np.stack([cx - w / 2, cy - h / 2, w, h], 1)
    idxs = cv2.dnn.NMSBoxes(rects.tolist(), conf.astype(float).tolist(),
                            conf_thresh, nms_thresh)
    out = []
    for i in np.array(idxs).reshape(-1):
        x, y, bw, bh = rects[int(i)]
        out.append((float(x), float(y), float(x + bw), float(y + bh),
                    float(conf[int(i)])))
    return out


def _largest_zero_run(proj: np.ndarray, tol: int):
    """Longest run of (near) empty entries in a 1-D projection - the widest
    whitespace band. Returns (length, centre index)."""
    best_len, best_at, run, start = 0, 0, 0, 0
    for j, v in enumerate(proj):
        if v <= tol:
            if run == 0:
                start = j
            run += 1
        else:
            if run > best_len:
                best_len, best_at = run, start + run // 2
            run = 0
    if run > best_len:
        best_len, best_at = run, start + run // 2
    return best_len, best_at


def _xycut(ink: np.ndarray, vgap: int, hgap: int, tol: int, depth: int = 0
           ) -> list[np.ndarray]:
    """Recursive XY-cut. An empty ROW band (a VERTICAL gap - the "height"
    control) splits when it is >= `vgap`; an empty COLUMN band (a horizontal
    gap - the "distance" control) splits when it is >= `hgap`. Either can fire;
    when both do, the one that most exceeds its own threshold wins."""
    ys, xs = np.nonzero(ink)
    if xs.size < 20:
        return []
    if depth >= 8:
        return [ink]
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    sub = ink[y0:y1 + 1, x0:x1 + 1]
    rg, rat = _largest_zero_run(sub.sum(1), tol)   # empty ROWS -> vertical gap
    cg, cat = _largest_zero_run(sub.sum(0), tol)   # empty COLS -> horizontal gap
    r_ok, c_ok = rg >= vgap, cg >= hgap
    if not (r_ok or c_ok):
        return [ink]
    if r_ok and (not c_ok or (rg - vgap) >= (cg - hgap)):
        cut = y0 + rat
        a = ink.copy(); a[cut:, :] = 0
        b = ink.copy(); b[:cut, :] = 0
    else:
        cut = x0 + cat
        a = ink.copy(); a[:, cut:] = 0
        b = ink.copy(); b[:, :cut] = 0
    return (_xycut(a, vgap, hgap, tol, depth + 1)
            + _xycut(b, vgap, hgap, tol, depth + 1))


# The close in `_blob_split` is only ever asked a question about CONNECTIVITY:
# which pieces of ink end up in the same blob. The masks it returns are cut
# from the original ink (`blab == li) & (ink > 0)`), so the closing itself
# never contributes a pixel to any answer.
#
# That matters because the kernel is as wide as the gap being bridged -- 3.5
# median marks on a webtoon -- and on a page with a big brush sound effect the
# median mark is 148 pixels, so the kernel comes out **518 across**. An ellipse
# is not separable, and one such call measured **4.6 seconds** on a 720x1212
# crop.
#
# So a large kernel is answered at a smaller scale. The gap and the kernel
# shrink together, connectivity is preserved, and the labels are read back up
# at full size. `COARSE` is the kernel size to aim for once shrunk: bigger is
# more faithful and slower.
COARSE = 48


def _blob_split(ink: np.ndarray, gap: int) -> list[np.ndarray]:
    """Separate ink into blobs by bridging gaps up to `gap`; anything farther
    apart than that becomes its own blob. Catches groups that are separated
    diagonally or irregularly, where a straight XY-cut finds no clean band."""
    k = max(3, int(gap))
    f = max(1, int(round(k / float(COARSE))))
    if f > 1:
        h, w = ink.shape[:2]
        sh, sw = max(1, h // f), max(1, w // f)
        small = cv2.resize(ink, (sw, sh), interpolation=cv2.INTER_AREA)
        small = (small > 0).astype(np.uint8)
        sk = max(3, int(round(k / float(f))))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sk, sk))
        closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel)
        closed = cv2.resize(closed, (w, h), interpolation=cv2.INTER_NEAREST)
        # A piece of ink that fell between two sample rows on the way down
        # would come back with no label at all, so the closing is unioned with
        # the ink it is labelling. It can only ever have covered it anyway.
        closed = ((closed > 0) | (ink > 0)).astype(np.uint8)
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
    nb, blab, bstats, _ = cv2.connectedComponentsWithStats(closed, 8)
    if nb <= 2:
        return [ink]
    total = int(ink.sum())
    out = []
    for li in range(1, nb):
        m = ((blab == li) & (ink > 0))
        if int(m.sum()) >= max(20, 0.03 * total):
            out.append(m.astype(np.uint8))
    return out if len(out) >= 2 else [ink]


def _split_clusters(text: np.ndarray, gap_mult: float = 1.8,
                    height_mult: float = 1.8) -> list[np.ndarray]:
    """Split one detected block into separate texts on whitespace gaps wider
    than the character-size threshold (distance) or an empty row band (height).
    Returns one full-page mask per piece."""
    ink = (text > 0).astype(np.uint8)
    if int(ink.sum()) < 40:
        return [ink]
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    if n <= 1:
        return [ink]
    sizes = np.maximum(stats[1:, cv2.CC_STAT_HEIGHT],
                       stats[1:, cv2.CC_STAT_WIDTH])
    gsz = float(np.median(sizes)) if sizes.size else 10.0
    hgap = max(4, int(round(gsz * gap_mult)))      # horizontal / distance
    vgap = max(4, int(round(gsz * height_mult)))   # vertical / height
    tol = max(1, int(round(gsz * 0.15)))           # ignore a few stray pixels

    # Everything below works on a CROP round the writing, not on the page.
    #
    # `text` arrives as a full-page mask holding one block, and on a webtoon
    # that page is 720 by up to 7,000 -- four megapixels of empty for a few
    # hundred pixels of ink. The close inside `_blob_split` uses an elliptical
    # kernel as wide as the gap it is bridging, which on these formats is 3.5
    # median marks, and an ellipse is not separable: the cost is the whole
    # canvas times the kernel. Profiled on a 720x5702 page, that one call was
    # **21.4 of 34.1 seconds** -- more than the neural net.
    #
    # lee: *"right now its taking a very ong tike to do pages"*.
    #
    # Nothing about the answer changes. Morphology, connected components and
    # the XY-cut are all translation-invariant, and the margin is wider than
    # the kernel, so what happens inside the crop is what would have happened
    # inside the page. There is a test that runs both and compares.
    H, W = ink.shape[:2]
    ys, xs = np.nonzero(ink)
    pad = max(hgap, vgap) + 2
    y0 = max(0, int(ys.min()) - pad); y1 = min(H, int(ys.max()) + pad + 1)
    x0 = max(0, int(xs.min()) - pad); x1 = min(W, int(xs.max()) + pad + 1)
    small = ink[y0:y1, x0:x1]

    parts = []
    for blob in _blob_split(small, hgap):          # distance separation
        parts += _xycut(blob, vgap, hgap, tol)     # + straight-band separation
    parts = [p for p in parts if int(p.sum()) >= 20]
    parts = _merge_columns(parts)                  # undo splits of one bubble
    if len(parts) < 2:
        return [ink]
    out = []
    for p in parts:
        full = np.zeros((H, W), np.uint8)
        full[y0:y1, x0:x1] = p
        out.append(full)
    return out


def _merge_columns(parts: list) -> list:
    """Merge pieces that are really columns of ONE bubble, not separate texts:
    side by side (small horizontal gap, overlapping vertically) with the same
    height and matching top and bottom edges. A sound effect or a second line
    has a different height or a staggered top/bottom, so it stays separate."""
    if len(parts) < 2:
        return parts

    def _bb(m):
        ys, xs = np.nonzero(m)
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    boxes = [_bb(p) for p in parts]
    changed = True
    while changed and len(parts) > 1:
        changed = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                ax0, ay0, ax1, ay1 = boxes[i]
                bx0, by0, bx1, by1 = boxes[j]
                ah = ay1 - ay0 + 1; bh = by1 - by0 + 1
                mh = max(ah, bh)
                hgap = (bx0 - ax1) if ax1 < bx0 else \
                       (ax0 - bx1) if bx1 < ax0 else 0     # side-by-side gap
                vov = min(ay1, by1) - max(ay0, by0)        # vertical overlap
                if (hgap <= 0.25 * mh                       # extremely close
                        and abs(ah - bh) <= 0.15 * mh       # same height
                        and abs(ay0 - by0) <= 0.15 * mh     # tops match
                        and abs(ay1 - by1) <= 0.15 * mh     # bottoms match
                        and vov >= 0.6 * min(ah, bh)):      # truly side by side
                    parts[i] = ((parts[i] > 0) | (parts[j] > 0)).astype(np.uint8)
                    boxes[i] = _bb(parts[i])
                    del parts[j]; del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return parts


# A caption is boxed off by STRAIGHT edges. A balloon is boxed off by a curve.
#
# lee, twice: *"one box over 2 text boxes and its missed labled as an outside
# box"*, and then *"teh ai fuly misslabed teh 6th picture"* -- page 006's
# caption, called Outside text. Counted over every box on all 67 pages of his
# chapter 1 and every one looked at: **23 of the 240 are captions and NOT ONE
# came back as `narration`.** About one box in eight.
#
# The old test looked for a dark rule hugging three sides, as the mean darkness
# of a 6-pixel strip. Two things wrong with it. A 3-pixel rule inside a 6-pixel
# strip tops out at 0.5, and widening the strip makes that worse, not better --
# on page 006 every side scores 0.00 at every distance out to 70 pixels. And
# half this chapter's captions have no dark rule at all to find: four are navy
# system panels with an ornate LIGHT frame and two are gold.
#
# The uniform-region idea was tried and failed, which is worth recording: a
# caption panel on a white page has an inside continuous with the page around
# it, so it is not a rectangle to a flood fill. Region fill came out at 0.68
# for captions against 0.77 for balloons -- no separation. Same fact that
# killed the two-white-lobes idea for the double balloon.
#
# So the edge rather than the region. Scan outward from each side of the box
# for one row -- or column -- where the picture changes sharply at the SAME
# PLACE right across the box. A printed rule does that, so does the boundary of
# a navy panel, a gold frame, and a white panel lying on artwork. A balloon
# outline is a curve and crosses any given row in two places, so it cannot.
#
#     reach 1.2   across 0.70..0.90   step 20..45   3 sides
#         -> 16 of 23 captions, 0 of 118 balloons wrongly called captions
#
# All nine combinations in that range give exactly 16 and 0, which is what
# makes it a threshold rather than a fit. The seven it misses stay `bubble`,
# which is what they are today, so nothing gets worse. Reaching further (2.0)
# finds one or two more and starts flagging balloons at the loose end.
RULE_REACH = 1.2         # how far outside the box to look, times the box
RULE_STEP = 30           # how big a change of grey counts as an edge
RULE_ACROSS = 0.80       # ...and how much of the box's span must change at once
RULE_SIDES = 3           # how many sides must have one


def _straight_edges(gray: "np.ndarray", box: tuple) -> int:
    """How many of the four sides have a straight edge just outside them."""
    H, W = gray.shape[:2]
    X1, Y1, X2, Y2 = box
    w = max(1, X2 - X1); h = max(1, Y2 - Y1)
    g = gray.astype(np.int16)
    found = 0
    for axis, span, start, step in (
            (0, h, Y1 - 1, -1), (0, h, Y2, 1),
            (1, w, X1 - 1, -1), (1, w, X2, 1)):
        for d in range(0, max(6, int(RULE_REACH * span))):
            i = start + step * d
            if i < 1 or i >= (H if axis == 0 else W) - 1:
                break
            if axis == 0:
                a, b = g[i, X1:X2], g[i + 1, X1:X2]
            else:
                a, b = g[Y1:Y2, i], g[Y1:Y2, i + 1]
            if a.size and float((np.abs(a - b) > RULE_STEP).mean()) \
                    >= RULE_ACROSS:
                found += 1
                break
    return found


def _classify_kind(gray: "np.ndarray", box: tuple) -> str:
    """Best-effort guess at a block's role from the art around it - for the
    'box type' label only. It never moves, resizes, adds or drops a box; it
    just sets kind.

    A caption is boxed off by straight edges; dialogue is wrapped in a bright
    enclosed shape; text on open artwork is 'freefloat' (outside text).
    Conservative - when unsure it returns 'bubble', and every box stays one
    click from a manual fix.

    The caption question is asked FIRST. It has to be: page 006's caption is a
    white panel on a starfield, so the ring round it is 0.433 bright against a
    0.45 bar and the freefloat test claimed it before anything else got a
    look. And it is safe to ask first - measured over the chapter it never once
    called a balloon a caption.
    """
    H, W = gray.shape
    X1, Y1, X2, Y2 = box
    bw = max(1, X2 - X1); bh = max(1, Y2 - Y1)

    if _straight_edges(gray, box) >= RULE_SIDES:
        return "narration"

    # freefloat: the margin around the text is mostly dark artwork, not paper -
    # i.e. the text sits on the drawing, not inside a balloon or caption.
    mx = max(8, int(0.40 * bw)); my = max(8, int(0.40 * bh))
    ax0 = max(0, X1 - mx); ay0 = max(0, Y1 - my)
    ax1 = min(W, X2 + mx); ay1 = min(H, Y2 + my)
    sub = gray[ay0:ay1, ax0:ax1]
    if sub.size == 0:
        return "bubble"
    frame = np.ones(sub.shape, bool)
    iy0 = Y1 - ay0; ix0 = X1 - ax0; iy1 = Y2 - ay0; ix1 = X2 - ax0
    frame[max(0, iy0):max(0, iy1), max(0, ix0):max(0, ix1)] = False
    ring = (sub > 200)[frame]
    if ring.size and float(ring.mean()) < 0.45:
        return "freefloat"
    return "bubble"


# A character this share of the page WIDE is not dialogue. lee's 부스럭 measures
# 0.223 of the page; the next biggest character in any balloon on the chapter is
# 0.120, and the studio credits at the end are 0.015. See the demotion.
LOOSE_HUGE = 0.15
# ...and a box of OUTSIDE TEXT this much taller than it is wide. Korean runs
# along a line, so a tall box out on the artwork is one drawn shape, not a
# sentence. Same 1.15 the file already uses to call a box vertical.
TALL_EFFECT = 1.15


def _glyph_share(gray: "np.ndarray", bbox, mask=None) -> float:
    """How big this box's characters are, as a share of the page WIDTH.

    Off the page width and not the box, because a box is drawn round whatever
    was found and a page is the thing the artist drew to.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    if mask is not None:
        ink = (np.asarray(mask)[y0:y1, x0:x1] > 0).astype(np.uint8)
    else:
        ink = (gray[y0:y1, x0:x1] < INK).astype(np.uint8)
    if int(ink.sum()) < DRAWN_MIN_INK:
        return 0.0
    n, _l, st, _c = cv2.connectedComponentsWithStats(ink, 8)
    hs = [int(st[i, cv2.CC_STAT_HEIGHT]) for i in range(1, n)
          if int(st[i, cv2.CC_STAT_AREA]) >= DRAWN_PIECE]
    if not hs:
        return 0.0
    med = float(np.median(hs))
    hs = [v for v in hs if v >= 0.45 * med] or hs
    return float(np.median(hs)) / float(max(1, W))


def _taller_than_wide(bbox) -> bool:
    w, h = int(bbox[2]), int(bbox[3])
    return bool(w) and h > TALL_EFFECT * w



# How big the characters in a COVERAGE box may be before it is read as a drawn
# shape rather than as writing the block head missed. Smaller than `LOOSE_HUGE`
# and measured on a different question: 0.10 of the page width is the line
# between 진 빠진다 (0.051) and 달칵 (0.109), the two boxes on either side of it.
COVER_CHAR = 0.10

# ...and how bright the paper the letters are PRINTED ON has to be. Measured
# inside the box, ink excluded. lee, of page 048: *"this is not a negotiable it
# need to be detected"* -- four lines of set type inside a spiky white burst
# laid over dark trousers. Its margin is not paper at any radius (206 close in,
# 191 wide) because the burst's rays run right up against the writing, but the
# writing itself is standing on the burst's white core:
#
#   the sky, demote          margin 200   under the letters 191
#   page 048's burst, keep   margin 206   under the letters 227
#   the system panel, keep   margin 252   under the letters 254
#
# So the margin is asked first and this is asked second, and BOTH have to say
# "not paper" before the word dialogue is taken away.
UNDER_PAPER = 210


def _paper_under(gray: "np.ndarray", bbox, mask=None) -> float:
    """The tone of what the writing in this box is printed on.

    Everything inside the box that is not ink and not touching ink -- the ink
    is grown by a couple of pixels first, because the edge of a letter is a
    ramp and counting the ramp drags a white page grey.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return 255.0
    sub = gray[y0:y1, x0:x1]
    if mask is not None:
        ink = (np.asarray(mask)[y0:y1, x0:x1] > 0).astype(np.uint8)
    else:
        ink = (sub < INK).astype(np.uint8)
    grown = cv2.dilate(ink, np.ones((5, 5), np.uint8)) > 0
    v = sub[~grown]
    return float(np.median(v)) if v.size else 255.0


# How bright the paper round a box has to read before it counts as a balloon
# lining rather than a pale sky. See `_ring_paper`.
LOOSE_RING = 230


# How far out to look for the paper. NOT `_classify_kind`'s 0.40 -- that reaches
# clean past a small enclosure into whatever is drawn beyond it, and lee's
# system panel ("용사 링카는 마법사 소환진을 얻었다!") is exactly that case: its
# own white frame reads 252 at 8% and 225 at 40%, because at 40% the ring is
# mostly the yellow burst outside the panel. Measured on the four boxes that
# matter, median tone of the ring:
#
#                          40%   15%    8%
#   the sky, demote        205   205   200
#   a balloon, keep        251   255   255
#   the system panel,keep  225   251   252
#
# 8% keeps the panel by 52 and still demotes the sky by 30.
RING_LOOK = 0.08
RING_FLOOR = 4


def _ring_paper(gray: "np.ndarray", bbox) -> float:
    """The median tone of the margin just outside a box.

    The same question `_classify_kind` asks, measured differently. That one
    measures what SHARE of a wide margin is brighter than 200, which a pale
    blue morning passes at 0.555; this one measures what the margin close in
    actually IS. The lining of a balloon is paper and reads 251-255. Sky reads
    200.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    mx = max(RING_FLOOR, int(RING_LOOK * w))
    my = max(RING_FLOOR, int(RING_LOOK * h))
    ax0, ay0 = max(0, x - mx), max(0, y - my)
    ax1, ay1 = min(W, x + w + mx), min(H, y + h + my)
    sub = gray[ay0:ay1, ax0:ax1]
    if sub.size == 0:
        return 0.0
    frame = np.ones(sub.shape, bool)
    frame[max(0, y - ay0):max(0, y - ay0 + h),
          max(0, x - ax0):max(0, x - ax0 + w)] = False
    v = sub[frame]
    return float(np.median(v)) if v.size else 0.0


# How full of ink a box must be to survive `_looks_hand_drawn`. Both numbers
# come straight out of `letterforms` in /root/measure/outside_or_effect.py and
# changing either of them changes what the measurement below means.
DRAWN_PIECE = 25         # ink smaller than this is a speck, not a letter
DRAWN_MIN_INK = 40       # below this there is nothing here to measure


def _looks_hand_drawn(gray: "np.ndarray", bbox, mask=None,
                      thresh: float = 0.28) -> bool:
    """Is this OUTSIDE TEXT box actually a drawn sound effect?

    lee: *"outside tetx is usualy normal tet hats just outide the boubble while
    sfx are usualy text with starteched charaters"*, narrowed by his next
    message to *"it shoud only apply for outide text and sfx so boubble text
    shoud not be considered"*.

    The diagnosis is right -- the answer is in the letters, not in the artwork
    behind them, which is what the ring test was asking about and why it kept
    calling plain type on a sky a sound effect. The feature he named is not the
    one that works. Four were measured off the ink inside the box: the spread
    of the glyph heights (his "stretched characters"), the variation in pen
    weight, how far the glyph bottoms stray from their row, and FILL, the share
    of the rectangle that is ink.

    His own example settles the first three. 부웅 on page 037 of chapter 1 is a
    brush-drawn shout and it scores 0.12 on height spread -- the most REGULAR
    value in the whole set, three big characters of similar height. The
    baseline number did catch it, then scored 0.00, 0.03, 0.00 and 0.11 on
    chapter 8's drawn effects, so it only ever worked because 부웅's three
    characters happen to sit on a diagonal.

    Fill is the one left, and it is the difference between a hollow outlined
    shout and solid set type. On the 12 hand-labelled boxes it separated every
    one of them -- drawn max 0.288, set min 0.291 -- and that 0.003 margin is
    sample luck, not a rule. Checked against a bigger population where the
    label is the detector's own provenance (39 boxes the block head found
    inside balloons, which is set type and the head is excellent at it, against
    12 the coverage pass found alone, which is by construction writing that
    head could not see), a line at 0.29 puts 9 of the 39 set-type boxes on the
    wrong side. 23% of real writing.

    So the line is not fitted for accuracy. lee: asked whether a correctly
    found sound effect VANISHING from a manhwa page -- which is what
    `project.detectable_kinds` does with an sfx box -- is better or worse than
    one sitting there mislabelled, he said better. That makes a false positive
    expensive: it does not mislabel his text, it deletes it. So the threshold
    is the most aggressive one with ZERO false positives.

    **AND THE FLOOR HAS TO BE MEASURED ON THE RIGHT POPULATION.** It was 0.20
    for one day, taken from the emptiest box of printed dialogue on the pages
    (0.225). That is the wrong floor: this function is only ever called about a
    box already called OUTSIDE TEXT, so dialogue inside a balloon is not a box
    it can hurt. lee, sending back the figure with 부웅 on it -- *"this shoud be
    sfx not outside text ... make its so that this is an sfx"* -- was right,
    and the reason it was not is that the line had been drawn against boxes the
    rule never sees.

    Measured on the population it DOES see, both chapters hand-labelled:

        real writing, outside a balloon   0.291  0.433  0.471  0.554  0.559
        drawn effects                     0.093  0.136  0.146  0.248  0.275

    0.28 sits between them. Run over all 82 pages of chapters 1 and 8, 238
    boxes, it renames seven: 부웅, three 짭툰.com watermarks, and three drawn
    effects. **No real writing, on any page.**

    The margin is 0.011 on six labelled boxes and that is thin -- and the wider
    typography is the reason for caution rather than comfort: 25% of the
    dialogue INSIDE balloons is emptier than 0.28. If outside-text writing ever
    behaves like balloon dialogue, this line will delete some. Lower the number
    and that stops; 0.20 was safe and caught nothing lee cared about.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    sub = gray[y0:y1, x0:x1]
    if sub.size < 400:
        return False
    if mask is not None:
        ink = (np.asarray(mask)[y0:y1, x0:x1] > 0).astype(np.uint8)
    else:
        ink = (sub < INK).astype(np.uint8)
    # White typesetting on a black balloon carries no dark ink at all, and a
    # box measured off nothing would read as empty and be thrown away.
    if int(ink.sum()) < DRAWN_MIN_INK:
        ink = (sub > 200).astype(np.uint8)
    if int(ink.sum()) < DRAWN_MIN_INK:
        return False
    # One mark is a mark. The measurement was made on boxes holding at least
    # two pieces of writing and says nothing about the others, so they are left
    # alone -- which here means left as outside text, on the page.
    n, _lab, st, _c = cv2.connectedComponentsWithStats(ink, 8)
    if sum(1 for i in range(1, n)
           if int(st[i, cv2.CC_STAT_AREA]) >= DRAWN_PIECE) < 2:
        return False
    fill = float(ink.sum()) / float(max(1, (y1 - y0) * (x1 - x0)))
    return fill < thresh



# --- the coverage pass ------------------------------------------------------
#
# The model has two heads that can find writing: `blk`, which draws a rectangle
# round each block of text, and `seg`, a mask that marks every pixel of writing
# on the page. Measured on lee's chapter, `blk` is excellent at dialogue -- it
# boxes even the black balloons with white typesetting, which nothing that looks
# for dark ink can ever find -- and completely blind to sound effects drawn onto
# the artwork: page 8 lost はら, ドキーッ, 居たぞ and 落ちてたわよ, page 13 lost
# every one of its six. Dropping conf_thresh from 0.4 to 0.05 does not bring
# them back (page 13: 5 boxes at 0.4, 8 at 0.05, none of them the sound
# effects), because they are simply not in that head's output.
#
# `seg` has them all. So the mask is read twice: once inside each block, to
# measure that block's boxes, and once for everything left over, which is the
# writing the block head never saw.
SEG_KEEP = 0.30          # how sure the mask must be before a pixel counts
LEFT_PIECE = 12          # ink smaller than this is a printing speck
LEFT_NEAR = 0.60         # two pieces join when the gap is small next to them
LEFT_INK = 500           # measured floor: real leftover writing carries 615+,
                         # tone dots and stray marks topped out at 438
LEFT_SIDE = 12           # ... and a piece of writing is at least this thick
DUP_IOU = 0.72           # two boxes this far on top of each other are one box
# ...and how much of the SMALLER has to be inside the bigger before it is not a
# second piece of writing but a second box over the same piece. IoU cannot see
# a pair whose rectangles are nothing like the same size. See `_drop_duplicates`.
DUP_INSIDE = 0.75
# ...and how far apart in AREA the two may be before the smaller is read as a
# thing inside a bigger thing rather than a second answer about one thing.
DUP_UNEVEN = 0.10
# How much two boxes have to overlap, as a share of the smaller one's
# rectangle, before they are read as ONE piece of writing that came back in
# pieces. See `_join_overlapping` for what this is measured on.
JOIN_OVER = 0.05
# ...and the same, raised, for a pair where only ONE of the two was seen by a
# pass that measures ink. See `_join_overlapping`.
JOIN_ALONE = 0.20
# ...and the same question for two boxes that do NOT overlap: how far apart
# they may stand and still be one piece of writing, as a share of the shorter
# box's height, and how much of the perpendicular extent has to line up before
# the gap is worth measuring at all. See `_next_to`.
NEAR_SIDE = 0.75         # a word space, sideways along one line
NEAR_STACK = 0.35        # the leading between two lines of one caption
NEAR_PERP = 0.80
# How empty a box has to be, and how few marks it may hold, before there is
# nothing in it that anybody wrote. See `_a_stray_mark`.
STRAY_PIECES = 2
STRAY_FILL = 0.115
STRAY_MARK = 25          # ink smaller than this is a speck, not a mark
# ...and how much of a box one or two characters have to cover before the box
# is a drawn shout rather than a short line of dialogue. See the two CRAFT
# questions at the bottom of `detect_comictext`.
FX_CHARS = 2
FX_COVER = 0.30
# ...and the reverse: a box called sfx holding this many characters, of at
# most this height as a share of the page width, is a body of writing the
# coverage pass swallowed. See the same block.
SFX_TEXT_CHARS = 6
SFX_TEXT_H = 0.15
# The Canny thresholds and the seal for the ENCLOSURE question -- "is anything
# at all drawn round this writing" -- as against the balloon rescue's own
# `balloon.WALL_LO/HI/SEAL`. Gentler on purpose: the walls it has to see are
# drawn fainter than a balloon's. lee's pale thought-circles read nothing at
# 30/90, and his ornate caption frame has ornament gaps wider than the 15px
# seal. Measured over every no-balloon box on 46 pages, these move exactly
# three answers -- that frame, those two circles -- and none of the bursts,
# credits or bare-paper captions.
ENCLOSE_LO = 20
ENCLOSE_HI = 60
ENCLOSE_SEAL = 25
# Two texts in one box. How much the two groups may share of each other's
# rows AND columns before the staircase refuses (039 and 040 measure under
# 0.11 on columns; nothing that is one text comes near); how many
# line-heights of empty band say two stacked texts (the real pairs measure
# 1.11-2.85, the widest gap inside one text is 0.50); and the least share of
# the ink either side may hold (035's droplet marks are 2%). See
# `_two_texts_in`.
DIAG_ROWCOL = 0.30
STACK_SPLIT = 0.80
DIAG_BALANCE = 0.15
# How dense with drawn strokes the margin of a paper-ringed box must be
# before the strokes are read as a burst's rays. See `_ring_rays`.
RAYS_DENS = 0.04
# PAINTED LETTERING IS NOT DIALOGUE.
#
# How coloured the strokes may be, in Lab chroma, before the two WEAKEST
# escapes from the demotion are refused. See `_ink_chroma`.
#
# Only those two: the burst's rays and the bright floor are the escapes that
# never find anything drawn round the writing -- they read the ground and
# infer a balloon from it. A balloon mask, a round wall and an enclosure are
# all somebody's line round the letters, and a coloured line of dialogue
# inside a real balloon must keep it. Two on this chapter do: the blue second
# line on 008 scores 24.3 and 065's tinted shout 22.1, and both are inside
# drawn ovals, so neither is ever asked.
#
# Measured over the sixteen boxes that reach the paper test on chapter 1.
# Every one that is rightly dialogue scores 0.0 -- 042's two bursts, 044's two
# spiky balloons, 017's ornate caption frame, 012's and 072's credit lines.
# 로얀 수틀렉스 scores 33.5. Nothing on the chapter lands between, and the bar
# sits at twelve with twelve below it and twenty-one above.
INK_CHROMA = 12.0
CHROMA_MIN_BOX = 100     # a box smaller than this has no letters to read
CHROMA_MIN_INK = 30      # ...nor has one with fewer strokes than this
CHROMA_FRAME = 2         # the border of the box, which the GROUND runs to
# The box of a writing region is the writing. A single blob of ink this big,
# outside every character the second detector sees, is a piece of the artwork
# the mask swallowed -- the junk cases measure 2,267-23,619 against 1,048 for
# the biggest legitimate fringe. See the shave in the CRAFT block.
SHAVE_BLOB = 1500
SHAVE_NEAR = 8           # the margin round a character that is its own ink
# There is NO fill-ratio floor here, and there must not be one. Page 17 came
# back with a 351x358 box over collapsing masonry holding no writing at all,
# filling a tenth of its own rectangle where the real writing on that page
# filled a fifth to a half, so a 0.18 floor was tried. Every gate-dropped box
# on all 39 pages was then cropped and looked at: 8 were artwork, and 9 were
# real sound effects -- 004's ドン崩壊, 012's キッ, 015's ドドド and ドドン, 016's
# ゴーン, 018's トク, 020's ミシ, 024's ガタガタ -- plus 012's 天の階は, which is
# the very writing lee said was being missed. Big hollow outlined typesetting
# fills as little of its box as a hollow outlined DRAWING does (real 0.10-0.16,
# artwork 0.09-0.16, no gap at all), because in both cases the ink is a thin
# line and the rest of the rectangle is whatever the line went round. No
# measurement of the box separates them. A box holding no writing is caught
# where that is a fact rather than a guess: after Read text, when the reader has
# had a look and come back with nothing.


# ---------------------------------------------------------------- per format
#
# What Find text is tuned to, one set of numbers per format.
#
# Every number in `manga` was measured on lee's chapters and is not to be
# touched by anything done for another format. lee: *"save what we ahve for
# find text for manga and now we will modify it for manhwa"*.
#
# The other two start as COPIES, not aliases, so the fork costs nothing today -
# a manhwa page is found exactly as it was this morning - and tuning one of
# them can never reach back into manga. That is the whole point of the table:
# not the values, which are identical right now, but the fact that they are
# separate values.
#
# `tuning_for` hands back a copy of its own, so a caller that edits what it
# gets does not edit the table.
TUNING = {
    "manga": {
        "conf_thresh": 0.4,      # how sure the block head must be
        "nms_thresh": 0.35,      # how much two blocks may overlap
        "mask_thresh": SEG_KEEP,  # how sure a pixel of the mask must be
        "split_gap": 1.8,        # the gap that ends one block of writing
        "split_height": 1.8,     # ...and the same across lines
        # How far one leftover mark reaches for another, as a CIRCLE: the
        # straight-line gap, over the smaller mark. None means `LEFT_NEAR`,
        # which is what manga was measured on.
        "join_x": None,
        "join_y": None,
        # The second detector, and the reach for ITS marks. None is off, and
        # manga is off by construction: `blk` and `seg` were measured on manga
        # across 39 pages and they find it. See `detect/craft.py`.
        "craft_x": None,
        "craft_y": None,
        "craft_cap": 0.05,       # a group this big is a panel, not writing
        # How much of a mark the box must already hold before it may widen to
        # the whole of it. None is off, and manga is off: the clipping was
        # measured on lee's Korean webtoon and the numbers below are that
        # chapter's. See `_grow_to_the_stroke`.
        "sfx_grow": None,
        "sfx_grow_cap": 0.12,    # ...and a grow past this share of the page
        # The same question asked of a DIALOGUE box, and a much higher bar. A
        # sound effect is a drawn shape whose box came off something only
        # looking for writing, so 0.40 of a stroke is enough to follow it; a
        # letter is a letter, and a mark a printed box holds most of is its
        # own. None is off, and manga is off for the same reason as above:
        # measured on lee's Korean webtoon, not on manga.
        "text_grow": None,
        # How empty an OUTSIDE TEXT box has to be before it is called a sound
        # effect instead. None is off, and manga is off: measured on the Korean
        # webtoons and nowhere else. See `_looks_hand_drawn`.
        "effect_fill": None,
        # How close two balloons' paper has to come before their boxes are
        # joined as one balloon. None is off, and manga is off: measured on
        # lee's webtoon pages. See `balloon.link_touching_bubbles`.
        "link_touching": None,
        # Taking the word "dialogue" back off a box with no balloon anywhere
        # near it. None is off, and manga is off: measured on chapter 1 of the
        # Korean webtoon and on nothing else. See the demotion at the bottom of
        # `detect_comictext`.
        "loose_bubble": None,
        # How full of ink a box the COVERAGE pass found has to be before it is
        # read as writing the block head missed rather than as a drawn shape.
        # None is off, and manga is off: measured on the Korean webtoons. See
        # the last block of `detect_comictext`.
        "cover_text": None,
        # How much two boxes must overlap, as a share of the smaller, before
        # they are read as one piece of writing in pieces. None is off, and
        # manga is off: the "no two separate texts on the chapter overlap"
        # measurement is a fact about 46 Korean webtoon pages and about
        # nothing else. See `_join_overlapping`.
        "join_over": None,
        # ...and how empty a box holding at most two marks has to be before
        # there is nothing written in it. None is off, and manga is off for
        # the same reason. See `_a_stray_mark`.
        "stray_fill": None,
        # Letting the second detector veto a BLOCK HEAD box it can see no
        # characters in, and read one it sees only a character or two in as a
        # drawn shout. Off, and manga is off twice over: these need CRAFT,
        # which manga does not run, and the counts behind them were measured
        # on 46 Korean webtoon pages. See the two questions at the bottom of
        # `detect_comictext`.
        "art_veto": False,
        "fx_chars": None,
        # Splitting one box that holds two texts -- the staircase and the
        # stacked band. Off, and manga is off: both bars were measured on 46
        # Korean webtoon pages and on nothing else. See `_two_texts_in`.
        "split_texts": False,
    },
}

# The webtoons, first pass. Three of the five moved, and why:
#
# lee, with all three box types ticked: *"its still missing a lot of sfx"*, and
# the ones it did find came back in pieces - one hand-drawn 촤악 as boxes 4 and
# 5, one 퍽 as boxes 1 and 2.
#
#   conf_thresh  unchanged      It was 0.22 here for one turn, on the
#                               reasoning that a brush-drawn Korean sound
#                               effect lying on bare artwork with no enclosure
#                               scores low on a head trained to look for
#                               printed type inside a drawn one. That is right
#                               about WHY the head misses them and wrong about
#                               what lowering the bar buys, and lee's own
#                               chapter settled it. On page 028 - 720x2770,
#                               sound effects covering something like a sixth
#                               of it - the head returns 0 blocks at 0.22, 0
#                               at 0.10 and 0 at 0.05. On page 021 it returns
#                               the same 2 blocks at 0.05 as at 0.40. There is
#                               no confidence at which those effects appear,
#                               because they are not in that head's output at
#                               any score. What the 0.22 DID buy was boxes on
#                               an eye and a jewel on page 026. A bar lowered
#                               for something it cannot reach, paid for in
#                               artwork, goes back up.
#   mask_thresh  0.30 -> 0.20   ...and so the COVERAGE pass - the one that
#                               re-reads the mask for ink the block head
#                               missed, which is exactly this - has ink to
#                               find. A thin brush stroke on white is the
#                               weakest thing on the mask.
#   split_gap    1.80 -> 3.50   Both gaps are multiples of the MEDIAN mark in
#                               the block. Hangul is written as separate
#                               syllable blocks and a brush-drawn shape leaves
#                               daylight between them, so the median mark is
#                               small and the gaps between them are large next
#                               to it - which is the arithmetic that cut one
#                               effect into two boxes. Widened, so one sound
#                               effect stays one sound effect. This is the
#                               SIDEWAYS gap and it stays at 3.50: the effects
#                               that came back in pieces came back in pieces
#                               side by side.
#   split_height 3.50 -> 1.10   The gap DOWN the page, moved with its sideways
#                               twin on the same reasoning and measured
#                               afterwards - see THE DOUBLE BALLOON below.
#   nms_thresh   unchanged      Nothing lee showed was two boxes on top of one
#                               another; they were two boxes side by side.
#
# `join_x` / `join_y` were then measured on all 36 pages of lee's chapter: the
# joins inside one effect need gx/sz <= 1.72 and gy/sz <= 0.60, and the closest
# pair belonging to two DIFFERENT effects sits at gy/sz = 1.02, so no circle
# separates them (a circle wide enough to close the 1.72 merges two effects
# into a box covering 17% of the page). An ellipse 1.8 wide by 0.9 tall clears
# both with margin: 21 groups in, 21 groups out, no box over 5% of a page.
# Manga keeps its circle.
#
# `mask_thresh` is the one number here still unmeasured. It is kept because it
# feeds the coverage pass, which is the pass that is working.
#
# `craft_x` / `craft_y` -- the second detector's reach -- are measured on the
# same 36 pages, and they are NOT the mask's 1.8 x 0.9. The mask's marks are
# stroke fragments, often a fraction of one syllable, so 1.8 is a fraction of a
# syllable; CRAFT's pieces are whole character groups, so the same 1.8 is 1.8
# whole syllables, and it swept all eight 하아 on page 026 into one box covering
# 26% of the page. Same rule, different marks, measured again:
#
#   jx / jy    026    biggest    pages >5%   chapter groups
#   0.20/0.20    8      26.1%            6              525
#   0.25/0.10    8      26.1%            4              571
#   0.30/0.05    8      26.1%            4              548   <- here
#   0.50/0.10    5      26.1%            4              452
#
# Page 026 holds eight sound effects, so eight groups is the answer and 0.50
# undershoots it. Between the two that get eight, 0.30/0.05 fragments the
# chapter less (548 groups against 571), and on page 018 -- where the right
# answer is known, one box on the four-syllable effect and one on the
# two-syllable one -- the two are identical.
# The ratio being 6:1 rather than 2:1 is the same fact the mask's ellipse
# records, only sharper: CRAFT's pieces are whole syllables sharing a baseline,
# so two of one effect have almost no vertical gap at all.
#
# `biggest 26.1%` does not move at ANY reach, down to 0.15/0.05, and that is
# not a tuning failure -- see `craft.merge_into`, which falls back to the
# pieces. The bottom of page 026 is four 하아 cascading diagonally and every
# consecutive pair of their nine syllables has gx = 0 and gy = 0.
#
# THE DOUBLE BALLOON. lee: *"here are some issue to try to fix ... the doubke
# bubble"*, with screenshots of one red rectangle drawn across BOTH lobes of a
# two-lobed balloon -- one box where there should be two, so one translation
# and one typesetting for two separate things said.
#
# The first idea was that two balloons means two white regions and the box
# straddles them, which would have been a way to find it that does not depend
# on any threshold. It is wrong. On page 010 the two lobes share ONE white
# interior: the wall between them is not drawn, and eroding the white by eleven
# pixels does not separate them. Nothing distinguishes the lobes except the gap
# in the WRITING -- which is exactly what `split_height` already measures, and
# it was walking straight past it:
#
#     page 010 box 1   median mark 37   biggest empty row band 76px
#                      split_height 3.50 wanted 130
#
# So the only question was where the number goes, and that is a distribution.
# Every block the block head produced on all 67 pages of lee's chapter 1, 142
# of them, with the biggest empty row band as a multiple of the median mark.
# Every one over 0.83 was looked at:
#
#     13 are two lobes of one balloon under one box     1.17 .. 4.67
#      2 are real text that must stay whole             0.83, 1.00
#      4 are boxes on artwork with no writing in them   1.40 .. 4.20
#
#     and the other 123 blocks are all at 0.40 or below.
#
# The two that must stay whole are the credits line and the chapter title card,
# and the title card is the one that sets the bar: it is set with a whole
# line-height of leading, so its gap is 1.00 median marks, honestly airy rather
# than two of anything. Nothing real sits between 1.00 and 1.17, so the
# threshold goes in that gap and 1.10 is the middle of it: 13 of 13 double
# balloons split, 0 of 125 whole blocks broken.
#
# A second rule was tried and thrown away -- biggest gap over SECOND biggest,
# which asks "is one gap much wider than this block's own line spacing" and
# needs no notion of mark size. It cannot answer: a balloon with one line per
# lobe has no second gap, so 59 of the 125 whole blocks score infinity. Adding
# it to the ratio above changes nothing, and one number that separates cleanly
# beats two that need each other.
#
# What this does NOT cover: the four junk boxes now split into eight junk
# boxes. They are boxes on a building, a figure and two watermark strips with
# no writing in them at all -- a false-positive box is a different defect and
# fixing it here would mean tuning the threshold on blocks that should not
# exist. And the sound effects that put `split_gap` at 3.50 were on chapter
# 227, which is not measured here; the sideways gap they argued for is
# untouched, but if a vertical brush effect comes back in two pieces this is
# the number that did it.
# `join_y` was 0.9 and is 0.6. The old reach pulled the writing "진 빠진다, 진
# 빠져" and a purple lightning bolt drawn BELOW it into one 335x249 box holding
# 18% ink, which reads as a drawn shape whatever else is done, and on a manhwa
# that means dropped.
#
# ONLY the vertical reach moved, and `join_x` is untouched at 1.8. Both numbers
# were measured on chapter 227 and the sideways one is load-bearing: the two
# halves of one 퍽써! on page 18 sit 1.47 smaller-marks apart sideways, so
# anything under that cuts a real effect in two --
# `test_two_strokes_of_one_sound_effect_join_sideways` is that measurement and
# it fails at 1.2. The vertical one has room: the case it exists to refuse is
# two stacked effects on page 28 at 1.02 smaller-marks, and 0.6 refuses them
# exactly as 0.9 did. Swept over 17 pages of chapter 1: 0.7 does not split
# lee's box, 0.6 does.
TUNING["manhwa"] = dict(TUNING["manga"], mask_thresh=0.20,
                        split_gap=3.5, split_height=1.1,
                        join_x=1.8, join_y=0.6,
                        craft_x=0.30, craft_y=0.05,
                        sfx_grow=0.40, text_grow=0.70,
                        effect_fill=0.28, loose_bubble=LOOSE_RING,
                        cover_text=0.25,
                        join_over=JOIN_OVER, stray_fill=STRAY_FILL,
                        art_veto=True, fx_chars=FX_CHARS,
                        split_texts=True,
                        link_touching=_BL.TOUCH_GAP)
TUNING["manhua"] = dict(TUNING["manhwa"])


def tuning_for(medium: str | None) -> dict:
    """The numbers Find text should run with on this format.

    An unknown format is read as manga: it is the format the numbers were
    measured on, and falling back to the measured one is better than falling
    back to nothing.
    """
    return dict(TUNING.get(medium or "manga") or TUNING["manga"])


def _pieces(mask: np.ndarray):
    """The separate marks of ink in `mask`, specks thrown away."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in stats[i])
        if a >= LEFT_PIECE:
            out.append(dict(x0=x, y0=y, x1=x + w - 1, y1=y + h - 1,
                            ink=a, sz=max(w, h), lab=i))
    return out, lab


def reach_groups(marks, near: float | None = None,
                 near_x: float | None = None, near_y: float | None = None
                 ) -> dict:
    """Which marks belong to the same piece of writing.

    `marks` is anything with `x0 y0 x1 y1 sz` -- the mask's own pieces, or
    CRAFT's character groups, or a hand-written list in a test. Returns
    {root index: [indices]}.

    This is lifted out of `_harvest` so that a second source of marks is
    grouped by the SAME rule rather than by a second copy of it that can drift.
    The rule and the two shapes it comes in are documented on `_harvest`.
    """
    near = LEFT_NEAR if near is None else near
    n = len(marks)
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            a, b = marks[i], marks[j]
            gx = max(0, max(a['x0'], b['x0']) - min(a['x1'], b['x1']))
            gy = max(0, max(a['y0'], b['y0']) - min(a['y1'], b['y1']))
            s = min(a['sz'], b['sz'])
            if (gx <= near_x * s and gy <= near_y * s) if near_x and near_y \
                    else ((gx * gx + gy * gy) ** 0.5 <= near * s):
                ra, rb = find(i), find(j)
                if ra != rb:
                    par[ra] = rb
    out: dict = {}
    for i in range(n):
        out.setdefault(find(i), []).append(i)
    return out


def _harvest(tmask: np.ndarray, claimed: np.ndarray,
             near: float = None, near_x: float = None, near_y: float = None):
    """Group the writing the block head left behind.

    Two marks belong together when the gap between them is small next to the
    SMALLER of the two -- deliberately not next to the group they would make.
    An earlier version measured the gap against the merged box, which grows
    every time something joins it, and on page 13 that snowballed until one
    group covered the whole page (39,60)-(863,1320). Holding the reach to each
    mark's own size keeps a tall sound effect from reaching across a panel to
    pull in a small one, and a speck can never reach anything at all.

    **Two shapes of reach**, and which one is used is the format's business.

    `near` alone is a CIRCLE: the straight-line gap must be within `near` times
    the smaller mark. That is what manga was measured on and it stays exactly
    that.

    `near_x` and `near_y` are an ELLIPSE, wide and flat: the sideways gap and
    the up-and-down gap are allowed different reaches. Writing runs along a
    line, so two marks of one sound effect are beside each other; two different
    sound effects are usually stacked. Measured on lee's chapter 227 (36
    pages), the strokes that had to join inside one effect are at most 1.72
    smaller-marks apart sideways and 0.6 vertically, while the closest two
    marks belonging to DIFFERENT effects are 1.02 apart vertically. A circle
    cannot separate those; an ellipse can, and 1.8 by 0.9 sits between them
    with room on both sides.
    """
    P, lab = _pieces((tmask > 0) & ~claimed)
    bunches: dict = {}
    for root, members in reach_groups(P, near, near_x, near_y).items():
        bunches[root] = [P[i] for i in members]

    out = []
    for members in bunches.values():
        ink = sum(m['ink'] for m in members)
        x0 = min(m['x0'] for m in members); y0 = min(m['y0'] for m in members)
        x1 = max(m['x1'] for m in members); y1 = max(m['y1'] for m in members)
        if ink < LEFT_INK or min(x1 - x0 + 1, y1 - y0 + 1) < LEFT_SIDE:
            continue
        keep = np.zeros(int(lab.max()) + 2, bool)
        keep[np.array([m['lab'] for m in members], int)] = True
        sub = np.where(keep[lab[y0:y1 + 1, x0:x1 + 1]], 255, 0).astype(np.uint8)
        out.append(((x0, y0, x1, y1), sub, ink))
    out.sort(key=lambda g: -g[2])
    return out


def _grow_to_the_stroke(gray: "np.ndarray", bbox: tuple, share: float,
                        cap: float, pad: int = 0):
    """Widen a sound-effect box to the whole of the strokes it already holds.

    lee, with six screenshots of a box cutting the ends off a brush-drawn
    effect: *"the sfx is doing well but its still just sligthly miiing the edge
    of them"*. Measured on the chapter: **39% of the 82 sound-effect boxes have
    ink reaching more than a twentieth of the box outside them, against 1% of
    the 151 dialogue boxes.** The block head boxes printed type properly. It is
    the drawn effects that get clipped, because the box comes off the
    segmentation mask (or off CRAFT), and neither of those is a measurement of
    where the brush went -- only of where it looked most like writing.

    Growing a box to its ink was tried before and made things worse:

        on page 8 the はら box grew from (729,26,86,261) to (709,0,126,342),
        taking in the balloon edge and the girl's hair, and on page 13 the
        ぽん box slid off the writing and onto the birdcage below it.

    **The difference is `share`.** A mark is only followed if the box already
    holds that fraction of it. A balloon wall crossing the corner of the box, a
    hairline passing through it, a panel rule clipping its edge -- the box holds
    a sliver of each and may not follow any of them. At 0.40, measured over all
    82 sound-effect boxes on lee's chapter 1, 55 grow, the median grow is 1.17x
    and the ninetieth percentile 2.06x, and every one of the 30 biggest was
    cropped and looked at: each covers the effect where the old box clipped it.

    `cap` is the runaway guard and it is a share of the PAGE, not a multiple of
    the box, because that is what the failure actually is -- the same reasoning
    `craft_cap` is written on, that a rectangle this big is a panel and not
    writing. A multiple was tried first and it is the wrong shape: page 039's
    effect needs 6.1x and comes out at 5.1% of the page, which is fine, while
    page 043's box is already a fifth of the page and 2.2x takes it to a half,
    which is not. At 0.12 the first grows and the second does not.

    Both polarities are read. A sound effect is as often white with a coloured
    outline as it is black, and `gray < 110` finds nothing at all in the first
    case.

    Returns `(bbox, mask)` -- the widened box, and the marks that were followed,
    so the cleaner has the rest of the stroke to paint out and not just the part
    the detector originally saw.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    reach = max(40, max(w, h))
    y0, y1 = max(0, y - reach), min(H, y + h + reach)
    x0, x1 = max(0, x - reach), min(W, x + w + reach)
    sub = gray[y0:y1, x0:x1]
    if sub.size == 0:
        return tuple(bbox), None
    inside = np.zeros(sub.shape, bool)
    inside[y - y0:y - y0 + h, x - x0:x - x0 + w] = True
    keep = np.zeros(sub.shape, np.uint8)
    gx0, gy0, gx1, gy1 = x, y, x + w - 1, y + h - 1
    for ink in ((sub < INK - 18).astype(np.uint8),
                (sub > 200).astype(np.uint8)):
        n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
        for li in range(1, n):
            area = int(st[li, cv2.CC_STAT_AREA])
            if area < 40:
                continue
            piece = (lab == li)
            held = int((piece & inside).sum())
            if held < share * area or held < 30:
                continue
            ys, xs = np.nonzero(piece)
            gx0 = min(gx0, x0 + int(xs.min()))
            gx1 = max(gx1, x0 + int(xs.max()))
            gy0 = min(gy0, y0 + int(ys.min()))
            gy1 = max(gy1, y0 + int(ys.max()))
            keep |= piece
    gx0 = max(0, gx0 - pad); gy0 = max(0, gy0 - pad)
    gx1 = min(W - 1, gx1 + pad); gy1 = min(H - 1, gy1 + pad)
    gw, gh = gx1 - gx0 + 1, gy1 - gy0 + 1
    if gw * gh > cap * H * W:
        return tuple(bbox), None          # that is a panel, not a sound effect
    if (gx0, gy0, gw, gh) == tuple(bbox):
        return tuple(bbox), None
    full = np.zeros((H, W), np.uint8)
    full[y0:y1, x0:x1] = keep * 255
    return (gx0, gy0, gw, gh), full


def _characters_in(pieces, bbox):
    """What the second detector sees inside this box: how many character
    groups, how much of the box they cover, and their median height.

    A piece is counted if it meets the box at all - the same bar as
    `_seen_by`, and for the same reason: real writing goes down to 0.07 of a
    box and there is no fraction the measurement supports. The COVER is the
    union of the pieces clipped to the box, so two marks that overlap are not
    counted twice; the HEIGHT is of the clipped pieces, in pixels, because
    the question it answers is how big the characters on this page are.
    """
    x, y, w, h = [int(v) for v in bbox]
    if w <= 0 or h <= 0:
        return 0, 0.0, 0.0
    heights = []
    seen = np.zeros((h, w), bool)
    for px0, py0, px1, py1 in pieces:
        if px1 < x or px0 > x + w or py1 < y or py0 > y + h:
            continue
        heights.append(min(py1, y + h) - max(py0, y))
        a, b = max(0, px0 - x), max(0, py0 - y)
        c, d = min(w, px1 - x), min(h, py1 - y)
        if c > a and d > b:
            seen[b:d, a:c] = True
    if not heights:
        return 0, 0.0, 0.0
    return (len(heights), float(seen.sum()) / float(w * h),
            float(np.median(heights)))


def _seen_by(pieces, x0: int, y0: int, x1: int, y1: int) -> bool:
    """Does the second detector see ANY writing inside this box?

    lee, of the boxes Find text draws on his chapter: half of what came back as
    a sound effect had no writing in it at all - boxes on sword blades, faces,
    buildings, clothing, gold ornaments, and five times on the little trailing
    ellipses of a thought balloon's tail. 18 of 36 on chapter 1.

    That is the coverage pass. It keeps whatever ink the mask left over after
    the block head had its turn, and the mask fires on drawn lines as happily
    as on written ones. Six ways of telling the two apart were measured on
    those 36 boxes - how many separate marks, how even they are in size, ink
    density, how thin the longest stroke is, how many holes it has, and which
    pass made the box - and **not one of them separates**. The text and the
    artwork sit on top of each other in every distribution. The mask's leftover
    ink genuinely looks like writing by every cheap statistic there is.

    What does separate them is asking something that was trained on writing.
    CRAFT is already here for the other half of the job, so it costs one extra
    question per page:

        16 of 18 artwork boxes    CRAFT sees NOTHING in them
         2 of 18 artwork boxes    0.10 and 0.19 of the box covered
        17 of 18 real effects     0.07 to 0.53

    So the bar is the lowest one there is - any overlap at all. Not a fraction:
    a fraction would be a number to tune and the measurement does not support
    one, since the real effects run down to 0.07 and the two artwork boxes
    CRAFT does see run up to 0.19.

    **What it costs.** One real effect in eighteen: page 036's 휘잉, a thin
    hand-drawn vertical scrawl on pale paper, which CRAFT scores at 0.000 -
    and at 0.000 with `low_text` swept down to 0.15, so no amount of generosity
    recovers it. Nothing in the shape statistics tells it from the artwork
    boxes CRAFT also cannot see: page 031's face is 4 marks / 0.58 even / 0.133
    density / 1.4 thin / 4 holes against the 휘잉's 4 / 0.92 / 0.144 / 1.6 / 4.

    lee: *"Missed SFX is worse"* than an extra box to delete. So this is a
    setting and not a law - `auto_kind`'s neighbour in Find text - and it is on
    because 16 boxes gone for 1 lost is the better default, not because the
    loss is acceptable in the abstract.

    **Run for real over the whole chapter it does exactly that and no more.**
    257 boxes with the switch off, 240 with it on: 16 artwork boxes gone, one
    real effect gone, nothing added, nothing outside the coverage pass touched.
    The two artwork boxes CRAFT does see survive, as measured.

    An earlier version of this note claimed the veto also ADDED nine boxes,
    seven of them real effects. That was wrong and worth saying why: the
    "before" it was measured against had been recorded on a machine where
    easyocr was not installed, so CRAFT contributed nothing to it at all. Seven
    of those nine were boxes CRAFT adds whether the veto is on or off. A
    before-and-after has to move ONE thing.

    A veto needs an opinion. With no CRAFT installed, or a format that does not
    run it, `pieces` is None and nothing is ever refused.

    Both rectangles are INCLUSIVE of their far edge -- `_harvest` returns the
    last row and column of the ink, and CRAFT's are the corners of a polygon --
    so two that share one edge column share one column of pixels, and that is
    an overlap. Hence `>=` on all four and not `>` on some of them. At a
    one-pixel scale it decides nothing either way; being able to say which
    convention is in force is the point.
    """
    for cx0, cy0, cx1, cy1 in pieces:
        if cx1 >= x0 and cx0 <= x1 and cy1 >= y0 and cy0 <= y1:
            return True
    return False


def _next_to(a, b) -> bool:
    """Are these two boxes a word space apart on one line, or a line's
    leading apart in one column?

    lee, of "3년 전" with its trailing "…" boxed separately: *"one caption
    line split into three boxes"*. The two do not overlap -- there are 18
    pixels of daylight between them -- so `_join_overlapping`'s own rule
    cannot see them, and neither can anything else: they are two boxes over
    one line of writing with an ordinary word space between.

    Two questions, and both have to answer yes. **Do they line up** -- the
    perpendicular extents must overlap by `NEAR_PERP` of the smaller, which is
    what says "one line" or "one column" rather than "somewhere nearby". And
    **is the gap small next to the writing**, measured against the shorter
    box's height because that is the size of the letters.

    The two numbers are different because a line of type is not symmetrical.
    Sideways, the gap between two pieces of one line is a WORD SPACE, which is
    a third to a half of a character; down the page it is LEADING, which is
    tighter still relative to the letters. Measured over the chapter on every
    pair that lines up:

        sideways   018#2/#3 at 0.72 of a height, and it is the ONLY sideways
                   pair on 46 pages that lines up at all
        stacked    042#3/#5 at 0.18 -- two lines of one caption -- then the
                   two studio credit blocks on 046 at 0.66, which are two
                   things and must not join, then 024's two ornaments at 0.95

    So the stacked line goes between 0.18 and 0.66 with a margin near 2x
    either way, and the sideways line is fitted on ONE example and that should
    be said plainly. What is not thin about it is the typography: a Korean
    word space runs a third to a half of a character height, so 0.75 is inside
    "one phrase" by construction and two separate texts on one line would have
    to be set closer than any typesetter sets them.
    """
    ax, ay, aw, ah = [int(v) for v in a]
    bx, by, bw, bh = [int(v) for v in b]
    short = max(1, min(ah, bh))
    gx = max(ax, bx) - min(ax + aw, bx + bw)
    gy = max(ay, by) - min(ay + ah, by + bh)
    if gx > 0 and gy <= 0:
        rows = min(ay + ah, by + bh) - max(ay, by)
        return (rows >= NEAR_PERP * short
                and gx <= NEAR_SIDE * short)
    if gy > 0 and gx <= 0:
        cols = min(ax + aw, bx + bw) - max(ax, bx)
        return (cols >= NEAR_PERP * max(1, min(aw, bw))
                and gy <= NEAR_STACK * short)
    return False


def _join_overlapping(regions: list, share: float) -> list:
    """Boxes of one family whose rectangles overlap are one piece of writing.

    lee, with a hand-drawn 쳐벅 in four boxes and a crumb on the end of one
    stroke: *"one sfx split into four boxes"*; and before that, of chapter 1's
    와아아아: the same thing in five. The block head splits a drawn shout at
    the daylight between its strokes, the coverage pass harvests what is left
    as separate marks, and CRAFT adds its own -- three passes that each see
    part of one word and no pass that puts them back together.

    The rule is as blunt as the measurement allows, and the measurement is
    what makes it safe. Over all 46 pages of chapter 8, **21 pairs of boxes
    overlap at all**, and every one of them is either one piece of writing in
    pieces or two boxes over the same piece:

        001#3/4/5/6   와아아아 in four        013#1/2  쿵 in two
        002#1/2       쾅앙 in two             031#3/4  쳐벅
        004#3/4/5     쳉 in three             045#3/4  술렁
        005#2/3/4     쳉 in three             046#5/6  the title logo
        007#4/5       우르릉 in two           017#2/3, 5/6, 7/8  ornaments

    **No two separate texts on the chapter overlap by so much as a pixel.**
    Which is not a surprise once said out loud -- writing is laid out not to
    collide -- but it is the whole justification for a rule this loose, and it
    is why the floor is 0.05 rather than something that sounds careful: the
    two pairs under it (001#8/9, two effects that graze at 0.02; 007#0/2, a
    balloon and an effect at 0.02) are the only ones that must NOT join, and
    they are an order of magnitude below the smallest true pair at 0.07.

    A box that already has a balloon under it is never joined. That one is
    dialogue, `attach_balloons` has said where it sits, and two balloons whose
    rectangles graze are two things said.

    ...and two boxes that do not overlap at all but stand a letter's width
    apart on one line, or a line's leading apart in one column, are the same
    piece of writing too. See `_next_to`.

    **A BOX ONLY CRAFT SAW NEEDS MORE THAN A GRAZE.** The floor above is
    measured on pairs that were already there before anything grew, and
    `_grow_to_the_stroke` runs first and deliberately, so that two clipped
    boxes on one effect grow into each other and come out as one. On lee's
    029 that mechanism runs backwards: a CRAFT core on the balustrade becomes
    a box of its own, grows 5.2x following the dark band down the page, and
    ends up grazing the box over the real 웅성. They join, and the effect's
    box comes out 282x304 across a piece of architecture -- lee: *"029 has a
    sfx green box thats donst exist"*.

    What separates that pair from every pair that must join is not size, not
    colour and not how far the boxes grew -- all three were measured and all
    three put a real pair on the wrong side. It is **provenance**. A region
    CRAFT invented over nothing carries no text mask: no pass that measures
    ink ever saw it, so its rectangle is a guess about a mark, while the
    other box's rectangle sits on a measurement. Over 26 pages of chapter 1
    there are 24 overlapping pairs, and the ten where exactly one side is
    CRAFT's alone are:

        029#6 / the 웅성           0.090   <- the guess, and the only one wrong
        042, 007, 031, 042 x4 ...  0.283 .. 1.000

    Nothing between 0.090 and 0.283, and the nine above the gap include the
    chapter title on 042 and the two balloons on 031. Pairs where BOTH sides
    are CRAFT's alone are untouched by this and still join on `share`: 001's
    fragment at 0.015 and 045's 울렁 at 0.093 both have to.
    """
    if not share:
        return regions
    live = [r for r in regions if r.bubble_mask is None]
    if len(live) < 2:
        return regions
    parent = {id(r): id(r) for r in live}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, a in enumerate(live):
        ax, ay, aw, ah = [int(v) for v in a.bbox]
        for b in live[i + 1:]:
            if _kinds.family_of(a.kind) != _kinds.family_of(b.kind):
                continue
            bx, by, bw, bh = [int(v) for v in b.bbox]
            ox = min(ax + aw, bx + bw) - max(ax, bx)
            oy = min(ay + ah, by + bh) - max(ay, by)
            # Only one of the two was seen by a pass that measures ink, so a
            # graze is not enough -- see the docstring.
            bar = share
            if (a.text_mask is None) != (b.text_mask is None):
                bar = max(share, JOIN_ALONE)
            if not (ox > 0 and oy > 0
                    and ox * oy >= bar * min(aw * ah, bw * bh)) \
                    and not _next_to(a.bbox, b.bbox):
                continue
            ra, rb = find(id(a)), find(id(b))
            if ra != rb:
                parent[rb] = ra

    groups: dict = {}
    for r in live:
        groups.setdefault(find(id(r)), []).append(r)

    gone: set = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        head = max(members, key=lambda q: q.bbox[2] * q.bbox[3])
        x0 = min(int(q.bbox[0]) for q in members)
        y0 = min(int(q.bbox[1]) for q in members)
        x1 = max(int(q.bbox[0]) + int(q.bbox[2]) for q in members)
        y1 = max(int(q.bbox[1]) + int(q.bbox[3]) for q in members)
        head.bbox = (x0, y0, x1 - x0, y1 - y0)
        head.bubble_bbox = head.bbox
        head.src_vertical = (y1 - y0) > (x1 - x0) * 1.15
        # The mask is what Clean paints out, so the other pieces' ink has to
        # come with the rectangle or the join would cover the effect over a
        # mask that only holds a quarter of it.
        masks = [np.asarray(q.text_mask) for q in members
                 if q.text_mask is not None]
        if masks:
            head.text_mask = masks[0].copy()
            for m in masks[1:]:
                head.text_mask = np.maximum(head.text_mask, m)
        gone.update(id(q) for q in members if q is not head)

    return [r for r in regions if id(r) not in gone]


def _sheltered(gray: "np.ndarray", bbox, mask=None) -> bool:
    """Is something drawn round this writing, with paper under or around it?

    The two answers that, agreeing, make a balloon: an enclosure (at the
    gentle thresholds - a thought-circle is drawn fainter than a balloon
    wall) and ground that reads as paper (the margin, or for a plate laid
    over artwork, the floor under the letters). Asked by the promotion, and
    by the shout label as its refusal - a drawn shout never has a wall round
    it.
    """
    from .balloon import _round_wall_around
    if not (_ring_paper(gray, bbox) >= LOOSE_RING
            or _paper_under(gray, bbox, mask) >= UNDER_PAPER):
        return False
    return _round_wall_around(gray, bbox, roundish=False,
                              lo=ENCLOSE_LO, hi=ENCLOSE_HI,
                              seal=ENCLOSE_SEAL)


def _ring_rays(gray: "np.ndarray", bbox) -> float:
    """How much of the margin round a box is drawn strokes.

    lee, of two speech bursts whose golden rays radiate onto a white page:
    *"3 is bubble text but is labbled as outside text"*. A burst's rays are
    open to the page, so no wall ever shuts round them and the demotion read
    the boxes as writing on bare paper. But bare paper is EMPTY, and a
    burst's margin is dense with drawn strokes: measured over every
    freefloat box on the chapter whose margin reads as paper, the two bursts
    score 0.066 and 0.072 edge density and nothing legitimate is over 0.022
    (a studio credit block). `RAYS_DENS` sits between with a margin either
    way.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    m = int(0.5 * max(w, h))
    a0, b0 = max(0, x - m), max(0, y - m)
    a1, b1 = min(W, x + w + m), min(H, y + h + m)
    sub = gray[b0:b1, a0:a1]
    if sub.size == 0:
        return 0.0
    e = cv2.Canny(cv2.GaussianBlur(sub, (3, 3), 0), 30, 90)
    fr = np.ones(sub.shape, bool)
    fr[max(0, y - b0):max(0, y - b0 + h),
       max(0, x - a0):max(0, x - a0 + w)] = False
    return float((e > 0)[fr].mean()) if fr.any() else 0.0


def _ink_chroma(bgr: "np.ndarray", bbox) -> float:
    """How COLOURED the type in this box is.

    lee's 로얀 수틀렉스 on page 055 is a magenta brush title laid across an
    impact flash, and the app called it dialogue. Nothing in the demotion could
    see why not: the flash is bright, its margin is dense with drawn strokes,
    and the floor under the letters is white. Every measurement the demotion
    has asks about the PAPER, and the paper round a title is the same paper as
    round a shout.

    The letters are not. Dialogue on this chapter is set in black, in white, or
    in one grey; the titles and the sound effects are painted. So this asks the
    one question the rest of the demotion never does -- what colour is the
    writing -- and it takes two things to ask it honestly:

    * **Find the glyphs, not the dark pixels.** Otsu inside the box, then keep
      whichever side does NOT own the box's own border, because the ground
      runs to the edges of a box and the letters do not. `_glyph_share`'s flat
      `gray < INK` cannot do this: a white caption on a black plate has no
      dark letters at all. Neither can "keep the smaller side", which is right
      on nearly every real box and wrong on a tight one -- three fat glyphs
      cropped close are most of their own box, and the minority there is the
      paper.
    * **Measure the stroke CORES.** The edge of any letter is a blend of ink
      and ground, so a black glyph on cream paper has a warm rim, and over a
      thin face the rim outnumbers the core. The distance transform picks the
      middle of the stroke at whatever width the stroke happens to be -- which
      a fixed erosion cannot, and eroding twice leaves 35 pixels of a caption
      face to average.

    Chroma in Lab, not saturation in HSV. Black, white and every grey between
    sit at a = b = 128, so neutral type scores zero at any lightness; HSV
    saturation reads 249 for a white-on-black caption plate, because hue means
    nothing near black. Measured over all 212 boxes of the chapter:

        bubble     n=109  median  0.0   p90  1.0
        narration  n= 17  median  2.0   p90  3.2
        freefloat  n= 15  median 19.8   p90 45.1
        sfx        n= 71  median 20.2   p90 42.1
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if (x1 - x0) * (y1 - y0) < CHROMA_MIN_BOX:
        return 0.0
    sub = bgr[y0:y1, x0:x1]
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    _t, dark = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV +
                             cv2.THRESH_OTSU)
    d = dark > 0
    edge = np.zeros(d.shape, bool)
    edge[:CHROMA_FRAME, :] = edge[-CHROMA_FRAME:, :] = True
    edge[:, :CHROMA_FRAME] = edge[:, -CHROMA_FRAME:] = True
    ink = (~d if d[edge].mean() > 0.5 else d).astype(np.uint8)
    if int(ink.sum()) < CHROMA_MIN_INK:
        return 0.0
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    core = dt >= max(1.0, 0.5 * float(np.percentile(dt[ink > 0], 90)))
    if int(core.sum()) < CHROMA_MIN_INK:
        core = ink > 0
    lab = cv2.cvtColor(sub, cv2.COLOR_BGR2LAB)
    a = lab[..., 1].astype(np.float32) - 128.0
    b = lab[..., 2].astype(np.float32) - 128.0
    return float(np.median(np.hypot(a, b)[core]))


def _a_stray_mark(gray: "np.ndarray", bbox, mask=None,
                  fill_under: float = STRAY_FILL) -> bool:
    """Is there a piece of the ARTWORK in this box rather than writing?

    lee, with six screenshots of the ornamental flourishes round a caption
    frame each carrying its own red box: *"a systme that clears out bad boxes
    a pr boxes on art"*.

    What every one of them has in common is not where it sits -- they sit on
    clean paper, which is why every test that asks about the surroundings
    keeps them -- but what is inside it: **one thin swash, alone in a
    rectangle it barely marks.** Writing is not like that. A line of Korean is
    several syllable blocks; a drawn shout is one shape that FILLS its box.
    Neither is one hairline crossing an empty rectangle.

    Two numbers, both measured over all 187 boxes of chapter 8 with the ink
    taken from the detector's own mask:

        marks kept   at most 2 pieces of 25 pixels or more
        fill         under 0.115 of the rectangle

    Eleven boxes are on the wrong side of both, and every one of them was
    cropped and looked at: the six flourishes on 017, the two crumbs left on
    the strokes of 031's 쳐벅, an ornament on 022, a curl on 032 and a piece of
    architecture on 042. **No writing on the chapter is inside the line.** The
    nearest real thing is 004#4, a fragment of 쳉 at 0.116 -- and it is a
    fragment, which is to say `_join_overlapping` has already put it back into
    the box beside it before this is asked.

    What it does NOT catch is worth writing down: a chandelier (008#2, three
    marks at 0.487), a wooden staff (001#2), and the gold embroidery on a
    dress (024#2 and #3, one blob at 0.42-0.48). Those are solid, and by every
    number measured here they are indistinguishable from a drawn effect. They
    need something that knows what a letter is, and this is not it.

    Asked BEFORE the join, and that order is measured -- see the call site.
    """
    x, y, w, h = [int(v) for v in bbox]
    H, W = gray.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if (x1 - x0) * (y1 - y0) < 400:
        return False
    if mask is not None:
        ink = (np.asarray(mask)[y0:y1, x0:x1] > 0).astype(np.uint8)
    else:
        sub = gray[y0:y1, x0:x1]
        dark = (sub < INK).astype(np.uint8)
        light = (sub > 200).astype(np.uint8)
        ink = dark if dark.mean() <= light.mean() else light
    # A box with NOTHING in it is the emptiest case of this rule, not an
    # exception to it. This used to read `return False` and keep it, which
    # never showed while CRAFT was the only second detector -- over lee's
    # whole chapter, all 23 boxes only CRAFT found have ink in them and the
    # median is 33% -- and showed the moment a detector arrived that can put a
    # rectangle on blank paper. Falling through gives the right answer for
    # free: no marks is not more than STRAY_PIECES, and a fill of zero is
    # under any threshold.
    n, _lab, st, _c = cv2.connectedComponentsWithStats(ink, 8)
    marks = sum(1 for i in range(1, n)
                if int(st[i, cv2.CC_STAT_AREA]) >= STRAY_MARK)
    if marks > STRAY_PIECES:
        return False
    fill = float(ink.sum()) / float(max(1, (y1 - y0) * (x1 - x0)))
    return fill < fill_under


def _pieces_and_bands(mask):
    """The components of a box's ink, and those components grouped into row
    bands - the lines of the writing, if it is writing."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(
        (np.asarray(mask) > 0).astype(np.uint8), 8)
    ps = [(int(st[i, 0]), int(st[i, 1]),
           int(st[i, 0]) + int(st[i, 2]), int(st[i, 1]) + int(st[i, 3]),
           int(st[i, 4]), i) for i in range(1, n)
          if int(st[i, 4]) >= STRAY_MARK]
    bands = []
    for p in sorted(ps, key=lambda p: p[1]):
        for b in bands:
            if min(b[3], p[3]) - max(b[1], p[1]) > \
                    0.3 * min(b[3] - b[1], p[3] - p[1]):
                b[0] = min(b[0], p[0]); b[1] = min(b[1], p[1])
                b[2] = max(b[2], p[2]); b[3] = max(b[3], p[3])
                b[4] += p[4]; b[5].extend(p[5:])
                break
        else:
            bands.append([p[0], p[1], p[2], p[3], p[4], [p[5]]])
    return ps, sorted(bands, key=lambda b: b[1]), lab


def _two_texts_in(mask):
    """Are there two separate texts in this one box - and which ink belongs
    to which?

    lee, with three crops of two-lobed balloons each holding two things said
    and each boxed ONCE across both: *"fisrt i want you to come up a system
    that make each text box tehir own box and not merged"*.

    Neither existing split can see these. `_split_clusters` cuts on straight
    empty bands, and its gaps scale with the median piece - which the merged
    multi-character lines of exactly these boxes inflate: 044's pair needs a
    91px cut and the bar computes to 116. And 040's pair cannot be cut by any
    straight band at all: its two texts overlap in rows by 28%.

    What separates them is a fact about typesetting rather than about gaps.
    **A paragraph's lines share their columns.** Two utterances laid into the
    two lobes of one balloon are set on a diagonal - down and across - so the
    two groups share neither rows nor columns. A single text never does that:
    however ragged its lines, they stack.

    Two rules, both measured over every dialogue and outside-text box on the
    46 pages, where they propose exactly the three splits lee pointed at and
    nothing else:

      staircase   a bipartition of the components, in row order, where the
                  two groups overlap at most `DIAG_ROWCOL` of the smaller in
                  BOTH rows and columns. 039 measures -1.35/-0.14 and 040
                  -0.35/0.11; nothing that is one text comes near.
      stacked     an empty row band of at least `STACK_SPLIT` line-heights
                  between two groups of lines. The pairs measure 1.11 to
                  2.85; the widest gap inside any single text on the chapter
                  is 0.50 (a credit block), so 0.8 sits between the
                  populations with a margin either way. This is what catches
                  044, whose top lobe carries a piece of the artwork in its
                  mask and so fails the staircase on columns.

    Both require each side to hold at least `DIAG_BALANCE` of the ink, which
    is what keeps this away from 035's 쿵 - a drawn stroke with droplet marks
    diagonal from it at 2% of the ink. And it is never asked about an sfx
    box at all: 001's 와아아아 is four syllables ON a diagonal, and joining
    those back together was this same session's work.

    Returns (pieces_A, pieces_B, labels) or None.
    """
    ps, bands, lab = _pieces_and_bands(mask)
    if len(ps) < 2:
        return None
    total = sum(p[4] for p in ps)

    idx = sorted(range(len(ps)), key=lambda i: (ps[i][1] + ps[i][3]))
    for k in range(1, len(ps)):
        A = [ps[i] for i in idx[:k]]; B = [ps[i] for i in idx[k:]]
        ay0 = min(p[1] for p in A); ay1 = max(p[3] for p in A)
        by0 = min(p[1] for p in B); by1 = max(p[3] for p in B)
        ax0 = min(p[0] for p in A); ax1 = max(p[2] for p in A)
        bx0 = min(p[0] for p in B); bx1 = max(p[2] for p in B)
        ro = (min(ay1, by1) - max(ay0, by0)) \
            / max(1, min(ay1 - ay0, by1 - by0))
        co = (min(ax1, bx1) - max(ax0, bx0)) \
            / max(1, min(ax1 - ax0, bx1 - bx0))
        ia = sum(p[4] for p in A)
        if ro <= DIAG_ROWCOL and co <= DIAG_ROWCOL \
                and DIAG_BALANCE <= ia / total <= 1 - DIAG_BALANCE:
            return A, B, lab

    if len(bands) >= 2:
        med = float(np.median([b[3] - b[1] for b in bands]))
        for i in range(len(bands) - 1):
            if bands[i + 1][1] - bands[i][3] < STACK_SPLIT * med:
                continue
            ia = sum(b[4] for b in bands[:i + 1])
            if not (DIAG_BALANCE <= ia / total <= 1 - DIAG_BALANCE):
                continue
            A = [p for b in bands[:i + 1] for p in _band_pieces(b, ps)]
            B = [p for b in bands[i + 1:] for p in _band_pieces(b, ps)]
            return A, B, lab
    return None


def _band_pieces(band, ps):
    return [p for p in ps if p[5] in band[5]]


# TWO SOUND EFFECTS IN ONE BOX.
#
# lee, with a box drawn round 와아아아 AND 쾅: *"these 2 clusters shou be thei
# own boxes"*, and the rule he read off the page himself -- *"if there are a
# 2-3 box that are close to eachoter and one that fater away it probably a
# difrent sfx"*.
#
# He is right about the shape, and the numbers say so. Measured over all 49
# sound-effect boxes of a 46-page chapter, taking CRAFT's characters inside
# each box and the gap between neighbours normalised by character size (the
# same normalisation `reach_groups` uses, so big and small effects read on one
# scale): every box that really is ONE effect has neighbour gaps of 0.35 or
# less. Three boxes have a gap of 0.84, 1.26 and 1.75.
#
# **But distance alone splits two of those three wrongly**, which is why there
# is a second condition. Cropped and looked at one at a time:
#
#     001#1  gap 0.84   와아아아 | 쾅              two effects  <- the one to split
#     004#3  gap 1.26   콰앙 | a stray CRAFT box    one effect
#     030#2  gap 1.75   킥킥 | its own trailing ..  one effect
#
# What separates them is not how far the far thing is, it is WHAT it is. In
# 001#1 both sides are writing of comparable size -- 261px against 118px. The
# other two are a speck on empty artwork and a pair of dots. Measured at the
# cut the three come out 0.45, 0.29 and 0.14, so the bar sits at 0.35 with the
# same kind of room either side that the gap bar has.
#
# **This is measured on ONE positive example.** lee: *"do this ill do anther
# chapter later"*. So it is deliberately the conservative shape -- three
# conditions, all of which must hold -- and on the chapter it was measured on
# it makes exactly one change. Widen it when there are more chapters.
SPLIT_GAP = 0.60         # ...against 0.35, the widest gap inside a real effect
SPLIT_ALIKE = 0.35       # ...and the smaller side is at least this much of it
SPLIT_LEAST = 3          # two characters cannot say which of them is the far one


def _cores_in(pieces, bbox) -> list:
    """CRAFT's characters that sit inside this box, as (x0, y0, x1, y1).

    A whisker of slack on each side, because the box is the union of these
    very rectangles and rounding has already put a character a pixel outside
    the box it helped define.
    """
    x, y, w, h = [int(v) for v in bbox]
    out = []
    for q in (pieces or []):
        gx0, gy0, gx1, gy1 = (int(v) for v in q[:4])
        if gx0 >= x - 6 and gx1 <= x + w + 6 \
                and gy0 >= y - 6 and gy1 <= y + h + 6:
            out.append((gx0, gy0, gx1, gy1))
    return out


def _around(cores: list) -> tuple:
    """The box round a group of characters, as (x, y, w, h)."""
    x0 = min(c[0] for c in cores)
    y0 = min(c[1] for c in cores)
    x1 = max(c[2] for c in cores)
    y1 = max(c[3] for c in cores)
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _core_gap(a, b) -> float:
    """The gap between two characters, in units of the smaller one."""
    gx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    gy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    s = min(max(a[2] - a[0], a[3] - a[1]), max(b[2] - b[0], b[3] - b[1]))
    return ((gx * gx + gy * gy) ** 0.5) / max(1, s)


def _widest_link(cores: list):
    """Grow a minimum spanning tree over the characters and hand back its
    longest link, with the two groups that cutting the link would leave.

    A tree, and not a bounding box or a pairwise maximum, because this is
    about a CHAIN: 와아아아 is four characters strung in a row and the two ends
    of that row are far apart. What is really far is the STEP from the row to
    쾅, and only the longest link of a spanning tree is that step.
    """
    n = len(cores)
    if n < 2:
        return None
    seen, rest, edges = {0}, set(range(1, n)), []
    while rest:
        best = min(((_core_gap(cores[i], cores[j]), i, j)
                    for i in seen for j in rest), key=lambda t: t[0])
        edges.append(best)
        seen.add(best[2])
        rest.discard(best[2])
    edges.sort(key=lambda t: t[0])
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    for _g, i, j in edges[:-1]:
        ri, rj = find(i), find(j)
        if ri != rj:
            par[ri] = rj
    side: dict = {}
    for k in range(n):
        side.setdefault(find(k), []).append(k)
    if len(side) != 2:
        return None
    a, b = side.values()
    return edges[-1][0], a, b


def _two_effects_in(cores: list):
    """Is this box two sound effects? If so, the two groups of characters.

    All three conditions, and every one of them has to hold. See the note
    above for what each is worth and what it was measured against.
    """
    if len(cores) < SPLIT_LEAST:
        return None
    got = _widest_link(cores)
    if got is None:
        return None
    gap, a, b = got
    if gap < SPLIT_GAP:
        return None
    big = [max(max(cores[k][2] - cores[k][0], cores[k][3] - cores[k][1])
               for k in side) for side in (a, b)]
    if min(big) < SPLIT_ALIKE * max(big):
        return None                  # a speck or a pair of dots, not an effect
    return a, b


def _each_text_its_own_box(regions: list, skip_sfx: bool = True) -> list:
    """Split every box holding two texts, until none does.

    `skip_sfx` is the manhwa behaviour and the default: there, a painted
    effect's strokes scatter across the artwork and asking whether the box
    holds "two texts" is asking about the drawing. The manga route passes
    False, because a row of three effects painted across one panel comes back
    from comic-text-detector as ONE rectangle -- 008's ガチャ ガチャ ガチャ at
    434px -- and lee: *"teh box merging shou not happen"*.
    """
    out = []
    todo = list(regions)
    while todo:
        r = todo.pop(0)
        if (skip_sfx and _kinds.family_of(r.kind) == "sfx") \
                or r.text_mask is None:
            out.append(r)
            continue
        found = _two_texts_in(r.text_mask)
        if found is None:
            out.append(r)
            continue
        A, B, lab = found
        full = np.asarray(r.text_mask)
        for side in (A, B):
            m = (np.isin(lab, [p[5] for p in side])
                 & (full > 0)).astype(np.uint8) * 255
            ys, xs = np.nonzero(m)
            x0 = max(0, int(xs.min()) - PAD)
            y0 = max(0, int(ys.min()) - PAD)
            x1 = min(full.shape[1] - 1, int(xs.max()) + PAD)
            y1 = min(full.shape[0] - 1, int(ys.max()) + PAD)
            bb = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
            piece = TextRegion(
                id=r.id, bbox=bb, text_mask=m, bubble_mask=None,
                bubble_bbox=bb, kind=r.kind,
                src_vertical=bb[3] > bb[2] * 1.15)
            piece.confidence = getattr(r, "confidence", 0.0)
            todo.append(piece)
    for n, r in enumerate(out):
        r.id = n
    return out


def _drop_duplicates(regions: list) -> list:
    """One piece of writing, one box.

    The block head can return two boxes over the same writing -- its own
    non-maximum suppression compares the rectangles it predicted, and two of
    those can overlap too little to be suppressed while the ink measured inside
    each of them lands in almost exactly the same place. Page 17 came back with
    (782,662,103,248) and (783,663,99,247), and (650,827,106,164) and
    (651,828,105,163): four boxes over two lines of writing. Both copies then
    got read, translated and typeset, one on top of the other.

    The bigger box wins, on the reasoning that the smaller is the same writing
    with an edge clipped off it. Nothing is merged and no rectangle moves.
    """
    keep: list = []
    for r in sorted(regions, key=lambda q: -(q.bbox[2] * q.bbox[3])):
        x, y, w, h = r.bbox
        dup = False
        for k in keep:
            a, b, c, d = k.bbox
            ox = max(0, min(x + w, a + c) - max(x, a))
            oy = max(0, min(y + h, b + d) - max(y, b))
            inter = ox * oy
            if not inter:
                continue
            if inter >= DUP_IOU * (w * h + c * d - inter):
                dup = True
                break
            # ...and TWO PASSES THAT DISAGREE ABOUT ONE PIECE OF INK.
            #
            # This is a different mistake from the one above and IoU cannot
            # see it. Page 032's "황제 디마커스 튜베린" plate came back twice:
            # once from the block head as outside text and once from CRAFT as
            # a sound effect, 79% of the smaller inside the bigger at an IoU
            # of 0.39. Page 001's wooden staff is the same at 0.85 and 0.11.
            # `_join_overlapping` cannot help -- it only ever joins boxes of
            # ONE family, because two families is two answers and joining them
            # would be picking one at random.
            #
            # The size guard is what keeps this away from the case that made
            # `test_a_box_wholly_inside_a_much_bigger_one_is_not_a_duplicate`:
            # a small sound effect really can sit inside a big balloon's
            # rectangle, and that pair is a hundredth of an area apart. The two
            # measured here are 0.13 and 0.55.
            if _kinds.family_of(r.kind) != _kinds.family_of(k.kind) and \
                    inter >= DUP_INSIDE * min(w * h, c * d) and \
                    min(w * h, c * d) >= DUP_UNEVEN * max(w * h, c * d):
                dup = True
                break
        if not dup:
            keep.append(r)
    # Back into the order they were found in, and renumbered without gaps.
    # Keyed on object identity, not `regions.index`: list.index falls back on
    # `==`, and two TextRegions compare field by field until they differ, which
    # on a pair that happens to agree as far as `text_mask` means comparing two
    # numpy arrays and getting "truth value of an array is ambiguous".
    place = {id(r): n for n, r in enumerate(regions)}
    keep.sort(key=lambda q: place[id(q)])
    for n, r in enumerate(keep):
        r.id = n
    return keep


def page_text_mask(img: "np.ndarray", model_path: str,
                   mask_thresh: float = SEG_KEEP) -> "np.ndarray":
    """comic-text-detector's `seg` head alone, as a full-page binary mask.

    Split out of `detect_comictext` unchanged so a different detector can
    borrow it, and it has to be borrowed: `inpaint` skips any region whose
    `text_mask is None`, in three separate places, so a page whose boxes came
    from something that returns rectangles and nothing else would not clean at
    all. This head is the only thing in the app that says WHERE THE INK IS.

    See `dbcoo`, which takes its boxes from two other models and its masks
    from here.
    """
    net = _get_net(model_path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    im_h, im_w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    lb, dw, dh = _letterbox(rgb, INPUT)
    blob = cv2.dnn.blobFromImage(lb, scalefactor=1 / 255.0,
                                 size=(INPUT, INPUT))
    net.setInput(blob)
    outs = net.forward(net.getUnconnectedOutLayersNames())
    maps = [np.asarray(o) for o in outs if np.asarray(o).ndim == 4]
    mask_raw = next((m for m in maps if m.shape[1] == 1),
                    maps[0] if maps else None)
    tmask = np.zeros((im_h, im_w), np.uint8)
    if mask_raw is None:
        return tmask
    m = np.asarray(mask_raw).squeeze()
    if m.ndim != 2:
        return tmask
    if m.max() > 1.5:                    # 0..255 rather than 0..1
        m = m / 255.0
    mm = (m > mask_thresh).astype(np.uint8) * 255
    mm = mm[:INPUT - dh, :INPUT - dw]
    if mm.size:
        tmask = cv2.resize(mm, (im_w, im_h), interpolation=cv2.INTER_NEAREST)
    return tmask


def detect_comictext(page: Page, model_path: str, conf_thresh: float = 0.4,
                     nms_thresh: float = 0.35, mask_thresh: float = SEG_KEEP,
                     split_gap: float = 1.8, split_height: float = 1.8,
                     join_x: float = None, join_y: float = None,
                     craft_x: float = None, craft_y: float = None,
                     craft_cap: float = 0.05, craft_low: float = None,
                     sfx_grow: float = None, sfx_grow_cap: float = 0.12,
                     text_grow: float = None,
                     effect_fill: float = None,
                     loose_bubble: float = None,
                     cover_text: float = None,
                     join_over: float = None,
                     stray_fill: float = None,
                     art_veto: bool = False,
                     fx_chars: int = None,
                     split_texts: bool = False,
                     link_touching: float = None,
                     classify: bool = True,
                     second_opinion: bool = True,
                     bubble_weights: str = "",
                     want_sfx: bool = True
                     ) -> list[TextRegion]:
    net = _get_net(model_path)
    img = page.image
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    im_h, im_w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # THE TWO DETECTORS START TOGETHER.
    #
    # lee: *"if you can spped up teh find text it take a long time, if
    # sspeeding oit up will decrease teh quality than just leave it"*.
    #
    # Profiled over three pages of chapter 8, a page costs 24.6 seconds and
    # **21.3 of them are two neural nets**: 12.0 in CRAFT and 9.3 in the block
    # head. Everything this file measures itself -- the harvest, the balloons,
    # the walls, the grow, the kinds -- is the other 3.3.
    #
    # So there is nothing to shave off the measuring, and the only honest
    # saving is that THE TWO NETS DO NOT NEED EACH OTHER. CRAFT is handed the
    # page and nothing else; the block head is handed the page and nothing
    # else; the first line that needs both is the coverage pass, hundreds of
    # lines below. Started together they overlap, and a page costs the slower
    # of the two rather than the sum -- about 40% on a machine with a core to
    # spare, and nothing at all on one without, which is the sandbox this was
    # measured in.
    #
    # It cannot change an answer. Same page in, same weights, same code, same
    # boxes out; all that moves is when the work happens. Both nets release
    # the interpreter while they compute, which is what makes the overlap real
    # rather than two things taking turns.
    # ...AND ONLY IF ANYBODY ASKED FOR SOUND EFFECTS.
    #
    # lee: *"i also want to make it so that if sfx are not selectd to be
    # detected craft shoud not run"*. He is asking for the largest saving
    # available anywhere in Find text and it is free: CRAFT is **93% of the
    # run**, everything it contributes is a sound effect -- `merge_into`
    # builds its regions with `kind="sfx"` and nothing else -- and
    # `only_kinds` was throwing every one of them away afterwards. Eight
    # seconds a page spent finding boxes that were then binned.
    #
    # The three ticks in the dialog steer the measuring detectors and used to
    # walk straight past this one, because comic-text-detector reads the whole
    # page whatever is ticked and CRAFT was hung off the format rather than
    # off the choice.
    # WHERE THE SECONDS GO, said out loud once a page.
    #
    # lee: *"ctd is taking 50 second per page, i timmed it"*, against 4.7 on
    # the chapter measured here. A number nobody can break down is a number
    # nobody can act on, so the run reports its own split rather than being
    # argued about: the net, the wait on CRAFT, and everything after.
    _t0 = _time.time()
    craft_job = None
    # `craft_low` is CRAFT's `low_text`, its floor for "this pixel is in a
    # letter"; None leaves CRAFT its own, which was set on printed type. The
    # webtoon route lowers it for painted sounds - see `webtoon.CRAFT_LOW`.
    knobs = {"low_text": craft_low} if craft_low is not None else {}
    if craft_x and craft_y and want_sfx:
        from . import craft as _craft
        if _craft.available():
            craft_job = _POOL.submit(_craft.pieces, img, **knobs)

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    lb, dw, dh = _letterbox(rgb, INPUT)
    blob = cv2.dnn.blobFromImage(lb, scalefactor=1 / 255.0, size=(INPUT, INPUT))
    net.setInput(blob)
    outs = net.forward(net.getUnconnectedOutLayersNames())

    # The model returns (blocks, mask, lines). Blocks are 3-D (1,N,5+nc); the
    # 4-D maps are the mask and the line map - OpenCV sometimes reverses those,
    # so the 1-channel one is the text mask.
    blks = next((o for o in outs if np.asarray(o).ndim == 3), None)
    maps = [np.asarray(o) for o in outs if np.asarray(o).ndim == 4]
    mask_raw = None
    for m in maps:
        if m.shape[1] == 1:
            mask_raw = m
            break
    if mask_raw is None and maps:
        mask_raw = maps[0]

    # text segmentation mask -> full-page binary mask
    tmask = np.zeros((im_h, im_w), np.uint8)
    if mask_raw is not None:
        m = np.asarray(mask_raw).squeeze()
        if m.ndim == 2:
            if m.max() > 1.5:            # 0..255 rather than 0..1
                m = m / 255.0
            mm = (m > mask_thresh).astype(np.uint8) * 255
            mm = mm[:INPUT - dh, :INPUT - dw]
            if mm.size:
                tmask = cv2.resize(mm, (im_w, im_h),
                                   interpolation=cv2.INTER_NEAREST)

    # ...and the page keeps it. `detect_ctd_sfx` needs this exact mask to
    # cut its sound-effect regions out of, and computing it there means
    # running this net twice on one page -- 2.29s of the 9.44 the route was
    # costing, for an answer that was already in this variable.
    try:
        page.seg_mask = tmask
    except Exception:
        pass

    rr_x = im_w / max(1, (INPUT - dw))
    rr_y = im_h / max(1, (INPUT - dh))

    regions: list[TextRegion] = []
    # Which regions the BLOCK head produced, as identities. The second
    # detector is not allowed to overrule these -- see `craft.merge_into`.
    from_block: set = set()
    # ...and which the COVERAGE pass produced, which is a different
    # question: those are the ones it calls `sfx` on sight.
    from_cover: set = set()
    rid = 0
    claimed = np.zeros((im_h, im_w), bool)   # what the block head has boxed
    for x1, y1, x2, y2, cf in _decode_blocks(blks, conf_thresh, nms_thresh):
        X1 = max(0, int(x1 * rr_x)); Y1 = max(0, int(y1 * rr_y))
        X2 = min(im_w - 1, int(x2 * rr_x)); Y2 = min(im_h - 1, int(y2 * rr_y))
        if X2 - X1 < 4 or Y2 - Y1 < 4:
            continue
        claimed[Y1:Y2 + 1, X1:X2 + 1] = True
        boxsel = np.zeros((im_h, im_w), bool)
        boxsel[Y1:Y2 + 1, X1:X2 + 1] = True
        text = (tmask > 0) & boxsel
        if int(text.sum()) < 20:         # mask missed it - fall back to ink
            text = (gray <= INK) & boxsel
        if int(text.sum()) < 20:
            continue
        # One block can hold two separate texts with a big gap between them -
        # give each its own box.
        block_regions: list[TextRegion] = []
        for cluster in _split_clusters(text.astype(np.uint8),
                                       gap_mult=split_gap,
                                       height_mult=split_height):
            ys, xs = np.nonzero(cluster)
            if xs.size < 20:
                continue
            bx0 = max(0, int(xs.min()) - PAD); by0 = max(0, int(ys.min()) - PAD)
            bx1 = min(im_w - 1, int(xs.max()) + PAD)
            by1 = min(im_h - 1, int(ys.max()) + PAD)
            bb = (bx0, by0, bx1 - bx0 + 1, by1 - by0 + 1)
            glyph = (cluster.astype(np.uint8) * 255)
            tw, th = bx1 - bx0, by1 - by0
            kind = _classify_kind(gray, (bx0, by0, bx1, by1)) if classify \
                else "bubble"
            r = TextRegion(id=rid, bbox=bb, text_mask=glyph, bubble_mask=None,
                           bubble_bbox=bb, kind=kind,
                           src_vertical=th > tw * 1.15)
            r.confidence = round(float(cf), 3)
            block_regions.append(r)
            rid += 1
        # Nothing is linked here any more.
        #
        # This used to link every box a single detected block split into, on
        # the theory that a run of text broken up by the clusterer is still one
        # run. Sometimes it is. Just as often the block is one balloon holding
        # two things said, and the two cases look identical in ink: lee's
        # hot-spring balloon holds よく見てください and a separate remark beside
        # it, and it was linked, so the long English was typeset into the short
        # line's column.
        #
        # A link is not a small thing to be wrong about. It tells the reader
        # neither half may complete the sentence, it tells the translator to
        # split one English sentence between them, and it makes the typesetter
        # re-cut the balloon by English length. Guessing it from pixels is
        # guessing at grammar from the shape of the paper.
        #
        # So the question is asked where it can be answered: after Read text,
        # off the words, by `translate.link_sections`. A person can still link
        # anything to anything with L, and splitting a box by hand still links
        # the pieces - that one is not a guess, it is somebody saying so.
        regions.extend(block_regions)
        from_block.update(id(r) for r in block_regions)

    # The second detector's marks, fetched here rather than further down
    # because the coverage pass below wants a second opinion before it keeps a
    # box, and asking CRAFT twice for the same page would double what it costs.
    # ...and this is where the two come back together. Started at the top of
    # the run, collected here, which is the first line that needs both.
    _t_net = _time.time()
    craft_pieces = craft_job.result() if craft_job is not None else None
    _t_craft = _time.time()

    # Everything the block head never boxed. The box comes straight off the
    # mask -- re-measuring it from the ink was tried and made it worse: on
    # page 8 the はら box grew from (729,26,86,261) to (709,0,126,342), taking
    # in the balloon edge and the girl's hair, and on page 13 the ぽん box slid
    # off the writing and onto the birdcage below it. The mask is already a
    # measurement of exactly where the writing is, so it is used as one, and it
    # doubles as the text mask the cleaner paints out.
    for (x0, y0, x1, y1), sub, ink in _harvest(
            tmask, claimed, near_x=join_x, near_y=join_y):
        if second_opinion and craft_pieces is not None and \
                not _seen_by(craft_pieces, x0, y0, x1, y1):
            continue
        glyph = np.zeros((im_h, im_w), np.uint8)
        glyph[y0:y1 + 1, x0:x1 + 1] = sub
        bx0 = max(0, x0 - PAD); by0 = max(0, y0 - PAD)
        bx1 = min(im_w - 1, x1 + PAD); by1 = min(im_h - 1, y1 + PAD)
        bb = (bx0, by0, bx1 - bx0 + 1, by1 - by0 + 1)
        # Writing the block head cannot see is writing that is not set in a
        # block: hand-drawn typesetting laid over the artwork. Calling it sfx
        # keeps it out of the balloon fitter and lets it be set at the angle it
        # was drawn at; the AI judge relabels it if it disagrees. _classify_kind
        # is asked only about the one case it can settle from the page -- a
        # caption boxed off by a printed rule -- because its other answer,
        # "bright all round, so a balloon", is meaningless out here: a sound
        # effect drawn over pale artwork is bright all round too, which is why
        # it called all six of page 13's sound effects bubbles.
        kind = "sfx"
        if classify and _classify_kind(gray, (bx0, by0, bx1, by1)) == \
                "narration":
            kind = "narration"
        tw, th = bx1 - bx0, by1 - by0
        cover = TextRegion(
            id=rid, bbox=bb, text_mask=glyph, bubble_mask=None,
            bubble_bbox=bb, kind=kind, src_vertical=th > tw * 1.15)
        regions.append(cover)
        from_cover.add(id(cover))
        rid += 1

    # ------------------------------------------------- the second detector
    #
    # Everything above comes from ONE model's two heads, and on a Korean
    # webtoon both go blank on the same thing: coloured brush-drawn shapes laid
    # over artwork. Page 026 of chapter 227 is eight 하아 in red across a blue
    # panel and the block head returns nothing at any confidence while the mask
    # holds 0.04% of the page. `detect/craft.py` has the measurement.
    #
    # So on the formats where that happens, and only there, a second detector
    # supplies marks the mask never had. It adds regions and it grows
    # half-found ones; it never overrules the block head, which is still the
    # best thing here at dialogue. Off unless the format asks for it, and off
    # if easyocr is not installed.
    if craft_pieces is not None:
        from . import craft as _craft
        groups = _craft.group(craft_pieces, craft_x, craft_y)
        for gx0, gy0, gx1, gy1 in _craft.merge_into(
                regions, from_block, groups, im_w, im_h, craft_cap,
                pad=PAD):
            bb = (gx0, gy0, gx1 - gx0, gy1 - gy0)
            regions.append(TextRegion(
                id=rid, bbox=bb, text_mask=None, bubble_mask=None,
                bubble_bbox=bb, kind="sfx",
                src_vertical=(gy1 - gy0) > (gx1 - gx0) * 1.15))
            rid += 1

    # A sound effect is a drawn shape and the box came off something that was
    # only ever looking for writing, so it clips. Widen each one to the strokes
    # it already holds most of. See `_grow_to_the_stroke` -- and note this runs
    # BEFORE `_drop_duplicates`, because two clipped boxes on one effect can
    # grow into each other and the pair should then come out as one box.
    #
    # ...AND THE SAME FOR THE PRINTED TYPE, at a much higher bar.
    #
    # lee, with a screenshot of one balloon: *"can you make it so taht the whole
    # text is detected"*. The box was 009.png#1 of his own chapter, round
    # "마탑의 주인이시자 / 불멸의 대마법사이자—", and the em dash ran out through
    # the right-hand edge. Measured on the page: the dash and the 자 before it
    # are ONE ink component of 226 pixels and the box holds 208 of them. **92%
    # inside, 9 pixels out.** Not a new kind of failure -- the one this function
    # was written for, on a box it was not allowed near.
    #
    # 0.70 rather than the effects' 0.40, and no extra `pad`: the box already
    # carries PAD, and printed type does not have strokes that leave it. Over
    # lee's chapter that moves 2 of 39 dialogue boxes -- his, by the 9 pixels of
    # the dash, and one other by a pixel. Over chapter 8, which has far more
    # hand-drawn writing the block head calls dialogue, 29 of 114 move, median
    # 1.09x, and all 16 of the biggest were cropped and looked at: none leaves
    # the balloon it started in.
    for r in regions:
        share = sfx_grow if r.kind == "sfx" else text_grow
        if not share:
            continue
        bb, mask = _grow_to_the_stroke(gray, r.bbox, share, sfx_grow_cap,
                                       pad=PAD if r.kind == "sfx" else 0)
        if mask is None:
            continue
        r.bbox = bb
        r.bubble_bbox = bb
        r.src_vertical = bb[3] > bb[2] * 1.15
        # The mask doubles as what the cleaner paints out, so the rest of the
        # stroke has to go into it too -- a box that covers the effect over a
        # mask that does not would leave the tail of it on the page. It is what
        # makes lee's dash actually disappear rather than merely be inside the
        # rectangle.
        if r.text_mask is not None:
            r.text_mask = np.maximum(np.asarray(r.text_mask), mask)

    # One piece of writing, one box.
    #
    # THE EMPTY BOXES GO FIRST, and the order was measured rather than
    # reasoned. Joining first looked obviously right -- put the fragments back
    # together, then ask which boxes are empty -- and on page 017 it is
    # exactly wrong: the six ornamental flourishes round one caption frame sit
    # in three overlapping PAIRS, each pair joins into a rectangle that is no
    # longer empty, and two of the six survive a rule that catches all six
    # when it is asked first.
    #
    # The thing that would argue the other way is a real fragment thin enough
    # to be swept up before the join can rescue it, and on 46 pages there is
    # none: every box under `stray_fill` with at most `STRAY_PIECES` marks is
    # artwork, and the nearest real fragment -- 004#4, a piece of 쳉 -- is at
    # 0.116, on the far side of the line by a thousandth. That margin is thin
    # and is the reason to keep watching this, not a reason to reorder it.
    if stray_fill:
        regions = [r for r in regions
                   if not _a_stray_mark(gray, r.bbox, r.text_mask, stray_fill)]
    regions = _join_overlapping(regions, join_over)
    regions = _drop_duplicates(regions)
    if split_texts:
        regions = _each_text_its_own_box(regions)

    # This model reports TEXT, so every region above has no balloon and the
    # fitter would be handed the footprint of the Japanese - a tall narrow
    # column - to lay horizontal English out in. Find the balloon each block
    # sits in so the English can use the whole of it.
    from .balloon import attach_balloons
    attach_balloons(gray, regions)

    # ...and the balloons INK CANNOT FIND, which is a different question.
    #
    # lee, three screenshots side by side: *"how are these bubble text ? and
    # these grey bubble are not"*. Everything above works from ink -- a
    # balloon is found when a dark outline separates its inside from the page
    # -- and page 050's balloons are flat grey with no outline, overlapping
    # the bright panels above and below. Nothing lies between the balloon and
    # the panel, so they run together, the blob fails every shape test, and
    # the region comes out with the box round its writing and the word
    # `freefloat` on it. No threshold reaches a boundary that is not there.
    #
    # `comicbubble` is a model that knows what a balloon looks like without
    # asking for an outline. It runs AFTER the measurement and only ever adds:
    # a region that already has a mask keeps it, because that mask is a
    # reading of this page and this is a guess about comics in general. Off
    # unless the weights are on disk, so a machine that has not downloaded
    # them finds a chapter exactly as it did before.
    cb_boxes = None
    if bubble_weights:
        from . import comicbubble as _CB
        # ONE forward pass, read twice: the balloons here, and the WORD on each
        # box at the very end of this function, after every measured rule has
        # had its say.
        cb_boxes = _CB.look(img, bubble_weights)
        _CB.name_the_balloons(img, regions, bubble_weights, boxes=cb_boxes)

    # A box called DIALOGUE with no balloon anywhere near it is not dialogue.
    #
    # lee, of the three hand-lettered lines on the sky beside a real balloon:
    # *"the first one shoud be outside etx"*. He is right and the reason is
    # exact: `_classify_kind` asks whether the margin round the box is mostly
    # brighter than 200, and a pale blue morning answers 0.555 -- brighter than
    # paper's bar, so the box is called dialogue before anything has looked for
    # a balloon.
    #
    # By this point something HAS looked. Three things have to agree before the
    # word is taken away, and on all 44 pages of chapter 1 they only ever agree
    # about that one box:
    #
    #   no balloon mask   `attach_balloons` found nothing under it. On its own
    #                     this is not enough -- 035's other box is inside a
    #                     balloon far bigger than its own text and the fitter
    #                     misses it too.
    #   no closed wall    and neither does `_round_wall_around`, which is what
    #                     rescues a grey balloon drawn on a starfield.
    #   the margin is not paper   the last one, and the one that separates the
    #                     two boxes on that page: the balloon's lining reads
    #                     251, the sky reads 205.
    #
    # MEASURED, chapter 1, 89 dialogue and caption boxes: 84 have a balloon
    # mask; of the five left, one has a wall; of the remaining four, two are
    # title cards already called `narration` and out of scope, and the last two
    # are 035's, split 205 against 251. **One box moves, and it is his.**
    #
    # Two other readings were measured first and BOTH POINT THE WRONG WAY, so
    # nobody should reach for them again:
    #
    #   ring flatness   "paper is flat, sky is not" -- the sky's margin varies
    #                   LESS (37) than 70 of the 89 dialogue boxes, because a
    #                   balloon's margin holds its own black outline and the
    #                   artwork past it.
    #   the wall alone  it fires on the sky text, off the balloon edge and the
    #                   clouds, and does NOT fire on the real balloon whose
    #                   inside runs past the search window.
    #
    # AND THE SAME BOX MAY BE AN EFFECT RATHER THAN OUTSIDE TEXT.
    #
    # lee, of 부스럭 brushed across a white bedsheet and boxed as dialogue:
    # *"the second on shod be sfx"*. Its margin is a bedsheet and reads 249, so
    # the margin test above says paper and it is right -- there IS paper all
    # round it. What gives it away is the writing: no balloon, thin ink (0.271,
    # under the effects line), and characters **0.223 of the page wide**. The
    # next biggest characters in any balloon on the chapter are 0.120 and the
    # studio credits on the last page are 0.015, so nothing else on 70 pages
    # comes near it. All three, and the size is what keeps the credits -- which
    # are thinner-inked than 부웅 -- out of it.
    demoted: set = set()
    if loose_bubble:
        from .balloon import _round_wall_around
        for r in regions:
            if r.kind != "bubble" or r.bubble_mask is not None:
                continue
            if _round_wall_around(gray, r.bbox):
                continue
            if effect_fill and \
                    _glyph_share(gray, r.bbox, r.text_mask) >= LOOSE_HUGE and \
                    _looks_hand_drawn(gray, r.bbox, r.text_mask, effect_fill):
                r.kind = "sfx"
                continue
            # PAPER IS NOT A BALLOON.
            #
            # lee, of "이것이 제가 / 인내한 대가입니까?" set on a bare white page
            # at the end of the chapter, boxed red: *"i think this box is using
            # teh edge of the pannel to make it a bubble tetx it shoud ever do
            # that"*, and of the studio credits under it: *"outside etxt beigng
            # detected as inside box"*.
            #
            # He has the mechanism exactly right. Both tests below ask about
            # TONE -- is the margin bright, is the floor bright -- and a page
            # with nothing drawn on it answers 255 to both. So the emptier the
            # page, the more certain this was that the writing was in a
            # balloon. On chapter 8 that is 046#0, #2 and #3 at 255/255, and
            # the six ornamental flourishes on 017 at 254/253.
            #
            # A balloon is not bright paper. A balloon is bright paper WITH
            # SOMETHING DRAWN ROUND IT, and the wall test above already knows
            # how to look for that -- it was only ever refusing these because
            # it also insists the wall be round, which a caption plate is not.
            # So the tone tests keep their say and keep their numbers, and they
            # are asked second, after something has been found to enclose the
            # writing at all.
            #
            # Measured over chapter 8's 33 no-balloon dialogue boxes: seven
            # stay dialogue (a balloon, two grey panels, two ruled captions, a
            # black plate, a gold 어쩜 that should have been an effect anyway),
            # and 26 become outside text -- lee's three, the six flourishes,
            # 크크 / 쳐벅 / 옹성 / 씨익, and the captions typeset straight onto
            # the paper. The cost is three boxes inside white BURSTS (042#0,
            # 042#2, 044#0): a burst's rays are open to the page, nothing shuts
            # round them, and they come back outside text. That is a colour on
            # a box and one click, against writing that was being called
            # dialogue because the page under it was blank.
            if _ring_paper(gray, r.bbox) >= loose_bubble:
                if _round_wall_around(gray, r.bbox, roundish=False,
                                      lo=ENCLOSE_LO, hi=ENCLOSE_HI,
                                      seal=ENCLOSE_SEAL):
                    continue
                # ...or a BURST's rays. A burst is open to the page, so no
                # wall ever shuts round one -- but its margin is dense with
                # drawn strokes where bare paper is empty. See `_ring_rays`.
                #
                # ...unless the LETTERING IS PAINTED. lee's 로얀 수틀렉스 is a
                # magenta brush title laid across an impact flash, and a flash
                # is speed lines: 0.053 of margin density against the 0.04
                # bar, so this escape took it. Nothing that reads the ground
                # can separate a flash from a burst -- both are bright with
                # strokes all round -- and nothing has to, because the writing
                # inside them is not the same writing. See `_ink_chroma`.
                if _ring_rays(gray, r.bbox) >= RAYS_DENS \
                        and _ink_chroma(img, r.bbox) < INK_CHROMA:
                    continue
            # ...and the paper it is printed on, which is the second opinion
            # page 048 needs: its margin is rays and its floor is the burst.
            #
            # Untouched, and the shape of the change is why. This one is only
            # ever reached when the margin is NOT paper, so what it finds is a
            # bright patch that ENDS -- writing standing on a plate laid over
            # artwork, which is a thing drawn round the writing even when no
            # closed line is. lee's boxes are 255 outside and 255 underneath
            # and never get here -- which is what the `elif` is for, and it is
            # not a tidying. Reached unconditionally it rescues every one of
            # them: 046#0 measures 255 under the letters as well as round
            # them, because there is nothing on that page but the letters.
            #
            # The same veto as the rays: a bright floor under painted letters
            # is the white core of a flash, not a plate. 로얀 measures 248
            # here, which is how it stayed dialogue with the rays escape shut
            # as well -- it needed both doors closed.
            elif _paper_under(gray, r.bbox, r.text_mask) >= UNDER_PAPER \
                    and _ink_chroma(img, r.bbox) < INK_CHROMA:
                continue
            r.kind = "freefloat"
            demoted.add(id(r))

        # ...and the same question the other way round: OUTSIDE TEXT that is
        # enclosed and standing on paper is dialogue.
        #
        # lee, of the "황제 디마커스 튜베린" plate and of the caption in the
        # ornate frame: *"8 shoud be bubble text ... 3 is bubble text"*. Both
        # came from `_classify_kind` as outside text -- the plate because its
        # margin is a dark sleeve and red drapery, the caption because the
        # demotion above had no enclosure test when it was written -- and no
        # rule anywhere promoted a free-floating box into a bubble on the
        # strength of the thing drawn round it.
        #
        # The same two answers the demotion asks for, agreeing the other way:
        # something is drawn round this writing, AND the ground it stands on
        # is paper (the margin for the caption at 255; the floor for the
        # plate, whose margin reads 210 but whose plate reads 228). Measured
        # over every free-floating box on the chapter, exactly two are
        # enclosed-and-on-paper -- his two. The bursts, the credits, the
        # captions on bare paper and the effects all fail the enclosure, and
        # the embroidery that IS enclosed (024#3, ring 26) fails the paper.
        for r in regions:
            if r.kind != "freefloat" or r.bubble_mask is not None \
                    or id(r) in demoted:
                continue
            if _sheltered(gray, r.bbox, r.text_mask):
                r.kind = "bubble"

    # ...and last of all, the outside-text boxes that are really drawn effects.
    #
    # LAST is the point. It runs after `attach_balloons`, so a box the wall
    # test rescued into a grey balloon is dialogue by then and is never asked
    # this question at all -- which is exactly lee's *"boubble text shoud not
    # be considered"*. Every promotion above takes precedence over this
    # demotion, and on a manhwa an sfx label means the box is dropped, so
    # anything that narrows the population here is a box that stays on his
    # page. See `_looks_hand_drawn` for what the number is and what it costs.
    #
    # ...and a TALL one, which is the other way a drawn shape gives itself away.
    #
    # lee, of 앙 painted over the dragon's fire: *"the trird shoud be sfx"*. Its
    # ink is not thin -- 0.354, well over the line, because the character is a
    # fat brushed shape -- but its box is 211 wide by 268 tall. Korean runs
    # along a line, so a run of writing out on the artwork is WIDE: the other
    # four outside-text boxes on the chapter measure 0.26, 0.43, 0.63 and 0.76
    # of their width in height, and this one measures 1.27. One drawn character
    # standing on its own is the only thing out here that is taller than it is
    # wide.
    #
    # Thin evidence and it is worth saying so: five boxes, one of them tall. It
    # is safe in the sense that costs are asymmetric only if outside text stays
    # horizontal, which is true of Korean and Chinese webtoons and is NOT true
    # of Japanese manga -- which is why this, like everything round it, is off
    # unless the format asks.
    #
    # A DEMOTED BOX IS NEVER ASKED THIS. The block head called it dialogue, and
    # that head was trained on printed comic type and is excellent at it; the
    # demotion above only changes where the box SITS, not what is written in
    # it. Asked anyway, page 048's "어린 나이에 / 해외 유명 대학교에서 / 여러 개의
    # 박사 학위를 딴 / 천재!" -- four lines of set type inside a spiky white
    # burst over dark trousers -- fills 0.262 of its box, goes under the
    # effects line and is DROPPED off the page. lee: *"the fitrst picture is
    # not being detected"*. That is this, and it is the interaction the fill
    # number was never measured against: 0.28 was measured on the boxes the
    # block head calls outside text, and the demotion adds boxes to that
    # population which it was not measured on.
    #
    # (A demoted box can still become an effect -- 부스럭 does -- but by the
    # branch above, which asks for characters 0.15 of the page wide as well as
    # thin ink. Set type never is.)
    if effect_fill:
        for r in regions:
            if r.kind != "freefloat" or id(r) in demoted:
                continue
            if _looks_hand_drawn(gray, r.bbox, r.text_mask, effect_fill) or \
                    _taller_than_wide(r.bbox):
                r.kind = "sfx"

    # ...and the other direction: WRITING THE BLOCK HEAD MISSED.
    #
    # The coverage pass calls everything it finds `sfx` on sight -- writing that
    # head cannot see is usually a drawn shout, and that has been right for a
    # long time. But on a manhwa an sfx box is DROPPED, so when it is wrong the
    # writing is gone off the page with no box to delete or rename.
    #
    # lee, of "진 빠진다, 진 빠져" laid on a bedroom floor: *"we lost this it use
    # to be outside texxt and now it not maerk"*. Nothing about the labelling
    # rules changed it. He re-cut the chapter from 70 pages to 71, the block
    # head stopped seeing that writing on the new cut, and it came back through
    # the coverage pass instead -- and so was dropped.
    #
    # So the coverage boxes are asked the same three questions the effects rule
    # asks, and a box that answers no to all of them is writing:
    #
    #   thin ink      under `cover_text` of its box -- a hollow outlined shout.
    #                 0.25 and not the 0.28 above, because the two populations
    #                 are not the same and the cost is not the same: out here a
    #                 wrong answer deletes a box the block head already failed
    #                 to find.
    #   taller than wide
    #   big characters   over `COVER_CHAR` of the page. This is what carries it:
    #                 진 빠진다 measures 0.051 and 달칵 on the next page measures
    #                 0.109, and every drawn effect on the chapter tail is above
    #                 the line.
    #
    # MEASURED over 17 pages, 17 coverage boxes: **exactly one moves**, and it
    # is his. 부스럭, 파, 앙, 달칵, 훅 and the rest all stay sound effects.
    #
    # Thin evidence, and it should be said plainly: two numbers fitted with one
    # positive example. What is not thin is the direction -- when this rule is
    # wrong lee gets a box to delete, and when the old behaviour was wrong he
    # got nothing at all.
    if cover_text:
        for r in regions:
            if r.kind != "sfx" or id(r) not in from_cover:
                continue
            if _looks_hand_drawn(gray, r.bbox, r.text_mask, cover_text) or \
                    _taller_than_wide(r.bbox) or \
                    _glyph_share(gray, r.bbox, r.text_mask) >= COVER_CHAR:
                continue
            r.kind = "freefloat"

    # ------------------------------ what the second detector can see in a box
    #
    # Two questions that need CRAFT's marks AND the balloons -- and asked
    # after every older rule has had its say, which was measured rather than
    # preferred: `cover_text`'s three proxies read 029's 옹성 at a glyph share
    # of 0.097 against a bar of 0.10 and handed the shout back as outside
    # text after the count had already answered. The count is the better
    # informed of the two, so it speaks last.
    #
    # A BOX WITH NO CHARACTERS IN IT IS NOT A BOX OF WRITING.
    #
    # lee: *"a systme that clears out bad boxes a pr boxes on art"*, with a
    # chandelier, a wooden staff and the gold embroidery on a dress each
    # carrying a box. `_a_stray_mark` cannot touch those -- they are solid,
    # and by every number measured on the page they are a drawn effect.
    #
    # `test_is_there_writing_in_it.py` already wrote down why, on the other
    # half of this same job: **six cheap ways of telling writing from drawing
    # were measured on 36 boxes and not one of them separates.** What does is
    # asking something trained on writing, and CRAFT is already here and
    # already paid for. It has been vetoing the COVERAGE pass on exactly this
    # basis since then.
    #
    # What is new is that it now vetoes the BLOCK HEAD too, which that file
    # forbade in as many words -- "the second detector is not allowed to
    # overrule these". The reason it forbade it was that the block head is
    # excellent at printed comic type, and it is; but the boxes lee is
    # complaining about are the ones it drew, and the measurement is one-sided
    # enough to say so. Over 46 pages, 109 boxes that survive to be shown:
    #
    #     008#2 the chandelier    CRAFT sees 0 characters
    #     017#2 an ornament       0
    #     024#2 embroidery        0
    #     024#3 embroidery        0
    #     034#1 a lone "!"        0  -- and it is in a BALLOON
    #     everything else        1 or more
    #
    # So the veto is narrowed by the one thing that separates the exception:
    # a box `attach_balloons` put inside a balloon is dialogue and is never
    # asked. Nothing else on the chapter has nothing in it.
    #
    # ...AND A BOX WITH ONE OR TWO CHARACTERS FILLING IT IS A DRAWN EFFECT.
    #
    # lee: *"a bunch of sfx are being detected as other boxes"* -- 크크, 저벅,
    # 어쩜, 옹성 twice, 쳐벅, 옹성 again and 씨익, all boxed as dialogue or
    # outside text. `_classify_kind` has never had an sfx answer to give
    # (see `claude/nothing-asks-if-it-is-a-sound-effect`), and the fill test
    # cannot be asked here: 023's real caption fills 0.256 and 크크 fills
    # 0.267, so a line drawn between them deletes writing.
    #
    # CRAFT counts CHARACTERS, and that is the thing these eight have in
    # common: one or two of them, big enough to fill the box. Measured over
    # the same 109 boxes, every box outside a balloon holding at most
    # `fx_chars` characters is one of the eight, and every one of the eight is
    # in it -- coverage 0.335 to 0.728 against a floor of `FX_COVER`. The
    # boxes that come closest to it are "아니." and "이런.", two-syllable
    # lines that would be caught by the count alone; both are inside balloons
    # and never asked.
    #
    # ON MANHWA AN SFX LABEL DELETES THE BOX, so this is the expensive
    # direction and the bar is lee's: the most aggressive line with zero false
    # positives. Two of the eight were only reachable at all because
    # `_next_to` had already put "3년 전…" and 042's two caption lines back
    # together first -- unjoined, both look like two-character boxes.
    if craft_pieces is not None and (art_veto or fx_chars):
        kept = []
        for r in regions:
            if r.bubble_mask is not None:
                kept.append(r)
                continue
            n, cover, med_h = _characters_in(craft_pieces, r.bbox)
            if art_veto and n == 0:
                continue
            if fx_chars and n <= fx_chars and cover >= FX_COVER \
                    and _kinds.family_of(r.kind) != "sfx" \
                    and not _sheltered(gray, r.bbox, r.text_mask):
                # ...unless something is drawn round it and it stands on
                # paper. lee, of 어쩜… inside a pale drawn circle: *"1 missed
                # this one text"* -- two characters filling their box measure
                # exactly like a shout, and the label deleted it from the
                # page. What a shout never has is a wall round it: of the
                # nine boxes this rule catches on the chapter, 어쩜 is the
                # only one enclosed, and it is the only one that is speech.
                r.kind = "sfx"
            # ...and the same count read the other way round. lee: *"missinga
            # lot of text detection on teh last one"* -- and nothing on that
            # page is missing. Its title plate and its pink caption were both
            # boxed, called sfx by the coverage pass, and dropped by
            # `detectable_kinds`. CRAFT sees FIFTEEN characters in one and six
            # in the other, at a median height of 0.072 of the page width;
            # every real drawn effect on 46 pages carries at most five. Many
            # small characters is a body of writing whatever pass boxed it.
            #
            # The COUNT carries this -- the nearest effect is 004#3's
            # 쳉-in-pieces at five characters, so the line sits between 5 and
            # 6 with no crowd on either side. The height gate is a backstop
            # against a giant six-syllable shout, and it was 0.09 for a day
            # before lee's chapter TITLE ("일당백으로...", thirteen display
            # characters at 0.113 of the page) failed it and stayed dropped.
            # The real shouts run 0.21-0.66; 0.15 keeps the backstop without
            # pricing out display type.
            elif fx_chars and _kinds.family_of(r.kind) == "sfx" \
                    and n >= SFX_TEXT_CHARS and med_h <= SFX_TEXT_H * im_w:
                r.kind = "freefloat"
            kept.append(r)
        if len(kept) != len(regions):
            regions = kept
            for n, r in enumerate(regions):
                r.id = n

        # THE WHOLE OF THE WRITING, one more time, for the boxes the late
        # passes built. lee, of the chapter title: *"on 2 the text is not
        # being fully encased"*. Its box is the union of CRAFT's character
        # rectangles, and CRAFT hugs the glyph cores -- the white contour of
        # outlined display type runs a few pixels past every one. The main
        # grow ran long before this box existed, so it is asked once more,
        # for every box without a balloon, at the same shares and the same
        # cap. Asked BEFORE the shave, and the order is measured: grown
        # after it, 041's boxes follow the sword's ink straight back to their
        # pre-shave rectangles. Grown first, the grow may take whatever it
        # holds enough of and the shave has the last word about the artwork.
        for r in regions:
            if r.bubble_mask is not None:
                continue
            share = sfx_grow if _kinds.family_of(r.kind) == "sfx" \
                else text_grow
            if not share:
                continue
            bb, gmask = _grow_to_the_stroke(
                gray, r.bbox, share, sfx_grow_cap,
                pad=PAD if _kinds.family_of(r.kind) == "sfx" else 0)
            if gmask is None:
                continue
            r.bbox = bb
            r.bubble_bbox = bb
            r.src_vertical = bb[3] > bb[2] * 1.15
            if r.text_mask is not None:
                r.text_mask = np.maximum(np.asarray(r.text_mask), gmask)

        # THE BOX OF A WRITING REGION IS THE WRITING.
        #
        # lee, of the rescued boxes: *"2 these boxes are way bigger than the
        # text"* and *"5 is passed teh the tetx"*. He is right about why,
        # too: those boxes came off the coverage mask, and the mask swallowed
        # the sword the caption is printed over and the artwork beside the
        # shout -- ink that is CONNECTED to the writing's ink, so no
        # component split can take it back out. What can is the second
        # detector: keep only the mask within a margin of the characters it
        # sees, when what falls outside includes a single blob bigger than
        # any legitimate fringe. Measured over every writing box on the
        # chapter: the junk blobs run 2,267-23,619 pixels (a sword blade, a
        # hilt, an emblem, a wall of drapery) and the biggest legitimate
        # fringe -- a pillar edge grazing a caption -- is 1,048.
        for r in regions:
            if r.bubble_mask is not None or r.text_mask is None \
                    or _kinds.family_of(r.kind) == "sfx":
                continue
            x, y, w, h = [int(v) for v in r.bbox]
            m = np.asarray(r.text_mask)
            near = np.zeros(m.shape, bool)
            hit = False
            for px0, py0, px1, py1 in craft_pieces:
                if px1 < x or px0 > x + w or py1 < y or py0 > y + h:
                    continue
                hit = True
                near[max(0, py0 - SHAVE_NEAR):py1 + SHAVE_NEAR,
                     max(0, px0 - SHAVE_NEAR):px1 + SHAVE_NEAR] = True
            if not hit:
                continue
            outside = ((m > 0) & ~near).astype(np.uint8)
            if not outside.any():
                continue
            nb, _lab, st, _c = cv2.connectedComponentsWithStats(outside, 8)
            if max((int(st[i, cv2.CC_STAT_AREA]) for i in range(1, nb)),
                   default=0) < SHAVE_BLOB:
                continue
            m = np.where(near, m, 0).astype(m.dtype)
            ys, xs = np.nonzero(m)
            if xs.size < 20:
                continue
            r.text_mask = m
            x0 = max(0, int(xs.min()) - PAD)
            y0 = max(0, int(ys.min()) - PAD)
            x1 = min(m.shape[1] - 1, int(xs.max()) + PAD)
            y1 = min(m.shape[0] - 1, int(ys.max()) + PAD)
            r.bbox = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
            r.bubble_bbox = r.bbox
            r.src_vertical = r.bbox[3] > r.bbox[2] * 1.15

        # ...and one more pass of the join, now that every kind is settled.
        #
        # The first join ran before the balloons and the census, which is
        # where it must run -- but it judges "same family" on the kinds of
        # that moment, and the census can change them. lee's chapter title is
        # the measured case: half of it arrived as a CRAFT addition (born
        # sfx) and half as a block fragment (classified outside text), the
        # two overlap by 0.60, and the census then called BOTH writing --
        # one piece of writing, two boxes, exactly what the join exists to
        # mend. Boxes with balloons under them are never joined, so the
        # split-balloon halves stay put.
        regions = _join_overlapping(regions, join_over)
        for n, r in enumerate(regions):
            r.id = n

        # ...and one sound-effect box holding TWO effects comes apart. See
        # `_two_effects_in` for the three conditions and what each was
        # measured against.
        #
        # AFTER the last join, deliberately: a join is what puts the two
        # halves of ONE effect back together, and a split running before it
        # would be undone by the very next line. After the census too, so the
        # kind read here is the settled one and not the coverage pass's first
        # guess.
        if craft_pieces is not None:
            fresh = []
            for r in regions:
                two = None
                if _kinds.family_of(r.kind) == "sfx":
                    cores = _cores_in(craft_pieces, r.bbox)
                    got = _two_effects_in(cores)
                    if got is not None:
                        two = [_around([cores[k] for k in side])
                               for side in got]
                if two is None:
                    fresh.append(r)
                    continue
                for bb in two:
                    part = copy.copy(r)
                    part.bbox = bb
                    part.bubble_mask = None
                    part.bubble_bbox = bb
                    part.polygon = None
                    part.src_vertical = bb[3] > bb[2] * 1.15
                    fresh.append(part)
            if len(fresh) != len(regions):
                regions = fresh
                for n, r in enumerate(regions):
                    r.id = n

    # THE FRAME A CAPTION SITS IN IS ITS BALLOON.
    #
    # lee, with arrows pushing a title plate's box out to its ornate frame:
    # *"i wnat you to do this for the box detecton because i thing teh deisgn
    # on teh box is making teh box not be detected"*. He is right about the
    # cause. The balloon fitter wants an enclosed run of PAPER -- flat, bright,
    # no drawn edges -- and a decorated plate fails every part of that: its
    # interior is an emblem, a glow, a sunset. So the writing kept a box the
    # size of the writing and the English was typeset into that, inside a
    # frame with three times the room.
    #
    # The enclosure question already knows better. If something is drawn shut
    # round the writing and the fitter found nothing, the room inside that
    # wall is the balloon -- decorated or not. The interior comes back from
    # the wall test itself, so the shape typeset into is the shape the artist
    # drew, and it persists the way every balloon does, as its outline.
    #
    # Never when two boxes share the enclosure: whose room it is is the
    # split-balloon divider's question, and handing both boxes the whole
    # frame would typeset them on top of each other.
    if loose_bubble:
        wants = [r for r in regions
                 if r.bubble_mask is None and r.text_mask is not None
                 and _kinds.family_of(r.kind) != "sfx"]
        got = []
        for r in wants:
            found = _round_wall_around(gray, r.bbox, roundish=False,
                                       lo=ENCLOSE_LO, hi=ENCLOSE_HI,
                                       seal=ENCLOSE_SEAL, bounds=True)
            # Only a real (interior, rect) answer counts. The wall test
            # returns None for "no frame" -- and a test double that answers
            # the yes/no question with a plain bool must read as "no frame"
            # here, not as something to unpack.
            if isinstance(found, tuple):
                got.append((r, found))
        for r, (interior, fb) in got:
            shared = False
            for q, (qi, qb) in got:
                if q is r:
                    continue
                ox = min(fb[0] + fb[2], qb[0] + qb[2]) - max(fb[0], qb[0])
                oy = min(fb[1] + fb[3], qb[1] + qb[3]) - max(fb[1], qb[1])
                if ox > 0 and oy > 0 and \
                        ox * oy > 0.5 * min(fb[2] * fb[3], qb[2] * qb[3]):
                    shared = True
                    break
            if shared:
                continue
            r.bubble_mask = interior
            r.bubble_bbox = tuple(int(v) for v in fb)
            cs, _ = cv2.findContours((interior > 0).astype(np.uint8),
                                     cv2.RETR_EXTERNAL,
                                     cv2.CHAIN_APPROX_SIMPLE)
            if cs:
                big = max(cs, key=cv2.contourArea)
                r.polygon = [[int(a), int(b)] for a, b in big.reshape(-1, 2)]

    # ...and LAST of all, the two lobes of one balloon become one box pair.
    #
    # Last because it reads `kind`, and every rule above can still change one.
    # lee: *"it shoud only be bubble text and only be bubbles"* - both of those
    # are decided by the time the run gets here.
    # ...and LAST of all but one, what each box IS.
    #
    # Every rule above decides dialogue-versus-outside-text by measuring the
    # paper -- the margin's brightness, a closed wall, a balloon mask -- and
    # those proxies lie in two places lee has reported all day: a caption on a
    # pale empty page reads as inside a balloon, and a balloon on a dark panel
    # reads as outside. The model was told which was which on eleven thousand
    # comic pages instead of inferring it.
    #
    # It runs after the measuring, not instead of it: on 133 of 139 boxes the
    # two agree, and where they do not this is the one that was right on every
    # box that was looked at. It only ever changes the WORD -- never a corner,
    # never a sound effect, never a sub-type somebody chose.
    if bubble_weights and cb_boxes:
        from . import comicbubble as _CB
        _CB.name_the_kinds(img, regions, bubble_weights, boxes=cb_boxes)

    if link_touching:
        _BL.link_touching_bubbles(gray, regions, link_touching)

    # CRAFT is started at the top and collected in the middle, so its cost is
    # the WAIT - what the block head could not hide. On the first page of a
    # run that wait carries the weight load too, which is why page one always
    # reads far worse than the rest and why an average over one page is not a
    # measurement.
    _say_timing(page, _t0, _t_net, _t_craft, len(regions),
                craft_job is not None)
    return regions
