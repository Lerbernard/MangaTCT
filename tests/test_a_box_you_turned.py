"""A box you drew, turned - and everything downstream turning with it.

lee: *"alow me to rotate boxes, only teh ser shoud be able to rotate them the
detector boxes shoud be normal"*, and, asked what "rotate" should mean:
**the box and the text together**, on **every box he drew**.

## Only a box somebody drew

A detected box's rectangle came off the artwork: it is a reading of where the
writing already is. Turning it would be claiming the drawing is at an angle it
is not, and the next detect would put it straight back. So the endpoint refuses
one, and no turn handle is drawn on it.

## A turn is not an angle

`TextRegion.angle` was already there and already meant something: the axis a
sound effect's artwork runs along, read off the page the moment the effect is
drawn. Every sound effect drawn by hand therefore arrives carrying one - so
reading a turn out of `angle` would have leant the outline, the clean and the
typesetting of every hand-drawn effect in the chapter, none of which anybody
turned. `turn` is its own field: `angle` is a reading of the drawing, `turn`
is a decision about the box, and one box can have both.

Turning a sound effect moves its axis by as much, which is how its letters -
which are laid along that axis and not in a block - turn with the box.

## The turn is stored as GEOMETRY as well

Held only as a number it would have to be read separately by the cleaner, the
fitter, the renderer and the browser, and each of those is a place to forget.
Writing the four corners into `polygon` means the turn arrives wherever the
outline already arrives: `_is_a_box` answers False for a tilted rectangle, so
the region loads with a real placement area. `bbox` stays the upright
rectangle the turn is derived FROM - so resizing a turned box re-derives it
rather than straightening it, and straightening it gives the plain box back.

## The text is fitted straight and then turned

Fitting into the tilted shape directly would set level lines inside a leaning
box: every line a different width, which is a staircase, not turned text. So
`fit_region` fits against the box upright and hangs `rotate` on the layout,
and the renderer - which already turns any layout carrying one - does the rest.

Which means the finished block is turned about the layout FRAME's centre while
the mask is the box turned about the BOX's centre. Those are close but not the
same point, so clipping the block to the mask shaves the ends off lines that
fitted perfectly. A turned box is not clipped, for the same reason a sound
effect is not: where its text goes was decided by a person.
"""

import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import cv2
import numpy as np
import pytest

from mangatl.project import is_turned, turned_box


# --- the four corners ----------------------------------------------------------

def test_a_quarter_turn_stands_the_box_on_its_side():
    """Clockwise, to match `TextRegion.angle` and the sound-effect reader.
    A wide box a quarter turn on is a tall one about the same centre."""
    assert turned_box((100, 100, 200, 100), 90) == \
        [[250, 50], [250, 250], [150, 250], [150, 50]]


def test_and_the_centre_does_not_move():
    poly = turned_box((10, 20, 200, 60), 37)
    cx = sum(p[0] for p in poly) / 4.0
    cy = sum(p[1] for p in poly) / 4.0
    assert abs(cx - 110) < 1 and abs(cy - 50) < 1


def test_a_turn_of_nothing_is_the_box_itself():
    """Which is what puts a straightened box back to ordinary: `_is_a_box`
    reads these four corners and the region loads with no placement mask."""
    assert turned_box((10, 20, 200, 60), 0) == \
        [[10, 20], [210, 20], [210, 80], [10, 80]]


def test_a_positive_turn_goes_clockwise_on_the_page():
    """Page coordinates run DOWN, so the corner that was top-right drops."""
    poly = turned_box((0, 0, 100, 100), 30)
    assert poly[1][1] > 0, "the top-right corner should have swung down"
    assert poly[0][1] < 0, "...and the top-left one up"


def test_the_shape_keeps_its_size():
    a = turned_box((0, 0, 200, 80), 0)
    b = turned_box((0, 0, 200, 80), 41)
    side = lambda p, i, j: ((p[i][0] - p[j][0]) ** 2
                            + (p[i][1] - p[j][1]) ** 2) ** 0.5
    assert abs(side(a, 0, 1) - side(b, 0, 1)) < 2
    assert abs(side(a, 1, 2) - side(b, 1, 2)) < 2


