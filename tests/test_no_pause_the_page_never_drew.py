"""A line does not open with an ellipsis unless the original does.

lee, looking at 悪女見習いさん come back as *"...little villainess-in-training."*:
*"remove the ... at the begening if its not on teh japanesse text it shoud not
exist"*.

There is no ellipsis on that page. The model put it there because this prompt
taught it to: the rule for a sentence carried across two balloons said the
first bubble ENDS with three periods and the second one BEGINS with three
periods. That is a scanlation habit rather than the author's punctuation, and
it ends up on the front of standalone lines that continue nothing at all -
which is what happened here, on a label lying on the artwork.

The trailing half stays. Three periods at the END of a line is how trailing
off reads, the {source} usually earns it, and lee has kept it everywhere. It
is only the FRONT that has to be the author's.

The same rule as the em-dashes and the asterisks round sound effects, and for
the same reason: a mark the artist did not draw is a beat the reader did not
get.
"""
import pytest

from mangatl.translate import (build_proofread_system, build_system,
                               source_leads_with_ellipsis, strip_added_ellipsis)


# ------------------------------------------------------------------- at the door

@pytest.mark.parametrize("dst,src,want", [
    # lee's own line, both ways the model writes an ellipsis
    ("...little villainess-in-training.", "悪女見習いさん",
     "little villainess-in-training."),
    ("…little villainess-in-training.", "悪女見習いさん",
     "little villainess-in-training."),
    ("... and then he left.", "それから彼は出て行った", "and then he left."),
    ("・・・maybe.", "たぶん", "maybe."),
    # an opening quote does not hide it
    ('"...well, fine."', "「まあいいや」", '"well, fine."'),
    ("'...I guess.'", "「まあね」", "'I guess.'"),
])
def test_an_ellipsis_the_page_does_not_have_comes_off(dst, src, want):
    assert strip_added_ellipsis(dst, src) == want


@pytest.mark.parametrize("dst,src", [
    # the author's own trailing-off, which is the whole point of keeping it
    ("...I see.", "……そうか"),
    ("...I see.", "『……そうか』"),
    ("...well?", "・・・どうだ"),
    ("...", "…"),
])
def test_an_ellipsis_the_page_does_have_stays(dst, src):
    assert strip_added_ellipsis(dst, src) == dst


@pytest.mark.parametrize("dst,src", [
    # the END of a line is not the front, and trailing off is how a sentence
    # carried into the next bubble reads. lee has kept these everywhere.
    ("I THOUGHT...", "思ったんだ"),
    ("BUT THEN... IT MOVED.", "でも動いた"),
    # a single period is a full stop
    (". Hello", "なに"),
    # a lone ・ separates the halves of a foreign name
    ("Mr. John Smith", "ジョン・スミスさん"),
    ("", "なに"),
])
def test_everything_else_is_left_alone(dst, src):
    assert strip_added_ellipsis(dst, src) == dst


def test_a_line_that_is_nothing_but_an_ellipsis_survives():
    """Stripping it would leave the box empty, and an empty box is worse than
    a wrong one: lee's standing rule is that the full translation always goes
    in, and a box with nothing in it is not a translation to correct."""
    assert strip_added_ellipsis("...", "なに") == "..."


def test_the_source_is_read_past_its_brackets():
    assert source_leads_with_ellipsis("『……そうか』")
    assert source_leads_with_ellipsis("「...」")
    assert not source_leads_with_ellipsis("『そうか……』"), \
        "trailing off at the END says nothing about the front"
    assert not source_leads_with_ellipsis("")


# ------------------------------------------------------- and the model is told

def test_the_translator_is_no_longer_taught_to_open_with_one():
    """Stripping it at the door is the safety net. The prompt is where it
    stops being written in the first place - and this prompt used to ASK for
    it."""
    sys = build_system("manga", "en", "ja")
    assert "the next bubble BEGINS" not in sys, \
        "the rule that taught the habit has to go, not just its output"
    assert "Never START a line with an ellipsis" in sys


def test_the_translator_still_trails_off_at_the_end():
    """Only the front is the author's business. Removing the trailing half
    would take out the one that actually reads as speech running on."""
    sys = build_system("manga", "en", "ja")
    assert "ENDS with three periods" in sys


def test_the_proofreader_is_told_to_take_them_off():
    """It reads the whole chapter after the fact, which is the only pass that
    sees a line the translator opened wrongly on a page it has left behind."""
    sys = build_proofread_system("manga", "en", "ja")
    assert "ellipsis at the START" in sys


# -------------------------------------------------- and it happens for real

def _page(src="悪女見習いさん"):
    import numpy as np
    from mangatl.models import Page, TextRegion
    r = TextRegion(id=13, bbox=(10, 10, 60, 40), kind="freefloat", order=0)
    r.src_text = src
    r.dst_text = "placeholder"
    return Page(image=np.full((80, 80, 3), 255, np.uint8), regions=[r])


def test_the_translator_output_comes_through_the_door(monkeypatch):
    """Stripping it in a function nothing calls would fix nothing."""
    from mangatl import translate
    monkeypatch.setattr(translate, "_ask", lambda *a, **k: (
        '{"regions":[{"id":13,"translation":"...little villainess-in-training.",'
        '"speaker":null,"confidence":1.0}],"page_notes":[]}'))
    page = _page()
    translate.translate_page(page, client=object())
    assert page.regions[0].dst_text == "little villainess-in-training."


def test_the_proofreaders_output_comes_through_it_too(monkeypatch):
    """It rewrites lines of its own, so it can put one back."""
    from mangatl import translate
    monkeypatch.setattr(translate, "_ask", lambda *a, **k: (
        '{"regions":[{"id":13,"text":"...little villainess-in-training."}],'
        '"page_notes":[]}'))
    page = _page()
    translate.proofread_page(page, client=object())
    assert page.regions[0].dst_text == "little villainess-in-training."


def test_a_translation_file_comes_through_it_as_well():
    """A translations.json is very often a machine's, and it lands by the same
    door as everything else a machine writes."""
    from mangatl.editor import set_translation
    rec = {"src_text": "悪女見習いさん", "dst_text": ""}
    set_translation(rec, "...little villainess-in-training.")
    assert rec["dst_text"] == "little villainess-in-training."
    rec2 = {"src_text": "……そうか", "dst_text": ""}
    set_translation(rec2, "...I see.")
    assert rec2["dst_text"] == "...I see.", "the author's own stays"
