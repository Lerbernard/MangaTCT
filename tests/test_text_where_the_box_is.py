"""Bubble text goes where its own box is, and nowhere else.

lee, twice, looking at a page where one block's lines ran clear across the
next block's rectangle:

* *"this is still happening, make it so that this NEVER happens EACH BOX HAS
  ITS OWN TEXT"*
* *"the typesetting is should not be putting text across 2 boxes it shoud
  never happen for buble text make it so that teh text goes where teh box is
  with a little leeway"*

Until now a balloon holding two blocks was divided by measuring: typeset it
down the middle, typeset it across, keep whichever made the smaller block
bigger. Cutting across usually won, because English wants width - and cutting
across is exactly what puts one block's words over the other block's box.
Measured on the page-030 balloon it is 26pt and 19pt for the full-width stack
against 14 and 14 for the columns, so this is not a free change: it is lee
choosing where the words go over how big they are, having been shown both.

`_box_confined` is the rule. Each block's share of the balloon is cut three
ways - within `BOX_LEEWAY` of its own box, nearer its own box than anybody
else's, and one connected piece - and the leeway is what keeps it from being
brutal, a third of the box's own short side in every direction.

Two things it deliberately does NOT do:

* **A block alone in its balloon still gets the whole balloon.** There is
  nobody to run into, the box and the speech are the same thing, and
  typesetting into the balloon is what makes it big and centred.
* **A balloon the artist drew as two lobes keeps the neck cut.** That is the
  same answer arrived at better: a block in each lobe IS a block where its
  box is, with the artist's own leeway rather than a number.
"""
import numpy as np
import pytest

from mangatl.models import TextRegion
from mangatl.typeset import (BOX_LEEWAY, TypesetConfig, _box_confined,
                             default_font_path, fit_region, share_masks)


def _cfg():
    return TypesetConfig(font_path=default_font_path(), min_font=12, max_font=34)


def _oval(w, h, pad=30):
    yy, xx = np.mgrid[0:h + 2 * pad, 0:w + 2 * pad]
    m = np.zeros(xx.shape, np.uint8)
    m[(((xx - (pad + w / 2)) / (w / 2.0)) ** 2
       + ((yy - (pad + h / 2)) / (h / 2.0)) ** 2) <= 1.0] = 255
    return m


def _blocks(mask, boxes, texts=None, kind="bubble"):
    """Regions sharing one balloon `mask`, each with its own writing box."""
    out = []
    for i, b in enumerate(boxes):
        r = TextRegion(id=i + 1, bbox=tuple(int(v) for v in b), kind=kind,
                       text_mask=mask, bubble_mask=mask,
                       bubble_bbox=(0, 0, mask.shape[1], mask.shape[0]))
        r.dst_text = (texts or ["SOME WORDS HERE."] * len(boxes))[i]
        out.append(r)
    return out


def _covers(share, box, balloon):
    """How much of the box the share covers - of the part of it that is inside
    the balloon at all. A box drawn round the Japanese can poke out past the
    artwork's outline at a corner; the letters must not follow it there."""
    x, y, w, h = box
    inside = balloon[y:y + h, x:x + w] > 0
    if not inside.any():
        return 0.0
    return float(((share[y:y + h, x:x + w] > 0) & inside).sum()) / int(inside.sum())


# ------------------------------------------------------- what the share is

def test_each_block_gets_a_share_that_covers_its_own_box():
    m = _oval(280, 420)
    rs = _blocks(m, [(60, 70, 150, 120), (60, 260, 150, 120)])
    got = _box_confined(rs, [m, m])
    assert set(got) == {1, 2}
    for r in rs:
        assert _covers(got[r.id], r.bbox, m) > 0.999, r.bbox


def test_no_share_reaches_into_anybody_elses_box():
    """The whole of what lee asked for, stated once."""
    m = _oval(280, 420)
    rs = _blocks(m, [(60, 70, 150, 120), (60, 260, 150, 120)])
    got = _box_confined(rs, [m, m])
    for r in rs:
        for other in rs:
            if other is r:
                continue
            x, y, w, h = other.bbox
            assert got[r.id][y:y + h, x:x + w].max() == 0, (r.id, other.id)


