"""A flat patch where the artwork has detail is a refusal, not a result.

lee, with a screenshot of a white rectangle sitting where a column of Japanese
used to be on hatched cloth:

> *the ai seem to have given up and just made teh white box instard of cleaning
> teh text*

A model that cannot reconstruct an area sometimes hands back a flat patch of
one colour. That is not a cleaned page, it is an erased one, and it was being
accepted and composited exactly as though it were a good answer.

The test cannot be "is the answer flat" — inside a plain bubble the right
answer IS flat. It has to be "is the answer flat where its surroundings are
not". So both are measured: the detail in a ring just outside the mask, on the
page as it was handed to the model, and the detail inside the mask in what came
back. Flat against hatching, tone or line work goes to the local fill instead,
which at least copies from the page rather than inventing a blank — and the
report says "left to the local fill because the AI would not run", which is the
truth about what happened.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion

H, W = 340, 300


def _page(flat_bg):
    img = np.full((H, W), 248, np.uint8)
    if not flat_bg:
        for y in range(0, H, 6):
            for x in range(0, W, 6):
                if (x // 6 + y // 6) % 2 == 0:
                    cv2.rectangle(img, (x, y), (x + 4, y + 4), 110, -1)
    ink = np.zeros((H, W), np.uint8)
    y = 70
    while y < 250:
        cv2.rectangle(ink, (110, y), (150, y + 18), 255, -1)
        cv2.rectangle(ink, (117, y + 5), (143, y + 13), 0, -1)
        y += 24
    img[ink > 0] = 20
    return img, ink


def _white(sub, m):
    """A model that gives up: everything under the mask, one colour."""
    return np.where(m[..., None] > 0, 255, sub).astype(np.uint8)


def _honest(sub, m):
    """A model that answers: the surroundings carried through."""
    return sub.copy()


def _run(flat_bg, model):
    img, ink = _page(flat_bg)
    x, y, w, h = cv2.boundingRect(ink)
    r = TextRegion(id=1, bbox=(x - 4, y - 4, w + 8, h + 8), kind="freefloat",
                   text_mask=ink, bubble_mask=None,
                   bubble_bbox=(x - 4, y - 4, w + 8, h + 8))
    r.src_text = "a"
    r.dst_text = "b"
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    I.inpaint_page(page, neural=model)
    return page, r


def test_a_blank_answer_over_artwork_is_refused():
    """lee's white box. The ring outside the mask is hatching; the answer has
    nothing in it at all."""
    page, r = _run(False, _white)
    assert page.clean_stats.get("fell back") == 1, page.clean_stats
    assert not page.clean_stats.get("neural"), page.clean_stats
    # startswith, not equals: the model gave nothing, so the writing is still
    # standing afterwards and the second step correctly has a go at it. What
    # this test is about is that the refusal was RECOGNISED as one.
    assert r.clean_route.startswith("fell back"), r.clean_route


def test_a_real_answer_over_the_same_artwork_is_kept():
    """The premise. If the guard ever started refusing good answers this would
    fail, and the whole thing would be worse than doing nothing."""
    page, r = _run(False, _honest)
    assert page.clean_stats.get("neural") == 1, page.clean_stats
    assert not page.clean_stats.get("fell back"), page.clean_stats
    assert r.clean_route == "neural", r.clean_route


def test_a_blank_answer_on_plain_paper_is_fine():
    """Flat on flat is not giving up, it is the right answer — a bubble
    interior is one colour and so is a good fill of it."""
    page, r = _run(True, _white)
    assert page.clean_stats.get("neural") == 1, page.clean_stats
    assert not page.clean_stats.get("fell back"), page.clean_stats


# --------------------------------------------------------------- the measure

def _mask(shape, box):
    m = np.zeros(shape[:2], np.uint8)
    x, y, w, h = box
    m[y:y + h, x:x + w] = 255
    return m


def test_the_two_numbers_are_the_ring_and_the_answer():
    """`_gave_up` on its own, so what it measures is written down: the detail
    OUTSIDE the mask on the page that went in, and the detail INSIDE the mask
    in what came back."""
    busy = np.zeros((120, 120, 3), np.uint8)
    for y in range(0, 120, 6):
        busy[y:y + 3, :] = 200
    plain = np.full((120, 120, 3), 240, np.uint8)
    m = _mask(busy.shape, (40, 40, 40, 40))
    blank = np.full((120, 120, 3), 255, np.uint8)

    assert I._gave_up(busy, blank, m) is True          # detail out, nothing in
    assert I._gave_up(plain, blank, m) is False        # nothing out either
    assert I._gave_up(busy, busy, m) is False          # detail in as well


def test_nothing_to_compare_against_is_not_giving_up():
    """A mask with no ring around it — one that fills its own window — cannot
    be judged, and an unjudgeable answer is accepted rather than thrown away."""
    busy = np.zeros((40, 40, 3), np.uint8)
    for y in range(0, 40, 6):
        busy[y:y + 3, :] = 200
    m = np.full((40, 40), 255, np.uint8)
    blank = np.full((40, 40, 3), 255, np.uint8)
    assert I._gave_up(busy, blank, m) is False


def test_an_empty_mask_is_not_giving_up():
    busy = np.zeros((60, 60, 3), np.uint8)
    busy[::6] = 200
    m = np.zeros((60, 60), np.uint8)
    assert I._gave_up(busy, np.full((60, 60, 3), 255, np.uint8), m) is False
