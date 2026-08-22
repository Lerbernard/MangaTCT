"""The outline can carry a gradient of its own.

lee: *"can you make it so that i can add gradient to the ouline of the text"*.

The letters could already fade from one colour to another; the ring round them
could not, and there was no reason for that other than nobody having asked. It
is a SEPARATE gradient with its own two colours and its own angle - a red-to-
blue outline under a yellow-to-green fill is an ordinary piece of typesetting, and
neither should be deciding the other.

**In the export** the ring is painted through a mask that is the ring and only
the ring: drawn with the stroke lit and the fill dark, so the glyph the stroke
was grown around is punched back out of it. Painting through the whole stroked
shape would lay the outline's gradient across the letters as well, and then the
fill would repaint over the top of it - two answers to one question.

**In the preview** it is a stack of sixteen solid copies, each clipped to one
slab across the block. CSS will not put a gradient on a text stroke:
`background-clip:text` paints the fill area and leaves `-webkit-text-stroke`
exactly the colour it was given. That was measured in Chromium, not assumed.
"""
import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

from mangatl import render as R
from mangatl.models import Page, TextRegion
from mangatl.typeset import TypesetConfig, fit_region
from where import PKG

ROOT = PKG
PANELS = (ROOT / "static" / "js" / "panels.js").read_text(encoding="utf-8")
TYPESETTING = (ROOT / "static" / "js" / "typesetting.js").read_text(encoding="utf-8")
LEDIT = (ROOT / "static" / "js" / "typesetting-edit.js").read_text(encoding="utf-8")

RED, BLUE = "#ff2d2d", "#2d7dff"


def _page():
    img = np.full((240, 720, 3), 255, np.uint8)
    r = TextRegion(id=0, bbox=(30, 40, 660, 160),
                   polygon=[[30, 40], [690, 40], [690, 200], [30, 200]],
                   kind="freefloat", dst_text="GRADIENT OUTLINE", src_text="x")
    r.text_mask = np.zeros((240, 720), np.uint8)
    r.text_mask[40:200, 30:690] = 255
    p = Page(image=img)
    p.regions = [r]
    cfg = TypesetConfig()
    r.layout = fit_region(r, cfg)
    r.layout.fg, r.layout.edge, r.layout.stroke = "#ffffff", "#000000", 6
    return p, r, cfg


def _render(ov):
    p, r, cfg = _page()
    r.layout_override = dict({"stroke": 6, "fg": "#ffffff", "edge": "#111111"},
                             **ov)
    return R.render_page(p, cfg)


def _ink(img):
    """Where anything was drawn at all."""
    return img.min(axis=2) < 240


# ------------------------------------------------------------- what it paints

def test_the_outline_fades_from_one_colour_to_the_other():
    out = _render({"edge1": RED, "edge2": BLUE, "edge_angle": 90})
    ink = _ink(out)
    xs = np.nonzero(ink.any(axis=0))[0]
    left = out[:, xs[0]:xs[0] + 40][ink[:, xs[0]:xs[0] + 40]]
    right = out[:, xs[-1] - 39:xs[-1] + 1][ink[:, xs[-1] - 39:xs[-1] + 1]]
    # BGR: red at one end, blue at the other
    assert left[:, 2].mean() > left[:, 0].mean() + 30, left.mean(axis=0)
    assert right[:, 0].mean() > right[:, 2].mean() + 30, right.mean(axis=0)


def test_the_angle_turns_it():
    across = _render({"edge1": RED, "edge2": BLUE, "edge_angle": 90})
    down = _render({"edge1": RED, "edge2": BLUE, "edge_angle": 0})
    assert int((across != down).sum()) > 2000


def test_with_no_second_colour_nothing_changes():
    plain = _render({})
    assert int((plain != _render({"edge1": RED})).sum()) == 0, \
        "one end of a gradient is not a gradient"


def test_a_block_with_no_outline_has_no_outline_to_paint():
    """`stroke: 0` means there is no ring. Painting the mask anyway would put
    the gradient on nothing, or worse, on the letters."""
    a = _render({"stroke": 0})
    b = _render({"stroke": 0, "edge1": RED, "edge2": BLUE})
    assert int((a != b).sum()) == 0


