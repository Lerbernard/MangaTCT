"""A drawing can sit on top of the typesetting - and the tool gets out of the way.

lee: *"i shou d be able to move the text out of the text folder and to move
other layers above the text folder, i shoud be able to click and hold the text
layer wiythout going into the text edit tab and if im using a tool like the
brush or any other tool and i clcik a text box and open the text edit tab it
shoud automaicaly diactive the tool"*.

Text was always drawn last - on screen and in the export - so nothing painted
could ever cover a word. Now there are two bands, and a layer belongs to one of
them:

    the artwork
    the paint that is UNDER the text     (baked into the plate, as before)
    the text
    the paint that is OVER the text      (composited after render_page)

Offered a free interleave instead, lee picked the two bands, so that is what
this is: a drawing is under all the text or over all of it, never between two
of them. It costs one extra PNG per page, and only on pages that use it.

Drag a layer across the Text block in the list to move it between bands. The
list draws the bands in that order, so where a row sits is what the page does.

The other two are about not being interrupted:

* A text row is a CLICK to open the typesetting panel and a PRESS-AND-DRAG to
  restack - the panel replaces the whole list, so opening it on mousedown
  pulled the list out from under the drag before it went anywhere.
* Picking a text box with a paint tool armed puts the tool away. The panel
  swaps to the typesetting controls, the armed tool is no longer on screen, and
  the next drag painted a stroke across the page instead of moving the words.
"""
import os
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