def test_the_shares_never_overlap_each_other():
    m = _oval(280, 420)
    rs = _blocks(m, [(60, 70, 150, 120), (60, 260, 150, 120)])
    got = _box_confined(rs, [m, m])
    both = (got[1] > 0) & (got[2] > 0)
    assert not both.any(), int(both.sum())


def test_a_share_never_leaves_the_balloon():
    """A box may stick out past the artwork's balloon; the letters may not."""
    m = _oval(280, 420)
    rs = _blocks(m, [(0, 70, 250, 120), (0, 280, 250, 120)])
    got = _box_confined(rs, [m, m])
    for r in rs:
        assert not ((got[r.id] > 0) & (m == 0)).any(), r.id


def test_the_leeway_is_a_little_and_it_is_real():
    """Neither nothing - a box drawn tight around the Japanese would give
    English nowhere to breathe - nor a licence to take the balloon.

    The balloon here is deliberately much roomier than the leeway: every
    direction the share could grow in has far more room than `BOX_LEEWAY`
    allows, so the number is the only thing holding it in and the test fails
    if that number stops being consulted.
    """
    m = _oval(400, 600)
    box = (150, 150, 120, 100)
    rs = _blocks(m, [box, (150, 420, 120, 100)])
    got = _box_confined(rs, [m, m])[1]
    x, y, w, h = box
    ys, xs = np.nonzero(got)
    grew = [x - xs.min(), xs.max() - (x + w), y - ys.min(), ys.max() - (y + h)]
    want = BOX_LEEWAY * min(w, h)
    assert min(grew) > 0, grew                       # it breathes every way
    assert max(grew) <= want + 2, (grew, want)       # and no further
    # ...and the balloon really did have more to give in every direction.
    ys2, xs2 = np.nonzero(m)
    assert x - xs2.min() > want * 2 and xs2.max() - (x + w) > want * 2
    assert y - ys2.min() > want * 2


def test_each_share_is_one_piece():
    """A paragraph goes in one place. A share in two lumps would let the
    fitter centre a line in a lump the reader does not associate with it -
    and a thought balloon's trailing bubbles are exactly such a lump, sitting
    just off the paper and well inside the nearest block's leeway.
    """
    import cv2
    m = _oval(300, 420)
    yy, xx = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    m = m.copy()
    m[((xx - 20) ** 2 + (yy - 100) ** 2) <= 12 ** 2] = 255   # a detached bubble
    rs = _blocks(m, [(60, 70, 170, 130), (60, 270, 170, 130)])
    got = _box_confined(rs, [m, m])
    assert set(got) == {1, 2}
    for r in rs:
        n, _ = cv2.connectedComponents((got[r.id] > 0).astype(np.uint8), 8)
        assert n == 2, (r.id, n - 1)   # background + exactly one piece
    # ...and the detached bubble really was inside somebody's reach, so this
    # test would notice if the pruning stopped happening.
    assert not any(got[r.id][100, 20] for r in rs)


# ---------------------------------------------------- when it stands aside

def test_one_block_alone_keeps_the_whole_balloon():
    m = _oval(280, 420)
    rs = _blocks(m, [(60, 150, 150, 120)])
    assert _box_confined(rs, [m]) == {}


def test_an_empty_balloon_is_left_to_the_older_cuts():
    m = np.zeros((200, 200), np.uint8)
    rs = _blocks(m, [(10, 10, 40, 40), (100, 100, 40, 40)])
    assert _box_confined(rs, [m, m]) == {}


def test_a_box_off_the_page_is_left_to_the_older_cuts():
    m = _oval(200, 200)
    rs = _blocks(m, [(10, 10, 40, 40), (100, 100, 40, 40)])
    rs[1].bbox = (10_000, 10_000, 40, 40)
    assert _box_confined(rs, [m, m]) == {}


def test_a_box_the_balloon_does_not_cover_is_left_to_the_older_cuts():
    """If a share cannot even cover the box it belongs to, this balloon is not
    the shape it looks like and the older cuts are better placed to guess."""
    m = _oval(280, 420)
    rs = _blocks(m, [(60, 70, 150, 120), (2, 2, 40, 40)])   # the corner is white
    assert _box_confined(rs, [m, m]) == {}


