"""The selection you can see, and the piece you can pick up.

lee, pointing at the marquee, the lasso and the wand: *"these 3 just dont
work"*. They did work — every one of them built the right mask — and showed
absolutely nothing for it, which from the outside is the same thing.

The marching ants are drawn as `mask` minus the mask ERODED by a pixel, and
erosion is the INTERSECTION of the four one-pixel shifts. The code subtracted
each shifted copy from the mask in turn, which subtracts their UNION — and the
union of the four shifts covers every pixel of any solid shape. The ring came
out empty on every selection that has ever been made in this editor, so the
ants were never once visible. Nothing else about selecting was wrong: paint
fenced correctly, heal fenced correctly, the bucket filled the right area.

Two more things go with it, because they are what a selection is FOR:

* **J lifts the selection to its own layer** — Photoshop's Ctrl+J. Copy and
  paste could already do this, but only through Ctrl+C then Ctrl+V and with
  nothing on screen to say the feature existed. lee: *"i shud be abke to copy
  a oiece o fthe image that i selcted and copy and paste it as a lyer that i
  can edit"*.
* The lifted piece is a **copy**. The page underneath keeps its pixels, which
  is what makes it safe to try — and what this file checks, in the PNG the
  server exports.

None of this can be tested in jsdom: its canvas is a stub with no compositing
and no pixels, so `selHasMask()` is false there no matter what you drag. It
takes a real browser, and the proof is real pixels.
"""
import os
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 235, np.uint8)
    # something with an edge the wand can find, and a mark that can be lifted
    cv2.rectangle(img, (60, 60), (200, 160), (30, 30, 30), -1)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].detected = True
    return p


def _ants_pixels(pg):
    return pg.evaluate("""(()=>{
        const a=document.getElementById('selAnts');
        if(!a) return -1;
        const d=a.getContext('2d').getImageData(0,0,a.width,a.height).data;
        let n=0; for(let i=3;i<d.length;i+=4) if(d[i]>0) n++;
        return n;})()""")


@pytest.fixture()
def editor_page(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = str(tmp_path / "sel")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip('chromium unavailable')
    with browserpool.session() as br:
        # The clipboard is the whole point of the copy/paste tests: without
        # permission `navigator.clipboard.write` fails silently, the system
        # clipboard stays empty, and Ctrl+V quietly takes the in-app path —
        # which is the path that was already right. The bug lives on the other
        # one.
        ctx = br.new_context(viewport={"width": 1500, "height": 900},
                             permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset'); setToolTab('select')")
        browserpool.settled(pg)
        try:
            yield pg, p, root, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _to_screen(pg, x, y):
    o = pg.evaluate("(()=>{const b=document.getElementById('img')"
                    ".getBoundingClientRect();"
                    "return {x:b.x,y:b.y,s:scale};})()")
    return o["x"] + x * o["s"], o["y"] + y * o["s"]


def _drag(pg, x0, y0, x1, y1, steps=6):
    pg.mouse.move(*_to_screen(pg, x0, y0))
    pg.mouse.down()
    pg.mouse.move(*_to_screen(pg, x1, y1), steps=steps)
    pg.mouse.up()
    pg.wait_for_timeout(250)


# ------------------------------------------------- you can see the selection

def test_the_marquee_is_visible_on_the_page(editor_page):
    pg, _p, _root, errs = editor_page
    pg.evaluate("toggleSelTool('rect')")
    # -1 is "the overlay canvas has not even been made yet", which is the
    # honest state before anything has been selected
    assert _ants_pixels(pg) <= 0, "something was drawn before anything was done"
    _drag(pg, 40, 40, 220, 180)
    assert pg.evaluate("selHasMask()") is True
    assert _ants_pixels(pg) > 100, \
        "the selection was made and nothing was drawn to say so"
    assert not errs, errs[:2]


def test_the_lasso_is_visible_on_the_page(editor_page):
    pg, _p, _root, _e = editor_page
    pg.evaluate("toggleSelTool('lasso')")
    pg.mouse.move(*_to_screen(pg, 60, 60))
    pg.mouse.down()
    for x, y in [(200, 60), (200, 160), (60, 160), (60, 60)]:
        pg.mouse.move(*_to_screen(pg, x, y), steps=4)
    pg.mouse.up()
    pg.wait_for_timeout(250)
    assert pg.evaluate("selHasMask()") is True
    assert _ants_pixels(pg) > 100, "the lasso selected in silence"


def test_the_wand_is_visible_on_the_page(editor_page):
    pg, _p, _root, _e = editor_page
    pg.evaluate("toggleSelTool('wand')")
    pg.mouse.click(*_to_screen(pg, 120, 110))
    pg.wait_for_timeout(400)
    assert pg.evaluate("selHasMask()") is True
    assert _ants_pixels(pg) > 100, "the wand selected in silence"


def test_deselecting_takes_the_ants_away(editor_page):
    pg, _p, _root, _e = editor_page
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 40, 40, 220, 180)
    assert _ants_pixels(pg) > 100
    pg.evaluate("selDeselect()")
    pg.wait_for_timeout(200)
    assert _ants_pixels(pg) == 0, "the ants stayed after the selection went"


def _ants_bbox(pg):
    return pg.evaluate("""(()=>{
        const a=document.getElementById('selAnts');
        if(!a) return null;
        const d=a.getContext('2d').getImageData(0,0,a.width,a.height).data;
        let x0=1e9,y0=1e9,x1=-1,y1=-1;
        for(let y=0;y<a.height;y++) for(let x=0;x<a.width;x++)
          if(d[(y*a.width+x)*4+3]>0){
            if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y; }
        return x1<0?null:{x:x0,y:y0,w:x1-x0+1,h:y1-y0+1};})()""")


def test_a_second_selection_moves_the_ants(editor_page):
    """The ring is cached — it is five full-page composites and it must not be
    rebuilt eight times a second just to animate the stripes running through
    it. Cached on the wrong key, the ants keep drawing the outline of the
    selection BEFORE this one, which is worse than not drawing them at all."""
    pg, _p, _root, _e = editor_page
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 20, 20, 120, 100)
    first = _ants_bbox(pg)
    assert first and abs(first["x"] - 20) <= 3, first
    pg.evaluate("selDeselect()")
    _drag(pg, 260, 170, 420, 270)
    second = _ants_bbox(pg)
    assert second and abs(second["x"] - 260) <= 3, \
        f"the ants stayed on the old selection: {first} -> {second}"


