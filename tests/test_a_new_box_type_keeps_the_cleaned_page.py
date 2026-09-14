"""A page that was cleaned stays cleaned when its boxes change.

lee, after turning boxes from Free text to Bubble (and SFX to Free text) by hand
on thirteen pages of a chapter he had just cleaned: *"also some of teh clena
pages are not shwoing up"*. Page 025 came back with every word of its Japanese
under the English, and the Clean step still said 27/27.

## Why

A cleaned plate is kept on disk under its stamp (`_plate_stamp`), and the
stamp carries every box's position and FAMILY - rightly, because the cleaner
fences a balloon differently from free text. Change a box's family and the page
asks for a plate that was never made. With the hosted cleaner on, nothing but
Clean may make one, so the view got the bare scan. The plate he had paid for
that morning was still in `plate_cache`, under the name the old boxes gave it.

He had already said what a cleaned page should do when what it was cleaned from
moves on: *"keep existing cleaned pages until you re-clean them yourself"*.

## What the fix says

Every plate written is remembered against its page (`plate_last.json`, keyed
on the page's contents). A page that cannot be cleaned right now shows the last
plate it had. Pressing Clean still cleans it properly, and the old plate is
never passed off as the new stamp's own, so the Clean step is not fooled.
"""
import json
import os
import shutil

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

SCAN = 246


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 240, 3), SCAN, np.uint8)
    cv2.rectangle(img, (30, 40), (200, 150), (0, 0, 0), 2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "freefloat", "order": 0, "bbox": [40, 50, 150, 90],
        "bubble_bbox": [32, 42, 166, 106],
        "polygon": [[40, 50], [190, 50], [190, 140], [40, 140]],
        "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


@pytest.fixture()
def hosted(monkeypatch):
    """The hosted cleaner switched on, and no Clean running: the state in which
    a page view may not make a plate."""
    from mangatl import editor
    monkeypatch.setattr(editor, "_hosted_cleaning", lambda p: True)
    monkeypatch.setattr(editor._MAY_CLEAN, "on", False, raising=False)
    editor._plate_cache.clear()
    yield editor
    editor._plate_cache.clear()


def _plate(p, value):
    return np.full((p.pages[0].height, p.pages[0].width, 3), value, np.uint8)


def _shown(editor, p):
    """What the page is drawn from, as one grey level."""
    editor._plate_cache.clear()
    page = p.materialize(0)
    editor.clean_page(p, 0, page, include_paint=False)
    return int(np.median(page.clean_plate))


def _change_the_type_by_hand(p):
    p.pages[0].regions[0]["kind"] = "bubble"
    p.pages[0].regions[0]["kind_by_hand"] = True


def test_the_fixture_shows_its_plate_before_anything_changes(hosted):
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_0")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        assert _shown(editor, p) == 200
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_box_given_another_family_keeps_the_page_cleaned(hosted):
    """The bug. The stamp moves, the plate is still there, and the page must
    not go back to the scan."""
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_1")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        was = editor._plate_disk_path(p, 0)
        _change_the_type_by_hand(p)
        assert editor._plate_disk_path(p, 0) != was, \
            "the fixture has to move the stamp, or it tests nothing"
        assert _shown(editor, p) == 200, "the page went back to the scan"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_old_plate_is_not_passed_off_as_the_new_ones(hosted):
    """Shown, not adopted. Written under the new name or held in memory under
    the new stamp, a Clean step that skips pages it thinks are done would take
    it for this page's plate and never clean the new boxes."""
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_2")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        _change_the_type_by_hand(p)
        _shown(editor, p)
        assert not os.path.exists(editor._plate_disk_path(p, 0))
        assert editor._plate_stamp(p, 0) not in editor._plate_cache
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cleaning_it_again_shows_the_new_plate(hosted):
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_3")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        _change_the_type_by_hand(p)
        editor._store_plate(p, 0, _plate(p, 120))       # what Clean does
        assert _shown(editor, p) == 120
        assert editor.last_plate_path(p, 0) == editor._plate_disk_path(p, 0)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_page_never_cleaned_is_still_the_scan(hosted):
    """The honest picture of a page nothing was erased from is unchanged."""
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_4")
    try:
        p = _project(root)
        assert _shown(editor, p) == SCAN
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_remembered_plate_that_is_gone_is_the_scan_and_not_an_error(hosted):
    """The pruner deletes plates by count. The list outlives them."""
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_5")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        gone = editor._plate_disk_path(p, 0)
        _change_the_type_by_hand(p)
        os.remove(gone)
        assert editor.last_plate_path(p, 0) == ""
        assert _shown(editor, p) == SCAN
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_picture_key_moves_when_the_last_plate_is_what_is_shown(hosted):
    """The rendered page is cached on disk under `_render_stamp`. A picture
    built from the scan before the list existed must not answer for the page
    once the last plate is shown instead."""
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_6")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        _change_the_type_by_hand(p)
        with_last = editor._render_stamp(p, 0, "clean")
        os.remove(editor._last_plates_file(p))
        assert editor._render_stamp(p, 0, "clean") != with_last
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_list_is_kept_out_of_the_folder_the_pruner_empties(hosted):
    editor = hosted
    root = scratch("_tmp_type_keeps_plate_7")
    try:
        p = _project(root)
        editor._store_plate(p, 0, _plate(p, 200))
        listed = editor._last_plates_file(p)
        assert os.path.dirname(listed) != os.path.dirname(
            editor._plate_disk_path(p, 0))
        with open(listed, encoding="utf-8") as fh:
            got = json.load(fh)
        assert got == {editor._page_fingerprint(p, 0):
                       os.path.basename(editor._plate_disk_path(p, 0))}
    finally:
        shutil.rmtree(root, ignore_errors=True)
