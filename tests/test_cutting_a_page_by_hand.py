"""Cutting a page in two, and joining two back into one.

lee: *"add page splitter that allow the user to splite the pages manualy to the
translation tab"*, and then *"also add a page mergin feature"*.

The automatic re-cut is deliberately narrow. It runs only on a chapter that
ARRIVED as a sliced strip, only before any work has been done on it, and only
when four separate tests agree that it is one — because being wrong there
rearranges somebody's chapter behind their back. Every one of those rules is
worth keeping, and between them they leave every other too-long page exactly as
it is: a chapter that came as proper files, a page you split off yourself, a
scan of a double spread.

So: a knife. One page, one row, chosen by the person looking at it. And its
opposite, because a cut in the wrong place has to be undoable and because a
site's slicer sometimes puts a scene across two files.

What is NOT allowed either way: a page with work on it. The boxes are placed in
that page's coordinates and cutting it would leave half of them measured from
the wrong top edge.
"""
import json
import os
import shutil
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor, imgio
from mangatl.project import Project
from where import PKG

W = 400
GUT = 30


def _page(h=900, seed=2, gaps=((400, 430),)):
    """A page with real gutters in it, so snapping has something to snap to."""
    rng = np.random.default_rng(seed)
    img = np.repeat(rng.integers(60, 200, (h, W, 1), dtype=np.uint8), 3, axis=2)
    for a, b in gaps:
        img[a:b] = 255
    return img


@pytest.fixture()
def proj(tmp_path):
    p = Project(None, str(tmp_path / "out"))
    for i in range(3):
        p.add_uploaded("p%d.png" % i,
                       cv2.imencode(".png", _page(seed=i + 1))[1].tobytes())
    yield p
    shutil.rmtree(str(tmp_path / "out"), ignore_errors=True)


# -------------------------------------------------------------- the splitter

def test_one_page_becomes_two(proj):
    was = len(proj.pages)
    ok, why = proj.split_page(1, 400)
    assert ok, why
    assert len(proj.pages) == was + 1


def test_the_halves_are_the_page_again_with_nothing_lost(proj):
    """Not merely two pages of the right total height: the same picture."""
    before = imgio.imread(proj.pages[1].path)
    assert proj.split_page(1, 400)[0]
    a = imgio.imread(proj.pages[1].path)
    b = imgio.imread(proj.pages[2].path)
    assert a.shape[0] == 400 and b.shape[0] == before.shape[0] - 400
    assert np.array_equal(np.vstack([a, b]), before)


def test_they_land_where_the_page_was(proj):
    """Page 2 of 3 splits into pages 2 and 3, and what was page 3 is now page
    4. A split that appended to the end would scramble the chapter.

    Asked of the PICTURES, not the names: everything is renumbered afterwards
    (see `test_the_chapter_before_this_one.py`), so a name proves nothing about
    where a page ended up."""
    was = [imgio.imread(pg.path) for pg in proj.pages]
    assert proj.split_page(1, 400)[0]
    now = [imgio.imread(pg.path) for pg in proj.pages]
    assert np.array_equal(now[0], was[0])
    assert np.array_equal(np.vstack(now[1:3]), was[1])
    assert np.array_equal(now[3], was[2])


def test_the_page_you_split_is_kept(proj):
    """Nothing a person handed the editor is deleted behind them — the same
    promise the strip re-cut makes about the tiles it replaces."""
    was = proj.pages[1].path
    assert proj.split_page(1, 400)[0]
    assert not os.path.isfile(was), "it must stop being a page"
    assert os.path.isfile(os.path.join(os.path.dirname(was), "split",
                                       os.path.basename(was)))


def test_the_new_pages_know_their_own_size(proj):
    assert proj.split_page(1, 400)[0]
    for pg in proj.pages[1:3]:
        img = imgio.imread(pg.path)
        assert (pg.height, pg.width) == img.shape[:2]


