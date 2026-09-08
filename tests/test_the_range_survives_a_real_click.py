# -*- coding: utf-8 -*-
"""The range survives a REAL click on the side panel - and stays visible.

lee, testing: *"the whole not unslecting text when i clcik on the side bard
is still not working"* and *"only the outine and color say only ob teh
selceted text everything else does teh whole tetx box"*.

Two different faults wearing one symptom:

* The range was surviving underneath (it lives in the editor's state), but
  the browser only PAINTS ::selection while the box is focused - so the
  moment a panel control took focus the highlight vanished and the range
  looked thrown away. The editor now decorates the held range in the same
  amber while the box is blurred (`textbox.js`), and the decoration yields
  the moment focus returns, so there is only ever ONE highlight.

* Opacity - the one range tool added after the `pv` guard was written -
  bypassed it in `currentPatch`, so fading a range also saved the number as
  the BLOCK's opacity on the debounced save, and the whole box faded.

Driven with the real mouse throughout, because a dispatched event moves no
focus and this whole family of bugs lives in focus moves - the same lesson
this suite has now paid for three times.
"""
import json
import shutil
import threading

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import browserpool
from where import PKG                                       # noqa: E402


def _serve(tmp_root):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(tmp_root, ignore_errors=True)
    p = Project(None, tmp_root)
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "x",
        "dst_text": "the hot springs in this region"}]
    p.pages[0].detected = True
    p.save()
    editor.do_typeset(p, 0)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return p, srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def test_a_real_drag_a_real_well_click_and_the_range_holds():
    from mangatl import editor
    root = scratch("_tmp_realrange")
    p, srv, was, base = _serve(root)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 1000})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(600)
            box = pg.evaluate(
                "(()=>{const r=document.querySelector('#overlay .tgrp')"
                ".getBoundingClientRect();"
                "return {x:r.x+r.width/2, y:r.y+r.height/2};})()")
            pg.mouse.click(box["x"], box["y"])
            pg.wait_for_timeout(500)
            pg.mouse.dblclick(box["x"], box["y"])
            pg.wait_for_timeout(700)
            assert pg.evaluate("editing") == 1, "the box did not open"
            # a REAL drag across part of the first row
            row = pg.evaluate(
                "(()=>{const r=document.querySelector('#canvasEdit p')"
                ".getBoundingClientRect();"
                "return {x:r.x, y:r.y+r.height/2, w:r.width};})()")
            pg.mouse.move(row["x"] + 2, row["y"])
            pg.mouse.down()
            pg.mouse.move(row["x"] + row["w"] * 0.6, row["y"], steps=8)
            pg.mouse.up()
            pg.wait_for_timeout(300)
            rng = pg.evaluate("editRange()")
            assert rng and rng["e"] > rng["s"], rng

            # a REAL click on the shadow well (scrolled into view first -
            # a click below the fold lands on nothing and proves nothing)
            pg.evaluate("document.getElementById('lySh')"
                        ".closest('.colwell').scrollIntoView({block:'center'})")
            pg.wait_for_timeout(200)
            well = pg.evaluate(
                "(()=>{const r=document.getElementById('lySh')"
                ".closest('.colwell').getBoundingClientRect();"
                "return {x:r.x+r.width/2, y:r.y+r.height/2};})()")
            pg.mouse.click(well["x"], well["y"])
            pg.wait_for_timeout(400)
            # the box stayed open, the range held, and - THE POINT - the
            # person can still SEE it: the held range wears the amber
            # decoration while the panel has the focus
            assert pg.evaluate("editing") == 1, \
                "clicking a colour well closed the box mid-edit"
            assert pg.evaluate("editRange()") == rng, "the range was lost"
            held = pg.evaluate(
                "[...document.querySelectorAll('#canvasEdit .tbheld')]"
                ".map(e=>e.textContent).join('')")
            assert held, "the range went invisible when the panel took focus"

            # a REAL click on a swatch in the picker
            sw = pg.evaluate(
                "(()=>{const s=document.querySelector('#pkSw i[style]');"
                "if(!s) return null; const r=s.getBoundingClientRect();"
                "return {x:r.x+r.width/2, y:r.y+r.height/2};})()")
            assert sw, "the picker never opened"
            pg.mouse.click(sw["x"], sw["y"])
            pg.wait_for_timeout(1800)          # the debounced save lands
            got = pg.evaluate(
                "(()=>{const r=regions.find(x=>x.id===1);"
                "const ov=r.layout_override||{};"
                "return {spans:ov.spans||[], shadow:ov.shadow||''};})()")
            assert got["spans"] and any(
                "shadow" in (sp.get("st") or {}) for sp in got["spans"]), \
                "the shadow never reached the range"
            assert not got["shadow"], \
                "the range's shadow leaked into the block"
            # ...and back in the box, the decoration yields to the browser's
            # own highlight - one highlight, never two
            pg.evaluate("tbFocus()")
            pg.wait_for_timeout(250)
            assert pg.evaluate(
                "document.querySelectorAll('#canvasEdit .tbheld').length") \
                == 0, "two highlights again"
            assert not errs, errs[:2]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_ranges_opacity_does_not_fade_the_block_on_the_save():
    """The `pv` guard, asked of the one field that skipped it."""
    import re
    src = open(str(PKG / "static" / "js" / "typesetting-edit.js"),
               encoding="utf8").read()
    body = src.split("function currentPatch(")[1].split("\nfunction ")[0]
    m = re.search(r"opacity:\(\$\('lyOpacity'\)[\s\S]{0,220}?pv\('opacity'",
                  body)
    assert m, "opacity is read raw off the panel again - a range's " \
              "opacity will save as the block's"
