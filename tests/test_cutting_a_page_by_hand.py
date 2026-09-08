"""Cutting a page in two, and joining two back into one.

lee: *"add page splitter that allow the user to splite the pages manualy to the
translation tab"*, and then *"also add a page mergin feature"*.

The automatic re-cut is deliberately narrow. It runs only on a chapter that
ARRIVED as a sliced strip, only before any work has been done on it, and only
when four separate tests agree that it is one - because being wrong there
rearranges somebody's chapter behind their back. Every one of those rules is
worth keeping, and between them they leave every other too-long page exactly as
it is: a chapter that came as proper files, a page you split off yourself, a
scan of a double spread.

So: a knife. One page, the rows chosen by the person looking at it. And its
opposite, because a cut in the wrong place has to be undoable and because a
site's slicer sometimes puts a scene across two files.

MANY ROWS AT ONCE, since lee: *"can you make it so that i can have multiple
cut lines"*. A 10,413-row webtoon is four or five pages, and cutting it a row
at a time meant reopening the dialog on a piece whose panels had all moved,
with a renumber and a reload between each. The rows go together and the page
comes back as N+1.

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
    """Nothing a person handed the editor is deleted behind them - the same
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


# ------------------------------------------------- more than one cut at once

def test_three_cuts_make_four_pages(proj):
    """lee: *"can you make it so that i can have multiple cut lines"*. Not the
    same job done three times: one pass, one move of the original into
    `split/`, one renumber."""
    was = len(proj.pages)
    ok, why = proj.split_page(1, [200, 400, 600])
    assert ok, why
    assert len(proj.pages) == was + 3


def test_the_pieces_are_the_page_again_with_nothing_lost_and_in_order(proj):
    """Top to bottom, every row once, no row twice. A cut that loses or
    duplicates a band of pixels is a cut nobody can see went wrong until they
    read the chapter."""
    was = imgio.imread(proj.pages[1].path)
    assert proj.split_page(1, [200, 400, 600])[0]
    got = [imgio.imread(pg.path) for pg in proj.pages[1:5]]
    assert [g.shape[0] for g in got] == [200, 200, 200, 300]
    assert np.array_equal(np.vstack(got), was)


def test_a_row_asked_for_twice_is_one_cut(proj):
    """Two lines on the same row is one line, and a piece nought rows tall is
    not a page. Sorted and de-duplicated where the rows go in, so nothing
    downstream has to think about it."""
    assert proj.split_page(1, [400, 400])[0]
    assert len(proj.pages) == 4


def test_the_rows_do_not_have_to_arrive_in_order(proj):
    """The pieces are named `a`, `b`, `c` down the page and `renumber_pages`
    trusts that order, so a caller handing them over shuffled must not end up
    with a chapter that reads back to front."""
    assert proj.split_page(1, [600, 200, 400])[0]
    assert [pg.height for pg in proj.pages[1:5]] == [200, 200, 200, 300]


def test_two_cuts_too_close_together_are_refused(proj):
    """A fourteen-row page in the MIDDLE of a chapter is the same mistake as
    one at the end of it, and the edge rule was only ever asking about the
    ends. Refused whole - a cut that half happened is worse than one that did
    not."""
    ok, why = proj.split_page(1, [400, 410])
    assert not ok and "apart" in why
    assert len(proj.pages) == 3


def test_one_bad_row_refuses_the_whole_cut(proj):
    """Nothing is written before every row has been looked at."""
    ok, why = proj.split_page(1, [300, 899])
    assert not ok and why
    assert len(proj.pages) == 3
    assert all(os.path.isfile(pg.path) for pg in proj.pages)


def test_no_rows_at_all_is_refused(proj):
    ok, why = proj.split_page(1, [])
    assert not ok and why
    assert len(proj.pages) == 3


def test_every_box_goes_to_the_piece_it_is_on(proj):
    """The one thing a multi-cut can get wrong that a single cut cannot: each
    piece is measured from ITS OWN top edge, not from the first cut. A box at
    row 500 on a page cut at 200/400/600 is 100 rows down the third piece."""
    proj.pages[1].detected = True
    proj.pages[1].regions = [_box(1, 50), _box(2, 250), _box(3, 500),
                             _box(4, 700)]
    assert proj.split_page(1, [200, 400, 600])[0]
    tops = [[r["bbox"][1] for r in pg.regions] for pg in proj.pages[1:5]]
    assert tops == [[50], [50], [100], [100]], tops


