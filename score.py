"""Score how much a detected region looks like a block of text rather than art.

Japanese typesetting has a strong signature: many similarly-sized ink components,
consistent stroke width, and alignment along a column (vertical) or row
(horizontal). Art has neither. This does not replace a trained detector, but it
lets the editor show weak detections differently instead of burying the user in
boxes to delete.
"""
from __future__ import annotations

import cv2
import numpy as np

from .models import TextRegion


def _stroke_width(binary: np.ndarray) -> tuple[float, float]:
    """Mean and CV of stroke width, via distance transform ridge values."""
    if binary.sum() == 0:
        return 0.0, 1.0
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
    vals = dist[dist > 0.6]
    if vals.size < 10:
        return 0.0, 1.0
    m = float(vals.mean())
    return m, float(vals.std() / max(1e-6, m))


def text_likeness(region: TextRegion) -> float:
    """0..1. Above ~0.55 is confidently text; below ~0.35 is probably art."""
    m = region.text_mask
    if m is None:
        return 0.0
    x, y, w, h = region.bbox
    sub = (m[y:y + h, x:x + w] > 0).astype(np.uint8)
    if sub.sum() < 20:
        return 0.0

    n, _, stats, cents = cv2.connectedComponentsWithStats(sub, 8)
    comps = [(stats[i], cents[i]) for i in range(1, n) if stats[i, 4] >= 5]
    if len(comps) < 2:
        return 0.15

    # 1. component count — text is many small marks
    count_s = min(1.0, len(comps) / 8.0)

    # 2. size consistency — glyphs are similar in size, art debris is not
    sizes = np.array([max(s[2], s[3]) for s, _ in comps], dtype=np.float32)
    cv_size = float(sizes.std() / max(1e-6, sizes.mean()))
    size_s = float(np.clip(1.0 - cv_size, 0.0, 1.0))

    # 3. alignment — vertical text shares an x centre, horizontal a y centre
    cx = np.array([c[0] for _, c in comps], dtype=np.float32)
    cy = np.array([c[1] for _, c in comps], dtype=np.float32)
    span = max(1.0, float(max(w, h)))
    align = 1.0 - min(float(cx.std()), float(cy.std())) / span
    align_s = float(np.clip(align, 0.0, 1.0))

    # 4. stroke-width consistency — typesetting is drawn with one nib
    _, cv_stroke = _stroke_width(sub)
    stroke_s = float(np.clip(1.0 - cv_stroke, 0.0, 1.0))

    return float(
        0.20 * count_s + 0.28 * size_s + 0.30 * align_s + 0.22 * stroke_s
    )


def score_regions(regions: list[TextRegion]) -> None:
    for r in regions:
        r.confidence = round(text_likeness(r), 3)
        if r.confidence < 0.35:
            r.flagged = (r.flagged or "") + " weak detection: may be art"
