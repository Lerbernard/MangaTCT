"""One strip of tools, always on screen.

lee: *"make a side bar lke this for all the tool and make tool folder for them
like photoshop where you can right clcik to slected similiar tool from a small
windown, move every too there exaxt for the main zoom an teh filded"*, with a
picture of GIMP's toolbox.

The tools lived in four tabbed sections of the side panel: pick a section to
see its buttons, and the buttons for the other three were not on screen at all.
Reaching for the clone stamp while the brush was out meant changing section
first, and nothing anywhere showed what was armed unless you happened to be
looking at the right tab.

A toolbox is one place that is always there. Tools that do the same KIND of job
share a slot — marquee, lasso and wand are all "choose part of the page" — and
the slot shows whichever of them you used last, with a corner mark saying there
are others behind it. Right-click, or press and hold, to pick another.

What stays out: the zoom stepper in the top bar, which is a readout with two
buttons rather than a tool, and every numeric field — those are settings FOR a
tool and belong beside that tool's controls.
"""
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
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "tb"))
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
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _slots(pg):
    return pg.evaluate(
        "[...document.querySelectorAll('#toolbox .tbtn')].map(b=>b.dataset.slot)")


def _right_click(pg, slot):
    b = pg.evaluate(f"""(()=>{{const r=document.querySelector(
        '.tbtn[data-slot={slot}]').getBoundingClientRect();
        return {{x:r.left+r.width/2, y:r.top+r.height/2}};}})()""")
    pg.mouse.click(b["x"], b["y"], button="right")
    pg.wait_for_timeout(350)


# --------------------------------------------------------------- it is there

def test_every_tool_is_in_it(ed):
    pg, _p, errs = ed
    assert _slots(pg) == ["move", "select", "text", "paint", "fill",
                          "retouch", "shape", "pick", "view"]
    tools = pg.evaluate("TOOLBOX.flatMap(g=>g.tools.map(t=>t.k))")
    for want in ("xf", "rect", "lasso", "wand", "addtext", "brush", "eraser",
                 "fill", "stamp", "heal", "shrect", "shcirc",
                 "shline", "eyedrop", "hand", "zoomin", "zoomout"):
        assert want in tools, want
    assert not errs, errs[:2]


def test_the_zoom_stepper_stays_in_the_top_bar(ed):
    """lee: *"move every too there exaxt for the main zoom an teh filded"*. The
    − 100% + cluster is a readout, not a tool: there is nothing to arm."""
    pg, _p, errs = ed
    for keep in ("zoutBtn", "zlabel", "zinBtn"):
        assert pg.evaluate(
            f"!!document.querySelector('#pageTools #{keep}')"), keep
    # ...and the numbers stay beside the tool they belong to
    assert pg.evaluate("!document.querySelector('#toolbox input')")
    assert not errs, errs[:2]


def test_it_is_only_up_where_there_is_a_page(ed):
    pg, _p, errs = ed
    assert pg.evaluate(
        "getComputedStyle(document.getElementById('toolbox')).display") != "none"
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)
    assert pg.evaluate(
        "getComputedStyle(document.getElementById('toolbox')).display") == "none"
    pg.evaluate("setTab('edit')")
    browserpool.settled(pg)
    assert pg.evaluate(
        "getComputedStyle(document.getElementById('toolbox')).display") != "none"
    assert not errs, errs[:2]


# ------------------------------------------------------------- it arms things

def test_clicking_a_slot_arms_its_tool_and_lights_it(ed):
    pg, _p, errs = ed
    pg.evaluate("document.querySelector('.tbtn[data-slot=paint]').click()")
    pg.wait_for_timeout(500)
    assert pg.evaluate("brush") is True
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=paint]').classList.contains('on')")
    assert not errs, errs[:2]


def test_arming_from_the_panel_lights_the_toolbox_too(ed):
    """The toolbox is the one place that says what is armed, so it has to be
    right however the tool was reached."""
    pg, _p, errs = ed
    pg.evaluate("toggleStamp(true)")
    pg.wait_for_timeout(500)
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=retouch]').classList.contains('on')")
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=retouch]').dataset.tool") == "stamp"
    assert not errs, errs[:2]


def test_only_one_slot_is_lit_at_a_time(ed):
    pg, _p, errs = ed
    pg.evaluate("document.querySelector('.tbtn[data-slot=paint]').click()")
    pg.wait_for_timeout(400)
    pg.evaluate("document.querySelector('.tbtn[data-slot=select]').click()")
    pg.wait_for_timeout(400)
    lit = pg.evaluate(
        "[...document.querySelectorAll('#toolbox .tbtn.on')].map(b=>b.dataset.slot)")
    assert lit == ["select"], lit
    assert pg.evaluate("brush") is False
    assert not errs, errs[:2]


# ----------------------------------------------------------------- the folders

