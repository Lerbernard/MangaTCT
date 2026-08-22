"""lee, going through the panel and the page one control at a time.

* *"instad of saying sma as this text box it shoud just say the font, do that
  for all of the spot fonts are used"*
* *"remove teh all caps in teh seeting"*
* *"the lock shoud prevent teh layer form getting edited or moved"*
* *"remove the manuel from the box"*
* *"when i clcik the plus and minus in the zoom it shoud not go to theses
  random bumbers, it shiud increase and decrease by 5 and teh default shoud be
  100%"*
* *"the etxt box shifted out of the page and is now stuck and unclicable"*
* *"change the on hover color it sberely readable"*
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root, big=False):
    from mangatl.project import Project
    from mangatl.typeset import default_font_path
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    h, w = (2000, 1400) if big else (600, 500)
    img = np.full((h, w, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.settings["font"] = default_font_path()
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160], "manual": True,
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": "look closely"}]
    p.pages[0].detected = True
    p.save()
    return p


def _serve(p):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1], was


@pytest.fixture()
def ed(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "reads"))
    editor.do_typeset(p, 0)
    srv, base, was = _serve(p)
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip('chromium unavailable')
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1500, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(900)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


# ------------------------------------------------------------- the fonts

def test_the_font_menu_names_the_face_it_would_use(ed):
    """It read "Same as the bubble setting", which answers a question nobody
    asked: you opened the menu to find out WHICH FACE, and the one word not on
    it was the name of the face."""
    pg, _p, errs = ed
    first = pg.evaluate(
        "document.getElementById('lyFont').options[0].textContent.trim()")
    assert first == "CCWildWords", first
    assert pg.evaluate(
        "document.getElementById('lyFont').options[0].dataset.name") \
        == "CCWildWords"
    shown = pg.evaluate("""(()=>{const s=document.getElementById('lyFont');
        return s.options[s.selectedIndex].textContent.trim();})()""")
    assert shown == "CCWildWords", shown
    assert "Same as" not in pg.evaluate(
        "document.getElementById('inspector').textContent")
    assert not errs, errs[:2]


def test_a_sub_type_row_names_the_face_it_inherits(ed):
    """The row used to show the first font in the list as though it had been
    chosen for that sub-type."""
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
    browserpool.settled(pg)
    got = pg.evaluate("""(()=>{
        const rows=[...document.querySelectorAll('#ckList .ckrow:not(.ckdef)')];
        const s=rows[0] && rows[0].querySelector('select.ckft');
        if(!s) return null;
        return [s.options[0].value, s.options[0].textContent.trim(),
                s.selectedIndex];})()""")
    assert got is not None, "no sub-type row"
    assert got[0] == "", got
    assert got[1] == "CCWildWords", got
    assert got[2] == 0, "an inherited face is shown as a chosen one"
    assert not errs, errs[:2]


def test_the_font_menu_is_the_browser_s_own(ed):
    """It was a widget: the select hidden, a div mirroring it, a menu placed by
    hand above or below depending on room. Four rounds of fixes and it still
    did not work - lee: *"the text drop down still dosent work re design it and
    remake it so taht it works"*. So the control is the control. Where it opens
    and how far it scrolls are the browser's business, and there is nothing
    left here that can open off the window."""
    pg, _p, errs = ed
    got = pg.evaluate("""(()=>{const s=document.getElementById('lyFont');
        const r=s.getBoundingClientRect();
        return {tag:s.tagName, widget:!!s._fw,
                shown:getComputedStyle(s).display!=='none',
                wide:Math.round(r.width)>100,
                onScreen:r.top>=0 && r.bottom<=innerHeight+1,
                leftovers:document.querySelectorAll('.fsel').length};})()""")
    assert got == {"tag": "SELECT", "widget": False, "shown": True,
                   "wide": True, "onScreen": True, "leftovers": 0}, got
    assert not errs, errs[:2]


# ------------------------------------------------------------ the settings

def test_the_project_wide_all_caps_is_not_on_the_settings_page(ed):
    """Capitals are a decision about a BLOCK - one shout in capitals on a page
    that is not - and that switch is in the typesetting panel where the block
    is. A project that had the old one on keeps it on."""
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
    browserpool.settled(pg)
    assert "ALL CAPS typesetting" not in pg.evaluate(
        "document.querySelector('.set-section[data-sec=fonts]').textContent")
    assert pg.evaluate(
        "getComputedStyle(document.getElementById('upper')).display") == "none"
    assert not errs, errs[:2]


def test_the_settings_nav_is_readable_under_the_pointer(ed):
    """lee, with a picture of it: *"change the on hover color it sberely
    readable"*."""
    pg, _p, errs = ed
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)
    # measured the honest way: the stylesheet's own hover rule
    rule = pg.evaluate("""(()=>{
        for(const sh of document.styleSheets){
          let rs; try{ rs=sh.cssRules; }catch(e){ continue; }
          for(const r of rs){
            if(r.selectorText && r.selectorText.indexOf('.setnav-btn:hover')===0)
              return [r.style.backgroundColor, r.style.color];
          }
        }
        return null;})()""")
    assert rule is not None, "no hover rule for the settings nav"
    bg = [int(x, 16) for x in
          (rule[0].lstrip("#")[0:2], rule[0].lstrip("#")[2:4],
           rule[0].lstrip("#")[4:6])] if rule[0].startswith("#") else \
        [int(x) for x in __import__("re").findall(r"\d+", rule[0])[:3]]
    fg = [255, 255, 255] if rule[1] in ("#fff", "white", "rgb(255, 255, 255)") \
        else [int(x) for x in __import__("re").findall(r"\d+", rule[1])[:3]]

    def lum(c):
        def s(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * s(c[0]) + 0.7152 * s(c[1]) + 0.0722 * s(c[2])

    a, b = lum(fg), lum(bg)
    ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
    assert ratio >= 4.5, (rule, round(ratio, 2))
    assert not errs, errs[:2]


# ------------------------------------------------------------- the row

def test_the_manual_chip_is_gone(ed):
    """Whether a box was drawn by hand or found by the detector is a fact
    about how it got here, not about what it is - and it took a slot on a row
    that has to fit on one line."""
    pg, p, errs = ed
    assert p.pages[0].regions[0]["manual"] is True, "the fixture is not manual"
    pg.evaluate("setView('original')")
    browserpool.settled(pg)
    assert "manual" not in pg.evaluate(
        "document.querySelector('#list .rowhead').textContent")
    assert not errs, errs[:2]


# ------------------------------------------------------------- the lock

def test_a_locked_text_box_cannot_be_typed_into_or_moved(ed):
    pg, _p, errs = ed
    pg.evaluate("toggleTextLock(1)")
    pg.wait_for_timeout(800)
    assert pg.evaluate("regions.find(r=>r.id===1).locked") is True
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(400)
    assert pg.evaluate("editing") is None, "a locked box opened for typing"
    was = pg.evaluate("regions.find(r=>r.id===1).layout.frame.slice()")
    pg.evaluate("""(()=>{const e=new MouseEvent('mousedown',
        {bubbles:true, clientX:100, clientY:100});
        try{ startFrame(e, 1, 'move'); }catch(err){}})()""")
    pg.wait_for_timeout(300)
    assert pg.evaluate("typeof fdrag==='undefined' || !fdrag"), \
        "a locked box was picked up"
    assert pg.evaluate("regions.find(r=>r.id===1).layout.frame") == was
    assert not errs, errs[:2]


def test_a_locked_paint_layer_cannot_be_picked_up(ed):
    pg, _p, errs = ed
    pg.evaluate("select(null)")
    pg.wait_for_timeout(600)
    pg.evaluate("""(()=>{
        layers.push({id:layerSeq++, type:'stroke', label:'test',
                     group:'drawing', col:'#fff', sz:4,
                     pts:[{x:5,y:5},{x:9,y:9}], visible:true});
        layerSel=layers[0].id; renderLayers();})()""")
    pg.wait_for_timeout(400)
    pg.evaluate("toggleLayerLock(layers[0].id)")
    pg.wait_for_timeout(400)
    pg.evaluate("layerSel=layers[0].id; xfStart()")
    pg.wait_for_timeout(400)
    assert pg.evaluate("!(typeof xf!=='undefined' && xf)"), \
        "a locked layer went into free transform"
    assert not errs, errs[:2]


# -------------------------------------------------------------- the zoom

def test_the_zoom_steps_by_five_and_lands_on_round_numbers(ed):
    """It multiplied by 1.25, so from a fit of 43% the readout walked 54, 67,
    84, 105 - every number arbitrary, and never 100."""
    pg, _p, errs = ed
    read = "document.getElementById('zlabel').textContent"
    assert pg.evaluate(read) == "100%", pg.evaluate(read)
    # Pressed, not called: the buttons are what the person touches, and they
    # are where the old multiply-by-1.25 lived.
    for want in ("95%", "90%", "85%"):
        pg.click("#zoutBtn")
        pg.wait_for_timeout(250)
        assert pg.evaluate(read) == want, (want, pg.evaluate(read))
    for want in ("90%", "95%", "100%"):
        pg.click("#zinBtn")
        pg.wait_for_timeout(250)
        assert pg.evaluate(read) == want, (want, pg.evaluate(read))
    # …and from somewhere that is NOT already a multiple of five, the first
    # press lands on one rather than carrying the odd number along.
    pg.evaluate("zoomBy(0.43/scale)")
    pg.wait_for_timeout(300)
    assert pg.evaluate(read) == "43%", pg.evaluate(read)
    pg.click("#zinBtn")
    pg.wait_for_timeout(300)
    assert pg.evaluate(read) == "50%", pg.evaluate(read)
    pg.click("#zoutBtn")
    pg.wait_for_timeout(300)
    assert pg.evaluate(read) == "45%", pg.evaluate(read)
    assert not errs, errs[:2]


# --------------------------------------------------- it cannot leave the page

def test_a_block_can_hang_over_the_edge_but_never_leave_it():
    """A frame is free to overhang - a sound effect running off the side of a
    panel does exactly that. What it may not do is leave altogether: a block
    whose whole box is past the edge is not drawn, not clickable and not
    reachable by any means. lee: *"the etxt box shifted out of the page and is
    now stuck and unclicable"*, with a picture of it out on the black."""
    from mangatl.typeset import ON_PAGE_PX, _frame_on_page
    H, W = 600, 500
    # right off the right-hand side
    x, y, w, h = _frame_on_page((900, 200, 180, 60), (H, W))
    assert x + w > W and x < W, (x, w)
    assert x <= W - ON_PAGE_PX
    # …and off the left, the top and the bottom
    assert _frame_on_page((-900, 200, 180, 60), (H, W))[0] >= ON_PAGE_PX - 180
    assert _frame_on_page((100, -900, 180, 60), (H, W))[1] >= ON_PAGE_PX - 60
    assert _frame_on_page((100, 5000, 180, 60), (H, W))[1] <= H - ON_PAGE_PX
    # a frame already on the page is untouched
    assert _frame_on_page((100, 200, 180, 60), (H, W)) == (100, 200, 180, 60)
    # …and a modest overhang is left exactly as it is
    assert _frame_on_page((W - 40, 200, 180, 60), (H, W)) == (W - 40, 200, 180, 60)


def test_it_cannot_be_dragged_off_the_page_in_the_first_place(ed):
    """The browser is where it went: a drag put the frame past the edge and
    then there was nothing left on screen to grab. `setFrame` is the one door
    every move and resize goes through."""
    pg, _p, errs = ed
    got = pg.evaluate("""(()=>{
        const r=regions.find(x=>x.id===1);
        setFrame(r,[9000,300,200,60]);
        const far=r.layout.frame.slice();
        setFrame(r,[-9000,300,200,60]);
        const near=r.layout.frame.slice();
        return {far, near, W:pageW, H:pageH};})()""")
    assert got["far"][0] <= got["W"] - 24, got
    assert got["far"][0] + got["far"][2] > got["W"], \
        "it was pulled fully onto the page; overhang is allowed"
    assert got["near"][0] >= 24 - got["near"][2], got
    assert got["near"][0] < 0, "overhang on the left is allowed too"
    assert not errs, errs[:2]


def test_the_typesetting_comes_back_onto_the_page(tmp_path):
    """And a chapter with one already stranded repairs itself: the stored
    frame is clamped on the way back in, so the block is drawn where it can
    be reached."""
    from mangatl import typeset as T
    from mangatl.models import Page, TextRegion
    img = np.full((600, 500, 3), 240, np.uint8)
    m = np.zeros((600, 500), np.uint8)
    m[140:220, 170:330] = 255
    r = TextRegion(id=1, bbox=(170, 140, 160, 80), kind="bubble",
                   text_mask=m, bubble_mask=m, bubble_bbox=(170, 140, 160, 80))
    r.dst_text = "look closely"
    r.layout_override = {"lines": ["look closely"], "font_size": 18,
                         "locked": True, "frame": [1400, 300, 200, 60]}
    page = Page(image=img)
    page.regions = [r]
    cfg = T.TypesetConfig(font_path=T.default_font_path(),
                          min_font=10, max_font=30)
    T.typeset_page(page, cfg)
    fr = r.layout.frame
    assert fr[0] <= 500 - T.ON_PAGE_PX, fr


# ------------------------------------------------- the round after that

def test_a_page_opens_fitted(tmp_path):
    """lee asked for actual size when "100%" in the readout still meant the
    fit, and asked for the fit back the moment the readout started telling the
    truth: *"ok make the defaut zoom fit the page"*."""
    from mangatl import editor
    p = _project(str(tmp_path / "fit"), big=True)
    editor.do_typeset(p, 0)
    srv, base, was = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 900, "height": 600})
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset')")
            browserpool.settled(pg)
            assert pg.evaluate("fitZoom") < 0.6, pg.evaluate("fitZoom")
            assert abs(pg.evaluate("zoom") - 1) < 0.01, pg.evaluate("zoom")
            assert pg.evaluate("scale") < 0.6, pg.evaluate("scale")
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