def test_a_painted_page_is_refused(proj):
    """Touch-up strokes and a hand-supplied clean plate are PICTURES the size
    of the page, and re-cutting those is a different job from re-cutting a
    list of rectangles."""
    proj.pages[1].paint_overlay = "/tmp/strokes.png"
    ok, why = proj.split_page(1, 400)
    assert not ok and "touch-up strokes" in why
    assert len(proj.pages) == 3

    proj.pages[1].paint_overlay = ""
    proj.pages[1].custom_clean = "/tmp/mine.png"
    ok, why = proj.split_page(1, 400)
    assert not ok and "clean plate of your own" in why
    assert len(proj.pages) == 3


# ------------------------------------------- ...and the work comes with it

def _box(i, y, h=40, x=10, w=60, **kw):
    return dict({"id": i, "kind": "bubble", "order": i - 1,
                 "bbox": [x, y, w, h],
                 "polygon": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                 "src_text": "s%d" % i, "dst_text": "d%d" % i}, **kw)


def test_a_page_with_boxes_on_it_can_be_cut(proj):
    """lee: *"also alow me to cut teh page after ive done so steps it"*. It
    refused outright the moment there were boxes, so noticing a page was wrong
    after reading it cost you the reading."""
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(1, 100), _box(2, 600)]
    ok, why = proj.split_page(1, 400)
    assert ok, why
    assert len(proj.pages) == 4


def test_each_box_goes_to_the_half_it_is_on(proj):
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(1, 100), _box(2, 600)]
    assert proj.split_page(1, 400)[0]
    top, bot = proj.pages[1], proj.pages[2]
    assert [r["id"] for r in top.regions] == [1]
    assert [r["id"] for r in bot.regions] == [2]


def test_the_bottom_halfs_boxes_are_measured_from_its_own_top(proj):
    """The whole reason it used to refuse. A box 600 rows down a page cut at
    400 is 200 rows down the second half, and leaving it at 600 puts it off
    the bottom of a 500-row page."""
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(2, 600)]
    assert proj.split_page(1, 400)[0]
    r = proj.pages[2].regions[0]
    assert r["bbox"] == [10, 200, 60, 40]
    assert [p[1] for p in r["polygon"]] == [200, 200, 240, 240]


def test_the_reading_and_the_translation_come_with_it(proj):
    """Boxes are not just rectangles. Losing the Korean and the English is
    losing the run that cost coins."""
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(2, 600, kind="sfx", speaker="Bella")]
    assert proj.split_page(1, 400)[0]
    r = proj.pages[2].regions[0]
    assert (r["src_text"], r["dst_text"]) == ("s2", "d2")
    assert r["kind"] == "sfx" and r["speaker"] == "Bella"


def test_a_typeset_frame_moves_with_its_box(proj):
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(2, 600, layout={"frame": [10, 605, 60, 30],
                                                  "lines": ["hi"]})]
    assert proj.split_page(1, 400)[0]
    lay = proj.pages[2].regions[0]["layout"]
    assert lay["frame"] == [10, 205, 60, 30]
    assert lay["lines"] == ["hi"], "and nothing else about it is touched"


def test_a_box_across_the_cut_goes_where_most_of_it_is(proj):
    """It has to go somewhere whole, and the half holding most of the box is
    the half holding most of its writing. It is then clipped to that half
    rather than left hanging off the end."""
    proj.pages[1].detected = True
    # 380..480 on a page cut at 400: centre 430, so the bottom half.
    proj.pages[1].regions = [_box(1, 380, h=100)]
    assert proj.split_page(1, 400)[0]
    assert not proj.pages[1].regions
    r = proj.pages[2].regions[0]
    assert r["bbox"][1] == 0 and r["bbox"][3] == 80


def test_a_hidden_box_is_still_hidden_afterwards(proj):
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(1, 100), _box(2, 600)]
    proj.pages[1].hidden_ids = [2]
    proj.pages[1].hidden_kinds = ["sfx"]
    assert proj.split_page(1, 400)[0]
    assert proj.pages[1].hidden_ids == []
    assert proj.pages[2].hidden_ids == [2]
    assert proj.pages[1].hidden_kinds == ["sfx"]
    assert proj.pages[2].hidden_kinds == ["sfx"]


