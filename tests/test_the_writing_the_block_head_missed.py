"""A box the coverage pass found is not automatically a sound effect.

lee, of "진 빠진다, 진 빠져" hand-lettered onto a bedroom floor::

    we lost this it use to be outside texxt and now it not maerk thst the only
    issue i see in teh whole thing

**Nothing about the labelling rules did it.** With `effect_fill` and
`loose_bubble` both switched off the box still came back a sound effect, because
the coverage pass calls everything it finds `sfx` on sight -- and a run with
the sound-effect tick clear drops those, so the writing left the page with no
box to rename or delete.

He had re-cut the chapter from 70 pages to 71. On the new cut the block head
stopped seeing that writing, so it arrived through the coverage pass instead.
Which head finds a piece of writing is not a fact about the writing.

TWO THINGS WERE WRONG AND BOTH ARE FIXED HERE.

**The box was two things.** The leftover-join's VERTICAL reach (0.9) pulled the
writing and a purple lightning bolt drawn below it into one 335x249 box holding
18% ink -- which reads as a drawn shape whatever else is done. It is now 0.6.
The sideways reach is untouched at 1.8 and must be: the two halves of one 퍽써!
on page 18 of chapter 227 sit 1.47 smaller-marks apart, so anything under that
cuts a real effect in two. The vertical one had room -- the case it exists to
refuse is two stacked effects at 1.02 smaller-marks, which 0.6 refuses exactly
as 0.9 did.

**The label was a guess dressed as a fact.** A coverage box is now asked the
same three questions the effects rule asks, and one that answers no to all three
is writing:

    thin ink          under `cover_text` (0.25) of its box
    taller than wide
    big characters    over `COVER_CHAR` (0.10) of the page width

0.25 rather than the effects rule's 0.28 because the populations differ and so
does the cost: out here a wrong answer deletes a box the block head already
failed to find. The character size is what carries it -- 진 빠진다 measures
**0.051** and 달칵 on the next page measures **0.109**.

MEASURED, 17 pages, 17 coverage boxes: **one moves, and it is his.** 부스럭, 파,
앙, 달칵 and 스윽 all stay sound effects. Two junk boxes -- a fragment of a brush
stroke and a thought balloon's trail circles -- come back as outside text
instead of being dropped, which is a box to delete rather than nothing at all.

Two numbers fitted with one positive example, and that is worth saying plainly.
What is not thin is the direction: when this rule is wrong lee gets a box to
delete, and when the old behaviour was wrong he got silence.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT
from mangatl.models import Page

INPUT = CT.INPUT


# ------------------------------------------------------------ the two numbers

def test_manga_is_untouched():
    assert CT.tuning_for("manga").get("cover_text") is None
    assert CT.tuning_for(None).get("cover_text") is None


def test_the_webtoons_run_it_at_the_measured_number():
    for medium in ("manhwa", "manhua"):
        assert CT.tuning_for(medium)["cover_text"] == 0.25, medium


def test_the_coverage_bar_is_looser_than_the_effects_one():
    """Same measurement, different cost. A wrong answer on a box the block head
    DID find leaves it on the page under the wrong name; a wrong answer out
    here deletes it."""
    t = CT.tuning_for("manhwa")
    assert t["cover_text"] < t["effect_fill"]


def test_the_character_bar_sits_between_the_two_boxes_that_set_it():
    """진 빠진다 is 0.051 of the page wide and 달칵 on the next page is 0.109."""
    assert 0.051 < CT.COVER_CHAR <= 0.109


def test_the_reach_is_the_swept_one_and_still_wide_and_flat():
    """Only the vertical reach moved, 0.9 to 0.6. The sideways one is holding a
    measured case together on chapter 227 and did not move at all -- and the
    shape of the reach is the same as it always was: writing runs along a line,
    so it reaches further sideways than down."""
    t = CT.tuning_for("manhwa")
    assert (t["join_x"], t["join_y"]) == (1.8, 0.6)
    assert t["join_x"] > t["join_y"]


# ------------------------------------------ end to end, through the detector

class _Net:
    """The mask head with writing on it and the block head blind to it, which
    is the whole case: everything here arrives through the coverage pass."""

    def __init__(self, seg):
        self.seg = seg

    def setInput(self, blob):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["blk", "seg"]

    def forward(self, names):
        blk = np.zeros((1, 1, 6), np.float32)          # no blocks at all
        seg = np.zeros((1, 1, INPUT, INPUT), np.float32)
        seg[0, 0] = (self.seg > 0).astype(np.float32)
        return [blk, seg]


def _page(glyph=48, n=5, hollow=False, tall=False, thick=4):
    """A run of writing on open artwork, at whatever size is asked for."""
    page = np.full((INPUT, INPUT), 150, np.uint8)
    spec = np.zeros((INPUT, INPUT), np.uint8)
    x, y = 300, 450
    if tall:
        # SOLID, so the ink test does not answer for it; two pieces, so it is
        # not thrown out for holding one mark; and the pieces SMALL, so the
        # character-size test does not answer for it either. All that is left
        # to notice is that the box is taller than it is wide.
        cv2.rectangle(spec, (x, y), (x + 90, y + 80), 255, -1)
        cv2.rectangle(spec, (x + 8, y + 125), (x + 82, y + 205), 255, -1)
    else:
        for i in range(n):
            cv2.rectangle(spec, (x + i * int(glyph * 1.25), y),
                          (x + i * int(glyph * 1.25) + glyph, y + glyph), 255,
                          thick if hollow else -1)
    page = np.where(spec > 0, 20, page).astype(np.uint8)
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), spec


def _run(monkeypatch, **kw):
    img, seg = _page(**{k: v for k, v in kw.items()
                        if k in ("glyph", "n", "hollow", "tall", "thick")})
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    tune.update({k: v for k, v in kw.items()
                 if k not in ("glyph", "n", "hollow", "tall", "thick")})
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_small_solid_writing_the_block_head_missed_is_outside_text(monkeypatch):
    rs = _run(monkeypatch)
    assert rs and rs[0].kind == "freefloat", [r.kind for r in rs]


def test_a_hollow_shout_is_still_a_sound_effect(monkeypatch):
    rs = _run(monkeypatch, hollow=True)
    assert rs and rs[0].kind == "sfx", [r.kind for r in rs]


def test_one_tall_character_is_still_a_sound_effect(monkeypatch):
    rs = _run(monkeypatch, tall=True)
    assert rs and rs[0].kind == "sfx", [r.kind for r in rs]


def test_big_characters_are_still_a_sound_effect(monkeypatch):
    """부스럭 and 파 are solid, upright and enormous. Size is the question that
    keeps them."""
    rs = _run(monkeypatch, glyph=170, n=3)
    assert rs, "nothing came back"
    gray = np.zeros((INPUT, INPUT), np.uint8)
    assert rs[0].kind == "sfx", rs[0].kind


def test_switching_it_off_leaves_them_all_sound_effects(monkeypatch):
    on = _run(monkeypatch)
    off = _run(monkeypatch, cover_text=None)
    assert [tuple(r.bbox) for r in on] == [tuple(r.bbox) for r in off], \
        "the rule moved a box, and it is only allowed to rename one"
    assert on[0].kind == "freefloat" and off[0].kind == "sfx"


def test_it_never_changes_the_number_of_boxes(monkeypatch):
    on = _run(monkeypatch)
    off = _run(monkeypatch, cover_text=None)
    assert len(on) == len(off) == 1


class _NetB(_Net):
    """...and the same page WITH the block head seeing it."""

    def __init__(self, seg, block):
        super().__init__(seg)
        self.block = block

    def forward(self, names):
        _blk, seg = super().forward(names)
        x0, y0, x1, y1 = self.block
        blk = np.zeros((1, 1, 6), np.float32)
        blk[0, 0] = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0,
                     0.9, 0.9]
        return [blk, seg]


def test_a_box_the_BLOCK_head_found_is_not_reached_by_this(monkeypatch):
    """The rule renames boxes the COVERAGE pass produced and nothing else.

    Driven where the two rules disagree: the box is hollow enough for the
    effects rule to call it a sound effect and full enough that the coverage
    rule, if it were allowed near it, would hand it straight back. The block
    head found it, so it is not asked -- and the effects rule's answer, which
    was measured on exactly this population, stands.
    """
    img, seg = _page(hollow=True, thick=4)
    ys, xs = np.nonzero(seg)
    block = (int(xs.min()) - 6, int(ys.min()) - 6,
             int(xs.max()) + 6, int(ys.max()) + 6)
    monkeypatch.setattr(CT, "_get_net", lambda p: _NetB(seg, block))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                effect_fill=0.34, cover_text=0.20)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    r = rs[0]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert CT._looks_hand_drawn(gray, r.bbox, r.text_mask, 0.34), \
        "the fixture is not an effect by the effects rule"
    assert not CT._looks_hand_drawn(gray, r.bbox, r.text_mask, 0.20), \
        "the coverage rule would agree anyway, so this tests nothing"
    assert not CT._taller_than_wide(r.bbox)
    assert CT._glyph_share(gray, r.bbox, r.text_mask) < CT.COVER_CHAR
    assert r.kind == "sfx", r.kind
