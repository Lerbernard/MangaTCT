"""Black balloons are found the same way white ones are.

lee, with a screenshot of each — a white oval holding a black HUH?, and an eye
with a flat black speech shape inside it holding a white ...HUH? :

> *can you do a tecting for black bubbles like teh white bubbles*

Every balloon test in `detect/` reads `gray <= 128` as ink and the rest as
paper, which is a white balloon with dark typesetting. A black balloon's
interior IS ink by that definition, so it is never a run of paper to begin
with, and `_interior_ok`'s `mean >= 190` would refuse it even if it were. The
block still gets found — comic-text-detector's segmentation head sees white
typesetting perfectly well — it just arrives with no balloon and, because the
ring around it reads as artwork, labelled outside text.

The fix is not a new threshold. It is the same search run a second time on
`255 - gray` for the blocks the first pass left with nothing. Every test the
upright pass applies — enclosed, the right size, a flat fill, no drawn edges
in it — applies unchanged to the negative, where it means "a flat DARK fill".
Coordinates and masks land on the same pixels either way.

The pages here are drawn rather than loaded, so the tests run everywhere and
say which property broke.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect.balloon import BalloonConfig, attach_balloons
from mangatl.models import TextRegion

H, W = 300, 260

# How far apart the hatch lines over the eye are drawn, and it is not a free
# choice. The lines are what stops the eye's own dark from being one run of
# paper with the balloon's on the negative — `_free_labels` dilates ink by
# `close_px` on every side, so a one-pixel line seals a five-pixel gap and no
# more. Drawn at 5 the balloon comes back clean: 0.6% of what it takes lies
# outside the drawn shape. Drawn at 7 the seal fails and the run leaks out
# along the eye's dark bands, and the shape comes back 25% too big — a thin
# filigree spanning the whole eye that every plausibility test passes, because
# it IS flat and dark and enclosed. That is a real limit of this approach, not
# a fixture artefact, and `test_sparse_hatching_leaks_and_this_says_so` pins
# it so it is a known number rather than a surprise.
HATCH_GAP = 5


def _white_page():
    """lee's first screenshot: a white oval on a light page, dark typesetting."""
    page = np.full((H, W), 210, np.uint8)
    for x in range(0, W, 6):                    # a strip of hatched art on top
        cv2.line(page, (x, 0), (x - 40, 70), 120, 2)
    cv2.ellipse(page, (215, 140), (60, 90), 0, 0, 360, 235, -1)
    cv2.ellipse(page, (110, 160), (78, 66), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (110, 160), (78, 66), 0, 0, 360, 20, 3)
    return page


def _black_page():
    """lee's second screenshot: a hatched dark eye with a flat black speech
    shape inside it."""
    page = np.full((H, W), 250, np.uint8)
    eye = np.zeros((H, W), np.uint8)
    cv2.ellipse(eye, (125, 155), (105, 110), 0, 0, 360, 255, -1)
    page[eye > 0] = 25
    for y in range(20, H, HATCH_GAP):           # the hatching over the eye
        line = np.zeros((H, W), np.uint8)
        cv2.line(line, (0, y), (W, y - 30), 255, 1)
        page[(line > 0) & (eye > 0)] = 215
    cv2.ellipse(page, (125, 155), (60, 74), 0, 0, 360, 8, -1)   # the balloon
    return page


def _dark_art_page():
    """White typesetting straight onto TEXTURED dark artwork — a real free
    shout, and it must stay one."""
    page = np.full((H, W), 30, np.uint8)
    for y in range(0, H, 5):
        cv2.line(page, (0, y), (W, y - 40), 190, 1)
    for x in range(0, W, 11):
        cv2.line(page, (x, 0), (x + 30, H), 70, 2)
    cv2.circle(page, (45, 45), 26, 200, -1)
    return page


def _flat_grey_page():
    """A flat mid-grey panel. Dark-ish, uniform, and not a balloon."""
    return np.full((H, W), 120, np.uint8)


def _write(page, cx, cy, rows, cols, light, gap=13):
    """A block of typesetting, drawn as marks so the fixtures carry no font."""
    ink = np.zeros_like(page)
    x0 = cx - (cols * gap) // 2
    y0 = cy - (rows * gap) // 2
    for r in range(rows):
        for c in range(cols):
            x, y = x0 + c * gap, y0 + r * gap
            cv2.rectangle(ink, (x, y), (x + 8, y + 9), 255, -1)
    page[ink > 0] = 245 if light else 15
    return ink


