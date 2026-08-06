"""One slow page does not stop the editor.

lee pasted a hundred of these, and then: *"the page is stuck"*.

    ConnectionAbortedError: [WinError 10053] An established connection was
    aborted by the software in your host machine

Every one of them is the answer to a request being written to a socket the
browser had already given up on. That is the symptom, not the fault. The fault
is that building a page took a lock the WHOLE editor shared, and building a
page can mean calling the hosted cleaner and waiting on the network for it. One
slow page therefore stopped every other request in the app — page views, region
edits, the lot — until it came back or timed out three minutes later. From
outside, the app has died; the browser abandons what it asked for, and every
answer that eventually arrives is written to nobody.

Two changes:

* the lock is **per page**. Two builds of the same page still take turns, which
  is what the lock was for; two builds of different pages no longer wait on
  each other at all.
* the wait on the hosted cleaner is **75 seconds**, not 180. A page whose
  cleaner has gone quiet holds up that page and nothing else, and not for
  three minutes.

The connection-aborted case is handled where it belongs as well: whoever asked
is not there to be told, so the answer is dropped quietly instead of raising,
printing a traceback, and then having the handler try to write a 500 down the
same dead socket — which raised again. Two tracebacks apiece, tens a minute,
burying anything real.
"""
import json
import shutil
import threading
import time
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from scratch import scratch


def _project(root, pages=4):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 220, 3), 245, np.uint8)
    cv2.ellipse(img, (110, 150), (70, 45), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (110, 150), (70, 45), 0, 0, 360, (25, 25, 25), 3)
    for k in range(pages):
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
    for st in p.pages:
        st.regions = [{"id": 1, "kind": "bubble", "order": 0,
                       "bbox": [60, 130, 100, 40],
                       "bubble_bbox": [55, 125, 110, 50],
                       "polygon": [[60, 130], [160, 130], [160, 170], [60, 170]],
                       "confidence": 0.9}]
        st.detected = True
    return p


# ------------------------------------------------------ one lock per page

def test_a_page_has_its_own_lock():
    assert editor._page_lock(3) is editor._page_lock(3)
    assert editor._page_lock(3) is not editor._page_lock(4)


def test_two_different_pages_do_not_wait_on_each_other(tmp_path):
    """The whole point. A page held up in `clean_page` used to hold every other
    page's build with it, because they all shared one lock."""
    p = _project(str(tmp_path / "out"))
    held = threading.Event()
    let_go = threading.Event()

    def sit_on_page_0():
        with editor._page_lock(0):
            held.set()
            let_go.wait(5)

    t = threading.Thread(target=sit_on_page_0, daemon=True)
    t.start()
    assert held.wait(2)
    try:
        start = time.time()
        editor.render_index(p, 1, "original")
        took = time.time() - start
    finally:
        let_go.set()
        t.join(5)
    assert took < 2.0, f"page 1 waited {took:.1f}s for page 0"


def test_the_same_page_still_takes_turns(tmp_path):
    """Two builds of one page overlapping is what the lock is for: building
    materialises the page, writes layouts back and mutates the project."""
    p = _project(str(tmp_path / "out"))
    held = threading.Event()
    let_go = threading.Event()

    def sit_on_page_0():
        with editor._page_lock(0):
            held.set()
            let_go.wait(4)

    t = threading.Thread(target=sit_on_page_0, daemon=True)
    t.start()
    assert held.wait(2)
    done = threading.Event()

    def build():
        editor.render_index(p, 0, "original")
        done.set()

    b = threading.Thread(target=build, daemon=True)
    b.start()
    try:
        assert not done.wait(0.7), "it built the page anyway, mid-build"
    finally:
        let_go.set()
        t.join(4)
    assert done.wait(6), "and it never finished once the way was clear"


def test_the_wait_on_the_cleaner_is_not_three_minutes():
    """Long enough for a real page, short enough that a cleaner which has gone
    quiet does not read as the app being dead."""
    assert 30 <= editor.CLEAN_TIMEOUT <= 120, editor.CLEAN_TIMEOUT
    src = (editor.__file__.replace(".pyc", ".py"))
    with open(src, encoding="utf8") as fh:
        text = fh.read()
    assert "timeout=CLEAN_TIMEOUT" in text
    assert "timeout=180" not in text


def test_a_page_is_only_loaded_once_however_many_ask_for_it(tmp_path):
    """Two pages can now be built at the same time, so this cache is reached
    from more than one thread — and decoding a scan is the expensive thing in
    the whole editor. Unguarded, every thread that misses decodes its own copy
    and then they overwrite each other.

    Slowed deliberately, because that is what a real 3000px scan is."""
    from mangatl import project as P
    p = _project(str(tmp_path / "out"), pages=3)
    p._img_cache.clear()
    loads = []
    real = P.load_page

    def slow(path):
        loads.append(path)
        time.sleep(0.4)
        return real(path)

    P.load_page = slow
    try:
        got = []
        ts = [threading.Thread(target=lambda: got.append(p.image(0)))
              for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
    finally:
        P.load_page = real
    assert len(loads) == 1, f"decoded the same page {len(loads)} times"
    assert len(got) == 6
    assert all(g is got[0] for g in got), "six different copies of one page"


# --------------------------------------------- and a client that went away

def _serve(fn, root=scratch("_tmp_gone")):
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


def test_a_client_that_hangs_up_is_not_an_error(capfd):
    """Send a request and close the socket before reading the answer — a
    browser does this whenever a page reloads or a fetch is superseded. The
    server must not print a traceback, and must not then try to write a 500
    down the same dead socket."""
    import socket

    def check(p, port):
        body = json.dumps({"kind": "narration"}).encode()
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(b"POST /api/page/0/region/1 HTTP/1.1\r\n"
                  b"Host: localhost\r\n"
                  b"Content-Type: application/json\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                  b"\r\n" + body)
        s.close()                     # gone before the answer is written
        time.sleep(0.8)
        # ...and the editor still answers the next one
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/page/0", timeout=10) as r:
            assert json.loads(r.read())["regions"]
    _serve(check)
    err = capfd.readouterr().err
    assert "ConnectionAborted" not in err, err
    assert "Traceback" not in err, err


def test_the_editor_carries_on_afterwards():
    """A dropped connection must not take the whole handler thread out."""
    import socket
    import urllib.request

    def check(p, port):
        for _ in range(5):
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(b"GET /api/project HTTP/1.1\r\nHost: x\r\n\r\n")
            s.close()
        time.sleep(0.5)
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/project", timeout=10) as r:
            assert json.loads(r.read())["pages"]
    _serve(check)
