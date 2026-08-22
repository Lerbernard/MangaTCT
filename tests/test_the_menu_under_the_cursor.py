"""The right-click menu on boxes, and the undo that takes the merge back.

lee: *"if i undo a merge it shoud delete the merge box, and add a right
clcik setting for boxes that allwa me to mege , delete  And othrer stuff"*.
"""
import pytest

from where import JS, CSS

RO = (JS / "region-ops.js").read_text(encoding="utf-8")


def _merge_body():
    body = RO[RO.index("async function mergeSelected(ids)"):]
    return body[:body.index("\nfunction ") if "\nfunction " in body
                else len(body)]


def test_undoing_a_merge_deletes_the_merged_box_first():
    """The merge MADE a box as well as deleting some. Its undo closure has
    to take both back, or the union box sits on top of the restored
    originals - which is what lee saw."""
    body = _merge_body()
    at = body.index("record('region-merge'")
    undo = body[at:at + 600]
    assert "region/${made}`, 'DELETE'" in undo
    assert "restoreRegions(pg, snaps)" in undo
    # ...and the deletion comes BEFORE the restore.
    assert undo.index("'DELETE'") < undo.index("restoreRegions")


def test_the_menu_opens_on_a_box_and_nowhere_else():
    """Right-click on empty page keeps the browser's own menu."""
    at = RO.index("$('stage').addEventListener('contextmenu'")
    h = RO[at:at + 700]
    assert "closest('.box')" in h
    assert "if(!box) return;" in h
    assert "boxMenu(e, r.id)" in h


def test_the_menu_offers_what_lee_asked_for():
    at = RO.index("function boxMenu(ev, id)")
    body = RO[at:at + 2400]
    assert "mergeSelected(" in body, "merge"
    assert "delSelected()" in body, "delete"
    # ...and the other stuff: the three types, split, link, hide
    for act in ("setKindSelected('bubble')", "setKindSelected('freefloat')",
                "setKindSelected('sfx')", "splitRegion", "startLink",
                "linkNext", "setBoxShown"):
        assert act in body, act


def test_merge_appears_only_with_two_or_more_selected():
    at = RO.index("function boxMenu(ev, id)")
    body = RO[at:at + 2400]
    at2 = body.index("mergeSelected(")
    assert "many >= 2" in body[:at2], \
        "one box has nothing to merge with"


def test_every_row_calls_what_the_panel_already_calls():
    """No third way to do anything: the menu is the side panel's own
    functions at the cursor, so behaviour cannot drift between them."""
    at = RO.index("function boxMenu(ev, id)")
    body = RO[at:at + 2400]
    assert "api(" not in body, "rows call functions, never the server raw"


def test_a_right_click_selects_the_box_it_lands_on():
    """The menu must always describe the boxes it will act on - but a
    multi-selection the box is PART of survives, or right-clicking to merge
    would destroy the selection being merged."""
    at = RO.index("$('stage').addEventListener('contextmenu'")
    h = RO[at:at + 900]
    assert "!selMulti.has(r.id)" in h


def test_the_menu_dies_on_escape_and_on_a_click_elsewhere():
    assert "boxMenuClose()" in RO
    at = RO.index("function boxMenuClose()")
    tail = RO[at:]
    assert "closest('#boxmenu')" in tail
    assert "e.key==='Escape') boxMenuClose()" in tail


def test_the_key_hints_are_styled_not_guessed():
    css = (CSS / "editor.css").read_text(encoding="utf-8")
    assert ".tbrow .mkey" in css
    assert ".tbhr" in css


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