def _region(ink, kind, rid=1):
    x, y, w, h = cv2.boundingRect((ink > 0).astype(np.uint8))
    return TextRegion(id=rid, bbox=(x, y, w, h), bubble_bbox=(x, y, w, h),
                      text_mask=ink, bubble_mask=None, kind=kind)


def _white_case(kind="bubble"):
    page = _white_page()
    ink = _write(page, 110, 160, 3, 5, light=False)
    return page, _region(ink, kind)


def _black_case(kind="freefloat"):
    page = _black_page()
    ink = _write(page, 125, 155, 3, 5, light=True)
    return page, _region(ink, kind)


# ------------------------------------------------------- the two screenshots

def test_a_white_balloon_is_still_found_the_way_it_always_was():
    """The upright pass, untouched. If this ever needs the negative to pass,
    something has been broken rather than added to."""
    page, r = _white_case()
    assert attach_balloons(page, [r]) == 1
    assert r.bubble_mask is not None
    assert r.kind == "bubble"
    # the balloon, not the box: it reaches well outside the block's own ink
    x, y, w, h = r.bbox
    assert float((r.bubble_mask > 0).sum()) > 1.15 * w * h
    # …and what it took is the oval that was drawn, not the page around it.
    # (The typesetting is inside the mask — `_filled` fills the glyph holes on
    # purpose — so the drawn shape is the truth here, not the pixel values.)
    got = r.bubble_mask > 0
    shape = np.zeros((H, W), np.uint8)
    cv2.ellipse(shape, (110, 160), (75, 63), 0, 0, 360, 1, -1)
    shape = shape > 0
    assert float((got & shape).sum()) / float(shape.sum()) > 0.9
    assert float((got & ~shape).sum()) / float(got.sum()) < 0.05


def test_a_black_balloon_is_found_on_the_negative():
    page, r = _black_case()
    assert attach_balloons(page, [r]) == 1
    assert r.bubble_mask is not None
    x, y, w, h = r.bbox
    assert float((r.bubble_mask > 0).sum()) > 1.15 * w * h
    # It really is the black SHAPE and not the eye around it: nearly every
    # pixel it took is the balloon's own flat fill, and the eye's dark bands
    # and hatching are not.
    got = r.bubble_mask > 0
    shape = np.zeros((H, W), bool)
    cv2.ellipse(shape.view(np.uint8), (125, 155), (60, 74), 0, 0, 360, 1, -1)
    shape = shape.view(np.uint8) > 0
    assert float((got & shape).sum()) / float(shape.sum()) > 0.9
    assert float((got & ~shape).sum()) / float(got.sum()) < 0.05


def test_sparse_hatching_leaks_and_this_says_so():
    """The known limit, pinned rather than hidden.

    Draw the eye's hatching further apart than the ink dilation can seal and
    the run of dark reaches out of the balloon along the bands between the
    lines. What comes back is flat, dark, enclosed and the right size, so
    every plausibility test passes it — it is simply a quarter bigger than the
    balloon, as a filigree spanning the eye.

    Nothing here fixes that. It is written down so that a change which makes
    it worse is visible, and one which fixes it fails this test and gets to
    delete it."""
    page = np.full((H, W), 250, np.uint8)
    eye = np.zeros((H, W), np.uint8)
    cv2.ellipse(eye, (125, 155), (105, 110), 0, 0, 360, 255, -1)
    page[eye > 0] = 25
    for y in range(20, H, 7):                   # too far apart to seal
        line = np.zeros((H, W), np.uint8)
        cv2.line(line, (0, y), (W, y - 30), 255, 1)
        page[(line > 0) & (eye > 0)] = 215
    cv2.ellipse(page, (125, 155), (60, 74), 0, 0, 360, 8, -1)
    ink = _write(page, 125, 155, 3, 5, light=True)
    r = _region(ink, "freefloat")
    assert attach_balloons(page, [r]) == 1
    got = r.bubble_mask > 0
    shape = np.zeros((H, W), np.uint8)
    cv2.ellipse(shape, (125, 155), (60, 74), 0, 0, 360, 1, -1)
    shape = shape > 0
    assert float((got & shape).sum()) / float(shape.sum()) > 0.9   # still all of it
    spill = float((got & ~shape).sum()) / float(got.sum())
    assert 0.15 < spill < 0.35, spill            # ...plus about a quarter again
    # …and the spill is the eye's flat dark, never its hatching. A mask that
    # started swallowing the drawn lines would be a different failure.
    assert float((page[got & ~shape] < 60).mean()) > 0.99


