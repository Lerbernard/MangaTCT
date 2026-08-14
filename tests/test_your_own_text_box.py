"""A text box of your own, put where you want it.

lee: *"also add a way to allow me to add text boxes independently of teh
boxes"*.

Every other box on a page stands for writing that is already in the artwork.
It is found by the detector, read by the OCR, translated, and the Japanese
under it is erased so the English can go on top. The whole chain assumes there
is something there.

This one stands for nothing that was there. It is a place on the page where
you want words — a caption, a note, a sign the artist left blank — so every
link in that chain has to be told to leave it alone:

* the rectangle is kept exactly as drawn, because there is no ink to tighten
  onto and tightening would collapse it onto whatever line art it caught;
* nothing under it is erased, because the artwork under it is the artwork;
* the reader skips it — there is nothing to read, and reading a crop of bare
  art hands the translator whatever the engine hallucinated from it;
* the proofreader skips it, because there is no source to check it against and
  these are not a translation to be corrected;
* and it is typeset the moment it is made, because the reason for putting one
  down is to type into it, and a box with no layout offers no typesetting
  controls at all.

`T+` in the page toolbar arms it; the next drag on empty page draws one, on
whichever view you are looking at; and it puts itself away afterwards so it
cannot swallow the drag after that.
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    # something drawn where the caption will go, so "nothing was erased" can
    # actually be measured
    cv2.rectangle(img, (90, 430), (330, 500), (30, 30, 30), 5)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.pages[0].detected = True
    return p


@pytest.fixture()
def stage(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "own"))
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


def _place(pg, x0f=0.15, y0f=0.70, x1f=0.70, y1f=0.85):
    """Arm T+ and drag a box on the page, in fractions of the picture."""
    pg.evaluate("toggleAddText(true)")
    r = pg.evaluate("""(()=>{const b=document.getElementById('img')
        .getBoundingClientRect();
        return {l:b.left,t:b.top,w:b.width,h:b.height};})()""")
    pg.mouse.move(r["l"] + r["w"] * x0f, r["t"] + r["h"] * y0f)
    pg.mouse.down()
    pg.mouse.move(r["l"] + r["w"] * x1f, r["t"] + r["h"] * y1f, steps=8)
    pg.mouse.up()
    # The drag POSTs the new box and the panel opens when the reply lands. A
    # flat 2200ms sleep was long enough on an idle machine and not on a busy
    # one — `test_it_is_typeset_the_moment_it_is_made` went red once in a
    # full run and never once on its own. Wait for the box instead.
    pg.wait_for_function(
        "() => regions.some(r => r.own_text) "
        "&& !!document.getElementById('lyFont')", timeout=20000)
    pg.wait_for_timeout(120)


def _own(p):
    return [r for r in p.pages[0].regions if r.get("own_text")]


# ------------------------------------------------------------- putting one down

def test_a_drag_on_empty_page_makes_one(stage):
    pg, p, errs = stage
    _place(pg)
    own = _own(p)
    assert len(own) == 1, [r["id"] for r in p.pages[0].regions]
    assert own[0]["kind"] == "freefloat"
    assert own[0]["dst_text"], "it arrived with nothing in it"
    assert not errs, errs[:2]


def test_the_box_is_where_it_was_drawn(stage):
    """Kept to the pixel. There is no writing under it to tighten onto, and
    tightening would collapse it onto whatever line art it happened to catch."""
    pg, p, errs = stage
    _place(pg)
    x, y, w, h = _own(p)[0]["bbox"]
    # the drag covered 15%..70% across and 70%..85% down of a 500x600 page
    assert abs(x - 75) <= 6 and abs(w - 275) <= 12, (x, w)
    assert abs(y - 420) <= 6 and abs(h - 90) <= 12, (y, h)
    assert not errs, errs[:2]


def test_it_works_on_the_edit_view_not_only_the_original(stage):
    """The ordinary new-bubble drag is confined to the Original view, where an
    empty-space drag is expected. This one is placed where you can see the
    typesetting, so it has to work on the view that shows it."""
    pg, p, errs = stage
    assert pg.evaluate("view") == "typeset"
    _place(pg)
    assert len(_own(p)) == 1
    assert not errs, errs[:2]


def test_it_puts_itself_away_afterwards(stage):
    """One drag, one box. Left armed, the next drag anywhere on the page would
    make another one by surprise."""
    pg, p, errs = stage
    _place(pg)
    assert pg.evaluate("addingText") is False
    assert not errs, errs[:2]


def test_arming_it_puts_a_paint_tool_down(stage):
    """The same rule as picking a text box: two things that both want the next
    drag cannot both be armed."""
    pg, _p, errs = stage
    pg.evaluate("setToolTab && setToolTab('paint'); toggleBrush && toggleBrush()")
    pg.wait_for_timeout(200)
    if pg.evaluate("typeof paintArmed==='function' && paintArmed()") is not True:
        pytest.skip("the brush would not arm; nothing to disarm")
    pg.evaluate("toggleAddText(true)")
    assert pg.evaluate("paintArmed()") is False
    assert not errs, errs[:2]


# ----------------------------------------------------- what the page does with it

def test_it_is_typeset_the_moment_it_is_made(stage):
    """...and the typesetting controls are on screen, because typing into it is
    the reason for putting one down."""
    pg, p, errs = stage
    _place(pg)
    assert _own(p)[0].get("layout"), "it was left with no layout"
    assert pg.evaluate("!!document.getElementById('lyFont')") is True, \
        "the typesetting panel did not open on it"
    assert not errs, errs[:2]


def test_it_arrives_with_no_outline(stage):
    """lee: *"the text created by the text box creator sould not have any
    outline by deafult"*. A stroke is there to push typesetting away from the
    artwork it is sitting on; this is not replacing anything, so there is
    nothing to push away from — and it is a decision you can still make in the
    panel."""
    pg, p, errs = stage
    _place(pg)
    rec = _own(p)[0]
    assert (rec.get("layout_override") or {}).get("stroke") == 0, rec.get("layout_override")
    assert (rec.get("layout") or {}).get("stroke") == 0, rec.get("layout")
    assert not errs, errs[:2]


def test_it_appears_at_once(stage):
    """It used to clean and typeset the WHOLE page to lay out one box, which on
    a page whose plate is not built yet is an inpainting pass. lee: *"it works
    but it very slow to show up"*."""
    import time
    pg, p, errs = stage
    t0 = time.time()
    _place(pg, 0.10, 0.05, 0.60, 0.16)
    took = time.time() - t0
    assert len(_own(p)) == 1
    # `_place` itself waits 2.2s; anything near that is the wait, not the work
    assert took < 6.0, f"a text box took {took:.1f}s to appear"
    assert not errs, errs[:2]


