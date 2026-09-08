# -*- coding: utf-8 -*-
"""The Image view settles into the page the export writes.

lee: *"i want you to make it so that what is in the editor and what is
exported are 100% the exact same"*.

## Why it could not be done by calibrating

The editor lays the typesetting out in the browser, over the cleaned plate:
CSS text, SVG masks, `text-shadow`. The export draws it with PIL on the
server. Two programs, two rasterisers. They have been measured against each
other and pushed to between 0.68 and 0.93 of each other's ink
(`test_the_editor_looks_like_the_page`), and the last stretch is not
reachable: nothing makes a browser's blur round the way a Gaussian in numpy
rounds.

So the answer is not a better copy. It is to stop looking at the copy.

## What happens instead

`/render/<i>?mode=typeset` is the exported page - the same `typeset_page`, the
same `render_page`, the same compositing `do_export` runs, one function away
from the file that gets written. A moment after nothing is being touched, the
browser fetches that and lays it over its own drawing, and hides the drawing
underneath. Touch anything and it is gone again before the next frame, so
editing is as quick as it ever was.

Two pictures, and it is always clear which: a badge says *exported page* when
the real one is up.

## What this file guards

* the picture the view asks for is the picture the export writes, pixel for
  pixel, not merely one that looks like it;
* the key it hangs on the URL changes when the TYPESETTING changes, which
  `vkey` does not - hang it on that and a change of font leaves the browser
  showing the render from before it;
* the drawn overlay and the render are never both on screen;
* and everything the person can click is still on top of both.
"""
import re
import shutil

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

