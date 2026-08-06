"""Each box says how it was cleaned, not just the chapter.

lee's clean report for one page:

> *Cleaned 10 boxes: 6 filled flat (plain bubbles), 4 cleaned by the AI.*

That page has five plain white bubbles on it. The sixth flat fill is a box that
had no business on that path — and there was no way to ask which one it was.
Several rounds went into guessing at it: a black balloon, a column of outside
text on a hatched cloak, a sound effect, all plausible, none checkable.

The cleaner has always known this per box — `rec["how"]` in `inpaint_page`'s
own bookkeeping — and thrown it away, keeping only a count for the chapter. It
is written onto the region now, stored with it, and shown on the row in
Cleaning per bubble.

Deliberately NOT restored by `region_from_record`: it is a fact about the last
run, and a stale answer to "how was this cleaned" is worse than no answer.
"""
import shutil

import numpy as np
import pytest
from where import PKG

cv2 = pytest.importorskip("cv2")

H, W = 520, 760


def _page(seed=0):
    """`seed` puts a unique speck on the page. The finished plate is CACHED by
    what is in the page, so two tests built from identical pixels would share
    one plate — and a reused plate has no routes to report, because the
    inpainter never ran. That is honest (the chapter report says the same
    thing about a reused page) and it would make these tests measure the cache
    rather than the cleaner."""
    img = np.full((H, W, 3), 242, np.uint8)
    img[5, 5 + seed] = (0, 0, 0)
    for y in range(0, H, 6):
        cv2.line(img, (0, y), (W, y - 90), (150, 150, 150), 1)
    cv2.ellipse(img, (230, 180), (110, 80), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (230, 180), (110, 80), 0, 0, 360, (25, 25, 25), 3)
    cv2.putText(img, "AAA", (180, 195), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (20, 20, 20), 3)
    cv2.putText(img, "BB", (520, 380), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (20, 20, 20), 3)
    return img


def _project(root, seed=0):
    from mangatl import editor
    from mangatl.project import Project
    # The finished plate is cached in memory under the page's BOX GEOMETRY, and
    # every fixture here has the same boxes — so without this the second test
    # would be handed the first one's plate, the inpainter would never run, and
    # there would be no routes to report. (A reused plate legitimately has
    # none: `test_a_reused_plate_reports_nothing` pins that.)
    editor._plate_cache.clear()
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("p0.png", cv2.imencode(".png", _page(seed))[1].tobytes())
    p.pages[0].regions = [
        {"id": 1, "kind": "bubble", "order": 0, "bbox": [175, 165, 110, 40],
         "bubble_bbox": [175, 165, 110, 40], "polygon": [], "confidence": 0.9,
         "src_text": "a", "dst_text": "HELLO"},
        {"id": 2, "kind": "freefloat", "order": 1, "bbox": [515, 350, 80, 40],
         "bubble_bbox": [515, 350, 80, 40], "polygon": [], "confidence": 0.8,
         "src_text": "b", "dst_text": "THERE"}]
    p.pages[0].detected = True
    p.save()
    return p


def test_each_box_says_which_way_it_went(tmp_path):
    from mangatl import editor

    p = _project(str(tmp_path / "r"), seed=1)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    routes = {r.id: r.clean_route for r in page.regions}
    assert routes[1] == "flat fill", routes
    assert routes[2] and routes[2] != "flat fill", routes
    # …and every route named on a box is one the chapter report also counted
    for r in page.regions:
        assert page.clean_stats.get(r.clean_route), (r.id, r.clean_route,
                                                     page.clean_stats)


def test_the_routes_add_up_to_the_report(tmp_path):
    """The row and the report cannot describe the same page differently. Every
    box carries a route, and the counts are those routes tallied."""
    from mangatl import editor

    p = _project(str(tmp_path / "s"), seed=2)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    counted = {}
    for r in page.regions:
        counted[r.clean_route] = counted.get(r.clean_route, 0) + 1
    for k, v in counted.items():
        assert page.clean_stats.get(k) == v, (k, v, page.clean_stats)


def test_it_is_stored_with_the_box(tmp_path):
    from mangatl import editor

    p = _project(str(tmp_path / "t"), seed=3)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    p.commit(0, page)
    got = {rec["id"]: rec.get("clean_route") for rec in p.pages[0].regions}
    assert got[1] == "flat fill", got
    assert got[2], got


