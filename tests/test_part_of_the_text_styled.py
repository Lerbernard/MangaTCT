# -*- coding: utf-8 -*-
"""Part of the text, styled by itself - Photoshop-fashion.

lee: *"if te user selects part of teh text ... theey shoud be able to
modifly that soesific part of teh text with all teh tools and if teh user
change a spesific part of teh text and slects the while box now, the are
with confilects for exmaple if thy have difent color or gradients shoud be
empthy like photoshop does it"*.

The model: `layout_override.spans` - [{s, e, st}] character ranges over the
flat text of the block's lines joined with newlines, each carrying its
own style (colours, gradients, outline width, glow, inner glow, shadow -
`render.SPAN_KEYS`). This file is about the PAINT half of that list, which
is all of it but two: a face and a size also change how much ROOM the
words take, and what follows from that - refitting, the panel, the
handles - lives in `test_a_word_in_its_own_size.py`.

## How both renderers draw it, and the way they used to

There were two ways. A span that changed the metrics was laid out RUN BY
RUN - a flow, the way any text engine sets mixed type. Every other span,
which is to say almost all of them, was drawn by painting the WHOLE block
once per distinct style and cutting the copies into vertical BANDS at the
glyph boundaries, so that each copy showed only over its own characters.
The bands partitioned the page: no pixel was painted twice, and an effect
that bled past a seam was drawn in its neighbour's style.

The bands are gone. A letter's ink is not inside its advance box - the
diagonal of an A overhangs both ways, and a heavy sound-effect face
overhangs a long way - so a vertical cut at the boundary slices through
the ink of the glyph beside it, and the letter comes out with a hard seam
down it, half in one colour and half in the other. No amount of precision
in the cut helps, because the cut is in the wrong place by construction.
lee photographed it twice and then named the whole thing in one line:
*"it shoud apply to the letter it self and not a box behiod teh letter"*.
A band IS a box behind the letter.

So there is one way now, and every span goes down it: `render.flow_runs`
places the runs, `_ink_layer` draws one style's runs per pass, `drawText`
lays out the same flow with `align-items:baseline`, and the box you type
into mirrors that run for run and goes fully transparent - so what you see
while typing is the page with a caret. Nothing is clipped anywhere, which
is why a colour can only ever land on the characters that carry it.
"""
import os
import re
import shutil

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import mangatl
from mangatl import render as render_mod

FONT = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                    "fonts", "Bangers-Regular.ttf")


