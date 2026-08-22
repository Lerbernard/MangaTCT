"""One piece of writing, one box - and paper is not a balloon.

lee, with about thirty screenshots of Find text's own output on a 46-page
Korean webtoon::

    here are some issue i found what can you do to inprove on them
    i think this box is using teh edge of the pannel to make it a bubble tetx
    it shoud ever do that
    a bunch of sfx are being detected as other boxes and outside etxt beigng
    detected as inside box

Four faults, and they are four and not one:

1. **One piece of writing in several boxes.** A hand-drawn 쳐벅 in four, a
   와아아아 in four, a 쿵 in two, the title logo in two.
2. **Two boxes over the same piece.** A 쳉 boxed at 62x69 and again at
   297x333, the small one entirely inside the big one.
3. **Boxes on the artwork.** Six on the ornamental flourishes round one
   caption frame, and crumbs left on the ends of a brush stroke.
4. **Bare paper read as a balloon.** Which is the one he diagnosed himself,
   and he is right: the demotion asked whether the margin was bright and
   whether the floor was bright, and an empty page answers 255 to both.

Everything here was measured on all 46 pages, 187 boxes, and every number in
it is written down with what it was measured against - in this file for the
bounds, and in `detect/comictext.py` for the reasoning.

**Manga is off.** Every number below is a fact about Korean webtoon pages;
`tuning_for("manga")` returns None for both new keys and the manga path cannot
move.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT
from mangatl.detect import balloon as BL
from mangatl.models import Page, TextRegion

INPUT = CT.INPUT


def _r(bbox, kind="sfx", mask=None, balloon=None):
    return TextRegion(id=0, bbox=tuple(int(v) for v in bbox),
                      text_mask=mask, bubble_mask=balloon,
                      bubble_bbox=tuple(int(v) for v in bbox), kind=kind)


# ------------------------------------------------- one piece, several boxes

def test_two_boxes_over_one_shout_come_back_as_one():
    a, b = _r((100, 100, 120, 120)), _r((180, 100, 120, 120))
    out = CT._join_overlapping([a, b], CT.JOIN_OVER)
    assert len(out) == 1
    assert tuple(out[0].bbox) == (100, 100, 200, 120)


def test_a_chain_of_four_becomes_one_rectangle():
    """와아아아 on page 001: four boxes, each overlapping only its neighbour.
    Joining pairs is not enough - the first and the last never touch."""
    rs = [_r((100 + 80 * i, 100 + 40 * i, 120, 120)) for i in range(4)]
    out = CT._join_overlapping(rs, CT.JOIN_OVER)
    assert len(out) == 1
    assert tuple(out[0].bbox) == (100, 100, 360, 240)


def test_boxes_that_only_graze_are_left_alone():
    """The floor is not decoration. Chapter 8's two pairs that must NOT join
    overlap at 0.02 of the smaller; the smallest true pair is at 0.07."""
    a, b = _r((100, 100, 200, 200)), _r((295, 100, 200, 200))
    share = (5 * 200) / float(200 * 200)
    assert share < CT.JOIN_OVER, "not the grazing case"
    assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 2


def test_two_families_are_two_things():
    a = _r((100, 100, 120, 120), kind="sfx")
    b = _r((180, 100, 120, 120), kind="bubble")
    assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 2


def test_a_box_with_a_balloon_under_it_is_never_joined():
    """`attach_balloons` has said where that one sits. Two balloons whose
    rectangles graze are two things said."""
    ball = np.zeros((10, 10), np.uint8)
    a = _r((100, 100, 120, 120), kind="bubble", balloon=ball)
    b = _r((180, 100, 120, 120), kind="bubble", balloon=ball)
    assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 2


def test_the_join_carries_the_ink_of_every_piece():
    """The mask is what Clean paints out. A rectangle over the whole effect
    with a mask holding a quarter of it leaves the rest on the page."""
    m1 = np.zeros((400, 400), np.uint8); m1[110:150, 110:150] = 255
    m2 = np.zeros((400, 400), np.uint8); m2[110:150, 250:290] = 255
    out = CT._join_overlapping([_r((100, 100, 120, 120), mask=m1),
                                _r((180, 100, 120, 120), mask=m2)],
                               CT.JOIN_OVER)
    assert len(out) == 1
    got = np.asarray(out[0].text_mask) > 0
    assert got[120, 120] and got[120, 260], "a piece's ink was dropped"


def test_the_biggest_piece_keeps_its_identity():
    small, big = _r((100, 100, 60, 60)), _r((140, 100, 300, 300))
    big.kind = "sfx"
    out = CT._join_overlapping([small, big], CT.JOIN_OVER)
    assert out[0] is big


def test_switched_off_it_does_nothing():
    rs = [_r((100, 100, 120, 120)), _r((180, 100, 120, 120))]
    assert CT._join_overlapping(rs, None) is rs


# ------------------------------------------------ two boxes over one piece

def test_two_passes_that_disagree_about_one_piece_of_ink_leave_one_box():
    """Page 032's title plate: outside text from the block head, a sound
    effect from CRAFT, 79% of the smaller inside the bigger at an IoU of
    0.39 - a fifth of `DUP_IOU`, so nothing above it can see the pair."""
    small = _r((120, 120, 200, 160), kind="freefloat")
    big = _r((100, 100, 260, 230), kind="sfx")
    out = CT._drop_duplicates([small, big])
    assert len(out) == 1 and tuple(out[0].bbox) == (100, 100, 260, 230)


def test_the_containment_bar_is_above_the_pair_that_must_not_merge():
    """Measured over the chapter: the pairs that are one piece of writing sit
    at 0.77, 0.79, 1.00 and 1.00, and the next pair down is 0.39."""
    assert 0.39 < CT.DUP_INSIDE <= 0.77


def test_one_family_is_left_to_the_join():
    """Two boxes of the SAME family are `_join_overlapping`'s business, and it
    unions them rather than throwing one away - which keeps whatever the
    smaller one was covering."""
    small, big = _r((150, 150, 62, 69)), _r((100, 100, 297, 333))
    assert len(CT._drop_duplicates([small, big])) == 2
    assert len(CT._join_overlapping([small, big], CT.JOIN_OVER)) == 1


def test_a_small_effect_inside_a_big_balloon_is_not_a_duplicate():
    """The case this rule has to stay away from, and it is a real one - lee
    has both on the same page. A hundredth of an area apart; the two pairs
    the rule is for are 0.13 and 0.55."""
    big = _r((0, 0, 300, 300), kind="bubble")
    tiny = _r((100, 100, 30, 30), kind="sfx")
    assert len(CT._drop_duplicates([big, tiny])) == 2


def test_two_boxes_side_by_side_are_two_boxes():
    a, b = _r((100, 100, 200, 200)), _r((280, 100, 200, 200))
    assert len(CT._drop_duplicates([a, b])) == 2


# ------------------------------------------------------- boxes on the artwork

def _one_swash(w=300, h=300):
    """One thin ornamental stroke, alone in a rectangle it barely marks."""
    p = np.full((h, w), 245, np.uint8)
    cv2.ellipse(p, (w // 2, h // 2), (w // 2 - 20, h // 2 - 20),
                0, 200, 340, 30, 3)
    return p


def _a_line_of_writing(w=300, h=300):
    """Four syllable blocks, which is what a line of Korean looks like to
    anything counting marks."""
    p = np.full((h, w), 245, np.uint8)
    for i in range(4):
        cv2.rectangle(p, (20 + i * 70, 110), (20 + i * 70 + 50, 190), 30, -1)
    return p


def _mask_of(p):
    return (p < CT.INK).astype(np.uint8) * 255


def test_one_thin_swash_in_an_empty_rectangle_is_not_writing():
    p = _one_swash()
    assert CT._a_stray_mark(p, (0, 0, 300, 300), _mask_of(p))


def test_a_line_of_writing_is_kept():
    p = _a_line_of_writing()
    assert not CT._a_stray_mark(p, (0, 0, 300, 300), _mask_of(p))


def test_a_shape_that_fills_its_box_is_kept():
    """A drawn shout is one mark - and it FILLS the rectangle. Only the pair
    of answers throws a box away."""
    p = np.full((300, 300), 245, np.uint8)
    cv2.rectangle(p, (30, 30), (270, 270), 30, -1)
    assert not CT._a_stray_mark(p, (0, 0, 300, 300), _mask_of(p))


def test_three_marks_are_enough_to_be_writing():
    p = np.full((300, 300), 245, np.uint8)
    for i in range(3):
        cv2.circle(p, (60 + i * 90, 150), 6, 30, -1)
    assert not CT._a_stray_mark(p, (0, 0, 300, 300), _mask_of(p))


def test_specks_do_not_count_as_marks():
    """Jpeg dirt beside the swash must not rescue it. Three specks, because
    two would leave the count inside `STRAY_PIECES` either way and the fixture
    would prove nothing."""
    p = _one_swash()
    for i in range(3):
        p[10, 10 + i * 8] = 30
    assert CT._a_stray_mark(p, (0, 0, 300, 300), _mask_of(p))


def test_the_fill_is_the_thing_being_compared():
    p = _one_swash()
    m = _mask_of(p)
    fill = float((m > 0).sum()) / float(300 * 300)
    assert CT._a_stray_mark(p, (0, 0, 300, 300), m, fill + 0.01)
    assert not CT._a_stray_mark(p, (0, 0, 300, 300), m, fill - 0.01)


def test_it_measures_the_mask_it_is_given():
    p = _one_swash()
    m = _mask_of(p)
    p[:] = np.minimum(p, 60)
    assert CT._a_stray_mark(p, (0, 0, 300, 300), m), "it read the page"


def test_a_box_too_small_to_measure_is_left_alone():
    p = np.full((15, 15), 240, np.uint8)
    assert not CT._a_stray_mark(p, (0, 0, 15, 15), None)


def test_a_box_off_the_page_edge_is_clipped_not_crashed():
    p = _one_swash()
    CT._a_stray_mark(p, (-40, -40, 600, 600), _mask_of(p))


def test_the_fill_line_is_under_the_nearest_real_writing():
    """004#4, a fragment of 쳉, measures 0.116, and it is the nearest real
    thing to the line on 46 pages. A thousandth of margin is thin and is the
    reason to keep watching this."""
    assert CT.tuning_for("manhwa")["stray_fill"] < 0.116


# ---------------------------------------------------- paper is not a balloon

def _wall_page(shape="round"):
    """A page with one enclosure drawn on it, and writing inside it."""
    p = np.full((900, 900), 255, np.uint8)
    if shape == "round":
        cv2.ellipse(p, (450, 450), (240, 200), 0, 0, 360, 0, 6)
    elif shape == "plate":
        # A caption plate: long and thin, which is what takes it under
        # `WALL_CIRC` - a squarish frame is round enough to pass either way.
        cv2.rectangle(p, (60, 380), (840, 520), 0, 6)
    for i in range(3):
        cv2.rectangle(p, (330 + i * 60, 400), (330 + i * 60 + 40, 500), 30, -1)
    return p


def test_a_round_wall_answers_yes_either_way():
    p = _wall_page("round")
    assert BL._round_wall_around(p, (330, 400, 220, 100))
    assert BL._round_wall_around(p, (330, 400, 220, 100), roundish=False)


def test_a_ruled_caption_plate_only_answers_when_roundness_is_not_asked():
    """A caption plate is a rectangle. The demotion wants to know whether
    anything encloses the writing, and a rectangle has to count."""
    p = _wall_page("plate")
    box = (330, 400, 220, 100)
    assert not BL._round_wall_around(p, box)
    assert BL._round_wall_around(p, box, roundish=False)


def test_bare_paper_answers_no_to_both():
    """The whole of lee's complaint in one assertion: nothing is drawn round
    this writing, so nothing encloses it, however bright the page is."""
    p = np.full((900, 900), 255, np.uint8)
    for i in range(3):
        cv2.rectangle(p, (330 + i * 60, 400), (330 + i * 60 + 40, 500), 30, -1)
    box = (330, 400, 220, 100)
    assert not BL._round_wall_around(p, box)
    assert not BL._round_wall_around(p, box, roundish=False)
    assert CT._ring_paper(p, box) >= CT.LOOSE_RING, \
        "the ring test still says paper, which is why the wall test is needed"


# ------------------------------------ a word space is not the end of a line

def test_two_boxes_on_one_line_a_word_space_apart_are_one():
    """018's "3년 전" with its trailing "…" boxed separately - 18 pixels of
    daylight, so nothing that measures overlap can see them. lee: *"4 shoud
    be one box not 2"*."""
    a, b = _r((100, 100, 200, 80)), _r((330, 100, 60, 80))
    assert CT._next_to(a.bbox, b.bbox)
    assert len(CT._join_overlapping([a, b], CT.JOIN_OVER)) == 1


