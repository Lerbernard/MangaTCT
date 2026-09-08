"""The third translated chapter, and two regressions of my own making.

The shout came back - 13 runs of marks in the source, 13 in the English, none
dropped, where the run before had lost four. The splice stayed fixed. The
speaker labels came down to six, and the eight lines with no speaker are the
eight captions and status windows, which is the right answer.

Two lines came back wrong, and both were the interior-dash rule:

**Page 002 lost a title plate.** `- 대마법사 김진우 -` is a caption framed with
two hyphens. `_SRC_DASHES` had no hyphen-minus in it, so the page counted as
having no dash, the model's "Arsilan - Archmage Kim Jinwoo" was read as an
invented dash, and the comma it became says Arsilan IS the archmage.

**Page 039 came back starting with a comma.** The model wrote
"...-The existence known as Kim Jinwoo has probably ceased to exist."
`strip_added_dashes` saw a dash with three periods in front of it, called it an
interior dash and made it a comma; then `strip_added_ellipsis`, which runs
straight after, took the periods away and left the comma standing at the front
of the line.

**And the lines did not shorten** - 2.35x to 2.33x, the same 50 of 134 over
2.5x. Measured on the chapter afterwards: `fits_chars` said the median balloon
held 634 characters, the median line was 43, and the note fired zero times.
The budget was taken at `min_font`, the floor below which a human is flagged,
and the typesetter never goes there: on those 71 pages it set a median of 32px
against a floor of 11, and 18px was the smallest thing in the chapter. So the
model was told a balloon holds what could be crammed into it at a size nobody
would print.
"""

import re

import pytest

from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _r(w=300, h=160, i=0):
    r = TextRegion(id=i, bbox=(0, 0, w, h), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, w, h), kind="bubble")
    r.src_text, r.order = "테스트", 0
    return r


def _page(regions):
    p = Page(image=None, source_path="t.png")
    p.regions = list(regions)
    return p


def _clean(dst, src):
    """Both cleaners, in the order the translator runs them."""
    return T.strip_added_ellipsis(T.strip_added_dashes(dst, src), src)


# --- the title plate ---------------------------------------------------------

def test_a_page_that_types_its_dashes_on_an_ascii_keyboard_still_has_dashes():
    assert T.source_has_dash("- 대마법사 김진우 -")


def test_and_so_the_plate_keeps_its_frame():
    """Page 002. The comma made Arsilan and the archmage one person."""
    got = _clean("An Earthling summoned to another world, "
                 "Arsilan — Archmage Kim Jinwoo",
                 "이세계,\n아르실란으로 소환된 지구인\n- 대마법사 김진우 -")
    assert "—" in got


@pytest.mark.parametrize("src", [
    "- 대마법사 김진우 -",
    "- 영혼의 고향과 연결된 문",       # the bulleted status window on page 029
    "그래 - 그렇지",
])
def test_a_hyphen_standing_on_its_own_counts(src):
    assert T.source_has_dash(src)


@pytest.mark.parametrize("src", [
    "T-셔츠",
    "하이-엘프 터리스",
    "SSR-5성",
    "네 <-\n아니오",      # page 069's menu cursor. An arrow, not a dash.
    "그래.",
    "",
])
def test_a_hyphen_inside_a_word_does_not(src):
    assert not T.source_has_dash(src)


def test_a_hyphen_the_line_ends_on_counts():
    """The closing half of a title plate, where the text simply stops."""
    assert T.source_has_dash("대마법사 김진우 -")


def test_one_long_vowel_mark_is_still_not_a_dash():
    """The rule this sits next to, and the reason it is written as it is."""
    assert not T.source_has_dash("ハート")
    assert T.source_has_dash("やめてーー")


# --- the comma left standing -------------------------------------------------

def test_a_dash_behind_an_opening_ellipsis_is_an_edge_dash():
    """Page 039. It is at the edge of the line the READER gets."""
    got = _clean("...—The existence known as Kim Jinwoo has probably "
                 "ceased to exist.",
                 "아마 김진우라는 존재는\n소멸했겠지.")
    assert got == ("The existence known as Kim Jinwoo has probably "
                   "ceased to exist.")


def test_no_line_comes_back_opening_with_a_comma():
    for dst in ("...—Well then", "…—Well then", '"...—Well then',
                "——Well then", "—Well then"):
        assert not _clean(dst, "그럼").lstrip().startswith(",")


def test_the_same_at_the_other_end():
    got = _clean("Well then—...", "그럼")
    assert not got.rstrip().endswith(",")
    assert "," not in got


def test_an_ellipsis_the_source_asked_for_survives_the_dash_coming_off():
    """The source opens by trailing off, so the ellipsis stays and the dash goes."""
    got = _clean("...—Well then", "…그럼")
    assert got.startswith("...")
    assert "—" not in got


def test_a_dash_in_the_middle_is_still_a_comma():
    """The rule the run before this one was shipped for. It still holds."""
    assert T.strip_added_dashes(
        "Legend of the Dragon 7—a game that met my standards",
        "전생에 아주 깐깐한 게임 디렉터인") == \
        "Legend of the Dragon 7, a game that met my standards"


