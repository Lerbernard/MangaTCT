"""Curved typesetting.

lee: *"Add text curve"*.

`curve` is one number: the whole angle, in degrees, that the line subtends. That
makes it mean the same thing on "OH" as on "OH NO, LOOK OUT!!" and at any size —
the radius is worked out from the arc length, `R = length / angle`. Positive
arches up like a rainbow, negative sags, 0 is straight.

Three things had to be got right, and each of them was wrong first:

1. **The bend must not move the line.** Hung from its middle, an arch sinks by
   its whole sagitta — a third of the line's length at 140 degrees — and the
   words walk out of the box. Half the sagitta comes back off, so the middle
   rides as far up as the ends ride down.
2. **A letter is not its own bounding box.** `ImageDraw.text` cannot rotate, so
   each letter is stamped as a turned mask; centring each mask on the arc put
   every comma and descender on the line's middle. The offset has to be measured
   from the same anchor the straight path draws from — the middle of the
   letter's advance, on the middle of the line.
3. **The outline of the whole line goes down before any fill does**, or each
   letter's outline eats into the face of the one before it.

The browser draws the same curve with one span per letter, so there are two
copies of the arithmetic. `test_the_two_arcs_agree` runs both over the same line
with the same advances and compares every letter's place, which is the only way
that stays true.
"""
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from PIL import ImageFont

from mangatl import render
from mangatl.models import Page, TextRegion
from mangatl.typeset import (FITTING_KEYS, TypesetConfig, default_font_path,
                             typeset_page)
from where import PKG

JS = PKG / "static" / "js"
H, W = 300, 620
LINE = "OH NO, LOOK OUT!!"
BASE = {"fg": "#ffffff", "edge": "#000000", "locked": True}


def _draw(ov, text=LINE):
    img = np.full((H, W, 3), 245, np.uint8)
    ink = np.zeros((H, W), np.uint8)
    cv2.rectangle(ink, (40, 60), (W - 40, H - 60), 255, -1)
    r = TextRegion(id=0, bbox=(40, 60, W - 80, H - 120), kind="sfx",
                   text_mask=ink)
    r.dst_text, r.order = text, 0
    r.layout_override = dict(ov)
    page = Page(image=img, source_path="c")
    page.regions = [r]
    page.clean_plate = img.copy()
    cfg = TypesetConfig(font_path=default_font_path())
    cfg.min_font, cfg.max_font = 34, 44
    typeset_page(page, cfg)
    out = render.render_page(page, cfg)
    return out, r


def _ink(im):
    """Where the typesetting is: anything that is not the flat page."""
    return np.abs(im.astype(int) - 245).sum(2) > 40


def _rows(im):
    ys, xs = np.nonzero(_ink(im))
    return ys, xs


# ------------------------------------------------------------------ the shape

def test_a_curve_bends_the_line_into_an_arch():
    flat, _ = _draw(BASE)
    arch, _ = _draw(dict(BASE, curve=90))
    fy, fx = _rows(flat)
    ay, ax = _rows(arch)
    assert fy.size and ay.size
    # a straight line is a band; an arch is much taller
    assert (ay.max() - ay.min()) > (fy.max() - fy.min()) * 1.8, \
        "the line did not bend"
    # and the top of the ink is found in the MIDDLE for an arch
    mid = (ax > np.percentile(ax, 40)) & (ax < np.percentile(ax, 60))
    ends = (ax < np.percentile(ax, 12)) | (ax > np.percentile(ax, 88))
    assert ay[mid].min() < ay[ends].min() - 10, \
        "the middle of the arch is not its highest point"


def test_a_negative_curve_sags_the_other_way():
    sag, _ = _draw(dict(BASE, curve=-90))
    ys, xs = _rows(sag)
    mid = (xs > np.percentile(xs, 40)) & (xs < np.percentile(xs, 60))
    ends = (xs < np.percentile(xs, 12)) | (xs > np.percentile(xs, 88))
    assert ys[mid].max() > ys[ends].max() + 10, \
        "a negative curve should hang, not arch"


def test_a_bend_keeps_the_line_where_the_fitter_put_it():
    """The whole point of taking half the sagitta back off. Without it a 140
    degree arch sinks by a third of the line's length."""
    flat, _ = _draw(BASE)
    fy, _ = _rows(flat)
    centre = (fy.min() + fy.max()) / 2.0
    for curve in (45, 90, 140, -90):
        ys, _ = _rows(_draw(dict(BASE, curve=curve))[0])
        c = (ys.min() + ys.max()) / 2.0
        assert abs(c - centre) < 0.16 * H, \
            f"curve {curve} moved the line by {c - centre:.0f}px"


def test_curving_keeps_every_letter():
    """A turned letter is stamped as its own mask, which is exactly the sort of
    change that loses the last one or drops the punctuation."""
    flat, _ = _draw(BASE)
    for curve in (30, 90, 140, -60):
        arch, _ = _draw(dict(BASE, curve=curve))
        a, b = int(_ink(flat).sum()), int(_ink(arch).sum())
        assert 0.75 * a < b < 1.35 * a, \
            f"curve {curve}: {b} ink pixels against {a} straight"


def test_a_comma_stays_under_the_line_and_a_capital_stays_on_it():
    """Centring each letter's own box on the arc lifted every comma onto the
    baseline, which is the bug this pins: the vertical spread of the ink has to
    survive being curved."""
    flat, _ = _draw(BASE, "Ojg,.")
    arch, _ = _draw(dict(BASE, curve=8), "Ojg,.")   # barely bent
    fy, _ = _rows(flat)
    ay, _ = _rows(arch)
    assert abs((ay.max() - ay.min()) - (fy.max() - fy.min())) < 6, \
        "a hair of curve changed the height of the line — the anchor is wrong"


