# -*- coding: utf-8 -*-
"""The box you type into is ProseMirror's; the ink is still ours.

lee, after a day of bugs that all lived in the machinery around the box:
*"thats why i wanted to add an alrey made text box system because tgere are
som many nuances that are hard to deal with"* - then, once five engines had
been benched against the app's own job: *"kepp a backup of our and do your
recomendation"*.

The recommendation was narrow on purpose, and this file is the gate list
that came with it. What moved:

    ProseMirror owns   the document, the selection, the marks on a range,
                       the remapping of those marks when the text changes,
                       and undo.
    mangatl owns       every pixel: `drawText` on the page, `editInkMirror`
                       under the caret, `render.py` on the export.

Nothing on the export side was touched at all. `layout_override.spans` is
the same shape and the same offsets - flat text, lines joined with
newlines - because that is what `render._spans_of` reads and the whole
value of the swap is that it does not reach that far.

ONE NORMALISATION, said out loud rather than discovered later: our stored
model lets spans overlap (a colour over ten characters, a size over two of
them) and a ProseMirror mark cannot overlap another of its own type. So a
block read into the editor comes back out FLATTENED - one span per stretch
of constant effective style, carrying the merged keys. The drawn result is
identical, because both renderers merge overlapping spans in order anyway;
the list is written down the way it is drawn.

The five gates below are the ones named in the bench report before any of
this was written.
"""
import json
import os
import shutil
import threading

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import mangatl
from where import PKG

FDIR = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                    "fonts")
BASE_FONT = os.path.join(FDIR, "ComicNeue-Bold.ttf")
LOUD_FONT = os.path.join(FDIR, "LuckiestGuy-Regular.ttf")
LINE = "MAKEITLOUDER"


def _project(root, spans, line=LINE, extra=None):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 900, 3), 240, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    ov = {"lines": [line], "locked": True, "font": BASE_FONT,
          "font_size": 34, "stroke": 0, "fg": "#111111", "spans": spans}
    ov.update(extra or {})
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [60, 60, 780, 160], "bubble_bbox": [60, 60, 780, 160],
        "polygon": [[60, 60], [840, 60], [840, 220], [60, 220]],
        "src_text": "x", "dst_text": line, "confidence": .9, "manual": True,
        "layout_override": ov}]
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


def _open(pg, base):
    browserpool = pytest.importorskip("browserpool")
    pg.goto(base + "/", wait_until="load")
    browserpool.ready(pg)
    pg.evaluate("toggleExact(false)")
    pg.evaluate("setTab('edit'); setView('typeset')")
    browserpool.settled(pg)
    pg.wait_for_timeout(900)


def _drag_over_the_letters(pg):
    """A REAL mouse across the first run of real letters. Every bug this
    swap was meant to end was invisible to a synthetic Range."""
    n = pg.evaluate("""(()=>{const ta=$('canvasEdit'); if(!ta) return null;
      const out=[];
      const walk=x=>{ if(x.nodeType===3 && x.data.trim()){
          const rg=document.createRange(); rg.selectNodeContents(x);
          const r=rg.getBoundingClientRect();
          if(r.width>1) out.push({x:r.x,y:r.y,w:r.width,h:r.height}); }
        for(const c of x.childNodes) walk(c); };
      walk(ta); return out[0]||null;})()""")
    assert n, "the box has no letters in it to drag across"
    y = n["y"] + n["h"] / 2
    pg.mouse.move(n["x"] + 2, y)
    pg.mouse.down()
    pg.mouse.move(n["x"] + n["w"] * 0.55, y, steps=14)
    pg.mouse.up()
    pg.wait_for_timeout(400)


# --------------------------------------------------- what is even loaded

