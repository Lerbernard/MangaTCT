"""A box with no writing in it, only marks.

lee: *"i want you ta add a button in the setting setting to auto emove boxes
taht are only symbol like ! or ....... etc make it on by defaut and after read
text happens if a box is only symboed with no text it shodu auto delete"*.

The detector cannot answer this. Ink is ink, and a box drawn round a lone `!`
is a box drawn round something that really is printed on the page — there is
nothing in the pixels that says it is not a word. Only the READER can say
there is no word in it, so the first moment the question can be asked at all
is when Read text comes back, which is exactly where lee put it.

Three separate things are held here and they fail in different ways:

* `ocr.only_symbols` — what counts as writing. Asked of Unicode rather than of
  a list of characters somebody typed out.
* `editor.symbol_only_boxes` — which boxes are the app's to throw away. Three
  kinds never are, however they read.
* `editor.do_ocr` — that the drop happens, that it happens BEFORE the sections
  are linked, and that the page is renumbered afterwards.
"""
import json
import os
import shutil
import types

import numpy as np
import pytest

from mangatl import editor, ocr as O
from mangatl.models import Page, TextRegion
from mangatl.project import Project
from scratch import scratch
from where import PKG

ROOT = scratch("_tmp_marks")


# --------------------------------------------------------- what is writing

MARKS = [
    "!", "!!!", "?!", "...", "......", "…", "……", "。", "、",
    "♡", "♥", "★", "☆", "※", "—", "——", "~", "〜",
    "ーー",                 # a stretched sound and nothing else
    "「」", "（）", "《》",   # empty brackets: the reader saw the shape only
    "・・・", "＋", "→", "🡒", "!?!?", " ! ", "!\n!",
]

WRITING = [
    "ㅋㅋㅋ",               # Korean laughter IS what he is saying
    "3", "12", "1994",     # a number on a sign is something to read
    "A", "a!", "네!", "え？", "ラーメン", "…と", "3년 전",
    "옹성", "Привет", "!!!x",
]


@pytest.mark.parametrize("t", MARKS)
def test_a_box_of_marks_has_no_writing_in_it(t):
    assert O.only_symbols(t) is True, t


@pytest.mark.parametrize("t", WRITING)
def test_one_letter_or_one_digit_is_enough_to_keep_it(t):
    assert O.only_symbols(t) is False, t


def test_nothing_read_at_all_is_not_the_same_as_marks():
    """The one outcome this must never have is deleting a box because the
    reader had a bad turn. An empty read is a different fault with its own
    name — `ocr: no text read` — and it is not this one."""
    for t in ("", "   ", "\n", "\t\n ", None):
        assert O.only_symbols(t) is False, repr(t)


def test_the_answer_is_unicode_and_not_a_list_somebody_typed():
    """The point of the rewrite, stated as a test rather than as a comment.
    The old hand-written class had `…` and `・` in it and had never heard of
    `♡`, `★`, `※` or a full-width bracket — the marks it missed were simply
    the ones whoever wrote it did not happen to think of."""
    old = "。、,.!?！？…・-—ー~〜"
    fresh = [m for m in MARKS if not all(ch in old or ch.isspace() for ch in m)]
    assert fresh, "the fixture for this test has stopped being true"
    for t in fresh:
        assert O.only_symbols(t) is True, t
    # ...and every script gets the same answer without being listed either.
    for t in ("Ω", "ب", "อ", "क", "ㄱ", "ᚠ"):
        assert O.only_symbols(t) is False, t


def test_a_modifier_alone_is_a_sound_and_not_a_word():
    """Unicode calls `ー` a letter (`Lm`) and inside a word it is one. A box
    holding nothing BUT them is a stretched vowel drawn large, which is the
    thing being removed."""
    assert O.only_symbols("ーー") is True
    assert O.only_symbols("ラーメン") is False, "it is a letter inside a word"


# ------------------------------------------- ...and whose box it is to drop

def _reg(rid, text, **kw):
    r = TextRegion(id=rid, bbox=(0, rid * 20, 10, 10), text_mask=None,
                   bubble_mask=None, bubble_bbox=(0, rid * 20, 10, 10),
                   kind="bubble")
    r.src_text = text
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def test_the_marks_boxes_and_only_those():
    regs = [_reg(0, "안녕"), _reg(1, "!!"), _reg(2, ""), _reg(3, "……")]
    assert [r.id for r in editor.symbol_only_boxes(regs)] == [1, 3]


