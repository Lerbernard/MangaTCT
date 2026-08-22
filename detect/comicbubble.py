"""A balloon finder that does not care what colour the balloon is.

Why there is one
----------------

lee, with three screenshots side by side -- two shouts on an ice panel boxed
red, a sound effect boxed red, and two grey speech balloons boxed green:
*"how are these bubble text ? and these grey bubble are not"*.

He is pointing at an inversion, and the mechanism is exact. Everything this
package knows about balloons it works out from INK. `balloon._free_labels`
dilates every pixel under 128 and calls what is left "paper", so a balloon is
found when a dark outline separates its inside from the page behind it. On
page 050 the balloons are flat grey with **no outline at all**, and they
overlap the bright panels above and below them. There is no ink between the
balloon and the panel, so the two run together into one blob, the blob fails
every shape test, and the region comes out with no balloon: the box hugs the
writing, and `loose_bubble` then reads a dark margin and calls it outside
text. Green box, wrong shape, wrong word.

No threshold reaches that, because the thing that is missing is the boundary
itself.

What this is
------------

`ogkalu/comic-text-and-bubble-detector` -- RT-DETR-v2 r50vd fine-tuned on
about eleven thousand pages of manga, webtoons, manhua and western comics.
Colour is in its training set, which is the whole reason it is here. Three
classes: 0 a balloon, 1 and 2 the writing inside one and the writing lying
free on the artwork. Apache 2.0, and it ships as ONNX so it runs on the
runtime the block head already uses.

Measured on lee's chapter: the two grey balloons on 050 come back at **0.98
and 0.96**, the four white ones on 029 at 0.93-0.97, and it does NOT put a box
on the balustrade that CRAFT invented one on. 0.9 seconds a page for the full
model, 0.26 for the int8 one.

What this is NOT
----------------

It is not a replacement for CRAFT and it must never be made into one. Asked to
find the sixteen sound effects CRAFT finds and DBNet misses, it finds **six**,
and all six are TYPESET -- the two title cards, a dialogue balloon, a grey
balloon. The ten it misses are brush-drawn: 뚝, 슬꾸, 훽, 술렁, 탁, 빙!, 후욱,
쿠쿵, 와아아아. Every detector tried in a day of this reads type and not
paint. This one is here for balloons, and the sound-effect path is untouched.

How the outline is found
------------------------

The model gives a rectangle, and a rectangle is not a balloon -- the cleaner
paints the mask and the typesetter measures it, so a rectangle would paint the
artwork in the corners. The shape comes from the crop instead, and by the one
property every balloon has whatever its colour is: **the inside is one flat
tone**. Take the commonest colour in the middle of the box, keep what is near
it, close the gaps, keep the piece the writing stands on, fill the letters
back in. That works on grey, on pale green, on white and on a black plate with
white type, and none of it asks for an outline.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

# 640 square, /255, no mean or variance -- matched to the model's own
# preprocessing rather than guessed.
SIDE = 640
CONF = 0.45
# Tall pages are read in windows. A webtoon squashed whole into a square shows
# the model writing four times narrower than anything it was trained on; these
# three numbers are the ones comic-translate slices with.
TALL = 3.5
SLICE_MIN = 0.7
OVERLAP = 0.2

# The balloon has to actually hold the writing before it is that writing's
# balloon, and it has to be bigger than the writing or it has bought nothing.
HOLDS = 0.90
GAIN = 1.15
# ...and it is a balloon, not a panel.
MAX_PAGE = 0.45

# Saying what a box IS, rather than where a balloon is. How much of the box the
# model's own box has to cover before its label counts, and how sure it has to
# be. Measured over all 139 dialogue boxes of lee's chapter: the model agrees
# with the app on 133 and the six it does not are six the app has wrong.
SAYS_OVER = 0.35
SURE = 0.50

# Finding the outline inside the box.
TONE = 26          # how far from the balloon's own colour still counts as it
SEAL = 5           # closing the gaps the letters cut in the fill
KEEP = 0.35        # the piece kept must be this much of the box, or no outline
# How much of the shape has to actually BE the balloon's colour. A balloon is
# its fill plus the holes its letters cut in it, and the letters are a
# minority; artwork closed into one blob by the 11-pixel brush is mostly not
# the seed colour at all.
SOLID = 0.55
# ...and how much of the ring just outside the rectangle may be the same
# colour before what was found is not a balloon but the page it stands on.
SPILLS = 0.55
RING = 8

_sess: dict = {}


def _session(path: str):
    """One session per file, for the life of the process."""
    if path not in _sess:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _sess[path] = ort.InferenceSession(
            path, so, providers=["CPUExecutionProvider"])
    return _sess[path]


_said = set()


def why_not(path: str) -> str:
    """Why this pass is not going to run, in words, or "" if it will.

    It used to be a bare `available()` returning False, and that silence cost
    lee an evening: the weights were on disk, the code was on disk, and the
    grey balloons still came back as Outside text -- because `onnxruntime` is
    not in `requirements.txt` and never had been. Nothing else in the app
    needs it; the block head's `.onnx` runs on `cv2.dnn`, and cv2.dnn
    SEGFAULTS on this one, so there is no way round it. A pass that can
    silently do nothing has to be able to say so.
    """
    if not path:
        return "no colour-balloon weights found beside the detector"
    if not os.path.isfile(path):
        return "colour-balloon weights are not at %s" % path
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return ("onnxruntime is not installed -- run `pip install "
                "onnxruntime` (the colour-balloon model needs it; "
                "nothing else in this app does)")
    return ""


def available(path: str) -> bool:
    """Whether this can run at all.

    A weights file nobody has downloaded, or an onnxruntime nobody has
    installed, must leave Find text exactly as it was -- not a traceback, and
    not a chapter found a different way without saying so. But it has to SAY
    so, once, which is what `why_not` is for.
    """
    reason = why_not(path)
    if reason:
        if reason not in _said:
            _said.add(reason)
            print("[mangatl] colour balloons off: %s" % reason, flush=True)
        return False
    return True


def _windows(h: int, w: int):
    """Top and bottom of each window a page is read in."""
    if h <= w * TALL:
        return [(0, h)]
    win = min(h, max(int(w * TALL), int(w / SLICE_MIN)))
    step = max(1, int(win * (1 - OVERLAP)))
    tops = list(range(0, max(1, h - win + 1), step))
    if tops[-1] + win < h:
        tops.append(h - win)
    return [(t, min(h, t + win)) for t in tops]


def detect(bgr: np.ndarray, path: str, conf: float = CONF) -> list:
    """Everything the model reports: (x0, y0, x1, y1, label, score)."""
    H, W = bgr.shape[:2]
    sess = _session(path)
    out = []
    for top, bot in _windows(H, W):
        crop = bgr[top:bot]
        ch, cw = crop.shape[:2]
        im = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), (SIDE, SIDE),
                        interpolation=cv2.INTER_LINEAR)
        x = (im.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        lab, box, sc = sess.run(
            None, {"images": x,
                   "orig_target_sizes": np.array([[cw, ch]], dtype=np.int64)})
        lab = np.asarray(lab).reshape(-1)
        box = np.asarray(box).reshape(-1, 4)
        sc = np.asarray(sc).reshape(-1)
        for i in range(len(sc)):
            if sc[i] < conf:
                continue
            x0, y0, x1, y1 = box[i]
            x0, x1 = max(0, int(x0)), min(W, int(x1))
            y0 = max(0, int(y0) + top)
            y1 = min(H, int(y1) + top)
            if x1 > x0 and y1 > y0:
                out.append((x0, y0, x1, y1, int(lab[i]), float(sc[i])))
    return out


def look(bgr: np.ndarray, path: str, conf: float = CONF) -> list:
    """Everything on the page, once. Both passes below read this.

    Separate from `detect` only so the two things this module does -- give a
    region its balloon, and say what the region IS -- cost one forward pass
    between them rather than one each.
    """
    if not available(path):
        return []
    return detect(bgr, path, conf)


def balloons(bgr: np.ndarray, path: str, conf: float = CONF) -> list:
    """Just the balloons, biggest score first, panels left out."""
    H, W = bgr.shape[:2]
    got = [b for b in detect(bgr, path, conf) if b[4] == 0
           and (b[2] - b[0]) * (b[3] - b[1]) <= MAX_PAGE * W * H]
    return sorted(got, key=lambda b: -b[5])


def _two_colours(px: np.ndarray) -> list:
    """The two commonest colours in a box of writing: the ink and the paper.

    Quantised to a coarse grid and counted, then the second is the commonest
    colour that is not NEAR the first -- otherwise both answers are the same
    tone twice, one bin apart, and the caller has one guess instead of two.
    """
    q = (px // 8).astype(np.int32)
    key = q[:, 0] * 4096 + q[:, 1] * 64 + q[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    order = np.argsort(-counts)
    out = []
    for i in order:
        seed = px[key == vals[i]].mean(axis=0)
        if any(float(np.linalg.norm(seed - s)) <= 2 * TONE for s in out):
            continue
        out.append(seed)
        if len(out) == 2:
            break
    return out


def _flat_piece(lab: np.ndarray, seed, cx: int, cy: int):
    """The connected run of one colour the writing stands on, letters filled
    back in. None when nothing near that colour is connected at all."""
    d = np.linalg.norm(lab.astype(np.float32) - np.asarray(seed, np.float32),
                       axis=2)
    flat = (d <= TONE).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * SEAL + 1,) * 2)
    flat = cv2.morphologyEx(flat, cv2.MORPH_CLOSE, k)
    n, lb, st, _ = cv2.connectedComponentsWithStats(flat, 8)
    if n < 2:
        return None
    want = int(lb[cy, cx])
    if want == 0:
        # The writing's middle is on ink, not on fill. Take the biggest flat
        # piece in the box instead -- on a black plate with white type that is
        # the plate, which is the right answer.
        want = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    piece = (lb == want).astype(np.uint8)
    # Fill the letters back in: the glyphs are holes in the fill, and the
    # placement area is the whole balloon, not the balloon minus its writing.
    ff = np.zeros((piece.shape[0] + 2, piece.shape[1] + 2), np.uint8)
    inv = (1 - piece).copy()
    cv2.floodFill(inv, ff, (0, 0), 2)
    piece[inv == 1] = 1
    return piece


def _it_ends(bgr: np.ndarray, box, tone) -> bool:
    """Does the fill STOP at the model's rectangle, or run on past it?

    A balloon has something else outside it -- artwork, a panel, the page. A
    block of credits standing on white paper has more white paper, and the
    flat shape found inside the rectangle is that paper, not a balloon.
    """
    H, W = bgr.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in box[:4]]
    a0, b0 = max(0, x0 - RING), max(0, y0 - RING)
    a1, b1 = min(W, x1 + RING), min(H, y1 + RING)
    out = np.ones((b1 - b0, a1 - a0), bool)
    out[y0 - b0:y1 - b0, x0 - a0:x1 - a0] = False
    if out.sum() < 60:
        return True          # the rectangle is the whole page; nothing to ask
    lab = cv2.cvtColor(bgr[b0:b1, a0:a1], cv2.COLOR_BGR2LAB)
    d = np.linalg.norm(lab.astype(np.float32) - np.asarray(tone, np.float32),
                       axis=2)
    return float((d[out] <= TONE).mean()) <= SPILLS


def outline(bgr: np.ndarray, box, text_bbox):
    """The balloon's actual shape inside the rectangle, by flat colour.

    Returns `(mask, bbox, polygon)` in page coordinates, or None when the crop
    holds no flat region big enough to be a balloon -- a rectangle round a bit
    of busy artwork answers None and the region keeps whatever it had.
    """
    H, W = bgr.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in box[:4]]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = bgr[y0:y1, x0:x1]
    lab = cv2.cvtColor(cv2.GaussianBlur(crop, (3, 3), 0), cv2.COLOR_BGR2LAB)

    # THE BALLOON'S OWN COLOUR IS THE COLOUR BETWEEN THE LETTERS.
    #
    # Sampled inside the rectangle round the WRITING, and taken as the mode:
    # letters are a minority of their own box by area, so the commonest colour
    # in there is the paper they are printed on, whether that is white, pale
    # green, grey, or a black plate under white type. And it is certainly
    # inside the balloon, which is what the other two ideas could not promise.
    #
    # Both were tried on 050 and both failed. A ring scaled off the writing
    # lands OUTSIDE the balloon when the writing nearly fills it. The margin
    # between the writing and the model's rectangle looks right until you
    # notice the rectangle is a box round an ellipse on a black page: 38% of
    # that margin is the page, and the mode came back Lab 0,128,128 -- black.
    tx, ty, tw, th = [int(v) for v in text_bbox]
    cx = int(np.clip(tx + tw / 2 - x0, 0, crop.shape[1] - 1))
    cy = int(np.clip(ty + th / 2 - y0, 0, crop.shape[0] - 1))
    band = np.zeros(crop.shape[:2], np.uint8)
    band[max(0, ty - y0):ty - y0 + th, max(0, tx - x0):tx - x0 + tw] = 1
    take = band > 0
    if take.sum() < 60:
        take = np.ones(crop.shape[:2], bool)
    px = lab[take].reshape(-1, 3)
    # ...and there are exactly TWO colours in a box of writing: the letters
    # and the paper under them. The mode is usually the paper -- strokes are a
    # minority of their own box -- but not always: bold display type at 73% of
    # its box makes the letters the mode, and the first version of this seeded
    # on the ink and found nothing.
    #
    # So take both, and let the page decide. The paper is the one that grows
    # into a big connected shape; the ink grows into scattered strokes. No
    # rule about light and dark, which is what lets a black plate under white
    # type come out the same way round as grey paper under black.
    seeds = _two_colours(px)

    # Each candidate is judged in full, not just by size. The biggest flat
    # piece is usually the paper -- but on a pale balloon lying on a pale
    # panel the two run together into one shape covering the whole crop, and
    # that shape is bigger than the right answer and is not a balloon. So a
    # candidate has to pass everything before it can win, and the ink is still
    # there to fall back to.
    piece = tone = None
    for seed in seeds:
        got = _flat_piece(lab, seed, cx, cy)
        if got is None or float(got.sum()) < KEEP * got.size:
            continue

        # A BALLOON IS MOSTLY ITS OWN COLOUR.
        #
        # Closing gaps with an 11-pixel brush will weld anything into one
        # shape, busy artwork included, so the shape has to be asked what it
        # is MADE of. A balloon is fill plus the holes its letters cut in it,
        # and the letters are a minority of it; a rectangle of noise closed
        # into one blob is a few per cent seed colour and the rest anything.
        # `balloon._interior_ok` asks this of a balloon it already has -- same
        # question, and this is the only place it can be asked here, because
        # the letters are inside the shape by the time it exists.
        near = np.linalg.norm(lab.astype(np.float32)
                              - np.asarray(seed, np.float32), axis=2) <= TONE
        held = float((near & (got > 0)).sum())
        if held < SOLID * float(got.sum()):
            continue

        # A BALLOON ENDS.
        #
        # 072's studio credits stand on a white page: the model put a
        # rectangle round them, the fill inside it is flat, and it is flat
        # because it is the PAGE. What tells the two apart is what happens
        # just outside the rectangle -- a balloon has something else there, a
        # page has more page. lee filed this one against the old code already:
        # *"outside etxt beigng detected as inside box"*.
        if not _it_ends(bgr, (x0, y0, x1, y1), seed):
            continue

        # ...and it is BIGGER than the writing, or it has bought nothing.
        # The same rule the rectangle is judged by, asked again of the shape:
        # a block of type on paper offers its own ink as a candidate, and that
        # candidate comes back the size and shape of the type. A balloon has
        # room round its words; a word does not.
        if float(got.sum()) < GAIN * max(1.0, float(tw * th)):
            continue

        if piece is None or got.sum() > piece.sum():
            piece, tone = got, seed
    if piece is None:
        return None

    cnts, _ = cv2.findContours(piece, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    big = max(cnts, key=cv2.contourArea)
    bx, by, bw, bh = cv2.boundingRect(big)

    mask = np.zeros((H, W), np.uint8)
    mask[y0:y1, x0:x1] = piece * 255
    poly = [[int(a) + x0, int(b) + y0] for a, b in big.reshape(-1, 2)]
    return mask, (bx + x0, by + y0, bw, bh), poly


def _inside(text_bbox, box) -> float:
    """How much of the writing the balloon holds."""
    tx, ty, tw, th = [int(v) for v in text_bbox]
    ix = max(0, min(tx + tw, box[2]) - max(tx, box[0]))
    iy = max(0, min(ty + th, box[3]) - max(ty, box[1]))
    return ix * iy / float(max(1, tw * th))


def name_the_balloons(bgr: np.ndarray, regions: list, path: str,
                      conf: float = CONF, boxes: list = None) -> int:
    """Give a balloon to every region standing in one that ink could not find.

    Only ever ADDS. A region that already has a `bubble_mask` keeps it -- that
    mask is a measurement of the page and this is a guess from a model, and
    where the two disagree about a balloon with an outline the measurement is
    better. What this reaches is the case the measurement cannot have an
    opinion about: no outline, so nothing was found.

    Returns how many regions were given one, so a caller can say whether the
    pass did anything.
    """
    if not available(path) or not regions:
        return 0
    if boxes is None:
        boxes = balloons(bgr, path, conf)
    else:
        H, W = bgr.shape[:2]
        boxes = sorted([b for b in boxes if b[4] == 0
                        and (b[2] - b[0]) * (b[3] - b[1]) <= MAX_PAGE * W * H],
                       key=lambda b: -b[5])
    if not boxes:
        return 0
    from .. import kinds as _kinds

    # ONE BALLOON, ONE OWNER.
    #
    # A balloon that already belongs to a region is not going spare. On 055 a
    # burst balloon had been found by measurement and given to the writing
    # inside it; a second region's box also sat inside the model's rectangle,
    # and without this it was handed the same balloon -- so the page came back
    # with two boxes round one burst, one inside the other. `_drop_duplicates`
    # cannot save it: that pass runs long before this one does.
    taken = [tuple(int(v) for v in r.bubble_bbox) for r in regions
             if getattr(r, "bubble_mask", None) is not None
             and getattr(r, "bubble_bbox", None)]

    done = 0
    for r in regions:
        if getattr(r, "bubble_mask", None) is not None:
            continue
        bb = getattr(r, "bbox", None)
        if not bb or len(bb) != 4:
            continue
        # A SOUND EFFECT DRAWN OVER A BALLOON IS STILL A SOUND EFFECT.
        #
        # On 029 the upper 웅성 is painted across the spikes of a shout
        # balloon, so the model's rectangle round that balloon holds all of
        # it, and without this the effect came back `bubble` with the
        # balloon's own outline on it -- which would send it to the balloon
        # fitter and have the cleaner paint out the whole shout. The question
        # this pass answers is whether a piece of DIALOGUE is in a balloon or
        # loose on the art. It has nothing to say about effects.
        if _kinds.family_of(getattr(r, "kind", "bubble")) == "sfx":
            continue
        best = None
        for b in boxes:
            if _inside(bb, b) < HOLDS:
                continue
            area = (b[2] - b[0]) * (b[3] - b[1])
            if area < GAIN * max(1, bb[2] * bb[3]):
                continue        # the same rectangle again, in a hat
            if best is None or area < (best[2] - best[0]) * (best[3] - best[1]):
                best = b         # the SMALLEST balloon that holds it
        if best is None:
            continue
        if any(_inside((t[0], t[1], t[2], t[3]), best) > 0.5 or
               _inside((best[0], best[1], best[2] - best[0],
                        best[3] - best[1]),
                       (t[0], t[1], t[0] + t[2], t[1] + t[3])) > 0.5
               for t in taken):
            continue
        found = outline(bgr, best, bb)
        if found is None:
            continue
        mask, box, poly = found
        r.bubble_mask = mask
        r.bubble_bbox = tuple(int(v) for v in box)
        r.polygon = poly
        taken.append(tuple(int(v) for v in box))
        # A balloon makes it dialogue, and the sub-type the person picked --
        # a thought, an angry balloon -- is theirs and is left alone. Only a
        # region the detectors called something else moves.
        if _kinds.family_of(getattr(r, "kind", "bubble")) != "bubble":
            r.kind = "bubble"
        done += 1
    return done


def name_the_kinds(bgr: np.ndarray, regions: list, path: str,
                   conf: float = CONF, boxes: list = None,
                   sure: float = SURE) -> int:
    """Say whether a piece of writing is IN a balloon or loose on the artwork.

    lee has filed this one all day, from both directions: *"how are these
    bubble text ? and these grey bubble are not"*, *"i think this box is using
    teh edge of the pannel to make it a bubble tetx it shoud ever do that"*,
    *"outside etxt beigng detected as inside box"*.

    Every one of those is the same mechanism. The app decides this by MEASURING
    THE PAPER -- is the margin round the box brighter than 200, is there a
    closed wall, is there a balloon mask under it. Those are good measurements
    and they are all proxies, so they lie in exactly two places: a caption on a
    pale empty page reads as "inside a balloon" because the page is bright, and
    writing in a balloon on a dark panel reads as "outside" because the margin
    is dark.

    This model does not infer it. It was shown eleven thousand comic pages and
    told which writing was in a balloon and which was loose, and class 1 and
    class 2 are those two answers.

    Measured over all 139 dialogue boxes of lee's chapter:

        app says    ->  model says
        bubble      ->  bubble       123
        bubble      ->  freefloat      5
        freefloat   ->  bubble         1
        freefloat   ->  freefloat     10

    **96% agreement, and all six disagreements were cropped and looked at, and
    on all six the model is right and the app is wrong.** Three are the ruled
    caption boxes on 022 standing on a cream page; one is a name plate on
    artwork; one is 에어돔, the box lee sent a screenshot of; and the last is
    the other way round -- 후계자는 무슨! 입 닥쳐!!! is in a balloon and the app
    had demoted it.

    Three things it will not do:

    * **It never touches a sound effect.** The question is dialogue-versus-
      outside-text and it has nothing to say about paint.
    * **It never touches a sub-type.** A thought bubble, an angry balloon, a
      caption somebody moved by hand -- those are decisions, and this only
      moves a box still sitting on the family default it was detected as.
    * **It never moves a box.** Only the word on it changes.
    """
    if not regions:
        return 0
    if boxes is None:
        boxes = look(bgr, path, conf)
    said = [b for b in boxes if b[4] in (1, 2)]
    if not said:
        return 0
    from .. import kinds as _kinds

    done = 0
    for r in regions:
        kind = getattr(r, "kind", "bubble")
        # The family defaults only. Anything else is somebody's decision.
        if kind not in ("bubble", "freefloat"):
            continue
        bb = getattr(r, "bbox", None)
        if not bb or len(bb) != 4:
            continue
        best, over = None, 0.0
        for b in said:
            o = _inside(bb, b)
            if o > over:
                best, over = b, o
        if best is None or over < SAYS_OVER or best[5] < sure:
            continue
        want = "bubble" if best[4] == 1 else "freefloat"
        if want == kind:
            continue
        r.kind = want
        done += 1
    return done


def rectangles(boxes: list, W: int, H: int) -> list:
    """The model's boxes, as the rectangles the block head would have given.

    lee: *"i liek the boxes teh other detetor does but i still want teh
    maskinf of ctd"*, and then *"lets focus on the buble and outside etxt for
    now"*.

    So this stands in for `_decode_blocks` and nothing else changes: whatever
    comes back is still cropped to comic-text-detector's pixel mask, still
    split into clusters, still classified, still padded, still carries the
    mask the cleaner paints. Only WHERE the rectangles come from moves.

    The one real problem is granularity, and the model's own balloon class
    solves it. It boxes a LINE where this app boxes a BALLOON -- 182 against
    141 over lee's chapter -- so every line whose centre stands inside one
    balloon becomes one rectangle. Measured that way over the same 69 pages:

        the app ships                 141 dialogue boxes
        this produces                 147
        of the app's it finds         139
        of the app's it misses          2
        boxes nothing else has          4
        boxes with no ink under them    3

    The two it misses are big stylised display type. Of the four it adds, the
    chapter title on 012 and 수군 on 039 are real writing the app has never
    boxed; two flourishes on 022 and a chandelier on 042 are artwork.

    `(x0, y0, x1, y1, score)`, in page coordinates, biggest score first.
    """
    bub = sorted([b for b in boxes if b[4] == 0
                  and (b[2] - b[0]) * (b[3] - b[1]) <= MAX_PAGE * W * H],
                 key=lambda b: -b[5])
    # The same balloon comes back from two overlapping windows on a tall page.
    keep = []
    for b in bub:
        if any(_inside((b[0], b[1], b[2] - b[0], b[3] - b[1]), k) > 0.6
               for k in keep):
            continue
        keep.append(b)

    text = [b for b in boxes if b[4] in (1, 2)]
    out, claimed = [], set()
    for k in keep:
        mine = [b for b in text
                if k[0] <= (b[0] + b[2]) / 2.0 <= k[2]
                and k[1] <= (b[1] + b[3]) / 2.0 <= k[3]]
        if not mine:
            continue                    # an empty balloon is not a text box
        for b in mine:
            claimed.add(id(b))
        out.append((min(b[0] for b in mine), min(b[1] for b in mine),
                    max(b[2] for b in mine), max(b[3] for b in mine),
                    float(k[5])))
    for b in text:
        if id(b) not in claimed:
            out.append((b[0], b[1], b[2], b[3], float(b[5])))
    return sorted(out, key=lambda r: -r[4])
