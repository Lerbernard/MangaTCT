"""Two boxes lying on top of each other, and which words are in which.

lee, with a screenshot of a speech balloon and a sound effect running
diagonally underneath it: *"teh two boxes are overlapping on eacher text and
messing teh readding what can i do for this"*.

A box is a rectangle. A sound effect drawn diagonally across a panel is not,
and the rectangle round it reaches halfway into the balloon beside it. The
reader is handed that picture — two rectangles, one lying over the other, each
with a number on it — and asked which of them the words in the overlap belong
to. The picture does not answer that. So the model puts the sound effect into
the balloon's line, or the balloon's last column into the sound effect, and
whichever it picks, one of them is now wrong for the rest of the chapter.

Cleaning was never at risk: the eraser works off each region's glyph mask, so
box 13 has never rubbed out box 12's balloon. It is the READING that the
rectangle lies to.

The fix is that the reader is shown the ink instead. Each region is outlined by
the pixels it OWNS — shared ones settled once, by `_pixel_owner`, rather than
by whichever box happens to be drawn last — so the sound effect arrives as a
slanted strip and the speech as an upright block, and the two barely touch.
Neither box has to be moved for that to be true, which matters, because the
balloon's box was right all along.
"""
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import ocr
from mangatl.models import Page, TextRegion

H, W = 470, 340
RED = (0, 0, 255)
GREY = (168, 168, 168)


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def _page():
    """lee's panel: an upright block of speech, and a sound effect slanting up
    through it from the bottom left."""
    img = np.full((H, W, 3), 250, np.uint8)
    cv2.ellipse(img, (205, 175), (108, 140), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (205, 175), (108, 140), 0, 0, 360, (30, 30, 30), 2)

    speech = np.zeros((H, W), np.uint8)
    for cx in (262, 228, 194, 160, 126):          # vertical columns, right to left
        for k in range(6):
            box = (cx - 12, 60 + k * 36), (cx + 12, 60 + k * 36 + 26)
            cv2.rectangle(img, *box, (20, 20, 20), -1)
            cv2.rectangle(speech, *box, 255, -1)

    sfx = np.zeros((H, W), np.uint8)
    for k in range(9):
        at = (62 + k * 15, 445 - k * 29)
        cv2.circle(img, at, 12, (10, 10, 10), -1)
        cv2.circle(sfx, at, 12, 255, -1)

    r12 = TextRegion(id=12, bbox=_bbox(speech), text_mask=speech,
                     kind="bubble", order=0)
    r13 = TextRegion(id=13, bbox=_bbox(sfx), text_mask=sfx,
                     kind="sfx", order=1)
    return Page(image=img, regions=[r12, r13]), speech, sfx


def _rect_poly(b, g=0):
    x, y, w, h = b
    return np.array([[x - g, y - g], [x + w + g, y - g],
                     [x + w + g, y + h + g], [x - g, y + h + g]], np.int32)


def _holds(mask, poly):
    """The share of `mask`'s ink that falls inside `poly`."""
    m = np.zeros(mask.shape, np.uint8)
    cv2.fillConvexPoly(m, np.asarray(poly, np.int32), 255)
    return float(((mask > 0) & (m > 0)).sum()) / max(1, int((mask > 0).sum()))


def _outlines(page):
    owner, index_of = ocr._pixel_owner(page)
    return {r.id: ocr.ink_outline(r, owner, index_of.get(r.id, -1))
            for r in page.regions}


# ------------------------------------------------------------- the shape


def test_the_box_round_slanted_words_is_slanted():
    """The whole point. A rectangle round a diagonal sound effect is mostly
    not the sound effect."""
    page, _speech, sfx = _page()
    shape = _outlines(page)[13]
    assert shape is not None
    box = cv2.contourArea(_rect_poly(page.regions[1].bbox).astype(np.float32))
    assert cv2.contourArea(shape.astype(np.float32)) < box * 0.5, \
        "the shape round slanted words must be far smaller than the rectangle"


