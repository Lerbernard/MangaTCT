"""A balloon you can only see by its EDGE, because its inside is artwork.

lee, page 023 of his chapter 1: a soft grey disc on a starfield, holding two
lines of dialogue, boxed as **Outside text**. And then, after both obvious
fixes had been measured and thrown out::

    for detecting teh fuzy eadge can you make it si that it looks for a
    drasticaky high cang in color from teh backgorund its at right no and if
    teh change is in circularish shape it shoud be a ballon tetx

He is right, and the reason is exact. **Everything that existed asked about the
balloon's FILL** - is it bright (`min_interior_brightness`), is it flat
(`max_interior_std`), is it free of drawing (`max_edge_density`). That page is a
disc with a starfield and a planetary ring **drawn across it**. Every fill
question answers "artwork", and answers correctly. Its fill measures 150
against a floor of 190, its edge density 0.030 against a bar of 0.018.

**TWO FIXES WERE MEASURED FIRST AND BOTH ARE DEAD.** Written down because both
look obvious and someone will suggest them again:

*Lower the ring test's brightness bar.* Killed by page 037. 부웅, a hand-drawn
sound effect over pale buildings, has a ring median of **136**; this balloon's
is **106**. The sound effect is BRIGHTER than the balloon, so no brightness bar
anywhere separates them.

*Lower `min_interior_brightness`.* Measured at 190, 160, 140, 120 and 100
across 43 pages: **zero boxes change kind at any value.** The edge-density
guard refuses the disc regardless, so the floor was never the blocker.

lee's rule never looks at the fill. It asks whether a hard edge SHUTS around
the writing and whether the thing it shuts is roundish - and a starfield
painted on the balloon disturbs neither question.

MEASURED over 128 boxes on 43 pages of chapter 1:

    kind         boxes   a closed wall   ...and elliptical
    bubble          60        47                45
    narration       16        14                14
    freefloat        3         1                 1     <- page 023, wanted
    sfx             49         5                 4

Only free-floating blocks are renamed, so the only boxes this can act on are
that third row - three of them, and exactly the right one fires. The two that
must not move find no closed wall at all.

**The label only.** No `bubble_mask` is set, so the English is still laid out
in the text box. Saying what a box IS and deciding where the words GO are two
questions, and only the first one has been measured here.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import balloon as B
from mangatl.detect.balloon import attach_balloons
from mangatl.models import TextRegion


def _page(h=520, w=520, fill=250):
    return np.full((h, w), fill, np.uint8)


def _ink(page, x, y, w=110, h=40):
    m = np.zeros(page.shape, np.uint8)
    for i in range(3):
        cv2.rectangle(page, (x, y + i * 14), (x + w, y + i * 14 + 7), 20, -1)
        cv2.rectangle(m, (x, y + i * 14), (x + w, y + i * 14 + 7), 255, -1)
    return m


def _region(mask, kind="freefloat"):
    ys, xs = np.nonzero(mask)
    bb = (int(xs.min()), int(ys.min()),
          int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1)
    return TextRegion(id=0, bbox=bb, text_mask=mask, bubble_mask=None,
                      bubble_bbox=bb, kind=kind)


def _grey_disc_on_a_dark_page(fill=150, sky=25, art=True):
    """Page 023 in miniature: a mid-grey oval with a hard rim, on a dark sky,
    with artwork drawn ON the oval so no fill test can accept it.

    The artwork has to be FAITHFUL, and getting it wrong is how this fixture
    lied twice. Fat stars (radius 3) and a hard 3-pixel planet ring both become
    ~20-pixel bars once the wall is sealed and thickened, and a bar across the
    disc cuts the region in two - so the fixture said the rule failed when the
    real page says it works. On the page the stars are single pixels and the
    ring is a soft glow, so the wall sees neither. Written that way here.
    """
    page = np.full((520, 520), sky, np.uint8)
    cv2.ellipse(page, (260, 250), (170, 120), 0, 0, 360, fill, -1)
    cv2.ellipse(page, (260, 250), (170, 120), 0, 0, 360, 10, 7)
    if art:
        rng = np.random.RandomState(4)
        for _ in range(60):                          # the starfield
            px, py = rng.randint(110, 410), rng.randint(140, 360)
            if ((px - 260) / 170.0) ** 2 + ((py - 250) / 120.0) ** 2 < 0.75:
                cv2.circle(page, (px, py), 1, 235, -1)
        lay = page.copy()                            # the planet ring, soft
        cv2.line(lay, (120, 380), (400, 120), 190, 9)
        lay = cv2.GaussianBlur(lay, (31, 31), 0)
        page = np.where((page > 100) & (lay > page), lay, page).astype(np.uint8)
    return page, _region(_ink(page, 200, 230))


# ------------------------------------------------------ the case it exists for

def test_a_grey_balloon_with_artwork_on_it_is_called_a_bubble():
    page, r = _grey_disc_on_a_dark_page()
    attach_balloons(page, [r])
    assert r.kind == "bubble", r.kind


def test_the_old_tests_still_refuse_it_which_is_why_this_exists():
    """The control, and the whole argument in one assertion: every fill test
    says artwork, and they are not wrong - there IS artwork on it."""
    page, r = _grey_disc_on_a_dark_page()
    cfg = B.BalloonConfig()
    _n, labels = B._free_labels(page, cfg)
    lab = B._surrounding_label(labels, r.text_mask)
    assert lab > 0, "the disc is not even a run of paper"
    mask, outer = B._filled(labels, lab)
    assert mask is not None
    assert not B._plausible(page, mask, outer, cfg), \
        "if the fill tests accept this, the fixture is not the hard case"


def test_the_label_changes_and_the_layout_does_not():
    """It says what the box is. It does not hand the typesetter a shape that
    nothing has measured for that job."""
    page, r = _grey_disc_on_a_dark_page()
    attach_balloons(page, [r])
    assert r.kind == "bubble"
    assert r.bubble_mask is None


# ------------------------------------------------------------ and what it won't

def test_writing_on_open_artwork_stays_outside_text():
    """Page 004: a mark on the art, nothing shut around it."""
    page = np.full((520, 520), 90, np.uint8)
    rng = np.random.RandomState(7)
    for _ in range(60):
        p1 = (rng.randint(0, 520), rng.randint(0, 520))
        p2 = (rng.randint(0, 520), rng.randint(0, 520))
        cv2.line(page, p1, p2, int(rng.randint(20, 230)), rng.randint(2, 9))
    r = _region(_ink(page, 200, 230))
    attach_balloons(page, [r])
    assert r.kind == "freefloat"


def test_a_wall_that_does_not_close_is_not_a_balloon():
    """Two thirds of an oval. The inside leaks out to the page, and a shape you
    can walk out of is not something the writing is inside."""
    page = np.full((520, 520), 30, np.uint8)
    cv2.ellipse(page, (260, 250), (170, 120), 0, 200, 480, 240, 6)
    r = _region(_ink(page, 200, 230))
    attach_balloons(page, [r])
    assert r.kind == "freefloat"


def test_a_long_thin_slot_is_not_roundish():
    """`WALL_CIRC` earning itself: shut, but nothing like a balloon.

    Asked of `_round_wall_around` and not of `attach_balloons`, because a long
    slot with a flat pale fill is a perfectly good ENCLOSURE - the ordinary
    pass finds it and promotes it, correctly, before this rule is ever
    reached. What is being measured here is only the roundness gate.
    """
    page = np.full((520, 520), 30, np.uint8)
    cv2.rectangle(page, (20, 215), (500, 285), 240, 5)
    r = _region(_ink(page, 200, 235, w=110, h=30))
    assert not B._round_wall_around(page, r.bbox)


def test_a_sound_effect_is_never_renamed():
    """Even drawn straight across a balloon. Only free text is promoted."""
    page, r = _grey_disc_on_a_dark_page()
    r.kind = "sfx"
    attach_balloons(page, [r])
    assert r.kind == "sfx"


def test_a_caption_is_never_renamed():
    page, r = _grey_disc_on_a_dark_page()
    r.kind = "narration"
    attach_balloons(page, [r])
    assert r.kind == "narration"


def test_a_box_that_already_found_a_balloon_is_left_to_it():
    """The ordinary pass is the better answer when it has one; this runs after
    it and only on what it left behind."""
    page = _page()
    cv2.ellipse(page, (260, 250), (170, 120), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (260, 250), (170, 120), 0, 0, 360, 0, 3)
    r = _region(_ink(page, 200, 230))
    attach_balloons(page, [r])
    assert r.kind == "bubble"
    assert r.bubble_mask is not None, \
        "a white balloon must still come back with its shape"


# ------------------------------------------------------------------ the numbers

def test_the_thresholds_are_the_measured_ones():
    assert (B.WALL_LO, B.WALL_HI) == (30, 90)
    assert B.WALL_SEAL == 15
    assert B.WALL_FIT == 0.85
    assert B.WALL_CIRC == 0.50


def test_the_wall_has_to_be_thicker_than_canny_draws_it():
    """The bug this nearly shipped with, kept as a test because it is invisible
    by inspection.

    Canny returns a curve that is 8-connected, and a 4-connected fill walks
    straight through the diagonal steps of one. On a clean drawn oval the
    sealed wall came back 987 pixels for a 940-pixel perimeter - a single thin
    line - and the inside joined the outside through it, so a perfectly closed
    balloon read as open. It only worked on lee's own page by luck, because fur
    is thick. One dilation fixes it.
    """
    import inspect
    src = inspect.getsource(B._round_wall_around)
    assert "cv2.dilate(e, np.ones((3, 3)" in src
    page, r = _grey_disc_on_a_dark_page(art=False)
    assert B._round_wall_around(page, r.bbox), \
        "a plain drawn oval must be found; if not, the wall is leaking again"


def test_it_runs_after_both_of_the_ordinary_passes():
    import inspect
    src = inspect.getsource(B.attach_balloons)
    assert src.index("_attach(255 - gray") < src.index("_shut_in_a_round_wall")
