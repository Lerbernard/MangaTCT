"""A text box you drew yourself is ONE box.

lee, twice, with pictures: *"when i created a new text box it created a new box
as well , it shoud [not] do that it shud just create the text box inependent of
everything"*, and then *"the etxt box still crated a new box"*.

There was never a second region - the endpoint makes exactly one, and that is
measured here too. There are two RECTANGLES, and on this kind of box they must
not be allowed to come apart:

* the **region**, drawn once with the text tool and never moved again; and
* the **typesetting frame**, which is what the handles actually drag.

On every other box those mean different things - the region is where the
Japanese was, the frame is where the English goes - and both are worth seeing.
On a text box there is no Japanese. So the two coming apart leaves an empty box
sitting where you first drew it while the words are somewhere else entirely,
which is lee's first screenshot; and while the box is selected, both being
drawn puts two outlines and two sets of handles around one rectangle, which is
his second.

Two halves, then. The region FOLLOWS the frame, wherever the frame is last put.
And while a text box is the selected one and its frame is therefore on screen,
the frame is its box - the region's own outline is not drawn as well.
"""
import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

import browserpool
from where import PKG

cv2 = pytest.importorskip("cv2")

FRAMES = (PKG / "static" / "js"
          / "frames.js").read_text(encoding="utf-8")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 250, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].detected = True
    p.save()
    return p


def _server(p):
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1], was


def _post(base, path, obj):
    req = urllib.request.Request(
        base + path, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def _text_box(base, x=60, y=50, w=170, h=110, text="THE WRONG DOLL LOL"):
    return _post(base, "/api/page/0/region",
                 {"x": x, "y": y, "w": w, "h": h, "snap": False,
                  "own_text": True, "kind": "freefloat", "text": text})


def _new_id(j):
    """The reply carries the whole page's regions plus the one just made -
    `regions[0]` is whatever was already there."""
    return j["region"]["id"]


# --------------------------------------------------------- one region, always

def test_drawing_one_makes_exactly_one_region(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "tb"))
    srv, base, was = _server(p)
    try:
        j = _text_box(base)
        assert len(j["regions"]) == 1, j["regions"]
        assert len(p.pages[0].regions) == 1
        assert p.pages[0].regions[0]["own_text"] is True
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_it_is_typeset_inside_the_box_it_was_drawn_in(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "tb"))
    srv, base, was = _server(p)
    try:
        j = _text_box(base)
        r = next(x for x in j["regions"] if x["id"] == _new_id(j))
        fx, fy, fw, fh = (r.get("layout") or {})["frame"]
        bx, by, bw, bh = r["bbox"]
        assert bx <= fx and by <= fy, (r["bbox"], (fx, fy, fw, fh))
        assert fx + fw <= bx + bw and fy + fh <= by + bh, \
            (r["bbox"], (fx, fy, fw, fh))
    finally:
        editor.PROJECT = was
        srv.shutdown()


# ------------------------------------------------ the region follows the frame

def test_moving_the_frame_takes_the_box_with_it(tmp_path):
    """The empty box left behind is what lee photographed."""
    from mangatl import editor
    p = _project(str(tmp_path / "tb"))
    srv, base, was = _server(p)
    try:
        rid = _new_id(_text_box(base))
        _post(base, f"/api/page/0/region/{rid}",
              {"layout": {"frame": [300, 400, 150, 90]}})
        rec = p.pages[0].regions[0]
        assert rec["bbox"] == [300, 400, 150, 90], rec["bbox"]
        assert rec["polygon"][0] == [300, 400], rec["polygon"]
        assert rec["polygon"][2] == [450, 490], rec["polygon"]
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_and_it_stays_that_way_when_the_project_is_reopened(tmp_path):
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "tb")
    p = _project(root)
    srv, base, was = _server(p)
    try:
        rid = _new_id(_text_box(base))
        _post(base, f"/api/page/0/region/{rid}",
              {"layout": {"frame": [300, 400, 150, 90]}})
        p.save()
    finally:
        editor.PROJECT = was
        srv.shutdown()
    assert Project(None, root).pages[0].regions[0]["bbox"] == [300, 400, 150, 90]


def test_an_ordinary_box_keeps_its_own_rectangle(tmp_path):
    """This is the half that must NOT change. On a translated bubble the region
    is where the Japanese was - the cleaner erases it, the reader read it - and
    the frame is where the English is set. Moving the English must not move the
    record of where the original was."""
    from mangatl import editor
    p = _project(str(tmp_path / "tb"))
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.save()
    editor.do_typeset(p, 0)
    srv, base, was = _server(p)
    try:
        _post(base, "/api/page/0/region/1",
              {"layout": {"frame": [300, 400, 150, 90]}})
        rec = p.pages[0].regions[0]
        assert rec["bbox"] == [170, 140, 160, 80], rec["bbox"]
        assert rec["bubble_bbox"] == [110, 100, 280, 160], rec["bubble_bbox"]
    finally:
        editor.PROJECT = was
        srv.shutdown()


