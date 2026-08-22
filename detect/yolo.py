"""Detector backed by a pretrained YOLO model.

No training required. Several people have already trained speech-bubble
detectors on thousands of manga pages and published the weights; download one
and point at it. They run on CPU at roughly a second a page, and they catch
what the classical detector cannot: burst bubbles, bubbles over dark art,
borderless dialogue, and irregular shapes.

Known weights (download the .pt file and pass its path):

  ogkalu/comic-speech-bubble-detector-yolov8m
      Detection boxes. Trained on ~8k manga, webtoon, manhua and western
      pages. Handles the extreme aspect ratios common in webtoons.

  kitsumed/yolov8m_seg-speech-bubble
      Segmentation masks rather than boxes, so outlines come out shaped
      rather than rectangular. Edges are somewhat wavy.

  ogkalu/comic-text-segmenter-yolov8m
      Segments the TEXT rather than the bubble. Useful as a second pass for
      free-floating dialogue and sound effects outside any bubble.

Most predict a single class, which is fine: this module takes the bubble from
the model and derives the text mask from the ink inside it, exactly as the
classical detector does.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

from ..models import Page, TextRegion

INK = 128
TEXT_PAD = 8            # breathing room around the text so the box never clips it
_models: dict = {}

KNOWN = {
    "bubble-box": "ogkalu/comic-speech-bubble-detector-yolov8m",
    "bubble-seg": "kitsumed/yolov8m_seg-speech-bubble",
    "text-seg": "ogkalu/comic-text-segmenter-yolov8m",
}


def get_model(weights: str):
    """Load and cache a YOLO model. `weights` is a path to a .pt file."""
    if weights not in _models:
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise RuntimeError(
                "the YOLO detector needs ultralytics: pip install ultralytics"
            ) from e
        if not os.path.isfile(weights):
            raise FileNotFoundError(
                f"model weights not found: {weights}. "
                f"Download one of: {', '.join(KNOWN.values())}"
            )
        _models[weights] = YOLO(weights)
    return _models[weights]


def _mask_from_result(res, i: int, W: int, H: int):
    """Segmentation mask if the model produces one, otherwise the filled box."""
    masks = getattr(res, "masks", None)
    if masks is not None:
        m = masks.data[i].cpu().numpy()
        m = (m > 0.5).astype(np.uint8)
        if m.shape != (H, W):
            m = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
        return m * 255
    boxes = getattr(res, "boxes", None)
    if boxes is not None:
        x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().astype(int)
        m = np.zeros((H, W), np.uint8)
        m[max(0, y1):min(H, y2), max(0, x1):min(W, x2)] = 255
        return m
    return None


def _region_from_mask(gray, mask, rid: int, kind: str = "bubble"):
    """Build a region: the model supplies the bubble, the ink supplies the text."""
    if mask is None or not mask.any():
        return None
    glyph = ((gray <= INK) & (mask > 0)).astype(np.uint8) * 255
    ys, xs = np.nonzero(glyph)
    if xs.size < 20:
        return None                      # an empty bubble, nothing to translate

    H, W = gray.shape
    tx0 = max(0, int(xs.min()) - TEXT_PAD); tx1 = min(W - 1, int(xs.max()) + TEXT_PAD)
    ty0 = max(0, int(ys.min()) - TEXT_PAD); ty1 = min(H - 1, int(ys.max()) + TEXT_PAD)
    tw, th = tx1 - tx0 + 1, ty1 - ty0 + 1

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    outer = max(cnts, key=cv2.contourArea)

    # The DRAWN box hugs the text, not the whole balloon - so the region sits on
    # the words like a caption box. The bubble shape is still kept as the mask
    # (and polygon), so typesetting can still fill the whole balloon at typeset.
    return TextRegion(
        id=rid, bbox=(tx0, ty0, tw, th), text_mask=glyph, bubble_mask=mask,
        bubble_bbox=(tx0, ty0, tw, th),
        polygon=outer.reshape(-1, 2).tolist(),
        kind=kind, src_vertical=th > tw * 1.15,
    )


def detect(page: Page, weights: str, conf: float = 0.30,
           kind: str = "bubble", imgsz: int = 1024) -> list[TextRegion]:
    model = get_model(weights)
    img = page.image
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    res = model.predict(img, conf=conf, imgsz=imgsz, retina_masks=True,
                        verbose=False)[0]
    boxes = getattr(res, "boxes", None)
    n = 0 if boxes is None else len(boxes)

    out, rid = [], 0
    for i in range(n):
        r = _region_from_mask(gray, _mask_from_result(res, i, W, H), rid, kind)
        if r is not None:
            out.append(r)
            rid += 1
    return out


def _area(b) -> int:
    return max(1, int(b[2])) * max(1, int(b[3]))


def _containment(inner, outer) -> float:
    """Fraction of `inner`'s area that falls inside `outer`."""
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    x = max(0, min(ix + iw, ox + ow) - max(ix, ox))
    y = max(0, min(iy + ih, oy + oh) - max(iy, oy))
    return (x * y) / _area(inner)