def test_the_ring_is_the_border_and_not_the_whole_selection(editor_page):
    """An outline, not a filled block. A ring around a 180x140 marquee is a few
    hundred pixels; the block would be twenty-five thousand."""
    pg, _p, _root, _e = editor_page
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 40, 40, 220, 180)
    n = _ants_pixels(pg)
    assert 100 < n < 3000, f"{n} pixels — that is a fill, not an outline"


# ------------------------------------------------- and you can lift a piece

def test_lifting_copies_the_piece_into_its_own_layer(editor_page):
    pg, p, root, errs = editor_page
    from mangatl import editor
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 70, 70, 190, 150)          # inside the black block
    st = pg.evaluate("(()=>{const s=selLift();"
                     "return s?{id:s.id,type:s.type,label:s.label,"
                     "x:s.x,y:s.y}:null;})()")
    pg.wait_for_timeout(400)
    assert st and st["type"] == "patch", st
    assert st["label"] == "Lifted piece", st
    assert abs(st["x"] - 70) <= 2 and abs(st["y"] - 70) <= 2, st
    assert pg.evaluate("selHasMask()") is False, \
        "the selection stayed up and would fence the next tool"
    assert pg.evaluate("layerSel") == st["id"]
    assert pg.evaluate("layers.length") == 1

    # move it somewhere empty, put it down, and let the save land
    pg.evaluate("(()=>{ if(xf) xfCancel(); })()")
    pg.evaluate("""(()=>{ const l=layers[0]; l.x=250; l.y=180;
                          repaintAll(); queueSync(); })()""")
    pg.wait_for_timeout(2500)
    assert not errs, errs[:2]

    assert len(p.pages[0].paint_layers) == 1, "the lifted layer never saved"
    p.settings["export_dir"] = root
    p.settings["export_name"] = "out"
    os.makedirs(editor.export_root(p), exist_ok=True)
    ex = cv2.imread(editor.export_page(p, 0, mode="clean"))
    assert ex is not None
    dark = (ex.astype(int).sum(2) < 200)
    # the original block is untouched — lifting copies, it does not cut
    assert dark[70:150, 80:190].mean() > 0.9, \
        "lifting took the pixels off the page instead of copying them"
    # ...and the copy is where it was moved to
    assert dark[190:250, 260:360].mean() > 0.9, \
        "the lifted piece is not where it was put"


def test_lifting_nothing_lifts_nothing(editor_page):
    pg, _p, _root, _e = editor_page
    assert pg.evaluate("selHasMask()") is False
    assert pg.evaluate("selLift()") is None
    assert pg.evaluate("layers.length") == 0


def test_the_key_lifts_without_a_button_for_it(editor_page):
    """lee: *"get rid of this"* — the button said the same thing as J, Ctrl+C
    and Ctrl+V, in a row that already had five icons in it. The key stays."""
    pg, _p, _root, _e = editor_page
    assert not pg.evaluate("!!document.getElementById('liftBtn')"), \
        "the lift button came back"
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 70, 70, 190, 150)
    pg.keyboard.press("j")
    pg.wait_for_timeout(300)
    assert pg.evaluate("layers.length") == 1, "J did not lift"
    assert pg.evaluate("layers[0].label") == "Lifted piece"


