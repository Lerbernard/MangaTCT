"""M merges on whatever view you are looking at, and a linked sound is one
sound.

Two things lee hit in the same sitting.

**M did nothing outside the typeset view.** *"when i clcik the selct tool to
slect a bunch of [boxes] and clik m or right click and clcik merge nothing
happens but if i manaualy do it it works"*. The whole shortcut block in
`select.js` is the PAINT tools, and paint only exists on the typeset view, so
it opens with `if(view !== 'typeset') return;`. M had been dropped into that
block because M is also the pixel marquee - and the merge half went behind the
gate with it. Boxes are selected on every view, the select tool arms on every
view, and the right-click menu offers Merge on every view; the one way in that
did not work was the key the menu tells you to press.

**And a link between sound effects means one sound, not two.** lee: *"if sfx
bubbles are linked it means that the are part of a one sfx sound that is
split"* - his `し` and `ん…` drawn either side of two characters, linked. The
prompt already said what a link means for dialogue and said nothing about
paint, so each half was translated as a sound of its own.
"""
import pytest

from where import JS, PKG

SEL = (JS / "select.js").read_text(encoding="utf-8")
TR = (PKG / "translate.py").read_text(encoding="utf-8")


def _keydown():
    at = SEL.index("window.addEventListener('keydown'")
    return SEL[at:at + 4000]


def test_m_merges_before_the_typeset_gate():
    body = _keydown()
    at = body.index("mergeSelected()")
    gate = body.index("view!=='typeset'")
    assert at < gate, "the merge is behind the paint tools' own gate"


def test_it_only_takes_the_key_when_there_is_something_to_merge():
    """With nothing selected M is still the pixel marquee, and that must keep
    working - two tools, one key, and the selection decides which."""
    body = _keydown()
    at = body.index("mergeSelected()")
    head = body[max(0, at - 320):at]
    assert "selMulti.size>1" in head.replace(" ", "")
    assert "e.key==='m'" in head.replace(" ", "")


def test_the_marquee_half_stays_with_the_tool_it_arms():
    """`toggleSelTool('rect')` is a paint tool. It belongs below the gate."""
    body = _keydown()
    assert "toggleSelTool('rect')" in body
    assert body.index("view!=='typeset'") < body.index("toggleSelTool('rect')")


def test_the_merge_is_not_swallowed_by_whatever_listens_next():
    body = _keydown()
    at = body.index("mergeSelected()")
    near = body[max(0, at - 320):at + 120]
    assert "preventDefault()" in near and "stopPropagation()" in near


def test_a_writing_box_still_keeps_its_own_m():
    """Typing an m into the Japanese is not a merge."""
    body = _keydown()
    assert body.index("if(writing) return;") < body.index("mergeSelected()")


# ------------------------------------------------- one sound, split in two

def test_the_translator_is_told_what_a_linked_sound_is():
    at = TR.index('- Some regions carry a "link" number.')
    rule = TR[at:at + 1600]
    assert "SOUND EFFECTS" in rule
    assert "one effect" in rule or "one sound" in rule
    assert "two sounds" in rule, "and what it must NOT do with them"


def test_the_two_halves_are_still_handed_back_split():
    """The same rule the dialogue links have: one line, split where it was
    split. A sound repeated whole in both boxes is the failure this stops."""
    at = TR.index('- A link between SOUND EFFECTS')
    rule = TR[at:TR.index("\n- ", at + 5)]
    flat = " ".join(rule.split())
    assert "split the English at the same place" in flat
    assert "never put the whole of it in both" in flat.lower()


def test_the_payload_carries_the_link_on_a_sound_effect_too():
    """The rule needs the data. Regions are listed with their link whatever
    their kind - it is the PROOFREAD payload that leaves sound effects out,
    and that one is not about links."""
    at = TR.index('"src_char_count": len(r.src_text),')
    near = TR[at - 400:at + 700]
    assert '"link"' in near
    assert 'if r.src_text.strip()' in near, \
        "every region with words in it, sound effects included"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
