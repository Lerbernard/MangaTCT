"""`BubbleGeom` measures a balloon on the balloon's own box, and gets the same
answer it got measuring the whole page.

lee: *"optimaze the app make it faster and moother dont chnage teh
fuctionality"*. The masks are page-sized whatever the balloon is, and the
fitter asks for a balloon's chords at an inset hundreds of times a page; taking
them over the mask's bounding box instead of the page saved about 1.6s of CPU a
page on his chapter. The whole claim is that nothing changes, so that is what is
checked: every value `_measure` hands out, against the page-wide computation it
replaced, over the shapes that make a chord interesting.
"""
import cv2
import numpy as np
import pytest

from mangatl import typeset as T


def _page_wide(geom, key):
    """The measurement exactly as it was before it was taken on the box."""
    inner = (geom.dist >= key).astype(np.uint8)
    rows, first, last = T._row_chords(inner)
    ys = np.flatnonzero(rows)
    if ys.size:
        y0, y1 = int(ys[0]), int(ys[-1])
        widths = np.where(rows, last - first + 1, 0).astype(np.float32)
    else:
        y0 = y1 = 0
        widths = np.zeros(0)
    return (inner, widths, y0, y1, first.astype(np.float32),
            last.astype(np.float32))


def _masks():
    H, W = 420, 380
    oval = np.zeros((H, W), np.uint8)
    cv2.ellipse(oval, (190, 210), (120, 160), 0, 0, 360, 255, -1)
    holed = oval.copy()
    cv2.circle(holed, (200, 200), 40, 0, -1)          # hair through the middle
    edge = np.zeros((H, W), np.uint8)
    cv2.ellipse(edge, (20, 30), (90, 70), 0, 0, 360, 255, -1)   # off the corner
    sliver = np.zeros((H, W), np.uint8)
    sliver[100:300, 150:156] = 255                    # thinner than most insets
    empty = np.zeros((H, W), np.uint8)
    return {"oval": oval, "holed": holed, "edge": edge,
            "sliver": sliver, "empty": empty}


@pytest.mark.parametrize("name", ["oval", "holed", "edge", "sliver", "empty"])
@pytest.mark.parametrize("key", [0.0, 0.5, 1.0, 2.5, 6.0, 40.0])
def test_the_box_and_the_page_give_the_same_measurement(name, key):
    geom = T.BubbleGeom(_masks()[name])
    got = geom._measure(key)
    want = _page_wide(geom, key)
    assert len(got) == len(want) == 6
    for g, w in zip(got, want):
        if isinstance(w, np.ndarray):
            assert isinstance(g, np.ndarray)
            assert g.dtype == w.dtype and g.shape == w.shape, (name, key)
            assert np.array_equal(g, w), (name, key)
        else:
            assert g == w, (name, key)


def test_the_accessors_still_agree_with_each_other():
    geom = T.BubbleGeom(_masks()["holed"])
    inner, widths, y0, y1 = geom.inset(3.0)
    left, right = geom.edges(3.0)
    rows = np.flatnonzero(widths > 0)
    assert rows.size and y0 == int(rows[0]) and y1 == int(rows[-1])
    assert np.array_equal(widths[rows], right[rows] - left[rows] + 1)