def test_the_plate_and_the_layout_are_dropped_rather_than_carried_wrong(proj):
    """Both are page-sized pictures of a page that no longer exists, and both
    are rebuilt from the boxes that just moved."""
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(1, 100)]
    proj.pages[1].cleaned = True
    proj.pages[1].typeset = True
    assert proj.split_page(1, 400)[0]
    for half in proj.pages[1:3]:
        assert not half.cleaned and not half.typeset
        assert half.detected, "the boxes are still there, so it is still found"


def test_joining_puts_the_boxes_back_where_they_were(proj):
    """Cut and join are each other's opposite for the pixels; they have to be
    for the boxes too, or a mis-placed cut costs you the reading."""
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(1, 100), _box(2, 600)]
    was = [dict(r) for r in proj.pages[1].regions]
    assert proj.split_page(1, 400)[0]
    assert proj.merge_pages(1)[0]
    assert [r["bbox"] for r in proj.pages[1].regions] == \
        [r["bbox"] for r in was]
    assert [r["id"] for r in proj.pages[1].regions] == [1, 2]


def test_joining_shifts_the_second_pages_boxes_down(proj):
    proj.pages[0].detected = True
    proj.pages[0].regions = [_box(1, 100)]
    proj.pages[1].regions = [_box(7, 50)]
    assert proj.merge_pages(0)[0]
    ys = sorted(r["bbox"][1] for r in proj.pages[0].regions)
    assert ys == [100, 950], "the first page is 900 tall"


@pytest.mark.parametrize("at", [0, 5, 900, 899, -20, 10 ** 6])
def test_a_cut_at_the_edge_or_outside_is_refused(proj, at):
    """A sliver is not a page, and a click on the very edge of a preview is a
    slip rather than a decision."""
    ok, why = proj.split_page(1, at)
    assert not ok and why
    assert len(proj.pages) == 3


def test_a_half_never_writes_over_a_page_that_is_already_there(proj):
    """The halves are named off the stem with an `a` and a `b` on it, and
    `p0a.png` is a perfectly ordinary thing for a chapter to already contain.
    Without the check, splitting `p0` would write over it - somebody's page,
    replaced by half of another one, silently."""
    proj.add_uploaded("p0a.png",
                      cv2.imencode(".png", _page(h=300, seed=8))[1].tobytes())
    keep = imgio.imread(proj.pages[-1].path)
    assert proj.split_page(0, 400)[0]
    # It is renumbered afterwards, so it is found by its picture: still the
    # last page, still every pixel of it.
    assert np.array_equal(imgio.imread(proj.pages[-1].path), keep), \
        "their page must be exactly as it was"
    assert len({pg.path for pg in proj.pages}) == len(proj.pages)
    assert all(os.path.isfile(pg.path) for pg in proj.pages)


def test_splitting_the_same_page_twice_does_not_collide(proj):
    """Both halves are named off the same stem. Splitting one of them again
    must not write over the other."""
    assert proj.split_page(0, 400)[0]
    assert proj.split_page(0, 200)[0]        # the top half of the top half
    assert len(proj.pages) == 5
    paths = [pg.path for pg in proj.pages]
    assert len(set(paths)) == 5, paths
    assert all(os.path.isfile(p) for p in paths)


# ----------------------------------------------------------------- the joiner

def test_two_pages_become_one(proj):
    a = imgio.imread(proj.pages[0].path)
    b = imgio.imread(proj.pages[1].path)
    ok, why = proj.merge_pages(0)
    assert ok, why
    assert len(proj.pages) == 2
    assert np.array_equal(imgio.imread(proj.pages[0].path), np.vstack([a, b]))


def test_a_split_can_be_undone_by_a_join(proj):
    """The two are each other's opposite, and the picture has to survive the
    round trip — that is what makes a mis-placed cut a small mistake."""
    before = imgio.imread(proj.pages[1].path)
    assert proj.split_page(1, 400)[0]
    assert proj.merge_pages(1)[0]
    assert np.array_equal(imgio.imread(proj.pages[1].path), before)
    assert len(proj.pages) == 3


def test_more_than_two_at_a_time(proj):
    whole = np.vstack([imgio.imread(pg.path) for pg in proj.pages])
    assert proj.merge_pages(0, 3)[0]
    assert len(proj.pages) == 1
    assert np.array_equal(imgio.imread(proj.pages[0].path), whole)


