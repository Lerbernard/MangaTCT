"""The per-bubble font picker works, and leaves the panel alive.

lee, four times: *"the font drop box donat work"*, *"the test for this bubble
is broken"*, *"this is still broken, when i open it it opens and close and isnt
repsosive after that"*, and finally *"the text drop down still dosent work re
design it and remake it so taht it works"*.

It was a custom widget: the native select hidden, a div mirroring it, a search
box, a recents band, a menu positioned by hand, and a click handler writing the
pick back through whichever select was live at the time. Each round fixed the
failure in front of it and the next one arrived. It is a native `<select>` now
- the browser opens it, scrolls it, filters it on type-ahead, and cannot leave
it open over a panel that has since been rebuilt.

What is left to get wrong is the panel around it. The typesetting panel redraws
itself constantly and already knew not to redraw out from under a field
somebody is using: every control saves on `change`, which fires on BLUR, and an
element removed while it still has focus never blurs. So a redraw asked for
while a field has focus is deferred until that field blurs - and:

* a deferred redraw runs a TICK after the blur, so the interaction that caused
  it has finished; and
* the wait is released if the field it is waiting on has left the page, however
  that happened. Chromium fires a blur on removal, Firefox does not, and a wait
  released by nothing else leaves the panel dead for the rest of the session.
"""
import shutil
import time
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((900, 700, 3), 240, np.uint8)
    cv2.ellipse(img, (350, 300), (200, 120), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (350, 300), (200, 120), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [240, 240, 220, 120],
        "bubble_bbox": [150, 180, 400, 240],
        "polygon": [[240, 240], [460, 240], [460, 360], [240, 360]],
        "confidence": 0.9, "src_text": "テスト",
        "dst_text": "HELLO THERE FRIEND"}]
    p.pages[0].detected = True
    return p


@pytest.fixture()
def panel(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "fs"))
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
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(600)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _with_a_redraw_waiting(pg):
    """Put the panel in the state lee's was in: a field focused, and a redraw
    asked for and deferred. Touching any control in this panel does that."""
    pg.evaluate("""(()=>{const i=document.querySelector('#inspector input[type=number]');
        if(!i) throw new Error('no field in the typesetting panel to focus');
        i.focus();})()""")
    pg.evaluate("renderInspector()")
    assert pg.evaluate("!!renderInspector._pending"), \
        "the panel did not defer the redraw, so this test proves nothing"


# ------------------------------------------------------------- the dropdown

def test_the_picker_is_a_select(panel):
    """Not a widget standing in for one. Everything below is about the panel
    around it; this is the thing itself."""
    pg, _p, errs = panel
    got = pg.evaluate("""(()=>{const s=document.getElementById('lyFont');
        return {tag:s.tagName, shown:getComputedStyle(s).display!=='none',
                widget:!!s._fw, options:s.options.length>0};})()""")
    assert got == {"tag": "SELECT", "shown": True,
                   "widget": False, "options": True}, got
    assert not errs, errs[:2]


def test_using_it_while_a_redraw_is_waiting_leaves_the_panel_alive(panel):
    """*"isnt repsosive after that"* - the half that survives the redesign.

    A select takes focus when it is used, which defers the redraw onto it. If
    that wait is never released, every later redraw returns early and nothing
    in the panel changes again for the rest of the session.
    """
    pg, _p, errs = panel
    _with_a_redraw_waiting(pg)
    opts = pg.evaluate("""[...document.getElementById('lyFont').options]
        .map(o=>o.value).filter(Boolean)""")
    assert opts, "no fonts offered"
    # Reaching for the picker is what takes focus off the field the redraw is
    # waiting on - the blur, and the whole reason the wait exists.
    pg.focus("#lyFont")
    pg.select_option("#lyFont", opts[0])
    pg.wait_for_timeout(600)
    # The picker itself now holds the wait, which is right - it has focus and
    # is being used. What must not happen is the wait outliving it.
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.wait_for_timeout(800)
    assert pg.evaluate("!renderInspector._pending"), \
        "the panel is still waiting for something that has gone"
    alive = pg.evaluate("""(()=>{
        document.getElementById('inspector').innerHTML='<b id="probe">x</b>';
        renderInspector();
        return !document.getElementById('probe');})()""")
    assert alive is True, "the panel stopped redrawing"
    assert not errs, errs[:2]


def test_picking_a_font_from_it_sticks(panel):
    """It has to do its job, not merely stay on screen."""
    pg, _p, errs = panel
    _with_a_redraw_waiting(pg)
    opts = pg.evaluate("""[...document.getElementById('lyFont').options]
        .map(o=>o.value).filter(Boolean)""")
    assert opts, "no fonts offered"
    pg.focus("#lyFont")
    pg.select_option("#lyFont", opts[0])
    pg.wait_for_timeout(700)
    assert pg.evaluate("document.getElementById('lyFont').value") == opts[0]
    assert not errs, errs[:2]


# ------------------------------------------------- the wait that never ended

