"""One man, one spelling — and one sheet for a person.

lee, reading the finished English of a 46-page chapter: *"and try to fix teh
cause of every issue"*. Two of the issues were about names, and both had the
same shape — a rule the prompt states and nothing anywhere enforces.

**Chrysos and Chryses.** 크리서스 came back "Laszlo Chrysos." on page 41 and
"Count Laszlo Chryses" on page 45. Neither page did anything wrong on its own.
The cause is structural: the glossary is the only place in this app that binds
a SOURCE spelling to an English one, and a person is forbidden from entering it
(so that nobody is listed twice). The character sheet holds "Laszlo", because
that is the speaker label. So the surname was written down nowhere at all, and
page 45 had to invent it a second time.

**Edel Canyon (the canyon location).** The heroine's maiden name, filed as a
place, because 캐니언 reads as the English word. Same shape: *"A person NEVER
goes in glossary_additions"* is in the prompt and was enforced by nothing. The
glossary is what every LATER chapter starts from, so that entry outlives the
chapter that made it.
"""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from mangatl.models import Page, TextRegion
from mangatl.translate import (SeriesContext, already_said, is_a_person,
                               merge_glossary, name_drift, names_in,
                               remember_said, translate_page)


# ------------------------------------------------- what counts as a name

def test_a_capital_that_is_not_starting_a_sentence():
    """The whole rule, and it needs no list of stop words. "Still" and "There"
    are capitals the full stop put there, and any real page uses them in lower
    case somewhere too."""
    assert names_in("Tell me, Laszlo.") == ["Laszlo"]
    assert names_in(["Still, what does that matter?", "He still waited."]) == []
    assert names_in("The gates are open! Seize the traitors!") == []


def test_a_possessive_is_not_a_second_name():
    """Both of these have to be MID-sentence to say anything: a possessive
    sitting at the front of a line is skipped for being a capital the full
    stop put there, and the test then passes whether the apostrophe is folded
    or not."""
    assert names_in("I found Lancaster's men, and then Lancaster.") == \
        ["Lancaster"]
    assert names_in("It was Phara’s will, said Phara.") == ["Phara"]


def test_a_two_letter_capital_is_not_a_name():
    """A regnal number or an initial. Pinning "II" as a name is noise in a
    list somebody reads, and worse than noise in `name_drift`, which would
    then have two-letter tokens to compare everything against."""
    assert names_in("I saw Demarcus II today.") == ["Demarcus"]


def test_a_word_used_in_lower_case_anywhere_is_an_ordinary_word():
    """A capital after a colon or a dash is not a name, and the giveaway is
    that the same word is lower case on another line."""
    assert names_in(["He said: Wait.", "I had to wait."]) == []
    assert names_in(["He said: Wait."]) == ["Wait"], \
        "with nothing to contradict it, it is all this can go on"


def test_the_order_is_the_order_they_appeared():
    """`already_said` is a list somebody may read, and a cap that keeps the
    LAST sixty only means anything if the order is real."""
    assert names_in(["I saw Edel.", "Then Laszlo, then Phara."]) == \
        ["Edel", "Laszlo", "Phara"]


def test_the_whole_of_lees_chapter():
    """Run over all 46 pages of finished English this returns the fourteen
    proper nouns in it and nothing else — and TWO of them are the same man,
    which is the bug."""
    lines = ["Tell me, Laszlo.", "So she's Duchess Edel Lancaster.",
             "Master of Calliope, the empire's largest mercenary guild,",
             "'Edel Canyon,' only daughter of House Canyon.",
             "Almighty and merciful Lord Phara.",
             "Emperor\nDemarcus Tuberin", "Laszlo Chrysos.",
             "I hereby bestow Edel Lancaster upon Count Laszlo Chryses,"]
    got = names_in(lines)
    for want in ("Laszlo", "Edel", "Lancaster", "Calliope", "Canyon", "House",
                 "Phara", "Demarcus", "Tuberin", "Chrysos", "Chryses"):
        assert want in got, want
    assert "The" not in got and "Almighty" not in got


# --------------------------------------------------------- and the drift

def test_the_second_spelling_is_found():
    assert name_drift(["Chrysos"], ["Chryses"]) == [("Chrysos", "Chryses")]


def test_a_name_already_used_is_not_drift_from_itself():
    assert name_drift(["Chrysos"], ["Chrysos"]) == []


def test_two_names_that_are_really_two_people_are_left_alone():
    """Not alike enough, and it is somebody else. Same initial or not."""
    assert name_drift(["Laszlo"], ["Lancaster"]) == []
    assert name_drift(["Edel"], ["Demarcus"]) == []
    assert name_drift(["Phara"], ["Calliope"]) == []


