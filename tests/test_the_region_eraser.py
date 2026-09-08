# -*- coding: utf-8 -*-
"""The eraser that goes one layer further down.

lee, having looked at a cleaned chapter: *"thiis pretty god, only a few
mistakes here and tere that are eaily fixable with the ediytor"*, and then:
*"make a region erreser tool that allow the user to use an erraser on the
regions taht weere clened to revelal the original page undernea it"*.

## Two erasers, and what is under each of them

The ordinary eraser (E) rubs out PAINT. Its own comment says so - *"erases
paint - strokes, fills, patches - never the page itself"* - and it works by
punching holes in the overlay's alpha with `destination-out`. What shows
through a hole is the CLEANED PLATE, because that is what the overlay is
composited onto.

That is the right eraser for a brush stroke you regret and no use at all for a
clean you regret. Where the cleaner smeared a patch of tone or ate the corner
of a drawing, the thing you want back is the SCAN - the artwork as it arrived,
Japanese and all - and no amount of rubbing out paint reaches it.

So R goes through the plate. Paint over a spot and the scan comes back there.

## It is a clone stamp aimed at a different picture

Everything a clone stroke already does is what this needs: a soft round tip, a
live preview, freezing into a patch on mouse-up, a row in the layer list, undo,
a place in the saved overlay and therefore in the exported page. The only thing
that differs is where it samples from - `off:{dx:0,dy:0}` and a `snap` holding
the scan instead of the screen.

Which is why there is no server change here at all. It saves, reloads and
exports as an ordinary `patch` layer, labelled `Original` so the list says
which kind it is.

## and the per-box eye is the same idea with a checkbox

`skip_clean` already means "put the original pixels back in this region" -
`_finish_plate` does literally `plate[m > 0] = page.image[m > 0]`. This is that,
chosen by the pixel and by hand, for the times when the box is right and a
corner of it is not.
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool
from where import PKG

cv2 = pytest.importorskip("cv2")

STROKE = """(()=>{const c=$('paint'), r=c.getBoundingClientRect();
  const at=(x,y)=>({x:r.left+x*r.width/c.width, y:r.top+y*r.height/c.height});
  const mk=(t,x,y)=>{const o=at(x,y);
    c.dispatchEvent(new MouseEvent(t,{bubbles:true,clientX:o.x,clientY:o.y,
                                      button:0}));};
  mk('mousedown',%d,%d); mk('mousemove',%d,%d); mk('mousemove',%d,%d);
  window.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));})()"""


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    # something for the cleaner to take off, so there is a difference between
    # the scan and the plate for the tool to reveal
    cv2.putText(img, "NIHONGO", (150, 195), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (10, 10, 10), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [140, 150, 220, 60],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[140, 150], [360, 150], [360, 210], [140, 210]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "rev"))
    editor.do_typeset(p, 0)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip("chromium unavailable")
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


# --------------------------------------------------------------- it is there

def test_it_is_on_the_strip_with_the_other_retouch_tools(ed):
    """Beside the clone stamp and the healing brush, because it is for the
    same thing: the cleaner got this spot wrong."""
    pg, _p, errs = ed
    slot = pg.evaluate(
        "document.querySelector('.tbtn[data-tool=unclean]').dataset.slot")
    assert slot == "retouch", slot
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-tool=unclean]').title") \
        == "Reveal the original (R)"
    assert not errs, errs[:2]


def test_arming_it_puts_the_other_tools_down(ed):
    """Every tool arms through `disarmTools`, and a tool that forgets to is a
    tool you can be holding two of."""
    pg, _p, errs = ed
    pg.evaluate("toggleBrush(true)")
    pg.wait_for_timeout(250)
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(250)
    assert pg.evaluate("unclean") is True
    assert pg.evaluate("brush") is False
    lit = pg.evaluate(
        "[...document.querySelectorAll('#toolbox .tbtn.on')].map(b=>b.dataset.tool)")
    assert lit == ["unclean"], lit
    assert not errs, errs[:2]


def test_r_arms_it(ed):
    pg, _p, errs = ed
    pg.evaluate("document.body.focus()")
    pg.keyboard.press("r")
    pg.wait_for_timeout(300)
    assert pg.evaluate("unclean") is True
    assert not errs, errs[:2]


def test_it_shows_a_brush_ring_and_the_brush_rows(ed):
    """It is a soft round brush on screen, so it wants the size, hardness and
    opacity rows - and NOT a colour, because it does not have one."""
    pg, _p, errs = ed
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(300)
    shown = pg.evaluate("""(()=>{const g=id=>{const e=document.getElementById(id);
      return !!e && e.style.display!=='none';};
      return {sz:g('rowSize'), op:g('rowOp'), hard:g('rowHard'),
              col:g('rowCol')};})()""")
    assert shown["sz"] and shown["op"] and shown["hard"], shown
    assert not shown["col"], "it was offered a colour it cannot use"
    assert not errs, errs[:2]


def test_arming_it_leaves_nothing_on_the_page(ed):
    """The clone stamp's source mark and ring are drawn ON the artwork and
    were only cleared when the STAMP was put away - so arming anything else
    while one was up left a dashed green circle sitting there. lee, with a crop
    of it: *"not a seperate erraser taht stay on the board it shoud be lnked
    with teh cursur"*. The ring under the pointer is the whole of this tool's
    UI."""
    pg, _p, errs = ed
    # put the stamp's furniture on the page the way using it would
    pg.evaluate("toggleStamp(true); cloneSrc={x:200,y:180}; cloneMark(200,180);")
    pg.wait_for_timeout(300)
    assert pg.evaluate(
        "getComputedStyle(document.getElementById('cloneMark')).display") != "none"
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(400)
    for el in ("cloneMark", "cloneRing", "clonePrev"):
        assert pg.evaluate("""(()=>{const e=document.getElementById('%s');
          return !e || getComputedStyle(e).display==='none';})()""" % el), el
    assert not errs, errs[:2]


def test_a_stroke_leaves_nothing_on_the_page(ed):
    """A clone stroke shows a ring where it is copying FROM, which is only a
    question for the stamp. This is a clone stroke with no offset - it samples
    the spot it is painting - so that ring is a green circle drawn under the
    cursor saying "here", and it was still sitting there when the stroke
    ended. lee, with a crop of one: *"also it shoud not leave this behind it
    shod lway be with teh cusur"*."""
    pg, _p, errs = ed
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(900)
    pg.evaluate(STROKE % (170, 185, 260, 185, 330, 185))
    pg.wait_for_timeout(900)
    for el in ("cloneMark", "cloneRing", "clonePrev"):
        assert pg.evaluate("""(()=>{const e=document.getElementById('%s');
          return !e || getComputedStyle(e).display==='none';})()""" % el), el
    assert not errs, errs[:2]


