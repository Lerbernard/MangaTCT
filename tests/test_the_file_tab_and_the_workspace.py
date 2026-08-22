"""The tab bar, the two view buttons, and the rows down the side.

Five things lee asked for in one sitting, all of them about the chrome rather
than the pages:

* **File.** "New project" named one screen; it is a tab with a section rail now,
  the way Settings is, with New project as the only section on it - *"wheni
  clcik it a tab with multiple section shoud show rigt now new project shoud be
  the only one"*. The rail is what makes the next section a button and a
  `<section>` rather than a rebuild.
* **Workspace.** "Edit" named the tab AND the right-hand view button, so the bar
  read Edit ▸ Edit.
* **Results.** Unlocked on lee's word - *"the result tab shoud be unloacked"* -
  and shut again on his next one, *"re lock the results page after export is
  doen"*, which is where it started.
* **Image / Translation**, and the lit pill SLIDES between them instead of
  being cut from one to the other.
* **The rows are grey**, and the blue is gone. They wore their box's colour for
  two rounds - mixed with the panel, then the swatch held at a fixed lightness -
  and lee looked at both: *"aslo just go back to the  grey backgrounf"*.

Measured in the browser wherever the answer is a computed one: a rule that is
present and overridden is a rule that is not there.
"""
import os
import re
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

ROOT = PKG / "static"
HTML = (ROOT / "editor.html").read_text(encoding="utf-8")
CSS = (ROOT / "css" / "editor.css").read_text(encoding="utf-8")
VIEWJS = (ROOT / "js" / "view.js").read_text(encoding="utf-8")
PANELJS = (ROOT / "js" / "panels.js").read_text(encoding="utf-8")


def _serve(fn, root=scratch("_tmp_filetab"), pages=3, exported=0):
    from mangatl import editor
    from mangatl.project import Project
    # One folder per xdist worker. Every case in this file used the same
    # directory name, so under `-n 2` two of them could build and tear down the
    # same project at the same time - one wiping the input folder the other was
    # about to read. It failed as `FileNotFoundError: _tmp_filetab/input/p0.png`
    # once in a hundred runs, which is exactly often enough to be blamed on
    # whatever was changed that day.
    root = root + os.environ.get("PYTEST_XDIST_WORKER", "")
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


# ------------------------------------------------------------- what they say

def test_the_first_tab_is_file():
    assert '>File</button>' in HTML
    assert '>New project</button>' not in HTML.split('id="tabs"')[1] \
                                            .split('</span>')[0]


def test_the_second_tab_is_not_called_edit_any_more():
    bar = HTML.split('id="tabs"')[1].split('</span>')[0]
    assert '>Workspace</button>' in bar
    assert '>Edit</button>' not in bar


def test_the_two_view_buttons_have_their_own_names():
    """Not "Original" and "Edit" - the second named the tab it sat under, so
    the bar read Edit ▸ Edit. lee: *"rename the to translation tab and image
    tab"*, then *"siwthc the tab name arund"*, then *"cha teh names of teh 2
    tabs aroung so the image tabs shoud be named translation"*.

    Each is named for the WORK, not for the artwork behind it - which is why
    the names read the other way round from the views. lee: *"teh translation
    tab shoud be teh tab with teh bozes and the image tab shud be the tav with
    the clenned pages and text boxes"*.

    * **Translation** - the page as it came, boxes over it, list beside it.
      That is the `original` view, and it is where the translating happens.
    * **Image** - the picture you end up with: cleaned, typeset, carrying any
      text boxes of your own. The `typeset` view.
    """
    strip = re.search(r'<span class="views">.*?</span>', HTML, re.S).group(0)
    assert re.findall(r'>([\w ]+)</button>', strip) == ["Translation", "Image"]
    assert re.search(r"id=\"vOriginal\"[^>]*>Translation<", strip), strip
    assert re.search(r"id=\"vTypeset\"[^>]*>Image<", strip), strip


