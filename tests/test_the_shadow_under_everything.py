# -*- coding: utf-8 -*-
"""The drop shadow and the outer glow are painted ONCE, under everything.

lee set a fill gradient, an outline gradient and a red drop shadow on one
shout, and the editor showed him a solid red letter: *"i test ted the
gradient and here is what i found"* - both gradients gone, everything the
shadow's colour. The export drew the same block perfectly.

`text-shadow` is an INHERITED property. The shadow-and-glow list was written
on the LINE DIV, so every child span repainted the whole list over whatever
was under it: the outline span, the gradient fill's clipped background (a
background paints under its own element's shadow), the inner-glow rim - and
all sixteen clones an outline gradient splits the ring into. Sixteen coats
of a blurred red shadow is a slab.

The export paints the shadow once, under everything (`render_page`
composites it first, the glow next, the letters after). So does the preview
now: `.tsh` effect spans at the bottom of every letter's stack, and no
`text-shadow` anywhere.

And they are drawn the way the export draws them, not approximated: each
effect is one span of the letters STROKED FAT (`-webkit-text-stroke`, the
export's PIL `stroke_width`) and GAUSSIAN BLURRED (`filter: blur()`, whose
length is a standard deviation - the same unit PIL's radius is). The first
design was a ring of text-shadow copies, and its stacking was
uncalibratable: overlapping tails add up, so lee's orange glow came out
hotter and wider in the editor than on the exported page (*"the color
difference betrween what i pick and what ius exported is bad"*), and a glow
no bigger than the outline hid under it entirely (his SPLAAASH, glow 2 on
outline 2). The glow's stroke carries the outline's width (`stroke +
spread`, the export's own growth) and a chosen glow is drawn twice, an
automatic one once - the export's compositing, move for move.
"""
import os
import re

import pytest

import mangatl


def _js():
    return open(os.path.join(os.path.dirname(os.path.abspath(
        mangatl.__file__)), "static", "js", "typesetting.js"),
        encoding="utf-8").read()


def test_draw_text_writes_no_text_shadow_at_all():
    """The inherited-list design is GONE. A text-shadow on the line div (or
    on any per-letter host) repaints on every child span - that is what
    buried the gradients - and the effects are silhouette spans now, so
    drawText has no business writing text-shadow anywhere.

    The silhouettes themselves moved during the one-ink unification: every
    caller draws through `inkRun` now, so that is where the construction is
    asked for. `drawText`'s own body carrying a copy again would be the
    two-spellings bug on its way back."""
    src = _js()
    fn = src.split("function drawText(")[1].split("\nfunction ")[0]
    sets = re.findall(r"(?:text-shadow:|\.textShadow\s*=)", fn)
    assert not sets, \
        "text-shadow is written inside drawText again - either the " \
        "inherited-shadow bug or an uncalibratable ring is on its way back"
    assert "inkRun(" in fn, "drawText no longer draws through the one ink"
    ink = src.split("function inkRun(")[1].split("\nfunction ")[0]
    assert "-webkit-text-stroke" in ink \
        and "filter:blur(" in ink.replace(" ", ""), \
        "the effects are no longer drawn as stroked-and-blurred silhouettes"
    assert not re.findall(r"text-shadow:", ink), \
        "the one ink writes text-shadow - the inherited-shadow bug"


def test_the_shadow_span_is_first_and_invisible():
    src = _js()
    inked = src.split("function inkRun(")[1].split("\nfunction ")[0]
    assert inked.index("tsh") < inked.index("hollowInk"), \
        "the shadow span is appended after the hollow SVG - it would paint " \
        "over the rim instead of under it"
    assert inked.index("tsh") < inked.index("className='ts'"), \
        "the shadow span is appended after the outline span"
    css = open(os.path.join(os.path.dirname(os.path.abspath(
        mangatl.__file__)), "static", "css", "editor.css"),
        encoding="utf-8").read()
    rule = css.split(".ink .tsh{")[1].split("}")[0]
    assert "transparent" in rule, \
        "the shadow span's own letters would paint over the stack"


