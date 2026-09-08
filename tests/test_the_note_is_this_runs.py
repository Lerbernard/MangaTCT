"""A remark on a box belongs to the run that made it, and to no other.

lee reran the whole chapter and sent back `outproofread0822.md`. Three things
in it could not be true of one run:

    fourteen lines saying the SAME remark twice, word for word -
        "about 9 characters for a balloon that holds ~5
         about 9 characters for a balloon that holds ~5"

    three sound effects flagged "a sound that starts mid-word", by
        `half_a_sound` - a check DELETED FROM THE APP earlier the same day

    a hundred and sixty-three lines flagged too long, on a chapter where the
        note had been moved to the floor and fires on none of them

`flagged` arrives on a region carrying whatever the last run left there -
`region_from_record` loads it - and every writer below APPENDED. So the field
was not a note on this page, it was a sediment: every remark any run had ever
made about any wording the box had ever held, including remarks made by code
that no longer exists.

Both writers rebuild it now. The reading's own note is not lost with it,
because `ocr.looks_like_garbage` is a pure function of the source text and the
box: asking it again gives the answer it gave at Read text. What goes is every
remark about ENGLISH THAT NO LONGER EXISTS.

And `do_proofread` writes the field unconditionally, for the same reason the
page note is written unconditionally: a run that finds nothing wrong has to be
able to clear what the last one said.
"""
import json

import pytest

from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _r(src="よろしくお願いします", dst="", w=300, h=160, flagged=None):
    r = TextRegion(id=1, bbox=(0, 0, w, h), text_mask=None, bubble_mask=None,
                   bubble_bbox=(0, 0, w, h), kind="bubble", order=0)
    r.src_text, r.dst_text, r.flagged = src, dst, flagged
    return r


def _page(rs):
    p = Page(image=None, source_path="t.png")
    p.regions = list(rs)
    return p


def _reply(monkeypatch, key, text):
    from mangatl import translate as TT
    monkeypatch.setattr(TT, "make_client",
                        lambda **kw: (object(), "test-model", "openai"))
    monkeypatch.setattr(
        TT, "_ask",
        lambda *a, **k: json.dumps(
            {"regions": [{"id": 1, key: text}]}
            if key == "translation" else
            {"regions": [{"id": 1, "text": text}], "page_notes": ""}))


# ----------------------------------------------------------- the translator

def test_last_runs_remark_does_not_come_back_with_this_one(monkeypatch):
    """The doubled line, straight off lee's report."""
    _reply(monkeypatch, "translation", "x" * 400)
    r = _r(w=90, h=60, flagged="about 400 characters for a balloon that holds ~5")
    T.translate_page(_page([r]), ctx=T.SeriesContext())
    assert r.flagged.count("holds ~") == 1, r.flagged


def test_a_remark_from_a_check_that_no_longer_exists_is_dropped(monkeypatch):
    """`half_a_sound` was deleted in the morning and was still on three of his
    sound effects in the evening. Nothing in the app could ever have taken it
    off, because nothing ever took anything off."""
    _reply(monkeypatch, "translation", "Hello.")
    r = _r(flagged="a sound that starts mid-word: 'lence...'")
    T.translate_page(_page([r]), ctx=T.SeriesContext())
    assert "mid-word" not in (r.flagged or "")


def test_a_line_that_is_fine_now_stops_being_flagged(monkeypatch):
    """The whole point. A box flagged too long, retranslated into something
    that fits, used to keep the warning for ever.

    (The stub reply carries no confidence, so `translate_page` adds its own
    remark about that - which is this run's, and is the thing being asked for.)
    """
    _reply(monkeypatch, "translation", "Hello.")
    r = _r(flagged="about 400 characters for a balloon that holds ~5")
    T.translate_page(_page([r]), ctx=T.SeriesContext())
    assert "holds ~" not in (r.flagged or "")


def test_this_runs_remark_is_still_made(monkeypatch):
    """Rebuilding is not the same as saying nothing."""
    _reply(monkeypatch, "translation", "x" * 400)
    r = _r(w=90, h=60)
    T.translate_page(_page([r]), ctx=T.SeriesContext())
    assert "holds ~" in (r.flagged or "")


