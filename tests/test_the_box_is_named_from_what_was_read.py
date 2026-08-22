"""Name a box from what the reader got out of it, not from a second net.

lee, after every cheaper alternative to DB++/COO was measured: *"do this I
build the reordered pipeline, since that's where the idea pays off regardless
of which OCR you use"*.

    detect (and label)  ->  OCR  ->  translate          before
    detect  ->  OCR everything  ->  label  ->  translate  after

The label costs nothing in the second order, because `ocr.ocr_page` and the
editor's AI read already run over every region on the page -- sound effects
included -- and the answer was being thrown away. What it replaces is a 116MB
model and 2.4-3.9 s a page.

## THE SIGNAL IS GRAMMAR, NOT LEGIBILITY

Measured over 257 boxes with a recogniser:

    boxes COO calls paint   median 1 character,  0.00 kanji, 0.00 kana
    boxes COO calls text    median 3 characters, 0.50 kanji, 0.29 kana

"Clean readable Japanese means dialogue" was the first shape of this idea and
it is wrong -- ガチャ is perfectly clean readable Japanese. A sentence carries
kanji and it carries particles; a painted sound is kana with no grammar in it.

Five things have to hold:

* **The balloon still outranks the text.** A box inside a drawn balloon is
  dialogue whatever the reader made of it.
* **Somebody's own box is never touched.** Nothing was read out of it because
  there was nothing under it to read, and calling that paint is the worst
  available answer.
* **It is off by default and manga only**, because the thresholds have never
  been swept against real OCR output.
* **It runs BEFORE the two drop passes**, so a box renamed `sfx` is judged as
  a sound rather than as dialogue that came back empty.
* **And it is asked of the ocr step, not of the detector**, because that is
  the first moment the evidence exists.
"""
import tempfile

import pytest

from where import PKG

from mangatl import readkinds
from mangatl.project import Project


def _p(**settings):
    d = tempfile.mkdtemp()
    p = Project(None, d)
    p.settings.setdefault("medium", "manga")
    p.settings.update(settings)
    return p


class _R:
    def __init__(self, kind="freefloat", text="", balloon=None, own=False):
        self.kind = kind
        self.src_text = text
        self.bubble_mask = balloon
        self.own_text = own


# --- what reads as a sound -----------------------------------------------

@pytest.mark.parametrize("text", ["ガチャ", "ドドド", "ザァァ", "スッ",
                                  "キョロキョロ", "ぶぶぶっっっ", "ゴゴゴゴ"])
def test_kana_with_no_grammar_in_it_is_a_sound(text):
    assert readkinds.looks_like_a_sound(text)


@pytest.mark.parametrize("text", ["こっちの部屋は自由に使ってください", "第三章",
                                  "悪女見習いさん", "血が…", "大丈夫ですか",
                                  "はい", "そうだね"])
def test_kanji_or_grammar_is_speech(text):
    assert not readkinds.looks_like_a_sound(text)


def test_nothing_read_at_all_is_a_sound():
    """A box the reader returned nothing for held no letters it knew, which
    is what a brush stroke is -- and it is the honest answer when OCR failed
    too: paint it out rather than hand a translator an empty line."""
    assert readkinds.looks_like_a_sound("")
    assert readkinds.looks_like_a_sound("   ")


def test_punctuation_alone_is_a_sound():
    assert readkinds.looks_like_a_sound("…！？")


def test_a_long_run_of_kana_is_a_sentence_the_reader_mangled():
    """Twelve characters with no kanji and no particle is not a noise."""
    assert not readkinds.looks_like_a_sound("あいうえおかきくけこさしすせそ")


def test_the_length_bar_is_its_own_setting():
    assert readkinds.looks_like_a_sound("アアアアアアアア", least=12)
    assert not readkinds.looks_like_a_sound("アアアアアアアア", least=4)


def test_the_long_vowel_mark_is_writing_and_not_punctuation():
    """`ー` is what an effect is made of, so it counts toward the length --
    unlike a full stop, which carries no evidence either way. A full stop
    being stripped and a 長音 not is the whole difference."""
    assert "ー" not in readkinds.STRIP
    assert "。" in readkinds.STRIP
    assert readkinds.looks_like_a_sound("ゴォォォ")
    # eleven marks with a 長音 in them is still under the bar; strip it and
    # the count would be wrong rather than merely different.
    assert not readkinds.looks_like_a_sound("アーアーアーアーアーアーア")


def test_the_known_miss_is_written_down():
    """つづく is three hiragana with no grammar and reads as a sound. It is
    documented rather than special-cased: a stop-list of words that are not
    effects never covers the next series."""
    assert readkinds.looks_like_a_sound("つづく")
    assert "つづく" in readkinds.__doc__


# --- and what that makes the box ----------------------------------------

def test_a_balloon_outranks_whatever_was_read():
    assert readkinds.kind_from_text("sfx", "ガチャ", True) == "bubble"
    assert readkinds.kind_from_text("freefloat", "", True) == "bubble"


def test_outside_a_balloon_the_text_decides():
    assert readkinds.kind_from_text("bubble", "ガチャ", False) == "sfx"
    assert readkinds.kind_from_text("sfx", "血が…", False) == "freefloat"


def test_relabel_counts_what_it_moved():
    rs = [_R("bubble", "ガチャ"), _R("sfx", "大丈夫ですか"), _R("sfx", "ドドド")]
    assert readkinds.relabel(rs) == 2
    assert [r.kind for r in rs] == ["sfx", "freefloat", "sfx"]


def test_somebody_elses_own_box_is_left_alone():
    rs = [_R("bubble", "", own=True)]
    assert readkinds.relabel(rs) == 0
    assert rs[0].kind == "bubble"


def test_a_region_with_no_text_attribute_does_not_explode():
    class Bare:
        kind = "bubble"
        bubble_mask = None
    r = Bare()
    readkinds.relabel([r])
    assert r.kind == "sfx"


# --- and where it is wired ----------------------------------------------

def test_it_is_off_by_default():
    assert _p().settings.get("kind_from_text") in (False, None)


def test_the_ocr_step_takes_the_switch_and_defaults_to_off():
    import inspect
    from mangatl import ocr
    sig = inspect.signature(ocr.ocr_page)
    assert sig.parameters["relabel"].default is False


def test_the_editor_does_not_rename_a_box_any_more():
    """The rule still stands and `readkinds` still holds it - the command line
    can still ask `ocr_page(relabel=True)` for it. What went is the editor
    calling it: lee: *"make it so that read text only read teh etxt and not
    modify boxes exapt for removing boxes with no text or remoeving boxes
    with only symobos"*, and renaming a box is modifying it.

    It was off by default the whole time it was wired in, so nothing about a
    run changes - the thresholds behind it were swept against a recogniser,
    never against real reader output, which is why it never got turned on."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def do_ocr("):]
    body = body[:body.index("\ndef ")]
    assert "from .readkinds import" not in body
    assert "_relabel(" not in body
    # ...and there is no switch left offering it
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="kind_from_text"' not in html
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "function syncKindText(" not in js
