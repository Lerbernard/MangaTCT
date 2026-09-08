"""The reader on this computer says so when it has read paint.

lee: *"what can i do about this[:] Sound effects read badly by every reader"*.

The first answer given to that was wrong, and wrong because it was measured on
five sound effects. The chapter has forty-three. Every box the detector filed
as a sound effect across the 23 pages was cut out and transcribed off the page
by eye, and the picture that came back is not "manga-ocr is bad at sound
effects" - it is two different things sharing a label:

    typeset writing filed as sfx   CER 0.000   11/11 exact
    actually painted sounds        CER 0.376   24/43 exact

Perfect on one, a coin toss on the other, and the label does not tell them
apart - eleven of the fifty-four boxes marked "sfx" hold ordinary typeset
dialogue or a shop sign.

**The dangerous half is not the error rate.** Nine of the nineteen misses are
not misreadings at all. They are ordinary Japanese words invented over a brush
stroke:

    アア     -> そして        バチャ  -> じゃあ      バチャ -> ダメっ、
    ガチャッ  -> やっぱり      ドホ    -> いや、      グッ   -> ハハッ

That is the decoder's language model filling a silence. It was trained on
typeset dialogue, so when the glyphs are nothing it knows, it emits a common
dialogue string at full confidence. `looks_like_garbage` cannot catch one:
they are not garbage, they are good Japanese in the wrong place. Nothing
downstream can catch one either, and nobody reading the finished page would
question it.

So the box says so itself. A note, not a verdict: the reading stays, `ocr_ok`
stays true, nothing is removed - it is right more often than not, and the cost
of throwing away 24 correct readings to catch 19 wrong ones is not worth
paying. What changes is that a wrong one is now visible.
"""
import numpy as np
import pytest

from mangatl import ocr as O
from mangatl.models import Page, TextRegion


def _page(kinds):
    pg = Page(image=np.full((200, 400, 3), 240, np.uint8))
    pg.regions = []
    for i, k in enumerate(kinds):
        r = TextRegion(id=i, bbox=(10 + i * 60, 10, 50, 80), kind=k, order=i)
        r.text_mask = np.zeros((200, 400), np.uint8)
        r.text_mask[20:70, 15 + i * 60:55 + i * 60] = 255
        pg.regions.append(r)
    return pg


def _read(pg, answer="ドン"):
    O.ocr_page(pg, engine=lambda img: answer, lang="ja", relabel=False)
    return {r.id: (r.src_text, r.flagged or "") for r in pg.regions}


def test_a_sound_effect_read_here_is_flagged():
    got = _read(_page(["sfx"]))
    assert "weak spot" in got[0][1]


def test_the_reading_is_kept_and_the_box_is_not_touched():
    """A note, not a verdict. Twenty-four of the forty-three are right."""
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "ドン", lang="ja", relabel=False)
    r = pg.regions[0]
    assert r.src_text == "ドン"
    assert r.ocr_ok is not False, "a flag is not a failure"
    assert r.kind == "sfx", "nothing renames the box"


def test_dialogue_is_not_flagged():
    """The 81% of boxes this reader is excellent at get no note. A warning on
    every box is a warning on none."""
    got = _read(_page(["bubble", "freefloat", "narration"]))
    for rid, (_text, flag) in got.items():
        assert "weak spot" not in flag, rid


def test_a_sound_effect_that_read_nothing_is_not_flagged():
    """An empty box is `empty_boxes`'s question. There is no invented reading
    to warn about when there is no reading."""
    got = _read(_page(["sfx"]), answer="")
    assert "weak spot" not in got[0][1]


def test_the_note_does_not_replace_a_real_complaint():
    """`looks_like_garbage` speaks first and keeps the box. Its message is
    about THIS reading being unusable; the note is about the reader's record on
    paint, and a box that failed outright does not need both."""
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "|||", lang="ja", relabel=False)
    flag = pg.regions[0].flagged or ""
    assert flag and "weak spot" not in flag


def test_it_is_measured_where_it_is_decided():
    """The numbers, in the code, next to the line that acts on them - so the
    next person to argue about this argues with 43 boxes rather than a
    feeling. Five was how the wrong answer got given the first time."""
    from where import PKG
    src = (PKG / "ocr.py").read_text(encoding="utf-8")
    at = src.index("painted sounds are ")
    note = src[max(0, at - 2400):at]
    assert "24/43" in note and "11/11" in note
    assert "0.401" in note and "0.000" in note
    assert "そして" in note, "the invented dialogue, named"


def test_the_note_goes_away_once_the_second_reader_is_here():
    """A warning about a problem that has been fixed teaches people to ignore
    warnings. With `paintread` running these boxes come back at 0.138 and the
    invented dialogue is gone, so there is nothing to warn about."""
    from where import PKG
    src = (PKG / "ocr.py").read_text(encoding="utf-8")
    at = src.index("painted sounds are ")
    head = src[max(0, at - 2400):at]
    assert "painter is None" in src[max(0, at - 2600):at], \
        "the note is not conditioned on the specialist being absent"
    assert "0.138" in head, "and it says what the second reader scores instead"


def test_the_ai_path_carries_no_such_note():
    """It does not invent dialogue over paint - lee's own 23-page export has
    36 sound effects read by the AI and not one of them is a stray sentence.
    A note there would be a warning about nothing."""
    from where import PKG
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_with_ai("):]
    body = body[:body.index("\ndef ")]
    assert "weak spot" not in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
