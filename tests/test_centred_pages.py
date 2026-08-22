"""The full-window pages read like the Add pages screen.

lee: *"Change the settings layout make it like the add page with a center focus
do it to both settings pages and the results pages"* and *"Change the add pages
so it's 2 pages, add the pages , next, add json, with done or skip button"*.

Two separate things, measured the same way - by asking the browser where things
actually ended up, not by reading the stylesheet. A rule that is present and
overridden is a rule that is not there.

Settings, Manga settings and Results were all left-aligned against a 224px nav
and capped at 600px, so on any normal screen the eye started a third of the way
in and the right half of the window was empty. They are centred on a card now.

Add pages asked three questions at once - what language, which pages, and do
you have a settings file - with the .json button sitting between the two "add
pages" buttons as though it were a third way of adding pages. It is now two
screens: pages, Next; then the settings file, Done or Skip.
"""
import json
import os
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")


def _serve(fn, root=scratch("_tmp_centred"), pages=3, exported=0, own=True):
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 420, 3), 245, np.uint8)
    for k in range(pages):
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
    if exported:
        out = os.path.join(root, "pages")
        os.makedirs(out, exist_ok=True)
        for k in range(exported):
            cv2.imwrite(os.path.join(out, f"p{k}.png"), img)
        # Files in the folder are not enough: the project has to have been the
        # one that put them there. The export folder outlives a chapter, so a
        # new project pointed at it would otherwise inherit the last one's
        # results. See `exported` in editor.py.
        if own:
            p.settings["exported"] = True
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


# `left` and `right` are the gaps between the content and the space it sits in.
# Equal gaps is what "centred" means and is the only thing worth asserting: a
# max-width, a margin and a flex rule can all be present and still lose to
# something else.
_GAPS = """(args)=>{
   const [sel, holder] = args;
   const a=document.querySelector(sel).getBoundingClientRect();
   const b=document.querySelector(holder).getBoundingClientRect();
   return {left: Math.round(a.left-b.left), right: Math.round(b.right-a.right),
           width: Math.round(a.width)};}"""


_BOX = """(args)=>{
   const [sel, holder] = args;
   const a=document.querySelector(sel).getBoundingClientRect();
   const b=document.querySelector(holder).getBoundingClientRect();
   return {left: Math.round(a.left-b.left), right: Math.round(b.right-a.right),
           top: Math.round(a.top-b.top), bottom: Math.round(b.bottom-a.bottom),
           width: Math.round(a.width), height: Math.round(a.height)};}"""


@pytest.mark.parametrize("tab,card", [
    ("setTab('settings'); setSettingsTab('fonts')", "#settingsPage .setcard"),
    ("setTab('settings'); setSettingsTab('synopsis')", "#settingsPage .setcard"),
])
def test_the_settings_card_is_centred_both_ways(tab, card):
    """lee: *"the cenetr page shoud be center verticsaly and horizontaly"*."""
    def check(pg, p):
        pg.evaluate(tab)
        pg.wait_for_timeout(700)
        g = pg.evaluate(_BOX, [card, card.split(" ")[0]])
        assert abs(g["left"] - g["right"]) <= 2, g
        assert abs(g["top"] - g["bottom"]) <= 2, g
        assert g["left"] > 60, f"still hard against the edge: {g}"
    _serve(check)


@pytest.mark.parametrize("tab,nav,card", [
    ("setTab('settings')", "#setNav", "#settingsPage .setcard"),
    ("setTab('settings'); setSettingsTab('synopsis')", "#setNav",
     "#settingsPage .setcard"),
])
def test_the_nav_is_inside_the_card_not_beside_it(tab, nav, card):
    """lee: *"the side bar shoud be intergrated with the center"*.

    It was a full-height column against the left edge of the window with the
    content floating separately to its right - two things, and the eye had to
    cross a gap between them."""
    def check(pg, p):
        pg.evaluate(tab)
        pg.wait_for_timeout(700)
        g = pg.evaluate(_BOX, [nav, card])
        # 1px each side is the card's own border; the nav is flush inside it.
        assert g["left"] <= 2 and g["top"] <= 2 and g["bottom"] <= 2, g
        assert g["width"] < 260, f"a full-width nav is not inside anything: {g}"
        assert g["right"] > 300, f"the nav is not beside the content: {g}"
    _serve(check)


@pytest.mark.parametrize("tab,card", [
    ("setTab('settings')", "#settingsPage .setcard"),
    # Was `setSettingsTab('project')` - a Settings screen for files, which is
    # gone; everything a file does is under File now. Any other section makes
    # the same point, which is that the card's foot follows the section.
    ("setTab('settings'); setSettingsTab('cleaning')", "#settingsPage .setcard"),
])
def test_save_and_cancel_end_the_card_at_the_bottom_right(tab, card):
    """lee: *"the save an cancel button shoud be at teh bttom right"*.

    They were pinned to the foot of the nav column on the far left - a whole
    screen away from the last control you touched."""
    def check(pg, p):
        pg.evaluate(tab)
        pg.wait_for_timeout(700)
        g = pg.evaluate(_BOX, [f"{card} .setfoot", card])
        assert g["bottom"] <= 2, g
        buttons = pg.evaluate(f"""(()=>{{
            const f=document.querySelector('{card} .setfoot');
            const b=[...f.querySelectorAll('button')];
            const r=f.getBoundingClientRect();
            return {{names: b.map(x=>x.textContent.trim()),
                     rightGap: Math.round(
                       r.right - b[b.length-1].getBoundingClientRect().right)}};
            }})()""")
        assert buttons["names"][0] == "Cancel", buttons
        assert "Save" in buttons["names"][-1], buttons
        assert buttons["rightGap"] <= 26, buttons
    _serve(check)