# -------------------------------------------------------- one box on the page

def _browser(fn, tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "tbui"))
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.save()
    editor.do_typeset(p, 0)
    srv, base, was = _server(p)
    try:
        rid = _new_id(_text_box(base, x=60, y=380, w=200, h=120))
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            # Entering the Translation view puts the region boxes away, and
            # this whole question is about what happens when they are ON -
            # which is the state lee's screenshot was taken in.
            pg.evaluate("""(()=>{document.getElementById('hideboxes')
              .checked=false; drawBoxes();})()""")
            pg.wait_for_timeout(400)
            try:
                return fn(pg, rid)
            finally:
                assert not errs, errs[:2]
    finally:
        editor.PROJECT = was
        srv.shutdown()


def _boxes(pg):
    return pg.evaluate("""(()=>({
      boxes:[...document.querySelectorAll('#stage .box')].map(b=>+b.dataset.id),
      frame:!!document.getElementById('tframe')}))()""")


def test_a_selected_text_box_is_drawn_once(tmp_path):
    """Both at once is two outlines and two sets of handles round one
    rectangle - which is the picture lee sent."""
    def check(pg, rid):
        pg.evaluate("select(%d)" % rid)
        pg.wait_for_timeout(700)
        got = _boxes(pg)
        assert got["frame"] is True, "the typesetting frame is not on screen"
        assert rid not in got["boxes"], got
        assert 1 in got["boxes"], ("the other box went too", got)
    _browser(check, tmp_path)


def test_an_unselected_one_still_has_a_box_to_click(tmp_path):
    """Without it there would be nothing to see and nothing to select."""
    def check(pg, rid):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        got = _boxes(pg)
        assert rid in got["boxes"], got
    _browser(check, tmp_path)


def test_an_ordinary_box_keeps_both(tmp_path):
    """The region is where the Japanese was and the frame is where the English
    is set: on a translated bubble they are two different facts and both are
    worth seeing."""
    def check(pg, rid):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        got = _boxes(pg)
        assert got["frame"] is True, got
        assert 1 in got["boxes"], got
    _browser(check, tmp_path)


# ------------------------------------------------- and it is not a detection

def _row(pg, rid):
    return pg.evaluate("""(id)=>{
      const r=document.querySelector(`#list .lrow[data-id="${id}"]`);
      if(!r) return null;
      return {score:!!r.querySelector('.chip.g,.chip.r'),
              kind:!!r.querySelector('.chip.kind'),
              ja:!!r.querySelector('.ja'),
              text:r.querySelector('.tx').textContent.trim()};}""", rid)


def test_it_is_not_in_the_translation_at_all(tmp_path):
    """The list is the translation - a row per piece of Japanese, with what it
    says and what it will say. A box holding your own words is not one of
    those, and every part of it that said otherwise was a lie about where it
    came from: a green **1.00**, a *"no text read"* line, a reading-order
    number on the artwork.

    lee: *"wheni create a text box its hsoud JUST CREATE TEH ETXT BOX WITH NO
    TRANSLATION BOX  JUST TEH TEXT BOX  ITS SHSOUD BE [not] LINK TO ANYTJING
    ITS SHOUD BE AN IDENPENDNT TEXT BOX"*.
    """
    def check(pg, rid):
        pg.evaluate("setView('original'); select(null)")
        pg.wait_for_timeout(700)
        assert _row(pg, rid) is None, "it is still in the translation list"
        got = pg.evaluate("""(id)=>({
          box:!!document.querySelector(`#stage .box[data-id="${id}"]`),
          tag:!!document.querySelector(`#stage .tagf[data-id="${id}"]`),
          })""", rid)
        assert got == {"box": False, "tag": False}, got
    _browser(check, tmp_path)


def test_and_it_is_not_counted_as_text_on_the_page(tmp_path):
    """One bubble and one box of your own is one piece of text to translate,
    not two."""
    def check(pg, rid):
        pg.evaluate("setView('original')")
        pg.wait_for_timeout(700)
        card = pg.evaluate("""(()=>{const c=[...document.querySelectorAll(
            '#side .card')].find(c=>/text box/.test(c.textContent));
            return c ? c.textContent.replace(/\\s+/g,' ') : '';})()""")
        assert "1 text box" in card, card
        assert "2 text boxes" not in card, card
        # ...and the number on the page in the rail, which is the same fact
        # counted by the server rather than by the browser
        assert pg.evaluate("""document.querySelector(
            '#pages .pg .ct, .pglist .ct, #pagelist .ct').textContent.trim()
            """) == "1", "the page rail still counts it"
    _browser(check, tmp_path)


