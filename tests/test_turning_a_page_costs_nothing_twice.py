# -*- coding: utf-8 -*-
"""Turning to a page you have already seen must be free.

lee: *"i wan t you to try to have teh switching pages, the clenned and tyeset
pages make it seemless and fast right now when i swithc only some section of
teh page show up and i take sa while to get teh rest to show up and some ting
it takes time for the typset text to show up. find a way to have it switch as
afsts at teh pages with teh boxes"*.

The Translation view is instant because it serves the scan off disk. The other
two views serve a picture that has to be BUILT, and measured on lee's chapter:

    materialize        ~110 ms
    the plate, decoded ~180 ms   (a 840KB PNG)
    typeset_page      ~2570 ms   ← every block laid out again, from scratch
    render_page        ~300 ms
    jpeg               ~6 ms

Three seconds for a finished page. There are three reasons it was being paid
more than once, and this file is one part per reason.

## 1. Reading the cache changed the key of what was in it

`_render_stamp` learnt about the plate on 2026-08-29 - it had to, or a re-clean
left the old picture on screen (`the-picture-and-the-plate-2026-08-29`). It
learnt about it by the plate's FILE TIME, and `clean_page` touched that file on
every reuse so the pruner could tell a live plate from an abandoned one.

So looking at a page changed the identity of the picture of that page. It was
rebuilt on the next visit, the browser's `v=` moved with it and the download
happened again, and the copy on disk could never be read back at all.

**A cache key must not be changed by reading the cache.** The touch is gone.

## 2. Nothing survived a restart

Rendered pages lived in memory. A restart threw the chapter away and it was
built again one three-second page at a time, in front of whoever turned to it.
They are kept on disk now, beside the plates, under the same stamp - so a file
there can only be read by a request that would have built exactly it.

## 3. The finished page was not warmed

The warm-up built plates only, on the reasoning that nothing read the finished
page. The Image view reads it now (`exactview.js`), so it is warmed too - in a
second sweep, after every plate, so the thing being waited for finishes first.

Measured on lee's 23 pages, end to end: 12.9s to build the chapter cold, 18ms
to walk it again, **27ms to walk it after a restart**, and not one of the 23
browser keys moved between the three walks.
"""
import os
import shutil
import time

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")


