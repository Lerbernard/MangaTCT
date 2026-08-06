"""The proofreader's note belongs to one page, and shows on that page only.

lee sent a screenshot of a note card — *"Region 8/5 seem to be a background
aside (someone getting drunk) unrelated to Rofan's main speech…"* — with
*"these messages shoud only be on teh relevenat page not on every page"*.

The server was right all along: `do_proofread` writes `page_notes` to
`p.pages[i].note`, one page at a time, and `/api/page/<i>` hands back that
page's own note. The bug was in `renderList`, which wrote the card **after** its
own early return:

    const hide = view==='clean' || view==='typeset';
    $('listHead').style.display = hide?'none':'';
    $('list').style.display = hide?'none':'';
    if(hide){ renderInspector(); return; }     // <- left before this point
    ...
    noteEl.style.display = pageNote?'':'none'; // <- never reached

So in the Cleaned and Translated views — the two you are in while reviewing the
typesetting, which is exactly when a proofreader's remark gets read — the card was
never updated and never hidden. The list vanished, the note stayed, and it kept
the note of whichever page had last been seen in the Edit view: one page's
remark, floating over all 39.

Reproduced before the fix, page 0 carrying a note and page 1 carrying none:

    view=original  page 0 -> shown   page 1 -> hidden      (correct)
    view=typeset   page 0 -> shown   page 1 -> STILL SHOWN (page 0's text)

The note is written first now, before anything can return early.
"""
import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

JS = PKG / "static" / "js"

NOTE = ("Region 8/5 seem to be a background aside (someone getting drunk) "
        "unrelated to Rofan's main speech, but left as-is.")

# is the card on screen, and what does it say
CARD = """(()=>{const e=document.getElementById('pageNote');
  return {shown: !!e && e.style.display!=='none',
          text: e?e.textContent.trim():''};})()"""


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for n in range(2):
        img = np.full((520, 760, 3), 242, np.uint8)
        cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (25, 25, 25), 3)
        cv2.putText(img, f"PAGE {n}", (215, 235), cv2.FONT_HERSHEY_SIMPLEX,
                    1.1, (20, 20, 20), 3)
        p.add_uploaded(f"p{n}.png", cv2.imencode(".png", img)[1].tobytes())
        p.pages[n].regions = [{
            "id": 1, "kind": "bubble", "order": 0,
            "bbox": [200, 170, 200, 100], "bubble_bbox": [150, 130, 300, 180],
            "polygon": [[200, 170], [400, 170], [400, 270], [200, 270]],
            "src_text": "テストの文章", "dst_text": f"LINE ON PAGE {n}",
            "confidence": 0.9, "proofread": True}]
        p.pages[n].detected = True
        # the Translated view refuses to open on an uncleaned page
        # (`pageReady` in view.js), and that view is where lee saw this
        p.pages[n].cleaned = True
        p.pages[n].ocr = 1
        p.pages[n].translated = 1
    # only the first page has anything to say
    p.pages[0].note = NOTE
    p.pages[1].note = ""
    return p


def test_the_note_follows_the_page_in_every_view(tmp_path):
    """Chromium, against the real server. Both views, both directions."""
    from mangatl import editor

    root = scratch("_tmp_note")
    p = _project(root)
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

            def show(i, wait=1200):
                pg.evaluate(f"showPage({i})")
                pg.wait_for_timeout(wait)
                return pg.evaluate(CARD)

            for v in ("original", "typeset"):
                pg.evaluate(f"setTab('edit'); setView('{v}')")
                browserpool.settled(pg)
                assert pg.evaluate("view") == v, \
                    f"the {v} view would not open, so this proves nothing"

                first = show(0)
                assert first["shown"], f"{v}: the note never appeared"
                assert "background aside" in first["text"], first

                second = show(1)
                if v == "typeset":
                    # the picture: page 1, in the view where the card used to
                    # follow you around the whole chapter. The panel scrolls, and
                    # the card sits under the Current-page block, so scroll to
                    # where it would be before looking.
                    # scroll to just below the inspector, which is the same
                    # height in both cases, so the same window of the panel is
                    # shown whether the card is there or not
                    pg.evaluate("$('side').scrollTop="
                                "$('inspector').offsetTop"
                                "+$('inspector').offsetHeight-40")
                    pg.wait_for_timeout(250)
                    pg.locator("#side").screenshot(
                        path=str(tmp_path / "side_page1_typeset.png"))
                assert not second["shown"], \
                    f"{v}: page 1 has no note and is showing page 0's: {second}"

                # and back again, so it is not simply cleared once and forgotten
                again = show(0)
                assert again["shown"] and "background aside" in again["text"], \
                    f"{v}: the note did not come back with its page"

            # the plate has no text on it, so no remark about the text either
            pg.evaluate("setView('clean')")
            browserpool.settled(pg)
            assert pg.evaluate("view") == "clean"
            assert not show(0)["shown"], \
                "the Cleaned view is the bare plate; the note has no place on it"
            pg.evaluate("setView('original')")
            browserpool.settled(pg)
            assert show(0)["shown"], "the note did not survive coming back"
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_server_keeps_one_note_per_page():
    """The other half of "on every page": prove the note is not chapter-wide.
    `/api/page/<i>` answers with page i's own note, and proofreading a page
    cannot touch its neighbour's."""
    from mangatl import editor
    import urllib.request

    root = scratch("_tmp_note_api")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        def note(i):
            with urllib.request.urlopen(base + f"/api/page/{i}",
                                        timeout=30) as r:
                return json.loads(r.read()).get("note", "")

        assert "background aside" in note(0)
        assert note(1) == "", "page 1 is being handed page 0's note"

        # two pages, two different notes, no leaking in either direction
        p.pages[1].note = "something about page two"
        assert note(1) == "something about page two"
        assert "background aside" in note(0)
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_note_is_written_before_anything_can_return_early():
    """The guard. `renderList` returns early in two views; the note card must be
    settled before that happens, or it goes stale again."""
    src = (JS / "panels.js").read_text(encoding="utf8")
    body = src[src.index("function renderList("):]
    body = body[:body.index("\nfunction ", 5)]
    note_at = body.index("getElementById('pageNote')") \
        if "getElementById('pageNote')" in body else body.index("$('pageNote')")
    ret_at = body.index("renderInspector(); return;")
    assert note_at < ret_at, \
        "the note card is written after renderList's early return, so the " \
        "Cleaned and Translated views keep the last page's note"
    assert "view!=='clean'" in body, \
        "the note must be hidden on the bare plate"


