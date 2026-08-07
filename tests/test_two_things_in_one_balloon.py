"""Two things said inside one balloon, and which of them is spoken first.

lee sent back a hot-spring page. One balloon, two speeches: よく見てください up
the right, and ここの湯は白っぽく濁っているので神経痛に効果がありそうです beside it. What
came out was the long English typeset into the short line's column, in six-point
type, and the short English sitting in the space the long one should have had.

Two defects behind it, and both of them travel further than the typesetting.

FIRST, the order. `sections_in_one_balloon` sorted on the top edge and then the
right edge. That is right for two things stacked and a coin toss for two side by
side: vertical columns beside each other start within a pixel or two, and two
pixels decided which was spoken first. The order is not just a number on the
page - it is the order the reader is handed the boxes in and the order the
translator splits a linked sentence across.

SECOND, the link. `detect_comictext` links every box a single detected block
splits into, because a run of text broken up by the clusterer is still one run.
In a balloon holding two things said that is wrong, and it is not a small wrong
thing: the reader is told a link group is one sentence broken across the boxes
and that neither half may complete it, and the translator is told to split one
English sentence between them.

`sections_in_one_balloon` has said in its docstring since it was written that
sections are NOT linked. It now says it in code as well.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect.balloon import sections_in_one_balloon
from mangatl.models import TextRegion


H, W = 900, 1000


def _rim(img):
    """A black outline round every white shape, which is what makes it a
    balloon rather than a patch of paper."""
    cnts, _ = cv2.findContours((img >= 250).astype(np.uint8),
                               cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, 20, 3)
    return img


def _write(img, boxes):
    """Blocks of typesetting, and one mask per block.

    Characters and not solid slabs: real typesetting leaves the paper round it
    connected, and that connectedness is the whole signal - two clumps standing
    on one run of white paper are two clumps in one balloon.
    """
    out = []
    for x0, y0, x1, y1 in boxes:
        m = np.zeros((H, W), np.uint8)
        for x in range(x0, x1 - 12, 30):
            for y in range(y0, y1 - 12, 30):
                cv2.rectangle(m, (x, y), (x + 18, y + 18), 255, -1)
        m[img < 250] = 0
        img[m > 0] = 15
        out.append(m)
    return out


def _block(mask, rid=0, link=0):
    r = TextRegion(id=rid, kind="bubble", text_mask=mask,
                   bbox=tuple(int(v) for v in cv2.boundingRect(mask)))
    r.link = link
    return r


def two_columns(drop=0, link=0):
    """One balloon, two columns of writing side by side.

    `drop` moves the RIGHT column down the page relative to the left one, which
    is the thing that used to decide which was spoken first. lee's page had
    them level to within a pixel or two.
    """
    img = np.full((H, W), 246, np.uint8)
    cv2.ellipse(img, (500, 430), (250, 210), 0, 0, 360, 255, -1)
    _rim(img)
    masks = _write(img, [(580, 280 + drop, 690, 570 + drop),
                         (340, 280, 450, 570)])
    right, left = _block(masks[0], 1, link), _block(masks[1], 2, link)
    return img, right, left


def stacked():
    """One balloon, a sentence with a short line under it. The case the old
    sort got right and the new one must not lose."""
    img = np.full((H, W), 246, np.uint8)
    cv2.ellipse(img, (500, 430), (250, 210), 0, 0, 360, 255, -1)
    _rim(img)
    masks = _write(img, [(360, 290, 640, 390), (400, 490, 560, 560)])
    return img, _block(masks[0], 1), _block(masks[1], 2)


# ------------------------------------------------------------------ the order

@pytest.mark.parametrize("drop", [0, 3, 12])
def test_the_right_column_is_spoken_first_however_the_tops_line_up(drop):
    """The whole bug in one line: it must not matter whether the right column
    starts level with the left one, three pixels below it, or twelve."""
    img, right, left = two_columns(drop)
    assert sections_in_one_balloon(img, [right, left], rtl=True) == 1
    assert right.order == 0, (right.order, left.order)
    assert left.order == 1


@pytest.mark.parametrize("drop", [0, 3, 12])
def test_and_the_left_one_is_first_when_the_page_reads_the_other_way(drop):
    """Manhwa and manhua read left to right, and the same balloon has to come
    out the other way round. The direction is passed in rather than assumed:
    it is a fact about the chapter, not about the picture."""
    img, right, left = two_columns(drop)
    assert sections_in_one_balloon(img, [right, left], rtl=False) == 1
    assert left.order == 0, (left.order, right.order)
    assert right.order == 1


def test_two_stacked_are_still_read_top_to_bottom():
    """The case the old sort got right, which the new one must not lose. A
    sentence with a small line under it is not two columns."""
    img, top, low = stacked()
    assert sections_in_one_balloon(img, [low, top], rtl=True) == 1
    assert top.order == 0, (top.order, low.order)
    assert low.order == 1


def test_an_order_somebody_already_set_is_left_alone():
    """A number is only handed out to a box that has not got one. Renumbering
    a page somebody has dragged into shape is worse than never numbering it."""
    img, right, left = two_columns()
    right.order, left.order = 7, 4
    assert sections_in_one_balloon(img, [right, left], rtl=True) == 1
    assert (right.order, left.order) == (7, 4)


# ------------------------------------------------------------------- the link

def test_two_sections_of_one_balloon_are_not_one_sentence():
    """The detector links every box a block split into. This pass has just
    looked at the paper and decided they are two things said, so the link goes.

    It matters twice over. The reader is told a link group is one sentence
    broken across the boxes and that neither half may complete it. The
    translator is told to split one English sentence between them. Both are
    lies about a balloon holding a line and a separate remark.
    """
    img, right, left = two_columns(link=1)   # what the detector leaves behind
    assert sections_in_one_balloon(img, [right, left], rtl=True) == 1
    assert right.link == 0
    assert left.link == 0


def test_they_are_grouped_instead():
    """Not linked, but not unrelated either: one balloon, so one box drawn
    round the pair and one share of the paper each."""
    img, right, left = two_columns()
    assert sections_in_one_balloon(img, [right, left], rtl=True) == 1
    assert right.box_group and right.box_group == left.box_group
    for r in (right, left):
        assert r.bubble_mask is not None and (r.bubble_mask > 0).any()
    # ...and the shares do not overlap, or the two English blocks would be
    # typeset on top of each other.
    both = (right.bubble_mask > 0) & (left.bubble_mask > 0)
    assert not both.any(), int(both.sum())


def test_each_section_keeps_the_side_its_own_writing_is_on():
    """The symptom lee could see: the long English in the short line's column.
    Each share has to contain that section's OWN ink and not the other's."""
    img, right, left = two_columns()
    assert sections_in_one_balloon(img, [right, left], rtl=True) == 1
    for r, other in ((right, left), (left, right)):
        mine = (r.bubble_mask > 0) & (r.text_mask > 0)
        theirs = (r.bubble_mask > 0) & (other.text_mask > 0)
        assert mine.sum() > 0
        assert theirs.sum() == 0, (int(mine.sum()), int(theirs.sum()))


def test_a_link_across_two_real_balloons_is_left_alone():
    """A sentence really split between two balloons is what a link is FOR, and
    nothing here may touch it. Two enclosures, so this pass does not fire at
    all and the link survives it."""
    img = np.full((H, W), 246, np.uint8)
    cv2.ellipse(img, (300, 400), (140, 180), 0, 0, 360, 255, -1)
    cv2.ellipse(img, (700, 620), (110, 110), 0, 0, 360, 255, -1)
    _rim(img)
    masks = _write(img, [(230, 300, 370, 500), (640, 560, 760, 680)])
    out = [_block(masks[0], 1, link=3), _block(masks[1], 2, link=3)]
    assert sections_in_one_balloon(img, out, rtl=True) == 0
    assert [r.link for r in out] == [3, 3]


@pytest.mark.parametrize("handed", ["right first", "left first"])
def test_the_answer_does_not_depend_on_the_order_they_arrived_in(handed):
    """The detector hands its boxes over in whatever order it found them, and
    that is not a fact about the balloon.

    This is the test that catches the shares being dealt out by READING
    position instead of to the block they belong to. With the blocks arriving
    right-first the two orders agree and the mistake is invisible; arriving
    left-first they disagree, and each block gets the other one's half of the
    paper. That is exactly the symptom: the long English in the short line's
    column.
    """
    img, right, left = two_columns()
    members = [right, left] if handed == "right first" else [left, right]
    assert sections_in_one_balloon(img, members, rtl=True) == 1

    assert right.order == 0 and left.order == 1
    for r, other in ((right, left), (left, right)):
        mine = (r.bubble_mask > 0) & (r.text_mask > 0)
        theirs = (r.bubble_mask > 0) & (other.text_mask > 0)
        assert mine.sum() > 0, handed
        assert theirs.sum() == 0, (handed, int(theirs.sum()))


# ---------------------------------------------------- one sentence, or two?
#
# The question the detector used to guess at, moved to where it can be
# answered. lee, on the page it went wrong on: *"sometimes teh rader is
# reading the letter and tributting them to the wrong box these boxes used to
# be linked 1 and 2"*.

def test_the_detector_no_longer_guesses_at_it():
    """The pixels cannot tell one sentence broken in two from two things said,
    and this is where it used to try."""
    from where import PKG
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    body = src.split("def detect_comictext", 1)[1]
    for line in body.split("\n"):
        code = line.split("#")[0]
        assert ".link = " not in code and "link_seq" not in code, line


@pytest.mark.parametrize("first,second,want", [
    # lee's two balloons. Neither runs on, and both were linked.
    ("こっちの部屋は自由に使ってください", "内湯が付いてるんで", False),
    ("よく見てください", "ここの湯は白っぽく濁っているので", False),
    # ...and his split sentence, which does, and says so in the ink.
    ("がんばった甲斐が あったってもんだ——", "——だから気をつけてね！", True),
    ("そのとき彼は…", "…振り返った", True),
    ("だから〜", "いいんだよ", True),
    # A full stop settles it whatever comes next.
    ("もういい。", "——帰れ", False),
    # A mark on the SECOND block alone is evidence too: a typesetter writes the
    # dash at whichever end of the break reads better.
    ("そのとき", "——彼は振り返った", True),
    # Brackets sit outside the mark and must not hide it. Closing quote after
    # the dash on the first, and nothing at all on the second.
    ("「そう言った", "わけだ」", False),
    ("「そんな——」", "馬鹿な", True),
    ("（まさか——", "——本当に？）", True),
    # Nothing to join.
    ("", "何か", False),
    ("何か", "", False),
])
def test_only_the_authors_own_typography_says_a_line_runs_on(first, second, want):
    """Deliberately narrow.

    Manga drops the full stop constantly, so "no ending punctuation" would link
    half the balloons in a chapter. A link invented where there is none is much
    worse than one missed: it makes the translator write one sentence across two
    separate speeches, and it is what told the reader it could hand the wrong
    line to the wrong box. A missed one costs a press of L.
    """
    from mangatl.translate import reads_on
    assert reads_on(first, second) is want


class _Box:
    def __init__(self, rid, group, text, order, link=0):
        self.id, self.box_group, self.src_text = rid, group, text
        self.order, self.link = order, link


def test_two_speeches_in_one_balloon_come_out_unlinked():
    from mangatl.translate import link_sections
    boxes = [_Box(1, 4, "こっちの部屋は自由に使ってください", 0, link=9),
             _Box(2, 4, "内湯が付いてるんで", 1, link=9)]
    assert link_sections(boxes) == 0
    assert [b.link for b in boxes] == [0, 0]


def test_a_sentence_carried_across_the_break_is_linked():
    from mangatl.translate import link_sections
    boxes = [_Box(1, 4, "あったってもんだ——", 0),
             _Box(2, 4, "——だから気をつけてね！", 1)]
    assert link_sections(boxes) == 1
    assert boxes[0].link == boxes[1].link != 0


def test_it_is_asked_in_reading_order_and_not_in_id_order():
    """The boxes are numbered by the page, not by the detector's arrival order,
    and a dash trailing the SECOND-numbered box is not a carried sentence."""
    from mangatl.translate import link_sections
    boxes = [_Box(1, 4, "——だから気をつけてね！", 1),
             _Box(2, 4, "あったってもんだ——", 0)]
    assert link_sections(boxes) == 1
    boxes[1].src_text, boxes[0].src_text = boxes[0].src_text, boxes[1].src_text
    assert link_sections(boxes) == 0


def test_a_re_read_can_change_its_mind():
    """A box corrected from a fragment into a whole sentence stops being half
    of one. The link is derived from the words every time they are read, not
    written once and kept."""
    from mangatl.translate import link_sections
    # Joined by the trailing dash on the first alone, so taking it off is the
    # whole of the correction.
    boxes = [_Box(1, 4, "あったってもんだ——", 0), _Box(2, 4, "だから！", 1)]
    assert link_sections(boxes) == 1
    boxes[0].src_text = "あったってもんだ"
    assert link_sections(boxes) == 0
    assert [b.link for b in boxes] == [0, 0]


def test_a_link_outside_a_balloon_group_is_never_touched():
    """A sentence running across two separate balloons is what a link is for,
    and somebody may have set it by hand. Only sections of ONE balloon are
    ever decided here."""
    from mangatl.translate import link_sections
    boxes = [_Box(1, 0, "あったってもんだ", 0, link=6),
             _Box(2, 0, "だから気をつけてね！", 1, link=6)]
    assert link_sections(boxes) == 0
    assert [b.link for b in boxes] == [6, 6]


def test_reading_a_page_asks_the_question():
    """It has to run inside the read, not be a thing somebody remembers to
    call. This is the line that makes the detector's silence safe."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor.do_ocr)
    assert "link_sections(" in src