def test_two_lines_of_one_caption_are_one():
    """042's caption, set as two lines 13px apart in one column."""
    a, b = _r((100, 100, 200, 80)), _r((100, 200, 200, 80))
    assert CT._next_to(a.bbox, b.bbox)


def test_boxes_that_do_not_line_up_are_two_things():
    """The gap is only worth measuring once they line up. Two boxes a word
    space apart but on different lines are two pieces of writing."""
    a, b = _r((100, 100, 200, 80)), _r((330, 250, 60, 80))
    assert not CT._next_to(a.bbox, b.bbox)
    # ...and a pair whose ROWS graze without lining up is the case the
    # perpendicular bar exists for: a quarter of the smaller box's rows is
    # "somewhere nearby", not "on this line".
    c, d = _r((100, 100, 200, 80)), _r((330, 160, 60, 80))
    assert not CT._next_to(c.bbox, d.bbox)


def test_the_two_studio_credit_blocks_stay_apart():
    """046's credits, 0.66 of a height apart in one column - two things, and
    the measured pair the stacked line has to refuse. 042's two caption lines
    are at 0.18, so the line goes between them with about 2x either way."""
    assert 0.18 < CT.NEAR_STACK < 0.66
    a, b = _r((100, 100, 200, 80)), _r((100, 234, 200, 80))   # 0.67 apart
    assert not CT._next_to(a.bbox, b.bbox)


