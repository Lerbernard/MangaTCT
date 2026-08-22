"""Merging: one type only, and the box it makes gets a number of its own.

lee: *"merge is broken and male it so that i can only merge boxes of the same
type"*.

TWO THINGS, and the first is the one that made it "broken".

**The new box was being handed a dead box's number.** `next_id` exists so that
a box drawn after a delete cannot inherit the deleted one's words - lee:
*"when i deleet an text box and create a new one it come back with teh same
text as teh olde text box"*. But the counter only ever moved when a box was
MADE. Delete the highest-numbered box on a page and the floor dropped back to
it, and the next box created took its number.

A merge is deletes followed immediately by a create, so it hit that every
single time. On chapter 3's page 005, merging ids 2 and 6 produced a new box
called 6 - and everything the editor still held about the old 6 (the pending
keystroke, the edit whose save had not come home, the undo snapshot) is filed
under that number.

**And a merged box has to be SOME type.** It was quietly the first one's, so
merging a sound effect into a balloon turned the sound into dialogue, and the
reverse hid a line of dialogue from the cleaning pass. Neither is a thing
anybody asked for by selecting two boxes.
"""
import json
import shutil

import pytest

from mangatl.project import Project
from scratch import scratch
from where import JS

ROOT = scratch("_tmp_merge_ids")
RO = (JS / "region-ops.js").read_text(encoding="utf-8")


def _page():
    shutil.rmtree(ROOT, ignore_errors=True)
    p = Project(None, ROOT)
    p.pages.append(type(p.pages[0])() if p.pages else None)
    return p


def _fresh(tmp_path, ids):
    """A page carrying these region ids and NO counter - which is what a
    project.json written before `next_id` existed looks like."""
    p = Project(None, str(tmp_path / "out"))
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    p.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((80, 60, 3), 240, np.uint8))[1].tobytes())
    pg = p.pages[0]
    pg.regions = [{"id": i, "bbox": [0, 0, 10, 10], "kind": "bubble",
                   "order": n} for n, i in enumerate(ids)]
    pg.next_id = 0
    return p, pg


# ------------------------------------------------------- the number

def test_a_number_is_never_handed_out_twice(tmp_path):
    """The case off lee's own page: delete the top box, draw a new one."""
    _p, pg = _fresh(tmp_path, [0, 1, 2, 3, 4, 5, 6])
    pg.remember_ids()
    pg.regions = [r for r in pg.regions if r["id"] not in (2, 6)]
    assert pg.new_region_id() == 7, "6 has been used and is not free again"


def test_the_counter_starts_itself_on_an_old_project(tmp_path):
    """`next_id` of 0 means "never written down", not "start at zero"."""
    _p, pg = _fresh(tmp_path, [0, 1, 2])
    assert pg.new_region_id() == 3
    assert pg.new_region_id() == 4


def test_deleting_every_box_does_not_reset_the_page(tmp_path):
    _p, pg = _fresh(tmp_path, [0, 1, 2])
    pg.remember_ids()
    pg.regions = []
    assert pg.new_region_id() == 3


def test_the_delete_endpoint_remembers_before_it_removes():
    """The order is the whole of it: after the box is gone its number is gone
    with it, and there is nothing left to remember."""
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index("def do_DELETE(")
    body = src[at:src.index("\ndef ", at)]
    assert "remember_ids()" in body
    assert body.index("remember_ids()") < body.index('if r["id"] != rid'), \
        "remembered before removed, or it is not remembered at all"


def test_the_method_is_not_the_field_of_the_same_name():
    """`note_ids` was already taken - it is the list of boxes a page's note is
    about - and a method by that name is shadowed by the field at runtime,
    which is a `'list' object is not callable` on every delete."""
    from mangatl.project import PageState
    p = PageState(path="x.png", name="x.png")
    assert isinstance(p.note_ids, list)
    assert callable(p.remember_ids)


# ------------------------------------------------------- the type

def test_a_mixed_selection_is_refused_with_the_types_named():
    body = RO.split("async function mergeSelected(ids)", 1)[1] \
             .split("\n/*", 1)[0]
    at = body.index("new Set(rs.map")
    head = body[at:at + 400]
    assert "kinds.length > 1" in head
    assert "return;" in head, "refused, not merged anyway"
    assert "kindLabel" in head, "says WHICH types, or it is a puzzle"
    # ...and it is decided before anything is deleted
    assert body.index("kinds.length > 1") < body.index("'DELETE'")


def test_the_menu_does_not_offer_a_merge_that_would_be_refused():
    """A row that answers with a refusal is a row that should not be lit."""
    body = RO.split("function boxMenu(ev, id)", 1)[1].split("\n}", 1)[0]
    assert "oneKind" in body
    at = body.index("mergeSelected(")
    assert "many >= 2 && oneKind" in body[:at]


def test_the_kind_of_the_merged_box_is_the_kind_they_all_share():
    body = RO.split("async function mergeSelected(ids)", 1)[1].split("\n/*", 1)[0]
    assert "const kind = rs[0].kind;" in body


def test_the_menu_merges_exactly_the_boxes_it_named():
    """lee: *"thsi donst work when multtiple boxes are slected"*.

    The menu was built from the selection when it OPENED and read the
    selection again when a row was clicked. Anything that touched it in
    between - a redraw landing while the menu was up, `syncMulti` finding
    `sel` null and clearing the set - left a menu offering "Merge 3 boxes"
    over a merge that saw one box and did nothing at all."""
    body = RO.split("function boxMenu(ev, id)", 1)[1].split("\n}", 1)[0]
    assert "mergeSelected(${JSON.stringify(ids)})" in body
    # ...and the merge takes them rather than looking the selection up again
    head = RO.split("async function mergeSelected(ids)", 1)[1][:400]
    assert "(ids && ids.length) ? ids.slice() : selIds()" in head


def test_it_says_so_when_the_boxes_it_named_have_gone():
    """"Select two or more boxes to merge" is a puzzle with three of them
    lit."""
    head = RO.split("async function mergeSelected(ids)", 1)[1][:1200]
    assert "not on this page any more" in head


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
