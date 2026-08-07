"""Translating by hand: a labelled file out, a filled-in file back.

lee: *"translation json  or txt should override current text Add a manual
translation mode that allows download a txt template with the boxes labeled
and uploading that withhteh trasnalation Or just typing it in the text tab
the manual tranlat button should grey out the read text translate and
profread"*.

Four separate promises, and each one is a test below.

**Labelled.** The file names every box the way the page does — the page's own
file name and the number drawn on the box sheet — so a person filling it in
never has to look at a region id, and a line that comes back finds the box it
was written for.

**Overrides.** Whatever is in the file wins. Not "fills in the empty ones":
the point of translating by hand is usually that the machine's answer was
wrong, so a block with words in it replaces what the box says now. What is
NOT overridden is the styling — the face, the ink, the frame somebody dragged
where they wanted it — because none of that was a translation.

**Or just typing it in.** That half needs no new code: the text panel already
writes `dst_text`, and this file only checks the two routes end at the same
place.

**Greys out.** Read text, Translate and Proofread are the three steps that
call a model. In manual mode nothing is going to, so they go quiet. This is a
MODE somebody chose, not a lock the app imposed — which is exactly the
difference from the step gates lee had removed, and why turning it off gives
all three straight back.
"""
import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch

cv2 = pytest.importorskip("cv2")


# ------------------------------------------------------------------- harness

def _region(k, **extra):
    r = {"id": k + 1, "kind": "bubble", "order": k,
         "bbox": [110, 140 + 150 * k, 180, 120],
         "bubble_bbox": [105, 138 + 150 * k, 190, 124],
         "polygon": [[110, 140 + 150 * k], [290, 140 + 150 * k],
                     [290, 260 + 150 * k], [110, 260 + 150 * k]],
         "confidence": 0.9, "src_text": "テスト%d" % (k + 1)}
    r.update(extra)
    return r


def _project(root, pages=2, boxes=2, **extra):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 420, 3), 245, np.uint8)
    for k in range(pages):
        p.add_uploaded("p%d.png" % k, cv2.imencode(".png", img)[1].tobytes())
        p.pages[k].regions = [_region(j, **extra) for j in range(boxes)]
        p.pages[k].detected = True
    p.save()
    return p


def _server(p):
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1], was


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return r.read().decode("utf-8"), dict(r.headers)


def _post(base, path, obj):
    req = urllib.request.Request(
        base + path, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


# ------------------------------------------------------- the file that goes out

def test_the_template_labels_every_box_with_the_page_and_its_number(tmp_path):
    """The label is the two things a person can see: which page, and the
    number printed on that box by the box sheet. Not the region id, which is
    an internal number nobody filling in a text file should have to find."""
    from mangatl import manual
    p = _project(str(tmp_path / "t"))
    out = manual.template(p)
    for name in ("p0.png", "p1.png"):
        for n in (1, 2):
            assert f"[{name} #{n}]" in out, out


def test_the_numbers_are_the_ones_drawn_on_the_box_sheet(tmp_path):
    """Reading order, not the order the records happen to sit in. The number
    in the label is what lee can see printed on the box, so a file numbered
    any other way sends every line to the wrong bubble."""
    from mangatl import manual
    p = _project(str(tmp_path / "t"), pages=1, boxes=3)
    st = p.pages[0]
    st.regions[0]["order"], st.regions[0]["src_text"] = 2, "LAST"
    st.regions[1]["order"], st.regions[1]["src_text"] = 0, "FIRST"
    st.regions[2]["order"], st.regions[2]["src_text"] = 1, "MIDDLE"
    out = manual.template(p)
    assert "[p0.png #1]  FIRST" in out, out
    assert "[p0.png #2]  MIDDLE" in out, out
    assert "[p0.png #3]  LAST" in out, out


def test_and_a_line_comes_back_to_the_box_that_number_names(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "t"), pages=1, boxes=3)
    st = p.pages[0]
    st.regions[0]["order"] = 2
    st.regions[1]["order"] = 0
    st.regions[2]["order"] = 1
    editor.import_translation(p, "[p0.png #1]\nTHE FIRST THING SAID\n")
    assert st.regions[1]["dst_text"] == "THE FIRST THING SAID"
    assert not (st.regions[0].get("dst_text") or "")


def test_the_japanese_rides_along_beside_its_label(tmp_path):
    """Translating from a file with no source in it is translating blind."""
    from mangatl import manual
    p = _project(str(tmp_path / "t"))
    out = manual.template(p)
    assert "[p0.png #1]  テスト1" in out, out
    assert "[p1.png #2]  テスト2" in out, out


