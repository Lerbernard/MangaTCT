"""Your own cleaned page is not a suggestion.

lee: *"if i uploade my own file it shoud exclude that page from cleaing and
shoud alway use the uploadd page as a cleneed page"*.

Two halves, and only the second half was ever true. The plate was used — but
the page was still *cleaned*: pressing Clean threw the cached plate away, built
a mask, ran the inpainter over every bubble and, with the hosted cleaner
switched on, posted the page to it and waited on the network. Then it dropped
all of that and used the uploaded file, which is what it was going to do
anyway. The picture was right and the bill was real.

So the exclusion is now written down where cleaning is decided:

* `do_clean` — the Clean step — returns before it drops anything, builds
  anything or asks anyone anything. It still marks the page done, because a
  step that can never reach the end of its own list locks the step after it
  for ever.
* `clean_page` — every other way a page gets built — takes the file as the
  plate, as it already did.
* the background warm-up treats the page as free, because reading a PNG is.
* the per-bubble eyes disappear: they choose which bubbles the cleaner erases,
  and on this page the cleaner does not run.

And "always": nothing downstream is allowed to put the Japanese back. The eye
toggles, the flat fill, the model — none of them get a turn.
"""
import json
import os
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from mangatl.project import Project
from scratch import scratch


def _bubble_page(bg=245):
    """A page with one black-on-white balloon: something a cleaner can visibly
    change, so "was it cleaned?" is answerable from the pixels."""
    img = np.full((300, 220, 3), bg, np.uint8)
    cv2.ellipse(img, (110, 150), (70, 45), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (110, 150), (70, 45), 0, 0, 360, (25, 25, 25), 3)
    cv2.putText(img, "AAA", (70, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 0, 0), 3)
    return img


def _project(root, pages=2):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = _bubble_page()
    for k in range(pages):
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
    for st in p.pages:
        st.regions = [{"id": 1, "kind": "bubble", "order": 0,
                       "bbox": [60, 130, 100, 40],
                       "bubble_bbox": [45, 110, 130, 80],
                       "polygon": [[60, 130], [160, 130], [160, 170], [60, 170]],
                       "confidence": 0.9}]
        st.detected = True
    return p


def _give_plate(p, i, colour=(200, 0, 200)):
    """Upload a plate for page `i` that could not possibly be mistaken for
    anything the cleaner would produce."""
    d = os.path.join(p.output_dir, "custom_clean")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{i:03d}.png")
    cv2.imwrite(dest, np.full((p.pages[i].height, p.pages[i].width, 3),
                              colour, np.uint8))
    p.pages[i].custom_clean = dest
    return dest


def _is_mine(plate):
    """The magenta plate, not a cleaned scan."""
    b, g, r = plate.mean(axis=(0, 1))
    return g < 40 and b > 150 and r > 150


# ----------------------------------------------------- the page is excluded

def test_the_clean_step_does_not_touch_a_page_you_cleaned_yourself(tmp_path):
    """The heart of it. Nothing is inpainted, nothing is asked of anyone —
    `do_clean` does not even materialize the page."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    calls = []
    real = editor.clean_page

    def spy(pr, i, page, include_paint=True):
        calls.append(i)
        return real(pr, i, page, include_paint)

    editor.clean_page = spy
    try:
        editor.do_clean(p, 0, force=True)
        editor.do_clean(p, 1, force=True)
    finally:
        editor.clean_page = real
    assert calls == [1], f"page 0 was cleaned anyway: {calls}"


def test_the_hosted_cleaner_is_never_asked_about_that_page(tmp_path):
    """What the exclusion is actually FOR. AI cleaning on, a cleaner
    configured, and the page still costs nothing."""
    p = _project(str(tmp_path / "out"))
    p.settings.update(ai_clean="all", clean_url="http://example.invalid/clean",
                      clean_token="t")
    _give_plate(p, 0)
    asked = []
    real = editor._make_cleaner

    def spy(pr, strict=False):
        asked.append(strict)
        return real(pr, strict)

    editor._make_cleaner = spy
    try:
        editor.do_clean(p, 0, force=True)
    finally:
        editor._make_cleaner = real
    assert asked == [], "the page went to the hosted cleaner"


def test_the_plate_on_disk_is_not_thrown_away(tmp_path):
    """`force` means "redo this page". There is nothing to redo, and dropping
    the plate would make the next page view rebuild a page that has an answer
    sitting on disk."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    dropped = []
    real = editor.drop_plate
    editor.drop_plate = lambda pr, i: dropped.append(i)
    try:
        editor.do_clean(p, 0, force=True)
    finally:
        editor.drop_plate = real
    assert dropped == [], "it threw away a plate it was never going to use"


def test_it_still_counts_as_done(tmp_path):
    """Otherwise the Clean step sits at 22/23 for ever and Typeset — which
    waits on Clean finishing — is locked behind a page that will never be
    cleaned."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    assert not p.pages[0].cleaned
    editor.do_clean(p, 0, force=True)
    assert p.pages[0].cleaned


def test_the_browser_counts_it_as_done_too(tmp_path):
    """The step bar is built from `summary()`, and a page can carry its own
    plate before Clean has ever been pressed."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    pages = p.summary()["pages"]
    assert pages[0]["custom_clean"] is True
    assert pages[1]["custom_clean"] is False


def test_the_step_bar_counts_your_own_page():
    """The JS half of the same rule, read out of the file so the two cannot
    drift apart."""
    js = os.path.join(os.path.dirname(editor.__file__),
                      "static", "js", "pipeline.js")
    with open(js, encoding="utf8") as fh:
        text = fh.read()
    assert "p.custom_clean" in text, \
        "stepProgress does not count a page with its own plate"