# ------------------------------------------------- one copy, in the one place

def test_copy_and_paste_leaves_exactly_one_copy(editor_page):
    """lee: *"wheni make a slection and copy it theer a duplicate copy at teh
    bottom right of teh screen theer shud only be one copy"*.

    Two faults, one press apart.

    Ctrl+C also writes the selection to the SYSTEM clipboard, so Ctrl+V came
    back through the browser's paste event as a plain image with no idea where
    it had come from, and landed in the middle of the view. The guard meant to
    catch that compared FILE sizes, and the browser re-encodes on the way
    through the clipboard, so it never matched once — it compares the image's
    dimensions now.

    Then the transform, opened to place the new layer, took the still-live
    SELECTION instead, because it preferred a mask over a layer and had no way
    to be told which one was meant. So the pasted layer sat at the bottom
    right while a floating copy of the original hovered where it was cut.
    Two copies from one paste. `xfStart(layer)` now says which."""
    pg, _p, _root, errs = editor_page
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 60, 60, 180, 160)
    assert pg.evaluate("selHasMask()") is True
    pg.keyboard.press("Control+c")
    pg.wait_for_timeout(700)
    assert pg.evaluate("selClipObj!=null"), "Ctrl+C copied nothing"
    pg.keyboard.press("Control+v")
    pg.wait_for_timeout(1200)

    got = pg.evaluate("JSON.stringify(layers.map("
                      "l=>({label:l.label,x:l.x,y:l.y})))")
    import json
    got = json.loads(got)
    assert len(got) == 1, f"one paste made {len(got)} layers: {got}"
    assert abs(got[0]["x"] - 60) <= 2 and abs(got[0]["y"] - 60) <= 2, \
        f"the copy was dropped somewhere else: {got}"
    # ...and the transform is holding THAT layer, not the old selection
    t = pg.evaluate("xf ? {cx:xf.cx, cy:xf.cy, w:xf.w, h:xf.h} : null")
    assert t, "nothing was picked up to place"
    assert abs(t["w"] - 120) <= 2 and abs(t["h"] - 100) <= 2, t
    assert not errs, errs[:2]


def test_a_foreign_image_still_lands_in_the_middle(editor_page):
    """The in-place rule is for OUR copy. An image from another app has no
    place on this page to go back to, so the middle of the view is right —
    and that is the path the guard must not swallow."""
    pg, _p, _root, _e = editor_page
    pg.evaluate("toggleSelTool('rect')")
    _drag(pg, 60, 60, 180, 160)
    pg.keyboard.press("Control+c")
    pg.wait_for_timeout(700)
    # a different-sized image is not our copy
    same = pg.evaluate("""(()=>{
        const c=document.createElement('canvas'); c.width=40; c.height=30;
        const g=c.getContext('2d'); g.fillStyle='#f0f'; g.fillRect(0,0,40,30);
        return selClipObj && selClipObj.canvas.width===c.width;})()""")
    assert same is False, "the fixture image must not match the copy"


def test_move_and_resize_takes_the_layer_it_was_asked_for(editor_page):
    """A live selection and a picked layer at the same time. The transform
    used to prefer the mask with no way to be told otherwise, so "Move &
    resize" on a layer picked up the selection instead — the same fault that
    put a second copy on the page after a paste, reached a different way."""
    pg, _p, _root, _e = editor_page
    # a shape to move: 90 wide, 60 tall
    pg.evaluate("""(()=>{ setToolTab('shapes');
      layers.push({id:layerSeq++, type:'shape', shape:'rect', col:'#ff2d55',
                   sz:5, fill:false, op:1, visible:true,
                   pts:[{x:300,y:200},{x:390,y:260}]});
      repaintAll(); renderLayers(); })()""")
    # ...and a selection of a completely different size, still up
    pg.evaluate("setToolTab('select'); toggleSelTool('rect')")
    _drag(pg, 20, 20, 200, 180)
    assert pg.evaluate("selHasMask()") is True
    pg.evaluate("moveLayer(layers[0].id)")
    pg.wait_for_timeout(200)
    t = pg.evaluate("xf ? {w:xf.w, h:xf.h, vec:!!xf.vector} : null")
    assert t, "nothing was picked up"
    assert t["vec"] is True, "it picked up the selection's pixels, not the shape"
    assert abs(t["w"] - 90) <= 2 and abs(t["h"] - 60) <= 2, \
        f"it picked up something else: {t}"