def test_and_a_source_with_a_real_dash_still_exempts_the_whole_line():
    assert T.strip_added_dashes("WAIT—WHAT DID YOU SAY?", "まって—何て言った") == \
        "WAIT—WHAT DID YOU SAY?"


# --- and then lee took the length budget away ---------------------------------
#
# Everything from here down used to be about `comfort_size`, a fraction of the
# project's full type size that the model was given as a budget and told to cut
# words to stay inside. lee: *"i wan the most accurate transaltion no matter
# the leght of the of it so i dont want to shrink or expand teh translation to
# fit anythng"*. The budget is gone, the function is gone, and what is left is
# the one question a floor can answer: does this line go in AT ALL.

def test_no_length_budget_reaches_the_model():
    """Both numbers, gone from the region. Removing the RULE and leaving the
    NUMBERS would have been the worse half of the job: a budget in the payload
    with nothing said about it is still a budget."""
    c = T.SeriesContext()
    c.min_font, c.max_font = 11, 40
    got = T.build_payload(_page([_r()]), c)["regions"][0]
    assert "fits_chars" not in got
    assert "src_char_count" not in got


def test_the_comfortable_size_is_gone_with_it():
    assert not hasattr(T, "comfort_size")
    assert not hasattr(T, "COMFORT_FONT")


def test_the_prompt_tells_the_model_length_is_not_its_problem():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "LENGTH IS NOT A CONSTRAINT ON YOU" in sys
    flat = re.sub(r"\s+", " ", sys)
    assert "Never cut a word, a qualifier or a nuance to make a line shorter" \
        in flat
    assert "never pad one out to fill a balloon" in flat
    assert "the type is set smaller" in flat


def test_and_still_asks_for_natural_english():
    """The one length-ish thing that survives, and it is not about space: the
    shortest wording that carries the WHOLE meaning is how people talk."""
    flat = re.sub(r"\s+", " ", T.build_system("manhwa", "en", "Korean"))
    assert "Being NATURAL is still a constraint" in flat
    assert "Do not translate long" in flat


def test_the_old_budget_is_nowhere_in_the_prompt():
    sys = T.build_system("manhwa", "en", "Korean")
    for gone in ("fits_chars", "src_char_count", "comfortable reading size",
                 "OVERRULES the ratio", "1.6 times"):
        assert gone not in sys, gone


def test_no_target_language_is_told_to_keep_its_lines_tight():
    """Spanish, Portuguese and French each carried "runs 20% longer than
    English, so keep lines tight". That is the same instruction in a
    per-language coat."""
    for tgt in ("es", "pt", "fr", "en"):
        sys = T.build_system("manhwa", tgt, "Korean")
        assert "keep lines tight" not in sys, tgt
        assert "disciplined about length" not in sys, tgt


# --- the note that is left -----------------------------------------------------

def test_the_character_area_is_the_measured_one():
    """1.05, off `typeset._best` against the real masks - not the reasoned 0.6.

    `fits_chars` outlived the budget: it is what the remaining note measures
    with, at the floor.
    """
    assert 0.9 <= T.CHAR_AREA <= 1.2


def test_a_line_that_will_not_go_in_at_the_floor_is_flagged():
    """The one thing the typesetter cannot solve by setting smaller type."""
    r = _r(w=90, h=60)
    room = T.fits_chars(r, 11)
    assert room, "the fixture measures nothing, so it proves nothing"
    assert "holds ~" in T.too_long("x" * (room * 3), r, 11)


def test_a_line_that_merely_comes_out_small_says_nothing():
    """Page 067's 133 characters in a 300x300 balloon: the typesetter drops to
    21px and sets it, and that is now the right answer rather than a fault.
    Under the old comfortable budget this was a flag."""
    r = _r(w=300, h=300)
    assert T.too_long("x" * 133, r, 11) == ""


def test_the_note_is_taken_at_the_projects_own_floor():
    """Not at a number invented here - a project set in big type has the same
    floor question as one set in small."""
    r = _r(w=200, h=200)
    assert T.fits_chars(r, 11) > T.fits_chars(r, 30)
    assert T.too_long("x" * 400, r, 30) and not T.too_long("x" * 400, r, 8)


# --- and it has to reach the request -----------------------------------------

def test_the_context_still_carries_the_floor():
    c = T.SeriesContext()
    assert hasattr(c, "min_font")


def test_the_run_takes_the_note_at_the_floor():
    """Both places a translated line is checked, and neither of them budgets
    against anything else any more."""
    from where import PKG
    src = (PKG / "translate.py").read_text(encoding="utf-8")
    calls = [ln for ln in src.splitlines() if "too_long(r.dst_text" in ln]
    assert len(calls) == 2, calls
    body = "\n".join(src.splitlines())
    assert body.count('too_long(r.dst_text, r,') == 2
    # and the only mentions left of the old budget are the notes saying it went
    live = [ln for ln in src.splitlines()
            if "comfort_size" in ln and not ln.lstrip().startswith("#")
            and "`comfort_size`" not in ln]
    assert not live, live
