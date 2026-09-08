"""Why turning a page of a cleaned chapter was slow, and it was not the work.

lee: *"also figure out a way to have the cleaned pages switch fataer for one
page to another"*.

The obvious answer is a bigger cache, and it would have been the wrong one.
There are two caches on this path and both were working. What was broken was
the KEY they were looked up by: it changed on every other view of a page that
had not changed at all.

## The loop

`clean_route` is the cleaner's report - how each box was erased, "flat fill",
"model", "fell back". `inpaint_page` writes it, and `inpaint_page` only runs
when a plate is actually built. Look at a cleaned page again and the plate
comes off the disk instead, so the freshly materialised regions carry no
report - and committing the page wrote that emptiness over the real one.

The next view finds an empty `clean_route`, cleans nothing (the plate is still
on disk), and the commit... leaves it empty. But the view AFTER a real clean
puts it back. So the record alternates, and `_render_stamp` reads every region
record. Two consequences, and it is the second one that lee felt:

  1. `_render_cache` is keyed on that stamp, so every other look at a page
     rebuilt a picture that was already in memory.
  2. `_render_key` - the `v=` the browser hangs on the image URL, which is
     what lets it answer from its own cache - is a hash of the SAME stamp. So
     every other look also re-downloaded the image.

A page that had been cleaned, typeset and looked at twice was rebuilt and
re-sent the third time, and the fifth, and the seventh.

## The fix, in two halves

`_commit_keep_proofread` stops the report being thrown away - which is a bug
on its own account, and the reason `_keep_the_clean_report` exists at all.

`_NOT_A_PICTURE` keeps the report out of the key regardless. Both, because
they answer different questions: one is what a page KEEPS, the other is what a
PICTURE IS. A report about how a box was erased cannot change what the erased
box looks like, so it has no business in the identity of a picture.
"""
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


# ------------------------------------------------------- the key itself

def test_the_report_is_not_part_of_what_a_picture_is():
    from mangatl import editor
    for field in ("clean_route", "clean_core", "flagged"):
        assert field in editor._NOT_A_PICTURE, field
    # ...and the one that was always excluded is still excluded.
    assert "layout" in editor._NOT_A_PICTURE


def test_two_records_that_differ_only_in_the_report_are_the_same_picture():
    """Stated at the level the bug lived at, with no rendering involved: these
    two pages look identical, so they must key identically."""
    from mangatl import editor
    root = scratch("_tmp_key_report")
    try:
        p = _project(root)
        a = editor._render_stamp(p, 0, "clean")
        akey = editor._render_key(p, 0)
        p.pages[0].regions[0]["clean_route"] = "flat fill"
        p.pages[0].regions[0]["clean_core"] = True
        p.pages[0].regions[0]["flagged"] = "still readable"
        assert editor._render_stamp(p, 0, "clean") == a, \
            "the cleaner's report changed the identity of the picture"
        assert editor._render_key(p, 0) == akey, \
            "...and the browser was told to download it again"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_but_something_that_does_change_the_picture_still_changes_the_key():
    """The guard on the guard. A key that ignores too much is the "nothing
    vhanged" bug, which is worse than a slow page: it shows the old picture
    for ever."""
    from mangatl import editor
    root = scratch("_tmp_key_real")
    try:
        p = _project(root)
        a = editor._render_stamp(p, 0, "clean")
        p.pages[0].regions[0]["bbox"] = [40, 50, 151, 90]
        assert editor._render_stamp(p, 0, "clean") != a, "a moved box"
        p.pages[0].regions[0]["bbox"] = [40, 50, 150, 90]
        p.pages[0].regions[0]["kind"] = "freefloat"
        assert editor._render_stamp(p, 0, "clean") != a, "a family change"
        p.pages[0].regions[0]["kind"] = "bubble"
        p.pages[0].regions[0]["dst_text"] = "GOODBYE"
        assert editor._render_stamp(p, 0, "clean") != a, "different words"
        # ...and back to exactly where it started is the same picture again.
        p.pages[0].regions[0]["dst_text"] = "HELLO"
        assert editor._render_stamp(p, 0, "clean") == a
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- and it settles when rendered

