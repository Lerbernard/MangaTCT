"""Four things wrong with cleaning, all of them about WHERE.

lee, on a fresh run over 72 pages: *"very good progress was made with teh
clenning, but theer are stil some issue"* - and then five screenshots.

## 1 and 2 - a plate that was never cleaned at all

*"at no point shoud a bubble not be cleneed"*, about two gold caption plates.
There were two separate reasons, and the first one is not about gold.

**The page was cut in half and the balloon's box stayed behind.**
`_region_moved` moved `bbox`, `polygon` and the layout frames when a page is
split, and never `bubble_bbox`. On a region with no polygon that box IS the
placement area, so a plate 4056px down a 4417px page went on saying 4056 after
the cut - 1848px off the bottom of a page 2208 tall. numpy hands back an empty
slice without complaint, the mask came out empty, `text_mask` came out empty,
and nothing downstream reads that as an error: there is simply nothing to
erase. The box was silently skipped.

**And the mask could not see gold.** A bbox-only region's glyph mask is
`gray <= 128`; gold on cream is 150 to 190. Measured over the chapter, the
detector's mask holds a median **0.99** of the letter-like ink an Otsu split
finds in the same box, and 137 of 139 are over 0.95 - the two sides agree.
The two that do not are these plates, at **0.15** and **0.39**. So when the
mask holds less than `SAW_ENOUGH` of the split, the mask is not a reading of
that box and the split is used instead.

The plate's corner flourishes come back with the writing, because they are ink
on paper too, and erasing them chews the frame. `_letters_only` drops them: a
letter is about as tall as the letters beside it, and those flourishes are 53
and 43 pixels against a median glyph of 19.

## 4 - the fill walked out of the bubble

*"the box extarnt out f the bubble but the clenner shoud not mess uo teh bubble
this bad"*, with a night sky that had a white rectangle bitten out of it. The
fence at the end of `inpaint_page` allowed the box and its doorstep, and a box
is a rectangle while a balloon is not. A balloon is the page saying THE WORDS
ARE IN HERE, so nothing outside one can be that region's typesetting.

Only safe now that the mask covers the writing: it used to have bays bitten out
of it exactly where a word was, and clipping to it then would have PRESERVED
that word. See `test_no_bays_in_the_writing`.

## and - only the text, not the box

*"the ai tries to clenned everything in the box, it shoud only try to clen teh
text"*. Measured as a share of the box: the glyphs are 14.5%, the seed takes it
to 41%, the haze sweep adds a point, and `MODEL_PAD` at 6 took it to **73%**.
At 1 it is 42%, and misses no more ink. The seed stays at 3 - tried at 1, the
local fills got worse, because that 3px paints the skirt the haze sweep is
built to ignore.
"""

import cv2
import numpy as np
import pytest

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion


# --- the page was cut in half and the balloon's box stayed behind -------------

def test_the_balloon_box_moves_with_the_page_it_is_cut_onto():
    from mangatl.project import Project
    r = {"id": 0, "bbox": [10, 4056, 100, 60], "bubble_bbox": [5, 4040, 120, 100]}
    moved, _ = Project._region_moved(r, dy=2209, height=2208)
    assert moved["bubble_bbox"][1] == 4040 - 2209


def test_and_is_clamped_to_the_half_it_lands_on():
    from mangatl.project import Project
    r = {"id": 0, "bbox": [10, 2200, 100, 60], "bubble_bbox": [5, 2150, 120, 200]}
    moved, _ = Project._region_moved(r, dy=2100, height=200)
    x, y, w, h = moved["bubble_bbox"]
    assert y >= 0 and y + h <= 200


def test_a_balloon_wholly_on_the_other_half_is_dropped_not_kept():
    """Kept, it points off the page. Dropped, the reader falls back to the box
    round the writing, which is always on the page."""
    from mangatl.project import Project
    r = {"id": 0, "bbox": [10, 2300, 100, 60], "bubble_bbox": [5, 100, 120, 80]}
    moved, _ = Project._region_moved(r, dy=2209, height=2208)
    assert not moved["bubble_bbox"]
def _bubble_page():
    """A white balloon on a black sky, with writing that reaches its edge."""
    img = np.zeros((300, 400, 3), np.uint8)
    cv2.circle(img, (200, 150), 110, (255, 255, 255), -1)
    cv2.circle(img, (200, 150), 110, (0, 0, 0), 3)
    cv2.putText(img, "HELLO", (120, 165), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (0, 0, 0), 4)
    return img


def _region_with_a_box_wider_than_its_balloon(img):
    """...and a mask that reaches past the balloon, which is the whole point.

    The detector segments TEXT, not balloons, so its mask is not clipped to the
    bubble; a box drawn round writing that touches the bubble's edge catches a
    corner of whatever is outside it. Clipping the fixture's own mask to the
    balloon would test nothing.
    """
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bm = np.zeros(g.shape, np.uint8)
    cv2.circle(bm, (200, 150), 104, 255, -1)
    r = TextRegion(id=0, bbox=(60, 120, 320, 60), text_mask=None,
                   bubble_mask=bm, bubble_bbox=(96, 46, 208, 208), kind="bubble")
    box = np.zeros(g.shape, bool)
    box[120:180, 60:380] = True
    r.text_mask = (((g <= 128) & box).astype(np.uint8) * 255)
    assert ((r.text_mask > 0) & (bm == 0)).any(), "the fixture has to overhang"
    r.src_text, r.order = "a", 0
    return r


def test_a_region_with_no_balloon_box_is_untouched():
    from mangatl.project import Project
    r = {"id": 0, "bbox": [10, 2300, 100, 60]}
    moved, _ = Project._region_moved(r, dy=2209, height=2208)
    assert not moved.get("bubble_bbox")