def test_pages_of_different_widths_are_centred_not_stretched(proj):
    """Two scans of the same book rarely agree to the pixel. Stretching the
    narrow one changes the artwork; jamming it left puts a step down one edge
    of the page. It is centred, on paper the colour of its own corner.

    The narrow page is NOISE with a known corner on purpose: a flat one is the
    same picture whether it was centred, jammed left or padded with black, so
    it proves none of the three."""
    narrow = np.repeat(np.random.default_rng(21).integers(
        60, 200, (100, W - 60, 1), dtype=np.uint8), 3, axis=2)
    narrow[0, 0] = (7, 200, 11)          # a corner nothing else could be
    proj.add_uploaded("narrow.png", cv2.imencode(".png", narrow)[1].tobytes())
    proj.pages.insert(1, proj.pages.pop())
    assert proj.merge_pages(0, 2)[0]
    out = imgio.imread(proj.pages[0].path)
    assert out.shape[1] == W, "as wide as the widest part"
    band = out[-100:]
    assert np.array_equal(band[:, 30:W - 30], narrow), \
        "centred, and not one pixel of it resampled"
    for edge in (band[:, :30], band[:, W - 30:]):
        assert (edge == (7, 200, 11)).all(), \
            "the paper each side is the page's own corner, not black"


def test_joining_a_painted_page_is_refused(proj):
    proj.pages[1].paint_layers = [{"id": 1}]
    ok, why = proj.merge_pages(0)
    assert not ok and "touch-up strokes" in why
    assert len(proj.pages) == 3


def test_there_has_to_be_a_page_to_join_to(proj):
    ok, why = proj.merge_pages(2)
    assert not ok and why
    assert len(proj.pages) == 3


def test_the_pages_you_joined_are_kept(proj):
    was = [pg.path for pg in proj.pages[:2]]
    assert proj.merge_pages(0)[0]
    folder = os.path.dirname(was[0])
    for p in was:
        assert os.path.isfile(os.path.join(folder, "merged",
                                           os.path.basename(p)))


# ------------------------------------------------------------------ the gaps

def test_the_gaps_on_a_page_are_offered(proj):
    """So the line can land on a real gutter. A row picked by eye off a
    preview a tenth of the size is a row picked to the nearest thirty."""
    gaps = proj.gaps_in(1)
    assert gaps == [415], gaps       # the middle of the 400..430 band


def test_a_page_with_no_gap_says_so_rather_than_inventing_one(proj):
    solid = np.repeat(np.random.default_rng(9).integers(
        60, 200, (600, W, 1), dtype=np.uint8), 3, axis=2)
    proj.add_uploaded("solid.png", cv2.imencode(".png", solid)[1].tobytes())
    assert proj.gaps_in(len(proj.pages) - 1) == []


# ------------------------------------------------------------ through the app

@pytest.fixture()
def serving(proj):
    was, editor.PROJECT = editor.PROJECT, proj
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield proj, "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        editor.PROJECT = was


