"""The smear in the middle of a pattern-copied box.

`shift_fill` looks for the one translation of the page whose ring - the band of
real pixels just outside the hole - best matches the ring where it lands, then
copies that block of real pixels in. Whatever the shift cannot source falls
through to Telea, which invents no texture at all.

The ring was the whole of the evidence, and that is the bug. A shift SHORTER
than the hole lands part of the hole back on **itself**: those pixels have no
source and go to Telea, while the ring, which sits entirely outside the hole,
matches perfectly and reports a flawless zero.

Measured, on period-9 vertical hatching with a 64x36 hole cut in it: the winner
was dx=18, ring score exactly 0.00. It sourced 83% of the hole and Telea blurred
the remaining 18-pixel strip - a true error of 48.9, against the 0.00 that
dy=36 was sitting there offering with the same perfect ring and nothing left
over. That grey strip through the middle of otherwise real hatching is the smear.

The fix charges the unsourced share of the hole at `rough`, the variance of the
artwork in the ring. That is the honest price of not sourcing a pixel: Telea
reproduces the local mean and none of the texture, so its squared error on
textured art is near enough that texture's variance. On flat paper the figure is
~0 and coverage stops mattering, which is right - there Telea is perfect.

Over 175 measured holes across hatching at five periods and five angles,
screentone at four pitches, line art, a panel border, gradients and paper grain:
**mean error 17.9 -> 5.2**, with not one case worse except by the noise floor on
a hole cut into pure random grain, where no fill can be right.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.inpaint import shift_fill


# ------------------------------------------------------------------- the pages

def _hatch(period, angle, H=300, W=700, dark=118, light=240):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    t = (x * np.cos(angle) + y * np.sin(angle)) / period
    g = np.where(np.abs((t % 1.0) - 0.5) < 0.24, dark, light).astype(np.uint8)
    return np.dstack([g] * 3)


def _dots(pitch=5, r=2.0, H=300, W=700, dark=90, light=245):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.hypot((x % pitch) - pitch / 2.0, (y % pitch) - pitch / 2.0)
    g = np.where(d < r, dark, light).astype(np.uint8)
    return np.dstack([g] * 3)


def _gradient(H=300, W=700):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    g = np.clip(120 + 110 * x / W, 0, 255).astype(np.uint8)
    return np.dstack([g] * 3)


def _lines(H=300, W=700):
    a = np.full((H, W, 3), 243, np.uint8)
    for k in range(-3, 4):
        cv2.line(a, (0, 120 + 40 * k), (W, 180 + 40 * k), (30, 30, 30), 3)
    return a


def _hole(truth, bw, bh, cx=300, cy=150):
    H, W = truth.shape[:2]
    m = np.zeros((H, W), np.uint8)
    m[max(0, cy - bh // 2):min(H, cy + bh // 2),
      max(0, cx - bw // 2):min(W, cx + bw // 2)] = 255
    punched = truth.copy()
    punched[m > 0] = 255
    return punched, m


def _err(out, truth, mask):
    m = mask > 0
    return float(np.abs(out.astype(np.float32)[m]
                        - truth.astype(np.float32)[m]).mean())


def _invented(out, truth, mask):
    """Pixels in the hole holding a tone the artwork does not contain.

    A copied fill can only ever put back tones that were already on the page.
    Anything else is diffusion, and on a flat two-tone pattern that is visible
    as grey haze at a glance.
    """
    tones = np.unique(truth)
    return int(np.isin(out[mask > 0], tones, invert=True).sum())


# ------------------------------------------------------------------- the tests

def test_the_short_shift_with_the_perfect_ring_no_longer_wins():
    truth = _hatch(9, 0.0)
    punched, m = _hole(truth, 64, 36)

    out = shift_fill(punched, m)

    # 42.41 before, and 4761 of the hole's 6912 values were tones that are
    # nowhere on the page - the Telea strip.
    assert _err(out, truth, m) < 0.5
    assert _invented(out, truth, m) == 0
    # ...and it is not that Telea got lucky: it is far worse than either.
    blurred = cv2.inpaint(punched, m, 5, cv2.INPAINT_TELEA)
    assert _err(blurred, truth, m) > 40


def test_screentone_comes_back_as_dots_not_as_a_grey_block():
    truth = _dots(5)
    punched, m = _hole(truth, 140, 80)

    out = shift_fill(punched, m)

    # 54.72 before, with 24000 of 33600 values invented.
    assert _err(out, truth, m) < 0.5
    assert _invented(out, truth, m) == 0


def test_smooth_shading_still_takes_the_nearer_shift():
    """The charge is scaled by the ring's variance, and this is why.

    On a gradient there is no exact answer and no texture to lose. The near
    shift is 40px off the tone and covers most of the hole; the nearest shift
    that covers ALL of it is twice as far and twice as wrong. Preferring full
    coverage outright, or charging the shortfall at any fixed price, picks the
    far one and scores 12.57. Charging it at the local variance - which on
    smooth shading is almost nothing - leaves the answer exactly where it was.
    """
    truth = _gradient()
    punched, m = _hole(truth, 140, 80)

    assert _err(shift_fill(punched, m), truth, m) < 6.0


def test_a_box_in_the_corner_of_the_page():
    """Coverage is counted for the shift that is actually about to be made.

    In the middle of a page it makes no difference which way round it is
    counted: for a tidy rectangle, going left covers exactly as much as going
    right, and the opposite shift is in the candidate list anyway. In a corner
    it is the whole story - one direction runs off the paper and the other does
    not - and counting the wrong one of the pair pushes this hole from an exact
    fill to 72.05.
    """
    truth = _hatch(7, np.pi / 2)
    punched, m = _hole(truth, 200, 26, cx=36, cy=36)

    out = shift_fill(punched, m)

    assert _err(out, truth, m) < 0.5
    assert _invented(out, truth, m) == 0


def test_a_box_against_the_edge_cannot_source_off_the_page():
    """Pixels beyond the paper are not a source, and must not be counted as one.

    The lookup has to be clamped to the page or it walks off the array, and a
    clamped read lands on the edge row - which is real, unmasked artwork, and
    would otherwise be counted as a perfectly good source. Then a shift that
    hangs half of itself over the edge of the page looks fully covered, wins,
    and delivers half a fill. On this hole that is 0.19 against 12.87.
    """
    truth = _lines()
    punched, m = _hole(truth, 40, 90, cx=676, cy=150)

    assert _err(shift_fill(punched, m), truth, m) < 4.0


def test_plain_paper_is_left_alone():
    truth = np.full((300, 700, 3), 238, np.uint8)
    punched, m = _hole(truth, 64, 36)

    assert _err(shift_fill(punched, m), truth, m) < 1.0