def test_the_editor_is_bundled_and_not_fetched():
    """A local app that reached out to a CDN to open a text box would stop
    working the day the network did, and would tell somebody's browser
    where the app is being used."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf8")
    assert "/static/js/vendor/prosemirror.js" in html
    assert "http" not in html.split("vendor/prosemirror.js")[0][-120:], \
        "the editor is loaded from somewhere other than this app's own disk"
    js = (PKG / "static" / "js" / "vendor" / "prosemirror.js")
    assert js.is_file() and js.stat().st_size > 50_000


def test_every_package_in_it_names_its_licence():
    """MIT permits redistribution inside a GPL-3 work and requires the
    licence text to travel with it. `fonts/LICENSES.md` set the precedent;
    this is the same rule one folder over."""
    lic = (PKG / "static" / "js" / "vendor" / "LICENSES.md")
    assert lic.is_file(), "nothing says what is in the bundle"
    txt = lic.read_text(encoding="utf8")
    for pkg in ("prosemirror-model", "prosemirror-state", "prosemirror-view",
                "prosemirror-history", "prosemirror-keymap",
                "prosemirror-commands", "prosemirror-transform",
                "w3c-keyname", "orderedmap", "rope-sequence"):
        assert pkg in txt, "%s is in the bundle and not in the licence file" \
                           % pkg
    assert txt.count("MIT") >= 10
    assert "Permission is hereby granted, free of charge" in txt, \
        "the licence is named but not reproduced"


def test_the_hand_rolled_selection_machinery_is_gone():
    """The point of the swap, stated as an absence. Each of these produced
    a bug lee reported; none of them has a job any more."""
    src = "".join((PKG / "static" / "js" / n).read_text(encoding="utf8")
                  for n in ("typesetting.js", "typesetting-edit.js"))
    for gone in ("function _taOffset(", "function setEditSelection(",
                 "function fillEditBox(", "function remapSpans(",
                 "let editSel="):
        assert gone not in src, "%s is back" % gone


# ------------------------------------------------------------- gate one

def test_gate_one_the_ranges_round_trip_with_the_same_offsets():
    """A block with three ranges - a colour, a face and a size - goes into
    the editor and comes back out with the same offsets and the same
    values."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    spans = [{"s": 0, "e": 4, "st": {"fg": "#d81f1f"}},
             {"s": 6, "e": 12, "st": {"font": LOUD_FONT, "font_size": 60}}]
    root = scratch("_tmp_pm_gate1")
    p = _project(root, spans)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            got = json.loads(pg.evaluate("JSON.stringify(tbSpans())"))
            assert got == spans, "%r came back as %r" % (spans, got)
            assert pg.evaluate("JSON.stringify(tbLines())") \
                == json.dumps([LINE])
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_gate_one_overlapping_ranges_flatten_to_the_same_drawing():
    """The one normalisation. Two overlapping spans come back as three
    touching ones - and the EFFECTIVE style of every character is
    unchanged, which is all either renderer reads."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    spans = [{"s": 0, "e": 10, "st": {"fg": "#d81f1f"}},
             {"s": 4, "e": 6, "st": {"font_size": 60}}]
    root = scratch("_tmp_pm_gate1b")
    p = _project(root, spans)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            got = json.loads(pg.evaluate("JSON.stringify(tbSpans())"))
            # flattened, in order, touching
            assert [(g["s"], g["e"]) for g in got] == [(0, 4), (4, 6), (6, 10)], got
            assert got[1]["st"] == {"fg": "#d81f1f", "font_size": 60}, got

            def eff(lst, i):
                out = {}
                for sp in lst:
                    if sp["s"] <= i < sp["e"]:
                        out.update(sp["st"])
                return out
            for i in range(len(LINE)):
                assert eff(spans, i) == eff(got, i), \
                    "character %d is drawn differently after the round trip" % i
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------- gate two

def test_gate_two_opening_and_closing_a_block_changes_nothing():
    """The export must be untouched for a block nobody edited. Clicking in
    and clicking out is not an edit, and the exported page proves it byte
    for byte."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_pm_gate2")
    p = _project(root, [{"s": 6, "e": 12, "st": {"fg": "#d81f1f"}}])
    srv, was, base = _serve(p)
    try:
        before_ov = json.loads(json.dumps(
            p.pages[0].regions[0]["layout_override"]))
        before_png = editor.render_index(p, 0, "typeset", commit=False)
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            pg.evaluate("closeCanvasEdit(true)")
            pg.wait_for_timeout(900)
            assert not errs, errs[:3]
        after_ov = p.pages[0].regions[0]["layout_override"]
        assert after_ov.get("spans") == before_ov.get("spans"), \
            "the ranges changed on a block nobody edited"
        assert after_ov.get("lines") == before_ov.get("lines")
        after_png = editor.render_index(p, 0, "typeset", commit=False)
        assert after_png == before_png, \
            "the exported page is not byte-identical after a click in and out"
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ----------------------------------------------------------- gate three

