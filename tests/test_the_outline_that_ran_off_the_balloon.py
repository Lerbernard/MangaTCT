# -*- coding: utf-8 -*-
"""A saved outline is read against the page before the English is put in it.

lee, with page 009 of his chapter - a black balloon with the English sitting
low in it and crowding the bottom-left curve: *"the position of teh text iide
is too low and too close to tehe edge at teh bottom left"*.

## It was not the typesetter

The outline saved for that box is not the balloon. It follows the balloon along
the top and the right, and then runs out as a straight-edged rectangle across
the screentone at the bottom-left, down to the corner of the box - hull clipped
by a rectangle, which is what an older build's bay-fill leaves behind when the
box it is clipped to is bigger than the balloon. Page 019's outline is worse: a
rectangle a third bigger than its balloon in every direction, taking in two
panels' worth of artwork.

The fitter is not wrong about any of this. It measures the room in the shape it
is given and fills it, so a shape with an extra lobe of artwork hanging off the
bottom-left puts the block low and to the left. Given the balloon it centres.

**Nothing rewrites a saved outline.** It is written once, by the detector, and
read for ever after; a chapter carries whatever the build of the day wrote. So
a bad one cannot be waited out - it has to be read.

## The rule

A balloon is a FIELD OF ONE TONE with a rim drawn round it, and the words go in
the field. So the outline is checked against the page: walk out from the
writing over one tone until drawn edges stop you - the same walk that found the
balloon in the first place, `detect.balloon._free_labels` - and keep the part
of the outline that walk reaches. Whichever way round the balloon is drawn: the
polarity is picked the way `_writing_in` picks it, because a rule that read one
of them upright and the other inverted would cut the balloon in half.

The writing is always its own ground - union'd back in, holes filled - because
the walk stops at ink, and a placement area with the letters punched out of it
is the tall-narrow-column bug `place_mask` exists to avoid.

MEASURED over lee's 137 balloon outlines: 131 come back to the pixel, all 137
keep every pixel of their writing, and the four that move are the four that are
wrong.

Nothing is written back. The outline on disk stays the one he drew and the one
he sees; this is only where the English is allowed to go, worked out from the
page on every load - the same arrangement as `balloon.room_around`.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.project import (GROUND_KEEPS, INK, _one_ground,  # noqa: E402
                             _writing_in, region_from_record)

H, W = 300, 260
CX, CY, RX, RY = 120, 150, 70, 95


def _balloon_page(dark=False):
    """A balloon with a rim, artwork round it, and writing inside."""
    page = np.full((H, W), 150, np.uint8)
    for y in range(0, H, 5):                     # screentone artwork
        page[y:y + 2, :] = 30
    # A rim is drawn in the colour the fill is NOT - that is what makes it a
    # rim, and it is what stops the walk.
    cv2.ellipse(page, (CX, CY), (RX + 6, RY + 6), 0, 0, 360,
                250 if dark else 15, -1)          # the rim
    cv2.ellipse(page, (CX, CY), (RX, RY), 0, 0, 360,
                8 if dark else 252, -1)           # the fill
    for k in range(4):                            # four bars of writing
        y = CY - 50 + k * 26
        page[y:y + 10, CX - 40:CX + 40] = 250 if dark else 12
    return page


def _outline(extra=None):
    """The balloon as an outline mask, optionally with a lobe of artwork."""
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (CX, CY), (RX, RY), 0, 0, 360, 255, -1)
    if extra is not None:
        x0, y0, x1, y1 = extra
        m[y0:y1, x0:x1] = 255
    return m


def _glyph(page, mask, dark):
    return _writing_in(page, mask, balloon=True)


def _area(m):
    return int((m > 0).sum())


# --------------------------------------------------------- the outline is read

@pytest.mark.parametrize("dark", [False, True])
def test_a_lobe_of_artwork_is_not_where_the_words_may_go(dark):
    """lee's page 009 and 019, either way round the balloon is drawn."""
    page = _balloon_page(dark)
    good = _outline()
    bad = _outline(extra=(10, CY, CX, CY + RY + 30))     # off the balloon
    glyph = _glyph(page, bad, dark)
    got = _one_ground(page, bad, glyph)
    assert _area(got) < _area(bad), "the lobe was kept"
    # what is left is the balloon, near enough: nine tenths of it, and almost
    # nothing outside it.
    inside = good > 0
    assert float(((got > 0) & inside).sum()) / _area(good) > 0.9
    assert float(((got > 0) & ~inside).sum()) / max(1, _area(got)) < 0.1


@pytest.mark.parametrize("dark", [False, True])
def test_an_outline_that_is_the_balloon_is_left_alone(dark):
    """131 of lee's 137 are this case and they must come back to the pixel."""
    page = _balloon_page(dark)
    good = _outline()
    got = _one_ground(page, good, _glyph(page, good, dark))
    keep = float(((got > 0) & (good > 0)).sum()) / _area(good)
    assert keep > 0.97, keep
    assert _area(got) <= _area(good) * 1.001


