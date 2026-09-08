"""A box whose reading is part of an overlapping box's reading is the same
writing answered twice - the fragment goes, the whole stays.

lee: *"do this Substring dedupe after read"*, and again after it spent a day
out: *"can you gring teh fix we had before"*.

001's painted 今日 title survives detection as two overlapping boxes, 今
inside 今日, because COO vouches for the small one past the kids-union rule.
The pixels cannot settle that and the readings can.

The match is EXACT and the overlap is 0.6, and both of those were briefly
loosened and put back. lee's page 017 has そんなので足りるか over 足りるかよ,
offset down one column, which reads exactly like one shout boxed twice - so
the comparison was widened to let a character differ and the overlap dropped
to 0.35. They are two people shouting over each other, Rofan and Glow, and the
loosened rule would have deleted Glow's line: *"everrything is working as
entened the 2 016 and 017 are not mistakes"*. A duplicate left on the page is
one keypress from gone; a deleted line is gone.

It only ever REMOVES a box, which is what earns it a place in a step that
reads: lee's rule is *"read text only read teh etxt and not modify boxes exapt
for removing boxes with no text or remoeving boxes with only symobos"*, and a
box holding no writing of its own is the third of those. The pass that RENAMED
a box on what was read in it stayed out.
"""
import pytest

from mangatl.editor import read_twice_boxes
from mangatl.models import TextRegion


def _r(id, bbox, text, kind="sfx", **kw):
    r = TextRegion(id=id, bbox=tuple(bbox), kind=kind, src_text=text)
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _ids(dead):
    return sorted(r.id for r in dead)


def test_the_fragment_dies_and_the_whole_stays():
    regs = [_r(1, (0, 0, 166, 179), "今"),
            _r(2, (0, 0, 434, 180), "今日")]
    assert _ids(read_twice_boxes(regs)) == [1]


def test_every_fragment_of_the_title_dies():
    regs = [_r(1, (0, 0, 166, 179), "今"),
            _r(2, (240, 0, 170, 180), "日"),
            _r(3, (0, 0, 434, 180), "今日")]
    assert _ids(read_twice_boxes(regs)) == [1, 2]


def test_a_chain_resolves_to_the_whole_line_in_one_pass():
    """今 inside 今日 inside the painted line: only the line stays, and the
    middle box dies into a SURVIVOR, not into a box that is also dying."""
    regs = [_r(1, (0, 0, 60, 60), "今"),
            _r(2, (0, 0, 120, 60), "今日"),
            _r(3, (0, 0, 300, 60), "今日は晴れ")]
    assert _ids(read_twice_boxes(regs)) == [1, 2]


def test_equal_readings_keep_the_bigger_box():
    regs = [_r(1, (0, 0, 60, 60), "ドン"),
            _r(2, (0, 0, 120, 100), "ドン")]
    assert _ids(read_twice_boxes(regs)) == [1]


# ------------------------------------- and the pair that must NOT be touched

def test_the_two_shouts_on_lees_page_017_both_stay():
    """The reason the comparison is exact.

    Two people shouting over each other, boxed one above the other down the
    same column: id6 is Rofan's そんなので足りるか, id5 is Glow's 足りるかよ.
    They overlap 45% of the smaller box, they are the same size, and one
    reading is one character off a piece of the other - every loose measure
    calls them one shout read twice, and lee says they are not: *"everrything
    is working as entened the 2 016 and 017 are not mistakes"*.

    Exact substring is what saves them: 足りるかよ is not inside
    そんなので足りるか, because of the よ."""
    regs = [_r(6, (691, 553, 68, 126), "そんなので足りるか"),
            _r(5, (677, 609, 68, 123), "足りるかよ")]
    assert read_twice_boxes(regs) == []


def test_and_they_stay_when_the_reader_slips_a_script_too():
    """The same pair from the run before, where the reader gave 足リるかよ with
    a katakana リ and the first box a trailing と. Folding the scripts together
    was tried to make these match - which would have deleted Glow's line."""
    regs = [_r(6, (752, 596, 60, 200), "そんなので足りるかと"),
            _r(5, (742, 660, 62, 140), "足リるかよ")]
    assert read_twice_boxes(regs) == []


def test_a_near_miss_is_a_different_sound():
    """ドン and ドッ are two sounds, whatever they overlap."""
    regs = [_r(1, (0, 0, 60, 60), "ドッ"),
            _r(2, (0, 0, 120, 100), "ドン")]
    assert read_twice_boxes(regs) == []


def test_a_sound_written_in_the_other_script_is_its_own_box():
    """キョロ and きょろ are the same word and may be two deliberate
    spellings, and this function DELETES a box. Two of them stay two."""
    regs = [_r(1, (0, 0, 60, 60), "キョロ"),
            _r(2, (0, 0, 200, 200), "きょろきょろ")]
    assert read_twice_boxes(regs) == []


def test_nothing_written_down_goes_through_the_comparison_form():
    regs = [_r(1, (0, 0, 60, 60), "キョロ"),
            _r(2, (0, 0, 200, 200), "きょろきょろ")]
    read_twice_boxes(regs)
    assert regs[0].src_text == "キョロ"
    assert regs[1].src_text == "きょろきょろ"


