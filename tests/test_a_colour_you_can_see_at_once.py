# -*- coding: utf-8 -*-
"""A colour you can see at once, and one highlight rather than two.

Two of the four things lee reported against the text box:

  *"when ever i chnage teh color it take a while to update and it not
  consistent"* - and, earlier, *"the color doesnt change until i change page
  and go back or reload the page"*.

  *"teher a bouble heilightes going on it shoud be one"*.

THE COLOUR. Everything the panel touches is written into `r.style` and the
overlay is redrawn on the spot; the round trip that follows only writes it
down. `pick`/`num` therefore read `r.style` FIRST and `layout_override` -
the last answer the server gave - second, and the comment on `num` says
exactly why. `inkPair` was the one place that read them the other way
round, so a colour picked on a block that had ever been saved kept painting
the OLD one until the server answered. Measured before the fix: the redraw
finished in 4ms and the letters changed colour 660ms later, when the
`layout_preview` POST landed - and never at all when it didn't, which is
the reload lee had to do.

THE HIGHLIGHT. The mirror under the box draws the selection itself, as an
amber band cut on the same glyph boundaries as the ink, so it survives the
panel taking the browser's own selection away. The browser's `::selection`
slab was still painting on top of it: two bands, and twice the tint where
they overlapped. The mirror's band is the one that stays.
"""
import os
import shutil
import threading

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import mangatl

FONT = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                    "fonts", "Bangers-Regular.ttf")


def _project(root, saved_fg="#111111"):
    """One block whose colour has ALREADY been saved into the override -
    which is the state the bug needed. A block nobody has restyled has no
    `layout_override.fg` to shadow the panel with."""
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 900, 3), 240, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [60, 60, 780, 160], "bubble_bbox": [60, 60, 780, 160],
        "polygon": [[60, 60], [840, 60], [840, 220], [60, 220]],
        "src_text": "x", "dst_text": "WAVE TO THE CAT", "confidence": .9,
        "manual": True,
        "layout_override": {"lines": ["WAVE TO THE CAT"], "locked": True,
                            "font": FONT, "font_size": 34, "stroke": 2,
                            "fg": saved_fg, "edge": "#ffffff"}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


