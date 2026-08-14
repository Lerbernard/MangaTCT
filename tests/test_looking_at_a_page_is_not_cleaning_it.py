"""Opening the Image view must not run the cleaner.

lee: *"if i move to teh image tab and i havnt done teh clenneing it shud just
show teh unclened age not clen them until i clean teh page"* — and, in the same
message, seven of these::

    mangatl: the cleaner refused the token (401) -- not asking again this run.

Seven, from turning pages. `render_index` inpainted on demand: asking for the
Image view of a page nobody had cleaned built the plate right then, which on a
project with the hosted cleaner switched on is a call out to it per page.

It also showed the wrong picture, which is the part that matters after the 401
is fixed. A view that cleans on sight cannot show what a page looks like BEFORE
cleaning — so there is no way to judge whether the Clean step is worth running,
and the Clean button reads 7/67 while every page you open is clean.

Now: a page that HAS been cleaned shows its plate. A page that has not shows
the scan, with the English still drawn on it, which is exactly what it will
look like until Clean runs.
"""
import shutil

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor as ED
from scratch import scratch


def _project(root, regions=True):
    from mangatl.project import Project

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 240, 3), 245, np.uint8)
    cv2.ellipse(img, (120, 90), (80, 45), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (120, 90), (80, 45), 0, 0, 360, (20, 20, 20), 2)
    cv2.putText(img, "ABC", (70, 100), 0, 1.2, (10, 10, 10), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    if regions:
        p.pages[0].regions = [{
            "id": 1, "kind": "bubble", "order": 0,
            "bbox": [60, 70, 120, 40], "bubble_bbox": [40, 45, 160, 90],
            "polygon": [[60, 70], [180, 70], [180, 110], [60, 110]],
            "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
        p.pages[0].detected = True
    return p


def _cleaned_calls(monkeypatch):
    """Count every time the cleaner is asked to build a plate."""
    calls = []
    real = ED.clean_page

    def spy(p, i, page, include_paint=True):
        calls.append(i)
        return real(p, i, page, include_paint=include_paint)

    monkeypatch.setattr(ED, "clean_page", spy)
    return calls


# ------------------------------------------------- it does not clean on sight

@pytest.mark.parametrize("mode", ["original", "clean", "typeset"])
def test_no_view_of_an_uncleaned_page_runs_the_cleaner(monkeypatch, mode):
    root = scratch("_tmp_nolook")
    p = _project(root)
    calls = _cleaned_calls(monkeypatch)
    ED.render_index(p, 0, mode)
    assert calls == [], "%s built a plate for a page nobody cleaned" % mode
    shutil.rmtree(root, ignore_errors=True)


def test_the_clean_view_of_an_uncleaned_page_is_the_scan(monkeypatch):
    """"Nothing has been erased yet" is a true picture and an empty one is
    not."""
    root = scratch("_tmp_nolook2")
    p = _project(root)
    _cleaned_calls(monkeypatch)
    got = ED.render_index(p, 0, "clean")
    want = ED.render_index(p, 0, "original")
    a = cv2.imdecode(np.frombuffer(got, np.uint8), 1)
    b = cv2.imdecode(np.frombuffer(want, np.uint8), 1)
    assert a.shape == b.shape
    assert float(np.abs(a.astype(int) - b.astype(int)).mean()) < 1.0
    shutil.rmtree(root, ignore_errors=True)


def test_the_english_is_still_drawn_on_the_uncleaned_page(monkeypatch):
    """The Image view is where you check the typesetting. Refusing to clean
    must not turn it into the Translation view."""
    root = scratch("_tmp_nolook3")
    p = _project(root)
    _cleaned_calls(monkeypatch)
    typeset = cv2.imdecode(np.frombuffer(
        ED.render_index(p, 0, "typeset"), np.uint8), 1)
    scan = cv2.imdecode(np.frombuffer(
        ED.render_index(p, 0, "original"), np.uint8), 1)
    assert float(np.abs(typeset.astype(int) - scan.astype(int)).mean()) > 1.0, \
        "nothing was drawn on it"
    shutil.rmtree(root, ignore_errors=True)


# -------------------------------------------- ...and it does once you clean

def test_a_cleaned_page_gets_its_plate(monkeypatch):
    root = scratch("_tmp_nolook4")
    p = _project(root)
    calls = _cleaned_calls(monkeypatch)
    p.pages[0].cleaned = True
    ED.render_index(p, 0, "clean")
    assert calls == [0], "the plate was not built for a cleaned page"
    shutil.rmtree(root, ignore_errors=True)


def test_cleaning_changes_what_the_view_shows(monkeypatch):
    """The render cache is keyed on everything that changes the picture, and
    "has it been cleaned" is now one of those. Without it the view you had
    open before pressing Clean is the view you keep."""
    root = scratch("_tmp_nolook5")
    p = _project(root)
    _cleaned_calls(monkeypatch)
    before = ED.render_index(p, 0, "clean")
    p.pages[0].cleaned = True
    after = ED.render_index(p, 0, "clean")
    assert before != after, "the cached pre-clean picture was served again"
    shutil.rmtree(root, ignore_errors=True)


def test_an_uploaded_plate_counts_as_cleaned(monkeypatch):
    """A page somebody cleaned by hand outside the app is cleaned, whatever
    the Clean step thinks."""
    root = scratch("_tmp_nolook6")
    p = _project(root)
    plate = root + "/own.png"
    cv2.imwrite(plate, np.full((300, 240, 3), 250, np.uint8))
    p.pages[0].custom_clean = plate
    calls = _cleaned_calls(monkeypatch)
    ED.render_index(p, 0, "clean")
    assert calls == [0]
    shutil.rmtree(root, ignore_errors=True)


def test_a_page_with_no_boxes_is_just_the_scan(monkeypatch):
    root = scratch("_tmp_nolook7")
    p = _project(root, regions=False)
    calls = _cleaned_calls(monkeypatch)
    ED.render_index(p, 0, "typeset")
    assert calls == []
    shutil.rmtree(root, ignore_errors=True)


def test_the_flag_is_in_the_cache_key():
    import inspect

    src = inspect.getsource(ED._render_stamp)
    assert "bool(st.cleaned)" in src