def test_the_stamp_still_shows_where_it_copies_from(ed):
    """The mark is not gone, it is the STAMP's. Guarded on the code, because
    the fix is one condition and deleting it outright would be the same
    diff."""
    js = (PKG / "static" / "js" / "paint.js").read_text(encoding="utf-8")
    at = js.index("if(painting.type==='clone' && !painting.unclean){")
    assert "cloneMark(p.x+painting.off.dx" in js[at:at + 300]


def test_the_ring_follows_the_pointer(ed):
    """It is a brush, and a brush cursor that stands still is the complaint
    above wearing a different hat."""
    pg, _p, errs = ed
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(400)
    b = pg.evaluate("""(()=>{const r=$('img').getBoundingClientRect();
      return {x:r.left, y:r.top, w:r.width, h:r.height};})()""")
    seen = []
    for fx, fy in ((0.3, 0.4), (0.7, 0.6)):
        pg.mouse.move(b["x"] + b["w"] * fx, b["y"] + b["h"] * fy)
        pg.wait_for_timeout(200)
        seen.append(pg.evaluate("""(()=>{const e=$('brushCursor');
          return {d:getComputedStyle(e).display, l:e.style.left, t:e.style.top};})()"""))
    assert seen[0]["d"] == "block" and seen[1]["d"] == "block", seen
    assert seen[0]["l"] != seen[1]["l"], seen


def test_arming_it_brings_the_boxes_back(ed):
    """What it erases is a REGION, and you cannot aim at one you cannot see.
    lee: *"also ckicling teh tool shoud unhide boxes automaticaly"*."""
    pg, _p, errs = ed
    pg.evaluate("$('hideboxes').checked=true; drawBoxes();")
    pg.wait_for_timeout(250)
    assert pg.evaluate("boxesHidden()") is True
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(400)
    assert pg.evaluate("boxesHidden()") is False
    assert not errs, errs[:2]


