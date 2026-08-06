"""A verdict about the background has to be measured on the background.

lee, with a before-and-after of a column of vertical Japanese printed on a
girl's white cloak beside her hatched hood: *"can you look into why this
cleened like this — it jusm amde a white box insated of mathing the
backgroung"*.

`_flat_from` decides whether the paper behind a block of text is one colour,
and what colour. It samples the area with the ink stood off by
`DILATE_PX + HALO_REACH` — twelve pixels — because twelve is how far the halo
fill can reach, so the question is asked over the paper the answer will be used
to paint.

It had a fallback: if that left fewer than thirty pixels, ask again with a
THREE pixel stand-off. On a column of vertical Japanese that fallback is not a
smaller sample, it is a different question. A column's box is about thirty
pixels wide; the ink grown by twelve covers all of it, so the proper sample is
not small, it is **empty** — zero pixels, measured on the fixture below. What
answered instead was a three-pixel rim hugging the letters: the least
representative paper on the page, and on lee's crop the white cloak the words
happen to be printed on. "Flat, and white" then licenses `_with_halo` to paint
white out to nine pixels and `_sweep_ghosts` to widen that to fifteen.

So the fallback is gone. "I cannot see enough background to tell" is not "the
background is flat" — a region nobody can measure goes to the model, which is
where the hard ones belong.

What this file does NOT claim: that this was the cause of the white box in
lee's screenshot. His page has not been run here. What is claimed is measured:
the sample was empty, the rim answered in its place, and the rim's answer was
wrong about the paper the fill would touch.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion

H, W = 340, 240


def _column_page(gap=4, pad=2):
    """A white cloak, a hatched hood `gap` pixels to the right of the words,
    and a column of vertical marks with a box `pad` pixels around it."""
    img = np.full((H, W), 250, np.uint8)
    ink = np.zeros((H, W), np.uint8)
    y = 40
    while y < H - 60:
        cv2.rectangle(ink, (100, y), (130, y + 16), 255, -1)
        cv2.rectangle(ink, (106, y + 4), (124, y + 12), 0, -1)
        y += 22
    for yy in range(0, H, 7):
        for xx in range(130 + gap, W, 7):
            if (xx // 7 + yy // 7) % 2 == 0:
                cv2.rectangle(img, (xx, yy), (xx + 5, yy + 5), 105, -1)
    img[ink > 0] = 20
    x, y0, w, h = cv2.boundingRect(ink)
    box = (max(0, x - pad), max(0, y0 - pad), w + 2 * pad, h + 2 * pad)
    return img, ink, box


def _region(box, ink):
    r = TextRegion(id=9, bbox=box, kind="free", text_mask=ink,
                   bubble_mask=None, bubble_bbox=box)
    r.src_text = "やけに簡単に"
    r.dst_text = "I WONDERED WHY"
    return r


def _samples(img, ink, box):
    """(pixels at the proper stand-off, pixels in the three-pixel rim)."""
    area = np.zeros((H, W), np.uint8)
    x, y, w, h = box
    area[y:y + h, x:x + w] = 255
    wide = (area > 0) & (I._dilated(ink, I.DILATE_PX + I.HALO_REACH) == 0)
    rim = (area > 0) & (I._dilated(ink) == 0)
    return area, wide, rim


def test_a_column_box_has_no_background_to_sample():
    """The geometry, pinned. This is not a small sample, it is no sample."""
    img, ink, box = _column_page()
    _area, wide, rim = _samples(img, ink, box)
    assert int(wide.sum()) == 0, int(wide.sum())
    assert int(rim.sum()) > 300, int(rim.sum())


def test_the_rim_would_have_said_flat_and_white():
    """…and it would have been wrong about the paper the fill reaches. If the
    rim ever stops saying that on this fixture, the test below stops proving
    anything and this one says so."""
    img, ink, box = _column_page()
    _area, _wide, rim = _samples(img, ink, box)
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    px = bgr[rim]
    spread = float(px.std(axis=0).mean())
    assert spread < I.WHITE_STD, spread
    assert float(px.mean()) >= I.WHITE_LEVEL, float(px.mean())


def test_a_handful_of_pixels_is_not_a_measurement():
    """Thirty, and not one. A dozen pixels of paper can be a dozen pixels of
    anything — a fold, a stroke's skirt, the edge of a panel — and a verdict
    taken from them is the same mistake as the rim in a smaller costume."""
    img = np.full((80, 80, 3), 250, np.uint8)
    img[10:14, 10:15] = 90                     # something that is not paper
    ink = np.zeros((80, 80), np.uint8)
    ink[35:45, 35:45] = 255
    # the area is the ink's own reach and a scrap of paper beside it — twenty
    # pixels, which is what a narrow box leaves once the stand-off is honoured
    area = (I._dilated(ink, I.DILATE_PX + I.HALO_REACH) > 0).astype(np.uint8) * 255
    area[10:14, 10:15] = 255
    left = int(((area > 0) & (I._dilated(ink, I.DILATE_PX + I.HALO_REACH) == 0)
                ).sum())
    assert 0 < left < 30, left                 # a handful, and no more
    flat, bg, spread = I._flat_from(img, area, ink, None)
    assert flat is False and spread == 255.0 and not bg.any()


def test_a_textured_background_is_not_flat():
    """The measurement itself still means something. Plenty of sample, and it
    is tone rather than paper — the answer is no."""
    img = np.full((160, 160, 3), 250, np.uint8)
    for yy in range(0, 160, 6):
        for xx in range(0, 160, 6):
            if (xx // 6 + yy // 6) % 2 == 0:
                img[yy:yy + 4, xx:xx + 4] = 105
    area = np.zeros((160, 160), np.uint8)
    area[:, :] = 255
    ink = np.zeros((160, 160), np.uint8)
    ink[70:90, 70:90] = 255
    left = int(((area > 0) & (I._dilated(ink, I.DILATE_PX + I.HALO_REACH) == 0)
                ).sum())
    assert left > 1000, left                   # nothing degenerate here
    flat, _bg, spread = I._flat_from(img, area, ink, None)
    assert flat is False, (flat, spread)
    assert spread > I.FLAT_STD, spread


def test_it_answers_that_it_cannot_tell():
    img, ink, box = _column_page()
    area, _wide, _rim = _samples(img, ink, box)
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    flat, bg, spread = I._flat_from(bgr, area, ink, None)
    assert flat is False
    assert spread == 255.0, spread
    assert not bg.any()


def test_the_column_no_longer_takes_the_flat_fill():
    """End to end: this region used to be filled with one colour off a
    three-pixel rim. It is now somebody else's problem, which is the whole of
    the change."""
    img, ink, box = _column_page()
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [_region(box, ink)]
    I.inpaint_page(page)
    assert "flat fill" not in page.clean_stats, page.clean_stats


# --------------------------------------------------------- and what must not

def test_a_white_balloon_still_takes_the_flat_fill():
    """The thing the flat path is unbeatable at, and it must not be touched.
    A balloon's area is the BALLOON, so there is plenty of paper twelve pixels
    off the words and the proper sample was never in doubt."""
    img = np.full((H, W), 245, np.uint8)
    cv2.ellipse(img, (120, 170), (95, 120), 0, 0, 360, 255, -1)
    cv2.ellipse(img, (120, 170), (95, 120), 0, 0, 360, 25, 3)
    ink = np.zeros((H, W), np.uint8)
    for row, yy in enumerate((130, 160, 190)):
        cv2.rectangle(ink, (75, yy), (165, yy + 16), 255, -1)
        cv2.rectangle(ink, (82, yy + 4), (158, yy + 12), 0, -1)
    img[ink > 0] = 20
    bub = np.zeros((H, W), np.uint8)
    cv2.ellipse(bub, (120, 170), (92, 117), 0, 0, 360, 255, -1)
    x, y, w, h = cv2.boundingRect(ink)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="bubble", text_mask=ink,
                   bubble_mask=bub, bubble_bbox=(25, 50, 190, 240))
    r.src_text = "a"
    r.dst_text = "b"
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    area = bub
    flat, bg, spread = I._flat_from(bgr, area, ink, None)
    assert flat is True, (flat, spread)
    assert float(bg.mean()) >= I.WHITE_LEVEL, bg
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    I.inpaint_page(page)
    assert page.clean_stats.get("flat fill") == 1, page.clean_stats
    # …and the words really did go
    out = cv2.cvtColor(page.clean_plate, cv2.COLOR_BGR2GRAY)
    assert float((out[ink > 0] >= 235).mean()) > 0.9