def test_full_width_and_half_width_are_the_same_reading():
    from mangatl.editor import _fold_kana
    assert _fold_kana("ﾄﾞﾝ") == _fold_kana("ドン")
    assert _fold_kana("Ａ１") == "A1"


def test_the_same_word_elsewhere_on_the_page_is_its_own_writing():
    """Substring alone is nothing: the fragment must stand on the bigger
    box's ground."""
    regs = [_r(1, (0, 0, 60, 60), "今"),
            _r(2, (300, 300, 200, 60), "今日")]
    assert read_twice_boxes(regs) == []


def test_touching_at_a_corner_is_not_standing_on_it():
    """`READ_TWICE_IN` is 0.6 of the SMALLER box - a fragment of one piece of
    writing is drawn where that writing is, not beside it."""
    regs = [_r(1, (0, 0, 100, 100), "今"),
            _r(2, (90, 90, 300, 300), "今日")]
    assert read_twice_boxes(regs) == []


def test_the_overlap_is_the_one_it_was_put_back_to():
    from mangatl.editor import READ_TWICE_IN
    assert READ_TWICE_IN == 0.6, "0.35 came from the misread 017 pair"


def test_there_is_no_fuzzy_comparison_left():
    """`_off_by` was an approximate-substring distance with a 0.25 slack. It
    existed to catch 017, which was never a duplicate."""
    from mangatl import editor as E
    assert not hasattr(E, "_off_by")
    assert not hasattr(E, "READ_TWICE_OFF")


def test_the_readings_are_compared_without_their_spacing():
    regs = [_r(1, (0, 0, 60, 60), "今 日"),
            _r(2, (0, 0, 200, 60), "今日は晴れ")]
    assert _ids(read_twice_boxes(regs)) == [1]


def test_an_empty_reading_proves_nothing_either_way():
    """"" is a substring of everything, and a box that read nothing is
    `empty_boxes`'s question, not this one's."""
    regs = [_r(1, (0, 0, 60, 60), ""),
            _r(2, (0, 0, 200, 60), "今日")]
    assert read_twice_boxes(regs) == []


def test_the_three_protections_hold_for_the_fragment():
    for kw in ({"locked": True}, {"own_text": True},
               {"dst_text": "TODAY"}):
        regs = [_r(1, (0, 0, 166, 179), "今", **kw),
                _r(2, (0, 0, 434, 180), "今日")]
        assert read_twice_boxes(regs) == [], kw


def test_families_do_not_matter_the_writing_does():
    """The route may have called the fragment sfx and the whole freefloat -
    it is still one piece of writing."""
    regs = [_r(1, (0, 0, 166, 179), "今", kind="sfx"),
            _r(2, (0, 0, 434, 180), "今日", kind="freefloat")]
    assert _ids(read_twice_boxes(regs)) == [1]


def test_dialogue_side_by_side_is_left_alone():
    """はい in one balloon, はい、そうです in the next: no overlap, two
    answers to two moments."""
    regs = [_r(1, (0, 0, 80, 120), "はい", kind="bubble"),
            _r(2, (100, 0, 120, 120), "はい、そうです", kind="bubble")]
    assert read_twice_boxes(regs) == []


def test_the_do_ocr_wiring_runs_before_the_links():
    """A dropped fragment must never first be linked to a neighbour - same
    rule as the other post-read drops."""
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    assert body.index("read_twice_boxes(regs)") < \
        body.index("link_sections(regs)")


def test_the_reader_is_asked_not_to_do_it_in_the_first_place():
    """The drop is the safety net; the prompt is the system. lee: *"can you
    come up with a system or a prompt so that it dont double read"*.

    The rule names the DECISION rather than the symptom - one run of writing
    belongs to one region, the one whose outline fits it, and the other gets
    the empty string - and it is careful to say ONE RUN, because two boxes
    overlapping on a page is not evidence that they hold the same writing.
    lee's 017 pair overlap and hold two different shouts."""
    from mangatl.translate import build_ocr_system
    t = build_ocr_system("Japanese")
    assert "ONE RUN OF WRITING BELONGS TO ONE REGION" in t
    assert "EMPTY STRING for the other" in t
    assert "PART of the same line" in t, "the tail case, not just the twin"
    assert "fits them most closely" in t, "and which of the two keeps it"


def test_the_emptied_box_is_then_removed_by_the_drop_that_already_exists():
    """Nothing new has to decide about boxes: the reader empties the loser and
    `empty_boxes` takes it away, which is a drop lee already asked for."""
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    assert "empty_boxes(regs)" in body


def test_the_crop_still_shows_every_glyph_under_it():
    """Blanking the neighbour's ink was tried and reverted: `_pixel_owner`
    splits a SHARED glyph by nearest centre, which butchers the very case it
    was tried for - both boxes on one column came back holding half-erased
    characters."""
    from where import PKG
    src = (PKG / "ocr.py").read_text(encoding="utf-8")
    body = src[src.index("def page_box_crops("):]
    body = body[:body.index("\ndef ")]
    assert "keep = owner[y0:y1, x0:x1] >= 0" in body
    assert "vis[others] = 255" not in body


def test_it_is_the_only_one_of_the_three_that_came_back():
    """The other two passes taken out that day RENAMED a box. This one
    removes one, which is the difference lee's rule turns on."""
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert "def read_twice_boxes(" in src
    assert "def speech_in_sfx(" not in src
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    assert "_relabel(" not in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