def test_looking_at_the_same_page_again_does_not_rebuild_it():
    """The measurement, end to end. Before the fix this alternated for ever:
    hit, miss, hit, miss. Now it settles and stays settled."""
    from mangatl import editor
    root = scratch("_tmp_key_settles")
    try:
        p = _project(root)
        editor.render_index(p, 0, "clean", paint=False)     # cold
        editor.render_index(p, 0, "clean", paint=False)     # records settle
        keys = []
        for _ in range(6):
            keys.append(editor._render_key(p, 0))
            editor.render_index(p, 0, "clean", paint=False)
        assert len(set(keys)) == 1, \
            ("the page's identity changed while nothing about it did: %r"
             % (keys,))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_clean_report_survives_looking_at_the_page_again():
    """The other half, and a bug in its own right. `_keep_the_clean_report`
    exists because the report was never committed at all - measured on lee's
    chapter, `clean_route` was empty on all 134 regions with three boxes that
    had visibly kept their text. Committing an empty report over a real one
    puts it straight back."""
    from mangatl import editor
    root = scratch("_tmp_key_keeps")
    try:
        p = _project(root)
        p.pages[0].regions[0]["clean_route"] = "flat fill"
        p.pages[0].regions[0]["proofread"] = True
        page = p.materialize(0)
        editor._commit_keep_proofread(p, 0, page)
        assert p.pages[0].regions[0].get("clean_route") == "flat fill", \
            "a re-commit wiped the report of a clean that really happened"
        assert p.pages[0].regions[0].get("proofread") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_fresh_report_still_wins_over_the_kept_one():
    """Kept, not frozen. A page that really was just cleaned has the new
    report on it, and the new report is the true one."""
    from mangatl import editor
    root = scratch("_tmp_key_fresh")
    try:
        p = _project(root)
        p.pages[0].regions[0]["clean_route"] = "flat fill"
        page = p.materialize(0)
        page.regions[0].clean_route = "model"
        editor._commit_keep_proofread(p, 0, page)
        assert p.pages[0].regions[0].get("clean_route") == "model"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------- what the warm-up builds

def test_the_warm_up_builds_the_plate_first():
    """`frames.js:pageUrl` asks for `mode=clean&paint=0` even when the view on
    screen is the finished page - the browser draws the typesetting itself,
    over that plate. So the plate is what somebody clicking Next is waiting
    for, and nothing may get in front of it.

    THIS TEST USED TO SAY the finished page must not be warmed at all, and
    gave a good reason: nothing read it, so building it would be double the
    work to fill a cache nobody looked in. That stopped being true on
    2026-08-29, when the Image view learnt to settle into the exported page
    (`static/js/exactview.js`) - which costs three seconds a page to build and
    was building it in front of him.

    So the rule is now about ORDER rather than about absence: the plates for
    the whole chapter, and then the finished pages on whatever time is left.
    A second sweep, not one pass doing both, so a chapter of plates is never
    held up behind a chapter of typesetting."""
    import inspect
    from mangatl import editor
    from where import PKG
    src = inspect.getsource(editor.warm_pages)
    assert 'render_index(p, i, "clean", paint=False)' in src
    assert 'render_index(p, i, "typeset", commit=False)' in src, \
        "the finished page is read now and has to be warmed"
    assert (src.index('"clean", paint=False') < src.index('"typeset"')), \
        "the finished pages are being built before the plates"
    # ...and the warm-up is nobody's edit: it must not write layouts back.
    assert 'commit=False' in src, \
        "a background re-typeset overwrites whatever is being edited"
    js = (PKG / "static" / "js" / "frames.js").read_text(encoding="utf-8")
    assert "'clean'" in js and "&paint=0" in js, \
        "the browser stopped asking for the plate - re-check warm_pages"