def test_zero_curve_is_the_straight_path_untouched():
    a, _ = _draw(BASE)
    b, _ = _draw(dict(BASE, curve=0))
    assert np.array_equal(a, b)


def test_a_curve_carries_the_outline_and_the_glow_round_with_it():
    """Every pass that draws the line — the shadow, the glow silhouette, the
    letters, the gradient mask, the inner-glow mask — has to be given the same
    curve, or one of them stays straight and the block comes out doubled."""
    plain, _ = _draw(dict(BASE, curve=90))
    glowed, _ = _draw(dict(BASE, curve=90, glow="#ff3b30", glow_size=9))
    ink = _ink(plain)
    lit = (np.abs(plain.astype(int) - glowed.astype(int)).sum(2) > 25) & ~ink
    ys, xs = np.nonzero(lit)
    assert ys.size > 400, "no glow"
    # the glow follows an arch too: its highest point is in the middle
    mid = (xs > np.percentile(xs, 40)) & (xs < np.percentile(xs, 60))
    ends = (xs < np.percentile(xs, 12)) | (xs > np.percentile(xs, 88))
    assert ys[mid].min() < ys[ends].min() - 8, "the glow stayed straight"


def test_a_curve_survives_pressing_typeset_again():
    assert "curve" not in FITTING_KEYS
    _, r = _draw(dict(BASE, curve=75, dx=5))
    page = Page(image=np.full((H, W, 3), 245, np.uint8), source_path="c")
    page.regions = [r]
    page.clean_plate = page.image.copy()
    cfg = TypesetConfig(font_path=default_font_path())
    typeset_page(page, cfg, redo=True)
    assert (r.layout_override or {}).get("curve") == 75
    assert "dx" not in (r.layout_override or {})


# ------------------------------------------------------- the arithmetic itself

def test_the_arc_is_the_arc_it_says_it_is():
    f = ImageFont.truetype(default_font_path(), 40)
    places = render.arc_places(LINE, f, 0.0, 90.0, 300.0, 150.0)
    assert places and len(places) == len(LINE)
    # the tangent runs from -half the angle to +half the angle
    assert abs(places[0][2] - -45) < 6 and abs(places[-1][2] - 45) < 6
    # every letter is the same distance from the centre of the circle
    total = sum(f.getlength(c) for c in LINE)
    R = total / math.radians(90)
    sag = R * (1 - math.cos(math.radians(45)))
    cx, cy = 300.0, 150.0 + R - sag / 2
    for x, y, _, _, _ in places:
        assert abs(math.hypot(x - cx, y - cy) - R) < 0.75


def test_a_bigger_angle_is_a_tighter_curve():
    f = ImageFont.truetype(default_font_path(), 40)
    spread = []
    for curve in (30, 120):
        p = render.arc_places(LINE, f, 0.0, float(curve), 300.0, 150.0)
        spread.append(max(y for _, y, _, _, _ in p)
                      - min(y for _, y, _, _, _ in p))
    assert spread[1] > spread[0] * 2.5, spread


def test_no_curve_means_no_places():
    f = ImageFont.truetype(default_font_path(), 40)
    assert render.arc_places(LINE, f, 0.0, 0.0, 0.0, 0.0) is None
    assert render.arc_places("", f, 0.0, 90.0, 0.0, 0.0) is None


def test_the_two_arcs_agree():
    """The editor and the exporter each walk the arc themselves. They have to
    land in the same places, or the preview is a guess."""
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    f = ImageFont.truetype(default_font_path(), 36)
    spec = {"line": LINE, "size": 36, "lspace": 1.5, "curve": 85.0,
            "x": 310.0, "y": 160.0,
            "widths": {ch: f.getlength(ch) for ch in set(LINE)}}
    want = render.arc_places(LINE, f, spec["lspace"], spec["curve"],
                             spec["x"], spec["y"])
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(spec, fh)
    try:
        out = subprocess.run(
            ["node", os.path.join("tests", "ui", "arc_places.test.js"), path],
            cwd=root, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stdout + out.stderr
        got = json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        os.remove(path)
    assert len(got) == len(want)
    for (gx, gy, gdeg, gch), (wx, wy, wdeg, wch, _) in zip(got, want):
        assert gch == wch
        assert abs(gx - wx) < 0.01, f"{gch}: x {gx} vs {wx}"
        assert abs(gy - wy) < 0.01, f"{gch}: y {gy} vs {wy}"
        assert abs(gdeg - wdeg) < 0.01, f"{gch}: angle {gdeg} vs {wdeg}"


# --------------------------------------------------------------- the plumbing

def test_the_panel_the_patch_and_the_preview_all_carry_the_curve():
    panels = (JS / "panels.js").read_text(encoding="utf8")
    assert 'id="lyCurve"' in panels
    edit = (JS / "typesetting-edit.js").read_text(encoding="utf8")
    assert "curve:$('lyCurve')" in edit.replace(" ", "")
    assert "curve:+(j.curve||0)" in edit.replace(" ", "")
    lt = (JS / "typesetting.js").read_text(encoding="utf8")
    assert "function arcPlaces(" in lt
    assert "tlcurve" in lt
    from mangatl import editor
    src = __import__("inspect").getsource(editor.Handler.do_POST)
    assert '"curve": max(-180.0, min(180.0, float(' in src
    prev = __import__("inspect").getsource(editor.layout_preview)
    assert '"curve": float(o.get("curve") or 0)' in prev
