"""What lee found the second time round.

* *"detete these"* - three unlabelled font dropdowns at the top of the Fonts
  section, saying AnimeAce, AnimeAce, CCWildWords.
* *"remoeve the second picture line up"* - the Box types rows did not line up:
  the default's row has no × so everything on it sat a button further along.
* *"you didnt add teh preloaded sub types"*
* *"the etxt box still rejexcts me deleteing all teh text"*
* *"the fre tansfor too shoude be able to move everything when i slect it"*
* *"make it so that i can select shapes like i can text boxes"*
* *"the hand tool and text tool is sttill duplicated up too"*
* *"make it si that dubble lciking the hand tool on the side is also make the
  page go to 100%"*
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root, text="HELLO THERE"):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト", "dst_text": text}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "again"))
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
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


# ------------------------------------------------------- deleting the words

def test_deleting_the_words_takes_the_typesetting_off_the_page(tmp_path):
    """Clearing a block's translation left its typesetting exactly where it was.
    `typeset_page` has nothing to fit for a block with no words, so it skipped
    it, and the layout from the run before stayed - which reads as the editor
    refusing the edit."""
    from mangatl import editor
    p = _project(str(tmp_path / "empty"))
    editor.do_typeset(p, 0)
    was = p.pages[0].regions[0]["layout"]
    assert was["lines"] == ["HELLO THERE"], was["lines"]

    p.pages[0].regions[0]["dst_text"] = ""
    editor.do_typeset(p, 0)
    now = p.pages[0].regions[0]["layout"]
    assert now is not None, "the box was thrown away with its words"
    assert now["lines"] == [], now["lines"]


def test_the_emptied_box_is_the_size_it_was(tmp_path):
    """lee: *"stay the last size it was"*. Falling back to the region's own
    rectangle put an emptied balloon back at box size and at the floor point
    size, so the box you clicked afterwards was not the one you emptied."""
    from mangatl import editor
    p = _project(str(tmp_path / "size"))
    editor.do_typeset(p, 0)
    was = dict(p.pages[0].regions[0]["layout"])
    p.pages[0].regions[0]["dst_text"] = ""
    editor.do_typeset(p, 0)
    now = p.pages[0].regions[0]["layout"]
    assert now["frame"] == was["frame"], (now["frame"], was["frame"])
    assert now["font_size"] == was["font_size"]


def test_it_is_still_the_same_box_after_the_project_is_reopened(tmp_path):
    """An empty layout used to be stored as nothing at all, so the frame was
    lost on the way to disk and the box came back at whatever the fitter last
    chose."""
    from mangatl.project import Project
    from mangatl import editor
    root = str(tmp_path / "trip")
    p = _project(root)
    editor.do_typeset(p, 0)
    p.pages[0].regions[0]["dst_text"] = ""
    editor.do_typeset(p, 0)
    frame = list(p.pages[0].regions[0]["layout"]["frame"])
    p.save()

    q = Project(None, root)
    lay = q.pages[0].regions[0]["layout"]
    assert lay is not None and lay["lines"] == []
    assert lay["frame"] == frame, (lay["frame"], frame)


def test_typing_into_it_again_brings_the_typesetting_back(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "back"))
    editor.do_typeset(p, 0)
    p.pages[0].regions[0]["dst_text"] = ""
    editor.do_typeset(p, 0)
    assert p.pages[0].regions[0]["layout"]["lines"] == []
    p.pages[0].regions[0]["dst_text"] = "BACK AGAIN"
    editor.do_typeset(p, 0)
    assert p.pages[0].regions[0]["layout"]["lines"] == ["BACK AGAIN"]


def test_the_last_box_on_a_page_counts_too(tmp_path):
    """`do_typeset` returned early when nothing on the page had any text -
    which is true of a one-box page the moment you delete its words, so the
    typesetting stayed on it and the guard was the reason."""
    from mangatl import editor
    p = _project(str(tmp_path / "last"))
    editor.do_typeset(p, 0)
    assert len(p.pages[0].regions) == 1
    p.pages[0].regions[0]["dst_text"] = ""
    editor.do_typeset(p, 0)
    assert p.pages[0].regions[0]["layout"]["lines"] == []


def test_a_block_that_never_had_words_is_left_alone(tmp_path):
    """The rule is "take the typesetting off", not "give every box a layout".
    A box waiting to be translated has nothing to take off and must stay as
    it is, or every undetected box on the page grows a frame."""
    from mangatl import editor
    p = _project(str(tmp_path / "never"), text="")
    editor.do_typeset(p, 0)
    assert p.pages[0].regions[0].get("layout") is None


# --------------------------------------------------- the preloaded sub-types

def test_an_old_project_still_gets_the_preloaded_types(tmp_path):
    """lee: *"you didnt add teh preloaded sub types"*.

    His project was stamped `kinds_seeded` by a build whose `PRELOADED` list
    was empty, and "seeded once" then meant "never again" - so every type
    added to the list afterwards could not reach it. What is remembered now is
    WHICH keys have been offered, so a new preload reaches an old project and
    a deleted one stays deleted.
    """
    from mangatl.project import Project
    from mangatl import kinds as K
    root = str(tmp_path / "old")
    p = _project(root)
    p.settings["custom_kinds"] = [{"key": "ck_test", "label": "test",
                                   "family": "bubble", "color": "#ed4545",
                                   "font": ""}]
    p.settings["kinds_seeded"] = True
    p.settings.pop("kinds_seeded_keys", None)
    p.save()

    q = Project(None, root)
    keys = {s["key"] for s in q.settings["custom_kinds"]}
    for want in K.PRELOAD_KEYS:
        assert want in keys, want
    assert "ck_test" in keys, "their own sub-type was dropped"


def test_a_preloaded_type_you_delete_stays_deleted(tmp_path):
    from mangatl.project import Project
    root = str(tmp_path / "del")
    p = _project(root)
    p.settings["kinds_seeded"] = True
    p.settings.pop("kinds_seeded_keys", None)
    p.save()
    q = Project(None, root)
    assert any(s["key"] == "whisper" for s in q.settings["custom_kinds"])
    q.settings["custom_kinds"] = [s for s in q.settings["custom_kinds"]
                                  if s["key"] != "whisper"]
    q.save()
    r = Project(None, root)
    assert not any(s["key"] == "whisper" for s in r.settings["custom_kinds"])
    # ...and everything else is still there
    assert len(r.settings["custom_kinds"]) == len(q.settings["custom_kinds"])


def test_a_new_project_is_not_seeded_twice(tmp_path):
    from mangatl.project import Project
    root = str(tmp_path / "new")
    p = _project(root)
    n = len(p.settings["custom_kinds"])
    p.save()
    q = Project(None, root)
    assert len(q.settings["custom_kinds"]) == n


# ------------------------------------------------------------- on the screen

def test_the_fonts_section_has_no_dropdowns_of_its_own(ed):
    """The three family faces are carried by selects that `saveSettings` reads;
    the row you set them from is the family's own row in Box types. They are
    marked `headless` and stay hidden - which mattered doubly when a widget
    stood beside each one, because hiding the select left the widget showing.
    lee: *"detete these"*."""
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
    browserpool.settled(pg)
    stray = pg.evaluate("""(()=>{
        const sec=document.querySelector('.set-section[data-sec=fonts]');
        const list=document.getElementById('ckList');
        return [...sec.querySelectorAll('select.fontsel')]
          .filter(s=>!list.contains(s)
                     && getComputedStyle(s).display!=='none')
          .map(s=>s.id||'?');})()""")
    # what is left is the picker on the "add a sub-type" row, which is a
    # control somebody uses
    assert stray == ["ckFont"], stray
    assert not errs, errs[:2]


def test_the_preloaded_types_are_on_the_settings_page(ed):
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
    browserpool.settled(pg)
    labels = pg.evaluate(
        "[...document.querySelectorAll('#ckList .ckrow .cknm')]"
        ".map(e=>e.value!==undefined?e.value:e.textContent)")
    for want in ("Regular speech", "Thought bubble", "Whisper",
                 "Narration on the art", "Big / impact"):
        assert want in labels, (want, labels)
    assert not errs, errs[:2]


def test_every_row_in_a_family_starts_and_ends_in_the_same_place(ed):
    """lee: *"line up"*. The default's row has no × to press, so it was a
    button and a gap wider than every row under it and its font picker began
    and ended somewhere else."""
    pg, _p, errs = ed
    pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
    browserpool.settled(pg)
    off = pg.evaluate("""(()=>{
        const fam=document.querySelector('#ckList .ckfam');
        const rows=[...fam.querySelectorAll('.ckrow')];
        if(rows.length<2) return 'too few rows';
        const b=rows.map(r=>r.querySelector('select.fontsel')
                             .getBoundingClientRect());
        return [Math.max(...b.map(x=>Math.abs(x.left-b[0].left))),
                Math.max(...b.map(x=>Math.abs(x.right-b[0].right)))];})()""")
    assert off != "too few rows"
    assert off[0] <= 1 and off[1] <= 1, off
    assert not errs, errs[:2]


def test_the_top_bar_is_a_zoom_readout_and_nothing_else(ed):
    """lee: *"the hand tool and text tool is sttill duplicated up too"*."""
    pg, _p, errs = ed
    ids = pg.evaluate(
        "[...document.querySelectorAll('#pageTools .zoomer button')]"
        ".map(b=>b.id)")
    assert ids == ["zoutBtn", "zlabel", "zinBtn"], ids
    # ...and both of them are still reachable, in the toolbox
    assert pg.evaluate(
        "TOOLBOX.flatMap(g=>g.tools.map(t=>t.k)).includes('hand')")
    assert pg.evaluate(
        "TOOLBOX.flatMap(g=>g.tools.map(t=>t.k)).includes('addtext')")
    assert not errs, errs[:2]


def test_arming_the_hand_still_lights_the_toolbox(ed):
    """Its own button is gone, so the toolbox is the only thing left that can
    say the hand is out - and it has to, however the hand was reached."""
    pg, _p, errs = ed
    pg.evaluate("toggleHand(true)")
    pg.wait_for_timeout(400)
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=view]').dataset.tool") == "hand"
    assert pg.evaluate(
        "document.querySelector('.tbtn[data-slot=view]').classList.contains('on')")
    assert not errs, errs[:2]


def test_double_clicking_the_hand_fits_the_page(ed):
    """lee: *"dubble lciking the hand tool on the side is also make the page go
    to 100%"*. The pair of clicks would otherwise arm the hand and put it
    straight back down, so it is re-armed: one gesture, and the tool stays in
    your hand."""
    pg, _p, errs = ed
    for _ in range(5):
        pg.evaluate("zoomBy(1.25)")
    pg.wait_for_timeout(400)
    big = pg.evaluate("scale")
    assert big > 1.5, big
    b = pg.evaluate("""(()=>{const r=document.querySelector(
        '.tbtn[data-slot=view]').getBoundingClientRect();
        return {x:r.left+r.width/2, y:r.top+r.height/2};})()""")
    pg.mouse.dblclick(b["x"], b["y"])
    pg.wait_for_timeout(700)
    assert pg.evaluate("scale") < big, "the page did not refit"
    assert pg.evaluate("handMode") is True, "it put the hand back down"
    assert not errs, errs[:2]


# --------------------------------------------------------------- the shapes

def _to_screen(pg, x, y):
    o = pg.evaluate(
        "(()=>{const b=document.getElementById('img').getBoundingClientRect();"
        "return {x:b.x,y:b.y,s:scale};})()")
    return o["x"] + x * o["s"], o["y"] + y * o["s"]


def _draw_a_rectangle(pg):
    pg.evaluate("""(()=>{
        brushState.col='#ff2d55'; brushState.sz=6;
        setShapeFill(true);
        if(shapeKind!=='rect') toggleShape('rect');})()""")
    x0, y0 = _to_screen(pg, 60, 380)
    x1, y1 = _to_screen(pg, 200, 470)
    pg.mouse.move(x0, y0); pg.mouse.down()
    pg.mouse.move(x1, y1, steps=6); pg.mouse.up()
    pg.wait_for_timeout(200)
    pg.evaluate("toggleShape('rect')")     # put the shape tool away
    pg.wait_for_timeout(200)


def test_a_shape_is_picked_up_by_clicking_it(ed):
    """lee: *"make it so that i can select shapes like i can text boxes"*. The
    arrow (V) had to be armed first, so on a page with a rectangle on it the
    obvious click - straight at the rectangle - did nothing at all."""
    pg, _p, errs = ed
    _draw_a_rectangle(pg)
    assert pg.evaluate("layers.filter(l=>l.type==='shape').length") == 1
    assert pg.evaluate("shapeEdit") is False, "a tool was left armed"

    pg.mouse.click(*_to_screen(pg, 130, 425))
    pg.wait_for_timeout(400)
    assert pg.evaluate("shapeEdit") is True, "the click did not reach for it"
    assert pg.evaluate("layerSel") == pg.evaluate(
        "layers.find(l=>l.type==='shape').id")
    assert pg.evaluate("xf!=null && xf.vector!=null"), \
        "the shape was selected but not picked up"
    assert not errs, errs[:2]


def test_clicking_the_bare_page_picks_up_nothing(ed):
    pg, _p, errs = ed
    _draw_a_rectangle(pg)
    pg.mouse.click(*_to_screen(pg, 420, 560))
    pg.wait_for_timeout(400)
    assert pg.evaluate("!(typeof xf!=='undefined' && xf)")
    assert not errs, errs[:2]


def test_an_armed_brush_still_paints_over_a_shape(ed):
    """Picking shapes up on a bare click must not take the click away from a
    tool that is out: a stroke across a rectangle is a stroke."""
    pg, _p, errs = ed
    _draw_a_rectangle(pg)
    n = pg.evaluate("layers.length")
    pg.evaluate("toggleBrush(true)")
    pg.wait_for_timeout(200)
    x0, y0 = _to_screen(pg, 80, 400)
    x1, y1 = _to_screen(pg, 180, 450)
    pg.mouse.move(x0, y0); pg.mouse.down()
    pg.mouse.move(x1, y1, steps=6); pg.mouse.up()
    pg.wait_for_timeout(400)
    assert pg.evaluate("layers.length") == n + 1, "the stroke was swallowed"
    assert pg.evaluate("layers[layers.length-1].type") != "shape"
    assert pg.evaluate("!(typeof xf!=='undefined' && xf)"), \
        "the brush stroke picked the shape up as well"

    # An armed tool owns the canvas above the page, so in practice the press
    # never reaches the page underneath. That is layering, not a decision -
    # so the decision is asked for directly here: the same press, delivered
    # to the page itself, with the brush still out.
    pg.evaluate("""(()=>{
        const st=document.getElementById('stage');
        const b=document.getElementById('img').getBoundingClientRect();
        st.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,
          clientX:b.x+130*scale, clientY:b.y+425*scale}));})()""")
    pg.wait_for_timeout(300)
    assert pg.evaluate("!(typeof xf!=='undefined' && xf)"), \
        "a press on the page took the shape while a tool was armed"
    assert pg.evaluate("brush") is True, "it put the brush away"
    assert not errs, errs[:2]


def test_lifting_a_selection_takes_what_is_drawn_over_the_text_as_well(ed):
    """lee: *"the fre tansfor too shoude be able to move everything when i
    slect it"*. What came up was the plate and the paint UNDER the typesetting;
    anything on the over band stayed standing where it was while the rest of
    the piece moved off without it.

    The ROUTE has changed since - arming the transform on a bare selection
    used to float a copy of it, and lee has since asked that it not: *"teh
    select too shoud just be there and do nothing  no new image shoud be made
    until i hit copy and past"*. So J is the press that makes the layer now,
    and the requirement moved with it: what J takes is everything visible
    inside the selection, over band included. The typesetting itself is not in
    it - that is drawn from the region records by its own overlay, and a copy
    baked into the patch would show twice.
    """
    pg, _p, errs = ed
    # something drawn on the band ABOVE the typesetting...
    pg.evaluate("""(()=>{
        ensureCanvas(); ensureOverCanvas();
        const o=document.getElementById('paintOver').getContext('2d');
        o.fillStyle='#00ff00'; o.fillRect(40,300,120,120);})()""")
    pg.wait_for_timeout(200)
    # ...selected, and lifted with J
    pg.evaluate("""(()=>{
        const m=selMaskCanvas(), g=m.getContext('2d');
        g.clearRect(0,0,m.width,m.height);
        g.fillStyle='#fff'; g.fillRect(30,290,150,150);
        selBBoxCache=undefined; selMaskVer++;
        selLift();})()""")
    pg.wait_for_function("typeof xf!=='undefined' && !!(xf&&xf.src)",
                         timeout=15000)
    lifted = pg.evaluate("""(()=>{
        const g=xf.src.getContext('2d');
        const d=g.getImageData(Math.round(xf.src.width/2),
                               Math.round(xf.src.height/2),1,1).data;
        return [...d];})()""")
    assert lifted[1] > 200 and lifted[0] < 90 and lifted[2] < 90, \
        f"what it lifted has no over-the-text paint in it: {lifted}"
    pg.evaluate("xfCancel && xfCancel()")
    assert not errs, errs[:2]