def test_two_of_them_do_not_collide(stage):
    """The typeset copy used to be written back to the END of the list — and
    `reorder` had already re-sorted it, so it landed on somebody else's box and
    two boxes ended up carrying the same id."""
    pg, p, errs = stage
    _place(pg, 0.10, 0.05, 0.60, 0.16)
    _place(pg, 0.10, 0.70, 0.60, 0.85)
    ids = [r["id"] for r in p.pages[0].regions]
    assert len(ids) == len(set(ids)), ids
    assert len(_own(p)) == 2, ids
    assert all((r.get("layout") or {}).get("stroke") == 0 for r in _own(p))
    assert not errs, errs[:2]


def test_the_words_are_drawn_inside_it(stage):
    pg, p, errs = stage
    _place(pg)
    from mangatl import editor, render as R, typeset as T
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    T.typeset_page(page, editor._typeset_cfg(p))
    out = R.render_page(page, editor._typeset_cfg(p))
    x, y, w, h = _own(p)[0]["bbox"]
    ink = float((out[y:y + h, x:x + w].astype(int).sum(2) < 300).mean())
    assert ink > 0.005, f"nothing was typeset in it ({ink:.4f})"
    assert not errs, errs[:2]


def test_nothing_under_it_is_erased(stage):
    """It is not replacing anything, so the artwork under it is the artwork."""
    pg, p, errs = stage
    _place(pg)
    assert _own(p)[0]["skip_clean"] is True
    from mangatl import editor
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    x, y, w, h = _own(p)[0]["bbox"]
    was = p.image(0)[y:y + h, x:x + w].astype(int)
    now = page.clean_plate[y:y + h, x:x + w].astype(int)
    same = float((np.abs(now - was).sum(2) < 12).mean())
    assert same > 0.995, f"the cleaner went over it ({same:.4f} untouched)"
    assert not errs, errs[:2]


