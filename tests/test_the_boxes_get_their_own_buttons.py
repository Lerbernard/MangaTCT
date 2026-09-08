# -*- coding: utf-8 -*-
"""The box rows grow up, and each tab keeps its own furniture.

One sitting of lee's, seven asks:

* *"get rid of this in the imaged tab"* - the manual-translation toggle and
  the shortcut hint showed on the Image tab, where neither does anything;
* *"remoev these form the image tab"* - the box-kind legend too;
* *"make teh slector tool be seprated form the other as they have diferent
  functions"* - Select boxes is a TOOL, the kind chips are assignments;
* *"remove teh split button and a change mark to a special charater button"*;
* *"add a read text and traslate buuton to each box and it shoud jut send
  that box and text with no extra context to the ai and make it cost 1
  coin"*;
* *"make teh 2 button take teh whoe with of teh box with some adiing and
  make it 3 row of 2"*;
* *"remve teh json button"*, and the boxes list scrolls inside its own pane
  *"like how Cleaning per bubble works"*.
"""
import json
import os
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

import mangatl

PKG = os.path.dirname(os.path.abspath(mangatl.__file__))


def _read(*parts):
    return open(os.path.join(PKG, *parts), encoding="utf-8").read()


# ------------------------------------------------------------- the sources

def test_the_json_template_button_is_gone():
    html = _read("static", "editor.html")
    assert "downloadManualTemplate('json')" not in html, \
        "the JSON button is back"
    assert "downloadManualTemplate('txt')" in html, \
        "...and the TXT one went with it, which was not the ask"
    assert 'onchange="uploadManualTranslation(this)"' in html, \
        "a filled-in file can no longer come back up"


def test_the_split_button_is_gone_and_marks_became_special_characters():
    js = _read("static", "js", "panels.js")
    body = js.split("function regionInlineEditor(")[1].split("\nfunction ")[0]
    assert "splitRegion" not in body, "the Split button is back"
    assert "Special characters" in body, \
        "the special-characters button never arrived"
    assert "openMarks" in body
    html = _read("static", "editor.html")
    assert "<h2>Special characters</h2>" in html, \
        "the dialog still calls itself a mark"


def test_the_row_buttons_are_a_grid_of_six():
    js = _read("static", "js", "panels.js")
    body = js.split("function regionInlineEditor(")[1].split("\nfunction ")[0]
    assert 'class="rbtns"' in body
    for needle in ("readBox(", "translateBox(", "linkNext(",
                   "openMarks(", "delSelected()"):
        assert needle in body, f"{needle} missing from the row grid"
    css = _read("static", "css", "editor.css")
    rule = css.split(".rbtns{")[1].split("}")[0]
    assert "grid" in rule and "1fr 1fr" in rule, \
        "the six buttons are not two to a row"
    assert "width:100%" in css.split(".rbtns button{")[1].split("}")[0], \
        "the buttons do not fill their halves"


def test_the_output_text_is_typed_straight_into_the_row():
    """lee: *"the user shodu be able to go to each page output tetx and
    manual type teh translation"*. The selected row's editor has always
    carried the two textareas; pinned so the manual-translation rework
    cannot take the typing away."""
    js = _read("static", "js", "panels.js")
    body = js.split("function regionInlineEditor(")[1].split("\nfunction ")[0]
    assert 'id="out_${r.id}"' in body, "no output textarea on the row"
    assert "noteEdit(${r.id},'dst_text',this.value)" in body, \
        "typing in it saves nothing"


def test_the_boxes_list_scrolls_inside_its_own_pane():
    css = _read("static", "css", "editor.css")
    rule = css.split("#list{")[1].split("}")[0]
    assert "overflow-y:auto" in rule and "max-height" in rule, \
        "the whole side panel scrolls again"


def test_the_image_tab_keeps_none_of_the_translation_furniture():
    js = _read("static", "js", "view.js")
    fn = js.split("function syncViewChrome(")[1].split("\nfunction ")[0]
    for eid in ("manual", "kbdHint", "legend"):
        assert f"$('{eid}')" in fn, \
            f"syncViewChrome no longer decides #{eid} by view"
    assert "view === 'original'" in fn