def test_upright_speech_is_left_as_the_box_it_already_was():
    """Most text on most pages is upright, and for it the smallest turned
    rectangle round the ink IS the box it already had — set out by the halo
    that keeps the line off the glyphs, and nothing else. Nothing about a
    normal page may change."""
    page, speech, _sfx = _page()
    shape = _outlines(page)[12]
    x, y, w, h = page.regions[0].bbox
    g = ocr.GROW
    xs, ys = shape[:, 0], shape[:, 1]
    assert abs(int(xs.min()) - (x - g)) <= 2 and abs(int(ys.min()) - (y - g)) <= 2
    assert abs(int(xs.max()) - (x + w + g)) <= 2
    assert abs(int(ys.max()) - (y + h + g)) <= 2


def test_the_sound_effect_stops_swallowing_the_speech():
    """lee's complaint, measured: how much of the BALLOON'S ink sits inside
    the sound effect's outline."""
    page, speech, _sfx = _page()
    r13 = page.regions[1]
    was = _holds(speech, _rect_poly(r13.bbox))
    now = _holds(speech, _outlines(page)[13])
    assert was > 0.10, "the rectangle really did cover the neighbour's words"
    assert now < was / 2, f"the shape must cover far less; {was:.0%} -> {now:.0%}"


def test_no_box_covers_more_of_its_neighbour_than_before():
    """Both directions, so the fix cannot be a trade — one box getting tidier
    at the other's expense. Measured against the rectangle held off the ink by
    the same halo, so it is the SHAPE being compared and not the clearance."""
    page, speech, sfx = _page()
    shapes = _outlines(page)
    for r, theirs in ((page.regions[0], sfx), (page.regions[1], speech)):
        was = _holds(theirs, _rect_poly(r.bbox, ocr.GROW))
        now = _holds(theirs, shapes[r.id])
        assert now <= was + 1e-9, f"region {r.id} got worse: {was:.0%} -> {now:.0%}"


def test_ink_in_the_overlap_belongs_to_one_box_only():
    """Where two masks claim the same glyphs — which is what the detector does
    when two balloons touch — the nearer centre wins, once, for everybody.
    Without that, each box is outlined round the other's words as well as its
    own and the two shapes grow back into the overlapping rectangles they
    were meant to replace.

    Here the left box has been given the middle column that really belongs to
    the right one. That column is nearer the right box's centre, so it is the
    right box that is drawn round it."""
    cols = {}
    img = np.full((H, W, 3), 250, np.uint8)
    for cx in (126, 160, 194, 228):
        m = np.zeros((H, W), np.uint8)
        for k in range(6):
            box = (cx - 12, 60 + k * 36), (cx + 12, 60 + k * 36 + 26)
            cv2.rectangle(img, *box, (20, 20, 20), -1)
            cv2.rectangle(m, *box, 255, -1)
        cols[cx] = m
    left = cols[126] | cols[160] | cols[194]      # 194 is not really its own
    right = cols[194] | cols[228]
    a = TextRegion(id=1, bbox=_bbox(left), text_mask=left, order=0)
    b = TextRegion(id=2, bbox=_bbox(right), text_mask=right, order=1)
    shapes = _outlines(Page(image=img, regions=[a, b]))
    near, far = _holds(cols[194], shapes[2]), _holds(cols[194], shapes[1])
    assert near > 0.9, f"the nearer box keeps it ({near:.0%})"
    assert far < 0.5 and near > far * 2, \
        f"the far box must not be drawn round a whole column that is not its "\
        f"own (near {near:.0%}, far {far:.0%})"
    assert _holds(cols[126], shapes[1]) > 0.9, "its own columns are untouched"


def test_a_box_with_nothing_in_it_keeps_its_rectangle():
    """A box drawn on blank artwork to put English on, and a region out of a
    project saved before masks existed. There is nothing to measure and the
    rectangle is all it ever had."""
    assert ocr.ink_outline(TextRegion(id=1, bbox=(0, 0, 40, 40))) is None
    blank = np.zeros((H, W), np.uint8)
    assert ocr.ink_outline(
        TextRegion(id=1, bbox=(0, 0, 40, 40), text_mask=blank)) is None


def test_a_speck_is_not_a_shape():
    """Fewer inked pixels than `MIN_INK` is dust or the tail of a neighbour's
    glyph, and a turned rectangle round three pixels is worse than the box."""
    m = np.zeros((H, W), np.uint8)
    m[10:12, 10:13] = 255                       # 6 pixels
    assert ocr.ink_outline(TextRegion(id=1, bbox=(8, 8, 8, 8), text_mask=m)) is None