def test_the_readings_own_note_survives_the_rebuild(monkeypatch):
    """It is about the JAPANESE, so a new English line does not settle it -
    and it is re-derived rather than carried, so it cannot go stale either."""
    from mangatl.ocr import looks_like_garbage
    _reply(monkeypatch, "translation", "Hello.")
    r = _r(src="！！！")
    assert looks_like_garbage(r.src_text, r), "the fixture reads clean"
    T.translate_page(_page([r]), ctx=T.SeriesContext())
    assert "ocr:" in (r.flagged or ""), r.flagged


def test_and_it_is_not_doubled_either(monkeypatch):
    _reply(monkeypatch, "translation", "Hello.")
    r = _r(src="！！！", flagged="ocr: punctuation only")
    T.translate_page(_page([r]), ctx=T.SeriesContext())
    assert (r.flagged or "").count("ocr:") == 1, r.flagged


# ---------------------------------------------------------- the proofreader

def test_the_proofreader_rebuilds_it_too(monkeypatch):
    _reply(monkeypatch, "text", "Hello.")
    r = _r(dst="Hello.", flagged="a sound that starts mid-word: 'lence...'")
    T.proofread_page(_page([r]), ctx=T.SeriesContext())
    assert "mid-word" not in (r.flagged or "")


def test_a_cleared_flag_reaches_the_stored_record(tmp_path, monkeypatch):
    """`do_proofread` used to write the field only when there was something to
    say, so a box could never lose a flag however many times it was read."""
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl import editor
    from mangatl.project import Project

    root = str(tmp_path / "p")
    p = Project(None, root)
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((400, 400, 3), 245, np.uint8))[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [50, 50, 200, 120],
        "src_text": "よろしく", "dst_text": "Nice to meet you.",
        "speaker": "Ada",
        "flagged": "about 400 characters for a balloon that holds ~5"}]
    _reply(monkeypatch, "text", "Nice to meet you.")
    editor._ctx_from_settings(p, "proofread")
    editor.do_proofread(p, 0)
    assert not p.pages[0].regions[0].get("flagged")


# ------------------------------------------------- and which way round -san

def _said(rows):
    """(page, line, record, english) - the shape `_chapter_audit` is handed."""
    return [(pg, ln, {"src_text": src}, en)
            for pg, ln, src, en in rows]


def _audit(rows, keep=True):
    from mangatl import editor
    from mangatl.project import Project

    class P:
        ctx = T.SeriesContext(honorifics=keep)
        pages = []
        settings = {}
    return "\n".join(editor._chapter_audit(P(), _said(rows)))


def test_a_name_that_lost_its_honorific_is_the_anomaly_when_they_are_kept():
    """lee's three, on a chapter with `keep_honorifics` on. The report used to
    name the EIGHT lines that kept one and say nothing about these."""
    got = _audit([(1, 7, "グロウさん!", "Mr. Glow!"),
                  (6, 9, "…レオノーラ様", "...Lady Leonora."),
                  (4, 8, "グロウさん\n傷付いて", "Sometimes Glow-san looks...")])
    assert "A name that lost its honorific" in got
    assert "p1 l7" in got and "p6 l9" in got
    assert "p4 l8" not in got, "that one kept it"


def test_the_ones_that_kept_it_are_not_called_out():
    got = _audit([(4, 8, "グロウさん", "Glow-san!"),
                  (8, 1, "ローファンさん", "Rofan-san")])
    assert "honorific" not in got


def test_a_word_that_is_not_a_name_is_not_drift():
    """`お姉様` is Sister and `店主さん` is the shopkeeper - the English there
    is a word, not a name, and losing the suffix is a rendering rather than a
    mistake. Only a KATAKANA name is asked about."""
    got = _audit([(7, 4, "…何を考えているの お姉様が", "...What am I thinking? Sister..."),
                  (14, 5, "まーまー 店主", "Now, now, shopkeeper.")])
    assert "honorific" not in got


def test_the_old_question_is_still_asked_of_a_chapter_that_drops_them():
    """Turned off, the anomaly is the other way round again."""
    rows = [(1, 1, "グロウ", "Glow-san!")] + [
        (2, n, "テスト", "Nothing here.") for n in range(60)]
    got = _audit(rows, keep=False)
    assert "left on a name" in got and "p1 l1" in got


def test_and_not_of_a_chapter_that_keeps_them():
    rows = [(1, 1, "グロウ", "Glow-san!")] + [
        (2, n, "テスト", "Nothing here.") for n in range(60)]
    assert "left on a name" not in _audit(rows, keep=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