def _project(root, spans):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((360, 900, 3), 235, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    flat = "Y-YOU RENTED\nOUT THIS ENTIRE\nCOTTAGE FOR US?!"
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [150, 40, 600, 280],
        "bubble_bbox": [150, 40, 600, 280],
        "polygon": [[150, 40], [750, 40], [750, 320], [150, 320]],
        "src_text": "x", "dst_text": flat.replace("\n", " "),
        "confidence": .9, "manual": True,
        "layout_override": {
            "lines": flat.split("\n"), "font_size": 56, "locked": True,
            "stroke": 3, "fg": "#000000", "edge": "#ffffff", "font": FONT,
            "spans": spans}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p, flat


# ------------------------------------------------------------ the model

def test_the_override_builder_takes_spans_and_scrubs_them():
    from mangatl.editor import _clean_spans
    got = _clean_spans([
        {"s": 4, "e": 8, "st": {"fg": "#d81f1f", "glow_size": "5",
                                "junk": "x", "font_size": 99}},
        {"s": 9, "e": 9, "st": {"fg": "#000000"}},        # empty range
        {"s": 3, "e": 5, "st": {}},                       # nothing to say
        "not a span",
        {"s": "a", "e": 8, "st": {"fg": "#fff000"}},      # bad offsets
    ])
    assert got == [{"s": 4, "e": 8,
                    "st": {"fg": "#d81f1f", "glow_size": 5.0,
                           "font_size": 99.0}}], got
    # A SIZE RIDES A SPAN NOW - stage two, done. It is not paint, so a line
    # carrying one is laid out run by run instead of painted whole and cut
    # into bands; see `test_a_word_in_its_own_size.py` for the whole of it.
    assert "font" in render_mod.SPAN_KEYS
    assert "font_size" in render_mod.SPAN_KEYS
    assert set(render_mod.METRIC_KEYS) == {"font", "font_size"}


def test_every_character_is_drawn_exactly_once():
    """The invariant the band masks used to carry, in the model that
    replaced them.

    The bands guaranteed it about PIXELS - every pixel of the page belonged
    to exactly one style - and paid for it by cutting through letters. The
    flow guarantees it about CHARACTERS, which is the thing that was
    actually wanted: the runs of all the styles, put back in the order
    their x positions put them, are the block's own lines, each character
    once and no character twice. A style that drew a character it does not
    own would show up here as an extra."""
    root = scratch("_tmp_span_once")
    p, flat = _project(root, [])
    try:
        a = flat.index("THIS ENTIRE")
        p.pages[0].regions[0]["layout_override"]["spans"] = [
            {"s": a, "e": a + 11, "st": {"fg": "#d81f1f"}}]
        from mangatl import editor
        editor.do_typeset(p, 0, reset=False)
        page = p.materialize(0)
        r = page.regions[0]
        lay = r.layout
        f = render_mod._font(lay.font_path, lay.font_size)
        ov = render_mod.style_of(r)
        spans = render_mod._spans_of(r, lay)
        assert spans, "the record's spans never reached the renderer"
        flow = render_mod.flow_runs(r, lay, f, ov, spans, "")
        assert len(flow) == 2, "one base style + one span style"

        # every piece of every style, gathered by the row it sits on
        rows = {}
        for _st, pieces in flow:
            for cx, cy, text, _ff, _pl in pieces:
                rows.setdefault(round(cy, 2), []).append((cx, text))
        drawn = []
        for _cy in sorted(rows):
            drawn.append("".join(t for _x, t in sorted(rows[_cy])))
        assert drawn == [ln for ln in lay.lines if ln], \
            "the runs do not add back up to the block's own lines:\n%r\n%r" \
            % (drawn, lay.lines)

        # ...and the span's own style draws the span's own characters and
        # nothing else
        spanned = "".join(
            t for st, pieces in flow if st
            for _x, _y, t, _ff, _pl in pieces)
        assert spanned.replace("\n", "") == "THIS ENTIRE", spanned
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_export_paints_the_span_and_only_the_span():
    root = scratch("_tmp_span_paint")
    p, flat = _project(root, [])
    try:
        a = flat.index("THIS ENTIRE")
        p.pages[0].regions[0]["layout_override"]["spans"] = [
            {"s": a, "e": a + 11, "st": {"fg": "#d81f1f"}}]
        from mangatl import editor
        editor.do_typeset(p, 0, reset=False)
        out = editor.render_index(p, 0, "typeset", commit=False)
        im = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
        b, g, rch = im[..., 0].astype(int), im[..., 1].astype(int), \
            im[..., 2].astype(int)
        red = (rch > 150) & (g < 90) & (b < 90)
        dark = (rch < 80) & (g < 80) & (b < 80)
        assert red.sum() > 200, "the span's red never made the page"
        assert dark.sum() > 500, "the block's own black is gone with it"
        # the red lives on the middle row, the black elsewhere
        ys = np.where(red)[0]
        assert ys.mean() == pytest.approx(im.shape[0] / 2, abs=60), \
            "the red is not where THIS ENTIRE is"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_render_stamp_sees_a_span_change():
    """Restyling a range must retire the cached picture, or the preview
    shows the block before the words changed colour."""
    from mangatl import editor
    root = scratch("_tmp_span_stamp")
    p, flat = _project(root, [])
    try:
        editor.do_typeset(p, 0, reset=False)
        a = editor._render_stamp(p, 0, "typeset")
        p.pages[0].regions[0]["layout_override"]["spans"] = [
            {"s": 0, "e": 5, "st": {"fg": "#d81f1f"}}]
        b = editor._render_stamp(p, 0, "typeset")
        assert a != b, "a span edit does not change the picture's identity"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_fit_key_does_not_see_a_span_change():
    """Paint-only, by design: the same words in the same places, so the
    remembered fitting must keep answering."""
    from mangatl import editor, typeset
    root = scratch("_tmp_span_fitkey")
    p, flat = _project(root, [])
    try:
        editor.do_typeset(p, 0, reset=False)
        page = p.materialize(0)
        cfg = editor._typeset_cfg(p)
        a = typeset.page_fit_key(page, cfg)
        p.pages[0].regions[0]["layout_override"]["spans"] = [
            {"s": 0, "e": 5, "st": {"fg": "#d81f1f"}}]
        page2 = p.materialize(0)
        b = typeset.page_fit_key(page2, cfg)
        assert a == b, "a paint-only span re-runs the whole fitting"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------- the live editor

def test_the_browser_flow_start_to_finish():
    """Select part of the text in the box you type into, restyle it, click
    out: the range carries the style, the save carries the range, the
    whole-box panel shows the conflicted field EMPTY, and setting that
    field block-wide strips the span copies - every step of lee's ask."""
    import threading
    from http.server import ThreadingHTTPServer
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_span_flow")
    p, flat = _project(root, [])
    p.pages[0].regions[0]["layout_override"]["lines"] = ["OUT THIS ENTIRE"]
    p.pages[0].regions[0]["dst_text"] = "OUT THIS ENTIRE"
    editor.do_typeset(p, 0, reset=False)
    p.save()
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
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(400)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(600)
            pg.evaluate("""(()=>{
              const ta=document.getElementById('canvasEdit');
              const tn=(function find(n){ if(n.nodeType===3) return n;
                for(const c of n.childNodes){const f=find(c); if(f) return f;}
                return null;})(ta);
              const rg=document.createRange();
              rg.setStart(tn,4); rg.setEnd(tn,8);
              const se=window.getSelection();
              se.removeAllRanges(); se.addRange(rg);})()""")
            pg.wait_for_timeout(350)
            assert pg.evaluate("JSON.stringify(editRange())") == \
                '{"s":4,"e":8}', "the selection never became a range"
            pg.evaluate("""(()=>{
              const f=$('lyFg'); f.value='#d81f1f';
              f.removeAttribute('data-auto');
              onTypesetStyle(1);})()""")
            pg.wait_for_timeout(250)
            got = pg.evaluate("JSON.stringify((regions.find(x=>x.id===1)"
                              ".layout_override||{}).spans)")
            assert got == '[{"s":4,"e":8,"st":{"fg":"#d81f1f"}}]', got
            # the box goes transparent and the mirror carries the fill
            assert pg.evaluate("""(()=>{
              const c=getComputedStyle($('canvasEdit'));
              return c.webkitTextFillColor;})()""") \
                == "rgba(0, 0, 0, 0)", \
                "the box's own ink still paints over the styled range"
            pg.wait_for_timeout(900)             # the debounced save
            pg.evaluate("closeCanvasEdit(true)")
            pg.wait_for_timeout(1000)
            # the save carried the range
            sv = pg.evaluate("""(async()=>{
              const j=await api(`/api/page/0`);
              const rr=(j.regions||[]).find(x=>x.id===1);
              return JSON.stringify(((rr||{}).layout_override||{})
                                    .spans);})()""")
            assert '"fg":"#d81f1f"' in sv, \
                "the range never reached the server: %r" % sv
            # whole box selected, conflicted field EMPTY - Photoshop-fashion
            assert pg.evaluate("$('lyFg')?$('lyFg').value:null") == "", \
                "a field the spans disagree about claims one answer"
            # ...and setting it block-wide applies to everything
            pg.evaluate("""(()=>{
              const f=$('lyFg'); f.value='#0044cc';
              f.removeAttribute('data-auto');
              onTypesetStyle(1);})()""")
            pg.wait_for_timeout(900)
            left = pg.evaluate("JSON.stringify((regions.find(x=>x.id===1)"
                               ".layout_override||{}).spans)")
            assert left in ("[]", "null"), \
                "the block-wide set left per-range copies behind: %r" % left
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_range_colour_never_becomes_the_blocks_colour():
    """A range edit must never touch the block's own colour.

    The invariant behind lee's report - *"only the word cloudy should be
    orange but the editor shows the whole thing as orange while the exported
    preview gets it right"*, and *"after a while the editor version gets it
    right too"*. Server right, editor wrong, righting itself after a moment is
    the signature of a value pinned locally by `markInFlight` until its own
    reply comes home, and the value that could get pinned is the range's
    colour standing in as the block's.

    **This does not reproduce his case, and it is not a regression test for
    it.** It was written to catch the read-mismatch `panelValue` fixes - the
    snapshot recorded a raw `el.value` where `currentPatch` reads through
    `wellNow` - and it passes with that mismatch put back, so the mismatch is
    not what he saw. It is kept because the invariant is worth holding and
    because the next attempt starts here: whatever the cause turns out to be,
    it ends with these three assertions.

    The base colour is left AUTOMATIC on purpose - that is the state most
    blocks are in and the one least exercised elsewhere.
    """
    import threading
    from http.server import ThreadingHTTPServer
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_span_leak")
    p, flat = _project(root, [])
    # ...no `fg` in the override at all: the well shows what the page worked
    # out, and `wellNow` reports it as not-chosen.
    p.pages[0].regions[0]["layout_override"].pop("fg", None)
    editor.do_typeset(p, 0, reset=False)
    p.save()
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
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(500)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            # a word in the middle, not the whole line
            pg.evaluate("""(()=>{
              const ta=document.getElementById('canvasEdit');
              const tn=(function f(n){ if(n.nodeType===3) return n;
                for(const c of n.childNodes){const g=f(c); if(g) return g;}
                return null;})(ta);
              const rg=document.createRange();
              rg.setStart(tn,2); rg.setEnd(tn,8);
              const se=window.getSelection();
              se.removeAllRanges(); se.addRange(rg);})()""")
            pg.wait_for_timeout(300)
            assert pg.evaluate("!!editRange()")
            # ...coloured through the well, WITHOUT clearing data-auto by
            # hand: that flag is exactly what `wellNow` reads, and clearing it
            # in the test would be testing the case that already worked.
            pg.evaluate("""(()=>{
              const f=document.getElementById('lyFg');
              f.value='#ff8000';
              f.dispatchEvent(new Event('input',{bubbles:true}));
              onTypesetStyle(1);})()""")
            pg.wait_for_timeout(1200)
            got = pg.evaluate("""(()=>{
              const r=regions.find(x=>x.id===1);
              const ov=r.layout_override||{};
              return JSON.stringify({base:ov.fg||'', spans:ov.spans||[]});})()""")
            import json as J
            d = J.loads(got)
            assert d["spans"], "the range never took the colour: %s" % got
            assert d["spans"][0]["st"].get("fg") == "#ff8000", got
            # THE POINT: the block's own colour is untouched.
            assert d["base"] != "#ff8000", \
                "the range's colour was saved as the whole block's: %s" % got
            # ...and nothing pinned it locally either, which is what made the
            # editor and the export disagree for a moment.
            pinned = pg.evaluate("""(()=>{
              if(typeof inFlight==='undefined') return null;
              const m=inFlight.get(1); return m? (m.fg||'') : '';})()""")
            assert pinned in (None, "", "#000000"), \
                "the range's colour is pinned over the block: %r" % pinned
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------- where one letter ends and the next begins

FACES = ["ComicNeue-Bold.ttf", "ComicNeue-Italic.ttf", "Bangers-Regular.ttf",
         "Anton-Regular.ttf", "LuckiestGuy-Regular.ttf", "Kalam-Regular.ttf",
         "PatrickHand-Regular.ttf", "Chewy-Regular.ttf", "Jua-Regular.ttf",
         "GochiHand-Regular.ttf"]

def test_a_colour_lands_on_the_letter_and_not_on_a_box_behind_it():
    """lee, twice, with photographs, and then in his own words: *"it shoud
    apply to the letter it self and not a box behiod teh letter thats teh
    issue we have here"*.

    A spanned block used to be drawn by painting the WHOLE line once per
    style and cutting the copies into vertical bands at the glyph
    ADVANCES. A letter's ink is not inside its advance box - the diagonal
    of an A overhangs both ways, and a heavy sound-effect face overhangs a
    long way - so the cut sliced through the neighbouring glyph and left a
    letter with a hard vertical seam down it, half in each colour.

    Measured here as the shape of the coloured region. A band cut begins
    with a full-height column of colour, because that is what a straight
    cut is. A letter begins with the tip of a stroke - a few pixels. Run
    over every face the app ships, because how far a glyph overhangs its
    advance is a property of the face.
    """
    from mangatl import editor
    fdir = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                        "fonts")
    worst = []
    for face in FACES:
        root = scratch("_tmp_span_shape")
        shutil.rmtree(root, ignore_errors=True)
        from mangatl.project import Project
        p = Project(None, root)
        img = np.full((320, 900, 3), 240, np.uint8)
        p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
        line = "ROAA"
        p.pages[0].regions = [{
            "id": 1, "kind": "sfx", "order": 0,
            "bbox": [60, 50, 780, 200], "bubble_bbox": [60, 50, 780, 200],
            "polygon": [[60, 50], [840, 50], [840, 250], [60, 250]],
            "src_text": "x", "dst_text": line, "confidence": .9,
            "manual": True,
            "layout_override": {
                "lines": [line], "locked": True, "font_size": 80,
                "stroke": 5, "fg": "#ff7a00", "edge": "#ffffff",
                "font": os.path.join(fdir, face),
                # PAINT ONLY - same face, same size. This is the case the
                # bands used to be used for.
                "spans": [{"s": 2, "e": 3, "st": {"fg": "#1428ff"}}]}}]
        p.pages[0].detected = True
        p.pages[0].cleaned = True
        try:
            editor.do_typeset(p, 0, reset=False)
            out = editor.render_index(p, 0, "typeset", commit=False)
            im = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
            b, g, r = (im[..., 0].astype(int), im[..., 1].astype(int),
                       im[..., 2].astype(int))
            blue = (b > 150) & (r < 90) & (g < 90)
            assert blue.sum() > 200, "%s: the range's colour never made " \
                                     "the page" % face
            ys, xs = np.where(blue)
            h = ys.max() - ys.min() + 1
            # the leftmost and rightmost columns of the coloured region
            first = int((xs == xs.min()).sum())
            last = int((xs == xs.max()).sum())
            worst.append((face, first / float(h), last / float(h)))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    for face, lo, hi in worst:
        assert lo < 0.45, \
            "%s: the colour starts with a column %.0f%% of the letter's " \
            "height - that is a straight cut through the glyph beside it, " \
            "not a letter" % (face, lo * 100)
        assert hi < 0.45, \
            "%s: the colour ends on a straight cut (%.0f%% of the " \
            "height)" % (face, hi * 100)