def test_a_box_only_half_on_the_paper_is_left_to_the_older_cuts():
    """The harder half of the same rule: not a box wholly off the balloon,
    which yields no share at all and is easy, but one hanging off the edge
    with a corner still on it. A share covering a third of its own box is a
    place to typeset a third of a paragraph, and something about the balloon is
    not what it looks like."""
    m = _oval(280, 420)
    box = (0, 200, 60, 90)
    rs = _blocks(m, [(80, 60, 150, 110), box])
    frac = float((m[200:290, 0:60] > 0).mean())
    assert 0.05 < frac < 0.5, frac       # genuinely half off, not all off
    assert _box_confined(rs, [m, m]) == {}


# ------------------------------------------------- wired into the typesetter

def test_a_two_block_balloon_typesets_each_block_inside_its_own_box():
    """End to end, through the entry the typesetter actually calls."""
    m = _oval(280, 460)
    rs = _blocks(m, [(70, 60, 140, 150), (70, 290, 140, 150)],
                 ["THE PALACE LOT ARE AFTER YOU, YOU KNOW.",
                  "LET THEM COME AND TRY IT."])
    cfg = _cfg()
    shares = share_masks(rs, cfg)
    assert set(shares) == {1, 2}
    laid = [fit_region(r, cfg, shares[r.id]) for r in rs]
    for k, lay in enumerate(laid):
        ox, oy, ow, oh = rs[1 - k].bbox
        for x, y in lay.line_origins:
            assert not (ox <= x < ox + ow and oy <= y < oy + oh), \
                (k, (x, y), rs[1 - k].bbox)


def test_the_full_translation_still_goes_in():
    """Standing rule: the whole line, always. Confining a block must never
    become a reason to drop a word."""
    m = _oval(280, 460)
    texts = ["THE PALACE LOT ARE AFTER YOU, YOU KNOW.",
             "LET THEM COME AND TRY IT."]
    rs = _blocks(m, [(70, 60, 140, 150), (70, 290, 140, 150)], texts)
    cfg = _cfg()
    shares = share_masks(rs, cfg)
    for r, text in zip(rs, texts):
        lay = fit_region(r, cfg, shares[r.id])
        assert " ".join(lay.lines) == text, lay.lines


def test_the_regions_own_geometry_is_never_written_back():
    """A shape invented for one typesetting pass must not become the region's,
    because regions persist and the next pass would compound it."""
    m = _oval(280, 460)
    rs = _blocks(m, [(70, 60, 140, 150), (70, 290, 140, 150)])
    was = [(r.bbox, r.bubble_mask.copy()) for r in rs]
    share_masks(rs, _cfg())
    for r, (bbox, mask) in zip(rs, was):
        assert r.bbox == bbox
        assert np.array_equal(r.bubble_mask, mask)


def test_a_balloon_drawn_as_two_lobes_stays_inside_the_neck_and_the_box():
    """The neck cut decides WHICH side of the balloon a block letters on; the
    box decides where on that side.

    Both, in that order. The neck runs first, so a share never crosses into
    the other lobe - that is the artist's own division and no measurement of
    ours improves on it. Then the share is trimmed back to the block's own box
    plus `BOX_LEEWAY`, because a lobe and the trunk are one piece of paper and
    a block handed the whole of its side will happily set its words down at
    the waist. On lee's page that is exactly what happened to HUH!?.

    The trim is not free - see `test_the_box_is_what_costs_the_point_size` in
    test_two_lobes.py for the measured half-the-point-size it costs. lee:
    *"that fine the size dnst mattaer as long as it in the box"*.
    """
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from mangatl.typeset import _lobe_cut, BOX_LEEWAY
    from test_pipeline import _two_lobe_regions

    rs = _two_lobe_regions("I NEVER MEANT FOR ANY OF THIS TO HAPPEN TO YOU.",
                           "IT IS TOO LATE NOW.")
    cfg = _cfg()
    masks = [r.bubble_mask for r in rs]
    lobes = _lobe_cut(rs, masks, cfg)
    assert lobes, "the neck cut stopped firing; this test protects nothing"
    shares = share_masks(rs, cfg)
    trimmed = 0
    for r in rs:
        got, lobe = shares[r.id] > 0, lobes[r.id] > 0
        assert got.any(), r.id
        # Never outside the lobe the artist drew...
        assert not (got & ~lobe).any(), r.id
        if int(got.sum()) < int(lobe.sum()):
            trimmed += 1
        # ...and never outside this block's own box plus its leeway.
        x, y, w, h = (int(v) for v in r.bbox)
        reach = int(BOX_LEEWAY * max(4.0, float(min(w, h)))) + 2
        room = np.zeros(got.shape, bool)
        room[max(0, y - reach):y + h + reach,
             max(0, x - reach):x + w + reach] = True
        assert not (got & ~room).any(), r.id
        # A share that no longer covers its own box is not a share.
        assert got[max(0, y):y + h, max(0, x):x + w].mean() > 0.5, r.id
    assert trimmed, "nothing was trimmed; the box rule is not running"