def test_the_block_in_it_stops_being_called_outside_text():
    """On a black balloon the "is there paper round this?" ring reads as
    artwork, so the block arrives labelled free text. Finding a balloon around
    it answers that question better than the ring did."""
    page, r = _black_case(kind="freefloat")
    assert attach_balloons(page, [r]) == 1
    assert r.kind == "bubble", r.kind


def test_the_upright_pass_promotes_too_now():
    """Promotion used to belong to the inverted pass alone, and a free-floating
    block on a WHITE page was not even looked at.

    lee: *"when you lable a bubble i want you ta do a very quick text that try
    to find teh bubble if it fins teh bubble then lable it a bubble box"*. The
    rule was already here for black balloons; a block turning out to be inside
    a balloon is better evidence than the ring test that called it free,
    whichever polarity found it. See `test_the_balloon_may_name_the_box.py` for
    the measurement, and for the half of his sentence that is NOT here."""
    page, r = _white_case(kind="freefloat")
    assert attach_balloons(page, [r]) == 1
    assert r.kind == "bubble", r.kind


def test_a_caption_keeps_its_name_either_way():
    """Promotion renames free text and nothing else. A caption found in a
    balloon is still a caption — the person said what it was."""
    page, r = _white_case(kind="narration")
    assert attach_balloons(page, [r]) == 1
    assert r.bubble_mask is not None            # it still gets its shape...
    assert r.kind == "narration"                # ...and keeps its name
    page, r = _black_case(kind="narration")
    assert attach_balloons(page, [r]) == 1
    assert r.bubble_mask is not None
    assert r.kind == "narration"


# ---------------------------------------------------------- and when it must not

def test_typesetting_on_textured_dark_art_gets_nothing():
    """The case the whole thing has to be safe for. Hatching cuts the dark
    into strips, so there is no enclosed run of it, and it carries drawn edges
    the flat-fill test refuses. Neither pass finds anything, and the block
    stays outside text."""
    page = _dark_art_page()
    ink = _write(page, 125, 155, 3, 5, light=True)
    r = _region(ink, "freefloat")
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None
    assert r.kind == "freefloat"


def test_a_flat_grey_panel_is_not_a_balloon():
    """Flat and dark-ish is not enough — a balloon is ENCLOSED. This panel
    runs to the page edge, so there is nothing round the block at all."""
    page = _flat_grey_page()
    ink = _write(page, 125, 155, 3, 5, light=True)
    r = _region(ink, "freefloat")
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None
    assert r.kind == "freefloat"


def test_a_sound_effect_is_left_alone_on_either_pass():
    """Sound effects have no balloon and never wanted one: the ink's own
    footprint is where they belong. A white one drawn over a black panel must
    not be swept up by the new pass."""
    page = _black_page()
    ink = _write(page, 125, 155, 3, 5, light=True)
    r = _region(ink, "sfx")
    assert attach_balloons(page, [r]) == 0
    assert r.bubble_mask is None
    assert r.kind == "sfx"


def test_a_block_that_already_has_a_balloon_is_not_searched_again():
    """The inverted pass is a rescue, not a second opinion. Whatever the
    upright pass decided stands."""
    page, r = _black_case()
    assert attach_balloons(page, [r]) == 1
    was = r.bubble_mask.copy()
    assert attach_balloons(page, [r]) == 0
    assert np.array_equal(r.bubble_mask, was)


# ------------------------------------------------------------- two in one

def test_two_blocks_in_one_black_balloon_divide_it():
    """A split bubble is a split bubble whichever way round the ink is. Both
    blocks must come back with their own share, or the two speeches are
    typeset on top of each other."""
    page = _black_page()
    cv2.ellipse(page, (125, 155), (66, 96), 0, 0, 360, 8, -1)   # room for two
    a = _write(page, 125, 110, 2, 5, light=True)
    b = _write(page, 125, 200, 2, 5, light=True)
    ra, rb = _region(a, "freefloat", 1), _region(b, "freefloat", 2)
    assert attach_balloons(page, [ra, rb]) == 2
    ma, mb = ra.bubble_mask > 0, rb.bubble_mask > 0
    assert ma.any() and mb.any()
    both = float((ma & mb).sum())
    assert both <= 0.02 * min(float(ma.sum()), float(mb.sum())), both
    for r, m in ((ra, ma), (rb, mb)):           # each keeps its own writing
        own = r.text_mask > 0
        assert float((m & own).sum()) / float(own.sum()) > 0.8, r.id


