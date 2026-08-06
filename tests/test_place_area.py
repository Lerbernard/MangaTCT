"""Where the English is allowed to sit.

The text box says WHICH balloon a block of dialogue belongs to. It does not say
what shape the typesetting has to be — the balloon does. Three things used to
confuse the two, and each of them put English inside the little rectangle drawn
round the Japanese instead of inside the bubble the reader can see:

* a balloon whose outline has a small hole in it (usually the tail) is not
  found at all, because its interior runs out of the hole and joins the page;
* a region with no balloon fell back to the FOOTPRINT of the Japanese, which is
  a tall narrow column with holes in it, and not to its box;
* masks are not saved, so a region reloaded from disk rebuilt its "balloon"
  from whatever polygon was stored — and for a hand-drawn or hand-tightened
  box that polygon is a rectangle.

These pages are drawn here rather than loaded, so the tests run everywhere.
"""
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import TextRegion

H, W = 700, 520


def _page():
    return np.full((H, W), 246, np.uint8)


def _column(page, cx, top, bot):
    """A column of vertical Japanese: tall, narrow, and full of holes."""
    ink = np.zeros_like(page)
    for y in range(top, bot, 22):
        cv2.rectangle(ink, (cx - 7, y), (cx + 7, y + 15), 255, -1)
    page[ink > 0] = 15
    return ink


def _region(ink, kind="bubble", rid=1):
    x, y, w, h = cv2.boundingRect((ink > 0).astype(np.uint8))
    return TextRegion(id=rid, bbox=(x, y, w, h), bubble_bbox=(x, y, w, h),
                      text_mask=ink, bubble_mask=None, kind=kind)


# ------------------------------------------- no balloon: the box, not the ink

def test_speech_with_no_balloon_is_typeset_into_its_box_not_the_japanese():
    """The fallback is the BOX. The ink is the wrong shape by construction.

    Japanese runs down the page, so the footprint of the writing being replaced
    is a tall narrow column with a hole between every character. Measuring the
    room on each line of English off that shape is why speech with no balloon
    came out at single figures inside a box with room for twenty.
    """
    page = _page()
    ink = _column(page, 250, 140, 320)
    r = _region(ink)
    x, y, w, h = r.bbox

    area = r.place_mask()
    assert area is not None
    assert area is not r.text_mask, "the fitter is still measuring the Japanese"
    assert int((area > 0).sum()) == w * h, "the fallback is not the whole box"
    assert (area[y:y + h, x:x + w] > 0).all()
    assert not (area[:y] > 0).any() and not (area[y + h:] > 0).any()


def test_the_box_fallback_has_room_on_the_rows_the_ink_skipped():
    """A line of English can land in the gap between two Japanese characters.

    Measuring the ink gives those rows a width of nothing, and the fitter takes
    the narrowest row under each line — so one blank row between characters
    priced the whole line at zero and drove the type down to the floor.
    """
    page = _page()
    r = _region(_column(page, 250, 140, 320))
    x, y, w, h = r.bbox
    blank = [row for row in range(y, y + h)
             if not (r.text_mask[row] > 0).any()]
    assert blank, "fixture has no gap between characters"
    assert not (r.text_mask[blank[0]] > 0).any()
    assert int((r.place_mask()[blank[0]] > 0).sum()) == w


def test_sound_effects_with_no_balloon_still_keep_their_own_ink():
    """An sfx is drawn along an axis of its own, over artwork.

    It belongs exactly where the original was, so it is the one kind that must
    NOT be spread across the rectangle drawn round it.
    """
    page = _page()
    r = _region(_column(page, 250, 140, 320), kind="sfx")
    assert r.place_mask() is r.text_mask, (
        "sfx was handed its box instead of its own ink")


@pytest.mark.parametrize("kind", ["bubble", "freefloat", "narration"])
def test_everything_that_is_not_a_sound_effect_gets_its_box(kind):
    """Free-floating speech is speech: a block, not a tracing of the Japanese.

    It used to be lumped in with sound effects and measured against the ink,
    and that is what made lee's on-art lines both small and crooked. A stack
    of Japanese columns of unequal height has a different chord at every line,
    so the block came out as a staircase down the page; a box has one chord,
    which is the shape a paragraph belongs in.
    """
    page = _page()
    ink = _column(page, 250, 140, 320)
    r = _region(ink, kind=kind)
    x, y, w, h = r.bbox
    area = r.place_mask()
    assert area is not r.text_mask, (
        "%s is still being measured against the Japanese" % kind)
    assert int((area > 0).sum()) == w * h


def test_a_balloon_still_wins_over_the_box():
    page = _page()
    r = _region(_column(page, 250, 140, 320))
    r.bubble_mask = np.zeros_like(page)
    r.bubble_mask[100:360, 120:400] = 255
    assert r.place_mask() is r.bubble_mask


