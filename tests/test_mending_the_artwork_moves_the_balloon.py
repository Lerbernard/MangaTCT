"""Painting a balloon's edge back changes the shape the words are typeset into.

lee:

> *the issiye with the tyessetting is the clenner clenner a box while clening
> it errased some of a side of a box, now the typesetting thinks the bubble ie
> bigger then it accually is, i clenned the bubble and added the edge back but
> the typeseetting is not registerng that and is still typessting as if the box
> was open, thats the issiue*

Two balloons sharing a wall. Nick the wall and the run of paper the balloon
finder walks joins the balloon next door, so the shape comes back about twice
the size and the fitter typesets into both. Measured on the fixture below:
**25,137px intact, 50,578px nicked.**

Then it freezes. A balloon is stored as a POLYGON in the box's record;
`region_from_record` rebuilds the shape from it on every page build, and
`find_balloons` skips anything that already has one — *"a balloon found once is
not searched for again"*. That is right almost always and exactly wrong once
the artwork it was read from has been mended: painting the wall back and
rebuilding gave 50,601px, unchanged.

Two things had to move:

* `Project.repaired` — the scan with the under-text touch-up strokes painted
  onto it. The balloon finder reads that now, because a balloon's outline is
  artwork and a person is allowed to mend it. The WRITING is still read off
  the bare scan: painting over a line of Japanese means "leave this alone", not
  "there was never anything here to erase".
* `_unfreeze_repaired_balloons` — paint that lands on or near a stored outline
  drops that outline, so the next build looks again. Only where the paint
  actually reaches it, and never for a box drawn or tightened by hand: that
  shape is a decision, not a reading.
"""
import base64
import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

H, W = 520, 760
WALL_A, WALL_B = (326, 206), (334, 234)


def _art(nick):
    """Two balloons side by side. `nick` rubs a hole in the wall between them,
    which is what the cleaner did to lee's page."""
    img = np.full((H, W, 3), 120, np.uint8)
    for y in range(0, H, 5):
        cv2.line(img, (0, y), (W, y - 90), (60, 60, 60), 2)
    for c in ((230, 220), (430, 220)):
        cv2.ellipse(img, c, (96, 92), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, c, (96, 92), 0, 0, 360, (25, 25, 25), 3)
    if nick:
        cv2.line(img, WALL_A, WALL_B, (255, 255, 255), 9)
    cv2.putText(img, "AAA", (185, 232), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (20, 20, 20), 3)
    return img


def _mend_png(at_a=WALL_A, at_b=WALL_B):
    """The overlay a person paints: one dark stroke down the wall."""
    ov = np.zeros((H, W, 4), np.uint8)
    cv2.line(ov, (at_a[0], at_a[1] - 2), (at_b[0], at_b[1] + 2),
             (25, 25, 25, 255), 9)
    ov[..., 3] = np.where(ov[..., :3].any(axis=2), 255, 0)
    return cv2.imencode(".png", ov)[1].tobytes()


def _project(root, nick=True, manual=False):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", _art(nick))[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [175, 200, 125, 45],
        "bubble_bbox": [175, 200, 125, 45], "polygon": [], "confidence": 0.9,
        "manual": manual,
        "src_text": "あ", "dst_text": "HELLO THERE FRIEND"}]
    p.pages[0].detected = True
    p.save()
    return p


def _area(p, i=0):
    page = p.materialize(i)
    r = page.regions[0]
    return int((r.bubble_mask > 0).sum()) if r.bubble_mask is not None else 0