def _post(base, route, body):
    req = urllib.request.Request(base + route, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_browser_can_cut_a_page(serving):
    p, base = serving
    code, got = _post(base, "/api/page/1/split", {"at": 400})
    assert code == 200 and got["pages"] == 4
    assert len(p.pages) == 4


def test_the_browser_can_join_two(serving):
    p, base = serving
    code, got = _post(base, "/api/page/0/merge", {"count": 2})
    assert code == 200 and got["pages"] == 2
    assert len(p.pages) == 2


def test_a_refusal_comes_back_as_a_sentence(serving):
    """Not a traceback and not a 200 that did nothing. The person picked a
    row; they are owed the reason it was not used."""
    p, base = serving
    p.pages[1].paint_overlay = "/tmp/strokes.png"
    code, got = _post(base, "/api/page/1/split", {"at": 400})
    assert code == 400
    assert "touch-up strokes" in got["error"]


def test_the_gaps_route_answers_with_the_height_too(serving):
    _p, base = serving
    with urllib.request.urlopen(base + "/api/page/1/gaps") as r:
        got = json.loads(r.read())
    assert got["gaps"] == [415]
    assert got["height"] == 900
    assert got["busy"] is False


def test_the_gaps_route_says_when_the_page_is_painted(serving):
    """So the dialog can say why before a row has been chosen, rather than
    after. Boxes are no longer a reason — they come through the cut."""
    p, base = serving
    p.pages[1].detected = True
    p.pages[1].regions = [{"id": 1, "bbox": [1, 2, 3, 4]}]
    with urllib.request.urlopen(base + "/api/page/1/gaps") as r:
        assert json.loads(r.read())["busy"] is False, \
            "a page with boxes on it can be cut"
    p.pages[1].paint_overlay = "/tmp/strokes.png"
    with urllib.request.urlopen(base + "/api/page/1/gaps") as r:
        assert json.loads(r.read())["busy"] is True


# ------------------------------------------------------------ on the screen

import browserpool                                              # noqa: E402

HTML = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
CUT = (PKG / "static" / "js" / "pagecut.js").read_text(encoding="utf-8")
CSS = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")


def test_it_is_a_click_and_not_a_drag():
    """lee: *"remoeve teh click and drag and allow me to clci where i want it
    to cut"*. Dragging is for something you are adjusting; this is not that.

    The pointer capture also swallowed a click while the pointer was down, so
    a quick click on a slow frame sometimes did nothing at all."""
    assert "setPointerCapture" not in CUT
    assert "pointermove" not in CUT
    assert "addEventListener('click', cutFromEvent)" in CUT
    assert "Click on the page where you want" in HTML


def test_nothing_moves_the_line_off_the_row_it_was_given():
    """lee: *"the cut line shoud apar where i click no matter hwat remove
    nything that is precenting that"*. The clamp that used to pull it back
    from the top and bottom sixteen rows is gone — a cut that close is refused
    by the BUTTON going off with the reason beside it, which is a different
    thing from being overruled."""
    at = CUT.index("function putLine(")
    body = CUT[at:CUT.index("\n}", at)]
    assert "Math.max(16" not in body and "_cutH - 16, Math.round" not in body
    assert "line.dataset.row = row;" in body
    assert "too close to the edge" in body


def test_nothing_moves_the_line_at_all():
    """Three asks, one answer. It jumped to the nearest gap within sixty rows
    on every click — lee: *"in teh cut page it teh cut line shoud be where my
    mouse is when i clcick it"*; that became a button — *"and removethe cut a
    the nearst gap button"*; and the drag went too.

    Click, line, done. What survives is the readout: green when the row it
    landed on happens to BE a gap."""
    assert "const SNAP" not in CUT
    assert "snapToGap" not in CUT and "cutSnap" not in CUT
    assert "cutSnap" not in HTML
    assert "The line goes exactly there" in HTML
    assert "line.classList.toggle('snap', on)" in CUT, "the readout stays"


def test_the_join_buttons_say_a_direction_and_not_a_filename():
    """"Join with page 1" told you a filename, which is not what you are
    picking. lee: *"instad of saying join with pagess 1 its hsou be join with
    preiouis and join with next page"*."""
    assert ">Join with previous<" in HTML
    assert ">Join with next<" in HTML
    assert "'Join with ' + proj.pages" not in CUT
    assert "function joinPrev(" in CUT


def test_the_button_has_a_background():
    """It sat among the zoom controls, which are bare glyphs, and read as a
    label rather than something you press. lee: *"make it a button with a
    backgroud"*."""
    assert "#cutBtn{" in CSS
    at = CSS.index("#cutBtn{")
    rule = CSS[at:CSS.index("}", at)]
    assert "background:" in rule and "border:" in rule


def _editor(br, base, medium=None):
    ctx = br.new_context(viewport={"width": 1400, "height": 950})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/", wait_until="load")
    browserpool.ready(pg)
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)
    return pg, errs


@pytest.fixture()
def screen(proj):
    if not browserpool.available():
        pytest.skip("chromium unavailable")
    was, editor.PROJECT = editor.PROJECT, proj
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    with browserpool.session() as br:
        try:
            yield proj, br, base
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _shown(pg, el):
    return pg.evaluate("(id)=>{const e=document.getElementById(id);"
                       "return !!(e && e.offsetParent!==null)}", el)


