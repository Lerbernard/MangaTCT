"""An eye on every row: one box put away, or brought back.

lee:

> *add a eye button to the [row] in teh original page thag allow me to hid a
> box, just like i can hide all the sfx box — i shud be able to hide individual
> boxes. if i hid an individual sfx box and i use the main unhide tool to hide
> and unhide all the sfx it shoud allso unhide teh individual box*

The page already had the group switches: `PageState.hidden_kinds` puts a whole
kind away, and a hidden group is not drawn and takes no part in any stage —
not read, not translated, not cleaned, not typeset, not exported — and is not
deleted. `hidden_ids` is the same rule, one box at a time.

Two things about it are worth stating plainly, because they are the whole
design:

* **A hidden box leaves `regions`.** It has to: `regions` is the page's work,
  and anything that walks it would otherwise start treating a put-away box as
  work again. So the browser gets `hidden_rows` as well — the little the list
  needs to draw a greyed row with a closed eye on it, and nothing more. Without
  that row there would be no way back to a hidden box at all.
* **The group switch is the master control.** Using it is a statement about
  every box in that group, so it spends the per-box choices inside it — which
  is exactly the sentence lee wrote. Groups the switch did not move keep
  theirs.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((520, 760, 3), 242, np.uint8)
    cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (300, 220), (150, 90), 0, 0, 360, (25, 25, 25), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [
        {"id": 1, "kind": "bubble", "order": 0, "bbox": [200, 170, 200, 100],
         "bubble_bbox": [150, 130, 300, 180],
         "polygon": [[200, 170], [400, 170], [400, 270], [200, 270]],
         "src_text": "ひとつめ", "dst_text": "FIRST", "confidence": 0.9},
        {"id": 2, "kind": "sfx", "order": 1, "bbox": [520, 60, 120, 160],
         "bubble_bbox": [520, 60, 120, 160],
         "polygon": [[520, 60], [640, 60], [640, 220], [520, 220]],
         "src_text": "ドドド", "dst_text": "DODODO", "confidence": 0.8},
        {"id": 3, "kind": "sfx", "order": 2, "bbox": [60, 380, 110, 90],
         "bubble_bbox": [60, 380, 110, 90],
         "polygon": [[60, 380], [170, 380], [170, 470], [60, 470]],
         "src_text": "バン", "dst_text": "BAM", "confidence": 0.8},
    ]
    p.pages[0].detected = True
    p.save()
    return p


def _ids(page):
    return [r["id"] for r in page.active]


# --------------------------------------------------------------- the rule

def test_one_box_put_away_leaves_the_pages_work(tmp_path):
    p = _project(str(tmp_path / "hide"))
    pg = p.pages[0]
    assert _ids(pg) == [1, 2, 3]
    pg.hidden_ids = [2]
    assert _ids(pg) == [1, 3]
    assert [r["id"] for r in pg.hidden] == [2]
    # ...and is not deleted
    assert [r["id"] for r in pg.regions] == [1, 2, 3]


def test_a_hidden_group_and_a_hidden_box_are_the_same_kind_of_gone(tmp_path):
    p = _project(str(tmp_path / "hide"))
    pg = p.pages[0]
    pg.hidden_kinds = ["sfx"]
    assert _ids(pg) == [1]
    pg.hidden_kinds = []
    pg.hidden_ids = [2, 3]
    assert _ids(pg) == [1]


def test_the_group_switch_spends_the_per_box_choices_in_it(tmp_path):
    """lee's sentence, exactly. Hide one sfx by hand, then use the sfx switch:
    the hand-hidden one comes back with the rest."""
    p = _project(str(tmp_path / "hide"))
    pg = p.pages[0]
    pg.hidden_ids = [2]
    assert _ids(pg) == [1, 3]

    pg.hide_group(["sfx"])              # hide them all
    assert pg.hidden_ids == []
    assert _ids(pg) == [1]

    pg.hide_group([])                   # ...and show them all
    assert pg.hidden_ids == []
    assert _ids(pg) == [1, 2, 3], "the hand-hidden box did not come back"


def test_a_switch_that_did_not_move_leaves_its_boxes_alone(tmp_path):
    """It spends the choices in the groups it MOVED, not everywhere. Hiding
    the bubbles must not quietly un-hide a sound effect."""
    p = _project(str(tmp_path / "hide"))
    pg = p.pages[0]
    pg.hidden_ids = [2]
    pg.hide_group(["bubble"])
    assert pg.hidden_ids == [2], pg.hidden_ids
    assert _ids(pg) == [3]


def test_setting_the_same_groups_again_changes_nothing(tmp_path):
    """"Moved" means moved. Re-sending the list that is already set — which is
    what the every-page switch does on its own — must not spend anything."""
    p = _project(str(tmp_path / "hide"))
    pg = p.pages[0]
    pg.hide_group(["sfx"])
    pg.hidden_ids = [1]
    pg.hide_group(["sfx"])
    assert pg.hidden_ids == [1], pg.hidden_ids


def test_it_survives_being_saved_and_reopened(tmp_path):
    from mangatl.project import Project
    root = str(tmp_path / "hide")
    p = _project(root)
    p.pages[0].hidden_ids = [2]
    p.save()
    back = Project(None, root)
    assert [int(v) for v in back.pages[0].hidden_ids] == [2]
    assert _ids(back.pages[0]) == [1, 3]


def test_an_id_that_is_not_a_number_does_not_take_the_page_down(tmp_path):
    p = _project(str(tmp_path / "hide"))
    pg = p.pages[0]
    pg.regions[0].pop("id")
    pg.hidden_ids = [2]
    assert [r.get("id") for r in pg.active] == [None, 3]


# ------------------------------------------------------------- the server

def _serve(p):
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _post(base, path, body):
    import json
    import urllib.request
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as fh:
        return json.loads(fh.read().decode())


def _get(base, path):
    import json
    import urllib.request
    with urllib.request.urlopen(base + path) as fh:
        return json.loads(fh.read().decode())


def test_the_endpoints_hide_and_show_one_box(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "hide"))
    srv, was, base = _serve(p)
    try:
        j = _post(base, "/api/page/0/region/2", {"hidden": True})
        assert j["hidden_ids"] == [2], j["hidden_ids"]
        assert [r["id"] for r in j["regions"]] == [1, 3]
        assert [r["id"] for r in j["hidden_rows"]] == [2]
        # The row carries enough to draw ITSELF and no more. It is drawn in
        # its own place in the list now, greyed rather than moved, so "the
        # same row, greyed" is the bar: the score and the link are part of
        # how a row looks and are in; nothing that would let something
        # downstream mistake a hidden box for work is.
        row = j["hidden_rows"][0]
        assert set(row) == {"id", "order", "kind", "bbox", "src_text",
                            "dst_text", "confidence", "own_text", "link"}
        assert row["kind"] == "sfx"
        assert "polygon" not in row and "layout" not in row

        # and the page endpoint agrees, on its own
        page = _get(base, "/api/page/0")
        assert page["hidden_ids"] == [2]
        assert [r["id"] for r in page["regions"]] == [1, 3]
        assert page["hidden_boxes"] == 1

        j = _post(base, "/api/page/0/region/2", {"hidden": False})
        assert j["hidden_ids"] == []
        assert [r["id"] for r in j["regions"]] == [1, 2, 3]
        assert j["hidden_rows"] == []
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


def test_the_group_endpoint_brings_a_hand_hidden_box_back(tmp_path):
    """The same sentence again, through the API the switch actually calls."""
    from mangatl import editor
    p = _project(str(tmp_path / "hide"))
    srv, was, base = _serve(p)
    try:
        _post(base, "/api/page/0/region/2", {"hidden": True})
        j = _post(base, "/api/page/0/hidden", {"groups": ["sfx"], "all": False})
        assert j["hidden_ids"] == [], j["hidden_ids"]
        assert [r["id"] for r in j["regions"]] == [1]
        j = _post(base, "/api/page/0/hidden", {"groups": [], "all": False})
        assert [r["id"] for r in j["regions"]] == [1, 2, 3]
        assert j["hidden_ids"] == []
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


# --------------------------------------------------------------- on screen

def test_the_eye_is_on_every_row_and_puts_a_box_away(tmp_path):
    """Chromium, against the real server: click the eye on a row and the box
    goes out of the page's work, while its row stays exactly where it was,
    greyed, with an eye that brings it back.

    It used to be lifted out of the list and stacked under a "Hidden" heading
    at the bottom, which moved the row you had just pressed, moved everything
    under it, and put the way back somewhere you had to go looking for it.
    lee: *"when i click the eye button on teh tab in screenshot 3 it shoud
    stay inplace instad of going to teh bottom, and just grey out"*.
    """
    from mangatl import editor

    p = _project(str(tmp_path / "hide"))
    srv, was, base = _serve(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('original')")
            browserpool.settled(pg)

            eyes = pg.evaluate(
                "document.querySelectorAll('#list .lrow .beye').length")
            assert eyes == 3, eyes
            assert pg.evaluate("regions.length") == 3
            rows = """[...document.querySelectorAll('#list .lrow')]
                .map(r=>({id:+r.dataset.id,
                          away:r.classList.contains('away'),
                          head:r.querySelector('.rowhead').textContent
                                .replace(/\\s+/g,' ').trim()}))"""
            before = pg.evaluate(rows)

            pg.evaluate("setBoxShown(2,false)")
            pg.wait_for_timeout(1800)
            assert pg.evaluate("regions.map(r=>r.id)") == [1, 3]
            assert pg.evaluate("hiddenIds") == [2]
            assert pg.evaluate(
                "document.querySelectorAll('#list .lrow.away').length") == 1
            assert "Hidden" not in pg.evaluate(
                "document.getElementById('list').textContent"), \
                "the row was moved to a section instead of greyed in place"
            # ...in its own place, second of three, and still the same row:
            # same number, same score, same type, only greyed.
            got = pg.evaluate(rows)
            assert [r["id"] for r in got] == [1, 2, 3], got
            assert [r["away"] for r in got] == [False, True, False], got
            assert got[1]["head"] == before[1]["head"], (before[1], got[1])
            assert "0.80" in got[1]["head"], got[1]
            # Greyed and INERT: a box taking no part in the page cannot be
            # opened for editing, cannot be dragged into a new reading order,
            # and does not answer a click anywhere but the eye.
            inert = pg.evaluate("""(()=>{const r=document.querySelector(
                '#list .lrow.away');
                return {click:!!r.getAttribute('onclick'),
                        drop:!!r.getAttribute('ondrop'),
                        grab:!!r.querySelector('.rowhead')
                                .getAttribute('onmousedown'),
                        eye:!!r.querySelector('.beye')};})()""")
            assert inert == {"click": False, "drop": False, "grab": False,
                             "eye": True}, inert
            pg.evaluate("document.querySelector('#list .lrow.away').click()")
            browserpool.settled(pg)
            assert pg.evaluate("sel") != 2, "a hidden box was selected"

            pg.evaluate("setBoxShown(2,true)")
            pg.wait_for_timeout(1800)
            assert pg.evaluate("regions.map(r=>r.id)") == [1, 2, 3]
            assert pg.evaluate("hiddenIds") == []
            assert pg.evaluate(
                "document.querySelectorAll('#list .lrow.away').length") == 0
            assert not errs, errs[:2]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
