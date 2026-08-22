"""Exporting the picture with the boxes on it.

lee: *"add a button n in the export that allow me to export the picture with
the boxes"*.

A third choice in the Export dialog's **What to write**, beside the finished
pages and the cleaned art. It writes the ORIGINAL page with the boxes drawn on
it: a check sheet, not a page of the book.

Two things make or break it, and both are pinned here.

**It has to look like the editor.** A marked-up page is only useful if a red
rectangle means the same thing on paper as it does on screen, so the colours,
the balloon hint, the dashes and the numbers are copies of `frames.js` and
`editor.css` - and one test below parses `frames.js` and fails if the two tables
ever drift apart. That is the whole reason the drawing lives next to the record
rather than being reinvented.

**It is not the export.** No cleaning, no typesetting, no `exported`, no
`cleaned`: a chapter whose boxes were saved has not been published, and the step
counter is what tells lee which is which.
"""
import os
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import render
from mangatl.project import Project
from scratch import scratch
from where import PKG

JS = PKG / "static" / "js"
CSS = PKG / "static" / "css"


def _page(w=340, h=260):
    """A pale page with a dark blob in each box, so ink and furniture differ."""
    img = np.full((h, w, 3), 236, np.uint8)
    cv2.rectangle(img, (70, 60), (110, 130), (30, 30, 30), -1)
    cv2.rectangle(img, (210, 150), (250, 210), (30, 30, 30), -1)
    return img


def _rec(rid, box, **kw):
    r = {"id": rid, "bbox": list(box), "bubble_bbox": list(box),
         "kind": "bubble", "order": rid, "confidence": 0.9, "manual": False,
         "link": 0, "box_group": 0}
    r.update(kw)
    return r


A = _rec(0, (60, 50, 60, 90))
B = _rec(1, (200, 140, 60, 80))


def _tiny_project(root, img=None):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", img if img is not None
                                          else _page())[1].tobytes())
    return p


# ------------------------------------------------------------------ the drawing

def test_the_sheet_is_the_page_with_the_boxes_on_it():
    img = _page()
    out = render.box_sheet(img, [A, B])
    assert out.shape == img.shape
    assert not np.array_equal(out, img), "nothing was drawn"
    # the art itself is untouched away from the boxes
    far = (np.s_[0:40], np.s_[260:340])
    assert np.array_equal(out[far[0], far[1]], img[far[0], far[1]])
    # and every box's own border really changed
    for r in (A, B):
        x, y, w, h = r["bbox"]
        assert not np.array_equal(out[y, x:x + w], img[y, x:x + w])


def test_a_box_is_drawn_in_its_own_text_type_colour():
    img = _page()
    for kind, hexcol in render.KIND_COLOURS.items():
        out = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), kind=kind)])
        want = np.array(render._bgr(hexcol), np.float32)
        edge = out[50, 60:120].astype(np.float32)
        near = min(float(np.abs(px - want).max()) for px in edge)
        assert near <= 2, f"{kind} border is not {hexcol}"


def test_the_number_on_the_sheet_is_the_reading_order_not_the_id():
    """The editor's badge reads `order+1`; a sheet numbered by id would send
    lee looking for box 4 in the wrong corner of the page."""
    img = _page()
    plain = render.box_sheet(img, [_rec(7, (60, 50, 60, 90), order=0)])
    same = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), order=0)])
    assert np.array_equal(plain, same), "the id leaked into the badge"
    other = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), order=4)])
    assert not np.array_equal(plain, other), "the badge ignored the order"


def test_the_balloon_is_not_drawn_at_all():
    """It used to be, faint and dashed behind the writing, wherever the balloon
    was more than 1.25x the text area. lee asked for it gone on 2026-07-30:
    *"there a thin dahed red box around the box around the text what does it do
    and remove it"*. The sheet shows what the editor shows - one rectangle per
    box - so a roomy balloon and a tight one now produce the same picture."""
    img = _page()
    tight = _rec(0, (60, 50, 60, 90), bubble_bbox=[58, 48, 64, 94])
    roomy = _rec(0, (60, 50, 60, 90), bubble_bbox=[30, 20, 130, 160])
    a = render.box_sheet(img, [tight])
    b = render.box_sheet(img, [roomy])
    assert np.array_equal(a, b), "the balloon is still being drawn"
    # nothing is painted out at the roomy balloon's own corner
    assert np.array_equal(b[20, 30:160], img[20, 30:160])