def test_a_box_somebody_typed_themselves_is_never_dropped():
    """There was never anything under it to read, so whatever the reader made
    of the bare artwork under it says nothing about the box at all."""
    regs = [_reg(0, "!!", own_text=True), _reg(1, "!!")]
    assert [r.id for r in editor.symbol_only_boxes(regs)] == [1]


def test_a_locked_box_is_never_dropped():
    """Locked is the word for *I have corrected this, leave it alone*, and
    deleting it is the loudest possible way of not leaving it alone."""
    regs = [_reg(0, "!!", locked=True), _reg(1, "!!")]
    assert [r.id for r in editor.symbol_only_boxes(regs)] == [1]


def test_a_box_that_already_has_a_translation_is_never_dropped():
    """Re-reading a page that has been through the translator must not take
    the English with it. The reader having a worse turn this time than last is
    not a reason to lose work."""
    regs = [_reg(0, "!!", dst_text="Hey!"), _reg(1, "!!", dst_text="   "),
            _reg(2, "!!")]
    assert [r.id for r in editor.symbol_only_boxes(regs)] == [1, 2], \
        "an empty translation is not a translation"


# ------------------------------------------------- ...through the read step

def _drive(texts, settings=None, monkeypatch=None, regs=None):
    """Run the real `editor.do_ocr` over a stub project.

    A stub rather than a project on disk: what is under test is which boxes
    survive the step, and a real project would drag a page file, a model and a
    network call in with it. What the step really did is read back off the
    page it committed.
    """
    from mangatl import translate as T
    seen = {}
    monkeypatch.setattr(O, "page_label_tiles", lambda *a, **k: [])
    monkeypatch.setattr(T, "read_page_ocr", lambda *a, **k: dict(texts))
    monkeypatch.setattr(T, "link_sections",
                        lambda rs: seen.setdefault("linked",
                                                   [r.id for r in rs]))
    monkeypatch.setattr(editor, "reorder",
                        lambda p, i, **k: seen.setdefault("reordered", i))
    regs = regs if regs is not None else [_reg(k, "") for k in sorted(texts)]
    page = Page(image=np.full((80, 40, 3), 245, np.uint8), regions=regs)
    ctx = types.SimpleNamespace(medium="manhwa", source="", target="en",
                                safety="", synopsis="", characters="",
                                glossary="", story="", notes="")
    p = types.SimpleNamespace(
        settings=dict(settings or {}), ctx=ctx, job={},
        materialize=lambda i: page,
        commit=lambda i, pg: seen.setdefault("committed",
                                             [r.id for r in pg.regions]))
    editor.do_ocr(p, 0)
    seen["left"] = [r.id for r in page.regions]
    return seen


TEXTS = {0: "안녕하세요", 1: "!!", 2: "……", 3: "3년 전"}


def test_the_marks_boxes_are_gone_when_the_read_finishes(monkeypatch):
    got = _drive(TEXTS, {"drop_symbol_only": True}, monkeypatch)
    assert got["left"] == [0, 3]
    assert got["committed"] == [0, 3], "the page written back still had them"


def test_and_it_is_on_for_a_project_that_has_never_heard_of_it(monkeypatch):
    """lee: *"make it on by defaut"*. A project.json written before the
    setting existed has no key at all, and `.get(k, True)` is not what makes
    that work — `.get(k) is not False` is."""
    assert _drive(TEXTS, {}, monkeypatch)["left"] == [0, 3]


def test_switched_off_the_box_stays_and_says_why(monkeypatch):
    """Off is not "the app stops noticing". The box is still flagged, so a
    `!!` never slides into the translation unremarked."""
    regs = [_reg(k, "") for k in sorted(TEXTS)]
    got = _drive(TEXTS, {"drop_symbol_only": False}, monkeypatch, regs=regs)
    assert got["left"] == [0, 1, 2, 3]
    assert regs[1].flagged == "ocr: punctuation only"
    assert regs[0].flagged is None


def test_the_page_is_renumbered_after_a_box_goes(monkeypatch):
    """The same call the delete button makes. Without it the reading order
    keeps the gap the dropped box left, and the cached overlay still has its
    rectangle drawn on it."""
    assert _drive(TEXTS, {}, monkeypatch).get("reordered") == 0


def test_and_not_when_nothing_went(monkeypatch):
    """Renumbering drops the cached page, and rebuilding that page is the
    seconds-long pause on the next keystroke. A read that changed no box must
    not pay it."""
    got = _drive({0: "안녕", 1: "3년 전"}, {}, monkeypatch)
    assert "reordered" not in got, got