def _serve(p):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    editor.do_typeset(p, 0, reset=False)
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def test_a_picked_colour_paints_before_the_server_hears_about_it():
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_col_now")
    p = _project(root)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(600)
            pg.evaluate("select(1)")
            pg.wait_for_timeout(400)
            # the saved colour is on the letters
            painted = """(()=>{const f=document
              .querySelector('#overlay .tgrp .tf');
              return f?getComputedStyle(f).webkitTextFillColor:null;})()"""
            assert pg.evaluate(painted) == "rgb(17, 17, 17)", \
                pg.evaluate(painted)
            # THE POINT: pick a colour and read the letters in the SAME
            # turn of the event loop. Nothing has been sent anywhere yet.
            got = pg.evaluate("""(()=>{
              const f=$('lyFg'); f.value='#cc0000';
              f.removeAttribute('data-auto');
              onTypesetStyle(1);
              const t=document.querySelector('#overlay .tgrp .tf');
              return t?getComputedStyle(t).webkitTextFillColor:null;})()""")
            assert got == "rgb(204, 0, 0)", \
                "the letters still wear the saved colour straight after " \
                "the pick (%r) - the screen is waiting on the server" % got
            # ...and it stays picked while the round trips land behind it
            pg.wait_for_timeout(1600)
            assert pg.evaluate(painted) == "rgb(204, 0, 0)", \
                "the colour came back and then went away again"
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_outline_colour_shows_at_once_too():
    """The rim was read in the same wrong order on the very next line."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_edge_now")
    p = _project(root)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(600)
            pg.evaluate("select(1)")
            pg.wait_for_timeout(400)
            got = pg.evaluate("""(()=>{
              const f=$('lyEdge'); f.value='#0066ff';
              f.removeAttribute('data-auto');
              onTypesetStyle(1);
              const s=document.querySelector('#overlay .tgrp .ts');
              return s?getComputedStyle(s).webkitTextStrokeColor:null;})()""")
            assert got == "rgb(0, 102, 255)", \
                "the outline still wears the saved colour: %r" % got
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_selection_wears_one_highlight_and_the_browser_draws_it():
    """lee: *"teher a bouble heilightes going on it shoud be one"*.

    There were two for a while - the browser's tint and a band the mirror
    drew by hand underneath - and the overlap read as twice the colour. The
    band won that round, because the browser used to throw its own
    selection away the moment a colour well took focus.

    The band lost the next one. It was placed by measurement and stood as
    tall as the tallest RUN rather than as tall as the letters, so on a
    sound effect with a resized word in it it came out as an amber slab
    across the middle of the word; lee sent a picture. *"i want it GONE"*.

    It is gone, and the reason it existed went with the swap to a real
    editor: the selection lives in the editor's state now, so nothing can
    throw it away. What is left is the browser's own highlight, which sits
    on the glyphs it highlights by construction and cannot be off by a
    pixel."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_one_band")
    p = _project(root)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(600)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            pg.evaluate("(()=>{ tbSetSelection(5,7); })()")
            pg.wait_for_timeout(400)
            assert pg.evaluate("JSON.stringify(editRange())") == \
                '{"s":5,"e":7}', "the selection never became a range"

            # NOTHING is drawn by hand any more
            assert pg.evaluate(
                "document.querySelectorAll('[data-hl]').length") == 0, \
                "the mirror is drawing a band again - that is the slab"

            # ...and the browser's own tint is back on, see-through
            slab = pg.evaluate("""(()=>{
              let hit=[];
              for(const sh of document.styleSheets){
                let rules; try{ rules=sh.cssRules; }catch(e){ continue; }
                for(const r of rules||[]){
                  if(r.selectorText && /#canvasEdit.*::(-moz-)?selection/
                       .test(r.selectorText))
                    hit.push(r.style.backgroundColor||r.style.background||'');
                }
              }
              return hit;})()""")
            assert slab, "the ::selection rule vanished altogether"
            for bg in slab:
                assert "255, 196, 0" in bg or "255,196,0" in bg, \
                    "the browser draws no highlight and nothing else does " \
                    "either: %r" % bg
                assert "0.32" in bg or ".32" in bg, \
                    "the tint is not see-through - the letters go under a " \
                    "solid slab again: %r" % bg
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_highlight_lands_on_the_letters_it_marks():
    """Measured off the browser's own selection rectangle against the
    glyphs it covers - which is the whole reason the hand-drawn band was
    not worth keeping."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_band_cut")
    p = _project(root)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(600)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            pg.evaluate("(()=>{ tbSetSelection(0,4); })()")
            pg.wait_for_timeout(400)
            off = pg.evaluate("""(()=>{
              const se=window.getSelection();
              if(!se||!se.rangeCount) return null;
              const hl=se.getRangeAt(0).getBoundingClientRect();
              // the same four characters, measured on the text itself
              const ta=$('canvasEdit');
              const tn=(function f(n){ if(n.nodeType===3) return n;
                for(const c of n.childNodes){const g=f(c); if(g) return g;}
                return null;})(ta);
              const rg=document.createRange();
              rg.setStart(tn,0); rg.setEnd(tn,4);
              const want=rg.getBoundingClientRect();
              return {dx:Math.abs(hl.x-want.x),
                      dw:Math.abs(hl.width-want.width)};})()""")
            assert off is not None, "nothing is selected to measure"
            assert off["dx"] < 1.0 and off["dw"] < 1.0, \
                "the highlight is %.2fpx off and %.2fpx wide of the letters" \
                % (off["dx"], off["dw"])
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_three_effect_switches_reach_the_overlay_in_the_same_turn():
    """Task #91: *"Flipping outer glow, outline, or inner glow in the panel
    doesn't redraw the live editor text immediately."*

    The same rule as the colours above, asked of the EFFECTS: set the glow,
    the inner glow and the outline width, and read the overlay's own DOM in
    the same turn of the event loop, long before the 600ms save debounce
    can have sent anything. `inkRun` builds the layers from the live panel
    (`runStyle` reads `r.style` first), so the spans must exist at once."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_fx_now")
    p = _project(root)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(600)
            pg.evaluate("select(1)")
            pg.wait_for_timeout(400)
            got = pg.evaluate("""(()=>{
              const n=k=>document.querySelectorAll(k).length;
              const out={before:{glow:n('#overlay .tsh.tglow'),
                                 ig:n('#overlay .tg')}};
              const g=$('lyGlow'); g.value='#d81f1f';
              g.removeAttribute('data-auto');
              onTypesetStyle(1);
              out.glow=n('#overlay .tsh.tglow');
              const i=$('lyIGlow'); i.value='#1428ff';
              i.removeAttribute('data-auto');
              onTypesetStyle(1);
              out.ig=n('#overlay .tg');
              const s=$('lyStroke'); s.value='9';
              onTypesetStyle(1);
              const ts=document.querySelector('#overlay .ts');
              out.sw=ts?ts.style.webkitTextStroke:null;
              return out;})()""")
            assert got["glow"] > got["before"]["glow"], \
                "the outer glow waits for the server (%r)" % got
            assert got["ig"] > got["before"]["ig"], \
                "the inner glow waits for the server (%r)" % got
            # 9 nominal = 18px at scale 1 (`inkRun` strokes at twice the
            # width and masks nothing here); anything over 10 is the new
            # width at any plausible zoom, and the old width was under 3.
            assert got["sw"] and float(got["sw"].split("px")[0]) > 10, \
                "the outline width did not land on the letters at once " \
                "(%r)" % got
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
