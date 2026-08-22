"""Sound effects: read the angle the original was drawn at, and typeset the
English at that same angle.

One public entry point for the measurement:

    frame = sfx_frame(gray, box, text_mask=None)   # geometry of the original ink

The English is always set as one word, however the Japanese ran. Japanese
stacks down a column because it is written that way; English is not, and a
column of English capitals reads as a ransom note rather than a sound. So the
column's geometry is used for the size and the lean, not for the shape: the
word may run as far as the effect was long, stand as tall as it was wide, and
leans exactly as far off its own natural axis as the original leaned off
theirs.

`sfx_frame` returns an `SfxFrame`: the centre of the original ink, its length
along the axis it was written on, its width across that axis, the angle of that
axis in degrees, and whether the axis is closer to vertical than to horizontal.

Nothing here draws anything or knows about the project's fitting code -- it is
measurement only, so it can be dropped into typeset.py and called from
fit_region for kind == "sfx".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

# An axis this straight is not worth rotating for -- scan noise alone moves it
# a degree or two, and a rotated paste always costs a little sharpness.
DEAD_ZONE_DEG = 4.0
# Past this the estimate is more likely to be a bad read than a bold typesetter.
MAX_TILT_DEG = 40.0
# Below this the ink cloud is round enough that its "long axis" is meaningless.
MIN_ELONGATION = 1.5
# A stroke is drawn with a brush; screentone dots and hatching are not.
GLYPH_STROKE = 3
# A break longer than the effect is wide means the box holds more than one thing.
SPLIT_GAP = 1.0


@dataclass
class SfxFrame:
    cx: float
    cy: float
    length: float      # extent of the ink along its own axis
    width: float       # extent across it
    angle: float       # degrees, 0 = the axis runs along the page's own axis
    vertical: bool     # the axis is closer to vertical than to horizontal
    elongation: float  # how much the measurement is worth trusting
    ink: int           # ink pixels the estimate was built from
    trusted: bool = True  # False when the angle was refused rather than read

    @property
    def tilt(self) -> float:
        """Rotation to apply to a block laid out on the page's own axes."""
        return self.angle


def ink_mask(gray: np.ndarray, box, text_mask=None,
             pad_frac: float = 0.45) -> np.ndarray:
    """Ink inside `box`, as a uint8 0/255 mask the size of the box.

    Prefers the detector's own mask. Without one it thresholds both ways and
    keeps whichever side is the minority, which is what typesetting is against
    both a white bubble and a black panel.

    The threshold is taken on a padded crop, and any mark that carries on well
    outside the box is dropped before the box is cut back out -- a panel border
    or a bubble tail running through the region is not part of the effect and
    would drag its angle straight onto the diagonal of whatever crosses it.
    """
    H, W = gray.shape[:2]
    x, y, w, h = [int(v) for v in box]
    if w <= 0 or h <= 0:
        return np.zeros((max(h, 1), max(w, 1)), np.uint8)

    if text_mask is not None:
        m = np.asarray(text_mask)
        if m.shape[:2] != (h, w):
            m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
        m = ((m > 0).astype(np.uint8)) * 255
        if int(m.sum()) > 0:
            return _letterlike(m)

    px = int(max(8, w * pad_frac))
    py = int(max(8, h * pad_frac))
    X0, Y0 = max(0, x - px), max(0, y - py)
    X1, Y1 = min(W, x + w + px), min(H, y + h + py)
    crop = gray[Y0:Y1, X0:X1]
    if crop.size == 0:
        return np.zeros((h, w), np.uint8)

    blur = cv2.GaussianBlur(crop, (3, 3), 0)
    _, dark = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    light = 255 - dark
    m = dark if dark.mean() <= light.mean() else light
    m = _letterlike(m)
    inner = (x - X0, y - Y0, w, h)
    m = _drop_intruders(m, inner)
    return m[inner[1]:inner[1] + h, inner[0]:inner[0] + w]


# A mark this much of itself outside the box belongs to the artwork, not the
# effect. Same rule and same figure as inpaint.glyphs_only.
OUTSIDE_SHARE = 0.35


