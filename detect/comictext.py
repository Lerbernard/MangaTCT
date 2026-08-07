"""Manga/comic text-block detection via dmMaze's comic-text-detector.

This runs the model's ONNX export with OpenCV's DNN module and reads its two
useful outputs directly: the YOLO text-BLOCK boxes and the text segmentation
mask. Text is detected DIRECTLY and already grouped into blocks by the model,
so none of the bubble-detect / dedup / separate / merge heuristics are needed —
each block is a tight, non-overlapping TextRegion.

Deliberately dependency-light: OpenCV + numpy only (no torch, shapely or
pyclipper), so it installs cleanly anywhere the rest of the app already runs.
The DBNet "lines" output is ignored; the block boxes plus the mask are enough
to build regions.

Model: `comictextdetector.pt.onnx` from the manga-image-translator releases
(beta-0.2.1). Point the detector's model-path setting at that file.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

from ..models import Page, TextRegion

INPUT = 1024            # the size the model was exported at
PAD = 8                 # breathing room around each block so nothing clips
INK = 128

_nets: dict = {}


def _get_net(path: str):
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(
            "comic-text-detector model not found: "
            f"{path!r}. Download comictextdetector.pt.onnx from the "
            "manga-image-translator beta-0.2.1 release and point the "
            "detector model path at it.")
    if path not in _nets:
        _nets[path] = cv2.dnn.readNetFromONNX(path)
    return _nets[path]


def _letterbox(im: np.ndarray, new: int = INPUT):
    """Resize keeping aspect, pad bottom/right to a square — matches the
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
    """Longest run of (near) empty entries in a 1-D projection — the widest
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
    """Recursive XY-cut. An empty ROW band (a VERTICAL gap — the "height"
    control) splits when it is >= `vgap`; an empty COLUMN band (a horizontal
    gap — the "distance" control) splits when it is >= `hgap`. Either can fire;
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


def _blob_split(ink: np.ndarray, gap: int) -> list[np.ndarray]:
    """Separate ink into blobs by bridging gaps up to `gap`; anything farther
    apart than that becomes its own blob. Catches groups that are separated
    diagonally or irregularly, where a straight XY-cut finds no clean band."""
    k = max(3, int(gap))
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
    parts = []
    for blob in _blob_split(ink, hgap):            # distance separation
        parts += _xycut(blob, vgap, hgap, tol)     # + straight-band separation
    parts = [p for p in parts if int(p.sum()) >= 20]
    parts = _merge_columns(parts)                  # undo splits of one bubble
    return parts if len(parts) >= 2 else [ink]


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


def _classify_kind(gray: "np.ndarray", box: tuple) -> str:
    """Best-effort guess at a block's role from the art around it — for the
    'box type' label only. It never moves, resizes, adds or drops a box; it
    just sets kind.

    Text wrapped in a bright, enclosed shape is dialogue ('bubble'); if that
    shape is a clean rectangle it's a caption ('narration'); text on open
    artwork is 'freefloat' (outside text). Conservative — when unsure it
    returns 'bubble', and every box stays one click from a manual fix."""
    H, W = gray.shape
    X1, Y1, X2, Y2 = box
    bw = max(1, X2 - X1); bh = max(1, Y2 - Y1)

    # freefloat: the margin around the text is mostly dark artwork, not paper —
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

    # narration: a bordered caption box — a straight dark rule line hugging 3+
    # sides of the box. (On white pages a balloon's interior merges with the
    # page, so shape tests fail; the drawn border is the reliable tell.)
    pad = 6
    def _darkfrac(strip):
        return float((strip <= 90).mean()) if strip.size else 0.0
    sides = [
        _darkfrac(gray[max(0, Y1 - pad):Y1, X1:X2]),          # top
        _darkfrac(gray[Y2:min(H, Y2 + pad), X1:X2]),          # bottom
        _darkfrac(gray[Y1:Y2, max(0, X1 - pad):X1]),          # left
        _darkfrac(gray[Y1:Y2, X2:min(W, X2 + pad)]),          # right
    ]
    if sum(1 for s in sides if s > 0.5) >= 3:
        return "narration"
    return "bubble"


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


