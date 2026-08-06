"""Rectangle, ellipse and line.

lee: *"Add shapes - rectangle, circle line"*.

A shape is an ordinary paint layer. That is the whole design: the paint system
already has a layer list with an eye and a delete, undo, a selection fence, a
saved overlay and an export path that bakes the overlay into the page — so a
shape that arrives as a layer inherits every one of those, and the server needed
no changes at all. `type:'shape'` with `shape:'rect'|'circle'|'line'`, its two
corners in `pts`, and `fill` for solid rather than outlined.

Three things were worth getting right:

* **One function draws it** — `shapePath` — used by the live drag preview, by the
  layer replay, and therefore by the flattened overlay that is saved and
  exported. Three copies of an ellipse would have disagreed by a pixel forever.
* **Shift constrains**, as it does everywhere else: a square, a circle, or a line
  snapped to 45 degrees.
* **`paintArmed()`** now answers "is a paint tool armed", in one place. That
  question was written out longhand as `brush||stamp||heal||eraser` in five
  files — for the canvas's pointer events, the class that stops region boxes
  swallowing the click, the selection canvas, and the typesetting editor — and the
  shape tool drew literally nothing until all five knew about it. The last test
  here fails if a sixth copy appears.

The main test drives the real editor in a real Chromium against a real server:
it arms each tool, drags on the page, checks the layers, round-trips them through
the save format, lets the debounced sync land, exports the page **server-side**
and looks for the shapes' own colours in the exported PNG. That is the whole
loop, and nothing about it is stubbed.
"""
import json
import os
import shutil
import threading
from pathlib import Path

import numpy as np
import pytest

import browserpool
from where import PKG

cv2 = pytest.importorskip("cv2")

JS = PKG / "static" / "js"


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 235, np.uint8)
    cv2.ellipse(img, (230, 150), (150, 90), 0, 0, 360, (0, 0, 0), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].detected = True
    return p