def test_and_takes_them_away_again_when_it_is_put_down(ed):
    """Borrowed, not taken. lee: *"unslecting the tool or click something elso
    sjodu turn off teh boxes"*. Three ways down, and all three give it back:
    clicking the tool again, arming another tool, and the put-everything-away
    path."""
    pg, _p, errs = ed
    for put_down in ("toggleUnclean(false)", "toggleBrush(true)",
                     "stopBrush()"):
        pg.evaluate("$('hideboxes').checked=true; drawBoxes();")
        pg.evaluate("toggleUnclean(true)")
        pg.wait_for_timeout(350)
        assert pg.evaluate("boxesHidden()") is False, put_down
        pg.evaluate(put_down)
        pg.wait_for_timeout(350)
        assert pg.evaluate("boxesHidden()") is True, put_down
        pg.evaluate("stopBrush()")
    assert not errs, errs[:2]


def test_a_box_setting_it_never_borrowed_is_left_alone(ed):
    """Somebody who has the boxes ON keeps them on after the tool goes down -
    the tool only ever gives back what it took."""
    pg, _p, errs = ed
    pg.evaluate("$('hideboxes').checked=false; drawBoxes(); stopBrush();")
    pg.wait_for_timeout(250)
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(350)
    pg.evaluate("toggleUnclean(false)")
    pg.wait_for_timeout(350)
    assert pg.evaluate("boxesHidden()") is False
    assert not errs, errs[:2]


# ------------------------------------------------------------ and it reveals

def test_a_stroke_becomes_an_original_patch(ed):
    """It freezes to an ordinary `patch` layer, which is what makes it save,
    reload and export with no server change at all. The label is what the
    layer list shows, and it says which of the two stamps made it."""
    pg, _p, errs = ed
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(900)            # the scan is fetched, not read off DOM
    assert pg.evaluate("!!scanSnapshot()"), "the scan never loaded"
    pg.evaluate(STROKE % (170, 185, 260, 185, 330, 185))
    pg.wait_for_timeout(1200)
    got = pg.evaluate("layers.map(l=>[l.type, l.label||'', l.group||''])")
    assert got == [["patch", "Original", "retouch"]], got
    assert not errs, errs[:2]


def test_what_it_puts_back_is_the_scan_and_not_the_plate(ed):
    """The point of the whole tool. The plate has the Japanese erased; the scan
    still has it. After a stroke across the words, the pixels under the stroke
    have to match the SCAN - which means they are darker than the blank white
    the cleaner left."""
    pg, _p, errs = ed
    pg.evaluate("toggleUnclean(true)")
    pg.wait_for_timeout(900)
    pg.evaluate("$('brushSz').value=40; cursorSize&&cursorSize();")
    pg.evaluate(STROKE % (170, 185, 260, 185, 330, 185))
    pg.wait_for_timeout(1200)
    dark = pg.evaluate("""(()=>{const c=$('paint');
      const d=c.getContext('2d').getImageData(150,165,220,40).data;
      let n=0; for(let i=0;i<d.length;i+=4)
        if(d[i+3]>40 && d[i]<128) n++;
      return n;})()""")
    assert dark > 200, "the stroke put back nothing dark: %d px" % dark
    assert not errs, errs[:2]


def test_the_ordinary_eraser_still_only_rubs_out_paint(ed):
    """The two are not the same tool with a different name. E punches a hole in
    the overlay - what shows through is the cleaned plate - and R goes past it.
    Guarded on the code, because the difference is one composite operation."""
    js = (PKG / "static" / "js" / "paint.js").read_text(encoding="utf-8")
    at = js.index("if(st.type==='erase'){")
    assert "destination-out" in js[at:at + 500]
    at = js.index("const snap=scanSnapshot();")   # the paintDown branch
    body = js[at:at + 900]
    assert "off:{dx:0,dy:0}" in body and "snap:snap" in body
    assert "destination-out" not in body


def test_it_asks_for_the_scan_and_not_for_what_is_on_screen(ed):
    """`cloneSnapshot` is the screen - the plate and the strokes so far - and
    sampling that would clone the cleaned page back onto itself, which is a
    tool that does nothing. The scan is a separate fetch."""
    js = (PKG / "static" / "js" / "paint.js").read_text(encoding="utf-8")
    at = js.index("function loadScanSnapshot(")
    body = js[at:at + 700]
    assert "pageUrl(want, 'original')" in body, \
        "it is not asking the server for the scan"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
