"""The balloon shape does not get to cut a bay out of its own writing.

Page 067 of lee's chapter came back with `스토리가` and `매력적인` still on it and
the four lines above them cleaned off. The mask handed to the cleaner is the
reason, and it is visible in one number: at the height of that line the
placement area is four runs - 257-271, 380-385, 393-481, 604-626 - with a
hundred-pixel gap over each of the two surviving words. At the height of line
one it is a single run, 271 to 611.

**Where the bays come from.** `_give_back` grows the sealed shape into paper
and stops it against ink (`wall`), so that the shape ends at the drawn outline
instead of stepping over it. Typesetting the seal missed is ink too. It becomes
a wall, the growth goes around it, and the finished balloon has a bay exactly
the shape of the word - which is then the one place in the balloon the cleaner
is not looking.

**The rule.** Anything inside the shape's convex hull AND inside the region's
own text box is interior. Both halves carry weight: the hull alone steps over
the outline of a crescent-shaped balloon, and the box alone swallows whatever
the box happens to overlap at the rim. Between them the fill can only reach
places the writing is already standing in.

**Measured on the chapter**, over the 124 balloons stored on disk: the median
mask does not grow at all, page 067 grows 7.0%, one other passes 1%, and
across all 124 **not one pixel** lands outside a text box.

It is fixed in two places on purpose. `detect.balloon._apply` is where new
detections are made; `project.region_from_record` is where a project saved
before today is rebuilt, and nothing rewrites a stored polygon except a fresh
detect. lee's chapter is one of those, so without the second one the page he
sent would still be wrong.
"""

import cv2
import numpy as np
import pytest

from mangatl.detect.balloon import _no_bays_in_the_writing


class _R:
    def __init__(self, bbox):
        self.bbox = bbox


def _outer(mask):
    cnts, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    return max(cnts, key=cv2.contourArea)


def _balloon(w=400, h=300, bays=()):
    """A filled ellipse, with a bay bitten out of it for each rectangle.

    A BAY and not a hole. `_give_back` grows the shape inward from the rim, so
    what it leaves round a missed word opens onto the outside - and that is the
    shape that matters, because `RETR_EXTERNAL` drops a hole for free and keeps
    a bay. Every bite here is widened to the left edge of the frame so the
    contour has to snake in around it.
    """
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (w // 2, h // 2), (w // 2 - 10, h // 2 - 10), 0, 0, 360, 255, -1)
    for bx, by, bw, bh in bays:
        m[by:by + bh, 0:bx + bw] = 0
    return m


def _filled(poly, shape):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.array(poly, np.int32)], 255)
    return m


def test_a_bay_bitten_out_of_the_writing_is_filled_back():
    """The 067 case, in miniature."""
    m = _balloon(bays=[(60, 140, 100, 30)])
    fixed = _no_bays_in_the_writing(_R((50, 100, 300, 100)), m, _outer(m))
    assert fixed[150, 100] > 0


def test_and_the_word_is_whole_again():
    m = _balloon(bays=[(60, 140, 100, 30)])
    fixed = _no_bays_in_the_writing(_R((50, 100, 300, 100)), m, _outer(m))
    assert (fixed[140:170, 60:160] > 0).all()


def test_a_bay_nowhere_near_the_writing_is_left_alone():
    """It may be the artist's shape. Only the text box gives leave to fill."""
    m = _balloon(bays=[(60, 30, 100, 30)])
    fixed = _no_bays_in_the_writing(_R((50, 140, 300, 60)), m, _outer(m))
    assert fixed[45, 100] == 0


def test_nothing_lands_outside_the_text_box():
    m = _balloon(bays=[(60, 140, 100, 30)])
    box = (50, 100, 300, 100)
    fixed = _no_bays_in_the_writing(_R(box), m, _outer(m))
    x, y, w, h = box
    added = (fixed > 0) & (m == 0)
    added[y:y + h, x:x + w] = False
    assert not added.any()


