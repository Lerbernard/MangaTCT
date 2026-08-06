"""The ghost sweep's second go at a region is a second ATTEMPT, not a second
layer.

lee, with a screenshot of a black balloon on a real page: *"teh clesning is
bad"* — the rectangle of the region came back visibly grainier than the smooth
black around it, with faint residue of the Japanese still in it.

`_sweep_ghosts` gives a region the model drew one more go with a wider mask,
because the usual reason a ghost survives is that a sliver of the stroke was
never inside the mask. That is right. What was wrong is what the model was
shown: `_run_neural` reads `out`, and by the time the sweep runs `out` already
holds the first answer. So the model was asked to redraw its own
reconstruction — two stacked generations, each adding its own noise floor,
which over a flat black fill is exactly a grainy rectangle. And the fence
trims the plate to the boxes without a ramp, so the difference ends as a crisp
rectangular edge rather than fading out.

Handed the original page, the retry answers the same question it was asked the
first time, with more room. Only the part under the FIRST mask goes back —
everything else in the context window may be a neighbour's finished cleaning.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion
from mangatl.typeset import _font, default_font_path

H, W = 260, 220


def _black_balloon():
    """A flat black balloon with white typesetting in it — the hard case."""
    page = np.full((H, W), 245, np.uint8)
    cv2.ellipse(page, (110, 130), (95, 105), 0, 0, 360, 8, -1)
    p = Image.fromarray(page)
    ImageDraw.Draw(p).text((110, 125), "CHI\nCHI",
                           font=_font(default_font_path(), 30), fill=250,
                           anchor="mm", align="center")
    page = np.array(p)
    sel = np.zeros((H, W), bool)
    sel[85:175, 55:170] = True
    tm = np.zeros((H, W), np.uint8)
    tm[(page >= 200) & sel] = 255
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="bubble", text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    return page, tm, r


def _half_hearted(seen, seed=1):
    """A cleaner that leaves half the typesetting standing, so the ghost sweep
    always comes back for a second go — and records what it was shown."""
    rng = np.random.default_rng(seed)

    def fake(sub, mask):
        seen.append(sub.copy())
        out = sub.copy()
        m = mask > 0
        half = m.copy()
        half[::2] = False
        out[half] = (8, 8, 8)
        n = rng.normal(0, 6, out.shape).astype(np.int16)
        return np.clip(out.astype(np.int16) + np.where(m[..., None], n, 0),
                       0, 255).astype(np.uint8)
    return fake


def _run(seed=1):
    page, tm, r = _black_balloon()
    seen = []
    bgr = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    pg = Page(image=bgr.copy())
    pg.original = bgr.copy()
    pg.regions = [r]
    I.inpaint_page(pg, neural=_half_hearted(seen, seed))
    return page, tm, r, seen


def test_the_sweep_really_does_come_back():
    """The premise. If a ghost stopped triggering a retry, everything below
    would pass by never running."""
    _page, _tm, _r, seen = _run()
    assert len(seen) == 2, len(seen)


def test_the_retry_is_shown_the_page_and_not_the_first_answer():
    """The fix, stated as what the model receives. The two calls see exactly
    the same pixels — the second is a fresh attempt at the original problem,
    not a pass over a reconstruction."""
    _page, _tm, _r, seen = _run()
    assert len(seen) == 2
    assert np.array_equal(seen[0], seen[1]), \
        "the retry was shown the model's own output"


def test_the_typesetting_is_back_under_the_mask_for_the_retry():
    """Not just "the same" — the same as the PAGE. A retry shown a blank where
    the words were has nothing to work from and no reason to do better."""
    page, tm, _r, seen = _run()
    assert len(seen) == 2
    grey = cv2.cvtColor(seen[1], cv2.COLOR_BGR2GRAY).astype(np.int16)
    # the second call's window still contains bright typesetting on black
    assert int((grey >= 200).sum()) > 200, int((grey >= 200).sum())


def test_only_this_regions_own_mask_goes_back_to_the_page():
    """The limit on the restore, stated exactly.

    Under the region's FIRST mask the model is shown the page as it arrived.
    Everywhere else in the context window it is shown the plate, because
    everywhere else may be another box's finished cleaning and putting the
    page back over that would undo a neighbour's work. Asserted straight at
    `_run_neural` — one call, two pictures, and every pixel accounted for."""
    plate = np.full((120, 140, 3), 90, np.uint8)      # "already cleaned"
    original = np.full((120, 140, 3), 200, np.uint8)  # the page as it arrived
    win = (slice(30, 80), slice(40, 100))
    m = np.zeros((50, 60), np.uint8)
    m[10:40, 15:45] = 255
    job = {"win": win, "mask": m, "tight": m}

    seen = []

    def neural(sub, mask):
        seen.append(sub.copy())
        return sub.copy()

    I._run_neural(plate.copy(), job, neural, extra=5, again=original)
    assert len(seen) == 1
    sub = seen[0]
    ctx = I._grow(win, plate.shape, I.NEURAL_CTX)
    back = np.zeros(sub.shape[:2], bool)
    back[win[0].start - ctx[0].start: win[0].stop - ctx[0].start,
         win[1].start - ctx[1].start: win[1].stop - ctx[1].start] = m > 0
    assert back.any() and (~back).any()
    assert (sub[back] == 200).all(), "the page did not go back under the mask"
    assert (sub[~back] == 90).all(), "the plate was overwritten outside it"


def test_the_first_pass_is_shown_the_plate_as_it_stands():
    """…and without `again` nothing is restored at all, which is what the
    first pass wants: the page has not been touched there yet, and the plate
    IS the page."""
    plate = np.full((120, 140, 3), 90, np.uint8)
    win = (slice(30, 80), slice(40, 100))
    m = np.zeros((50, 60), np.uint8)
    m[10:40, 15:45] = 255
    seen = []
    I._run_neural(plate.copy(), {"win": win, "mask": m, "tight": m},
                  lambda sub, mask: (seen.append(sub.copy()), sub.copy())[1])
    assert len(seen) == 1
    assert (seen[0] == 90).all()
