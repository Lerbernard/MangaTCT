"""A box the reader found nothing in.

lee: *"i also want to add a fetur for read text that delets any boxes that no
text is found in so if it return nothing then delete that box that probly mena
that teh box was bad anyways"*.

This reverses a decision, and the reversal is the interesting part.
`ocr.only_symbols` refuses to call empty "symbols only", and says why:
*"deleting a box because the reader had a bad turn is the one outcome this
must never have"*.

That is still right about a bad **turn**. lee is pointing at a bad **box** --
the detector put a rectangle on something that was never writing, the reader
looked and found nothing, and that is the best evidence anybody has that the
box should not be there.

Telling the two apart is the whole of `empty_boxes`: **at least one box on the
page has to have read something.** Nine boxes read and one did not is a bad
box. Nothing read at all is an outage -- no key, no quota, a refusal, a
dropped connection -- and on that page nothing is deleted.
"""
import pytest

from where import PKG

from mangatl.editor import empty_boxes, symbol_only_boxes
from mangatl.models import TextRegion


def _r(src="", dst="", own=False, locked=False):
    r = TextRegion(id=0, bbox=(0, 0, 10, 10), kind="bubble")
    r.src_text = src
    r.dst_text = dst
    r.own_text = own
    r.locked = locked
    return r


# ------------------------------------------------- the bad box goes

def test_the_one_box_that_read_nothing_goes():
    bad, good = _r(""), _r("안녕")
    assert empty_boxes([bad, good]) == [bad]


def test_whitespace_is_nothing():
    bad, good = _r("  \n  "), _r("안녕")
    assert empty_boxes([bad, good]) == [bad]


def test_several_empties_all_go():
    a, b, good = _r(), _r(), _r("안녕")
    assert empty_boxes([a, b, good]) == [a, b]


# ------------------------------------------------- ...but an outage does not

def test_a_page_where_nothing_read_at_all_keeps_every_box():
    """No key, no quota, a refusal, a dropped connection. Deleting the page's
    boxes because the reader never answered is the outcome the original rule
    was written to prevent, and it still is."""
    assert empty_boxes([_r(), _r(), _r()]) == []


def test_a_single_box_page_that_read_nothing_is_left_alone():
    """One box and it is empty is indistinguishable from an outage, and the
    safe way to be wrong is to keep it."""
    assert empty_boxes([_r()]) == []


def test_no_boxes_is_not_an_error():
    assert empty_boxes([]) == []


# ------------------------------------------------- and three boxes are never touched

def test_a_box_somebody_typed_themselves_is_never_deleted():
    """There was never anything under it to read, so what the reader made of
    it says nothing at all."""
    mine, good = _r(own=True), _r("안녕")
    assert empty_boxes([mine, good]) == []


def test_a_locked_box_is_never_deleted():
    """Locked is the word for *I have corrected this, leave it alone*, and
    deleting it is the loudest possible way of not doing that."""
    lock, good = _r(locked=True), _r("안녕")
    assert empty_boxes([lock, good]) == []


def test_a_box_that_already_has_a_translation_is_never_deleted():
    """Re-reading a translated page must not take the English with it."""
    done, good = _r(dst="Hello"), _r("안녕")
    assert empty_boxes([done, good]) == []


def test_a_protected_box_does_not_count_as_evidence_either():
    """The three protected boxes are out of the population entirely -- they
    neither get deleted nor prove the reader was working. A page of one real
    empty box and one locked box is still a page where nothing read."""
    assert empty_boxes([_r(), _r(locked=True)]) == []


# ------------------------------------------------- it is a different question

def test_symbols_and_nothing_are_two_different_sweeps():
    """`!!` is a box with something in it that is not worth translating; empty
    is a box with nothing in it. Two questions, two switches."""
    marks, blank, good = _r("!!"), _r(""), _r("안녕")
    assert symbol_only_boxes([marks, blank, good]) == [marks]
    assert empty_boxes([marks, blank, good]) == [blank]


def test_only_symbols_still_refuses_to_call_empty_a_symbol():
    from mangatl.ocr import only_symbols
    assert only_symbols("") is False
    assert only_symbols("   ") is False
    assert only_symbols("!!") is True


# ------------------------------------------------- and it is wired in

def test_read_text_runs_the_sweep_and_can_be_turned_off():
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'if p.settings.get("drop_empty") is not False:' in src
    assert "blank = empty_boxes(regs)" in src


def test_it_runs_after_the_symbol_sweep():
    """Order does not change the answer -- the two populations cannot
    overlap -- but the message the bar shows should read in the order the
    boxes went."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    assert src.index("junk = symbol_only_boxes(regs)") < \
        src.index("blank = empty_boxes(regs)")


def test_it_is_on_for_a_project_that_has_never_heard_of_it():
    """`is not False`, not `.get(..., True)` -- a project.json written before
    this setting existed has no key at all and should behave the way lee asked
    for by default."""
    from mangatl.project import Project
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        assert Project(None, d).settings["drop_empty"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