# ----------------------------------------------- reload: a rectangle is not a balloon

def _balloon_page():
    """A page with one outlined oval bubble and a column of Japanese in it."""
    page = _page()
    cv2.ellipse(page, (250, 220), (150, 110), 0, 0, 360, 252, -1)
    cv2.ellipse(page, (250, 220), (150, 110), 0, 0, 360, 20, 3)
    ink = _column(page, 250, 150, 290)
    return page, ink


def _record(ink, poly):
    x, y, w, h = cv2.boundingRect((ink > 0).astype(np.uint8))
    return {"id": 1, "bbox": [x, y, w, h], "bubble_bbox": [x, y, w, h],
            "polygon": poly, "kind": "bubble", "order": 0,
            "dst_text": "THIS FAITH EXISTS BECAUSE OF YOU, SISTER."}


def _rect_poly(ink):
    x, y, w, h = cv2.boundingRect((ink > 0).astype(np.uint8))
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_a_rectangle_polygon_is_not_loaded_back_as_a_bubble_outline():
    """What gets stored for a hand-drawn or hand-tightened box is four corners.

    Rebuilding a "balloon" from that hands the fitter the text box wearing a
    balloon's name, and there is then nothing left to tell the two apart.
    """
    from mangatl.project import region_from_record

    page, ink = _balloon_page()
    r = region_from_record(_record(ink, _rect_poly(ink)), page)
    assert r.bubble_mask is None, "a rectangle came back as a balloon outline"


def test_a_real_outline_is_still_loaded_back_as_a_bubble():
    from mangatl.project import region_from_record

    page, ink = _balloon_page()
    poly = [[int(250 + 148 * np.cos(t)), int(220 + 108 * np.sin(t))]
            for t in np.linspace(0, 2 * np.pi, 40, endpoint=False)]
    r = region_from_record(_record(ink, poly), page)
    assert r.bubble_mask is not None and r.bubble_mask.any(), (
        "a balloon found once has to survive the round trip")


def test_a_region_saved_as_a_rectangle_typesets_into_the_balloon_on_reload(tmp_path):
    """The whole point, end to end.

    Masks are not saved — a chapter is held as geometry — so the balloon has to
    be looked for again on the way back in. Without that, everything the person
    reloads is typeset inside the little box round the Japanese, which is what
    the overflowing bubble in the screenshot was.
    """
    from mangatl.project import PageState, Project

    page, ink = _balloon_page()
    src = os.path.join(str(tmp_path), "001.png")
    cv2.imwrite(src, cv2.cvtColor(page, cv2.COLOR_GRAY2BGR))

    p = Project(None, str(tmp_path / "out"))
    p.pages.append(PageState(path=src, name="001.png", width=W, height=H,
                             regions=[_record(ink, _rect_poly(ink))]))

    got = p.materialize(0).regions[0]
    assert got.bubble_mask is not None, "reloaded with no balloon at all"
    area = got.place_mask()
    x, y, w, h = got.bbox
    assert int((area > 0).sum()) > 1.15 * w * h, (
        "the placement area is still the text box: %d px against a box of %d"
        % (int((area > 0).sum()), w * h))
    # And it is the bubble that is there, not something invented around it.
    truth = np.zeros_like(page)
    cv2.ellipse(truth, (250, 220), (147, 107), 0, 0, 360, 255, -1)
    a, b = area > 0, truth > 0
    assert (a & b).sum() / max(1, (a | b).sum()) > 0.80


def test_reloading_typesets_bigger_than_the_text_box_would(tmp_path):
    """Same page, both placement areas, through the real fitter."""
    from mangatl.project import PageState, Project
    from mangatl.typeset import TypesetConfig, fit_region

    page, ink = _balloon_page()
    src = os.path.join(str(tmp_path), "001.png")
    cv2.imwrite(src, cv2.cvtColor(page, cv2.COLOR_GRAY2BGR))

    p = Project(None, str(tmp_path / "out"))
    p.pages.append(PageState(path=src, name="001.png", width=W, height=H,
                             regions=[_record(ink, _rect_poly(ink))]))
    r = p.materialize(0).regions[0]

    cfg = TypesetConfig()
    lay = fit_region(r, cfg)
    x, y, w, h = r.bbox
    box = np.zeros((H, W), np.uint8)
    box[y:y + h, x:x + w] = 255
    was = fit_region(r, cfg, mask=box)
    assert lay is not None and was is not None
    assert lay.font_size > was.font_size, (
        "typesetting the balloon is no bigger than typesetting the box "
        "(%dpt against %dpt)" % (lay.font_size, was.font_size))