def test_the_page_is_not_read_as_one_paragraph():
    """A line's leading is tighter than a word space, and both are a fraction
    of the letters. Neither number may grow into "anything on this page"."""
    assert CT.NEAR_STACK < CT.NEAR_SIDE < 1.0
    a, b = _r((100, 100, 200, 80)), _r((100, 500, 200, 80))
    assert not CT._next_to(a.bbox, b.bbox)


def test_overlapping_boxes_are_not_this_rule():
    """`_next_to` is about the gap. Two boxes that overlap have no gap, and
    the overlap rule owns them."""
    a, b = _r((100, 100, 200, 80)), _r((250, 100, 200, 80))
    assert not CT._next_to(a.bbox, b.bbox)


# ------------------------------- what the second detector can see in a box

def test_a_box_with_no_characters_in_it_measures_none():
    assert CT._characters_in([(500, 500, 560, 560)], (10, 10, 100, 100)) \
        == (0, 0.0, 0.0)


def test_two_marks_that_overlap_are_not_counted_twice_in_the_cover():
    n, cover, med = CT._characters_in(
        [(10, 10, 60, 110), (10, 10, 60, 110)], (10, 10, 100, 100))
    assert n == 2
    assert abs(cover - 0.5) < 0.01, cover
    assert med == 100.0


def test_the_height_is_of_the_piece_clipped_to_the_box():
    """A piece running out of the box is only as tall as the part inside it -
    the question is how big the characters HERE are."""
    n, cover, med = CT._characters_in([(10, 10, 60, 500)], (10, 10, 100, 100))
    assert med == 100.0


def test_a_box_with_no_size_is_not_measured():
    assert CT._characters_in([(0, 0, 10, 10)], (10, 10, 0, 0)) == (0, 0.0, 0.0)


# ------------------------------------------------------------ the format fork

def test_manga_is_untouched():
    for medium in ("manga", None, "nonsense"):
        t = CT.tuning_for(medium)
        assert t.get("join_over") is None, medium
        assert t.get("stray_fill") is None, medium
        assert t.get("art_veto") is False, medium
        assert t.get("fx_chars") is None, medium


def test_the_webtoons_run_both_at_the_measured_numbers():
    for medium in ("manhwa", "manhua"):
        assert CT.tuning_for(medium)["join_over"] == CT.JOIN_OVER, medium
        assert CT.tuning_for(medium)["stray_fill"] == CT.STRAY_FILL, medium
        assert CT.tuning_for(medium)["art_veto"] is True, medium
        assert CT.tuning_for(medium)["fx_chars"] == CT.FX_CHARS, medium


# ----------------------------------------------------- end to end, one page

class _Net:
    """The block head and the mask, minus the 95MB."""

    def __init__(self, blocks, seg):
        self.blocks, self.seg = blocks, seg

    def setInput(self, blob):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["blk", "seg"]

    def forward(self, names):
        blk = np.zeros((1, max(1, len(self.blocks)), 6), np.float32)
        for i, (x0, y0, x1, y1) in enumerate(self.blocks):
            blk[0, i] = [(x0 + x1) / 2.0, (y0 + y1) / 2.0,
                         x1 - x0, y1 - y0, 0.9, 0.9]
        seg = np.zeros((1, 1, INPUT, INPUT), np.float32)
        seg[0, 0] = (self.seg > 0).astype(np.float32)
        return [blk, seg]


def _split_shout_page():
    """One drawn word across two blocks the head reported separately - which
    is what a brush-drawn Korean effect does to it."""
    page = np.full((INPUT, INPUT), 40, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for x in (400, 520):
        cv2.rectangle(page, (x, 430), (x + 150, 600), 250, -1)
        cv2.rectangle(seg, (x, 430), (x + 150, 600), 255, -1)
    blocks = [(400, 430, 560, 600), (520, 430, 670, 600)]
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), blocks, seg


def _run(monkeypatch, **kw):
    img, blocks, seg = _split_shout_page()
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    tune.update(kw)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_one_word_in_two_blocks_comes_back_as_one_box(monkeypatch):
    on = _run(monkeypatch)
    off = _run(monkeypatch, join_over=None)
    assert len(on) < len(off), [tuple(r.bbox) for r in off]
    assert len(on) == 1


def test_the_joined_box_covers_both_pieces(monkeypatch):
    (r,) = _run(monkeypatch)
    x, y, w, h = r.bbox
    assert x <= 400 and x + w >= 670, r.bbox


def _two_ornaments_page():
    """Two thin swashes whose rectangles overlap - which is how the six
    flourishes round page 017's caption frame are boxed, in three pairs."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for x in (400, 500):
        # TWO strokes each, which is what makes this fixture worth having:
        # one swash apiece leaves the joined box inside `STRAY_PIECES` and it
        # would be swept whichever order the passes ran in. Two apiece is
        # four in the union, and only asking first catches them.
        for arc in ((200, 340), (20, 160)):
            cv2.ellipse(page, (x + 100, 500), (90, 70), 0, *arc, 20, 3)
            cv2.ellipse(seg, (x + 100, 500), (90, 70), 0, *arc, 255, 3)
    blocks = [(400, 420, 600, 580), (500, 420, 700, 580)]
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), blocks, seg


def test_two_overlapping_ornaments_both_go(monkeypatch):
    """The order the passes run in, asserted where it can be seen. Joined
    first, the pair becomes one rectangle that is no longer empty and
    survives; swept first, both go. Page 017 loses two of its six flourishes
    to the wrong order."""
    img, blocks, seg = _two_ornaments_page()
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    assert CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                               **tune) == []


def test_the_same_two_ornaments_survive_with_the_rule_off(monkeypatch):
    img, blocks, seg = _two_ornaments_page()
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                stray_fill=None)
    assert CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_the_sweep_is_asked_before_the_join():
    """The order, asserted where it is decided.

    It was the other way round for one turn, on the obvious reasoning - put
    the fragments back, then ask which boxes are empty - and page 017 is the
    counter-example: its six ornamental flourishes are boxed in three
    overlapping PAIRS, each pair joins into a rectangle holding four marks
    instead of two, and two of the six survive. Swept first, all six go.

    Said against the source rather than against a page because the fault is
    an ordering and a fixture for it has to arrange two boxes that overlap,
    hold at most `STRAY_PIECES` marks each and more than that together -
    which is a page built to the shape of the answer. The real evidence is 46
    pages, and it is written down at the call site."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    sweep = src.index("_a_stray_mark(gray, r.bbox")
    join = src.index("_join_overlapping(regions, join_over)")
    assert sweep < join, "the join runs first and the ornaments survive it"


def _blank_page_with_writing():
    """lee's 046: three words set on a page with nothing else on it. The
    margin reads 255 and so does the paper under the letters, which is what
    the old demotion took for a balloon."""
    page = np.full((INPUT, INPUT), 255, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (400 + i * 60, 480), (400 + i * 60 + 40, 560),
                      20, -1)
        cv2.rectangle(seg, (400 + i * 60, 480), (400 + i * 60 + 40, 560),
                      255, -1)
    return (cv2.cvtColor(page, cv2.COLOR_GRAY2BGR),
            [(394, 474, 646, 566)], seg)


def test_writing_on_a_blank_page_is_outside_text_end_to_end(monkeypatch):
    """The whole of lee's complaint, through the detector. Nothing is drawn
    round this writing, so it is not in a balloon however bright the page is."""
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    img, blocks, seg = _blank_page_with_writing()
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert CT._ring_paper(gray, rs[0].bbox) >= CT.LOOSE_RING, \
        "the margin is not paper here, so this is not the case being tested"
    assert rs[0].kind == "freefloat", rs[0].kind


def test_the_same_writing_inside_a_drawn_shape_stays_dialogue(monkeypatch):
    """The control. One line drawn round it and the answer flips back - which
    is the difference the rule is actually reading."""
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    img, blocks, seg = _blank_page_with_writing()
    cv2.ellipse(img, (520, 520), (240, 160), 0, 0, 360, (0, 0, 0), 5)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs and rs[0].kind == "bubble", [r.kind for r in rs]


# ------------------------------------------- the two detectors start together

def test_the_two_detectors_are_running_at_the_same_time(monkeypatch):
    """lee: *"if you can spped up teh find text it take a long time"*.

    21.3 of a page's 24.6 seconds are two neural nets that do not need each
    other - 12.0 in CRAFT and 9.3 in the block head - and the first line that
    needs both is hundreds of lines below either. Started together a page
    costs the slower rather than the sum.

    Asserted by making the two nets WAIT FOR EACH OTHER rather than by a
    clock. A wall-clock assertion on a two-core machine measures the sandbox;
    this measures the thing that makes the saving real - that CRAFT is still
    running when the block head starts. Run one after the other, the block
    head never starts, nothing sets the flag, and the wait times out.
    """
    import threading

    started = threading.Event()
    overlapped = threading.Event()
    img, blocks, seg = _split_shout_page()

    class _Timed(_Net):
        def forward(self, names):
            started.set()
            return super().forward(names)

    def craft_pieces(image, *a, **kw):
        if started.wait(timeout=10):
            overlapped.set()
        return []

    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net", lambda p: _Timed(blocks, seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces", craft_pieces)
    monkeypatch.setattr(CR, "group", lambda *a, **kw: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **kw: [])
    tune = dict(CT.tuning_for("manhwa"))
    CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert overlapped.is_set(), "the two nets took turns"