def _harvest(tmask: np.ndarray, claimed: np.ndarray):
    """Group the writing the block head left behind.

    Two marks belong together when the gap between them is small next to the
    SMALLER of the two -- deliberately not next to the group they would make.
    An earlier version measured the gap against the merged box, which grows
    every time something joins it, and on page 13 that snowballed until one
    group covered the whole page (39,60)-(863,1320). Holding the reach to each
    mark's own size keeps a tall sound effect from reaching across a panel to
    pull in a small one, and a speck can never reach anything at all.
    """
    P, lab = _pieces((tmask > 0) & ~claimed)
    par = list(range(len(P)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    for i in range(len(P)):
        for j in range(i + 1, len(P)):
            a, b = P[i], P[j]
            gx = max(0, max(a['x0'], b['x0']) - min(a['x1'], b['x1']))
            gy = max(0, max(a['y0'], b['y0']) - min(a['y1'], b['y1']))
            if (gx * gx + gy * gy) ** 0.5 <= LEFT_NEAR * min(a['sz'], b['sz']):
                ra, rb = find(i), find(j)
                if ra != rb:
                    par[ra] = rb
    bunches: dict = {}
    for i, piece in enumerate(P):
        bunches.setdefault(find(i), []).append(piece)

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


def detect_comictext(page: Page, model_path: str, conf_thresh: float = 0.4,
                     nms_thresh: float = 0.35, mask_thresh: float = SEG_KEEP,
                     split_gap: float = 1.8, split_height: float = 1.8,
                     classify: bool = True
                     ) -> list[TextRegion]:
    net = _get_net(model_path)
    img = page.image
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    im_h, im_w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    lb, dw, dh = _letterbox(rgb, INPUT)
    blob = cv2.dnn.blobFromImage(lb, scalefactor=1 / 255.0, size=(INPUT, INPUT))
    net.setInput(blob)
    outs = net.forward(net.getUnconnectedOutLayersNames())

    # The model returns (blocks, mask, lines). Blocks are 3-D (1,N,5+nc); the
    # 4-D maps are the mask and the line map — OpenCV sometimes reverses those,
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

    rr_x = im_w / max(1, (INPUT - dw))
    rr_y = im_h / max(1, (INPUT - dh))

    regions: list[TextRegion] = []
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
        if int(text.sum()) < 20:         # mask missed it — fall back to ink
            text = (gray <= INK) & boxsel
        if int(text.sum()) < 20:
            continue
        # One block can hold two separate texts with a big gap between them —
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

    # Everything the block head never boxed. The box comes straight off the
    # mask -- re-measuring it from the ink was tried and made it worse: on
    # page 8 the はら box grew from (729,26,86,261) to (709,0,126,342), taking
    # in the balloon edge and the girl's hair, and on page 13 the ぽん box slid
    # off the writing and onto the birdcage below it. The mask is already a
    # measurement of exactly where the writing is, so it is used as one, and it
    # doubles as the text mask the cleaner paints out.
    for (x0, y0, x1, y1), sub, ink in _harvest(tmask, claimed):
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
        regions.append(TextRegion(
            id=rid, bbox=bb, text_mask=glyph, bubble_mask=None,
            bubble_bbox=bb, kind=kind, src_vertical=th > tw * 1.15))
        rid += 1

    regions = _drop_duplicates(regions)

    # This model reports TEXT, so every region above has no balloon and the
    # fitter would be handed the footprint of the Japanese — a tall narrow
    # column — to lay horizontal English out in. Find the balloon each block
    # sits in so the English can use the whole of it.
    from .balloon import attach_balloons
    attach_balloons(gray, regions)
    return regions