def test_only_the_boxs_own_corner_of_the_page_is_measured():
    """A text mask is page-sized and a chapter has sixty of them. Ink far from
    the box is not this box's, and reading the whole mask for every region is
    how a page gets slow."""
    m = np.zeros((H, W), np.uint8)
    cv2.rectangle(m, (40, 40), (90, 90), 255, -1)
    cv2.rectangle(m, (300, 430), (330, 460), 255, -1)      # somebody else's
    shape = ocr.ink_outline(TextRegion(id=1, bbox=(40, 40, 51, 51), text_mask=m))
    assert int(shape[:, 0].max()) < 200 and int(shape[:, 1].max()) < 200


# ------------------------------------------------- what the reader is sent


def _tags(vis):
    """Just the solid red number plates — the outlines are 2px and erode away."""
    red = (np.abs(vis.astype(int) - np.array(RED)) <= 30).all(2)
    return cv2.morphologyEx(red.astype(np.uint8), cv2.MORPH_ERODE,
                            np.ones((5, 5), np.uint8)) > 0


def _tile(page, detail="page"):
    tiles = ocr.page_label_tiles(page, detail=detail)
    return cv2.imdecode(np.frombuffer(tiles[0][0], np.uint8),
                        cv2.IMREAD_COLOR), tiles[0][1]


def _near(vis, xy, colour, rad=6):
    x, y = int(xy[0]), int(xy[1])
    patch = vis[max(0, y - rad):y + rad + 1, max(0, x - rad):x + rad + 1]
    if not patch.size:
        return False
    return bool((np.abs(patch.astype(int) - np.array(colour)) <= 40).all(2).any())


def test_the_reader_is_shown_the_slanted_shape_not_the_rectangle():
    """Down the middle of the sound effect's left edge there is now a red line
    where the rectangle had blank paper, and the rectangle's own top-left
    corner — which used to be drawn deep inside nothing — is bare."""
    page, _speech, _sfx = _page()
    vis, ids = _tile(page)
    assert ids == [12, 13]
    shape = _outlines(page)[13]
    mid = shape[:2].mean(0)                     # middle of one slanted edge
    assert _near(vis, mid, RED), "the shape's own edge must be drawn"
    x, y, w, h = page.regions[1].bbox
    for corner in ((x + 4, y + 4), (x + w - 4, y + h - 4)):
        assert not _near(vis, corner, RED, rad=4), \
            "the rectangle's corners are no longer corners of anything"


def test_a_neighbour_from_another_piece_of_the_page_is_still_grey():
    """Unchanged: a box being asked for is red and numbered, one that merely
    shows up in this piece of the page is grey and unnumbered, and the reader
    is told to ignore its words."""
    page, _speech, _sfx = _page()
    shape = _outlines(page)[13]
    vis = page.image.copy()
    ocr._draw_label(vis, page.regions[1], 0, 0, False, shape)
    assert _near(vis, shape[:2].mean(0), GREY), "a neighbour is outlined grey"
    red = (np.abs(vis.astype(int) - np.array(RED)) <= 30).all(2)
    assert not red.any(), "and carries no red anywhere — no outline, no number"


def test_the_number_is_not_printed_over_the_words():
    """A number on top of a glyph costs the reader that glyph — and the old
    placement, above the rectangle's top-left corner, put the sound effect's
    number inside the BALLOON."""
    page, _speech, _sfx = _page()
    vis, _ids = _tile(page)
    red = (np.abs(vis.astype(int) - np.array(RED)) <= 30).all(2)
    # the filled tag blocks: solid runs of red, unlike the 2px outlines
    filled = cv2.morphologyEx(red.astype(np.uint8), cv2.MORPH_ERODE,
                              np.ones((5, 5), np.uint8))
    ys, xs = np.nonzero(filled)
    assert len(xs), "the numbers must still be printed"
    page_ink = (cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY) < 100)
    covered = page_ink[ys, xs].mean()
    assert covered < 0.10, f"{covered:.0%} of the tags are sitting on ink"