def test_the_save_button_does_not_need_you_to_scroll_to_it():
    """Outside the scrolling body on purpose. Fonts & typesetting is longer than
    the card, and a Save at the end of it is a Save you have to go looking
    for."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const body=document.getElementById('setBody');
            const f=document.querySelector('#settingsPage .setfoot');
            const c=document.querySelector('#settingsPage .setcard')
                     .getBoundingClientRect();
            const r=f.getBoundingClientRect();
            return {scrolls: body.scrollHeight > body.clientHeight + 4,
                    inside: r.bottom <= c.bottom + 1 && r.top >= c.top - 1,
                    tall: r.height > 0};})()""")
        assert got["scrolls"], "pick a section long enough to scroll"
        assert got["inside"] and got["tall"], got
    _serve(check)


def test_the_card_is_the_only_card():
    """The section used to carry its own panel background and border. Inside a
    card that is a box in a box."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const s=getComputedStyle(document.querySelector('.set-section.on'));
            const c=getComputedStyle(
                document.querySelector('#settingsPage .setcard'));
            const pk=getComputedStyle(document.querySelector('.filecard'));
            return {section:s.borderTopWidth, cardBg:c.backgroundColor,
                    pkBg:pk.backgroundColor,
                    radius:parseFloat(c.borderTopLeftRadius)};})()""")
        assert got["section"] == "0px", got
        # The File screen is a card with a section rail now, exactly as this
        # one is, and `.pk` inside it is a section - so the card to compare
        # against is `.filecard`. A panel background on `.pk` as well would be
        # the box in a box this test exists to catch.
        assert got["cardBg"] == got["pkBg"], got
        assert pg.evaluate(
            "getComputedStyle(document.querySelector('.pk')).backgroundColor"
        ) in ("rgba(0, 0, 0, 0)", "transparent")
        assert got["radius"] >= 8, got
    _serve(check)


