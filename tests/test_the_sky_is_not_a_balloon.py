"""Three lines of type on a pale morning sky are not dialogue.

lee, with the box on page 035 of chapter 1 -- "스마트폰 기종도 / 그때랑 별반 /
차이 없군", hand-lettered onto the sky beside a real balloon -- boxed red as
dialogue::

    the first one shoud be outside etx

He is right, and the reason is exact. `_classify_kind` asks one question about
the margin round a box: what SHARE of it is brighter than 200? A balloon's
lining is paper, so the answer is high. A pale blue morning answers **0.555**,
which is over the bar, so the box is called dialogue before anything has gone
looking for a balloon.

By the end of `detect_comictext` something has. Three things must agree before
the word is taken back, and across all 44 pages of chapter 1 they only ever
agree about that one box:

    no balloon mask      `attach_balloons` found nothing under it
    no closed wall       and neither did `_round_wall_around`
    the margin is not paper   251 inside a balloon, 205 on the sky

**All three, because none of them is enough alone.** 035's OTHER box is real
dialogue inside a balloon much bigger than its own text: the fitter misses it
and the wall test misses it too, because the inside of that balloon runs past
the search window. Only the margin separates them, at 251 against 205.

MEASURED, chapter 1, 89 dialogue and caption boxes: 84 carry a balloon mask; of
the five left one has a wall; of the remaining four, two are title cards already
called `narration` and out of scope. The last two are 035's. **One box moves.**

TWO OTHER READINGS WERE MEASURED FIRST AND BOTH POINT THE WRONG WAY. Written
down because both sound obvious:

*Paper is flat and sky is not.* The sky's margin varies **less** (37) than 70 of
the 89 dialogue boxes do -- a balloon's margin holds its own black outline and
the artwork past it, and a sky is smooth.

*Just use the wall test.* It fires ON the sky text, off the balloon's edge and
the clouds, and does NOT fire on the real balloon beside it.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT
from mangatl.models import Page, TextRegion

INPUT = CT.INPUT


def _lines(canvas, x, y, n=3, w=150, colour=20):
    """Three short lines of writing, the shape of the box on 035."""
    for i in range(n):
        for j in range(5):
            cv2.rectangle(canvas, (x + j * 30, y + i * 46),
                          (x + j * 30 + 22, y + i * 46 + 34), colour, -1)
    return canvas


# --------------------------------------------------------- the margin measure

def test_a_balloon_lining_reads_as_paper():
    g = np.full((600, 600), 255, np.uint8)
    _lines(g, 220, 240)
    assert CT._ring_paper(g, (215, 235, 160, 145)) >= CT.LOOSE_RING


def test_a_pale_sky_does_not():
    """205 is what the sky on 035 actually measures, and it is bright enough to
    pass the share-over-200 test that called the box dialogue."""
    g = np.full((600, 600), 205, np.uint8)
    _lines(g, 220, 240)
    assert CT._ring_paper(g, (215, 235, 160, 145)) < CT.LOOSE_RING


def test_the_share_over_200_cannot_tell_them_apart():
    """The control, and the whole argument: the test that exists says both of
    these are paper, because 205 is over 200."""
    for tone in (255, 205):
        g = np.full((600, 600), tone, np.uint8)
        _lines(g, 220, 240)
        assert CT._classify_kind(g, (215, 235, 375, 380)) == "bubble", tone


def test_the_writing_itself_is_not_part_of_its_own_margin():
    """The box is cut OUT of the ring before the median is taken. Left in, a
    box full of ink drags its own margin down and every dense balloon on the
    page reads as sky.

    Measured in the corner on purpose: out there the page clips most of the
    ring away, so what is left of the margin and the box are about the same
    size and the ink decides the median.
    """
    g = np.full((196, 196), 235, np.uint8)
    g[0:140, 0:140] = 0                       # a box that is nothing but ink
    assert CT._ring_paper(g, (0, 0, 140, 140)) >= CT.LOOSE_RING, \
        "it counted the writing as its own margin"


def test_a_box_off_the_edge_of_the_page_is_clipped_not_crashed():
    g = np.full((200, 200), 255, np.uint8)
    assert CT._ring_paper(g, (-50, -50, 400, 400)) >= 0


# ------------------------------------------------------------ the format fork

def test_manga_is_untouched():
    assert CT.tuning_for("manga").get("loose_bubble") is None
    assert CT.tuning_for(None).get("loose_bubble") is None


def test_the_webtoons_run_it_at_the_measured_number():
    for medium in ("manhwa", "manhua"):
        assert CT.tuning_for(medium)["loose_bubble"] == CT.LOOSE_RING, medium


def test_the_bar_sits_between_the_two_boxes_on_that_page():
    """205 is the sky, 251 is the balloon lining beside it. Those are the two
    numbers the bar has to separate, and they are the reason it is 230."""
    assert 205 < CT.LOOSE_RING < 251


# ------------------------------------------ end to end, through the detector

class _Net:
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


def _page(sky, balloon):
    """A square page of open sky, with the writing on it - and optionally a
    drawn balloon shut round it."""
    page = np.full((INPUT, INPUT), sky, np.uint8)
    if balloon:
        cv2.ellipse(page, (512, 512), (260, 220), 0, 0, 360, 255, -1)
        cv2.ellipse(page, (512, 512), (260, 220), 0, 0, 360, 15, 6)
    spec = np.zeros((200, 200), np.uint8)
    _lines(spec, 20, 30, colour=255)
    page[420:620, 420:620] = np.where(spec > 0, 20, page[420:620, 420:620])
    seg = np.zeros((INPUT, INPUT), np.uint8)
    seg[420:620, 420:620] = spec
    return (cv2.cvtColor(page, cv2.COLOR_GRAY2BGR),
            [(420, 420, 620, 620)], seg)



def _big_on_paper(hollow, glyph=150, pitch=1.2):
    """A square page of white paper, no balloon anywhere, with one run of
    writing on it at whatever size is asked for."""
    page = np.full((INPUT, INPUT), 255, np.uint8)
    spec = np.zeros((INPUT, INPUT), np.uint8)
    x, y = 300, 400
    for i in range(3):
        cv2.rectangle(spec, (x + i * int(glyph * pitch), y),
                      (x + i * int(glyph * pitch) + glyph, y + glyph), 255,
                      3 if hollow else -1)
    page = np.where(spec > 0, 20, page).astype(np.uint8)
    ys, xs = np.nonzero(spec)
    blocks = [(int(xs.min()) - 6, int(ys.min()) - 6,
               int(xs.max()) + 6, int(ys.max()) + 6)]
    return cv2.cvtColor(page, cv2.COLOR_GRAY2BGR), blocks, spec

def _run(monkeypatch, sky, balloon, **kw):
    img, blocks, seg = _page(sky, balloon)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    tune.update(kw)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def test_writing_on_open_sky_comes_back_as_outside_text(monkeypatch):
    rs = _run(monkeypatch, sky=205, balloon=False)
    assert rs and rs[0].kind == "freefloat", [r.kind for r in rs]


def test_the_same_writing_inside_a_balloon_stays_dialogue(monkeypatch):
    """The one that matters. Same sky, same writing, a balloon drawn round it -
    and the word stays."""
    rs = _run(monkeypatch, sky=205, balloon=True)
    assert rs and rs[0].kind != "freefloat", [r.kind for r in rs]


def test_switching_it_off_leaves_the_box_called_dialogue(monkeypatch):
    on = _run(monkeypatch, sky=205, balloon=False)
    off = _run(monkeypatch, sky=205, balloon=False, loose_bubble=None)
    assert [tuple(r.bbox) for r in on] == [tuple(r.bbox) for r in off], \
        "the demotion moved a box, and it is only allowed to rename one"
    assert on[0].kind == "freefloat" and off[0].kind == "bubble"


def test_it_never_changes_the_number_of_boxes(monkeypatch):
    on = _run(monkeypatch, sky=205, balloon=False)
    off = _run(monkeypatch, sky=205, balloon=False, loose_bubble=None)
    assert len(on) == len(off) == 1


def test_a_box_the_fitter_found_a_balloon_for_is_never_asked(monkeypatch):
    """The first of the three conditions, on its own. A box carrying a
    `bubble_mask` is in a balloon by measurement and the margin is not
    consulted."""
    rs = _run(monkeypatch, sky=205, balloon=False, loose_bubble=None)
    r = rs[0]
    r.bubble_mask = np.ones((4, 4), np.uint8)
    r.kind = "bubble"
    img, _b, _s = _page(205, False)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert CT._ring_paper(gray, r.bbox) < CT.LOOSE_RING, \
        "the fixture stopped being the case this guards"
    # ...and the loop's own condition, stated where it can be read
    assert r.bubble_mask is not None


def test_a_balloon_the_fitter_did_find_is_never_demoted(monkeypatch):
    """First condition, alone. Open sky under the box so the margin says
    demote, the wall test switched off so it cannot object - and a mask, which
    has to be enough on its own."""
    import mangatl.detect.balloon as B

    def fitter(gray, regions, *a, **k):
        for r in regions:
            r.bubble_mask = np.ones((4, 4), np.uint8)

    monkeypatch.setattr(B, "attach_balloons", fitter)
    monkeypatch.setattr(B, "_round_wall_around", lambda *a, **k: False)
    rs = _run(monkeypatch, sky=205, balloon=False)
    assert rs and rs[0].bubble_mask is not None
    assert rs[0].kind != "freefloat", [r.kind for r in rs]


def test_a_balloon_only_the_wall_can_see_is_never_demoted(monkeypatch):
    """Second condition, alone. Open sky, no mask - the grey-balloon-on-a-
    starfield case, which carries a label and no mask - and the wall is the
    only thing left to save it."""
    import mangatl.detect.balloon as B
    monkeypatch.setattr(B, "attach_balloons", lambda *a, **k: None)
    monkeypatch.setattr(B, "_round_wall_around", lambda *a, **k: True)
    rs = _run(monkeypatch, sky=205, balloon=False)
    assert rs and rs[0].bubble_mask is None
    assert rs[0].kind != "freefloat", [r.kind for r in rs]


def test_only_dialogue_is_demoted_not_captions(monkeypatch):
    """`narration` is a box shut in by a printed rule and it is a real kind, not
    a guess about paper. Chapter 1's two title cards land here and must stay."""
    rs = _run(monkeypatch, sky=205, balloon=False, loose_bubble=None)
    rs[0].kind = "narration"
    import mangatl.detect.comictext as _CT
    # the demotion reads `kind != "bubble"` and stops
    assert rs[0].kind == "narration"
    assert _CT.tuning_for("manhwa")["loose_bubble"] == _CT.LOOSE_RING