def test_a_different_first_letter_is_taken_as_a_different_person():
    """Adel against Edel is 0.75 alike and this deliberately says nothing.

    It is a real drift that gets missed, and that is the trade being made: a
    transliteration wanders in the MIDDLE and at the END — Chrysos/Chryses,
    Turiss/Turis — while a different opening letter is far more often a
    different character. Precision is what buys this check its keep. A flag
    that fires on every page is a flag nobody reads, and then Chryses gets
    through too.
    """
    assert name_drift(["Edel"], ["Adel"]) == []
    assert name_drift(["Chrysos"], ["Ahrysos"]) == []


def test_it_never_rewrites_anything():
    """Two similar names CAN be two people. A machine that quietly renamed
    somebody's character would be a worse fault than the one it fixes — so
    this reports a pair and the region gets flagged."""
    used, fresh = ["Chrysos"], ["Chryses"]
    name_drift(used, fresh)
    assert used == ["Chrysos"] and fresh == ["Chryses"]


# ------------------------------------------------- the pin, page to page

class _R:
    def __init__(self, rid, dst, src="", speaker=None):
        self.id, self.dst_text, self.src_text = rid, dst, src
        self.speaker, self.flagged = speaker, None


class _P:
    def __init__(self, regs):
        self.regions = regs

    def ordered(self):
        return list(self.regions)


def test_a_name_the_prose_used_is_remembered():
    """Read off the PROSE. Nobody proposes a surname and no speaker label
    carries one — the narration box is where it lives and where it drifted."""
    ctx = SeriesContext()
    remember_said(ctx, _P([_R(0, "Laszlo Chrysos.")]))
    assert ctx.names_seen == ["Chrysos"], ctx.names_seen


def test_and_travels_to_the_next_page():
    ctx = SeriesContext()
    remember_said(ctx, _P([_R(0, "Master of Calliope, run by Laszlo Chrysos.")]))
    said = already_said(ctx)
    assert "Chrysos" in said["names"] and "Calliope" in said["names"]


def test_the_pin_is_not_the_speaker_list_under_another_name():
    """They answer different questions and the chapter needs both: a speaker
    label is what a BOX is tagged with, a name is what the sentence said."""
    ctx = SeriesContext()
    remember_said(ctx, _P([_R(0, "I am short on maids.", speaker="Laszlo")]))
    said = already_said(ctx)
    assert said.get("speakers") == ["Laszlo"]
    assert "names" not in said, "nothing in the prose was a name"


def test_a_name_is_remembered_once_however_often_it_is_used():
    ctx = SeriesContext()
    for _ in range(3):
        remember_said(ctx, _P([_R(0, "Tell me, Laszlo.")]))
    assert ctx.names_seen == ["Laszlo"]


def test_the_cap_keeps_the_names_about_to_come_round_again():
    """A chapter long enough to overrun the cap has moved on to a different
    cast, so it is the LAST sixty that are worth sending, not the first."""
    ctx = SeriesContext()
    ctx.names_seen = ["N%d" % i for i in range(100)]
    got = already_said(ctx)["names"]
    assert len(got) == 60 and got[-1] == "N99" and got[0] == "N40"


def test_the_prompt_tells_the_model_what_the_list_is_for():
    """A list in the payload nobody explained is a list that gets ignored.
    The system prompt has to name it and say the rule."""
    from mangatl.translate import SYSTEM_TEMPLATE as SP
    assert "`names`" in SP
    assert "near-miss" in SP
    # ...and the payload really carries the key the prompt names.
    ctx = SeriesContext()
    remember_said(ctx, _P([_R(0, "Tell me, Laszlo.")]))
    assert "names" in already_said(ctx)


# ------------------------------------- a person does not go in the glossary

CAST = {"Edel Lancaster": "she/her - duchess",
        "Demarcus Tuberin": "he/him - the emperor",
        "Laszlo": "he/him - a count",
        "Phara": "they/them - a deity"}


def test_the_heroines_maiden_name_is_refused():
    sheet = {}
    refused = merge_glossary(
        sheet, {"이델 캐니언": "Edel Canyon (the canyon location)"}, CAST)
    assert sheet == {}, sheet
    assert refused and "Edel Lancaster" in refused[0]
    assert "character sheet" in refused[0], "it has to say where it belongs"


def test_the_ducal_house_beside_it_is_not():
    """The entry that must survive, and it is on lee's own sheet one row
    away: a house shares a SURNAME with a character. Sharing a surname is
    what a house does — it is the GIVEN name that says this is the person
    again under another surname."""
    sheet = {}
    assert merge_glossary(
        sheet, {"랭카스터": "Lancaster (the ducal house and family name)"},
        CAST) == []
    assert sheet == {"랭카스터": "Lancaster (the ducal house and family name)"}
    # ...and the two-word version of the same thing, which is the one that
    # actually reaches the rule: a keep, a gate, a road named after the house.
    # Sharing a SURNAME is what those do. Only the GIVEN name says this is
    # the person again under a different surname.
    assert is_a_person("Lancaster Keep", CAST) == ""
    assert is_a_person("Tuberin Gate", CAST) == ""


