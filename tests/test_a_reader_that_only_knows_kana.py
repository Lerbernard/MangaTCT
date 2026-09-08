"""A second reader for paint, and one rule for whose answer to keep.

lee: *"what can i do about this[:] Sound effects read badly by every reader"*,
and after the measurement came back: *"do it for offline rrader"*.

manga-ocr was trained on typeset dialogue. It is superb at typeset dialogue and
a coin toss on a hand-drawn sound, and it fails in the way that cannot be caught
downstream - it emits an ordinary Japanese line at full confidence, because that
is what its decoder knows how to say. COO's TRBA+2D is the mirror image: trained
on 61,465 hand-labelled onomatopoeia with a 182-character alphabet, it reads
paint and cannot spell a kanji at all.

Measured over every box the detector filed as a sound effect across the 23 pages
of chapter 3 - 54 boxes transcribed off the page by eye, scored on the crop
`ocr.prepare_crop` actually makes:

    reader                painted sounds (43)   typeset filed as sfx (11)
    manga-ocr             0.401 CER  24/43      0.000 CER  11/11
    TRBA+2D               0.138 CER  32/43      0.602 CER   4/11
    the kanji rule        0.138 CER  32/43      0.136 CER   9/11

**The router is not a heuristic.** TRBA's alphabet holds no kanji, so a kanji in
manga-ocr's answer is proof the box contains something TRBA could not have
produced even in principle - which happens because one box in five labelled a
sound effect is not one: it is painted speech, a shop sign, or dialogue in a
drawn balloon.

    manga-ocr everywhere        0.319  35/54
    TRBA everywhere             0.232  36/54
    the kanji rule              0.137  41/54
    a perfect router (cheating) 0.138  43/54

Within a thousandth of a router that has been told the right answer.
"""
import numpy as np
import pytest

from mangatl import ocr as O
from mangatl import paintread as P
from mangatl.models import Page, TextRegion
from where import PKG


# ------------------------------------------------------------- the rule

def test_a_kanji_means_manga_ocr_saw_something_trba_cannot_write():
    assert P.prefer("当然ですねっ", "ずずずず") == "当然ですねっ"
    assert P.prefer("店主", "はは") == "店主"


def test_without_one_the_painted_answer_wins():
    assert P.prefer("そして", "アア") == "アア"
    assert P.prefer("じゃあ", "バチャ") == "バチャ"
    assert P.prefer("やっぱり", "ガチャン") == "ガチャン"


def test_an_empty_answer_from_either_side_is_not_an_answer():
    assert P.prefer("ドン", "") == "ドン"
    assert P.prefer("", "ドン") == "ドン"
    assert P.prefer("", "") == ""


def test_a_tie_goes_to_the_reader_that_runs_on_every_other_box():
    """Both silent, nothing to choose - and a box where the specialist has
    nothing to say should read like its neighbours."""
    assert P.prefer("  ", "  ") == ""


def test_the_kanji_test_is_the_blocks_and_not_a_guess_at_shape():
    assert P.has_kanji("当然")
    assert P.has_kanji("店主です")
    assert not P.has_kanji("バチャ")
    assert not P.has_kanji("ぬら")
    assert not P.has_kanji("う〜ん…")
    assert not P.has_kanji("")


def test_kana_and_marks_are_never_mistaken_for_kanji():
    """Everything TRBA's own alphabet contains has to pass, or the router
    hands its own vocabulary to the other reader."""
    chars = (PKG / "paintread" / "trba" / "charset.txt").read_text(
        encoding="utf-8-sig").strip()
    assert len(chars) > 150, "the alphabet did not load"
    assert not P.has_kanji(chars), \
        "something in TRBA's own alphabet reads as a kanji"


# ------------------------------------------------- absent is a normal state

def test_no_checkpoint_is_a_sentence_and_not_a_crash():
    assert "no painted-text weights" in P.why_not("")
    assert "not at" in P.why_not("/nowhere/trba.pth")
    assert not P.available("")


def test_the_page_reads_exactly_as_before_when_it_is_missing():
    pg = _page(["sfx", "bubble"])
    O.ocr_page(pg, engine=lambda img: "ドン", lang="ja", paint_weights="")
    assert [r.src_text for r in pg.regions] == ["ドン", "ドン"]


def test_a_named_path_that_is_not_there_does_not_stop_the_read():
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "ドン", lang="ja",
               paint_weights="/nowhere/trba.pth")
    assert pg.regions[0].src_text == "ドン"


# --------------------------------------------------------- and the wiring

def _page(kinds):
    pg = Page(image=np.full((200, 400, 3), 240, np.uint8))
    pg.regions = []
    for i, k in enumerate(kinds):
        r = TextRegion(id=i, bbox=(10 + i * 60, 10, 50, 80), kind=k, order=i)
        r.text_mask = np.zeros((200, 400), np.uint8)
        r.text_mask[20:70, 15 + i * 60:55 + i * 60] = 255
        pg.regions.append(r)
    return pg