# ------------------------------------------------------------- end to end

def test_the_black_balloon_typesets_bigger_and_in_white():
    """What lee is actually looking at. Without the balloon the English is
    squeezed into the footprint of the writing it replaces; with it the block
    gets the balloon, and the colour picker — which already read the
    background and needed no changing — sets it white on black."""
    from mangatl import render, typeset
    from mangatl.models import Page

    def _letter(find_it):
        page, r = _black_case()
        if find_it:
            attach_balloons(page, [r])
        r.dst_text = "WHAT WAS THAT NOISE?"
        img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
        p = Page(image=img)
        p.original = img.copy()
        p.regions = [r]
        cfg = typeset.TypesetConfig(font_path=typeset.default_font_path(),
                                    min_font=10, max_font=30)
        typeset.typeset_page(p, cfg, redo=True)
        render.assign_colours(p, cfg)
        return r

    without = _letter(False)
    with_it = _letter(True)
    assert with_it.layout.font_size > without.layout.font_size, (
        without.layout.font_size, with_it.layout.font_size)
    assert with_it.layout.fg == "#ffffff", with_it.layout.fg
    assert with_it.layout.edge == "#000000", with_it.layout.edge
    assert " ".join(with_it.layout.lines) == "WHAT WAS THAT NOISE?"


# --------------------------------------------------------------- the config

def test_the_two_passes_share_one_set_of_rules():
    """No second, looser set of numbers for dark balloons.

    Proved by loosening them: a flat MID-GREY enclosed blob does not get a
    balloon SHAPE, and the only thing that says so is
    `min_interior_brightness` — 255 minus 112 is 143, and the rule wants 190.
    Drop the rule to 120 and the same blob comes back with a shape.

    So if the inverted pass is ever given its own gentler config to make lee's
    page work, this test fails, which is the point: that is exactly how
    artwork starts becoming balloons.

    THE LABEL IS A SEPARATE QUESTION AND IT DOES CHANGE HERE. This blob is
    flat, enclosed and round, so `_shut_in_a_round_wall` calls it a bubble —
    see `test_a_wall_of_sharp_change.py`. That is not this test being sanded
    down to fit: the two are different claims and both are still checked below.
    A grey ellipse with writing in it really is a balloon nine times out of
    ten, the cost of being wrong about the name is one keypress, and no shape
    is handed to the typesetter on the strength of it — which is the thing this
    test was written to protect."""
    import copy

    def _grey_blob():
        page = np.full((H, W), 245, np.uint8)
        cv2.ellipse(page, (125, 155), (72, 86), 0, 0, 360, 112, -1)
        ink = _write(page, 125, 155, 3, 4, light=True)
        return page, _region(ink, "freefloat")

    page, r = _grey_blob()
    assert attach_balloons(page, [r], BalloonConfig()) == 0
    assert r.bubble_mask is None, "no SHAPE may come from a grey blob"

    loose = copy.copy(BalloonConfig())
    loose.min_interior_brightness = 120
    page, r = _grey_blob()
    assert attach_balloons(page, [r], loose) == 1, \
        "the brightness rule no longer decides; this test proves nothing"


def test_a_balloon_found_by_the_rescue_pass_is_renamed_too():
    """Renaming happens in one place, after both searches, and not beside each
    `_apply`. This black balloon's outline has a gap in it, so the page-wide
    pass loses the run of dark out into the page and only `_second_pass` — the
    one that seals the hole — finds it. It still has to come back a bubble."""
    from mangatl.detect import balloon as mod

    page = _black_page()
    # A dark channel from the balloon out to the page edge — the black-balloon
    # version of the broken tail `_local_balloon` exists for. The run of dark
    # now reaches the border, so the page-wide pass throws it out.
    cv2.line(page, (125, 155 + 70), (125, H - 1), 8, 4)
    ink = _write(page, 125, 140, 3, 5, light=True)
    r = _region(ink, "freefloat")

    rescued = []
    real = mod._second_pass
    mod._second_pass = lambda g, t, c: (lambda n: (rescued.append(n), n)[1])(
        real(g, t, c))
    try:
        assert attach_balloons(page, [r]) == 1
    finally:
        mod._second_pass = real
    assert rescued and rescued[-1] == 1, \
        f"the page-wide pass found it; this test proves nothing ({rescued})"
    assert r.bubble_mask is not None
    assert r.kind == "bubble", r.kind