def test_a_recorded_plate_that_is_gone_is_not_a_plate(tmp_path):
    """The file can be deleted from underneath the project — by a sync client,
    by hand. A dangling path must fall back to cleaning the page, not exclude
    it from cleaning and then have nothing to show."""
    p = _project(str(tmp_path / "out"))
    dest = _give_plate(p, 0)
    os.remove(dest)
    assert editor.own_plate_path(p, 0) == ""
    calls = []
    real = editor.clean_page
    editor.clean_page = lambda pr, i, page, include_paint=True: (
        calls.append(i), real(pr, i, page, include_paint))[1]
    try:
        editor.do_clean(p, 0, force=True)
    finally:
        editor.clean_page = real
    assert calls == [0], "a page whose plate has vanished must be cleaned"


def test_warming_a_page_with_its_own_plate_is_free(tmp_path):
    """The background warm-up leaves never-cleaned pages alone when the hosted
    cleaner is on, because building one costs a network call. This page costs
    an imread."""
    p = _project(str(tmp_path / "out"))
    p.settings.update(ai_clean="all", clean_url="http://example.invalid/clean")
    _give_plate(p, 0)
    assert editor._worth_warming(p, 0) is True
    assert editor._worth_warming(p, 1) is False, \
        "the hosted-cleaner guard itself has stopped working"


# ---------------------------------------------------- ...and always used

def test_your_file_is_the_plate_everywhere_a_page_is_built(tmp_path):
    """Not just the Clean step: opening the page, exporting, typesetting."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    assert _is_mine(page.clean_plate)


def test_a_closed_eye_does_not_put_the_japanese_back(tmp_path):
    """`skip_clean` pastes the original pixels back over a bubble — over the
    automatic plate. Doing it to your plate would paint the raws' text on top
    of the page you cleaned by hand, which is the exact opposite of "always
    use the uploaded page"."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    p.pages[0].regions[0]["skip_clean"] = True
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    assert _is_mine(page.clean_plate), "an eye toggle overrode the plate"


def test_a_mismatched_plate_is_resized_to_the_page(tmp_path):
    """A hand-cleaned file exported at a different size still has to line up
    with the boxes, which are in page coordinates."""
    p = _project(str(tmp_path / "out"))
    d = os.path.join(p.output_dir, "custom_clean")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "000.png")
    cv2.imwrite(dest, np.full((60, 40, 3), (200, 0, 200), np.uint8))
    p.pages[0].custom_clean = dest
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    assert page.clean_plate.shape[:2] == page.image.shape[:2]
    assert _is_mine(page.clean_plate)


def test_the_page_next_door_is_cleaned_normally(tmp_path):
    """Per page. Page 3 hand-cleaned must not stop pages 1, 2, 4 and 5."""
    p = _project(str(tmp_path / "out"))
    _give_plate(p, 0)
    page = p.materialize(1)
    editor.clean_page(p, 1, page)
    assert not _is_mine(page.clean_plate)
    inside = page.clean_plate[135:165, 70:150]
    assert float(np.min(cv2.cvtColor(inside, cv2.COLOR_BGR2GRAY))) > 120, \
        "page 1 was not cleaned"


def test_the_eyes_are_not_offered_for_a_page_that_is_never_cleaned():
    """A control that decides nothing is worse than no control."""
    js = os.path.join(os.path.dirname(editor.__file__),
                      "static", "js", "panels.js")
    with open(js, encoding="utf8") as fh:
        text = fh.read()
    at = text.index("function cleanPanel(")
    body = text[at:at + 1200]
    assert "cleanable.length && !custom" in body, \
        "the per-bubble eyes still show over a hand-cleaned page"


# -------------------------------------------------------- through the door

def _serve(fn, root=scratch("_tmp_ownplate")):
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return fn(p, srv.server_address[1])
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def _post(port, path, body):
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def test_uploading_one_marks_that_page_cleaned():
    """From the browser's side: upload the file, and the Clean step moves."""
    import base64

    def check(p, port):
        png = cv2.imencode(".png", np.full((300, 220, 3), (200, 0, 200),
                                           np.uint8))[1].tobytes()
        j = _post(port, "/api/page/0/clean_plate",
                  {"data": "data:image/png;base64,"
                           + base64.b64encode(png).decode()})
        assert j.get("custom") is True, j
        assert p.pages[0].cleaned is True
        assert editor.own_plate_path(p, 0)
    _serve(check)


def test_going_back_to_automatic_makes_it_undone_again():
    """It was never cleaned — it was excluded. Clearing the plate means there
    is real work to do on the page again, and the step has to say so."""
    import base64

    def check(p, port):
        png = cv2.imencode(".png", np.full((300, 220, 3), (200, 0, 200),
                                           np.uint8))[1].tobytes()
        _post(port, "/api/page/0/clean_plate",
              {"data": "data:image/png;base64,"
                       + base64.b64encode(png).decode()})
        j = _post(port, "/api/page/0/clean_plate", {"clear": True})
        assert j.get("custom") is False, j
        assert p.pages[0].cleaned is False, \
            "the Clean step still claims this page is done"
        assert editor.own_plate_path(p, 0) == ""
    _serve(check)


def test_clean_says_how_many_pages_it_left_alone():
    """Silence over a page that was skipped is how "the cleaner did nothing"
    gets reported as a bug."""
    def check(p, port):
        _give_plate(p, 0)
        j = _post(port, "/api/clean_all", {"pages": [0, 1]})
        assert j["own"] == 1, j
        for _ in range(200):
            if not p.job.get("running"):
                break
            import time
            time.sleep(0.05)
        msg = editor.clean_report(p)
        assert "your own cleaned file" in msg, msg
    _serve(check)