def _room(shape, box):
    """The box grown by its leeway, as a mask, with a pixel of slack."""
    x, y, w, h = (int(v) for v in box)
    reach = int(BOX_LEEWAY * max(4.0, float(min(w, h)))) + 2
    room = np.zeros(shape[:2], bool)
    room[max(0, y - reach):y + h + reach, max(0, x - reach):x + w + reach] = True
    return room


def test_the_band_cut_is_trimmed_back_to_the_boxes_too():
    """`_box_confined` is the first answer, not the only one, and every answer
    after it obeys the same rule.

    This balloon gets past `_box_confined` because one of its two boxes is
    drawn mostly off the artwork - a hand-tightened box on a balloon whose
    outline moved - so the confine bails and the band cut takes over. The band
    is the full width of the balloon, which is exactly the shape that used to
    put one block's words over the other block's box, so it is trimmed on the
    way out.

    And the block whose box the trim CANNOT cover keeps its band whole. That
    is per block, not per balloon: one oddly placed box must not hand the
    whole balloon back untrimmed, which is how the word ended up at the waist.
    """
    from mangatl.typeset import _lobe_cut, _prop_cut

    m = _oval(280, 420)
    rs = _blocks(m, [(90, 70, 140, 120), (0, 300, 120, 130)],
                 ["ONE TWO THREE.", "FOUR FIVE SIX."])
    cfg = _cfg()
    masks = [r.bubble_mask for r in rs]
    assert not _lobe_cut(rs, masks, cfg), "a neck appeared; wrong path"
    assert not _box_confined(rs, masks), "the confine held; wrong path"
    bands = _prop_cut(rs, masks, [r.dst_text for r in rs], vertical=False)
    assert len(bands) == len(rs), "no band cut; this test protects nothing"

    shares = share_masks(rs, cfg)
    good, odd = rs
    # The band that could be trimmed was, and it still covers its own box.
    got, raw = shares[good.id] > 0, bands[good.id] > 0
    assert (raw & ~_room(m.shape, good.bbox)).any(), "the band was already in"
    assert not (got & ~_room(m.shape, good.bbox)).any()
    assert int(got.sum()) < int(raw.sum())
    x, y, w, h = good.bbox
    assert got[y:y + h, x:x + w].mean() > 0.5

    # The band that could not keeps every pixel it had.
    assert np.array_equal(shares[odd.id] > 0, bands[odd.id] > 0)


