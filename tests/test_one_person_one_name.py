"""What the chapter has already called things, so it keeps calling them that.

Measured on a translated chapter of lee's, all in one run:

    the grandfather   "Jinwoo's Grandfather" on page 46,
                      "Osung Group Chairman" on page 57, null on 55-56
    침식              "erosion" 5 times, "Erosion" 12
    마정석            "mana crystals" once, "magic stones" once
    마력 장벽         "mana barrier" once, bare "barrier" twice

Four labels for two people, and three terms that are each two terms. The
character sheet and the glossary travel with every request already and did not
stop any of it, for a reason each: a one-off speaker never joins the sheet BY
DESIGN — a guard, a bystander, the narration voice — and a term nobody thought
to propose never joins the glossary at all.

`already_said` is the rest of it: what the run has SAID, whether or not it was
written down. It is per-run and thrown away with the run, which is the right
lifetime — it is about one chapter agreeing with itself, and the sheet and the
glossary are what carry across chapters.
"""
from mangatl import translate as T
from mangatl.models import Page, TextRegion


def _r(rid, src, dst=None, who=None):
    r = TextRegion(id=rid, bbox=(0, rid * 40, 30, 30), text_mask=None,
                   bubble_mask=None, bubble_bbox=(0, rid * 40, 30, 30),
                   kind="bubble")
    r.src_text, r.dst_text, r.speaker, r.order = src, dst, who, rid
    return r


def _page(rs):
    p = Page(image=None, source_path="t.png")
    p.regions = rs
    return p


def _ctx():
    c = T.SeriesContext()
    c.medium, c.source, c.target = "manhwa", "Korean", "en"
    return c


# ------------------------------------------------------------ the remembering

def test_a_page_remembers_who_spoke_on_it():
    c = _ctx()
    T.remember_said(c, _page([_r(0, "가", "Hi", "Kim Jinwoo"),
                              _r(1, "나", "Yes", "Turiss")]))
    assert c.speakers_seen == ["Kim Jinwoo", "Turiss"]



def test_a_speaker_is_not_listed_twice():
    c = _ctx()
    pg = _page([_r(0, "가", "Hi", "Kim Jinwoo"), _r(1, "나", "Ah", "kim jinwoo")])
    T.remember_said(c, pg)
    T.remember_said(c, pg)
    assert c.speakers_seen == ["Kim Jinwoo"]


def test_an_unattributed_line_adds_nothing():
    c = _ctx()
    T.remember_said(c, _page([_r(0, "가", "Hi", None), _r(1, "나", "Ah", "")]))
    assert c.speakers_seen == []


def test_a_term_is_remembered_the_first_way_it_was_rendered():
    """First wins, the same rule the glossary uses. A second rendering is the
    drift this is here to stop, so it must not overwrite the first."""
    c = _ctx()
    T.remember_said(c, _page([]), {"침식": "Erosion (the blight)"})
    T.remember_said(c, _page([]), {"침식": "erosion"})
    assert c.terms_seen == {"침식": "Erosion (the blight)"}


# ------------------------------------------------------------- what is sent

def test_it_travels_with_the_page():
    c = _ctx()
    c.speakers_seen = ["Kim Jinwoo", "Osung Group Chairman"]
    c.terms_seen = {"침식": "Erosion"}
    got = T.build_payload(_page([_r(0, "응?")]), c)
    assert got["already_said"]["speakers"] == ["Kim Jinwoo",
                                               "Osung Group Chairman"]
    assert got["already_said"]["terms"]["침식"] == "Erosion"


def test_a_name_is_sent_once_however_it_got_into_the_list():
    """`remember_said` dedupes as it goes, and this dedupes again on the way
    out. Not belt and braces: the list is a plain field on the context, and
    the run is not the only thing that can put something in it."""
    c = _ctx()
    c.speakers_seen = ["Kim Jinwoo", "kim jinwoo", "KIM JINWOO", "Turiss"]
    assert T.build_payload(_page([_r(0, "응?")]), c)["already_said"]["speakers"] \
        == ["Kim Jinwoo", "Turiss"]


def test_the_first_page_of_a_chapter_sends_nothing():
    """An empty key is a key the model has to read and decide is empty, on
    every page of every run, inside the part of the request nothing caches."""
    assert "already_said" not in T.build_payload(_page([_r(0, "응?")]), _ctx())


def test_it_sits_below_the_cached_part_of_the_request():
    """It changes page to page. Up in the prefix it would break the cache on
    every page — see the note on key order in `_base_payload`."""
    c = _ctx()
    c.speakers_seen = ["Kim Jinwoo"]
    keys = list(T.build_payload(_page([_r(0, "응?")]), c))
    assert keys.index("already_said") > keys.index("previous_page_tail") - 1
    assert keys.index("already_said") < keys.index("regions")


def test_a_long_chapter_does_not_send_the_whole_cast_for_ever():
    c = _ctx()
    c.speakers_seen = ["Person %d" % i for i in range(80)]
    assert len(T.build_payload(_page([_r(0, "응?")]), c)["already_said"]
               ["speakers"]) == 40


# --------------------------------------------------------- what it is told

def test_the_prompt_says_one_person_one_name():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "already_said" in sys
    assert "One person, one name" in sys
    assert "A speaker already labelled gets that label again" in sys


def test_and_one_rendering_per_term():
    sys = T.build_system("manhwa", "en", "Korean")
    assert "A source term already rendered is rendered the same way" in sys
    assert "capitals and" in sys


def test_the_translator_writes_it_down_as_it_goes():
    """A page that is translated and not remembered is a page the next one
    cannot agree with."""
    import inspect
    src = inspect.getsource(T.translate_page)
    assert "remember_said(ctx, page" in src
