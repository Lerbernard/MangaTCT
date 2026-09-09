# -*- coding: utf-8 -*-
"""A broken balloon outline gets the model's balloon - for the typesetter.

lee, in order: *"alright add it"*; *"ok it it good enought to use it more
than just a warning, espaesialy with the typesetter for bubble"*; *"it
should only help the typesetter on bubble text"*; and, over a crop of page
022's double bubble, *"thesy hsoud stil be detected as two seperate ballons
not merge into one"*.

The check (`balloonck.py`) measures each bubble-family outline's SPILL - the
share of it outside every balloon the model sees. Measured on lee's 23 pages
before it was built: 142 outlines, median spill 0.024, three real catches,
zero false alarms.

The rules these tests pin:

* `polygon` is NEVER touched - the cleaner reads it, and every past change
  to the cleaning mask moved something else. The better shape goes in
  `fit_poly`, which only the typesetter reads (`typeset.share_masks`);
* a fit is refused when no single balloon holds the box's writing, and
  refused again when the winning balloon also holds a neighbour's box - a
  double bubble is one connected shape, the model reads it as one balloon,
  and its division belongs to the app's own share-cutting;
* a stale `fit_poly` comes off when the outline is sound again;
* bubble family only; hidden boxes untouched; its own flag sentences are
  replaced, never stacked, and everybody else's survive;
* it remembers what it checked this run, so an unchanged page costs a hash;
* absent model, absent ultralytics, or `balloon_check: off` mean no check,
  no flags, no error.

Where it runs: the end of `Project.detect`, and a final `warm_pages` sweep
for chapters that arrive already boxed. Same behaviour in both - a fit that
cannot touch the cleaner has no cost that depends on where it happens.
"""
import os
import shutil
import time

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

from mangatl import balloonck                                  # noqa: E402