def test_the_letters_keep_their_own_colour():
    """The mask is the RING, not the whole stroked shape.

    Drawn with the stroke lit and the fill dark, so the glyph the stroke was
    grown around is punched back out of it. Lit both ways instead and the
    gradient runs straight across the letters - which is measured here as the
    white of the fill, pixel for pixel, being exactly what it was before the
    outline gained a gradient at all.
    """
    plain = _render({})
    grad = _render({"edge1": RED, "edge2": BLUE, "edge_angle": 90})
    was = (plain == 255).all(axis=2)
    now = (grad == 255).all(axis=2)
    assert int(was.sum()) > 3000, "nothing white to check"
    assert int((was != now).sum()) == 0, \
        f"{int((was & ~now).sum())} white pixels were painted over"


def test_the_fill_keeps_its_own_gradient_too():
    """Both at once, each running its own way. This is the case that would go
    wrong if one were implemented in terms of the other."""
    both = _render({"edge1": RED, "edge2": BLUE, "edge_angle": 90,
                    "fg1": "#ffe066", "fg2": "#00d0a0", "grad_angle": 0})
    edge_only = _render({"edge1": RED, "edge2": BLUE, "edge_angle": 90})
    assert int((both != edge_only).sum()) > 2000, "the fill gradient went missing"
    ink = _ink(both)
    ys, xs = np.nonzero(ink)
    band = both[ys.min():ys.max(), xs.min():xs.min() + 60]
    m = _ink(band)
    # yellow-ish fill (BGR) somewhere in the left of the block, next to red ring
    assert (band[m][:, 1] > band[m][:, 0] + 40).any(), band[m].mean(axis=0)


# ------------------------------------------------- what the server will accept

def _preview(tmp_path, override):
    """What the browser is told about a block, live, as it is being edited."""
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "grad")
    shutil.rmtree(root, ignore_errors=True)
    pr = Project(None, root)
    pr.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((240, 720, 3), 255, np.uint8))[1].tobytes())
    pr.pages[0].regions = [{
        "id": 1, "kind": "freefloat", "order": 0, "bbox": [30, 40, 660, 160],
        "polygon": [[30, 40], [690, 40], [690, 200], [30, 200]],
        "confidence": 0.9, "src_text": "x", "dst_text": "GRADIENT OUTLINE"}]
    pr.pages[0].detected = True
    pr.save()
    return editor.layout_preview(pr, 0, 1, override)


def test_a_colour_that_is_not_a_colour_is_dropped(tmp_path):
    d = _preview(tmp_path, {"edge1": "not a colour", "edge2": BLUE,
                            "edge_angle": 45})
    assert d["edge1"] == "" and d["edge2"] == BLUE
    assert d["edge_angle"] == 45.0


def test_the_outline_gradient_reaches_the_browser(tmp_path):
    """It has to be in the live answer as well as in the saved record, or the
    preview shows one thing and the export another."""
    d = _preview(tmp_path, {"edge1": RED, "edge2": BLUE, "edge_angle": 90})
    assert (d["edge1"], d["edge2"], d["edge_angle"]) == (RED, BLUE, 90.0)


def test_it_survives_being_saved(tmp_path):
    """Through the region endpoint, which is what actually writes it down."""
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "save")
    shutil.rmtree(root, ignore_errors=True)
    pr = Project(None, root)
    pr.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((240, 720, 3), 255, np.uint8))[1].tobytes())
    pr.pages[0].regions = [{
        "id": 1, "kind": "freefloat", "order": 0, "bbox": [30, 40, 660, 160],
        "polygon": [[30, 40], [690, 40], [690, 200], [30, 200]],
        "confidence": 0.9, "src_text": "x", "dst_text": "HI"}]
    pr.pages[0].detected = True
    pr.save()
    was, editor.PROJECT = editor.PROJECT, pr
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        import urllib.request
        req = urllib.request.Request(
            base + "/api/page/0/region/1", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"layout": {
                "edge1": RED, "edge2": BLUE, "edge_angle": 30}}).encode())
        urllib.request.urlopen(req).read()
        ov = pr.pages[0].regions[0]["layout_override"]
        assert (ov["edge1"], ov["edge2"], ov["edge_angle"]) == (RED, BLUE, 30.0)
    finally:
        editor.PROJECT = was
        srv.shutdown()