def _serve(p):
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _paint(base, png, over=b""):
    body = {"overlay": "data:image/png;base64," + base64.b64encode(png).decode()
                       if png else "",
            "overlay_over": "data:image/png;base64,"
                            + base64.b64encode(over).decode() if over else "",
            "layers": [{"id": 1}]}
    req = urllib.request.Request(
        base + "/api/page/0/paint", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as fh:
        return json.loads(fh.read().decode())


# ------------------------------------------------------------ the fault

def test_a_nicked_wall_makes_the_balloon_twice_the_size(tmp_path):
    """The premise, measured. If a nick ever stops leaking, everything below
    is testing nothing and this says so."""
    intact = _area(_project(str(tmp_path / "a"), nick=False))
    leaked = _area(_project(str(tmp_path / "b"), nick=True))
    assert 20000 < intact < 30000, intact
    assert leaked > 1.5 * intact, (intact, leaked)


def test_the_shape_freezes_into_the_record(tmp_path):
    """…and once it is written down, mending the page cannot reach it. This is
    the half that made lee's repair look like it did nothing."""
    from mangatl.project import region_from_record, find_balloons

    p = _project(str(tmp_path / "c"), nick=True)
    p.commit(0, p.materialize(0))
    rec = p.pages[0].regions[0]
    assert len(rec.get("polygon") or []) > 3, rec.get("polygon")
    leaked = _area(p)
    # the same record, rebuilt against a page whose wall is whole again
    good = _art(False)
    r = region_from_record(rec, good)
    find_balloons(good, [r])
    assert int((r.bubble_mask > 0).sum()) > 1.5 * 25000, "the leak did not survive"


# ------------------------------------------------------------- the fix

def test_painting_the_wall_back_gives_the_balloon_its_shape(tmp_path):
    """End to end, through the endpoint the brush actually posts to."""
    from mangatl import editor

    p = _project(str(tmp_path / "d"), nick=True)
    p.commit(0, p.materialize(0))
    p.save()
    before = _area(p)
    assert before > 40000, before

    srv, was, base = _serve(p)
    try:
        j = _paint(base, _mend_png())
        assert j.get("balloons_redone") == 1, j
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was

    assert not (p.pages[0].regions[0].get("polygon") or [])
    after = _area(p)
    assert after < 0.7 * before, (before, after)
    assert 20000 < after < 30000, after


def test_the_finder_reads_the_page_as_it_now_stands(tmp_path):
    """`Project.repaired` on its own: the strokes are in the picture the
    balloon is found from, and only the under-text ones."""
    from mangatl import editor

    p = _project(str(tmp_path / "e"), nick=True)
    srv, was, base = _serve(p)
    try:
        _paint(base, _mend_png())
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
    scan = p.image(0)
    fixed = p.repaired(0)
    assert fixed.shape == scan.shape
    # the wall is dark in the repair and white in the scan
    y, x = (WALL_A[1] + WALL_B[1]) // 2, (WALL_A[0] + WALL_B[0]) // 2
    assert int(scan[y, x].mean()) > 200, scan[y, x]
    assert int(fixed[y, x].mean()) < 80, fixed[y, x]


def test_the_writing_is_still_read_off_the_scan(tmp_path):
    """Painting over a line of Japanese says "leave this alone". It must not
    also mean "there was never anything here to erase" — the cleaner would
    then have nothing to do and the words would stay on the page."""
    from mangatl import editor

    p = _project(str(tmp_path / "f"), nick=False)
    ink = int((p.materialize(0).regions[0].text_mask > 0).sum())
    assert ink > 200, ink
    ov = np.zeros((H, W, 4), np.uint8)
    cv2.rectangle(ov, (175, 200), (300, 245), (255, 255, 255, 255), -1)
    ov[..., 3] = 255
    png = cv2.imencode(".png", ov)[1].tobytes()
    srv, was, base = _serve(p)
    try:
        _paint(base, png)
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
    again = int((p.materialize(0).regions[0].text_mask > 0).sum())
    assert again == ink, (ink, again)


# ------------------------------------------------------ and when it must not

def test_a_stroke_nowhere_near_a_balloon_leaves_it_alone(tmp_path):
    """Mending one balloon must not re-open the question for every box on the
    page. A shape found once should not wander."""
    from mangatl import editor

    p = _project(str(tmp_path / "g"), nick=True)
    p.commit(0, p.materialize(0))
    p.save()
    was_poly = list(p.pages[0].regions[0]["polygon"])
    assert len(was_poly) > 3
    ov = np.zeros((H, W, 4), np.uint8)
    cv2.circle(ov, (60, 470), 12, (0, 0, 0, 255), -1)      # a corner of the page
    ov[..., 3] = np.where(ov[..., :3].any(axis=2) | (ov[..., 3] > 0), 255, 0)
    png = cv2.imencode(".png", ov)[1].tobytes()
    srv, wasp, base = _serve(p)
    try:
        j = _paint(base, png)
        assert j.get("balloons_redone") == 0, j
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = wasp
    assert p.pages[0].regions[0]["polygon"] == was_poly


def test_a_box_drawn_by_hand_keeps_its_shape(tmp_path):
    """That outline is a decision, not a reading, and no amount of painting
    makes it a guess again."""
    from mangatl import editor

    p = _project(str(tmp_path / "h"), nick=True, manual=False)
    p.commit(0, p.materialize(0))
    p.pages[0].regions[0]["manual"] = True
    p.save()
    was_poly = list(p.pages[0].regions[0]["polygon"])
    srv, wasp, base = _serve(p)
    try:
        j = _paint(base, _mend_png())
        assert j.get("balloons_redone") == 0, j
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = wasp
    assert p.pages[0].regions[0]["polygon"] == was_poly


def test_a_box_that_never_had_a_balloon_keeps_its_rectangle(tmp_path):
    """A rectangle in the polygon field is not a drawn outline — it is what is
    stored for a region no balloon was found for, and for one tightened by
    hand. Nothing is gained by forgetting it (the shape is searched for again
    on every build anyway), and something is lost: `bubble_bbox` is the
    rectangle that region falls back to, and clearing it drops the block back
    onto the smaller box round its writing."""
    from mangatl import editor

    p = _project(str(tmp_path / "j"), nick=False)
    rec = p.pages[0].regions[0]
    rec["polygon"] = [[150, 180], [330, 180], [330, 270], [150, 270]]
    rec["bubble_bbox"] = [150, 180, 180, 90]
    p.save()
    wide = _area(p)

    srv, wasp, base = _serve(p)
    try:
        ov = np.zeros((H, W, 4), np.uint8)
        cv2.line(ov, (150, 180), (330, 180), (25, 25, 25, 255), 7)
        ov[..., 3] = np.where(ov[..., :3].any(axis=2), 255, 0)
        j = _paint(base, cv2.imencode(".png", ov)[1].tobytes())
        assert j.get("balloons_redone") == 0, j
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = wasp
    assert p.pages[0].regions[0]["bubble_bbox"] == [150, 180, 180, 90]
    assert _area(p) == wide


def test_erasing_the_paint_again_costs_nothing(tmp_path):
    """An empty overlay is not a repair. Saving one must not go round
    forgetting shapes."""
    from mangatl import editor

    p = _project(str(tmp_path / "i"), nick=True)
    p.commit(0, p.materialize(0))
    p.save()
    was_poly = list(p.pages[0].regions[0]["polygon"])
    srv, wasp, base = _serve(p)
    try:
        j = _paint(base, b"")
        assert j.get("balloons_redone") in (0, None), j
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = wasp
    assert p.pages[0].regions[0]["polygon"] == was_poly
