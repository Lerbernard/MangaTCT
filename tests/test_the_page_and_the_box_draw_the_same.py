# -*- coding: utf-8 -*-
"""One ink, two places: the page overlay and the box you type into.

lee, with a photograph of a sound effect whose brown O had painted itself
over the orange A beside it: *"this is still hapeening use any mean to fix
it i want it GONE"*, then *"I MEAN THE COLOR SLIPING TO OTHER LETTER"*, and
then the diagnosis, which was right: *"the letter themselft are not getting
coloed but teh background is and teh text is going out of teh bound"*.

Measured, it was this, in the mirror under the caret:

    trunf 'R'   x=366        ts (outline)  x=366        tf (fill)  x=446

The FILL span is an in-flow element - that is how a run comes to be the
width of its own letters - and the mirror put an invisible sizer in front
of it. So the fill started one whole run to the right: the outline in the
right place, the colour on the next letter along.

## Why there was a second copy of the ink at all

The five layers - shadow, glow, outline, fill, inner glow - were written
TWICE: `inked` inside `drawText` for the page, `stack` inside
`editInkMirror` for the box, 146 lines saying one thing in two spellings,
with the positioning as classes on one side and inline styles on the other.
Every change had to be made in both, and the times it was made in one are
the times the page and the box disagreed. lee has now reported that
disagreement in four different shapes.

There is one `inkRun` now, and one `paintRamps` for the gradients - which
the mirror could not call before, so an outline gradient did not show in
the box at all and a fill gradient faded differently there than on the
page.

What this file guards is the agreement itself: the same runs, in the same
order, at the same offsets, with every layer of every run sitting on top of
its own letters and not beside them.
"""
import json
import os
import shutil
import threading

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import mangatl
from where import PKG

FDIR = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                    "fonts")
SFX_FONT = os.path.join(FDIR, "LuckiestGuy-Regular.ttf")
LINE = "ROAA"

# lee's own block: a sound effect, one letter resized and recoloured, one
# letter recoloured, a fat white rim on all of it.
SPANS = [{"s": 1, "e": 2, "st": {"fg": "#7a3b0e", "font_size": 96}},
         {"s": 3, "e": 4, "st": {"fg": "#1428ff"}}]