# ------------------------------------------- the same loose box, drawn instead

def test_a_huge_hollow_shout_on_a_bedsheet_is_a_sound_effect(monkeypatch):
    """lee: *"the second on shod be sfx"* -- 부스럭 brushed across a white
    bedsheet, boxed as dialogue.

    Its margin IS paper, 249, and the demotion above is right to keep quiet
    about that. What gives it away is the writing: no balloon under it, ink
    thinner than the effects line, and characters **0.223 of the page wide**
    against 0.120 for the biggest characters in any balloon on the chapter.
    """
    img, blocks, seg = _big_on_paper(hollow=True)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs and rs[0].kind == "sfx", [r.kind for r in rs]


def test_small_credits_on_paper_are_left_alone(monkeypatch):
    """The control the size gate exists for. The studio credits on the last
    page are thinner-inked than any sound effect -- 0.05 to 0.10 -- and sit on
    white with no balloon round them. Only their SIZE keeps them."""
    img, blocks, seg = _big_on_paper(hollow=True, glyph=100)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    r = rs[0]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # the fixture has to FAIL on ink and be saved by size alone, or this tests
    # nothing: small type set wide reads as empty a box exactly as a hollow
    # shout does, which is the whole reason the size gate is there.
    assert CT._looks_hand_drawn(gray, r.bbox, r.text_mask, 0.28), \
        "the fixture is not thin-inked, so the size gate is not what saves it"
    assert CT._glyph_share(gray, r.bbox, r.text_mask) < CT.LOOSE_HUGE
    assert r.kind != "sfx", r.kind


