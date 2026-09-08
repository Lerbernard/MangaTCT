# -*- coding: utf-8 -*-
"""A cache must not be able to outlive the fix that made it wrong.

lee, with an export beside its preview: *"so teh export preview is wrong in
some places"* - the preview showing captions clipped mid-word and no SPLAAASH
on the page at all, the real export correct.

## What happened

On 2026-08-29 the rendered pages started being kept on disk, so that a restart
would not rebuild the chapter one three-second page at a time. The key is
`_render_stamp`: the words, the boxes, the plate, the typesetting settings -
every INPUT to the picture.

Not the code that turns those inputs into pixels. That had never needed to be
in it, because until the pictures lived on disk a restart threw them all away
and a new build always drew its own. Keeping them removed that guarantee
silently: every page drawn by Friday's build was still on disk on Saturday,
still matched every input, and was served in preference to drawing it again.
The fixes shipped in between could not be seen on any page that had already
been looked at.

Two holes, and they are the same hole seen from either end:

* **`RENDER_ALGO`** - the build is part of the picture's identity, exactly as
  `inpaint.ALGO` is part of a plate's. Bumped when a change would draw an
  existing page differently.
* **`_invalidate_renders`** - and here the first fix overreached, and was
  taken back the same day. For one morning it also deleted the disk copies,
  on the reasoning that a picture declared wrong had to go from everywhere.
  But every one of its fifteen call sites changes something the STAMP
  already reads, so the old files were unreachable by key the moment the
  change landed - and deleting them turned every small bump into a chapter
  rebuild. Hiding one heal stroke cost lee 45 finished pages, remade in
  front of him at seconds each. The lever moves the epoch and clears
  memory; the disk keeps what it has, because a picture nothing can ask
  for hurts nobody.

`RENDER_ALGO` is why the glow appeared to break twice: a size you go back to
is a stamp you have been to before, and the picture filed under it was drawn
by whatever build was running the first time.

## And the bar that was counting the wrong job

`warm_pages` does two sweeps - plates for the whole chapter, then the finished
pages - and `total` was the plates alone. The bar reached "23 of 23" at the end
of the first sweep and sat there, full, for the whole of the second, which is
the long one. Both sweeps are the job, so both are counted.

Its poll had the matching fault: three of its four exits returned without
booking another look, so the loop died on the first blip and left its last
sentence on screen for the session. Asking again is the default now.
"""
import os
import shutil
import time

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")


def _project(root, pages=1):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for n in range(pages):
        img = np.full((300, 240, 3), 246, np.uint8)
        cv2.rectangle(img, (30, 40), (200, 150), (0, 0, 0), 2)
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
    editor._render_cache.clear()
    editor._plate_cache.clear()
    editor._page_cache.clear()


# ------------------------------------------------- the build is in the key

def test_a_new_build_does_not_serve_the_old_builds_picture():
    """The one lee photographed. Same words, same boxes, same plate, and a
    different typesetter - so a different picture, and the one on disk is not
    it."""
    from mangatl import editor
    root = scratch("_tmp_algo_new")
    try:
        p = _project(root)
        editor.do_typeset(p, 0)
        was = editor.render_index(p, 0, "typeset", commit=False)
        assert was

        old = editor.RENDER_ALGO
        try:
            editor.RENDER_ALGO = old + "-plus-a-fix"
            _cold(editor)                   # memory gone, disk still full
            now = editor.render_index(p, 0, "typeset", commit=False)
        finally:
            editor.RENDER_ALGO = old
        assert now, "the new build drew nothing"
        d = os.path.join(root, "render_cache")
        assert len(os.listdir(d)) >= 2, (
            "the new build wrote its picture over the old build's, so going "
            "back is the same hole in the other direction")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_build_is_in_the_stamp():
    from mangatl import editor
    root = scratch("_tmp_algo_stamp")
    try:
        p = _project(root)
        was = editor._render_stamp(p, 0, "typeset")
        old = editor.RENDER_ALGO
        try:
            editor.RENDER_ALGO = old + "-x"
            now = editor._render_stamp(p, 0, "typeset")
        finally:
            editor.RENDER_ALGO = old
        assert was != now
        # ...and on the plate view too. A renderer fix is a different picture
        # whichever of the three the person is looking at.
        old = editor.RENDER_ALGO
        try:
            plate = editor._render_stamp(p, 0, "clean")
            editor.RENDER_ALGO = old + "-x"
            assert editor._render_stamp(p, 0, "clean") != plate
        finally:
            editor.RENDER_ALGO = old
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_same_build_still_reads_the_disk():
    """The guard on the guard. `RENDER_ALGO` must retire other builds' work
    and nothing else, or the disk cache it sits in front of is pointless."""
    from mangatl import editor
    root = scratch("_tmp_algo_same")
    try:
        p = _project(root)
        editor.do_typeset(p, 0)
        t0 = time.time()
        first = editor.render_index(p, 0, "typeset", commit=False)
        built = time.time() - t0
        _cold(editor)
        t0 = time.time()
        again = editor.render_index(p, 0, "typeset", commit=False)
        read = time.time() - t0
        assert again == first
        assert read < max(0.05, built / 4.0), (
            "%.0f ms to build, %.0f ms to read" % (built * 1000, read * 1000))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------- the lever does NOT reach the disk

