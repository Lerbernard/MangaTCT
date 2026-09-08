# -*- coding: utf-8 -*-
"""One drawn sound, one English word — and one word for one sound.

lee, after a sound effect came back wrong: *"so can you don something about
getting the ai to cobsitenly get the translation better"*.

**Consistently** is the word, and the app was making it impossible.
`do_translate` runs ONE PAGE PER REQUEST, and `run_context` hands a
full-chapter run nothing at all, on this reasoning:

> A full-chapter run gets nothing. Every page is being translated, so there is
> nothing to be consistent WITH that is not already in the run.

That holds if the run is one request. It is twenty-three. Page 22 is answered
without knowing what page 21 decided, so there is nothing to be consistent
with and nothing making it consistent.

Measured over all fifty sound effects in lee's chapter:

    same Japanese, two Englishes
        スッ   ->  SHH (021)  and  SWISH (022)
        ぱっ   ->  PERK (010) and  BEAM (022)

    different Japanese, one English
        SPLASH  <-  ザブン / ザボンッ / バチャ x3
        SWISH   <-  サラッ / スッ
        GLANCE  <-  キョロ / チラッ
        GLUB    <-  ゴボ / ザボ

Sixteen of the fifty are caught in one or the other. `ザブン` is a body going
under and `バチャ` is a splatter; the artist drew two sounds and both came out
SPLASH.

## What carries it now

`already_said` was already the mechanism - what this chapter has called
people and things, page to page, sitting deliberately BELOW the cached part of
the payload so it can grow during a run without costing the prefix. Sounds
were the fourth gap in it and the widest: a sound effect has no speaker, is
never proposed as a term and never reaches the glossary, so what a chapter
decided `スッ` was had no record anywhere at all.

About 150 tokens on a chapter with fifty of them.

## And a shape rule

The kana say the duration and the stop, and the English has to have the same
shape. A trailing small ッ cuts the sound off; ー holds it; … lets it fade.
`セッ` is clipped and came back `SHFF`, which is a sustained hiss - the
opposite of what the page drew.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import translate as T                          # noqa: E402
from mangatl.models import Page, TextRegion                 # noqa: E402


def _r(rid, kind, src, dst):
    return TextRegion(id=rid, bbox=[0, 0, 10, 10], kind=kind,
                      src_text=src, dst_text=dst)


def _page(*regions):
    return Page(image=None, regions=list(regions))


# --------------------------------------------------------------- the key

def test_a_sound_drawn_down_a_column_is_one_sound():
    """It arrives with the newlines the column was drawn in."""
    assert T.sound_key("ザ\nブ\nン") == "ザブン"


def test_two_encodings_of_one_sound():
    assert T.sound_key("ﾄﾞﾝ") == T.sound_key("ドン")


def test_katakana_is_not_folded_into_hiragana():
    """Borrowed whole from `editor._fold_kana`, which learnt it the hard way:
    キョロ and きょろ are two spellings somebody may have chosen."""
    assert T.sound_key("キョロ") != T.sound_key("きょろ")


def test_nothing_is_not_a_sound():
    assert T.sound_key("") == ""
    assert T.sound_key("   \n ") == ""


# ------------------------------------------------------- what is remembered

def test_a_sound_is_remembered_for_the_pages_after_it():
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "sfx", "スッ", "SHH")))
    assert T.already_said(ctx)["sounds"] == {"スッ": "SHH"}


def test_the_first_answer_wins():
    """The second one IS the drift. It is a floor and not a ceiling: a sound
    given a new word on page 22 is the thing this exists to stop, and it can
    only stop it by having gone first."""
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "sfx", "スッ", "SHH")))
    T.remember_said(ctx, _page(_r(2, "sfx_big", "スッ", "SWISH")))
    assert T.already_said(ctx)["sounds"]["スッ"] == "SHH"


def test_the_column_and_the_line_are_one_entry():
    """lee's page 021 draws スッ down a column and 022 draws it across. Two
    spellings of one sound would be two entries and no consistency at all."""
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "sfx", "ス\nッ", "SHH")))
    T.remember_said(ctx, _page(_r(2, "sfx", "スッ", "SWISH")))
    assert T.already_said(ctx)["sounds"] == {"スッ": "SHH"}


def test_only_sounds():
    """A bubble is not a sound effect, and the speech on a page has its own
    three lists already."""
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "bubble", "こんにちは", "Hello"),
                               _r(2, "narration", "その日", "That day"),
                               _r(3, "sfx", "ドン", "BOOM")))
    assert T.already_said(ctx)["sounds"] == {"ドン": "BOOM"}


def test_a_sound_with_no_english_yet_is_not_an_entry():
    """An untranslated box has nothing to be consistent with."""
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "sfx", "ドン", "")))
    assert "sounds" not in T.already_said(ctx)


def test_a_chapter_with_no_sounds_sends_no_list():
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "bubble", "こんにちは", "Hello")))
    assert "sounds" not in T.already_said(ctx)


# --------------------------------------------------------- where it travels

def test_the_sounds_ride_below_the_cached_prefix():
    """`already_said` changes from page to page, so it sits under the fixed
    part of the payload - putting it above would end the cache prefix there
    and throw away every fixed byte after it. The sounds inherit that place by
    being inside it, and this says so rather than trusting it."""
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "sfx", "ドン", "BOOM")))
    payload = T._base_payload(_page(_r(2, "bubble", "はい", "Yes")), ctx)
    keys = list(payload)
    assert "already_said" in keys
    assert payload["already_said"]["sounds"] == {"ドン": "BOOM"}
    # ...after everything that is fixed for a run, and before the regions.
    assert keys.index("already_said") > keys.index("target_language")
    assert keys.index("already_said") < keys.index("regions")


def test_a_full_chapter_run_still_carries_them():
    """The case that was broken. `run_context` gives a full-chapter run no
    chapter context at all - and it is right to, the pages are all in the run
    - but the sounds are not chapter context, they are decisions, and they
    have to travel whether the story lines do or not."""
    ctx = T.SeriesContext()
    T.remember_said(ctx, _page(_r(1, "sfx", "ドン", "BOOM")))
    payload = T._base_payload(_page(_r(2, "sfx", "ドン", "")), ctx, chapter=None)
    assert "chapter_context" not in payload
    assert payload["already_said"]["sounds"] == {"ドン": "BOOM"}


# ------------------------------------------------------------- the rules

def test_the_prompt_teaches_the_shape_of_a_sound():
    """The kana carry duration and stop, and it is the one part of a sound
    effect the model is not guessing at."""
    s = T.build_system()
    for want in ("っ", "ー", "…"):
        assert want in s, want
    low = s.lower()
    assert "cuts the sound off" in low or "cut off" in low, \
        "the prompt says nothing about the small tsu"


def test_the_prompt_asks_for_one_word_per_sound_both_ways():
    s = T.build_system()
    assert "already_said.sounds" in s, \
        "the prompt never tells the model the list exists"
    low = s.lower()
    assert "not already spoken for" in low, "one word may serve two sounds"
    assert "ザブン" in s and "バチャ" in s, \
        "the example that shows what flattening costs is gone"


# ------------------------------------------------- and the chapter on disk

def test_a_run_starts_from_what_the_chapter_already_says(tmp_path):
    """`sounds_seen` lives in memory, like the two lists beside it - and
    unlike those it has nowhere else to go: a term has the glossary, a name
    has the character sheet, a sound has never been written down anywhere.
    So the chapter itself is the record, and it costs nothing to read."""
    from mangatl import editor
    from mangatl.project import Project

    root = str(tmp_path / "out")
    p = Project(None, root)
    img = np.full((80, 80, 3), 255, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [
        {"id": 1, "kind": "sfx", "order": 0, "bbox": [10, 10, 40, 20],
         "src_text": "ス\nッ", "dst_text": "SHH"},
        {"id": 2, "kind": "bubble", "order": 1, "bbox": [10, 40, 40, 20],
         "src_text": "はい", "dst_text": "Yes"},
    ]
    assert editor.seed_sounds(p) == 1
    assert T.already_said(p.ctx)["sounds"] == {"スッ": "SHH"}
    # ...and it does not overwrite what a live run has already settled.
    p.ctx.sounds_seen["スッ"] = "SWISH"
    editor.seed_sounds(p)
    assert p.ctx.sounds_seen["スッ"] == "SWISH"


def test_a_sub_type_is_answered_by_the_projects_own_list(tmp_path):
    """`sfx_big` is one of lee's own. Asked with the project's list rather
    than the module global, so the answer cannot depend on whether
    `kinds.use()` has run - an unregistered sub-type reads as a bubble."""
    from mangatl import editor, kinds as K
    from mangatl.project import Project

    root = str(tmp_path / "out")
    p = Project(None, root)
    img = np.full((80, 80, 3), 255, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.settings["custom_kinds"] = [{"key": "sfx_big", "family": "sfx"}]
    p.pages[0].regions = [
        {"id": 1, "kind": "sfx_big", "order": 0, "bbox": [10, 10, 40, 20],
         "src_text": "ザァァ", "dst_text": "ROAA"}]
    was = K.known()
    try:
        K.use([])                       # ...the registry deliberately empty
        assert editor.seed_sounds(p) == 1
        assert p.ctx.sounds_seen == {"ザァァ": "ROAA"}
    finally:
        K.use(was)


def test_the_run_seeds_before_it_starts():
    """It has to happen where the run is set up, not inside the per-page work
    - by then page one has already been answered."""
    import inspect

    from mangatl import editor
    src = inspect.getsource(editor.Handler)
    at = src.index('path == "/api/translate_all"')
    block = src[at:at + 1200]
    assert "seed_sounds(p)" in block, \
        "a translate run no longer starts from what the chapter says"