def test_only_one_settings_section_is_on_screen_at_a_time():
    """Centring them all in a column would stack five pages of settings under
    each other and make the nav do nothing."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('detection')")
        browserpool.settled(pg)
        n = pg.evaluate("""document.querySelectorAll('#setBody .set-section')
            .length && [...document.querySelectorAll('#setBody .set-section')]
            .filter(s=>s.getBoundingClientRect().height>0).length""")
        assert n == 1, n
    _serve(check)


def test_the_exported_pages_are_centred_rather_than_pushed_left():
    """With four pages and room for seven the grid kept the three empty columns
    and packed everything against the left edge."""
    def check(pg, p):
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        g = pg.evaluate("""(()=>{
            const cards=[...document.querySelectorAll('.rcard')];
            const b=document.querySelector('#results').getBoundingClientRect();
            const l=Math.min(...cards.map(c=>c.getBoundingClientRect().left));
            const r=Math.max(...cards.map(c=>c.getBoundingClientRect().right));
            return {n:cards.length, left:Math.round(l-b.left),
                    right:Math.round(b.right-r)};})()""")
        assert g["n"] == 3, g
        assert abs(g["left"] - g["right"]) <= 4, g
    _serve(check, exported=3)


def test_a_result_card_does_not_grow_to_fill_the_window():
    """Three pages across a wide screen used to become three enormous ones."""
    def check(pg, p):
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        w = pg.evaluate(
            "document.querySelector('.rcard').getBoundingClientRect().width")
        assert w <= 245, w
    _serve(check, exported=3)


def test_nothing_exported_yet_reads_as_a_sentence_not_a_caption():
    """The empty line is a flex item too. Left as one item of a centred row it
    sits under a page that is not there.

    Reachable when the export folder is emptied on disk under an app that has
    already been there - the tab itself is shut until something is exported."""
    def check(pg, p):
        import os
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        out = os.path.join(p.output_dir, "pages")
        for f in os.listdir(out):
            os.remove(os.path.join(out, f))
        pg.evaluate("loadResults()")
        pg.wait_for_timeout(800)
        g = pg.evaluate(_GAPS, ["#results p", "#results"])
        assert abs(g["left"] - g["right"]) <= 4, g
    _serve(check, exported=1)


# ------------------------------------------------------ add pages, in two

def test_it_opens_on_the_pages_step():
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        assert pg.evaluate("pkStepNow") == 1
        assert pg.evaluate(
            "document.querySelector('#pkTitle').textContent") == "Open a chapter"
        assert pg.evaluate(
            "document.querySelector('.pkstep[data-step=\"2\"]')"
            ".getBoundingClientRect().height") == 0
    _serve(check)


def test_the_settings_file_is_not_asked_for_on_the_first_screen():
    """It used to sit between the two "add pages" buttons, reading as a third
    way of adding pages."""
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        inside = pg.evaluate("""(()=>{
            const one=document.querySelector('.pkstep[data-step="1"]');
            return !!one.querySelector('#impSetPk, #dropJson');})()""")
        assert inside is False
    _serve(check)


def test_next_carries_the_staged_pages_and_moves_on(tmp_path):
    shot = tmp_path / "a.png"
    cv2.imwrite(str(shot), np.full((300, 200, 3), 240, np.uint8))

    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        pg.set_input_files("#ffile", [str(shot)])
        pg.wait_for_timeout(600)
        assert pg.evaluate(
            "document.querySelector('#loadBtn').textContent") == "Next"
        pg.click("#loadBtn")
        pg.wait_for_timeout(2500)
        assert pg.evaluate("pkStepNow") == 2, "it did not go on to the second"
        assert len(p.pages) == 1, "the page did not load"
        assert pg.evaluate(
            "document.getElementById('picker').classList.contains('on')"), \
            "it closed instead of asking the second question"
    _serve(check, pages=0)


def test_next_with_nothing_staged_says_so_on_an_empty_project():
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        pg.click("#loadBtn")
        pg.wait_for_timeout(400)
        assert pg.evaluate("pkStepNow") == 1
        assert "Add some pages" in pg.evaluate(
            "document.getElementById('pkmsg').textContent")
    _serve(check, pages=0)


def test_next_moves_on_when_the_chapter_is_already_loaded():
    """Opening this again on a chapter that is loaded is a real thing to do -
    you came back for the settings file. A Next that refused would leave no way
    to reach the second screen at all."""
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        pg.click("#loadBtn")
        pg.wait_for_timeout(500)
        assert pg.evaluate("pkStepNow") == 2
    _serve(check, pages=3)


def test_skip_closes_it():
    """The way off this screen when you have no settings file, which is most
    of the time."""
    def check(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.wait_for_timeout(400)
        pg.click('.pkstep[data-step="2"] >> text="Skip"')
        pg.wait_for_timeout(500)
        assert not pg.evaluate(
            "document.getElementById('picker').classList.contains('on')")
    _serve(check)


def test_done_does_nothing_until_a_file_has_been_added():
    """lee: *"done shoud not work if no file was uploaded"*.

    Done and Skip both closed the screen, and Done was the primary - the yellow
    one, the one you press. So the ordinary way through was to press the button
    that means "I added the file" without having added one, and never find out
    the settings had not come in.
    """
    def check(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.wait_for_timeout(400)
        assert pg.evaluate("document.getElementById('pkDoneBtn').disabled")
        pg.click('#pkDoneBtn', force=True)
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "document.getElementById('picker').classList.contains('on')"), \
            "Done closed the screen with no file added"
    _serve(check)


def test_done_works_once_a_file_is_in(tmp_path):
    f = tmp_path / "proj.json"
    f.write_text(json.dumps({"target": "fr"}))

    def check(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.wait_for_timeout(300)
        pg.set_input_files("#impSetPk", [str(f)])
        pg.wait_for_timeout(1500)
        assert not pg.evaluate("document.getElementById('pkDoneBtn').disabled")
        pg.click("#pkDoneBtn")
        pg.wait_for_timeout(500)
        assert not pg.evaluate(
            "document.getElementById('picker').classList.contains('on')")
    _serve(check)


def test_a_file_that_will_not_read_does_not_open_done(tmp_path):
    """A file that was refused is not a file added."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json")

    def check(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.wait_for_timeout(300)
        pg.set_input_files("#impSetPk", [str(bad)])
        pg.wait_for_timeout(1200)
        assert pg.evaluate("document.getElementById('pkDoneBtn').disabled"), \
            "a file that would not read opened Done anyway"
        assert "Could not read" in pg.evaluate(
            "document.getElementById('pkJsonMsg').textContent")
    _serve(check)


def test_done_ships_shut():
    """`pkStep` shuts it, and `showPicker` calls `pkStep`. But the markup says
    so as well: a button whose only closed state comes from a script is open
    for as long as that script has not run - and one broken file above it in
    editor.html is enough for that to be for ever."""
    from pathlib import Path
    html = (PKG / "static"
            / "editor.html").read_text(encoding="utf8")
    i = html.index('id="pkDoneBtn"')
    assert "disabled" in html[i - 120:i + 120], html[i - 120:i + 120]


def test_done_shuts_again_for_the_next_chapter():
    """Import once, start a new chapter, and Done must not still be open from
    the file the LAST one imported."""
    def check(pg, p):
        pg.evaluate("""(()=>{const d=document.getElementById('pkDoneBtn');
            d.disabled=false;})()""")
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        assert pg.evaluate("pkStepNow") == 1
        assert pg.evaluate("document.getElementById('pkDoneBtn').disabled")
    _serve(check)


def test_back_returns_to_the_pages():
    def check(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.wait_for_timeout(300)
        pg.click('.pkstep[data-step="2"] >> text="Back"')
        pg.wait_for_timeout(300)
        assert pg.evaluate("pkStepNow") == 1
    _serve(check)


def test_a_settings_file_chosen_on_the_second_screen_goes_in(tmp_path):
    f = tmp_path / "proj.json"
    f.write_text(json.dumps({"medium": "manhwa", "target": "es"}))

    def check(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.wait_for_timeout(300)
        pg.set_input_files("#impSetPk", [str(f)])
        pg.wait_for_timeout(1500)
        assert p.settings.get("medium") == "manhwa", p.settings.get("medium")
        assert "Imported" in pg.evaluate(
            "document.getElementById('pkJsonMsg').textContent")
    _serve(check)


def test_adding_more_pages_later_does_not_reopen_the_dialog(tmp_path):
    """The two screens are for STARTING a chapter. "+ Add pages" on a chapter
    already open must not put a settings-file question in the way - and must
    not clear the chapter it is adding to."""
    shot = tmp_path / "extra.png"
    cv2.imwrite(str(shot), np.full((300, 200, 3), 240, np.uint8))

    def check(pg, p):
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        was = len(p.pages)
        pg.set_input_files("#faddm", [str(shot)])
        pg.wait_for_timeout(2500)
        assert len(p.pages) == was + 1, (was, len(p.pages))
        assert not pg.evaluate(
            "document.getElementById('picker').classList.contains('on')"), \
            "it opened the New project screen to add one page"
        assert pg.evaluate("tab") == "edit"
        # ...and the New project screen was not quietly wound on to its second
        # question behind the scenes, waiting to show it the next time it opens.
        assert pg.evaluate("pkStepNow") == 1, "it advanced the wizard anyway"
    _serve(check, pages=2)


# ------------------------------------------------- the top bar follows the tab

def test_the_page_tools_are_only_on_the_edit_tab():
    """lee: *"thsi sjoud only be visible on the edit page"*, of the zoom, snap,
    hide-boxes and Original/Edit strip.

    Every one of those acts on the page on the canvas. Results and both
    settings pages have no canvas, so on those tabs they are controls for
    something that is not there - a 100% button that zooms nothing and an
    Original/Edit pair that appears to say which view you are on when you are
    not on either.
    """
    def check(pg, p):
        seen = {}
        for t in ("edit", "results", "settings"):
            pg.evaluate(f"setTab('{t}')")
            browserpool.settled(pg)
            seen[t] = pg.evaluate(
                "document.getElementById('pageTools')"
                ".getBoundingClientRect().height > 0")
        assert seen == {"edit": True, "results": False,
                        "settings": False}, seen
    _serve(check, exported=1)


def test_the_tabs_themselves_stay_put():
    """The left half of the top bar is how you get back. Hiding the whole bar
    would be a tab strip you cannot reach."""
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        assert pg.evaluate(
            "document.getElementById('tabs').getBoundingClientRect().width") > 0
    _serve(check)


def test_they_come_back_when_you_do():
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        assert pg.evaluate("document.getElementById('zlabel')"
                           ".getBoundingClientRect().width") > 0
    _serve(check)


def test_add_pages_is_not_offered_on_the_results_tab():
    """lee: *"the add page shosud not be visible in teh result page"*.

    Results is the gallery of what came out. Offering to add pages there is an
    editing action on the one screen that is only ever about the finished
    thing - and the page list is shared with the Edit tab, so it came along
    without anybody deciding it should."""
    def check(pg, p):
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        assert pg.evaluate(
            "!!document.querySelector('#pages .addbtn:not(.selbtn)')"), \
            "it went missing where it belongs"
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        assert not pg.evaluate(
            "!!document.querySelector('#pages .addbtn:not(.selbtn)')")
    _serve(check, exported=1)


def test_the_page_list_itself_stays_on_results():
    """You still click a page there to jump to it."""
    def check(pg, p):
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        assert pg.evaluate("document.querySelectorAll('#pages .pg').length") == 3
    _serve(check, exported=1)


def test_it_comes_back_on_the_edit_tab():
    def check(pg, p):
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        assert pg.evaluate(
            "!!document.querySelector('#pages .addbtn:not(.selbtn)')")
    _serve(check, exported=1)


def test_the_top_bar_is_reachable_from_the_add_pages_screen():
    """lee: *"the add page shoud have this top bar be visible"*.

    It used to cover the whole window - brand, Add pages, and all four tabs -
    so from that screen there was no way to Edit, Results or Settings at all.
    The Close button is the only way out and it is not shown until a chapter is
    loaded, which is exactly when you are least able to get anywhere."""
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(500)
        got = pg.evaluate("""(()=>{
            const t=document.getElementById('top').getBoundingClientRect();
            const mid=document.elementFromPoint(
                Math.round(t.left+t.width/2), Math.round(t.top+t.height/2));
            const tab=document.getElementById('tabSet');
            const r=tab.getBoundingClientRect();
            const hit=document.elementFromPoint(
                Math.round(r.left+r.width/2), Math.round(r.top+r.height/2));
            const pk=document.querySelector('.filecard').getBoundingClientRect();
            return {overBar: document.getElementById('top').contains(mid),
                    tabClickable: hit === tab || tab.contains(hit),
                    above: Math.round(pk.top - t.bottom),
                    below: Math.round(innerHeight - pk.bottom)};})()""")
        assert got["overBar"], "the picker is drawn over the top bar"
        assert got["tabClickable"], "a tab cannot be clicked through it"
        assert got["above"] >= 0, got
        # Centred in the room BELOW the bar, not in the whole window - the
        # difference only shows once the card is tall enough that half of it
        # would reach up behind the bar, and then it is the top of the card
        # that goes missing.
        assert abs(got["above"] - got["below"]) <= 2, got
    _serve(check)


def test_a_tab_pressed_from_the_add_pages_screen_gets_you_there():
    """Visible and dead is worse than hidden."""
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(500)
        pg.click("#tabSet")
        pg.wait_for_timeout(600)
        assert pg.evaluate("tab") == "settings"
    _serve(check)


# ------------------------------------------------ New project, and only that

def test_the_top_button_says_what_it_does():
    """lee: *"rename it from add paeg to new project"*.

    It never added pages to the chapter you have open - it opens the screen
    that starts a new one, and starting one throws the old one away. "Add
    pages" is the button on the page list, which is a different thing."""
    from pathlib import Path
    html = (PKG / "static"
            / "editor.html").read_text(encoding="utf8")
    assert '>New project</button>' in html
    assert '>Add pages</button>' not in html


def test_there_is_no_separate_clear_this_project():
    """lee: *"remoev teh close this project it shoud do it by default"*.

    Loading pages already resets - a red button next to it offering to do the
    same thing first reads as something you have to remember to press."""
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        assert pg.evaluate("!document.getElementById('pkClear')")
    _serve(check)


def test_starting_a_chapter_clears_the_last_one_s_content(tmp_path):
    """The custom text types and where the last chapter exported to belong to
    the chapter just finished. Fonts and the translation engine do not - you
    would be setting those up again every time."""
    shot = tmp_path / "a.png"
    cv2.imwrite(str(shot), np.full((300, 200, 3), 240, np.uint8))

    def check(pg, p):
        p.settings["custom_kinds"] = [{"key": "narrator_b", "label": "B",
                                       "color": "#2cddd6"}]
        p.settings["export_dir"] = "/somewhere/old"
        p.settings["min_font"] = 17           # a typesetting setting, kept
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        pg.set_input_files("#ffile", [str(shot)])
        pg.wait_for_timeout(600)
        pg.click("#loadBtn")
        pg.wait_for_timeout(2500)
        assert not p.settings.get("custom_kinds"), p.settings.get("custom_kinds")
        assert not p.settings.get("export_dir"), p.settings.get("export_dir")
        assert p.settings.get("min_font") == 17, "it forgot the typesetting too"
    _serve(check, pages=1)


def test_the_choices_made_on_that_screen_survive_the_clearing(tmp_path):
    """The reset happens between choosing the language and the pages landing.
    Saving those four choices BEFORE it meant the reset put them back to what
    the last chapter used."""
    shot = tmp_path / "a.png"
    cv2.imwrite(str(shot), np.full((300, 200, 3), 240, np.uint8))

    def check(pg, p):
        p.settings["medium"] = "manga"
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        pg.select_option("#pkMedium", "manhwa")
        pg.select_option("#pkTarget", "es")
        pg.set_input_files("#ffile", [str(shot)])
        pg.wait_for_timeout(600)
        pg.click("#loadBtn")
        pg.wait_for_timeout(2500)
        assert p.settings.get("medium") == "manhwa", p.settings.get("medium")
        assert p.settings.get("target") == "es", p.settings.get("target")
    _serve(check, pages=1)


def test_the_folder_on_this_computer_route_is_gone():
    """lee: *"remoe direct fom computer"*. A box you type a path into, on a
    screen that already takes a folder by drag or by button - and the endpoint
    behind it took whatever path it was handed."""
    from pathlib import Path
    root = PKG
    html = (root / "static" / "editor.html").read_text(encoding="utf8")
    js = (root / "static" / "js" / "project-io.js").read_text(encoding="utf8")
    py = (root / "editor.py").read_text(encoding="utf8")
    assert "localpath" not in html
    assert "already on this computer" not in html
    assert "openFolder" not in js, "the handler is still there with no button"
    assert "/api/open_folder" not in py, "the endpoint outlived its screen"


# --------------------------------------------- one Settings page, two groups

def test_there_is_one_settings_page():
    """lee: *"merege the setting into one and have it be into 2 section one
    setting and teh other manga setting or somthing more newtral"*.

    Two full-page tabs with two navs and two Save buttons, both writing through
    the same save - which of them you were on decided nothing except which four
    sections you could reach."""
    from pathlib import Path
    root = PKG
    html = (root / "static" / "editor.html").read_text(encoding="utf8")
    assert 'id="mangaPage"' not in html
    assert 'id="mangaNav"' not in html
    assert 'id="mangaBody"' not in html
    assert 'id="tabManga"' not in html


def test_the_group_is_not_called_manga():
    """The app does manhwa and manhua too, and none of those sections are about
    manga in particular. lee: *"somthing more newtral that donrt have teh word
    manga in it"*."""
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        heads = pg.evaluate(
            "[...document.querySelectorAll('#setNav .setnav-title')]"
            ".map(e=>e.textContent.trim())")
        assert len(heads) == 2, heads
        # Story first: it is the chapter you are working on. The editor's own
        # configuration is the thing you set up once and leave alone.
        # lee: *"put teh story section above teh setting section"*.
        assert heads[1] == "Settings", heads
        assert "anga" not in heads[0], heads
        assert heads[0] == "Story", heads
    _serve(check)


def test_every_section_is_reachable_from_the_one_nav():
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        # "project" was here - a Settings screen for the series file. It is
        # gone; everything a FILE does is under File now, next to the chapter
        # file. lee: *"move the import to the file tab and remove this tab"*.
        for sec in ("fonts", "language", "detection", "translation", "cleaning",
                    "synopsis", "characters", "terms"):
            pg.evaluate(f"setSettingsTab('{sec}')")
            pg.wait_for_timeout(120)
            got = pg.evaluate(
                "(document.querySelector('#setBody .set-section.on')||{})"
                ".dataset && document.querySelector('#setBody .set-section.on')"
                ".dataset.sec")
            assert got == sec, (sec, got)
    _serve(check)


def test_the_old_name_for_the_story_page_still_lands_somewhere():
    """`setTab('manga')` was the way in for two years of muscle memory and for
    anything else in the app that still calls it."""
    def check(pg, p):
        pg.evaluate("setTab('manga')")
        browserpool.settled(pg)
        assert pg.evaluate("tab") == "settings"
        assert pg.evaluate(
            "document.getElementById('settingsPage')"
            ".getBoundingClientRect().height") > 0
    _serve(check)


def test_the_card_is_the_same_size_whichever_section_is_open():
    """lee: *"ishnta fo the setting pages swithing size it shoud be this size
    and it there more text a side scroll bar shoud appear"*.

    Fonts & typesetting is five times the height of Synopsis, and the card
    resized to each of them - so moving between two sections moved everything
    on screen, including the Save button."""
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        sizes = {}
        for sec in ("fonts", "synopsis", "cleaning", "characters"):
            pg.evaluate(f"setSettingsTab('{sec}')")
            pg.wait_for_timeout(200)
            sizes[sec] = pg.evaluate(
                "Math.round(document.querySelector('#settingsPage .setcard')"
                ".getBoundingClientRect().height)")
        assert len(set(sizes.values())) == 1, sizes
    _serve(check)


def test_a_long_section_scrolls_inside_the_card():
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const b=document.getElementById('setBody');
            return {scrolls: b.scrollHeight > b.clientHeight + 4,
                    overflow: getComputedStyle(b).overflowY};})()""")
        assert got["scrolls"], got
        assert got["overflow"] in ("auto", "scroll"), got
    _serve(check)


def test_the_footer_is_the_same_colour_as_the_body_above_it():
    """lee: *"the bottom piec shoud math the colro above it background"*. A
    darker strip read as a different surface stuck to the bottom of the card."""
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const f=getComputedStyle(document.querySelector('.setfoot'));
            const c=getComputedStyle(
                document.querySelector('#settingsPage .setcard'));
            return [f.backgroundColor, c.backgroundColor];})()""")
        assert got[0] == got[1], got
    _serve(check)


