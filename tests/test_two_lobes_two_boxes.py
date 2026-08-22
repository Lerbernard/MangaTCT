"""A balloon drawn as two rounds is one balloon, and its boxes say so.

lee, with three screenshots of pairs he wants joined and one of a pair he does
not::

    here are exmaole of what i want withh teh link it shoud only be bubble text
    and only be bubbles so the ;ast screenshot shoud not be conected

**This is not the guess `detect_comictext` refuses to make.** That one is about
a block of writing a clusterer chopped in two, where the question is whether the
WORDS run on and the picture cannot answer it - see the long note there, and the
hot-spring balloon it was written for. This one is about the drawn shape: two
lobes of paper that touch were drawn as one balloon by the artist, and that is a
fact about the page.

MEASURED on all four of lee's examples, and the gap is not a close call:

    029  "영혼의 문?" + "영혼 상태로 통과할 수 있다고?"            5 px    join
    049  "하지만 이건…" + "사실상 사망 상태잖아…?"                 5 px    join
    049  "영혼이 존재하지 않아" + "몇 시간 뒤면…"                  5 px    join
    every other pair of balloons on those two pages         658 - 2144 px

...and the pair he does NOT want joined never reaches the geometry. Page 029's
"[초월] 영혼의 문" and the lines beneath it sit in a dark system panel rather
than a balloon: their interiors measure **33** and **67**, where a speech
balloon measures **255**. That is what "only be bubbles" is, and `TOUCH_PAPER`
is the number for it.

Run end to end afterwards on those pages: 029 joins one pair and leaves the
system panel alone, 049 joins both pairs, 048's four separate balloons join
nothing.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import balloon as B
from mangatl.models import TextRegion


def _region(rid, bbox, kind="bubble", mask=None, link=0):
    r = TextRegion(id=rid, bbox=bbox, text_mask=None, bubble_mask=mask,
                   bubble_bbox=bbox, kind=kind)
    r.link = link
    r.order = rid
    return r


def _page(gap, paper=255, kinds=("bubble", "bubble"), masks=(True, True)):
    """Two round balloons, `gap` pixels apart, on dark artwork."""
    g = np.full((600, 900), 40, np.uint8)
    out = []
    cx = [250, 250 + 200 + gap]
    for i, x in enumerate(cx):
        m = np.zeros(g.shape, np.uint8)
        cv2.circle(m, (x, 300), 100, 1, -1)
        g[m > 0] = paper
        out.append((m > 0).astype(np.uint8) * 255)
    regions = [_region(i, (cx[i] - 60, 280, 120, 40), kinds[i],
                       out[i] if masks[i] else None)
               for i in range(2)]
    return g, regions


# ------------------------------------------------------------- the geometry

def test_two_lobes_that_touch_are_one_balloon():
    g, rs = _page(gap=4)
    assert B.link_touching_bubbles(g, rs) == 1
    assert rs[0].link and rs[0].link == rs[1].link


def test_two_balloons_across_the_page_are_not():
    g, rs = _page(gap=400)
    assert B.link_touching_bubbles(g, rs) == 0
    assert not rs[0].link and not rs[1].link


def test_the_reach_is_the_measured_one():
    """5 px is what lee's three pairs measure and 658 px is the nearest pair he
    does not want joined. Anything between those two would do; the number is
    near the small end because a balloon that is nearly touching is a balloon
    that is nearly touching."""
    assert 5 < B.TOUCH_GAP < 100


# ------------------------------------------------------- ...and only bubbles

def test_a_dark_system_panel_is_not_a_balloon():
    """Page 029: "[초월] 영혼의 문" and the lines under it. Two runs of paper
    that touch - but the paper is navy, 33 and 67 against a balloon's 255."""
    g, rs = _page(gap=4, paper=60)
    assert B.link_touching_bubbles(g, rs) == 0


def test_the_paper_bar_sits_between_the_panel_and_the_balloon():
    assert 67 < B.TOUCH_PAPER < 255


def test_outside_text_is_not_joined():
    g, rs = _page(gap=4, kinds=("freefloat", "freefloat"))
    assert B.link_touching_bubbles(g, rs) == 0


def test_a_sound_effect_is_not_joined():
    g, rs = _page(gap=4, kinds=("sfx", "sfx"))
    assert B.link_touching_bubbles(g, rs) == 0


def test_a_narration_panel_is_not_joined():
    g, rs = _page(gap=4, kinds=("narration", "narration"))
    assert B.link_touching_bubbles(g, rs) == 0


def test_a_box_with_no_balloon_under_it_is_not_joined():
    """Outside text promoted to `bubble` by the wall test carries a label and
    no mask. There is no paper to measure and nothing to touch."""
    g, rs = _page(gap=4, masks=(True, False))
    assert B.link_touching_bubbles(g, rs) == 0