def test_the_last_resort_cut_is_trimmed_back_to_the_boxes_too():
    """Three blocks all claiming the whole balloon, in a shape no band will
    divide - the emergency cut, and it obeys the box rule as well.

    Same fixture logic as the band test: one box drawn off the artwork gets
    past `_box_confined`, and lopsided speech lengths in a small round balloon
    make every band come out too thin to typeset into, so it falls all the way
    through to `_nearest_ink_cut`.
    """
    from mangatl.typeset import _lobe_cut, _nearest_ink_cut, _prop_cut

    m = _oval(160, 160, pad=20)
    boxes = [(0, 0, 50, 45), (110, 30, 50, 40), (40, 110, 110, 60)]
    said = ["HI", "OK",
            "A VERY LONG SPEECH INDEED THAT RUNS ON AND ON AND ON AND ON."]
    rs = []
    for i, (b, t) in enumerate(zip(boxes, said)):
        x, y, w, h = b
        ink = np.zeros(m.shape, np.uint8)
        ink[y:y + h, x:x + w] = 255
        r = TextRegion(id=i + 1, bbox=b, kind="bubble", text_mask=ink,
                       bubble_mask=m, bubble_bbox=(0, 0, m.shape[1], m.shape[0]))
        r.dst_text = t
        rs.append(r)
    cfg = _cfg()
    masks = [r.bubble_mask for r in rs]
    assert not _lobe_cut(rs, masks, cfg), "a neck appeared; wrong path"
    assert not _box_confined(rs, masks), "the confine held; wrong path"
    for vertical in (False, True):
        assert len(_prop_cut(rs, masks, said, vertical=vertical)) != len(rs), \
            "a band divided this after all; wrong path"
    raw = _nearest_ink_cut(rs, masks)
    assert len(raw) == len(rs), "no emergency cut; this test protects nothing"

    shares = share_masks(rs, cfg)
    odd, a, b = rs
    for r in (a, b):
        was, got = raw[r.id] > 0, shares[r.id] > 0
        assert (was & ~_room(m.shape, r.bbox)).any(), (r.id, "already in")
        assert not (got & ~_room(m.shape, r.bbox)).any(), r.id
        assert int(got.sum()) < int(was.sum()), r.id
        x, y, w, h = r.bbox
        assert got[y:y + h, x:x + w].mean() > 0.5, r.id
    assert np.array_equal(shares[odd.id] > 0, raw[odd.id] > 0)


def test_free_text_outside_a_balloon_is_not_touched():
    """lee said *for buble text*. Loose captions and shouts are not grouped
    into a balloon in the first place, and must stay that way."""
    m = _oval(280, 420)
    rs = _blocks(m, [(60, 70, 150, 120), (60, 260, 150, 120)], kind="free")
    for r in rs:
        r.bubble_mask = None
        r.bubble_bbox = r.bbox
    assert share_masks(rs, _cfg()) == {}

# --------------------------------------- and where the words land inside it

def _waisted_page(max_font=22):
    """A balloon shaped like lee's: one waisted shape, two blocks, and each
    box a good deal narrower than the lobe it sits in."""
    import cv2
    from mangatl.models import Page, TextRegion
    H, W = 500, 340
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (170, 140), (140, 105), 0, 0, 360, 255, -1)   # upper lobe
    cv2.ellipse(m, (150, 340), (120, 120), 0, 0, 360, 255, -1)   # lower lobe
    cv2.rectangle(m, (120, 190), (210, 300), 255, -1)            # the waist

    def blk(rid, box, text):
        x, y, w, h = box
        tm = np.zeros((H, W), np.uint8)
        tm[y:y + h, x:x + w] = 255
        r = TextRegion(id=rid, bbox=(x, y, w, h), kind="bubble",
                       text_mask=tm, bubble_mask=m.copy(),
                       bubble_bbox=(0, 0, W, H),
                       polygon=[[0, 0], [W, 0], [W, H], [0, H]])
        r.dst_text = text
        return r

    # …and both boxes sitting to the RIGHT of their lobe's centre, as his do
    rs = [blk(9, (200, 60, 90, 130), "HUH!?..."),
          blk(10, (150, 250, 95, 150), "...GLOW IS!?")]
    page = Page(image=np.full((H, W, 3), 240, np.uint8))
    page.regions = rs
    cfg = _cfg()
    cfg.max_font = max_font
    return page, rs, cfg


def _spread(lay):
    """Left and right edge of the typesetting, in page pixels."""
    from mangatl.typeset import _font
    f = _font(lay.font_path, lay.font_size)
    lo, hi = [], []
    for (ox, _oy), line in zip(lay.line_origins, lay.lines):
        half = f.getlength(line) / 2.0
        lo.append(ox - half)
        hi.append(ox + half)
    return min(lo), max(hi)