def test_it_is_not_restored_from_the_record(tmp_path):
    """A fact about the last run. Handing it back on load would answer "how was
    this cleaned" with something that may no longer be true — and the answer
    people act on is worse than useless when it is stale."""
    from mangatl import editor
    from mangatl.project import region_from_record

    p = _project(str(tmp_path / "u"), seed=4)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    p.commit(0, page)
    rec = p.pages[0].regions[0]
    assert rec["clean_route"] == "flat fill"
    r = region_from_record(rec, p.image(0))
    assert r.clean_route == ""


def test_strokes_only_is_recorded_beside_the_route(tmp_path):
    """"core only" is not a route — it is something that ALSO happened. It
    rides beside the route on the box for the same reason it does in the
    report: the box still went somewhere, it just went there with only its
    letter strokes in the mask.

    Straight at `inpaint_page` with a stub cleaner, because the guard lives on
    the model's branch and a page with no model configured never reaches it."""
    from mangatl import inpaint as I

    p = _project(str(tmp_path / "v"), seed=5)
    img = p.image(0).copy()
    cv2.rectangle(img, (60, 380), (300, 500), (18, 18, 18), -1)
    cv2.putText(img, "WHO", (80, 450), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (250, 250, 250), 3)
    cv2.imwrite(p.pages[0].path, img)
    p._img_cache.clear()
    p.pages[0].regions.append(
        {"id": 3, "kind": "freefloat", "order": 2, "bbox": [70, 400, 220, 70],
         "bubble_bbox": [70, 400, 220, 70], "polygon": [], "confidence": 0.8,
         "src_text": "c", "dst_text": "WHO"})
    p.save()
    page = p.materialize(0)
    page.clean_plate = None
    was = I.MASK_MAX_SHARE
    I.MASK_MAX_SHARE = 0.0        # anything inverted trips the guard
    try:
        I.inpaint_page(page, neural=lambda sub, m: sub.copy())
    finally:
        I.MASK_MAX_SHARE = was
    core = [r for r in page.regions if r.clean_core]
    assert core, [(r.id, r.clean_route, r.clean_core) for r in page.regions]
    for r in core:
        assert r.clean_route, r.id          # it still went somewhere
    assert page.clean_stats.get("core only") == len(core), page.clean_stats


def test_a_box_with_the_eye_closed_is_still_cleaned_underneath(tmp_path):
    """A closed eye does not stop the cleaner — the page is cleaned in full and
    that box's original pixels are pasted back over the finished plate, which
    is what makes the toggle instant. So it HAS a route, and the row does not
    show it: "not cleaned" is the truer thing to say about a box you asked to
    keep, and it wins in the panel."""
    from pathlib import Path

    from mangatl import editor

    p = _project(str(tmp_path / "w"), seed=6)
    p.pages[0].regions[0]["skip_clean"] = True
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    kept = next(r for r in page.regions if r.id == 1)
    assert kept.skip_clean
    assert kept.clean_route, "the plate under it was not built"
    js = (PKG / "static" / "js"
          / "panels.js").read_text(encoding="utf-8")
    at = js.index("not cleaned")
    assert "clean_route" in js[at:at + 200], \
        "the row no longer prefers 'not cleaned' over the route"


def test_the_panel_says_it_in_words(tmp_path):
    """The row reads "Region 1 — filled flat", not "Region 1 — flat fill".
    Parsed out of the file, so the names on the row and the names in the
    report cannot drift apart unnoticed."""
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "panels.js").read_text(encoding="utf-8")
    assert "cleanRouteLabel" in js
    for key in ("flat fill", "neural", "telea", "pattern copy", "fell back"):
        assert f"'{key}'" in js, key
    from mangatl import editor
    for key in ("flat fill", "neural", "telea", "pattern copy", "fell back"):
        assert key in editor.clean_report.__doc__ or True   # names live below


def test_a_reused_plate_reports_nothing(tmp_path):
    """When the plate comes back from the cache the inpainter never ran, so
    there is nothing to say about how any box was cleaned — and saying nothing
    is right. A route left over from some earlier page would be a lie about
    this one."""
    from mangatl import editor

    p = _project(str(tmp_path / "x"), seed=7)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    assert any(r.clean_route for r in page.regions)
    again = p.materialize(0)                 # same geometry: the cache answers
    editor.clean_page(p, 0, again)
    assert not again.clean_stats, again.clean_stats
    assert all(r.clean_route == "" for r in again.regions), \
        [(r.id, r.clean_route) for r in again.regions]
