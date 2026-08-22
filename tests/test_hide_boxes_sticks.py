"""Turning the boxes back on survives changing pages.

lee: *"the hide boxes shoud stay off wheni switch pages"*.

`syncBoxesForView('typeset')` forced `hideboxes` on every time it ran, and
`showPage` runs it on every page change - so the switch could be turned off, and
went back on at the next page, every time. The remembered preference
(`boxPrefBeforeText`) made it worse by disguising the cause: it looked like the
value was being restored from somewhere.

Entering the Translated view still hides the boxes, because that view is for
reading the typesetting. After that the switch is his.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch

cv2 = pytest.importorskip("cv2")


def _project(root, n=3):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for k in range(n):
        img = np.full((520, 760, 3), 242, np.uint8)
        cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (25, 25, 25), 3)
        cv2.putText(img, f"P{k}", (250, 235), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (20, 20, 20), 3)
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
        p.pages[k].regions = [{
            "id": 1, "kind": "bubble", "order": 0,
            "bbox": [200, 170, 200, 100], "bubble_bbox": [150, 130, 300, 180],
            "polygon": [[200, 170], [400, 170], [400, 270], [200, 270]],
            "src_text": "テスト", "dst_text": f"LINE {k}", "confidence": 0.9}]
        p.pages[k].detected = True
        p.pages[k].cleaned = True          # or the Translated view will not open
    return p


def test_the_boxes_stay_on_across_pages():
    from mangatl import editor

    root = scratch("_tmp_hidebox")
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

            hidden = lambda: pg.evaluate("$('hideboxes').checked")
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            assert pg.evaluate("view") == "typeset", "the view would not open"
            assert hidden(), "entering the Translated view should hide the boxes"

            # he turns them back on, then moves through the chapter
            pg.evaluate("$('hideboxes').checked=false; drawBoxes()")
            for i in (1, 2, 0, 1):
                pg.evaluate(f"showPage({i})")
                pg.wait_for_timeout(800)
                assert not hidden(), \
                    f"page {i} turned Hide boxes back on by itself"

            # and the boxes really are drawn, not merely unticked
            assert pg.evaluate(
                "document.querySelectorAll('#stage .box').length") > 0, \
                "the switch is off but nothing is drawn"

            # leaving and re-entering the view hides them again, as before
            pg.evaluate("setView('original')")
            browserpool.settled(pg)
            pg.evaluate("setView('typeset')")
            browserpool.settled(pg)
            assert hidden(), \
                "coming back into the Translated view should hide them again"
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)