def test_a_drawn_box_with_a_turn_is_turned():
    assert is_turned({"manual": True, "turn": 12.0})


def test_a_box_the_detector_put_down_can_be_turned_too():
    """It was hand-drawn boxes only - lee: *"only teh ser shoud be able to
    rotate them the detector boxes shoud be normal"* - and he then asked for
    the other thing: *"alowm me to be able to rotate every box"*. A detector
    can be wrong about the ANGLE as easily as about the edges, and it is the
    same person fixing both. `is_turned` reads the turn, not who drew it."""
    assert is_turned({"turn": 44.0})
    assert is_turned({"manual": False, "turn": 12.0})


def test_and_neither_is_a_drawn_box_left_straight():
    assert not is_turned({"manual": True, "turn": 0.0})
    assert not is_turned({"manual": True})


def test_a_measured_angle_is_not_a_turn():
    """A sound effect drawn by hand is measured the moment it is drawn, so it
    arrives carrying an angle - the axis its artwork runs along. Reading that
    as a turn would have leant the clean of every one of them."""
    assert not is_turned({"manual": True, "angle": 44.0})


# --- through the endpoint -------------------------------------------------------

# A sound effect drawn up a diagonal, in its own corner of the page. The axis
# reader gives it a real angle at draw time - which is the whole point: a
# hand-drawn effect ALWAYS arrives carrying one, and the turn has to be a
# different number from it.
_SFX_BOX = (30, 190, 110, 100)


def _page(w=420, h=300):
    img = np.full((h, w, 3), 245, np.uint8)
    cv2.putText(img, "AB", (150, 170), cv2.FONT_HERSHEY_SIMPLEX, 2,
                (10, 10, 10), 6)
    for k in range(-2, 3):
        cv2.line(img, (45 + k * 3, 275), (125 + k * 3, 205), (15, 15, 15), 7)
    return img


@pytest.fixture()
def proj(tmp_path):
    from mangatl import editor as ed
    from mangatl.project import Project
    ed._plate_cache.clear()
    root = str(tmp_path / "r")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", _page())[1].tobytes())
    p.pages[0].detected = True
    p.save()
    was, ed.PROJECT = ed.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ed.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def post(url, body):
        req = urllib.request.Request(
            base + url, method="POST", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())

    try:
        yield ed, p, post
    finally:
        srv.shutdown()
        ed.PROJECT = was


def _drawn(post, kind="bubble", box=(130, 120, 180, 70)):
    x, y, w, h = box
    return post("/api/page/0/region",
                {"x": x, "y": y, "w": w, "h": h, "snap": False, "kind": kind})


def _turn(post, rid, turn):
    return post("/api/page/0/region/%d" % rid, {"turn": turn})


def test_a_box_you_drew_can_be_turned(proj):
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    out = _turn(post, rid, 25)
    assert "error" not in out
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    assert abs(float(rec["turn"]) - 25) < 0.01


def test_and_its_outline_becomes_the_turned_rectangle(proj):
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    _turn(post, rid, 25)
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    assert rec["polygon"] == turned_box(rec["bbox"], 25)


def test_a_box_the_detector_put_down_turns_as_well(proj):
    """The endpoint stopped refusing when lee asked for every box to turn."""
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    rec["manual"] = False
    out = _turn(post, rid, 25)
    assert "error" not in out
    assert abs(float(rec.get("turn") or 0.0) - 25) < 0.01


def test_a_sound_effect_you_drew_can_be_turned_too(proj):
    """lee, asked which boxes: *"every box I drew"*."""
    ed, p, post = proj
    rid = _drawn(post, kind="sfx", box=_SFX_BOX)["region"]["id"]
    assert "error" not in _turn(post, rid, 30)


def test_and_turning_it_turns_the_axis_its_letters_run_along(proj):
    """A sound effect is not set as a block: its letters run along the axis
    that was measured off the artwork. Moving that axis by the turn is what
    makes "the box and the text together" true for one."""
    ed, p, post = proj
    rid = _drawn(post, kind="sfx", box=_SFX_BOX)["region"]["id"]
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    was = float(rec.get("angle") or 0.0)
    assert abs(was) > 10, "the fixture's effect has to have been measured"
    _turn(post, rid, 20)
    assert abs(float(rec["angle"]) - (was + 20)) < 0.01