def _looks_like_text(region: TextRegion) -> bool:
    """Reject artwork the text model grabbed by mistake - a face, hair, a solid
    black shape. Typesetting is built from THIN strokes, so the thickest point of
    real text is small relative to the block; a filled blob is not.
    """
    m = region.text_mask
    if m is None or not m.any():
        return True
    ink = (m > 0).astype(np.uint8)
    if int(ink.sum()) < 20:
        return False
    thick = float(cv2.distanceTransform(ink, cv2.DIST_L2, 3).max()) * 2.0
    _, _, w, h = region.bbox
    return thick <= 0.45 * min(w, h) + 10


def _dedup_overlap(regions: list[TextRegion], cover: float = 0.85,
                   iou: float = 0.6) -> list[TextRegion]:
    """Drop only TRUE duplicate detections, keeping genuinely separate bubbles.

    Two boxes over the same bubble - a text box almost entirely inside its own
    bubble, or a bubble outlined twice (an outer ring and its inner white) -
    are duplicates and one is removed. Two DIFFERENT bubbles that merely touch
    or overlap (a sentence split across two adjacent bubbles) are NOT: they only
    partly cover each other, so they both survive and can be linked instead.
    Thresholds are deliberately high. Double-READING of any residual overlap is
    prevented separately, in OCR, by assigning each glyph to one region. Run
    AFTER drop_parents so real panels are already gone and are not swallowed.
    """
    from .classical import _iou as iou_of
    order = sorted(range(len(regions)),
                   key=lambda i: -_area(regions[i].bubble_bbox))
    keep, boxes = [], []
    for i in order:
        b = regions[i].bubble_bbox
        if any(_containment(b, kb) >= cover or iou_of(b, kb) >= iou
               for kb in boxes):
            continue
        keep.append(regions[i])
        boxes.append(b)
    return keep


