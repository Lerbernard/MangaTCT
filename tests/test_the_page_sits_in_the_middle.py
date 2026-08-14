"""Where the page actually sits in the workspace.

lee, on the framing for the fourth time: *"try to fi the issue of teh image not
being centered"*. Nothing in the suite measured this — `test_centred_pages.py`
is about the Settings and Results cards, not the canvas — so the first thing
was to ask the browser where the page is, in every state it can be in:

    first paint (tall page)     L  406 R  407 | T   14 B   14
    turned to the SHORT page    L  186 R  187 | T -599 B  627   <-- here
    turned back to the TALL     L  406 R  407 | T   14 B   14
    Find text dialog up         L  406 R  407 | T   14 B   14
    Fit page                    L  406 R  407 | T   14 B   14
    zoomed to 2x                L  312 R  312 | T -397 B -396
    side panel hidden           L  477 R  477 | T -397 B -396
    side panel back             L  312 R  312 | T -397 B -396
    a page wider than the pane  L -758 R -758 | T-4704 B 2269   <-- and here

One state in nine, and it is the one lee turns pages through all day. The cause
is in `tests/ui/the_paint_layer_is_not_the_last_pages_height.test.js`: an
invisible canvas keeping the previous page's height and making the stage taller
than the picture, so centring the stage scrolled the picture off the top.

These tests are the measurement, kept. They drive a real browser and ask where
the picture ended up, because that is the only thing that answers the question
— a stylesheet can say `centre` and lose.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch

cv2 = pytest.importorskip("cv2")

# Where the picture sits inside the pane it scrolls in. Equal gaps is what
# "centred" means; nothing else is worth asserting.
GAP = """()=>{
  const w=document.getElementById('canvasWrap');
  const i=document.getElementById('img');
  const a=i.getBoundingClientRect(), b=w.getBoundingClientRect();
  return {left: Math.round(a.left-b.left), right: Math.round(b.right-a.right),
          top: Math.round(a.top-b.top), bottom: Math.round(b.bottom-a.bottom),
          iw: Math.round(a.width), ih: Math.round(a.height)};}"""

SLACK = 3          # a pixel of rounding either way, and one for the scrollbar


def _serve(fn, heights=(3000, 900), root=scratch("_tmp_middle")):
    from mangatl import editor
    from mangatl.project import Project

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for k, h in enumerate(heights):
        im = np.full((h, 690, 3), 240, np.uint8)
        cv2.rectangle(im, (40, 40), (650, h - 40), (60, 60, 60), 6)
        p.add_uploaded("p%d.png" % k, cv2.imencode(".png", im)[1].tobytes())
    p.settings["medium"] = "manhwa"
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.wait_for_timeout(1100)
            try:
                return fn(pg)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def _centred(pg, what):
    g = pg.evaluate(GAP)
    assert abs(g["left"] - g["right"]) <= SLACK, \
        "%s: left %d, right %d (%r)" % (what, g["left"], g["right"], g)
    assert abs(g["top"] - g["bottom"]) <= SLACK, \
        "%s: top %d, bottom %d (%r)" % (what, g["top"], g["bottom"], g)
    return g


def test_the_first_page_opens_in_the_middle():
    _serve(lambda pg: _centred(pg, "first paint"))


def test_turning_to_a_shorter_page_stays_in_the_middle():
    """The one that was broken. A 3000-tall page then a 900-tall one, which is
    the pair lee works with all day on a webtoon."""
    def go(pg):
        _centred(pg, "the tall page")
        pg.evaluate("showPage(1)")
        pg.wait_for_timeout(1000)
        g = _centred(pg, "the short page")
        assert g["ih"] < 900, "the fixture did not actually get shorter: %r" % (
            g,)
    _serve(go)


def test_and_back_to_a_taller_one():
    def go(pg):
        pg.evaluate("showPage(1)")
        pg.wait_for_timeout(1000)
        pg.evaluate("showPage(0)")
        pg.wait_for_timeout(1000)
        _centred(pg, "back to the tall page")
    _serve(go)


def test_two_pages_of_the_same_height_are_both_centred():
    """A control. If the fixture were centred whatever happened, the test above
    would pass on the broken code too — it did not, but this says so."""
    def go(pg):
        _centred(pg, "first")
        pg.evaluate("showPage(1)")
        pg.wait_for_timeout(1000)
        _centred(pg, "second")
    _serve(go, heights=(1200, 1200))


def test_a_page_bigger_than_the_pane_is_centred_on_its_middle():
    """Zoomed past the window, "centred" means the middle of the page is in
    front of you and the overhang is equal on both sides — which is a scroll
    position, not a margin."""
    def go(pg):
        pg.evaluate("showPage(1)")
        pg.wait_for_timeout(1000)
        pg.evaluate("zoom=4;applyZoom();centerPageSoon()")
        pg.wait_for_timeout(900)
        g = _centred(pg, "4x")
        assert g["iw"] > 1000, "the fixture is not bigger than the pane: %r" % (
            g,)
    _serve(go)


def test_the_find_text_dialog_does_not_shift_it():
    def go(pg):
        before = _centred(pg, "before")
        pg.evaluate("openDetect()")
        pg.wait_for_timeout(500)
        after = _centred(pg, "dialog up")
        assert before["left"] == after["left"], (before, after)
    _serve(go)


def test_the_pane_changing_width_recentres_it():
    """A page fitted to a pane that no longer exists comes out the wrong size
    for the one you are looking at, and centring it then only puts its middle
    in front of you."""
    def go(pg):
        pg.evaluate("document.getElementById('side').style.display='none'")
        pg.wait_for_timeout(800)
        _centred(pg, "side panel hidden")
        pg.evaluate("document.getElementById('side').style.display=''")
        pg.wait_for_timeout(800)
        _centred(pg, "side panel back")
    _serve(go)


def test_the_paint_layer_does_not_outgrow_the_picture():
    """The cause, measured directly: the invisible canvas in the stage must be
    the size of the picture, not of whatever page was open when someone last
    painted."""
    def go(pg):
        pg.evaluate("showPage(1)")
        pg.wait_for_timeout(1000)
        g = pg.evaluate("""()=>{
          const s=document.getElementById('stage');
          const i=document.getElementById('img');
          return {stage: Math.round(s.getBoundingClientRect().height),
                  img: Math.round(i.getBoundingClientRect().height),
                  border: parseFloat(getComputedStyle(s).borderTopWidth)};}""")
        # The stage is the picture plus its two transparent borders and nothing
        # else. More than that is something invisible propping it open.
        assert abs(g["stage"] - (g["img"] + 2 * g["border"])) <= 4, g
    _serve(go)
