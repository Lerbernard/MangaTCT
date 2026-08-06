"""Free transform, with each corner its own.

lee: *"can you a a trasform tool like photoshops cotolr + t tant allow e to
move each coner of an image indpenedently look only on how phoshot tranfor tool
works and ompliment it"*.

Photoshop's free transform is one box with several behaviours hanging off
modifier keys. Dragging a corner SCALES; holding Ctrl (Cmd) while you drag it
puts that corner exactly where the pointer is and leaves the other three where
they were. That second one is what was missing here, and it is what this adds.

**T arms it with the corners already loose.** lee asked for Ctrl+T — *"ctrl + t
shoud enable the tranform tool tahat allwos met ot move all teh corners
independntly"* — and then, told that Chrome keeps that combination for opening
a tab and a page cannot take it back: *"isntead of control t just make it t"*.
So the key is T, and scale-and-rotate keeps its place under the same toolbox
slot for when a box should stay a box.

**Images and shapes, not text.** A shape moved by the ordinary transform stays
a shape — two points and an angle, nothing baked. Pulled out of true it cannot:
a record that holds two corners cannot hold four. So distort RASTERISES it
first, the way Photoshop does when a vector layer is handed to a warp, and undo
puts the shape back because the patch replaces it rather than joining it.

**Freezing is the trick.** A box described by a centre, a scale and an angle
cannot describe a quadrilateral at all, so the first Ctrl-drag writes down
where the four corners are at that moment and from then on the corners ARE the
transform — `xfCorners` returns them, and the handles, the hit test, the dashed
outline and the warp all follow from that one line.

**The warp is bilinear**, drawn as a mesh: an 8x8 grid of cells, two triangles
each, every triangle drawn with the affine that carries its own three source
corners onto its own three destination corners and clipped to them. Bilinear
because that is what a free deform IS — a projective map is the other tool
(Perspective), and it would move the corners you are not touching. Two
triangles for the whole quad would draw a folded parallelogram; the error falls
off as the square of the cell size and eight is where it stops showing.

Everything here is measured in a real browser. jsdom's canvas has no pixels, so
a warp is not a thing it can be asked about.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 235, np.uint8)
    cv2.rectangle(img, (60, 60), (200, 160), (30, 30, 30), -1)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].detected = True
    return p


def _serve(fn, root=scratch("_tmp_corner")):
    from mangatl import editor
    p = _project(root)
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
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------- the pure parts
# Evaluated in the page, because that is where they live — a classic script
# sharing globals, with no module boundary to import across.

def test_a_corner_of_the_quad_is_the_corner_of_the_quad():
    def check(pg, p):
        got = pg.evaluate("""(()=>{
          const q=[{x:0,y:0},{x:10,y:0},{x:10,y:10},{x:0,y:10}];
          return [xfQuadPoint(q,0,0), xfQuadPoint(q,1,0),
                  xfQuadPoint(q,1,1), xfQuadPoint(q,0,1),
                  xfQuadPoint(q,0.5,0.5)];})()""")
        assert got[:4] == [{"x": 0, "y": 0}, {"x": 10, "y": 0},
                           {"x": 10, "y": 10}, {"x": 0, "y": 10}]
        assert got[4] == {"x": 5, "y": 5}
    _serve(check)


def test_the_middle_of_a_pulled_quad_follows_the_corner():
    """Bilinear: pull one corner and the middle moves a quarter of the way,
    which is what makes the picture stretch instead of shearing in one block."""
    def check(pg, p):
        got = pg.evaluate("""(()=>{
          const q=[{x:0,y:0},{x:10,y:0},{x:10,y:10},{x:0,y:10}];
          q[1]={x:30,y:0};
          return xfQuadPoint(q,0.5,0.5);})()""")
        assert got == {"x": 10, "y": 5}
    _serve(check)


def test_the_triangle_matrix_carries_the_triangle():
    def check(pg, p):
        got = pg.evaluate("""(()=>{
          const s=[{x:0,y:0},{x:4,y:0},{x:0,y:4}];
          const d=[{x:5,y:5},{x:13,y:5},{x:5,y:9}];
          const m=xfTriMatrix(s,d);
          const put=p=>({x:m[0]*p.x+m[2]*p.y+m[4],
                         y:m[1]*p.x+m[3]*p.y+m[5]});
          return [put(s[0]),put(s[1]),put(s[2])];})()""")
        assert got == [{"x": 5, "y": 5}, {"x": 13, "y": 5}, {"x": 5, "y": 9}]
    _serve(check)


def test_a_flat_triangle_has_no_matrix():
    """Three points on a line have no inverse, and drawing one is a divide by
    zero rather than a thin sliver."""
    def check(pg, p):
        assert pg.evaluate("""xfTriMatrix(
          [{x:0,y:0},{x:2,y:2},{x:4,y:4}],
          [{x:0,y:0},{x:1,y:1},{x:2,y:2}])""") is None
    _serve(check)


def test_the_mesh_triangles_are_grown_so_the_seams_do_not_show():
    """Neighbouring cells are clipped to a shared edge, and a clip is
    antialiased on both sides of it — so without this every seam in the mesh
    is a pale hairline across the picture."""
    def check(pg, p):
        got = pg.evaluate("""(()=>{
          const t=[{x:0,y:0},{x:9,y:0},{x:0,y:9}];
          const g=xfGrow(t,0.5);
          return t.map((q,i)=>Math.hypot(g[i].x-q.x,g[i].y-q.y));})()""")
        assert all(abs(d - 0.5) < 1e-6 for d in got), got
    _serve(check)


# --------------------------------------------------------- and the tool itself

def _pick_up(pg):
    """A selection LIFTED to its own layer, with the transform armed on it.

    The lift is the point: the transform moves layers, not selections — a
    selection is left to fence the brush and to be copied. lee: *"teh select
    too shoud just be there and do nothing  no new image shoud be made until i
    hit copy and past"*. J is that lift, and it is what puts something on the
    page for the tool to take hold of.

    Waited for rather than slept on: the mask needs the page image to have
    finished arriving, which under a loaded machine is not always inside a
    fixed pause, and a test that starts before the tool is armed fails
    somewhere else entirely.
    """
    pg.wait_for_function("!!(document.getElementById('img')||{}).naturalWidth",
                         timeout=15000)
    pg.evaluate("""(()=>{
      selTool='rect';
      selCommitShape({kind:'rect',x0:60,y0:60,x1:200,y1:160},'new');
      selLift();
      xfStart();})()""")
    pg.wait_for_function("typeof xf!=='undefined' && !!xf",
                         timeout=15000)


def _drag(pg, handle, i, to, ctrl=False):
    """Drive one drag frame at a page point.

    `selMove` asks `canvasPt` where the pointer is, and that reads the canvas\'s
    own geometry — so the honest way to say "the pointer is at this page point"
    is to answer that question directly for the length of the call.
    """
    pg.evaluate("""([handle,i,to,ctrl])=>{
      xfDrag={h:{type:handle,i}, start:xfCorners(xf)[i]||{x:0,y:0},
              t0:{...xf}, t0q:xf.quad?xf.quad.map(q=>({x:q.x,y:q.y})):null,
              a0:0};
      const real=window.canvasPt; window.canvasPt=()=>to;
      try{
        selMove({ctrlKey:ctrl, metaKey:false, shiftKey:false,
                 preventDefault(){}, stopPropagation(){}});
      } finally { window.canvasPt=real; }}""", [handle, i, to, ctrl])


def test_dragging_a_corner_still_scales():
    """The path that was there before this, untouched: no Ctrl, no freezing,
    and the corner opposite the one being dragged stays put because it is the
    anchor a scale turns about."""
    def check(pg, p):
        _pick_up(pg)
        assert pg.evaluate("!!xf"), "the transform did not arm"
        before = pg.evaluate("xfCorners(xf)")
        _drag(pg, "corner", 0, {"x": 20, "y": 20})
        after = pg.evaluate("xfCorners(xf)")
        assert pg.evaluate("!xf.quad"), "a plain drag froze the corners"
        assert abs(after[2]["x"] - before[2]["x"]) < 0.5, (before[2], after[2])
        assert abs(after[2]["y"] - before[2]["y"]) < 0.5, (before[2], after[2])
        assert abs(after[0]["x"] - 20) < 0.5 and abs(after[0]["y"] - 20) < 0.5, \
            after[0]
    _serve(check)


def test_ctrl_dragging_one_corner_leaves_the_other_three():
    def check(pg, p):
        _pick_up(pg)
        before = pg.evaluate("xfCorners(xf)")
        _drag(pg, "corner", 1, {"x": 320, "y": 20}, ctrl=True)
        after = pg.evaluate("xfCorners(xf)")
        assert pg.evaluate("!!xf.quad"), "the corners were never frozen"
        assert after[1] == {"x": 320, "y": 20}, after
        for i in (0, 2, 3):
            assert after[i] == before[i], (i, before[i], after[i])
    _serve(check)


def test_the_picture_is_actually_bent(tmp_path):
    """Not just the outline. The pixels are drawn through the mesh, and a
    corner pulled a long way out puts ink where the untouched box had none."""
    def check(pg, p):
        _pick_up(pg)
        pg.evaluate("""(()=>{
          xfFreeze(xf);
          xf.quad[1]={x:430, y:20};
          selRedrawAnts();})()""")
        pg.wait_for_timeout(400)
        got = pg.evaluate("""(()=>{
          const a=document.getElementById('selAnts');
          const d=a.getContext('2d').getImageData(0,0,a.width,a.height).data;
          const q=xf.quad;
          // How far a point is from the nearest EDGE of the quad. The dashed
          // outline and its handles are drawn on those edges, so anything
          // well clear of them is the picture and nothing else — which is the
          // whole question here: does the outline go out there on its own, or
          // do the pixels go with it?
          const edge=(x,y)=>{
            let m=1e9;
            for(let i=0;i<4;i++){
              const p1=q[i], p2=q[(i+1)%4];
              const vx=p2.x-p1.x, vy=p2.y-p1.y;
              const L=vx*vx+vy*vy||1;
              let t=((x-p1.x)*vx+(y-p1.y)*vy)/L;
              t=Math.max(0,Math.min(1,t));
              m=Math.min(m, Math.hypot(x-(p1.x+t*vx), y-(p1.y+t*vy)));
            }
            return m;
          };
          let far=0, all=0;
          for(let y=0;y<a.height;y++)
            for(let x=0;x<a.width;x++){
              const i=(y*a.width+x)*4;
              if(d[i+3]<=40) continue;
              all++;
              if(x>260 && xfInside(xf,{x,y}) && edge(x,y)>10) far++;
            }
          return {far, all};})()""")
        assert got["all"] > 500, got
        assert got["far"] > 200, ("the outline went out to the pulled corner "
                                  "but the picture stayed behind", got)
    _serve(check)


def test_letting_go_bakes_the_bent_picture_and_not_the_flat_one():
    """Apply draws the transform once more, for keeps, into a patch layer. It
    has to draw the SAME thing the preview was showing — the warp — or the
    picture snaps back to a rectangle at the moment you commit it, which is
    the worst possible time to find out."""
    def check(pg, p):
        _pick_up(pg)
        pg.evaluate("""(()=>{
          xfFreeze(xf);
          xf.quad[1]={x:430, y:20};})()""")
        quad = pg.evaluate("xf.quad")
        pg.evaluate("xfApply()")
        pg.wait_for_timeout(700)
        got = pg.evaluate("""(q)=>{
          const l=layers.filter(l=>l.type==='patch').pop();
          if(!l) return {err:'no patch layer'};
          const c=document.createElement('canvas');
          const im=l.img;
          if(!im) return {err:'the layer never loaded'};
          c.width=im.naturalWidth||im.width; c.height=im.naturalHeight||im.height;
          c.getContext('2d').drawImage(im,0,0);
          const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
          const inside=(x,y)=>{
            let in_=false;
            for(let i=0,j=3;i<4;j=i++){
              const a=q[i], b=q[j];
              if((a.y>y)!==(b.y>y) &&
                 x < (b.x-a.x)*(y-a.y)/((b.y-a.y)||1e-9)+a.x) in_=!in_;
            }
            return in_;
          };
          const edge=(x,y)=>{
            let m=1e9;
            for(let i=0;i<4;i++){
              const p1=q[i], p2=q[(i+1)%4];
              const vx=p2.x-p1.x, vy=p2.y-p1.y, L=vx*vx+vy*vy||1;
              let t=Math.max(0,Math.min(1,((x-p1.x)*vx+(y-p1.y)*vy)/L));
              m=Math.min(m, Math.hypot(x-(p1.x+t*vx), y-(p1.y+t*vy)));
            }
            return m;
          };
          let far=0, all=0;
          for(let yy=0; yy<c.height; yy++)
            for(let xx=0; xx<c.width; xx++){
              if(d[(yy*c.width+xx)*4+3]<=40) continue;
              all++;
              const X=l.x+xx, Y=l.y+yy;
              if(X>260 && inside(X,Y) && edge(X,Y)>10) far++;
            }
          return {far, all, x:l.x, y:l.y};}""", quad)
        assert "err" not in got, got
        assert got["all"] > 500, got
        assert got["far"] > 200, ("the baked patch is the flat rectangle, not "
                                  "the bent picture", got)
    _serve(check)


def test_a_shape_cannot_be_pulled_out_of_true():
    """A shape transform moves the shape's own two points and its angle. There
    is no rectangle of pixels to bend, and writing a quadrilateral into a
    record that can only hold a box would lose the shape."""
    def check(pg, p):
        pg.evaluate("""(()=>{
          layers.push({id:layerSeq++, type:'shape', shape:'rect', group:'drawing',
                       col:'#ff0000', sz:3, op:1, visible:true, rot:0,
                       pts:[{x:60,y:60},{x:180,y:150}]});
          layerSel=layers[layers.length-1].id;
          xfStart(layers[layers.length-1]);})()""")
        pg.wait_for_timeout(300)
        assert pg.evaluate("!!(xf && xf.vector)"), "the shape was not picked up"
        _drag(pg, "corner", 1, {"x": 300, "y": 10}, ctrl=True)
        assert pg.evaluate("!xf.quad"), "a shape was frozen into a quad"
    _serve(check)


def test_inside_means_inside_the_quad_not_the_old_box():
    """The move handle is "am I in the box", and after a corner has been pulled
    the box is a quadrilateral. Asking the old rotated-rectangle question would
    grab thin air on one side and refuse the picture on the other."""
    def check(pg, p):
        _pick_up(pg)
        pg.evaluate("""(()=>{ xfFreeze(xf);
          xf.quad=[{x:0,y:0},{x:100,y:0},{x:100,y:100},{x:0,y:100}];})()""")
        assert pg.evaluate("xfInside(xf,{x:50,y:50})") is True
        assert pg.evaluate("xfInside(xf,{x:150,y:50})") is False
        pg.evaluate("xf.quad[2]={x:400,y:400}")
        assert pg.evaluate("xfInside(xf,{x:200,y:200})") is True
        assert pg.evaluate("xfInside(xf,{x:60,y:390})") is False
    _serve(check)


# ------------------------------------------------------- the warp, in pixels

_WARP = """([quad, wantU, wantV])=>{
  // a plain source: opaque white with one red square at a known place in it
  const src=document.createElement('canvas'); src.width=src.height=100;
  const sg=src.getContext('2d');
  sg.fillStyle='#ffffff'; sg.fillRect(0,0,100,100);
  sg.fillStyle='#ff0000'; sg.fillRect(45,45,10,10);
  const out=document.createElement('canvas'); out.width=out.height=400;
  const t={src, w:100, h:100, cx:0, cy:0, sx:1, sy:1, rot:0, op:1, quad};
  xfDrawQuad(out.getContext('2d'), t);
  const d=out.getContext('2d').getImageData(0,0,400,400).data;
  let rx=0, ry=0, rn=0, holes=0, opaque=0;
  for(let y=0;y<400;y++) for(let x=0;x<400;x++){
    const i=(y*400+x)*4;
    if(d[i]>200 && d[i+1]<90 && d[i+2]<90 && d[i+3]>200){ rx+=x; ry+=y; rn++; }
    if(d[i+3]>250) opaque++;
    // a hole is a part-transparent pixel with solid neighbours either side:
    // that is what a seam between two clipped triangles looks like
    if(d[i+3]>10 && d[i+3]<200 && x>1 && x<398 &&
       d[i-8+3]>250 && d[i+8+3]>250) holes++;
  }
  const want=xfQuadPoint(quad, wantU, wantV);
  return {n:rn, cx:rn?rx/rn:-1, cy:rn?ry/rn:-1,
          want, holes, opaque};
}"""


def test_the_middle_of_the_picture_lands_where_the_map_says():
    """A bilinear warp is not affine, so the whole quad drawn as two triangles
    comes out a folded parallelogram — the middle of the picture ends up
    somewhere the map never sent it. The mesh is what fixes that, and this is
    the measurement that says by how much."""
    quad = [{"x": 40, "y": 40}, {"x": 360, "y": 90},
            {"x": 300, "y": 340}, {"x": 60, "y": 250}]

    def check(pg, p):
        got = pg.evaluate(_WARP, [quad, 0.5, 0.5])
        assert got["n"] > 40, got
        off = ((got["cx"] - got["want"]["x"]) ** 2
               + (got["cy"] - got["want"]["y"]) ** 2) ** 0.5
        assert off < 4.0, (off, got)
    _serve(check)


def test_the_mesh_has_no_seams_in_it():
    """Neighbouring cells are clipped to a shared edge and a clip is
    antialiased on BOTH sides of it, so an ungrown mesh draws a pale grid over
    the picture — part-transparent pixels with solid pixels either side."""
    quad = [{"x": 40, "y": 40}, {"x": 360, "y": 90},
            {"x": 300, "y": 340}, {"x": 60, "y": 250}]

    def check(pg, p):
        got = pg.evaluate(_WARP, [quad, 0.5, 0.5])
        assert got["opaque"] > 20000, got
        assert got["holes"] < got["opaque"] // 200, got
    _serve(check)


# ------------------------------------------------------------------ Ctrl + T

def test_t_arms_it_with_the_corners_already_loose():
    def check(pg, p):
        pg.wait_for_function("!!(document.getElementById('img')||{}).naturalWidth",
                             timeout=15000)
        pg.evaluate("""(()=>{
          selTool='rect';
          selCommitShape({kind:'rect',x0:60,y0:60,x1:200,y1:160},'new');
          selLift();})()""")
        pg.evaluate("xfToggle('distort')")
        pg.wait_for_function("typeof xf!=='undefined' && !!xf", timeout=15000)
        assert pg.evaluate("!!xf.quad"), "the corners were not freed"
        # ...and one drag with no modifier at all moves just that corner
        before = pg.evaluate("xfCorners(xf)")
        _drag(pg, "corner", 1, {"x": 330, "y": 15})
        after = pg.evaluate("xfCorners(xf)")
        assert after[1] == {"x": 330, "y": 15}, after
        for i in (0, 2, 3):
            assert after[i] == before[i], (i, before[i], after[i])
    _serve(check)


def test_scale_and_rotate_is_still_there():
    """Two tools in one slot, not one tool that changed. Freezing the corners
    throws the angle away, so there has to be a way to a box that stays a
    box."""
    def check(pg, p):
        pg.wait_for_function("!!(document.getElementById('img')||{}).naturalWidth",
                             timeout=15000)
        pg.evaluate("""(()=>{
          selTool='rect';
          selCommitShape({kind:'rect',x0:60,y0:60,x1:200,y1:160},'new');
          selLift();})()""")
        # ...and reached the way a person reaches it: out of the toolbox slot,
        # not by calling the function. A tool with no button and no key is a
        # tool that is gone.
        tools = pg.evaluate("""TOOLBOX.find(s=>s.slot==='move').tools
          .map(t=>t.k)""")
        assert len(tools) == 2, tools
        pg.evaluate("""(()=>{
          TOOLBOX.find(s=>s.slot==='move').tools
            .find(t=>t.k!=='xfd').on();})()""")
        pg.wait_for_function("typeof xf!=='undefined' && !!xf", timeout=15000)
        assert pg.evaluate("!xf.quad"), "the plain tool came up distorted"
    _serve(check)


def test_the_key_is_the_plain_one():
    """Chrome will not hand a page Ctrl+T in an ordinary tab, so a binding
    there is one lee could never reach. T is bare, and reaches us."""
    from pathlib import Path
    root = PKG / "static" / "js"
    sel = (root / "select.js").read_text(encoding="utf-8")
    tb = (root / "toolbar.js").read_text(encoding="utf-8")
    # after the guard that drops anything with a modifier on it
    bare = sel.split("if(e.ctrlKey||e.metaKey||e.altKey) return;")[1]
    assert "else if(e.key==='t'||e.key==='T') xfToggle('distort');" in bare
    assert "ctrlKey||e.metaKey)&&(e.key==='t'" not in sel, \
        "Ctrl+T is bound to something Chrome will never deliver"
    assert "xfToggle('distort')" in tb, "the toolbox cannot reach it"
    assert "(T)" in tb


def test_a_shape_is_rasterised_when_it_is_pulled_out_of_true():
    """It cannot stay a shape: two points cannot describe four corners. What
    matters is that the shape goes back on undo, which it does because the
    patch REPLACES it rather than joining it."""
    def check(pg, p):
        pg.wait_for_function("!!(document.getElementById('img')||{}).naturalWidth",
                             timeout=15000)
        pg.evaluate("""(()=>{
          ensureCanvas();
          layers.push({id:layerSeq++, type:'shape', shape:'rect',
                       group:'drawing', col:'#ff0000', sz:4, op:1,
                       visible:true, rot:0,
                       pts:[{x:60,y:60},{x:180,y:150}]});
          layerSel=layers[layers.length-1].id;
          xfStart(layers[layers.length-1], 'distort');})()""")
        pg.wait_for_function("typeof xf!=='undefined' && !!xf", timeout=15000)
        got = pg.evaluate("({quad:!!xf.quad, vector:!!xf.vector, "
                          "src:!!xf.src, replacing:!!xf.replacing})")
        assert got == {"quad": True, "vector": False,
                       "src": True, "replacing": True}, got
    _serve(check)


def test_a_turned_shape_is_cropped_to_where_it_really_is():
    """Its two points describe an upright rectangle. Turned, the shape leaves
    that rectangle, and cropping to it would cut the corners off the picture
    the transform is about to be handed."""
    def check(pg, p):
        got = pg.evaluate("""(()=>{
          const up = xfShapeBox({pts:[{x:100,y:100},{x:200,y:140}],
                                 rot:0, sz:0});
          const turned = xfShapeBox({pts:[{x:100,y:100},{x:200,y:140}],
                                     rot:Math.PI/2, sz:0});
          return {up, turned};})()""")
        assert got["up"]["w"] > got["up"]["h"], got["up"]
        # a quarter turn swaps them
        assert abs(got["turned"]["w"] - got["up"]["h"]) <= 1, got
        assert abs(got["turned"]["h"] - got["up"]["w"]) <= 1, got
    _serve(check)


# ------------------------------------------------- a selection is not a layer

def test_a_selection_alone_is_not_picked_up():
    """It used to be: with a mask down, arming the tool copied everything
    inside it out of the page and floated that copy, so letting go left the
    moved pixels sitting on top of the ones they came from. lee: *"whn i use
    the selcet tool and with to the move tool it shoud [n]ot automaticaly make
    a copy of teh selected area ... no new image shoud be made until i hit copy
    and past"*."""
    def check(pg, p):
        pg.wait_for_function(
            "!!(document.getElementById('img')||{}).naturalWidth", timeout=15000)
        pg.evaluate("""(()=>{
          selTool='rect';
          selCommitShape({kind:'rect',x0:60,y0:60,x1:200,y1:160},'new');})()""")
        assert pg.evaluate("selHasMask()") is True, "no selection was made"
        pg.evaluate("xfToggle('distort')")
        pg.wait_for_timeout(500)
        assert pg.evaluate("!xf"), "the selection was floated anyway"
        assert pg.evaluate("layers.length") == 0, "a layer was made"
        assert pg.evaluate("selHasMask()") is True, "the selection was eaten"
    _serve(check)


