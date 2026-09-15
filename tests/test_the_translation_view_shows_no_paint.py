"""The Translation view is the artwork as it came - no strokes on it.

lee, with his Translation view of page 001 showing the healing he had painted
in the Image view (a box's writing half gone, another box wiped): *"on the
tranlation tab some of teh man cenning that i did is shouing up on that tab"*.

`setView` hides the paint canvas when the view changes. But a page opens in
the Translation view, and on that first change there is no canvas yet; the
page's saved layers arrive after it, `ensureCanvas` makes the canvas, and it
was made visible - so every stroke was drawn over the original scan. The
canvases are now born in the state the current view wants (`paintShownIn`),
and `setView` hides the canvas above the text as well as the one below it.
"""
import base64
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _png_data_url(w, h):
    patch = np.full((h, w, 4), (255, 255, 255, 255), np.uint8)
    ok, buf = cv2.imencode(".png", patch)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 30, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [100, 100, 150, 80],
        "bubble_bbox": [80, 80, 190, 120],
        "polygon": [[100, 100], [250, 100], [250, 180], [100, 180]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    # A heal the person painted, saved with the page the way the editor saves it.
    p.pages[0].paint_layers = [
        {"t": "p", "id": 1, "x": 120, "y": 110, "png": _png_data_url(90, 50),
         "label": "Heal", "g": "r", "op": 1, "visible": True}]
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    p = _project(str(tmp_path / "nopaint"))
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip("chromium unavailable")
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1300, "height": 950})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


_SHOWN = """(()=>{
  const vis = id => { const c=document.getElementById(id);
    if(!c) return null;
    const s=getComputedStyle(c);
    return s.display!=='none' && s.visibility!=='hidden'; };
  return {view: typeof view!=='undefined'?view:null, paint: vis('paint'),
          over: vis('paintOver')};})()"""


def _open_page(pg):
    pg.evaluate("setTab('edit'); showPage(0)")
    pg.wait_for_function(
        "()=>{const i=document.getElementById('img');"
        "return i&&i.complete&&i.naturalWidth>0;}", timeout=60000)
    pg.wait_for_function(
        "!(document.getElementById('pageLoading')||{classList:"
        "{contains:()=>false}}).classList.contains('on')", timeout=60000)
    pg.wait_for_timeout(800)
    browserpool.settled(pg)


def test_a_page_opened_in_the_translation_view_shows_none_of_its_paint(ed):
    pg, _p, errs = ed
    _open_page(pg)
    assert pg.evaluate("view") == "original", "fixture: the page opens in Translation"
    got = pg.evaluate(_SHOWN)
    assert got["paint"] is not True, "the strokes are on the Translation view: %r" % got
    assert got["over"] is not True, got
    assert not errs, errs[:2]


def test_the_paint_is_there_in_the_image_view_and_gone_again_after(ed):
    pg, _p, errs = ed
    _open_page(pg)
    pg.evaluate("setView('typeset')")
    pg.wait_for_timeout(800)
    got = pg.evaluate(_SHOWN)
    assert got["paint"] is True, "fixture: no paint canvas in the Image view (%r)" % got
    pg.evaluate("setView('original')")
    pg.wait_for_timeout(500)
    got = pg.evaluate(_SHOWN)
    assert got["paint"] is not True and got["over"] is not True, got
    assert not errs, errs[:2]
