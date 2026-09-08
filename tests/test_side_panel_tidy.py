"""The side panel: grouped, one search box, and an up/down you can hit.

Three things lee asked for, looking at the typesetting panel:

* *"get rid of the seach font in teh pictyure"* - there were two. The font
  PICKER has a search inside its dropdown, which is where it belongs; above it
  sat a second, permanent one filtering the same list. That one is gone.
* *"make teh up and down button look better"* - both browsers draw their own
  spinner on a number box and neither can be made to look like the other:
  Chromium's `::-webkit-inner-spin-button` can be painted, Firefox's cannot be
  touched at all, and lee works in Firefox. Both natives are off now and one is
  built out of two real buttons, so it is the same control everywhere.
* *"make teh side bar more organized"* - fourteen controls in one unbroken
  strip, now folded into five named groups that remember whether they were
  open.

These run in Chromium because that is what is installed. The browser lee uses
is Firefox, and the one thing that genuinely differs between them - a `change`
event on an element removed while focused - is not what any of this rests on.
"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")


def _project(root):
    import shutil
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((900, 700, 3), 245, np.uint8)
    for k in range(2):
        cv2.ellipse(img, (220 + k * 300, 220), (110, 80), 0, 0, 360,
                    (255, 255, 255), -1)
        cv2.ellipse(img, (220 + k * 300, 220), (110, 80), 0, 0, 360,
                    (25, 25, 25), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": k + 1, "kind": "bubble", "order": k,
        "bbox": [150 + k * 300, 180, 140, 80],
        "bubble_bbox": [110 + k * 300, 140, 220, 160],
        "polygon": [[150 + k * 300, 180], [290 + k * 300, 180],
                    [290 + k * 300, 260], [150 + k * 300, 260]],
        "src_text": "テスト", "dst_text": "HELLO THERE", "confidence": 0.9,
        "layout": {"lines": ["HELLO", "THERE"], "font_size": 18,
                   "leading": 1.1,
                   "origins": [[220 + k * 300, 205], [220 + k * 300, 228]],
                   "fg": "#000000", "edge": "#ffffff", "stroke": 1,
                   "font": "", "rotate": 0.0, "frame": [], "fixed": False,
                   "fit_ok": True, "used_compact": False}}
        for k in range(2)]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    p.pages[0].typeset = True
    return p


def _panel(fn, root=scratch("_tmp_tidy")):
    """Open the typesetting panel with a region selected and hand it to `fn`."""
    import shutil
    from mangatl import editor

    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 1200})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset'); showPage(0)")
            browserpool.settled(pg)
            pg.evaluate("select(1)")
            pg.wait_for_timeout(800)
            assert not errs, errs
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_there_is_no_loose_font_search_in_the_panel():
    """There used to be one inside the custom picker's own menu, and the rule
    was that it was the only one. The picker is a native <select> now - the
    browser's own type-ahead is the search - so there should be no search box
    in this panel at all."""
    def check(pg, p):
        boxes = pg.evaluate(
            "[...document.querySelectorAll('#inspector input[placeholder]')]"
            ".filter(i=>/search/i.test(i.placeholder)).length")
        assert boxes == 0, boxes
    _panel(check)


def test_the_panel_is_pinned_to_one_width():
    """lee, with two screenshots of the panel at two widths: *"make thsi side
    bar a consistent size"*. `width` on a flex item is only its basis - the
    item still refuses to shrink below its widest child, so one wide row on
    one page moved the panel and the artwork with it. min and max close both
    doors; overflow-x makes a too-wide child that page's problem."""
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    rule = css[css.index("#side{"):]
    rule = rule[:rule.index("}")]
    assert "width:330px" in rule
    assert "min-width:330px" in rule and "max-width:330px" in rule
    assert "flex:0 0 330px" in rule
    assert "overflow-x:hidden" in rule


def test_the_panel_is_grouped():
    def check(pg, p):
        titles = pg.evaluate(
            "[...document.querySelectorAll('#inspector details.grp > summary')]"
            ".map(s=>s.textContent.trim())")
        # Paragraph and Character, the way a typesetter's panels are laid out.
        # "This box" is gone - its two menus are at the head of the panel, so
        # what a box IS is the first thing you read rather than a fold at the
        # bottom. lee: *"remove the this box section too"*.
        assert titles == ["Paragraph", "Character", "Colour",
                          "Effects"], titles
    _panel(check)