def test_the_reader_never_sees_a_box_drawn_round_somebody_elses_words():
    """The owner map has to be threaded all the way to the picture, not merely
    computed. Two regions at opposite corners, and the left one's mask has
    sloppily swallowed the right one's glyphs — which is what the detector
    does when two things touch. Outlined off its raw mask, the left box is a
    quad stretching right across the page, through artwork belonging to
    neither of them."""
    img = np.full((H, W, 3), 250, np.uint8)
    a_ink, b_ink = np.zeros((H, W), np.uint8), np.zeros((H, W), np.uint8)
    cv2.rectangle(img, (30, 30), (110, 110), (20, 20, 20), -1)
    cv2.rectangle(a_ink, (30, 30), (110, 110), 255, -1)
    cv2.rectangle(img, (230, 350), (310, 430), (20, 20, 20), -1)
    cv2.rectangle(b_ink, (230, 350), (310, 430), 255, -1)
    a = TextRegion(id=1, bbox=_bbox(a_ink | b_ink), text_mask=a_ink | b_ink,
                   order=0)
    b = TextRegion(id=2, bbox=_bbox(b_ink), text_mask=b_ink, order=1)
    page = Page(image=img, regions=[a, b])
    vis, _ids = _tile(page)
    drawn = ((np.abs(vis.astype(int) - np.array(RED)) <= 40).all(2)
             | (np.abs(vis.astype(int) - np.array(GREY)) <= 40).all(2))
    # the number plates are solid red and are allowed to sit on blank paper —
    # blank paper is exactly where they are supposed to go
    drawn &= ~(cv2.dilate(_tags(vis).astype(np.uint8),
                          np.ones((21, 21), np.uint8)) > 0)
    near_words = cv2.dilate(a_ink | b_ink, np.ones((51, 51), np.uint8)) > 0
    stray = int((drawn & ~near_words).sum())
    assert stray == 0, \
        f"{stray} pixels of box are drawn across paper with no words on it"


def test_the_number_moves_off_the_artwork():
    """The old placement was the top-left corner and nothing else, so a number
    landed wherever that corner happened to be — over a black panel, over the
    neighbour's face, over the neighbour's words. It goes to whichever corner
    of the shape has the emptiest paper under it."""
    img = np.full((H, W, 3), 250, np.uint8)
    ink = np.zeros((H, W), np.uint8)
    cv2.rectangle(img, (120, 200), (200, 300), (20, 20, 20), -1)
    cv2.rectangle(ink, (120, 200), (200, 300), 255, -1)
    # solid artwork exactly where the top-left corner's label used to go
    dark = ((110, 160), (200, 200))
    cv2.rectangle(img, *dark, (0, 0, 0), -1)
    page = Page(image=img, regions=[TextRegion(id=7, bbox=_bbox(ink),
                                               text_mask=ink, order=0)])
    vis, _ids = _tile(page)
    tags = _tags(vis)
    assert tags.any(), "the number must still be printed"
    on_dark = tags[dark[0][1]:dark[1][1], dark[0][0]:dark[1][0]]
    assert not on_dark.any(), "the number must not be printed onto the artwork"


def test_every_region_still_lands_in_exactly_one_tile():
    """The invariant the tiling has always had, and which the outlines must
    not disturb: nothing read twice, nothing missed."""
    page, _speech, _sfx = _page()
    seen = [rid for _png, ids in ocr.page_label_tiles(page, detail="high")
            for rid in ids]
    assert sorted(seen) == [12, 13]


def test_a_region_with_no_mask_is_still_outlined():
    """Boxes the person drew by hand carry no ink of their own. They must go
    on being drawn, as the rectangles they are."""
    page, _speech, _sfx = _page()
    hand = TextRegion(id=14, bbox=(20, 20, 60, 40), kind="freefloat", order=2)
    page.regions.append(hand)
    vis, ids = _tile(page)
    assert 14 in ids
    assert _near(vis, (50, 20), RED), "its top edge must be drawn"


def test_the_reader_is_told_the_outline_follows_the_words():
    """Drawing a slanted outline is only half of it — the model has to be told
    that the outline, and not the upright rectangle around it, is the box."""
    from mangatl.translate import build_ocr_system
    sys = build_ocr_system("Japanese").lower()
    assert "slanted" in sys and "outline" in sys
    assert "rectangle" in sys, \
        "say what NOT to read: everything inside the upright rectangle"