def test_the_pool_is_one_worker():
    """It exists to overlap one page's two nets, not to run pages at once -
    Find text over a chapter is a loop and it stays one."""
    assert CT._POOL._max_workers == 1


def test_a_second_detector_that_throws_still_reaches_the_caller(monkeypatch):
    """A future swallows an exception until somebody asks for the result. The
    old code raised at the call; this has to raise at the collect."""
    img, blocks, seg = _split_shout_page()
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    monkeypatch.setattr(CR, "available", lambda: True)

    def boom(*a, **kw):
        raise RuntimeError("craft fell over")

    monkeypatch.setattr(CR, "pieces", boom)
    tune = dict(CT.tuning_for("manhwa"))
    with pytest.raises(RuntimeError, match="craft fell over"):
        CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_no_gaps_in_the_numbering(monkeypatch):
    """The boxes are renumbered after everything is dropped, not before."""
    img, blocks, seg = _split_shout_page()
    blocks = blocks + [(100, 100, 200, 200)]
    seg = seg.copy()
    cv2.ellipse(seg, (150, 150), (40, 30), 0, 200, 340, 255, 3)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert [r.id for r in rs] == list(range(len(rs)))


# ----------------------------- letters against drawings, both directions

def _craft_run(monkeypatch, craft_boxes, patch=(400, 430, 600, 600), **kw):
    """One page, one block over `patch`, and whatever CRAFT is told to see."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    x0, y0, x1, y1 = patch
    w = (x1 - x0) // 5
    for i in range(4):
        cv2.rectangle(page, (x0 + i * w, y0), (x0 + i * w + w - 6, y1), 20, -1)
        cv2.rectangle(seg, (x0 + i * w, y0), (x0 + i * w + w - 6, y1), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([patch], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces", lambda im, **k: list(craft_boxes))
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(kw)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_a_box_craft_sees_no_characters_in_is_thrown_away(monkeypatch):
    """The chandelier, the staff and the embroidery: solid shapes that every
    cheap statistic reads as a drawn effect. What tells them from one is that
    nothing trained on writing can find a character in them."""
    assert _craft_run(monkeypatch, []) == []


def test_the_same_box_survives_with_the_veto_off(monkeypatch):
    assert _craft_run(monkeypatch, [], art_veto=False, fx_chars=None)


def test_one_big_character_filling_the_box_is_a_drawn_shout(monkeypatch):
    """lee: *"sfx are big shoud s that usslkly are gig randon angles"*. 크크,
    저벅, 옹성, 찰랑, 씨익: one or two oversized characters filling the box."""
    rs = _craft_run(monkeypatch, [(400, 430, 600, 600)])
    assert rs and rs[0].kind == "sfx", [r.kind for r in rs]


def test_four_characters_along_a_line_are_writing(monkeypatch):
    """lee: *"outside tetx are ussiuly normal text"* -- a row of several
    characters of one size. The count carries it; coverage alone would call a
    line of close-set type a shout."""
    seen = [(400 + i * 50, 430, 400 + i * 50 + 50, 600) for i in range(4)]
    rs = _craft_run(monkeypatch, seen)
    assert rs and rs[0].kind != "sfx", [r.kind for r in rs]


def test_two_small_characters_in_a_big_box_are_left_as_writing(monkeypatch):
    """The count on its own would delete a two-syllable line; the cover is
    the guard, and on manhwa an sfx label deletes the box."""
    rs = _craft_run(monkeypatch, [(400, 430, 430, 460), (440, 430, 470, 460)])
    assert rs and rs[0].kind != "sfx", [r.kind for r in rs]


def _coverage_box_run(monkeypatch, craft_boxes):
    """A box the COVERAGE pass made - no block, hollow outlined shapes, so it
    is called sfx on sight and stays one - with CRAFT told what to see."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (400 + i * 50, 430), (400 + i * 50 + 40, 600),
                      20, 3)
        cv2.rectangle(seg, (400 + i * 50, 430), (400 + i * 50 + 40, 600),
                      255, 3)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces", lambda im, **k: list(craft_boxes))
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                               **CT.tuning_for("manhwa"))


