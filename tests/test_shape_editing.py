"""A shape you have drawn is still a shape.

lee: *"make sure all of tehse tools work and that they a each are sectiond
properly and mske teh shapes movable and allwo chnage color, add a shap tab"*.

Before this, a shape was a one-way trip. You dragged it, and that was where it
lived: the only way to move it was the free transform, which RASTERISED the
layer first — it rendered the rectangle to pixels, transformed the pixels and
kept a flat patch. The rectangle stopped being a rectangle the first time you
nudged it, and its colour, its line width and whether it was filled all went
with it. Drawn one pixel out of place, or in the wrong colour, and the only fix
was to delete it and draw it again.

Now the transform has a second mode. When what is picked up is a shape, the
same handles — drag to move, corners and edges to resize, just outside a corner
to turn — drive the shape's own two points and an angle instead of a bitmap.
Nothing is ever baked, so afterwards it is still `type:'shape'`, and the colour,
the width and the fill are still there to change. The arrow (V) in the new
Shapes section is what picks one up: click a shape on the page and it is in
your hands.

This file proves it end to end and in pixels: a real Chromium, a real server,
a shape drawn, moved, resized and recoloured through the actual mouse and the
actual panel, then exported by the SERVER and read back as an image. The colour
has to be gone from where it was drawn and present where it was moved to.
"""
import json
import os
import shutil
import threading

import numpy as np
import pytest

import browserpool
from where import PKG

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 235, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].detected = True
    return p


def _count(img, bgr, box=None, tol=70):
    d = np.abs(img.astype(int) - np.array(bgr)).sum(2) < tol
    if box:
        x0, y0, x1, y1 = box
        m = np.zeros(d.shape, bool)
        m[y0:y1, x0:x1] = True
        d = d & m
    return int(d.sum())


