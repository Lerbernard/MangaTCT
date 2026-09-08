"""Settings opens on the section its nav says is open.

lee sent a crop of it: the Synopsis on screen, `Story settings` highlighted in
the rail beside it, and *"fix this"*.

The page answered the question twice. One nav button carried `on` in the
markup and one section carried `on` in the markup, nothing kept them in step,
and an edit to either half moved one without the other.

**The first fix went too far and made it worse.** Taking `on` off the Synopsis
section stopped the two DISAGREEING and left them both silent, and lee came
back with a screenshot of an empty panel: *"and fix thios"*, then *"that only
happesn when i first click the setting buttton"*.

Which is the shape of it exactly. `_pickSection` is only reached through
`openSettingsDlg`, and the Settings TAB does not call that - `editor.html`
carries `onclick="setTab('settings',1)"` on it. So the first press shows
whatever the markup says is open, and the markup said nothing was. Press a rail
item, `setSettingsTab` runs, and from then on it works - which is why it only
ever happened once a session.

So the rule is not "the nav decides and the markup says nothing". It is
**exactly one of each, naming the same section**: one lit button, one open
section, agreeing.

The File screen has the same shape - `#fileNav` and `#fileBody`, through the
same `_pickSection` - so it is checked here too rather than waiting for its
own turn to drift.
"""
import re

import pytest

from where import PKG

HTML = (PKG / "static" / "editor.html").read_text("utf-8")
IO = (PKG / "static" / "js" / "project-io.js").read_text("utf-8")
VIEW = (PKG / "static" / "js" / "view.js").read_text("utf-8")


def _nav_default(nav_id):
    """The `data-sec` of the button that carries `on` in the markup."""
    at = HTML.index('id="%s"' % nav_id)
    end = HTML.index("</nav>", at)
    lit = re.findall(r'<button class="setnav-btn on" data-sec="([a-z]+)"',
                     HTML[at:end])
    assert len(lit) == 1, (nav_id, lit)
    return lit[0]


#: Where each rail's sections live, in document order. Bounding a body by
#: "the next body" rather than by a closing tag, because the last one on the
#: page has no next tag to stop at and a search that runs to the end of the
#: file reads the OTHER rail's sections as its own.
BODIES = sorted((HTML.index('id="%s"' % b), b)
                for b in ("setBody", "fileBody"))


def _sections_open(body_id):
    """Every section that carries `on` in the markup, under this body."""
    at = HTML.index('id="%s"' % body_id)
    later = [i for i, _ in BODIES if i > at]
    end = min(later) if later else len(HTML)
    return re.findall(r'<section class="set-section on" data-sec="([a-z]+)"',
                      HTML[at:end])


def test_the_settings_markup_opens_on_one_section_and_lights_it():
    """One lit button, one open section, and the same name on both.

    The empty panel lee saw was this test's earlier version being satisfied by
    a page with nothing open at all."""
    assert _nav_default("setNav") == "story"
    assert _sections_open("setBody") == ["story"], \
        "the section the nav lights has to be the one the markup opens"


def test_the_file_screen_agrees_with_itself_too():
    assert _nav_default("fileNav") == "new"
    assert _sections_open("fileBody") == ["new"]


def test_the_tab_itself_does_not_go_through_the_opener():
    """Which is WHY the markup has to be right. If the Settings tab is ever
    given `openSettingsDlg`, this can be relaxed - until then the first press
    of it is served by the markup alone."""
    at = HTML.index('id="tabSet"')
    assert "setTab('settings'" in HTML[at:at + 200]
    assert "openSettingsDlg" not in HTML[at:at + 200]


def test_opening_settings_shows_what_the_nav_says():
    body = IO.split("function openSettingsDlg()", 1)[1].split("\n}", 1)[0]
    assert "#setNav .setnav-btn.on" in body
    assert "setSettingsTab(" in body
    assert body.index("#setNav") < body.index("setTab('settings')"), \
        "the section is chosen before the tab is shown, or it flashes"


def test_picking_a_section_moves_both_halves():
    """`_pickSection` is what keeps them together from then on: it lights the
    button AND opens the section, in one call, off one name."""
    body = VIEW.split("function _pickSection(", 1)[1].split("\n}", 1)[0]
    assert ".setnav-btn" in body and ".set-section" in body
    assert body.count("dataset.sec===name") == 2, \
        "both halves are matched against the same name"


def test_the_nav_buttons_and_the_sections_are_the_same_set():
    """A button with no section is a dead tab; a section with no button is a
    page nobody can reach."""
    at = HTML.index('id="setNav"')
    navs = set(re.findall(r'<button class="setnav-btn[^"]*" data-sec="([a-z]+)"',
                          HTML[at:HTML.index("</nav>", at)]))
    at = HTML.index('id="setBody"')
    secs = set(re.findall(r'<section class="set-section[^"]*" data-sec="([a-z]+)"',
                          HTML[at:]))
    assert navs == secs, (navs ^ secs)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
