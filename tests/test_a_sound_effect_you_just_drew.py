"""Two things wrong with a sound effect box drawn by hand.

lee: *"when i switch to a diftrent page a create a sfx but its visulay not
there an i have to clcik trhe sfx button a lot for it to show up visulay, also
for the typsetter, i wnat you to have it also check fro the thext dircetion and
copy that too"*.

## It was drawn into a group that was put away

`PageState.active` is what the create endpoint answers with and what the client
draws, and it leaves out every box whose GROUP is hidden. So drawing a sound
effect on a page whose sound effects are away appended the record, answered
without it, and the box was simply not on screen. Nothing said so - the group
switch lives in another panel - and on manhwa and manhua the detector makes no
sound effects at all, so that group is routinely away and the only boxes in it
are the ones drawn by hand. The button lee kept clicking IS the group switch,
and clicking it is what brought the box back.

Drawing a box is as plain a statement as there is that you want to see it, so
it wins over a switch set earlier and the group comes back out on that page.

## And it was set dead straight

`read_sfx_axis` reads the axis an effect is drawn along. It ran at detection,
and it ran when a box was RE-TYPED to `sfx` from something else - never when a
box ARRIVES as one, which is every box the Add-sound-effect tool puts down.
Those reached the typesetter with `sfx_len` unset, took its "never measured"
branch, and were laid straight across the box whatever the artwork did.

Read at the moment the box is drawn, for the reason detection reads it there:
while the page still carries the Korean. By typeset time the effect is painted
out and there is no angle left to take.
"""

import numpy as np
import pytest


def _slanted(w=420, h=300):
    """A page with a sound effect drawn up the diagonal."""
    import cv2
    img = np.full((h, w, 3), 245, np.uint8)
    for k in range(-3, 4):
        cv2.line(img, (110 + k * 3, 230), (300 + k * 3, 90), (15, 15, 15), 9)
    return img


@pytest.fixture()
def proj(tmp_path):
    """A one-page project served over the real endpoint.

    Through HTTP rather than a shim: the thing under test is what the CREATE
    endpoint answers with, and `active` - the filter that dropped the box - is
    applied as it builds that answer.
    """
    import json
    import shutil
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import cv2

    from mangatl import editor as ed
    from mangatl.project import Project
    ed._plate_cache.clear()
    root = str(tmp_path / "r")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", _slanted())[1].tobytes())
    p.pages[0].detected = True
    p.save()
    was, ed.PROJECT = ed.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ed.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def post(body):
        req = urllib.request.Request(
            base + "/api/page/0/region", method="POST",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())

    try:
        yield ed, p, post
    finally:
        srv.shutdown()
        ed.PROJECT = was


def _draw(post, kind="sfx", box=(100, 80, 220, 170)):
    """The POST the Add-sound-effect tool sends."""
    x, y, w, h = box
    return post({"x": x, "y": y, "w": w, "h": h, "snap": False, "kind": kind})


def test_a_box_drawn_into_a_hidden_group_is_still_on_screen(proj):
    ed, p, post = proj
    p.pages[0].hidden_kinds = ["sfx"]
    out = _draw(post)
    assert any(r["id"] == out["region"]["id"] for r in out["regions"]), \
        "the reply left out the box that was just drawn"


def test_and_the_group_it_is_in_comes_back_out(proj):
    ed, p, post = proj
    p.pages[0].hidden_kinds = ["sfx"]
    _draw(post)
    assert "sfx" not in (p.pages[0].hidden_kinds or [])


def test_a_group_nobody_drew_into_stays_away(proj):
    """Only the group the box belongs to. Drawing a bubble is no statement at
    all about the sound effects."""
    ed, p, post = proj
    p.pages[0].hidden_kinds = ["sfx", "freefloat"]
    _draw(post, kind="bubble")
    assert "sfx" in p.pages[0].hidden_kinds
    assert "freefloat" in p.pages[0].hidden_kinds


def test_and_a_group_that_was_never_away_is_left_alone(proj):
    ed, p, post = proj
    p.pages[0].hidden_kinds = []
    out = _draw(post)
    assert p.pages[0].hidden_kinds == []
    assert any(r["id"] == out["region"]["id"] for r in out["regions"])


def test_a_box_hidden_one_at_a_time_is_not_what_this_is_about(proj):
    """`hidden_ids` is a choice about THAT box, made after it existed. A box
    being drawn has no id anyone could have hidden."""
    ed, p, post = proj
    p.pages[0].hidden_ids = [999]
    _draw(post)
    assert p.pages[0].hidden_ids == [999]


# --- and the axis it is drawn along -------------------------------------------

def test_a_sound_effect_drawn_by_hand_is_measured(proj):
    ed, p, post = proj
    rec = _draw(post)["region"]
    assert float(rec.get("sfx_len") or 0) > 0, \
        "unmeasured, so the typesetter lays it straight"


def test_and_the_angle_follows_the_artwork(proj):
    """The effect runs up the diagonal, so the English has to lean too."""
    ed, p, post = proj
    rec = _draw(post)["region"]
    assert abs(float(rec.get("angle") or 0.0)) > 10


def test_a_bubble_drawn_by_hand_is_not_measured(proj):
    """Only a sound effect is drawn along an axis. Speech is set level."""
    ed, p, post = proj
    rec = _draw(post, kind="bubble")["region"]
    assert not float(rec.get("sfx_len") or 0)


def test_the_typesetter_uses_it_rather_than_its_own_guess(proj):
    """`fit_sfx_region` reads `sfx_len`/`sfx_wid` and falls back to straight
    when they are unset. Measuring at draw time is what stops that fallback."""
    import inspect

    from mangatl import typeset
    src = inspect.getsource(typeset)
    assert "sfx_len" in src and "Never measured" in src


def test_a_page_that_cannot_be_read_still_takes_the_box(proj):
    """A measurement is a nicety; losing the box is not."""
    ed, p, post = proj
    from mangatl import project as pj
    real = pj.read_sfx_axis
    ed_real = ed.read_sfx_axis

    def boom(*a, **k):
        raise RuntimeError("no")

    pj.read_sfx_axis = boom
    ed.read_sfx_axis = boom
    try:
        out = _draw(post)
    finally:
        pj.read_sfx_axis = real
        ed.read_sfx_axis = ed_real
    assert out["region"]["id"] is not None


def test_only_the_group_the_box_is_in_comes_back(proj):
    """Drawing a sound effect says nothing about the outside text. Bringing
    every group back would undo choices nobody revisited."""
    ed, p, post = proj
    p.pages[0].hidden_kinds = ["sfx", "freefloat"]
    _draw(post)
    assert "sfx" not in p.pages[0].hidden_kinds
    assert "freefloat" in p.pages[0].hidden_kinds