HERE = "test_what_you_see_is_what_is_exported"


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 240, 3), 246, np.uint8)
    cv2.rectangle(img, (30, 40), (200, 150), (0, 0, 0), 2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [40, 50, 150, 90],
        "bubble_bbox": [32, 42, 166, 106],
        "polygon": [[40, 50], [190, 50], [190, 140], [40, 140]],
        "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


# --------------------------------------------- the picture is the exported one

def test_the_view_is_the_export_pixel_for_pixel():
    """Not "looks like": the same array. `render_index` in typeset mode and
    the export both run typeset_page, render_page and the same compositing -
    and if they ever stop doing that, this is what says so."""
    from mangatl import editor
    root = scratch("_tmp_wysiwyg")
    try:
        p = _project(root)
        editor.do_typeset(p, 0)
        shown = cv2.imdecode(
            np.frombuffer(editor.render_index(p, 0, "typeset"), np.uint8),
            cv2.IMREAD_COLOR)
        out = editor.export_page(p, 0, mode="full")
        wrote = cv2.imread(out, cv2.IMREAD_COLOR)
        assert shown is not None and wrote is not None
        assert shown.shape == wrote.shape, (shown.shape, wrote.shape)
        # The view is JPEG for the wire and the file may be PNG, so the
        # comparison is of what a person sees, not of the bytes: a handful of
        # levels of encoding noise, and nothing structural.
        d = np.abs(shown.astype(np.int16) - wrote.astype(np.int16))
        assert float(d.mean()) < 2.0, ("the view is not the exported page",
                                       float(d.mean()), int(d.max()))
        assert float((d.max(2) > 24).mean()) < 0.01, float((d.max(2) > 24).mean())
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_key_moves_when_the_typesetting_does():
    """`vkey` is asked with no mode, so it says nothing about the font or the
    size - right for the clean plate, which they cannot change, and wrong for
    this view. Hang the exported page on `vkey` and a change of font leaves
    the browser showing the render from before it."""
    from mangatl import editor
    root = scratch("_tmp_wysiwyg_key")
    try:
        p = _project(root)
        v0 = editor._render_key(p, 0)
        t0 = editor._render_key(p, 0, "typeset")
        p.settings["max_font"] = int(p.settings.get("max_font", 34)) + 6
        assert editor._render_key(p, 0) == v0, \
            "the plate's key moved for a typesetting change"
        assert editor._render_key(p, 0, "typeset") != t0, \
            "the finished page's key did NOT move for a typesetting change"
        # ...and a change to the page itself moves both.
        p.pages[0].regions[0]["bbox"] = [40, 50, 151, 90]
        assert editor._render_key(p, 0) != v0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_page_hands_over_both_keys():
    """The browser needs them both: one for the plate it draws on, one for the
    finished page it settles into."""
    from mangatl import editor
    root = scratch("_tmp_wysiwyg_api")
    try:
        p = _project(root)
        assert editor._render_key(p, 0, "typeset")
        # the field the endpoint sends, and the name the browser reads
        src = open(editor.__file__, encoding="utf-8").read()
        assert '"tkey": _render_key(p, i, "typeset")' in src
        js = open(editor.STATIC + "/js/frames.js", encoding="utf-8").read()
        assert "tKey[i]=d.tkey" in js
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------- and the wiring itself

def _js(name):
    from mangatl import editor
    return open(editor.STATIC + "/js/" + name, encoding="utf-8").read()


def test_only_one_of_the_two_pictures_is_ever_shown():
    """The render is laid OVER the browser's drawing and the drawing is hidden
    under it. Both at once is a double image, and the seam between two
    rasterisers is exactly where it would show."""
    from mangatl import editor
    css = open(editor.STATIC + "/css/editor.css", encoding="utf-8").read()
    assert "#stage.exact #overlay .tl{visibility:hidden}" in css
    js = _js("exactview.js")
    # shown and hidden by the same class, from one place each
    assert "st.classList.add('exact')" in js
    assert "st.classList.remove('exact')" in js


def test_every_redraw_takes_it_off_again():
    """`drawText` is the one choke point: an edit, a zoom, a selection or a
    page turn all pass through it, and each of them means the render on screen
    is out of date. Off at the top, asked for again at the bottom."""
    js = _js("typesetting.js")
    body = js[js.index("function drawText()"):]
    body = body[:body.index("\nfunction ")]
    assert "exactOff" in body, "a redraw leaves a stale render on screen"
    assert body.count("exactSoon") >= 2, \
        "both ways out of drawText have to re-arm it"
    assert body.index("exactOff") < body.index("exactSoon")


def test_what_you_can_click_stays_on_top():
    """The render is a picture, not a surface: the boxes, the handles and the
    text you type into all live above it and must keep working."""
    from mangatl import editor
    css = open(editor.STATIC + "/css/editor.css", encoding="utf-8").read()
    rule = css[css.index("#exact{"):css.index("#exact.on")]
    assert "pointer-events:none" in rule
    z = int(re.search(r"z-index:(\d+)", rule).group(1))
    boxz = int(re.search(r"\.box\{[^}]*z-index:(\d+)", css, re.S).group(1))
    assert z < boxz, ("the render is above the boxes", z, boxz)


def test_it_can_be_turned_off_and_stays_off():
    """A switch, remembered. Off means the editor behaves exactly as it did
    before this existed."""
    from mangatl import editor
    js = _js("exactview.js")
    assert "localStorage.setItem('mangatl.exact'" in js
    assert "localStorage.getItem('mangatl.exact')" in js
    assert "function toggleExact" in js
    html = open(editor.STATIC + "/editor.html", encoding="utf-8").read()
    assert 'id="exactCk"' in html and "toggleExact(this.checked)" in html


def test_the_switch_is_left_of_the_view_buttons():
    """That group is laid out from the RIGHT edge, so anything that appears to
    the right of the two view buttons shoves them - and this switch appears
    and disappears with the view, so it would shove them on every press.

    lee said it about the last pair of switches to land here: *"just make them
    she up to the left of the 2 tab buttons so that the 2 tab buttons dont
    move"*. `test_the_view_buttons_do_not_move_when_the_view_changes` measures
    it in pixels; this says why, next to the thing that has to obey it."""
    from mangatl import editor
    html = open(editor.STATIC + "/editor.html", encoding="utf-8").read()
    assert html.index('id="exactWrap"') < html.index('class="views"'), \
        "the Exact switch is to the right of the view buttons"
    # ...and wearing the same clothes as the switches beside it
    row = html[html.index('id="exactWrap"'):]
    assert 'class="swx"' in row[:120], row[:120]


def test_it_never_writes_the_page_back():
    """The view appears BY ITSELF, so it must not change anything. Building
    the typeset render lays the page out again and commits it - right when
    somebody asked for that view, and a quiet re-typeset of the block being
    edited when it arrives on its own. Four tests about emptied boxes found
    this the hard way."""
    from mangatl import editor
    js = _js("exactview.js")
    assert "ro=1" in js, "the exact view is asking for a page that commits"
    src = open(editor.__file__, encoding="utf-8").read()
    assert "commit: bool = True" in src
    assert "if commit:\n                    p.commit(i, page)" in src

    root = scratch("_tmp_wysiwyg_ro")
    try:
        p = _project(root)
        editor.do_typeset(p, 0)
        # a hand edit that a re-typeset would undo: the block is deliberately
        # empty, which is exactly the state the four tests were about
        p.pages[0].regions[0]["layout"]["lines"] = []
        editor.render_index(p, 0, "typeset", commit=False)
        assert p.pages[0].regions[0]["layout"]["lines"] == [], \
            "looking at the exported page filled an emptied box back in"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_it_never_asks_while_something_is_being_edited():
    """The whole point is that it costs nothing while you work: it is only
    fetched when the page is settled, and a dirty block is not settled."""
    js = _js("exactview.js")
    fn = js[js.index("function exactPossible()"):]
    fn = fn[:fn.index("\n}")]
    for guard in ("typesetDirty", "editing", "view !== 'typeset'"):
        assert guard in fn, guard


# ------------------------------------------------------ and in a real browser

@pytest.fixture()
def ed(tmp_path):
    """The editor, open on a typeset page, in the Image view."""
    import threading
    from http.server import ThreadingHTTPServer

    import browserpool
    from mangatl import editor

    p = _project(str(tmp_path / "wys"))
    editor.do_typeset(p, 0)
    p.save()
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip("chromium unavailable")
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1400, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _state(pg):
    return pg.evaluate("""(()=>{
      const st=document.getElementById('stage');
      const ex=document.getElementById('exact');
      const tl=document.querySelector('#overlay .tl');
      return {on: !!(st&&st.classList.contains('exact')),
              lit: !!(ex&&ex.classList.contains('on')),
              src: (ex&&ex.getAttribute('src'))||'',
              textHidden: tl ? getComputedStyle(tl).visibility==='hidden' : null,
              badge: (document.getElementById('exactBadge')||{}).textContent||''};
    })()""")


def test_the_page_settles_into_the_exported_one(ed):
    """Left alone, the view becomes the export. This is the whole feature."""
    pg, _p, errs = ed
    pg.evaluate("toggleExact(true)")
    pg.wait_for_timeout(2600)
    got = _state(pg)
    assert got["on"] and got["lit"], got
    # blob:, not a URL into any cache. The picture is fetched as bytes with
    # cache:'no-store' - the one fetch mode the spec says must bypass the
    # browser's HTTP cache entirely - after a picture survived a restart AND
    # an F5 in lee's browser. A src that is not a blob is a src that
    # negotiated with a cache again.
    assert got["src"].startswith("blob:"), got["src"]
    assert got["textHidden"] is True, "the browser's own copy is still showing"
    assert "export" in got["badge"].lower(), got["badge"]
    assert not errs, errs[:2]


def test_the_browsers_own_strokes_hide_under_the_settled_page(ed):
    """THE ONE LEE FOUND HIMSELF, after a day spent hunting it as a cache:
    *"teh clenening layers is shouing abobe eth text layers thats the
    issue"*. The paint canvases sit at z-index 18 and 23; the settled render
    at 5. Every stroke is already IN the render - under band baked into the
    plate, over band composited after the text - so a visible canvas draws
    the browser's copy of the strokes over the server's finished page: his
    heal covered the sfx, a white stroke cut the letters out of a balloon,
    and hiding a layer "brought the text back" by clearing the canvas."""
    pg, _p, errs = ed
    pg.evaluate("""(()=>{
      // both canvases exist and hold ink, as they would mid-edit
      const c=document.createElement('canvas'); c.id='paint';
      c.width=c.height=50;
      c.style.cssText='position:absolute;left:0;top:0;z-index:18';
      document.getElementById('stage').appendChild(c);
      const o=document.createElement('canvas'); o.id='paintOver';
      o.width=o.height=50;
      o.style.cssText='position:absolute;left:0;top:0;z-index:23';
      document.getElementById('stage').appendChild(o);
    })()""")
    pg.evaluate("toggleExact(true)")
    pg.wait_for_timeout(2600)
    got = pg.evaluate("""(()=>{
      const st=document.getElementById('stage');
      return {on: st.classList.contains('exact'),
              paint: getComputedStyle(document.getElementById('paint')).visibility,
              over: getComputedStyle(document.getElementById('paintOver')).visibility};
    })()""")
    assert got["on"], got
    assert got["paint"] == "hidden",         "the under-band canvas draws over the exported page: %r" % (got,)
    assert got["over"] == "hidden",         "the over-band canvas draws over the exported page: %r" % (got,)
    # ...and the moment the render comes off, the strokes are back on screen
    pg.evaluate("exactOff()")
    got2 = pg.evaluate(
        "getComputedStyle(document.getElementById('paint')).visibility")
    assert got2 == "visible", got2
    assert not errs, errs[:2]


def test_touching_it_puts_the_fast_copy_straight_back(ed):
    """...and editing has to stay instant, so the render goes the moment
    anything is drawn - not when its replacement arrives."""
    pg, _p, errs = ed
    pg.evaluate("toggleExact(true)")
    pg.wait_for_timeout(2600)
    assert _state(pg)["on"], "it never settled, so this proves nothing"
    now = pg.evaluate("(()=>{drawText();return (()=>{"
                      "const st=document.getElementById('stage');"
                      "return st.classList.contains('exact');})();})()")
    assert now is False, "the exported page stayed up over a redraw"
    got = _state(pg)
    assert got["textHidden"] is False, "the browser's copy did not come back"
    assert not errs, errs[:2]


def test_the_switch_turns_it_off(ed):
    pg, _p, errs = ed
    pg.evaluate("toggleExact(false)")
    pg.wait_for_timeout(2400)
    got = _state(pg)
    assert not got["on"] and not got["lit"], got
    assert pg.evaluate("localStorage.getItem('mangatl.exact')") == "0"
    assert not errs, errs[:2]