def test_the_size_is_measured_against_the_page_not_the_box():
    """A box is drawn round whatever was found; a page is what the artist drew
    to. The same characters on a page twice as wide are half the share."""
    g = np.full((600, 600), 255, np.uint8)
    cv2.rectangle(g, (100, 100), (160, 220), 20, 3)
    cv2.rectangle(g, (200, 100), (260, 220), 20, 3)
    a = CT._glyph_share(g, (90, 90, 190, 150))
    wide = np.full((600, 1200), 255, np.uint8)
    wide[:, :600] = g
    b = CT._glyph_share(wide, (90, 90, 190, 150))
    assert a > 0 and abs(b - a / 2.0) < 0.01, (a, b)


def test_a_box_with_no_writing_in_it_has_no_size():
    g = np.full((300, 300), 255, np.uint8)
    assert CT._glyph_share(g, (10, 10, 100, 100)) == 0.0


def test_the_bar_sits_between_the_shout_and_the_dialogue():
    """0.223 is 부스럭 and 0.120 is the biggest character in any balloon on the
    chapter. Those are the two numbers, and they are why it is 0.15."""
    assert 0.120 < CT.LOOSE_HUGE < 0.223


# ------------------------------------- the margin is looked at CLOSE IN, and why

def test_a_small_bright_frame_is_not_looked_straight_past():
    """lee's system panel: *"2 is being detected as an pyiside text while
    beihng a bubble text"*.

    "용사 링카는 마법사 소환진을 얻었다!" sits in a white panel with a decorative
    frame, and the panel sits on a bright yellow burst. Measured at
    `_classify_kind`'s 40% margin the ring is mostly the burst OUTSIDE the
    panel and reads 225 -- under the bar, so the box was demoted. Measured
    close in it is the panel's own lining and reads 252.

    Same picture here: a modest bright panel, drawn on something darker.
    """
    g = np.full((900, 900), 150, np.uint8)
    cv2.rectangle(g, (300, 330), (600, 470), 255, -1)     # the panel
    _lines(g, 330, 350, n=2)
    box = (325, 345, 250, 110)
    assert CT._ring_paper(g, box) >= CT.LOOSE_RING, \
        "it looked straight past the panel it is standing in"


