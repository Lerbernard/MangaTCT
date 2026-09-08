"""Two things the last translated chapter did that the page cannot hold.

**The lines were long.** Median English came back at 2.5x the Korean by
character count, and page 006 at 2.6x: 110 characters of English in a bubble
that held 42 of Korean. The answer at the time was a budget - `src_char_count`
with a rule to aim under 1.6 times it, and later `fits_chars` off the balloon
itself.

**Both budgets are gone**, and this file keeps the record of why they went.
lee: *"i wan the most accurate transaltion no matter the leght of the of it so
i dont want to shrink or expand teh translation to fit anythng"*. Six-point
type is a price he will pay; a line that has had a qualifier cut out of it to
fit is not. What replaced the budget is one rule saying length is not the
model's problem, and one note - `too_long`, taken at the project's FLOOR - for
the only case the typesetter cannot solve by setting smaller.

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


def test_the_prompt_gives_the_line_no_budget_at_all():
    sys = _flat()
    assert "src_char_count" not in sys
    assert "1.6 times" not in sys
    assert "LENGTH IS NOT A CONSTRAINT ON YOU" in sys


def test_and_the_example_of_cutting_one_went_with_the_rule():
    """"Nearly 90% of Arsilan is already gone." was there to show what cutting
    a line looks like. Showing it now would teach the behaviour the rule above
    forbids - an example outlives the sentence around it."""
    assert "Nearly 90% of Arsilan is already gone." not in _flat()


def test_the_region_carries_no_count_either():
    """The rule went and the number went with it. A budget in the payload with
    nothing said about it is still a budget."""
    from mangatl.models import Page, TextRegion
    r = TextRegion(id=0, bbox=(0, 0, 40, 40), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, 40, 40), kind="bubble")
    r.src_text, r.order = "이미 아르실란 영토의", 0
    p = Page(image=None, source_path="t.png")
    p.regions = [r]
    got = T.build_payload(p, T.SeriesContext())["regions"][0]
    assert "src_char_count" not in got and "fits_chars" not in got
    assert got["text"] == r.src_text, "the words themselves still travel"


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
    """One ー is the ordinary long-vowel mark and turns up in normal words -
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
