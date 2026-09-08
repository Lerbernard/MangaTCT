"""The R that was drawn and then deleted.

lee typeset chapter 3 himself and sent it over untouched. On page 001, in the
two-lobed balloon, a line reads::

    'EGION ARE

The R of REGION is not there and the E is cut down its left side. Nothing in
the app knew: the fitter's own containment check had passed the block, no
warning was raised, and the export is simply missing a letter.

`render_page` composites each region's typesetting through a mask - that is
the guarantee that words never land outside the box they belong to - so ink
that falls outside the mask is not clipped so much as **deleted, silently**.
Three separate things put ink there, and each of them believed it was inside:

1.  **A chord measured across a hole.** `_row_chords` reported each row of a
    mask as the span from its first set pixel to its last. For a balloon that
    is the same answer as the longest unbroken run, because a balloon interior
    is one piece. For lee's page 008 it is not: the words sit on the flat back
    of a panel with a character in it, so the mask is that flat area with her
    hair punched out of the middle, and first-to-last called a 206px chord
    across a shape whose widest usable run is 94. Three lines were set across
    it and "...I MEAN, / THIS IS ONLY / NATURAL!" lost a fifth of its ink, the
    word ONLY hollowed straight through.

2.  **A share bigger than its balloon.** `_lobe_cut` closes the union of the
    group's masks with a 9x9 kernel to bridge the detector's hairline, and a
    close fills every dent in the OUTLINE too - 330px of page 001's balloon,
    313 of them handed to the lower lobe along its outer flank.

3.  **A share the renderer had never heard of.** `share_masks` may divide a
    balloon differently from the detector - a balloon drawn as two lobes goes
    a lobe to each block, whatever the Japanese was arranged like - and the
    renderer clipped with `place_mask()`, the detector's answer. Where the two
    disagreed the words were cut back to a shape nothing had fitted them to.

Measured over lee's twelve pages: 597px of ink deleted before, 9px after. Two
of the ninety-one blocks come out differently, and only one of them smaller -
page 008's, which drops from 19pt across three lines to 14 across four, and is
whole instead of a fifth eaten. Nothing new lands on the artwork: 8px against
3px before, all of it at a neck, none of it a letter.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import render
from mangatl import typeset as T
from mangatl.models import Page, TextRegion


# ---------------------------------------------------- 1. the chord and the hole

def test_a_row_with_no_hole_reports_the_whole_of_it():
    """The common case is unchanged, to the pixel. A balloon's rows are one
    piece each, so nothing about a balloon may move."""
    m = np.zeros((5, 40), np.uint8)
    m[2, 7:31] = 1
    rows, first, last = T._row_chords(m)
    assert bool(rows[2]) and (first[2], last[2]) == (7, 30)


def test_a_row_with_a_hole_reports_the_longest_side_of_it():
    """Not 7..30 across the bite - the run a line of type could stand in."""
    m = np.zeros((5, 40), np.uint8)
    m[2, 7:14] = 1                    # 7 wide
    m[2, 20:31] = 1                   # 11 wide, and the answer
    rows, first, last = T._row_chords(m)
    assert (first[2], last[2]) == (20, 30)


def test_the_wider_side_wins_whichever_side_it_is_on():
    m = np.zeros((5, 40), np.uint8)
    m[2, 3:18] = 1                    # 15 wide, and the answer
    m[2, 24:29] = 1                   # 5 wide
    _rows, first, last = T._row_chords(m)
    assert (first[2], last[2]) == (3, 17)


def test_an_empty_row_still_says_it_has_no_room():
    """(0, -1) is what every caller in this module reads as "nothing here",
    and it has to survive the rewrite."""
    m = np.zeros((4, 20), np.uint8)
    m[1, 5:9] = 1
    rows, first, last = T._row_chords(m)
    assert not rows[0] and (first[0], last[0]) == (0, -1)
    assert not rows[3] and (first[3], last[3]) == (0, -1)


def test_an_empty_mask_answers_without_falling_over():
    rows, first, last = T._row_chords(np.zeros((6, 9), np.uint8))
    assert not rows.any() and (first == 0).all() and (last == -1).all()


def test_every_row_is_answered_separately():
    """One row's hole must not narrow another's."""
    m = np.zeros((3, 30), np.uint8)
    m[0, 2:28] = 1
    m[1, 2:10] = 1
    m[1, 18:28] = 1
    m[2, 0:30] = 1
    _rows, first, last = T._row_chords(m)
    assert (first[0], last[0]) == (2, 27)
    assert (first[1], last[1]) == (18, 27)
    assert (first[2], last[2]) == (0, 29)


def test_the_profile_measures_the_run_and_not_the_span():
    """`chord_profile` is what the fit search is handed as "room"."""
    m = np.zeros((3, 60), np.uint8)
    m[1, 4:20] = 1
    m[1, 40:56] = 1
    widths, _y0, _y1 = T.chord_profile(m)
    assert widths[1] == 16                    # not 52


# ------------------------------------------- 2. a share is a part of a balloon

def _two_lobes():
    """A balloon drawn as two overlapping ovals, with a DENT in its outline.

    The dent is the point: `_lobe_cut` closes the union to bridge the hairline
    the detector leaves between two shares, and a close fills a dent in the
    outline just as readily as a gap between the parts. lee's page 001 has one
    on the outer flank of the lower lobe, and the block was typeset into it.
    """
    H, W = 500, 600
    left = np.zeros((H, W), np.uint8)
    right = np.zeros((H, W), np.uint8)
    cv2.ellipse(left, (230, 250), (120, 150), 0, 0, 360, 255, -1)
    cv2.ellipse(right, (390, 250), (120, 150), 0, 0, 360, 255, -1)
    # the balloon as the artist drew it, before anything is taken off it
    drawn = ((left > 0) | (right > 0))
    # the hairline: the detector's division, taken off both sides
    both = (left > 0) & (right > 0)
    left[both] = 0
    right[both] = 0
    # a slot bitten into the left lobe's outer flank - narrow enough for a 9x9
    # close to bridge, long enough that bridging it hands over real paper. This
    # is the shape of the dent on lee's page 001: shallow, and 313px of it.
    left[246:252, 110:190] = 0
    drawn[246:252, 110:190] = False
    return left, right, drawn


def _regions_for(left, right, texts=("I'M SORRY, ADA...",
                                     "IT'S MY OWN WEAKNESS.")):
    out = []
    for i, (m, t) in enumerate(zip((left, right), texts)):
        ys, xs = np.nonzero(m)
        bbox = (int(xs.min()) + 30, int(ys.min()) + 40,
                int(xs.max() - xs.min()) - 60, int(ys.max() - ys.min()) - 80)
        r = TextRegion(id=i, bbox=bbox, text_mask=None, bubble_mask=m,
                       bubble_bbox=bbox, kind="bubble")
        r.order = i
        r.dst_text = t
        ink = np.zeros(m.shape, np.uint8)
        ink[bbox[1]:bbox[1] + bbox[3], bbox[0]:bbox[0] + bbox[2]] = 255
        ink[m == 0] = 0
        r.text_mask = ink
        out.append(r)
    return out


def test_no_block_is_given_the_dented_paper_outside_its_balloon():
    """A share of a balloon is a part of that balloon.

    This is the invariant lee's missing R broke: the fitter measured a shape
    that reached past the outline, and the renderer - which clips through masks
    that do not - deleted the letters standing on the difference.

    Not to the pixel. The bridging that joins the two shares reaches a few
    pixels past the rim where the seam opens onto it, and those are at the
    neck, where no line of type ends. What it may not do is swallow a dent -
    313px of flank, on lee's page. So the fixture measures its own dent and
    the share has to come in under a twentieth of it, which is the difference
    between a rounding at the neck and a bite out of the side.
    """
    left, right, drawn = _two_lobes()
    regions = _regions_for(left, right)
    closed = cv2.morphologyEx(drawn.astype(np.uint8), cv2.MORPH_CLOSE,
                              np.ones((9, 9), np.uint8)) > 0
    dent = int((closed & ~drawn).sum())
    assert dent > 100, "the fixture's dent must be worth catching"
    shares = T.share_masks(regions, T.TypesetConfig())
    assert shares, "the fixture must actually be divided, or this proves nothing"
    for rid, m in shares.items():
        outside = int(((m > 0) & ~drawn).sum())
        assert outside * 20 < dent, (
            "region %s was given %d px of paper the artist never drew, out of "
            "the %d a close would have added" % (rid, outside, dent))


def test_the_dent_in_the_outline_is_not_offered_as_room():
    """Specifically the notch. A 9x9 close fills it; the balloon does not
    have it, and neither may any share of the balloon."""
    left, right, drawn = _two_lobes()
    regions = _regions_for(left, right)
    notch = np.zeros(left.shape, bool)
    notch[247:251, 115:185] = True
    assert not (drawn & notch).any()
    for m in T.share_masks(regions, T.TypesetConfig()).values():
        assert not ((m > 0) & notch).any()


# ------------------------------ 3. the renderer clips with the shape that fitted

def test_typeset_page_tells_each_region_which_share_it_got():
    """The renderer cannot ask `share_masks` itself - it has no config and no
    business re-running a search. It is told."""
    left, right, drawn = _two_lobes()
    regions = _regions_for(left, right)
    page = Page(image=np.full((500, 600, 3), 255, np.uint8), regions=regions)
    page.clean_plate = page.image.copy()
    T.typeset_page(page, T.TypesetConfig(), redo=True)
    assert any(r.share_mask is not None for r in page.regions)


def test_a_solo_block_is_told_it_has_no_share():
    """One block alone in a balloon is typeset into the balloon, and
    `place_mask()` stays the answer for it."""
    m = np.zeros((400, 400), np.uint8)
    cv2.ellipse(m, (200, 200), (150, 110), 0, 0, 360, 255, -1)
    r = TextRegion(id=0, bbox=(120, 160, 160, 80), text_mask=None,
                   bubble_mask=m, bubble_bbox=(120, 160, 160, 80),
                   kind="bubble")
    r.order = 0
    r.dst_text = "HELLO."
    page = Page(image=np.full((400, 400, 3), 255, np.uint8), regions=[r])
    page.clean_plate = page.image.copy()
    T.typeset_page(page, T.TypesetConfig(), redo=True)
    assert r.share_mask is None


def test_the_words_are_clipped_with_the_share_and_not_the_old_mask():
    """The bug, in one page: a block fitted into a shape the renderer did not
    know about, with letters standing on the difference.

    `bubble_mask` here is deliberately the LEFT half of the balloon while the
    share is the whole of it - the same disagreement a lobe cut produces - and
    the line is set across the middle. Clipping with `bubble_mask` deletes its
    right-hand half; clipping with the share prints it whole.
    """
    H, W = 300, 500
    whole = np.zeros((H, W), np.uint8)
    cv2.ellipse(whole, (250, 150), (200, 90), 0, 0, 360, 255, -1)
    half = whole.copy()
    half[:, 250:] = 0

    r = TextRegion(id=0, bbox=(90, 120, 320, 60), text_mask=None,
                   bubble_mask=whole, bubble_bbox=(90, 120, 320, 60),
                   kind="bubble")
    r.order = 0
    r.dst_text = "THE HOT SPRINGS OF THIS REGION"
    page = Page(image=np.full((H, W, 3), 255, np.uint8), regions=[r])
    page.clean_plate = page.image.copy()
    # fitted into the whole balloon, the way a lobe cut fits a block into the
    # lobe it was given...
    T.typeset_page(page, T.TypesetConfig(), redo=True)
    assert r.layout and r.layout.lines
    # ...and the detector's own answer for this region is only half of it.
    r.bubble_mask = half

    r.share_mask = None
    cut = render.render_page(page, T.TypesetConfig())
    r.share_mask = whole
    kept = render.render_page(page, T.TypesetConfig())

    def ink(img):
        return int((img[:, :, 0] < 128).sum())

    right_of_the_seam = slice(250, W)
    assert ink(cut[:, right_of_the_seam]) == 0
    assert ink(kept[:, right_of_the_seam]) > 0
    assert ink(kept) > ink(cut)


def test_a_share_never_lets_the_words_off_the_balloon():
    """The share is what the block was fitted into, so trusting it is only
    safe while a share stays inside its balloon - which is what the tests
    above are for. Here: nothing is printed on the paper outside."""
    left, right, drawn = _two_lobes()
    regions = _regions_for(left, right)
    page = Page(image=np.full((500, 600, 3), 255, np.uint8), regions=regions)
    page.clean_plate = page.image.copy()
    T.typeset_page(page, T.TypesetConfig(), redo=True)
    out = render.render_page(page, T.TypesetConfig())
    assert not ((out[:, :, 0] < 128) & ~drawn).any()
