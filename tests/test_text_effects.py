"""Outer glow, inner glow and transparency on the typesetting.

lee: *"Make the text Editor better / add outter glow text / Add inner glow text
/ Add transparency text / Add gradient text"*. Gradient text was already there
(`fg1`/`fg2`/`grad_angle`), so this is the other three, built the way the
gradient and the shadow were: override-only keys, read at draw time, mirrored in
the browser's preview, and never touched by the fitter.

What each one is, and why it is not one of the others:

* **Outer glow** is not a shadow with no offset. A shadow is the letters moved
  and blurred; blur a silhouette in place and it stays *inside* the letters and
  never shows past the outline. A glow has to be SPREAD first — drawn with a fat
  stroke — then blurred, then stacked so it is dense enough to read on artwork.
  Photoshop's Size and Spread, under one knob.
* **Inner glow** is light from the letter's own edge, inwards, and it must not
  put a single pixel on the artwork. The measure of "how far in from the edge am
  I" is the glyph mask's blurred inverse, multiplied back by the mask.
* **Transparency** belongs to the whole block — letters, outline, shadow, both
  glows — so it scales one layer's alpha once, after everything has drawn and
  before the balloon clips it. Fading the composited page would fade the art.

The trap all three share is that they have to be added in *six* places or they
half-work: the panel, the patch the panel posts, the save whitelist in
`editor.py` (which rebuilds `layout_override` key by key and silently drops
anything not listed), the preview echo, the browser's own draw, and the export.
The tests below walk that chain end to end.
"""
import json
import os
import shutil
import threading
import urllib.request
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import render
from mangatl.models import Page, TextRegion
from mangatl.project import Project
from mangatl.typeset import (FITTING_KEYS, TypesetConfig, default_font_path,
                             typeset_page)
from scratch import scratch
from where import PKG

CSS = PKG / "static" / "css" / "editor.css"
JS = PKG / "static" / "js"

H, W = 240, 420
TEXT = "BOOM"


def _page(ov, dark=True):
    """One block of typesetting over flat artwork, drawn with `ov` applied."""
    img = np.full((H, W, 3), 30 if dark else 240, np.uint8)
    ink = np.zeros((H, W), np.uint8)
    cv2.rectangle(ink, (60, 90), (W - 60, 160), 255, -1)
    r = TextRegion(id=0, bbox=(60, 90, W - 120, 70), kind="bubble",
                   text_mask=ink)
    r.dst_text, r.order = TEXT, 0
    r.layout_override = dict(ov) if ov else None
    page = Page(image=img, source_path="fx")
    page.regions = [r]
    page.clean_plate = img.copy()
    cfg = TypesetConfig(font_path=default_font_path())
    cfg.min_font, cfg.max_font = 22, 40
    typeset_page(page, cfg)
    return page, cfg, r


def _draw(ov, dark=True):
    page, cfg, r = _page(ov, dark)
    assert r.layout and r.layout.lines, "nothing was laid out to draw"
    return render.render_page(page, cfg)


BASE = {"fg": "#ffffff", "edge": "#000000", "locked": True}


def _glyph_mask(ov=None):
    """Where the letters themselves are — used to tell inside from outside."""
    plain = _draw(BASE)
    empty = _draw(dict(BASE, opacity=0))
    return (np.abs(plain.astype(int) - empty.astype(int)).sum(2) > 12)


# ---------------------------------------------------------------- outer glow

def test_an_outer_glow_reaches_outside_the_letters():
    plain = _draw(BASE)
    glow = _draw(dict(BASE, glow="#ffc400", glow_size=10))
    inside = _glyph_mask()
    out = ~inside
    diff = np.abs(plain.astype(int) - glow.astype(int)).sum(2)
    assert (diff[out] > 20).sum() > 400, "the glow never left the letters"
    # and it is the colour that was asked for: yellow means blue drops away
    px = glow[out][diff[out] > 60].astype(int)
    assert px[:, 2].mean() > px[:, 0].mean() + 40, \
        "what landed outside is not the glow colour"


