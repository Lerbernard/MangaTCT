"""manga-image-translator's own detector, and the page turned inside out.

A DBNet on a ResNet34 U-Net with self-attention, trained on COMICS. It is the
default detector of the most-used open manga translator there is, and on 23
pages of Japanese it reads **100% of the dialogue** -- once it is asked twice.

lee, of two captions reversed out of black balloons that it returned nothing
for: *"can you tune teh db net to ready back boxes too?"*.

He has the mechanism right. A DB segmentation head is trained on dark strokes
against light ground; white type knocked out of a black balloon is the
photographic negative of everything it ever saw, and it answers with silence
rather than with a bad box. 012's ...あ？ and 015's ...エーダ both come back
empty. Invert the page and the same writing arrives the way round it was
trained on, and both are found. So the page is read twice and the boxes are
unioned -- 5.22 s/page against 3.58, and dialogue goes 92.5% to 100%.

Contract matched to `craft.pieces`: page in, `[x0, y0, x1, y1]` out,
deliberately ungrouped. Something else decides which of them are one balloon,
and that something is `craft.group`, which is the app's own reach rule.
"""
import os

import cv2
import numpy as np

# THE DETECT SIZE IS A LONG-SIDE TARGET, AND 1536 UPSCALES A MANGA PAGE.
#
# lee: *"its 25 second per page every time not once or twice i timeed it"*.
#
# 1536 is manga-image-translator's own default, and it is the size of the
# LONGER side after `resize_aspect_ratio`. lee's pages are 1365x960, so the
# net was being handed **1536x1280** -- a third bigger than the scan in each
# direction, 1.78x the pixels, for detail that was never there. The same
# shape of mistake `onomatopoeia` had at 1152, found the same way.
#
# Swept over the chapter, both passes, against the 226 sites:
#
#     size   s/page   missed   junk
#     1536     7.86        4      4
#     1280     3.70        5      3
#     1024     2.31       13      4
#      896     2.31       22      3
#      768     1.86       34      3
#
# **1280 is where the page stops being upscaled** -- 1365x960 arrives as
# 1280x896 -- and it is less than half the time for one box. Below it the
# recall falls off a cliff: 1024 loses eight more and 896 loses eighteen.
DETECT_SIZE = 1280
TEXT_THRESH = 0.5
BOX_THRESH = 0.7
UNCLIP = 2.3
# A shape bigger than this share of the page is a panel, not a mark. DB floods
# a light page at a loose threshold -- on the title page one shape came back
# covering half of it -- and one such mark dominates the grouping and takes the
# real boxes with it. Same idea as `craft._under_cap`, applied earlier because
# DB has no smaller pieces to trade down to.
CAP = 0.12

_model = None
_ckpt = None


def why_not(path: str) -> str:
    """Why this detector cannot run, in a sentence, or empty if it can."""
    if not path:
        return "no manga-text weights are set"
    if not os.path.isfile(path):
        return "manga-text weights are not at %s" % path
    try:
        import torch  # noqa: F401
    except Exception:
        return "pytorch is not installed -- run `pip install torch`"
    # `_dbnet/DBNet_resnet34.py` rearranges the feature map with einops for
    # its self-attention block. Checked here rather than left to explode at
    # the first page: a missing dependency is a sentence somebody can act on,
    # and a traceback out of the middle of a run is not.
    try:
        import einops  # noqa: F401
    except Exception:
        return ("einops is not installed -- run `pip install einops` "
                "(the manga-text model needs it)")
    return ""


def available(path: str) -> bool:
    return not why_not(path)


def model(ckpt: str):
    """The net, loaded once and kept.

    `channels_last` for the same reason `craft.lay_out_for_the_cpu` does it:
    oneDNN's blocked convolution wants that layout and reorders every tensor
    when it does not get it. Measured on CRAFT it was 1.19x for identical
    boxes.
    """
    global _model, _ckpt
    import torch
    from .. import cores
    cores.claim()                # every core, every time - see cores.py
    if _model is None or _ckpt != ckpt:
        from ._dbnet.DBNet_resnet34 import TextDetection
        m = TextDetection()
        sd = torch.load(ckpt, map_location="cpu", weights_only=False)
        m.load_state_dict(sd["model"] if "model" in sd else sd)
        m.eval()
        m.to(memory_format=torch.channels_last)
        _model, _ckpt = m, ckpt
    return _model


def _raw(bgr, ckpt, detect_size=DETECT_SIZE, smooth=True, rgb=None):
    import torch
    from ._dbnet import imgproc
    if rgb is None:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if smooth:
            rgb = cv2.bilateralFilter(rgb, 17, 80, 80)
    small, ratio, _s, _pw, _ph = imgproc.resize_aspect_ratio(
        rgb, detect_size, cv2.INTER_LINEAR, mag_ratio=1)
    x = imgproc.normalizeMeanVariance(small)
    x = torch.from_numpy(x).permute(2, 0, 1)[None].contiguous(
        memory_format=torch.channels_last)
    with torch.no_grad():
        db, mask = model(ckpt)(x)
    return db.numpy(), small.shape[0], small.shape[1], 1.0 / ratio


def _one_way(bgr, ckpt, detect_size, text_thresh, box_thresh, unclip, cap,
             rgb=None):
    from ._dbnet import dbnet_utils
    db, sh, sw, back = _raw(bgr, ckpt, detect_size, rgb=rgb)
    det = dbnet_utils.SegDetectorRepresenter(text_thresh, box_thresh,
                                             unclip_ratio=unclip)
    boxes, _scores = det({"shape": [(sh, sw)]}, db)
    boxes = boxes[0]
    H, W = bgr.shape[:2]
    out = []
    if getattr(boxes, "size", 0) == 0:
        return out
    for q in boxes:
        a = np.asarray(q, dtype=float).reshape(-1, 2) * back
        x0, y0 = a.min(0)
        x1, y1 = a.max(0)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(W, int(x1)), min(H, int(y1))
        if x1 <= x0 or y1 <= y0:
            continue
        if cap and (x1 - x0) * (y1 - y0) > cap * W * H:
            continue
        out.append([x0, y0, x1, y1])
    return out


def pieces(img: np.ndarray, ckpt: str, detect_size: int = DETECT_SIZE,
           text_thresh: float = TEXT_THRESH, box_thresh: float = BOX_THRESH,
           unclip: float = UNCLIP, cap: float = CAP,
           both_ways: bool = True) -> list:
    """Every shape of writing DB can find, read forwards and backwards.

    `both_ways=False` is the single pass, kept because it is half the time and
    a series with no reversed captions in it loses nothing by it. The default
    is both, because a caption that is never found is not a thing anybody
    notices is missing.
    """
    # The bilateral filter is the expensive part of the preprocessing and it
    # is done ONCE for both passes. It commutes with inversion exactly:
    # the spatial kernel does not look at the pixels at all, and the range
    # kernel is |I_p - I_q|, which is unchanged by 255 - I. Checked over a
    # page rather than argued: max difference 1, mean 0.0000.
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb = cv2.bilateralFilter(rgb, 17, 80, 80)
    out = _one_way(img, ckpt, detect_size, text_thresh, box_thresh, unclip,
                   cap, rgb=rgb)
    if both_ways:
        out += _one_way(255 - img, ckpt, detect_size, text_thresh, box_thresh,
                        unclip, cap, rgb=255 - rgb)
    return out