def test_two_sections_of_one_balloon_are_dashed_and_not_framed():
    """The frame round the pair is gone. lee, finding one on a burst holding
    two speeches: *"there a big box with no label or anything"*, then *"hide
    teh big box afterware it dosnt need to be visibel"*. The sheet shows what
    the screen shows, so it went from both - and what it said is still said,
    by the sections' own dashed outlines."""
    img = _page()
    solo = render.box_sheet(img, [_rec(0, (60, 50, 60, 90)),
                                  _rec(1, (60, 150, 60, 60))])
    pair = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), box_group=3),
                                  _rec(1, (60, 150, 60, 60), box_group=3)])
    # Nothing is drawn in the gap BETWEEN the boxes any more - that band is
    # where the frame used to run. Clear of the lower box's number badge.
    band = np.s_[143:148], np.s_[80:118]
    assert np.array_equal(solo[band[0], band[1]], img[band[0], band[1]])
    assert np.array_equal(pair[band[0], band[1]], img[band[0], band[1]]), \
        "the frame round the pair is back"
    # ...and the grouping still shows: the outlines go dashed, so the two
    # renders are not identical either.
    assert not np.array_equal(solo, pair), "the sections are not marked at all"


def test_a_line_split_across_two_balloons_is_joined_by_a_connector():
    img = _page()
    apart = render.box_sheet(img, [A, B])
    joined = render.box_sheet(img, [dict(A, link=2), dict(B, link=2)])
    assert not np.array_equal(apart, joined)
    # the connector crosses the middle of the page, where nothing else draws
    mid = np.s_[110:130], np.s_[150:180]
    assert np.array_equal(apart[mid[0], mid[1]], img[mid[0], mid[1]])
    assert not np.array_equal(joined[mid[0], mid[1]], img[mid[0], mid[1]])


def test_two_sections_of_one_balloon_are_not_also_wired_together():
    """The group frame already says they are one thing; a connector across the
    balloon says it twice and draws a line over the art lee asked to keep."""
    img = _page()
    one = render.box_sheet(img, [dict(A, link=2, box_group=3),
                                 dict(B, link=2, box_group=3)])
    none = render.box_sheet(img, [dict(A, box_group=3), dict(B, box_group=3)])
    assert np.array_equal(one, none)


def test_a_sub_type_is_drawn_in_the_shade_it_was_given():
    """A sub-type carries its own colour, and the sheet has to use it - the
    sheet and the screen are two drawings of one thing."""
    from mangatl import kinds as K
    img = _page()
    shade = K.family_shades("sfx")[3]
    custom = [{"key": "ck_boom", "family": "sfx", "color": shade}]
    out = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), kind="ck_boom")],
                           custom)
    want = np.array(render._bgr(shade), np.float32)
    edge = out[50, 60:120].astype(np.float32)
    assert min(float(np.abs(px - want).max()) for px in edge) <= 2


def test_a_main_type_keeps_its_family_colour():
    """The three families are drawn in fixed colours so the sheet reads the
    same from one chapter to the next. A sub-type that reuses a family's key
    must not repaint it - a family's colour is not anybody's to change."""
    from mangatl import kinds as K
    img = _page()
    out = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), kind="sfx")],
                           [{"key": "sfx", "family": "sfx", "color": "#2cddd6"}])
    want = np.array(render._bgr(K.FAMILY_COLOUR["sfx"]), np.float32)
    edge = out[50, 60:120].astype(np.float32)
    assert min(float(np.abs(px - want).max()) for px in edge) <= 2


def test_a_sub_type_wearing_a_colour_from_another_family_is_not_drawn_in_it():
    """A project written before families existed could have a sub-type in any
    hue at all. Drawing it in that colour is a box that says the wrong family,
    which is worse than a box with no colour meaning at all."""
    from mangatl import kinds as K
    img = _page()
    custom = [{"key": "ck_old", "family": "bubble", "color": "#00ff00"}]
    out = render.box_sheet(img, [_rec(0, (60, 50, 60, 90), kind="ck_old")],
                           custom)
    green = np.array(render._bgr("#00ff00"), np.float32)
    edge = out[50, 60:120].astype(np.float32)
    assert min(float(np.abs(px - green).max()) for px in edge) > 20
    assert render.kind_colour("ck_old", custom) in K.family_shades("bubble")


def test_a_box_off_the_edge_of_the_page_does_not_crash_the_sheet():
    img = _page()
    out = render.box_sheet(img, [_rec(0, (-20, -30, 90, 100)),
                                 _rec(1, (300, 230, 200, 200))])
    assert out.shape == img.shape


def test_a_page_with_no_boxes_comes_out_as_the_page():
    img = _page()
    assert np.array_equal(render.box_sheet(img, []), img)
    assert np.array_equal(render.box_sheet(img, None), img)


# ------------------------------------------- the sheet agrees with the editor

def test_the_sheet_uses_the_editor_s_own_colours():
    js = (JS / "frames.js").read_text(encoding="utf8")
    block = re.search(r"const KIND_COLORS=\{(.*?)\}", js, re.S).group(1)
    seen = dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{6})'", block))
    assert seen, "could not read KIND_COLORS out of frames.js"
    assert {k: v.lower() for k, v in seen.items()} == \
        {k: v.lower() for k, v in render.KIND_COLOURS.items()}

    link = re.search(r"const LINK_COLOR='(#[0-9a-fA-F]{6})'", js).group(1)
    assert link.lower() == render.LINK_COLOUR.lower()
    # ...and every shade a sub-type may take, family by family.
    from mangatl import kinds as K
    block2 = re.search(r"const FAMILY_SHADES=\{(.*?)\n\};", js, re.S).group(1)
    for fam in K.FAMILIES:
        row = re.search(rf"{fam}:\[(.*?)\],", block2, re.S).group(1)
        assert [c.lower() for c in re.findall(r"'(#[0-9a-fA-F]{6})'", row)] == \
            [c.lower() for c in K.family_shades(fam)], fam


