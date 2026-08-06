"""Who cleans what — and a count that says so afterwards.

lee: *"the ai shoud be clening those not the cleaner the cleneer only need to
cleaner the white bubbles"*.

That was already almost the rule. `inpaint_page` sends a region to the local
fill when its background is FLAT — the colour is known, so the fill is exact and
instant and no model can beat it — and everything else to the model. The gap was
that "flat" says nothing about what the area IS: the inside of a black panel is
flat too, and a solid dark field carrying white typesetting is precisely the hard
case the model is for.

So with a model configured, the local path now keeps only the thing it is
unbeatable at — the pale flat bubble (`FLAT_LIGHT`) — and everything else goes to
the model. With no model configured nothing changes: a flat fill of the right
colour still beats Telea on a dark panel, and that path is long-tested.

And because every argument about this so far has been settled by looking at the
page and guessing, `inpaint_page` now counts what it did into `page.clean_stats`,
and a finished Clean says it: *"Cleaned 18 boxes: 12 filled flat (plain bubbles),
6 cleaned by the AI."*
"""
import json
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")


def _page_with(bg, text_colour, w=360, h=260):
    """A flat panel of `bg` with typesetting of `text_colour` written on it."""
    img = np.full((h, w, 3), bg, np.uint8)
    cv2.putText(img, "GO", (90, 160), cv2.FONT_HERSHEY_SIMPLEX, 2.2,
                text_colour, 9)
    return img


def _one_region(img, box, dark_text, kind="sfx"):
    from mangatl.models import Page, TextRegion
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    x, y, w, h = box
    tm = np.zeros(gray.shape, np.uint8)
    sub = gray[y:y+h, x:x+w]
    tm[y:y+h, x:x+w] = ((sub < 120) if dark_text else (sub > 190)
                        ).astype(np.uint8) * 255
    # the area the region occupies — without it `_flat_from` has nothing to
    # measure and every region looks "not flat", which would make this test
    # pass for the wrong reason
    area = np.zeros(gray.shape, np.uint8)
    area[y:y+h, x:x+w] = 255
    r = TextRegion(id=1, bbox=box, kind=kind, order=0,
                   src_text="ゴ", dst_text="GO",
                   bubble_mask=area, bubble_bbox=box)
    r.text_mask = tm
    pg = Page(image=img.copy())
    pg.regions = [r]
    return pg


def _model(sub, sm):
    """A cleaner that answers — the answer's content does not matter here."""
    return np.full_like(sub, 127)


def test_a_dark_flat_panel_goes_to_the_model_not_the_local_fill():
    """The case lee is pointing at: white typesetting on a black panel. Flat, and
    emphatically not a white bubble."""
    from mangatl import inpaint as I
    img = _page_with((18, 18, 18), (255, 255, 255))
    box = (70, 100, 220, 90)

    pg = _one_region(img, box, dark_text=False)
    I.inpaint_page(pg, neural=_model, neural_all=False)
    assert pg.clean_stats.get("neural") == 1, \
        f"the model was not asked to do it: {pg.clean_stats}"
    assert not pg.clean_stats.get("flat fill")

    # with nothing to hand it to, the flat fill is still the right answer —
    # it knows the colour exactly, and Telea on a dark panel does not
    pg2 = _one_region(img, box, dark_text=False)
    I.inpaint_page(pg2, neural=None)
    assert pg2.clean_stats.get("flat fill") == 1, pg2.clean_stats


def test_a_white_bubble_stays_with_the_local_fill():
    """The other half of the rule. Sending a plain white bubble to a hosted
    model costs money and cannot beat filling it with its own colour.

    WHITE, now, not merely pale: lee moved the line after seeing what the flat
    fill left on light screentone. See test_only_a_white_bubble... below."""
    from mangatl import inpaint as I
    img = _page_with((250, 250, 250), (20, 20, 20))
    # a BUBBLE, and it has to say so: with a model configured, a block with no
    # balloon round it goes to the model whatever the paper under the words
    # looks like — see test_outside_text_on_white_cloth_goes_to_the_model.
    pg = _one_region(img, (70, 100, 220, 90), dark_text=True, kind="bubble")
    I.inpaint_page(pg, neural=_model, neural_all=False)
    assert pg.clean_stats.get("flat fill") == 1, pg.clean_stats
    assert not pg.clean_stats.get("neural")

    # ...unless the person asked for the model on everything
    pg2 = _one_region(img, (70, 100, 220, 90), dark_text=True)
    I.inpaint_page(pg2, neural=_model, neural_all=True)
    assert pg2.clean_stats.get("neural") == 1, pg2.clean_stats


def test_a_region_the_model_refused_is_counted_apart():
    """"6 cleaned by the AI" must not include the ones it dropped."""
    from mangatl import inpaint as I
    img = _page_with((18, 18, 18), (255, 255, 255))

    def refuse(sub, sm):
        raise RuntimeError("401")

    pg = _one_region(img, (70, 100, 220, 90), dark_text=False)
    I.inpaint_page(pg, neural=refuse, neural_all=False)
    assert pg.clean_stats.get("fell back") == 1, pg.clean_stats
    assert not pg.clean_stats.get("neural"), \
        "a refused region is being counted as cleaned by the AI"