def test_the_select_tool_is_set_apart_in_the_legend():
    js = _read("static", "js", "panels.js")
    fn = js.split("function renderLegend(")[1].split("\nfunction ")[0]
    assert "lgdiv" in fn, "no seam between the kinds and the tool"
    assert fn.index("lgdiv") < fn.index("lgsel"), \
        "the seam is on the wrong side of the tool"


def test_special_characters_reach_the_image_tab_and_its_text():
    js = _read("static", "js", "panels.js")
    tp = js.split("function typesettingPanel(")[1].split("\nfunction ")[0]
    assert "openMarks(" in tp, "no special-characters button on the Image tab"
    pm = js.split("function putMark(")[1].split("\nfunction ")[0]
    # `tbInsertText` since the editor swap - the character goes through the
    # editor's own document, at its caret, not through deprecated
    # `execCommand('insertText')` or a write behind the editor's back
    assert "editBox" in pm and ("tbInsertText" in pm or "insertText" in pm), \
        "a character cannot land at the caret of the box being typed into"
    # the record path sends the words and the lines in ONE body - two saves
    # raced, and the text edit's fitting drop popped the line the ♥ was on
    assert "upd(markFor" in pm and "dst_text:dst" in pm \
        and "layout:ov" in pm, \
        "a character never reaches the words on the page"
    assert "view==='original'" in pm, \
        "the Image tab funnels the character into a bare text edit again"
    # ...and the tile carries its character as data, not as an inline call:
    # putMark("♥") inside a double-quoted onclick ends the attribute at the
    # heart's own quote, and every tile was a click that did nothing
    om = js.split("function openMarks(")[1].split("\nfunction ")[0]
    assert "data-ch" in om and "JSON.stringify(ch)" not in om, \
        "the tile onclick truncates at the character's own quotes"


def test_the_two_ai_buttons_wear_their_price():
    """lee: *"add a (1coind) fro teh read text and translate text like the
    other stuff"* - the same coin pip the scoped-run dialog shows, and the
    same silence for a free step: an offline-reader project's Read text
    carries no number, because the endpoint takes none."""
    js = _read("static", "js", "panels.js")
    body = js.split("function regionInlineEditor(")[1].split("\nfunction ")[0]
    assert "coinChip(1)" in body, "no price on the buttons"
    assert "readFree" in body, "an offline read is priced like a bought one"
    assert "#tctcoin" in js.split("function coinChip(")[1] \
                           .split("\nfunction ")[0], \
        "the chip does not carry the real coin"
    css = _read("static", "css", "editor.css")
    assert ".rbcoin{" in css
    py = _read("editor.py")
    assert 'paid = (what == "translate") or not reading_offline(p)' in py, \
        "the server does not agree that an offline read is free"


def test_the_legend_is_a_grid_with_the_tool_on_its_own_row():
    """lee: *"give select box its own sectiona dn amek teh button be a 2x2
    and teh selction button shodu be a 2x1"*."""
    css = _read("static", "css", "editor.css")
    rule = css.split(".legend{")[1].split("}")[0]
    assert "grid" in rule and "1fr 1fr" in rule, \
        "the legend is not two buttons to a row"
    sel = css.split(".legend .lgsel{")[1].split("}")[0]
    assert "1/-1" in sel, "Select boxes does not take a whole row"
    div = css.split(".legend .lgdiv{")[1].split("}")[0]
    assert "1/-1" in div and "height:1px" in div, \
        "the seam does not run across the grid"


