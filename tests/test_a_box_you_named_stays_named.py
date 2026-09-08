"""A box keeps the type you gave it when the project is opened again.

lee: *"can you look into box dissapiraring or boxes chaning type after i reload
the projet"*.

Reproduced in three lines. Set a box to Outside text on a page with a drawn
balloon round it, save, open the project again:

    set to                : freefloat
    on disk               : freefloat
    after materialize     : bubble      <- what the editor draws
    after any save        : bubble      <- and now it is on disk too

`Project.materialize` calls `find_balloons` on EVERY page build - which is
every page view, every step and every reload - and `attach_balloons` renames a
free-floating block to a bubble whenever it turns out to be inside one. That
renaming is right where it was written, at detection, and wrong here, because
here is every time the page is opened. Silent, and permanent after one save.

It hit exactly the boxes somebody had corrected by hand, because those are the
boxes whose label disagrees with the pixels - which is what a correction IS.

**And it is also the disappearing.** A page with the Bubble text group put away
hides by FAMILY: rename a sound effect or a free block into `bubble` and the
next `materialize` builds from `active`, which no longer contains it. The box is
still in the file and gone from the page.

The rule is the one `region_from_record` already keeps for the outline: **the
label wins over the geometry.** A kind on disk is a decision already made, by a
detector or by a person, and only a fresh Find text may make it again.
"""
import numpy as np
import pytest

from where import PKG

cv2 = pytest.importorskip("cv2")


