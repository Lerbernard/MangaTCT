"""Four things lee's finished chapter got wrong, and what was done about each.

He sent back `translations 0822.json` - 23 pages, 220 lines of Japanese and
English - with the box sheets and his live `project.json`, and asked whether
there was anything wrong with the reading or the translation. There was.

Two of the four already had a rule in the prompt and were ignored anyway, so
those rules now carry the failure itself: naming the exact confusion beats
naming the category. The other two are new.

    READING     furigana spliced into the word it explains      013
                a small kana written full size                  5 lines
    TRANSLATION a line that trails off in Japanese and stops
                dead in English                                 008

A third was written and then withdrawn: 016's し / ん… coming back "Si..." and
"lence...", which I read as a word cut in half across two unlinked boxes. lee
looked at the page - *"everrything is working as entened the 2 016 and 017 are
not mistakes"* - and it is one hush drawn across two boxes, split exactly where
the drawing splits. The flag and the prompt rule that came out of it are gone.

The measurement that did NOT turn into a rule is worth recording too: 141 of
the 220 lines are longer than their balloon holds at the comfortable type size,
and NONE of them fail at the floor. That is not a translation defect, it is the
bill for `fits_chars` never reaching the downloaded request - fixed the same
day in `test_the_request_you_download_is_the_request.py` - and the cost of it
was small type on two thirds of the page, not text that would not fit.
"""
import pytest

from mangatl.translate import build_ocr_system, build_system, stops_short


# --------------------------------------------------------------- reading

def test_the_furigana_rule_carries_the_page_it_failed_on():
    """`実` with じつ set beside it came back `実じっは…`. The rule against ruby
    was already there; what it lacked was the shape of the mistake."""
    t = build_ocr_system("Japanese")
    assert "実は…" in t and "実じっは…" in t
    assert "SMALLER" in t and "OFF TO THE SIDE" in t


def test_the_small_kana_rule_points_the_way_the_error_goes():
    """Every one of the five went the same direction - the small form written
    full size, never the reverse - so the rule says which way to doubt."""
    t = build_ocr_system("Japanese")
    assert "THE SMALL FORM IS THE ONE THAT GETS MISSED" in t
    for pair in ("タッ", "クッ", "あって", "ぶっ"):
        assert pair in t, pair
    assert "SIZE against the ones around it" in t, \
        "the test is the glyph's size, not whether it makes a word"


def test_the_small_kana_rule_still_names_the_other_marks():
    """It grew out of the dakuten rule and must not have replaced it."""
    t = build_ocr_system("Japanese")
    assert "が vs か" in t and "ば vs は" in t
    assert "っ" in t and "ッ" in t


# ----------------------------------------------------------- translation

def test_a_drawn_sound_may_be_split_without_a_link():
    """The rule that was here said the opposite, and it was wrong.

    016's `し` and `ん…` are unlinked, with a line of dialogue between them in
    reading order, and they came back "Si..." / "lence...". I called that a
    word cut in half and told the model a link is what licenses a split. lee:
    *"everrything is working as entened the 2 016 and 017 are not mistakes"* -
    the split is the answer he wants, so the prompt says so."""
    t = build_system(target="English")
    assert "WITHOUT A LINK, NOTHING IS SPLIT" not in t
    at = t.index("Two SOUND EFFECTS that plainly form one drawn sound")
    rule = " ".join(t[at:t.index("\n- ", at)].split())
    assert "even where no link joins them" in rule
    assert "the English splits where the drawing splits" in rule


def test_and_dialogue_still_may_not_be():
    """The half that was always right: a sentence never crosses two bubbles
    that nobody linked."""
    t = build_system(target="English")
    at = t.index("Two SOUND EFFECTS that plainly form one drawn sound")
    rule = " ".join(t[at:t.index("\n- ", at)].split())
    assert "DIALOGUE is not like that" in rule
    assert "never carried from one unlinked bubble into the next" in rule


def test_it_sits_with_the_link_rule_it_qualifies():
    t = build_system(target="English")
    assert t.index("A link between SOUND EFFECTS") < \
        t.index("Two SOUND EFFECTS that plainly form one drawn sound")
    between = t[t.index("A link between SOUND EFFECTS"):
                t.index("Two SOUND EFFECTS that plainly")]
    assert between.count("\n- ") == 1, "another rule got in between the two"


def test_the_linked_rules_are_still_there():
    t = build_system(target="English")
    assert "ONE continuous sentence broken across several bubbles" in t
    assert "one effect" in t


# ------------------------------------------- and the line that stopped dead

def test_the_line_that_stopped_dead():
    """008: `とっても良かったですあり…` - she is being cut off saying thank you -
    came back "It was wonderful. Than"."""
    assert stops_short("It was wonderful. Than", "とっても良かったですあり…")


def test_a_line_that_trails_off_properly_says_nothing():
    for ok in ("It was wonderful. Than...", "Thank yo—", "Than…", "Thank yo-"):
        assert not stops_short(ok, "とっても良かったですあり…"), ok


def test_a_source_that_does_not_trail_off_is_not_its_business():
    assert not stops_short("Fine", "わかった")
    assert not stops_short("Let's go", "行くぞ")


def test_nothing_is_said_about_an_empty_line_either_way():
    assert not stops_short("", "あり…")
    assert not stops_short("Than", "")


def test_a_closing_bracket_or_quote_counts_as_an_ending():
    """`様々な効能をもたらします…` came back `and offer a wide variety of
    benefits..."` - the quote closes outside the dots and the line is finished.
    """
    assert not stops_short('and offer a wide variety of benefits..."',
                           "様々な効能をもたらします…")


def test_it_is_a_note_and_never_a_repair():
    """Choosing between "Than-", "Thank yo-" and "Than..." is the typesetter's
    call, not this function's - the same rule `quieter` keeps."""
    import inspect
    from mangatl import translate as T
    src = inspect.getsource(T.stops_short)
    assert "note and not a repair" in src
    assert "dst_text" not in src, "it must not write the line"


# ------------------------------------------- and the one that was withdrawn

def test_nothing_flags_a_sound_for_starting_lower_case():
    """`half_a_sound` lived for one day. It flagged any sound effect whose
    English opened mid-word, which is exactly what 016's second box correctly
    does - lee: *"everrything is working as entened the 2 016 and 017 are not
    mistakes"*. A check that calls a good page bad is worse than no check."""
    from mangatl import translate as T
    assert not hasattr(T, "half_a_sound")


def test_it_is_asked_wherever_a_translated_line_is_checked():
    """Both places - the live run and the reply somebody pastes in - or a line
    typed by hand skips every check the model's answer gets."""
    from where import PKG
    src = (PKG / "translate.py").read_text(encoding="utf-8")
    assert src.count("stops_short(r.dst_text, r.src_text)") == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