def test_the_box_goes_before_the_sections_are_linked(monkeypatch):
    """`!` under a line of dialogue is exactly the shape that reads on as the
    second half of a sentence. Linking it and then deleting it leaves the
    first half pointing at a box that is not there."""
    got = _drive(TEXTS, {}, monkeypatch)
    assert got["linked"] == [0, 3], got["linked"]
    # ...and the order the two run in is pinned in the source as well, because
    # the test above passes just as well if a future edit moves the link up
    # and the fixture happens to have nothing to link.
    import inspect
    src = inspect.getsource(editor.do_ocr)
    assert src.index("symbol_only_boxes(regs)") < src.index("link_sections("), \
        "the drop has to happen first"


def test_a_read_that_failed_outright_deletes_nothing(monkeypatch):
    """The reader threw. Every box comes back unread, and unread is not the
    same as read-and-empty — deleting the page's boxes because the network
    fell over is the worst version of this feature there is."""
    from mangatl import translate as T

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(O, "page_label_tiles", lambda *a, **k: [])
    monkeypatch.setattr(T, "read_page_ocr", boom)
    regs = [_reg(0, ""), _reg(1, "")]
    page = Page(image=np.full((80, 40, 3), 245, np.uint8), regions=regs)
    ctx = types.SimpleNamespace(medium="manhwa", source="", target="en",
                                safety="", synopsis="", characters="",
                                glossary="", story="", notes="")
    p = types.SimpleNamespace(settings={}, ctx=ctx, job={},
                              materialize=lambda i: page,
                              commit=lambda i, pg: None)
    with pytest.raises(RuntimeError):
        editor.do_ocr(p, 0)
    assert [r.id for r in page.regions] == [0, 1]


# ------------------------------------------------------- the switch itself

def test_the_default_is_on_in_a_fresh_project():
    shutil.rmtree(ROOT, ignore_errors=True)
    try:
        assert Project(None, ROOT).settings["drop_symbol_only"] is True
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)


def test_the_screen_has_the_switch():
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert 'id="drop_symbol_only"' in html
    # Ticked in the MARKUP as well as in the settings, so the box does not sit
    # unticked for the moment between the page drawing and the project
    # loading — which is the moment somebody clicks it.
    i = html.index('id="drop_symbol_only"')
    assert "checked" in html[i:i + 120], html[i:i + 120]
    assert "saveSettings()" in html[i:i + 160]


def test_the_switch_is_read_and_saved_like_the_other_default_on_ones():
    """Two behaviours, and a plain `$('x').checked` gives neither: read with
    `!==false`, so an old project.json is not switched off by `!!undefined`;
    and omitted from the save when the box does not exist, so saving from a
    screen that has not been built yet does not write an off nobody chose."""
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "const DEFAULT_ON = ['drop_symbol_only']" in js
    assert "const ON_SWITCHES = [...STORY_SWITCHES, ...DEFAULT_ON]" in js
    # Both places read the combined list, not the story one.
    assert "ON_SWITCHES.forEach" in js
    assert "...ON_SWITCHES.reduce" in js
    assert "STORY_SWITCHES.forEach" not in js
    assert "...STORY_SWITCHES.reduce" not in js
    # ...and it is NOT sent as a bare `.checked`, which is the trap.
    assert "drop_symbol_only:" not in js


def test_the_setting_survives_a_save_and_a_reload():
    shutil.rmtree(ROOT, ignore_errors=True)
    try:
        p = Project(None, ROOT)
        p.settings["drop_symbol_only"] = False
        p.save()
        with open(p.state_path, encoding="utf-8") as fh:
            assert json.load(fh)["settings"]["drop_symbol_only"] is False
        again = Project(None, ROOT)
        assert again.settings["drop_symbol_only"] is False, \
            "the default was written back over somebody's choice"
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)


# ------------------------------------------- one definition, two uses of it

def test_the_flag_and_the_drop_ask_the_same_question():
    """`looks_like_garbage` FLAGS a marks-only read and the switch DELETES the
    box. Two actions, one definition — a hand-written character class beside a
    Unicode test is two answers to "is there writing in this"."""
    import inspect
    src = inspect.getsource(O.looks_like_garbage)
    assert "only_symbols(" in src
    assert "。、" not in src, "the hand-written class is back"
    r = _reg(0, "")
    assert O.looks_like_garbage("….", r) == "ocr: punctuation only"
    assert O.looks_like_garbage("♡♡", r) == "ocr: punctuation only"
    assert O.looks_like_garbage("안녕", r) is None