def test_the_note_says_which_boxes_it_is_about():
    """lee, on a note reading *"Replaced the honorific Onee-sama…"*: *"this
    shoud tell which region is the chnage done to"*.

    The remark is the model's prose and may name nothing at all. The list of
    boxes is not asked for — it is worked out: every region whose wording the
    proofread actually changed, plus any it flagged. The chips show the numbers
    the page shows (`order + 1`), not the ids the model works in, and clicking
    one selects that box.
    """
    from mangatl import editor

    root = scratch("_tmp_note_ids")
    p = _project(root)
    # two boxes on page 0, and the remark is about the second one
    p.pages[0].regions.append({
        "id": 2, "kind": "bubble", "order": 1,
        "bbox": [420, 170, 200, 100], "bubble_bbox": [400, 150, 240, 140],
        "polygon": [[420, 170], [620, 170], [620, 270], [420, 270]],
        "src_text": "お姉様", "dst_text": "SISTER", "confidence": 0.9,
        "proofread": True})
    p.pages[0].note = ('Replaced the honorific "Onee-sama" (not in character '
                       'sheet/glossary) with "sister".')
    p.pages[0].note_ids = [2]
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
            pg.evaluate("setTab('edit'); setView('original'); showPage(0)")
            browserpool.settled(pg)

            chips = pg.evaluate(
                "[...document.querySelectorAll('#pageNote .nchip')]"
                ".map(e=>e.textContent.trim())")
            assert chips == ["2"], \
                f"the note does not say which box it is about: {chips}"

            # and the chip takes you to it
            pg.click("#pageNote .nchip")
            pg.wait_for_timeout(600)
            assert pg.evaluate("sel") == 2, "the chip did not select the box"

            # a page whose note is about nothing shows no chips at all
            pg.evaluate("showPage(1)")
            pg.wait_for_timeout(900)
            assert pg.evaluate(
                "document.querySelectorAll('#pageNote .nchip').length") == 0
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_box_list_is_worked_out_not_asked_for():
    """The proofreader is asked to name boxes, but the list under the note does
    not depend on it doing so: it is built from what actually changed."""
    src = (PKG
           / "editor.py").read_text(encoding="utf8")
    fn = src[src.index("def do_proofread("):]
    fn = fn[:fn.index("\ndef ", 5)]
    assert 'changed.add(int(rec["id"]))' in fn
    assert 'flagged.add(int(rec["id"]))' in fn
    assert "note_ids = sorted(changed | flagged)" in fn
    # a re-translation drops the remark; the boxes must go with it
    tr = src[src.index("def do_translate("):]
    tr = tr[:tr.index("\ndef ", 5)]
    assert "note_ids = []" in tr, \
        "a new translation leaves the old note's box list behind"
    # and the prompt asks for it in prose too, so the sentence itself reads well
    pr = (PKG
          / "translate.py").read_text(encoding="utf8")
    assert '"Box 5:"' in pr


def test_selecting_typesetting_on_the_page_keeps_it_readable():
    """lee: *"this is what happens when i select the text with the outine it
    shoud look normal"* — with a picture of a line of typesetting turned into a
    solid blue block.

    The on-page editor is a contenteditable carrying the typesetting's own colour
    and its outline as a text-shadow. A browser's default selection paints an
    opaque slab behind every glyph and overrides the text colour with its own,
    so white-on-black typesetting becomes unreadable the moment it is selected.
    A see-through tint, and the letters keep their colour, outline and shadow.
    """
    css = (PKG / "static" / "css"
           / "editor.css").read_text(encoding="utf8")
    for sel in ("#canvasEdit::selection", "#canvasEdit *::selection",
                "#canvasEdit::-moz-selection"):
        assert sel in css, f"{sel} has no rule, so the browser paints its own"
    block = css[css.index("#canvasEdit::selection"):]
    block = block[:block.index("}", block.index("-moz-selection"))]
    assert "color:inherit" in block, \
        "the selection is still allowed to repaint the typesetting's colour"
    assert "rgba(255,196,0,.32)" in block, "the tint is not see-through"