# ------------------------------------------------- New project lights up

def test_the_new_project_button_lights_up_while_that_screen_is_open():
    """lee: *"the top bar shoud work on the add pages so if im on te add page
    it shiud be yellow"*."""
    def check(pg, p):
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        assert not pg.evaluate(
            "document.querySelector('.addpages-top').classList.contains('on')")
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "document.querySelector('.addpages-top').classList.contains('on')")
        # Light the Settings tab too and let its colour settle: buttons carry a
        # transition now, so a colour read in the same tick as the class change
        # is the colour it is animating FROM.
        pg.evaluate("document.getElementById('tabSet').classList.add('on')")
        pg.wait_for_timeout(300)
        assert pg.evaluate("""(()=>{
            const a=getComputedStyle(document.querySelector('.addpages-top'));
            const t=getComputedStyle(document.getElementById('tabSet'));
            return a.backgroundColor === t.backgroundColor;})()"""), \
            "not the tab's yellow"
    _serve(check)


def test_it_goes_out_again_when_that_screen_closes():
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        pg.evaluate("showPicker(false)")
        pg.wait_for_timeout(300)
        assert not pg.evaluate(
            "document.querySelector('.addpages-top').classList.contains('on')")
    _serve(check)


def test_close_ends_the_row_on_the_left():
    """lee: *"close shoud be at teh bottom left"*. It was up beside the title,
    which is where a dialog's dismiss goes - but this screen has a row of
    buttons at the bottom and Close belongs in it."""
    def check(pg, p):
        pg.evaluate("showPicker(true)")
        pg.wait_for_timeout(400)
        g = pg.evaluate("""(()=>{
            const f=document.querySelector('.pkstep.on .pkfoot');
            const c=document.getElementById('pkClose');
            const n=document.getElementById('loadBtn');
            return {inFoot: f.contains(c),
                    leftOfNext: c.getBoundingClientRect().right
                              < n.getBoundingClientRect().left,
                    gap: Math.round(c.getBoundingClientRect().left
                                    - f.getBoundingClientRect().left)};})()""")
        assert g["inFoot"] and g["leftOfNext"], g
        assert g["gap"] <= 4, g
    _serve(check)


