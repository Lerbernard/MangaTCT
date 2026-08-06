"""Small edits do not wait for the whole project to reach disk.

lee, on renumbering a box and on deleting one: *"it works but very slow"*.

Both of those go through `POST /api/page/<i>/region/<id>`, and so does every
arrow press, every kind change and every typesetting nudge — and every one of
them serialised the WHOLE project and wrote it out before the answer went back
to the browser. On a real chapter that is half a megabyte of JSON. Measured
here: **35ms per press** on a plain local disk, and a project folder that is
synced (OneDrive, Dropbox) or scanned pays a great deal more than that, because
every write wakes the sync client and the virus scanner.

Nothing about WHAT is saved changes. The same whole-project write happens, off
the request thread, and twenty presses in a row cost one write instead of
twenty. What the editor answers from is what is in memory, so nothing can be
read stale; the file is only for the next time the app starts.

Two things had to be true before that was safe:

* the write is **atomic** — a crash halfway through a direct write over
  `project.json` is not a lost edit, it is a lost chapter;
* the flag saying "there is something to write" is kept under its own small
  lock, so marking an edit never waits behind a write that is already running.
"""
import json
import os
import shutil
import threading
import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.project import Project
from scratch import scratch


@pytest.fixture
def proj(tmp_path):
    p = Project(None, str(tmp_path / "out"))
    img = np.full((120, 90, 3), 240, np.uint8)
    for k in range(3):
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
    yield p
    p.flush()


def _on_disk(p):
    with open(p.state_path, encoding="utf8") as fh:
        return json.load(fh)


# ------------------------------------------------------------ it gets there

def test_a_soon_save_lands(proj):
    proj.settings["marker"] = "one"
    proj.save_soon()
    end = time.time() + 4
    while time.time() < end:
        if _on_disk(proj)["settings"].get("marker") == "one":
            return
        time.sleep(0.05)
    pytest.fail("it never reached disk")


def test_flush_does_not_wait_for_the_timer(proj):
    proj.settings["marker"] = "two"
    proj.save_soon()
    proj.flush()
    assert _on_disk(proj)["settings"].get("marker") == "two"


def test_flush_with_nothing_pending_is_free(proj):
    proj.save()
    t = time.time()
    for _ in range(200):
        proj.flush()
    assert (time.time() - t) < 0.5, "flush wrote the file every time"


def test_the_last_word_wins(proj):
    """Twenty presses in a row are one write of the final state, not twenty
    writes of twenty states."""
    for k in range(20):
        proj.settings["marker"] = f"v{k}"
        proj.save_soon()
    proj.flush()
    assert _on_disk(proj)["settings"]["marker"] == "v19"


def test_an_edit_made_while_it_is_writing_is_not_swallowed(proj):
    """The flag is cleared BEFORE the state is taken, so an edit that arrives
    while the write is running marks it again and is written next time round.
    Cleared afterwards, that edit is silently dropped — the write it was racing
    did not contain it, and nothing says there is anything left to do.

    So: make an edit from another thread in the middle of a save, and then ask
    whether the project still knows it has something to write."""
    proj.settings["marker"] = "before"
    proj.save()

    real_state = Project._state
    landed = []

    def slow_state(self):
        out = real_state(self)
        if not landed:
            landed.append(True)
            t = threading.Thread(target=lambda: (
                self.settings.__setitem__("marker", "during"),
                self.save_soon()))
            t.start(); t.join(2)
        return out

    Project._state = slow_state
    try:
        proj.save()
    finally:
        Project._state = real_state
    assert proj._dirty, "the edit made during the write was forgotten"
    proj.flush()
    assert _on_disk(proj)["settings"]["marker"] == "during"


def test_it_says_the_same_thing_a_plain_save_would(proj):
    """`save_soon` is not a smaller save. It is the same one, later."""
    proj.settings["marker"] = "same"
    proj.pages[0].detected = True
    proj.save_soon()
    proj.flush()
    soon = _on_disk(proj)
    os.remove(proj.state_path)
    proj.save()
    assert _on_disk(proj) == soon


# --------------------------------------------------------------- atomically