def test_many_small_characters_in_an_effect_box_are_given_back(monkeypatch):
    """041: a title plate and a caption swallowed into coverage boxes, called
    sfx on sight, and so left off a run that did not tick sound effects --
    "missing" without one pixel being missed. Fifteen and six characters at 0.07 of the page; no real
    effect on 46 pages carries more than five."""
    small = [(402 + (i % 4) * 48, 434 + (i // 4) * 60,
              402 + (i % 4) * 48 + 40, 434 + (i // 4) * 60 + 50)
             for i in range(8)]
    rs = _coverage_box_run(monkeypatch, small)
    assert rs, "the box was thrown away instead of given back"
    assert all(r.kind == "freefloat" for r in rs), [r.kind for r in rs]


def test_five_big_characters_stay_a_drawn_shout(monkeypatch):
    """004's 쳉-in-pieces is the nearest real effect to the line: five
    characters, none of them small. Neither gate lets it through -- the count
    line sits between five and six, and the height line under it."""
    big = [(400 + i * 40, 430, 400 + i * 40 + 36, 600) for i in range(5)]
    rs = _coverage_box_run(monkeypatch, big)
    assert rs and all(r.kind == "sfx" for r in rs), [r.kind for r in rs]


def test_five_small_characters_are_still_a_shout(monkeypatch):
    """The COUNT is a gate of its own. Five characters is the biggest real
    effect on the chapter, however small they run, and the line has to hold
    at five even when the height line would let them through."""
    small = [(402 + i * 40, 434, 402 + i * 40 + 34, 484) for i in range(5)]
    rs = _coverage_box_run(monkeypatch, small)
    assert rs and all(r.kind == "sfx" for r in rs), [r.kind for r in rs]


def test_six_big_characters_are_still_a_shout(monkeypatch):
    """...and the HEIGHT is the other gate. Six full-height characters are a
    long drawn shout, not a caption, and the count alone must not flip them."""
    big = [(400 + i * 33, 430, 400 + i * 33 + 30, 600) for i in range(6)]
    rs = _coverage_box_run(monkeypatch, big)
    assert rs and all(r.kind == "sfx" for r in rs), [r.kind for r in rs]


def test_a_box_in_a_balloon_is_never_asked(monkeypatch):
    """`attach_balloons` has said where that one sits. 034's lone "!" is the
    only box on 46 pages CRAFT sees nothing in that is real writing -- and it
    is in a balloon."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (420 + i * 40, 460), (450 + i * 40, 560), 20, -1)
        cv2.rectangle(seg, (420 + i * 40, 460), (450 + i * 40, 560), 255, -1)
    cv2.ellipse(page, (500, 510), (200, 130), 0, 0, 360, 0, 5)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(410, 450, 600, 570)], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces", lambda im, **k: [])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                             **CT.tuning_for("manhwa"))
    assert rs and rs[0].bubble_mask is not None, "not the balloon case"
    assert rs[0].kind != "sfx"


def test_nothing_happens_without_the_second_detector(monkeypatch):
    """Neither question can be asked with no marks to count. A chapter found
    without CRAFT has to keep its boxes."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (420 + i * 45, 460), (455 + i * 45, 560), 20, -1)
        cv2.rectangle(seg, (420 + i * 45, 460), (455 + i * 45, 560), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(410, 450, 610, 570)], seg))
    monkeypatch.setattr(CR, "available", lambda: False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                             **CT.tuning_for("manhwa"))
    assert rs, "the veto ran with nothing to run on"


# --------------------------------------- outside text shut inside a frame

def test_enclosed_writing_on_paper_is_promoted_to_dialogue():
    """lee: *"8 shoud be bubble text"* -- the 황제 plate, outside text from
    `_classify_kind` because its margin is a dark sleeve. Something is drawn
    round it and it stands on paper, and those two answers agreeing is what a
    balloon IS."""
    p = np.full((900, 900), 255, np.uint8)
    cv2.rectangle(p, (60, 340), (840, 560), 0, 6)
    for i in range(3):
        cv2.rectangle(p, (330 + i * 60, 400), (330 + i * 60 + 40, 500), 30, -1)
    box = (330, 400, 220, 100)
    assert BL._round_wall_around(p, box, roundish=False,
                                 lo=CT.ENCLOSE_LO, hi=CT.ENCLOSE_HI,
                                 seal=CT.ENCLOSE_SEAL)


def test_the_enclosure_question_is_gentler_than_the_balloon_rescue():
    """A pale drawn circle -- lee's page 021, his *"5 both hsoud be buble
    text"* -- reads nothing at the balloon rescue's 30/90 and reads a wall at
    the enclosure's own thresholds. Both numbers exist because the two
    questions look for differently drawn things."""
    p = np.full((900, 900), 255, np.uint8)
    cv2.ellipse(p, (450, 450), (240, 200), 0, 0, 360, (235,), 7)
    for i in range(3):
        cv2.rectangle(p, (330 + i * 60, 400), (330 + i * 60 + 40, 500), 30, -1)
    box = (330, 400, 220, 100)
    assert not BL._round_wall_around(p, box, roundish=False)
    assert BL._round_wall_around(p, box, roundish=False,
                                 lo=CT.ENCLOSE_LO, hi=CT.ENCLOSE_HI,
                                 seal=CT.ENCLOSE_SEAL)
    assert CT.ENCLOSE_LO < BL.WALL_LO and CT.ENCLOSE_SEAL > BL.WALL_SEAL


def _framed_plate_page(plate_tone=255):
    """A dark page with a big ORNAMENTALLY framed plate on it and writing
    inside - the 황제 plate's shape. The frame is dashed, with gaps wider
    than the balloon rescue's 15px seal, so nothing that existed before the
    promotion can shut it; and the plate is big enough that the balloon
    fitter refuses it. What happens to the box is the promotion's alone."""
    page = np.full((INPUT, INPUT), 40, np.uint8)
    cv2.rectangle(page, (110, 260), (910, 760), int(plate_tone), -1)

    def dashed(p0, p1):
        (x0, y0), (x1, y1) = p0, p1
        length = max(abs(x1 - x0), abs(y1 - y0))
        for t in range(0, length, 60):
            f0, f1 = t / length, min(1.0, (t + 40) / length)
            a = (int(x0 + (x1 - x0) * f0), int(y0 + (y1 - y0) * f0))
            b = (int(x0 + (x1 - x0) * f1), int(y0 + (y1 - y0) * f1))
            cv2.line(page, a, b, 0, 5)

    dashed((130, 280), (890, 280))
    dashed((130, 740), (890, 740))
    dashed((130, 280), (130, 740))
    dashed((890, 280), (890, 740))
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (420 + i * 45, 460), (455 + i * 45, 560), 30, -1)
        cv2.rectangle(seg, (420 + i * 45, 460), (455 + i * 45, 560), 255, -1)
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), [(410, 450, 610, 570)], seg


def _tight_plate_page(plate_tone):
    """A dark page, a plate barely bigger than the writing on it. The margin
    `_classify_kind` reads is mostly the dark page, so the box arrives as
    outside text - which is how the 황제 plate arrives, and the case the
    promotion exists for."""
    page = np.full((INPUT, INPUT), 40, np.uint8)
    cv2.rectangle(page, (390, 430), (630, 590), int(plate_tone), -1)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (420 + i * 45, 460), (455 + i * 45, 560), 30, -1)
        cv2.rectangle(seg, (420 + i * 45, 460), (455 + i * 45, 560), 255, -1)
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), [(410, 450, 610, 570)], seg