def _project(root, pages=3):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for n in range(pages):
        img = np.full((300, 240, 3), 246, np.uint8)
        cv2.rectangle(img, (30, 40), (200, 150), (0, 0, 0), 2)
        cv2.putText(img, "%d" % n, (20, 280), cv2.FONT_HERSHEY_SIMPLEX, 1,
                    (0, 0, 0), 2)
        p.add_uploaded("p%d.png" % n, cv2.imencode(".png", img)[1].tobytes())
        p.pages[n].regions = [{
            "id": 1, "kind": "bubble", "order": 0, "bbox": [40, 50, 150, 90],
            "bubble_bbox": [32, 42, 166, 106],
            "polygon": [[40, 50], [190, 50], [190, 140], [40, 140]],
            "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9}]
        p.pages[n].detected = True
        p.pages[n].cleaned = True
    return p


def _cold(editor):
    """Everything the process is holding in memory, forgotten - as if the app
    had just been started."""
    editor._render_cache.clear()
    editor._plate_cache.clear()
    editor._page_cache.clear()


# ------------------------------------------------- the key stops moving

def test_looking_at_a_page_does_not_change_what_it_is():
    """The one-line version of the whole file. Build the picture, look at it
    four times, and the browser's key must be the same key each time - it is
    what decides whether the page is downloaded again."""
    from mangatl import editor
    root = scratch("_tmp_turn_key")
    try:
        p = _project(root, pages=1)
        editor.do_typeset(p, 0)
        keys = []
        for _ in range(4):
            editor.render_index(p, 0, "clean", paint=False)
            editor.render_index(p, 0, "typeset", commit=False)
            keys.append((editor._render_key(p, 0),
                         editor._render_key(p, 0, "typeset")))
        assert len(set(keys)) == 1, ("the page's identity moved while nobody "
                                     "changed it: %r" % (keys,))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_plate_is_not_touched_when_it_is_read():
    """...and this is why. The plate's file time is part of that key, so
    marking it as recently-used throws away every picture built from it."""
    from mangatl import editor
    root = scratch("_tmp_turn_touch")
    try:
        p = _project(root, pages=1)
        editor.render_index(p, 0, "clean", paint=False)
        fp = editor._plate_disk_path(p, 0)
        if not os.path.exists(fp):
            pytest.skip("this fixture cleaned without writing a plate")
        was = os.path.getmtime(fp)
        _cold(editor)
        time.sleep(0.02)
        editor.render_index(p, 0, "clean", paint=False)   # reads it off disk
        assert os.path.getmtime(fp) == was, \
            "reading the plate moved its time, and so its picture's key"
        src = open(editor.__file__, encoding="utf-8").read()
        assert "os.utime(fp, None)          # touch: it is still in use" not in src
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------- and the second time is free

def test_the_second_look_is_off_the_disk_and_not_rebuilt():
    """The measurement that matters: a restart must not cost the chapter
    again. Timed rather than counted, because "did it rebuild" is exactly the
    question a person is asking when they click Next."""
    from mangatl import editor
    root = scratch("_tmp_turn_disk")
    try:
        p = _project(root, pages=1)
        editor.do_typeset(p, 0)
        t0 = time.time()
        first = editor.render_index(p, 0, "typeset", commit=False)
        built = time.time() - t0
        assert first

        _cold(editor)                       # the app has been restarted
        t0 = time.time()
        again = editor.render_index(p, 0, "typeset", commit=False)
        read = time.time() - t0

        assert again == first, "the picture off the disk is a different picture"
        assert read < max(0.05, built / 4.0), (
            "the finished page was built again after a restart: "
            "%.0f ms to build, %.0f ms to read" % (built * 1000, read * 1000))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_pictures_are_kept_where_the_plates_are():
    from mangatl import editor
    root = scratch("_tmp_turn_where")
    try:
        p = _project(root, pages=1)
        editor.render_index(p, 0, "clean", paint=False)
        d = os.path.join(root, "render_cache")
        assert os.path.isdir(d) and os.listdir(d), \
            "nothing was kept, so every restart pays for the chapter again"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_page_that_changed_is_built_again():
    """The guard on all of it. A cache that never misses is a page that never
    updates - which is the bug the plate went into the key to fix."""
    from mangatl import editor
    root = scratch("_tmp_turn_moved")
    try:
        p = _project(root, pages=1)
        editor.do_typeset(p, 0)
        was = editor.render_index(p, 0, "typeset", commit=False)
        p.pages[0].regions[0]["dst_text"] = "SOMETHING ELSE ENTIRELY"
        p.pages[0].regions[0].pop("layout", None)
        _cold(editor)
        now = editor.render_index(p, 0, "typeset", commit=False)
        assert now != was, "the words changed and the picture did not"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_walking_the_chapter_twice_costs_almost_nothing_the_second_time():
    """End to end, the way it is used: turn through every page, then turn
    through them again."""
    from mangatl import editor
    root = scratch("_tmp_turn_walk")
    try:
        p = _project(root, pages=3)
        for i in range(3):
            editor.do_typeset(p, i)

        def walk():
            t0 = time.time()
            for i in range(3):
                editor.render_index(p, i, "clean", paint=False)
                editor.render_index(p, i, "typeset", commit=False)
            return time.time() - t0

        cold = walk()
        _cold(editor)
        again = walk()
        assert again < max(0.15, cold / 4.0), (
            "turning through the chapter again cost %.0f ms against %.0f ms "
            "the first time" % (again * 1000, cold * 1000))
    finally:
        shutil.rmtree(root, ignore_errors=True)