def test_a_range_selection_outlives_a_click_on_the_side_panel():
    """lee: *"when i slect a part of a text box, it should not undlesct i i
    clik anything on the side bar so i can accukat chnage some styles"*.

    `caretIntent` - the guard that decided whether a collapse "counted" -
    is gone, and the property now holds by construction: the EDITOR owns
    the selection in its own state (`tbSelection`), and a panel control
    that steals browser focus cannot take away something the browser never
    owned. What is guarded here is that nothing has gone back to reading
    the browser's live selection: the one reader is `editRange`, and it
    asks the editor."""
    js = _read("static", "js", "typesetting.js")
    assert "caretIntent" not in js, \
        "the fragile collapse guard is back - the editor owns the selection"
    assert "function editRange(" in js
    body = js.split("function editRange(")[1].split("\nfunction ")[0]
    assert "tbSelection" in body, \
        "the range is read off the browser again - a panel click kills it"
    ed = _read("static", "js", "typesetting-edit.js")
    assert "document.addEventListener('selectionchange'" not in ed, \
        "the selectionchange listener is back"


# ------------------------------------------------------------ the endpoint

def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 400, 3), 240, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [40, 50, 200, 90],
        "bubble_bbox": [32, 42, 216, 106],
        "polygon": [[40, 50], [240, 50], [240, 140], [40, 140]],
        "src_text": "テスト", "dst_text": "OLD WORDS", "confidence": 0.9}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


def test_one_box_one_coin_end_to_end(monkeypatch, tmp_path):
    """The read re-reads THIS box with the project's own reader; the
    translate sends this box's line alone; each PAID step takes one coin, an
    offline read takes none (the same rule the chapter buttons price by),
    and an empty purse refuses before anything is sent."""
    from mangatl import coins, editor
    root = scratch("_tmp_boxai")
    p = _project(root)

    def fake_read(_p, page, _say):
        for r in page.regions:
            r.src_text = "よんだ"
            r.ocr_ok = True

    def fake_translate(page, ctx=None, **kw):
        # the box and nothing else - no story, no synopsis, one region
        assert len(page.regions) == 1
        assert ctx is not None and not ctx.story and not ctx.synopsis
        page.regions[0].dst_text = "NEW WORDS"
        return {}

    monkeypatch.setattr(editor, "_read_here", fake_read)
    monkeypatch.setattr(editor, "reading_offline", lambda _p: True)
    import mangatl.translate as tr
    monkeypatch.setattr(tr, "translate_page", fake_translate)

    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def post(path):
        req = urllib.request.Request(base + path, data=b"{}",
                                     headers={"Content-Type":
                                              "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        start = coins.balance()
        if start < 2:
            coins.credit(10 - start, "test float")
            start = coins.balance()
        # this project reads OFFLINE, so the box read is free - a read that
        # happens on this computer is not bought from anybody
        code, j = post("/api/page/0/region/1/read")
        assert code == 200, j
        assert coins.balance() == start, "an offline read took a coin"
        rec = next(r for r in p.pages[0].regions if r["id"] == 1)
        assert rec["src_text"] == "よんだ", "the fresh reading never landed"

        # ...an AI read is a paid one
        import mangatl.editor as ed
        monkeypatch.setattr(ed, "reading_offline", lambda _p: False)
        monkeypatch.setattr(ed, "_read_with_ai",
                            lambda _p, _i, page, *_a, **_k:
                            fake_read(_p, page, None))
        code, j = post("/api/page/0/region/1/read")
        assert code == 200, j
        assert coins.balance() == start - 1, \
            "the AI read did not cost 1 coin"

        code, j = post("/api/page/0/region/1/translate")
        assert code == 200, j
        assert coins.balance() == start - 2, \
            "the translate did not cost 1 coin"
        rec = next(r for r in p.pages[0].regions if r["id"] == 1)
        assert rec["dst_text"] == "NEW WORDS"

        # ...and an empty purse is told no BEFORE anything is sent
        drained = coins.balance()
        if drained > 0:
            coins.spend(drained, "drain for the test")
        code, j = post("/api/page/0/region/1/translate")
        assert code == 402 and "coin" in (j.get("error") or "").lower(), j
        coins.credit(max(0, start), "put the float back")
    finally:
        srv.shutdown()
        editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