def test_the_pieces_are_named_so_they_sort_in_reading_order(proj):
    """`a`, `b`, `c`, ... is what makes them sort where the page they came
    from sorted, which is the only thing holding the chapter in order between
    the cut and `renumber_pages`."""
    from mangatl.project import _part_suffix
    assert [_part_suffix(k, 4) for k in range(4)] == ["a", "b", "c", "d"]
    # `a, b, ... z, aa` does NOT sort - `aa` comes before `b` in every sort
    # there is - so the width is fixed by how many pieces there are instead.
    assert [_part_suffix(k, 30) for k in range(3)] == ["aa", "ab", "ac"]
    for n in (2, 4, 26, 30, 700):
        got = [_part_suffix(k, n) for k in range(n)]
        assert sorted(got) == got, n
        assert len(set(got)) == n, n


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
    round trip - that is what makes a mis-placed cut a small mistake."""
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
    after. Boxes are no longer a reason - they come through the cut."""
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


def test_placing_a_line_is_a_click_and_never_a_drag():
    """lee: *"remoeve teh click and drag and allow me to clci where i want it
    to cut"*, and later *"alow me to drag them into place"*. Those are not
    opposite asks and the difference is what this pins down.

    PLACING is a click. The drag that came out was how a line got put down -
    pointer down anywhere on the page, capture, follow, release - and its
    capture swallowed a click while the pointer was down, so a quick click on
    a slow frame sometimes did nothing at all. Nothing about a press on bare
    page is held waiting to see whether it becomes something else.

    ADJUSTING is a drag, and it starts on a line already down. So the
    pointer handlers exist again, and every one of them turns back at the top
    unless the press landed on a `.cutline`."""
    assert "addEventListener('click', cutFromEvent)" in CUT
    assert "Click on the page where you want" in HTML
    down = CUT[CUT.index("function cutDown("):]
    down = down[:down.index("\n}")]
    assert "closest('.cutline')" in down
    assert "if(!line) return;" in down, "a press on bare page is not held"
    # ...and the capture is on the WRAP, because `drawCuts` replaces the lines
    # on every move and capture held by a replaced element is capture lost.
    assert "wrap.setPointerCapture" in down
    assert "line.setPointerCapture" not in CUT


def test_nothing_moves_the_line_off_the_row_it_was_given():
    """lee: *"the cut line shoud apar where i click no matter hwat remove
    nything that is precenting that"*. The clamp that used to pull it back
    from the top and bottom sixteen rows is gone - a cut that close is refused
    by the BUTTON going off with the reason beside it, which is a different
    thing from being overruled."""
    at = CUT.index("function drawCuts(")
    body = CUT[at:CUT.index("\n}", at)]
    assert "Math.max(16" not in body and "_cutH - 16, Math.round" not in body
    assert "line.dataset.row = row;" in body
    assert "too close to the edge" in CUT


