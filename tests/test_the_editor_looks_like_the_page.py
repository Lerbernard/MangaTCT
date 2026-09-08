# -*- coding: utf-8 -*-
"""Every effect, drawn twice, and the two pictures put side by side.

lee: *"i want you to make sure tha all teh dit effct acculy show uo on the
ediyot live a quick and when iiexport they shoul loo likw what it does in the
editor"*.

The editor and the exporter are two renderers. The exporter draws with PIL onto
the page; the browser draws with CSS over a picture of it, because it has no
page to look at and cannot wait on a round trip for every keystroke. Two
renderers of one thing drift, and every place they have drifted so far was
found by somebody looking at a screenshot and saying *this is not what I set*.

This looks instead. One bubble, one word, and for each effect in turn:

* the override is POSTed, so the export has it;
* the browser is handed the page back the way opening a page hands it over,
  and draws from that - no panel, no typing, so what is measured is what the
  app itself would draw;
* the page is screenshotted at zoom 1, clipped to the artwork, and `/render/0`
  is fetched - the actual export.

What is compared is not the two pictures. CSS anti-aliases differently from
PIL and always will, so a pixel comparison would only ever measure that. What
is compared is **what each effect CHANGED**: the pixels that differ from the
same renderer's own plain version. Two renderers that agree about an effect
change the same pixels, whatever they do to the edges of the letters.

`IoU` below is the overlap of those two sets over their union, allowing a
best-fit shift of up to six pixels in each direction - because a systematic
one-pixel offset between the two is a fact about text layout, not about the
effect being measured.

## What the numbers said the first time it ran

    fill              0.86     opacity           0.93
    outline           0.88     curve             0.76
    stroke width      0.80     letter spacing    0.83
    fill gradient     0.80     rotate            0.87
    outline gradient  0.88
                              --------------------------------
    no fill (3px)     0.55 -> 0.65    shadow            0.52 -> 0.63
    no fill (6px)     0.41 -> 0.68    outer glow        0.38 -> 0.68
    hollow, glow           0.63    inner glow        0.55
    hollow, inner glow     0.64

The top group is agreement: the residual is the letters' edges, where one
renderer's anti-aliasing is not the other's.

The bottom group is the honest list of where the two still differ, and each has
a reason:

* **A letterform with nothing inside it** was the worst of them and is not any
  more. PIL's `stroke_width` grows OUTWARD from the glyph; `-webkit-text-stroke`
  is CENTRED on it, so half of every pixel went inward, and with nothing behind
  it to cover that half the editor drew a solid letter where the page draws a
  hollow one. CSS cannot knock a glyph body out of a stroke - there is no
  Porter-Duff in `mix-blend-mode` and no inner shadow for text - so the preview
  stops being CSS there and becomes SVG, which has masks: stroke at twice the
  width, take the glyph body out, and what is left is the outward half alone.
  See `typesetting.hollowInk`. 0.41 to 0.68 at six pixels, and the inner glow
  a hollow block gets is drawn INSIDE the hole now rather than on the rim.
* **The shadow** and **the outer glow** are no longer approximated at all:
  the preview draws each as the letters STROKED FAT (`-webkit-text-stroke`,
  the export's PIL `stroke_width`) and GAUSSIAN BLURRED (`filter: blur()`,
  whose length is a standard deviation, the same unit PIL's radius is), in
  the export's own compositing order. The rings of text-shadow copies these
  replaced measured 0.63 and 0.68 here; the silhouettes are the same
  construction on both sides, so what remains is rasteriser rounding. What
  is still true is that a shadow behind a letter is a thin CRESCENT, and
  two crescents thrown by letters a pixel apart overlap poorly however
  right they both are; that number will not reach the top group.
* **The inner glow** is drawn on the outside of the letters in the preview and
  the inside on the page. CSS has no inner shadow for text. It is the one
  place the two deliberately part, and `render_page` says so where it draws it.

The floors below are set under the measured numbers, not at them: this is a
guard against the two drifting APART, not a demand that they converge. Anything
that improves one of the three is welcome to raise its floor.
"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch

cv2 = pytest.importorskip("cv2")

W, H = 520, 300

# A hand-set layout, so the exporter uses these words at this size rather than
# fitting the bubble again - and an outline in a colour that is not the paper,
# so a change to its width is something either renderer can be seen to make.
BASE = {"lines": ["BOOM"], "font_size": 54, "leading": 1.1, "locked": True,
        "fg": "#000000", "edge": "#ff9900", "stroke": 3}

# name, override, the floor under the measured overlap, and why it is not 1.
CASES = [
    ("fill", {"fg": "#c81e3c"}, 0.65),
    ("outline", {"edge": "#1e64c8", "stroke": 6}, 0.65),
    ("stroke width", {"stroke": 9}, 0.60),
    ("fill gradient", {"fg1": "#ff0000", "fg2": "#0000ff",
                       "grad_angle": 0}, 0.60),
    ("outline gradient", {"stroke": 8, "edge1": "#ff0000",
                          "edge2": "#00c800", "edge_angle": 0}, 0.65),
    ("opacity", {"opacity": 35}, 0.70),
    ("curve", {"curve": 60}, 0.55),
    ("letter spacing", {"lspace": 9}, 0.60),
    ("rotate", {"rotate": 20}, 0.65),
    # ...and the three that are known to differ. See the note above.
    ("no fill", {"fg": "#00000000", "stroke": 3}, 0.55),
    ("no fill 6", {"fg": "#00000000", "stroke": 6}, 0.55),
    ("hollow glow", {"fg": "#00000000", "stroke": 3,
                     "glow": "#00c000", "glow_size": 6}, 0.50),
    ("hollow inner glow", {"fg": "#00000000", "stroke": 3,
                           "iglow": "#00c0ff", "iglow_size": 6}, 0.50),
    ("shadow", {"shadow": "#ff00ff", "sh_dist": 8, "sh_blur": 4}, 0.45),
    ("outer glow", {"glow": "#00c000", "glow_size": 10}, 0.50),
    ("inner glow", {"iglow": "#00c0ff", "iglow_size": 8}, 0.35),
]

# `caps` is not an overlap question: it does not add anything to the page, it
# changes what the letters ARE. Two renderers that both apply it draw the word
# the plain page already shows - so the test is that both come back to plain.
SAME_AS_PLAIN = [("caps", {"caps": True, "lines": ["boom"]})]


def _project(root):
    from mangatl.project import Project
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((H, W, 3), 250, np.uint8)
    cv2.ellipse(img, (260, 150), (200, 110), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (260, 150), (200, 110), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [110, 105, 300, 90],
        "bubble_bbox": [60, 40, 400, 220],
        "polygon": [[110, 105], [410, 105], [410, 195], [110, 195]],
        "src_text": "x", "dst_text": "BOOM", "confidence": 0.9,
        "layout_override": dict(BASE),
        "layout": {"lines": ["BOOM"], "font_size": 54, "leading": 1.1,
                   "origins": [[260, 155]], "fg": "#000000",
                   "edge": "#ffffff", "stroke": 2, "font": "",
                   "rotate": 0.0, "frame": [], "fixed": False,
                   "fit_ok": True, "used_compact": False}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    p.pages[0].typeset = True
    return p


def _png(url):
    with urllib.request.urlopen(url) as f:
        buf = np.frombuffer(f.read(), np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def _post(base, ov):
    urllib.request.urlopen(urllib.request.Request(
        base + "/api/page/0/region/1", method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"layout": ov}).encode())).read()


@pytest.fixture(scope="module")
def shot_and_page():
    """Both pictures of every case, taken in one browser session."""
    from mangatl import editor
    p = _project(scratch("_tmp_lookalike"))
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    shots, pages = {}, {}
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 1000},
                             device_scale_factor=1)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset'); showPage(0)")
            browserpool.settled(pg)
            # The picture has to BE there before it can be measured against.
            pg.wait_for_function(
                "()=>{const i=document.getElementById('img');"
                "return i&&i.complete&&i.naturalWidth>0;}", timeout=60000)
            # One page pixel per screen pixel, or every number below is a
            # measurement of the browser's scaler.
            pg.evaluate("zoom=1; fitZoom=1; applyZoom(); drawOverlay();")
            pg.wait_for_timeout(400)
            box = pg.locator("#img").bounding_box()
            assert box and box["height"] > 0, box

            todo = ([("plain", {}, 0)] + CASES
                    + [(n, o, 0) for n, o in SAME_AS_PLAIN])
            for name, ov, _floor in todo:
                full = dict(BASE, **ov)
                _post(base, full)
                # The way OPENING A PAGE hands the boxes over. Poking `r.style`
                # by hand would be measuring the poke.
                pg.evaluate("""async ()=>{
                    const j=await api('/api/page/'+cur, 'GET');
                    setRegions(j.regions);
                    drawOverlay();}""")
                pg.wait_for_timeout(300)
                pg.screenshot(path="/tmp/lookalike.png", clip=box)
                shots[name] = cv2.imread("/tmp/lookalike.png")
                pages[name] = _png(base + "/render/0")
            assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
    return shots, pages


def _changed(a, b):
    """Which pixels this effect moved, on one renderer."""
    return np.abs(a.astype(int) - b.astype(int)).max(2) > 30


def _overlap(db, ds, reach=6):
    """How much the two renderers agree about WHERE the effect landed.

    Best over a small shift, because a systematic pixel of offset between two
    text layouts is not a fact about the effect being measured.
    """
    best = 0.0
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            sh = np.roll(np.roll(db, dy, 0), dx, 1)
            u = int((sh | ds).sum()) or 1
            best = max(best, int((sh & ds).sum()) / u)
    return best


def test_the_two_agree_about_the_plain_page(shot_and_page):
    """Before any effect: the same words in the same place at the same size.

    If this drifts, every number below is measuring the drift instead.
    """
    shots, pages = shot_and_page
    a, b = shots["plain"], pages["plain"]
    assert a.shape == b.shape, (a.shape, b.shape)
    off = int((np.abs(a.astype(int) - b.astype(int)).max(2) > 40).sum())
    assert off < a.shape[0] * a.shape[1] * 0.04, off


@pytest.mark.parametrize("name,ov,floor", CASES)
def test_the_effect_shows_on_both_sides(shot_and_page, name, ov, floor):
    """It DOES something, in both renderers. Half of lee's question is not
    whether they match but whether the editor draws the effect at all."""
    shots, pages = shot_and_page
    db = _changed(shots[name], shots["plain"])
    ds = _changed(pages[name], pages["plain"])
    assert int(db.sum()) > 400, (name, "the editor draws nothing", int(db.sum()))
    assert int(ds.sum()) > 400, (name, "the export draws nothing", int(ds.sum()))


@pytest.mark.parametrize("name,ov,floor", CASES)
def test_the_effect_lands_in_the_same_place(shot_and_page, name, ov, floor):
    shots, pages = shot_and_page
    got = _overlap(_changed(shots[name], shots["plain"]),
                   _changed(pages[name], pages["plain"]))
    assert got >= floor, (name, round(got, 3), floor)


@pytest.mark.parametrize("name,ov", SAME_AS_PLAIN)
def test_what_changes_the_letters_changes_them_on_both_sides(
        shot_and_page, name, ov):
    """`boom` with capitals on is `BOOM`, which is what the plain page already
    says - so each renderer has to come back to its own plain picture. A
    renderer that ignored the switch would draw lowercase and be a long way
    from it."""
    shots, pages = shot_and_page
    for what, got in (("editor", shots), ("export", pages)):
        moved = int(_changed(got[name], got["plain"]).sum())
        assert moved < 300, (what, name, moved)
