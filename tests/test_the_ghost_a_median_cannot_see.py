"""A haze three grey levels off white is a readable ghost and no median sees it.

lee: *"lets forcus on manga cleaming for now"*, after fifteen of his cleaned
pages were diffed against their originals.

`_sweep_ghosts` was already the right machine - re-fill or ask the model again,
then flag what survives - and its detector could not see the thing. `ghost_delta`
compares the MEDIAN level where the ink was against the ring round it, and a
ghost at 252 against paper at 255 is three levels, under `GHOST_TOL` of six.
Lowering the tolerance to reach it fires on grain.

What a ghost has, however faint, is EDGES: it is writing. So `ghost_detail`
asks a different question with a high-pass - is anything still DRAWN here, on a
page that has nothing around it. The two are independent and either is enough:

    a thick grey smear      moves the median      ghost_delta catches it
    a three-level haze      moves neither the median nor `_gave_up`'s
                            standard deviation    only this catches it

Measured before the number was chosen, on lee's chapter 3 (23 manga pages, 252
painted areas, and the same statistic on the 15-page manhwa):

    flat surroundings          199 of 252    detail inside: median 0.02
    the 164 FLAT FILL boxes                  every one under 0.30
    everything over 0.30                     telea or pattern copy, and
                                             visibly ghosted on inspection

`GHOST_HF = 0.35` is an order of magnitude over the floor and clear of
everything the flat fill does. `GHOST_FLAT = 0.6` is the other half: past that
the artwork round the box has detail of its own, the comparison means nothing,
and this test says nothing - which is exactly the argument `_gave_up` makes in
the other direction.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I


def _page(bg=255, w=200, h=90):
    return np.full((h, w), bg, np.uint8)


def _word(img, level, thick=2):
    """Writing, or what is left of it: strokes, not a block."""
    ink = np.zeros(img.shape, np.uint8)
    for x in (30, 60, 90, 120):
        cv2.line(ink, (x, 25), (x, 65), 255, thick)
        cv2.line(ink, (x, 25), (x + 20, 25), 255, thick)
    img[ink > 0] = level
    return ink


# ------------------------------------------------------------- the measure

def test_a_faint_ghost_is_seen_where_a_median_sees_nothing():
    """252 on 255 paper. Three levels - `ghost_delta` cannot raise it and the
    eye reads the word without trying."""
    page = _page()
    ink = _word(page, 252)
    assert I.ghost_detail(page, ink) > I.GHOST_HF
    # ...and the median measure agrees it cannot see it, which is the point
    before = _page()
    _word(before, 40)
    assert I.ghost_delta(before, page, ink) <= I.GHOST_TOL


def test_a_properly_cleaned_box_says_nothing():
    page = _page()
    ink = _word(_page(), 40)          # where the ink WAS; the page is blank now
    assert I.ghost_detail(page, ink) < I.GHOST_HF


def test_a_little_grain_is_not_a_ghost():
    """Paper is not perfectly flat and a test that fires on it is a test
    nobody keeps."""
    rng = np.random.default_rng(4)
    page = np.clip(_page().astype(np.int16)
                   + rng.normal(0, 1.2, (90, 200)), 0, 255).astype(np.uint8)
    ink = _word(_page(), 40)
    assert I.ghost_detail(page, ink) < I.GHOST_HF


def test_a_dark_ghost_is_seen_too():
    """White writing left on a black panel - the manhwa case."""
    page = _page(bg=8)
    ink = _word(page, 14)
    assert I.ghost_detail(page, ink) > I.GHOST_HF


# ------------------------------------------------- and where it says nothing

def test_it_refuses_to_judge_artwork():
    """Screentone, hatching, a face. The ring has detail of its own, so
    "detail inside" means nothing - and manga is made of this."""
    rng = np.random.default_rng(7)
    page = (rng.integers(0, 2, (90, 200)) * 255).astype(np.uint8)
    ink = _word(_page(), 40)
    assert I.ghost_detail(page, ink) == 0.0


def test_the_flatness_gate_is_what_does_that():
    page = _page()
    ink = _word(page, 252)
    seen = I.ghost_detail(page, ink)
    assert seen > 0
    was = I.GHOST_FLAT
    try:
        I.GHOST_FLAT = 0.0            # nothing is flat enough to judge
        assert I.ghost_detail(page, ink) == 0.0
    finally:
        I.GHOST_FLAT = was


def test_a_box_with_no_ring_around_it_is_not_judged():
    ink = np.ones((20, 20), np.uint8) * 255
    assert I.ghost_detail(np.full((20, 20), 255, np.uint8), ink) == 0.0


# -------------------------------------------------------------- the wiring

def test_either_measure_is_enough():
    from mangatl.inpaint import _ghost_left
    page = _page()
    ink = _word(page, 252)
    before = _page()
    _word(before, 40)
    rec = {"win": (slice(0, 90), slice(0, 200)), "ink": ink, "inv": False}
    still, how = _ghost_left(before, page, rec)
    assert still and "drawn" in how


def test_the_level_measure_still_answers_first():
    """A thick smear is a ghost by the old measure and its message says so -
    the number a person reads should be the one that caught it."""
    from mangatl.inpaint import _ghost_left
    page = _page()
    ink = _word(page, 200)            # 55 levels down: loud
    before = _page()
    _word(before, 40)
    still, how = _ghost_left(before, page, {
        "win": (slice(0, 90), slice(0, 200)), "ink": ink, "inv": False})
    assert still and "levels" in how


def test_a_clean_box_reaches_neither():
    from mangatl.inpaint import _ghost_left
    page = _page()
    ink = _word(_page(), 40)
    before = _page()
    _word(before, 40)
    assert not _ghost_left(before, page, {
        "win": (slice(0, 90), slice(0, 200)), "ink": ink, "inv": False})[0]


def test_all_three_places_in_the_sweep_ask_the_same_question():
    """The re-fill, the second model call and the flag. Three copies of one
    condition is how they come apart."""
    from where import PKG
    src = (PKG / "inpaint.py").read_text(encoding="utf-8")
    body = src[src.index("def _sweep_ghosts("):]
    body = body[:body.index("\ndef ")]
    assert body.count("_ghost_left(") == 3, body.count("_ghost_left(")
    assert "ghost_delta(" not in body, "one of them still asks the old one"


def test_the_cleaner_version_was_bumped():
    """It changes PIXELS, not only flags: a box that now reads as ghosted is
    re-filled or asked of the model again. Every plate made before it has to
    retire, or the change arrives invisible on the pages being looked at.

    `>=` and not `==`: what this test is owed is that no plate predating THIS
    change is still being served, and a stamp that has moved on since keeps
    that promise. The dates sort. What guards the next change is the
    fingerprint in `test_clean_routing`, which pins the file itself."""
    assert I.ALGO >= "2026-08-22-a"


def test_the_thresholds_are_the_measured_ones():
    assert I.GHOST_HF == 0.35 and I.GHOST_FLAT == 0.6


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
