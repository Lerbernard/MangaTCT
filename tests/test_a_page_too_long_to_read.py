"""Find text says when a page is too long for it.

lee: *"somthing i notice is that when the pages are smaller teh issies are gone
... if the page exide a cerain lenght can you give a warning to he user"*.

He is describing something the detector does by construction. `_letterbox` fits
the page into a 1024 square by its LONG side, so a strip is seen at
`1024 / height` and its writing arrives that many times smaller.

WHICH MAKES IT AN ASPECT AND NOT A LENGTH. A 690x4140 page and a 1400x8400 one
both arrive 170 pixels wide, and their writing — drawn relative to the page
width — arrives the same number of pixels tall. Warning on height would nag the
second one for being twice as big at nothing like twice the risk.

MEASURED TWICE, because the obvious measurement was wrong.

**The wrong one.** Run all 55 pages of two chapters whole, then in halves, and
count what the halves find that the whole page did not: 12% at aspect 2 rising
to 75% past 6. A clean-looking curve, and an artifact. Split by kind, the
dialogue misses do not move with aspect at all — 0.9, 1.5, 0.7, 0.4, 1.2 per
page up the bands — and the entire rise is sound effects. Cropping those says
what they are: page 004's fifteen "missed" boxes are **fifteen copies of the
짭툰.com watermark**. Tall pages in that chapter are scenery with the site stamp
down them. Nothing about the detector.

**The right one.** Take 11 pages Find text already reads and pad WHITE SPACE
under them out to aspect 3, 4, 5, 6, 8 and 10. The artwork, the writing and the
writing's size in page pixels are all untouched; the only thing that changes is
the number the letterbox divides by::

    aspect      3     4     5     6     8    10
    boxes      49    58    57    52    39    39     (53 at the page's own size)
    relabelled 14%   17%   15%   34%   29%   26%

**Recall is not what goes.** A box that was there at the page's own height is
still there at eight times its width. What goes is the box list and the labels
on it: past six, the page loses about a quarter of its boxes and a third of
what survives comes back a different kind.

Which is exactly what lee has been looking at. Every one of his twelve
screenshots was a box of the wrong TYPE or one run of writing cut into two —
not writing that vanished. So the warning says that, and does not say the other
thing.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT


# ------------------------------------------------------- the number itself

def test_the_limit_is_an_aspect_and_it_is_the_measured_one():
    assert CT.TALL_ASPECT == 6.0


def test_it_is_measured_against_the_long_side_either_way_round():
    """A page six times WIDER than tall is letterboxed exactly as hard. Nothing
    in this app makes one, and a rule that only looks at height would be a rule
    about webtoons rather than about the 1024 square."""
    assert CT.too_tall(690, 690 * 7)
    assert CT.too_tall(690 * 7, 690)


def test_a_wider_page_is_allowed_to_be_longer():
    """The point of an aspect. Both of these are seen at the same scale, and a
    limit written in pixels would pass one and fail the other."""
    assert not CT.too_tall(690, 690 * 5)
    assert not CT.too_tall(1400, 1400 * 5)
    assert CT.too_tall(690, 690 * 7) and CT.too_tall(1400, 1400 * 7)


def test_the_limit_is_where_the_relabelling_doubles():
    """5 is measured fine and 6 is measured bad, so the line is between them
    and this says which side each is on."""
    assert not CT.too_tall(690, int(690 * 5.5))
    assert CT.too_tall(690, int(690 * 6.5))


def test_a_page_with_no_size_is_not_warned_about():
    assert not CT.too_tall(0, 0)
    assert not CT.too_tall(690, 0)


def test_the_number_is_sent_and_not_written_twice():
    """The browser draws the warning and must not carry its own copy of the
    limit — that is two numbers to keep in step and one of them nowhere near
    the letterbox it describes."""
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "proj.tall_aspect" in js
    assert "6" not in js.split("function tallPages")[1].split("}")[0]
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert '"tall_aspect": _ctd.TALL_ASPECT,' in src


# ------------------------------------------------------------ on the screen

def _serve(fn, sizes, root=scratch("_tmp_tall")):
    from mangatl import editor
    from mangatl.project import Project

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for i, (w, h) in enumerate(sizes):
        img = np.full((h, w, 3), 245, np.uint8)
        cv2.putText(img, "HI", (10, min(h - 10, 60)), 0, 1.2, (20, 20, 20), 3)
        p.add_uploaded("p%d.png" % i, cv2.imencode(".png", img)[1].tobytes())
    p.settings["medium"] = "manhwa"
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.wait_for_timeout(900)
            pg.evaluate("openDetect()")
            pg.wait_for_timeout(400)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


SHOWN = """()=>{const n=document.getElementById('tallNote');
  return {on: getComputedStyle(n).display!=='none', text: n.textContent};}"""


def test_a_long_page_is_warned_about_before_the_run():
    """In the Find text sheet, which is the moment it matters — the run has not
    started and Cut / join is two clicks away."""
    def go(pg, _p):
        s = pg.evaluate(SHOWN)
        assert s["on"], s
        assert "1 page is very long" in s["text"], s["text"]
        assert "6 times taller than wide" in s["text"], s["text"]
        assert "p0.png" in s["text"], "it does not say which page"
    _serve(go, [(200, 1600)])


def test_it_counts_them_and_names_them():
    def go(pg, _p):
        s = pg.evaluate(SHOWN)
        assert "2 pages are very long" in s["text"], s["text"]
        assert "p0.png" in s["text"] and "p2.png" in s["text"], s["text"]
        assert "p1.png" not in s["text"], "the short one is in the list"
    _serve(go, [(200, 1600), (200, 400), (200, 1800)])


def test_a_chapter_of_ordinary_pages_says_nothing():
    """A warning that shows on every chapter is a warning nobody reads."""
    def go(pg, _p):
        assert pg.evaluate(SHOWN)["on"] is False
    _serve(go, [(200, 400), (200, 900), (200, 1100)])


def test_it_says_what_was_measured_and_not_more():
    """Recall was measured and it barely moves — padding a page out to eight
    times its width keeps the boxes. Telling lee his text will go missing would
    be the easy sentence and the untrue one."""
    def go(pg, _p):
        t = pg.evaluate(SHOWN)["text"].lower()
        assert "box types wrong" in t, t
        assert "cut / join" in t, "it warns without saying what to do about it"
    _serve(go, [(200, 1600)])


def test_the_page_cutter_is_the_answer_it_points_at():
    """`openCut` is what Cut / join calls. If that button is ever renamed or
    removed the warning is pointing at nothing."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="cutBtn"' in html and "openCut()" in html
    assert ">Cut / join<" in html