def _balloon_page(kind="freefloat"):
    """A drawn balloon with writing in it, and one region over the writing."""
    from mangatl.models import TextRegion
    img = np.full((500, 400, 3), 245, np.uint8)
    cv2.ellipse(img, (200, 250), (150, 110), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (200, 250), (150, 110), 0, 0, 360, (0, 0, 0), 3)
    cv2.putText(img, "AB", (150, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (10, 10, 10), 4)
    r = TextRegion(id=1, bbox=(140, 225, 130, 50), kind=kind, order=0,
                   src_text="AB")
    return img, [r]


def _project(tmp_path, img):
    from mangatl.project import Project
    p = Project(None, str(tmp_path))
    p.add_uploaded("a.png", cv2.imencode(".png", img)[1].tobytes())
    return p


# ------------------------------------------------------- the reload path

def test_a_box_called_outside_text_is_still_outside_text(tmp_path):
    """The case lee hit."""
    from mangatl.project import Project
    img, regs = _balloon_page("freefloat")
    p = _project(tmp_path, img)
    page = p.materialize(0)
    page.regions = regs
    p.commit(0, page)
    p.save()

    again = Project(None, str(tmp_path))
    assert again.pages[0].regions[0]["kind"] == "freefloat", "on disk"
    built = again.materialize(0)
    assert built.regions[0].kind == "freefloat", "after materialize"
    again.commit(0, built)
    again.save()
    assert again.pages[0].regions[0]["kind"] == "freefloat", "after a save"


def test_it_still_gets_its_balloon(tmp_path):
    """The label is left alone; the SHAPE is still found. Refusing the balloon
    too would typeset the English into the bare rectangle, which is the bug
    `find_balloons` was written for."""
    img, regs = _balloon_page("freefloat")
    p = _project(tmp_path, img)
    page = p.materialize(0)
    page.regions = regs
    p.commit(0, page)
    built = p.materialize(0)
    assert built.regions[0].bubble_mask is not None


def test_the_reload_path_asks_for_no_renaming():
    src = (PKG / "project.py").read_text(encoding="utf-8")
    body = src[src.index("def find_balloons("):]
    body = body[:body.index("\ndef ")]
    assert "rename=False" in body


def test_a_sound_effect_is_never_renamed_either(tmp_path):
    """Sound effects were never eligible, and this says so rather than
    trusting that they stay ineligible."""
    img, regs = _balloon_page("sfx")
    p = _project(tmp_path, img)
    page = p.materialize(0)
    page.regions = regs
    p.commit(0, page)
    assert p.materialize(0).regions[0].kind == "sfx"


# --------------------------------------------- and detection still renames

def _in_a_real_balloon(kind):
    """A balloon the finder actually accepts - it needs the writing's own mask
    to grow from, which `region_from_record` builds and a bare TextRegion has
    not got."""
    from mangatl.models import TextRegion
    page = np.full((420, 420), 250, np.uint8)
    cv2.ellipse(page, (210, 210), (150, 110), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (210, 210), (150, 110), 0, 0, 360, 0, 3)
    m = np.zeros(page.shape, np.uint8)
    for i in range(3):
        cv2.rectangle(page, (170, 195 + i * 10), (240, 200 + i * 10), 0, -1)
        cv2.rectangle(m, (170, 195 + i * 10), (240, 200 + i * 10), 255, -1)
    ys, xs = np.nonzero(m)
    bb = (int(xs.min()), int(ys.min()),
          int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1)
    return page, TextRegion(id=0, bbox=bb, text_mask=m, bubble_mask=None,
                            bubble_bbox=bb, kind=kind)


def test_detection_keeps_the_promotion():
    """The rule exists for a reason - page 023's balloon with a starfield drawn
    across it, which every fill test calls artwork. `attach_balloons` still
    renames by default, so every detection route is untouched."""
    from mangatl.detect.balloon import attach_balloons
    page, r = _in_a_real_balloon("freefloat")
    got = attach_balloons(page, [r])
    assert got >= 1, "the fixture has no balloon in it"
    assert r.kind == "bubble"


def test_and_says_no_when_it_is_asked_to():
    """The same balloon, still found, and the label untouched. Both halves
    matter: refusing to look would typeset the English into the bare box."""
    from mangatl.detect.balloon import attach_balloons
    page, r = _in_a_real_balloon("freefloat")
    got = attach_balloons(page, [r], rename=False)
    assert got >= 1, "it stopped finding the balloon as well"
    assert r.bubble_mask is not None
    assert r.kind == "freefloat"


def test_no_detection_route_was_quietly_changed():
    """Every caller in `detect/` passes nothing and keeps the old behaviour.
    If one of them ever wants `rename=False` it should say so out loud."""
    import re
    bad = []
    for f in sorted((PKG / "detect").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"(?<!def )attach_balloons\([^)]*\)", src):
            if "rename" in m.group(0):
                bad.append(f"{f.name}: {m.group(0)}")
    assert not bad, bad


# ------------------------------------------------- and the way lee met it

def test_a_box_you_draw_yourself_keeps_the_kind_you_drew_it_as(tmp_path):
    """lee: *"all new boxes that i draw revert to bubble text after
    realading"*.

    The same bug, and the way it is actually noticed - because the legend's lit
    key is how a hand-drawn box gets its kind, and drawing three sound effects
    or three outside-text boxes in a row is the normal way to work. Through the
    real endpoint, because that is the path: the client sends `newBoxKind`, the
    server stores it, and it survived every step until `materialize` renamed it
    on the way back.

    `sfx` never moved (it is not eligible for the promotion) and `narration`
    never moved (only `freefloat` is renamed), which is why this looked
    intermittent rather than broken.
    """
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from mangatl import editor
    from mangatl.project import Project

    img, _ = _balloon_page()
    p = _project(tmp_path, img)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        for kind in ("freefloat", "sfx", "narration"):
            req = urllib.request.Request(
                base + "/api/page/0/region",
                data=json.dumps({"x": 150, "y": 230, "w": 120, "h": 60,
                                 "snap": False, "kind": kind}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            got = json.loads(urllib.request.urlopen(req, timeout=30).read())
            assert got["region"]["kind"] == kind, "the draw itself"
        p.save()
    finally:
        srv.shutdown()
        editor.PROJECT = was

    again = Project(None, str(tmp_path))
    assert [r["kind"] for r in again.pages[0].regions] == \
        ["freefloat", "sfx", "narration"], "on disk"
    assert [r.kind for r in again.materialize(0).regions] == \
        ["freefloat", "sfx", "narration"], "after the page is built again"


# ------------------------------------------------------- and the vanishing

def test_a_hidden_family_is_what_makes_a_renamed_box_disappear(tmp_path):
    """Not a second bug - the same one, seen from the page. With Bubble text
    put away, a box renamed into that family is no longer in `active`, and
    `materialize` builds from `active`."""
    from mangatl.project import Project
    img, regs = _balloon_page("freefloat")
    p = _project(tmp_path, img)
    page = p.materialize(0)
    page.regions = regs
    p.commit(0, page)
    p.pages[0].hidden_kinds = ["bubble"]
    p.save()

    again = Project(None, str(tmp_path))
    assert len(again.pages[0].active) == 1, \
        "the box was renamed into the family that is put away"
    assert len(again.materialize(0).regions) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
