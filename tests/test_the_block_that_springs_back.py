"""A block that springs back to the size it was.

lee: *"when i reload the page teh text boxes revert to the smaller size, wheni
move it a little bit it reverts to the bigger size and teh after cliking off it
revest back t teh samler text"*. Three states, two sizes, and the block flipping
between them on every touch.

There are two copies of a block's size and line breaks while you are working on
one: the LAYOUT, which is what is drawn on the canvas, and the two fields in
the Typesetting panel, which is what `currentPatch` builds every save out of.

Dragging a corner re-fits the text locally and writes the answer onto the
layout. Nothing wrote it into the panel - the sync that exists for this runs
only when the SERVER sends a fit back, and while the mouse is down there is no
server. So the panel kept the size from before the drag, and the next save that
was not itself a fit posted it straight back over the top.

Big is the layout. Small is the panel. Whichever spoke last won.

Two fixes, and both are needed. `panelSaysWhatTheLayoutSays` puts a local
re-fit into the panel at the moment it happens, and `panelIsAbout` stops the
panel answering for a block it is not showing at all.
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    from mangatl.models import TextRegion

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((420, 520, 3), 245, np.uint8)
    cv2.ellipse(img, (250, 200), (170, 130), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 200), (170, 130), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())

    page = p.materialize(0)
    mask = np.zeros((420, 520), np.uint8)
    cv2.rectangle(mask, (150, 130), (350, 270), 255, -1)
    r = TextRegion(id=1, bbox=(150, 130, 200, 140), kind="bubble",
                   text_mask=mask, bubble_mask=mask,
                   bubble_bbox=(150, 130, 200, 140),
                   polygon=[[150, 130], [350, 130], [350, 270], [150, 270]])
    r.src_text = "ここの湯は白っぽく濁っている"
    r.dst_text = ("The water here is cloudy and white, "
                  "so it should be good for neuralgia.")
    r.order = 0
    page.regions = [r]
    p.commit(0, page)
    p.pages[0].detected = True

    # Laid out, because a block with no layout has nothing to spring between.
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    try:
        editor.do_typeset(p, 0)
    finally:
        editor.PROJECT = was
    return p


@pytest.fixture()
def editor_page(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = str(tmp_path / "springy")
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip("chromium unavailable")
    with browserpool.session() as br:
        ctx = br.new_context(viewport={"width": 1500, "height": 950})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        try:
            yield pg, p, base, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def drawn_size(pg):
    """What the canvas is drawing at, which is what lee can see."""
    return pg.evaluate("""(()=>{
        const r=(typeof regions!=='undefined'?regions:[]).find(x=>x.id===1);
        return r && r.layout ? r.layout.font_size : null;})()""")


def panel_size(pg):
    return pg.evaluate("""(()=>{const e=document.getElementById('lySize');
        return e ? +e.value : null;})()""")


def saved_size(p):
    """What is on disk, which is what a reload comes back to."""
    rec = p.pages[0].regions[0]
    return int((rec.get("layout") or {}).get("font_size") or 0)


def select_it(pg):
    pg.evaluate("select(1)")
    browserpool.settled(pg)


def grow_it(pg, by=90):
    """Drag the south-east corner outwards, which is the gesture that scales
    the text with the box."""
    pg.evaluate("""(([by])=>{
        const r=regions.find(x=>x.id===1);
        const f=(r.layout.frame||[0,0,100,100]).slice();
        setFrame(r,[f[0],f[1],f[2]+by,f[3]+by]);
        localFit(r);
    })""", [by])
    browserpool.settled(pg)


# ------------------------------------------------------------------ the bug

def test_a_local_refit_is_in_the_panel_before_anything_is_saved(editor_page):
    """The moment the fix turns on. While the mouse is still down the layout
    has the new size; the panel must not still be holding the old one, because
    the panel is what the next save is built from."""
    pg, p, _base, errs = editor_page
    select_it(pg)
    before = panel_size(pg)
    assert before, "the panel should be showing this block"

    grow_it(pg)
    assert drawn_size(pg) > before, "a bigger box has to mean bigger text"
    assert panel_size(pg) == drawn_size(pg), \
        f"panel {panel_size(pg)} vs page {drawn_size(pg)}"
    assert not errs, errs


def test_the_patch_a_save_would_send_carries_the_size_on_screen(editor_page):
    """`currentPatch` is what every save posts. Asked directly, because it is
    the one place the two copies meet."""
    pg, _p, _base, errs = editor_page
    select_it(pg)
    grow_it(pg)
    got = pg.evaluate("""(()=>{const r=regions.find(x=>x.id===1);
        return currentPatch(r).font_size;})()""")
    assert got == drawn_size(pg), (got, drawn_size(pg))
    assert not errs, errs


def test_the_panel_never_answers_for_a_block_it_is_not_showing(editor_page):
    """The other way the two get crossed: the panel is built for the SELECTED
    block, and asking it about a different one posts one block's size onto
    another."""
    pg, _p, _base, errs = editor_page
    select_it(pg)
    got = pg.evaluate("""(()=>{
        const r=regions.find(x=>x.id===1);
        const was=r.layout.font_size;
        // A panel holding a different block's number, which is what it is the
        // moment the selection moves and the fields have not been rebuilt.
        document.getElementById('lySize').value = was + 40;
        const old=sel; sel=999;
        const p=currentPatch(r);
        sel=old;
        return [p.font_size, was];})()""")
    assert got[0] == got[1], \
        f"posted {got[0]} for a block whose size is {got[1]}"
    assert not errs, errs


# ---------------------------------------------------- and it stays that way

def test_it_does_not_spring_back_when_you_nudge_it_afterwards(editor_page):
    """lee's exact sequence. Grow it, let go, then move it a little - and the
    move must not carry the old size back with it."""
    pg, p, _base, errs = editor_page
    select_it(pg)
    grow_it(pg)
    big = drawn_size(pg)

    pg.evaluate("saveTypesetting(1, true, {fit:true})")
    pg.wait_for_timeout(700)
    browserpool.settled(pg)
    assert drawn_size(pg) >= big * 0.9, (drawn_size(pg), big)

    # ...and now the nudge, which sends no fit at all and used to post the
    # panel's stale size.
    pg.evaluate("""(()=>{
        const r=regions.find(x=>x.id===1);
        const f=r.layout.frame.slice();
        setFrame(r,[f[0]+4,f[1]+3,f[2],f[3]]);
        saveTypesetting(1, true, null);})()""")
    pg.wait_for_timeout(700)
    browserpool.settled(pg)

    assert drawn_size(pg) >= big * 0.9, \
        f"a nudge shrank it from {big} to {drawn_size(pg)}"
    assert saved_size(p) >= big * 0.9, \
        f"what is on disk is {saved_size(p)}, not {big} - a reload would shrink it"
    assert not errs, errs


def rewrap_it(pg, by=70):
    """Drag the EAST side, which re-wraps at the same size instead of scaling.
    A different local path, and the panel has to follow it too."""
    pg.evaluate("""(([by])=>{
        const r=regions.find(x=>x.id===1);
        const f=r.layout.frame.slice();
        setFrame(r,[f[0],f[1],Math.max(40,f[2]-by),f[3]]);
        localWrap(r, true);
    })""", [by])
    browserpool.settled(pg)


def test_a_rewrap_reaches_the_panel_too(editor_page):
    """Corners scale and sides re-wrap: two local paths, two chances to leave
    the panel behind. The line box is what a save posts as the block's words."""
    pg, _p, _base, errs = editor_page
    select_it(pg)
    rewrap_it(pg)
    on_page = pg.evaluate(
        "(()=>regions.find(x=>x.id===1).layout.lines.join('\\n'))()")
    in_panel = pg.evaluate(
        "(()=>document.getElementById('lyLines').value)()")
    assert in_panel == on_page, (in_panel, on_page)
    assert not errs, errs


def test_the_sync_leaves_a_field_somebody_is_typing_in_alone(editor_page):
    """A value replaced under the caret is a value they were halfway through
    changing. The panel follows the page except where somebody is holding
    the pen."""
    pg, _p, _base, errs = editor_page
    select_it(pg)
    typed = pg.evaluate("""(()=>{
        const sz=document.getElementById('lySize');
        sz.focus(); sz.value='9';
        const r=regions.find(x=>x.id===1);
        const f=r.layout.frame.slice();
        setFrame(r,[f[0],f[1],f[2]+90,f[3]+90]);
        localFit(r);
        return sz.value;})()""")
    assert typed == "9", f"the field was overwritten while it was focused: {typed}"
    assert not errs, errs


def test_the_panel_is_still_read_when_it_is_about_this_block(editor_page):
    """The guard must not throw the panel away altogether: a value typed into
    it is the person's answer and has to reach the save."""
    pg, _p, _base, errs = editor_page
    select_it(pg)
    got = pg.evaluate("""(()=>{
        const a=document.getElementById('lyAlign');
        a.value='left';
        const r=regions.find(x=>x.id===1);
        return currentPatch(r).align;})()""")
    assert got == "left", got
    assert not errs, errs
