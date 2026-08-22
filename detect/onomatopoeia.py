"""DB++ finetuned on comic onomatopoeia -- the only model here that was
trained on SOUND EFFECTS and nothing else.

Naver's COO dataset, 61,465 hand-labelled onomatopoeia polygons, ECCV 2022,
and DB++ was the top of their own leaderboard. It is the one detector that
does not read type: 13% of the dialogue on lee's Japanese chapter and 70% of
the painted sound effects, which is exactly the shape of a specialist.

It is also the reason the boxes have to be grouped in TWO POOLS. lee, of the
first merge: *"the weld are horible, sfx and outide ext shodu not be welded
and bubble text shoud only weled to text very close to them"*. He is right,
and the split is free here because the pools are already separate: what this
module returns is a sound effect and what `dbtext` returns is writing, and no
reach is ever allowed to cross between them. Measured over 23 pages that
takes the boxes that swallow two texts from six to two, and both of the two
left are one sound effect that the ground truth had cut in half.

## SIDE = 640, and it was 1152

The authors' eval short side for finetuned models is 1152, which is what this
was run at first. lee's pages are 960 wide, so that was *upscaling* them.
Measured over the chapter:

    SIDE=1152   80 boxes   8.43 s/page
    SIDE= 640   80 boxes   2.38 s/page

The same eighty boxes in a third of the time -- and the junk halves, because
the upscaled pass was inventing shapes out of screentone.

The checkpoint says what it is: ResNet-50 bottlenecks (3,4,6,3), **modulated**
deformable convolution in layers 2-4 (27 offset channels = 18 offsets + 9
mask), and a decoder carrying `concat_attention`, the Adaptive Scale Fusion
module that makes it DB++ rather than DB. Their repo wants a CUDA extension
for the deformable conv; torchvision has had the operator for years, so
`_dbpp/dcnshim.py` stands in for it.
"""
import os

import cv2
import numpy as np

# The preprocessing from their `experiments/seg_detector/*.yaml`: ImageNet
# mean, BGR order, no division by std.
MEAN = np.array([122.67891434, 116.66876762, 104.00698793], np.float32)
SIDE = 640           # see the docstring -- their 1152 upscales a manga page
THRESH = 0.3         # probability above which a pixel is paint
BOX_THRESH = 0.5     # mean probability inside a shape before it is kept
UNCLIP = 1.5

_model = None
_ckpt = None


def why_not(path: str) -> str:
    if not path:
        return "no sound-effect weights are set"
    if not os.path.isfile(path):
        return "sound-effect weights are not at %s" % path
    try:
        import torch  # noqa: F401
    except Exception:
        return "pytorch is not installed -- run `pip install torch`"
    try:
        import pyclipper  # noqa: F401
        import shapely  # noqa: F401
    except Exception:
        return ("pyclipper and shapely are needed to unshrink DB's polygons "
                "-- run `pip install pyclipper shapely`")
    return ""


def available(path: str) -> bool:
    return not why_not(path)


def _build():
    import torch.nn as nn
    from ._dbpp import resnet as R
    from ._dbpp.seg_detector_asf import SegSpatialScaleDetector

    class DBPP(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = R.deformable_resnet50(pretrained=False)
            # `scale_channel_spatial`, not the module default
            # `scale_spatial`. The checkpoint carries
            # `enhanced_attention.channel_wise`, which only the
            # channel-spatial variant has; built the other way those two
            # tensors load into nothing and a piece of the attention runs on
            # whatever it was initialised with.
            self.decoder = SegSpatialScaleDetector(
                in_channels=[256, 512, 1024, 2048], k=50, adaptive=True,
                attention_type="scale_channel_spatial")

        def forward(self, x):
            return self.decoder(self.backbone(x))

    return DBPP()


def model(ckpt: str):
    global _model, _ckpt
    import torch
    if _model is None or _ckpt != ckpt:
        m = _build()
        sd = torch.load(ckpt, map_location="cpu", weights_only=False)
        sd = {k.replace("model.module.", ""): v for k, v in sd.items()}
        m.load_state_dict(sd, strict=False)
        m.eval()
        _model, _ckpt = m, ckpt
    return _model


def prob(bgr: np.ndarray, ckpt: str, side: int = SIDE) -> np.ndarray:
    """The probability map, at page size."""
    import torch
    H, W = bgr.shape[:2]
    r = side / float(min(H, W))
    nh = int(round(H * r / 32)) * 32
    nw = int(round(W * r / 32)) * 32
    im = cv2.resize(bgr, (max(32, nw), max(32, nh)))
    x = torch.from_numpy(
        ((im.astype(np.float32) - MEAN) / 255.0).transpose(2, 0, 1)[None])
    with torch.no_grad():
        y = model(ckpt)(x)
    p = y[0, 0].numpy() if torch.is_tensor(y) else np.asarray(y)[0, 0]
    return cv2.resize(p, (W, H), interpolation=cv2.INTER_LINEAR)


def pieces(img: np.ndarray, ckpt: str, side: int = SIDE,
           thresh: float = THRESH, box_thresh: float = BOX_THRESH,
           unclip: float = UNCLIP) -> list:
    """Sound effects as `[x0, y0, x1, y1]`, the same contract as
    `craft.pieces` and `dbtext.pieces`."""
    import pyclipper
    from shapely.geometry import Polygon
    p = prob(img, ckpt, side)
    H, W = p.shape[:2]
    cnts, _h = cv2.findContours((p > thresh).astype(np.uint8),
                                cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        if len(c) < 4:
            continue
        poly = cv2.approxPolyDP(c, 0.002 * cv2.arcLength(c, True),
                                True).reshape(-1, 2)
        if poly.shape[0] < 4:
            continue
        m = np.zeros(p.shape, np.uint8)
        cv2.fillPoly(m, [poly.astype(np.int32)], 1)
        if not m.any() or float(p[m > 0].mean()) < box_thresh:
            continue
        shp = Polygon(poly)
        if shp.length <= 0:
            continue
        off = pyclipper.PyclipperOffset()
        off.AddPath([tuple(q) for q in poly], pyclipper.JT_ROUND,
                    pyclipper.ET_CLOSEDPOLYGON)
        big = off.Execute(shp.area * unclip / shp.length)
        if not big:
            continue
        a = np.asarray(big[0], float).reshape(-1, 2)
        x0, y0 = a.min(0)
        x1, y1 = a.max(0)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(W, int(x1)), min(H, int(y1))
        if x1 - x0 > 3 and y1 - y0 > 3:
            out.append([x0, y0, x1, y1])
    return out
