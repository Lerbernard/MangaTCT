"""Tests for the comic-text-detector pass (dmMaze's model, via cv2.dnn).

Two groups. The first needs nothing at all: it exercises the coverage pass --
the part that reads the model's segmentation mask for the writing its block
head never boxed -- against hand-made masks. The second needs the real
94.7 MB `comictextdetector.pt.onnx` and a page to run it on; without them it
skips rather than fails.

Why the coverage pass exists, measured on lee's chapter: the `blk` head boxes
dialogue beautifully (including black balloons with white typesetting, which no
dark-ink pass can ever find) and is completely blind to sound effects drawn
onto the artwork -- page 8 lost はら, ドキーッ, 居たぞ and 落ちてたわよ, page 13
lost all six of its own. Dropping conf_thresh from 0.4 to 0.05 does not bring
them back. The `seg` mask has every one of them.
"""
import os as _os

import numpy as np
import pytest

from mangatl.detect import comictext as CT


# ----------------------------------------------------------------- fixtures

def _find_model() -> str:
    """The ONNX weights, if this machine has them."""
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for p in (_os.environ.get("MANGATL_CTD_MODEL", ""),
              _os.path.join(here, "models", "comictextdetector.pt.onnx"),
              _os.path.join("models", "comictextdetector.pt.onnx"),
              "comictextdetector.pt.onnx"):
        if p and _os.path.isfile(p):
            return p
    return ""


def _find_page() -> str:
    """One manga page, if this machine has one."""
    import glob as _glob
    roots = [_os.environ.get("MANGATL_TEST_PAGES", ""),
             "pages", "chapter", "up", "out/input"]
    for root in roots:
        if not root or not _os.path.isdir(root):
            continue
        for ext in ("jpg", "jpeg", "png", "webp"):
            hits = sorted(_glob.glob(_os.path.join(root, f"*.{ext}")))
            if hits:
                return hits[0]
    return ""


_MODEL = _find_model()
_PAGE = _find_page()
needs_model = pytest.mark.skipif(not _MODEL, reason="no comictextdetector.pt.onnx")
needs_page = pytest.mark.skipif(not (_MODEL and _PAGE),
                                reason="need the model and a page")


def _mark(mask, x0, y0, w, h):
    """Paint one solid rectangle of ink."""
    mask[y0:y0 + h, x0:x0 + w] = 255


def _boxes(groups):
    return [g[0] for g in groups]


# ------------------------------------------------------- the specks are gone

def test_pieces_throws_away_printing_specks():
    """A mark smaller than LEFT_PIECE is dust on the scan, not writing."""
    m = np.zeros((200, 200), np.uint8)
    _mark(m, 10, 10, 2, 2)          # area 4 -- a speck
    _mark(m, 100, 100, 12, 12)      # area 144 -- a real mark
    got, _lab = CT._pieces(m > 0)
    assert len(got) == 1
    assert got[0]["ink"] == 144


# ----------------------------------------------- the merge must not snowball

def test_harvest_reach_comes_from_each_mark_not_the_growing_group():
    """A tall mark must not reach across the page to swallow a small one.

    This is the bug that ate page 13. When the join radius is taken from the
    box the two marks WOULD make (or from the larger of them), every merge
    makes the next merge easier, and on page 13 that snowballed until one
    group covered (39,60)-(863,1320) -- the whole page. Holding the radius to
    the SMALLER mark's own size stops the chain: a big sound effect cannot
    pull in a distant small one, and a speck can never reach anything.
    """
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 0, 0, 30, 200)         # tall: sz 200, ink 6000
    _mark(m, 60, 0, 25, 25)         # small: sz 25, ink 625
    # the gap is 30px: 0.6 * 25 = 15, so they stay apart; 0.6 * 200 = 120
    # would have joined them.
    claimed = np.zeros(m.shape, bool)
    groups = CT._harvest(m, claimed)
    assert len(groups) == 2, _boxes(groups)
    # and the tall mark's box is still its own size, not the pair's
    tall = max(groups, key=lambda g: g[2])
    assert tall[0] == (0, 0, 29, 199)


def test_harvest_joins_marks_that_really_do_sit_together():
    """Two strokes of one sound effect, a couple of pixels apart, are one
    piece of writing -- the pass is not allowed to be so shy it splits every
    kana into its own box."""
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 100, 100, 30, 30)
    _mark(m, 140, 100, 30, 30)      # gap 10, radius 0.6 * 30 = 18
    groups = CT._harvest(m, np.zeros(m.shape, bool))
    assert len(groups) == 1
    assert groups[0][0] == (100, 100, 169, 129)


