"""The balloon rescue: giving a block of text the bubble it sits in.

comic-text-detector reports TEXT, not balloons, so every region it hands back
has ``bubble_mask=None`` and the fitter falls through to the footprint of the
Japanese — a tall narrow column. Typesetting English into that column is what
produced 8-12pt type inside a 200px bubble. ``attach_balloons`` walks back out
from the ink to the outline around it.

These pages are drawn here rather than loaded, so the tests run everywhere and
say exactly which property broke.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect.balloon import BalloonConfig, attach_balloons
from mangatl.models import TextRegion

H, W = 700, 520


def _page():
    """A light page with a strip of busy artwork along the bottom."""
    page = np.full((H, W), 246, np.uint8)
    rng = np.random.default_rng(7)
    art = rng.integers(0, 255, (160, W), dtype=np.uint8)
    page[H - 160:, :] = cv2.resize(art, (W, 160), interpolation=cv2.INTER_NEAREST)
    return page


def _balloon(page, cx, cy, ax, ay):
    """Draw an outlined oval bubble and return its interior as a mask."""
    cv2.ellipse(page, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (cx, cy), (ax, ay), 0, 0, 360, 20, 3)
    inner = np.zeros_like(page)
    cv2.ellipse(inner, (cx, cy), (ax - 3, ay - 3), 0, 0, 360, 255, -1)
    return inner


def _column(page, cx, top, bot):
    """A column of vertical Japanese: tall, narrow, and nothing like a bubble."""
    ink = np.zeros_like(page)
    for y in range(top, bot, 22):
        cv2.rectangle(ink, (cx - 7, y), (cx + 7, y + 15), 255, -1)
    page[ink > 0] = 15
    return ink


def _region(ink, kind="bubble", rid=1):
    x, y, w, h = cv2.boundingRect((ink > 0).astype(np.uint8))
    return TextRegion(id=rid, bbox=(x, y, w, h), bubble_bbox=(x, y, w, h),
                      text_mask=ink, bubble_mask=None, kind=kind)


# ------------------------------------------------------------ finding a balloon

def test_a_block_of_text_is_given_the_balloon_around_it():
    page = _page()
    truth = _balloon(page, 250, 200, 130, 95)
    ink = _column(page, 250, 130, 265)
    r = _region(ink)

    assert attach_balloons(page, [r]) == 1, "no balloon found around the text"
    got = r.bubble_mask > 0
    want = truth > 0
    iou = (got & want).sum() / max(1, (got | want).sum())
    assert iou > 0.85, f"balloon recovered but wrong shape (IoU {iou:.2f})"


def test_the_balloon_is_far_wider_than_the_column_of_japanese():
    """The point of the whole pass: horizontal English needs the width."""
    page = _page()
    _balloon(page, 250, 200, 130, 95)
    ink = _column(page, 250, 130, 265)
    r = _region(ink)
    text_w = r.bbox[2]

    attach_balloons(page, [r])
    assert r.place_mask() is r.bubble_mask
    assert r.bubble_bbox[2] > 3 * text_w, (
        "the fitter is still being handed a narrow column: balloon %dpx wide, "
        "text %dpx" % (r.bubble_bbox[2], text_w))


def test_the_balloon_is_stored_as_geometry_so_it_survives_a_save():
    """A chapter persists polygons, not bitmaps (see project.region_record)."""
    page = _page()
    _balloon(page, 250, 200, 130, 95)
    r = _region(_column(page, 250, 130, 265))

    attach_balloons(page, [r])
    assert r.polygon and len(r.polygon) >= 3, "balloon would be lost on reload"
    rebuilt = np.zeros_like(page)
    cv2.drawContours(rebuilt, [np.array(r.polygon, np.int32)], -1, 255, cv2.FILLED)
    a, b = rebuilt > 0, r.bubble_mask > 0
    assert (a & b).sum() / max(1, (a | b).sum()) > 0.95


# ------------------------------------------------------------- split bubbles

def test_two_blocks_in_one_balloon_each_get_their_own_half():
    """A split bubble must typeset BOTH blocks, not stack them on each other."""
    page = _page()
    _balloon(page, 250, 200, 150, 95)
    left = _region(_column(page, 190, 140, 260), rid=1)
    right = _region(_column(page, 310, 140, 260), rid=2)

    assert attach_balloons(page, [left, right]) == 2, "a block got no share"
    a, b = left.bubble_mask > 0, right.bubble_mask > 0
    assert not (a & b).any(), "the two blocks would be typeset on top of each other"
    assert (a & (left.text_mask > 0)).sum() > 0.9 * (left.text_mask > 0).sum()
    assert (b & (right.text_mask > 0)).sum() > 0.9 * (right.text_mask > 0).sum()
    for r, share in ((left, a), (right, b)):
        assert share.sum() > 1.15 * r.bbox[2] * r.bbox[3], (
            "share %d is no bigger than the text box it replaces" % r.id)


def test_stacked_blocks_are_cut_straight_across_not_diagonally():
    """The real split bubble: the second column of Japanese sits both LEFT of
    and BELOW the first, because columns read right-to-left. Dividing that by
    nearest ink draws a DIAGONAL line through the balloon, and a diagonal edge
    costs the fitter the width of every line it letters — it measures the
    narrowest row under each line, so a wedge prices out a size or two smaller
    than the paper really allows. Each stacked block must get the balloon's
    full width across its own rows."""
    page = _page()
    truth = _balloon(page, 250, 220, 150, 130)
    upper = _region(_column(page, 320, 110, 210), rid=1)
    lower = _region(_column(page, 180, 240, 330), rid=2)

    assert attach_balloons(page, [upper, lower]) == 2, "a block got no share"
    a, b = upper.bubble_mask > 0, lower.bubble_mask > 0
    assert not (a & b).any(), "the two blocks would be typeset on top of each other"
    for r, share in ((upper, a), (lower, b)):
        rows = np.nonzero(share.any(axis=1))[0]
        # Across the middle of its own band the share must be as wide as the
        # balloon is there. A wedge fails this by construction. The band's own
        # ends are left out: where the oval turns over, the outline and the
        # hairline gap take a few rows off, which costs real width on a steep
        # curve and has nothing to do with how the balloon was divided.
        for y in rows[len(rows) // 3:2 * len(rows) // 3]:
            got = int(share[y].sum())
            want = int((truth[y] > 0).sum())
            assert got > 0.90 * want, (
                "share %d is a wedge: %dpx of the balloon's %dpx at row %d"
                % (r.id, got, want, y))


def test_the_two_shares_between_them_use_up_the_balloon():
    page = _page()
    truth = _balloon(page, 250, 200, 150, 95)
    left = _region(_column(page, 190, 140, 260), rid=1)
    right = _region(_column(page, 310, 140, 260), rid=2)

    attach_balloons(page, [left, right])
    used = (left.bubble_mask > 0) | (right.bubble_mask > 0)
    assert used.sum() > 0.75 * (truth > 0).sum(), "most of the bubble went unused"


# ------------------------------------------------------------------- restraint

def test_text_lying_on_artwork_is_left_alone():
    """No balloon there. Inventing one would typeset over the drawing."""
    page = _page()
    r = _region(_column(page, 250, H - 140, H - 30))
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None, "artwork was mistaken for a bubble"


def test_a_hatched_panel_is_not_paper():
    """Light, flat, enclosed and the right shape — but it is a drawing.

    Everything the shape checks look at says bubble here. Only the drawn
    edges inside it say otherwise, so this is what stops the fitter from
    typesetting across artwork.
    """
    page = _page()
    cv2.rectangle(page, (110, 110), (390, 300), 245, -1)
    cv2.rectangle(page, (110, 110), (390, 300), 20, 3)
    for x in range(115, 388, 6):
        cv2.line(page, (x, 113), (x, 297), 150, 1)
    r = _region(_column(page, 250, 150, 260))

    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None, "hatched artwork was mistaken for a bubble"


def test_a_balloon_no_roomier_than_the_text_box_is_not_worth_taking():
    """Nothing is gained, so nothing changes — the old behaviour stands."""
    page = _page()
    cv2.rectangle(page, (150, 150), (270, 240), 250, -1)
    cv2.rectangle(page, (150, 150), (270, 240), 20, 3)
    ink = np.zeros_like(page)
    for y in range(158, 234, 8):
        for x in range(158, 264, 8):
            cv2.rectangle(ink, (x, y), (x + 2, y + 2), 255, -1)
    page[ink > 0] = 15
    r = _region(ink)

    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None


def test_sound_effects_are_never_given_a_balloon():
    """An sfx belongs on its own ink, wherever it was drawn."""
    page = _page()
    _balloon(page, 250, 200, 130, 95)
    r = _region(_column(page, 250, 130, 265), kind="sfx")
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None


def test_a_region_that_already_knows_its_balloon_is_not_touched():
    page = _page()
    _balloon(page, 250, 200, 130, 95)
    r = _region(_column(page, 250, 130, 265))
    r.bubble_mask = np.zeros_like(page)
    r.bubble_mask[190:210, 240:260] = 255
    before = r.bubble_mask.copy()
    assert attach_balloons(page, [r]) == 0
    assert np.array_equal(r.bubble_mask, before)


def test_text_on_the_open_page_gets_nothing():
    """No outline around it, so the paper here is the whole page."""
    page = np.full((H, W), 250, np.uint8)
    r = _region(_column(page, 250, 200, 320))
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None, "the page itself was handed over as a bubble"


def test_a_bubble_packed_with_japanese_is_still_a_bubble():
    """Shape is judged on the balloon, not on the paper left between glyphs.

    Half the inside of a busy bubble is ink. Measuring the bare paper makes
    that bubble look ragged and unsolid — and it is the one that needs the
    rescue most, because its text footprint fills the balloon.
    """
    page = _page()
    truth = _balloon(page, 250, 200, 130, 95)
    ink = np.zeros_like(page)
    for x in range(140, 360, 20):
        cv2.rectangle(ink, (x, 132), (x + 12, 268), 255, -1)
    ink[cv2.erode(truth, np.ones((9, 9), np.uint8)) == 0] = 0
    page[ink > 0] = 15
    r = _region(ink)
    covered = (ink > 0).sum() / max(1, (truth > 0).sum())
    assert 0.35 < covered < 0.60, "fixture no longer models a packed bubble"

    assert attach_balloons(page, [r]) == 1, "a bubble full of text was rejected"
    got, want = r.bubble_mask > 0, truth > 0
    assert (got & want).sum() / max(1, (got | want).sum()) > 0.85


def test_a_blank_page_is_survivable():
    page = np.full((H, W), 250, np.uint8)
    ink = np.zeros_like(page)
    ink[100:120, 100:140] = 255
    r = _region(ink)
    attach_balloons(page, [r], BalloonConfig())   # must not raise
    assert r.bubble_mask is None


# ------------------------------------------------- a balloon with a hole in it

def _leaky_balloon(page, cx, cy, ax, ay, gap=8):
    """An oval whose outline stops short of closing, as a drawn tail does.

    A tail is two strokes that do not meet, and where a balloon sits over a
    gutter that opening lets its white interior run straight out into the page
    margin. `gap` is the hole in pixels. Returns the interior the typesetting is
    entitled to.
    """
    cv2.ellipse(page, (cx, cy), (ax, ay), 0, 0, 360, 252, -1)
    cv2.ellipse(page, (cx, cy), (ax, ay), 0, 0, 360, 20, 3)
    # Wipe a short stretch of the outline at the bottom: the hole.
    cv2.circle(page, (cx + int(ax * 0.25), cy + int(ay * 0.96)),
               gap // 2 + 2, 252, -1)
    inner = np.zeros_like(page)
    cv2.ellipse(inner, (cx, cy), (ax - 3, ay - 3), 0, 0, 360, 255, -1)
    return inner


def test_a_balloon_whose_outline_has_a_hole_in_it_is_still_found():
    """Thirteen of twenty-seven misses on the sample chapter were this.

    The block is not sitting on artwork and it is not in a shape that fails the
    checks — its balloon simply leaks. The paper it is embedded in is then the
    page background, which is thrown out (rightly: nothing that reaches the
    page edge is a balloon), and the block is left with no placement area at
    all. Bridging the hole closes the balloon again.
    """
    page = _page()
    truth = _leaky_balloon(page, 250, 200, 130, 95)
    r = _region(_column(page, 250, 130, 265))

    assert attach_balloons(page, [r]) == 1, "the leaking balloon was not rescued"
    got, want = r.bubble_mask > 0, truth > 0
    iou = (got & want).sum() / max(1, (got | want).sum())
    assert iou > 0.75, f"balloon recovered but wrong shape (IoU {iou:.2f})"
    assert r.bubble_bbox[2] > 3 * r.bbox[2], (
        "still typesetting into a narrow column: balloon %dpx, text %dpx"
        % (r.bubble_bbox[2], r.bbox[2]))


def test_the_rescue_does_not_hand_a_leaking_balloon_back_shrunken():
    """Bridging the hole means dilating the ink, which eats the edges.

    A wide hole needs a heavy seal, and a heavy seal takes a band off the whole
    inside of the balloon — a fifth of it here. Those pixels are room the
    typesetting is entitled to, so they have to be given back: grown into paper
    only, so the shape stops against the drawn outline instead of stepping
    over it and typesetting across the artwork behind.
    """
    page = _page()
    truth = _leaky_balloon(page, 250, 250, 175, 165, gap=26)
    r = _region(_column(page, 250, 170, 330))

    assert attach_balloons(page, [r]) == 1
    got = int((r.bubble_mask > 0).sum())
    want = int((truth > 0).sum())
    assert got > 0.92 * want, (
        "the seal kept %d%% of the balloon and never gave the rest back"
        % (100 * got // max(1, want)))
    # And it stopped at the outline rather than spilling past it.
    assert int(((r.bubble_mask > 0) & (truth == 0)).sum()) < 0.05 * want, (
        "the give-back stepped outside the balloon")


def test_two_blocks_in_one_leaking_balloon_still_get_a_half_each():
    """The rescue runs per block, so both come back with the SAME balloon.

    Applied as found, each would claim the whole thing and the two blocks of
    English would be typeset on top of each other.
    """
    page = _page()
    truth = _leaky_balloon(page, 250, 250, 180, 170)
    upper = _region(_column(page, 310, 140, 230), rid=1)
    lower = _region(_column(page, 190, 270, 360), rid=2)

    assert attach_balloons(page, [upper, lower]) == 2, "a block got no share"
    a, b = upper.bubble_mask > 0, lower.bubble_mask > 0
    assert not (a & b).any(), "the two blocks would be typeset on top of each other"
    for r, share in ((upper, a), (lower, b)):
        assert (share & (r.text_mask > 0)).sum() > 0.9 * (r.text_mask > 0).sum(), (
            "share %d does not even cover its own block" % r.id)
    assert (a | b).sum() > 0.70 * (truth > 0).sum(), "most of the bubble went unused"


def test_the_rescue_does_not_invent_a_balloon_around_text_on_artwork():
    """Sealing harder must not turn a scrap of gutter into a bubble."""
    page = _page()
    r = _region(_column(page, 250, H - 140, H - 30))
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None, "artwork was sealed into a bubble"


def test_the_rescue_does_not_hand_over_the_open_page():
    page = np.full((H, W), 250, np.uint8)
    r = _region(_column(page, 250, 200, 320))
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None, "the page itself was sealed into a bubble"