def test_a_group_stays_as_it_was_left():
    """The panel is rebuilt on every change. A group that folded itself back up
    each time would be worse than no groups at all."""
    def check(pg, p):
        pg.evaluate("""(()=>{const d=[...document.querySelectorAll(
            '#inspector details.grp')][3];
            d.open=true; d.dispatchEvent(new Event('toggle'));})()""")
        pg.wait_for_timeout(200)
        pg.evaluate("renderInspector()")
        pg.wait_for_timeout(400)
        # every group starts open, so this one is folded by hand first
        pg.evaluate("""(()=>{const d=[...document.querySelectorAll(
            '#inspector details.grp')][2];
            d.open=false; d.dispatchEvent(new Event('toggle'));})()""")
        pg.wait_for_timeout(200)
        pg.evaluate("renderInspector()")
        pg.wait_for_timeout(400)
        assert pg.evaluate("[...document.querySelectorAll("
                           "'#inspector details.grp')][3].open") is True
        assert pg.evaluate("[...document.querySelectorAll("
                           "'#inspector details.grp')][2].open") is False,\
            "a group folded by hand sprang open again"
    _panel(check)


def test_every_number_box_gets_an_up_and_a_down():
    def check(pg, p):
        bare = pg.evaluate("""
          [...document.querySelectorAll('#inspector input[type=number]')]
            .filter(i=>!i.closest('.sl'))
            .filter(i=>!i.parentElement.classList.contains('numwrap'))
            .map(i=>i.id||i.className)""")
        assert bare == [], bare
        n = pg.evaluate("document.querySelectorAll('#inspector .numwrap').length")
        assert pg.evaluate(
            "document.querySelectorAll('#inspector .numbtn').length") == 2 * n
    _panel(check)


def test_a_box_with_a_slider_beside_it_is_left_plain():
    """Curve and Opacity have a slider for the coarse move; the box is there to
    read and to type in. Two more buttons in a 42px box is clutter."""
    def check(pg, p):
        assert pg.evaluate(
            "document.querySelectorAll('#inspector .sl .numbtn').length") == 0
    _panel(check)


def test_the_buttons_change_the_value_and_save_it():
    """Changing the number on screen is half of it. Every field in these panels
    saves on `input` or `change`, and a value set from script fires neither by
    itself - so a stepper that only wrote the box would look like it worked and
    lose the change."""
    def check(pg, p):
        before = pg.evaluate("+document.getElementById('lySize').value")
        pg.click("#lySize + .numbtn.up")
        pg.wait_for_timeout(500)
        assert pg.evaluate("+document.getElementById('lySize').value") == before + 1
        pg.click("#lySize ~ .numbtn.dn")
        pg.click("#lySize ~ .numbtn.dn")
        pg.wait_for_timeout(500)
        assert pg.evaluate("+document.getElementById('lySize').value") == before - 1
        # ...and the handler really ran. Line gap is the one that lands
        # somewhere the test can see immediately: onTypesetEdit writes it
        # straight into the region's layout so the lines move at once.
        was = pg.evaluate("+regions.find(r=>r.id===1).layout.leading")
        pg.click("#lyLead ~ .numbtn.up")
        pg.wait_for_timeout(500)
        now = pg.evaluate("+regions.find(r=>r.id===1).layout.leading")
        assert abs(now - (was + 0.05)) < 1e-6, \
            f"the box changed but nothing heard it: {was} -> {now}"
    _panel(check)


def test_the_buttons_respect_the_step_and_the_limits():
    def check(pg, p):
        # line gap steps by 0.05 and stops at 0.7
        assert pg.evaluate("document.getElementById('lyLead').step") == "0.05"
        start = pg.evaluate("+document.getElementById('lyLead').value")
        pg.click("#lyLead ~ .numbtn.up")
        pg.wait_for_timeout(300)
        assert pg.evaluate("+document.getElementById('lyLead').value") \
            == pytest.approx(start + 0.05)
        # the box's own floor, which is BELOW the fitter's: a person may set a
        # tighter gap on purpose (see test_panel_edits_stick)
        for _ in range(20):
            pg.click("#lyLead ~ .numbtn.dn")
        pg.wait_for_timeout(400)
        assert pg.evaluate("+document.getElementById('lyLead').value") \
            == pg.evaluate("+document.getElementById('lyLead').min")
    _panel(check)


def test_the_step_does_not_leave_a_long_tail_of_decimals():
    """0.05 added to 1.10 in binary floating point is 1.1500000000000001, and
    that is what would have gone in the box."""
    def check(pg, p):
        start = pg.evaluate("+document.getElementById('lyLead').value")
        for _ in range(3):
            pg.click("#lyLead ~ .numbtn.up")
        pg.wait_for_timeout(500)
        got = pg.evaluate("document.getElementById('lyLead').value")
        assert got == f"{start + 0.15:.2f}", (start, got)
        assert len(got.split(".")[1]) == 2, got
    _panel(check)