def test_the_group_is_dressed_right_before_anything_has_run():
    """What lee saw on opening the editor: a yellow pill under grey text, with
    the other label invisible against the dark plate. `setView` had not run
    yet, so the pill was at rest on the left while the lit class sat on the
    button to the right of it - the markup has to be born in a state that
    agrees with itself."""
    strip = re.search(r'<span class="views">.*?</span>', HTML, re.S).group(0)
    assert 'class="views"' in strip, "the group starts with the pill left..."
    first = re.search(r'<button id="(\w+)"[^>]*class="([^"]*)"', strip)
    assert first.group(1) == "vOriginal", first.groups()
    assert "on" in first.group(2).split(), \
        "...so the LEFT button is the lit one before anything has run"
    assert strip.count("vw on") == 1, strip


def test_the_view_buttons_do_not_move_when_the_view_changes():
    """The Translation view brings two switches with it, and they used to
    appear to the RIGHT of the pair. This group is laid out from the right
    edge, so everything to their right shoves them along: pressing Translation
    moved the very button you had just pressed out from under the pointer.

    lee: *"wheni clcik the translation button two button show up to the right
    of the 2 tabs button just make them she up to the left of the 2 tab
    buttons so that the 2 tab buttons dont move"*.

    Measured, in pixels, in both views - and not only the group's edge: the
    lit button used to go bold as it lit, and bold text is wider text, so the
    pair grew from the inside even once the switches had moved.
    """
    def check(pg, p):
        def rect(view):
            pg.evaluate(f"setView('{view}')")
            browserpool.at_rest(pg, "getComputedStyle(document.querySelector"
                                    "('.views'),'::before').transform")
            return pg.evaluate("""(()=>{
              const q=s=>{const b=document.querySelector(s)
                    .getBoundingClientRect();
                return {l:Math.round(b.left), r:Math.round(b.right),
                        w:Math.round(b.width)};};
              return {group:q('.views'), tl:q('#vTypeset'),
                      im:q('#vOriginal'),
                      switches:!!document.getElementById('sbsWrap')
                        .offsetWidth};})()""")
        image = rect("original")
        typeset = rect("typeset")
        assert typeset["switches"], "the switches never appeared"
        assert not image["switches"], "they are up in the Image view too"
        assert image["group"] == typeset["group"], (image, typeset)
        assert image["tl"] == typeset["tl"], (image["tl"], typeset["tl"])
        assert image["im"] == typeset["im"], (image["im"], typeset["im"])
    _serve(check)


def test_the_switches_are_before_the_buttons_in_the_bar():
    """Which is the whole mechanism: in a group laid out from the right edge,
    what comes first is what gets pushed."""
    bar = HTML.split('id="pageTools"')[1].split("</div>")[0]
    assert bar.index('id="sbsWrap"') < bar.index('class="views"'), \
        "Side by side is still to the right of the buttons"
    assert bar.index('id="showTextWrap"') < bar.index('class="views"'), \
        "Translated text is still to the right of the buttons"


# -------------------------------------------------------- File has a section rail

def test_the_file_screen_has_a_rail_and_every_entry_opens_something():
    """This began as one entry and a place for more - the rail was built for a
    second thing to be a button and a section rather than a rebuild, and
    saving a chapter turned out to be it. lee: *"add a save project save as
    and a load project and move into te files tab too"*.

    So the count is not the rule; the rule is that every entry names a section
    that exists, and that New project is the one you land on."""
    rail = re.search(r'<nav id="fileNav">.*?</nav>', HTML, re.S).group(0)
    entries = re.findall(r'data-sec="([^"]+)"', rail)
    assert entries[0] == "new" and ">New project<" in rail
    assert "save" in entries, "saving and opening a chapter live here now"
    assert 'id="fileBody"' in HTML
    body = HTML.split('id="fileBody"')[1]
    for sec in entries:
        on = ' on"' if sec == "new" else '"'
        assert f'<section class="set-section{on} data-sec="{sec}">' in body, sec
    assert rail.count('class="setnav-btn on"') == 1, \
        "exactly one of them is the one you arrive at"