def test_throwing_the_pictures_away_leaves_the_disk_alone():
    """`_invalidate_renders` moves the epoch and clears memory - and for one
    morning it also deleted every finished page on disk. Every one of its
    call sites changes something the stamp already reads, so the old files
    were already unreachable BY KEY; deleting them just turned every small
    bump into a chapter rebuild. Hiding one heal stroke cost 45 pages,
    remade in front of lee at seconds each: *"this disnt happen before and
    its not fast it redoing it again"*."""
    from mangatl import editor
    root = scratch("_tmp_inval_disk")
    try:
        p = _project(root)
        editor.do_typeset(p, 0)
        first = editor.render_index(p, 0, "typeset", commit=False)
        d = os.path.join(root, "render_cache")
        had = sorted(os.listdir(d))
        assert had, "nothing was kept, so this proves nothing"

        editor._invalidate_renders()
        assert sorted(os.listdir(d)) == had, \
            "the disk was purged - one hidden heal stroke costs the chapter"
        _cold(editor)
        t0 = time.time()
        again = editor.render_index(p, 0, "typeset", commit=False)
        assert again == first
        assert time.time() - t0 < 0.4, \
            "the picture was rebuilt though nothing about the page changed"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_change_retires_a_picture_by_its_key_not_by_deletion():
    """The half that makes the one above safe: every change routes through
    the STAMP, so the old file is unreachable, not served."""
    from mangatl import editor
    root = scratch("_tmp_inval_key")
    try:
        p = _project(root)
        editor.do_typeset(p, 0)
        was = editor.render_index(p, 0, "typeset", commit=False)
        p.pages[0].regions[0]["dst_text"] = "SOMETHING ELSE ENTIRELY"
        p.pages[0].regions[0].pop("layout", None)
        _cold(editor)
        now = editor.render_index(p, 0, "typeset", commit=False)
        assert now != was, "the words changed and the picture did not"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------- the bar counts the job

def test_the_warm_up_counts_both_of_its_sweeps():
    """It builds the plates and then the finished pages. Counting the plates
    alone is what left lee looking at a full bar for a minute and a half."""
    from mangatl import editor
    root = scratch("_tmp_warm_total")
    try:
        p = _project(root, pages=3)
        for i in range(3):
            editor.do_typeset(p, i)
        editor.warm_pages(p, 0)
        for _ in range(600):
            if not editor._warm.get("running"):
                break
            time.sleep(0.05)
        assert not editor._warm.get("running"), "the warm-up never finished"
        assert editor._warm["total"] > 3, (
            "the second sweep is not in the total, so the bar sits at 100%% "
            "for the whole of it: %r" % (dict(editor._warm),))
        assert editor._warm["done"] == editor._warm["total"], \
            "it finished without reaching its own total: %r" % (
                dict(editor._warm),)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_warm_up_stands_aside_for_somebody_turning_pages():
    """lee: *"when i swtitch too fast it not just lages and pauses for a
    while"*. It already yields to a real job; a person is not a job."""
    from mangatl import editor
    root = scratch("_tmp_warm_yield")
    try:
        p = _project(root, pages=2)
        editor._warm["gen"] += 1
        mine = editor._warm["gen"]
        with editor._someone_is_looking():
            t0 = time.time()
            done = []

            import threading
            th = threading.Thread(
                target=lambda: done.append(editor._wait_for_the_person(mine)))
            th.start()
            time.sleep(0.35)
            assert not done, "the warm-up carried on while a page was in flight"
        th.join(timeout=5)
        assert done and done[0] is True, "it never came back"
        assert time.time() - t0 < 5
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_standing_aside_is_capped():
    """A browser that goes away mid-download must not stop the chapter being
    built for the rest of the session."""
    from mangatl import editor
    src = open(editor.__file__, encoding="utf-8").read()
    fn = src.split("def _wait_for_the_person")[1].split("\ndef ")[0]
    assert "range(" in fn, "an uncapped wait is a warm-up somebody can wedge"


# ----------------------------------------------------------- the bar's loop

def test_the_warm_poll_always_books_another_look():
    """Three of four exits used to return without one, so the loop died on the
    first blip and left its last sentence on screen."""
    src = open(_js_path(), encoding="utf-8").read()
    fn = src.split("async function pollWarm")[1].split("\n/*")[0]
    # the fetch failed, the strip is busy, and the warm-up has finished
    assert fn.count("again(") >= 4, fn
    assert "catch(e){ again(" in fn, \
        "a failed fetch still ends the loop for the session"


def _js_path():
    import mangatl
    return os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                        "static", "js", "pipeline.js")


def test_the_switch_says_export_preview():
    """lee: *"also cahnge the exact button to say export preview"*. "Exact"
    named the mechanism; this names what you get."""
    import mangatl
    html = os.path.join(os.path.dirname(os.path.abspath(mangatl.__file__)),
                        "static", "editor.html")
    src = open(html, encoding="utf-8").read()
    assert "<span>Export preview</span>" in src
    assert "<span>Exact</span>" not in src
