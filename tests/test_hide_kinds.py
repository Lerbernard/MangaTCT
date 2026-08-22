"""Putting a kind of box away without deleting it.

lee: *"in the current page tab add a hide for the 3 tpy of bouble named hid
speech and naration box , hide otisie text a etc … if these new button are
unslected the boxes with that type shoud be hidden and not be consideres for teh
next steps  also add a a cjeck box to allay to all pages … it shoudnt delete
them just hod them"*.

Three switches in the Current page card, one per group, ticked to show. Untick
one and those boxes leave the page and the work; tick it and they come back
exactly as they were.

The two claims that need pinning are opposite sides of the same coin.

**Not considered.** Every stage - reading, translating, proofreading, cleaning,
typesetting, rendering, exporting - builds its page in `Project.materialize`, and
that now sees only the active boxes. So one filter, in one place, covers every
step there is and every step there will be. The counts and the page status go
with it: a page whose sound effects are put away must read as finished when its
speech is done, not as "12 of 15".

**Not deleted.** `commit` writes a worked-on page back over the record, and the
page it is given no longer contains the hidden boxes - so without care the first
stage to run after hiding a group would wipe it. The hidden records are merged
back in. Find text is the one exception, and passes `keep_hidden=False`: it is
replacing this page's boxes on purpose.

Also here: a narration caption now answers to the FIRST checkbox in the Find
text dialog, with speech, because lee renamed that box to "speech and narration
bubble". It used to answer to "text outside bubbles".
"""
import json
import os
import shutil
import threading
import urllib.request
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.project import KIND_GROUPS, PageState, Project, group_of, only_kinds
from scratch import scratch
from where import PKG

JS = PKG / "static" / "js"
HTML = PKG / "static" / "editor.html"


def _rec(rid, kind, order=None, **kw):
    r = {"id": rid, "kind": kind, "order": rid if order is None else order,
         "bbox": [10 + rid * 30, 10, 20, 20],
         "bubble_bbox": [10 + rid * 30, 10, 20, 20],
         "polygon": [[10 + rid * 30, 10], [30 + rid * 30, 10],
                     [30 + rid * 30, 30], [10 + rid * 30, 30]],
         "src_text": "テスト", "dst_text": "TEST", "confidence": 0.9}
    r.update(kw)
    return r


FOUR = [_rec(0, "bubble"), _rec(1, "narration"),
        _rec(2, "freefloat"), _rec(3, "sfx")]


def _state(hidden=()):
    st = PageState(path="p.png", name="p.png", width=200, height=80)
    st.regions = [dict(r) for r in FOUR]
    st.hidden_kinds = list(hidden)
    st.detected = True
    return st


def _project(root, hidden=(), n_pages=2):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((80, 200, 3), 240, np.uint8)
    for k in range(n_pages):
        cv2.rectangle(img, (12, 12), (28, 28), (20, 20, 20), -1)
        p.add_uploaded("p%d.png" % k, cv2.imencode(".png", img)[1].tobytes())
        p.pages[k].regions = [dict(r) for r in FOUR]
        p.pages[k].hidden_kinds = list(hidden)
        p.pages[k].detected = True
    return p


# ------------------------------------------------------------- the three groups

def test_the_three_groups_are_the_three_the_dialog_offers():
    assert list(KIND_GROUPS) == ["bubble", "freefloat", "sfx"]
    assert group_of("bubble") == "bubble"
    assert group_of("narration") == "bubble"
    assert group_of("freefloat") == "freefloat"
    assert group_of("sfx") == "sfx"


def test_a_narration_caption_answers_to_the_speech_box_now():
    """It used to answer to "text outside bubbles". lee renamed the first
    checkbox to "speech and narration bubble", which moves it."""
    from mangatl.models import TextRegion
    cap = TextRegion(id=0, bbox=(0, 0, 10, 10), kind="narration")
    assert only_kinds([cap], ["bubble"]) == [cap]
    assert only_kinds([cap], ["freefloat"]) == []
    assert only_kinds([cap], ["sfx"]) == []