# ------------------------------------------------------------- the two floors

def test_harvest_ink_floor_drops_tone_dots_and_stray_marks():
    """Measured on lee's chapter: the faintest real leftover writing carries
    615 pixels of ink (フゥ) and the loudest junk topped out at 438 (page 8's
    impact slashes), so the floor sits between them."""
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 20, 20, 20, 20)        # ink 400 -- under the floor
    groups = CT._harvest(m, np.zeros(m.shape, bool))
    assert groups == []
    m2 = np.zeros((400, 400), np.uint8)
    _mark(m2, 20, 20, 30, 30)       # ink 900 -- over it
    assert len(CT._harvest(m2, np.zeros(m2.shape, bool))) == 1


def test_harvest_drops_hairlines_however_long_they_are():
    """A speed line or a panel rule carries plenty of ink but is only a couple
    of pixels thick, and writing never is."""
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 10, 200, 380, 2)       # ink 760, but 2px thick
    assert CT._harvest(m, np.zeros(m.shape, bool)) == []


# --------------------------------------------- only what the blocks never got

def test_harvest_ignores_writing_the_block_head_already_boxed():
    """The whole point: this pass picks up the leftovers. Anything under a
    block rectangle has a region already and must not get a second one."""
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 100, 100, 40, 40)      # would easily clear both floors
    claimed = np.zeros(m.shape, bool)
    assert len(CT._harvest(m, claimed)) == 1
    claimed[90:150, 90:150] = True
    assert CT._harvest(m, claimed) == []


def test_harvest_hands_back_only_its_own_ink_as_the_text_mask():
    """The group's mask becomes the region's text_mask, which is what the
    cleaner paints out -- so a neighbour's ink must not be in it, or the
    cleaner rubs out a piece of the artwork."""
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 0, 0, 40, 40)          # ink 1600
    _mark(m, 300, 0, 40, 40)        # ink 1600, far away
    groups = CT._harvest(m, np.zeros(m.shape, bool))
    assert len(groups) == 2
    for (x0, y0, x1, y1), sub, ink in groups:
        assert sub.shape == (y1 - y0 + 1, x1 - x0 + 1)
        assert int((sub > 0).sum()) == ink


def test_harvest_returns_the_loudest_writing_first():
    m = np.zeros((400, 400), np.uint8)
    _mark(m, 0, 0, 30, 30)          # ink 900
    _mark(m, 200, 200, 60, 60)      # ink 3600
    groups = CT._harvest(m, np.zeros(m.shape, bool))
    assert [g[2] for g in groups] == [3600, 900]


# ------------------------------------------------------- the real model, live

@needs_model
def test_the_model_loads_under_opencv_and_has_the_heads_we_read():
    """Verified live on cv2 4.13.0: readNetFromONNX takes this export and the
    three output names are ('blk', 'det', 'seg'). If a future export renames
    them, the picking code below falls back on shape, but this test says out
    loud what was actually measured."""
    import cv2
    net = CT._get_net(_MODEL)
    names = tuple(net.getUnconnectedOutLayersNames())
    assert set(names) == {"blk", "det", "seg"}, names
    blob = np.zeros((1, 3, CT.INPUT, CT.INPUT), np.float32)
    net.setInput(blob)
    outs = {n: np.asarray(o) for n, o in zip(names, net.forward(names))}
    assert outs["blk"].ndim == 3 and outs["blk"].shape[2] == 7
    assert outs["seg"].shape == (1, 1, CT.INPUT, CT.INPUT)
    assert outs["det"].shape == (1, 2, CT.INPUT, CT.INPUT)
    del cv2


@needs_model
def test_blocks_are_decoded_in_pixels_not_fractions():
    """`blk` gives cx,cy,w,h in blob pixels (0..1024), and the caller scales
    them by the page size -- if they were ever 0..1 every box would collapse
    into the top-left corner."""
    pred = np.zeros((1, 3, 7), np.float32)
    pred[0, 0] = (512, 400, 200, 300, 0.9, 0.0, 1.0)
    got = CT._decode_blocks(pred, 0.4, 0.35)
    assert len(got) == 1
    x1, y1, x2, y2, cf = got[0]
    assert (round(x1), round(y1), round(x2), round(y2)) == (412, 250, 612, 550)
    assert cf > 0.8