@pytest.mark.parametrize("dark", [False, True])
def test_the_writing_is_always_its_own_ground(dark):
    """The walk stops at ink, so the letters are holes in the run. A placement
    area with the letters punched out of it is the shape `place_mask` was
    written to stop the fitter ever seeing."""
    page = _balloon_page(dark)
    good = _outline()
    glyph = _glyph(page, good, dark)
    got = _one_ground(page, good, glyph)
    assert (glyph > 0).any()
    left = float(((got > 0) & (glyph > 0)).sum()) / _area(glyph)
    assert left == 1.0, left


def test_nothing_is_believed_that_eats_the_balloon():
    """A reading that leaves almost nothing is not a reading, it is a page
    that is not what this rule thinks it is - and then the outline stands."""
    page = np.full((H, W), 128, np.uint8)      # no rim, no fill, no ground
    for y in range(0, H, 3):
        page[y:y + 1, :] = 20
    good = _outline()
    glyph = np.zeros((H, W), np.uint8)
    glyph[CY - 10:CY + 10, CX - 30:CX + 30] = 255
    got = _one_ground(page, good, glyph)
    assert _area(got) >= GROUND_KEEPS * _area(good)


def test_an_outline_with_no_writing_in_it_is_left_alone():
    page = _balloon_page()
    good = _outline()
    got = _one_ground(page, good, np.zeros((H, W), np.uint8))
    assert np.array_equal(got, good)


def test_the_line_is_written_down_once():
    assert 0.2 < GROUND_KEEPS < 0.5, GROUND_KEEPS


# ------------------------------------------------- and the door it comes in by

def _record(mask, kind="bubble"):
    cnts, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    poly = max(cnts, key=cv2.contourArea).reshape(-1, 2)
    x, y, w, h = cv2.boundingRect(max(cnts, key=cv2.contourArea))
    return {"id": 1, "kind": kind, "order": 0,
            "bbox": [CX - 45, CY - 55, 90, 110],
            "bubble_bbox": [int(x), int(y), int(w), int(h)],
            "polygon": [[int(a), int(b)] for a, b in poly],
            "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9}


def test_a_saved_record_comes_back_with_the_balloon_and_not_the_artwork():
    """End to end, through the door every reopened chapter comes in by."""
    page = _balloon_page(dark=True)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    bad = _outline(extra=(10, CY, CX, CY + RY + 30))
    r = region_from_record(_record(bad), img)
    got = r.place_mask()
    assert got is not None
    off = (got > 0) & (_outline() == 0)
    assert float(off.sum()) / max(1, _area(got)) < 0.1, \
        "the placement area still runs off the balloon"


def test_a_box_somebody_turned_is_not_read_this_way_either():
    """A leaning rectangle is a rectangle. `_is_a_box` answers about an UPRIGHT
    one, so a turned box arrives here looking like an outline - and it is not:
    it says where the WRITING is, somebody drew it, and reading it against the
    page took a fifth off it."""
    from mangatl.models import turned_box
    page = _balloon_page()
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    bbox = [CX - 60, CY - 40, 120, 80]
    rec = {"id": 1, "kind": "bubble", "order": 0, "bbox": bbox,
           "bubble_bbox": None, "polygon": turned_box(bbox, 30),
           "manual": True, "turn": 30, "src_text": "a", "dst_text": "HELLO",
           "confidence": 0.9}
    r = region_from_record(rec, img)
    quad = np.zeros((H, W), np.uint8)
    cv2.fillPoly(quad, [np.array(rec["polygon"], np.int32).reshape(-1, 1, 2)], 255)
    # Not to the pixel - the bay-fill above this may still add a little - but
    # nothing was taken away, which is what the reading would have done.
    assert _area(r.bubble_mask) >= _area(quad), "the turned box was trimmed"
    assert float(((quad > 0) & (r.bubble_mask > 0)).sum()) == _area(quad)


def test_a_box_is_not_read_this_way():
    """The rectangle that stands in where there is no balloon is not claiming
    to be a field of anything, and trimming it to one tone would be trimming
    the fallback the fitter depends on."""
    page = _balloon_page()
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    rec = _record(_outline(), kind="freefloat")
    rec["polygon"] = [[40, 40], [200, 40], [200, 200], [40, 200]]
    r = region_from_record(rec, img)
    m = r.place_mask()
    assert m is not None
    x, y, w, h = rec["bbox"]
    want = np.zeros((H, W), np.uint8)
    want[y:y + h, x:x + w] = 255
    assert np.array_equal((m > 0), (want > 0)), "the fallback box was trimmed"