def test_lifting_it_first_is_what_makes_something_to_move():
    """J, and copy-and-paste, are the two ways a new layer is deliberately
    made. Both end with the transform holding it."""
    def check(pg, p):
        _pick_up(pg)
        assert pg.evaluate("!!xf"), "the lifted layer was not picked up"
        assert pg.evaluate("layers.length") == 1, "J did not make a layer"
    _serve(check)


def test_only_the_armed_tool_is_lit():
    """One at a time, and it is the one you are using.

    A slot used to also mark which of its tools it was SET to, so that picking
    one out of a flyout looked like it had done something even when that tool
    could not arm yet. Every slot ever touched then kept its mark, and lee
    ended up looking at four outlined buttons of which none was the tool in
    his hand: *"only one tool sjou dbeselected at once and i dont now what
    this haft selection thing is but remove it"*.

    What the slot still does is CHANGE ITS ICON to the tool it is set to —
    that is the thing that says which one it is.
    """
    def check(pg, p):
        pg.wait_for_timeout(500)
        pg.evaluate("tbArm('move','xf')")     # nothing on the page to move
        pg.evaluate("tbArm('select','lasso')")
        pg.wait_for_timeout(400)
        got = pg.evaluate("""(()=>{
          const all=[...document.querySelectorAll('#toolbox .tbtn')];
          return {lit:all.filter(b=>b.classList.contains('on')).length,
                  marked:all.filter(b=>b.classList.contains('chosen')).length,
                  move:document.querySelector(
                    '#toolbox .tbtn[data-slot=move]').dataset.tool,
                  sel:document.querySelector(
                    '#toolbox .tbtn[data-slot=select]').dataset.tool};})()""")
        assert got["marked"] == 0, ("the half-selection is back", got)
        assert got["lit"] <= 1, ("two tools are lit at once", got)
        # ...and the slots still SAY which tool they hold
        assert got["move"] == "xf" and got["sel"] == "lasso", got
    _serve(check)


