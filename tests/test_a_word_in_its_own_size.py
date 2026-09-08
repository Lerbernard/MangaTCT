# -*- coding: utf-8 -*-
"""Part of the text in its own face, at its own size.

lee, with two pictures: *"the changing size and fonts happens to teh whole
etxt box instead fo just the selevcted text"*.

Every other range tool is PAINT - it puts a different colour on the same
glyphs in the same places. A face and a size are not: they change how much
room the words take.

That difference used to decide how a spanned line was DRAWN - paint was
painted whole and cut into bands, metrics were set run by run - and it no
longer does. Everything is set run by run now: run after run, each in its
own face at its own size, all of them sharing one baseline, the line
centred on the origin the fitter chose. `flow_runs` does that on the
export and `drawText` does it in the browser with `align-items:baseline` -
the same rule, so the two agree. (Why the bands went, in
`test_part_of_the_text_styled.py`: a vertical cut at a glyph boundary
slices the ink of the letter beside it.)

What the difference still decides is whether the block has to be REFITTED
when a range changes, and that is what this file is about: a colour cannot
move a word, a size can. `render.METRIC_KEYS`, `has_metric_spans`.

The baseline is placed so the line's ink box - the tallest ascender over
the deepest descender across the runs - is centred on the line origin.
For a line of one run that is exactly where PIL's `mm` anchor already puts
it, which is why a block nobody has resized comes out unchanged.

AND THE BOX STOPS RESCALING IT. lee: *"if all the text in a box is the same
, then keep the text box as is but if some of the text is not the same
make chnaging the text box size not change the text size like it does now
to keep it simple"*. Dragging a corner means one new size for the whole
block, and a block where somebody deliberately made one word bigger has no
one size to give - so a corner on such a block re-wraps instead.
"""
import os
import shutil
import threading

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import mangatl
from mangatl import render as R

FDIR = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                    "fonts")
BASE_FONT = os.path.join(FDIR, "ComicNeue-Bold.ttf")
LOUD_FONT = os.path.join(FDIR, "LuckiestGuy-Regular.ttf")
LINE = "MAKE IT LOUDER"
WORD_AT = LINE.index("LOUDER")
# The page tests render for real, and the fitter wraps at spaces whatever
# the box is - so their fixture is ONE word with the range inside it, which
# is a line it cannot break and a run boundary in the middle of it.
PLINE = "GOBIG"
PWORD = 2