# ----------------------- every tool on the panel, offered to a range

def _sfx_block(spans, extra=None, curve=0):
    """One big word on a flat page, exported, back as BGR."""
    from mangatl.project import Project
    from mangatl import editor
    root = scratch("_tmp_span_fx")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((320, 900, 3), 240, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    fdir = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                        "fonts")
    ov = {"lines": ["ROAA"], "locked": True, "font_size": 80,
          "stroke": 5, "fg": "#ff7a00", "edge": "#ffffff",
          "font": os.path.join(fdir, "LuckiestGuy-Regular.ttf"),
          "spans": spans}
    if curve:
        ov["curve"] = curve
    if extra:
        ov.update(extra)
    p.pages[0].regions = [{
        "id": 1, "kind": "sfx", "order": 0,
        "bbox": [60, 50, 780, 200], "bubble_bbox": [60, 50, 780, 200],
        "polygon": [[60, 50], [840, 50], [840, 250], [60, 250]],
        "src_text": "x", "dst_text": "ROAA", "confidence": .9,
        "manual": True, "layout_override": ov}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    try:
        editor.do_typeset(p, 0, reset=False)
        out = editor.render_index(p, 0, "typeset", commit=False)
        return cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _orange(im):
    b, g, r = (im[..., 0].astype(int), im[..., 1].astype(int),
               im[..., 2].astype(int))
    return (r > 180) & (g > 80) & (g < 160) & (b < 90)


def test_a_ranges_transparency_fades_the_range_and_nothing_else():
    """lee: *"all these affct shodu be able to be doen to xelecetd part of
    a text box with out changing or affceting teh rest of teh text"* - and
    Opacity sits on the same panel as the rest of them.

    A range's number REPLACES the block's over its own characters, exactly
    as every other range key does; the export fades style by style
    (`render._fade` per layer) instead of once over the block."""
    full = _sfx_block([])
    half = _sfx_block([{"s": 2, "e": 3, "st": {"opacity": 40}}])
    o_full, o_half = int(_orange(full).sum()), int(_orange(half).sum())
    # one letter of four went below the mask's threshold...
    lost = o_full - o_half
    assert 0.15 * o_full < lost < 0.4 * o_full, (o_full, o_half)
    # ...and at 40% it is not GONE - the ink still shows, faded
    d = cv2.absdiff(full, half).sum(2)
    assert (d > 20).sum() > 500, "nothing actually faded"


def test_the_x_takes_an_effect_off_the_range_while_the_block_keeps_it():
    """The panel's × with a range selected has to say *no shadow HERE* -
    an emptied field would just fall back to the block's shadow and the ×
    would do nothing. The range carries `NO_FILL` (#00000000), the app's
    own spelling of a colour that is not there, and `render._lit` reads
    any zero-alpha effect colour as OFF rather than drawing it invisibly.
    """
    sh = {"shadow": "#d81f1f", "sh_dist": 8, "sh_blur": 0}
    on = _sfx_block([], extra=sh)
    off = _sfx_block([{"s": 2, "e": 3, "st": {"shadow": "#00000000"}}],
                     extra=sh)
    def red(im):
        b, g, r = (im[..., 0].astype(int), im[..., 1].astype(int),
                   im[..., 2].astype(int))
        return (r > 150) & (g < 90) & (b < 90)
    a, b = int(red(on).sum()), int(red(off).sum())
    assert b < a - 200, ("the range kept its shadow", a, b)
    assert b > 200, "the WHOLE block lost its shadow, not just the range"


def test_the_x_takes_a_gradient_off_the_range_and_the_plain_colour_returns():
    grad = {"fg1": "#1428ff", "fg2": "#1428ff"}
    off = _sfx_block([{"s": 2, "e": 3, "st": {"fg1": "#00000000",
                                              "fg2": "#00000000"}}],
                     extra=grad)
    b, g, r = (off[..., 0].astype(int), off[..., 1].astype(int),
               off[..., 2].astype(int))
    blue = (b > 150) & (r < 90) & (g < 90)
    assert blue.sum() > 200, "the block lost its whole gradient"
    # the range shows the block's own plain fill again
    assert _orange(off).sum() > 2000, \
        "the range shows neither the gradient nor the plain colour"


def test_a_colour_on_a_curved_line_lands_on_the_arc():
    """The bands' one honest job was curved lines - the whole line was
    arced once per style and cut. With the bands gone, `flow_runs` hands
    each style its own slice of the line's `arc_places`, so the range's
    colour is drawn as turned letters exactly where the unspanned arc puts
    them - not as a straight run floating off the curve, and not cut."""
    im = _sfx_block([{"s": 2, "e": 3, "st": {"fg": "#1428ff"}}], curve=60)
    b, g, r = (im[..., 0].astype(int), im[..., 1].astype(int),
               im[..., 2].astype(int))
    blue = (b > 150) & (r < 90) & (g < 90)
    assert blue.sum() > 200, "the colour never made the curved page"
    ys, xs = np.where(blue)
    h = ys.max() - ys.min() + 1
    assert (xs == xs.min()).sum() / float(h) < 0.45, "cut on the left"
    assert (xs == xs.max()).sum() / float(h) < 0.45, "cut on the right"
    # ...and it sits where the arc puts that letter: compare against the
    # same block with no span - the blue must overlap the letter it
    # recoloured, not sit beside it
    plain = _sfx_block([], curve=60)
    om = _orange(plain)
    overlap = (blue & om).sum() / float(blue.sum())
    assert overlap > 0.5, \
        "the recoloured letter is not where the arc drew it (%.0f%%)" \
        % (overlap * 100)


def test_the_span_cleaner_accepts_opacity_and_clamps_it():
    from mangatl import editor
    got = editor._clean_spans([{"s": 0, "e": 2, "st": {"opacity": 250}},
                               {"s": 2, "e": 3, "st": {"opacity": 40}}])
    assert got[0]["st"]["opacity"] == 100.0
    assert got[1]["st"]["opacity"] == 40.0
    assert "opacity" in render_mod.SPAN_KEYS


def test_a_ranges_gradient_fades_across_the_range_and_not_the_block():
    """lee: *"gradient ... still universal"*. The editor painted every
    fill gradient across the WHOLE block's bounds, so a selected middle
    word showed only the middle blend of its ramp - while the export fades
    a style over that style's own letters (`_ink_layer` takes the bbox of
    the style's own mask). One ramp per STYLE now, spanning that style's
    own letters, on both sides."""
    import threading
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor
    from mangatl.project import Project
    from http.server import ThreadingHTTPServer
    root = scratch("_tmp_span_ramp")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((360, 900, 3), 238, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    fdir = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                        "fonts")
    line = "AAAA BBBB CCCC"
    p.pages[0].regions = [{
        "id": 1, "kind": "sfx", "order": 0,
        "bbox": [60, 60, 780, 200], "bubble_bbox": [60, 60, 780, 200],
        "polygon": [[60, 60], [840, 60], [840, 260], [60, 260]],
        "src_text": "x", "dst_text": line, "confidence": .9, "manual": True,
        "layout_override": {
            "lines": [line], "locked": True, "font_size": 60,
            "stroke": 0, "fg": "#111111", "edge": "#ffffff",
            "font": os.path.join(fdir, "LuckiestGuy-Regular.ttf"),
            # the MIDDLE word carries the gradient, angle 90 = left to right
            "spans": [{"s": 5, "e": 9, "st": {"fg1": "#ff0000",
                                              "fg2": "#0000ff",
                                              "grad_angle": 90}}]}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    editor.do_typeset(p, 0, reset=False)
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(900)
            got = pg.evaluate("""(()=>{
              const tf=document.querySelector('#overlay .trunf .tf.grad');
              if(!tf) return null;
              const el=tf.closest('.trunf');
              const m=(tf.style.backgroundImage.match(/-?[\\d.]+px/g)||[])
                       .map(parseFloat);
              return {stops:m, run:el.getBoundingClientRect().width,
                      block:document.querySelector('#overlay .tgrp')
                            .getBoundingClientRect().width};})()""")
            assert got and len(got["stops"]) == 2, got
            span = got["stops"][1] - got["stops"][0]
            # the ramp runs about the RANGE's width (plus the overhang pad),
            # nowhere near the block's
            assert span < got["run"] * 2.2, \
                ("the ramp still fades across the whole block", got)
            assert span > got["run"] * 0.5, ("the ramp collapsed", got)
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_range_style_never_flickers_across_the_block():
    """The TRANSIENT, not the save: while a range wears a gradient, a
    no-change `onTypesetStyle` - opening a picker used to fire one, a slider
    fires one on the press that does not move it - ran the block path, and
    `onTypesetEdit` copied the panel (showing the RANGE's values) onto
    `r.style`, which `runStyle` reads FIRST. The whole block wore the range's
    gradient until the next server reply rebuilt `r.style` - seconds, after a
    save. lee: *"whe i am editing it appears as if its universal but when i
    let teh app site it evently remove teh edits form teh other unslected
    text, it juts takes time"*.

    The read is SYNCHRONOUS with the trigger - the poisoned window opened
    the same instant, so no reply can have cleaned it up before the assert.
    """
    import json as J
    import threading
    from http.server import ThreadingHTTPServer
    browserpool = pytest.importorskip("browserpool")
    from mangatl import editor

    root = scratch("_tmp_span_flicker")
    p, flat = _project(root, [])
    editor.do_typeset(p, 0, reset=False)
    p.save()
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
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(500)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(700)
            pg.evaluate("""(()=>{
              const ta=document.getElementById('canvasEdit');
              const tn=(function f(n){ if(n.nodeType===3) return n;
                for(const c of n.childNodes){const g=f(c); if(g) return g;}
                return null;})(ta);
              const rg=document.createRange();
              rg.setStart(tn,2); rg.setEnd(tn,8);
              const se=window.getSelection();
              se.removeAllRanges(); se.addRange(rg);})()""")
            pg.wait_for_timeout(300)
            assert pg.evaluate("!!editRange()")
            # the RANGE takes a gradient, through the panel's own fields
            pg.evaluate("""(()=>{
              $('lyFg1').value='#1428ff'; $('lyFg2').value='#0aa010';
              onTypesetStyle(1);})()""")
            # THE TRIGGER AND THE READ IN ONE BREATH: a second call with
            # nothing changed takes the block path, and before the fix this
            # very expression came back holding the range's two colours.
            got = J.loads(pg.evaluate("""(()=>{
              onTypesetStyle(1);
              const st=(regions.find(x=>x.id===1)).style||{};
              return JSON.stringify({fg1:st.fg1||'', fg2:st.fg2||'',
                                     size:(regions.find(x=>x.id===1)
                                           .layout||{}).font_size});})()"""))
            assert got["fg1"] != "#1428ff" and got["fg2"] != "#0aa010", \
                ("the range's gradient flickered across the block", got)
            # ...and OPENING a picker writes nothing at all any more: on an
            # EMPTY well the wheel's parked position used to go straight onto
            # the selection as a near-white glow nobody chose.
            got2 = J.loads(pg.evaluate("""(()=>{
              const f=$('lyIGlow');
              openTypesetPicker(f.closest('.colwell'),'lyIGlow',1);
              const st=(regions.find(x=>x.id===1)).style||{};
              const sp=((regions.find(x=>x.id===1).layout_override||{})
                        .spans)||[];
              return JSON.stringify({well:f.value,
                iglow:st.iglow||'',
                span_ig:sp.some(x=>x.st&&x.st.iglow!==undefined)});})()"""))
            pg.evaluate("closePicker()")
            assert got2["well"] == "" and not got2["span_ig"], \
                ("opening the picker wrote a colour by itself", got2)
            pg.wait_for_timeout(1400)      # the debounced save lands
            ov = (editor.PROJECT.pages[0].regions[0]
                  .get("layout_override") or {})
            assert not ov.get("fg1") and not ov.get("fg2"), \
                ("the range's gradient was saved as the block's", ov)
            sp = ov.get("spans") or []
            assert any((x.get("st") or {}).get("fg1") == "#1428ff"
                       for x in sp), ("the range never took it", sp)
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