def test_the_glow_is_grown_from_the_rim_and_blurred_by_its_size():
    """The export's numbers, on this side: the glow's silhouette is stroked
    `2*(sw+spread)` (centred, so it reaches `stroke + spread` outward, which
    is `render_page`'s `stroke_width=stroke + spread`), and blurred by 0.55
    of the size, which is the export's sigma. A chosen glow is composited
    twice; an automatic one - its alpha under full - once."""
    src = _js()
    # the style is worked out in `runStyle` now - one place for the block's
    # own style and for a span's overlay alike
    dt = src.split("function runStyle(")[1].split("\nfunction ")[0]
    assert re.search(r"strokePx:\s*2\s*\*\s*\(sw\s*\+\s*spread\)", dt), \
        "the glow's stroke no longer carries the outline's width - a glow " \
        "the size of the outline hides under it again"
    assert re.search(r"blur:\s*glS\s*\*\s*0\.55", dt), \
        "the glow's blur parted from the export's sigma"
    assert re.search(r"passes:\s*\(ga\s*>=\s*255\)\s*\?\s*2\s*:\s*1", dt), \
        "a chosen glow is no longer composited twice like the export's"


@pytest.mark.usefixtures()
def test_gradient_and_shadow_share_a_block_on_screen():
    """The block that started this, on an actual screen: fill gradient,
    outline gradient and a red shadow together. The fill span must keep its
    gradient background with nothing painted over it - no span carries a
    text-shadow at all, and the effect spans sit at the bottom of the
    stack."""
    import shutil
    import threading
    from http.server import ThreadingHTTPServer

    import numpy as np
    from scratch import scratch
    browserpool = pytest.importorskip("browserpool")
    cv2 = pytest.importorskip("cv2")
    from mangatl import editor
    from mangatl.project import Project

    root = scratch("_tmp_shadow_under")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((400, 700, 3), 205, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "sfx_big", "order": 0, "bbox": [110, 90, 480, 180],
        "bubble_bbox": [110, 90, 480, 180],
        "polygon": [[110, 90], [590, 90], [590, 270], [110, 270]],
        "src_text": "ひゃ", "dst_text": "Eeeek!", "confidence": 0.95,
        "manual": True,
        "layout_override": {
            "lines": ["Eeeek!"], "font_size": 110, "locked": True,
            "stroke": 5, "shadow": "#ff0003", "sh_dist": 5, "sh_blur": 5,
            "fg1": "#ff8000", "fg2": "#000000", "grad_angle": 0,
            "edge1": "#0029ff", "edge2": "#0eff00", "edge_angle": 0}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    editor.do_typeset(p, 0, reset=False)
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(400)
            got = pg.evaluate("""(()=>{
              const g=document.querySelector('#overlay .tgrp');
              if(!g) return {err:'no block drawn'};
              const first=g.querySelector('.tl').firstElementChild;
              const carriers=[...g.querySelectorAll('*')].filter(el=>{
                const t=getComputedStyle(el).textShadow;
                return t && t!=='none';});
              const tf=g.querySelector('.tf');
              return {first:first?first.className:'',
                      carriers:carriers.map(e=>e.className),
                      bg:tf?getComputedStyle(tf).backgroundImage:'',
                      bands:g.querySelectorAll('.eband').length};})()""")
            assert not got.get("err"), got
            assert got["first"].startswith("tsh"), \
                "the shadow span is not the bottom of the stack: %r" % got
            assert got["carriers"] == [], \
                "something carries a text-shadow - the inherited-shadow " \
                "bug, or the ring design, is back: %r" % got["carriers"]
            assert "linear-gradient" in got["bg"], \
                "the fill gradient never made it onto the fill span"
            assert got["bands"] > 1, \
                "the outline gradient drew no bands"
            assert not errs, errs[:2]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