def test_and_turning_it_back_puts_that_axis_back(proj):
    """The turn is applied as a DIFFERENCE, or a second turn would count the
    first one twice and the letters would walk away from the box."""
    ed, p, post = proj
    rid = _drawn(post, kind="sfx", box=_SFX_BOX)["region"]["id"]
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    was = float(rec.get("angle") or 0.0)
    assert abs(was) > 10, "the fixture's effect has to have been measured"
    _turn(post, rid, 20)
    _turn(post, rid, 35)
    _turn(post, rid, 0)
    assert abs(float(rec["angle"]) - was) < 0.01


def test_a_bubble_you_turn_keeps_its_angle_alone(proj):
    """Only a sound effect's letters follow an axis. A block of speech is
    turned by the renderer, from the layout."""
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    _turn(post, rid, 20)
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    assert not float(rec.get("angle") or 0.0)


def test_a_sound_effect_is_not_re_laid_as_a_block(proj):
    """`fit_region` turns a block by fitting it straight and hanging `rotate`
    on the layout. Sending a sound effect through that would replace its
    letter-by-letter placement with level lines in a box."""
    from mangatl import typeset
    from mangatl.models import TextRegion
    r = TextRegion(id=0, bbox=(130, 120, 180, 70), kind="sfx",
                   dst_text="BOOM", src_text="ド", order=0)
    r.manual, r.turn, r.angle = True, 30.0, 30.0
    r.text_mask = np.zeros((300, 420), np.uint8)
    r.text_mask[130:180, 150:280] = 255
    lay = typeset.fit_region(r, typeset.TypesetConfig())
    assert not float(getattr(lay, "rotate", 0.0) or 0.0)


def test_the_turn_is_held_inside_a_quarter(proj):
    """Past a quarter turn a box is the same shape read the other way round,
    and the typesetting would be upside down rather than leaning."""
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    _turn(post, rid, 400)
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    assert abs(float(rec["turn"])) <= 89


def test_straightening_it_puts_the_plain_rectangle_back(proj):
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    _turn(post, rid, 25)
    _turn(post, rid, 0)
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    from mangatl.project import _is_a_box
    assert _is_a_box(np.array(rec["polygon"], np.int32))


def test_resizing_a_turned_box_does_not_straighten_it(proj):
    """The outline is DERIVED from the rectangle, and a resize writes a new
    rectangle. Without re-deriving, the box springs upright when touched."""
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    _turn(post, rid, 25)
    post("/api/page/0/region/%d" % rid,
         {"resnap": True, "snap": False, "bbox": [120, 110, 200, 90]})
    rec = next(r for r in p.pages[0].regions if r["id"] == rid)
    assert abs(float(rec.get("turn") or 0.0) - 25) < 0.01
    assert rec["polygon"] == turned_box(rec["bbox"], 25)


def test_the_page_is_recleaned_after_a_turn(proj):
    """The turn changes what gets erased, and the cleaned plate is cached per
    page. Without saying so, the turn is invisible until something else
    happens to touch the page."""
    ed, p, post = proj
    rid = _drawn(post)["region"]["id"]
    seen = []
    real = ed.invalidate_page
    ed.invalidate_page = lambda *a, **k: (seen.append(a), real(*a, **k))[1]
    try:
        _turn(post, rid, 25)
    finally:
        ed.invalidate_page = real
    assert seen, "the plate for this page was left as it was"


# --- what the rest of the app sees ----------------------------------------------

def _turned_record(turn=30):
    bbox = [130, 120, 180, 70]
    return {"id": 0, "bbox": bbox, "polygon": turned_box(bbox, turn),
            "bubble_bbox": None, "kind": "bubble", "manual": True,
            "turn": turn, "src_text": "a", "order": 0}


def test_the_turn_survives_a_page_being_rebuilt():
    """A chapter is held as geometry and the masks are thrown away and rebuilt
    on every page build, region -> record -> region. A field the record does
    not carry is a field that lasts until the next rebuild."""
    from mangatl.project import region_from_record, region_record
    rec = _turned_record(28)
    again = region_record(region_from_record(rec, _page()))
    assert abs(float(again.get("turn") or 0.0) - 28) < 0.01