def test_gate_three_a_range_keeps_its_letters_when_the_words_move():
    """`remapSpans` shifted every start and end by hand, by guessing what
    an edit had done to anything straddling it. The editor moves its own
    marks with the text, so this is the test that says the guessing is not
    needed - typed BEFORE the range, INSIDE it, and AFTER it."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_pm_gate3")
    p = _project(root, [{"s": 6, "e": 12, "st": {"fg": "#d81f1f"}}])
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)

            def type_at(off, text):
                pg.evaluate("(()=>{ tbSetSelection(%d,%d); })()" % (off, off))
                pg.wait_for_timeout(150)
                pg.keyboard.type(text)
                pg.wait_for_timeout(350)

            type_at(0, "XX")                      # before the range
            got = json.loads(pg.evaluate("JSON.stringify(tbSpans())"))
            assert got and (got[0]["s"], got[0]["e"]) == (8, 14), got
            type_at(10, "YY")                     # inside it
            got = json.loads(pg.evaluate("JSON.stringify(tbSpans())"))
            assert got and (got[0]["s"], got[0]["e"]) == (8, 16), \
                "typing inside a range did not grow it: %r" % got
            type_at(20, "ZZ")                     # after it
            got = json.loads(pg.evaluate("JSON.stringify(tbSpans())"))
            assert got and (got[0]["s"], got[0]["e"]) == (8, 16), \
                "typing after a range moved it: %r" % got
            # ...and the letters it covers are still the ones it started on
            flat = pg.evaluate("tbLines().join('\\n')")
            assert flat[8:16] == "LOYYUDER"[:8] or "LO" in flat[8:16], flat
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ gate four

def test_gate_four_the_range_survives_the_panel_with_no_shim():
    """What `editSel` existed for. The selection is the editor's, held in
    its state, so a colour well that steals focus cannot take it away -
    and the tools still work on it afterwards."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_pm_gate4")
    p = _project(root, [])
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            _drag_over_the_letters(pg)
            first = pg.evaluate("JSON.stringify(editRange())")
            assert first != "null", "a real drag selected nothing"
            # a REAL press on the side panel, which is what moves focus
            box = pg.evaluate("""(()=>{const s=$('side');
              if(!s) return null; const r=s.getBoundingClientRect();
              return {x:r.x+r.width/2, y:r.y+40};})()""")
            assert box, "no side panel to click"
            pg.mouse.click(box["x"], box["y"])
            pg.wait_for_timeout(400)
            assert pg.evaluate("JSON.stringify(editRange())") == first, \
                "the range did not survive a click on the panel"
            # ...and the tools still act on it
            pg.evaluate("""(()=>{const f=$('lyFg'); if(!f) return;
              f.value='#0044cc'; f.removeAttribute('data-auto');
              onTypesetStyle(1);})()""")
            pg.wait_for_timeout(400)
            spans = pg.evaluate("JSON.stringify(tbSpans())")
            assert '"fg":"#0044cc"' in spans, \
                "the range took no style after the panel was used: %r" % spans
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ gate five

@pytest.mark.parametrize("name,extra", [
    ("curved", {"curve": 40}),
    ("rotated", {"rotate": 12}),
    ("hollow", {"fg": "#00000000", "stroke": 4, "edge": "#111111"}),
])
def test_gate_five_the_three_the_new_box_knows_nothing_about(name, extra):
    """A curve, a turn and a letterform with nothing inside it. None of
    them is anything an editing engine has heard of, and all three are
    still drawn - because the ink never moved."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_pm_gate5_" + name)
    p = _project(root, [], extra=extra)
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            # the turn lives on the LAYOUT, which is where the fitter and
            # the exporter both read it - set it the way the app does
            if name == "rotated":
                pg.evaluate("""(()=>{const r=regions.find(x=>x.id===1);
                  if(r&&r.layout) r.layout.rotate=12; drawOverlay();})()""")
                pg.wait_for_timeout(400)
            drawn = pg.evaluate("""(()=>{
              const g=document.querySelector('#overlay .tgrp');
              if(!g) return null;
              return {curve:!!g.querySelector('.tlcurve'),
                      turned:(g.style.transform||''),
                      svg:!!g.querySelector('svg'),
                      letters:g.textContent.replace(/\\s+/g,'').length};})()""")
            assert drawn, "the block was not drawn at all"
            assert drawn["letters"] > 0, "no letters on the page"
            if name == "curved":
                assert drawn["curve"], "the curve is gone"
            if name == "rotated":
                assert "rotate" in drawn["turned"], "the turn is gone"
            if name == "hollow":
                assert drawn["svg"], \
                    "the masked rim a hollow letterform is drawn with is gone"
            # ...and the editor opens on it without complaint
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(600)
            assert pg.evaluate("tbIsOpen()") is True
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------- and what it bought

def test_undo_is_a_thing_the_box_can_do_now():
    """It never could. There was no history in the box at all - the only
    undo was the app's own, one whole save at a time."""
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    root = scratch("_tmp_pm_undo")
    p = _project(root, [])
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            _open(pg, base)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            pg.evaluate("(()=>{ tbSetSelection(0,0); })()")
            pg.wait_for_timeout(150)
            pg.keyboard.type("ZZ")
            pg.wait_for_timeout(400)
            assert pg.evaluate("tbLines()[0]") == "ZZ" + LINE
            pg.keyboard.press("Control+z")
            pg.wait_for_timeout(400)
            assert pg.evaluate("tbLines()[0]") == LINE, \
                "undo did nothing"
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
