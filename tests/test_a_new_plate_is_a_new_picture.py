"""Cleaning a page a second time has to change the picture the page shows.

lee, with page 009 open and its balloon still full of Japanese: *"the clenner
is working but teh page is not showing it, i even tried to re clean, but teh
text is still at the boittom left after typesetting again"*.

He was right about both halves. The plate on his disk was CLEAN - the balloon
solid black, the Japanese gone, written eleven minutes before he said it. What
he was looking at was a picture built from the plate before that one.

## The key knew a boolean, not a plate

`_render_stamp` is the identity of a rendered page: the server's cache is kept
under it and the browser hangs a hash of it on the image URL, so a page whose
stamp has not moved is answered from one cache or the other without being
built. Everything that can change the picture is supposed to be in it, and the
only thing in it about cleaning was `bool(st.cleaned)`.

That flag goes false to true ONCE, the first time a page is cleaned. Clean the
same page again and it is already true, so the stamp does not move, so both
caches answer with the picture made from the plate that has just been thrown
away. There is no way out of it from the browser either, because the URL is
the same URL.

Page 009 is the case that makes it bite hardest. It was cleaned a week ago by
a build whose cleaner read a black balloon inside out - it erased the balloon
and kept the writing. This build retires that plate (`inpaint.ALGO` is part of
a plate's identity) and builds a good one on the next Clean. The plate changed
completely. The picture could not.

## What the fix says

The picture is made from the plate, so the plate's identity is part of the
picture's identity. The plate's file time answers for its contents: it moves
whenever a plate is written for any reason - a re-clean, a bumped `ALGO`, a
moved box, a different eraser - and a plate nothing rebuilt keeps its time,
so a page that has not changed still costs nothing to look at again.

Deliberately not `_invalidate_renders()`, which is the other way to do this: a
plate is stored per page and that would throw away every OTHER page in the
chapter each time one was cleaned, which is exactly the "flick between pages
instantly" that `_render_key` was written to buy.
"""
import os
import shutil

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 240, 3), 246, np.uint8)
    cv2.rectangle(img, (30, 40), (200, 150), (0, 0, 0), 2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [40, 50, 150, 90],
        "bubble_bbox": [32, 42, 166, 106],
        "polygon": [[40, 50], [190, 50], [190, 140], [40, 140]],
        "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


def _write_plate(p, i, value):
    """Put a plate on disk exactly where the page will look for it."""
    from mangatl import editor
    fp = editor._plate_disk_path(p, i)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    plate = np.full((p.pages[i].height, p.pages[i].width, 3), value, np.uint8)
    cv2.imwrite(fp, plate)
    return fp


# ------------------------------------------------------- the plate is in the key

def test_a_page_cleaned_again_is_a_different_picture():
    """The bug, stated at the level it lived at. Both plates are this page's,
    both leave `cleaned` true, and they are not the same picture."""
    from mangatl import editor
    root = scratch("_tmp_plate_key")
    try:
        p = _project(root)
        _write_plate(p, 0, 200)
        was = editor._render_stamp(p, 0, "clean")
        waskey = editor._render_key(p, 0)
        assert p.pages[0].cleaned, "the fixture must be an already-cleaned page"

        fp = _write_plate(p, 0, 120)
        os.utime(fp, (1_000_000_000, 1_000_000_000))   # a plate from later
        assert editor._render_stamp(p, 0, "clean") != was, \
            "a re-cleaned page kept the identity of its old picture"
        assert editor._render_key(p, 0) != waskey, \
            "...and the browser was never told to fetch the new one"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_typeset_view_moves_with_it_too():
    """The typeset view is the plate with the English on top, so it is made of
    the plate as surely as the clean view is."""
    from mangatl import editor
    root = scratch("_tmp_plate_key_ts")
    try:
        p = _project(root)
        _write_plate(p, 0, 200)
        was = editor._render_stamp(p, 0, "typeset")
        fp = _write_plate(p, 0, 120)
        os.utime(fp, (1_000_000_000, 1_000_000_000))
        assert editor._render_stamp(p, 0, "typeset") != was
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_plate_that_has_not_moved_costs_nothing():
    """The guard on the fix. A key that changes when nothing has is the slow
    page `_render_key` exists to stop: it would re-render and re-download
    every view."""
    from mangatl import editor
    root = scratch("_tmp_plate_key_still")
    try:
        p = _project(root)
        fp = _write_plate(p, 0, 200)
        os.utime(fp, (1_000_000_000, 1_000_000_000))
        keys = [editor._render_key(p, 0) for _ in range(5)]
        assert len(set(keys)) == 1, keys
        # ...and reading the plate back does not count as writing one.
        assert cv2.imread(fp) is not None
        assert editor._render_key(p, 0) == keys[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_page_with_no_plate_at_all_still_has_a_key():
    """Nothing on disk is a perfectly ordinary state - a page nobody has
    cleaned, and a page whose plate has just been retired by a new build. Both
    have to render, and the one that then gets a plate has to change."""
    from mangatl import editor
    root = scratch("_tmp_plate_key_none")
    try:
        p = _project(root)
        p.pages[0].cleaned = False
        bare = editor._render_key(p, 0)
        assert bare
        p.pages[0].cleaned = True
        fp = _write_plate(p, 0, 200)
        os.utime(fp, (1_000_000_000, 1_000_000_000))
        assert editor._render_key(p, 0) != bare
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------- and it is the whole chapter's

def test_cleaning_one_page_does_not_throw_away_another():
    """Why this is in the stamp and not a call to `_invalidate_renders()`.
    Paging back and forth through a cleaned chapter is meant to be instant,
    and the epoch is chapter-wide."""
    from mangatl import editor
    root = scratch("_tmp_plate_key_others")
    try:
        p = _project(root)
        img = np.full((300, 240, 3), 240, np.uint8)
        p.add_uploaded("p1.png", cv2.imencode(".png", img)[1].tobytes())
        p.pages[1].regions = list(p.pages[0].regions)
        p.pages[1].detected = True
        p.pages[1].cleaned = True
        other = editor._render_key(p, 1)
        fp = _write_plate(p, 0, 120)
        os.utime(fp, (1_000_000_000, 1_000_000_000))
        assert editor._render_key(p, 1) == other, \
            "cleaning page 1 changed page 2's picture"
    finally:
        shutil.rmtree(root, ignore_errors=True)