def _drop_intruders(mask: np.ndarray, inner) -> np.ndarray:
    """Remove marks that mostly live outside the region."""
    x, y, w, h = inner
    n, lab = cv2.connectedComponents((mask > 0).astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    box_only = np.zeros_like(lab)
    box_only[y:y + h, x:x + w] = lab[y:y + h, x:x + w]
    total = np.bincount(lab.ravel(), minlength=n)
    inside = np.bincount(box_only.ravel(), minlength=n)
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(total > 0, inside / np.maximum(total, 1), 0.0)
    keep = np.nonzero(share >= (1.0 - OUTSIDE_SHARE))[0]
    keep = keep[keep > 0]
    if len(keep) == 0:
        return mask
    return (np.isin(lab, keep).astype(np.uint8)) * 255


def _letterlike(mask: np.ndarray) -> np.ndarray:
    """Drop specks: single pixels, jpeg dirt, the finest halftone.

    Deliberately gentler than inpaint._letterlike. That one is deciding what to
    erase and can afford to lose a dakuten; this one is deciding which way the
    typesetting runs, and a stroke thinned by a rotation is still a stroke. The
    real defence against tone is the size filter in _substantial(), because a
    dot is small next to a glyph however thick it is.
    """
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (GLYPH_STROKE,) * 2)
    thick = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    if int(thick.sum()) == 0:
        return mask
    n, lab = cv2.connectedComponents((mask > 0).astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    keep = np.unique(lab[thick > 0])
    out = np.isin(lab, keep[keep > 0])
    return (out.astype(np.uint8)) * 255


def _substantial(mask: np.ndarray):
    """Marks big enough to be part of the typesetting, and their centroids.

    A glyph is large next to a tone dot whatever the two are made of, so this
    is the filter that keeps a field of dots from steering the answer.
    """
    n, lab, stats, cent = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask, np.zeros((0, 2))
    areas = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
    keep = areas >= max(6.0, 0.08 * float(areas.max()))
    ids = np.arange(1, n)[keep]
    if len(ids) == 0:
        return mask, cent[1:]
    out = np.isin(lab, ids)
    return (out.astype(np.uint8)) * 255, cent[1:][keep].astype(np.float64)


def _line_angle(a: float) -> float:
    """An axis is a line, not an arrow: fold it into (-90, 90]."""
    while a <= -90.0:
        a += 180.0
    while a > 90.0:
        a -= 180.0
    return a


def _rect_angle(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if len(xs) < 8:
        return None, 1.0
    pts = np.stack([xs, ys], 1).astype(np.float32)
    (_, (w, h), a) = cv2.minAreaRect(pts)
    if w < h:
        a += 90.0
        w, h = h, w
    return _line_angle(a), float(w) / max(float(h), 1e-6)


def _axis(mask: np.ndarray):
    """Unit vector along the ink's long axis, and how elongated it is.

    The long side of the tightest rotated box around the ink. The principal
    axis of the ink was tried alongside it as a cross-check, on the theory that
    the two fail differently -- the box follows one stray mark a long way, the
    axis is pulled around by a single heavy glyph. Across every case built for
    it the two never disagreed by more than 1.3 degrees, including the ones
    designed to break them, so the second reading was dropped rather than
    shipped as untested insurance. What actually catches a box holding two
    things is the gap test in sfx_frame.
    """
    ra, aspect = _rect_angle(mask)
    if ra is None:
        return None, 1.0
    u = np.array([math.cos(math.radians(ra)), math.sin(math.radians(ra))])
    return u, float(aspect)


def sfx_frame(gray: np.ndarray, box, text_mask=None) -> SfxFrame:
    """Measure the original sound effect: where it sits, how it runs, how far."""
    x, y, w, h = [int(v) for v in box]
    m, cent = _substantial(ink_mask(gray, box, text_mask))
    ys, xs = np.nonzero(m)
    ink = int(len(xs))

    if ink < 8:
        # Nothing to measure. Fall back to the box itself.
        return SfxFrame(x + w / 2.0, y + h / 2.0, float(max(w, h)),
                        float(min(w, h)), 0.0, h >= w, 1.0, ink, False)

    u, elong = _axis(m)
    pxy = np.stack([xs, ys], 1).astype(np.float64)

    if u is None or elong < MIN_ELONGATION:
        # Round enough that the axis is a guess; trust the box's own shape.
        vertical = h >= w
        u = np.array([0.0, 1.0]) if vertical else np.array([1.0, 0.0])
        elong = 1.0

    v = np.array([-u[1], u[0]])
    along = pxy @ u
    across = pxy @ v
    lo_a, hi_a = float(along.min()), float(along.max())
    lo_c, hi_c = float(across.min()), float(across.max())
    mid = u * ((lo_a + hi_a) / 2.0) + v * ((lo_c + hi_c) / 2.0)

    length = hi_a - lo_a
    width = hi_c - lo_c

    # Angle of the axis, as a line, in (-90, 90].
    ang = _line_angle(math.degrees(math.atan2(float(u[1]), float(u[0]))))

    vertical = abs(ang) > 45.0
    tilt = (ang - 90.0) if ang > 45.0 else (ang + 90.0) if ang < -45.0 else ang

    trusted = elong >= MIN_ELONGATION
    if _longest_gap(along) > width * SPLIT_GAP:
        # A break longer than the effect is wide means the box is holding two
        # effects, or an effect and something else. The line drawn between two
        # far-apart clusters is not an angle anybody wrote at.
        trusted = False
    if not trusted or abs(tilt) < DEAD_ZONE_DEG:
        tilt = 0.0
    tilt = max(-MAX_TILT_DEG, min(MAX_TILT_DEG, tilt))

    return SfxFrame(x + float(mid[0]), y + float(mid[1]),
                    length, width, tilt, vertical, float(elong), ink, trusted)


def _longest_gap(along: np.ndarray) -> float:
    """The longest stretch of the axis with no ink on it at all."""
    p = along - along.min()
    n = int(p.max()) + 2
    if n <= 2:
        return 0.0
    occ = np.zeros(n, bool)
    occ[p.astype(int)] = True
    idx = np.flatnonzero(occ)
    if len(idx) < 2:
        return 0.0
    return float(np.max(np.diff(idx)) - 1)


# --------------------------------------------------------------------------
# Choosing a size

# Kept as the dataclass's line gap so a layout stays self-describing; with one
# line there is nothing between.
STACK_GAP = 0.10
# A sound effect is allowed to breach its own box a little; it always did.
OVER_WIDE = 1.35
OVER_LONG = 1.02


@dataclass
class SfxLayout:
    lines: list       # the lines to draw, in order along the axis
    size: int         # type size
    gap: int          # pixels between one line's ink and the next
    angle: float      # degrees to rotate the finished block by
    cx: float         # where its centre goes on the page
    cy: float
    fitted: bool      # False when even the floor size had to be forced in


def fit_sfx(frame: SfxFrame, text: str, measure, lo: int = 8, hi: int = 160,
            gap_frac: float = STACK_GAP) -> SfxLayout:
    """Largest size whose word fits the original's own footprint.

    `measure(size, s) -> (w, h)` returns the INK extent of `s` at that size --
    pass typeset's own measurement in, so the answer matches what the renderer
    will actually put down. Nothing here opens a font.

    The word is one line whichever way the Japanese ran, so `length` and
    `width` are read as "along the writing" and "across it" rather than as
    height and breadth. A column that was tall and narrow therefore lets the
    English run as far as it was tall and stand as high as it was narrow -
    same ink, same weight on the page, turned to read the way English reads.
    """
    lines = [(text or "").strip()]

    for size in range(int(hi), int(lo) - 1, -1):
        gap = max(1, int(round(size * gap_frac)))
        w, h = measure(size, lines[0])
        if w <= frame.length * OVER_LONG and h <= frame.width * OVER_WIDE:
            return SfxLayout(lines, size, gap, frame.angle, frame.cx, frame.cy,
                             True)

    size = int(lo)
    return SfxLayout(lines, size, max(1, int(round(size * gap_frac))),
                     frame.angle, frame.cx, frame.cy, False)
