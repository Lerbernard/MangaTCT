"""A second reader, for writing that was PAINTED rather than typeset.

lee: *"what can i do about this[:] Sound effects read badly by every reader"*,
and then, of the answer: *"do it for offline rrader"*.

manga-ocr was trained on typeset dialogue and it is superb at typeset dialogue.
On a hand-drawn sound effect it is a coin toss, and it fails in the one way that
cannot be caught downstream: it emits an ordinary Japanese line at full
confidence, because that is what its decoder's language model knows how to say.
Measured over every box the detector filed as a sound effect across the 23 pages
of chapter 3 - 54 boxes, transcribed off the page by eye:

    reader                painted sounds (43)   typeset filed as sfx (11)
    manga-ocr             0.401 CER  24/43      0.000 CER  11/11
    COO TRBA+2D           0.138 CER  32/43      0.602 CER   4/11

Scored on the crop `ocr.prepare_crop` actually makes, padding and all, rather
than on a bare cut of the box - a reader is only as good as the picture the app
hands it, and the two differ.

Each is excellent at the other's blind spot, which is what a specialist looks
like. TRBA+2D comes from the same ECCV 2022 release as the DB++ detector this
app already runs for sound-effect BOXES (`detect/onomatopoeia.py`); this is the
recogniser from the other half of that paper.

And it does not invent dialogue. Every one of its misses is a near miss on the
sound itself - ぶっ as ぶつ, ドホ as ゲホ, ガチャッ as ガチャン, シャリ as
ジャリ - against manga-ocr's アア as そして and バチャ as じゃあ.


WHICH ANSWER TO KEEP - AND WHY IT IS NOT A GUESS
------------------------------------------------
`prefer()` below. **TRBA's alphabet is 182 characters and holds no kanji at
all.** So a kanji in manga-ocr's reading is proof that the box contains
something this model could not have represented even in principle - which
happens because one box in five that gets labelled a sound effect is not one:
it is painted speech, a shop sign, or typeset dialogue in a drawn balloon.

    read the box with both;
    if manga-ocr's answer contains a kanji, keep it;
    otherwise take TRBA's.

Over the same 54 boxes:

    manga-ocr everywhere        0.319  35/54
    TRBA everywhere             0.232  36/54
    the kanji rule              0.137  41/54   <- this one
    a perfect router (cheating) 0.138  43/54

It cuts the error by well over half and gives up nothing on paint - it is
within a thousandth of a router that has been told the right answer, which is
as close as a rule gets. A length threshold on top of it was measured at 5, 6,
7 and 8 characters and changes nothing at any value: the kanji test alone does
all the work, which is what a rule about the ALPHABET should do. The two it
still misses are typeset boxes with no kanji in them - `あはは` and `ねぇ` -
and TRBA comes back with `あは` and `ねえ`, so even the misses are near.


IT DOES NOT CATCH THE AI, AND IT WAS NOT GOING TO
-------------------------------------------------
The other reader is still better at this. Scored against lee's own 23-page
Translate export, restricted to the twelve pages where both runs found the SAME
number of sound effects, so the two are answering about the same drawings -
eighteen effects:

    the AI, whole page at once      0.056 CER   17/18
    here, manga-ocr + TRBA          0.130 CER   13/18
    here, manga-ocr alone           (0.401 over the wider 43)

So the gap on paint went from four times to twice, which is what this is for:
somebody who has chosen the reader that needs no key and no network gets most
of the way, not all of it. n=18 and the AI reads the whole page WITH its
neighbours, which is exactly the advantage that tells on a drawn sound.

What is left is voicing. Every one of the five misses here is a dakuten:
シャリ read as ジャリ, ピッ as ビッ, ぬら as ぬっ, ドホ as ゲホ. Two strokes on
a brush-drawn kana, which is also where manga-ocr's own near-misses were.


THE ROTATION TRICK IS NOT AN OPTIMISATION
-----------------------------------------
Japanese sound effects are drawn down the page as often as across it, and the
network only reads left to right. So every crop goes in three times - as it is,
turned 90, turned 270 - and the answer with the highest mean character
probability wins. That is the SAR decoding in the checkpoint's own name, and
without it vertical paint comes back as confident nonsense.
"""
from __future__ import annotations

import os

CHARSET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "trba", "charset.txt")

# The released checkpoint, under any of the names it travels as. Same shape as
# `Project.coo_weights` looks for the detector's.
WEIGHT_NAMES = ("TRBA_Rot+SAR+HardROIhalf+2D.pth", "trba_coo.pth",
                "TRBA_2D.pth")

# What the model was trained at, from the repository's own evaluation line:
# `--model_name TRBA --SARdecode --imgH 100 --twoD`. The height is 100 and not
# 32 BECAUSE of the 2D attention - a flat 32-pixel strip has no second
# dimension to attend over.
IMG_H = IMG_W = 100
MAX_LEN = 25

_READER = None
_READER_KEY = ""


def why_not(path: str) -> str:
    """Why this reader cannot run, in a sentence, or "" if it can.

    The same shape as `detect.onomatopoeia.why_not`, and for the same reason: a
    reader that is quietly absent changes what a page says without saying so.
    """
    if not path:
        return "no painted-text weights are set"
    if not os.path.isfile(path):
        return "painted-text weights are not at %s" % path
    try:
        import torch  # noqa: F401
    except Exception:
        return "pytorch is not installed -- run `pip install torch`"
    return ""