def test_a_bigger_glow_reaches_further():
    inside = _glyph_mask()
    reach = []
    for size in (5, 20):
        g = _draw(dict(BASE, glow="#ffc400", glow_size=size))
        d = np.abs(_draw(BASE).astype(int) - g.astype(int)).sum(2)
        lit = (d > 20) & ~inside
        reach.append(int(lit.sum()))
    assert reach[1] > reach[0] * 1.6, f"size barely moved it: {reach}"


def test_no_glow_colour_means_no_glow_at_all():
    plain = _draw(BASE)
    for ov in (dict(BASE, glow=""), dict(BASE, glow="not a colour"),
               dict(BASE, glow="#ffc400", glow_size=0)):
        assert np.array_equal(_draw(ov), plain), ov


def test_a_glow_is_not_a_shadow_with_no_offset():
    """The distinction the implementation exists for: a blurred silhouette that
    was never spread stays under the outline and never shows."""
    glow = _draw(dict(BASE, glow="#ffc400", glow_size=10))
    shadow = _draw(dict(BASE, shadow="#ffc400", sh_dist=0, sh_blur=10))
    inside = _glyph_mask()
    plain = _draw(BASE)
    lit = lambda im: int((((np.abs(plain.astype(int) - im.astype(int))
                            .sum(2)) > 20) & ~inside).sum())
    assert lit(glow) > lit(shadow) * 1.5, \
        f"glow {lit(glow)} vs offsetless shadow {lit(shadow)}"


# ---------------------------------------------------------------- inner glow