def _project(root, spans=None, extra=None):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((360, 900, 3), 238, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    ov = {"lines": [LINE], "locked": True, "font": SFX_FONT,
          "font_size": 72, "stroke": 5, "fg": "#ff7a00", "edge": "#ffffff",
          "spans": SPANS if spans is None else spans}
    ov.update(extra or {})
    p.pages[0].regions = [{
        "id": 1, "kind": "sfx", "order": 0,
        "bbox": [60, 60, 780, 220], "bubble_bbox": [60, 60, 780, 220],
        "polygon": [[60, 60], [840, 60], [840, 280], [60, 280]],
        "src_text": "x", "dst_text": LINE, "confidence": .9, "manual": True,
        "layout_override": ov}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


def _serve(p):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    editor.do_typeset(p, 0, reset=False)
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _open(pg, base):
    browserpool = pytest.importorskip("browserpool")
    pg.goto(base + "/", wait_until="load")
    browserpool.ready(pg)
    pg.evaluate("toggleExact(false)")
    pg.evaluate("setTab('edit'); setView('typeset')")
    browserpool.settled(pg)
    pg.wait_for_timeout(900)


# Every inked layer in a container, with where it actually landed. `.ts` is
# the outline, `.tf` the fill, `.tsh` a shadow or glow pass, `.tg` the
# inner glow - the five `inkRun` builds.
_LAYERS = """(root)=>{
  const el = document.querySelector(root);
  if(!el) return null;
  const out = [];
  el.querySelectorAll('.ts,.tf,.tsh,.tg').forEach(sp=>{
    const r = sp.getBoundingClientRect();
    if(r.width < 1) return;
    const run = sp.closest('.trunf,.trun,.tl,.ink');
    const q = run ? run.getBoundingClientRect() : r;
    out.push({cls: sp.className.split(' ')[0],
              text: (sp.textContent||''),
              dx: +(r.x - q.x).toFixed(1),
              dy: +(r.y - q.y).toFixed(1),
              w: Math.round(r.width)});
  });
  return out;}"""


def test_every_layer_of_a_run_sits_on_its_own_letters():
    """THE BUG lee photographed, as one number: the fill's offset inside
    its run. It was a whole run's width; it has to be zero.

    Checked in the box you type into AND on the page, because the two used
    to build their ink from different code and only one of them was wrong.
    """
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_ink_same")
    p = _project(root)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)

            page = pg.evaluate(_LAYERS, "#overlay .tgrp")
            assert page, "nothing was drawn on the page"
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(800)
            box = pg.evaluate(_LAYERS, "#canvasEditRim")
            assert box, "the mirror under the caret drew nothing"

            for where, layers in (("page", page), ("box", box)):
                for l in layers:
                    # A shadow or a glow is DELIBERATELY offset - that is
                    # what a drop shadow is. Everything else is on the
                    # letters or it is on the wrong letters.
                    if l["cls"] == "tsh":
                        continue
                    assert abs(l["dx"]) < 1.5, \
                        "%s: the %s of %r starts %.1fpx into its run - " \
                        "that is the colour landing on the next letter" \
                        % (where, l["cls"], l["text"][:12], l["dx"])
                    assert abs(l["dy"]) < 1.5, \
                        "%s: the %s of %r is %.1fpx below its run" \
                        % (where, l["cls"], l["text"][:12], l["dy"])
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_box_lays_the_runs_out_the_way_the_page_does():
    """Same runs, same order, same widths, same gaps between them. The
    box is positioned on the block's frame and the page on the block's
    origins, so the two are compared as SHAPES - each run's offset from
    the first, and its width."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_ink_shape")
    p = _project(root)
    srv, was, base = _serve(p)
    probe = """(root)=>{
      const el = document.querySelector(root);
      if(!el) return null;
      const runs = [...el.querySelectorAll('.trunf')];
      if(!runs.length) return [];
      const x0 = runs[0].getBoundingClientRect().x;
      return runs.map(r=>{const q=r.getBoundingClientRect();
        return {t:(r.textContent||'').slice(0,4),
                off:+(q.x-x0).toFixed(1), w:+q.width.toFixed(1)};});}"""
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            page = pg.evaluate(probe, "#overlay .tgrp")
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(800)
            box = pg.evaluate(probe, "#canvasEditRim")
            assert page and box, (page, box)
            assert len(page) == len(box), \
                "the page draws %d runs and the box %d" % (len(page),
                                                           len(box))
            for a, b in zip(page, box):
                assert abs(a["off"] - b["off"]) < 1.5, \
                    "run %r starts %.1fpx along on the page and %.1f in " \
                    "the box" % (a["t"], a["off"], b["off"])
                assert abs(a["w"] - b["w"]) < 1.5, \
                    "run %r is %.1fpx wide on the page and %.1f in the box" \
                    % (a["t"], a["w"], b["w"])
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_there_is_one_ink_and_one_ramp_and_both_places_use_them():
    """The absence that keeps the two from drifting again. `inked` and
    `stack` were the same five layers written twice; the fill gradient was
    a block-wide ramp on the page and an inline per-run gradient in the
    box, which is a different fade."""
    js = (PKG / "static" / "js" / "typesetting.js").read_text(encoding="utf8")
    assert "function inkRun(" in js
    assert "function paintRamps(" in js
    # the mirror asks for both
    body = js.split("function editInkMirror(ta, r){")[1].split("\n}")[0]
    assert "inkRun(" in body, "the box builds its own ink again"
    assert "paintRamps(" in body, "the box paints its own gradients again"
    # ...and so does the page
    dt = js.split("function drawText(){")[1].split("\nfunction ")[0]
    assert "inkRun(" in dt and "paintRamps(" in dt
    # the old second copy is gone for good
    assert "const at=(txt,css)=>{" not in js, \
        "the mirror's own inline-styled inker is back"


def test_a_gradient_fades_the_same_way_in_both():
    """An outline gradient did not show in the box AT ALL before this, and
    a fill gradient faded per-run there against per-block on the page."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_ink_grad")
    # WITH a range on it, because that is when the mirror owns the fill.
    # On a block with no ranges the box's own text is still showing the
    # fill and the mirror must not paint a second copy over it - the
    # gradient there is `placeEditor`'s, and its own test guards it.
    p = _project(root, spans=[{"s": 1, "e": 2, "st": {"fg": "#7a3b0e"}}],
                 extra={"fg1": "#ff0000", "fg2": "#0000ff", "grad_angle": 90,
                        "edge1": "#00ff00", "edge2": "#ffff00",
                        "edge_angle": 90})
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            grab = """(root)=>{
                const el=document.querySelector(root);
                if(!el) return null;
                const tf=el.querySelector('.tf.grad');
                return {ramp: tf ? (tf.style.backgroundImage||'') : '',
                        bands: el.querySelectorAll('.ts.egrad,.eband').length};
              }"""
            # the page FIRST: `drawText` leaves the block being typed into
            # to the mirror, so there is no group on the page once the
            # editor is open
            page = pg.evaluate(grab, "#overlay .tgrp")
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(900)
            got = {"page": page, "box": pg.evaluate(grab, "#canvasEditRim")}
            assert got["box"], "no mirror to compare against"
            assert got["page"], "nothing was drawn on the page"
            assert "linear-gradient" in (got["box"]["ramp"] or ""), \
                "the box paints no fill ramp: %r" % got["box"]
            # THE SAME FADE, not merely some fade: same colours, same
            # angle, same two stops. Compared as numbers because the page
            # measures its lines and the box measures its rows, and the
            # two round a shared answer differently in the last pixel.
            import re as _re
            def parts(css):
                nums = [float(x) for x in _re.findall(r"(-?[\d.]+)px", css)]
                cols = _re.findall(r"rgb\([^)]*\)|#[0-9a-fA-F]{3,8}", css)
                deg = _re.findall(r"(-?[\d.]+)deg", css)
                return nums, cols, deg
            pn, pc, pd = parts(got["page"]["ramp"])
            bn, bc, bd = parts(got["box"]["ramp"])
            assert pc == bc and pd == bd, \
                "different colours or angle:\n  page %s\n   box %s" \
                % (got["page"]["ramp"], got["box"]["ramp"])
            assert len(pn) == len(bn) and all(abs(a - b) <= 2
                                              for a, b in zip(pn, bn)), \
                "the fade differs between the page and the box:\n  page %s\n"\
                "   box %s" % (got["page"]["ramp"], got["box"]["ramp"])
            assert got["box"]["bands"] > 0, \
                "an outline gradient still does not reach the box"
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
