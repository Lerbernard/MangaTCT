"""Settings opens on the section its nav says is open.

lee sent a crop of it: the Synopsis on screen, `Story settings` highlighted in
the rail beside it, and *"fix this"*.

The page answered the question twice. One nav button carried `on` in the
markup and one section carried `on` in the markup, nothing kept them in step,
and an edit to either half moved one without the other. Now the button is the
answer and `openSettingsDlg` opens whatever it names.

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


def _sections_open(body_id):
    """Every section that carries `on` in the markup, under this body."""
    at = HTML.index('id="%s"' % body_id)
    end = HTML.index("</main>", at) if "</main>" in HTML[at:] else len(HTML)
    return re.findall(r'<section class="set-section on" data-sec="([a-z]+)"',
                      HTML[at:end])


def test_the_settings_markup_has_exactly_one_default():
    """And it is the nav button. A section that also claims `on` is a second
    answer to a question with one right one."""
    assert _nav_default("setNav") == "story"
    assert _sections_open("setBody") == [], \
        "no section carries `on` - the nav decides"


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