def _wire(monkeypatch, painted="バチャ"):
    """Stand in for the model, so the wiring is tested without 200MB."""
    seen = []
    monkeypatch.setattr(P, "available", lambda p: True)
    monkeypatch.setattr(P, "get_reader", lambda p: ("fake",))

    def read_one(img, reader):
        seen.append(img)
        return painted
    monkeypatch.setattr(P, "read_one", read_one)
    return seen


def test_only_the_sound_effect_family_is_read_twice(monkeypatch):
    """Everywhere else manga-ocr is already at 0.025 CER and TRBA cannot spell
    a kanji, so a second pass there costs 0.7s a box to make the page worse."""
    seen = _wire(monkeypatch)
    pg = _page(["bubble", "freefloat", "sfx", "narration"])
    O.ocr_page(pg, engine=lambda img: "ドン", lang="ja", paint_weights="x.pth")
    assert len(seen) == 1, "read twice on a box that is not paint"


def test_the_painted_answer_reaches_the_box(monkeypatch):
    _wire(monkeypatch, painted="バチャ")
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "じゃあ", lang="ja", paint_weights="x.pth")
    assert pg.regions[0].src_text == "バチャ"


def test_a_kanji_in_the_first_answer_keeps_it(monkeypatch):
    _wire(monkeypatch, painted="ずずずず")
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "当然ですねっ", lang="ja",
               paint_weights="x.pth")
    assert pg.regions[0].src_text == "当然ですねっ"


def test_a_box_that_read_nothing_is_not_offered_to_it(monkeypatch):
    """There is no first answer to settle against, and `empty_boxes` is the
    step that has an opinion about an empty box."""
    seen = _wire(monkeypatch)
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "", lang="ja", paint_weights="x.pth")
    assert seen == []


def test_a_broken_specialist_costs_the_page_nothing(monkeypatch):
    """The first answer is already in hand, and it is the one the app had
    before this reader existed."""
    monkeypatch.setattr(P, "available", lambda p: True)
    monkeypatch.setattr(P, "get_reader", lambda p: ("fake",))

    def boom(img, reader):
        raise RuntimeError("no")
    monkeypatch.setattr(P, "read_one", boom)
    pg = _page(["sfx"])
    O.ocr_page(pg, engine=lambda img: "ドン", lang="ja", paint_weights="x.pth")
    assert pg.regions[0].src_text == "ドン"
    assert "painted-text reader failed" in (pg.regions[0].flagged or "")


def test_the_locked_line_is_still_never_overwritten(monkeypatch):
    _wire(monkeypatch)
    pg = _page(["sfx"])
    pg.regions[0].src_text = "ドドン"
    pg.regions[0].locked = True
    O.ocr_page(pg, engine=lambda img: "ドン", lang="ja", paint_weights="x.pth")
    assert pg.regions[0].src_text == "ドドン"


# ----------------------------------------------------- where it comes from

def test_the_offline_step_asks_the_project_for_it():
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_here("):]
    body = body[:body.index("\ndef ")]
    assert "p.paint_weights()" in body
    assert "paint_weights=paint" in body


def test_it_is_japanese_only():
    """The alphabet is Japanese kana. Offering it to a Korean or Chinese page
    is 0.7s a box to produce kana that is not on the page."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_here("):]
    body = body[:body.index("\ndef ")]
    assert 'if lang == "ja" else ""' in body


def test_the_ai_path_does_not_use_it():
    """It reads the same paint without inventing dialogue over it, and it
    reads the whole page at once rather than a crop at a time."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_with_ai("):]
    body = body[:body.index("\ndef ")]
    assert "paint_weights" not in body


def test_the_checkpoint_is_found_beside_the_others(tmp_path):
    from mangatl.project import Project
    p = Project(None, str(tmp_path))
    assert p.paint_weights() == ""
    (tmp_path / "w.onnx").write_bytes(b"x")
    (tmp_path / "TRBA_Rot+SAR+HardROIhalf+2D.pth").write_bytes(b"x")
    p.settings["weights"] = str(tmp_path / "w.onnx")
    assert p.paint_weights().endswith("TRBA_Rot+SAR+HardROIhalf+2D.pth")


def test_it_says_that_the_ai_is_still_ahead():
    """The thing a docstring is most tempted to leave out. Scored against lee's
    own export on the twelve pages where both runs found the same number of
    sound effects, the AI is 0.056 against this reader's 0.130 - better, and no
    longer four times better. Somebody choosing the offline reader should be
    able to find out what they are giving up without running the experiment
    again."""
    doc = P.__doc__ or ""
    assert "0.056" in doc and "0.130" in doc
    assert "DOES NOT CATCH THE AI" in doc
    assert "n=18" in doc, "and how thin the evidence is"


def test_the_licence_travels_with_the_code():
    """991 lines of somebody else's model are in this tree. MIT permits that
    and MIT asks for the notice to come with it."""
    lic = (PKG / "paintread" / "trba" / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in lic
    assert "Baek JeongHun" in lic
    notice = (PKG / "NOTICE").read_text(encoding="utf-8")
    assert "TRBA+2D" in notice
    assert "paintread/trba/" in notice
    assert "WEIGHTS are not" in notice, \
        "and that the weights are still the person's own download"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