# ------------------------------------------------- Results, once there is one

def test_the_results_tab_is_shut_until_something_is_exported():
    """lee: *"the resulat page shoud be empty until the project is exported and
    it hsoud not be accassel uptil the user export"*.

    Unlocked for exactly one round on *"the result tab shoud be unloacked"*,
    and shut again on the next message: *"re lock the results page after export
    is doen"*."""
    def check(pg, p):
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "document.getElementById('tabRes').classList.contains('off')")
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        assert pg.evaluate("tab") == "edit", "it went there anyway"
    _serve(check, exported=0)


def test_it_opens_once_there_is_something_there():
    def check(pg, p):
        pg.wait_for_timeout(500)
        assert not pg.evaluate(
            "document.getElementById('tabRes').classList.contains('off')")
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        assert pg.evaluate("tab") == "results"
    _serve(check, exported=2)


# ------------------------------------------- a shut tab says why, on the press

def test_a_shut_tab_can_still_be_pressed():
    """`disabled` swallows the click, and the click is the moment the person
    asked the question. lee: *"add and error pop up explaining whya p page is
    not assible when a peson try to clcik on them"*."""
    def check(pg, p):
        pg.wait_for_timeout(500)
        for tid in ("tabEdit", "tabRes"):
            assert not pg.evaluate(
                f"document.getElementById('{tid}').disabled"), tid
            assert pg.evaluate(
                f"document.getElementById('{tid}').getAttribute('aria-disabled')"
            ) == "true", tid
    _serve(check, pages=0, exported=0)


