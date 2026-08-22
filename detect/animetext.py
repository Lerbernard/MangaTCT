"""One model that finds all of it -- dialogue, captions and painted effects.

`deepghs/AnimeText_yolo`, the `yolo12l_animetext` weights: a YOLO12-L detector
with a single class, `text_block`, trained on **AnimeText** (arXiv 2510.07951)
-- 735,000 images and 4.2 million annotated text blocks, built because natural
scene detectors collapse on this material. The paper's own headline is that a
model trained on ICDAR15 scores **F1 0.008** on anime. Its training set
explicitly covers *"handwritten and stylized artistic fonts"*, which is the
thing Manga109 has no class for and comic-text-detector guesses at.

lee: *"impliment the animen text alone and maybe add ctd as a mask if
needed"*.

## WHAT IT DOES ON HIS CHAPTER, AGAINST THE SAME 226 SITES

    what                 found   missed
    bubble text            130        0     ALL of it
    outside text            29        0     ALL of it
    sound effects           56        5
    sites nothing boxes      0        6     see below

    imgsz   conf   s/page   boxes   missed   junk
     1024   0.25     3.59     257       11      1
     1024   0.15     3.42     261       11      1
     1280   0.25     7.20     259       11      0
     1280   0.15     6.53     264       11      0
     1536   0.25    15.03     258       12      0
     1536   0.15    15.49     268       11      1

Set against everything else measured on the same pages:

    route                              missed   junk   models   s/page
    comic-text-detector alone               5     13      1       2.94
    CTD + DB++/COO + the rules              6      4      2       9.9
    Manga109 seg + COO + CTD mask           7      3      3      12.7
    **AnimeText alone**                    11      1      1       3.59

Eleven looks worse than six until the eleven are read: **six of them are the
same six every route on this chapter misses** -- 013's white scribble, 014's
zigzag and the four lines of handwriting on the note at the bottom of 014 --
and the other five are sound effects. Nothing it misses is a line of dialogue
or a caption. It finds **every one of the 159 boxes of writing somebody has
to translate**, which no other detector here has done, and it does it with one
junk box on 23 pages.

`SIZE` is 1024 rather than 1280 for the one junk box: 1280 removes it and
doubles the time, and one stray rectangle a chapter is a click.

## WHAT IT DOES NOT DO

**No masks.** It is a detector, so `comictext.page_text_mask` still supplies
the ink Clean paints with -- lee: *"maybe add ctd as a mask if needed"*, and
it is needed: `inpaint` skips any region whose `text_mask is None`, three
times over.

**No classes.** One label, `text_block`, over dialogue, captions and painted
effects alike, so what a box IS gets decided after it is found -- by the
balloon round it, and by the sound-effect specialist if its weights are on the
machine. See `dbcoo.detect_animetext`.

## LICENCE

GPL-3.0, which is not the licence of the other checkpoints here. Worth knowing
before this ships in anything.

Contract matched to `craft.pieces`, `dbtext.pieces` and `mangaseg.pieces`:
page in, `[x0, y0, x1, y1]` out.
"""
import os

import numpy as np

# The long side the page is resized to. See the sweep in the docstring: 1024
# is one junk box on 23 pages and half the time of 1280, which is none.
SIZE = 1024
CONF = 0.25
TEXT = "text_block"

_model = None
_ckpt = None


def why_not(path: str) -> str:
    """Why this detector cannot run, in a sentence, or empty if it can."""
    if not path:
        return "no AnimeText weights are set"
    if not os.path.isfile(path):
        return "AnimeText weights are not at %s" % path
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return ("ultralytics is not installed -- run `pip install "
                "ultralytics` (the AnimeText model needs it)")
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


def pieces(img: np.ndarray, ckpt: str, size: int = SIZE,
           conf: float = CONF) -> list:
    """Every block of writing on the page, of any kind, ungrouped.

    Ungrouped in the contract sense only -- this model returns one rectangle
    per body of writing already, and nothing here reaches for a neighbour. The
    reach rules in this package exist for detectors that hand back fragments;
    pointing one at these boxes would weld two balloons together.
    """
    res = model(ckpt).predict(img, imgsz=size, conf=conf, verbose=False)[0]
    H, W = img.shape[:2]
    out = []
    for b in res.boxes:
        x0, y0, x1, y1 = [int(v) for v in b.xyxy[0].tolist()]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 > x0 and y1 > y0:
            out.append([x0, y0, x1, y1])
    return out