def test_the_file_is_replaced_not_overwritten(proj):
    """A crash partway through a direct write leaves a truncated project.json,
    which is a whole chapter, not one edit.

    Measured by breaking the write halfway: whatever the save was doing when it
    died, `project.json` still has to be the last complete one."""
    proj.settings["marker"] = "good"
    proj.save()
    was = _on_disk(proj)

    real = open
    import builtins

    def half(path, *a, **k):
        fh = real(path, *a, **k)
        if os.path.basename(str(path)).startswith("project.json"):
            w = fh.write

            def torn(text):
                w(text[:len(text) // 2])       # ...and then the power goes
                raise OSError("disk full")
            fh.write = torn
        return fh

    proj.settings["marker"] = "half"
    builtins.open = half
    try:
        with pytest.raises(OSError):
            proj.save()
    finally:
        builtins.open = real
    assert _on_disk(proj) == was, "the old project was destroyed by a failed save"


def test_nothing_is_left_lying_about(proj):
    proj.save()
    assert not os.path.exists(proj.state_path + ".tmp")


def test_a_failed_save_is_tried_again(proj):
    """A background save that dies must not leave the edit unwritten for ever.

    The failure has to happen INSIDE the write, after the flag has been
    cleared — a save that falls over before it starts leaves the flag set and
    would be retried by accident. This is the case that needs the re-mark: the
    project has said "nothing to write", and then the write did not happen.
    """
    proj.settings["marker"] = "retry"
    proj.save()                                   # a clean file to start from
    proj.settings["marker"] = "after the fall"

    real = open
    import builtins
    tries = {"n": 0}

    def once(path, *a, **k):
        if str(path).endswith("project.json.tmp"):
            tries["n"] += 1
            if tries["n"] == 1:
                raise OSError("not this time")
        return real(path, *a, **k)

    builtins.open = once
    try:
        proj.save_soon()
        end = time.time() + 8
        while time.time() < end:
            if tries["n"] >= 2:
                break
            time.sleep(0.05)
    finally:
        builtins.open = real
    assert tries["n"] >= 2, f"gave up after {tries['n']} attempts"
    proj.flush()
    assert _on_disk(proj)["settings"]["marker"] == "after the fall"


# ------------------------------------------------------- and it is not slow

def test_marking_an_edit_never_waits_for_a_write(proj):
    """The flag has its own lock. Sharing the write's lock meant one press in
    every handful paid the full cost of the write it happened to land on — the
    exact stall this whole change is about, back once in a while instead of
    every time.

    So: hold the WRITE's lock, the way a save in progress does, and ask how
    long it takes to mark an edit."""
    held = threading.Event()
    let_go = threading.Event()

    def hog():
        with proj._save_lock:
            held.set()
            let_go.wait(4)

    t = threading.Thread(target=hog, daemon=True)
    t.start()
    assert held.wait(2)
    try:
        start = time.time()
        proj.save_soon()
        took = time.time() - start
    finally:
        let_go.set()
        t.join(4)
    assert took < 0.3, f"marking an edit waited {took:.2f}s for the write"


def test_one_writer_at_a_time(proj):
    """Fifty edits must not start fifty threads."""
    before = threading.active_count()
    for _ in range(50):
        proj.settings["marker"] = "x"
        proj.save_soon()
    assert threading.active_count() - before <= 1
    proj.flush()


# --------------------------------------------------------- through the editor

def _serve(fn, root=scratch("_tmp_slow")):
    from http.server import ThreadingHTTPServer
    import urllib.request
    from mangatl import editor
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((400, 300, 3), 245, np.uint8)
    for n in range(6):
        p.add_uploaded(f"p{n}.png", cv2.imencode(".png", img)[1].tobytes())
    for st in p.pages:
        st.regions = [{"id": k + 1, "kind": "bubble", "order": k,
                       "bbox": [20, 20 + k * 40, 60, 30],
                       "bubble_bbox": [18, 18 + k * 40, 66, 36],
                       "polygon": [[20, 20 + k * 40], [80, 20 + k * 40],
                                   [80, 50 + k * 40], [20, 50 + k * 40]],
                       "src_text": "テスト", "dst_text": "HELLO",
                       "confidence": 0.9} for k in range(6)]
        st.detected = True
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def call(method, path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    try:
        return fn(p, call)
    finally:
        p.flush()
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_renumbering_a_box_does_not_write_the_project_first():
    """The endpoint lee was pressing. It has to answer with the new order and
    leave the writing for afterwards."""
    def check(p, call):
        writes = {"n": 0}
        real = Project.save
        Project.save = lambda self: (writes.__setitem__("n", writes["n"] + 1),
                                     real(self))[1]
        try:
            j = call("POST", "/api/page/0/region/4", {"order": 0})
            assert [r["id"] for r in j["regions"]][0] == 4, j["regions"]
            assert writes["n"] == 0, "it wrote the project before answering"
        finally:
            Project.save = real
        # ...and it still gets there
        p.flush()
        got = _on_disk(p)["pages"][0]["regions"]
        assert next(r for r in got if r["id"] == 4)["order"] == 0
    _serve(check)


def test_deleting_a_box_does_not_write_the_project_first():
    def check(p, call):
        writes = {"n": 0}
        real = Project.save
        Project.save = lambda self: (writes.__setitem__("n", writes["n"] + 1),
                                     real(self))[1]
        try:
            j = call("DELETE", "/api/page/0/region/2")
            assert all(r["id"] != 2 for r in j["regions"]), j["regions"]
            assert writes["n"] == 0, "it wrote the project before answering"
        finally:
            Project.save = real
        p.flush()
        got = _on_disk(p)["pages"][0]["regions"]
        assert all(r["id"] != 2 for r in got)
    _serve(check)


def test_twenty_presses_are_one_write():
    """Holding an arrow down, or retyping a run of boxes."""
    def check(p, call):
        p.flush()
        writes = {"n": 0}
        real = Project.save
        Project.save = lambda self: (writes.__setitem__("n", writes["n"] + 1),
                                     real(self))[1]
        try:
            for k in range(20):
                call("POST", "/api/page/0/region/3",
                     {"kind": "bubble" if k % 2 else "narration"})
            p.flush()
        finally:
            Project.save = real
        assert writes["n"] <= 3, writes
    _serve(check)
