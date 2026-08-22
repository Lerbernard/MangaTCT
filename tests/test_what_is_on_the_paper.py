"""The reader copies the page; it does not tidy it.

Two lines of `build_ocr_system` were telling the model to change what it saw,
and both showed up as measured losses when lee read chapter 1 four ways.

**The ellipsis.** The prompt said *"Write an ellipsis as three periods ..."*.
That was written for Japanese. His chapter prints ``거, 취향 참….`` and
``흐음….`` - an ellipsis glyph and then a full stop, which is ordinary Korean
typesetting - and the read came back ``참...``: the stop gone and the ellipsis
spelled a way the page does not spell it. Over the chapter, the run that
followed the instruction hardest wrote **8** ASCII ellipses and kept **2** of
the printed ``….``; the run that ignored it wrote **0** and kept **8**.

Three periods belong in the ENGLISH, where a comic font has to draw them.
That rule lives in the translation and proofreading prompts and stays there -
`test_the_english_still_gets_three_periods` is what stops somebody "making
these consistent" and undoing it. The transcription is meant to be what is on
the paper.

**The line breaks.** Nothing asked for them. Reading a crop per box, page
013's narration - printed as three lines - came back as one, and so did 049's
and 014's. A crop shows the whole box, so the break is right there in the
picture; it was being flattened because no one said not to.

Both are prompt-only changes. The pictures are identical; what changed is what
the reader is asked to do with them.
"""
import re

from mangatl.translate import (build_ocr_system, build_proofread_system,
                               build_system)


def _ocr(src="Korean"):
    return build_ocr_system(src)


# ------------------------------------------------------------- the ellipsis

def test_the_reader_is_no_longer_told_to_rewrite_an_ellipsis():
    """The exact sentence that cost the chapter its full stops."""
    assert "Write an ellipsis as three periods" not in _ocr()


def test_it_is_asked_for_the_punctuation_that_is_printed():
    s = _ocr()
    assert "Copy the punctuation EXACTLY as printed" in s
    assert "character for character" in s


def test_and_told_that_the_stop_after_an_ellipsis_is_part_of_the_line():
    """`….` is the specific thing that was being dropped, so it is named."""
    assert "….) is part of the line" in _ocr()


def test_the_long_vowel_mark_survived_the_edit():
    """It was in the same sentence as the ellipsis rule and is still wanted:
    ー is a mark, not a dash, and a reader that writes - instead has changed
    the page."""
    assert "long-vowel mark is ー" in _ocr()


def test_the_english_still_gets_three_periods():
    """The other half, and the reason the two rules look contradictory.

    A comic typesetting font often has no ellipsis glyph, so the TRANSLATION
    spells it out. Somebody reading these three prompts side by side will be
    tempted to make them agree; this is the test that says they must not."""
    for sys in (build_system("manhwa", "en", "Korean"),
                build_proofread_system("manhwa", "en", "Korean")):
        assert "three periods for an ellipsis" in sys


# ----------------------------------------------------------- the line breaks

def test_the_printed_line_breaks_are_asked_for():
    s = _ocr()
    assert "Keep the LINE BREAKS as printed" in s
    assert "broken in the same places" in s


def test_and_it_is_told_not_to_re_wrap_or_join():
    """Two different ways of getting it wrong: 013 came back joined into one
    line, and a re-wrap would put the breaks somewhere the artist did not."""
    s = _ocr()
    assert "Do not re-wrap it" in s and "do not join it into one line" in s


def test_the_break_is_asked_for_as_the_character_the_reader_returns():
    r"""It has to be \n, because that is what `_unescape_breaks` and
    `looks_like_garbage` are both written against."""
    assert "\\n" in _ocr()


# ------------------------------------------------- nothing else moved with it

def test_the_rules_that_were_already_earning_their_place_are_still_there():
    s = _ocr()
    assert "A NAME YOU DO NOT RECOGNISE IS STILL THE NAME THAT IS PRINTED" in s
    assert "Dashes, brackets and quotation marks printed as part of a line" in s
    assert "prefer the empty string" in s
    assert "Do NOT include furigana" in s


def test_it_is_still_one_prompt_per_source_language():
    assert "Korean comics" in _ocr("Korean")
    assert "Japanese comics" in _ocr("Japanese")


# ------------------------------------- ...and the gate downstream of the read

def test_a_printed_ellipsis_is_not_mistaken_for_a_runaway():
    """A small win that comes free with it. `looks_like_garbage` flags seven of
    the same character in a row, so ``음........`` - the ASCII spelling the old
    rule produced for page 029 - was one dot away from being flagged. Spelled
    the way the page spells it, it is three characters and nowhere near."""
    from mangatl.models import TextRegion
    from mangatl.ocr import looks_like_garbage
    r = TextRegion(id=0, bbox=(0, 0, 60, 40), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, 60, 40), kind="bubble")
    assert looks_like_garbage("음........", r) == "ocr: repeated character run"
    assert looks_like_garbage("음…….", r) is None
    assert looks_like_garbage("거, 취향 참….", r) is None


def test_a_line_that_is_only_punctuation_is_still_caught():
    """Copying punctuation faithfully must not turn the empty-box gate off."""
    from mangatl.models import TextRegion
    from mangatl.ocr import looks_like_garbage
    r = TextRegion(id=0, bbox=(0, 0, 60, 40), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, 60, 40), kind="bubble")
    assert looks_like_garbage("….", r) == "ocr: punctuation only"


def test_the_line_breaks_do_not_count_toward_the_length_gate():
    """Asking for three lines where there used to be one adds two characters
    to every narration box, and the gate must not start firing because of it."""
    import numpy as np
    from mangatl.models import TextRegion
    from mangatl.ocr import looks_like_garbage
    m = np.zeros((40, 200), np.uint8)
    m[5:35, 5:195] = 255
    r = TextRegion(id=0, bbox=(0, 0, 200, 40), text_mask=m, bubble_mask=None,
                   bubble_bbox=(0, 0, 200, 40), kind="bubble")
    flat = "아르실란의 원주민들은 침식의 땅에서 오래 못 버틴다."
    assert looks_like_garbage(flat, r) is None
    lines = "아르실란의 원주민들은\n침식의 땅에서 오래\n못 버틴다."
    assert looks_like_garbage(lines, r) is None