def test_the_button_is_only_there_for_a_webtoon(screen):
    """lee: *"cut and join shoud only be a thing for manhwa and manhua"*. A
    manga chapter arrives as pages somebody already decided the boundaries of;
    a webtoon arrives as a strip a slicer cut by counting."""
    p, br, base = screen
    p.settings["medium"] = "manga"; p.save()
    pg, errs = _editor(br, base)
    assert not _shown(pg, "cutBtn")
    # Through the menu, which is how it happens: `mediumChosen` is what the
    # Source material select calls, and the button has to follow it there and
    # then rather than after a reload.
    pg.evaluate("$('medium').value='manhwa'; mediumChosen('set')")
    pg.wait_for_timeout(400)
    browserpool.settled(pg)
    assert _shown(pg, "cutBtn")
    assert not errs, errs


def test_the_button_is_not_in_the_image_view(screen):
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    assert _shown(pg, "cutBtn")
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    assert not _shown(pg, "cutBtn")
    assert not errs, errs


def _open(pg):
    pg.evaluate("openCut()")
    pg.wait_for_timeout(700)
    browserpool.settled(pg)


def test_the_line_lands_exactly_where_it_is_put(screen):
    """410 is twenty rows off the gap at 415 — inside the old snap distance,
    so this is the row that used to be moved."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(410)")
    assert pg.evaluate("cutAt()") == 410
    pg.evaluate("putLine(123)")
    assert pg.evaluate("cutAt()") == 123
    # ...including a row nothing will let you cut at. The line still goes
    # there; the Cut button is what says no.
    pg.evaluate("putLine(3)")
    assert pg.evaluate("cutAt()") == 3
    assert pg.evaluate("$('cutGo').disabled") is True
    assert "edge" in pg.text_content("#cutRow")
    assert not errs, errs


def _clickAt(pg, frac):
    box = pg.evaluate("""(()=>{const r=document.getElementById('cutImg')
        .getBoundingClientRect();
        return {x:r.x+r.width/2, top:r.y, h:r.height};})()""")
    y = box["top"] + box["h"] * frac
    pg.mouse.click(box["x"], y)
    pg.wait_for_timeout(120)
    return y, box, pg.evaluate("""(()=>({
        lineY: document.getElementById('cutLine').getBoundingClientRect().y,
        row: cutAt()}))()""")


def test_a_click_on_the_page_puts_the_line_under_the_pointer(screen):
    """The gesture itself, through the browser: one click, line drawn on the
    pixel that was clicked."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    y, box, got = _clickAt(pg, 0.25)
    assert abs(got["lineY"] - y) <= 2, (got["lineY"], y)
    assert abs(got["row"] - 225) <= 900 / box["h"] + 2, got["row"]
    assert not errs, errs


def test_the_line_is_drawn_on_the_click_on_a_page_far_taller_than_the_box(screen):
    """The one that was wrong, and only on a tall page.

    lee: *"th e line is still not where i clicked, use the mouse cordinate to
    draw the line"*. The line was placed with `top: <percent>`, and a
    percentage `top` on an absolutely positioned box resolves against the
    height of its CONTAINING BLOCK — the preview window, not the picture. So
    "40% of the way down the page" was drawn 40% of the way down the WINDOW
    ONTO the page. On a short page the two are the same and it looked perfect;
    on a 6,000-row webtoon it was out by thousands of rows.
    """
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    tall = np.repeat(np.random.default_rng(5).integers(
        60, 200, (6000, 700, 1), dtype=np.uint8), 3, axis=2)
    p.add_uploaded("tall.png", cv2.imencode(".png", tall)[1].tobytes())
    pg, errs = _editor(br, base)
    pg.evaluate("(i)=>showPage(i)", len(p.pages) - 1)
    pg.wait_for_timeout(700)
    _open(pg)
    for frac in (0.1, 0.35, 0.5, 0.8):
        y, box, got = _clickAt(pg, frac)
        assert abs(got["lineY"] - y) <= 2, (frac, got["lineY"], y)
        want = 6000 * frac
        assert abs(got["row"] - want) <= 6000 / box["h"] + 2, (frac, got["row"])
    assert not errs, errs