def test_a_turned_box_loads_with_a_real_placement_area():
    """`_is_a_box` answers False for a tilted rectangle, which is the whole
    mechanism: the region comes back with a mask shaped like the box."""
    from mangatl.project import region_from_record
    r = region_from_record(_turned_record(), _page())
    assert r.bubble_mask is not None
    assert r.place_mask() is r.bubble_mask


def test_and_that_area_leans():
    """Not merely present - actually the turned shape. A mask that came out as
    the upright rectangle would pass the test above and mean nothing."""
    from mangatl.project import region_from_record
    r = region_from_record(_turned_record(35), _page())
    m = r.bubble_mask > 0
    x, y, w, h = _turned_record()["bbox"]
    upright = np.zeros(m.shape, bool)
    upright[y:y + h, x:x + w] = True
    assert (m & ~upright).sum() > 0.15 * w * h, \
        "a leaning box reaches well outside the upright one"
    assert 0.9 * w * h < m.sum() < 1.1 * w * h, "...and is the same box"


def test_an_upright_box_is_unaffected():
    from mangatl.project import region_from_record
    r = region_from_record(_turned_record(0), _page())
    assert r.bubble_mask is None


def test_the_cleaner_may_paint_the_corners_a_turn_swept_out():
    """The fence at the end of `inpaint_page` allows a region's own box and its
    doorstep. A turned box's corners stand OUTSIDE the upright rectangle
    `bbox` still describes, so keeping the intersection would shave exactly
    those corners off and leave the writing standing in them."""
    from mangatl import inpaint as I
    from mangatl.models import TextRegion
    r = TextRegion(id=0, bbox=(130, 120, 180, 70), text_mask=None,
                   bubble_mask=None, bubble_bbox=None, kind="bubble")
    r.manual = True
    r.turn = 30.0
    assert I._turned(r)
    r.turn = 0.0
    assert not I._turned(r)
    r.manual = False
    r.turn = 30.0
    assert not I._turned(r), "the detector's boxes are never turned"
    r.manual, r.turn, r.angle = True, 0.0, 40.0
    assert not I._turned(r), "a measured lean is not a turn"


# The two slivers of a box turned -35° that stand outside the upright
# rectangle AND outside its eight-pixel doorstep - one off each end. Ink here
# is reachable only because a turned box is its own fence; keep the
# intersection with the upright box and it survives the clean untouched.
_SWEPT = ((265, 96), (175, 210))


def test_the_writing_in_a_turned_corner_comes_off():
    """End to end, on a page whose ink sits where only the turn can reach it."""
    from mangatl import inpaint as I
    from mangatl.models import Page
    from mangatl.project import region_from_record
    img = np.full((300, 420, 3), 245, np.uint8)
    for cx, cy in _SWEPT:
        cv2.circle(img, (cx, cy), 7, (10, 10, 10), -1)
    rec = _turned_record(-35)
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    x, y, w, h = rec["bbox"]
    g = I.GLYPH_REACH
    doorstep = np.zeros(r.text_mask.shape, bool)
    doorstep[max(0, y - g):y + h + g, max(0, x - g):x + w + g] = True
    assert ((r.text_mask > 0) & doorstep).sum() == 0, \
        "the fixture's ink has to be OUTSIDE the upright box and its doorstep"
    assert (r.text_mask > 0).sum() > 100, "...and inside the turned one"
    pg = Page(image=img, source_path="t.png")
    pg.regions = [r]
    out = I.inpaint_page(pg, neural=None)
    for cx, cy in _SWEPT:
        sl = (slice(cy - 7, cy + 8), slice(cx - 7, cx + 8))
        assert int((cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[sl] <= 128).sum()) \
            < 0.25 * int((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[sl] <= 128).sum())