RED = [85, 45, 255]        # BGR of #ff2d55


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 240, np.uint8)
    cv2.ellipse(img, (230, 150), (130, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (230, 150), (130, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    st = p.pages[0]
    st.regions = [{"id": 1, "kind": "bubble", "order": 0,
                   "bbox": [150, 110, 160, 80],
                   "bubble_bbox": [110, 70, 240, 160],
                   "polygon": [[150, 110], [310, 110], [310, 190], [150, 190]],
                   "confidence": 0.9, "src_text": "テスト",
                   "dst_text": "UNDER OR OVER"}]
    st.detected = True
    return p


@pytest.fixture()
def page(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = str(tmp_path / "over")
    p = _project(root)
    editor.do_typeset(p, 0)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip('chromium unavailable')
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        try:
            yield pg, p, root, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _bar_over_the_words(pg):
    """A solid red bar right across where the typesetting is."""
    pg.evaluate("""(()=>{ layers.push({id:layerSeq++, type:'shape',
        shape:'rect', col:'#ff2d55', sz:4, fill:true, op:1, visible:true,
        pts:[{x:150,y:120},{x:310,y:180}]});
      repaintAll(); renderLayers(); queueSync(); })()""")
    pg.wait_for_timeout(2200)


def _export(p, root):
    from mangatl import editor
    p.settings["export_dir"] = root
    p.settings["export_name"] = "out"
    os.makedirs(editor.export_root(p), exist_ok=True)
    return cv2.imread(editor.export_page(p, 0))


def _dark_in(img, box):
    x0, y0, x1, y1 = box
    return float((img[y0:y1, x0:x1].astype(int).sum(2) < 260).mean())


# ----------------------------------------------------------- the two bands

def test_a_layer_under_the_text_does_not_cover_it(page):
    pg, p, root, errs = page
    _bar_over_the_words(pg)
    assert pg.evaluate("!!layers[0].over") is False, "it started in the wrong band"
    ex = _export(p, root)
    assert ex is not None
    red = float((np.abs(ex.astype(int) - np.array(RED)).sum(2) < 70).mean())
    # the bar is 160x60 of a 460x300 page - about 7% - less whatever the
    # typesetting drawn on top of it takes back
    assert red > 0.03, f"the bar is not on the page at all ({red:.3f})"
    # the typesetting is drawn ON TOP of it, so there is black ink inside the bar
    assert _dark_in(ex, (155, 125, 305, 175)) > 0.02, \
        "the words vanished under a layer that is supposed to be beneath them"
    assert not errs, errs[:2]


def test_the_same_layer_moved_over_the_text_covers_it(page):
    pg, p, root, errs = page
    _bar_over_the_words(pg)
    pg.evaluate("setLayerOver(layers[0].id, true)")
    pg.wait_for_timeout(2200)
    assert pg.evaluate("!!layers[0].over") is True
    assert p.pages[0].paint_over, "the over-the-text overlay never reached the server"
    ex = _export(p, root)
    assert _dark_in(ex, (155, 125, 305, 175)) < 0.005, \
        "the layer is over the text and the text is still showing through"
    assert not errs, errs[:2]


def test_the_band_survives_a_round_trip(page):
    pg, _p, _root, _e = page
    _bar_over_the_words(pg)
    pg.evaluate("setLayerOver(layers[0].id, true)")
    pg.wait_for_timeout(400)
    back = pg.evaluate("(()=>{const w=serializeLayers(); loadLayers(w);"
                       " return !!layers[0].over;})()")
    assert back is True, "which side of the text it is on was not saved"


def test_moving_it_back_puts_the_words_back(page):
    pg, p, root, _e = page
    _bar_over_the_words(pg)
    pg.evaluate("setLayerOver(layers[0].id, true)")
    pg.wait_for_timeout(2200)
    pg.evaluate("setLayerOver(layers[0].id, false)")
    pg.wait_for_timeout(2200)
    assert not p.pages[0].paint_over, "the over-the-text file was left behind"
    ex = _export(p, root)
    assert _dark_in(ex, (155, 125, 305, 175)) > 0.02, \
        "moving it back under the text did not bring the words back"


def test_the_list_draws_the_bands_in_the_right_order(page):
    pg, _p, _root, _e = page
    _bar_over_the_words(pg)
    pg.evaluate("""(()=>{ layers.push({id:layerSeq++, type:'shape',
        shape:'circle', col:'#2cdd60', sz:4, fill:false, op:1, visible:true,
        pts:[{x:20,y:20},{x:90,y:80}]});
      repaintAll(); renderLayers(); })()""")
    pg.evaluate("setLayerOver(layers[0].id, true)")
    pg.wait_for_timeout(300)
    kinds = pg.evaluate("""JSON.stringify([...document.querySelectorAll(
        '#stackList > .lay, #stackList > .textband')].map(
          e=>e.classList.contains('textband') ? 'TEXT'
            : (e.getAttribute('data-lid') ? 'paint' : 'other')))""")
    import json
    k = json.loads(kinds)
    assert k.index('paint') < k.index('TEXT'), \
        "the over-the-text layer is not above the Text block"
    assert k.count('paint') == 2 and k.index('TEXT') < k.count('paint') + 1


# ------------------------------------------- not being interrupted

def test_picking_a_text_box_puts_the_armed_tool_away(page):
    pg, _p, _root, _e = page
    pg.evaluate("setToolTab('paint'); toggleBrush(true)")
    assert pg.evaluate("paintArmed()") is True
    pg.evaluate("select(1)")
    pg.wait_for_timeout(200)
    assert pg.evaluate("paintArmed()") is False, \
        "the brush is still armed while the typesetting panel is open"
    assert pg.evaluate("document.getElementById('paint').style.pointerEvents")\
        == 'none', "the paint canvas is still swallowing clicks"
    assert pg.evaluate("sel") == 1, "and the text was not selected"


def test_picking_a_text_box_with_no_tool_armed_changes_nothing(page):
    pg, _p, _root, errs = page
    pg.evaluate("select(1)")
    pg.wait_for_timeout(150)
    assert pg.evaluate("sel") == 1
    assert not errs, errs[:2]


def test_a_press_on_a_text_row_does_not_open_the_typesetting_panel(page):
    pg, _p, _root, _e = page
    pg.evaluate("select(null); setToolTab('paint')")
    pg.wait_for_timeout(200)
    row = pg.evaluate("""(()=>{const r=document.querySelector(
        '#stackList .lay[data-tid]');
        if(!r) return null; const b=r.getBoundingClientRect();
        return {x:b.x+b.width/2, y:b.y+b.height/2};})()""")
    assert row, "no text row in the layer list"
    pg.mouse.move(row["x"], row["y"])
    pg.mouse.down()
    pg.mouse.move(row["x"], row["y"] + 30, steps=4)
    assert pg.evaluate("sel") is None, \
        "pressing and dragging a text row opened the typesetting panel"
    pg.mouse.up()
    pg.wait_for_timeout(200)


def test_a_click_on_a_text_row_still_opens_it(page):
    pg, _p, _root, _e = page
    # The Text block is folded when the panel opens - lee: *"make it pre
    # collapes by default"* - so unfold it before reaching for a row in it.
    pg.evaluate("select(null); setToolTab('paint');"
                " if(textShut) toggleTextFold();")
    pg.wait_for_timeout(300)
    row = pg.evaluate("""(()=>{const r=document.querySelector(
        '#stackList .lay[data-tid]');
        const b=r.getBoundingClientRect();
        return {x:b.x+b.width/2, y:b.y+b.height/2};})()""")
    pg.mouse.move(row["x"], row["y"])
    pg.mouse.down()
    pg.mouse.up()
    pg.wait_for_timeout(250)
    assert pg.evaluate("sel") == 1, "a plain click no longer selects the text"