def test_the_preview_is_the_page_as_it_is_now_and_not_as_it_was(screen):
    """lee: *"its still showing the previous uncut picure after i cut it, the
    the originalpage dosnt work the other haft works fine"*.

    The preview asked for `/img/3` — the same string every time — and an <img>
    already holding that src does not re-request when it is set to what it
    already says. So after cutting page 3 in two, opening the dialog on the TOP
    half showed the whole uncut page again; the bottom half was fine, because
    its index had not been looked at before.

    Keyed on the file's contents now, which cannot collide with the picture it
    replaced.
    """
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    was = pg.evaluate("$('cutImg').src")
    tall = pg.evaluate("$('cutImg').naturalHeight")
    assert tall == 900, tall

    pg.evaluate("putLine(400); cutHere()")
    pg.wait_for_timeout(1500)
    browserpool.settled(pg)
    assert len(p.pages) == 4

    # Straight back into the dialog, on the half that took the old page's
    # index — the one that was showing the wrong picture.
    _open(pg)
    now = pg.evaluate("$('cutImg').src")
    assert now != was, "the same URL cannot describe two different pictures"
    assert pg.evaluate("$('cutImg').naturalHeight") == 400, \
        "it has to be the half, not the page it was cut out of"
    assert not errs, errs


def test_the_whole_page_can_be_clicked_without_scrolling(screen):
    """You are picking one row out of a page you can see, and you cannot pick
    it out of a page you cannot. The preview used to fit the WIDTH and scroll,
    which on a 6,000-row webtoon was eight screenfuls."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    tall = np.repeat(np.random.default_rng(6).integers(
        60, 200, (6000, 700, 1), dtype=np.uint8), 3, axis=2)
    p.add_uploaded("tall.png", cv2.imencode(".png", tall)[1].tobytes())
    pg, errs = _editor(br, base)
    pg.evaluate("(i)=>showPage(i)", len(p.pages) - 1)
    pg.wait_for_timeout(700)
    _open(pg)
    fits = pg.evaluate("""(()=>{const w=document.getElementById('cutWrap');
        const i=document.getElementById('cutImg').getBoundingClientRect();
        return i.height <= w.getBoundingClientRect().height + 2
            && w.scrollHeight <= w.clientHeight + 2;})()""")
    assert fits, "the whole page has to be in the box"
    assert not errs, errs


def test_a_line_on_a_gap_says_so(screen):
    """The readout that is left. It never moves anything - it tells you the
    cut you have chosen happens to be a clean one."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(415)")               # the middle of the 400..430 band
    assert pg.evaluate("$('cutLine').classList.contains('snap')") is True
    assert "on a gap" in pg.text_content("#cutRow")
    pg.evaluate("putLine(390)")
    assert pg.evaluate("$('cutLine').classList.contains('snap')") is False
    assert pg.evaluate("cutAt()") == 390, "and it stayed where it was put"
    assert not errs, errs


def test_the_first_page_cannot_join_backwards(screen):
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    pg.evaluate("showPage(0)"); pg.wait_for_timeout(500)
    _open(pg)
    assert pg.evaluate("$('cutPrev').disabled") is True
    assert pg.evaluate("$('cutNext').disabled") is False
    assert not errs, errs


def test_the_last_page_cannot_join_forwards(screen):
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    pg.evaluate("showPage(2)"); pg.wait_for_timeout(500)
    _open(pg)
    assert pg.evaluate("$('cutNext').disabled") is True
    assert pg.evaluate("$('cutPrev').disabled") is False
    assert not errs, errs


def test_joining_backwards_joins_the_right_two(screen):
    """`joinPrev` on page 3 has to merge pages 2 and 3, not 3 and 4 — the one
    thing an off-by-one here gets wrong is which two pages the person loses."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    keep = imgio.imread(p.pages[2].path)
    pg, errs = _editor(br, base)
    pg.evaluate("showPage(2)"); pg.wait_for_timeout(500)
    _open(pg)
    pg.evaluate("joinPrev()")
    pg.wait_for_timeout(1200)
    assert len(p.pages) == 2
    out = imgio.imread(p.pages[1].path)
    assert out.shape[0] == 1800, "pages 2 and 3, one on top of the other"
    assert np.array_equal(out[900:], keep)
    assert not errs, errs
