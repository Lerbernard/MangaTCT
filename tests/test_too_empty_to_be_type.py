"""An OUTSIDE TEXT box with almost no ink in it is a drawn sound effect.

lee, with three screenshots of hand-drawn effects boxed green as **Outside
text**::

    this is a horible way of detecting outside text , outside tetx is usulay
    normal tet hats just outide the boubble while sfx are usualy text with
    starteched charaters try to use that to differentiate between them

and then, one message later, the narrowing that makes it a safe question at
all::

    it shoud only apply for outide text and sfx so boubble text shoud not be
    considered

**The diagnosis is right and the named feature does not work.** The old ring
test asked what is BEHIND the writing, which is a question about the artwork,
and that is why plain type on a sky came back as an effect. The letters are
where the answer is. But of the four letterform numbers measured off the ink --
height spread (his "stretched characters"), pen-weight variation, baseline
stray, and FILL -- his own example kills the first three: 부웅 on page 037 of
chapter 1 is a brush-drawn shout scoring **0.12** on height spread, the most
regular value in the whole set.

FILL is the survivor, and this file exists to bound it honestly.

**THE LINE IS FITTED FOR A COST, NOT FOR ACCURACY.** Asked whether a correctly
found sound effect VANISHING from a page -- which is what a run with the
sound-effect tick clear does with an sfx box -- beats one sitting there
mislabelled, lee said it does. So a false positive does not mislabel his text,
it DELETES it, and the threshold is the most aggressive one that flags nothing
real.

**AND THE FLOOR HAS TO COME FROM THE RIGHT POPULATION.** It was 0.20 for one
day, taken from the emptiest box of printed dialogue on the pages (0.225). That
is the wrong floor. This rule is only ever asked about a box already called
OUTSIDE TEXT, so dialogue inside a balloon is not a box it can hurt, and drawing
the line against those boxes made it far too shy -- it missed 부웅, the one
effect lee had actually pointed at, twice.

Measured on the population it does see, both chapters hand-labelled:

    real writing, outside a balloon   0.291  0.433  0.471  0.554  0.559
    drawn effects                     0.093  0.136  0.146  0.248  0.275

0.28 sits between them. Over all 82 pages of chapters 1 and 8, 238 boxes, it
renames seven: 부웅, three 짭툰.com watermarks and three drawn effects, and **no
real writing on any page**.

The margin is 0.011 on six labelled boxes, which is thin, and the wider
typography argues for watching it rather than relaxing: 25% of the dialogue
INSIDE balloons is emptier than 0.28. If outside-text writing ever behaves like
balloon dialogue, this line will delete some.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT
from mangatl.models import Page, TextRegion

INPUT = CT.INPUT


def _box(w=200, h=200):
    """A blank grey box to draw a specimen of writing into."""
    return np.full((h, w), 240, np.uint8)


def _solid_type(page, n=4, colour=20):
    """Set type: solid blocks of ink, which fill their rectangle."""
    for i in range(n):
        cv2.rectangle(page, (12 + i * 46, 60), (12 + i * 46 + 38, 140),
                      colour, -1)
    return page


def _hollow_shout(page, n=4, colour=20):
    """A drawn effect: the same letters as OUTLINES, so the box is mostly the
    paper the outline went round."""
    for i in range(n):
        cv2.rectangle(page, (12 + i * 46, 20), (12 + i * 46 + 38, 180),
                      colour, 2)
    return page


def _mask_of(page):
    return ((page < CT.INK).astype(np.uint8) * 255)


# ------------------------------------------------------- what the rule decides

def test_a_hollow_outlined_shout_is_a_sound_effect():
    p = _hollow_shout(_box())
    assert CT._looks_hand_drawn(p, (0, 0, 200, 200), _mask_of(p), 0.20)


def test_the_effect_lee_pointed_at_is_the_one_the_number_is_for():
    """부웅 measures 0.275, and the emptiest real box outside a balloon
    measures 0.291. There is one place the line can go."""
    t = CT.tuning_for("manhwa")["effect_fill"]
    assert 0.275 < t < 0.291, t


def test_solid_set_type_is_left_as_outside_text():
    p = _solid_type(_box())
    assert not CT._looks_hand_drawn(p, (0, 0, 200, 200), _mask_of(p), 0.20)


def test_the_threshold_is_the_thing_being_compared():
    """Same box, two lines: it is the number that decides, not the drawing."""
    p = _hollow_shout(_box())
    m = _mask_of(p)
    fill = float((m > 0).sum()) / float(200 * 200)
    assert CT._looks_hand_drawn(p, (0, 0, 200, 200), m, fill + 0.01)
    assert not CT._looks_hand_drawn(p, (0, 0, 200, 200), m, fill - 0.01)


def test_a_box_with_one_mark_in_it_is_left_alone():
    """One mark is a mark. The measurement was made on boxes holding at least
    two pieces of writing and says nothing about the others, and 'left alone'
    here means left on his page."""
    p = _box()
    cv2.rectangle(p, (20, 20), (60, 180), 20, 2)     # a single hollow stroke
    m = _mask_of(p)
    assert float((m > 0).sum()) / float(200 * 200) < 0.20, "not the empty case"
    assert not CT._looks_hand_drawn(p, (0, 0, 200, 200), m, 0.20)


def test_white_typesetting_on_a_black_balloon_is_not_read_as_empty():
    """A box measured off dark ink where the writing is WHITE holds no ink at
    all, reads as 0.00 fill, and would be thrown off the page. The bright
    fallback is what stops that."""
    p = np.full((200, 200), 15, np.uint8)
    _solid_type(p)
    p[p == 20] = 245                                  # the type, in white
    assert not CT._looks_hand_drawn(p, (0, 0, 200, 200), None, 0.20)


def test_writing_with_no_dark_ink_in_it_is_read_bright_not_read_as_empty():
    """The bright fallback, inherited from the function the numbers were
    measured with. A box with NOTHING under `INK` in it -- pale artwork, white
    typesetting -- measures 0.00 fill, which is below every threshold there is,
    and would be called an effect on the strength of holding no writing at all.
    Reading it bright is what makes the answer come off the letters."""
    p = np.full((200, 200), 150, np.uint8)         # no dark ink anywhere
    _hollow_shout(p, colour=250)
    assert int((p < CT.INK).sum()) == 0, "not the case this guards"
    assert CT._looks_hand_drawn(p, (0, 0, 200, 200), None, 0.20)
    solid = np.full((200, 200), 150, np.uint8)
    _solid_type(solid, colour=250)
    assert not CT._looks_hand_drawn(solid, (0, 0, 200, 200), None, 0.20)


def test_a_box_too_small_to_measure_is_left_alone():
    p = np.full((15, 15), 240, np.uint8)
    assert not CT._looks_hand_drawn(p, (0, 0, 15, 15), None, 0.20)


def test_it_measures_the_mask_it_is_given_not_the_page_under_it():
    """The mask is the detector's own record of where the writing is. A page
    covered in dark artwork must not make an effect look full."""
    p = _hollow_shout(_box())
    m = _mask_of(p)
    p[:] = np.minimum(p, 60)                          # black out the artwork
    assert CT._looks_hand_drawn(p, (0, 0, 200, 200), m, 0.20), \
        "it read the page instead of the mask"


def test_a_box_off_the_page_edge_is_clipped_not_crashed():
    p = _hollow_shout(_box())
    CT._looks_hand_drawn(p, (-40, -40, 400, 400), _mask_of(p), 0.20)


# ------------------------------------------------------------ the format fork

def test_manga_is_untouched():
    """Measured on the Korean webtoons and nowhere else, so manga is off."""
    assert CT.tuning_for("manga").get("effect_fill") is None
    assert CT.tuning_for(None).get("effect_fill") is None
    assert CT.tuning_for("nonsense").get("effect_fill") is None


def test_the_webtoons_run_it_at_the_measured_number():
    for medium in ("manhwa", "manhua"):
        assert CT.tuning_for(medium)["effect_fill"] == 0.28, medium


def test_the_number_is_below_the_lowest_real_outside_text_box():
    """0.291 is the emptiest box of real writing OUTSIDE a balloon -- ch8 007,
    "그게 / 네 죄를 갚는 방법이다, / 벨라 오투아." The floor comes from that
    population and not from dialogue in balloons, which this rule never sees.
    The threshold has to stay under it or the rule starts eating text."""
    assert CT.tuning_for("manhwa")["effect_fill"] < 0.291


# ------------------------------------------ end to end, through the detector

class _Net:
    """The block head and the mask, minus the 95MB.

    The mask is handed in as an IMAGE of the writing rather than a rectangle
    over it, and that is the whole point of this harness: the real `seg` head
    traces the strokes, the box's `text_mask` is cut from it, and it is that
    mask the rule measures. A fixture that fills the block rectangle instead
    hands every specimen a fill of 0.86 and tests nothing.
    """

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


def _outside_text_page(hollow, paper=30, letter=245):
    """A square page - dark all over, so `_classify_kind` says freefloat - with
    one specimen of writing in the middle of it, and the mask that goes with it.

    Square because `_letterbox` then does nothing and the mask lands where it
    was put. The mask is built from the SHAPES and not by thresholding the
    page: on a dark page every pixel is under `INK`, so a thresholded mask
    covers the whole 1024 square, the coverage pass harvests it as one
    page-sized sound effect, and the fixture measures nothing. That is a
    mistake this file made once.
    """
    page = np.full((INPUT, INPUT), paper, np.uint8)
    spec = np.zeros((200, 200), np.uint8)
    (_hollow_shout if hollow else _solid_type)(spec, colour=255)
    page[420:620, 400:600] = np.where(spec > 0, letter, paper)
    seg = np.zeros((INPUT, INPUT), np.uint8)
    seg[420:620, 400:600] = spec
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), [(400, 420, 600, 620)], seg


def _run(monkeypatch, hollow, **kw):
    img, blocks, seg = _outside_text_page(hollow)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    tune.update(kw)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_the_effect_comes_back_as_a_sound_effect(monkeypatch):
    rs = _run(monkeypatch, hollow=True)
    assert rs and any(r.kind == "sfx" for r in rs), [r.kind for r in rs]


def test_the_same_page_with_solid_type_stays_outside_text(monkeypatch):
    rs = _run(monkeypatch, hollow=False)
    assert rs and not any(r.kind == "sfx" for r in rs), [r.kind for r in rs]


def test_switching_it_off_leaves_the_effect_as_outside_text(monkeypatch):
    """The one control that matters: with the number off, nothing about the
    page has changed and the box is still there under its old name."""
    on = _run(monkeypatch, hollow=True)
    off = _run(monkeypatch, hollow=True, effect_fill=None)
    assert len(on) == len(off)
    assert [tuple(r.bbox) for r in on] == [tuple(r.bbox) for r in off], \
        "the rule moved a box, and it is only allowed to rename one"
    assert any(r.kind == "sfx" for r in on)
    assert not any(r.kind == "sfx" for r in off)


def test_it_never_changes_the_number_of_boxes(monkeypatch):
    """Renaming only. It is `project.only_kinds` that drops the sfx later, on a
    run that did not ask for them, and that is a separate decision in a
    separate file."""
    for hollow in (True, False):
        on = _run(monkeypatch, hollow=hollow)
        off = _run(monkeypatch, hollow=hollow, effect_fill=None)
        assert len(on) == len(off) == 1, (len(on), len(off))


def test_dialogue_is_never_asked_the_question(monkeypatch):
    """lee: *"boubble text shoud not be considered"*. The loop reads
    `kind == "freefloat"` and this is the assertion that says so: the same
    hollow specimen, on PAPER instead of artwork, is dialogue and stays
    dialogue however empty its box is."""
    img, blocks, seg = _outside_text_page(hollow=True, paper=240, letter=20)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    # `loose_bubble` off. It has its OWN sound-effect branch for a dialogue box
    # with no balloon under it -- lee's 부스럭 -- and this fixture is exactly
    # that shape, so leaving it on would have the box taken by a different rule
    # than the one under test. See `tests/test_the_sky_is_not_a_balloon.py`.
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                loose_bubble=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs and not any(r.kind == "sfx" for r in rs), [r.kind for r in rs]


def test_the_balloon_pass_gets_the_last_word_before_this_one(monkeypatch):
    """It runs AFTER `attach_balloons`, so a box the wall test rescued into a
    grey balloon is dialogue by the time this is asked and is never asked.
    Every promotion beats this demotion, which is the safe direction: on a
    manhwa an sfx label costs lee the box."""
    seen = {}
    real = CT._looks_hand_drawn

    def spy(gray, bbox, mask=None, thresh=0.20, _r=real):
        seen[tuple(int(v) for v in bbox)] = True
        return _r(gray, bbox, mask, thresh)

    import mangatl.detect.balloon as B
    order = []
    real_attach = B.attach_balloons

    def attach(gray, regions, *a, **kw):
        order.append("balloons")
        for r in regions:
            r.kind = "bubble"                          # the wall rescues it
        return real_attach(gray, regions, *a, **kw)

    monkeypatch.setattr(CT, "_looks_hand_drawn", spy)
    monkeypatch.setattr(B, "attach_balloons", attach)
    # `loose_bubble` off, because it sits between the two things being ordered
    # here and would take the word "dialogue" straight back off this fixture --
    # a synthetic page of dark artwork, no balloon mask, no wall. That is the
    # right answer for that rule and the wrong question for this test.
    rs = _run(monkeypatch, hollow=True, loose_bubble=None)
    assert order == ["balloons"], "the balloon pass did not run"
    assert not seen, "a rescued balloon was still asked if it was an effect"
    assert rs and not any(r.kind == "sfx" for r in rs)


# ------------------------------------------------- and the tall one, on its own

def test_one_tall_character_out_on_the_artwork_is_a_sound_effect(monkeypatch):
    """lee: *"the trird shoud be sfx"* -- 앙 painted over the dragon's fire.

    Its ink is NOT thin: 0.354, well over the line, because the character is a
    fat brushed shape. Its box is 211 wide by 268 tall. Korean runs along a
    line, so writing out on the artwork is wide -- the other four outside-text
    boxes on the chapter measure 0.26, 0.43, 0.63 and 0.76 of their width in
    height, and this one measures 1.27.
    """
    img, blocks, seg = _outside_text_page(hollow=False)
    # one solid character, taller than it is wide, which the ink test passes
    seg[:] = 0
    seg[380:660, 450:590] = 255
    page = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    page[380:660, 450:590] = 245
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    blocks = [(444, 374, 596, 666)]
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    r = rs[0]
    assert r.bbox[3] > r.bbox[2], "the fixture stopped being a tall box"
    assert not CT._looks_hand_drawn(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                                    r.bbox, r.text_mask, 0.28), \
        "the ink test catches it, so this is not measuring the tall rule"
    assert r.kind == "sfx", r.kind


def test_a_wide_run_of_outside_text_is_not_touched_by_the_tall_rule():
    assert not CT._taller_than_wide((0, 0, 302, 129))
    assert not CT._taller_than_wide((0, 0, 187, 142))
    assert CT._taller_than_wide((0, 0, 211, 268))


def test_a_square_box_is_not_tall_enough():
    """1.15, the same bar the file already uses to call a box vertical. A box
    that is merely not-wide is not evidence of anything."""
    assert not CT._taller_than_wide((0, 0, 200, 220))
    assert CT._taller_than_wide((0, 0, 200, 240))


def test_a_box_with_no_width_is_not_called_tall():
    assert not CT._taller_than_wide((0, 0, 0, 100))
