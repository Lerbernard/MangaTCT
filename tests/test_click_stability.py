"""Typesetting that does not move when you look at it.

Selecting a block of text and clicking away used to shift the words. The reason
was that the two halves of the program disagreed about where a line goes:

* the FITTER centres every line on the balloon's own width at that line's
  height, and hangs the block from the top of its ink;
* the OVERRIDE path — the one a hand edit takes — centred the whole block in
  the bounding RECTANGLE of the balloon.

On any balloon that is not a rectangle those are different places. And merely
clicking a block wrote an override, so the two answers were swapped on a click
that changed not one character. `place_lines` closes the gap: an override that
nobody has actually moved is placed by the fitter's own arithmetic.

The other half is the clamp. `enforce_bounds` used to hold lines inside the
bounding rectangle, which on a spiky or lobed balloon reaches out over the
artwork — so a line could pass the check while sitting almost entirely on the
picture. It now holds each line inside the narrowest chord the balloon actually
offers across that line's own ink.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion
from mangatl.typeset import (TypesetConfig, anchor_to_frame, enforce_bounds,
                             fit_region, layout_from_override, place_lines)


def _cfg(**kw):
    c = TypesetConfig()
    c.font_path = c.font_path or ""
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _diamond(h=260, w=260, cx=130, cy=130, r=110):
    """A balloon whose width changes a lot with height.

    A rectangle would hide every bug here: the point is that the middle is wide
    and the top and bottom are narrow, so centring in the bounding box and
    centring on the chord give different answers.
    """
    m = np.zeros((h, w), np.uint8)
    pts = np.array([[cx, cy - r], [cx + r, cy], [cx, cy + r], [cx - r, cy]])
    cv2.fillPoly(m, [pts.astype(np.int32)], 255)
    return m


def _lopsided(h=300, w=300):
    """A balloon with a big lobe on one side, like a shout with a spike.

    Its bounding rectangle takes in a lot of paper the balloon never covers,
    which is exactly the room the old clamp let typesetting wander into.
    """
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (110, 150), (80, 90), 0, 0, 360, 255, -1)
    cv2.circle(m, (235, 60), 34, 255, -1)          # the far lobe
    return m


def _region(mask, kind="bubble"):
    ys, xs = np.nonzero(mask)
    r = TextRegion(id=1, bbox=(int(xs.min()), int(ys.min()),
                               int(xs.max() - xs.min() + 1),
                               int(ys.max() - ys.min() + 1)), kind=kind)
    r.bubble_mask = mask
    return r


# --------------------------------------------------------------- placement

def test_untouched_override_lands_where_the_fitter_put_it():
    """Click a block, click away: the words must not have moved.

    The override carries the same lines at the same size, and nobody dragged
    anything, so it has to resolve to the very same positions the fit produced.

    What the page carries is the fit AFTER `anchor_to_frame` — `typeset_page`
    and the editor's preview both hand the fitter's result through it, because
    the block a person clicks on is a box and the words in it are spaced evenly
    down that box. Comparing against a bare `fit_region` asks the override to
    reproduce spacing that is never what ends up on the page, and the two
    agreed only as long as the rounding happened to land the same way.
    """
    cfg = _cfg()
    r = _region(_diamond())
    r.dst_text = "THERE IS A GHOST IN THE HOUSE TONIGHT"
    lay = anchor_to_frame(fit_region(r, cfg), cfg)
    assert lay.lines and lay.line_origins

    # what closing the canvas editor writes when nothing was typed
    r.layout_override = {"lines": list(lay.lines),
                         "font_size": int(lay.font_size),
                         "leading": float(lay.leading),
                         "font": lay.font_path or "",
                         "locked": True}
    again = layout_from_override(r, cfg)
    assert again is not None
    assert again.line_origins == lay.line_origins


def test_place_lines_centres_on_the_chord_not_the_rectangle():
    """A narrow line high in a diamond sits on the diamond, not mid-rectangle.

    Every line here is centred left-to-right on the same axis, so this checks
    the thing that actually differs: each line must land on balloon pixels.
    """
    cfg = _cfg()
    m = _lopsided()
    origins = place_lines(["HELLO", "THERE"], m, cfg, 18, 1.1)
    assert origins is not None
    for (x, y) in origins:
        assert m[int(y), int(x)] > 0, f"line origin {(x, y)} is off the balloon"


def test_a_hand_moved_block_is_left_where_it_was_put():
    """Dragging is the one case that DOES override the fitter's placement."""
    cfg = _cfg()
    r = _region(_diamond())
    r.dst_text = "MOVE ME"
    lay = fit_region(r, cfg)
    base = {"lines": list(lay.lines), "font_size": int(lay.font_size),
            "leading": float(lay.leading), "font": lay.font_path or "",
            "locked": True}
    r.layout_override = dict(base)
    still = layout_from_override(r, cfg)
    r.layout_override = dict(base, dx=25, dy=-14)
    moved = layout_from_override(r, cfg)
    assert moved.line_origins != still.line_origins


# ------------------------------------------------------------------- clamp

def test_clamp_keeps_lines_on_the_balloon_not_just_in_its_box():
    """A line shoved at the bounding box's edge comes back onto the paper.

    The far lobe is what makes the bounding rectangle much wider than the
    balloon at mid height. Pushed out there, the old clamp was satisfied — the
    line was inside the rectangle — and the words sat on the artwork.
    """
    cfg = _cfg()
    m = _lopsided()
    r = _region(m)
    r.dst_text = "OVER HERE"
    lay = fit_region(r, cfg)
    assert lay.lines

    xs = np.nonzero(m)[1]
    far_right = int(xs.max())
    lay.line_origins = [(far_right, y) for (_x, y) in lay.line_origins]
    fixed = enforce_bounds(r, lay, cfg)
    for (x, y) in fixed.line_origins:
        assert m[int(y), int(x)] > 0, f"clamped to {(x, y)}, which is off-balloon"
        assert x < far_right, "the clamp did not pull the line back at all"


def test_clamp_leaves_a_line_that_is_already_inside_alone():
    """Nothing that already fits gets nudged."""
    cfg = _cfg()
    r = _region(_diamond())
    r.dst_text = "FINE"
    lay = fit_region(r, cfg)
    before = list(lay.line_origins)
    after = enforce_bounds(r, lay, cfg).line_origins
    assert after == before