def _promotion_run(monkeypatch, plate_tone):
    """The promotion in isolation: the enclosure answer is forced to YES and
    every other way a box can become a bubble is switched off, so what the
    box comes back as is decided by the paper gates alone."""
    img, blocks, seg = _tight_plate_page(plate_tone)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    monkeypatch.setattr(BL, "attach_balloons", lambda *a, **k: 0)
    # bounds callers (the frame-as-balloon pass) get "no frame found", so
    # what these two tests measure stays the paper gates alone.
    monkeypatch.setattr(BL, "_round_wall_around",
                        lambda *a, **k: None if k.get("bounds") else True)
    # The label the box ARRIVES with is not what these two tests are about --
    # the 황제 plate arrives as outside text and the fixture pins that, not
    # the classifier's opinion of a synthetic page.
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "freefloat")
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_enclosed_writing_on_paper_comes_back_dialogue(monkeypatch):
    """The promotion itself. `_classify_kind` calls the plate's writing
    outside text - its margin past the plate is a dark page - and the
    enclosure plus the paper under the letters takes the word back."""
    rs = _promotion_run(monkeypatch, plate_tone=255)
    assert rs, "nothing came back"
    assert rs[0].kind == "bubble", [r.kind for r in rs]


def test_enclosed_writing_on_dark_ground_stays_outside_text(monkeypatch):
    """The paper gate. The same enclosure round a DARK plate is the
    embroidery case - being shut in by something is not a balloon; the
    ground has to be paper too."""
    rs = _promotion_run(monkeypatch, plate_tone=110)
    assert rs, "nothing came back"
    assert rs[0].kind == "freefloat", [r.kind for r in rs]


# ------------------------------------------- each text gets its own box

def _two_texts_mask(H=800, W=800):
    """Two three-line paragraphs on a diagonal, the way two things said are
    laid into the two lobes of one balloon."""
    m = np.zeros((H, W), np.uint8)
    for i in range(3):
        cv2.rectangle(m, (100, 100 + i * 60), (300, 140 + i * 60), 255, -1)
    for i in range(3):
        cv2.rectangle(m, (320, 280 + i * 60), (520, 320 + i * 60), 255, -1)
    return m


def test_two_diagonal_texts_are_found():
    got = CT._two_texts_in(_two_texts_mask())
    assert got is not None
    A, B, lab = got
    assert min(len(A), len(B)) == 3


def test_one_paragraph_is_one_text():
    """A paragraph's lines share their columns - the fact the staircase
    stands on."""
    m = np.zeros((800, 800), np.uint8)
    for i in range(6):
        cv2.rectangle(m, (100, 100 + i * 60), (300, 140 + i * 60), 255, -1)
    assert CT._two_texts_in(m) is None


def test_a_ragged_last_line_does_not_split_a_paragraph():
    m = np.zeros((800, 800), np.uint8)
    for i in range(3):
        cv2.rectangle(m, (100, 100 + i * 60), (300, 140 + i * 60), 255, -1)
    cv2.rectangle(m, (100, 280), (180, 320), 255, -1)   # short last line
    assert CT._two_texts_in(m) is None


def test_two_stacked_texts_a_line_height_apart_are_found():
    """044: the top lobe's mask carries a piece of the artwork, so the
    staircase fails on columns - the empty band is what catches it. The
    real pairs measure 1.11-2.85 line-heights; inside one text the widest
    band on the chapter is 0.50."""
    m = np.zeros((900, 800), np.uint8)
    for i in range(2):
        cv2.rectangle(m, (100, 100 + i * 55), (350, 140 + i * 55), 255, -1)
    for i in range(3):
        cv2.rectangle(m, (150, 320 + i * 55), (400, 360 + i * 55), 255, -1)
    assert CT._two_texts_in(m) is not None


def test_normal_leading_is_not_a_split():
    m = np.zeros((900, 800), np.uint8)
    for i in range(5):
        cv2.rectangle(m, (100, 100 + i * 55), (350, 140 + i * 55), 255, -1)
    assert CT._two_texts_in(m) is None


def test_the_stacked_bar_sits_between_the_measured_populations():
    assert 0.50 < CT.STACK_SPLIT < 1.11


def test_droplet_marks_do_not_split_a_drawn_stroke():
    """035's 쿵: droplet marks diagonal from the stroke at 2% of the ink.
    The balance gate refuses it - and an sfx box is never asked at all."""
    m = np.zeros((800, 800), np.uint8)
    cv2.rectangle(m, (100, 100), (400, 500), 255, -1)
    cv2.circle(m, (500, 600), 6, 255, -1)
    cv2.circle(m, (540, 640), 6, 255, -1)
    assert CT._two_texts_in(m) is None


def test_an_sfx_box_is_never_split():
    """와아아아 is four syllables ON a diagonal, and joining those back
    together was this same session's work."""
    m = _two_texts_mask()
    r = _r((90, 90, 500, 420), kind="sfx", mask=m)
    assert CT._each_text_its_own_box([r]) == [r]


def test_the_split_boxes_carry_their_own_ink():
    m = _two_texts_mask()
    r = _r((90, 90, 500, 420), kind="bubble", mask=m)
    out = CT._each_text_its_own_box([r])
    assert len(out) == 2
    assert [q.id for q in out] == [0, 1]
    for q in out:
        got = np.asarray(q.text_mask) > 0
        x, y, w, h = q.bbox
        ys, xs = np.nonzero(got)
        assert xs.min() >= x and xs.max() < x + w
        assert ys.min() >= y and ys.max() < y + h
    a, b = (np.asarray(q.text_mask) > 0 for q in out)
    assert not (a & b).any(), "the two boxes share ink"
    assert (a | b).sum() == (m > 0).sum(), "ink was lost in the split"


def test_the_split_runs_until_no_box_holds_two_texts():
    """Three texts down a staircase come back as three boxes."""
    m = np.zeros((1000, 1000), np.uint8)
    for s in range(3):
        for i in range(2):
            cv2.rectangle(m, (100 + s * 260, 100 + s * 180 + i * 60),
                          (300 + s * 260, 140 + s * 180 + i * 60), 255, -1)
    r = _r((90, 90, 800, 700), kind="bubble", mask=m)
    assert len(CT._each_text_its_own_box([r])) == 3


def test_two_texts_in_one_block_come_back_as_two_boxes(monkeypatch):
    """End to end: the block head returns one box across both lobes - which
    is what all three of lee's crops are - and two boxes come out, each with
    its own ink."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(3):
        cv2.rectangle(page, (200, 200 + i * 60), (400, 240 + i * 60), 20, -1)
        cv2.rectangle(seg, (200, 200 + i * 60), (400, 240 + i * 60), 255, -1)
        cv2.rectangle(page, (430, 400 + i * 60), (630, 440 + i * 60), 20, -1)
        cv2.rectangle(seg, (430, 400 + i * 60), (630, 440 + i * 60), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(190, 190, 640, 590)], seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert len(rs) == 2, [tuple(r.bbox) for r in rs]


def test_switched_off_the_block_stays_one_box(monkeypatch):
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(3):
        cv2.rectangle(page, (200, 200 + i * 60), (400, 240 + i * 60), 20, -1)
        cv2.rectangle(seg, (200, 200 + i * 60), (400, 240 + i * 60), 255, -1)
        cv2.rectangle(page, (430, 400 + i * 60), (630, 440 + i * 60), 20, -1)
        cv2.rectangle(seg, (430, 400 + i * 60), (630, 440 + i * 60), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(190, 190, 640, 590)], seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                split_texts=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert len(rs) == 1


# ------------------------- the shout label defers to a wall and to rays

def test_a_two_character_box_inside_a_drawn_circle_is_not_a_shout(monkeypatch):
    """lee, of 어쩜… in a pale thought-circle: *"1 missed this one text"*.
    Two characters filling their box measure exactly like a shout, and the
    sfx label deleted it from the page. A shout never has a wall round it."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    cv2.ellipse(page, (500, 500), (220, 160), 0, 0, 360, (225,), 7)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(2):
        cv2.rectangle(page, (420 + i * 90, 440), (490 + i * 90, 560), 30, -1)
        cv2.rectangle(seg, (420 + i * 90, 440), (490 + i * 90, 560), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(410, 430, 590, 570)], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(420, 440, 490, 560),
                                         (510, 440, 580, 560)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                             **CT.tuning_for("manhwa"))
    assert rs, "nothing came back"
    assert all(r.kind != "sfx" for r in rs), [r.kind for r in rs]