@needs_page
def test_a_real_page_gets_boxes_and_the_leftovers_are_labelled_outside_text():
    """End to end on a real page. Everything the block head missed is writing
    that is not set in a block -- hand typesetting over the artwork -- so it
    comes back as sfx (or narration when a printed rule boxes it off), never
    as a balloon: the balloon fitter must not be handed a sound effect.
    """
    import cv2
    from mangatl.models import Page
    img = cv2.imread(_PAGE)
    if img is None:
        pytest.skip("the page would not load")
    page = Page(image=img, source_path="t")
    regs = CT.detect_comictext(page, _MODEL)
    assert regs, "no text found on a real page"
    for r in regs:
        x, y, w, h = r.bbox
        assert w > 0 and h > 0
        assert 0 <= x and 0 <= y
        assert x + w <= img.shape[1] and y + h <= img.shape[0]
        assert r.kind in ("bubble", "freefloat", "sfx", "narration")
        assert r.text_mask is not None
        assert r.text_mask.shape[:2] == img.shape[:2]
    del cv2


# --------------------------------------------------- one piece of writing, one box

def _reg(rid, bbox):
    from mangatl.models import TextRegion
    return TextRegion(id=rid, bbox=bbox)


def test_two_boxes_over_the_same_writing_collapse_to_the_bigger_one():
    """Measured on page 17 of lee's chapter. The block head's own non-maximum
    suppression compares the rectangles it PREDICTED, so two predictions that
    overlap too little to suppress each other can still have their ink measured
    into almost exactly the same place -- (782,662,103,248) beside
    (783,663,99,247), an IoU of 0.96. Both copies were then read, translated and
    typeset on top of each other.

    The bigger box wins: the smaller is the same writing with an edge clipped.
    """
    regs = [_reg(0, (782, 662, 103, 248)), _reg(1, (783, 663, 99, 247))]
    got = CT._drop_duplicates(regs)
    assert len(got) == 1
    assert got[0].bbox == (782, 662, 103, 248)


def test_two_boxes_over_different_writing_are_both_kept():
    """Two balloons that merely touch are two balloons. lee: "each bubbles
    shoud have their own box" -- this pass drops copies, it never merges
    neighbours."""
    regs = [_reg(0, (0, 0, 100, 100)), _reg(1, (60, 0, 100, 100))]  # IoU 0.25
    assert len(CT._drop_duplicates(regs)) == 2


def test_the_duplicate_threshold_sits_where_the_constant_says_it_does():
    """Pins DUP_IOU so a future nudge has to be deliberate. Two 100x100 boxes
    16px apart overlap at IoU 0.72 and collapse; 18px apart is 0.70 and both
    stay."""
    assert len(CT._drop_duplicates([_reg(0, (0, 0, 100, 100)),
                                    _reg(1, (0, 16, 100, 100))])) == 1
    assert len(CT._drop_duplicates([_reg(0, (0, 0, 100, 100)),
                                    _reg(1, (0, 18, 100, 100))])) == 2


def test_survivors_keep_the_order_they_were_found_in_and_are_renumbered():
    """Reading order is worked out later from these boxes, and the editor keys
    every edit on the id -- so the ids must come back 0..n-1 with no holes, in
    the order the boxes were found, not in the order this pass happened to
    consider them (which is largest first)."""
    regs = [_reg(0, (0, 0, 40, 40)),          # small, found first
            _reg(1, (500, 500, 300, 300)),    # large, considered first
            _reg(2, (501, 501, 298, 298)),    # a copy of the large one
            _reg(3, (0, 900, 60, 60))]
    got = CT._drop_duplicates(regs)
    assert [r.bbox for r in got] == [(0, 0, 40, 40), (500, 500, 300, 300),
                                     (0, 900, 60, 60)]
    assert [r.id for r in got] == [0, 1, 2]


def test_a_box_wholly_inside_a_much_bigger_one_is_not_a_duplicate():
    """A small sound effect can legitimately sit inside a big balloon's
    rectangle, and lee has both on the same page. Containment is not
    duplication: the test is how much of the PAIR overlaps, so a 30x30 box
    inside a 300x300 one scores 0.01 and both live."""
    regs = [_reg(0, (0, 0, 300, 300)), _reg(1, (100, 100, 30, 30))]
    assert len(CT._drop_duplicates(regs)) == 2
