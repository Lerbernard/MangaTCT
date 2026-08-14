"""Three things the second translated chapter still got wrong.

The first pass fixed the em dashes (2 to 0), the glossary drift (`침식` 16 of 16
one way, `마정석` 2 of 2) and the grandfather (four labels down to one, on
eleven lines). Three things did not move, or moved the wrong way:

**Turiss became "Assistant".** Named on page 11, a role label on pages 16 to
19 — four pages into the same conversation. The grandfather was fixed and the
disciple broke instead, so `already_said` listing the name was not enough on
its own: it had to say that a name BEATS a role label.

**The lines were still long.** 2.48x the source down to 2.35x, with 50 of 134
still over 2.5x. The budget was a ratio, and a ratio is a fact about languages
rather than about this balloon. `fits_chars` is a fact about the balloon.

**And it started swallowing the shouting.** Four runs of `!!!` came back as one
`!` — `이건 기적이야!!!` as "This is a miracle!". New that run, and the same run
the prompt started asking for shorter lines: asked to cut, it cut the one thing
on the page that is not words.
"""
import re

import pytest

from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _r(rid=0, src="응?", dst=None, w=200, h=120):
    r = TextRegion(id=rid, bbox=(0, 0, w, h), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, w, h), kind="bubble")
    r.src_text, r.dst_text, r.order = src, dst, rid
    return r


def _page(rs):
    p = Page(image=None, source_path="t.png")
    p.regions = rs
    return p


# --------------------------------------------- a name beats a role label

def test_the_prompt_says_a_named_person_keeps_the_name():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "A person the chapter has NAMED keeps the name" in sys
    assert "Never coin a role" in sys
    assert "Turiss" in sys and "Assistant" in sys, \
        "the case is named, because a rule with no case reads as a preference"


def test_and_still_says_to_label_an_unnamed_one_by_what_they_are():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "A role label\n    is for somebody the story has not named at all" \
        in sys


# ------------------------------------------- what the balloon actually holds

def test_a_balloon_says_how_much_it_holds():
    assert T.fits_chars(_r(w=300, h=160), 12) > 100


def test_a_smaller_balloon_holds_less():
    big, small = T.fits_chars(_r(w=300, h=160)), T.fits_chars(_r(w=150, h=80))
    assert small < big / 3, (small, big)


def test_and_bigger_type_means_fewer_characters():
    r = _r(w=300, h=160)
    assert T.fits_chars(r, 24) < T.fits_chars(r, 12) / 3


def test_the_mask_is_used_where_there_is_one():
    """A round balloon is not its bounding box — about three quarters of it —
    and the box would promise room that is not there."""
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 90, 255, -1)
    r = _r(w=200, h=200)
    r.bubble_mask = m
    assert T.fits_chars(r) < T.fits_chars(_r(w=200, h=200))


def test_a_region_with_nothing_to_measure_promises_nothing():
    r = TextRegion(id=0, bbox=(0, 0, 0, 0), text_mask=None, bubble_mask=None,
                   bubble_bbox=None, kind="bubble")
    assert T.fits_chars(r) == 0


def test_it_travels_with_the_region():
    got = T.build_payload(_page([_r(w=300, h=160)]), T.SeriesContext())
    assert got["regions"][0]["fits_chars"] > 0


def test_and_is_left_out_when_it_cannot_be_measured():
    r = TextRegion(id=0, bbox=(0, 0, 0, 0), text_mask=None, bubble_mask=None,
                   bubble_bbox=None, kind="bubble")
    r.src_text, r.order = "응?", 0
    got = T.build_payload(_page([r]), T.SeriesContext())
    assert "fits_chars" not in got["regions"][0], \
        "a guess sent as a measurement is worse than no number"


def test_the_type_the_project_sets_in_is_the_one_used():
    """It was the FLOOR, and the floor is a size the typesetter never reaches.

    See `test_the_size_the_reader_gets`: on the chapter this file was written
    against, min_font was 11 and the typesetter set a median of 32. The budget
    is taken at `comfort_size` now — bigger type, less room.
    """
    c = T.SeriesContext()
    c.min_font, c.max_font = 24, 48
    small = T.build_payload(_page([_r(w=300, h=160)]), c)["regions"][0]
    big = T.build_payload(_page([_r(w=300, h=160)]),
                          T.SeriesContext())["regions"][0]
    assert small["fits_chars"] < big["fits_chars"]


