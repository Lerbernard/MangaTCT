"""What the box types look like once they are on screen.

The model is in `test_balloon_types.py` and the settings screen in
`test_box_type_families.py`. This is the round of changes lee asked for after
using the thing:

* *"instad of bullon it shodu be bubble text and outside text"*
* *"merge the fonts selctor with the bubble insatd of saying this sis default
  it shiud have the font selctor there"*
* *"upadte teh bar with the type of boxes"*
* *"if i chnage the colr of a subtype while i alread have some created it
  shoud update"*
* *"get rid of teh expanding on the boxes ... it shou djust always fit the
  text"*
* *"get rid of the numbers in te tetxt layers and make it pre collapes by
  default"*
* *"on teh original tab i lost teh ability to drag the tab to chnge tehre
  numbering"*
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

from mangatl import kinds as K
from where import PKG

BUBBLES = [((150, 120), "bubble"), ((350, 120), "thought"), ((150, 320), "sfx"),
           ((350, 320), "bubble")]


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 240, np.uint8)
    for (cx, cy), _ in BUBBLES:
        cv2.ellipse(img, (cx, cy), (80, 50), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, (cx, cy), (80, 50), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [
        {"id": i + 1, "kind": k, "order": i,
         "bbox": [cx - 60, cy - 30, 120, 60],
         "bubble_bbox": [cx - 80, cy - 50, 160, 100],
         "polygon": [[cx - 60, cy - 30], [cx + 60, cy - 30],
                     [cx + 60, cy + 30], [cx - 60, cy + 30]],
         "confidence": 0.9, "src_text": "テスト",
         # Only the first one is long. The rows are cards, and four tall ones
         # do not fit on screen at once - a press at coordinates outside the
         # window is not a press, so a drag test could never reach the last.
         "dst_text": (f"LINE {i + 1} WITH RATHER A LOT MORE WORDS IN IT THAN "
                      f"WOULD EVER FIT ON TWO SHORT LINES OF A LITTLE BOX"
                      if i == 0 else f"LINE {i + 1}")}
        for i, ((cx, cy), k) in enumerate(BUBBLES)]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "onscreen"))
    editor.do_typeset(p, 0)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip('chromium unavailable')
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _original(pg):
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)


# ------------------------------------------------------------- the names

def test_the_main_type_is_called_bubble_text():
    assert K.FAMILY_LABELS["bubble"] == "Bubble text"
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "frames.js").read_text(encoding="utf8")
    assert "bubble:'Bubble text'" in js.replace(", ", ",")
    assert "'Balloon'" not in js


def test_a_whisper_is_one_of_the_ones_you_start_with():
    """Yell, Angry and Flashback were preloads too until lee said which nine
    he actually wanted - *"only these should be default"*. A shout, a yell and
    an angry line are one kind of typesetting asked for three times."""
    labels = {s["label"] for s in K.migrate([], seed=True)}
    assert "Whisper" in labels
    assert "Thought bubble" in labels
    assert "Yell" not in labels


# -------------------------------------------------------------- the key

def test_the_key_names_the_types_this_project_actually_has(ed):
    """It used to list six flat types in colours nothing was drawn in any
    more. lee: *"upadte teh bar with the type of boxes"*."""
    pg, _p, errs = ed
    _original(pg)
    said = pg.evaluate(
        "[...document.querySelectorAll('#legend > *')]"
        "    .filter(s=>!s.hasAttribute('aria-hidden'))"
        ".map(s=>s.textContent.trim())")
    # The three main types and nothing under them - lee, later: *"this shoud
    # only show the 3 main type"*. A chip for every sub-type made a paragraph
    # of colour above the page longer than anything it explained.
    # The three main types are BUTTONS now - clicking one sets what a box
    # you draw comes out as. See
    # `tests/ui/the_legend_draws_the_box.test.js`. The key still reads
    # the same, which is what this pins. The select-boxes tool sits on the end
    # of the row - lee asked for it there, next to the things it selects.
    assert said == ["1 Bubble text", "2 Freefloat text", "3 Sound effect",
                    "unsure", "Select boxes"], said
    # nothing from the old flat list survives
    for gone in ("1 speech", "2 open", "4 caption", "5 thought", "6 burst"):
        assert gone not in said, gone
    assert not errs, errs[:2]


def test_a_row_says_the_sub_types_name_not_its_key(ed):
    pg, _p, errs = ed
    _original(pg)
    chips = pg.evaluate("""[...document.querySelectorAll('#list .lrow')]
        .map(r=>[...r.querySelectorAll('.chip')].map(c=>c.textContent.trim()))""")
    flat = [c for row in chips for c in row]
    assert "Thought bubble" in flat
    assert "thought" not in flat, "the raw key is on screen"
    assert not errs, errs[:2]


# ------------------------------------------------------- changing a colour

def test_recolouring_a_sub_type_updates_what_is_already_drawn(ed):
    """lee: *"if i chnage the colr of a subtype while i alread have some
    created it shoud update"*. The outlines were being redrawn and nothing
    else was - not the rows, not the key, not the menus."""
    pg, p, errs = ed
    _original(pg)
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)
    before = pg.evaluate("kindColor('thought')")
    pg.evaluate("cycleKindColor('thought')")
    pg.wait_for_timeout(900)
    after = pg.evaluate("kindColor('thought')")
    assert after != before, after
    assert after in K.family_shades("bubble")

    def to_hex(css):
        import re
        m = re.match(r"rgb\((\d+), (\d+), (\d+)\)", css or "")
        return "#%02x%02x%02x" % tuple(int(x) for x in m.groups()) if m else css

    # The key beside the page carries the three MAIN colours only now, so the
    # place a sub-type's new shade has to show up is the row for the box that
    # uses it - and the menus, below.
    _original(pg)
    rows = [to_hex(c) for c in pg.evaluate(
        "[...document.querySelectorAll('#list .lrow .kd')].map(i=>i.style.background)")]
    assert after in rows, rows
    assert not errs, errs[:2]


# --------------------------------------------------------------- the fonts

def test_every_type_picks_its_font_on_its_own_row(ed):
    """One place, not two. lee: *"merge the fonts selctor with the bubble
    insatd of saying this sis default it shiud have the font selctor there"*."""
    pg, p, errs = ed
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)
    got = pg.evaluate("""(()=>{
        const def=[...document.querySelectorAll('.ckrow.ckdef')];
        const sub=[...document.querySelectorAll('.ckrow:not(.ckdef)')];
        return {defaults:def.length,
                defaultsWithFont:def.filter(r=>r.querySelector('select.fontsel')).length,
                subsWithFont:sub.filter(r=>r.querySelector('select.fontsel')).length,
                subs:sub.length,
                saysDefault:def.filter(r=>/the default/.test(r.textContent)).length};})()""")
    assert got["defaults"] == 3
    assert got["defaultsWithFont"] == 3, "a main type has nowhere to set its face"
    assert got["subsWithFont"] == got["subs"]
    assert got["saysDefault"] == 0, '"the default" is still written on the row'
    assert not errs, errs[:2]