def test_the_warning_comes_before_the_things_it_should_change_your_mind_about():
    """lee: *"the find text popup is way too crowded ans tetx havvy, remove
    the undeserasy tet and ake teh pages that too long more visible"*.

    It used to sit at the bottom, under three tick boxes and two paragraphs of
    grey. It is the only line in that sheet that changes what you should DO
    before pressing the button, so it goes first."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    sheet = html.split('<h2>What should I look for?</h2>')[1]
    note = sheet.index('id="tallNote"')
    assert note < sheet.index('id="kBubble"'), \
        "the warning is below the boxes again"
    assert note < sheet.index('runDetect'), "it is below the buttons"


def test_the_sheet_stopped_explaining_itself():
    """The paragraph about the finder reading the whole page was true and was
    three lines of grey between lee and a button he presses every chapter.
    What it explained is asserted in `tests/ui/detect_kinds.test.js`, on the
    boxes themselves."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="ctdNote"' not in html
    assert "filter rather than a search" not in html
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "ctdNote" not in js, "the page dropped it and the script still sets it"


def test_the_page_names_are_their_own_line():
    """Which pages is the actionable half. It used to trail the sentence in
    grey italics at the end of six lines of prose."""
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "warnpages" in js
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".sheetwarn .warnpages{display:block" in css
    assert "border-left:4px solid" in css.split(".sheetwarn{")[1].split("}")[0]
