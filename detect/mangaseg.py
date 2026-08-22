"""The Manga109 segmenter: the best reader of dialogue on this chapter.

`ShadowB/Manga109-panel-balloon-text-yolov26-segmentation` -- a YOLO26s
instance-segmentation model with three classes, `frame`, `text` and
`balloon`, trained on 7,174 Manga109-derived pages across 83 titles with a
book-level split.

lee, having read the model card: *"ok impliment it"*.

## WHAT IT DOES ON HIS CHAPTER, AGAINST THE SAME 226 SITES AS EVERYTHING ELSE

    what                  found   missed
    bubble text             129        1     99.2%
    outside text             23        6
    sound effects             4       57     it has no sfx class
    sites nothing boxes       0        6

**Junk: ZERO.** Against comic-text-detector's thirteen. Nothing false on 23
pages, which is not a thing any other detector here has managed.

    imgsz   s/page   text   balloon   missed   junk
      640     0.44    161       125       71      0
     1024     0.86    168       127       70      0
     1280     1.37    170       126       70      0
     1536     1.93    179       129       66      0

1024 is the knee and it is what `SIZE` is: 1280 buys nothing and 1536 buys
four sites for another second a page. Against comic-text-detector's 2.94 for
five misses and thirteen junk boxes, this is a third of the time.

The onomatopoeia column is not a fault. Manga109 does not annotate painted
effects as text, so the model has never been shown one, and DB++/COO is the
specialist that has -- see `onomatopoeia`. The route runs both.

## AND ITS MASKS ARE NOT INK, WHICH IS WHY comic-text-detector STAYS

The dataset it was trained on says so in its name:
`Manga109_RegionLevelTextSegmentation`. Measured over 21 boxes on three
pages, as a share of each box's own area:

    Manga109 YOLO26          median 0.659   range 0.485-0.926
    comic-text-detector seg  median 0.342   range 0.227-0.617

One is a blob over the text AREA and the other is the strokes. `inpaint`
paints what the mask calls writing, so a 0.66-fill mask scrubs the balloon's
interior along with the words -- invisible on flat white and wrong the moment
the writing sits over screentone or artwork.

So this module returns rectangles and the balloon shapes, and the ink mask
still comes from `comictext.page_text_mask`. Same division of labour the
DBNet route already had, for the same reason.

Contract matched to `craft.pieces` and `dbtext.pieces`: page in,
`[x0, y0, x1, y1]` out. `balloons` is the second answer -- the shapes the
model found round the writing, which is the question `balloon._round_wall_around`
was guessing at with a Canny pass.
"""
import os

import numpy as np

# The long side the page is resized to. See the sweep in the docstring.
SIZE = 1024
# How sure the model has to be. Ultralytics' own default; the sweep above was
# run at it and there is no junk to trade away by raising it.
CONF = 0.25
TEXT = "text"
BALLOON = "balloon"
FRAME = "frame"

_model = None
_ckpt = None


def why_not(path: str) -> str:
    """Why this detector cannot run, in a sentence, or empty if it can."""
    if not path:
        return "no Manga109 segmenter weights are set"
    if not os.path.isfile(path):
        return "Manga109 segmenter weights are not at %s" % path
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return ("ultralytics is not installed -- run `pip install "
                "ultralytics` (the Manga109 segmenter needs it)")
    return ""


def available(path: str) -> bool:
    return not why_not(path)


def model(ckpt: str):
    """The net, loaded once and kept."""
    global _model, _ckpt
    if _model is None or _ckpt != ckpt:
        from ultralytics import YOLO
        _model, _ckpt = YOLO(ckpt), ckpt
    return _model


def read(img: np.ndarray, ckpt: str, size: int = SIZE, conf: float = CONF,
         want: tuple = (TEXT, BALLOON)) -> dict:
    """Everything the model finds, as `{class name: [[x0, y0, x1, y1], ...]}`.

    `frame` is asked for only if a caller wants it. Panels are not writing and
    nothing in the pipeline reads them yet, so they are dropped by default
    rather than carried around.
    """
    m = model(ckpt)
    res = m.predict(img, imgsz=size, conf=conf, verbose=False)[0]
    H, W = img.shape[:2]
    out = {k: [] for k in want}
    for b in res.boxes:
        name = m.names[int(b.cls.item())]
        if name not in out:
            continue
        x0, y0, x1, y1 = [int(v) for v in b.xyxy[0].tolist()]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 > x0 and y1 > y0:
            out[name].append([x0, y0, x1, y1])
    return out


def pieces(img: np.ndarray, ckpt: str, size: int = SIZE,
           conf: float = CONF) -> list:
    """Every rectangle of writing, deliberately ungrouped.

    Same contract as `craft.pieces` and `dbtext.pieces`, so the same reach
    rules can be pointed at it -- though on this model they are not needed:
    it returns one box per body of writing already.
    """
    return read(img, ckpt, size, conf, want=(TEXT,))[TEXT]


def balloons(img: np.ndarray, ckpt: str, size: int = SIZE,
             conf: float = CONF) -> list:
    """The shapes somebody drew round the writing.

    127 of them over the 23 pages, against a Canny wall test that reads paint
    over speed lines as enclosed and misses a caption plate on a busy panel.
    """
    return read(img, ckpt, size, conf, want=(BALLOON,))[BALLOON]