def test_a_balloon_box_off_the_page_still_yields_a_mask():
    """The repair for a project already saved with one. Nothing rewrites a
    record, and lee's chapter has a plate that was cut before the fix existed."""
    from mangatl.project import region_from_record
    img = np.full((300, 400, 3), 255, np.uint8)
    cv2.putText(img, "AB", (120, 170), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 6)
    rec = {"id": 0, "bbox": [110, 120, 160, 70],
           "bubble_bbox": [110, 4056, 160, 70],     # off the bottom
           "polygon": [], "kind": "bubble"}
    r = region_from_record(rec, img)
    assert r.text_mask.any(), "an empty mask is a box that never gets cleaned"


def test_and_the_fallback_is_the_box_round_the_writing():
    from mangatl.project import region_from_record
    img = np.full((300, 400, 3), 255, np.uint8)
    cv2.putText(img, "AB", (120, 170), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 6)
    rec = {"id": 0, "bbox": [110, 120, 160, 70],
           "bubble_bbox": [110, 4056, 160, 70], "polygon": [], "kind": "bubble"}
    r = region_from_record(rec, img)
    ys, xs = np.where(r.text_mask > 0)
    assert 110 <= xs.min() and xs.max() < 270
    assert 120 <= ys.min() and ys.max() < 190


def test_nothing_outside_the_balloon_is_repainted():
    img = _bubble_page()
    p = Page(image=img, source_path="t.png")
    p.regions = [_region_with_a_box_wider_than_its_balloon(img)]
    out = I.inpaint_page(p, neural=None)
    bm = p.regions[0].bubble_mask
    room = cv2.dilate((bm > 0).astype(np.uint8),
                      np.ones((2 * I.GLYPH_REACH + 1,) * 2, np.uint8)) > 0
    changed = np.abs(img.astype(int) - out.astype(int)).max(2) > 2
    assert not (changed & ~room).any(), "the sky came back square"


def test_and_the_writing_inside_it_still_goes():
    img = _bubble_page()
    p = Page(image=img, source_path="t.png")
    p.regions = [_region_with_a_box_wider_than_its_balloon(img)]
    out = I.inpaint_page(p, neural=None)
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    e = lambda z: float(np.abs(cv2.Laplacian(z, cv2.CV_64F)).mean())
    assert e(g1[120:180, 110:300]) < 0.4 * e(g0[120:180, 110:300])


def test_a_region_with_no_balloon_is_still_allowed_its_whole_box():
    """A bare box has no balloon to be inside of, and clipping to `place_mask()`
    there would hand a sound effect its own ink as its fence."""
    img = np.full((200, 300, 3), 250, np.uint8)
    cv2.putText(img, "WHAM", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (10, 10, 10), 5)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    r = TextRegion(id=0, bbox=(30, 80, 240, 60), text_mask=_u8_ink(g),
                   bubble_mask=None, bubble_bbox=None, kind="sfx")
    r.src_text, r.order = "a", 0
    p = Page(image=img, source_path="t.png")
    p.regions = [r]
    out = I.inpaint_page(p, neural=None)
    assert (np.abs(img.astype(int) - out.astype(int)).max(2) > 2).any()


def _u8_ink(g):
    return ((g <= 128).astype(np.uint8) * 255)


# --- only the text, not the box ------------------------------------------------

def test_the_model_is_not_handed_most_of_the_box():
    """At 6 the mask was 73% of its box, at 2 it is 55%, and the glyphs
    themselves are 14.5%. Held at 2 and not lower because `_local_fill` has to
    stay measurably tighter than what the model is given - see
    `test_clean_says_when_it_fails`."""
    assert I.MODEL_PAD <= 2


def test_the_local_seed_is_not_cut_down_with_it():
    """It paints the skirt the haze sweep is built to ignore. Tried at 1, page
    012's plain bubble went from 7% of its writing left to 24%."""
    assert I.DILATE_PX >= 3


def test_the_local_methods_keep_their_own_slack():
    assert I.NEURAL_PAD >= I.MODEL_PAD
def test_a_glyph_poking_past_the_balloon_interior_still_comes_off():
    """The doorstep on the balloon side of the fence.

    The detected interior stops a little inside the drawn outline, and ordinary
    writing pokes past it - `glyphs_only` grows the mask by GROW_PX for the
    same reason. Fence the fill at the bare interior and the outer rim of every
    glyph that touches the edge is left standing.
    """
    img = np.full((240, 320, 3), 255, np.uint8)
    cv2.circle(img, (160, 120), 100, (255, 255, 255), -1)
    cv2.circle(img, (160, 120), 100, (0, 0, 0), 3)
    # a stroke that runs from the middle out to the outline
    cv2.rectangle(img, (150, 110), (250, 130), (10, 10, 10), -1)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bm = np.zeros(g.shape, np.uint8)
    cv2.circle(bm, (160, 120), 92, 255, -1)          # interior, 8px short
    r = TextRegion(id=0, bbox=(140, 100, 120, 40),
                   text_mask=((g <= 128).astype(np.uint8) * 255),
                   bubble_mask=bm, bubble_bbox=(68, 28, 184, 184), kind="bubble")
    r.src_text, r.order = "a", 0
    p = Page(image=img, source_path="t.png")
    p.regions = [r]
    out = I.inpaint_page(p, neural=None)
    g1 = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    # the slice of stroke that lies between the interior and the outline
    rim = (slice(112, 128), slice(253, 259))
    assert int((g[rim] <= 128).sum()) > 0, "the fixture has to have ink there"
    assert int((g1[rim] <= 128).sum()) < int((g[rim] <= 128).sum())