def available(path: str) -> bool:
    return not why_not(path)


def beside(*folders: str) -> str:
    """The checkpoint if it is sitting in any of these folders, else ""."""
    for d in folders:
        if not d:
            continue
        for name in WEIGHT_NAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return ""


class _Opt:
    num_fiducial = 20
    input_channel = 3
    output_channel = 512
    hidden_size = 256
    batch_max_length = MAX_LEN
    imgH = IMG_H
    imgW = IMG_W
    twoD = True
    SARdecode = True
    Transformation = "TPS"
    FeatureExtraction = "ResNet"
    SequenceModeling = "BiLSTM"
    Prediction = "Attn"


class _Converter:
    """Index to character. Lifted rather than imported: the repository's
    `utils.AttnLabelConverter` prints its token count on construction and
    carries an encoder for training that nothing here uses."""

    SPECIAL = ["[PAD]", "[UNK]", "[SOS]", "[EOS]", " "]

    def __init__(self, characters: str):
        self.character = self.SPECIAL + list(characters)
        self.dict = {c: i for i, c in enumerate(self.character)}

    def decode(self, indices) -> str:
        return "".join(self.character[int(i)] for i in indices)


def get_reader(path: str):
    """Build the model once and hand back `(model, converter, opt)`.

    Cached on the checkpoint path, the same way `ocr.get_engine` caches
    manga-ocr: this is 200MB of weights and 2.8 seconds, and a chapter is a
    great many boxes.
    """
    global _READER, _READER_KEY
    if _READER is not None and _READER_KEY == path:
        return _READER
    import torch

    from .trba.model import Model

    with open(CHARSET, encoding="utf-8-sig") as fh:
        chars = fh.readlines()[0].strip()
    opt = _Opt()
    conv = _Converter(chars)
    opt.sos_token_index = conv.dict["[SOS]"]
    opt.eos_token_index = conv.dict["[EOS]"]
    opt.num_class = len(conv.character)

    model = Model(opt)
    state = torch.load(path, map_location="cpu")
    # Saved from a DataParallel wrapper, so every key carries a "module." the
    # bare model does not have.
    state = {k[7:] if k.startswith("module.") else k: v
             for k, v in state.items()}
    model.load_state_dict(state)
    model.eval()
    _READER, _READER_KEY = (model, conv, opt), path
    return _READER


def read_one(img, reader) -> str:
    """One reading of one crop, best of three rotations.

    Takes what the caller has: a PIL image, which is what `ocr.prepare_crop`
    hands its engine, or an OpenCV BGR array, which is what a bench script cuts
    off a page. Getting this wrong is a silent colour swap rather than an error,
    so it is decided here once instead of at each call.
    """
    import cv2
    import numpy as np
    import torch
    import torch.nn.functional as F

    model, conv, opt = reader
    if hasattr(img, "convert"):                  # PIL, already RGB
        rgb = np.asarray(img.convert("RGB"))
    else:                                        # OpenCV, BGR
        rgb = cv2.cvtColor(np.asarray(img), cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    if not h or not w:
        return ""
    # Only a TALL crop is a candidate for vertical writing; a wide one is
    # offered three times all the same, so the batch shape and the pick are the
    # same either way.
    views = [rgb]
    if h > w:
        views += [np.rot90(rgb, 1).copy(), np.rot90(rgb, 3).copy()]
    else:
        views += [rgb, rgb]

    batch = []
    for v in views:
        v = cv2.resize(v, (opt.imgW, opt.imgH), interpolation=cv2.INTER_CUBIC)
        t = torch.from_numpy(v).permute(2, 0, 1).float().div_(255.0)
        batch.append(t.sub_(0.5).div_(0.5))
    x = torch.stack(batch)

    with torch.no_grad():
        sos = torch.LongTensor(len(views)).fill_(opt.sos_token_index)
        preds = model(x, sos, is_train=False)
    prob = F.softmax(preds, dim=2)

    best_score, best = -1.0, ""
    for i in range(len(views)):
        idx = preds[i].argmax(1)
        hit = (idx == opt.eos_token_index).nonzero()
        cut = int(hit[0]) if len(hit) else len(idx)
        if not cut:
            continue
        score = float(prob[i].max(dim=1).values[:cut].mean())
        if score > best_score:
            best_score, best = score, conv.decode(idx[:cut])
    return best.split("[EOS]")[0].strip()


# Anything in the CJK ideograph blocks. TRBA's alphabet has none of them, so
# one of these in manga-ocr's answer means the box holds writing this reader
# could not have produced - see the module docstring.
def has_kanji(s: str) -> bool:
    return any("㐀" <= c <= "鿿" or "豈" <= c <= "﫿"
               for c in (s or ""))


def prefer(typeset: str, painted: str) -> str:
    """Which of the two readings to keep. See the module docstring.

    Ties go to manga-ocr, deliberately: it is the reader that runs on every
    other box on the page, and a box where this one has nothing to say should
    read the same as its neighbours.
    """
    typeset = (typeset or "").strip()
    painted = (painted or "").strip()
    if not painted:
        return typeset
    if not typeset:
        return painted
    return typeset if has_kanji(typeset) else painted