def test_an_inner_glow_lights_the_letters_and_not_the_page():
    plain = _draw(BASE)
    ig = _draw(dict(BASE, iglow="#ff3b30", iglow_size=7))
    inside = _glyph_mask()
    diff = np.abs(plain.astype(int) - ig.astype(int)).sum(2)
    assert (diff[inside] > 25).sum() > 200, "nothing lit up inside the letters"
    # "not on the artwork" is a claim about the artwork, not about the letters'
    # own antialiased rim: the glow is clipped to the glyph mask, whose edge
    # pixels are part-covered and shared with the outline drawn around them.
    # Anything more than a pixel or two out is a spill.
    art = ~cv2.dilate(inside.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    assert (diff[art] > 25).sum() == 0, \
        "the inner glow spilled onto the artwork"
    px = ig[inside][diff[inside] > 60].astype(int)
    assert px[:, 2].mean() > px[:, 0].mean() + 30, "not the colour asked for"


def _title(ov):
    """One word at title size — 140pt, strokes 25px thick.

    An inner glow is a title effect, and it has to be measured on one. At
    ordinary typesetting size a letter's stroke is about three pixels deep, so a
    glow of any useful size reaches the middle of it and legitimately looks
    like a second colour; there is no falloff to find because there is nowhere
    for it to fall. The behaviour under test is what happens when there IS
    room, which is also the case lee will use it in.
    """
    h, w = 340, 760
    img = np.full((h, w, 3), 30, np.uint8)
    ink = np.zeros((h, w), np.uint8)
    cv2.rectangle(ink, (40, 40), (w - 40, h - 40), 255, -1)
    r = TextRegion(id=0, bbox=(40, 40, w - 80, h - 80), kind="bubble",
                   text_mask=ink)
    r.dst_text, r.order = "BOOM", 0
    r.layout_override = dict(ov)
    page = Page(image=img, source_path="big")
    page.regions = [r]
    page.clean_plate = img.copy()
    cfg = TypesetConfig(font_path=default_font_path())
    cfg.min_font, cfg.max_font = 100, 140
    typeset_page(page, cfg)
    return render.render_page(page, cfg)


def test_an_inner_glow_hugs_the_edge_rather_than_flooding_the_letter():
    """It is light coming IN from the rim, so it has to FALL AWAY inwards.

    Landing evenly would make it a second text colour, which the panel already
    has. Measured as a correlation with depth rather than as a threshold, so
    the test says "it falls away" rather than picking a magic pixel.
    """
    plain = _title(BASE)
    ig = _title(dict(BASE, iglow="#ff3b30", iglow_size=7))
    delta = np.abs(plain.astype(int) - ig.astype(int)).sum(2).astype(float)
    # Depth is measured inside the LETTERS, which here are the white fill —
    # not inside letters-plus-outline. The black outline ring is where the glow
    # is not allowed to go, so counting it as "inside" puts every lit pixel at
    # the same middling depth and flattens the measurement completely.
    fill = plain.min(axis=2) > 200
    dist = cv2.distanceTransform(fill.astype(np.uint8), cv2.DIST_L2, 3)
    take = fill & (delta > 10)
    d, v = dist[take], delta[take]
    assert d.size > 3000, "not enough lit pixels to measure a falloff"
    corr = float(np.corrcoef(d, v)[0, 1])
    assert corr < -0.6, f"the glow does not fall away inwards (r={corr:.2f})"
    near = v[d <= 2].mean()
    far = v[(d >= 6) & (d < 9)].mean()
    assert far < near * 0.5, f"rim {near:.0f} vs 6-9px deep {far:.0f}"


def test_a_bigger_inner_glow_reaches_further_in():
    plain = _title(BASE)
    fill = plain.min(axis=2) > 200
    dist = cv2.distanceTransform(fill.astype(np.uint8), cv2.DIST_L2, 3)
    deep = fill & (dist >= 7)
    reach = []
    for size in (4, 14):
        d = np.abs(plain.astype(int)
                   - _title(dict(BASE, iglow="#ff3b30",
                                 iglow_size=size)).astype(int)).sum(2)
        reach.append(float(d[deep].mean()))
    assert reach[1] > reach[0] * 2, f"size barely moved it: {reach}"


def test_no_inner_glow_colour_means_no_inner_glow():
    plain = _draw(BASE)
    for ov in (dict(BASE, iglow=""), dict(BASE, iglow="#ff3b30", iglow_size=0)):
        assert np.array_equal(_draw(ov), plain), ov


# -------------------------------------------------------------- transparency

def test_opacity_fades_the_whole_block_towards_the_artwork():
    art = _draw(dict(BASE, opacity=0))
    solid = _draw(BASE)
    half = _draw(dict(BASE, opacity=50))
    inside = _glyph_mask()
    d_solid = np.abs(art.astype(int) - solid.astype(int)).sum(2)[inside].mean()
    d_half = np.abs(art.astype(int) - half.astype(int)).sum(2)[inside].mean()
    assert 0.35 * d_solid < d_half < 0.65 * d_solid, \
        f"50% came out at {d_half / d_solid:.2f} of solid"


def test_opacity_zero_leaves_the_page_exactly_as_it_was():
    """Zero is a real answer, and every link in the chain has to carry it —
    `or 100` anywhere turns it into solid ink."""
    page, cfg, r = _page(dict(BASE, opacity=0))
    bare = page.clean_plate.copy()
    assert np.array_equal(render.render_page(page, cfg), bare)


def test_opacity_takes_the_shadow_and_the_glow_with_it():
    """It is the block that fades, not the letters — a solid halo around
    ghosted letters would look like a mistake."""
    art = _draw(dict(BASE, opacity=0))
    full = _draw(dict(BASE, glow="#ffc400", glow_size=10,
                      shadow="#000000", sh_dist=3, sh_blur=4))
    fade = _draw(dict(BASE, glow="#ffc400", glow_size=10,
                      shadow="#000000", sh_dist=3, sh_blur=4, opacity=40))
    out = ~_glyph_mask()
    d_full = np.abs(art.astype(int) - full.astype(int)).sum(2)[out].mean()
    d_fade = np.abs(art.astype(int) - fade.astype(int)).sum(2)[out].mean()
    assert d_fade < d_full * 0.6, "the halo did not fade with the letters"


def test_100_is_the_same_picture_as_saying_nothing():
    assert np.array_equal(_draw(dict(BASE, opacity=100)), _draw(BASE))


# --------------------------------------------------- they are DRESSING, not FIT

def test_the_new_keys_survive_pressing_typeset_again():
    """`clear_fitting` drops what the fitter owns and keeps how the typesetting is
    dressed. A glow is dressing."""
    for k in ("glow", "glow_size", "iglow", "iglow_size", "opacity"):
        assert k not in FITTING_KEYS, k
    page, cfg, r = _page(dict(BASE, glow="#ffc400", glow_size=9,
                              iglow="#ff3b30", iglow_size=5, opacity=70,
                              dx=4, dy=6))
    typeset_page(page, cfg, redo=True)
    ov = r.layout_override or {}
    assert ov.get("glow") == "#ffc400" and ov.get("glow_size") == 9
    assert ov.get("iglow") == "#ff3b30" and ov.get("iglow_size") == 5
    assert ov.get("opacity") == 70
    assert "dx" not in ov and "dy" not in ov, "the fitting keys should be gone"


# ------------------------------------------------------------- over the wire

def _tiny(root):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((160, 240, 3), 240, np.uint8)
    cv2.ellipse(img, (120, 80), (80, 50), 0, 0, 360, (0, 0, 0), 2)
    cv2.putText(img, "A", (108, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 0, "kind": "bubble", "order": 0, "bbox": [50, 40, 140, 80],
        "bubble_bbox": [50, 40, 140, 80],
        "polygon": [[50, 40], [190, 40], [190, 120], [50, 120]],
        "src_text": "テスト", "dst_text": "BOOM", "confidence": 0.9}]
    p.pages[0].detected = True
    return p


def _serve(p):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1], was


