"""The proofreader's change is shown beside the line it replaced.

lee: *"shwo the proofreading changes too in the trnalation tab"*.

Before this, a proofread run told you two things and not the third. The card
above the list said the proofreader had a remark; the chips beside it said
which boxes it touched. **What it actually did was gone** - `do_proofread`
wrote the new wording straight over `dst_text` and the old line existed
nowhere, so the only way to see a copy edit was to remember the sentence.

A copy edit is not reviewable on its own. "Take a good look" is a fine line;
whether it is an improvement is a question about "Take a look", which is the
line it replaced. So the run records it:

    rec["proofread_was"] = <the wording this run replaced>

and the Translation view prints it under the new line, struck through.

It is a record of ONE run and has exactly that lifetime. A later proofread
that leaves the line alone clears it - otherwise the row keeps showing a
change nobody made today. Typing in the box clears it, and so does importing
a translations file, because a "was" under a line somebody has since retyped
is a comparison against nothing.
"""
import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch

cv2 = pytest.importorskip("cv2")

WAS = "Take a look."
NOW = "Take a good look."


def _project(root, dst=WAS):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((520, 760, 3), 242, np.uint8)
    cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (25, 25, 25), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [200, 170, 200, 100], "bubble_bbox": [150, 130, 300, 180],
        "polygon": [[200, 170], [400, 170], [400, 270], [200, 270]],
        "src_text": "よく見てください", "dst_text": dst,
        "speaker": "Ada", "confidence": 0.9}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    p.pages[0].ocr = 1
    p.pages[0].translated = 1
    return p


def _reply(monkeypatch, text, notes=""):
    """Stand in for the model, so the whole of `do_proofread` runs."""
    from mangatl import translate as T
    monkeypatch.setattr(
        T, "make_client",
        lambda **kw: (object(), "test-model", "openai"))
    monkeypatch.setattr(
        T, "_ask",
        lambda *a, **k: json.dumps(
            {"regions": [{"id": 1, "text": text}], "page_notes": notes}))


# --------------------------------------------------------------- the record

def test_the_line_it_replaced_is_kept(tmp_path, monkeypatch):
    from mangatl import editor
    _reply(monkeypatch, NOW)
    p = _project(str(tmp_path / "a"))
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)
    r = p.pages[0].regions[0]
    assert r["dst_text"] == NOW
    assert r["proofread_was"] == WAS
    assert 1 in p.pages[0].note_ids, "and the box is named as changed"


def test_a_line_that_came_back_unchanged_records_nothing(tmp_path,
                                                         monkeypatch):
    """Most lines. A "was" on every row would say the proofreader rewrote the
    page, which is the opposite of what a proofread is."""
    from mangatl import editor
    _reply(monkeypatch, WAS)
    p = _project(str(tmp_path / "b"))
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)
    assert "proofread_was" not in p.pages[0].regions[0]


def test_a_second_run_that_leaves_it_alone_clears_the_old_one(tmp_path,
                                                              monkeypatch):
    """The lifetime is ONE run. Otherwise the row shows a change nobody made
    today, for as long as the project exists."""
    from mangatl import editor
    p = _project(str(tmp_path / "c"))
    editor._ctx_from_settings(p, "proofread")
    _reply(monkeypatch, NOW)
    editor.do_proofread(p, 0)
    assert p.pages[0].regions[0]["proofread_was"] == WAS
    _reply(monkeypatch, NOW)              # this time it agrees with itself
    editor.do_proofread(p, 0)
    assert "proofread_was" not in p.pages[0].regions[0]


def test_typing_in_the_box_clears_it(tmp_path, monkeypatch):
    from mangatl import editor
    _reply(monkeypatch, NOW)
    p = _project(str(tmp_path / "d"))
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)

    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        req = urllib.request.Request(
            base + "/api/page/0/region/1",
            data=json.dumps({"dst_text": "Something else entirely."}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=30).read()
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
    r = p.pages[0].regions[0]
    assert r["dst_text"] == "Something else entirely."
    assert "proofread_was" not in r, \
        "a was-line under a line somebody retyped compares against nothing"


def test_an_imported_translation_clears_it(tmp_path):
    """`set_translation` throws away everything that was true of the old
    wording, and this is one of those things."""
    from mangatl.editor import set_translation
    rec = {"src_text": "よく見てください", "dst_text": NOW,
           "proofread": True, "proofread_was": WAS}
    set_translation(rec, "My own line.")
    assert "proofread_was" not in rec and "proofread" not in rec


# ---------------------------------------------------------------- the report

def test_the_report_prints_it_under_the_new_line(tmp_path, monkeypatch):
    from mangatl import editor
    _reply(monkeypatch, NOW)
    p = _project(str(tmp_path / "e"))
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)
    md = editor.proofread_report(p)["text"]
    at = md.index("- EN: " + NOW)
    assert "- was: " + WAS in md[at:at + 200], \
        "the report is the other place this gets reviewed"


def test_the_report_says_nothing_about_a_line_left_alone(tmp_path,
                                                         monkeypatch):
    from mangatl import editor
    _reply(monkeypatch, WAS)
    p = _project(str(tmp_path / "f"))
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)
    assert "- was: " not in editor.proofread_report(p)["text"]


# ------------------------------------------------------------- and on screen

def test_it_shows_in_the_translation_view(tmp_path, monkeypatch):
    """Chromium, against the real server. The Translation view is `original` -
    the one with the text list in it; `typeset` is the Image view, which has
    no list at all."""
    from mangatl import editor
    _reply(monkeypatch, NOW)
    root = scratch("_tmp_pfwas")
    p = _project(root)
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)

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
            pg.evaluate("setTab('edit'); setView('original')")
            browserpool.settled(pg)
            pg.evaluate("showPage(0)")
            pg.wait_for_timeout(1200)

            row = pg.evaluate("""(()=>{
              const r=document.querySelector('#list .lrow');
              if(!r) return null;
              const w=r.querySelector('.wasline');
              return {now: r.querySelector('.tx').textContent.trim(),
                      was: w?w.textContent.trim():'',
                      struck: !!(w && w.querySelector('s'))};})()""")
            assert row, "no row in the list at all"
            assert row["now"] == NOW, row
            assert row["was"] == WAS, "the replaced line is not on screen"
            assert row["struck"], "it has to read as history, not as a choice"
            pg.locator("#list").screenshot(path=str(tmp_path / "row.png"))
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_row_with_no_change_shows_no_was_line(tmp_path, monkeypatch):
    from mangatl import editor
    _reply(monkeypatch, WAS)
    root = scratch("_tmp_pfclean")
    p = _project(root)
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)

    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('original')")
            browserpool.settled(pg)
            pg.evaluate("showPage(0)")
            pg.wait_for_timeout(1200)
            assert pg.evaluate(
                "document.querySelectorAll('#list .wasline').length") == 0
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_it_survives_being_saved_and_opened_again(tmp_path, monkeypatch):
    """It lives on the stored record, so it is in project.json like anything
    else - a change is still there to review after lunch."""
    from mangatl import editor
    from mangatl.project import Project
    _reply(monkeypatch, NOW)
    root = str(tmp_path / "g")
    p = _project(root)
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)
    p.save()
    again = Project(None, root)
    assert again.pages[0].regions[0]["proofread_was"] == WAS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