def test_nothing_moves_the_line_at_all():
    """Three asks, one answer. It jumped to the nearest gap within sixty rows
    on every click - lee: *"in teh cut page it teh cut line shoud be where my
    mouse is when i clcick it"*; that became a button - *"and removethe cut a
    the nearst gap button"*; and the drag went too.

    Click, line, done. What survives is the readout: green when the row it
    landed on happens to BE a gap."""
    assert "const SNAP" not in CUT
    assert "snapToGap" not in CUT and "cutSnap" not in CUT
    assert "cutSnap" not in HTML
    assert "The line goes exactly there" in HTML
    assert "line.classList.toggle('snap', on && !tight)" in CUT, \
        "the readout stays"


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
    """410 is twenty rows off the gap at 415 - inside the old snap distance,
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
    assert "edge" in pg.text_content(".cutline b")
    assert not errs, errs


def _clickAt(pg, frac):
    """One click on the picture, on a preview with no lines on it yet.

    Cleared first because a click ADDS a line now - lee: *"can you make it so
    that i can have multiple cut lines"* - so a helper that did not would be
    reading the first of several every time it was called twice."""
    pg.evaluate("cutClear()")
    box = pg.evaluate("""(()=>{const r=document.getElementById('cutImg')
        .getBoundingClientRect();
        return {x:r.x+r.width/2, top:r.y, h:r.height};})()""")
    y = box["top"] + box["h"] * frac
    pg.mouse.click(box["x"], y)
    pg.wait_for_timeout(120)
    return y, box, pg.evaluate("""(()=>({
        lineY: document.querySelector('.cutline').getBoundingClientRect().y,
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
    height of its CONTAINING BLOCK - the preview window, not the picture. So
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

    The preview asked for `/img/3` - the same string every time - and an <img>
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
    # index - the one that was showing the wrong picture.
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
    assert pg.evaluate("!!document.querySelector('.cutline.snap')") is True
    assert "on a gap" in pg.text_content(".cutline b")
    pg.evaluate("putLine(390)")
    assert pg.evaluate("!!document.querySelector('.cutline.snap')") is False
    assert pg.evaluate("cutAt()") == 390, "and it stayed where it was put"
    assert not errs, errs


def test_a_second_click_is_a_second_cut(screen):
    """lee: *"can you make it so that i can have multiple cut lines"*.

    The dialog opens with NO line on it, which is the other half of the same
    change: it used to open with one across the middle as a hint that the
    thing was clickable, and that was fair while a click MOVED the line. Now a
    click adds one, so a line already there would mean the first click
    somebody makes leaves them with two cuts they never asked for."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    assert pg.evaluate("cutRows().length") == 0, "nothing until you click"
    assert pg.evaluate("$('cutGo').disabled") is True
    _clickAt(pg, 0.25)
    assert pg.evaluate("cutRows().length") == 1
    # ...and the helper clears, so the rest of this clicks by hand.
    for frac in (0.55, 0.75):
        box = pg.evaluate("""(()=>{const r=document.getElementById('cutImg')
            .getBoundingClientRect();
            return {x:r.x+r.width/2, top:r.y, h:r.height};})()""")
        pg.mouse.click(box["x"], box["top"] + box["h"] * frac)
        pg.wait_for_timeout(120)
    assert pg.evaluate("cutRows().length") == 3
    assert pg.evaluate("document.querySelectorAll('.cutline').length") == 3
    # In reading order, because the pieces are named down the page.
    rows = pg.evaluate("cutRows()")
    assert rows == sorted(rows), rows
    assert "Cut into 4 pages" in pg.text_content("#cutGo")
    assert not errs, errs


def test_the_button_adds_a_cut_in_the_middle_of_the_biggest_piece(screen):
    """lee: *"add a button to add like"*. A cut without aiming at one.

    The middle of the biggest piece is the one answer that is never wrong: it
    cannot land on a line already there, it needs no aim, and pressing it
    repeatedly spaces the cuts evenly - which is what a ten-thousand-row strip
    wants before anything is nudged."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    for _ in range(3):
        pg.click("#cutAdd")
        pg.wait_for_timeout(100)
    # 900 rows: 450, then 225 and 675, then 112 or 562 - whichever half of the
    # two 225-row pieces it reaches first. Evenly spaced is the property; the
    # exact third depends on which equal span is met first.
    rows = pg.evaluate("cutRows()")
    assert rows[:2] == sorted(rows[:2]) and len(rows) == 3, rows
    assert 450 in rows and 225 in rows and 675 in rows, rows
    assert "Cut into 4 pages" in pg.text_content("#cutGo")
    assert not errs, errs


def test_a_line_can_be_dragged_into_place(screen):
    """lee: *"alow me to drag them into place"*. A click puts it roughly
    where you want it; this is the nudge."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(300)")
    box = pg.evaluate("""(()=>{const l=document.querySelector('.cutline');
        const r=l.getBoundingClientRect();
        const i=document.getElementById('cutImg').getBoundingClientRect();
        return {x:i.x+i.width/2, y:r.y+1, h:i.height};})()""")
    pg.mouse.move(box["x"], box["y"])
    pg.mouse.down()
    pg.mouse.move(box["x"], box["y"] + 40, steps=8)
    pg.mouse.up()
    pg.wait_for_timeout(150)
    rows = pg.evaluate("cutRows()")
    assert len(rows) == 1, "a drag moves the line, it does not add one"
    want = 300 + 40 / box["h"] * 900
    assert abs(rows[0] - want) <= 900 / box["h"] + 2, (rows, want)
    assert not errs, errs


def test_dragging_one_line_past_another_keeps_them_in_reading_order(screen):
    """The pieces are named `a`, `b`, `c` down the page, so the rows have to
    stay sorted while the pointer is still down - and the drag has to go on
    following the line under the pointer rather than whatever is now at the
    index it started from."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(300); addCut(600)")
    box = pg.evaluate("""(()=>{const l=document.querySelectorAll('.cutline')[0];
        const r=l.getBoundingClientRect();
        const i=document.getElementById('cutImg').getBoundingClientRect();
        return {x:i.x+i.width/2, y:r.y+1, top:i.y, h:i.height};})()""")
    pg.mouse.move(box["x"], box["y"])
    pg.mouse.down()
    pg.mouse.move(box["x"], box["top"] + box["h"] * 0.85, steps=10)
    pg.mouse.up()
    pg.wait_for_timeout(150)
    rows = pg.evaluate("cutRows()")
    assert len(rows) == 2 and rows == sorted(rows), rows
    assert rows[0] == 600, "the one that did not move is still where it was"
    assert rows[1] > 700, rows
    assert not errs, errs


def test_a_drag_does_not_leave_a_cut_where_it_ended(screen):
    """The click that follows a pointerup would ADD one. It is swallowed
    after a drag and let through after a press that never moved, which is what
    lets a nudge and a removal be the same gesture without being the same
    outcome."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(300)")
    box = pg.evaluate("""(()=>{const l=document.querySelector('.cutline');
        const r=l.getBoundingClientRect();
        const i=document.getElementById('cutImg').getBoundingClientRect();
        return {x:i.x+i.width/2, y:r.y+1};})()""")
    pg.mouse.move(box["x"], box["y"])
    pg.mouse.down()
    pg.mouse.move(box["x"], box["y"] + 50, steps=6)
    pg.mouse.up()
    pg.wait_for_timeout(150)
    assert pg.evaluate("cutRows().length") == 1
    # ...and the very next click on bare page still adds one, so nothing is
    # left swallowing clicks after the drag is over.
    pg.mouse.click(box["x"], box["y"] - 120)
    pg.wait_for_timeout(150)
    assert pg.evaluate("cutRows().length") == 2
    assert not errs, errs


def _xy(pg, sel):
    return pg.evaluate("""(s)=>{const e=document.querySelector(s);
        const r=e.getBoundingClientRect();
        return {x:r.x+r.width/2, y:r.y+r.height/2};}""", sel)


def test_the_x_on_a_line_takes_that_line_away(screen):
    """lee: *"ad a way to delete the cut lines"*.

    Its own target and not a gesture on the line, because the line is a thing
    you DRAG now: a grab and a nudge are the same gesture with the distance
    turned down, so a hand that moved by nought pixels would have deleted the
    line it meant to move. Clicking a line used to remove it and that is
    exactly the ambiguity this replaces."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(200); addCut(450); addCut(700)")
    assert pg.evaluate("cutRows()") == [200, 450, 700]
    at = pg.evaluate("""(()=>{const e=document.querySelectorAll('.cutline .x')[1];
        const r=e.getBoundingClientRect();
        return {x:r.x+r.width/2, y:r.y+r.height/2};})()""")
    pg.mouse.click(at["x"], at["y"])
    pg.wait_for_timeout(150)
    assert pg.evaluate("cutRows()") == [200, 700], "the one it was on, and no other"
    assert pg.evaluate("document.querySelectorAll('.cutline').length") == 2
    assert not errs, errs


def test_the_x_is_on_top_of_the_handle_and_not_under_it(screen):
    """The grab strip runs the full width of the line - under the badge as
    well - so appended after the badge it is painted on top and takes every
    click meant for the X, which then does nothing at all. Asked of the
    browser and not of the source, because that is where it went wrong: the
    markup was right and the stacking was not."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(450)")
    hit = pg.evaluate("""(()=>{const e=document.querySelector('.cutline .x');
        const r=e.getBoundingClientRect();
        const t=document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
        return !!(t && t.closest && t.closest('.cutline .x'));})()""")
    assert hit, "the X has to be the thing under the pointer"
    assert not errs, errs


def test_pressing_the_x_does_not_start_a_drag(screen):
    """Without that, pressing it starts a drag, the drag swallows the click
    that was going to delete the line, and the X does nothing."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    pg.evaluate("putLine(450)")
    at = _xy(pg, ".cutline .x")
    pg.mouse.move(at["x"], at["y"])
    pg.mouse.down()
    pg.mouse.move(at["x"], at["y"] + 30, steps=5)
    pg.mouse.up()
    pg.wait_for_timeout(150)
    assert pg.evaluate("cutRows()") == [450], \
        "the line did not move, and nothing new was put where the press ended"
    # ...and letting go somewhere else does not delete it either, the way
    # letting go off a button you pressed means you thought better of it.
    at2 = _xy(pg, ".cutline .x")
    pg.mouse.move(at2["x"], at2["y"])
    pg.mouse.down()
    pg.mouse.move(at2["x"] - 200, at2["y"] + 60, steps=5)
    pg.mouse.up()
    pg.wait_for_timeout(150)
    assert pg.evaluate("cutRows()") == [450], "still there, still the only one"
    assert not errs, errs


def test_clear_all_takes_every_line_away(screen):
    """Four cuts placed by eye down a ten-thousand-row strip is four X's to
    find; starting over is one thought rather than four."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    assert pg.evaluate("$('cutClearAll').disabled") is True, \
        "nothing to clear until there is something"
    pg.evaluate("putLine(200); addCut(450); addCut(700)")
    assert pg.evaluate("$('cutClearAll').disabled") is False
    pg.click("#cutClearAll")
    pg.wait_for_timeout(150)
    assert pg.evaluate("cutRows()") == []
    assert pg.evaluate("document.querySelectorAll('.cutline').length") == 0
    assert pg.evaluate("$('cutGo').disabled") is True
    assert pg.evaluate("$('cutClearAll').disabled") is True
    assert not errs, errs


def test_a_click_on_a_line_neither_removes_it_nor_stacks_another_on_it(screen):
    """It used to remove it, and that was fine while a line was not something
    you could take hold of. Now it is: the line stays put, and the click is
    not turned into a second cut three pixels from the first either."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    y, box, _got = _clickAt(pg, 0.4)
    assert pg.evaluate("cutRows().length") == 1
    was = pg.evaluate("cutRows()")
    pg.mouse.click(box["x"], y)
    pg.wait_for_timeout(120)
    assert pg.evaluate("cutRows()") == was, "left exactly as it was"
    assert not errs, errs


def test_two_lines_too_close_together_say_so_before_the_button_is_pressed(
        screen):
    """The server refuses this, and being told after choosing four rows is
    being told too late. The line goes red and the button goes off - neither
    line is moved, which is the rule this dialog has kept from the start."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    pg, errs = _editor(br, base)
    _open(pg)
    # TWELVE rows apart, and the number matters. There are two thresholds
    # here and they are in different units: a click within `NEAR` (5 SCREEN
    # pixels) of a line means "take that one away", and two cuts closer than
    # `EDGE` (16 ROWS) are refused. On this 900-row page drawn about 494 tall
    # a row is 0.55px, so 8 rows reads as the same line and is removed, and 12
    # is a second line the server will not take. That window is what the red
    # is for - on a tall webtoon the removal tolerance covers the whole of it
    # and this state cannot be reached by clicking at all.
    pg.evaluate("putLine(400); addCut(412)")
    assert pg.evaluate("cutRows()") == [400, 412], \
        "12 rows has to be far enough apart to be a second line"
    assert pg.evaluate("document.querySelectorAll('.cutline.bad').length") == 2
    assert pg.evaluate("$('cutGo').disabled") is True
    assert "too close" in pg.text_content(".cutline b")
    # ...and a row that lands ON one of them is not a third line jammed
    # between the two. It used to be a removal; the X does that now.
    pg.evaluate("cutClear(); putLine(400); addCut(404)")
    assert pg.evaluate("cutRows()") == [400], "4 rows away is the same line"
    # ...and it comes back the moment the offending one is gone.
    pg.evaluate("cutClear(); putLine(400); addCut(600)")
    assert pg.evaluate("document.querySelectorAll('.cutline.bad').length") == 0
    assert pg.evaluate("$('cutGo').disabled") is False
    assert not errs, errs


def test_three_cuts_through_the_dialog_make_four_pages(screen):
    """End to end: the rows go to the server together and the chapter comes
    back one page longer for each of them."""
    p, br, base = screen
    p.settings["medium"] = "manhwa"; p.save()
    was = len(p.pages)
    pg, errs = _editor(br, base)
    pg.evaluate("showPage(1)"); pg.wait_for_timeout(500)
    _open(pg)
    pg.evaluate("putLine(200); addCut(430); addCut(650)")
    pg.evaluate("cutHere()")
    pg.wait_for_timeout(1500)
    assert len(p.pages) == was + 3
    assert [pg_.height for pg_ in p.pages[1:5]] == [200, 230, 220, 250]
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
    """`joinPrev` on page 3 has to merge pages 2 and 3, not 3 and 4 - the one
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
