"""The box round a sound effect covers the sound effect.

lee, with six screenshots of a red rectangle with the ends of a brush stroke
sticking out of it: *"the sfx is doing well but its still just sligthly miiing
the edge of them"*.

Measured on his chapter 1, all 67 pages, 240 boxes:

    39% of the 82 sound-effect boxes have ink running more than a twentieth
    of the box outside them.  1% of the 151 dialogue boxes do.

The block head boxes printed type properly. It is the drawn effects that get
clipped, because their box comes off the segmentation mask or off CRAFT, and
neither of those measures where the brush went - only where it most looked like
writing. And that 39% is a floor: the measure only counted a mark as the box's
own if the box already held half of it, so page 003's 쿵, where the box covers
about a quarter of the stroke, was recorded as spilling nothing.

**Growing a box to its ink has been tried before and made things worse.** On
page 8 the はら box grew from (729,26,86,261) to (709,0,126,342), taking in the
balloon edge and the girl's hair; on page 13 the ぽん box slid off the writing
and onto the birdcage below it. The difference here is a SHARE rule - a mark is
only followed if the box already holds that fraction of it, so a balloon wall
clipping the corner, a hairline crossing it, a panel rule touching its edge are
none of them the box's to follow.

At 0.40, over all 82 sound-effect boxes: 55 grow, median 1.17x, ninetieth
percentile 2.06x. The 30 biggest were cropped and looked at one at a time and
every one covers the effect where the old box cut it.

The runaway guard is a share of the PAGE and not a multiple of the box, because
that is what the failure is - the reasoning `craft_cap` is written on, that a
rectangle this big is a panel and not writing. A multiple was tried first and
it is the wrong shape: page 039's effect needs 6.1x and lands at 5.1% of the
page, which is fine, while page 043's box is already a fifth of the page and
2.2x takes it to a half, which is not. At 0.12 the first grows and the second
does not.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT

MANHWA = CT.TUNING["manhwa"]


def _page(h=600, w=600, fill=255):
    return np.full((h, w), fill, np.uint8)


def _stroke(g, x, y, w, h, v=0):
    g[y:y + h, x:x + w] = v
    return g


# ------------------------------------------------------------- the numbers

def test_the_share_and_the_cap_are_the_measured_ones():
    assert MANHWA["sfx_grow"] == 0.40
    assert MANHWA["sfx_grow_cap"] == 0.12
    assert CT.TUNING["manhua"]["sfx_grow"] == 0.40


def test_manga_does_not_grow():
    """The clipping was measured on a Korean webtoon. Manga's numbers were
    measured separately and nothing here re-measured them."""
    assert CT.TUNING["manga"]["sfx_grow"] is None


# ---------------------------------------------------------------- the rule

def test_a_clipped_box_grows_to_the_whole_stroke():
    """A box over the middle half of one stroke. It holds half the mark, so
    the mark is its to follow, and it follows it to both ends."""
    g = _page()
    _stroke(g, 100, 100, 200, 40)                 # the stroke, 100..300
    box = (150, 100, 100, 40)                     # the middle half of it
    bb, mask = CT._grow_to_the_stroke(g, box, 0.40, 0.12)
    assert bb[0] <= 100 and bb[0] + bb[2] >= 300, bb
    assert mask is not None and int(mask.sum()) > 0


def test_a_mark_the_box_barely_touches_is_not_followed():
    """The failure the old attempt hit. A balloon wall crossing the corner of
    the box is not the box's mark, however long it is."""
    g = _page()
    _stroke(g, 100, 100, 60, 60)                  # the effect, inside the box
    _stroke(g, 170, 0, 12, 600)                   # a wall past its corner
    box = (96, 96, 90, 68)                        # ...and the box clips the wall
    bb, mask = CT._grow_to_the_stroke(g, box, 0.40, 0.12)
    assert mask is None and bb == box, \
        "the box followed the wall off the page: %r" % (bb,)


def test_the_share_is_what_makes_that_work():
    """The same geometry with the share dropped to a tenth follows the wall -
    so the test above is measuring the share and not something else about the
    fixture."""
    g = _page()
    _stroke(g, 100, 100, 60, 60)
    _stroke(g, 170, 0, 12, 600)
    bb, _m = CT._grow_to_the_stroke(g, (96, 96, 90, 68), 0.02, 0.99)
    # Not the wall's full 600: the search window only reaches one box-width
    # out, which is its own guard. 68 pixels tall becoming 240 is the wall.
    assert bb[3] > 200, "the loose share should have taken the wall: %r" % (bb,)


