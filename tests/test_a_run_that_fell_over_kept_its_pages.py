"""Work already done survives the thing that stopped the run.

lee: *"sometime when i reload the page i lose some profreading or
tranaltiong look into that"*.

A run over a chapter did all its pages and then saved once, after the loop.
Two ways out of that loop skipped the save entirely:

* an exception — a rate limit on page 12, a reply the model mangled, a network
  blip — jumped straight past it to the `except`;
* and until it was found, every page before the failure lived in memory and
  nowhere else. The editor answers from memory, so the words were still on
  screen and everything looked fine. They were gone the next time the project
  was read off disk.

Twenty-three pages translated, a failure on the twelfth, and eleven pages of
translation never written down. That is the shape of "sometimes I lose some".

So: each page is written as it is finished — through `save_soon`, which
coalesces, so a chapter still costs about one write — and the run writes again
on the way out however it leaves, error or cancel or clean finish.
"""
import json
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from mangatl.project import Project


@pytest.fixture
def proj(tmp_path):
    p = Project(None, str(tmp_path / "out"))
    for i in range(5):
        p.add_uploaded("%03d.png" % (i + 1), cv2.imencode(
            ".png", np.full((60, 40, 3), 240, np.uint8))[1].tobytes())
    p.save()
    return p


def _on_disk(p):
    """The pages as the next run of the app would read them."""
    with open(p.state_path, encoding="utf-8") as fh:
        return json.load(fh)["pages"]


def _translated(pages):
    return [i for i, pg in enumerate(pages)
            if any((r.get("dst_text") or "") for r in pg["regions"])]


def _write(p, i):
    p.pages[i].regions = [{"id": 1, "bbox": [1, 1, 9, 9], "bubble_bbox": None,
                           "polygon": [], "kind": "bubble", "order": 0,
                           "src_text": "テスト", "dst_text": "PAGE %d" % i}]


def test_the_pages_done_before_the_failure_are_on_disk(proj):
    """The one that cost lee eleven pages."""
    def fn(i):
        if i == 3:
            raise RuntimeError("rate limited")
        _write(proj, i)

    editor._run_one(proj, {"label": "Translating", "indices": [0, 1, 2, 3, 4],
                           "fn": fn})
    assert proj.job["error"], "the failure is still reported"
    assert _translated(_on_disk(proj)) == [0, 1, 2], \
        "everything done before it went down has to be written"


def test_a_run_that_finishes_is_on_disk(proj):
    editor._run_one(proj, {"label": "Translating", "indices": [0, 1, 2],
                           "fn": lambda i: _write(proj, i)})
    assert not proj.job["error"]
    assert _translated(_on_disk(proj)) == [0, 1, 2]


def test_a_run_that_was_cancelled_keeps_what_it_had_done(proj):
    """Stopping a run is not undoing it."""
    def fn(i):
        _write(proj, i)
        if i == 1:
            proj.job["cancel"] = True      # asked to stop, between pages

    editor._run_one(proj, {"label": "Translating", "indices": [0, 1, 2, 3],
                           "fn": fn})
    assert proj.job["cancelled"]
    assert _translated(_on_disk(proj)) == [0, 1], \
        "the pages that ran are the pages that are kept"


def test_each_page_is_written_as_it_goes_not_only_at_the_end(proj):
    """What makes the first test true: the write happens per page, so there is
    no window in which several finished pages exist only in memory."""
    seen = []

    def fn(i):
        _write(proj, i)
        seen.append(sorted(proj._dirty_lock and [1]))   # touch nothing
    saves = []
    real = proj.save_soon
    proj.save_soon = lambda: (saves.append(len(seen)), real())[1]
    try:
        editor._run_one(proj, {"label": "Translating", "indices": [0, 1, 2],
                               "fn": fn})
    finally:
        proj.save_soon = real
    assert saves == [1, 2, 3], \
        f"one mark per page, as each finishes: {saves}"


def test_the_write_is_coalesced_so_a_long_chapter_still_costs_one(proj):
    """`save_soon` is what makes per-page affordable. Marking it dirty forty
    times must not be forty half-megabyte writes into a synced folder —
    lee: *"it works but very slow"* is the other half of this."""
    writes = []
    real = Project.save
    Project.save = lambda self: (writes.append(1), real(self))[1]
    try:
        editor._run_one(proj, {"label": "Translating",
                               "indices": list(range(5)),
                               "fn": lambda i: _write(proj, i)})
    finally:
        Project.save = real
    assert len(writes) <= 2, f"five pages should not be five writes: {writes}"