def test_no_rule_is_left_for_a_mark_nothing_sets():
    """`.tbtn.chosen` outliving the class that used it is how the next reader
    concludes the half-selection is still a thing."""
    from pathlib import Path
    root = PKG / "static"
    assert ".tbtn.chosen" not in (root / "css" / "editor.css").read_text(
        encoding="utf-8")
    assert "chosen" not in (root / "js" / "toolbar.js").read_text(
        encoding="utf-8")


def test_the_two_transforms_do_not_wear_the_same_picture():
    """They share one slot, so the flyout is the only place both are visible
    at once and the picture is most of what tells them apart there. lee: *"just
    cal it teh free transform tool and give it a difrent icon"*."""
    def check(pg, p):
        pg.wait_for_timeout(400)
        got = pg.evaluate("""(()=>{
          const b=document.querySelector('#toolbox .tbtn[data-slot=move]');
          return {shown:b.querySelector('path').getAttribute('d'),
                  distort:TB_ICON.distort, move:TB_ICON.move,
                  title:b.title};})()""")
        assert got["distort"] and got["move"], got
        assert got["distort"] != got["move"], "one drawing under two names"
        assert got["shown"] == got["distort"], got["shown"]
        assert got["title"] == "Free transform (T)", got["title"]
    _serve(check)