def test_the_other_boxes_keep_the_typesetting_they_had(stage):
    """Adding a caption typesets the page AS IT STANDS. It is not pressing
    Typeset, and it must not redo anybody else's hand corrections."""
    pg, p, errs = stage
    before = {r["id"]: dict(r.get("layout") or {})
              for r in p.pages[0].regions}
    _place(pg)
    for r in p.pages[0].regions:
        if r.get("own_text"):
            continue
        assert (r.get("layout") or {}).get("lines") == before[r["id"]].get("lines")
        assert (r.get("layout") or {}).get("font_size") == \
            before[r["id"]].get("font_size")
    assert not errs, errs[:2]


# ------------------------------------------------ the AI steps leave it alone

def test_the_reader_skips_it():
    """There is nothing under it to read, and an OCR engine handed a crop of
    bare artwork answers with something."""
    from mangatl import ocr
    from mangatl.models import Page, TextRegion
    img = np.full((80, 120, 3), 240, np.uint8)
    page = Page(image=img)
    a = TextRegion(id=1, bbox=(5, 5, 40, 30), text_mask=np.ones((80, 120), np.uint8))
    b = TextRegion(id=2, bbox=(60, 5, 40, 30), text_mask=np.ones((80, 120), np.uint8))
    b.own_text = True
    page.regions = [a, b]
    ocr.ocr_page(page, engine=lambda im: "READ")
    assert a.src_text == "READ"
    assert b.src_text == "", "the reader was handed a box with nothing in it"


def test_the_proofreader_skips_it():
    """No source to check it against, and it is not a translation to correct —
    it is what the person wanted the page to say."""
    from mangatl import translate as T
    from mangatl.models import Page, TextRegion
    page = Page(image=np.zeros((10, 10, 3), np.uint8))
    a = TextRegion(id=1, bbox=(0, 0, 5, 5), kind="bubble")
    a.src_text, a.dst_text = "テスト", "HELLO"
    b = TextRegion(id=2, bbox=(0, 5, 5, 5), kind="freefloat")
    b.src_text, b.dst_text = "", "MY OWN CAPTION"
    b.own_text = True
    page.regions = [a, b]
    ids = {r["id"] for r in T.build_proofread_payload(page, T.SeriesContext())["regions"]}
    assert ids == {1}, ids


def test_the_translator_has_nothing_to_send_for_it():
    from mangatl import translate as T
    from mangatl.models import Page, TextRegion
    page = Page(image=np.zeros((10, 10, 3), np.uint8))
    a = TextRegion(id=1, bbox=(0, 0, 5, 5), kind="bubble")
    a.src_text = "テスト"
    b = TextRegion(id=2, bbox=(0, 5, 5, 5), kind="freefloat")
    b.src_text, b.dst_text = "", "MY OWN CAPTION"
    b.own_text = True
    page.regions = [a, b]
    ids = {r["id"] for r in T._base_payload(page, T.SeriesContext())["regions"]}
    assert ids == {1}, ids


def test_it_survives_being_saved_and_read_back(stage):
    """`own_text` is what every skip above is decided from. A record that
    loses it comes back as an ordinary box, gets read, gets translated over,
    and the artwork under it is erased."""
    pg, p, errs = stage
    _place(pg)
    p.save()
    from mangatl.project import Project
    again = Project(None, p.output_dir)
    # A reload with no pages at all is not "own_text was lost" — it is the
    # whole chapter gone, and the message has to say which. It found this:
    # a transient field set on the series context was written into
    # project.json, `SeriesContext(**saved)` refused the key, `load` raised
    # into a bare `except`, and `rescan` saved an empty project over the top.
    assert again.pages, ("the reloaded project has no pages at all — the "
                         "chapter did not survive the round trip: %r"
                         % (p.output_dir,))
    rec = [r for r in again.pages[0].regions if r.get("own_text")]
    assert len(rec) == 1, "own_text did not survive the save"
    page = again.materialize(0)
    r = [q for q in page.regions if getattr(q, "own_text", False)]
    assert len(r) == 1, "own_text did not survive being materialised"
    assert not errs, errs[:2]