@pytest.mark.parametrize("tid,word", [("tabEdit", "pages"),
                                      ("tabRes", "Export")])
def test_pressing_it_says_why_and_what_to_do(tid, word):
    def check(pg, p):
        pg.wait_for_timeout(600)
        pg.click(f"#{tid}", force=True)
        pg.wait_for_timeout(400)
        said = pg.evaluate("document.getElementById('toast').textContent")
        assert word.lower() in said.lower(), (tid, said)
        assert len(said) > 20, said         # a reason, not a refusal
    _serve(check, pages=0, exported=0)


def test_it_says_nothing_when_the_app_moves_you_itself():
    """Saving settings ends with `setTab('edit')`. A toast about missing pages
    there is an answer to a question nobody put."""
    def check(pg, p):
        pg.evaluate("document.getElementById('toast').textContent=''")
        pg.evaluate("setTab('edit')")            # no second argument: not a press
        browserpool.settled(pg)
        assert pg.evaluate(
            "document.getElementById('toast').textContent") == ""
    _serve(check, pages=0, exported=0)


def test_an_open_tab_says_nothing_at_all():
    def check(pg, p):
        pg.wait_for_timeout(600)
        pg.evaluate("document.getElementById('toast').textContent=''")
        pg.click("#tabSet")
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "document.getElementById('toast').textContent") == ""
        assert pg.evaluate("tab") == "settings"
    _serve(check, pages=3, exported=0)