def test_a_wait_on_a_field_that_has_gone_is_released(panel):
    """The panel replaces its own HTML constantly, so the field a redraw is
    waiting on can simply cease to exist. `blur` does not reliably fire for an
    element removed while focused - Chromium sends it, Firefox does not - and
    a wait released by nothing else leaves the panel dead."""
    pg, _p, errs = panel
    # Chromium does send the blur, so the state Firefox leaves behind is set
    # up here directly: waiting, on a field that is no longer on the page and
    # whose listener will never run. That is the whole of what has to be
    # survivable, and it is the state the panel used to die in.
    stuck = pg.evaluate("""(()=>{
        const gone=document.createElement('input');
        gone.type='number';                     // detached: never in the page
        renderInspector._pending=true;
        renderInspector._on=gone;
        document.getElementById('inspector').innerHTML='<b id="probe">x</b>';
        renderInspector();                      // must not return early
        return {pending:!!renderInspector._pending,
                redrew:!document.getElementById('probe')};})()""")
    assert stuck["pending"] is False, \
        "the panel is still waiting for a field that is no longer on the page"
    assert stuck["redrew"] is True, "the panel did not redraw"
    assert not errs, errs[:2]


def test_nothing_of_the_old_widget_is_left_on_the_page(panel):
    """It hung two `window` listeners per open so the page moving would put it
    away, and the panel could remove the whole thing while it was open - a pair
    of listeners per open, holding a node that is not on the page. None of that
    exists to leak now, and this is what says so."""
    pg, _p, errs = panel
    left = pg.evaluate("""(()=>{
        for(let k=0;k<6;k++){
          document.getElementById('inspector').innerHTML='';
          renderInspector();
          select(1);
        }
        window.dispatchEvent(new Event('scroll', {bubbles:true}));
        return document.querySelectorAll('.fsel').length;})()""")
    assert left == 0, f"{left} of the old widgets are still on the page"
    assert not errs, errs[:2]


# ------------------------------- and it reaches the page, not just the box

def _pick(pg, want, p=None):
    """Choose a face, and WAIT FOR THE SERVER rather than for a stopwatch.

    Picking one starts a debounce and then a round trip; a fixed sleep is a
    guess about a machine's load, and the first version of this asserted after
    900ms and failed on a busy box while the product was working. Waiting for
    the thing being asserted is not a loosening.

    ...and the thing being asserted is the LAYOUT, not only the override. The
    server stores the override and then lays the block out again from it, and
    this reads the live project object from another thread - so there is a
    window, a few milliseconds wide on an idle machine and far wider on a
    loaded one, where the override already names the new face and the layout
    still names the old one. Waiting for the first and asserting the second is
    waiting for the wrong thing: it went red in batch 3 of a full run and
    passed alone every time.
    """
    opts = pg.evaluate("""[...document.getElementById('lyFont').options]
        .map(o=>o.value).filter(Boolean)""")
    hit = next((o for o in opts if want in o), None)
    assert hit, (want, opts[:6])
    pg.focus("#lyFont")
    pg.select_option("#lyFont", hit)
    if p is None:
        pg.wait_for_timeout(1200)
        return hit
    for _ in range(200):
        r = p.pages[0].regions[0]
        if ((r.get("layout_override") or {}).get("font") == hit
                and (r.get("layout") or {}).get("font") == hit):
            break
        browserpool.settled(pg)
        time.sleep(0.05)
    return hit


def test_the_face_reaches_the_stored_layout_and_not_only_the_menu(panel):
    """lee: *"chaneg teh font in teh side bar in after it been typeset is not
    working"*.

    The test above proved the `<select>` keeps the value it was given, which
    is a statement about the widget and not about the typesetting. What was
    never checked is the thing he was looking at: does the PAGE come out in
    that face?

    Four places have to agree, and each of them has been wrong at least once:
    the override the panel saves, the layout the server recomputes from it,
    the `font_path` on that layout - which is what `render_page` draws with -
    and the copy the browser holds and previews from.
    """
    pg, p, errs = panel
    hit = _pick(pg, "Anton", p)
    r = p.pages[0].regions[0]
    assert (r.get("layout_override") or {}).get("font") == hit, \
        "the panel did not save it"
    assert (r.get("layout") or {}).get("font") == hit, \
        "the server recomputed the layout in the old face"
    assert pg.evaluate(
        "(()=>{const x=regions.find(y=>y.id===1);"
        "return (x.layout&&x.layout.font)||''})()") == hit, \
        "the browser is previewing the old face"
    assert not errs, errs[:2]


@pytest.fixture()
def sfx_panel(tmp_path):
    """The same page with the block typed as a SOUND EFFECT from the start.

    Not the bubble fixture with its kind changed and the page reloaded: that
    is two variables in one test, and when it failed there was no telling
    whether the sound effect or the reload was to blame.
    """
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "fx"))
    p.pages[0].regions[0]["kind"] = "sfx"
    p.pages[0].regions[0]["dst_text"] = "CRASH"
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
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(600)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def test_and_on_a_sound_effect_too(sfx_panel):
    """Sound effects take a different road through the fitter - laid out
    letter by letter along an axis of their own by `fit_sfx_region`, which
    resolves its own face. It reached for `cfg.font_path` directly once and
    quietly ignored the sound-effect font.

    The two halves are asserted separately, so a failure says WHICH half:
    whether the panel saved the choice, or whether the server rebuilt the
    layout without it."""
    pg, p, errs = sfx_panel
    hit = _pick(pg, "Bangers", p)
    r = p.pages[0].regions[0]
    assert (r.get("layout_override") or {}).get("font") == hit, \
        ("the panel did not save it", (r.get("layout_override") or {}).get("font"))
    assert (r.get("layout") or {}).get("font") == hit, \
        ("a sound effect ignored the face it was given",
         (r.get("layout") or {}).get("font"))
    assert not errs, errs[:2]
