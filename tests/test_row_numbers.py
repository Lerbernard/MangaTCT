"""The number on the page and the number in the list are the same number.

lee sent two screenshots — the sidebar and the page — and said *"i notices that
the box 5 and box 7 ar swith look into that"*. He was right, and the cause is
not the reading order at all: both views print `(r.order??0)+1` off the same
array, so they cannot disagree in one render. One of them was simply not
redrawn.

Every region POST ends with `reorder(p, i)` on the server, which compacts the
order values — so **any** reply can come back renumbered. Three call sites
replaced `regions` and then refreshed the typesetting and the sidebar but never the
boxes: `saveTypesetting` (twice, including its undo) and `autoFit`. The badges kept
the numbers from before. `showPage` had the same shape of hole from the other
side: it refreshed the list immediately but only drew the boxes later, from the
image's load handler, so a reply that renumbered a cached page left the badges
stale until something else happened to redraw them.

Reproduced before the fix, with four boxes whose orders were 0, 1, 2, 4 — the
state a compaction changes:

    server orders before: [0, 1, 2, 4]
    start   badges {0:1, 1:2, 2:3, 3:5}   rows {0:1, 1:2, 2:3, 3:5}
    server orders after:  [0, 1, 2, 3]
    after   badges {0:1, 1:2, 2:3, 3:5}   rows {0:1, 1:2, 2:3, 3:4}
                                                             ^ box 3 disagrees

There is one `setRegions()` now, in core.js, and it redraws the boxes, the
typesetting and the list from the same array. Every site that takes new region data
goes through it; the last test here fails if a new assignment appears anywhere
else, which is the only way this stays fixed.
"""
import re
import shutil
import threading
from pathlib import Path

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

JS = PKG / "static" / "js"
CSS = PKG / "static" / "css" / "editor.css"