def test_the_buttons_do_not_steal_the_tab_order():
    """Tab runs through the fields. Two buttons per box would treble the number
    of stops between the top of the panel and the bottom."""
    def check(pg, p):
        assert pg.evaluate(
            "[...document.querySelectorAll('#inspector .numbtn')]"
            ".every(b=>b.tabIndex===-1)") is True
    _panel(check)


def test_a_box_with_a_width_of_its_own_keeps_its_buttons_inside_it():
    """The gradient angle is 52px wide in a wide row. Wrapping it in something
    that stretched left the buttons floating off to the side of the box."""
    def check(pg, p):
        pg.evaluate("document.querySelectorAll('#inspector details.grp')"
                    ".forEach(d=>{d.open=true;})")
        pg.wait_for_timeout(300)
        box = pg.evaluate("document.getElementById('lyGrad')"
                          ".getBoundingClientRect().width")
        row = pg.evaluate("document.getElementById('lyGrad')"
                          ".closest('.row').getBoundingClientRect().width")
        assert box <= 60, (f"the angle box grew from 52px to {box:.0f}px of a "
                           f"{row:.0f}px row — the wrapper stretched")
        gap = pg.evaluate("""(()=>{
            const i=document.getElementById('lyGrad');
            const b=i.parentElement.querySelector('.numbtn');
            return i.getBoundingClientRect().right
                 - b.getBoundingClientRect().right;})()""")
        assert abs(gap) <= 3, f"the buttons sit {gap}px away from the box"
    _panel(check)


def test_no_native_spinner_is_left_showing_underneath():
    """Both natives have to be off, or a box carries two sets of arrows.

    Read from the stylesheet rather than from the browser: Chromium drops
    `-moz-appearance` at parse time, so its CSSOM cannot be asked whether the
    rule Firefox needs is there, and `getComputedStyle` answers for a
    pseudo-element whether the rule applies or not.
    """
    from pathlib import Path
    css = (PKG / "static" / "css"
           / "editor.css").read_text(encoding="utf8")
    flat = css.replace(" ", "")
    # On the PLAIN rule, not only on the slider variant further down.
    bare = flat[flat.index("input[type=number]{"):][:200]
    assert "-moz-appearance:textfield" in bare, "Firefox keeps its own spinner"
    spin = flat[flat.index("::-webkit-inner-spin-button"):][:400]
    assert "display:none" in spin, "Chromium keeps its own spinner"