def test_a_sub_type_is_hidden_by_its_own_familys_switch():
    """Every box belongs to a family now, including one whose sub-type nobody
    recognises any more - so there is no box the three switches cannot reach.

    That is a change. There used to be a fourth state: a type invented by hand
    belonged to no group, so no switch touched it and it stayed on screen with
    everything else put away. A switch labelled "Balloon" that leaves some
    balloons showing is a switch that lies, and a box whose sub-type has since
    been deleted is exactly the one you would want to be able to put away.
    """
    st = _state(hidden=("bubble", "freefloat", "sfx"))
    st.regions.append(_rec(4, "ck_gone_for_ever"))
    assert group_of("ck_gone_for_ever") == "bubble"
    assert st.active == []
    st2 = _state(hidden=("freefloat", "sfx"))
    st2.regions.append(_rec(4, "ck_gone_for_ever"))
    assert [r["kind"] for r in st2.active if r["id"] == 4] == ["ck_gone_for_ever"]


@pytest.mark.parametrize("kind", ["thought", "shout", "narration"])
def test_every_balloon_type_answers_to_the_speech_switch(kind):
    """Thought, burst and caption are all closed shapes with a tail - the same
    geometry, told apart by the typesetting. Putting speech away and leaving a
    thought balloon on screen would be a switch that lies."""
    from mangatl.models import TextRegion
    r = TextRegion(id=0, bbox=(0, 0, 10, 10), kind=kind)
    assert group_of(kind) == "bubble"
    assert only_kinds([r], ["bubble"]) == [r]
    assert only_kinds([r], ["freefloat"]) == []
    assert only_kinds([r], ["sfx"]) == []


# ------------------------------------------------------------- what is offered

def test_only_the_groups_the_page_has_boxes_for_are_offered():
    st = _state()
    assert st.groups_present == ["bubble", "freefloat", "sfx"]
    st.regions = [_rec(0, "bubble"), _rec(1, "freefloat")]
    assert st.groups_present == ["bubble", "freefloat"], \
        "a page with no sound effects must not offer to hide them"


def test_a_hidden_group_is_still_offered_or_it_could_never_come_back():
    st = _state(hidden=("sfx",))
    assert "sfx" in st.groups_present
    assert [r["kind"] for r in st.active] == ["bubble", "narration",
                                              "freefloat"]


# --------------------------------------------------------- hidden means hidden

def test_unticking_a_group_takes_its_boxes_out_of_the_page():
    st = _state(hidden=("sfx",))
    assert [r["id"] for r in st.active] == [0, 1, 2]
    assert [r["id"] for r in st.hidden] == [3]
    assert len(st.regions) == 4, "nothing may be deleted"


def test_speech_and_narration_go_together():
    st = _state(hidden=("bubble",))
    assert [r["kind"] for r in st.active] == ["freefloat", "sfx"]


def test_the_counts_and_the_status_are_about_the_work_not_the_store():
    """A hidden box may well be translated already - it was on the page before
    it was put away. Counting it would report four of three done, and a page
    that reads 4/3 never matches its own total and never turns green."""
    st = _state()
    for r in st.regions:
        r["dst_text"] = "TEXT"          # every box, including the sfx
    st.hidden_kinds = ["sfx"]
    assert st.n_translated == 3, "the hidden box was counted"
    assert st.status() == "translated"
    st.regions[0]["dst_text"] = ""      # one ACTIVE box left undone
    assert st.n_translated == 2
    assert st.status() != "translated"
    st.regions[0]["dst_text"] = "TEXT"
    st.regions[3]["src_text"] = "ソフ"
    st.hidden_kinds = ["bubble", "freefloat", "sfx"]
    assert st.n_ocr == 0 and st.n_translated == 0, \
        "nothing is being worked on, so nothing counts"


def test_a_page_whose_every_box_is_hidden_is_done_not_stuck():
    st = _state(hidden=("bubble", "freefloat", "sfx"))
    assert st.active == []
    assert st.status() == "done"