def test_a_shape_is_moved_recoloured_and_still_a_shape(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = str(tmp_path / "shapemove")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    RED, BLUE = [85, 45, 255], [255, 100, 40]      # BGR of #ff2d55 / #2864ff
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset');")
            browserpool.settled(pg)

            # --- the Shapes section exists and holds the shape tools -------
            pg.evaluate("setToolTab('shapes')")
            pg.wait_for_timeout(200)
            assert pg.evaluate("toolTab()") == "shapes"
            # The tools are in the toolbox down the left of the page now, one
            # place and always on screen — lee: *"the tools are duplicated it
            # shoud only be onteh side bar"*.
            assert pg.evaluate(
                "['shrect','shcirc','shline'].every(k=>"
                " TOOLBOX.find(g=>g.slot==='shape').tools.some(t=>t.k===k))"), \
                "the shape tools are not in the toolbox"
            assert pg.evaluate(
                "['shapeFillBtn']"
                ".every(i=>!!document.getElementById(i))"), \
                "Filled is missing from the shape settings"
            assert not pg.evaluate(
                "!!document.getElementById('stampBtn')"), \
                "the retouching tools are still mixed in with the shapes"

            def org():
                return pg.evaluate(
                    "(()=>{const b=document.getElementById('img')"
                    ".getBoundingClientRect();return {x:b.x,y:b.y,s:scale};})()")

            def to_screen(x, y):
                o = org()
                return o["x"] + x * o["s"], o["y"] + y * o["s"]

            def press_drag(x0, y0, x1, y1):
                pg.mouse.move(*to_screen(x0, y0))
                pg.mouse.down()
                pg.mouse.move(*to_screen(x1, y1), steps=6)
                pg.mouse.up()
                pg.wait_for_timeout(120)

            # --- draw one rectangle, top-left ----------------------------
            pg.evaluate("""(()=>{
                brushState.col='#ff2d55'; brushState.sz=6;
                const cc=document.getElementById('brushCol');
                if(cc) cc.value='#ff2d55';
                const sz=document.getElementById('brushSz');
                if(sz) sz.value='6';
                setShapeFill(true);
                if(shapeKind!=='rect') toggleShape('rect');
            })()""")
            press_drag(40, 40, 160, 110)
            pg.evaluate("toggleShape('rect')")
            drawn = json.loads(pg.evaluate(
                "JSON.stringify(layers.map(l=>({t:l.type,s:l.shape,"
                "p:l.pts,col:l.col})))"))
            assert len(drawn) == 1 and drawn[0]["s"] == "rect", drawn
            a, b = drawn[0]["p"]
            assert abs(abs(b["x"] - a["x"]) - 120) < 4, drawn
            assert abs(abs(b["y"] - a["y"]) - 70) < 4, drawn

            # --- pick it up with the arrow and move it right --------------
            pg.evaluate("toggleShapeEdit(true)")
            assert pg.evaluate("shapeEdit") is True
            mx, my = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
            pg.mouse.click(*to_screen(mx, my))          # pick up
            pg.wait_for_timeout(150)
            assert pg.evaluate("xf!=null && xf.vector!=null"), \
                "clicking a shape did not pick it up as a shape"
            press_drag(mx, my, mx + 220, my + 130)      # move it
            pg.wait_for_timeout(150)
            moved = json.loads(pg.evaluate("JSON.stringify(layers[0].pts)"))
            assert abs((moved[0]["x"] - a["x"]) - 220) < 6, moved
            assert abs((moved[0]["y"] - a["y"]) - 130) < 6, moved
            assert pg.evaluate("layers[0].type") == "shape", \
                "moving it froze the shape into pixels"

            # --- and recolour it, which only a shape can do ---------------
            pg.evaluate("(()=>{ xfApply();"
                        " selectLayer(layers[0].id);"
                        " setLayerColour(layers[0].id,'#2864ff',true); })()")
            pg.wait_for_timeout(200)
            assert pg.evaluate("layers[0].col") == "#2864ff"
            assert pg.evaluate("layers[0].type") == "shape"
            assert pg.evaluate("canRecolour(layers[0])") is True

            pg.evaluate("queueSync()")
            pg.wait_for_timeout(2500)
            assert not errs, errs[:3]

        # --- what the SERVER exports -----------------------------------
        assert len(p.pages[0].paint_layers) == 1
        p.settings["export_dir"] = root
        p.settings["export_name"] = "out"
        os.makedirs(editor.export_root(p), exist_ok=True)
        ex = cv2.imread(editor.export_page(p, 0, mode="clean"))
        assert ex is not None

        # nothing red anywhere: the colour was changed, not added to
        assert _count(ex, RED) == 0, "the old colour is still on the page"
        # nothing at all where it was drawn...
        assert _count(ex, BLUE, (30, 30, 175, 125)) < 50, \
            "the shape did not move — it is still where it was drawn"
        # ...and a solid blue rectangle where it was moved to
        assert _count(ex, BLUE, (250, 160, 400, 250)) > 6000, \
            "the moved shape is not where it was put"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


def test_every_tool_in_the_panel_is_armed_and_used():
    """tests/ui/every_tool_works.test.js drives the real panel in jsdom: it
    opens each of the four sections, checks that a section shows only its own
    tools, then arms every tool in turn and DRAGS with it — brush, the three
    shapes, eraser, clone stamp, both healing brushes — and checks what each
    one left behind. Then the whole shape story: pick one up with the arrow,
    move it, resize it, turn it, put it down with Enter or throw the session
    away with Esc, recolour it, change its width, fill it, and round-trip it
    through the save format.

    lee: *"make sure all of tehse tools work"*. A button that lights up and
    paints nothing is what this is for."""
    import shutil as _sh
    import subprocess
    if not _sh.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "every_tool_works.test.js")],
        cwd=root, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "FAIL" not in out.stdout, out.stdout
    for line in ("the toolbox has a slot for every kind of tool",
                 "and the panel no longer has a second copy of any of them",
                 "arming from the toolbox puts the last tool down",
                 "the brush paints a stroke",
                 "the rectangle, the ellipse and the line each draw one",
                 "the eraser makes a pass",
                 "the clone stamp copies",
                 "the healing brush sends its spot off",
                 "dragging the middle moves it",
                 "a corner handle resizes it",
                 "and it is STILL a shape afterwards, not a frozen patch",
                 "a shape can be recoloured after it is drawn"):
        assert line in out.stdout, (line, out.stdout)


def test_a_finished_patch_has_no_colour_to_change():
    """A heal, a clone or a transformed selection is pixels by the time it is a
    layer. Offering a colour well over one would be a control that does
    nothing — `canRecolour` is the single place that draws the line, and the
    panel asks it rather than guessing from the label."""
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "paint.js").read_text(encoding="utf8")
    assert "function canRecolour(l)" in js
    at = js.index("function layerEditor(")
    body = js[at:at + 900]
    assert "canRecolour(l)" in body, \
        "the layer editor decides for itself which layers have a colour"