def test_what_is_already_translated_is_already_in_the_file(tmp_path):
    """So a pass by hand over a machine translation starts from the machine's
    words instead of from nothing."""
    from mangatl import manual
    p = _project(str(tmp_path / "t"))
    p.pages[0].regions[0]["dst_text"] = "THE FIRST ONE"
    out = manual.template(p)
    assert "THE FIRST ONE" in out
    block = out.split("[p0.png #1]")[1].split("[")[0]
    assert "THE FIRST ONE" in block, block


def test_only_the_pages_that_were_asked_for(tmp_path):
    """A chapter is done a few pages at a time; a file with every page in it
    is a file you lose your place in."""
    from mangatl import manual
    p = _project(str(tmp_path / "t"), pages=3)
    out = manual.template(p, [1])
    assert "p1.png" in out
    assert "p0.png" not in out and "p2.png" not in out


def test_the_json_form_says_the_same_things(tmp_path):
    from mangatl import manual
    p = _project(str(tmp_path / "t"))
    p.pages[0].regions[0]["dst_text"] = "THE FIRST ONE"
    d = manual.template_json(p)
    assert [pg["page"] for pg in d["pages"]] == ["p0.png", "p1.png"]
    b = d["pages"][0]["boxes"][0]
    assert b["n"] == 1 and b["japanese"] == "テスト1"
    assert b["english"] == "THE FIRST ONE"


# ----------------------------------------------------- the file that comes back

