"""Two things the last translated chapter did that the page cannot hold.

**The lines were long.** Median English came back at 2.5x the Korean by
character count, and page 006 at 2.6x: 110 characters of English in a bubble
that held 42 of Korean. That is not a wrong translation, it is six-point type
— the fitter has to put it somewhere. The request already carried
`src_char_count` per region and nothing told the model what to do with it.

**Two em dashes** that the prompt forbids in as many words, both from Korean
with no dash in it anywhere: "Legend of the Dragon 7—a game that earned the
approval of..." and "a standard premise—become the hero". `strip_added_dashes`
took them off the EDGES of a line and deliberately left one in the middle,
on the grounds that a dash in the middle is doing a job. Over a chapter the
job it was doing was the model's own voice.
"""
import re

from mangatl import translate as T


def _flat(medium="manhwa"):
    """The prompt with its line wrapping taken out.

    These used to match the wrapped text and went red the first time a rule
    was reworded and rewrapped around it, which is how a suite stops being
    read. What the test is about is the words, not where the lines break.
    """
    return re.sub(r"\s+", " ", T.build_system(medium, "en", "Korean"))


def test_the_prompt_gives_the_line_a_budget():
    sys = _flat()
    assert "src_char_count" in sys
    assert "1.6 times" in sys


def test_and_shows_what_cutting_one_looks_like():
    """A rule with no example is a rule that gets read as a preference."""
    assert "Nearly 90% of Arsilan is already gone." in _flat()


def test_the_region_still_carries_its_own_count():
    from mangatl.models import Page, TextRegion
    r = TextRegion(id=0, bbox=(0, 0, 40, 40), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, 40, 40), kind="bubble")
    r.src_text, r.order = "이미 아르실란 영토의", 0
    p = Page(image=None, source_path="t.png")
    p.regions = [r]
    got = T.build_payload(p, T.SeriesContext())["regions"][0]
    assert got["src_char_count"] == len(r.src_text)


# ------------------------------------------------------------- the dashes

def test_a_dash_in_the_middle_of_a_line_comes_off():
    got = T.strip_added_dashes("Legend of the Dragon 7—a game I liked.",
                               "드래건의 전설7.")
    assert got == "Legend of the Dragon 7, a game I liked."


def test_and_so_does_an_en_dash():
    assert T.strip_added_dashes("a premise – become the hero", "흔한 설정이지만") \
        == "a premise, become the hero"


def test_it_does_not_leave_a_double_comma_behind():
    assert T.strip_added_dashes("wait, — no", "기다려") == "wait, no"


def test_a_line_whose_source_has_a_dash_keeps_all_of_them():
    """The exemption is the whole line and not the dash: if the page reached
    for a dash once, a dash in that line may well be the page's own."""
    got = T.strip_added_dashes("Master of the Tower—the Immortal Archmage—",
                               "마탑의 주인이시자 불멸의 대마법사이자—")
    assert got == "Master of the Tower—the Immortal Archmage—"


def test_a_lone_long_vowel_mark_is_not_the_page_reaching_for_a_dash():
    """One ー is the ordinary long-vowel mark and turns up in normal words —
    see `source_has_dash`. It must not buy the line an exemption."""
    assert T.strip_added_dashes("the Archmage—and Lord of Rainsword",
                                "불멸의 대마법사이자ー") \
        == "the Archmage, and Lord of Rainsword"


def test_the_edges_still_come_off_too():
    assert T.strip_added_dashes("—Immortal Archmage—", "불멸의 대마법사") \
        == "Immortal Archmage"


def test_a_hyphen_inside_a_word_is_not_a_dash():
    assert T.strip_added_dashes("a well-known face", "유명한 얼굴") \
        == "a well-known face"


def test_a_line_that_is_nothing_but_a_dash_is_left_as_it_was():
    """Stripping it to nothing would delete the line, and an empty bubble is
    worse than a stray mark in it."""
    assert T.strip_added_dashes("—", "…") == "—"
