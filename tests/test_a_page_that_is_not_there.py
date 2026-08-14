"""Asking for a page the project no longer has.

lee's console, over and over::

    Traceback (most recent call last):
      File "editor.py", line 3306, in do_GET
        img = p.image(i)
      File "project.py", line 1223, in image
        self._img_cache[i] = load_page(self.pages[i].path).image
    IndexError: list index out of range

and in the editor, a toast reading `IndexError: list index out of range`.

Nothing was wrong with the page. There was no page. The browser holds one list
of pages and the server holds another, and they come apart every time the
server's list gets shorter while the old one is still on screen:

* a webtoon re-cut from 120 tiles into 66 pages;
* a page deleted;
* **Close project**, with the thumbnails of the chapter still arriving.

Requests already in flight then name a page nobody has. The browser asks for
twenty of them at once, so one closed project is a screenful of tracebacks and
a toast that reads like the editor is broken.

A page that is not there is a 404 with a sentence in it. The browser already
knows what to do with that, and nobody has to read Python to find out which
page it was.
"""
import json
import os
import shutil
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from where import PKG

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from mangatl.project import Project


def _project(root, pages=3):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    rng = np.random.default_rng(4)
    for i in range(pages):
        img = np.repeat(rng.integers(60, 220, (180, 120, 1), dtype=np.uint8),
                        3, axis=2)
        p.add_uploaded("p%d.png" % i, cv2.imencode(".png", img)[1].tobytes())
    return p


@pytest.fixture()
def serving(tmp_path):
    p = _project(str(tmp_path / "out"))
    was, editor.PROJECT = editor.PROJECT, p
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield p, "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        editor.PROJECT = was


def _get(base, route):
    """Returns (status, body). A 404 is an answer here, not a failure."""
    try:
        with urllib.request.urlopen(base + route) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _send(base, route, method, body=None):
    req = urllib.request.Request(
        base + route, json.dumps(body or {}).encode(),
        {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ------------------------------------------------------------------- reading

@pytest.mark.parametrize("route", [
    "/api/page/9",
    "/img/9",
    "/render/9",
    "/api/page/9/hidden",
])
def test_a_page_past_the_end_is_a_404(serving, route):
    p, base = serving
    assert len(p.pages) == 3
    code, body = _get(base, route)
    assert code == 404, (route, code, body[:200])
    assert b"IndexError" not in body, "a person cannot act on a Python type"


def test_it_says_which_page_and_how_many_there_are(serving):
    """The message is the whole point. "list index out of range" tells you
    nothing; "page 10 is not in this project any more (there are 3)" tells you
    the page list on screen is stale and the chapter is fine."""
    _p, base = serving
    code, body = _get(base, "/api/page/9")
    said = json.loads(body)["error"]
    assert code == 404
    assert "10" in said and "3" in said, said


def test_a_closed_project_says_there_are_no_pages(serving):
    """lee's most likely route in: Close project while a chapter of
    thumbnails is still on the wire. Twenty requests, twenty tracebacks."""
    p, base = serving
    p.clear()
    code, body = _get(base, "/img/0")
    assert code == 404
    assert "no pages" in json.loads(body)["error"], body


def test_the_pages_that_are_there_still_answer(serving):
    """The guard must not be a wall. Every real page has to come back
    untouched, including the last one, which is the one an off-by-one eats."""
    p, base = serving
    for i in range(len(p.pages)):
        code, body = _get(base, "/api/page/%d" % i)
        assert code == 200, (i, body[:200])
        assert json.loads(body)["index"] == i
    code, body = _get(base, "/img/%d" % (len(p.pages) - 1))
    assert code == 200 and body[:2] == b"\xff\xd8"


def test_something_that_is_not_a_page_route_is_untouched(serving):
    """`/api/project` has a number nowhere near it and must not be sniffed
    at by the page guard."""
    _p, base = serving
    code, body = _get(base, "/api/project")
    assert code == 200
    assert json.loads(body)


# ------------------------------------------------------------------- writing

def test_posting_work_to_a_page_that_is_gone_is_a_404(serving):
    """A run scoped to pages that have since been re-cut. Worse than a read:
    this one was about to charge coins for it."""
    _p, base = serving
    code, body = _send(base, "/api/page/9/ocr", "POST", {})
    assert code == 404, body[:200]
    assert b"IndexError" not in body


def test_deleting_a_page_that_is_gone_is_a_404(serving):
    _p, base = serving
    code, body = _send(base, "/api/page/9/region/1", "DELETE")
    assert code == 404, body[:200]


def test_a_real_page_can_still_be_written_to(serving):
    p, base = serving
    code, _b = _send(base, "/api/page/0/hidden", "POST", {"kinds": []})
    assert code == 200
    assert len(p.pages) == 3


# ----------------------------------------------------------------- the shape

def test_the_guard_reads_the_number_and_not_the_rest_of_the_path(serving):
    """`/api/page/1/region/99` names page 1, not region 99. Getting that
    backwards would 404 every region call on a project with few pages."""
    _p, base = serving
    code, _b = _send(base, "/api/page/1/region/99", "DELETE")
    assert code == 200, "page 1 exists; the region number is not its business"


# ------------------------------------------------- and the screen it leaves

def test_a_page_whose_picture_never_arrives_still_leaves_you_in_the_middle():
    """The stage carries a 46vmax transparent margin on every side so the page
    can be panned well past its own edges, and the view is centred in that
    slack when the picture loads.

    Hanging the centring on `onload` alone meant a page whose image 404s left
    the scroll exactly where boot put it - 0,0, which is deep inside that
    margin, and therefore a screen of nothing but background with two
    scrollbars on it. lee sent a screenshot of it and read it as the page not
    being centred. It was a missing page painted as a broken editor.

    A page that is not there is supposed to look like an empty middle with the
    page list still beside it.
    """
    src = (PKG / "static" / "js" / "frames.js").read_text(encoding="utf-8")
    assert "img.onload=fit;" in src
    assert "img.onerror=" in src, \
        "the centring must not depend on the picture arriving"
    at_load = src.index("img.onload=fit;")
    at_err = src.index("img.onerror=")
    assert at_err > at_load
    assert "fit()" in src[at_err:at_err + 200]


def test_a_page_opened_in_a_pane_that_then_changes_size_is_refitted():
    """lee, twice: *"some pages are still not at the center of the workspace"*.

    The fit is measured against the pane. A page opened while the pane was a
    different size - the settings page still up, the window not laid out yet,
    a sidebar appearing - is fitted to a pane that no longer exists, so it
    comes out too big for the one in front of you and centring it only puts its
    MIDDLE on screen. Which looks exactly like a page that was not centred.

    So while the centring is still pending, a change in the WRAP's size refits
    as well as re-centres. Only while pending: once the person has taken the
    view over, resizing the window must not throw their zoom away.
    """
    src = (PKG / "static" / "js" / "view.js").read_text(encoding="utf-8")
    at = src.index("const ro=new ResizeObserver(")
    block = src[at:at + 700]
    assert "fitZoom=fitScale()" in block, "a resize has to refit, not just scroll"
    assert "centerPending &&" in block, "...and only while it is still pending"
