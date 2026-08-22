"""A double balloon is one balloon, not one sentence.

The chapter came back with page 049 reading::

    "His soul is completely gone," / "and in just a few hours, he'll stop
    breathing altogether."

Two complete Korean sentences - `영혼이 존재하지 않아.` and `몇 시간 뒤면 완전히
숨이 멈출 거다.` - welded together with a comma. Page 029 did the same and
invented an "And" to bridge it.

**Two different facts were sharing one field.** `reads_on` links regions whose
WORDS run on, which is the case the translation prompt is written for: each
half is only correct as part of the whole. `link_touching_bubbles` links two
lobes of one drawn balloon, which is a fact about the PICTURE - and an artist
draws two statements in one balloon as readily as one sentence. Both wrote
`link`, and the prompt reads `link` as "ONE continuous sentence broken across
several bubbles".

So `link_kind` says which, the payload sends them under different names, and
the prompt has a paragraph for each. The boxes are still linked on screen and
still travel together; what changed is what the translator is told they mean.
"""
import pytest

from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _region(rid, text, link=0, kind="", order=None, group=0):
    r = TextRegion(id=rid, bbox=(0, rid * 50, 40, 40), text_mask=None,
                   bubble_mask=None, bubble_bbox=(0, rid * 50, 40, 40),
                   kind="bubble")
    r.src_text = text
    r.link = link
    r.link_kind = kind
    r.box_group = group
    r.order = rid if order is None else order
    return r


def _page(regions):
    p = Page(image=None, source_path="t.png")
    p.regions = regions
    return p


def _ctx():
    c = T.SeriesContext()
    c.medium, c.source, c.target = "manhwa", "Korean", "en"
    return c


def _regions_of(payload):
    return {r["id"]: r for r in payload["regions"]}


# ------------------------------------------------------- what the model sees

def test_a_carried_sentence_still_goes_as_a_link():
    p = _page([_region(0, "하지만 이건", 4, "sentence"),
               _region(1, "수준이 아니라…", 4, "sentence")])
    got = _regions_of(T.build_payload(p, _ctx()))
    assert got[0]["link"] == 4 and got[1]["link"] == 4
    assert "balloon" not in got[0]


def test_two_lobes_of_one_balloon_go_as_a_balloon():
    p = _page([_region(0, "영혼이 존재하지 않아.", 7, "balloon"),
               _region(1, "몇 시간 뒤면 완전히 숨이 멈출 거다.", 7, "balloon")])
    got = _regions_of(T.build_payload(p, _ctx()))
    assert got[0]["balloon"] == 7 and got[1]["balloon"] == 7
    assert "link" not in got[0], \
        "the prompt reads `link` as one sentence, and these are two"


def test_a_link_from_before_this_existed_is_still_a_link():
    """Projects on disk have `link` and no `link_kind`. Those links came from
    `reads_on`, which is the only thing that set one until the lobe detector
    arrived, so the old meaning is the safe reading."""
    p = _page([_region(0, "가", 2), _region(1, "나", 2)])
    got = _regions_of(T.build_payload(p, _ctx()))
    assert got[0]["link"] == 2 and "balloon" not in got[0]


def test_an_unlinked_region_carries_neither():
    got = _regions_of(T.build_payload(_page([_region(0, "응?")]), _ctx()))
    assert "link" not in got[0] and "balloon" not in got[0]


# ----------------------------------------------------------- what it is told

def test_the_prompt_says_what_a_balloon_number_is_not():
    sys = T.build_system("manhwa", "en", "Korean")
    assert '"balloon" number is a DIFFERENT thing' in sys
    assert "two lobes of one balloon" in sys
    assert "Do not weld two complete\n  sentences together with a comma" in sys
    assert 'do not open the second one with "and"' in sys


def test_and_still_says_what_a_link_is():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "ONE continuous sentence broken across several bubbles" in sys


def test_the_reader_is_not_told_they_are_one_sentence_either():
    """`_ocr_context` said "ONE sentence" about the same groups. For the reader
    it barely mattered - the instruction it hangs off is "do not complete a
    word across the split" - but a sentence it is not."""
    p = _page([_region(0, "가", 3, "balloon"), _region(1, "나", 3, "balloon")])
    note = T._ocr_context(p, _ctx())
    assert "two lobes of one drawn balloon" in note
    assert "ONE sentence split across several boxes" not in note


# --------------------------------------------- who sets which, end to end

def test_reads_on_sets_the_sentence_kind():
    a = _region(0, "하지만 이건…", group=1)
    b = _region(1, "사실상 사망 상태잖아…?", group=1)
    assert T.link_sections([a, b]) == 1
    assert a.link and a.link == b.link
    assert a.link_kind == b.link_kind == "sentence"


def test_and_clears_the_kind_when_it_unlinks_them():
    a = _region(0, "안녕하세요.", 5, "sentence", group=1)
    b = _region(1, "반갑습니다.", 5, "sentence", group=1)
    T.link_sections([a, b])
    assert not a.link and a.link_kind == "", (a.link, a.link_kind)


def test_the_lobe_detector_sets_the_balloon_kind():
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl.detect import balloon as B
    g = np.full((600, 900), 40, np.uint8)
    rs = []
    for i, x in enumerate((250, 454)):
        m = np.zeros(g.shape, np.uint8)
        cv2.circle(m, (x, 300), 100, 1, -1)
        g[m > 0] = 255
        r = TextRegion(id=i, bbox=(x - 60, 280, 120, 40), text_mask=None,
                       bubble_mask=(m > 0).astype(np.uint8) * 255,
                       bubble_bbox=(x - 60, 280, 120, 40), kind="bubble")
        r.order = i
        rs.append(r)
    assert B.link_touching_bubbles(g, rs) == 1
    assert rs[0].link and rs[0].link == rs[1].link
    assert rs[0].link_kind == rs[1].link_kind == "balloon"


# ------------------------------------------------------ ...and it is written

def test_the_kind_survives_a_save():
    """A project is read back off disk between the find and the translate, so
    a field that is not written is a field that is always empty by the time it
    matters."""
    import inspect

    from mangatl import project
    src = inspect.getsource(project)
    assert '"link_kind": str(getattr(r, "link_kind", "") or ""),' in src
    assert 'link_kind=str(rec.get("link_kind", "") or ""),' in src