def _post(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_the_save_keeps_all_three_effects_and_hands_them_back():
    """`layout_override` is rebuilt key by key on save, so a key nobody listed
    is dropped the moment you click away — and the panel would look like it
    worked until the page was reloaded."""
    from mangatl import editor
    root = scratch("_tmp_fx1")
    p = _tiny(root)
    srv, base, was = _serve(p)
    try:
        _post(base, "/api/page/0/typeset", {})
        _post(base, "/api/page/0/region/0", {"layout": {
            "lines": ["BOOM"], "font_size": 24, "leading": 1.1,
            "glow": "#ffc400", "glow_size": 9,
            "iglow": "#ff3b30", "iglow_size": 5, "opacity": 0}})
        ov = p.pages[0].regions[0]["layout_override"]
        assert ov["glow"] == "#ffc400" and ov["glow_size"] == 9
        assert ov["iglow"] == "#ff3b30" and ov["iglow_size"] == 5
        assert ov["opacity"] == 0, "a transparent block came back solid"
        # and the echo the browser draws from carries them
        lay = p.pages[0].regions[0]["layout"]
        assert lay["glow"] == "#ffc400" and lay["glow_size"] == 9
        assert lay["iglow"] == "#ff3b30" and lay["iglow_size"] == 5
        assert lay["opacity"] == 0
        # …and they survive the round trip to disk. `flush` because small edits
        # are written a moment after they are made now (see Project.save_soon)
        # — what is being tested is the round trip, not how soon it starts.
        p.flush()
        back = Project(None, root)
        back.load()
        ov2 = back.pages[0].regions[0]["layout_override"]
        assert (ov2["glow"], ov2["iglow"], ov2["opacity"]) == \
            ("#ffc400", "#ff3b30", 0)
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_colour_that_is_not_a_colour_is_echoed_as_off():
    from mangatl import editor
    root = scratch("_tmp_fx2")
    p = _tiny(root)
    srv, base, was = _serve(p)
    try:
        _post(base, "/api/page/0/typeset", {})
        _post(base, "/api/page/0/region/0", {"layout": {
            "lines": ["BOOM"], "font_size": 24, "leading": 1.1,
            "glow": "chartreuse", "iglow": "#12345"}})
        lay = p.pages[0].regions[0]["layout"]
        assert lay["glow"] == "" and lay["iglow"] == ""
        assert lay["opacity"] == 100, "opacity should default to solid"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------- the browser

def test_the_preview_shows_the_same_three_effects():
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "text_effects.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "group opacity: 0.6" in out.stdout, out.stdout
    assert "glow stops: 3" in out.stdout, out.stdout
    assert "glow has no offset: true" in out.stdout, out.stdout
    assert "inner rim: true true true" in out.stdout, out.stdout
    assert "rim text matches: true" in out.stdout, out.stdout
    assert ("panel: lyGlow=#ffc400 lyGlowS=8 lyIGlow=#ff3b30 lyIGlowS=6 "
            "lyOpacity=60") in out.stdout, out.stdout
    assert ('patch: {"glow":"#ffc400","glow_size":8,"iglow":"#ff3b30",'
            '"iglow_size":6,"opacity":60}') in out.stdout, out.stdout
    assert "opacity zero: 0" in out.stdout, out.stdout
    assert 'cleared: {"g":"","i":"","gl":"off","il":"off"}' in out.stdout, out.stdout
    assert ('plain: {"shadow":"none","rim":false,"op":"1"}') in out.stdout, \
        out.stdout


# -------------------------------------------------- the two controls lee asked for

def test_the_three_kind_switches_are_switches():
    """lee sent a picture of a toggle: "the first 3 button in the this page be
    this type of button". The every-page tick below them stays a tick — it is a
    modifier, not a thing being switched on and off."""
    js = (JS / "panels.js").read_text(encoding="utf8")
    assert 'type="checkbox" class="sw"' in js
    assert js.count('type="checkbox" class="sw"') == 1
    assert 'id="hideAllPages"' in js
    row = js[js.index('id="hideAllPages"') - 120:js.index('id="hideAllPages"')]
    assert 'class="sw"' not in row, "the every-page tick became a switch too"
    css = CSS.read_text(encoding="utf8")
    assert "input.sw[type=checkbox]" in css
    assert "input.sw[type=checkbox]:checked::after" in css


def test_the_number_boxes_have_a_stepper_of_our_own():
    """This used to PAINT Chromium's native spinner: appearance off, chevrons
    drawn in as a background image. It looked right in Chromium and did nothing
    at all in Firefox, which cannot be styled and simply kept its own cramped
    control — and Firefox is the browser lee works in. lee: *"make teh up and
    down button look better"*.

    Both natives are off now and one is BUILT, out of two real buttons, so
    there is one control and it is the same in every browser. What it does is
    tested in test_side_panel_tidy.py; this is the stylesheet's half.
    """
    css = CSS.read_text(encoding="utf8")
    flat = css.replace(" ", "")
    bare = flat[flat.index("input[type=number]{"):][:200]
    assert "-moz-appearance:textfield" in bare, "Firefox keeps its own"
    block = flat[flat.index("input[type=number]::-webkit-inner-spin-button"):]
    block = block[:block.index("}")]
    assert "display:none" in block, "Chromium keeps its own"
    assert "svg+xml" not in block, "the painted one is still being drawn"
    for want in (".numwrap{", ".numbtn{", ".numbtn.up{", ".numbtn.dn{"):
        assert want in flat, want


def test_the_built_stepper_is_inside_the_box():
    """The buttons are positioned against the wrapper, which takes the size the
    input had, so dressing a box changes nothing about the layout around it."""
    css = CSS.read_text(encoding="utf8").replace(" ", "")
    wrap = css[css.index(".numwrap{"):]
    wrap = wrap[:wrap.index("}")]
    assert "position:relative" in wrap
    btn = css[css.index(".numbtn{"):]
    btn = btn[:btn.index("}")]
    assert "position:absolute" in btn
    assert "right:1px" in btn