def test_a_slot_with_several_tools_says_so(ed):
    pg, _p, errs = ed
    marked = pg.evaluate("""[...document.querySelectorAll('#toolbox .tbtn')]
        .filter(b=>b.querySelector('.tbmore')).map(b=>b.dataset.slot)""")
    # "move" joined them when the transform gained a second tool: the same
    # box with its corners already loose (Ctrl+T).
    assert set(marked) == {"move", "select", "paint", "retouch", "shape",
                           "view"}
    assert not errs, errs[:2]


def test_right_clicking_one_offers_the_rest(ed):
    """Retouch held three: the clone stamp and two healing brushes. It holds
    two now — lee: *"remoev teh regualr healing brush, its ass"* — and the one
    that survives is simply "Healing brush", because there is no longer a
    second one for a name to tell it apart from."""
    pg, _p, errs = ed
    _right_click(pg, "retouch")
    rows = pg.evaluate(
        "[...document.querySelectorAll('#tbflyout .tbrow span')].map(s=>s.textContent)")
    assert rows == ["Clone stamp", "Healing brush"]
    assert not errs, errs[:2]


def test_picking_one_out_of_the_flyout_arms_it_and_the_slot_keeps_it(ed):
    pg, _p, errs = ed
    _right_click(pg, "retouch")
    pg.evaluate("document.querySelectorAll('#tbflyout .tbrow')[1].click()")
    pg.wait_for_timeout(500)
    assert pg.evaluate("heal") is True
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=retouch]').dataset.tool") == "heal"
    assert pg.evaluate("!document.getElementById('tbflyout')"), "it stayed open"
    # ...and the slot remembers it: putting the tool away and clicking the
    # slot again brings back the one you chose, not the first in the list
    pg.evaluate("stopBrush()")
    pg.wait_for_timeout(300)
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=retouch]').dataset.tool") == "heal"
    assert not errs, errs[:2]


def test_a_slot_with_one_tool_has_no_flyout(ed):
    pg, _p, errs = ed
    _right_click(pg, "text")
    assert pg.evaluate("!document.getElementById('tbflyout')")
    assert not errs, errs[:2]


def test_escape_and_a_click_away_put_the_flyout_back(ed):
    pg, _p, errs = ed
    _right_click(pg, "shape")
    assert pg.evaluate("!!document.getElementById('tbflyout')")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(250)
    assert pg.evaluate("!document.getElementById('tbflyout')")
    _right_click(pg, "shape")
    assert pg.evaluate("!!document.getElementById('tbflyout')")
    pg.mouse.click(900, 500)
    pg.wait_for_timeout(250)
    assert pg.evaluate("!document.getElementById('tbflyout')")
    assert not errs, errs[:2]


def test_a_flyout_never_opens_off_the_bottom_of_the_window(ed):
    """It is fixed to the viewport beside a button that can be anywhere down a
    long strip — measured, because a menu you have to scroll the window to see
    is a menu that is not there."""
    pg, _p, errs = ed
    _right_click(pg, "view")            # the last slot, at the bottom
    box = pg.evaluate("""(()=>{const r=document.getElementById('tbflyout')
        .getBoundingClientRect();
        return {top:r.top, bottom:r.bottom, h:innerHeight};})()""")
    assert box["top"] >= 4, box
    assert box["bottom"] <= box["h"] - 4, box
    assert not errs, errs[:2]


# ------------------------------------------------------------------ the icons

def test_every_tool_has_an_icon(ed):
    pg, _p, errs = ed
    missing = pg.evaluate("""TOOLBOX.flatMap(g=>g.tools)
        .filter(t=>!TB_ICON[t.icon]).map(t=>t.k)""")
    assert missing == [], missing
    drawn = pg.evaluate(
        "[...document.querySelectorAll('#toolbox .tbtn svg path')]"
        ".filter(p=>(p.getAttribute('d')||'').length>10).length")
    assert drawn == len(_slots(pg)), drawn
    assert not errs, errs[:2]


# ------------------------------------------------ names, not explanations

def test_a_tool_is_named_not_explained():
    """lee, with a picture of the hand tool's tooltip reading *"Hand (H) —
    double-click for 100%"*: *"clean up the ui from explaininga buch of stuff
    it shoud just name out stuff not explainit like teh hand tool for
    example"*.

    A tooltip on a button says WHICH button it is. What it can also do, and
    when, is not a thing to read while pointing at it.
    """
    from pathlib import Path
    import re
    tb = (PKG / "static" / "js"
          / "toolbar.js").read_text(encoding="utf-8")
    names = re.findall(r"name:'([^']+)'", tb)
    assert names, "no tools at all"
    assert "Hand (H)" in names, names
    for n in names:
        assert "—" not in n and " for " not in n, n
        assert len(n) <= 28, n


def test_the_page_layer_is_called_page():
    """It read *"Page — the artwork"*, which is the row telling you what a page
    is. lee: *"teh tab shoud just say page not age on backgorund"*."""
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "paint.js").read_text(encoding="utf-8")
    assert '<span class="lnm">Page</span>' in js
    assert "Page — the artwork" not in js
