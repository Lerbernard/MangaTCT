"""Every reading lands in the box its writing is in.

lee, with a balloon holding two columns side by side and each one's words
showing in the other's row: *"tdh etxt are not on the proper bubbles"* and
*"make sure that the read text alway does to the proper bubble"*. On his 27
pages it happened three times (004, 005, 021), always two columns in one
balloon, and the picture the AI reader was sent explains it: each column's red
number was printed in the gutter against the NEIGHBOUR's outline.

Two things are guarded here: where the number goes, and the check that puts a
swapped pair back whatever swapped it.
"""
import cv2
import numpy as np
import pytest

from mangatl import editor, ocr
from mangatl.models import Page, TextRegion


def _rect(x, y, w, h):
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.int32)


def _off(pts, x, y):
    return ocr._off_shape(pts, x, y)


# ------------------------------------------------------------- the number

def test_a_number_is_nearer_its_own_column_than_the_one_beside_it():
    """Two columns with a narrow gutter between them, on white paper - the
    emptiest spot for either number is that gutter, which is exactly where it
    is ambiguous."""
    vis = np.full((260, 260, 3), 255, np.uint8)
    left, right = _rect(60, 40, 40, 170), _rect(106, 40, 90, 170)
    # ink in both columns, so the corners over the words are not the emptiest
    cv2.rectangle(vis, (66, 50), (94, 200), (0, 0, 0), -1)
    cv2.rectangle(vis, (112, 50), (190, 200), (0, 0, 0), -1)
    for own, other in ((left, right), (right, left)):
        bw, bh = 24, 18
        x, y = ocr._tag_spot(vis, own, bw, bh, [other])
        cx, cy = x + bw / 2, y + bh / 2
        assert _off(own, cx, cy) < _off(other, cx, cy), \
            "the number sits at least as near the neighbour as its own column"


def test_with_no_neighbours_the_number_goes_where_it_always_did():
    vis = np.full((200, 200, 3), 255, np.uint8)
    pts = _rect(60, 40, 50, 120)
    assert ocr._tag_spot(vis, pts, 20, 16) == ocr._tag_spot(vis, pts, 20, 16, [])


def test_when_every_corner_is_ambiguous_it_goes_inside_its_own_box():
    """A small box wrapped by a bigger one: every corner outside it is inside
    the other."""
    vis = np.full((240, 240, 3), 255, np.uint8)
    small, big = _rect(90, 90, 40, 40), _rect(40, 40, 160, 160)
    x, y = ocr._tag_spot(vis, small, 16, 14, [big])
    assert 90 <= x and x + 16 <= 130 and 90 <= y and y + 14 <= 130


def test_every_picture_the_reader_gets_passes_the_neighbours_in():
    import inspect
    src = inspect.getsource(ocr)
    tiles = src.split("def page_label_tiles(")[1].split("\ndef ")[0]
    crops = src.split("def page_box_crops(")[1].split("\ndef ")[0]
    assert "for q in here if q.id != r.id" in tiles
    assert "for o in here if o.id != q.id" in crops


# ------------------------------------------------------ the check after it

def _page_with_two_columns():
    """A big block of five columns beside a single thin column, both lettered
    at the same size: roughly 25 characters' worth of ink against 5."""
    img = np.full((400, 400, 3), 255, np.uint8)
    mask = np.zeros((400, 400), np.uint8)
    big = TextRegion(id=10, bbox=(170, 60, 150, 170), kind="bubble")
    thin = TextRegion(id=4, bbox=(120, 70, 40, 170), kind="bubble")
    for col in range(5):
        for row in range(5):
            x, y = 180 + col * 28, 70 + row * 30
            mask[y:y + 16, x:x + 16] = 255
    for row in range(5):
        x, y = 128, 80 + row * 30
        mask[y:y + 16, x:x + 16] = 255
    big.text_mask = mask.copy()
    thin.text_mask = mask.copy()
    return Page(image=img, regions=[big, thin])


LONG = "エーダの\n遺体ですが\n王都の外に\n足を伸ばした\nものの…"
SHORT = "残念ながら…"


def test_a_swapped_pair_is_put_back():
    page = _page_with_two_columns()
    texts = {10: SHORT, 4: LONG}
    moved = editor._readings_that_belong_next_door(page, texts)
    assert texts == {10: LONG, 4: SHORT}
    assert moved == {10: 4, 4: 10}


def test_a_pair_read_right_is_left_alone():
    page = _page_with_two_columns()
    texts = {10: LONG, 4: SHORT}
    assert editor._readings_that_belong_next_door(page, texts) == {}
    assert texts == {10: LONG, 4: SHORT}


def test_a_sound_effect_is_never_part_of_a_swap():
    page = _page_with_two_columns()
    page.regions[0].kind = "sfx"
    texts = {10: SHORT, 4: LONG}
    assert editor._readings_that_belong_next_door(page, texts) == {}


def test_a_locked_line_is_never_part_of_a_swap():
    page = _page_with_two_columns()
    page.regions[1].locked = True
    page.regions[1].src_text = SHORT
    texts = {10: SHORT, 4: LONG}
    assert editor._readings_that_belong_next_door(page, texts) == {}


def test_boxes_far_apart_are_not_compared():
    page = _page_with_two_columns()
    page.regions[1].bbox = (0, 300, 40, 90)
    texts = {10: SHORT, 4: LONG}
    assert editor._readings_that_belong_next_door(page, texts) == {}


def test_the_read_step_runs_the_check_and_says_so_on_the_box():
    import inspect
    body = inspect.getsource(editor._read_with_ai)
    assert "_readings_that_belong_next_door(page, texts)" in body
    assert "it was moved here, where its writing" in body