# ------------------------------------------------- Edit needs pages to edit

def test_the_edit_tab_is_shut_with_no_pages():
    """lee: *"al the edit page shoud not be assibisble is therae are no
    pages"*. A canvas with nothing on it and a sidebar about a page that does
    not exist."""
    def check(pg, p):
        pg.wait_for_timeout(600)
        assert pg.evaluate(
            "document.getElementById('tabEdit').classList.contains('off')")
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        assert pg.evaluate("tab") == "new", "it went there anyway"
    _serve(check, pages=0)


def test_with_no_pages_you_land_on_New_project():
    """There is exactly one thing to do, so that is where you start."""
    def check(pg, p):
        pg.wait_for_timeout(800)
        assert pg.evaluate("tab") == "new"
        assert pg.evaluate(
            "document.getElementById('picker').classList.contains('on')")
    _serve(check, pages=0)


def test_the_edit_tab_opens_as_soon_as_there_are_pages():
    def check(pg, p):
        pg.wait_for_timeout(700)
        assert not pg.evaluate(
            "document.getElementById('tabEdit').classList.contains('off')")
        pg.click("#tabEdit")
        pg.wait_for_timeout(500)
        assert pg.evaluate("tab") == "edit"
    _serve(check, pages=2)


# ---------------------------------------------- New project is one of the four

def test_new_project_is_a_tab():
    """lee: *"new project shoud be a tab like teh otheer and only one shoud be
    accesabe at a time"*."""
    def check(pg, p):
        pg.wait_for_timeout(600)
        assert pg.evaluate("""(()=>{
            const b=document.getElementById('tabNew');
            return !!b && document.getElementById('tabs').contains(b)
                && b.classList.contains('tab');})()""")
    _serve(check)


def test_only_one_screen_is_up_at_a_time():
    def check(pg, p):
        pg.evaluate("setTab('settings')")
        browserpool.settled(pg)
        pg.click("#tabNew")
        pg.wait_for_timeout(600)
        got = pg.evaluate("""(()=>({
            tab: tab,
            picker: document.getElementById('picker')
                      .classList.contains('on'),
            settings: document.getElementById('settingsPage')
                        .getBoundingClientRect().height > 0,
            pages: document.getElementById('pages')
                     .getBoundingClientRect().width > 0}))()""")
        assert got == {"tab": "new", "picker": True, "settings": False,
                       "pages": False}, got
    _serve(check)