def test_a_filled_in_block_lands_in_its_box(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    got = editor.import_translation(p, "[p1.png #2]\nHELLO THERE\n")
    assert got["regions"] == 1 and got["pages"] == 1, got
    assert p.pages[1].regions[1]["dst_text"] == "HELLO THERE"


def test_it_overrides_what_the_box_says_now(tmp_path):
    """lee: *"translation json or txt should override current text"*. The
    file is not a set of suggestions for the empty boxes."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    p.pages[0].regions[0]["dst_text"] = "WHAT THE MACHINE SAID"
    editor.import_translation(p, "[p0.png #1]\nWHAT I SAY\n")
    assert p.pages[0].regions[0]["dst_text"] == "WHAT I SAY"


def test_a_block_left_empty_leaves_its_box_alone(tmp_path):
    """Half the file today and half tomorrow, without the untouched half
    wiping what is already there."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    p.pages[0].regions[1]["dst_text"] = "ALREADY DONE"
    editor.import_translation(p, "[p0.png #1]\nNEW\n\n[p0.png #2]\n\n")
    assert p.pages[0].regions[0]["dst_text"] == "NEW"
    assert p.pages[0].regions[1]["dst_text"] == "ALREADY DONE"


def test_two_lines_under_a_label_are_two_lines(tmp_path):
    """A break somebody put in by hand is a decision about the typesetting, and
    the typesetter honours it."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    editor.import_translation(p, "[p0.png #1]\nFIRST LINE\nSECOND LINE\n")
    assert p.pages[0].regions[0]["dst_text"] == "FIRST LINE\nSECOND LINE"


def test_the_comments_in_the_file_are_not_translations(tmp_path):
    """The template ships with instructions at the top. Reading them back in
    as dialogue would put the instructions on the page."""
    from mangatl import editor, manual
    p = _project(str(tmp_path / "t"))
    filled = manual.template(p).replace("[p0.png #1]  テスト1",
                                        "[p0.png #1]  テスト1\nSAID IT")
    editor.import_translation(p, filled)
    assert p.pages[0].regions[0]["dst_text"] == "SAID IT"
    for st in p.pages:
        for r in st.regions:
            assert "#" not in (r.get("dst_text") or "")


def test_the_round_trip_changes_nothing_by_itself(tmp_path):
    """Downloading the template and uploading it straight back is a no-op:
    every box gets exactly the words it already had."""
    from mangatl import editor, manual
    p = _project(str(tmp_path / "t"))
    p.pages[0].regions[0]["dst_text"] = "ONE"
    p.pages[1].regions[1]["dst_text"] = "TWO"
    editor.import_translation(p, manual.template(p))
    assert p.pages[0].regions[0]["dst_text"] == "ONE"
    assert p.pages[1].regions[1]["dst_text"] == "TWO"
    assert not (p.pages[0].regions[1].get("dst_text") or "")


def test_the_json_form_comes_back_too(tmp_path):
    from mangatl import editor, manual
    p = _project(str(tmp_path / "t"))
    d = manual.template_json(p)
    d["pages"][0]["boxes"][0]["english"] = "FROM JSON"
    editor.import_translation(p, json.dumps(d))
    assert p.pages[0].regions[0]["dst_text"] == "FROM JSON"


def test_a_flat_mapping_is_read_as_well(tmp_path):
    """What somebody writing the file by hand actually produces."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    editor.import_translation(p, json.dumps({"p0.png #2": "BY HAND"}))
    assert p.pages[0].regions[1]["dst_text"] == "BY HAND"


def test_a_label_that_matches_nothing_is_reported_not_swallowed(tmp_path):
    """A typed page name or a number off the end has to come back as a
    sentence, or the words vanish and the file looks like it worked."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    got = editor.import_translation(
        p, "[p0.png #1]\nFINE\n\n[nope.png #1]\nLOST\n\n[p0.png #9]\nALSO\n")
    assert got["regions"] == 1
    assert len(got["missing"]) == 2, got
    assert any("nope.png" in m for m in got["missing"])
    assert any("#9" in m or "box 9" in m for m in got["missing"])


def test_a_file_with_nothing_in_it_says_so(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    got = editor.import_translation(p, "# just the comments\n")
    assert got["regions"] == 0 and got.get("error")


# ------------------------------------------- what overriding throws away, and not

def test_new_words_throw_away_the_layout_of_the_old_ones(tmp_path):
    """The lines were broken to fit the words that were there. Keeping them
    typesets the new translation into the old shape."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    r = p.pages[0].regions[0]
    r["dst_text"] = "OLD"
    r["layout"] = {"lines": ["OLD"], "frame": [1, 2, 3, 4], "font_size": 20}
    editor.import_translation(p, "[p0.png #1]\nNEW\n")
    assert not r.get("layout")


def test_new_words_are_not_still_proofread(tmp_path):
    """The tick was given to the old wording."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    r = p.pages[0].regions[0]
    r["dst_text"], r["proofread"] = "OLD", True
    editor.import_translation(p, "[p0.png #1]\nNEW\n")
    assert not r.get("proofread")


def test_hand_typed_lines_in_the_override_go_but_the_styling_stays(tmp_path):
    """The `lines` in an override ARE the old wording, so they go with it. A
    font, a colour and a frame are choices about the box, and a new
    translation is no reason to undo them."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    r = p.pages[0].regions[0]
    r["dst_text"] = "OLD"
    r["layout_override"] = {"lines": ["OLD"], "wrap": 3,
                            "font": "CCWildWords.ttf", "colour": "#ff0000",
                            "frame": [10, 20, 30, 40]}
    editor.import_translation(p, "[p0.png #1]\nNEW\n")
    ov = r["layout_override"]
    assert "lines" not in ov and "wrap" not in ov
    assert ov["font"] == "CCWildWords.ttf"
    assert ov["colour"] == "#ff0000"
    assert ov["frame"] == [10, 20, 30, 40]


def test_a_box_lee_drew_himself_keeps_its_frame(tmp_path):
    """A text box has no detection behind it: the frame is the only record of
    where it is, so throwing the layout away outright would lose the box."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    r = p.pages[0].regions[0]
    r["own_text"] = True
    r["dst_text"] = "OLD"
    r["layout"] = {"lines": ["OLD"], "frame": [60, 50, 170, 110],
                   "font_size": 22}
    editor.import_translation(p, "[p0.png #1]\nNEW\n")
    assert (r.get("layout") or {}).get("frame") == [60, 50, 170, 110]
    assert not (r["layout"].get("lines") or [])


def test_the_words_are_tidied_the_same_way_the_panel_tidies_them(tmp_path):
    """Typing it in the text tab and uploading a file are two ways to the same
    box, so a curly quote pasted out of a document must not letter one way
    from the panel and another way from a file."""
    from mangatl import editor
    from mangatl.typeset import normalize_text
    p = _project(str(tmp_path / "t"))
    editor.import_translation(p, "[p0.png #1]\n“OH--REALLY?”\n")
    assert p.pages[0].regions[0]["dst_text"] == normalize_text("“OH--REALLY?”")


def test_the_re_typeset_afterwards_does_not_sweep_up_a_hand_drawn_box(tmp_path):
    """New words arriving re-typesets the page as a courtesy. Nobody pressed
    Typeset, so the reset that button carries must not come with it — a box
    lee drew himself is his, and a translation file is no reason to delete it.
    """
    from mangatl import editor
    p = _project(str(tmp_path / "t"), pages=1)
    p.pages[0].regions.append(
        _region(2, own_text=True, dst_text="MINE", src_text="",
                layout={"lines": ["MINE"], "frame": [60, 50, 170, 110]}))
    p.pages[0].regions[0]["dst_text"] = "SOMETHING"
    editor.do_typeset(p, 0, reset=False)
    mine = [r for r in p.pages[0].regions if r.get("own_text")]
    assert len(mine) == 1, p.pages[0].regions
    assert mine[0]["dst_text"] == "MINE"
    assert (mine[0].get("layout") or {}).get("frame") == [60, 50, 170, 110]


def test_and_the_import_asks_for_the_gentle_one(tmp_path, monkeypatch):
    """The whole way through, not just the flag: uploading a translation file
    onto a page with a hand-drawn box leaves the box there. The job that
    follows an import is run here on the spot so the test watches the same
    call the editor makes."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"), pages=1)
    p.pages[0].regions.append(
        _region(2, own_text=True, dst_text="MINE", src_text="",
                layout={"lines": ["MINE"], "frame": [60, 50, 170, 110]}))
    monkeypatch.setattr(editor, "run_job",
                        lambda proj, label, idxs, fn: [fn(i) for i in idxs])
    editor.import_translation(p, "[p0.png #1]\nNEW WORDS\n")
    mine = [r for r in p.pages[0].regions if r.get("own_text")]
    assert len(mine) == 1 and mine[0]["dst_text"] == "MINE", p.pages[0].regions