def test_a_hidden_group_never_reaches_a_stage():
    root = scratch("_tmp_hide1")
    p = _project(root, hidden=("sfx",))
    try:
        page = p.materialize(0)
        assert [r.kind for r in page.regions] == ["bubble", "narration",
                                                  "freefloat"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stage_writing_its_page_back_does_not_delete_the_hidden_boxes():
    """The bug this guards is fatal and silent: materialize hands a stage the
    active boxes, commit writes what it is given over the record, so the first
    Translate after hiding a group would have wiped that group off the page."""
    root = scratch("_tmp_hide2")
    p = _project(root, hidden=("sfx",))
    try:
        page = p.materialize(0)
        for r in page.regions:
            r.dst_text = "DONE"
        p.commit(0, page)
        kinds = [r["kind"] for r in p.pages[0].regions]
        assert kinds == ["bubble", "narration", "freefloat", "sfx"], kinds
        assert p.pages[0].hidden[0]["kind"] == "sfx"
        assert [r["order"] for r in p.pages[0].regions] == [0, 1, 2, 3], \
            "the hidden box lost its place in the reading order"
        # and it still carries everything it carried before
        assert p.pages[0].hidden[0]["src_text"] == "テスト"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_bringing_a_group_back_brings_the_boxes_back_unchanged():
    root = scratch("_tmp_hide3")
    p = _project(root, hidden=("sfx",))
    try:
        before = json.dumps(p.pages[0].hidden, sort_keys=True)
        page = p.materialize(0)
        p.commit(0, page)
        p.pages[0].hidden_kinds = []
        assert len(p.pages[0].active) == 4
        after = json.dumps([r for r in p.pages[0].regions
                            if r["kind"] == "sfx"], sort_keys=True)
        assert after == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_text_replaces_the_boxes_rather_than_resurrecting_them():
    """Find text is the one commit that must NOT keep them: it is replacing
    this page's boxes, and the dialog says so. Running it again with sound
    effects put away must not leave the old sound effects on the page."""
    root = scratch("_tmp_hide4")
    p = _project(root, hidden=("sfx",))
    try:
        p.detect(0, ["bubble"])
        assert all(r["kind"] != "sfx" for r in p.pages[0].regions), \
            "the superseded sound effect came back"
        # and the plain merge still keeps them when nobody said otherwise
        p.pages[0].regions = [dict(r) for r in FOUR]
        page = p.materialize(0)
        page.regions = page.regions[:1]
        p.commit(0, page)
        assert [r["kind"] for r in p.pages[0].regions] == ["bubble", "sfx"]
        p.pages[0].regions = [dict(r) for r in FOUR]
        page = p.materialize(0)
        page.regions = page.regions[:1]
        p.commit(0, page, keep_hidden=False)
        assert [r["kind"] for r in p.pages[0].regions] == ["bubble"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_exported_translations_leave_out_what_is_hidden():
    root = scratch("_tmp_hide5")
    p = _project(root, hidden=("sfx",))
    try:
        assert all(r["kind"] != "sfx" for r in p.pages[0].active)
        # the dump the browser downloads is built from `active`
        from mangatl import editor
        src = __import__("inspect").getsource(editor.Handler.do_GET)
        assert "for r in sorted(st.active," in src
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_box_sheet_shows_what_the_editor_shows():
    root = scratch("_tmp_hide6")
    p = _project(root, hidden=("sfx",))
    try:
        from mangatl import editor
        from mangatl import render
        os.makedirs(editor.export_root(p), exist_ok=True)
        got = cv2.imread(editor.export_page(p, 0, mode="boxes"))
        want = render.box_sheet(p.image(0), p.pages[0].active)
        assert np.array_equal(got, want)
        assert not np.array_equal(
            got, render.box_sheet(p.image(0), p.pages[0].regions)), \
            "the sheet drew the boxes that are not on screen"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_rendered_page_changes_when_a_group_is_put_away():
    """The three views are cached on a key built from the page's inputs. If
    hiding a group does not move that key, the picture on screen still has the
    hidden typesetting on it."""
    from mangatl import editor
    root = scratch("_tmp_hide7")
    p = _project(root)
    try:
        a = editor._render_stamp(p, 0, "typeset")
        p.pages[0].hidden_kinds = ["sfx"]
        assert editor._render_stamp(p, 0, "typeset") != a
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------- over the wire

def _serve(p):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1], was


def _post(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read())


def test_the_page_tells_the_browser_what_is_hidden_and_what_could_be():
    from mangatl import editor
    root = scratch("_tmp_hide8")
    p = _project(root, hidden=("sfx",))
    srv, base, was = _serve(p)
    try:
        d = _get(base, "/api/page/0")
        assert d["kinds"] == ["bubble", "freefloat", "sfx"]
        assert d["hidden"] == ["sfx"]
        assert d["hidden_boxes"] == 1
        assert [r["kind"] for r in d["regions"]] == ["bubble", "narration",
                                                     "freefloat"]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_hiding_applies_to_one_page_by_default():
    from mangatl import editor
    root = scratch("_tmp_hide9")
    p = _project(root, n_pages=3)
    srv, base, was = _serve(p)
    try:
        j = _post(base, "/api/page/1/hidden", {"groups": ["sfx"]})
        assert j["hidden"] == ["sfx"] and j["pages"] == 1
        assert p.pages[1].hidden_kinds == ["sfx"]
        assert p.pages[0].hidden_kinds == [] and p.pages[2].hidden_kinds == []
        assert p.settings["hide_all_pages"] is False
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_all_pages_switch_carries_the_choice_across_the_chapter():
    from mangatl import editor
    root = scratch("_tmp_hide10")
    p = _project(root, n_pages=3)
    srv, base, was = _serve(p)
    try:
        j = _post(base, "/api/page/0/hidden",
                  {"groups": ["sfx"], "all": True})
        assert j["pages"] == 3
        assert all(st.hidden_kinds == ["sfx"] for st in p.pages)
        assert p.settings["hide_all_pages"] is True
        # nothing was deleted anywhere
        assert all(len(st.regions) == 4 for st in p.pages)
        # and it comes back the same way
        _post(base, "/api/page/0/hidden", {"groups": [], "all": True})
        assert all(st.hidden_kinds == [] for st in p.pages)
        assert all(len(st.active) == 4 for st in p.pages)
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_the_choice_survives_a_save_and_a_reload():
    from mangatl import editor
    root = scratch("_tmp_hide11")
    p = _project(root, n_pages=2)
    srv, base, was = _serve(p)
    try:
        _post(base, "/api/page/0/hidden", {"groups": ["sfx", "freefloat"]})
        back = Project(None, root)
        back.load()
        assert sorted(back.pages[0].hidden_kinds) == ["freefloat", "sfx"]
        assert len(back.pages[0].regions) == 4
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


def test_a_group_nobody_has_heard_of_is_ignored_not_stored():
    from mangatl import editor
    root = scratch("_tmp_hide12")
    p = _project(root, n_pages=1)
    srv, base, was = _serve(p)
    try:
        j = _post(base, "/api/page/0/hidden",
                  {"groups": ["sfx", "sideways", "bubble"]})
        assert j["hidden"] == ["bubble", "sfx"]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------ the dialog

def test_the_first_checkbox_says_speech_and_narration():
    html = HTML.read_text(encoding="utf8")
    assert "Speech and narration bubbles" in html
    assert ">Speech bubbles<" not in html


def test_the_card_offers_one_switch_per_group_and_the_every_page_box():
    # One switch per family, named once - the table is in frames.js and the
    # card is built from it, so there is no second list of names to go stale.
    js = (JS / "panels.js").read_text(encoding="utf8")
    assert "const BOX_GROUPS=KIND_FAMILIES.map(" in js
    frames = (JS / "frames.js").read_text(encoding="utf8")
    for key, label in (("bubble", "Bubble text"),
                       ("freefloat", "Freefloat text"),
                       ("sfx", "Sound effect")):
        assert f"{key}:'{label}'" in frames.replace(", ", ","), key
    assert "hideAllPages" in js
    assert "setKindShown" in js
    ops = (JS / "region-ops.js").read_text(encoding="utf8")
    assert "async function setKindShown" in ops
    assert "/hidden'" in ops or "/hidden`" in ops


def test_the_card_offers_exactly_the_groups_there_are_boxes_for():
    """The rule lee gave: ask Find text for speech and outside text only, and
    no sound-effect switch appears. Run in a real DOM, because the answer comes
    from the page's own report and from the every-page switch together."""
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not available")
    root = str(PKG)
    if not os.path.isdir(os.path.join(root, "node_modules", "jsdom")):
        pytest.skip("jsdom not installed")
    out = subprocess.run(
        ["node", os.path.join("tests", "ui", "hide_kinds.test.js")],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert ('switches: ["Bubble text","Outside text",'
            '"Apply to every page in the chapter"]') in out.stdout, out.stdout
    assert '"Sound effect"' in out.stdout, out.stdout
    assert "sfx ticked: false speech ticked: true" in out.stdout, out.stdout
    assert "this page only: 3" in out.stdout, out.stdout
    assert "every page: 4" in out.stdout, out.stdout
    assert "every-page box ticked: true" in out.stdout, out.stdout
    assert 'posted: {"groups":["sfx"],"all":false}' in out.stdout, out.stdout
    assert "count line: true" in out.stdout, out.stdout