def test_the_detected_box_keeps_everything_it_had(tmp_path):
    """The half that must not change: on a box the detector found, the score
    is how sure it was, the Japanese is what it read, and the number is where
    it comes in the reading order."""
    def check(pg, rid):
        pg.evaluate("setView('original'); select(null)")
        pg.wait_for_timeout(700)
        got = _row(pg, 1)
        assert got and got["score"] is True and got["ja"] is True, got
        assert pg.evaluate(
            "!!document.querySelector('#stage .tagf[data-id=\"1\"]')")
    _browser(check, tmp_path)


def test_but_it_is_still_there_to_typeset_on_the_image_view(tmp_path):
    """Independent is not invisible. The Image view is where it lives: the
    cleaned page, the typesetting, and this."""
    def check(pg, rid):
        pg.evaluate("""(()=>{setView('typeset');
          document.getElementById('hideboxes').checked=false;
          drawBoxes();})()""")
        pg.wait_for_timeout(800)
        assert pg.evaluate(
            "!!document.querySelector(`#stage .box[data-id=\"%d\"]`)" % rid), \
            "there is nothing on the Image view to click"
    _browser(check, tmp_path)


# ------------------------------------------- a number is never handed out twice

def test_the_number_of_a_deleted_box_is_not_given_to_the_next_one(tmp_path):
    """lee: *"when i deleet an text box and create a new one it come back with
    teh same text as teh olde text box"*.

    Everything the editor holds about a box while it is in the air is filed
    under its NUMBER - the keystroke not yet sent, the edit whose save has not
    come home, the undo snapshot. Ids used to be `max(existing) + 1`, which
    hands the dead box's number to the next one drawn, and every one of those
    then lands on a box that never asked for it.
    """
    from mangatl import editor
    p = _project(str(tmp_path / "ids"))
    srv, base, was = _server(p)
    try:
        first = _new_id(_text_box(base, y=50))
        _post(base, f"/api/page/0/region/{first}", {"dst_text": "OLD WORDS"})
        req = urllib.request.Request(
            base + f"/api/page/0/region/{first}", method="DELETE")
        urllib.request.urlopen(req, timeout=30).read()
        second = _new_id(_text_box(base, y=300, text="NEW ONE"))
        assert second != first, (first, second)
        rec = p.pages[0].regions[-1]
        assert rec["dst_text"] == "NEW ONE", rec["dst_text"]
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_and_not_after_the_project_is_reopened(tmp_path):
    """The counter is written down. Without that, closing the editor is all it
    takes for the numbers to start again from whatever is left on the page."""
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "ids2")
    p = _project(root)
    srv, base, was = _server(p)
    try:
        rid = _new_id(_text_box(base, y=50))
        req = urllib.request.Request(
            base + f"/api/page/0/region/{rid}", method="DELETE")
        urllib.request.urlopen(req, timeout=30).read()
        p.save()
    finally:
        editor.PROJECT = was
        srv.shutdown()

    q = Project(None, root)
    srv, base, was = _server(q)
    try:
        again = _new_id(_text_box(base, y=300))
        assert again != rid, (rid, again)
    finally:
        editor.PROJECT = was
        srv.shutdown()


# ----------------------------------------- the box you drew stays the size it is

def test_typing_into_it_does_not_resize_the_box(tmp_path):
    """New words mean the old line breaks and the old point size are not this
    text's - so the fitting is dropped and done again. On a bubble that costs
    nothing: the frame is read off the balloon. A text box has no balloon. Its
    frame IS the rectangle you dragged, and it was going down with the rest of
    the layout. lee: *"the new text box ... reset in size when i clcik off teh
    tab and come back"*.
    """
    from mangatl import editor
    p = _project(str(tmp_path / "frame"))
    srv, base, was = _server(p)
    try:
        rid = _new_id(_text_box(base))
        _post(base, f"/api/page/0/region/{rid}",
              {"layout": {"frame": [90, 400, 260, 120]}})
        assert (p.pages[0].regions[0]["layout"] or {})["frame"] == \
            [90, 400, 260, 120]
        _post(base, f"/api/page/0/region/{rid}", {"dst_text": "SOMETHING ELSE"})
        lay = p.pages[0].regions[0]["layout"] or {}
        assert lay.get("frame") == [90, 400, 260, 120], lay
        # ...and the fitting itself IS dropped: the lines were laid out for the
        # words that are no longer there.
        assert not lay.get("lines"), lay
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_a_bubble_still_forgets_its_fitting_completely(tmp_path):
    """The half that must not change. A balloon's frame is derived, so keeping
    it would pin the new words inside a rectangle fitted for the old ones."""
    from mangatl import editor
    p = _project(str(tmp_path / "frame2"))
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.save()
    editor.do_typeset(p, 0)
    srv, base, was = _server(p)
    try:
        assert p.pages[0].regions[0]["layout"]
        _post(base, "/api/page/0/region/1", {"dst_text": "SOMETHING ELSE"})
        assert p.pages[0].regions[0]["layout"] is None
    finally:
        editor.PROJECT = was
        srv.shutdown()
