"""Three things about editing typesetting: it sticks, it drags, and it opens flat.

* *"sometime when i update someything loike teh text or ouline and clcik off it
  it reverts back to what it was before"* - everything typed into the typesetting
  panel was only PREVIEWED as you typed. The style fields saved themselves
  after a pause; the text, the size and the rotation were saved by "Keep this"
  and by nothing else. So a new line typed and clicked away from was lost - and
  because the preview had already redrawn the page, it looked as though it went
  in and then came back out.
* *"make it so ythat i can click on te tetx and hold and move teh tetx with
  opening up the text box"* - clicking typesetting opened the editor on the way
  DOWN, so the only way to move a block was to find its frame handle first.
* *"make all the section in the dide bar come open not collaped"*.

And the line gap floor, in two parts: *"make teh minimun line gap be 1.20"*,
then *"the line spacing shoud only be a minimun of 1.20 for the typesetting the
user shoud be able to go lowwer"*. The floor is on what the fitter chooses for
itself; a number typed into the panel is a decision and stands.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")



def _project(root):
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
                   "leading": 1.2,
                   "origins": [[220 + k * 300, 205], [220 + k * 300, 228]],
                   "fg": "#000000", "edge": "#ffffff", "stroke": 1,
                   "font": "", "rotate": 0.0, "frame": [], "fixed": False,
                   "fit_ok": True, "used_compact": False}}
        for k in range(2)]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    p.pages[0].typeset = True
    return p


def _open(fn, root=scratch("_tmp_stick")):
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
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def _stored(p, key):
    return (p.pages[0].regions[0].get("layout_override") or {}).get(key)


# ------------------------------------------------------ edits stick

def test_typing_new_text_and_clicking_off_keeps_it():
    """The one lee reported. It used to preview and never save."""
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        # The words are typed on the PAGE now, not in the panel - the Text box
        # is gone (lee, with a picture of it: *"remove this box"*). So this
        # opens the block on the canvas, types into it, and clicks away, which
        # is the whole of what the person does.
        pg.evaluate("editOnCanvas(1)")
        pg.wait_for_timeout(500)
        assert pg.evaluate("editing") == 1, "the block did not open for typing"
        pg.evaluate("""(()=>{ editBox.innerText='BRAND NEW'; })()""")
        pg.evaluate("closeCanvasEdit(true)")     # click off, at once
        pg.wait_for_timeout(1400)
        assert pg.evaluate("document.getElementById('lyLines').value") \
            == "BRAND NEW"
        assert _stored(p, "lines") == ["BRAND NEW"], _stored(p, "lines")
    _open(check)


def test_changing_the_outline_and_clicking_off_keeps_it():
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        pg.click("#lyStroke")
        pg.keyboard.press("Control+a")
        pg.keyboard.type("7")
        pg.click("#lySize")                      # click off, at once
        pg.wait_for_timeout(1400)
        assert _stored(p, "stroke") == 7, _stored(p, "stroke")
    _open(check)


def test_a_new_size_survives_the_panel_being_rebuilt():
    """The panel is rebuilt on all sorts of things - a poll landing, a save
    elsewhere. Whatever was half-typed has to be written down first."""
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        pg.click("#lySize")
        pg.keyboard.press("Control+a")
        pg.keyboard.type("26")
        pg.evaluate("renderInspector()")         # rebuild under it
        pg.wait_for_timeout(1400)
        assert _stored(p, "font_size") == 26, _stored(p, "font_size")
    _open(check)


# ------------------------------------------------------ press and drag

def _text_point(pg):
    return pg.evaluate("""(()=>{
        const r=regions.find(x=>x.id===1);
        const o=r.layout.origins[0];
        const c=document.getElementById('img').getBoundingClientRect();
        return {x:c.left+o[0]*scale, y:c.top+o[1]*scale};})()""")


def test_a_plain_click_still_opens_the_editor():
    def check(pg, p):
        at = _text_point(pg)
        pg.mouse.click(at["x"], at["y"])
        pg.wait_for_timeout(700)
        assert pg.evaluate("editing") == 1
    _open(check)


def test_pressing_and_dragging_moves_it_without_opening_the_editor():
    def check(pg, p):
        at = _text_point(pg)
        pg.mouse.move(at["x"], at["y"])
        pg.mouse.down()
        for k in range(1, 9):
            pg.mouse.move(at["x"] + k * 8, at["y"] + k * 4)
        pg.mouse.up()
        pg.wait_for_timeout(1300)
        assert pg.evaluate("editing") in (None, ""), "the editor opened anyway"
        fr = _stored(p, "frame")
        assert fr and len(fr) == 4, f"the move was not saved: {fr}"
    _open(check)


def test_a_click_that_wobbles_a_pixel_is_still_a_click():
    """A shaky hand must not leave a one-pixel nudge saved behind it."""
    def check(pg, p):
        at = _text_point(pg)
        pg.mouse.move(at["x"], at["y"])
        pg.mouse.down()
        pg.mouse.move(at["x"] + 2, at["y"] + 1)
        pg.mouse.up()
        pg.wait_for_timeout(900)
        assert pg.evaluate("editing") == 1, "a 2px wobble ate the click"
        assert _stored(p, "frame") in (None, [], ()), "it saved a nudge"
    _open(check)


# ------------------------------------------------------ groups and line gap

def test_every_group_starts_open():
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        shut = pg.evaluate(
            "[...document.querySelectorAll('#inspector details.grp')]"
            ".filter(d=>!d.open).map(d=>d.querySelector('summary').textContent.trim())")
        assert shut == [], shut
    _open(check)


def test_the_line_gap_box_goes_under_the_floor_by_hand():
    """The floor is on what the fitter chooses. lee: *"the line spacing shoud
    only be a minimun of 1.20 for the typesetting the user shoud be able to go
    lowwer"*."""
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        assert pg.evaluate("+document.getElementById('lyLead').min") < 1.20
        for _ in range(6):
            pg.click("#lyLead ~ .numbtn.dn")
        pg.wait_for_timeout(700)
        got = pg.evaluate("+document.getElementById('lyLead').value")
        assert got < 1.20, got
        assert _stored(p, "leading") == pytest.approx(got), _stored(p, "leading")
    _open(check)