def test_the_rail_uses_the_settings_page_s_own_machinery():
    """Not a second implementation of the same idea - `_pickSection` is what
    Settings switches with, and it is what this switches with."""
    assert "function setFileTab(name){ _pickSection('#fileNav','#fileBody'" \
        in VIEWJS


def test_the_rail_is_dressed_like_the_settings_one():
    assert "#fileNav{" in CSS or "#fileNav{" in CSS.replace(",#fileNav", "{")
    assert "#setNav,#mangaNav,#fileNav{" in CSS


# -------------------------------------------------------- Results, shut again

def test_results_is_shut_until_this_project_exports_something():
    """Unlocked for one round on lee's word, then shut again on his next:
    *"re lock the results page after export is doen"*."""
    def check(pg, p):
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "document.getElementById('tabRes').classList.contains('off')")
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        assert pg.evaluate("tab") != "results", "it went there anyway"
    _serve(check, exported=0)


def test_and_opens_once_it_has():
    def check(pg, p):
        pg.wait_for_timeout(500)
        assert not pg.evaluate(
            "document.getElementById('tabRes').classList.contains('off')")
        pg.evaluate("setTab('results')")
        browserpool.settled(pg)
        assert pg.evaluate("tab") == "results"
    _serve(check, exported=2)


def test_the_reason_names_the_tab_by_its_new_name():
    """It used to say "press Export on the Edit tab", and there is no Edit tab
    any more."""
    def check(pg, p):
        pg.wait_for_timeout(500)
        why = pg.evaluate("document.getElementById('tabRes').title")
        assert "Workspace" in why and "Edit tab" not in why, why
    _serve(check, exported=0)


def test_the_workspace_is_still_shut_with_no_pages():
    """The other gate stays. There is genuinely nothing to work on."""
    def check(pg, p):
        pg.wait_for_timeout(500)
        assert pg.evaluate(
            "document.getElementById('tabEdit').classList.contains('off')")
    _serve(check, pages=0)


# ----------------------------------------------------------- the pill slides

def test_the_lit_pill_is_one_thing_that_moves():
    def check(pg, p):
        # Read where the pill COMES TO REST, not where it is a fixed number of
        # milliseconds after being told to move: mid-flight the two ends of a
        # 200ms slide are the same value to a few decimal places, and a test
        # that catches it on the way back reads the place it started from.
        pill = ("getComputedStyle(document.querySelector('.views'),"
                "'::before').transform")
        pg.evaluate("setView('original')")
        left = browserpool.at_rest(pg, pill)
        # Translation - the `original` view - is the left-hand button, so the
        # pill is on the right only on Image. The class names a side, not a
        # view.
        assert not pg.evaluate(
            "document.querySelector('.views').classList.contains('right')")
        pg.evaluate("setView('typeset')")
        right = browserpool.at_rest(pg, pill)
        assert pg.evaluate(
            "document.querySelector('.views').classList.contains('right')"), \
            "the group was never told which side is lit"
        assert left != right, (left, right)
        assert pg.evaluate(
            "getComputedStyle(document.querySelector('.views'),'::before')"
            ".transitionDuration") not in ("", "0s"), \
            "it jumps instead of sliding"
    _serve(check)


