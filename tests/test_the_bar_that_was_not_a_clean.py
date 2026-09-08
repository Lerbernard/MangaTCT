"""A solid black bar where the Japanese was, and the guard that let it through.

lee, with a crop of page 1 of his own chapter - a hard black rectangle sitting
where the `SHHH` effect had been: *"i dont know if the ckenner or the amount of
step required to properly clenn it is too low but this is happening"*.

Neither, as it turned out.

## What it is not

His plate cache still holds page 1, and two of the plates in it have that
effect erased **perfectly** - fence, foliage and gradient all reconstructed. So
the cleaner can do this page, and the number of passes is not the problem.

The bar is in none of the cached plates and not in the paint layer. A plate
built while the hosted cleaner refused a box is deliberately not cached, which
is exactly the kind that never appears in the cache - so what he is looking at
is a build that failed and fell back.

## What it is

`_gave_up` exists to catch precisely this: an answer that ERASES an area rather
than redrawing it. It asks one question - *is the answer flat where its
surroundings are not?* - and needs `GAVE_UP_DETAIL` (12) levels of detail in
the ring before it will fire.

The `SHHH` box sits on the pale, smooth, sparkly gradient at the top of that
page. The ring has nothing like 12 levels in it. So the guard never fires, and
a slab that is flat ON FLAT is accepted. The comment above the constants had it
almost right - *"a flat answer on flat paper is right"* - and the word missing
was **same**: right only when it is the same flat.

That this is the failure mode is not a guess either; it is in the project
already. Seven erasers were measured on nine hard boxes off this chapter, and
`migan` produced *"a solid black blob"*.

## The number

`GAVE_UP_LEVEL = 60`, measured rather than picked. Over the 221 boxes the
cleaner paints on lee's chapter, the gap between a fill's own mean and the mean
of the ring outside it:

    every fill        mean 5.3   median 0.7   p90 15.7   max 105.2
    the FLAT ones     mean 1.6   median 0.6   p90  1.5   max  31.6

The flat ones are the only ones this clause looks at, and the worst legitimate
one in the chapter is 32 levels out. A black bar on pale paper is 150 to 200.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I

H = W = 120


def _ring_mask():
    """A mask the guard will actually measure - big enough for its ring."""
    m = np.zeros((H, W), np.uint8)
    m[40:80, 30:90] = 255
    return m


def _page(level, noise=0.0, seed=0):
    a = np.full((H, W, 3), level, np.uint8)
    if noise:
        rng = np.random.default_rng(seed)
        a = np.clip(a.astype(np.int16)
                    + rng.normal(0, noise, a.shape).astype(np.int16),
                    0, 255).astype(np.uint8)
    return a


def _filled(page, mask, level):
    out = page.copy()
    out[mask > 0] = level
    return out


# ------------------------------------------------------- the bar lee sent

def test_a_black_slab_on_pale_paper_is_a_refusal():
    """The case in the crop. Smooth surroundings, so the detail test cannot
    see it; the level is what gives it away."""
    m = _ring_mask()
    page = _page(226, noise=3.0)
    assert I._gave_up(page, _filled(page, m, 0), m)


def test_and_the_old_test_alone_would_have_let_it_through():
    """The fixture has to be one the detail test misses, or this file is
    checking a rule that was already there."""
    m = _ring_mask()
    page = _page(226, noise=3.0)
    near = I._dilated(m, I.HALO_REACH) > 0
    ring = near & ~(I._dilated(m, I.DILATE_PX) > 0)
    assert float(I._gray(page)[ring].std()) < I.GAVE_UP_DETAIL, \
        "the surroundings have detail, so the old test would fire anyway"


def test_a_white_slab_on_a_dark_panel_is_the_same_refusal():
    """The other way up, and the one lee reported the first time: *"the ai seem
    to have given up and just made teh white box"*."""
    m = _ring_mask()
    page = _page(28, noise=3.0)
    assert I._gave_up(page, _filled(page, m, 255), m)


# --------------------------------------------------- ...and what is allowed

def test_a_flat_fill_that_matches_its_paper_is_kept():
    """The whole reason the test could never just be "is it flat": inside a
    plain bubble the right answer IS flat, and it matches the paper."""
    m = _ring_mask()
    page = _page(240, noise=2.0)
    assert not I._gave_up(page, _filled(page, m, 240), m)


def test_and_it_is_kept_even_a_little_off_the_paper():
    """Measured on lee's chapter, a legitimate flat fill is within a level or
    two of its ring and the worst in the whole chapter is 32 out. Anything in
    that range has to survive."""
    m = _ring_mask()
    page = _page(240, noise=2.0)
    for off in (2, 10, 32):
        assert not I._gave_up(page, _filled(page, m, 240 - off), m), off


def test_a_redrawn_area_with_detail_in_it_is_kept():
    """A real redraw puts detail BACK, so it is not flat and none of this
    applies to it however far its mean has moved."""
    m = _ring_mask()
    page = _page(200, noise=3.0)
    rng = np.random.default_rng(1)
    out = page.copy()
    out[m > 0] = rng.integers(0, 255, (int((m > 0).sum()), 3)).astype(np.uint8)
    assert not I._gave_up(page, out, m)


def test_the_level_is_the_one_that_was_measured():
    assert I.GAVE_UP_LEVEL == 60.0, I.GAVE_UP_LEVEL
    assert I.GAVE_UP_FLAT == 4.0 and I.GAVE_UP_DETAIL == 12.0