def test_the_two_copies_of_the_floor_agree():
    """The browser has its own number so the box can be built without asking
    the server. Two numbers, one meaning - they have to be held together."""
    from mangatl.typeset import MIN_LEADING
    js = (PKG / "static" / "js" / "panels.js").read_text("utf8")
    line = [l for l in js.splitlines() if l.startswith("const MIN_LEADING")]
    assert line, "panels.js has no MIN_LEADING"
    assert float(line[0].split("=")[1].strip(" ;")) == MIN_LEADING


def test_nothing_the_fitter_chooses_is_tighter_than_the_floor():
    from mangatl.typeset import MIN_LEADING, TypesetConfig
    assert MIN_LEADING == 1.20
    assert min(TypesetConfig().leadings) == MIN_LEADING
    assert all(v >= MIN_LEADING for v in TypesetConfig().leadings)


def test_a_tighter_gap_typed_in_by_hand_is_taken_as_typed():
    """The floor bounds the FITTER. A number in the override came from a
    person, and it stands - including one saved back when the floor was lower.
    lee: *"the line spacing shoud only be a minimun of 1.20 for the typesetting
    the user shoud be able to go lowwer"*."""
    from mangatl.models import TextRegion
    from mangatl import typeset as T
    m = np.zeros((300, 300), np.uint8)
    m[80:220, 80:220] = 255
    r = TextRegion(id=1, bbox=(90, 90, 120, 120), text_mask=m, bubble_mask=m,
                   kind="bubble", order=0, src_text="x", dst_text="HELLO THERE",
                   layout_override={"lines": ["HELLO", "THERE"],
                                    "font_size": 18, "leading": 1.02,
                                    "locked": True})
    lay = T.layout_from_override(r, T.TypesetConfig())
    assert lay is not None
    assert lay.leading == pytest.approx(1.02), lay.leading


def test_the_fitter_still_will_not_choose_one():
    """Both halves of what lee asked for, side by side."""
    from mangatl.typeset import MIN_LEADING, TypesetConfig
    assert min(TypesetConfig().leadings) == MIN_LEADING == 1.20


# ------------------------------------------ an edit outlives a page refresh

def _lose_count(pg, p, trigger, tries=6):
    """Type a size, fire `trigger` at once, and count how often the panel comes
    back showing something else."""
    lost = 0
    for k in range(tries):
        want = 21 + k
        pg.evaluate("select(1)")
        pg.wait_for_timeout(450)
        pg.click("#lySize")
        pg.keyboard.press("Control+a")
        pg.keyboard.type(str(want))
        pg.evaluate(trigger)                     # no pause: the save is in air
        pg.wait_for_timeout(1500)
        on_screen = pg.evaluate(
            "(regions.find(r=>r.id===1).layout_override||{}).font_size")
        if _stored(p, "font_size") != want or on_screen != want:
            lost += 1
    return lost


def _move_lose_count(pg, p, trigger, tries=6):
    """Drag a block by hand, fire `trigger` while the save is still in the
    air, and count how often it hops back to where it was."""
    lost = 0
    for k in range(tries):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(400)
        was = pg.evaluate(
            "frameOf(regions.find(r=>r.id===1)).map(v=>Math.round(v))")
        assert was and len(was) == 4, was
        want = [was[0] + 12 + k, was[1] + 9, was[2], was[3]]
        pg.evaluate(
            "([f])=>{const r=regions.find(x=>x.id===1); setFrame(r,f);"
            " saveTypesetting(1,true,null,true);}", [want])
        pg.evaluate(trigger)                     # no pause: the save is in air
        pg.wait_for_timeout(1600)
        on_screen = pg.evaluate(
            "(regions.find(r=>r.id===1).layout_override||{}).frame")
        if on_screen != want:
            lost += 1
    return lost