def test_a_grow_past_the_page_share_is_refused():
    g = _page()
    _stroke(g, 10, 10, 580, 580)                  # a mark filling the page
    box = (200, 200, 100, 100)
    bb, mask = CT._grow_to_the_stroke(g, box, 0.05, 0.12)
    assert bb == box and mask is None


def test_the_cap_is_a_share_of_the_page_not_a_multiple_of_the_box():
    """The same box and the same stroke, on a small page and a large one. A
    multiple of the box cannot tell those apart; a share of the page can, and
    the page is what decides whether a rectangle is a panel."""
    small = _page(250, 250)
    _stroke(small, 20, 100, 200, 40)
    big = _page(1200, 1200)
    _stroke(big, 20, 100, 200, 40)
    box = (70, 100, 100, 40)
    on_small, _ = CT._grow_to_the_stroke(small, box, 0.40, 0.12)
    on_big, _ = CT._grow_to_the_stroke(big, box, 0.40, 0.12)
    assert on_small == box, \
        "the grown 8000px is 13%% of a 250x250 page: %r" % (on_small,)
    assert on_big[2] >= 200, \
        "...and 0.6%% of a 1200x1200 one: %r" % (on_big,)


def test_white_strokes_are_found_too():
    """A sound effect is as often white with a coloured outline as black, and
    `gray < 110` finds nothing at all in that case."""
    g = _page(fill=20)
    _stroke(g, 100, 100, 200, 40, v=255)
    box = (150, 100, 100, 40)
    bb, _m = CT._grow_to_the_stroke(g, box, 0.40, 0.12)
    assert bb[0] <= 100 and bb[0] + bb[2] >= 300, bb


def test_a_box_that_already_fits_is_left_alone():
    """No grow, and `None` for the mask, so the caller knows not to touch the
    region at all."""
    g = _page()
    _stroke(g, 200, 200, 60, 60)
    box = (192, 192, 76, 76)
    bb, mask = CT._grow_to_the_stroke(g, box, 0.40, 0.12)
    assert bb == box and mask is None


def test_the_mask_comes_back_with_the_rest_of_the_stroke():
    """The text mask doubles as what the cleaner paints out. A box that covers
    the effect over a mask that does not would leave the tail of it on the
    page - worse than the clipping, because nothing on screen says so."""
    g = _page()
    _stroke(g, 100, 100, 200, 40)
    _bb, mask = CT._grow_to_the_stroke(g, (150, 100, 100, 40), 0.40, 0.12)
    assert mask[110, 110] > 0, "the part outside the old box is not in the mask"
    assert mask[110, 280] > 0


def test_the_padding_is_applied_outside_the_grown_box():
    g = _page()
    _stroke(g, 100, 100, 200, 40)
    a, _ = CT._grow_to_the_stroke(g, (150, 100, 100, 40), 0.40, 0.12, pad=0)
    b, _ = CT._grow_to_the_stroke(g, (150, 100, 100, 40), 0.40, 0.12, pad=8)
    assert b[0] == a[0] - 8 and b[2] == a[2] + 16, (a, b)


def test_the_share_is_measured_against_the_MARK_and_not_the_box():
    """Two different questions, and only one of them is right. A mark the box
    holds most of is the box's mark however small the mark is next to the box;
    a mark that happens to fill a lot of the box is not the box's, if the box
    holds a sliver of it. Here the box holds 60% of the mark and the mark is
    14% of the box."""
    g = _page(900, 900)
    _stroke(g, 100, 300, 500, 20)             # a long thin mark, 10000px
    box = (100, 240, 300, 140)                # holding 300x20 = 6000 of it
    bb, _m = CT._grow_to_the_stroke(g, box, 0.40, 0.30)
    assert bb[2] >= 500, "60%% of the mark is the box's to follow: %r" % (bb,)


def test_it_never_leaves_the_page():
    g = _page()
    _stroke(g, 400, 560, 200, 40)             # hard against the bottom-right
    bb, _m = CT._grow_to_the_stroke(g, (460, 560, 100, 40), 0.40, 0.12, pad=8)
    assert bb[0] >= 0 and bb[1] >= 0
    assert bb[0] + bb[2] <= 600 and bb[1] + bb[3] <= 600, bb


# ------------------------------------------- and through the real function

INPUT = CT.INPUT