def test_the_settings_boxes_save_when_stepped():
    """Not every field in the app saves on `input`. Min pt and Max pt in the
    settings sheet save on `change`, which a value written from script does not
    fire by itself - so the stepper has to send both."""
    import shutil
    import threading
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = scratch("_tmp_tidyset")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 1100})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("openSettingsDlg(); setSettingsTab('fonts')")
            pg.wait_for_timeout(700)
            before = int(p.settings.get("min_font") or 0)
            assert pg.evaluate("+document.getElementById('minf').value") == before
            pg.click("#minf ~ .numbtn.up")
            pg.wait_for_timeout(900)
            assert int(p.settings["min_font"]) == before + 1, \
                "the stepper changed the box and the setting never moved"
            assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_the_value_lands_in_the_region_before_any_request_is_made():
    """The panel is built FROM the region, and it is rebuilt on all sorts of
    things - a save landing, a poll, a stepper being released. Anything typed
    that is not written into the region at once is a field that snaps back to
    the last answer the server gave while the new one is still in flight.

    lee, on the size box in Firefox: *"it donsent update at all right now"*.
    Every other press was being swallowed by exactly that.
    """
    def check(pg, p):
        before = pg.evaluate("regions.find(r=>r.id===1).layout.font_size")
        pg.evaluate("""(()=>{const i=document.getElementById('lySize');
            i.value = String(+i.value + 5);
            i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        # read it back in the SAME tick - before any request could return
        after = pg.evaluate("regions.find(r=>r.id===1).layout.font_size")
        assert after == before + 5, (before, after)
    _panel(check)


def test_pressing_eight_times_quickly_moves_eight():
    """Each press saves, and a save rebuilds the panel. If the field is rebuilt
    from state that has not caught up, the next press starts from the old
    number and half the presses vanish."""
    def check(pg, p):
        before = pg.evaluate("+document.getElementById('lySize').value")
        for _ in range(8):
            pg.click("#lySize ~ .numbtn.up")
            pg.wait_for_timeout(40)
        pg.wait_for_timeout(1200)
        assert pg.evaluate("+document.getElementById('lySize').value") \
            == before + 8
    _panel(check)


def test_holding_a_stepper_keeps_stepping():
    def check(pg, p):
        b = pg.locator("#lySize ~ .numbtn.up").bounding_box()
        before = pg.evaluate("+document.getElementById('lySize').value")
        pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        pg.mouse.down()
        pg.wait_for_timeout(1100)
        pg.mouse.up()
        pg.wait_for_timeout(900)
        after = pg.evaluate("+document.getElementById('lySize').value")
        assert after > before + 3, f"holding it moved {after - before}"
    _panel(check)


def test_a_single_press_moves_exactly_one():
    """Hold-to-repeat must not turn a tap into a run."""
    def check(pg, p):
        before = pg.evaluate("+document.getElementById('lySize').value")
        pg.click("#lySize ~ .numbtn.up")
        pg.wait_for_timeout(900)
        assert pg.evaluate("+document.getElementById('lySize').value") \
            == before + 1
    _panel(check)


def test_the_panel_is_not_rebuilt_while_a_stepper_is_down():
    """A button that leaves the page between the press and the release never
    reports a click at all - which is how this failed in Firefox and not in
    Chromium."""
    def check(pg, p):
        b = pg.locator("#lySize ~ .numbtn.up").bounding_box()
        pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        pg.mouse.down()
        pg.wait_for_timeout(150)
        same = pg.evaluate("""(()=>{const btn=document.querySelector(
            '#lySize ~ .numbtn.up');
            renderInspector();
            return btn === document.querySelector('#lySize ~ .numbtn.up');})()""")
        pg.mouse.up()
        pg.wait_for_timeout(400)
        assert same is True, "the button was replaced under the pointer"
    _panel(check)


def test_a_step_still_lands_if_the_box_was_replaced_under_it():
    """The panel is held still while a stepper is down, so this should not
    happen - but `stepNum` is called from a timer that outlives any one frame,
    and writing into a node that has left the page fails silently. It finds the
    box again by name."""
    def check(pg, p):
        moved = pg.evaluate("""(()=>{
            const live = document.getElementById('lySize');
            const before = +live.value;
            // a stale reference: same id, no longer on the page
            const stale = live.cloneNode(true);
            stepNum(stale, 1);
            return {before, after:+document.getElementById('lySize').value};})()""")
        assert moved["after"] == moved["before"] + 1, moved
    _panel(check)


def test_chromium_is_left_on_its_own_scrollbar_rules():
    """The fence has to actually fence. Chromium answers True to
    `selector(::-webkit-scrollbar)`, so the `@supports not` block is skipped
    and `scrollbar-color` never reaches it - which is what keeps the painted
    bar rather than the pale standard one with its stepper arrows.

    If this ever flips, the pale bar comes straight back and nothing else in
    the suite would notice.
    """
    def check(pg, p):
        assert pg.evaluate(
            "CSS.supports('selector(::-webkit-scrollbar)')") is True
        got = pg.evaluate(
            "getComputedStyle(document.body).scrollbarColor")
        assert got in ("auto", ""), \
            f"scrollbar-color reached Chromium ({got}) and disabled the rest"
    _panel(check)


def _saved(pg, timeout=180000):
    """Wait until the app says it has finished saving, then look.

    Polling the file on a stopwatch is guessing at how long a machine takes,
    and in a full run - twenty-five files and a browser each - a save that
    re-lays a block out and rebuilds a page can take tens of seconds. The
    browser knows the answer exactly: nothing is dirty and no lane of
    `saveTypesetting._q` is still holding a request. So ask it.
    """
    pg.wait_for_function(
        "()=>(typeof typesetDirty==='undefined'||typesetDirty===null)"
        "&&!(saveTypesetting._q&&Object.keys(saveTypesetting._q).length)",
        timeout=timeout)


def test_the_outline_arrow_does_not_snap_the_value_back():
    """lee: *"i can manuly tye a number and wheni try to use teh arrow its
    reverts back to 1"*.

    Typing worked because nothing rebuilds mid-keystroke. The arrow saves, the
    save rebuilds the panel, and every style field in it read the SAVED copy of
    the value rather than the live one - so the rebuild put back the number
    from before the press, and `||1` turned the miss into a 1.

    ## And the same complaint from the other end

    The panel was fixed and the FILE still ended up with the wrong number. Four
    presses posted 2, 3, 4 and 5, in that order, a fifth of a second apart, and
    what was saved was **4**: four overlapping read-modify-writes on a threaded
    server, and the one that finished last won whatever it had read first. On
    screen everything said 5.

    This test used to pass on that bug. It waited a flat 1200ms and looked -
    which is a sample of a race, not a check of a result, and the sample it
    happened to take was usually 5. `saveTypesetting` queues per region now, so
    the answer is settled rather than lucky, and the wait below is for THE
    THING BEING ASSERTED rather than for a number of milliseconds: a save
    re-lays the block out and rebuilds the page, and how long that takes is not
    this test's business.
    """
    def check(pg, p):
        before = pg.evaluate("+document.getElementById('lyStroke').value")
        for _ in range(4):
            pg.click("#lyStroke ~ .numbtn.up")
            pg.wait_for_timeout(60)
        assert pg.evaluate("+document.getElementById('lyStroke').value") \
            == before + 4
        _saved(pg)
        got = (p.pages[0].regions[0].get("layout_override") or {}).get("stroke")
        assert got == before + 4, got
        # ...and it STAYS there: a later save carrying an older number is
        # exactly the bug, so nothing may land after the answer is right.
        pg.wait_for_timeout(1500)
        assert (p.pages[0].regions[0].get("layout_override") or {}) \
            .get("stroke") == before + 4
    _panel(check)


def test_two_saves_for_one_box_are_never_in_the_air_at_once():
    """Which is the whole of the fix, and the only part of it that is a rule.

    HOW MANY requests a flurry of presses makes is not: a save that comes home
    before the next press is its own save, and one that does not is superseded
    at the gate - so the count is a fact about how fast the machine is, and a
    test that pinned it would be testing the machine. What must hold on every
    machine is that the second one does not start until the first has come
    home, because two at once is two read-modify-writes over one region and the
    loser is whatever the person typed last.
    """
    def check(pg, p):
        live, worst = [0], [0]

        def out(rq):
            if rq.method == "POST" and "/region/" in rq.url:
                live[0] += 1
                worst[0] = max(worst[0], live[0])

        def home(rq):
            if rq.method == "POST" and "/region/" in rq.url:
                live[0] -= 1

        pg.on("request", out)
        pg.on("requestfinished", home)
        pg.on("requestfailed", home)
        before = pg.evaluate("+document.getElementById('lyStroke').value")
        for _ in range(10):
            pg.click("#lyStroke ~ .numbtn.up")
            pg.wait_for_timeout(40)
        want = before + 10
        _saved(pg)
        got = (p.pages[0].regions[0].get("layout_override") or {}).get("stroke")
        assert got == want, got
        assert worst[0] <= 1, ("saves overlapped", worst[0])
    _panel(check)


def test_every_style_field_reads_the_live_copy():
    """One helper, `styleNow`, and nothing reaching past it. A field that goes
    to `layout_override` directly is a field one save behind itself."""
    from pathlib import Path
    src = (PKG / "static" / "js"
           / "panels.js").read_text("utf8")
    body = src[src.index("function typesettingPanel(r){"):]
    body = body[:body.index("\nfunction ")] if "\nfunction " in body else body
    import re as _re
    stale = _re.findall(r"ov\.(\w+)\s*(?:\?\?|\|\|)", body)
    allowed = {"rotate", "font", "lines", "font_size", "leading", "locked"}
    assert set(stale) <= allowed, sorted(set(stale) - allowed)


def test_the_font_picker_has_no_geometry_of_its_own():
    """Three tests stood here - the list visible wherever the panel is
    scrolled, the open list no taller than the room it has, and closing it
    putting its inline sizing back. All three were about a menu positioned by
    hand: fixed to the viewport because an absolutely positioned child cannot
    escape a scrolling ancestor, then cut to the space on whichever side it
    opened. lee: *"fix this make teh list be visible"*, and later *"the text
    drop down still dosent work re design it and remake it so taht it works"*.

    A native <select> is drawn by the browser over the page. There is no
    ancestor to escape, no height to cut and no inline style to clear, so what
    is left to check is that none of that machinery is still here to go wrong.
    """
    def check(pg, p):
        got = pg.evaluate("""(()=>{
            const s=document.getElementById('lyFont');
            return {tag:s.tagName, widget:!!s._fw,
                    menus:document.querySelectorAll('.fsel-menu').length,
                    placer:typeof placeFontMenu,
                    closer:typeof closeFontMenu};})()""")
        assert got == {"tag": "SELECT", "widget": False, "menus": 0,
                       "placer": "undefined", "closer": "undefined"}, got
    _panel(check)