def test_a_glyph_poking_past_a_turned_edge_still_comes_off():
    """A turned box gets the same doorstep an upright one gets.

    Writing drawn a little past its box has to be finishable, or "the text
    must go" and "never outside the box" cannot both be true - see
    `test_a_glyph_poking_past_the_balloon_interior_still_comes_off`. Fence a
    turned box at its bare outline and the outer rim of every stroke that
    reaches the edge is left standing, in a leaning line down the page.
    """
    from mangatl import inpaint as I
    from mangatl.models import Page
    from mangatl.project import region_from_record
    img = np.full((320, 440, 3), 250, np.uint8)
    # a bar that runs out through the lower-right edge of the turned box
    cv2.line(img, (200, 150), (300, 205), (10, 10, 10), 13)
    rec = _turned_record(30)
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    quad = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(quad, [np.array(turned_box(rec["bbox"], 30), np.int32)], 255)
    just_outside = (cv2.dilate(quad, np.ones((2 * I.GLYPH_REACH + 1,) * 2,
                                             np.uint8)) > 0) & (quad == 0)
    ink = lambda z: int(((cv2.cvtColor(z, cv2.COLOR_BGR2GRAY) <= 128)
                         & just_outside).sum())
    was = ink(img)
    assert was > 60, "the fixture has to have a rim standing outside the box"
    pg = Page(image=img, source_path="t.png")
    pg.regions = [r]
    assert ink(I.inpaint_page(pg, neural=None)) < 0.8 * was


def test_the_typesetter_fits_the_box_upright_and_turns_the_block():
    """Fitting into the leaning shape gives a staircase - a different width on
    every line. Fit straight, then turn."""
    from mangatl import typeset
    from mangatl.project import region_from_record
    rec = _turned_record(30)
    rec["dst_text"] = "TURNED"
    r = region_from_record(rec, _page())
    lay = typeset.fit_region(r, typeset.TypesetConfig())
    assert lay is not None and lay.lines
    assert abs(float(getattr(lay, "rotate", 0.0)) - 30) < 0.01


def test_and_an_upright_box_gets_no_turn():
    from mangatl import typeset
    from mangatl.project import region_from_record
    rec = _turned_record(0)
    rec["dst_text"] = "STRAIGHT"
    r = region_from_record(rec, _page())
    lay = typeset.fit_region(r, typeset.TypesetConfig())
    assert not float(getattr(lay, "rotate", 0.0) or 0.0)


def test_a_turned_block_is_not_clipped_back_to_its_mask():
    """The block turns about the FRAME's centre and the mask about the BOX's,
    and the two are not the same point - so clipping shaves the ends off lines
    that fitted. It is the same exemption a sound effect gets, for the same
    reason: a person decided where this text goes."""
    import inspect

    from mangatl import render
    src = inspect.getsource(render)
    i = src.index("free = _kinds.family_of")
    tail = src[i:i + 1200]
    assert "manual" in tail and "turn" in tail


def test_every_box_gets_the_turn_handle():
    """The browser half of *"alowm me to be able to rotate every box"*. The
    handle used to be drawn only on `r.manual`, which is the page refusing
    what the endpoint now allows."""
    from where import JS
    src = (JS / "frames.js").read_text(encoding="utf-8")
    i = src.index("function addHandles")
    body = src[i:i + 1400]
    assert "rot" in body, "there is still a turn handle"


def test_the_box_you_are_drawing_still_has_an_outline():
    """The preview rectangle that follows the pointer while you drag out a new
    box. lee: *"the preveiw when i am drawing a box is gone"*.

    It went because the turn handle's CSS was replaced by a slice taken on
    CHARACTER offsets rather than whole lines. The cut landed inside
    `.hd.rot::after` and left `height:13px;background:#ff9f0a}` orphaned in the
    stylesheet - and a browser recovering from a fragment like that swallows
    the rule after it, which was `#rubber`. Nothing threw; the preview simply
    had no border and no fill.

    So this asserts the rule is THERE and that the sheet around it is
    well-formed, which is the part that failed.
    """
    from where import PKG
    css = (PKG / "static/css/editor.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}"), \
        "the stylesheet has an unbalanced brace — something was cut in half"
    i = css.index("#rubber{")
    rule = css[i:css.index("}", i)]
    assert "border" in rule and "dashed" in rule, rule
    assert "background" in rule, rule
    # ...and nothing orphaned immediately above it, which is how it was lost.
    before = css[:i].rstrip().rsplit("\n", 1)[-1].strip()
    assert before.endswith("}") or before.endswith("*/"), \
        "the line above #rubber is not a finished rule: %r" % before