def test_the_picker_survives_the_panel_being_rebuilt(ed):
    """The panel replaces its own HTML on a poll, a save, a selection - and a
    redraw landing while the list was down took the list away mid-click.
    lee: *"it open onec and closes and dont work after"*.

    A native select's list is drawn by the browser over the page, not by us
    inside the panel, so a rebuild cannot take it. What is checked here is what
    a rebuild CAN still break: that the control comes back with the same face
    chosen."""
    pg, _p, errs = ed
    was = pg.evaluate("document.getElementById('lyFont').value")
    pg.evaluate("renderInspector(); renderInspector(); renderList()")
    pg.wait_for_timeout(500)
    got = pg.evaluate("""(()=>{const s=document.getElementById('lyFont');
        return s ? {v:s.value, n:s.options.length} : 'the picker is gone';})()""")
    assert got != "the picker is gone", got
    assert got["v"] == was, got
    assert got["n"] > 0, got
    assert not errs, errs[:2]


def test_picking_a_face_takes_even_after_a_rebuild(ed):
    """It has to reach the record, not just the control."""
    pg, _p, errs = ed
    opts = pg.evaluate("""[...document.getElementById('lyFont').options]
        .map(o=>o.value).filter(Boolean)""")
    assert opts, "no fonts offered"
    pg.focus("#lyFont")
    pg.select_option("#lyFont", opts[0])
    pg.wait_for_timeout(1500)
    # the override is the durable answer - `r.style` is scratch, replaced
    # whenever the save's reply lands and the regions are rebuilt
    got = pg.evaluate("""[document.getElementById('lyFont').value,
        ((regions.find(r=>r.id===1).layout_override)||{}).font]""")
    assert got[1] and got[1].endswith(".ttf"), got
    assert got[0] == got[1], got
    assert not errs, errs[:2]