def test_the_report_says_who_did_what():
    from mangatl import editor
    from mangatl.project import Project
    root = scratch("_tmp_report")
    shutil.rmtree(root, ignore_errors=True)
    try:
        p = Project(None, root)
        editor.clear_clean_warning()
        assert editor.clean_report(p) == "", "nothing cleaned, nothing to say"
        editor._tally_clean({"flat fill": 12, "neural": 6, "skipped": 2})
        r = editor.clean_report(p)
        assert r.startswith("Cleaned 18 boxes:"), r
        assert "12 filled flat (plain bubbles)" in r
        assert "6 cleaned by the AI" in r
        assert "2 boxes had nothing recorded to erase" in r, r
        # a closed eye is not the same thing and must not hide behind it
        editor._tally_clean({"kept": 3})
        r2 = editor.clean_report(p)
        assert "3 boxes are set to KEEP the original text" in r2, r2
        assert "Cleaned 18 boxes" in r2, "a kept box is not a cleaned box"
        editor._tally_clean({"fell back": 3})
        assert "left to the local fill because the AI would not run" in \
            editor.clean_report(p)
        # "core only" is not a way of cleaning a box — it is something that
        # ALSO happened to a box cleaned some other way. Counting it as a route
        # inflated the total and stood it beside the routes as if it were one:
        # lee's page said *"Cleaned 13 boxes: 6 filled flat, 4 cleaned by the
        # AI, 3 core only"* when ten boxes were cleaned and three of those ten
        # were done strokes-only.
        editor.clear_clean_warning()
        editor._tally_clean({"flat fill": 6, "neural": 4, "core only": 3})
        r3 = editor.clean_report(p)
        assert r3.startswith("Cleaned 10 boxes:"), r3
        assert "core only" not in r3, r3
        assert "3 of them had only the letter strokes erased" in r3, r3
        editor.clear_clean_warning()
        assert editor.clean_report(p) == "", "the tally outlived its run"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_finished_clean_reports_itself_through_the_job():
    """The bar is where it has to arrive, or it may as well not exist."""
    from mangatl import editor
    from mangatl.project import Project
    import urllib.request

    root = scratch("_tmp_report_api")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = _page_with((250, 250, 250), (20, 20, 20))
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [70, 100, 220, 90],
        "bubble_bbox": [60, 90, 240, 110],
        "polygon": [[70, 100], [290, 100], [290, 190], [70, 190]],
        "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}]
    p.pages[0].detected = True
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        editor.clear_clean_warning()

        def job():
            with urllib.request.urlopen(base + "/api/job", timeout=20) as r:
                return json.loads(r.read())

        assert "info" not in job()
        req = urllib.request.Request(
            base + "/api/clean_all", data=json.dumps({"pages": [0]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        for _ in range(120):
            if not job().get("running") and job().get("info"):
                break
            threading.Event().wait(0.25)
        j = job()
        assert "Cleaned 1 box" in (j.get("info") or ""), j
        assert not j.get("warn"), "a clean local run must not warn"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        editor.clear_clean_warning()
        shutil.rmtree(root, ignore_errors=True)


def test_a_second_clean_does_not_report_a_working_cleaner_as_dead():
    """lee, with the token finally accepted: *"its saying the ai did not run
    even though the clean token is working"*.

    Press Clean twice. The second press finds every plate already built and
    reuses it — so nothing is sent to the model, which is the entire point of
    the cache. Reporting that as "AI cleaning was on but nothing was sent to it"
    turned a cleaner that had just started working into one that looked broken.

    The remark only belongs to a run that actually rebuilt something.
    """
    from mangatl import editor
    from mangatl.project import Project
    import urllib.request

    root = scratch("_tmp_second_clean")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = _page_with((250, 250, 250), (20, 20, 20))
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.settings.update(ai_clean="hard", clean_url="http://127.0.0.1:9/none",
                      clean_token="a-real-looking-token")
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [70, 100, 220, 90],
        "bubble_bbox": [60, 90, 240, 110],
        "polygon": [[70, 100], [290, 100], [290, 190], [70, 190]],
        "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}]
    p.pages[0].detected = True
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def job():
        with urllib.request.urlopen(base + "/api/job", timeout=20) as r:
            return json.loads(r.read())

    def clean():
        editor.clear_clean_warning()
        req = urllib.request.Request(
            base + "/api/clean_all", data=json.dumps({"pages": [0]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        for _ in range(160):
            if not job().get("running"):
                break
            threading.Event().wait(0.25)
        return job()

    try:
        editor._plate_cache.clear()
        first = clean()
        assert "nothing was sent" in (first.get("info") or ""), \
            f"the first run really did send nothing, and should say so: {first}"
        assert not first.get("warn"), "nothing failed, so nothing is a warning"

        second = clean()
        assert not second.get("warn"), \
            f"a page with nothing hard on it is not a broken cleaner: {second}"

        # And the reuse case itself — an ordinary visit, which is what a render
        # or a typeset asks for. Nothing was sent because nothing was rebuilt,
        # so the run says that plainly and does NOT say the AI failed to run.
        editor.clear_clean_warning()
        editor.do_clean(p, 0)                       # no force: reuse the plate
        report = editor.clean_report(p)
        assert "already cleaned" in report, report
        assert editor.clean_note(p) == "", \
            "reusing a finished plate is being reported as the AI not running"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        editor.clear_clean_warning(); editor._plate_cache.clear()
        shutil.rmtree(root, ignore_errors=True)


def test_pressing_clean_redoes_the_page():
    """lee, reading "37 pages were already cleaned, so the finished plate was
    reused": *"if i clcik it again it shoud redo it"*.

    The plate cache is there so that MOVING to a page is instant. Pressing Clean
    is not moving to a page — it is asking for the work — so the step drops the
    plate first and rebuilds. Opening a page, typesetting and exporting still
    reuse, or every click would cost a full inpaint.
    """
    from mangatl import editor
    from mangatl.project import Project
    import os
    import urllib.request

    root = scratch("_tmp_redo")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = _page_with((250, 250, 250), (20, 20, 20))
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [70, 100, 220, 90],
        "bubble_bbox": [60, 90, 240, 110],
        "polygon": [[70, 100], [290, 100], [290, 190], [70, 190]],
        "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}]
    p.pages[0].detected = True
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    builds = {"n": 0}
    real = editor.inpaint_mod.inpaint_page

    def counting(page, **kw):
        builds["n"] += 1
        return real(page, **kw)

    editor.inpaint_mod.inpaint_page = counting

    def job():
        with urllib.request.urlopen(base + "/api/job", timeout=20) as r:
            return json.loads(r.read())

    def clean():
        editor.clear_clean_warning()
        req = urllib.request.Request(
            base + "/api/clean_all", data=json.dumps({"pages": [0]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        for _ in range(160):
            if not job().get("running"):
                break
            threading.Event().wait(0.25)
        return job()

    try:
        editor._plate_cache.clear()
        first = clean()
        assert builds["n"] == 1, builds
        assert "Cleaned 1 box" in (first.get("info") or ""), first

        second = clean()
        assert builds["n"] == 2, \
            "the second press reused the plate instead of redoing the page"
        assert "already cleaned" not in (second.get("info") or ""), second
        assert "Cleaned 1 box" in (second.get("info") or ""), second

        # ...while merely LOOKING at the page still reuses, or every visit
        # would pay for a full inpaint
        n = builds["n"]
        editor.do_clean(p, 0)                 # what a render asks for
        assert builds["n"] == n, \
            "an ordinary visit is rebuilding the plate; that is the cache gone"
    finally:
        editor.inpaint_mod.inpaint_page = real
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        editor.clear_clean_warning(); editor._plate_cache.clear()
        shutil.rmtree(root, ignore_errors=True)


def test_no_box_is_ever_left_untouched():
    """lee: *"these box are badly cleaned or just skipped — fix that so this
    never happen, it shoud not skip boxes"*.

    Two silent skips existed. A swallowing light/dark split gave up and left the
    box alone (see test_pipeline's backstop, rewritten for the same reason). And
    every filter between the detector's mask and the erase mask — the Otsu
    split, the letterlike pass, the containment test — can return NOTHING, and
    an empty mask erases nothing at all, quietly, with the box still sitting
    there on the page.

    Each of those filters answers "which ink", never "whether". So an empty
    answer now falls back to what the detector actually found.
    """
    from mangatl import inpaint as I
    from mangatl.models import Page, TextRegion

    img = np.full((240, 320, 3), 235, np.uint8)
    for k in range(4):
        cv2.line(img, (100, 60 + k * 25), (210, 60 + k * 25), (20, 20, 20), 7)
    box = (90, 40, 130, 130)
    x, y, w, h = box
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tm = np.zeros(gray.shape, np.uint8)
    tm[y:y+h, x:x+w] = ((gray[y:y+h, x:x+w] < 120).astype(np.uint8)) * 255
    area = np.zeros(gray.shape, np.uint8)
    area[y:y+h, x:x+w] = 255
    r = TextRegion(id=1, bbox=box, kind="freefloat", order=0,
                   src_text="テスト", dst_text="TEST",
                   bubble_mask=area, bubble_bbox=box)
    r.text_mask = tm
    pg = Page(image=img.copy(), regions=[r])

    # Force the emptying rather than engineering a page that provokes it: the
    # contract under test is "an empty answer from the filters is not a reason
    # to erase nothing", and each filter has its own reasons to return empty.
    real = I.glyphs_only
    I.glyphs_only = lambda *a, **k: np.zeros(gray.shape, np.uint8)
    try:
        out = I.inpaint_page(pg, neural=None)
    finally:
        I.glyphs_only = real
    inside = np.zeros(gray.shape, bool)
    inside[y:y+h, x:x+w] = True
    assert not (out[inside] == img[inside]).all(), \
        "the box was left exactly as it was — a silent skip"
    assert (r.flagged or "").find("detector's own text mask") >= 0, \
        "it fell back without saying so"
    assert pg.clean_stats.get("skipped", 0) == 0, pg.clean_stats


def test_a_box_with_something_in_it_always_gets_a_method():
    """Whatever route a region takes, it takes ONE of them — the count of boxes
    with a method has to equal the count of boxes with something to erase. This
    is the guard that catches a new `continue` being added to that loop."""
    from mangatl import inpaint as I
    from mangatl.models import Page, TextRegion

    rng = np.random.default_rng(3)
    img = rng.integers(0, 60, (300, 300, 3), dtype=np.uint8)
    cv2.putText(img, "AAA", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (255, 255, 255), 6)                       # light on dark
    cv2.circle(img, (210, 210), 60, (250, 250, 250), -1)
    cv2.putText(img, "BB", (170, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (10, 10, 10), 5)                          # dark on light
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    regions = []
    for k, (box, dark) in enumerate((((30, 50, 160, 60), False),
                                     ((160, 170, 110, 70), True))):
        x, y, w, h = box
        tm = np.zeros(gray.shape, np.uint8)
        sub = gray[y:y+h, x:x+w]
        tm[y:y+h, x:x+w] = ((sub < 120) if dark else (sub > 190)
                            ).astype(np.uint8) * 255
        area = np.zeros(gray.shape, np.uint8)
        area[y:y+h, x:x+w] = 255
        r = TextRegion(id=k, bbox=box, kind="sfx", order=k,
                       src_text="x", dst_text="X",
                       bubble_mask=area, bubble_bbox=box)
        r.text_mask = tm
        regions.append(r)
    pg = Page(image=img.copy(), regions=regions)
    I.inpaint_page(pg, neural=None)
    got = {k: v for k, v in pg.clean_stats.items()
           if k not in ("skipped", "core only", "fell back")}
    assert sum(got.values()) == len(regions), \
        f"{len(regions)} boxes went in and {sum(got.values())} were cleaned: {pg.clean_stats}"


def test_the_eye_on_one_bubble_leaves_its_neighbour_cleaned():
    """lee: *"wheni lcick the yey on region 3 region 2 cleans, and this happnes
    with other boxes"*.

    Keeping one bubble's original text used to paste back a RECTANGLE — that
    box plus 16 pixels of slack — over the finished plate. Boxes on a real page
    touch and overlap constantly, so closing the eye on one brought its
    neighbour's Japanese back too, and the neighbour looked like it had never
    been cleaned.

    A region's writing is a mask, not a rectangle. The restore is that mask now,
    and it is never allowed over a pixel another box is having cleaned.
    """
    from mangatl import editor
    from mangatl.project import Project

    root = scratch("_tmp_eye")
    shutil.rmtree(root, ignore_errors=True)
    # two bubbles, side by side and close enough that their boxes overlap once
    # the 16px slack is added — which on a real page is most of them
    img = np.full((240, 420, 3), 250, np.uint8)
    cv2.putText(img, "AAA", (40, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (15, 15, 15), 5)
    # B's first stroke sits within the 16px slack of A's box — which is what a
    # page of touching balloons looks like, and what the rectangle restore ate
    cv2.putText(img, "BBB", (198, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (15, 15, 15), 5)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [
        {"id": 1, "kind": "bubble", "order": 0, "bbox": [30, 90, 160, 60],
         "bubble_bbox": [30, 90, 160, 60],
         "polygon": [[30, 90], [190, 90], [190, 150], [30, 150]],
         "src_text": "あ", "dst_text": "AAA", "confidence": 0.9},
        {"id": 2, "kind": "bubble", "order": 1, "bbox": [194, 90, 190, 60],
         "bubble_bbox": [194, 90, 190, 60],
         "polygon": [[194, 90], [384, 90], [384, 150], [194, 150]],
         "src_text": "い", "dst_text": "BBB", "confidence": 0.9}]
    p.pages[0].detected = True
    was, editor.PROJECT = editor.PROJECT, p

    def plate():
        editor._plate_cache.clear()
        page = p.materialize(0)
        editor.clean_page(p, 0, page, include_paint=False)
        return page.clean_plate

    def ink(im, box):
        x, y, w, h = box
        g = cv2.cvtColor(im[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        return int((g < 100).sum())

    A, B = (30, 90, 160, 60), (194, 90, 190, 60)
    try:
        both = plate()
        assert ink(both, A) < 40 and ink(both, B) < 40, \
            f"the fixture was not cleaned to begin with: {ink(both, A)}, {ink(both, B)}"

        # keep the FIRST bubble's original text
        p.pages[0].regions[0]["skip_clean"] = True
        one = plate()
        assert ink(one, A) > 200, "the eye did not keep this bubble's text"
        assert ink(one, B) < 40, \
            f"the neighbour's text came back too: {ink(one, B)} pixels of it"

        # and the other way round, so it is not an artefact of the order
        p.pages[0].regions[0]["skip_clean"] = False
        p.pages[0].regions[1]["skip_clean"] = True
        two = plate()
        assert ink(two, B) > 200, "the eye did not keep this bubble's text"
        assert ink(two, A) < 40, \
            f"the neighbour's text came back too: {ink(two, A)} pixels of it"

        # The hard case: two boxes that OVERLAP, so the same glyphs belong to
        # both masks. Keeping the big one's original text must still not undo
        # the small one's clean — the pixels the other box erased are not this
        # region's to restore.
        p.pages[0].regions[0]["skip_clean"] = True
        p.pages[0].regions[1]["skip_clean"] = False
        p.pages[0].regions[0]["bbox"] = [30, 90, 355, 60]
        p.pages[0].regions[0]["bubble_bbox"] = [30, 90, 355, 60]
        p.pages[0].regions[0]["polygon"] = [[30, 90], [385, 90],
                                            [385, 150], [30, 150]]
        editor._page_cache.clear()
        over = plate()
        assert ink(over, (30, 90, 160, 60)) > 200, \
            "the eye did not keep the overlapping box's own text"
        assert ink(over, B) < 60, \
            (f"restoring the big box undid the small box's clean: "
             f"{ink(over, B)} pixels came back")
    finally:
        editor.PROJECT = was
        editor._plate_cache.clear()
        shutil.rmtree(root, ignore_errors=True)


def test_the_cleaner_only_touches_the_box_that_has_the_text():
    """lee: *"the cleneer shoud only clean the box that has the text"*.

    `place_mask()` is the BALLOON — the room the English may use — and it is the
    right area for measuring a background and deciding what is flat. It is not
    the right area to erase: on a wide oval with a narrow column of kana in it,
    anything else inside that oval was fair game, because the mask handed to the
    cleaner was "the ink in the balloon".
    """
    from mangatl import inpaint as I
    from mangatl.models import Page, TextRegion

    img = np.full((260, 420, 3), 250, np.uint8)
    cv2.ellipse(img, (210, 130), (190, 110), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (210, 130), (190, 110), 0, 0, 360, (20, 20, 20), 3)
    cv2.putText(img, "AA", (110, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (15, 15, 15), 6)                      # the writing, in its box
    cv2.putText(img, "zz", (280, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (15, 15, 15), 6)                      # ink inside the SAME balloon
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    text_box = (100, 105, 100, 60)
    balloon = np.zeros(gray.shape, np.uint8)
    cv2.ellipse(balloon, (210, 130), (185, 105), 0, 0, 360, 255, -1)
    tm = ((gray <= 128) & (balloon > 0)).astype(np.uint8) * 255   # as loaded back
    r = TextRegion(id=1, bbox=text_box, kind="bubble", order=0,
                   src_text="あ", dst_text="AA",
                   bubble_mask=balloon, bubble_bbox=(25, 25, 370, 210))
    r.text_mask = tm
    pg = Page(image=img.copy(), regions=[r])
    out = I.inpaint_page(pg, neural=None)

    def ink(im, box):
        x, y, w, h = box
        g = cv2.cvtColor(im[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        return int((g < 100).sum())

    assert ink(out, text_box) < 40, \
        f"the box's own writing was not erased: {ink(out, text_box)}"
    other = (270, 105, 110, 60)
    assert ink(out, other) > 200, \
        (f"the cleaner erased ink outside the box, elsewhere in the balloon: "
         f"{ink(out, other)} left of {ink(img, other)}")


def test_not_one_pixel_outside_the_boxes_is_ever_changed():
    """lee: *"the clenners shoud only clean withing the box, it hsoud never
    touch a pixel outside teh box area, both the local and the ai — the box that
    shoud be considered is teh box that i see"*.

    He sent a plate with a whole bubble wiped and two small boxes standing in
    it. Half a dozen steps can reach past the box they were given — the halo
    sweep grows the mask until the background stops looking like ink, the model
    gets `NEURAL_PAD` of slack, the ghost sweep re-fills a flat bubble to its own
    edges, a screentone copy works page-wide. Each has a reason; none of them is
    a reason to change a pixel nobody drew a box around.

    One fence, after everything, so a step added later cannot forget it.
    """
    from mangatl import inpaint as I
    from mangatl.models import Page, TextRegion

    # a big flat bubble: two small boxes in it, and writing elsewhere inside it
    img = np.full((320, 520, 3), 40, np.uint8)
    cv2.rectangle(img, (30, 30), (490, 290), (252, 252, 252), -1)
    cv2.putText(img, "AA", (70, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (15, 15, 15), 5)                       # inside box 1
    cv2.putText(img, "BB", (330, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (15, 15, 15), 5)                       # inside box 2
    cv2.putText(img, "xxxx", (90, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (15, 15, 15), 5)                       # in the bubble, no box
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bubble = np.zeros(gray.shape, np.uint8)
    cv2.rectangle(bubble, (34, 34), (486, 286), 255, -1)

    def region(rid, box):
        tm = ((gray <= 128) & (bubble > 0)).astype(np.uint8) * 255
        r = TextRegion(id=rid, bbox=box, kind="bubble", order=rid,
                       src_text="あ", dst_text="AA",
                       bubble_mask=bubble, bubble_bbox=(30, 30, 460, 260))
        r.text_mask = tm
        return r

    BOXES = [(60, 95, 110, 55), (320, 95, 110, 55)]
    inside = np.zeros(gray.shape, bool)
    # the box and its doorstep: a glyph drawn a few pixels past its box has to
    # be finishable or the text cannot all go (see inpaint.GLYPH_REACH). Nothing
    # further out may change, and nothing at all unless it is joined to ink the
    # box caught.
    from mangatl.inpaint import GLYPH_REACH as REACH
    for x, y, w, h in BOXES:
        inside[max(0, y-REACH):y+h+REACH, max(0, x-REACH):x+w+REACH] = True

    for label, neural in (("local", None),
                          # a model that answers with the paper colour, so
                          # "is the box clean" means the same thing either way
                          ("the model", lambda sub, sm: np.full_like(sub, 250))):
        pg = Page(image=img.copy(),
                  regions=[region(k, b) for k, b in enumerate(BOXES)])
        out = I.inpaint_page(pg, neural=neural, neural_all=neural is not None)
        assert (out[~inside] == img[~inside]).all(), \
            f"{label}: pixels outside the boxes were changed"
        # ...and it is still a clean: what IS in the boxes went
        for x, y, w, h in BOXES:
            g = cv2.cvtColor(out[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
            assert int((g < 100).sum()) < 40, f"{label}: the box was not cleaned"
        # the writing nobody boxed is untouched, which is the visible half of it
        g = cv2.cvtColor(out[215:265, 85:290], cv2.COLOR_BGR2GRAY)
        assert int((g < 100).sum()) > 200, \
            f"{label}: unboxed writing in the same bubble was erased"


def test_a_glyph_drawn_past_its_box_is_finished_not_cut_in_half():
    """lee, on a page of half-erased strokes: *"the tetxt is a non negotiable
    they need to go"*.

    Clipping the erase mask at the box — which is what "only clean inside the
    box" means — cuts every glyph that reaches past it, and half a glyph erased
    is a stub left on the page. Ink joined to what the box caught is followed
    into the doorstep (`GLYPH_REACH` pixels), and only there: line work crossing
    the middle of the box is not adopted, because nothing INSIDE the box is
    added.
    """
    from mangatl import inpaint as I
    from mangatl.models import Page, TextRegion

    img = np.full((240, 360, 3), 250, np.uint8)
    # a stroke that starts inside the box and runs 6px past its right edge
    cv2.line(img, (120, 120), (206, 120), (15, 15, 15), 9)
    box = (100, 90, 100, 60)                       # right edge at x=200
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tm = np.zeros(gray.shape, np.uint8)
    x, y, w, h = box
    tm[y:y+h, x:x+w] = ((gray[y:y+h, x:x+w] <= 128).astype(np.uint8)) * 255
    area = np.zeros(gray.shape, np.uint8)
    area[y:y+h, x:x+w] = 255
    r = TextRegion(id=1, bbox=box, kind="bubble", order=0,
                   src_text="ー", dst_text="-",
                   bubble_mask=area, bubble_bbox=box)
    r.text_mask = tm
    out = I.inpaint_page(Page(image=img.copy(), regions=[r]), neural=None)

    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    assert int((g[110:132, 100:200] < 100).sum()) < 30, "the stroke was not erased"
    stub = int((g[110:132, 200:210] < 100).sum())
    assert stub < 30, f"{stub} pixels of the stroke were left past the box"
    # and the doorstep is the limit: nothing further out is touched
    assert (out[:, 215:] == img[:, 215:]).all(), \
        "the clean ran past the doorstep"


def test_a_new_cleaner_retires_every_plate_the_old_one_made():
    """lee, after a round of fixes: *"nothing vhanged"*.

    Nothing had. A finished plate is written to `plate_cache/` and reused for
    ever, and its name is built from the page, the boxes and the settings —
    none of which change when the cleaning code does. So the improvements were
    real and invisible at the same time: opening a page handed back the picture
    the OLD code had made, and only a page whose boxes had been edited since
    would ever show the difference.

    `inpaint.ALGO` is part of the plate's identity now, so bumping it retires
    every plate the previous build made, without deleting anything by hand.
    """
    from mangatl import editor, inpaint
    from mangatl.project import Project
    root = scratch("_tmp_algo")
    shutil.rmtree(root, ignore_errors=True)
    try:
        p = Project(None, root)
        img = _page_with((250, 250, 250), (20, 20, 20))
        p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
        p.pages[0].regions = [{
            "id": 1, "kind": "bubble", "order": 0, "bbox": [70, 100, 220, 90],
            "bubble_bbox": [60, 90, 240, 110],
            "polygon": [[70, 100], [290, 100], [290, 190], [70, 190]],
            "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}]
        p.pages[0].detected = True

        was = inpaint.ALGO
        before = editor._plate_stamp(p, 0)
        path_before = editor._plate_disk_path(p, 0)
        try:
            inpaint.ALGO = was + "-next"
            assert editor._plate_stamp(p, 0) != before, \
                "the plate's identity does not include the cleaner's version"
            assert editor._plate_disk_path(p, 0) != path_before, \
                "the new build would read the old build's file"
        finally:
            inpaint.ALGO = was
        assert editor._plate_stamp(p, 0) == before, "the stamp is not stable"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_small_kana_on_a_dark_panel_are_erased_too():
    """lee, with the box drawn and the eye open and the text still there:
    *"try to fix the text we need all the text gone"*.

    Page 17, box 16. The mask covered the big display type at the top of the
    column and stopped: every smaller character below it was dropped before the
    cleaner ever saw it, and came out of a Clean untouched.

    `_letterlike` was the filter. On a light-on-dark panel the detector's mask is
    the panel, so it is thrown away and rebuilt from a light/dark split — and
    that split returns the screentone as well as the words, so anything thinner
    than a brush stroke is dropped. The opening that does it is sized for
    DISPLAY type; a column of small kana on the same panel is drawn thinner and
    loses every component to it. A tone dot is a handful of pixels; a letter is
    not, whatever its stroke width — so size joins thickness as a way to be kept.

    Measured on the real page: 7331 white pixels in that box before, 2198 left
    after — and 3 with this.
    """
    from mangatl import inpaint as I

    # a dark panel carrying screentone dots, one big glyph and one small one
    rng = np.random.default_rng(5)
    img = np.full((260, 320, 3), 20, np.uint8)
    dots = (rng.random((260, 320)) < 0.06)
    img[dots] = 235                                  # tone: small and thin
    cv2.putText(img, "A", (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 3.0,
                (255, 255, 255), 12)                 # display type
    cv2.putText(img, "abc", (150, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (255, 255, 255), 2)                  # the small kana's stand-in
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    kept = I._letterlike(((gray >= I.BRIGHT).astype(np.uint8)) * 255)
    big = kept[100:160, 25:110]
    small = kept[120:145, 148:230]
    assert big.any(), "the display type was dropped, which was never the bug"
    assert int((small > 0).sum()) > 60, \
        f"the small typesetting was dropped before the cleaner saw it: {int((small > 0).sum())}"

    # and the tone is still not mistaken for writing: whatever is kept must be
    # a small fraction of the dots on the panel
    tone_kept = int((kept > 0).sum()) - int((big > 0).sum()) - int((small > 0).sum())
    assert tone_kept < 0.25 * int(dots.sum()), \
        f"the screentone was swept in as typesetting: {tone_kept} of {int(dots.sum())}"


# ------------------------------------- only a WHITE bubble is the local job

def _white_page(level, noise=0.0, seed=1):
    """A balloon of one colour, with an optional grain in it."""
    rng = np.random.default_rng(seed)
    img = np.full((260, 220, 3), 30, np.uint8)
    cv2.ellipse(img, (110, 130), (85, 60), 0, 0, 360,
                (int(level), int(level), int(level)), -1)
    if noise:
        patch = img[70:190, 25:195].astype(np.float32)
        patch += rng.normal(0, noise, patch.shape)
        img[70:190, 25:195] = np.clip(patch, 0, 255).astype(np.uint8)
    cv2.putText(img, "AB", (75, 145), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (15, 15, 15), 4)
    return img


def _white_region(img):
    from mangatl.models import TextRegion
    r = TextRegion(id=1, bbox=(70, 112, 90, 42), kind="bubble")
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(mask, (110, 130), (83, 58), 0, 0, 360, 255, -1)
    r.bubble_mask = mask
    ink = np.zeros(img.shape[:2], np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink[(gray < 60)] = 255
    ink[mask == 0] = 0
    r.text_mask = ink
    return r


def _how(img, neural):
    """Which path this balloon took, as `inpaint_page` decided it."""
    from mangatl import inpaint
    from mangatl.models import Page
    page = Page(image=img.copy(), regions=[_white_region(img)])
    seen = []
    real = inpaint._flat_from

    def spy(*a, **k):
        out = real(*a, **k)
        seen.append(out)
        return out
    inpaint._flat_from = spy
    try:
        inpaint.inpaint_page(page, neural=neural)
    finally:
        inpaint._flat_from = real
    return page.regions[0], seen


@pytest.mark.parametrize("level,noise,local", [
    (252, 0.0, True),     # a white balloon: the local fill's own job
    (246, 1.5, True),     # white paper with a little grain in it
    (215, 0.0, False),    # pale grey — flat, but not white
    (250, 14.0, False),   # white-ish, with tone in it
    (90, 0.0, False),     # a dark panel, flat as anything
])
def test_only_a_white_bubble_stays_with_the_local_fill(level, noise, local):
    """lee: *"make it so that the local celener is only used fro fully white
    bubbles every thing else should be handles by the ai clenner"*.

    "Flat" was the old test and it is not the same question: the inside of a
    black panel is flat, and so is a page of light screentone. Both of those
    are exactly what the model is for, and a flat fill leaves a patch on them.
    """
    img = _white_page(level, noise)

    def neural(im, mask, **k):        # stands in for the hosted cleaner
        neural.asked = True
        return im
    neural.asked = False

    r, _ = _how(img, neural)
    assert (not neural.asked) is local, (r.flagged, neural.asked)


def test_with_no_model_a_pale_flat_area_still_gets_the_flat_fill():
    """There is nothing to hand it to, and a flat fill still beats Telea on a
    pale flat background. The tighter rule is about CHOOSING between the two,
    not about what the local path can do."""
    from mangatl import inpaint
    from mangatl.models import Page
    img = _white_page(215)
    page = Page(image=img.copy(), regions=[_white_region(img)])
    out = inpaint.inpaint_page(page, neural=None)
    assert out is not None
    # the letters are gone and the balloon is still its own colour
    mid = out[128, 100:130].mean()
    assert mid > 190, mid


def test_the_thresholds_say_white_not_pale():
    from mangatl import inpaint
    assert inpaint.WHITE_LEVEL >= 230, inpaint.WHITE_LEVEL
    assert inpaint.WHITE_STD <= 6, inpaint.WHITE_STD
    # ...and are stricter than the old "flat and lightish" pair they replaced
    assert inpaint.WHITE_LEVEL > inpaint.FLAT_LIGHT
    assert inpaint.WHITE_STD < inpaint.FLAT_STD


def test_the_algo_stamp_moved_with_the_white_only_rule():
    """A plate is built once and reused for ever, and its name is made of the
    page, the boxes and the settings — none of which change when the CLEANING
    CODE does. `inpaint.ALGO` is the part that does, and it has to be bumped
    with every change to how a page is cleaned.

    It was not bumped with the white-only routing, so every page already
    cleaned kept a plate made under the old rule and the change arrived
    invisible — on exactly the pages lee was looking at when he said the
    cleaner *"just ignores some text"*. This is the third time that mistake has
    been made; it is worth a test that names the change.
    """
    from mangatl import inpaint
    assert inpaint.ALGO >= "2026-07-31-a", inpaint.ALGO


# ------------------------------------------- a cloak is not a white bubble

def _on_cloak():
    """A column of outside text printed on white cloth, with hatching a little
    way off — lee's page. Every test the flat fill applies passes here: the
    cloth is white, it is flat, and the sample never reaches the hatching."""
    img = np.full((340, 300), 252, np.uint8)
    for y in range(0, 340, 6):
        for x in range(160, 300, 6):
            if (x // 6 + y // 6) % 2 == 0:
                cv2.rectangle(img, (x, y), (x + 4, y + 4), 150, -1)
    ink = np.zeros((340, 300), np.uint8)
    y = 70
    while y < 250:
        cv2.rectangle(ink, (90, y), (126, y + 18), 255, -1)
        cv2.rectangle(ink, (97, y + 5), (119, y + 13), 0, -1)
        y += 24
    img[ink > 0] = 20
    return img, ink


def _white_balloon():
    img = np.full((400, 400), 120, np.uint8)
    for y in range(0, 400, 5):
        cv2.line(img, (0, y), (400, y - 90), 60, 2)
    cv2.ellipse(img, (200, 200), (150, 140), 0, 0, 360, 255, -1)
    cv2.ellipse(img, (200, 200), (150, 140), 0, 0, 360, 25, 3)
    ink = np.zeros((400, 400), np.uint8)
    for yy in (175, 205):
        cv2.rectangle(ink, (160, yy), (245, yy + 14), 255, -1)
        cv2.rectangle(ink, (166, yy + 4), (239, yy + 10), 0, -1)
    img[ink > 0] = 20
    bub = np.zeros((400, 400), np.uint8)
    cv2.ellipse(bub, (200, 200), (147, 137), 0, 0, 360, 255, -1)
    return img, ink, bub


def _clean(img, ink, kind, bubble=None, neural=None):
    from mangatl.inpaint import inpaint_page
    from mangatl.models import Page, TextRegion
    from mangatl.detect import balloon as B
    x, y, w, h = cv2.boundingRect(ink)
    r = TextRegion(id=1, bbox=(x - 3, y - 3, w + 6, h + 6), kind=kind,
                   text_mask=ink, bubble_mask=bubble,
                   bubble_bbox=(x - 3, y - 3, w + 6, h + 6))
    r.src_text = "a"
    r.dst_text = "b"
    if bubble is None:
        B.give_room(img, [r])
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    inpaint_page(page, neural=neural)
    return page, r


def test_outside_text_on_white_cloth_goes_to_the_model():
    """lee: *"the local celener is only used fro fully white bubbles every
    thing else should be handles by the ai clenner"*.

    The three tests the flat path applies are all about the paper immediately
    round the words, and white cloth passes every one. What they cannot see is
    that this is not a bubble at all — the block is standing on artwork, and
    artwork is the model's job. That is the sixth "filled flat" on his page,
    and the white box he kept sending pictures of."""
    img, ink = _on_cloak()
    page, r = _clean(img, ink, "freefloat", neural=lambda sub, m: sub.copy())
    assert r.clean_route == "neural", r.clean_route
    assert not page.clean_stats.get("flat fill"), page.clean_stats


def test_a_real_white_balloon_still_takes_the_flat_fill():
    """The thing the local path is unbeatable at, untouched — the colour is
    known exactly, so the fill is exact and instant, and the words go."""
    img, ink, bub = _white_balloon()
    page, r = _clean(img, ink, "bubble", bubble=bub,
                     neural=lambda sub, m: sub.copy())
    assert r.clean_route == "flat fill", r.clean_route
    out = cv2.cvtColor(page.clean_plate, cv2.COLOR_BGR2GRAY)
    assert float((out[ink > 0] >= 235).mean()) > 0.95


def test_with_no_model_the_cloth_is_filled_flat_after_all():
    """Only when there IS a model to hand it to. With none configured there is
    nothing better to do with it, and a flat fill still beats Telea."""
    img, ink = _on_cloak()
    page, r = _clean(img, ink, "freefloat", neural=None)
    assert r.clean_route == "flat fill", r.clean_route