def test_a_block_in_a_lobe_still_typesets_over_its_own_box():
    """lee, over a picture of HUH!? beginning a good thirty pixels left of the
    box it belongs to, with the box's own right-hand side empty: *"this is
    still happening look into it"*.

    A balloon with a waist skipped the box rule altogether - a block in a lobe
    was taken to be a block where its box is, "with the artist's own leeway".
    A lobe can be far wider than the box in it, so the words came out centred
    on the lobe.
    """
    from mangatl.typeset import BOX_LEEWAY, typeset_page
    page, rs, cfg = _waisted_page()
    typeset_page(page, cfg, redo=True)
    for r in rs:
        x, y, w, h = r.bbox
        left, right = _spread(r.layout)
        leeway = BOX_LEEWAY * min(w, h)
        assert left >= x - leeway, (r.id, left, x, leeway)
        assert right <= x + w + leeway, (r.id, right, x + w, leeway)


def test_moving_it_there_costs_no_typesetting_size():
    """The share is not touched, so the size the balloon bought is the size
    that is set. Cutting the share back to the box instead is what halves it
    on a balloon whose boxes are narrow Japanese columns."""
    from mangatl.typeset import fit_region, share_masks, typeset_page
    page, rs, cfg = _waisted_page()
    shares = share_masks(rs, cfg)
    was = {r.id: fit_region(r, cfg, shares[r.id]).font_size for r in rs}
    typeset_page(page, cfg, redo=True)
    for r in rs:
        assert r.layout.font_size >= was[r.id], (r.id, r.layout.font_size,
                                                 was[r.id])


def test_a_block_alone_in_a_balloon_is_left_where_the_fitter_put_it():
    """It is typeset into the BALLOON on purpose - that is what makes it big
    and centred. Dragging it onto the narrow column the Japanese stood in
    would undo the whole of that."""
    import cv2
    from mangatl.typeset import pull_to_box, typeset_page
    from mangatl.models import Page, TextRegion
    H, W = 400, 400
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (200, 200), (160, 120), 0, 0, 360, 255, -1)
    tm = np.zeros((H, W), np.uint8)
    tm[120:280, 300:340] = 255                     # a column off to one side
    r = TextRegion(id=1, bbox=(300, 120, 40, 160), kind="bubble",
                   text_mask=tm, bubble_mask=m, bubble_bbox=(0, 0, W, H),
                   polygon=[[0, 0], [W, 0], [W, H], [0, H]])
    # Short, so there is nothing STOPPING it being carried over to the
    # column - if it stays put it is because it was never asked to move.
    r.dst_text = "HI!"
    page = Page(image=np.full((H, W, 3), 240, np.uint8))
    page.regions = [r]
    cfg = _cfg()
    cfg.max_font = 22
    typeset_page(page, cfg, redo=True)
    xs = [o[0] for o in r.layout.line_origins]
    mid = sum(xs) / len(xs)
    assert abs(mid - 200) < 40, (mid, "dragged onto its own Japanese column")
    # ...and the move really would have reached, so this is a guard and not a
    # geometry that could not have moved anyway
    moved = pull_to_box(r, r.layout, cfg, r.bubble_mask)
    mx = sum(o[0] for o in moved.line_origins) / len(moved.line_origins)
    assert mx > 260, (mx, "the fixture cannot move; it proves nothing")


def test_it_never_carries_a_line_off_the_paper():
    """The move is bounded by the share: it goes as far towards the box as it
    can while every line is still ON the balloon, and no further.

    Measured at the ENDS of each line, not at its origin - an origin is the
    middle of a line, and a line whose middle is on the paper can have both
    its ends out in the artwork."""
    from mangatl.typeset import _font, share_masks, typeset_page
    page, rs, cfg = _waisted_page(max_font=40)
    shares = share_masks(rs, cfg)
    typeset_page(page, cfg, redo=True)
    for r in rs:
        m = (shares[r.id] > 0) if shares.get(r.id) is not None \
            else (r.place_mask() > 0)
        f = _font(r.layout.font_path, r.layout.font_size)
        for (ox, oy), line in zip(r.layout.line_origins, r.layout.lines):
            half = f.getlength(line) / 2.0
            for px in (ox - half, ox, ox + half):
                assert m[int(round(oy)), int(round(px))], (r.id, px, oy, line)
