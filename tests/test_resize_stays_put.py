"""Letting go of a resize must leave the box where you let go of it.

lee: *"the detectioj is good teh issue im running into is the box are snappin
to teh edge of the text when i try to resize them it happens wheni i let go"*.

Dragging a corner posts the new rectangle back with `snap:false`, and
`region_from_box` documents that as "the rectangle is used exactly as drawn".
It was not. Both ends of the no-snap path went through `_fallback`, which
measured the ink inside the rectangle and returned THAT as `bbox` — and `bbox`
is the rectangle the editor draws. So the box sprang inwards onto the letters
the instant the mouse came up. Measured on the real chapter beforehand: of 250
drags over detected boxes, 250 came back somewhere other than where they were
released; a plain 12% grow lost its new room about two times in three.

`_fallback` now takes `exact`, and the no-snap path passes it. The ink is still
measured — it is what `src_vertical` is read from, and `text_mask` is still the
ink inside the rectangle, so cleaning is untouched — it just no longer
overrules a rectangle somebody dragged on purpose.

The tightening itself is not gone. A rectangle drawn round writing that has no
balloon to snap to is a rough gesture, and that still comes back wrapped round
the ink; there is a test for it below, so a later "fix" cannot quietly take
both behaviours to the same place.
"""
import glob
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.interactive import region_from_box
from mangatl.models import Page
from mangatl.project import region_record


def _pages(n: int = 4) -> list[str]:
    roots = [os.environ.get("MANGATL_TEST_PAGES", ""), "pages", "chapter",
             "up", "out/input", "mangatl/out/input"]
    for root in roots:
        if root and os.path.isdir(root):
            hits = sorted(glob.glob(os.path.join(root, "*.jpg")))
            if hits:
                return hits[:n]
    return []


PAGES = _pages()
needs_pages = pytest.mark.skipif(not PAGES, reason="need sample manga pages")


def _drags(box):
    """The five ways a hand actually changes a box."""
    x, y, w, h = box
    return [
        (x - int(w * .12), y - int(h * .12), int(w * 1.24), int(h * 1.24)),
        (x + int(w * .06), y + int(h * .06), max(8, int(w * .88)),
         max(8, int(h * .88))),
        (x + 9, y - 7, w, h),                      # moved, same size
        (x, y, int(w * 1.6), h),                   # wider only
        (x, y - int(h * .3), w, int(h * 1.3)),     # taller only
    ]


@needs_pages
def test_a_resized_box_is_exactly_the_box_you_let_go_of():
    from mangatl.detect import classical

    tot = moved = 0
    examples = []
    for f in PAGES:
        img = cv2.imread(f)
        page = Page(image=img, source_path=os.path.basename(f))
        for r in classical.detect_combined(page):
            for box in _drags(r.bbox):
                nr = region_from_box(page, *box, kind=r.kind, rid=r.id,
                                     snap=False)
                tot += 1
                if tuple(nr.bbox) != tuple(box):
                    moved += 1
                    examples.append((os.path.basename(f), box,
                                     tuple(nr.bbox)))
    if tot == 0:
        pytest.skip("no boxes detected to resize")
    assert moved == 0, f"{moved}/{tot} drags moved, e.g. {examples[:3]}"


@needs_pages
def test_the_rectangle_is_what_gets_stored_and_what_the_editor_draws():
    """The editor draws `bbox`, and a chapter is stored as geometry, so the
    rectangle has to survive the record as well as the call."""
    from mangatl.detect import classical

    img = cv2.imread(PAGES[-1])
    page = Page(image=img, source_path=os.path.basename(PAGES[-1]))
    found = classical.detect_combined(page)
    if not found:
        pytest.skip("no boxes detected")
    x, y, w, h = found[0].bbox
    drawn = [x - 14, y - 14, w + 28, h + 28]
    rec = region_record(region_from_box(page, *drawn, snap=False, rid=0))
    assert rec["bbox"] == drawn
    assert rec["bubble_bbox"] == drawn
    assert rec["polygon"] == [[drawn[0], drawn[1]],
                              [drawn[0] + drawn[2], drawn[1]],
                              [drawn[0] + drawn[2], drawn[1] + drawn[3]],
                              [drawn[0], drawn[1] + drawn[3]]]


def _column_page():
    """A tall narrow column of marks in the middle of a wide white page."""
    img = np.full((240, 320, 3), 245, np.uint8)
    for k in range(5):
        cv2.rectangle(img, (150, 70 + k * 18), (168, 82 + k * 18),
                      (20, 20, 20), -1)
    return Page(image=img, source_path="col")


def test_a_rough_box_round_writing_with_no_balloon_still_hugs_the_ink():
    """The other half of the contract. Snapping ON with nothing to snap to is
    a rough gesture at some writing, and it still comes back round the ink."""
    page = _column_page()
    drawn = (110, 40, 130, 150)
    r = region_from_box(page, *drawn, kind="sfx", rid=0, snap=True)
    assert tuple(r.bbox) != drawn
    assert r.bbox[2] < drawn[2] and r.bbox[3] < drawn[3]
    # and it must still contain every mark
    assert r.bbox[0] <= 150 and r.bbox[0] + r.bbox[2] >= 169
    assert r.bbox[1] <= 70 and r.bbox[1] + r.bbox[3] >= 155


def test_the_writing_runs_the_way_the_ink_runs_not_the_way_the_box_does():
    """`src_vertical` describes the Japanese, so it is read off the ink even
    when the rectangle round it is wider than it is tall."""
    page = _column_page()
    r = region_from_box(page, 110, 55, 130, 110, kind="bubble", rid=0,
                        snap=False)
    assert tuple(r.bbox) == (110, 55, 130, 110)      # wide box, kept
    assert r.src_vertical, "a vertical column read as horizontal"


def test_the_ink_inside_the_box_is_still_what_gets_cleaned():
    """Keeping the rectangle must not cost the erase mask: `text_mask` is the
    ink, not the rectangle, or Clean would wipe the whole box."""
    page = _column_page()
    r = region_from_box(page, 110, 40, 130, 150, kind="bubble", rid=0,
                        snap=False)
    ink = int((r.text_mask > 0).sum())
    assert 0 < ink < 130 * 150 * 0.5
    ys, xs = np.nonzero(r.text_mask)
    assert xs.min() >= 150 and xs.max() <= 168