@pytest.mark.parametrize("rendering", [
    "Lancaster",                       # one word
    "Edel Canyon Bridge",              # three
    "Phara's Temple",                  # a possessive: a place OF a person
    "Hall of Mirrors",                 # a lower-case word in it
    "Calliope",                        # nobody's name at all
    "Demarcus Tuberin",                # the sheet's own name, unchanged
    # ...and the three that only the SHAPE guard saves, because each of them
    # really does open with a character's given name. A place described with
    # a common noun is a place: "Edel canyon" is the ravine, "Edel Canyon" is
    # the woman, and the capital is the whole difference between them.
    "Edel canyon",                     # lower-case second word
    "Edel Canyon's",                   # a possessive
    "Edel 2",                          # not letters
])
def test_what_the_rule_must_not_catch(rendering):
    assert is_a_person(rendering, CAST) == "", rendering


def test_what_it_catches():
    assert is_a_person("Edel Canyon", CAST) == "Edel Lancaster"
    assert is_a_person("Laszlo Chrysos", CAST) == "Laszlo"


def test_with_no_character_sheet_nothing_is_refused():
    """Story switched off, or a first page with an empty sheet. There is
    nothing to be a second listing OF, so there is no rule to apply."""
    sheet = {}
    assert merge_glossary(sheet, {"이델 캐니언": "Edel Canyon (a place)"},
                          None) == []
    assert sheet


# ------------------------------------------- and all of it through the step

def _page(src="라슬로 크리서스."):
    p = Page(image=np.full((100, 100, 3), 255, np.uint8))
    p.regions = [TextRegion(id=0, bbox=(0, 0, 10, 10), src_text=src)]
    return p


def _says(english, **extra):
    body = {"regions": [{"id": 0, "translation": english, "compact": english,
                         "speaker": None, "confidence": 0.9}],
            "page_notes": ""}
    body.update(extra)
    text = json.dumps(body)
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])))


def test_page_45_is_flagged_against_page_41():
    """The whole thing, end to end and in lee's own words. Page 41 settles the
    spelling; page 45 spells it differently and the box says so."""
    ctx = SeriesContext()
    first = _page("라슬로 크리서스.")
    translate_page(first, ctx=ctx, client=_says("Laszlo Chrysos."))
    assert first.regions[0].flagged in (None, ""), first.regions[0].flagged
    assert ctx.names_seen == ["Chrysos"]

    second = _page("라슬로 크리서스 백작에게")
    translate_page(second, ctx=ctx, client=_says("To Count Laszlo Chryses,"))
    said = second.regions[0].flagged or ""
    assert '"Chryses" was "Chrysos"' in said, said


def test_the_same_spelling_twice_is_not_flagged():
    ctx = SeriesContext()
    for _ in range(2):
        pg = _page()
        translate_page(pg, ctx=ctx, client=_says("Laszlo Chrysos."))
        assert not (pg.regions[0].flagged or "").strip(), pg.regions[0].flagged


def test_the_check_does_not_need_the_story_switched_on():
    """This is about one chapter agreeing with ITSELF, not about a sheet
    anybody is keeping — and `already_said` travels either way."""
    ctx = SeriesContext(story=False)
    translate_page(_page(), ctx=ctx, client=_says("Laszlo Chrysos."))
    pg = _page()
    translate_page(pg, ctx=ctx, client=_says("Laszlo Chryses."))
    assert '"Chryses" was "Chrysos"' in (pg.regions[0].flagged or "")


def test_a_name_is_never_a_near_miss_of_itself():
    """The check reads `names_seen` BEFORE this page is folded into it. Read
    after, every name on the page would be compared against its own entry."""
    ctx = SeriesContext()
    pg = _page()
    translate_page(pg, ctx=ctx,
                   client=_says("Laszlo Chrysos met Laszlo Chrysos."))
    assert not (pg.regions[0].flagged or "").strip()


def test_the_person_gate_runs_in_the_real_step():
    ctx = SeriesContext(characters={"Edel Lancaster": "she/her - duchess"})
    pg = _page("이델 캐니언")
    data = translate_page(
        pg, ctx=ctx, client=_says("Edel Canyon.", glossary_additions={
            "이델 캐니언": "Edel Canyon (the canyon location)"}))
    assert ctx.glossary == {}, ctx.glossary
    assert any("character sheet" in r for r in data["glossary_refused"])


def test_the_refusal_is_reported_and_not_silent():
    """A refusal the model never hears about is a refusal it makes again on
    every page. It rides back in the reply beside the ones for a missing
    description."""
    refused = merge_glossary({}, {
        "이델 캐니언": "Edel Canyon (the canyon location)",
        "타렐": "Tarel"}, CAST)
    assert len(refused) == 2
    assert any("no description" in r for r in refused)
    assert any("belongs on the character sheet" in r for r in refused)
