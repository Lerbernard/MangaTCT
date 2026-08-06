"""Text typed into the side panel stays typed.

lee: *"whne i add text to the side panel in the original tab it hsoud stay and
not clear when i clcik off"*.

The two text boxes in the inspector saved on `change`, and a browser fires
`change` on BLUR — which never happens if the element is removed from the page
while it still has focus. Clicking the page, or another row, or anything else
that redraws the list did exactly that: the textarea was gone before it could
report itself, and the typing went with it.

The keystrokes are remembered as they are typed now (`oninput` → `noteEdit`),
and everything that rebuilds the list writes them out first (`flushEdit`, called
by `setRegions` and by `renderList`).

A note on what this test can and cannot prove. Chromium DOES fire `change` when
a focused, modified field is removed — measured here, one event — so the old
code survives this test and the mutation passes. Firefox, which is what lee
runs, does not: removing the element drops the pending change silently, and the
typing goes with it. So what is locked below is the CONTRACT — type, redraw the
list, the text is still there and has reached the server — which now holds
without depending on any browser's behaviour on removal.
"""
import shutil
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((520, 760, 3), 244, np.uint8)
    for k in range(2):
        cv2.ellipse(img, (220 + k * 300, 220), (110, 80), 0, 0, 360,
                    (255, 255, 255), -1)
        cv2.ellipse(img, (220 + k * 300, 220), (110, 80), 0, 0, 360,
                    (25, 25, 25), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": k + 1, "kind": "bubble", "order": k,
        "bbox": [150 + k * 300, 180, 140, 80],
        "bubble_bbox": [110 + k * 300, 140, 220, 160],
        "polygon": [[150 + k * 300, 180], [290 + k * 300, 180],
                    [290 + k * 300, 260], [150 + k * 300, 260]],
        "src_text": "テスト", "dst_text": "", "confidence": 0.9}
        for k in range(2)]
    p.pages[0].detected = True
    return p


def test_typing_survives_clicking_away():
    from mangatl import editor

    root = scratch("_tmp_paneledit")
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
            pg.evaluate("setTab('edit'); setView('original'); showPage(0)")
            browserpool.settled(pg)

            pg.evaluate("select(1)")
            pg.wait_for_timeout(600)
            box = "#list .lrow.on .rinline textarea:nth-of-type(2)"
            # typed, not `fill`: Playwright's fill dispatches a `change` event
            # of its own, which is exactly the event the browser does NOT send
            # when a focused element is removed — filling would hide the bug
            pg.click(box)
            pg.keyboard.type("HELLO THERE")

            # The exact thing that loses it: the list is rebuilt while the
            # textarea still has focus. A removed element never blurs, so it
            # never fires `change`, so nothing hears the typing. Anything that
            # redraws the list does this — a save elsewhere, a poll landing, a
            # click that re-selects.
            pg.evaluate("renderList()")
            pg.wait_for_timeout(900)

            got = pg.evaluate("regions.find(r=>r.id===1).dst_text")
            assert got == "HELLO THERE", f"the typing was lost: {got!r}"

            # and it reached the server, not just the screen
            saved = p.pages[0].regions[0].get("dst_text")
            assert saved == "HELLO THERE", f"never saved: {saved!r}"

            # coming back to the box shows it
            pg.evaluate("select(1)")
            pg.wait_for_timeout(700)
            shown = pg.evaluate(
                f"document.querySelector('{box}').value")
            assert shown == "HELLO THERE", shown

            # a reload of the page keeps it too
            pg.evaluate("showPage(0)")
            pg.wait_for_timeout(1000)
            assert pg.evaluate("regions.find(r=>r.id===1).dst_text") == \
                "HELLO THERE"
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_typesetting_panel_is_not_rebuilt_under_your_hands():
    """lee: *"when i make chnages in this menu sometime it dont apply or reverst
    back"*.

    Every field in the typesetting panel saves on `change`, and a browser fires
    `change` on blur — so a field that is removed from the page while it still
    has focus never reports the value typed into it, and the rebuilt panel shows
    whatever the server last said. Chromium fires the event on removal, Firefox
    does not, which is why it looked random.

    `renderInspector` now refuses to redraw while one of its own fields has
    focus, and does it when the field is finished with instead.
    """
    js = (PKG / "static" / "js"
          / "panels.js").read_text(encoding="utf8")
    body = js[js.index("function renderInspector("):]
    body = body[:body.index("\nfunction ", 5)]
    head = body[:body.index("const r=regions.find")]
    assert "document.activeElement" in head, \
        "the panel redraws without checking whether a field is in use"
    assert "INPUT|TEXTAREA|SELECT" in head
    assert "addEventListener('blur'" in head, \
        "the deferred redraw never happens, so the panel goes stale"