def _project(root, kinds=("bubble",)):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 240, 3), 246, np.uint8)
    cv2.ellipse(img, (120, 100), (80, 60), 0, 0, 360, (0, 0, 0), 2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    for n, kind in enumerate(kinds):
        p.pages[0].regions.append({
            "id": n, "kind": kind, "order": n, "bbox": [60, 60, 120, 80],
            "bubble_bbox": [40, 40, 160, 120],
            # a square outline sitting exactly on the stub model's balloon
            "polygon": [[50, 50], [190, 50], [190, 150], [50, 150]],
            "src_text": "テスト", "dst_text": "HELLO", "confidence": 0.9})
    p.pages[0].detected = True
    return p


def _weights(root):
    fp = os.path.join(root, "m109seg.pt")
    open(fp, "wb").write(b"not a real checkpoint")
    return fp


def _stub(monkeypatch, *rects):
    """The model sees one rectangular balloon per (x0,y0,x1,y1) given."""
    rects = rects or ((50, 50, 190, 150),)
    calls = []

    def balloons(img, path):
        calls.append(path)
        out = []
        for x0, y0, x1, y1 in rects:
            m = np.zeros(img.shape[:2], np.uint8)
            m[y0:y1, x0:x1] = 255
            out.append(m)
        return out
    monkeypatch.setattr(balloonck, "_balloons", balloons)
    # The model is stubbed, so the engine that would run it is "present"
    # whether or not ultralytics is installed where this runs. Without this
    # the whole file was green on a machine with it and red on CI without.
    monkeypatch.setattr(balloonck, "_engine_present", lambda: True)
    return calls


@pytest.fixture(autouse=True)
def _fresh():
    balloonck._done.clear()
    yield
    balloonck._done.clear()


# ------------------------------------------------------------------ verdicts

def test_an_outline_on_its_balloon_is_left_alone(monkeypatch):
    p = _project(scratch("_tmp_bck_ok"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    _stub(monkeypatch)
    try:
        assert balloonck.check_page(p, 0) == 0
        r = p.pages[0].regions[0]
        assert r.get("flagged") in (None, "")
        assert not r.get("fit_poly")
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_broken_outline_gets_the_balloon_as_its_typesetting_shape(
        monkeypatch):
    """The point of the whole module. The outline spills far left; the
    balloon holds the box's writing; so the typesetter gets the balloon,
    the stale fit goes, and the flag says what happened."""
    p = _project(scratch("_tmp_bck_fit"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.pages[0].regions[0]["polygon"] = [[0, 50], [190, 50],
                                        [190, 150], [0, 150]]
    p.pages[0].regions[0]["layout"] = {"lines": ["STALE"], "font_size": 12}
    _stub(monkeypatch, (50, 50, 190, 150))
    try:
        assert balloonck.check_page(p, 0) == 1
        r = p.pages[0].regions[0]
        assert balloonck.FITTED in r["flagged"], r["flagged"]
        xs = [pt[0] for pt in r["fit_poly"]]
        assert min(xs) >= 48, "the fit shape still spills left"
        assert "layout" not in r, "a fit made in the wrong shape was kept"
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_the_polygon_is_never_touched(monkeypatch):
    """lee: *"it should only help the typesetter on bubble text"*. The
    cleaner reads `polygon`; whatever this module concludes, `polygon` after
    is `polygon` before, byte for byte."""
    p = _project(scratch("_tmp_bck_poly"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.pages[0].regions[0]["polygon"] = [[0, 50], [190, 50],
                                        [190, 150], [0, 150]]
    was = [list(pt) for pt in p.pages[0].regions[0]["polygon"]]
    _stub(monkeypatch, (50, 50, 190, 150))
    try:
        balloonck.check_page(p, 0)
        assert p.pages[0].regions[0]["polygon"] == was
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_box_over_no_balloon_at_all_questions_the_kind(monkeypatch):
    """014 #23: wall-writing filed as a bubble. Nothing to fit to, so the
    flag - and its problem is its KIND, which the words say."""
    p = _project(scratch("_tmp_bck_none"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    _stub(monkeypatch, (200, 200, 230, 230))
    try:
        assert balloonck.check_page(p, 0) == 1
        r = p.pages[0].regions[0]
        assert balloonck.NOT_A_BALLOON in r["flagged"]
        assert not r.get("fit_poly")
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_balloon_shared_with_a_neighbour_is_never_handed_to_one_box(
        monkeypatch):
    """lee, over page 022's double bubble: *"thesy hsoud stil be detected as
    two seperate ballons not merge into one"*. One model balloon holding two
    boxes is a shared balloon - a real one, or a double bubble read as one
    connected shape - and its division belongs to `share_masks`. Neither box
    gets it whole; the flag stays a flag."""
    p = _project(scratch("_tmp_bck_shared"), kinds=("bubble", "bubble"))
    a, b = p.pages[0].regions
    a["bbox"], b["bbox"] = [55, 55, 60, 85], [125, 55, 60, 85]
    a["polygon"] = [[0, 50], [110, 50], [110, 150], [0, 150]]   # spills left
    b["polygon"] = [[115, 50], [190, 50], [190, 150], [115, 150]]
    p.settings["balloon_weights"] = _weights(p.output_dir)
    _stub(monkeypatch, (50, 50, 190, 150))     # ONE balloon over both boxes
    try:
        balloonck.check_page(p, 0)
        assert not a.get("fit_poly"), \
            "a merged balloon was handed whole to one of its two boxes"
        assert balloonck.OFF_BALLOON in (a.get("flagged") or "")
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_fit_comes_off_when_the_outline_is_sound_again(monkeypatch):
    """The person fixed the outline (or re-detected the page): the outline
    rules again, the borrowed shape goes, and so does the fit made in it."""
    p = _project(scratch("_tmp_bck_heal"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    r = p.pages[0].regions[0]
    r["fit_poly"] = [[50, 50], [190, 50], [190, 150], [50, 150]]
    r["layout"] = {"lines": ["OLD"], "font_size": 12}
    _stub(monkeypatch)                          # outline agrees with balloon
    try:
        assert balloonck.check_page(p, 0) == 0
        assert not r.get("fit_poly")
        assert "layout" not in r
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_only_the_bubble_family_is_judged(monkeypatch):
    p = _project(scratch("_tmp_bck_fam"),
                 kinds=("aside", "narration_free", "sfx", "sign"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    _stub(monkeypatch, (200, 200, 230, 230))
    try:
        assert balloonck.check_page(p, 0) == 0
        assert not any(r.get("flagged") or r.get("fit_poly")
                       for r in p.pages[0].regions)
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_hidden_box_is_not_judged(monkeypatch):
    p = _project(scratch("_tmp_bck_hid"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.pages[0].hidden_ids = [0]
    _stub(monkeypatch, (200, 200, 230, 230))
    try:
        assert balloonck.check_page(p, 0) == 0
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_its_opinion_is_replaced_and_everyone_elses_kept(monkeypatch):
    p = _project(scratch("_tmp_bck_stack"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.pages[0].regions[0]["flagged"] = 'speaker "Ruja" is not named anywhere'
    p.pages[0].regions[0]["polygon"] = [[0, 50], [190, 50],
                                        [190, 150], [0, 150]]
    _stub(monkeypatch, (50, 50, 190, 150))
    try:
        balloonck.check_page(p, 0)
        balloonck._done.clear()
        balloonck.check_page(p, 0)
        fl = p.pages[0].regions[0]["flagged"]
        assert fl.count(balloonck.FITTED) == 1, fl
        assert 'speaker "Ruja"' in fl, fl
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


# ------------------------------------------------------------ the economics

def test_an_unchanged_page_costs_a_hash_not_a_model(monkeypatch):
    p = _project(scratch("_tmp_bck_memo"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    calls = _stub(monkeypatch)
    try:
        balloonck.check_page(p, 0)
        balloonck.check_page(p, 0)
        balloonck.check_page(p, 0)
        assert len(calls) == 1, "the model ran %d times on one unchanged " \
            "page" % len(calls)
        assert not balloonck.wants(p, 0)
        p.pages[0].regions[0]["polygon"][0] = [51, 50]
        assert balloonck.wants(p, 0), "a moved outline must be looked at again"
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_fit_is_remembered_not_rechecked(monkeypatch):
    """The print is taken AFTER `fit_poly` was written - remembering the one
    from before would send every later sweep straight back in."""
    p = _project(scratch("_tmp_bck_remem"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.pages[0].regions[0]["polygon"] = [[0, 50], [190, 50],
                                        [190, 150], [0, 150]]
    calls = _stub(monkeypatch, (50, 50, 190, 150))
    try:
        balloonck.check_page(p, 0)
        assert p.pages[0].regions[0].get("fit_poly")
        assert not balloonck.wants(p, 0)
        balloonck.check_page(p, 0)
        assert len(calls) == 1
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_no_model_no_check_no_error():
    p = _project(scratch("_tmp_bck_nomodel"))
    # A NAMED path that is missing means no model - deliberately not "",
    # which falls back to looking beside the app, where lee's real machine
    # keeps m109seg.pt and this test must not find it.
    p.settings["balloon_weights"] = os.path.join(p.output_dir, "not-here.pt")
    try:
        assert not balloonck.available(p)
        assert balloonck.check_page(p, 0) == 0
        assert not balloonck.wants(p, 0)
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_the_kill_switch(monkeypatch):
    p = _project(scratch("_tmp_bck_off2"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.settings["balloon_check"] = "off"
    _stub(monkeypatch, (200, 200, 230, 230))
    try:
        assert not balloonck.available(p)
        assert balloonck.check_page(p, 0) == 0
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


def test_a_model_that_blows_up_costs_nothing_and_is_retried(monkeypatch):
    p = _project(scratch("_tmp_bck_boom"))
    p.settings["balloon_weights"] = _weights(p.output_dir)

    def boom(img, path):
        raise RuntimeError("cuda fell over")
    monkeypatch.setattr(balloonck, "_balloons", boom)
    monkeypatch.setattr(balloonck, "_engine_present", lambda: True)
    try:
        assert balloonck.check_page(p, 0) == 0
        assert not any(r.get("flagged") for r in p.pages[0].regions)
        assert balloonck.wants(p, 0), \
            "a failed check marked the page as checked"
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)


# -------------------------------------------- the typesetter actually reads it

def test_the_typesetter_fits_into_the_borrowed_shape():
    """`fit_poly` through `share_masks`: a bubble-family region carrying one
    typesets into IT, not into its own outline. This is the seam every
    fitting path reads - the page fit, the size levelling, the editor's
    per-box preview - so preferring it here is what keeps them agreeing."""
    from mangatl.models import TextRegion
    from mangatl.typeset import TypesetConfig, share_masks
    bub = np.zeros((300, 240), np.uint8)
    bub[50:150, 0:110] = 255                   # the broken outline's mask
    r = TextRegion(id=1, bbox=(60, 60, 120, 80), kind="bubble", order=0,
                   dst_text="HELLO", bubble_mask=bub,
                   text_mask=np.zeros((300, 240), np.uint8))
    r.fit_poly = [[50, 50], [190, 50], [190, 150], [50, 150]]
    shares = share_masks([r], TypesetConfig())
    m = shares.get(1)
    assert m is not None, "the borrowed shape never reached the fitter"
    assert m[100, 170] and not m[100, 20], \
        "the mask handed to the fitter is not the borrowed shape"


def test_a_shared_balloon_keeps_its_cut_over_the_borrowed_shape():
    """A block already in `share_masks`' answer keeps it - the check refuses
    shared balloons anyway, and this is the second lock on the same door."""
    from mangatl.models import TextRegion
    from mangatl.typeset import TypesetConfig, share_masks
    bub = np.zeros((300, 240), np.uint8)
    cv2.ellipse(bub, (120, 100), (100, 70), 0, 0, 360, 255, -1)
    rs = []
    for n, (bx, tx) in enumerate(((30, "ONE"), (130, "TWO"))):
        r = TextRegion(id=n, bbox=(bx, 60, 80, 80), kind="bubble", order=n,
                       dst_text=tx, bubble_mask=bub.copy(), link=7,
                       text_mask=np.zeros((300, 240), np.uint8))
        rs.append(r)
    rs[0].fit_poly = [[10, 10], [230, 10], [230, 290], [10, 290]]
    shares = share_masks(rs, TypesetConfig())
    m = shares.get(0)
    assert m is not None
    assert not m[150, 15], \
        "the whole-page borrowed shape overrode the balloon's own cut"


def test_fit_poly_survives_the_record_round_trip():
    """Written at the door, read at every reopen - `region_record` and
    `region_from_record` have to carry it or the door's work lasts one
    session."""
    from mangatl.models import TextRegion
    from mangatl.project import region_from_record, region_record
    r = TextRegion(id=3, bbox=(60, 60, 120, 80), kind="bubble", order=0,
                   dst_text="HELLO",
                   text_mask=np.zeros((300, 240), np.uint8))
    r.fit_poly = [[50, 50], [190, 50], [190, 150], [50, 150]]
    rec = region_record(r)
    assert rec["fit_poly"] == r.fit_poly
    img = np.full((300, 240), 246, np.uint8)
    back = region_from_record(rec, img)
    assert back.fit_poly == r.fit_poly


def test_the_fit_key_sees_the_borrowed_shape():
    """It moves lines as surely as the outline does, so it must be in
    `page_fit_key` - or a page whose fit shape changed would keep its old
    fitting."""
    from mangatl.models import Page, TextRegion
    from mangatl.typeset import TypesetConfig, page_fit_key
    def pg():
        r = TextRegion(id=1, bbox=(60, 60, 120, 80), kind="bubble", order=0,
                       dst_text="HELLO",
                       text_mask=np.zeros((300, 240), np.uint8))
        page = Page(image=np.full((300, 240, 3), 246, np.uint8))
        page.regions = [r]
        return page
    a, b = pg(), pg()
    b.regions[0].fit_poly = [[50, 50], [190, 50], [190, 150], [50, 150]]
    assert page_fit_key(a, TypesetConfig()) != page_fit_key(b, TypesetConfig())


# ------------------------------------------------------- where it runs

def test_the_door_is_wired():
    """`Project.detect` hands every fresh page to the check. Source-level,
    because running the real detector in this test costs a model this
    container does not carry."""
    import mangatl.project as project_mod
    src = open(project_mod.__file__, encoding="utf-8").read()
    body = src.split("def detect(")[1].split("\n    def ")[0]
    assert "balloonck.check_page" in body


def test_the_warm_up_gives_reopened_chapters_their_second_opinion(monkeypatch):
    """A reopened chapter never passes through `detect`, so the background
    sweep is its door - after the plates and the finished pages."""
    from mangatl import editor
    p = _project(scratch("_tmp_bck_warm"))
    p.settings["balloon_weights"] = _weights(p.output_dir)
    p.pages[0].regions[0]["polygon"] = [[0, 50], [190, 50],
                                        [190, 150], [0, 150]]
    _stub(monkeypatch, (50, 50, 190, 150))
    try:
        editor.warm_pages(p, 0)
        for _ in range(200):
            if not editor._warm.get("running"):
                break
            time.sleep(0.05)
        assert not editor._warm.get("running"), "the warm-up never finished"
        r = p.pages[0].regions[0]
        assert balloonck.FITTED in (r.get("flagged") or ""), \
            "the sweep never looked at a page that arrived already boxed"
        assert r.get("fit_poly")
        assert editor._warm["done"] == editor._warm["total"]
    finally:
        shutil.rmtree(p.output_dir, ignore_errors=True)
