"""A box somebody set to Free text keeps its own box, not the panel round it.

lee, with a screenshot of a small green box at the top left of a panel and the
English "So this is the brush..." set well below and to the right of it, over
the drawing: *"what happens here"*.

Page 013 box 7 was drawn by hand as a sound effect, and the record said so:
its outline was its own rectangle. He set it to Free text. `_kind_changed` did
exactly its job - the outline stayed a rectangle - and the next rebuild of the
page threw that away. `find_balloons` runs on every rebuild and offers the
balloon search to free text, because a caption the DETECTOR called free text
may be sitting alone in a balloon. It found the panel round the caption (the
white paper between the frame, a figure coming in from the left and a dotted
strip), the typesetter centred the English in it, and the next save wrote the
panel down as the box's outline (61 points) and its placement area.

A person setting the type, or drawing the box, has answered that question. So
such a box is not offered the search; it still gets `give_room`.

And the rectangle he drew had gone too: `draw_box` - what "Box as-is" puts back -
was written by `region_record` from a field `region_from_record` never set, so
every commit of a page wrote None over every box's.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

# A panel shaped like the one on page 013, which the balloon finder takes as a
# balloon. A plain rectangle of white is not taken (a rectangle reads as "no
# balloon"), so the figure and the strip are what make it the real case.
H, W = 1800, 1200
PX, PY, PW, PH = 400, 600, 240, 250
BOX = [516, 627, 34, 84]


def _panel():
    img = np.full((H, W, 3), 255, np.uint8)
    cv2.rectangle(img, (PX, PY), (PX + PW, PY + PH), (0, 0, 0), 3)
    figure = np.array([[PX, PY + PH // 5], [PX + PW // 3, PY + PH // 3],
                       [PX + PW // 4, PY + PH // 2], [PX + PW // 3, PY + 4 * PH // 5],
                       [PX, PY + PH]], np.int32)
    cv2.fillPoly(img, [figure], (30, 30, 30))
    for k in range(PX + PW // 3, PX + PW, 14):
        cv2.circle(img, (k, PY + 3 * PH // 4), 4, (60, 60, 60), -1)
    cx, cy = BOX[0] + 4, BOX[1] + 4
    for k in range(cy, cy + 80, 18):
        cv2.rectangle(img, (cx, k), (cx + 26, k + 11), (20, 20, 20), -1)
    return img


def _rec(**extra):
    x, y, w, h = BOX
    rec = {"id": 1, "bbox": list(BOX), "bubble_bbox": list(BOX),
           "polygon": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
           "kind": "freefloat", "order": 0}
    rec.update(extra)
    return rec


def _rebuilt(rec, img):
    """What a page rebuild does to one box, and what the next save writes."""
    from mangatl.project import find_balloons, region_from_record, region_record
    r = region_from_record(rec, img)
    find_balloons(img, [r])
    return region_record(r)


def test_the_fixture_is_a_panel_the_finder_takes():
    """Otherwise the tests below prove nothing: a free block the DETECTOR
    labelled is still offered the search, and here it is handed the panel."""
    got = _rebuilt(_rec(), _panel())
    assert len(got["polygon"]) > 4, "the finder did not take the panel"
    assert got["bubble_bbox"][2] > 4 * BOX[2], got["bubble_bbox"]


@pytest.mark.parametrize("how", [{"kind_by_hand": True},
                                 {"manual": True},
                                 {"kind_by_hand": True, "manual": True}])
def test_a_box_a_person_set_to_free_text_keeps_its_rectangle(how):
    got = _rebuilt(_rec(**how), _panel())
    assert len(got["polygon"]) == 4, (
        "the panel was handed to the box as its outline (%d points)"
        % len(got["polygon"]))
    assert got["bubble_bbox"] == BOX, got["bubble_bbox"]


def test_a_sound_effect_set_by_hand_is_not_offered_either():
    got = _rebuilt(_rec(kind="sfx", kind_by_hand=True), _panel())
    assert len(got["polygon"]) == 4, got["polygon"]


def test_the_rectangle_as_drawn_survives_a_save():
    from mangatl.project import region_from_record, region_record
    rec = _rec(manual=True, draw_box=list(BOX))
    got = region_record(region_from_record(rec, _panel()))
    assert got["draw_box"] == BOX, got.get("draw_box")