def test_nothing_lands_outside_the_balloon_either():
    """The hull is the other half of the rule. A text box wider than the shape
    must not turn the balloon into its own bounding rectangle."""
    m = _balloon()
    fixed = _no_bays_in_the_writing(_R((0, 0, 400, 300)), m, _outer(m))
    hull = np.zeros(m.shape, np.uint8)
    cv2.fillPoly(hull, [cv2.convexHull(_outer(m))], 255)
    assert not ((fixed > 0) & (hull == 0)).any()


def test_a_balloon_with_no_bays_is_returned_unchanged():
    m = _balloon()
    fixed = _no_bays_in_the_writing(_R((50, 100, 300, 100)), m, _outer(m))
    assert int((fixed > 0).sum()) == int((m > 0).sum())


def test_a_crescent_does_not_get_its_bite_filled_in():
    """The hull alone would step clean over the drawn outline. The text box is
    what stops it - the bite is not where the writing is."""
    m = _balloon()
    cv2.circle(m, (200, 40), 90, 0, -1)
    fixed = _no_bays_in_the_writing(_R((80, 180, 240, 80)), m, _outer(m))
    assert fixed[40, 200] == 0


@pytest.mark.parametrize("bbox", [(), (0, 0, 0, 0), (10, 10, 0, 40), None])
def test_a_region_with_no_usable_box_changes_nothing(bbox):
    m = _balloon(bays=[(60, 140, 100, 30)])
    r = _R(bbox)
    fixed = _no_bays_in_the_writing(r, m, _outer(m))
    assert int((fixed > 0).sum()) == int((m > 0).sum())


def test_a_box_hanging_off_the_edge_of_the_page_is_survivable():
    m = _balloon(bays=[(60, 140, 100, 30)])
    fixed = _no_bays_in_the_writing(_R((-40, 100, 500, 400)), m, _outer(m))
    assert fixed[150, 100] > 0


# --- and it has to reach both places -----------------------------------------

def test_the_finder_fills_the_bay_when_it_stores_the_shape():
    from mangatl.detect.balloon import _apply
    from mangatl.models import TextRegion
    m = _balloon(bays=[(60, 140, 100, 30)])
    r = TextRegion(id=0, bbox=(50, 100, 300, 100), text_mask=None,
                   bubble_mask=None, bubble_bbox=None, kind="bubble")
    assert _apply(r, m)
    assert r.bubble_mask[150, 100] > 0


def test_and_the_polygon_it_stores_is_the_shape_it_stored():
    """The polygon is what survives a save, and it is traced off the mask. Take
    it off the shape as it arrived and the bay comes back on the next load."""
    from mangatl.detect.balloon import _apply
    from mangatl.models import TextRegion
    m = _balloon(bays=[(60, 140, 100, 30)])
    r = TextRegion(id=0, bbox=(50, 100, 300, 100), text_mask=None,
                   bubble_mask=None, bubble_bbox=None, kind="bubble")
    assert _apply(r, m)
    assert _filled(r.polygon, m.shape)[150, 100] > 0


def test_and_a_project_saved_before_today_is_repaired_on_the_way_in():
    """Nothing rewrites a stored polygon except a fresh detect, so a chapter
    already on disk would keep the bays for ever."""
    from mangatl.project import region_from_record
    m = _balloon(bays=[(60, 140, 100, 30)])
    poly = _outer(m).reshape(-1, 2).tolist()
    assert _filled(poly, m.shape)[150, 100] == 0, \
        "the fixture has to reproduce the bay, or this proves nothing"
    rec = {"id": 0, "bbox": [50, 100, 300, 100], "bubble_bbox": [10, 10, 380, 280],
           "polygon": poly, "kind": "bubble"}
    img = np.full((300, 400, 3), 255, np.uint8)
    r = region_from_record(rec, img)
    assert r.place_mask()[150, 100] > 0


def test_the_repair_does_not_touch_a_region_that_is_only_a_box():
    """A rectangle is not a balloon and never had a bay - see `_is_a_box`."""
    from mangatl.project import region_from_record
    rec = {"id": 0, "bbox": [50, 100, 200, 60],
           "bubble_bbox": [50, 100, 200, 60], "polygon": [],
           "kind": "bubble"}
    img = np.full((300, 400, 3), 255, np.uint8)
    r = region_from_record(rec, img)
    assert r.bubble_mask is None