class _Net:
    """comic-text-detector, minus the 95MB and the neural net. No blocks, and
    a mask with one patch on it, so `_harvest` makes one `sfx` region and
    everything after it runs for real."""

    def __init__(self, patches):
        self.patches = patches

    def setInput(self, blob):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["blk", "seg"]

    def forward(self, names):
        blk = np.zeros((1, 1, 6), np.float32)
        seg = np.zeros((1, 1, INPUT, INPUT), np.float32)
        for x0, y0, x1, y1 in self.patches:
            seg[0, 0, y0:y1, x0:x1] = 1.0
        return [blk, seg]


def _run(monkeypatch, page, patch, **kw):
    from mangatl.models import Page

    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([patch]))
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                               mask_thresh=0.2, join_x=1.8, join_y=0.9,
                               classify=False, second_opinion=False, **kw)


def test_the_region_really_widens(monkeypatch):
    """A 1024-square page, so it letterboxes to nothing and the mask lands
    where it was put. One stroke, and the mask over only its middle."""
    g = _page(1024, 1024)
    _stroke(g, 200, 500, 500, 60)
    got = _run(monkeypatch, g, (400, 500, 600, 560), sfx_grow=0.40,
               sfx_grow_cap=0.5)
    assert len(got) == 1 and got[0].kind == "sfx"
    x, _y, w, _h = [int(v) for v in got[0].bbox]
    assert x <= 200 and x + w >= 700, got[0].bbox


def test_with_the_grow_off_it_stays_clipped(monkeypatch):
    """The other half of the fixture: without the grow this same page comes
    back clipped, so the test above is measuring the grow."""
    g = _page(1024, 1024)
    _stroke(g, 200, 500, 500, 60)
    got = _run(monkeypatch, g, (400, 500, 600, 560), sfx_grow=None)
    x, _y, w, _h = [int(v) for v in got[0].bbox]
    assert x > 200 and x + w < 700, got[0].bbox


def test_the_cleaner_gets_the_rest_of_the_stroke(monkeypatch):
    """`text_mask` is what Clean paints out. A box that covers the effect over
    a mask that does not leaves the tail of it on the page and nothing on
    screen says so - worse than the clipping lee reported."""
    g = _page(1024, 1024)
    _stroke(g, 200, 500, 500, 60)
    got = _run(monkeypatch, g, (400, 500, 600, 560), sfx_grow=0.40,
               sfx_grow_cap=0.5)
    m = np.asarray(got[0].text_mask)
    assert m[520, 250] > 0, "the far end of the stroke is not in the mask"
    assert m[520, 680] > 0


def test_the_widened_box_keeps_its_breathing_room(monkeypatch):
    """Every box gets `PAD` round it so nothing clips, and a box just widened
    to the exact edge of the ink needs it most."""
    g = _page(1024, 1024)
    _stroke(g, 200, 500, 500, 60)
    got = _run(monkeypatch, g, (400, 500, 600, 560), sfx_grow=0.40,
               sfx_grow_cap=0.5)
    x, _y, w, _h = [int(v) for v in got[0].bbox]
    assert x <= 200 - CT.PAD and x + w >= 700 + CT.PAD, got[0].bbox


# ---------------------------------------------------------- where it is used

def test_a_sound_effect_grows_on_its_own_number():
    """This used to read `if r.kind != "sfx": continue` - nothing else was
    allowed to grow at all, on the strength of the 1% above.

    That 1% was the wrong measurement, and lee found the box it missed: the
    measure only counted a mark as the box's own if the box already held HALF
    of it, and his em dash is a nine-pixel tail on a mark the box holds 92% of.
    Dialogue grows now too, on `text_grow` and a much higher share - see
    `test_the_whole_run_of_writing.py`. What this holds is that the two are
    still two: the loose 0.40 measured on brush strokes is for the brush
    strokes, and nothing else picks it up."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    at = src.index("_grow_to_the_stroke(gray, r.bbox")
    loop = src[src.rindex("for r in regions", 0, at):at]
    assert 'sfx_grow if r.kind == "sfx" else text_grow' in loop, loop


def test_the_grow_runs_before_the_duplicate_check():
    """Two clipped boxes on one effect can grow into each other, and the pair
    should then come out as one box rather than two overlapping ones."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    assert (src.index("_grow_to_the_stroke(gray, r.bbox")
            < src.index("_drop_duplicates(regions)"))


def test_it_is_off_unless_the_format_asks():
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    assert "sfx_grow: float = None" in src