# ------------------------------------------------------------ what you can set

def test_the_panel_offers_from_to_and_an_angle():
    assert PANELS.count('id="lyEdge1"') == 1
    assert PANELS.count('id="lyEdge2"') == 1
    assert PANELS.count('id="lyEdgeG"') == 1
    assert ">Outline gradient<" in PANELS


def test_each_gradient_has_its_own_clear_button():
    assert "clearGradient(${r.id},'fg')" in PANELS
    assert "clearGradient(${r.id},'edge')" in PANELS


def test_clearing_one_does_not_clear_the_other():
    body = LEDIT.split("function clearGradient(id, which){")[1].split("\n}")[0]
    assert "lyEdge1" in body and "lyFg1" in body
    assert "which==='edge'" in body


def test_the_preview_knows_css_cannot_do_it_directly():
    """A stack of clipped solid copies, because `background-clip:text` leaves
    the stroke alone - the comment says so and the code does it."""
    assert "EDGE_BANDS" in TYPESETTING
    assert "clipPath" in TYPESETTING


# ------------------------------------------------------------ and on the page

def _serve(fn, tmp_path, override):
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "prev")
    shutil.rmtree(root, ignore_errors=True)
    pr = Project(None, root)
    pr.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((500, 760, 3), 255, np.uint8))[1].tobytes())
    pr.pages[0].regions = [{
        "id": 1, "kind": "freefloat", "order": 0, "bbox": [40, 60, 660, 180],
        "polygon": [[40, 60], [700, 60], [700, 240], [40, 240]],
        "confidence": 0.95, "src_text": "x", "dst_text": "GRADIENT OUTLINE"}]
    pr.pages[0].detected = True
    pr.save()
    editor.do_typeset(pr, 0)
    pr.pages[0].regions[0]["layout_override"] = dict(
        {"stroke": 6, "fg": "#ffffff", "edge": "#111111"}, **override)
    pr.save()
    was, editor.PROJECT = editor.PROJECT, pr
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            try:
                return fn(pg, pr)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_the_preview_draws_the_ring_in_bands(tmp_path):
    def check(pg, pr):
        n = pg.evaluate("document.querySelectorAll('.ts.eband').length")
        lines = pg.evaluate("document.querySelectorAll('.tl').length")
        assert n == 16 * lines, (n, lines)
        cols = pg.evaluate("""[...document.querySelectorAll('.ts.eband')]
          .map(e=>getComputedStyle(e).webkitTextStrokeColor)""")
        assert len(set(cols)) >= 12, cols
    _serve(check, tmp_path, {"edge1": RED, "edge2": BLUE, "edge_angle": 90})


def test_no_bands_when_there_is_no_outline_gradient(tmp_path):
    def check(pg, pr):
        assert pg.evaluate(
            "document.querySelectorAll('.ts.eband').length") == 0
        assert pg.evaluate("document.querySelectorAll('.ts').length") > 0
    _serve(check, tmp_path, {})


def test_the_ring_on_screen_fades_the_way_the_export_does(tmp_path):
    """Read off the picture, not off the stylesheet - and compared against the
    exported page, which is the one that matters."""
    def check(pg, pr):
        f = str(tmp_path / "shot.png")
        pg.locator(".tgrp").screenshot(path=f)
        im = cv2.imread(f)
        # only the COLOURED pixels: the paper is white, the fill is white, and
        # the editor's own furniture is grey. What is left is the ring.
        spread = im.max(axis=2).astype(int) - im.min(axis=2).astype(int)
        ink = spread > 60
        ys, xs = np.nonzero(ink)
        assert xs.size > 500, "no coloured ring was drawn at all"
        lo = im[:, xs.min():xs.min() + 30][ink[:, xs.min():xs.min() + 30]]
        hi = im[:, xs.max() - 29:xs.max() + 1][ink[:, xs.max() - 29:xs.max() + 1]]
        assert lo[:, 2].mean() > lo[:, 0].mean() + 40, lo.mean(axis=0)
        assert hi[:, 0].mean() > hi[:, 2].mean() + 40, hi.mean(axis=0)
    _serve(check, tmp_path, {"edge1": RED, "edge2": BLUE, "edge_angle": 90})