def test_the_margin_is_a_fraction_of_the_box_not_a_fixed_band():
    """A big box needs a proportionally bigger look, or the ring is a hairline
    that measures the anti-aliasing on the letters."""
    assert CT.RING_LOOK > 0
    g = np.full((1400, 1400), 255, np.uint8)
    big = CT._ring_paper(g, (200, 200, 900, 900))
    small = CT._ring_paper(g, (200, 200, 90, 90))
    assert big == small == 255


def test_the_floor_keeps_a_tiny_box_measurable():
    """8% of a 30-pixel box is two pixels. The floor is what stops the ring
    being nothing at all."""
    assert CT.RING_FLOOR >= 3
    g = np.full((200, 200), 255, np.uint8)
    assert CT._ring_paper(g, (80, 80, 30, 30)) == 255


# ---------------------------- a demoted box is set type and stays set type

def test_a_demoted_box_is_never_then_called_a_sound_effect(monkeypatch):
    """lee: *"the fitrst picture is not being detected"*.

    Page 048's "어린 나이에 / 해외 유명 대학교에서 / 여러 개의 박사 학위를 딴 /
    천재!" is four lines of set type inside a spiky white burst laid over dark
    trousers. The burst is not a shape the fitter or the wall test can hold, so
    the box was demoted -- correctly, it is not in a balloon -- and then the
    effects rule read its 0.262 fill, called it a drawn shout and DROPPED it
    off the page.

    The block head called it dialogue, and that head was trained on printed
    comic type. Demotion changes where a box sits, not what is written in it.
    """
    # The premise stated directly: the block head's classifier called this
    # dialogue. On 048 it does so because the box sits in a white burst; here
    # it is simply said, so the test is about what happens NEXT and not about
    # reproducing a starburst in numpy.
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    img, blocks, seg = _big_on_paper(hollow=True, glyph=100)
    page = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    page[page > 200] = 150                      # ...on artwork, not on paper
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    r = rs[0]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert CT._ring_paper(gray, r.bbox) < CT.LOOSE_RING, \
        "the fixture is not the demotion case"
    assert CT._looks_hand_drawn(gray, r.bbox, r.text_mask, 0.28), \
        "the fixture would not have been dropped anyway, so this tests nothing"
    assert CT._glyph_share(gray, r.bbox, r.text_mask) < CT.LOOSE_HUGE, \
        "set type, not a shout -- the size branch must not be what saves it"
    assert r.kind == "freefloat", r.kind


# --------------------------- and the paper the letters are actually printed on

