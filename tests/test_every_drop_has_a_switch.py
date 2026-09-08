"""Read text deletes boxes. Every one of those deletions gets a tick.

Three passes at the end of `do_ocr` remove regions from the page: a box holding
nothing but marks, a box the reader found nothing in, and a box whose words
were read as part of an overlapping box's. All three are usually right. All
three are on by default, and lee asked for them in those words -- *"read text
only read teh etxt and not modify boxes exapt for removing boxes with no text
or remoeving boxes with only symobos"*.

TWO OF THEM WERE RUNNING WITH NOWHERE TO TURN THEM OFF. The switches came off
the settings page and the passes stayed; the comment left behind in
`project.py` even said so out loud -- *"No switch on the settings page ... none
of the three is a question worth asking"* -- and nothing on screen contradicted
it, so there was no way to find out from the app that a pass was deleting
anything at all.

It cost a box. Three readers were run over one 58-page chapter to compare them
(`claude/three-readers-on-one-chapter-2026-09-06.md`); one of them returned
nothing for page 005 box 0, `drop_empty` took that as evidence the box was bad,
and the box went. The artwork under it plainly reads a painted `슈`. It was
gone for the two readers that came afterwards and it is gone now.

The guard inside `empty_boxes` does not cover this: it refuses to empty a page
where EVERY box came back blank, which catches a reader that is down and not a
reader that shrugs at one box out of three. "The reader said nothing" and
"there is nothing there" are different sentences, and the only one who can tell
them apart is the person looking at the page. So they get a switch -- not
because the pass is wrong, but because it is destructive and silent.

This suite is written as a RULE rather than as three cases: any
`drop_*` setting `do_ocr` reads has to have a tick on the settings page and has
to be wired like the other default-on ones. A fourth drop added later is
covered without anybody remembering this file exists.
"""
import re

import pytest

from where import EDITOR_HTML, JS, PKG

HTML = EDITOR_HTML.read_text(encoding="utf-8")
PJS = (JS / "project.js").read_text(encoding="utf-8")
EDITOR = (PKG / "editor.py").read_text(encoding="utf-8")


def drops():
    """Every `drop_*` setting Read text acts on, read out of the code itself.

    Matched on the `is not False` shape all three share, which is also the
    shape that makes them default-on: a project.json written before the
    setting existed has no key and must behave as lee asked.
    """
    return sorted(set(re.findall(
        r'settings\.get\("(drop_[a-z_]+)"\)\s*is not False', EDITOR)))


def test_there_are_three_of_them_and_we_know_which():
    """A guard on the guard. If this list changes, the rest of this file is
    asking its question about a different set of passes and somebody should
    look at it on purpose."""
    assert drops() == ["drop_empty", "drop_read_twice", "drop_symbol_only"]


@pytest.mark.parametrize("key", drops())
def test_the_screen_has_the_switch(key):
    assert f'id="{key}"' in HTML, key
    at = HTML.index(f'id="{key}"')
    near = HTML[at:at + 200]
    # Ticked in the MARKUP as well as in the settings, so it does not sit
    # unticked for the moment between the page drawing and the project
    # loading - which is the moment somebody clicks it.
    assert "checked" in near, near
    assert "saveSettings()" in near, near


@pytest.mark.parametrize("key", drops())
def test_the_switch_says_what_gets_deleted(key):
    """The word on the label, not the name of the flag. Somebody reading this
    page has to be able to tell that a box is going to disappear."""
    at = HTML.index(f'id="{key}"')
    label = HTML[at:HTML.index("</label>", at)].lower()
    assert "delete" in label, label
    assert "box" in label, label


@pytest.mark.parametrize("key", drops())
def test_it_is_read_and_saved_like_the_other_default_on_ones(key):
    """Two behaviours a plain `$('x').checked` gives neither of: read with
    `!==false`, so an old project.json is not switched off by `!!undefined`;
    and omitted from the save when the box is not on screen, so saving from a
    half-built page does not write an off nobody chose."""
    on = PJS.split("const DEFAULT_ON")[1].split(";")[0]
    assert f"'{key}'" in on, key


@pytest.mark.parametrize("key", drops())
def test_it_is_still_on_for_a_project_that_never_heard_of_it(key):
    """Putting a switch back must not change the default. Every chapter that
    predates the setting keeps behaving the way lee asked for."""
    import tempfile

    from mangatl.project import Project
    with tempfile.TemporaryDirectory() as d:
        assert Project(None, d).settings[key] is True, key


def test_the_note_that_said_there_was_no_switch_is_gone():
    """It was the reason nobody noticed. A comment asserting a fact about the
    screen outlived the screen, and the next person to read it - including
    me - believed it."""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert "No switch on the settings page" not in src


def test_the_page_that_lost_a_box_is_written_down_somewhere():
    """Not a behaviour, a receipt. The switch exists because of one box on one
    page, and a rule with its reason attached survives a tidy-up that a bare
    rule does not."""
    assert "슈" in HTML or "005" in HTML.split('id="drop_empty"')[0][-2000:] \
        or "슈" in PJS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