def test_the_outline_is_never_drawn_on_the_words_it_points_at():
    """The outline is DRAWN, two pixels thick, onto the picture the reader
    gets. Lying along the edge of the glyphs, it takes the top off them: in
    lee's panel the old rectangle's bottom edge ran between the 目 and the
    rest of 見, and the box below it came back 悪魔 instead of 悪女."""
    page, speech, sfx = _page()
    shapes = _outlines(page)
    for r, mask, name in ((page.regions[0], speech, "speech"),
                          (page.regions[1], sfx, "sound effect")):
        vis = page.image.copy()
        ocr._draw_label(vis, r, 0, 0, True, shapes[r.id])
        drawn = (np.abs(vis.astype(int) - np.array(RED)) <= 40).all(2)
        drawn &= ~(cv2.dilate(_tags(vis).astype(np.uint8),
                              np.ones((21, 21), np.uint8)) > 0)
        assert int((drawn & (mask > 0)).sum()) == 0, \
            f"the outline is sitting on the {name} it points at"


def test_words_inside_two_outlines_go_to_the_closer_fit():
    """Speech is upright, so its shape stays the block it always was — and a
    sound effect slanting under it still falls inside that block. The picture
    cannot separate them, so the reader is told the rule."""
    from mangatl.translate import build_ocr_system
    assert "most closely" in build_ocr_system("Japanese")


def test_no_glyph_on_the_page_is_ever_covered_by_a_line():
    """Two boxes side by side have a border between them, and it lands on
    whichever of them is nearer. On lee's panel box 12's edge fell across 悪,
    which came back 悪魔 on one run and 聖女 on the next — the same character,
    guessed twice, because part of it was painted over.

    A box is an annotation. The glyph under it is the only thing on the page
    being asked about, so the words go back in front of the lines."""
    page, speech, sfx = _page()
    vis, _ids = _tile(page)
    lines = ((np.abs(vis.astype(int) - np.array(RED)) <= 40).all(2)
             | (np.abs(vis.astype(int) - np.array(GREY)) <= 40).all(2))
    lines &= ~(cv2.dilate(_tags(vis).astype(np.uint8),
                          np.ones((21, 21), np.uint8)) > 0)
    for name, mask in (("speech", speech), ("sound effect", sfx)):
        assert int((lines & (mask > 0)).sum()) == 0, \
            f"a line is painted over the {name}"


def test_the_lines_are_still_there_where_the_page_is_blank():
    """Putting the words back must not rub out the boxes as well — an outline
    broken where it passes behind a letter is still an outline; one that is
    gone is nothing."""
    page, _speech, _sfx = _page()
    vis, _ids = _tile(page)
    shape = _outlines(page)[13]
    assert _near(vis, shape[:2].mean(0), RED), \
        "the sound effect's own edge must still be drawn"
    assert _near(vis, _outlines(page)[12][:2].mean(0), RED)


def test_a_box_showing_up_in_somebody_elses_piece_is_drawn_grey():
    """A page too big to send at full resolution is cut into pieces, and a box
    near a cut shows up in the piece next door as well as its own. There it is
    a neighbour: grey, unnumbered, and the reader is told to ignore its words.
    Drawn red it would be a second, contradictory instruction."""
    tall = np.full((3200, 900, 3), 250, np.uint8)
    masks = []
    for cy in (960, 1140):                      # either side of the cut
        m = np.zeros(tall.shape[:2], np.uint8)
        cv2.rectangle(tall, (200, cy - 90), (700, cy + 90), (20, 20, 20), -1)
        cv2.rectangle(m, (200, cy - 90), (700, cy + 90), 255, -1)
        masks.append(m)
    page = Page(image=tall, regions=[
        TextRegion(id=n + 1, bbox=_bbox(m), text_mask=m, order=n)
        for n, m in enumerate(masks)])
    tiles = ocr.page_label_tiles(page, detail="high")
    assert len(tiles) > 1, "the page must actually be cut into pieces"
    grey = 0
    for png, ids in tiles:
        vis = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        grey += int((np.abs(vis.astype(int) - np.array(GREY)) <= 40).all(2).sum())
    assert grey > 0, "a box in a piece it does not belong to must be drawn grey"