def test_choosing_another_tab_puts_New_project_away():
    def check(pg, p):
        pg.click("#tabNew")
        pg.wait_for_timeout(500)
        pg.click("#tabSet")
        pg.wait_for_timeout(600)
        assert pg.evaluate("tab") == "settings"
        assert not pg.evaluate(
            "document.getElementById('picker').classList.contains('on')")
        assert not pg.evaluate(
            "document.getElementById('tabNew').classList.contains('on')")
    _serve(check)


def test_that_screen_will_not_close_onto_nothing():
    """Closing it lands on Edit, and Edit is shut with no pages. It stays."""
    def check(pg, p):
        pg.wait_for_timeout(700)
        pg.evaluate("showPicker(false)")
        pg.wait_for_timeout(400)
        assert pg.evaluate("tab") == "new"
        assert pg.evaluate(
            "document.getElementById('picker').classList.contains('on')")
    _serve(check, pages=0)


def test_what_you_can_do_with_a_finished_chapter_is_in_the_top_bar():
    """lee: *"add this to the top bar in the result page to the right and flipe
    the order"*. Above the pages they scrolled away on a long chapter."""
    def check(pg, p):
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const rt=document.getElementById('resultTools');
            const top=document.getElementById('top');
            const b=[...rt.querySelectorAll('button')];
            return {inTopBar: top.contains(rt),
                    shown: rt.getBoundingClientRect().width > 0,
                    order: b.map(x=>x.textContent.trim()),
                    inBody: !!document.querySelector('#results button')};})()""")
        assert got["inTopBar"] and got["shown"], got
        # The middle one was called "Download JSON" until lee pointed out
        # that a file format is not a description of what is in the file:
        # *"replace everywhere it say json with story context"*.
        assert got["order"] == ["Start a new project", "Export story context",
                                "Download all as .zip"], got
        assert not got["inBody"], "they are still drawn above the pages too"
    _serve(check, exported=2)


def test_those_buttons_are_only_on_the_results_tab():
    def check(pg, p):
        for t, want in (("results", True), ("edit", False),
                        ("settings", False)):
            pg.evaluate(f"setTab('{t}')")
            browserpool.settled(pg)
            shown = pg.evaluate("document.getElementById('resultTools')"
                                ".getBoundingClientRect().width > 0")
            assert shown is want, (t, shown)
    _serve(check, exported=2)


def test_the_pages_are_not_flush_against_the_edges():
    """lee: *"add some padding at teh top and bottom of the result page"*."""
    def check(pg, p):
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        pad = pg.evaluate("""(()=>{
            const s=getComputedStyle(document.getElementById('results'));
            return [parseFloat(s.paddingTop), parseFloat(s.paddingBottom)];})()""")
        assert pad[0] >= 16 and pad[1] >= 16, pad
    _serve(check, exported=2)


def test_a_new_project_does_not_inherit_the_last_one_s_results():
    """lee: *"teh resulat page is still avalable in a new project"*.

    The export folder is a place on disk and outlives the chapter that filled
    it. Counting the files in it meant a brand new project opened with a
    Results tab full of somebody else's pages."""
    def check(pg, p):
        pg.wait_for_timeout(700)
        assert pg.evaluate(
            "document.getElementById('tabRes').classList.contains('off')")
        j = pg.evaluate("fetch('/api/exported').then(r=>r.json())")
        assert j["files"] == [], j
    _serve(check, exported=3, own=False)


def test_exporting_is_what_makes_it_this_project_s_results(tmp_path):
    """Straight at the endpoints, no browser: it is the export that records it
    and the reset that forgets it."""
    import shutil as _sh
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "own")
    _sh.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((80, 60, 3), 240, np.uint8)
    p.add_uploaded("a.png", cv2.imencode(".png", img)[1].tobytes())
    assert not p.settings.get("exported")

    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        import urllib.request

        def post(path, obj):
            req = urllib.request.Request(
                base + path, data=json.dumps(obj).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())

        post("/api/export", {"dir": str(tmp_path / "out"), "mode": "clean"})
        assert p.settings.get("exported") is True
        post("/api/reset", {"keep_settings": True})
        assert not p.settings.get("exported"), \
            "a new chapter inherited the last one's results"
    finally:
        editor.PROJECT = was
        srv.shutdown()
        _sh.rmtree(root, ignore_errors=True)


def test_turning_to_a_smaller_page_does_not_keep_the_last_ones_size():
    """lee, third report of a page not being framed, and the one that named
    it:

        wheni swith to the next page its still keeping the old pages size,
        meanin that if the next page is smaller it gts stuck on top

    `fitScale` and `applyZoom` both asked the <img> element how big the page
    is. The element lags: while the next picture is on the wire it still
    reports the size of the page you just left, so the fit is a fit for the
    wrong page and the stage stays as tall as the old one -- which puts the
    middle of the scroll range below a shorter picture, and the picture at the
    top. `pageW`/`pageH` come from the server with the page's own record and
    are the authority; the element is the fallback.

    `tests/ui/next_page_is_not_the_last_ones_size.test.js` drives the real
    functions in jsdom with the element and the server disagreeing on purpose.
    It fails on the old precedence -- checked.
    """
    import os
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui",
                              "next_page_is_not_the_last_ones_size.test.js")],
        cwd=root, capture_output=True, text=True, timeout=90)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "ok" in out.stdout
