"""A box whose reading is part of an overlapping box's reading is the same
writing answered twice - the fragment goes, the whole stays.

lee: *"do this Substring dedupe after read"*, and again after it spent a day
out: *"can you gring teh fix we had before"*.

Two cases, one shape. 001's painted 今日 title survives detection as two
overlapping boxes, 今 inside 今日, because COO vouches for the small one past
the kids-union rule. 017's そんなので足りるかと and 足りるかよ are one line of
dialogue boxed twice at different extents. The pixels cannot settle either -
the 017 pair overlap 45% of the smaller box and are the same size, so no
containment rule reaches them - and the readings settle both.

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


def test_the_offset_pair_off_lees_page_017():
    """The case that brought it back, with the real boxes and the real
    readings off his page.

    TWO things had to give for it. They overlap 45% of the smaller box and are
    the same size, so containment never reached them. And the reader did not
    say the same thing both times - そんなので足りるかと against 足りるかよ,
    differing in the last character - so exact substring never reached them
    either."""
    regs = [_r(6, (691, 553, 68, 126), "そんなので足りるかと"),
            _r(5, (677, 609, 68, 123), "足りるかよ")]
    assert _ids(read_twice_boxes(regs)) == [5]


def test_a_reading_too_far_off_is_a_different_sound():
    """One character in five is the same line read twice. One in two is not:
    ドン and ドッ are two sounds, whatever they overlap."""
    regs = [_r(1, (0, 0, 60, 60), "ドッ"),
            _r(2, (0, 0, 120, 100), "ドン")]
    assert read_twice_boxes(regs) == []


def test_the_slack_is_measured_against_the_shorter_reading():
    """So it is mean about short ones, where a false match would hurt: a
    reading of three characters gets no slack at all."""
    from mangatl.editor import _off_by, READ_TWICE_OFF
    assert _off_by("足りるかよ", "そんなので足りるかと") <= READ_TWICE_OFF
    assert _off_by("今", "今日") == 0.0
    assert _off_by("ドン", "ドッ") > READ_TWICE_OFF
    assert _off_by("あ", "いろは") > READ_TWICE_OFF


def test_the_same_word_elsewhere_on_the_page_is_its_own_writing():
    """Substring alone is nothing: the fragment must stand on the bigger
    box's ground."""
    regs = [_r(1, (0, 0, 60, 60), "今"),
            _r(2, (300, 300, 200, 60), "今日")]
    assert read_twice_boxes(regs) == []


def test_touching_at_a_corner_is_not_standing_on_it():
    """`READ_TWICE_IN` is 0.35 of the SMALLER box - under the 45% lee's real
    pair overlap, and well over a graze."""
    regs = [_r(1, (0, 0, 100, 100), "今"),
            _r(2, (90, 90, 300, 300), "今日")]
    assert read_twice_boxes(regs) == []


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
    the empty string - because 017's pair were not identical: one box got the
    whole line and the other its tail."""
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