def test_a_link_somebody_already_set_is_left_alone():
    """Driven where it bites: the two lobes ARE touching, so without the guard
    this would renumber a link a person set by hand into its own group."""
    g, rs = _page(gap=4)
    rs[0].link = 9
    assert B.link_touching_bubbles(g, rs) == 0
    assert rs[0].link == 9, "it took away a link a person set by hand"
    assert not rs[1].link, "it joined the other lobe to nothing"


def test_three_lobes_come_out_as_one_group_not_two_pairs():
    g = np.full((600, 1200), 40, np.uint8)
    xs = [200, 380, 560]
    rs = []
    for i, x in enumerate(xs):
        m = np.zeros(g.shape, np.uint8)
        cv2.circle(m, (x, 300), 95, 1, -1)
        g[m > 0] = 255
        rs.append(_region(i, (x - 50, 280, 100, 40), "bubble",
                          (m > 0).astype(np.uint8) * 255))
    assert B.link_touching_bubbles(g, rs) == 1
    assert len({r.link for r in rs}) == 1 and rs[0].link


def test_one_balloon_on_its_own_is_not_a_group():
    g, rs = _page(gap=4)
    assert B.link_touching_bubbles(g, rs[:1]) == 0


# ------------------------------------------------------------ the format fork

def test_manga_is_untouched():
    from mangatl.detect import comictext as CT
    assert CT.tuning_for("manga").get("link_touching") is None
    assert CT.tuning_for(None).get("link_touching") is None


def test_the_webtoons_run_it_at_the_measured_reach():
    from mangatl.detect import comictext as CT
    for medium in ("manhwa", "manhua"):
        assert CT.tuning_for(medium)["link_touching"] == B.TOUCH_GAP, medium


def test_a_mask_that_is_not_the_shape_of_the_page_is_ignored():
    """Not a case the app makes, but a stub mask must not take a run down."""
    g, rs = _page(gap=4)
    rs[1].bubble_mask = np.ones((4, 4), np.uint8)
    assert B.link_touching_bubbles(g, rs) == 0


# ------------------------------------------ end to end, through the detector

class _Net:
    """Two touching balloons with writing in them, and the block head seeing
    both."""

    def __init__(self, seg, blocks):
        self.seg, self.blocks = seg, blocks

    def setInput(self, blob):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["blk", "seg"]

    def forward(self, names):
        blk = np.zeros((1, len(self.blocks), 6), np.float32)
        for i, (x0, y0, x1, y1) in enumerate(self.blocks):
            blk[0, i] = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0,
                         0.9, 0.9]
        seg = np.zeros((1, 1, 1024, 1024), np.float32)
        seg[0, 0] = (self.seg > 0).astype(np.float32)
        return [blk, seg]


def test_the_detector_hands_back_a_linked_pair(monkeypatch):
    """The rule is no use sitting in `balloon.py` if nothing calls it."""
    from mangatl.detect import comictext as CT
    from mangatl.models import Page
    page = np.full((1024, 1024), 40, np.uint8)
    seg = np.zeros((1024, 1024), np.uint8)
    blocks = []
    for cx in (330, 620):
        cv2.circle(page, (cx, 500), 150, 255, -1)
        cv2.circle(page, (cx, 500), 150, 20, 3)
        for i in range(3):
            cv2.rectangle(seg, (cx - 70 + i * 50, 470),
                          (cx - 70 + i * 50 + 36, 530), 255, -1)
        blocks.append((cx - 78, 462, cx + 80, 538))
    page = np.where(seg > 0, 20, page).astype(np.uint8)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(seg, blocks))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert len(rs) >= 2, [r.kind for r in rs]
    got = [r for r in rs if r.kind == "bubble"]
    assert len(got) == 2, [r.kind for r in rs]
    assert got[0].link and got[0].link == got[1].link, \
        [(r.kind, getattr(r, "link", 0)) for r in rs]


def test_the_same_page_with_it_switched_off_hands_back_neither(monkeypatch):
    from mangatl.detect import comictext as CT
    from mangatl.models import Page
    page = np.full((1024, 1024), 40, np.uint8)
    seg = np.zeros((1024, 1024), np.uint8)
    blocks = []
    for cx in (330, 620):
        cv2.circle(page, (cx, 500), 150, 255, -1)
        cv2.circle(page, (cx, 500), 150, 20, 3)
        for i in range(3):
            cv2.rectangle(seg, (cx - 70 + i * 50, 470),
                          (cx - 70 + i * 50 + 36, 530), 255, -1)
        blocks.append((cx - 78, 462, cx + 80, 538))
    page = np.where(seg > 0, 20, page).astype(np.uint8)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(seg, blocks))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                link_touching=None)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert not any(getattr(r, "link", 0) for r in rs), \
        [(r.kind, getattr(r, "link", 0)) for r in rs]