def test_pressing_typeset_still_sweeps_it_up(tmp_path):
    """The other half of the same rule, so `reset` is not quietly always off.
    lee: *"when i re typseet a page any custom chnages to text boxes or custom
    text box dshoud be removed"*."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"), pages=1)
    p.pages[0].regions.append(
        _region(2, own_text=True, dst_text="MINE", src_text="",
                layout={"lines": ["MINE"], "frame": [60, 50, 170, 110]}))
    p.pages[0].regions[0]["dst_text"] = "SOMETHING"
    editor.do_typeset(p, 0)
    assert not [r for r in p.pages[0].regions if r.get("own_text")]


def test_a_hand_drawn_box_survives_a_page_with_nothing_to_typeset(tmp_path):
    """The early return — no words anywhere, nothing to un-typeset — used to
    be a way out of the function that never put the boxes back."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"), pages=1)
    p.pages[0].regions.append(
        _region(2, own_text=True, dst_text="MINE", src_text="",
                layout={"lines": ["MINE"], "frame": [60, 50, 170, 110]}))
    editor.do_typeset(p, 0, reset=False)
    assert [r for r in p.pages[0].regions if r.get("own_text")]


# ----------------------------------------------------------------- over the wire

def test_the_template_is_served_as_a_file_to_keep(tmp_path):
    """Without a Content-Disposition the browser shows the template as a wall
    of text and the person has to save the page themselves."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    srv, base, was = _server(p)
    try:
        body, hdrs = _get(base, "/api/translation_template")
        assert "attachment" in (hdrs.get("Content-Disposition") or "")
        assert ".txt" in (hdrs.get("Content-Disposition") or "")
        assert "[p0.png #1]" in body
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_the_json_template_is_json(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    srv, base, was = _server(p)
    try:
        body, hdrs = _get(base, "/api/translation_template?fmt=json")
        d = json.loads(body)
        assert d["pages"][0]["page"] == "p0.png"
        assert ".json" in (hdrs.get("Content-Disposition") or "")
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_pages_narrows_the_template_over_the_wire(tmp_path):
    """1-based, because that is the number on the page strip."""
    from mangatl import editor
    p = _project(str(tmp_path / "t"), pages=3)
    srv, base, was = _server(p)
    try:
        body, _ = _get(base, "/api/translation_template?pages=2,3")
        assert "p0.png" not in body
        assert "p1.png" in body and "p2.png" in body
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_uploading_the_filled_in_file_answers_with_what_landed(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    srv, base, was = _server(p)
    try:
        j = _post(base, "/api/translation_import",
                  {"text": "[p0.png #1]\nOVER THE WIRE\n"})
        assert j["regions"] == 1 and j["pages"] == 1, j
        assert p.pages[0].regions[0]["dst_text"] == "OVER THE WIRE"
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_the_import_survives_being_reopened(tmp_path):
    """It is written to disk, not just into the running project."""
    from mangatl import editor
    from mangatl.project import Project
    root = str(tmp_path / "t")
    p = _project(root)
    editor.import_translation(p, "[p0.png #1]\nKEPT\n")
    again = Project(None, root)
    assert again.pages[0].regions[0]["dst_text"] == "KEPT"


# --------------------------------------------------------------- the mode itself

def test_a_project_does_not_start_in_manual_mode(tmp_path):
    from mangatl.project import Project
    p = Project(None, str(tmp_path / "t"))
    assert p.settings["manual_translate"] is False


def test_the_switch_is_saved_and_read_back(tmp_path):
    from mangatl import editor
    p = _project(str(tmp_path / "t"))
    srv, base, was = _server(p)
    try:
        _post(base, "/api/settings", {"settings": {"manual_translate": True}})
        assert p.settings["manual_translate"] is True
        j = _post(base, "/api/settings", {"settings": {}})
        assert j is not None
        with urllib.request.urlopen(base + "/api/project", timeout=30) as r:
            assert json.loads(r.read())["settings"]["manual_translate"] is True
    finally:
        editor.PROJECT = was
        srv.shutdown()


# ------------------------------------------------------------ on screen

_STEPS = """[...document.querySelectorAll('#steps .step')].map(b=>({
    label: b.querySelector('.sl').textContent,
    off: b.classList.contains('off')}))"""


def _screen(fn, manual_on):
    from mangatl import editor
    root = scratch("_tmp_manual")
    p = _project(root)
    p.settings["manual_translate"] = manual_on
    p.save()
    srv, base, was = _server(p)
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.skipif(not browserpool.available(), reason="chromium unavailable")
def test_the_three_model_steps_go_grey_in_manual_mode():
    """lee: *"the manual tranlat button should grey out the read text
    translate and profread"*. Those three and no others — Find text is not a
    model, Clean, Typeset and Export are not translations."""
    def check(pg, p):
        got = pg.evaluate(_STEPS)
        grey = [s["label"] for s in got if s["off"]]
        assert grey == ["Read text", "Translate", "Proofread"], got
    _screen(check, True)


@pytest.mark.skipif(not browserpool.available(), reason="chromium unavailable")
def test_with_the_switch_off_every_step_is_live():
    def check(pg, p):
        got = pg.evaluate(_STEPS)
        assert not [s["label"] for s in got if s["off"]], got
    _screen(check, False)


@pytest.mark.skipif(not browserpool.available(), reason="chromium unavailable")
def test_pressing_a_greyed_step_does_nothing():
    """Grey that still opens the dialog is a lie about what the button does."""
    def check(pg, p):
        pg.evaluate("runStep(2)")            # Translate
        browserpool.settled(pg)
        assert not pg.evaluate(
            "document.getElementById('scopedlg').classList.contains('on')")
    _screen(check, True)


@pytest.mark.skipif(not browserpool.available(), reason="chromium unavailable")
def test_turning_it_off_gives_the_three_straight_back():
    """A MODE, not a lock: nothing has to happen first for these to work
    again — that is the whole difference from the step gates lee had
    removed."""
    def check(pg, p):
        pg.evaluate("""() => { proj.settings.manual_translate = false;
                               document.getElementById('manual_translate')
                                 .checked = false;
                               syncManualMode(); }""")
        browserpool.settled(pg)
        got = pg.evaluate(_STEPS)
        assert not [s["label"] for s in got if s["off"]], got
        pg.evaluate("runStep(2)")
        browserpool.settled(pg)
        assert pg.evaluate(
            "document.getElementById('scopedlg').classList.contains('on')")
    _screen(check, True)


@pytest.mark.skipif(not browserpool.available(), reason="chromium unavailable")
def test_the_template_buttons_are_only_there_in_manual_mode():
    """The row is how you work in that mode; in the other one it is clutter
    in a settings pane that is long enough already."""
    def on(pg, p):
        assert pg.evaluate(
            "getComputedStyle(document.getElementById('manrow')).display")\
            != "none"
    def off(pg, p):
        assert pg.evaluate(
            "getComputedStyle(document.getElementById('manrow')).display")\
            == "none"
    _screen(on, True)
    _screen(off, False)


def test_the_switch_lives_beside_the_text_it_is_about():
    """lee: *"move teh ill translate myselt to the translation tab"*.

    It spent a while in Settings ▸ Translation engine, which is where you go
    to decide a thing once — not where you go to DO it. Typing a chapter in by
    hand happens against the text list, and that is where the switch and its
    template buttons are now.
    """
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    side = html.split('<div id="side">', 1)[1].split("<!-- /#side -->", 1)[0]
    for want in ('id="manual_translate"', 'id="manrow"',
                 "downloadManualTemplate", "uploadManualTranslation"):
        assert want in side, want
    # ...and it is above the list it is about, not below it.
    assert side.index('id="manual_translate"') < side.index('id="listHead"')
    # ...and it is not left behind in Settings as well. Two switches for one
    # setting is two places for them to disagree about which is on.
    settings = html.split('<div id="settingsPage"', 1)[1]
    assert 'id="manual_translate"' not in settings