def test_the_font_section_no_longer_asks_the_same_thing_again():
    from pathlib import Path
    html = (PKG / "static"
            / "editor.html").read_text(encoding="utf8")
    for gone in ("Font — balloons", "Font — outside text", "Font — sound effects"):
        assert gone not in html, gone
    # the selects themselves stay, hidden - saveSettings reads them
    for keep in ('id="font"', 'id="font_freefloat"', 'id="font_sfx"'):
        assert keep in html, keep


def test_setting_a_main_types_font_from_its_row_sticks(ed):
    pg, p, errs = ed
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)
    ok = pg.evaluate("""(async ()=>{
        const rows=[...document.querySelectorAll('.ckrow.ckdef')];
        const sel=rows[2].querySelector('select.fontsel');   // sound effect
        const opt=[...sel.options].find(o=>o.value);
        if(!opt) return 'no fonts';
        setFamilyFont('sfx', opt.value);
        return opt.value;})()""")
    if ok == "no fonts":
        pytest.skip("no fonts available to pick")
    pg.wait_for_timeout(900)
    assert (p.settings.get("fonts") or {}).get("sfx") == ok
    assert not errs, errs[:2]


# ------------------------------------------------------------ the text boxes

def test_the_text_boxes_fit_their_text_and_have_no_grip(ed):
    pg, _p, errs = ed
    _original(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(600)
    got = pg.evaluate("""[...document.querySelectorAll('#list .rinline textarea')]
        .map(t=>({resize:getComputedStyle(t).resize,
                  h:Math.round(t.getBoundingClientRect().height),
                  need:t.scrollHeight}))""")
    assert got, "no text boxes in the region editor"
    for t in got:
        assert t["resize"] == "none", t
        assert t["h"] + 3 >= t["need"], f"the text is taller than its box: {t}"
    # the English on this page is long, so its box must be the taller of the two
    assert max(t["h"] for t in got) > min(t["h"] for t in got)
    assert not errs, errs[:2]


def test_a_box_grows_as_you_type(ed):
    pg, _p, errs = ed
    _original(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(600)
    grew = pg.evaluate("""(()=>{
        const t=document.querySelectorAll('#list .rinline textarea')[0];
        const was=t.getBoundingClientRect().height;
        t.value=('MORE WORDS '.repeat(40));
        t.dispatchEvent(new Event('input',{bubbles:true}));
        return [was, t.getBoundingClientRect().height];})()""")
    assert grew[1] > grew[0], grew
    assert not errs, errs[:2]


# ------------------------------------------------------------ the layer list

def test_the_text_block_starts_folded_and_its_rows_have_no_numbers(ed):
    pg, _p, errs = ed
    pg.evaluate("setTab('edit'); setView('typeset')")
    browserpool.settled(pg)
    assert pg.evaluate("textShut") is True
    assert pg.evaluate(
        "document.querySelectorAll('#stackList .textrow .lth-glyph').length") == 0
    assert pg.evaluate(
        "!!document.querySelector('#stackList .textband.shut')") is True
    # ...and unfolding still works
    pg.evaluate("toggleTextFold()")
    pg.wait_for_timeout(300)
    assert pg.evaluate("!document.querySelector('#stackList .textband.shut')")
    assert not errs, errs[:2]


# ------------------------------------------------------- dragging to renumber

def _drag_row(pg, frm, to, grab=".chip.num"):
    # The rows on this page carry long lines, so the one being dragged can be
    # below the fold - a press at coordinates outside the window is not a
    # press at all.
    pg.evaluate(f"""document.querySelectorAll('#list .lrow')[{to}]
        .scrollIntoView({{block:'center'}})""")
    pg.wait_for_timeout(200)
    g = pg.evaluate(f"""(()=>{{const rows=[...document.querySelectorAll('#list .lrow')];
      const a=rows[{frm}].querySelector('{grab}').getBoundingClientRect();
      const b=rows[{to}].getBoundingClientRect();
      return {{ax:a.left+a.width/2, ay:a.top+a.height/2,
              bx:b.left+40, by:b.top+8}};}})()""")
    pg.mouse.move(g["ax"], g["ay"])
    pg.mouse.down()
    pg.mouse.move(g["bx"], g["by"], steps=12)
    pg.wait_for_timeout(150)
    pg.mouse.up()
    pg.wait_for_timeout(1100)


def _order(pg):
    return pg.evaluate("regions.slice().sort((a,b)=>a.order-b.order).map(r=>r.id)")


def test_a_row_can_be_dragged_by_its_number(ed):
    """The handle used to be the three-dot grip and nothing else - nine pixels
    of a card the size of a paragraph. lee: *"on teh original tab i lost teh
    ability to drag the tab to chnge tehre numbering"*."""
    pg, _p, errs = ed
    _original(pg)
    assert _order(pg) == [1, 2, 3, 4]
    _drag_row(pg, 2, 0)
    assert _order(pg) == [3, 1, 2, 4], _order(pg)
    assert not errs, errs[:2]


def test_it_can_still_be_dragged_by_the_type_chip(ed):
    """Any part of the head, not just the number - the three-dot grip that
    used to be the only handle is gone."""
    pg, _p, errs = ed
    _original(pg)
    _drag_row(pg, 3, 0, grab=".chip.kind")
    assert _order(pg) == [4, 1, 2, 3], _order(pg)
    assert not errs, errs[:2]


def test_the_new_order_reaches_the_server(ed):
    pg, p, errs = ed
    _original(pg)
    _drag_row(pg, 2, 0)
    pg.wait_for_timeout(600)
    got = sorted(p.pages[0].regions, key=lambda r: r["order"])
    assert [r["id"] for r in got] == [3, 1, 2, 4], [r["id"] for r in got]
    assert not errs, errs[:2]


def test_the_text_in_a_row_can_still_be_selected(ed):
    """Which is what the grip-only rule was protecting. A card that starts a
    drag on any press cannot have a word copied out of it."""
    pg, _p, errs = ed
    _original(pg)
    picked = pg.evaluate("""(()=>{
        const t=document.querySelector('#list .lrow .tx');
        const r=document.createRange(); r.selectNodeContents(t);
        const s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
        return String(s).trim().length>0;})()""")
    assert picked is True
    assert pg.evaluate(
        "[...document.querySelectorAll('#list .lrow')].every(r=>!r.draggable)")
    assert not errs, errs[:2]


# --------------------------------------------------- the reading-detail tabs
#
# lee, on being shown that the zoomed read is what makes a chapter dear:
# *"can you bring back teh 1, 4 and 9 cut and make them tabs instad of drop
# down"*, and then *"if teh user clcik on 1,4,or 9 sissble teh settings that
# only works with zoomed in boxes"*.

def test_the_reading_detail_is_four_tabs_that_carry_their_price(ed):
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('detection')")
    browserpool.settled(pg)
    got = pg.evaluate("""(()=>{
      const b=document.getElementById('detailCards');
      if(!b) return null;
      return [...b.querySelectorAll('.card')].map(c=>({
        k:c.dataset.detail, name:c.querySelector('b').textContent,
        cost:c.querySelector('i').textContent,
        on:c.classList.contains('on')}));})()""")
    assert got, "the reading-detail tabs are not on the screen"
    assert [g["k"] for g in got] == ["page", "auto", "high", "boxes"], got
    # cheapest first, and each says what it sends - which is the whole reason
    # the choice came back
    assert "1 picture" in got[0]["cost"], got
    assert "a box" in got[-1]["cost"], got
    # zoomed is what a project with nothing chosen is really doing
    assert [g["on"] for g in got] == [False, False, False, True], got
    assert not errs, errs[:3]


def test_picking_a_cut_up_page_greys_the_settings_that_need_a_close_up(ed):
    """Read in pieces a line can be filed under the wrong box - 16 of 225 at
    four pieces, measured - so a rule that changes a box's TYPE from the words
    filed under it is not safe. It greys rather than disappearing: the setting
    keeps its value and picking zoomed again finds it where it was."""
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('detection')")
    browserpool.settled(pg)
    state = lambda: pg.evaluate("""(()=>{
      const el=document.getElementById('retype_kinds');
      const row=el?el.closest('label'):null;
      return {disabled:!!(el&&el.disabled),
              greyed:!!(row&&row.classList.contains('offx')),
              checked:!!(el&&el.checked)};})()""")
    pg.evaluate("document.getElementById('retype_kinds').checked=true")
    pg.evaluate("pickDetail('high')")
    pg.wait_for_timeout(150)
    off = state()
    assert off["disabled"] and off["greyed"], off
    assert off["checked"], "the setting lost its value instead of greying"
    pg.evaluate("pickDetail('boxes')")
    pg.wait_for_timeout(150)
    on = state()
    assert not on["disabled"] and not on["greyed"], on
    assert on["checked"], "picking zoomed again did not find it as it was"
    assert not errs, errs[:3]


def test_the_reading_detail_is_saved_and_reaches_the_price(ed):
    """A tab that does not change the bill is a picture of a tab."""
    from mangatl import coins, editor
    pg, p, _errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('detection')")
    pg.evaluate("pickDetail('page')")
    pg.wait_for_timeout(400)
    assert pg.evaluate("proj.settings.ocr_detail") == "page"
    cheap = coins.usd_page("ocr", 10, "gemini-3.7-flash", "google",
                           detail="page")
    dear = coins.usd_page("ocr", 10, "gemini-3.7-flash", "google",
                          detail="boxes")
    assert dear > cheap * 3, (cheap, dear)