def _project(root, spans, line=LINE):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((260, 1000, 3), 242, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [20, 40, 960, 180], "bubble_bbox": [20, 40, 960, 180],
        "polygon": [[20, 40], [980, 40], [980, 220], [20, 220]],
        "src_text": "x", "dst_text": line, "confidence": .9, "manual": True,
        "layout_override": {"lines": [line], "locked": True,
                            "font": BASE_FONT, "font_size": 34,
                            "stroke": 0, "fg": "#111111", "spans": spans}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


# ------------------------------------------------------- what may ride a span

def test_a_face_and_a_size_may_ride_a_range_now():
    assert "font" in R.SPAN_KEYS and "font_size" in R.SPAN_KEYS
    assert set(R.METRIC_KEYS) == {"font", "font_size"}


def test_the_two_that_move_the_letters_are_the_ones_that_flow():
    assert not R.has_metric_spans([(0, 3, {"fg": "#ff0000"})])
    assert R.has_metric_spans([(0, 3, {"font_size": 60})])
    assert R.has_metric_spans([(0, 3, {"font": LOUD_FONT})])
    # a paint-only block keeps the band-and-partition path it always had
    assert not R.has_metric_spans([(0, 3, {"glow": "#fff", "stroke": 4})])


def test_the_cleaner_keeps_a_size_and_a_face_and_refuses_a_stranger():
    from mangatl.editor import _clean_spans
    got = _clean_spans([{"s": 2, "e": 6,
                         "st": {"font_size": "48", "font": BASE_FONT,
                                "fg": "#112233"}}])
    assert got == [{"s": 2, "e": 6, "st": {"fg": "#112233",
                                           "font": BASE_FONT,
                                           "font_size": 48.0}}], got
    # a size the panel's stepper cannot reach, and a face this app does not
    # offer, are both dropped rather than trusted
    bad = _clean_spans([{"s": 0, "e": 4,
                         "st": {"font_size": 0, "font": "/etc/passwd",
                                "fg": "#000000"}}])
    assert bad == [{"s": 0, "e": 4, "st": {"fg": "#000000"}}], bad


# ------------------------------------------------------------- the placement

def _block(spans, size=34, line=LINE, origin=(500, 120)):
    """One block, built by hand: the fitter has its own opinions about
    wrapping and these tests are about where the runs LAND, not about
    where the words break."""
    from mangatl.models import TextLayout, TextRegion
    lay = TextLayout(lines=[line], font_size=size, leading=1.12,
                     line_origins=[origin], font_path=BASE_FONT,
                     fg="#111111", edge="#ffffff", stroke=0,
                     frame=(20, 40, 960, 160))
    r = TextRegion(id=1, bbox=[20, 40, 960, 160], kind="bubble",
                   layout=lay,
                   layout_override={"font": BASE_FONT, "font_size": size,
                                    "stroke": 0, "fg": "#111111",
                                    "spans": spans})
    return r, lay


def test_one_run_lands_exactly_where_the_unflowed_line_does():
    """The invariant that says nothing already working has moved: a block
    with a paint-only span has one set of metrics, so flowing it must put
    the line back where `draw_line`'s own centring puts it."""
    r, lay = _block([])
    f = R._font(lay.font_path, lay.font_size)
    ov = R.style_of(r)
    runs = R.flow_runs(r, lay, f, ov,
                       [(0, len(LINE), {"fg": "#d81f1f"})], "")
    assert len(runs) == 1, runs
    pieces = runs[0][1]
    assert len(pieces) == 1
    x, y, txt, ff, pl = pieces[0]
    assert pl is None, "a straight block grew an arc"
    ox, oy = lay.line_origins[0]
    assert txt == LINE
    assert x == pytest.approx(ox, abs=0.51), (x, ox)
    assert y == pytest.approx(oy, abs=0.51), (y, oy)


def test_the_runs_share_a_baseline_and_the_line_stays_centred():
    spans = [{"s": WORD_AT, "e": len(LINE),
              "st": {"font_size": 60, "fg": "#d81f1f"}}]
    r, lay = _block(spans)
    if True:
        f = R._font(lay.font_path, lay.font_size)
        ov = R.style_of(r)
        got = R.flow_runs(r, lay, f, ov, R._spans_of(r, lay), "")
        assert len(got) == 2, "two styles, two layers"
        flat = [(x, y, t, ff) for _st, ps in got for (x, y, t, ff, _pl) in ps]
        assert {t for _x, _y, t, _f in flat} == {"MAKE IT ", "LOUDER"}
        # ONE BASELINE. `draw_line` centres on the middle of each run's own
        # ascender-to-descender box, so equal baselines means equal
        # `y + (asc - desc) / 2`.
        bases = []
        for _x, y, _t, ff in flat:
            asc, desc = ff.getmetrics()
            bases.append(y + (asc - desc) / 2.0)
        assert max(bases) - min(bases) < 0.51, bases
        # ...and the two runs sit side by side, in reading order, with the
        # whole line centred on the origin the fitter chose.
        small = [q for q in flat if q[2] == "MAKE IT "][0]
        big = [q for q in flat if q[2] == "LOUDER"][0]
        wsm = R._run_width("MAKE IT ", small[3], 0.0)
        wbg = R._run_width("LOUDER", big[3], 0.0)
        assert small[0] + wsm / 2.0 == pytest.approx(big[0] - wbg / 2.0,
                                                     abs=0.51), \
            "the runs do not meet - there is a gap or an overlap"
        left = small[0] - wsm / 2.0
        right = big[0] + wbg / 2.0
        assert (left + right) / 2.0 == pytest.approx(lay.line_origins[0][0],
                                                     abs=0.51), \
            "the line is not centred where the fitter put it"


# ---------------------------------------------------------------- the page

def _ink(p):
    """The exported page, and where its red and its black ink live."""
    from mangatl import editor
    out = editor.render_index(p, 0, "typeset", commit=False)
    im = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    b, g, rr = (im[..., 0].astype(int), im[..., 1].astype(int),
                im[..., 2].astype(int))
    red = (rr > 140) & (g < 90) & (b < 90)
    dark = (rr < 90) & (g < 90) & (b < 90)
    return im, red, dark


def _box(mask):
    ys, xs = np.where(mask)
    assert len(xs), "no ink of that colour on the page"
    return xs.min(), xs.max(), ys.min(), ys.max()


def test_the_exported_word_really_is_bigger_than_the_rest():
    root = scratch("_tmp_flow_page")
    spans = [{"s": PWORD, "e": len(PLINE),
              "st": {"font_size": 68, "fg": "#d81f1f"}}]
    p = _project(root, spans, line=PLINE)
    try:
        from mangatl import editor
        editor.do_typeset(p, 0, reset=False)
        _im, red, dark = _ink(p)
        rx0, rx1, ry0, ry1 = _box(red)
        dx0, dx1, dy0, dy1 = _box(dark)
        assert (ry1 - ry0) > 1.5 * (dy1 - dy0), \
            "the range's size did not reach the page: %d vs %d" \
            % (ry1 - ry0, dy1 - dy0)
        # ...and it sits AFTER the black, not on top of it
        assert rx0 > dx1 - 2, \
            "the runs overlap: black ends at %d, red starts at %d" \
            % (dx1, rx0)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_block_nobody_resized_is_drawn_exactly_as_before():
    """The regression guard for every page already typeset: a paint-only
    span still goes down the band-and-partition path, pixel for pixel."""
    root = scratch("_tmp_flow_noop")
    spans = [{"s": PWORD, "e": len(PLINE), "st": {"fg": "#d81f1f"}}]
    p = _project(root, spans, line=PLINE)
    try:
        from mangatl import editor
        editor.do_typeset(p, 0, reset=False)
        _im, red, dark = _ink(p)
        _rx0, _rx1, ry0, ry1 = _box(red)
        _dx0, _dx1, dy0, dy1 = _box(dark)
        # same size, so the two inks stand the same height
        assert abs((ry1 - ry0) - (dy1 - dy0)) <= 3, \
            "a paint-only span changed the size: %d vs %d" \
            % (ry1 - ry0, dy1 - dy0)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------- and the browser agrees

def test_the_editor_and_the_page_flow_the_line_the_same_way():
    """Measured on both sides and compared as PROPORTIONS, so the editor's
    zoom cannot flatter the answer: how wide the resized word is against
    the rest of the line, and how far along the line it starts."""
    browserpool = pytest.importorskip("browserpool")
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = scratch("_tmp_flow_agree")
    spans = [{"s": PWORD, "e": len(PLINE),
              "st": {"font_size": 68, "fg": "#d81f1f"}}]
    p = _project(root, spans, line=PLINE)
    editor.do_typeset(p, 0, reset=False)
    p.save()
    _im, red, dark = _ink(p)
    rx0, rx1, ry0, ry1 = _box(red)
    dx0, dx1, dy0, dy1 = _box(dark)
    page_ratio = (rx1 - rx0) / float(dx1 - dx0)
    page_tall = (ry1 - ry0) / float(dy1 - dy0)

    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("toggleExact(false)")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            pg.wait_for_timeout(1200)
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(500)
            pg.evaluate("drawOverlay()")
            pg.wait_for_timeout(400)
            got = pg.evaluate("""(()=>{
              const d=document.querySelector('#overlay .tl[data-flow]');
              if(!d) return null;
              const rs=[...d.querySelectorAll('.trunf')].map(w=>{
                const q=w.getBoundingClientRect();
                return {t:w.dataset.c0+'-'+w.dataset.c1,
                        x:q.x, w:q.width, h:q.height};});
              return rs;})()""")
            assert got, "the editor did not flow the line at all"
            assert len(got) == 2, got
            small, big = got[0], got[1]
            assert big["w"] / small["w"] == pytest.approx(page_ratio,
                                                          rel=0.08), \
                "the word is %.2f of the rest in the editor and %.2f on " \
                "the page" % (big["w"] / small["w"], page_ratio)
            assert big["h"] / small["h"] == pytest.approx(page_tall,
                                                          rel=0.15), \
                "the word stands %.2f as tall in the editor and %.2f on " \
                "the page" % (big["h"] / small["h"], page_tall)
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------- the panel and the box

def test_the_size_field_sets_the_range_and_leaves_the_block_alone():
    browserpool = pytest.importorskip("browserpool")
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = scratch("_tmp_flow_panel")
    p = _project(root, [], line=PLINE)
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
            pg.wait_for_timeout(600)
            pg.evaluate("editOnCanvas(1)")
            pg.wait_for_timeout(600)
            pg.evaluate("""(()=>{
              const ta=$('canvasEdit');
              const tn=(function f(n){ if(n.nodeType===3) return n;
                for(const c of n.childNodes){const g=f(c); if(g) return g;}
                return null;})(ta);
              const rg=document.createRange();
              rg.setStart(tn,%d); rg.setEnd(tn,%d);
              const se=window.getSelection();
              se.removeAllRanges(); se.addRange(rg);})()"""
                        % (PWORD, len(PLINE)))
            pg.wait_for_timeout(400)
            was_size = pg.evaluate(
                "(regions.find(x=>x.id===1).layout||{}).font_size")
            pg.evaluate("""(()=>{
              const f=$('lySize'); f.value='68';
              onTypesetStyle(1);})()""")
            pg.wait_for_timeout(400)
            spans = pg.evaluate("JSON.stringify((regions.find(x=>x.id===1)"
                                ".layout_override||{}).spans)")
            assert '"font_size":"68"' in spans or '"font_size":68' in spans, \
                "the size never reached the range: %r" % spans
            now = pg.evaluate(
                "(regions.find(x=>x.id===1).layout||{}).font_size")
            assert now == was_size, \
                "the whole block changed size too (%r -> %r)" % (was_size,
                                                                 now)
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_corner_stops_rescaling_a_block_with_mixed_sizes():
    """lee's simplification: a block with one size still scales with its
    box, a block with more than one re-wraps instead."""
    browserpool = pytest.importorskip("browserpool")
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = scratch("_tmp_flow_corner")
    p = _project(root, [])
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
            pg.wait_for_timeout(600)
            # one size: a corner scales, exactly as it always did
            assert pg.evaluate("""(()=>{
              const r=regions.find(x=>x.id===1);
              return JSON.stringify(resizeFlags('se', false, r));})()""") \
                == '{"fit":true}'
            # more than one: it re-wraps instead
            got = pg.evaluate("""(()=>{
              const r=regions.find(x=>x.id===1);
              r.layout_override=Object.assign({}, r.layout_override,
                {spans:[{s:8,e:14,st:{font_size:68}}]});
              return JSON.stringify(resizeFlags('se', false, r));})()""")
            assert '"fit"' not in got and '"wrap":true' in got, got
            # a PAINT-only span is not a mixed size and still scales
            got2 = pg.evaluate("""(()=>{
              const r=regions.find(x=>x.id===1);
              r.layout_override=Object.assign({}, r.layout_override,
                {spans:[{s:8,e:14,st:{fg:'#d81f1f'}}]});
              return JSON.stringify(resizeFlags('se', false, r));})()""")
            assert got2 == '{"fit":true}', got2
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_you_can_still_select_part_of_a_box_that_holds_two_faces():
    """lee: *"when theere 2 tetx with difent font in a box i cant select any
    part of teh text aymore and none of teh edit lick chnaging size works on
    that box"*.

    A box laid out in runs has the press land on a RUN'S SPAN, not on the
    box. The stage's mousedown guard asked `e.target.id === 'canvasEdit'` -
    an identity check - so it missed, took the click as a click on the
    block, and called `preventDefault`. The browser never started a
    selection, and every range tool then had nothing to work on: the second
    half of lee's sentence follows from the first.

    WITH A REAL MOUSE. A synthetic `Range` sets the selection directly and
    never goes near a mousedown handler, which is exactly why the tests
    written alongside the feature all passed while the thing was broken -
    the same lesson the mark tiles taught (`putMark` called by hand instead
    of clicked). The plain box is dragged too, as the control that says the
    harness itself can select at all.
    """
    browserpool = pytest.importorskip("browserpool")
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    from mangatl.project import Project

    root = scratch("_tmp_flow_select")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((460, 1000, 3), 242, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())

    def box(i, y, spans):
        return {"id": i, "kind": "bubble", "order": i - 1,
                "bbox": [20, y, 960, 150], "bubble_bbox": [20, y, 960, 150],
                "polygon": [[20, y], [980, y], [980, y + 150], [20, y + 150]],
                "src_text": "x", "dst_text": PLINE, "confidence": .9,
                "manual": True,
                "layout_override": {"lines": [PLINE], "locked": True,
                                    "font": BASE_FONT, "font_size": 34,
                                    "stroke": 0, "fg": "#111111",
                                    "spans": spans}}

    p.pages[0].regions = [
        box(1, 30, []),                                  # the control
        box(2, 240, [{"s": PWORD, "e": len(PLINE),
                      "st": {"font": LOUD_FONT}}]),      # two faces
    ]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    editor.do_typeset(p, 0, reset=False)
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def drag_over_the_letters(pg, rid):
        pg.evaluate("editOnCanvas(%d)" % rid)
        pg.wait_for_timeout(700)
        nodes = pg.evaluate("""(()=>{const ta=$('canvasEdit');
          if(!ta) return [];
          const walk=(n,out)=>{ if(n.nodeType===3 && n.data.trim()){
              const rg=document.createRange(); rg.selectNodeContents(n);
              const r=rg.getBoundingClientRect();
              out.push({x:r.x,y:r.y,w:r.width,h:r.height}); }
            for(const c of n.childNodes) walk(c,out); return out; };
          return walk(ta,[]);})()""")
        assert nodes, "the box has no text in it to drag across"
        n = nodes[0]
        y = n["y"] + n["h"] / 2
        pg.mouse.move(n["x"] + 2, y)
        pg.mouse.down()
        pg.mouse.move(n["x"] + n["w"] * 0.6, y, steps=14)
        pg.mouse.up()
        pg.wait_for_timeout(450)
        return pg.evaluate("window.getSelection().toString()")

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
            pg.wait_for_timeout(1200)

            plain = drag_over_the_letters(pg, 1)
            assert plain, "the control box selected nothing - the drag " \
                          "itself is broken, so this proves nothing"
            assert pg.evaluate("JSON.stringify(editRange())") != "null"
            pg.evaluate("closeCanvasEdit(false)")
            pg.wait_for_timeout(400)

            got = drag_over_the_letters(pg, 2)
            assert got, "a box with two faces in it cannot be selected at all"
            sel = pg.evaluate("JSON.stringify(editRange())")
            assert sel != "null", \
                "the browser selected %r but the range never reached the " \
                "tools" % got
            # ...and a range tool really does work on it
            pg.evaluate("""(()=>{
              const f=$('lyFg'); f.value='#d81f1f';
              f.removeAttribute('data-auto');
              onTypesetStyle(2);})()""")
            pg.wait_for_timeout(400)
            spans = pg.evaluate("JSON.stringify((regions.find(x=>x.id===2)"
                                ".layout_override||{}).spans)")
            assert '"fg":"#d81f1f"' in spans, \
                "the range took no style on a two-face box: %r" % spans
            assert not errs, errs[:3]
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