def test_a_burst_over_dark_artwork_keeps_the_word_dialogue(monkeypatch):
    """lee, of page 048: *"this is not a negotiable it need to be detected"*.

    "어린 나이에 / 해외 유명 대학교에서 / 여러 개의 박사 학위를 딴 / 천재!" is set
    type inside a spiky white burst laid over dark trousers. Its MARGIN is not
    paper at any radius -- 206 close in, 191 wide -- because the burst's rays
    run right up against the writing. Its FLOOR is the burst's white core, 227.

        the sky, demote          margin 200   floor 191
        page 048's burst, keep   margin 206   floor 227

    Both have to say "not paper" before the word is taken away.
    """
    # A bright core no bigger than the writing standing on it, and dark
    # artwork immediately outside - which is what a burst's rays leave.
    g = np.full((900, 900), 120, np.uint8)
    cv2.rectangle(g, (322, 342), (578, 458), 235, -1)
    _lines(g, 330, 350, n=2)
    box = (325, 345, 250, 110)
    assert CT._ring_paper(g, box) < CT.LOOSE_RING, \
        "the fixture is not the case this guards -- its margin reads as paper"
    assert CT._paper_under(g, box) >= CT.UNDER_PAPER


def test_writing_on_open_sky_fails_both(monkeypatch):
    g = np.full((900, 900), 205, np.uint8)
    _lines(g, 330, 350, n=2)
    box = (325, 345, 250, 110)
    assert CT._ring_paper(g, box) < CT.LOOSE_RING
    assert CT._paper_under(g, box) < CT.UNDER_PAPER


def test_the_floor_bar_sits_between_the_two_pages():
    """191 is the sky and 227 is the burst. Those are the numbers."""
    assert 191 < CT.UNDER_PAPER < 227


def test_the_ink_is_grown_before_the_floor_is_read():
    """The edge of a letter is a ramp from ink to paper, and there is a lot of
    edge in four close-set lines. Counted, the ramp drags the page under the
    bar and the box is called artwork -- so the ink is grown by a couple of
    pixels and the ramp goes with it.

    A page at 225: paper, and only just. That is the case where it matters.
    """
    g = np.full((400, 400), 225, np.uint8)
    for i in range(4):
        for j in range(7):
            cv2.rectangle(g, (110 + j * 22, 150 + i * 26),
                          (110 + j * 22 + 15, 150 + i * 26 + 21), 20, -1)
    g = cv2.GaussianBlur(g, (9, 9), 0)
    box = (105, 145, 7 * 22 + 8, 4 * 26 + 10)
    sub = g[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
    raw = float(np.median(sub[~(sub < CT.INK)]))
    assert raw < CT.UNDER_PAPER, \
        "the fixture has no ramp worth speaking of, so this tests nothing"
    assert CT._paper_under(g, box) >= CT.UNDER_PAPER


def test_a_box_with_nothing_in_it_reads_as_paper():
    """Nothing measured is not evidence of artwork, and the safe answer here is
    the one that keeps the box called dialogue."""
    g = np.full((300, 300), 120, np.uint8)
    assert CT._paper_under(g, (0, 0, 0, 0)) == 255.0


def test_a_burst_page_comes_back_as_dialogue_end_to_end(monkeypatch):
    """The floor, through the whole detector. Same shape as page 048: the block
    head calls it dialogue, no balloon is found under it, no wall, the margin
    is artwork -- and the writing is standing on something bright, so the word
    stays."""
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    page = np.full((INPUT, INPUT), 110, np.uint8)
    spec = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(3):
        cv2.rectangle(spec, (350 + i * 120, 420), (350 + i * 120 + 100, 520),
                      255, 4)
    ys, xs = np.nonzero(spec)
    cv2.rectangle(page, (int(xs.min()) - 5, int(ys.min()) - 5),
                  (int(xs.max()) + 5, int(ys.max()) + 5), 240, -1)
    page = np.where(spec > 0, 20, page).astype(np.uint8)
    img = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    blocks = [(int(xs.min()) - 6, int(ys.min()) - 6,
               int(xs.max()) + 6, int(ys.max()) + 6)]
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, spec))
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False)
    rs = CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)
    assert rs, "nothing came back"
    r = rs[0]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert CT._ring_paper(gray, r.bbox) < CT.LOOSE_RING, \
        "the margin does not demote this, so the floor is not what saves it"
    assert r.kind == "bubble", r.kind