def _separate_overlaps(regions: list[TextRegion], gray: np.ndarray
                       ) -> list[TextRegion]:
    """Reshape overlapping regions so no two cover the same text.

    Where regions' ink overlaps, each glyph blob is given WHOLE to the region
    whose centre is nearest, then every region that took part in an overlap is
    shrunk to hug only the text it kept - its drawn box included. Two bubbles
    can still sit side by side, but no glyph and no box is shared, so nothing is
    read or shown twice. Regions emptied out are dropped. Regions that never
    overlapped anything are left exactly as they were.
    """
    regs = [r for r in regions if r.text_mask is not None]
    if len(regs) < 2:
        return regions

    def _box(r):
        return r.bubble_bbox or r.bbox

    def _boxes_touch(a, b) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return (min(ax + aw, bx + bw) - max(ax, bx) > 0 and
                min(ay + ah, by + bh) - max(ay, by) > 0)

    # Pairs of regions whose DRAWN boxes overlap. These are the ones that were
    # sitting on top of each other - usually one line the artist split across
    # touching balloons - so they get separated AND linked together.
    pairs = [(j, k)
             for j in range(len(regs)) for k in range(j + 1, len(regs))
             if _boxes_touch(_box(regs[j]), _box(regs[k]))]
    involved = {j for pr in pairs for j in pr}
    if not involved:
        return regions                       # no boxes overlap - leave it be

    H, W = gray.shape[:2]
    owner = np.full((H, W), -1, np.int32)
    cover = np.zeros((H, W), np.uint16)
    union = np.zeros((H, W), np.uint8)
    for j, r in enumerate(regs):
        ink = r.text_mask > 0
        owner[ink] = j
        cover[ink] += 1
        union[ink] = 255

    # Where ink is claimed by more than one region, give each shared pixel to
    # the nearest region centre, then snap whole glyph blobs to their majority
    # owner so a glyph is never split down the middle.
    dbl = cover > 1
    if dbl.any():
        ys, xs = np.nonzero(dbl)
        C = np.array([[r.cx, r.cy] for r in regs], np.float32)
        P = np.stack([xs, ys], 1).astype(np.float32)
        memb = np.stack([(r.text_mask[ys, xs] > 0) for r in regs], 1)
        d = ((P[:, None, :] - C[None, :, :]) ** 2).sum(2)
        d[~memb] = np.inf
        owner[ys, xs] = d.argmin(1).astype(np.int32)
        n, lab = cv2.connectedComponents(union, 8)
        ink_idx = union > 0
        counts = np.zeros((max(n, 1), len(regs)), np.int32)
        np.add.at(counts, (lab[ink_idx], owner[ink_idx]), 1)
        maj = counts.argmax(1)
        owner = np.where(lab > 0, maj[lab], -1)

    # Reshape every overlapping region to hug ONLY the text it owns, so the
    # drawn boxes pull apart. Regions with no boxes overlapping keep their
    # original bubble shape untouched.
    survived = set()
    kept = []
    for j, r in enumerate(regs):
        if j in involved:
            mine = owner == j
            if int(mine.sum()) < 20:
                continue                     # reassigned away entirely - drop
            r.text_mask = (mine.astype(np.uint8) * 255)
            yy, xx = np.nonzero(mine)
            x0 = max(0, int(xx.min()) - TEXT_PAD)
            y0 = max(0, int(yy.min()) - TEXT_PAD)
            x1 = min(W - 1, int(xx.max()) + TEXT_PAD)
            y1 = min(H - 1, int(yy.max()) + TEXT_PAD)
            bb = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
            r.bbox = bb
            r.bubble_bbox = bb               # the drawn box now hugs its own text
            r.bubble_mask = None
            r.polygon = None
        survived.add(j)
        kept.append(r)

    # Auto-link: regions that overlapped each other are one continuous line.
    # Union the overlapping pairs into groups and give each surviving group of
    # two-or-more a shared link id (translated as a single flowing sentence).
    parent = list(range(len(regs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    comp: dict = {}
    for j in survived:
        comp.setdefault(find(j), []).append(j)
    g = 0
    for members in comp.values():
        if len(members) < 2:
            continue
        g += 1
        for j in members:
            regs[j].link = g

    return kept + [r for r in regions if r.text_mask is None]


def _auto_link_balloons(regions: list[TextRegion]) -> None:
    """Link bubbles whose BALLOONS overlap - one line split across touching
    balloons. Text boxes are tight now and rarely overlap, so linking keys off
    the balloon shape (the bubble mask) instead. Merges into any existing links.
    """
    bub = [r for r in regions if r.bubble_mask is not None]
    if len(bub) < 2:
        return
    bxs = []
    for r in bub:
        ys, xs = np.nonzero(r.bubble_mask > 0)
        bxs.append(None if xs.size == 0
                   else (int(xs.min()), int(ys.min()),
                         int(xs.max()), int(ys.max())))
    parent = list(range(len(bub)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(bub)):
        if bxs[a] is None:
            continue
        ax0, ay0, ax1, ay1 = bxs[a]
        for b in range(a + 1, len(bub)):
            if bxs[b] is None:
                continue
            bx0, by0, bx1, by1 = bxs[b]
            if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
                continue                         # balloon boxes disjoint
            if bool(((bub[a].bubble_mask > 0) & (bub[b].bubble_mask > 0)).any()):
                parent[find(a)] = find(b)

    comp: dict = {}
    for i in range(len(bub)):
        comp.setdefault(find(i), []).append(i)
    nextg = 1 + max([int(getattr(r, "link", 0) or 0) for r in regions] + [0])
    for members in comp.values():
        if len(members) < 2:
            continue
        existing = [bub[i].link for i in members if getattr(bub[i], "link", 0)]
        g = min(existing) if existing else nextg
        if not existing:
            nextg += 1
        for i in members:
            bub[i].link = g


def detect_hybrid(page: Page, weights: str, conf: float = 0.30,
                  text_weights: str = "") -> list[TextRegion]:
    """Model first, classical for whatever it missed.

    The two fail differently: the model finds oddly-shaped and borderless
    bubbles the heuristics cannot, while the heuristics still catch faint or
    unusual cases the model was not trained on. The union costs one extra pass
    and loses nothing.
    """
    from .classical import _iou, detect_combined, drop_parents

    gray = (cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
            if page.image.ndim == 3 else page.image)
    H, W = gray.shape[:2]

    bubbles = detect(page, weights, conf)
    # Merge duplicate detections of the SAME balloon here, while the boxes still
    # cover the whole balloon - two detections of one bubble overlap heavily and
    # collapse to one, so one balloon yields one box (and can't split into two
    # overlapping text boxes later). Genuinely separate balloons overlap less and
    # survive.
    bubbles = _dedup_overlap(bubbles)

    # The text segmenter finds the actual words. Its page-wide mask lets each
    # bubble's box shrink to hug the text inside it (the balloon still supplies
    # the typesetting mask), and whatever text falls OUTSIDE every bubble becomes
    # its own free-floating region.
    text_regs = (detect(page, text_weights, conf, kind="freefloat")
                 if text_weights else [])
    tmask = np.zeros((H, W), np.uint8)
    for t in text_regs:
        src = t.bubble_mask if t.bubble_mask is not None else t.text_mask
        if src is not None:
            tmask[src > 0] = 255

    out = []
    claimed = np.zeros((H, W), np.uint8)
    for b in bubbles:
        if text_regs and b.bubble_mask is not None:
            seg = (tmask > 0) & (b.bubble_mask > 0)
            if int(seg.sum()) >= 20:
                area = cv2.dilate(seg.astype(np.uint8),
                                  np.ones((5, 5), np.uint8)) > 0
                ink = (gray <= INK) & area & (b.bubble_mask > 0)
                use = ink if int(ink.sum()) >= 20 else seg
                ys, xs = np.nonzero(use)
                x0 = max(0, int(xs.min()) - TEXT_PAD)
                y0 = max(0, int(ys.min()) - TEXT_PAD)
                x1 = min(W - 1, int(xs.max()) + TEXT_PAD)
                y1 = min(H - 1, int(ys.max()) + TEXT_PAD)
                bb = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
                b.text_mask = (use.astype(np.uint8) * 255)
                b.bbox = bb
                b.bubble_bbox = bb                # box now hugs the text
                claimed[seg] = 255
        out.append(b)
    taken = [r.bubble_bbox for r in out]

    # Free text the segmenter found outside every bubble.
    for t in text_regs:
        src = t.bubble_mask if t.bubble_mask is not None else t.text_mask
        if src is None or int((src > 0).sum()) == 0:
            continue
        if float((claimed[src > 0] > 0).mean()) > 0.5:
            continue                              # already inside a bubble
        if not _looks_like_text(t):
            continue
        out.append(t)
        taken.append(t.bubble_bbox)

    for r in detect_combined(page):
        if all(_iou(r.bubble_bbox, t) < 0.35 for t in taken):
            out.append(r)
            taken.append(r.bubble_bbox)

    out = drop_parents(out)
    out = _dedup_overlap(out)            # remove true duplicate detections
    gray = (cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
            if page.image.ndim == 3 else page.image)
    out = _separate_overlaps(out, gray)  # split remaining overlaps: no shared text
    _auto_link_balloons(out)             # link bubbles whose balloons overlap
    for i, r in enumerate(out):
        r.id = i
    return out