def test_the_gradient_wells_say_which_end_they_are(ed):
    pg, _p, errs = ed
    labels = pg.evaluate(
        "[...document.querySelectorAll('#inspector label')]"
        ".map(l=>l.textContent.trim())"
        ".filter(t=>/^(Gradient|Outline gradient|From|To|Angle)$/.test(t))")
    # Twice over: the letters' gradient, then the outline's own, which is a
    # separate one with its own two ends and its own angle.
    assert labels == ["Gradient", "From", "To", "Angle",
                      "Outline gradient", "From", "To", "Angle"], labels
    off = pg.evaluate("['lyFg1','lyFg2','lyEdge1','lyEdge2']"
                      ".map(i=>document.getElementById(i+'Hex').textContent)")
    assert off == ["OFF", "OFF", "OFF", "OFF"], off
    assert not errs, errs[:2]


def test_all_caps_shows_at_once(ed):
    """It is a change to what the letters look like, not to what the fitter
    decides - so waiting on the round trip to see it was waiting for nothing,
    and the first preview after a save can take seconds."""
    pg, _p, errs = ed
    was = pg.evaluate("regions.find(r=>r.id===1).layout.lines")
    assert was and any(x != x.upper() for x in was), was
    pg.evaluate("""(()=>{const c=document.getElementById('lyCaps');
        c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));})()""")
    pg.wait_for_timeout(80)
    now = pg.evaluate("regions.find(r=>r.id===1).layout.lines")
    assert now == [x.upper() for x in was], \
        f"the screen waited for the server: {now}"
    pg.wait_for_timeout(1800)
    settled = pg.evaluate("regions.find(r=>r.id===1).layout.lines")
    assert all(x == x.upper() for x in settled), settled
    assert not errs, errs[:2]


