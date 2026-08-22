"""Ctrl+Z takes back what you did on THIS page.

lee: *"control + z shoud only work on a per pafe basix not a global thing"*.

One stack across the whole chapter meant Ctrl+Z on page 12 could take back a
merge on page 3 - and then jump you to page 3 to show you, because the undo of
a region change ends with `showPage` on the page the change belongs to. You
press it to take back the thing you just did HERE, and from the keyboard there
is no way to tell which page the top of the stack is on.

Nothing is thrown away: an entry for another page stays on the stack, and
going back to that page makes it the next thing that undoes.
"""
import re

import pytest

from where import JS

H = (JS / "history.js").read_text(encoding="utf-8")


def _fn(name):
    return H.split("function %s(" % name, 1)[1].split("\n}", 1)[0]


def test_every_entry_is_stamped_with_its_page():
    body = _fn("record")
    assert "recordPage()" in body
    assert "page" in body
    # ...on the log line AND on the undo entry, or the two disagree
    assert re.search(r"hist\.push\(\{[^}]*page", body), body
    assert re.search(r"undoStack\.push\(\{[^}]*page", body), body


def test_the_page_is_read_at_the_moment_the_change_happens():
    """Not when it is undone - by then you may be three pages away."""
    body = _fn("recordPage")
    assert "cur" in body


def test_undo_takes_the_newest_entry_for_the_page_on_screen():
    body = _fn("undoLast")
    assert "undoStack.pop()" not in body, "that is the global stack again"
    assert ".page === here" in body
    assert "splice(at, 1)" in body, "taken out of the middle, not off the top"
    # ...searched from the newest end
    assert "i = undoStack.length - 1" in body
    assert "i--" in body


def test_an_entry_for_another_page_is_kept_rather_than_dropped():
    """It is still yours; it just belongs somewhere else. Going to that page
    makes it the next thing that undoes."""
    body = _fn("undoLast")
    at = body.index("if(at < 0)")
    guard = body[at:at + 260]
    assert "return;" in guard
    assert "undoStack.length" in guard, \
        "and the message says whether there is anything at all"
    assert "Nothing to undo on this page" in guard


def test_the_shortcut_still_leaves_a_real_writing_surface_alone():
    """Unchanged, and worth holding: focus left on a slider or a button was
    why Ctrl+Z 'sometimes' did nothing."""
    at = H.index("window.addEventListener('keydown'")
    body = H[at:]
    assert "TEXTAREA" in body and "isContentEditable" in body
    assert "undoLast()" in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
