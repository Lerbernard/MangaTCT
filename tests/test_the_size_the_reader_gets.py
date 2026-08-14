"""The third translated chapter, and two regressions of my own making.

The shout came back — 13 runs of marks in the source, 13 in the English, none
dropped, where the run before had lost four. The splice stayed fixed. The
speaker labels came down to six, and the eight lines with no speaker are the
eight captions and status windows, which is the right answer.

Two lines came back wrong, and both were the interior-dash rule:

**Page 002 lost a title plate.** `- 대마법사 김진우 -` is a caption framed with
two hyphens. `_SRC_DASHES` had no hyphen-minus in it, so the page counted as
having no dash, the model's "Arsilan — Archmage Kim Jinwoo" was read as an
invented dash, and the comma it became says Arsilan IS the archmage.

**Page 039 came back starting with a comma.** The model wrote
"...—The existence known as Kim Jinwoo has probably ceased to exist."
`strip_added_dashes` saw a dash with three periods in front of it, called it an
interior dash and made it a comma; then `strip_added_ellipsis`, which runs
straight after, took the periods away and left the comma standing at the front
of the line.

**And the lines did not shorten** — 2.35x to 2.33x, the same 50 of 134 over
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


# --- the size the reader gets ------------------------------------------------

def test_the_budget_is_not_taken_at_the_floor():
    """min_font is where a human gets flagged, not where the type is set."""
    assert T.comfort_size(11, 40) > 11


def test_it_is_taken_at_a_fraction_of_the_full_size():
    assert T.comfort_size(11, 40) == round(40 * T.COMFORT_FONT)


def test_the_fraction_is_where_the_flags_matched_the_pages():
    """0.75 called out balloons that came out at 34px; 0.6 missed real ones."""
    assert 0.65 <= T.COMFORT_FONT <= 0.72


def test_it_never_goes_below_the_floor():
    assert T.comfort_size(30, 10) == 30
    assert T.comfort_size(20, 20) == 20


def test_a_project_with_no_full_size_setting_is_budgeted_at_its_floor():
    """Not at a number invented here. The floor is the only size it has said."""
    assert T.comfort_size(20, 0) == 20
    assert T.comfort_size(20, None) == 20


def test_a_bigger_full_size_leaves_room_for_fewer_characters():
    r = _r()
    assert T.fits_chars(r, T.comfort_size(11, 40)) < \
        T.fits_chars(r, T.comfort_size(11, 20))


def test_the_character_area_is_the_measured_one():
    """1.05, off `typeset._best` against the real masks — not the reasoned 0.6.

    The reasoning left out the space between words, the ragged right of a
    wrapped line, and a balloon being a round hole.
    """
    assert 0.9 <= T.CHAR_AREA <= 1.2


def test_the_median_balloon_no_longer_holds_a_paragraph():
    """690px webtoon bubble, 11/40. It used to say 634; the lines were 43."""
    r = _r(w=340, h=340)
    assert T.fits_chars(r, T.comfort_size(11, 40)) < 120


def test_a_line_the_typesetter_would_have_to_squeeze_is_flagged():
    """Page 067, 133 characters in a balloon the typesetter dropped to 21px."""
    r = _r(w=300, h=300)
    assert "holds ~" in T.too_long("x" * 133, r, T.comfort_size(11, 40))


def test_and_an_ordinary_line_in_the_same_balloon_is_not():
    r = _r(w=300, h=300)
    assert T.too_long("x" * 43, r, T.comfort_size(11, 40)) == ""


# --- and it has to reach the request -----------------------------------------

def test_the_context_carries_both_ends():
    c = T.SeriesContext()
    assert hasattr(c, "min_font") and hasattr(c, "max_font")


def test_the_settings_carry_the_full_size_too():
    import inspect

    from mangatl import editor
    src = inspect.getsource(editor._ctx_from_settings)
    assert 'p.ctx.max_font = int(s.get("max_font") or 34)' in src


def test_the_request_budgets_at_the_comfortable_size():
    c = T.SeriesContext()
    c.min_font, c.max_font = 11, 40
    got = T.build_payload(_page([_r()]), c)["regions"][0]
    assert got["fits_chars"] == T.fits_chars(_r(), T.comfort_size(11, 40))


def test_a_project_set_in_bigger_type_gets_a_smaller_budget():
    small, big = T.SeriesContext(), T.SeriesContext()
    small.min_font, small.max_font = 11, 20
    big.min_font, big.max_font = 11, 40
    a = T.build_payload(_page([_r()]), small)["regions"][0]["fits_chars"]
    b = T.build_payload(_page([_r()]), big)["regions"][0]["fits_chars"]
    assert b < a


def test_the_prompt_says_which_size_it_measured_at():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "fits_chars" in sys
    assert "comfortable reading size" in sys
    assert "smallest type this project allows" not in sys


def test_the_prompt_says_the_balloon_beats_the_ratio():
    """A ratio is a fact about languages; this one is about the balloon."""
    sys = re.sub(r"\s+", " ", T.build_system("manhwa", "en", "Korean"))
    assert "OVERRULES the ratio" in sys