def test_shapes_are_drawn_kept_and_exported(tmp_path):
    """The whole loop, in a real browser: drag three shapes onto the page, and
    find them in the file the server writes."""
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = str(tmp_path / "shapes")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            # the Edit view is where the plate is painted
            pg.evaluate("setTab('edit'); setView('typeset');")
            browserpool.settled(pg)
            # The tools are in the TOOLBOX down the left of the page now —
            # one place, always on screen. lee: *"the tools are duplicated it
            # shoud only be onteh side bar"*.
            pg.evaluate("setToolTab('shapes')")
            pg.wait_for_timeout(200)
            assert pg.evaluate(
                "['shrect','shcirc','shline'].every(k=>"
                " TOOLBOX.find(g=>g.slot==='shape').tools.some(t=>t.k===k))"), \
                "the shape tools are not in the toolbox"
            # ...and Filled, which is a setting for them rather than a tool,
            # stays in the panel beside the colour and the size.
            assert pg.evaluate("!!document.getElementById('shapeFillBtn')")

            def drag(kind, x0, y0, x1, y1, fill=False, col="#ff2d55", sz=4):
                pg.evaluate(f"""(()=>{{
                    brushState.col='{col}'; brushState.sz={sz};
                    const cc=document.getElementById('brushCol');
                    if(cc) cc.value='{col}';
                    const sz2=document.getElementById('brushSz');
                    if(sz2) sz2.value='{sz}';
                    setShapeFill({str(fill).lower()});
                    if(shapeKind!=='{kind}') toggleShape('{kind}');
                }})()""")
                o = pg.evaluate("(()=>{const b=document.getElementById('img')"
                                ".getBoundingClientRect();"
                                "return {x:b.x,y:b.y};})()")
                s = pg.evaluate("scale")
                pg.mouse.move(o["x"] + x0 * s, o["y"] + y0 * s)
                pg.mouse.down()
                pg.mouse.move(o["x"] + x1 * s, o["y"] + y1 * s, steps=4)
                pg.mouse.up()
                pg.wait_for_timeout(120)

            drag("rect", 40, 40, 200, 120)
            drag("circle", 240, 40, 420, 150, fill=True, col="#2cdd60")
            drag("line", 40, 200, 420, 260, col="#4da3ff", sz=6)

            got = json.loads(pg.evaluate(
                "JSON.stringify(layers.map(l=>({t:l.type,s:l.shape,"
                "f:!!l.fill,col:l.col,sz:l.sz,n:l.pts.length})))"))
            assert [g["s"] for g in got] == ["rect", "circle", "line"], got
            assert [g["f"] for g in got] == [False, True, False], got
            assert [g["col"] for g in got] == ["#ff2d55", "#2cdd60", "#4da3ff"]
            assert got[2]["sz"] == 6, "the line ignored the size"
            assert all(g["n"] == 2 for g in got), \
                "a shape is two points, not a stroke of them"
            assert json.loads(pg.evaluate("JSON.stringify(layers.map(layerName))")) \
                == ["Rectangle 1", "Ellipse 2", "Line 3"]

            # a click with no drag is not a shape
            pg.evaluate("if(shapeKind!=='rect') toggleShape('rect')")
            o = pg.evaluate("(()=>{const b=document.getElementById('img')"
                            ".getBoundingClientRect();return {x:b.x,y:b.y};})()")
            pg.mouse.click(o["x"] + 30, o["y"] + 280)
            pg.wait_for_timeout(200)
            assert pg.evaluate("layers.length") == 3, \
                "a click left a shape behind"

            # they survive the save format
            assert json.loads(pg.evaluate(
                "(()=>{const w=serializeLayers();loadLayers(w);"
                "return JSON.stringify(layers.map("
                "l=>({t:l.type,s:l.shape,f:!!l.fill})));})()")) == [
                {"t": "shape", "s": "rect", "f": False},
                {"t": "shape", "s": "circle", "f": True},
                {"t": "shape", "s": "line", "f": False}]

            pg.evaluate("queueSync()")
            pg.wait_for_timeout(2500)
            assert not errs, errs[:3]

        assert len(p.pages[0].paint_layers) == 3, "nothing reached the server"
        assert p.pages[0].paint_overlay, "no overlay was written"

        p.settings["export_dir"] = root
        p.settings["export_name"] = "out"
        os.makedirs(editor.export_root(p), exist_ok=True)
        ex = cv2.imread(editor.export_page(p, 0, mode="clean"))
        assert ex is not None

        def near(col, box=None, tol=70):
            d = np.abs(ex.astype(int) - np.array(col)).sum(2) < tol
            if box:
                x0, y0, x1, y1 = box
                m = np.zeros(d.shape, bool)
                m[y0:y1, x0:x1] = True
                d = d & m
            return int(d.sum())

        # BGR of the three colours, each looked for where it was drawn
        assert near([85, 45, 255], (30, 30, 210, 130)) > 300, "no rectangle"
        assert near([96, 221, 44], (235, 35, 425, 155)) > 4000, \
            "the ellipse is not filled"
        assert near([255, 163, 77], (35, 195, 425, 265)) > 500, "no line"
        # and nothing landed where nothing was drawn
        assert near([85, 45, 255], (240, 160, 460, 300)) == 0
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


def test_the_tools_put_each_other_away():
    """One tool at a time, and a shape is a tool like the others."""
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "shape_tools.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "rect armed: rect brush: false" in out.stdout, out.stdout
    assert "brush armed: brush shape: null" in out.stdout, out.stdout
    assert "circle then line: line" in out.stdout, out.stdout
    assert "clicking the armed one again: null" in out.stdout, out.stdout
    assert "armed with a shape: true" in out.stdout, out.stdout
    assert "armed with nothing: false" in out.stdout, out.stdout
    assert "after stopBrush: null" in out.stdout, out.stdout


def test_one_question_asks_whether_a_tool_is_armed():
    """`brush||stamp||heal||eraser` was written out in five files, and a new
    tool has to be added to every one of them or it silently does nothing.
    There is one function now, and this is the guard against a sixth copy."""
    hits = []
    for f in sorted(JS.glob("*.js")):
        src = f.read_text(encoding="utf8")
        for line_no, line in enumerate(src.splitlines(), 1):
            if "brush||stamp||heal||eraser" in line.replace(" ", ""):
                # `paintArmed` itself is where the list belongs, and the
                # cursor rules name the tools that draw a ring — a different
                # question from "is a tool armed"
                if "shapeKind" in line or "cursor" in line or "'none'" in line:
                    continue
                hits.append(f"{f.name}:{line_no}")
    assert not hits, f"longhand arming test left in {hits}"
    assert "function paintArmed()" in (JS / "paint.js").read_text(encoding="utf8")