def test_typing_into_the_typesetting_panel_survives_a_redraw():
    """The behaviour, in a real browser: focus a field, force the redraw that
    used to wipe it, and the field is still there with what was typed."""
    from mangatl import editor

    root = scratch("_tmp_lettpanel")
    p = _project(root)
    for st in p.pages:
        st.cleaned = True
        for rec in st.regions:
            rec["dst_text"] = "WAAAH!"
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 900})
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            if pg.evaluate("view") != "typeset":
                pytest.skip("the Translated view would not open in this fixture")
            pg.evaluate("select(1)")
            pg.wait_for_timeout(900)
            field = "#inspector input[type=number]"
            if not pg.evaluate(f"!!document.querySelector('{field}')"):
                pytest.skip("no typesetting panel in this fixture")

            pg.click(field)
            pg.evaluate(f"document.querySelector('{field}').value='42'")
            # the redraw that used to happen mid-edit
            pg.evaluate("renderInspector()")
            pg.wait_for_timeout(400)
            assert pg.evaluate(f"document.querySelector('{field}').value") == "42", \
                "the panel was rebuilt and the value went back"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_changing_the_text_anywhere_retires_the_old_typesetting():
    """lee: *"make sure that all the etxt are sync so if i chnage the text in
    one spot everywhere else that text is ghsoukd chnage"*.

    The line breaks and the fitted size are computed FOR a particular wording.
    Editing the words left them in place, so the sidebar said one thing and the
    bubble on the page still showed the sentence that had been replaced.
    Proofreading has always dropped the fitting when IT changed a line; an edit
    by hand is the same event and now does the same.

    Only the FITTING is dropped. Everything chosen about how it looks — colour,
    outline, glow, rotation — is dressing and survives.
    """
    from mangatl import editor
    import json as _json
    import urllib.request

    root = scratch("_tmp_sync")
    p = _project(root)
    rec = p.pages[0].regions[0]
    rec["dst_text"] = "OLD WORDS"
    rec["layout"] = {"lines": ["OLD", "WORDS"], "font_size": 22,
                     "leading": 1.0, "origins": [[0, 0], [0, 20]],
                     "fg": "#000", "edge": "#fff", "stroke": 2, "font": "",
                     "rotate": 0.0, "frame": [], "fixed": False,
                     "fit_ok": True, "used_compact": False}
    rec["layout_override"] = {"lines": ["OLD", "WORDS"], "locked": True,
                              "fg": "#ff0000", "rotate": 5.0}
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        req = urllib.request.Request(
            base + f"/api/page/0/region/{rec['id']}",
            data=_json.dumps({"dst_text": "NEW WORDS ENTIRELY"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()

        got = p.pages[0].regions[0]
        assert got["dst_text"] == "NEW WORDS ENTIRELY"
        assert not got.get("layout"), \
            "the bubble still carries the typesetting of the old sentence"
        ov = got.get("layout_override") or {}
        assert "lines" not in ov, "the old line breaks survived the new text"
        # ...and the dressing is untouched
        assert ov.get("fg") == "#ff0000" and ov.get("rotate") == 5.0, ov

        # an edit that is NOT text leaves the typesetting exactly as it was
        p.pages[0].regions[0]["layout"] = {"lines": ["KEEP"], "font_size": 20,
                                           "leading": 1.0, "origins": [[0, 0]],
                                           "fg": "#000", "edge": "#fff",
                                           "stroke": 2, "font": "",
                                           "rotate": 0.0, "frame": [],
                                           "fixed": False, "fit_ok": True,
                                           "used_compact": False}
        req = urllib.request.Request(
            base + f"/api/page/0/region/{rec['id']}",
            data=_json.dumps({"kind": "sfx"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        assert p.pages[0].regions[0].get("layout"), \
            "changing the kind threw away the typesetting as well"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