def test_the_same_two_characters_on_bare_paper_are_a_shout(monkeypatch):
    """The control: no circle, same ink, and the label stands. 크크, 저벅,
    옹성 and 씨익 are exactly this."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(2):
        cv2.rectangle(page, (420 + i * 90, 440), (490 + i * 90, 560), 30, -1)
        cv2.rectangle(seg, (420 + i * 90, 440), (490 + i * 90, 560), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(410, 430, 590, 570)], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(420, 440, 490, 560),
                                         (510, 440, 580, 560)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                             **CT.tuning_for("manhwa"))
    assert rs and any(r.kind == "sfx" for r in rs), [r.kind for r in rs]


# ------------------------------------------------- a burst is not bare paper

def _rayed_page(rays=True):
    page = np.full((900, 900), 255, np.uint8)
    if rays:
        # Sparse enough that the enclosure's 25px seal cannot close the ring
        # into a wall -- which is exactly the real bursts' situation, and the
        # reason the rays branch exists at all.
        for a in range(0, 360, 12):
            x = int(440 + 260 * np.cos(np.radians(a)))
            y = int(450 + 260 * np.sin(np.radians(a)))
            x2 = int(440 + 130 * np.cos(np.radians(a)))
            y2 = int(450 + 130 * np.sin(np.radians(a)))
            cv2.line(page, (x2, y2), (x, y), 200, 3)
    for i in range(3):
        cv2.rectangle(page, (330 + i * 60, 400), (330 + i * 60 + 40, 500),
                      30, -1)
    return page


def test_a_bursts_rays_read_as_drawn_margin():
    box = (330, 400, 220, 100)
    assert CT._ring_rays(_rayed_page(True), box) >= CT.RAYS_DENS
    assert CT._ring_rays(_rayed_page(False), box) < CT.RAYS_DENS


def test_the_rays_bar_sits_between_the_measured_populations():
    """The two bursts measure 0.066 and 0.072; the densest legitimate margin
    on paper is 0.022, a studio credit block."""
    assert 0.022 < CT.RAYS_DENS < 0.066


# --------------------------------- the box of a writing region is the writing

def test_a_writing_box_is_shaved_to_its_characters(monkeypatch):
    """lee: *"2 these boxes are way bigger than the text"*. The coverage mask
    swallowed the sword the caption is printed over - ink CONNECTED to the
    writing's ink, so no component split can take it back out."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(6):                              # the caption
        cv2.rectangle(page, (340 + i * 50, 430), (380 + i * 50, 500), 20, -1)
        cv2.rectangle(seg, (340 + i * 50, 430), (380 + i * 50, 500), 255, -1)
    cv2.rectangle(page, (480, 430), (510, 900), 20, -1)     # the sword
    cv2.rectangle(seg, (480, 430), (510, 900), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(330, 420, 650, 910)], seg))
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "freefloat")
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(340 + i * 50, 430, 380 + i * 50, 500)
                                         for i in range(6)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(split_texts=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    x, y, w, h = rs[0].bbox
    assert y + h < 600, "the box still holds the sword: %s" % (rs[0].bbox,)
    assert w >= 290, "the box lost the caption"


def test_a_legitimate_fringe_does_not_shave_the_box(monkeypatch):
    """The pillar edge grazing 024's caption is 1,048 pixels; the junk blobs
    start at 2,267. A fringe under the bar leaves the box alone."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(6):
        cv2.rectangle(page, (340 + i * 50, 430), (380 + i * 50, 500), 20, -1)
        cv2.rectangle(seg, (340 + i * 50, 430), (380 + i * 50, 500), 255, -1)
    cv2.rectangle(page, (648, 430), (658, 530), 20, -1)     # a 1000px fringe
    cv2.rectangle(seg, (648, 430), (658, 530), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(330, 420, 668, 540)], seg))
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "freefloat")
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(340 + i * 50, 430, 380 + i * 50, 500)
                                         for i in range(6)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(split_texts=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs
    x, y, w, h = rs[0].bbox
    assert x + w > 650, \
        "a fringe under the bar shaved the box: %s" % (rs[0].bbox,)


def test_an_effect_is_never_shaved():
    """A drawn shout's strokes ARE the content and CRAFT under-covers them.
    Said against the source: the shave walks only non-sfx regions."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    i = src.index("THE BOX OF A WRITING REGION")
    block = src[i:i + 1400]
    assert '_kinds.family_of(r.kind) == "sfx"' in block


def test_a_burst_stays_dialogue_end_to_end(monkeypatch):
    """The rays through the whole demotion. 042's two speech bursts: margin
    reads paper, no wall shuts (the rays are open to the page) - the rays are
    the only thing keeping the word dialogue."""
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    page = np.full((INPUT, INPUT), 255, np.uint8)
    page[62:962, 62:962] = _rayed_page(True)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(3):
        cv2.rectangle(seg, (392 + i * 60, 462), (432 + i * 60, 562), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(382, 452, 622, 572)], seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    assert rs[0].bubble_mask is None, "a balloon was found; not this case"
    assert rs[0].kind == "bubble", [r.kind for r in rs]


def test_the_same_writing_without_rays_is_outside_text(monkeypatch):
    """The control: bare paper, same ink, and the demotion stands."""
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    page = np.full((INPUT, INPUT), 255, np.uint8)
    page[62:962, 62:962] = _rayed_page(False)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(3):
        cv2.rectangle(seg, (392 + i * 60, 462), (432 + i * 60, 562), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(382, 452, 622, 572)], seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs and rs[0].kind == "freefloat", [r.kind for r in rs]


def test_display_type_is_given_back_too(monkeypatch):
    """lee's chapter title: thirteen display characters at 0.113 of the page
    width. The height gate was 0.09 for a day and priced it out - the real
    shouts run 0.21-0.66, so 0.15 keeps the backstop without deleting a
    title."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(6):
        cv2.rectangle(page, (200 + i * 90, 430), (270 + i * 90, 545), 20, 3)
        cv2.rectangle(seg, (200 + i * 90, 430), (270 + i * 90, 545), 255, 3)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(200 + i * 90, 430,
                                          270 + i * 90, 545)
                                         for i in range(6)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into", lambda *a, **k: [])
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx",
                             **CT.tuning_for("manhwa"))
    assert rs, "nothing came back"
    assert 0.09 * INPUT < 115 < CT.SFX_TEXT_H * INPUT, "not the title's case"
    assert all(r.kind == "freefloat" for r in rs), [r.kind for r in rs]


def test_the_join_is_asked_again_after_the_kinds_settle(monkeypatch):
    """Half of lee's title arrived as a CRAFT addition (born sfx) and half as
    a block fragment (classified outside text). They overlap by 0.60, and the
    census then called both writing - the first join could not see the pair
    because at its moment they were two families."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(8):
        cv2.rectangle(page, (150 + i * 90, 430), (220 + i * 90, 545), 20, 3)
        cv2.rectangle(seg, (150 + i * 90, 430), (220 + i * 90, 545), 255, 3)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    # The block head sees the LEFT half; CRAFT adds the right half as a new
    # region (born sfx) through merge_into.
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(140, 420, 500, 555)], seg))
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "freefloat")
    monkeypatch.setattr(CR, "available", lambda: True)
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(150 + i * 90, 430,
                                          220 + i * 90, 545)
                                         for i in range(8)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(
        CR, "merge_into",
        lambda regions, from_block, groups, w, h, cap, pad=0:
            [(430, 420, 940, 555)])
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(split_texts=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert len(rs) == 1, [(r.kind, tuple(r.bbox)) for r in rs]
    x, y, w, h = rs[0].bbox
    assert x <= 150 and x + w >= 930, rs[0].bbox


# ------------------------------- the frame a caption sits in is its balloon

def _framed_busy_plate():
    """A framed plate the balloon FITTER refuses - here for size, over its
    28%-of-page cap, which is one of the three refusals lee's real plates
    earn (the others are edges and brightness; a fixture busy enough for
    those defeats the enclosure test too, which is the documented
    hatched-art guard doing its job)."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    cv2.rectangle(page, (100, 250), (920, 780), 0, 6)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(page, (400 + i * 55, 460), (445 + i * 55, 550), 20, -1)
        cv2.rectangle(seg, (400 + i * 55, 460), (445 + i * 55, 550), 255, -1)
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), [(390, 450, 630, 560)], seg


def test_the_frame_a_caption_sits_in_becomes_its_balloon(monkeypatch):
    """lee, with arrows pushing a plate's box out to its ornate frame: *"teh
    deisgn on teh box is making teh box not be detected"*. The fitter wants
    flat paper and a decorated plate is not; the enclosure question already
    knows something is drawn shut round the writing."""
    img, blocks, seg = _framed_busy_plate()
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    r = rs[0]
    assert r.bubble_mask is not None, "the frame was not taken as the balloon"
    bx, by, bw, bh = r.bubble_bbox
    assert bw > 700 and bh > 400, r.bubble_bbox
    assert (bw * bh) > 0.28 * INPUT * INPUT, \
        "the fitter could have taken this plate; not the frame pass's case"
    assert r.polygon, "a balloon persists as its outline, and this has none"


def test_writing_on_the_open_page_gets_no_frame(monkeypatch):
    """The control: same writing, nothing drawn round it."""
    img, blocks, _ = _framed_busy_plate()
    img = cv2.cvtColor(np.full((INPUT, INPUT), 250, np.uint8),
                       cv2.COLOR_GRAY2BGR)
    seg2 = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(4):
        cv2.rectangle(img, (400 + i * 55, 460), (445 + i * 55, 550),
                      (20, 20, 20), -1)
        cv2.rectangle(seg2, (400 + i * 55, 460), (445 + i * 55, 550), 255, -1)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg2))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs and rs[0].bubble_mask is None


def test_two_boxes_sharing_one_frame_get_no_frame(monkeypatch):
    """Whose room it is is the split-balloon divider's question. Handing both
    the whole frame would typeset them on top of each other."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    cv2.rectangle(page, (140, 260), (880, 760), 0, 6)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(5):
        cv2.rectangle(page, (200 + i * 60, 320), (245 + i * 60, 410), 20, -1)
        cv2.rectangle(seg, (200 + i * 60, 320), (245 + i * 60, 410), 255, -1)
        cv2.rectangle(page, (500 + i * 60, 620), (545 + i * 60, 710), 20, -1)
        cv2.rectangle(seg, (500 + i * 60, 620), (545 + i * 60, 710), 255, -1)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net",
                        lambda p: _Net([(190, 310, 510, 420),
                                        (490, 610, 810, 720)], seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                split_texts=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    frameless = [r for r in rs if r.bubble_mask is None]
    assert len(rs) >= 2, [tuple(r.bbox) for r in rs]
    assert len(frameless) == len(rs), \
        "a shared frame was handed to a box whole"
    # ...and the fixture must actually put the frame within reach, or the
    # skip is never exercised and this test passes for nothing.
    from mangatl.detect import balloon as _bl
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for r in rs:
        found = _bl._round_wall_around(gray, r.bbox, roundish=False,
                                       lo=CT.ENCLOSE_LO, hi=CT.ENCLOSE_HI,
                                       seal=CT.ENCLOSE_SEAL, bounds=True)
        assert found is not None, "the frame is out of this box's reach"


def test_a_real_balloon_is_not_second_guessed():
    """A box the fitter already gave a balloon keeps it - the frame question
    is only asked where the fitter came back empty-handed."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    i = src.index("THE FRAME A CAPTION SITS IN IS ITS BALLOON")
    block = src[i:i + 1700]
    assert "r.bubble_mask is None" in block


def test_the_grow_runs_before_the_shave():
    """Grown after it, 041's boxes follow the sword's connected ink straight
    back to their pre-shave rectangles. The order is the fix."""
    import inspect

    src = inspect.getsource(CT.detect_comictext)
    grow = src.index("THE WHOLE OF THE WRITING, one more time")
    shave = src.index("THE BOX OF A WRITING REGION IS THE WRITING")
    join2 = src.index("one more pass of the join")
    assert grow < shave < join2


def test_a_late_box_is_grown_to_the_whole_of_its_ink(monkeypatch):
    """The late grow. A CRAFT-added box is the union of character rectangles,
    and CRAFT hugs the glyph cores - the contour of outlined display type
    runs past every one. lee: *"the text is not being fully encased"*."""
    page = np.full((INPUT, INPUT), 250, np.uint8)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(6):
        cv2.rectangle(page, (200 + i * 90, 430), (270 + i * 90, 545), 20, 7)
        cv2.rectangle(seg, (200 + i * 90, 430), (270 + i * 90, 545), 255, 7)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    from mangatl.detect import craft as CR
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net([], seg))
    monkeypatch.setattr(CR, "available", lambda: True)
    # CRAFT's pieces hug the cores: 6px inside the drawn outline on every side
    monkeypatch.setattr(CR, "pieces",
                        lambda im, **k: [(206 + i * 90, 436,
                                          264 + i * 90, 539)
                                         for i in range(6)])
    monkeypatch.setattr(CR, "group", lambda *a, **k: [])
    monkeypatch.setattr(CR, "merge_into",
                        lambda regions, from_block, groups, w, h, cap, pad=0:
                            [(206, 436, 714, 539)])
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(split_texts=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    x, y, w, h = rs[0].bbox
    assert x <= 200 and x + w >= 740 and y <= 430 and y + h >= 545, \
        "the box still clips the outline: %s" % (rs[0].bbox,)