def test_the_pill_lands_exactly_on_the_button():
    """The arithmetic only works because the two buttons are equal width. If
    that ever stops being true the pill sits half over the wrong one."""
    def check(pg, p):
        pg.evaluate("setView('typeset')")
        # Image is the right-hand button, so this switch MOVES the pill -
        # measured two frames in, it is caught halfway across.
        browserpool.at_rest(pg, "getComputedStyle(document.querySelector"
                                "('.views'),'::before').transform")
        g = pg.evaluate("""(()=>{
          const v=document.querySelector('.views');
          const b=document.getElementById('vTypeset').getBoundingClientRect();
          const s=getComputedStyle(v,'::before');
          const m=new DOMMatrixReadOnly(s.transform);
          const vr=v.getBoundingClientRect();
          return {left: vr.left+3+m.m41, width: parseFloat(s.width),
                  bl: b.left, bw: b.width};})()""")
        assert abs(g["left"] - g["bl"]) <= 1.5, g
        assert abs(g["width"] - g["bw"]) <= 1.5, g
    _serve(check)


def test_the_hover_does_not_draw_a_second_button():
    """It used to paint its own dark rounded plate, which read as a button
    appearing inside the group rather than as the one under the pointer waking
    up. lee: *"change the on hover of the scan tab"*."""
    def check(pg, p):
        pg.wait_for_timeout(400)
        pg.hover("#vTypeset")
        pg.wait_for_timeout(300)
        bg = pg.evaluate("getComputedStyle(document.getElementById('vTypeset'))"
                         ".backgroundColor")
        assert bg in ("rgba(0, 0, 0, 0)", "transparent"), bg
        # ...and it still answers the pointer, in the label
        assert pg.evaluate("getComputedStyle(document.getElementById('vTypeset'))"
                           ".color") != pg.evaluate(
            "getComputedStyle(document.getElementById('vOriginal')).color")
    _serve(check)


def test_only_the_pill_is_yellow():
    """A background on the lit button as well would put a hard-edged rectangle
    on top of the thing that is meant to be sliding."""
    def check(pg, p):
        pg.wait_for_timeout(400)
        bg = pg.evaluate("getComputedStyle(document.getElementById('vOriginal'))"
                         ".backgroundColor")
        assert bg in ("rgba(0, 0, 0, 0)", "transparent"), bg
    _serve(check)


# ------------------------------------------------------- the rows wear a colour

def test_a_row_is_a_plain_grey_plate():
    """Two rounds of colour and then back. What matters is that nothing is
    left half-applied: no rule reaching for a colour the rows no longer carry,
    and no colour written onto rows no rule reads."""
    assert "oklch(from var(--kc)" not in CSS
    assert "--kc" not in CSS
    assert "--kc" not in PANELJS


def test_every_row_is_the_same_colour():
    def check(pg, p):
        pg.evaluate("""(()=>{
          regions=[{id:0,kind:'bubble',order:0,dst_text:'a',src_text:'a',
                    confidence:.9,bbox:[0,0,9,9]},
                   {id:1,kind:'sfx',order:1,dst_text:'b',src_text:'b',
                    confidence:.9,bbox:[0,0,9,9]},
                   {id:2,kind:'freefloat',order:2,dst_text:'c',src_text:'c',
                    confidence:.9,bbox:[0,0,9,9]}];
          hiddenRows=[]; sel=null; renderList();})()""")
        pg.wait_for_timeout(300)
        got = pg.evaluate("""[...document.querySelectorAll('#list .lrow')]
          .map(r=>getComputedStyle(r).backgroundColor)""")
        assert len(got) == 3, got
        assert len(set(got)) == 1, got
        # ...and it is the panel's own plate, not a colour that happens to
        # match on this one page
        assert got[0] == pg.evaluate("""getComputedStyle(
          document.querySelector('#side .card:not(.lrow)')).backgroundColor"""), got
    _serve(check)


def test_no_row_is_blue_any_more():
    assert ".card.lrow.linked{background:" not in CSS
    assert "color-mix(in srgb, var(--link)" not in CSS


def test_a_linked_pair_still_says_so():
    """The blue background went; the border and the chip in the head are what
    said it before that rule existed and they say it still."""
    assert ".card.lrow.linked{border-color:var(--link)}" in CSS
    assert 'class="chip link"' in PANELJS