def test_a_style_edit_does_not_throw_the_page_cache_away(tmp_path):
    """The cached page is masks and a cleaned plate. A colour, a font, a line
    gap and capitals change none of that, and dropping it made the next
    keystroke rebuild the whole page. lee: *"the letter gap take a long time to
    work the first time"*."""
    import json
    import urllib.request
    from mangatl import editor
    p = _project(str(tmp_path / "cache"))
    editor.do_typeset(p, 0)
    srv, base, was = _serve(p)
    try:
        editor.cached_page(p, 0)
        assert 0 in editor._page_cache
        req = urllib.request.Request(
            base + "/api/page/0/region/1",
            data=json.dumps({"layout": {"lines": ["look closely"],
                                        "lspace": 8}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req).read()
        assert 0 in editor._page_cache, "a style edit dropped the page"
        # …but anything that MOVES a mask still does
        req2 = urllib.request.Request(
            base + "/api/page/0/region/1",
            data=json.dumps({"bbox": [170, 150, 160, 80]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req2).read()
        assert 0 not in editor._page_cache, "a moved box kept a stale page"
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


def test_typeset_puts_the_page_back_to_what_the_fitter_would_do(tmp_path):
    """lee: *"when i re typseet a page any custom chnages to text boxes or
    custom text box dshoud be removed"*. Without this there was no way back to
    a clean layout short of undoing each block one at a time - the button that
    was supposed to be the reset was the one thing that could not reset."""
    from mangatl import editor
    p = _project(str(tmp_path / "reset"))
    editor.do_typeset(p, 0)
    p.pages[0].regions[0]["layout_override"] = {
        "lines": ["MINE"], "font_size": 40, "locked": True, "fg": "#ff0000"}
    p.pages[0].regions.append({
        "id": 99, "kind": "bubble", "order": 1, "bbox": [40, 400, 200, 60],
        "polygon": [[40, 400], [240, 400], [240, 460], [40, 460]],
        "confidence": 1.0, "src_text": "", "dst_text": "MY OWN BOX",
        "own_text": True, "manual": True})
    p.save()

    editor.do_typeset(p, 0)
    assert not any(r.get("own_text") for r in p.pages[0].regions), \
        "a text box added by hand survived Typeset"
    assert all(not r.get("layout_override") for r in p.pages[0].regions), \
        "a hand correction survived Typeset"
    assert p.pages[0].regions[0]["layout"]["lines"] != ["MINE"]
