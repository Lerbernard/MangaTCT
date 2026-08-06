"""Turning a text box the way every drawing program turns one.

lee: *"remove teh rotate thing the the top of teh text bot and make it so that
if i go to the edgec corner and out out a little a rotate thing come up to
alow me to rorta an d and tht hsoud happen to all 4 corners, aklso make sure
when the txext box is rotated it the coner show acurate mouse icons"*.

Before: a ⟳ badge on a little stem above the box. One place, always in the
same spot, and the spot was wherever the top of the box happened to be — over
the artwork, off the top of the page, or underneath the box above it.

Now: a zone just outside each of the four corners. Press the corner itself and
you resize; step a little past it and the cursor becomes a curved arrow and
you turn. That is where the hand already is after a resize, it works from
whichever corner is nearest, and nothing sticks out of the box to be clicked
by accident.

And the cursors tell the truth. The eight resize handles used to be labelled
by their name in the box's OWN frame — the "nw" handle always said
`nw-resize`. Turn the box ninety degrees and its top-left corner points up and
to the RIGHT, and an arrow insisting otherwise is worse than no arrow at all.
The direction is worked out on screen now: handle angle minus the box's
rotation, to the nearest eighth of a turn.
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 240, np.uint8)
    cv2.ellipse(img, (230, 150), (120, 80), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (230, 150), (120, 80), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    st = p.pages[0]
    st.regions = [{"id": 1, "kind": "bubble", "order": 0,
                   "bbox": [150, 110, 160, 80],
                   "bubble_bbox": [110, 70, 240, 160],
                   "polygon": [[150, 110], [310, 110], [310, 190], [150, 190]],
                   "confidence": 0.9, "src_text": "テスト",
                   "dst_text": "ROTATE ME PLEASE"}]
    st.detected = True
    return p


@pytest.fixture()
def framed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "rot"))
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
        pg.wait_for_timeout(400)
        assert pg.evaluate("!!document.getElementById('tframe')"), \
            "no text frame to test"
        try:
            yield pg, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _rot(pg):
    return pg.evaluate("+(regions.find(r=>r.id===1).layout.rotate||0)")


def _frame_box(pg):
    return pg.evaluate("""(()=>{const f=document.getElementById('tframe');
        const b=f.getBoundingClientRect();
        return {x:b.x,y:b.y,w:b.width,h:b.height};})()""")


def _corner_point(pg, which):
    """Screen point of one corner of the frame, and the point a little way
    outside it along the diagonal."""
    return pg.evaluate("""(w=>{
        const f=document.getElementById('tframe');
        const z=[...f.querySelectorAll('.trotz')][w];
        const h=[...f.querySelectorAll('.th')].filter(
                  e=>e.style.cursor.indexOf('resize')>0);
        const zb=z.getBoundingClientRect();
        return {zx:zb.x+zb.width/2, zy:zb.y+zb.height/2};})""", which)


# ------------------------------------------------------- the badge is gone

def test_the_rotate_badge_above_the_box_is_gone(framed):
    pg, _e = framed
    assert not pg.evaluate("!!document.querySelector('#tframe .trot')"), \
        "the ⟳ badge is still there"
    assert not pg.evaluate("!!document.querySelector('#tframe .tstem')"), \
        "the stem it hung from is still there"


def test_all_four_corners_can_turn_it(framed):
    pg, _e = framed
    zones = pg.evaluate("document.querySelectorAll('#tframe .trotz').length")
    assert zones == 4, f"{zones} rotate zones, not one per corner"
    curs = pg.evaluate("""JSON.stringify([...document.querySelectorAll(
        '#tframe .trotz')].map(z=>z.style.cursor.slice(0,9)))""")
    assert curs.count('url(\\"data') == 4, curs


def test_dragging_just_outside_a_corner_turns_the_box(framed):
    pg, errs = framed
    for which in range(4):
        pg.evaluate("(()=>{const r=regions.find(x=>x.id===1);"
                    " r.layout.rotate=0; drawFrame();})()")
        pg.wait_for_timeout(120)
        z = _corner_point(pg, which)
        box = _frame_box(pg)
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        pg.mouse.move(z["zx"], z["zy"])
        pg.mouse.down()
        # swing a quarter turn about the centre
        import math
        a = math.atan2(z["zy"] - cy, z["zx"] - cx) + math.pi / 2
        rr = math.hypot(z["zx"] - cx, z["zy"] - cy)
        pg.mouse.move(cx + rr * math.cos(a), cy + rr * math.sin(a), steps=6)
        pg.mouse.up()
        pg.wait_for_timeout(200)
        # a quarter turn of the pointer is a quarter turn of the box —
        # relative to the grab, so touching a corner moves nothing by itself
        assert 80 <= abs(_rot(pg)) <= 100, \
            f"corner {which} turned the box by {_rot(pg)}, not a quarter"
    assert not errs, errs[:2]


def test_grabbing_a_corner_does_not_jolt_the_box(framed):
    """The old handle sat at a fixed angle above the box, so setting the
    rotation to "wherever the pointer is, plus ninety" happened to mean no
    change on the press. From a corner the same sum is a 45-degree jolt the
    instant you touch it."""
    pg, _e = framed
    pg.evaluate("(()=>{const r=regions.find(x=>x.id===1);"
                " r.layout.rotate=0; drawFrame();})()")
    pg.wait_for_timeout(120)
    z = _corner_point(pg, 0)
    pg.mouse.move(z["zx"], z["zy"])
    pg.mouse.down()
    pg.mouse.move(z["zx"] + 1, z["zy"], steps=2)
    pg.mouse.up()
    pg.wait_for_timeout(200)
    assert abs(_rot(pg)) < 5, \
        f"touching a corner turned the box to {_rot(pg)} on its own"


def test_the_corner_itself_still_resizes(framed):
    pg, _e = framed
    pg.evaluate("(()=>{const r=regions.find(x=>x.id===1);"
                " r.layout.rotate=0; drawFrame();})()")
    pg.wait_for_timeout(120)
    before = pg.evaluate("JSON.stringify(frameOf(regions.find(r=>r.id===1)))")
    h = pg.evaluate("""(()=>{const f=document.getElementById('tframe');
        const b=[...f.querySelectorAll('.th')][4].getBoundingClientRect();
        return {x:b.x+b.width/2, y:b.y+b.height/2};})()""")
    pg.mouse.move(h["x"], h["y"])
    pg.mouse.down()
    pg.mouse.move(h["x"] + 40, h["y"] + 30, steps=5)
    pg.mouse.up()
    pg.wait_for_timeout(300)
    after = pg.evaluate("JSON.stringify(frameOf(regions.find(r=>r.id===1)))")
    assert after != before, "pressing the corner itself did nothing"
    assert abs(_rot(pg)) < 1, \
        "pressing the corner turned the box instead of resizing it"


# ------------------------------------------------------- honest cursors

def test_the_cursors_follow_the_rotation(framed):
    pg, _e = framed

    def cursors(deg):
        pg.evaluate("(d=>{const r=regions.find(x=>x.id===1);"
                    " r.layout.rotate=d; drawFrame();})", deg)
        return pg.evaluate("""JSON.stringify([...document.querySelectorAll(
            '#tframe .th')].map(h=>h.style.cursor))""")

    import json
    # handles are built in the order nw, n, ne, e, se, s, sw, w
    at0 = json.loads(cursors(0))
    assert at0 == ["nwse-resize", "ns-resize", "nesw-resize", "ew-resize",
                   "nwse-resize", "ns-resize", "nesw-resize", "ew-resize"], at0
    # a quarter turn moves every arrow round by two places
    at90 = json.loads(cursors(-90))
    assert at90 == at0[2:] + at0[:2], at90
    # ...and a half turn brings them all back, because a resize arrow is a
    # line and a line looks the same both ways
    assert json.loads(cursors(-180)) == at0
    # something off the eighths rounds to the nearest one: 40 degrees is
    # nearer 45 than 90, so every arrow moves round by ONE place
    at40 = json.loads(cursors(-40))
    assert at40 == at0[1:] + at0[:1], at40


def test_the_cursor_maths_is_a_pure_function(framed):
    """Worth pinning on its own: it is the whole of the fix, and it is four
    lines with a modulo in them."""
    pg, _e = framed
    got = pg.evaluate("""JSON.stringify({
        e0:dirCursor(0), s90:dirCursor(90), w180:dirCursor(180),
        n270:dirCursor(270), wrap:dirCursor(360), neg:dirCursor(-90),
        round:dirCursor(20), nw:handleCursor('nw',0),
        nw90:handleCursor('nw',-90)})""")
    import json
    g = json.loads(got)
    assert g["e0"] == "ew-resize"
    assert g["s90"] == "ns-resize"
    assert g["w180"] == "ew-resize"
    assert g["n270"] == "ns-resize"
    assert g["wrap"] == "ew-resize", "360 degrees is not zero degrees"
    assert g["neg"] == "ns-resize", "a negative angle broke the modulo"
    assert g["round"] == "ew-resize", "20 degrees should round to east"
    assert g["nw"] == "nwse-resize"
    assert g["nw90"] == "nesw-resize", \
        "a box turned 90 degrees still claims its corner points up-left"