def test_a_block_that_was_dragged_does_not_hop_back():
    """lee, with a screen recording: *"the text is snapping back to its
    prrevious location"*.

    `saveTypesetting` marks the fields a person set so that a page answer
    already on its way cannot lay the old value back over them - and `frame`
    was not one of them, which is the only thing dragging a block writes. So
    the position was saved, and then immediately overwritten on screen by a
    refresh describing the page as it was a moment earlier."""
    def check(pg, p):
        assert _move_lose_count(pg, p, "poll()") == 0
    _open(check)


def test_the_same_holds_when_the_whole_page_reloads_under_it():
    def check(pg, p):
        assert _move_lose_count(pg, p, "showPage(cur)") == 0
    _open(check)


def test_an_edit_survives_the_page_being_refreshed_under_it():
    """lee: *"sometime some edits just revert when i lcik on a ballon"*, then
    *"when i click on another text box"*.

    Saving is a round trip and the page is reloaded from the server by all
    sorts of things that have nothing to do with the edit. An answer that was
    already on its way when the edit was made carries the value from BEFORE it,
    and laying that over the region puts the old number back on screen. The
    change still reaches disk - it just looks as though it did not, and the
    next edit then starts from the stale number.

    Measured before the fix: 4 in 6 with a poll landing, 3 in 6 with a page
    reload. Both are ordinary background traffic in this app.
    """
    def check(pg, p):
        assert _lose_count(pg, p, "poll()") == 0
    _open(check)


def test_the_same_holds_for_a_plain_page_reload():
    def check(pg, p):
        assert _lose_count(pg, p, "showPage(cur)") == 0
    _open(check)


def test_a_half_typed_value_is_written_down_before_any_reload():
    """`setRegions` flushed the region LIST and left the typesetting panel to
    `renderInspector` - which a refresh asking for no list redraw never calls.
    So a reload landing mid-keystroke dropped what was in the box."""
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(600)
        pg.click("#lySize")
        pg.keyboard.press("Control+a")
        pg.keyboard.type("31")
        # exactly what a reload does, and nothing else
        pg.evaluate("setRegions(JSON.parse(JSON.stringify(regions)),"
                    "{boxes:false, overlay:false, list:false})")
        pg.wait_for_timeout(1400)
        assert _stored(p, "font_size") == 31, _stored(p, "font_size")
    _open(check)


def test_the_overlay_lets_go_once_the_server_agrees():
    """The values held over a refresh cannot be held for ever, or a change from
    anywhere else would never show again. They are let go the moment an answer
    carries the same thing - agreement, not a timeout, because no length of
    time is reliably longer than 'every request already in flight'.

    So: make an edit, let it land, then hand the app an answer that says
    something different. It has to come through.
    """
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(600)
        pg.click("#lySize")
        pg.keyboard.press("Control+a")
        pg.keyboard.type("27")
        pg.evaluate("poll()")
        pg.wait_for_timeout(1800)
        assert _stored(p, "font_size") == 27, _stored(p, "font_size")
        # an answer from elsewhere, saying 41
        got = pg.evaluate("""(()=>{
            const list = JSON.parse(JSON.stringify(regions));
            const r = list.find(x=>x.id===1);
            r.layout_override.font_size = 41;
            r.layout.font_size = 41;
            setRegions(list, {list:false});
            return (regions.find(x=>x.id===1).layout_override||{}).font_size;})()""")
        assert got == 41, f"the overlay pinned the old value ({got})"
    _open(check)


def test_a_slow_save_does_not_let_go_of_a_newer_edit():
    """Type 2 then 7 and there are two saves in the air for the same bubble.
    The first one's answer says 2 - true when it was asked, wrong now. If it
    released the mark, the very next refresh would put 2 back on screen and the
    edit would look lost again.

    So a reply only lets go of the mark IT put there.
    """
    def check(pg, p):
        pg.evaluate("select(1)")
        pg.wait_for_timeout(600)
        held = pg.evaluate("""(()=>{
            const first = markInFlight(1, {layout_override:{font_size:20}}).seq;
            const second = markInFlight(1, {layout_override:{font_size:27}}).seq;
            settleInFlight(1, first);          // the slow one comes home
            const still = inFlight.has(1);
            settleInFlight(1, second);         // and then the current one
            return [still, inFlight.has(1), first !== second];})()""")
        assert held[0] is True, "a stale answer let go of the newer edit"
        assert held[1] is False, "the current answer never let go"
        assert held[2] is True, "both edits were given the same number"
    _open(check)
