"""`keep_honorifics` reaches the proofreader too.

The setting existed, the translator honoured it, and the copy editor two steps
later had never heard of it. `_base_payload` sent `keep_honorifics`;
`build_proofread_payload` did not, and `PROOFREAD_TEMPLATE` never mentioned an
honorific in any of its rules - so a step whose whole job is CONSISTENCY was
free to decide that "Glow-san" would read better as "Glow".

Found by running the real prompt over lee's chapter 3, page by page, with the
real payloads. 180 boxes went to the proofreader and it changed six of them.
One of the six:

    ja   やっぱり グロウさん なんか嫌い
    was  I really don't like Glow-san.
    now  I really don't like Glow.

It did the same thing on the same box under a second, differently worded
version of the prompt, which is what makes it the missing field rather than
one bad turn. `keep_honorifics` was true on that project.

The field goes in the FIXED half of the payload - it never changes during a
run, so it belongs above the character sheet where the prompt cache can keep
it. See the key-order note in `_base_payload`.
"""
import pytest

from mangatl.models import Page, TextRegion
from mangatl.translate import (SeriesContext, build_proofread_payload,
                               build_proofread_system, build_system)


def _page():
    p = Page(image=None)
    p.regions = [TextRegion(id=1, bbox=(0, 0, 40, 20), kind="bubble", order=0,
                            src_text="やっぱりグロウさんなんか嫌い",
                            dst_text="I really don't like Glow-san.",
                            speaker="Ada")]
    return p


# ------------------------------------------------------------- the payload

def test_the_proofreader_is_told_which_way_it_went():
    for want in (True, False):
        ctx = SeriesContext(honorifics=want)
        assert build_proofread_payload(_page(), ctx)["keep_honorifics"] is want


def test_it_is_the_same_field_the_translator_gets():
    """One setting, one name, or somebody will set it in two places."""
    from mangatl.translate import _base_payload
    ctx = SeriesContext(honorifics=True)
    a = _base_payload(_page(), ctx)
    b = build_proofread_payload(_page(), ctx)
    assert a["keep_honorifics"] == b["keep_honorifics"]


def test_it_sits_in_the_half_that_does_not_move():
    """Above `characters`, which grows page by page. A fixed field below a
    moving one ends the cached prefix and throws away every byte after it."""
    keys = list(build_proofread_payload(_page(), SeriesContext()))
    assert keys.index("keep_honorifics") < keys.index("characters")
    assert keys.index("keep_honorifics") < keys.index("previous_page_tail")


# -------------------------------------------------------------- the prompt

def test_the_prompt_says_what_to_do_with_it():
    t = build_proofread_system("manga", "en")
    at = t.index("HONORIFICS are the project's decision")
    rule = " ".join(t[at:t.index("\n- ", at)].split())
    assert '"keep_honorifics" in the request' in rule, "it must name the field"
    assert "-san" in rule and "-sama" in rule
    assert '"Glow-san" is never tidied into "Glow"' in rule, \
        "the failure it was written for, named"
    assert 'into "Mr. Glow"' in rule, "the other way round is the same loss"


def test_it_is_not_left_to_taste():
    t = build_proofread_system("manga", "en")
    at = t.index("HONORIFICS are the project's decision")
    rule = " ".join(t[at:t.index("\n- ", at)].split())
    assert "not a matter of what reads better" in rule


def test_it_stands_with_the_other_consistency_rules():
    """Beside the names-are-canon rule, which is the same argument about the
    same thing: one person, written one way, on every page."""
    t = build_proofread_system("manga", "en")
    assert t.index("Character names: the character sheet's spellings") < \
        t.index("HONORIFICS are the project's decision")
    assert t.index("HONORIFICS are the project's decision") < \
        t.index("Do not use a proper name the character sheet")


def test_the_translator_still_has_its_own_rule():
    """This is a second place the decision is enforced, not a move."""
    assert "honorific" in build_system(target="English").lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