def test_the_settings_carry_it_into_the_context():
    import inspect

    from mangatl import editor
    assert "p.ctx.min_font = int(s.get(\"min_font\") or 12)" in \
        inspect.getsource(editor._ctx_from_settings)


def test_the_prompt_explains_the_number():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "fits_chars" in sys
    assert "measured off the shape on the page" in re.sub(r"\s+", " ", sys)


def test_a_line_that_will_not_fit_is_flagged():
    r = _r(w=120, h=60)
    assert "holds ~" in T.too_long("x" * 300, r, 12)


def test_a_line_that_merely_fills_the_balloon_is_not():
    r = _r(w=300, h=160)
    room = T.fits_chars(r, 12)
    assert T.too_long("x" * room, r, 12) == ""


def test_the_estimate_is_given_room_to_be_wrong():
    assert 1.1 <= T.OVER_FITS <= 1.6


# ------------------------------------------------------------- the shouting

def test_a_shout_cut_down_to_one_mark_is_flagged():
    assert "shouts 3" in T.quieter("This is a miracle!", "이건 기적이야!!!")


def test_a_shout_that_survived_is_not():
    assert T.quieter("This is a miracle!!!", "이건 기적이야!!!") == ""


def test_a_line_with_one_mark_is_not_a_shout():
    assert T.quieter("Huh?", "응?") == ""
    assert T.quieter("Wait!", "잠깐!") == ""


def test_a_mixed_run_counts_too():
    assert T.marks("응?!!") == 3
    assert T.quieter("Right?", "이게 꿈은 아니겠지?\n응?!!") != ""


def test_the_prompt_says_a_run_is_not_words():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "A RUN of marks is part of the line" in sys
    assert "Shortening is about WORDS and never about punctuation" in sys


def test_it_is_a_note_and_not_a_repair():
    """Putting the marks back would be writing the line. The person reading
    the flag can see the page; the code cannot."""
    got = T.quieter("This is a miracle!", "이건 기적이야!!!")
    assert "!!!" not in got and got.startswith("the source shouts")


def test_both_notes_reach_the_region():
    import inspect
    src = inspect.getsource(T.translate_page)
    assert "quieter(r.dst_text, r.src_text)" in src
    assert "too_long(" in src and "r.flagged" in src


def test_a_stamp_sized_box_promises_nothing_rather_than_three_characters():
    """A number like 2 is not a budget, it is a rounding artefact — and the
    prompt treats `fits_chars` as a fact about the balloon, so a wrong small
    one is worse than none. Below the floor it is left out entirely."""
    assert T.fits_chars(_r(w=22, h=22), 12) == 0
    assert T.fits_chars(_r(w=300, h=160), 12) > 0


def test_a_balloon_is_not_packed_to_its_edges():
    """It is a round hole with a margin inside it, and the typesetter keeps
    clear of the outline — `typeset` has a whole clearance rule for it. Filling
    the rectangle edge to edge promises roughly twice the room that is there,
    and a promise like that comes back as a line that does not fit."""
    assert 0.3 < T.BALLOON_PACK < 0.8
    room = T.fits_chars(_r(w=300, h=160), 12)
    naive = 300 * 160 / (T.CHAR_AREA * 144)
    assert room < 0.8 * naive, (room, naive)


def test_one_mark_is_not_a_run_of_marks():
    """Nearly every line ends in one. If a single mark counted, `quieter`
    would fire on any line whose full stop replaced a question mark, which is
    a translation decision and not a lost shout."""
    assert T.marks("Wait!") == 0
    assert T.marks("Really?") == 0
    assert T.marks("Wait!!") == 2


def test_a_line_that_shouts_LOUDER_is_left_alone():
    """The note is about a shout being taken OFF. A translator who writes
    "!!!" where the source has "!!" has made a choice about the English, and
    a flag on it is a flag nobody can act on."""
    assert T.quieter("MOVE!!!!", "당장!!") == ""
    assert T.quieter("MOVE!", "당장!!") != ""