def test_the_sheet_uses_the_editor_s_own_opacities():
    """`.box` fills at 0x22, which is the difference between a sheet that
    looks like the screen and one that merely has boxes on it.

    Two things that used to be drawn are gone from BOTH and may not come back
    to either: the balloon hint, and the frame round two sections of one
    balloon. The sheet shows what the screen shows - that rule is what made
    each removal happen in two files at once."""
    js = (JS / "frames.js").read_text(encoding="utf8")
    assert "kc+'22'" in js
    assert abs(render.BOX_FILL - 0x22 / 255) < 1e-9
    css = (CSS / "editor.css").read_text(encoding="utf8")
    # the balloon hint is gone from both, so neither may draw it again
    assert ".bhint{" not in css and "kindColor(r.kind)+'88'" not in js
    assert "className='bhint'" not in js
    # ...and the group frame likewise
    assert ".gbox{" not in css and "className='gbox'" not in js
    assert "GROUP_FILL)" not in (PKG / "render.py").read_text(encoding="utf8")


# ----------------------------------------------------------------- the export

def test_exporting_the_boxes_writes_the_marked_up_original():
    from mangatl import editor
    root = scratch("_tmp_expboxes")
    p = _tiny_project(root)
    try:
        p.pages[0].regions = [A, B]
        os.makedirs(editor.export_root(p), exist_ok=True)
        out = editor.export_page(p, 0, mode="boxes")
        got = cv2.imread(out)
        assert got is not None, out
        want = render.box_sheet(p.image(0), [A, B])
        assert np.array_equal(got, want), "what was written is not the sheet"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_exporting_the_boxes_is_not_exporting_the_chapter():
    from mangatl import editor
    root = scratch("_tmp_expboxes2")
    p = _tiny_project(root)
    try:
        p.pages[0].regions = [A, B]
        os.makedirs(editor.export_root(p), exist_ok=True)
        editor.export_page(p, 0, mode="boxes")
        assert not p.pages[0].exported, "a box sheet is not the export"
        assert not p.pages[0].cleaned, "a box sheet cleans nothing"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_sheet_is_drawn_on_the_original_not_on_a_cleaned_plate():
    """The boxes say where the Japanese was, so they belong on the page that
    still has it. Erasing the writing and then pointing at it is no use."""
    from mangatl import editor
    root = scratch("_tmp_expboxes3")
    p = _tiny_project(root)
    try:
        p.pages[0].regions = [A, B]
        os.makedirs(editor.export_root(p), exist_ok=True)
        got = cv2.imread(editor.export_page(p, 0, mode="boxes"))
        orig = p.image(0)
        x, y, w, h = A["bbox"]
        # the ink inside the box is still ink: a cleaned plate would be pale
        inside = got[y + 12:y + h - 12, x + 12:x + w - 12]
        assert inside.min() < 60, "the writing was erased before drawing"
        assert orig[y + 12:y + h - 12, x + 12:x + w - 12].min() < 60
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_unknown_export_mode_is_refused_rather_than_guessed():
    from mangatl import editor
    root = scratch("_tmp_expboxes4")
    p = _tiny_project(root)
    try:
        with pytest.raises(ValueError):
            editor.export_page(p, 0, mode="sideways")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_dialog_and_the_server_agree_on_the_three_modes():
    from mangatl import editor
    html = (PKG / "static"
            / "editor.html").read_text(encoding="utf8")
    sel = re.search(r'<select id="expMode".*?</select>', html, re.S).group(0)
    assert sorted(re.findall(r'value="(\w+)"', sel)) == \
        sorted(editor.EXPORT_MODES)
    io = (JS / "project-io.js").read_text(encoding="utf8")
    assert "boxes:'-boxes'" in io.replace(" ", "")


def test_the_export_dialog_offers_the_boxes_and_names_the_folder_for_them():
    import shutil as sh
    import subprocess
    if not sh.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "export_boxes.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "modes offered: full,clean,boxes" in out.stdout, out.stdout
    assert "boxes name: chapter-12-en-boxes" in out.stdout, out.stdout
    assert "boxes blurb mentions boxes: true" in out.stdout, out.stdout
    assert "then clean name: chapter-12-en-cleaned" in out.stdout, out.stdout
    assert "back to boxes name: chapter-12-en-boxes" in out.stdout, out.stdout
    assert "back to full name: chapter-12-en" in out.stdout, out.stdout
    assert "posted mode: boxes" in out.stdout, out.stdout
    assert "dialog closed: true" in out.stdout, out.stdout