# the numbers the page shows, the numbers the list shows, and any id where the
# two disagree
NUMBERS = """(()=>{
  const badges=Object.fromEntries([...document.querySelectorAll('#stage .tagf')]
    .map(e=>[e.dataset.id, e.textContent.trim()]));
  const rows=Object.fromEntries([...document.querySelectorAll('#list .lrow')]
    .map(e=>[/select\\((\\d+)/.exec(e.getAttribute('onclick'))[1],
             e.querySelector('.chip').textContent.trim()]));
  return {badges, rows,
          bad: Object.keys(rows).filter(i=>badges[i]!==rows[i])};
})()"""


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 900, 3), 240, np.uint8)
    for k in range(4):
        cv2.rectangle(img, (120 + k * 190, 120), (200 + k * 190, 270),
                      (30, 30, 30), 2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    # orders 0, 1, 2, 4 — a gap, which the next reorder() will compact away.
    # Gaps are ordinary: anything that renumbers mid-session produces one.
    p.pages[0].regions = [
        {"id": k, "kind": "bubble", "order": o,
         "bbox": [120 + k * 190, 120, 80, 150],
         "bubble_bbox": [120 + k * 190, 120, 80, 150],
         "polygon": [[120 + k * 190, 120], [200 + k * 190, 120],
                     [200 + k * 190, 270], [120 + k * 190, 270]],
         "src_text": "テストの文章", "dst_text": f"LINE {k}",
         "confidence": 0.9}
        for k, o in enumerate((0, 1, 2, 4))]
    p.pages[0].detected = True
    return p


def test_the_page_and_the_list_never_disagree_about_a_number():
    """In a real browser, against the real server: after every action that can
    renumber, every badge equals its row's number."""
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = scratch("_tmp_rownum")
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
            pg.evaluate("setTab('edit'); setView('original')")
            browserpool.settled(pg)

            first = pg.evaluate(NUMBERS)
            assert first["bad"] == [], first
            assert first["rows"]["3"] == "5", \
                f"the fixture's gap did not survive to the browser: {first}"

            # a typesetting save: the path that used to leave the badges behind
            pg.evaluate("saveTypesetting(0, true, null, false)")
            pg.wait_for_timeout(1200)
            after = pg.evaluate(NUMBERS)
            assert after["bad"] == [], f"the save left the badges stale: {after}"
            assert after["rows"]["3"] == "4", \
                "the server did not renumber, so this proves nothing"

            for js, wait in (("autoFit(1)", 900),
                             ("moveOrder(3,-1)", 900),
                             ("upd(2,{kind:'sfx'})", 900),
                             ("del(1)", 1100)):
                pg.evaluate(js)
                pg.wait_for_timeout(wait)
                now = pg.evaluate(NUMBERS)
                assert now["bad"] == [], f"after {js}: {now}"

            # And a reload draws the boxes from the DATA, not from the
            # picture's load handler. `showPage` refreshes the list the moment
            # the reply lands but used to leave the boxes until the image
            # arrived, so a page whose render is slow — or cached and re-fetched
            # — showed the new numbers in the list beside the old ones on the
            # page. Proven by making the picture never arrive at all.
            p.pages[0].regions[-1]["order"] = 9        # renumber on the server
            pg.evaluate("window.readyImage=()=>new Promise(()=>{});"
                        "showPage(cur)")
            pg.wait_for_timeout(900)
            slow = pg.evaluate(NUMBERS)
            assert slow["bad"] == [], \
                f"the badges waited for the picture: {slow}"
            assert "10" in slow["rows"].values(), \
                f"the fixture's renumber never arrived: {slow}"
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_sidebar_text_behaves_like_text():
    """lee: *"allow me to edit the side bard text ... allow me to select and copy
    and paste etc like a regulart text box"*.

    Two things stopped it. A `draggable` card in Chromium starts a drag instead
    of a selection, so nothing in the row could be picked out with the mouse at
    all; and the click that ends a drag-selection rebuilt the whole list, which
    threw the selection away before it could be copied. The row drags from its
    grip now, and a click that merely finished selecting text is left alone.
    """
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = scratch("_tmp_rowtext")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('original')")
            browserpool.settled(pg)

            assert pg.evaluate(
                "document.querySelector('#list .lrow')"
                ".getAttribute('draggable')") == "false", \
                "the row is draggable, so its text cannot be selected"
            # The three-dot grip is gone — lee: *"remove teh 3 dots"*. The
            # whole head is the handle, which is what `armRowDrag` is armed
            # from, so there is more of it to grab and none of it is a speck.
            assert pg.evaluate("!document.querySelector('#list .lgrip')"), \
                "the grip is back"
            assert pg.evaluate("!!document.querySelector('#list .rowhead')"), \
                "nothing to drag the row by"

            # drag across the Japanese line, then let go: the selection must
            # survive the click that follows
            box = pg.evaluate(
                "(()=>{const e=document.querySelector('#list .lrow .ja');"
                "const b=e.getBoundingClientRect();"
                "return {x:b.x,y:b.y,w:b.width,h:b.height};})()")
            pg.mouse.move(box["x"] + 2, box["y"] + box["h"] / 2)
            pg.mouse.down()
            pg.mouse.move(box["x"] + box["w"] - 2, box["y"] + box["h"] / 2,
                          steps=8)
            pg.mouse.up()
            pg.wait_for_timeout(350)
            assert pg.evaluate("String(window.getSelection())").strip() == \
                "テストの文章", "the drag selected nothing"
            pg.wait_for_timeout(300)
            assert pg.evaluate("String(window.getSelection())").strip() == \
                "テストの文章", "the click after the drag wiped the selection"

            # the grip still drags the row, so reordering did not become
            # impossible on the way
            assert pg.evaluate(
                "(()=>{const g=document.querySelector('#list .rowhead');"
                "armRowDrag(g);"
                "return g.closest('.lrow').draggable;})()") is True

            # a select() called by hand — from the page, a link, the keyboard —
            # is never blocked by a selection left lying about in the list
            assert pg.evaluate("String(window.getSelection())").strip() == \
                "テストの文章"
            # ...and the edit boxes are exactly as tall as their text, with
            # nothing to drag: lee asked for the expanding to go and for them
            # to just fit. See growBox() in panels.js.
            pg.evaluate("select(2)")
            pg.wait_for_timeout(400)
            got = pg.evaluate("""(()=>{
                const t=document.querySelector('.rinline textarea');
                return {resize:getComputedStyle(t).resize,
                        h:Math.round(t.getBoundingClientRect().height),
                        need:t.scrollHeight};})()""")
            assert got["resize"] == "none", got
            assert got["h"] + 3 >= got["need"], got
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_only_one_place_replaces_the_region_list():
    """The guard that keeps it fixed. Fifteen sites each remembered their own
    subset of "redraw the boxes, the typesetting, the list" — three of them got it
    wrong, and nothing said so. `setRegions` in core.js is the only writer now."""
    pat = re.compile(r"(?<![\w.$])regions\s*=\s*(?!=)")
    offenders = []
    for f in sorted(JS.glob("*.js")):
        if f.name == "core.js":
            continue                      # where setRegions lives
        for n, line in enumerate(f.read_text(encoding="utf8").splitlines(), 1):
            if pat.search(line) and "setRegions" not in line:
                offenders.append(f"{f.name}:{n}: {line.strip()[:60]}")
    assert not offenders, \
        "these bypass setRegions() and can leave the two views disagreeing:\n" \
        + "\n".join(offenders)
    core = (JS / "core.js").read_text(encoding="utf8")
    assert "function setRegions(" in core
    # it must refresh all three surfaces, or it is just a rename
    body = core[core.index("function setRegions("):]
    body = body[:body.index("\n}\n")]
    for call in ("drawBoxes()", "drawOverlay()", "renderList()"):
        assert call in body, f"setRegions does not {call}"


def test_the_row_is_dragged_by_its_grip_not_by_its_text():
    panels = (JS / "panels.js").read_text(encoding="utf8")
    assert 'draggable="false"' in panels
    assert 'draggable="true"' not in panels, \
        "a draggable row cannot have its text selected in Chromium"
    assert "armRowDrag(this)" in panels
    assert "lgrip" not in panels, "the three-dot grip is back on the row"
    ops = (JS / "region-ops.js").read_text(encoding="utf8")
    assert "function armRowDrag" in ops and "function listTextSelected" in ops
    assert "if(listTextSelected(ev)) return;" in ops, \
        "select() must leave a finished text selection alone"
    css = CSS.read_text(encoding="utf8")
    assert ".lrow .rowhead{" in css and "cursor:grab" in css
    assert ".lrow .tx{" in css and "user-select:text" in css
    # The text boxes below the head fit their text and have no grip at all —
    # lee: *"get rid of teh expanding on the boxes ... it shou djust always
    # fit the text"*. See growBox() in panels.js.
    assert "resize:none" in css
