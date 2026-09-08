# -*- coding: utf-8 -*-
"""A well that shows a colour is not the same as somebody choosing one.

lee: *"when changing the outerglow number, the outline color also switches"*.

## What the outer glow had to do with the outline

Nothing, which is the point.

`_ink_colours` decides which way round a block goes by reading the artwork
under it: white letters with a black edge on dark, black with white on light,
and it hands back a PAIR. Most blocks on a page never have either colour
chosen; they are worked out afresh on every render, which is how a block that
is dragged onto a black panel stops being black letters.

`layout_preview` reported that pair as `fg` and `edge` - correctly, because the
browser draws its own preview and needs the colours the page will come out in.
The browser put them into `r.style`, and the side panel built its two colour
wells from `r.style`. And a well is not a readout: **what is standing in it is
what the next save sends.**

So every save of every unrelated field - the outer glow's size, the line
spacing, a nudge of the rotation - wrote the automatic pair into
`layout_override` as though somebody had picked it. From that moment
`_ink_colours` was not consulted about that block again, and `colours_for`'s
rule for an edge nobody set stopped applying. The outline lee saw switch is the
one the page had been about to work out for itself.

The same trap had already been found on the FILL well and half-fixed there:
`lyFill`'s comment says it in as many words - *"The well is not only a readout,
it is the control: what it shows is what a save writes back, so a colour
standing in it quietly filled the block in on the next save of anything else on
the panel."* That fix made the well show the right thing. It did not stop the
well being sent.

## The fix

`layout_preview` answers with **both**: `fg`/`edge`, the pair the page is drawn
in, and `fg_set`/`edge_set`, the pair somebody chose - empty when nobody did.
Every other colour on that answer already reports the override rather than the
result; these two could not, because the preview needs a colour to draw with.

The well then shows the drawn colour, which is honest, and carries `data-auto`
when nothing was chosen. `wellNow` sends the empty string for such a well, and
`str(lay.get("fg") or "")` in the override builder is already the server's
spelling of *nobody chose one*. Picking a colour clears the flag.

**Level one only.** `fg_set` reads the override and not `style_of`, for the
same reason `hand_style` reads level one alone: `inkstyle` measures the
original ink into `layout_measured`, and a measurement is a finding about the
artwork rather than a choice. Promoting one to a hand edit would pin it against
every later re-reading - which is the bug being fixed, one level down.
"""
import json
import os
import re
import threading
import time
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")


def js(name):
    with open(os.path.join(str(PKG), "static", "js", name),
              encoding="utf-8") as f:
        return f.read()


def code_only(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.M)


# ------------------------------------------------- the answer says both

def _mini(root):
    from mangatl.project import Project
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((400, 400, 3), 245, np.uint8)
    cv2.ellipse(img, (200, 200), (120, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (200, 200), (120, 90), 0, 0, 360, (25, 25, 25), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [140, 165, 120, 70],
        "bubble_bbox": [90, 120, 220, 160],
        "polygon": [[140, 165], [260, 165], [260, 235], [140, 235]],
        "src_text": "テスト", "dst_text": "HELLO THERE", "confidence": 0.9}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    return p


def test_the_answer_separates_what_is_drawn_from_what_was_chosen(tmp_path):
    from mangatl import editor
    p = _mini(str(tmp_path / "a"))
    ans = editor.layout_preview(p, 0, 1, {})
    assert ans.get("fg"), ans.get("error")
    assert ans.get("edge")
    # Nobody chose either.
    assert ans["fg_set"] == "", ans["fg_set"]
    assert ans["edge_set"] == "", ans["edge_set"]


def test_a_colour_that_was_chosen_comes_back_as_chosen(tmp_path):
    from mangatl import editor
    p = _mini(str(tmp_path / "b"))
    ans = editor.layout_preview(p, 0, 1, {"edge": "#ff0000"})
    assert ans["edge_set"] == "#ff0000", ans["edge_set"]
    assert ans["fg_set"] == "", ans["fg_set"]
    # ...and it is the colour the page comes out in, too. `fg`/`edge` are
    # `rgba()` rather than hex, because a hollow letterform has no fill and CSS
    # needs to be told so in a colour rather than in a flag.
    assert ans["edge"].replace(" ", "").startswith("rgba(255,0,0"), ans["edge"]


def test_a_measured_ink_is_a_finding_and_not_a_choice(tmp_path):
    """`inkstyle` writes what it read off the artwork into `layout_measured`.
    That belongs on the page - `colours_for` reads it through `style_of` - and
    it must not be promoted to a hand edit by somebody nudging a number."""
    from mangatl import editor
    p = _mini(str(tmp_path / "c"))
    p.pages[0].regions[0]["layout_measured"] = {"fg": "#020202",
                                                "edge": "#ffffff"}
    ans = editor.layout_preview(p, 0, 1, {})
    assert ans["fg_set"] == "", ans["fg_set"]
    assert ans["edge_set"] == "", ans["edge_set"]


def test_nonsense_in_the_override_is_not_a_choice_either(tmp_path):
    from mangatl import editor
    p = _mini(str(tmp_path / "d"))
    for junk in ("", "   ", "red", "#12", None):
        ans = editor.layout_preview(p, 0, 1, {"edge": junk})
        assert ans["edge_set"] == "", (junk, ans["edge_set"])


# ------------------------------------------------- and the browser sends it

def test_the_wells_are_sent_through_the_gate():
    src = code_only(js("typesetting-edit.js"))
    assert "function wellNow(" in src
    m = re.search(r"function wellNow\(id\)\{(.*?)\n\}", src, flags=re.S)
    assert m and "dataset" in m.group(1) and "auto" in m.group(1), m
    # ...and the second test, which does not depend on anybody remembering to
    # clear a flag: a well holding something other than what the page put in it
    # has been set, whoever set it.
    assert "was" in m.group(1), m.group(1)
    assert "data-was" in code_only(js("panels.js"))
    # `currentPatch` is what a save is built from, and both wells go through it.
    #
    # Cut at the next top-level function and not at the first `\n}`: the patch
    # builder holds an arrow function of its own now (`pv`, the gate that
    # stops a field DISPLAYING a range's value from being saved as the
    # block's), and splitting on a closing brace stopped at that instead.
    patch = src.split("function currentPatch(r){")[1].split("\nfunction ")[0]
    flat = patch.replace(" ", "")
    # Through `wellNow`, whatever wraps it - what matters is that neither
    # colour is read straight off the input.
    for key, well in (("fg", "lyFg"), ("edge", "lyEdge")):
        assert ("%s:el('%s')?" % (key, well)) in flat, (key, patch)
        assert ("wellNow('%s')" % well) in flat, (key, patch)


def test_a_well_that_nobody_chose_is_marked_as_such():
    src = code_only(js("panels.js"))
    assert "function wellChosen(" in src
    body = src.split("function wellBits(id, value, dflt, editable, auto){")[1] \
              .split("\n}")[0]
    assert "data-auto" in body, body
    # Both wells ask the question, and neither invents its own answer.
    assert src.count("wellChosen(r,ov,'fg')") == 1, src.count(
        "wellChosen(r,ov,'fg')")
    assert src.count("wellChosen(r,ov,'edge')") == 1


def test_picking_a_colour_takes_the_mark_off():
    src = code_only(js("typesetting-edit.js"))
    body = src.split("function openTypesetPicker(anchor, fid, rid){")[1] \
              .split("\n}")[0]
    assert "removeAttribute('data-auto')" in body.replace('"', "'"), body


def test_the_chosen_pair_travels_with_the_drawn_pair():
    """`livePreview` is what fills `r.style`, and the panel is built from it.
    Without `fg_set` there a colour just picked comes back marked automatic on
    the very next rebuild and is dropped by the save after it."""
    src = code_only(js("typesetting-edit.js"))
    assert "fg_set:j.fg_set" in src.replace(" ", "")
    assert "edge_set:j.edge_set" in src.replace(" ", "")
    assert "fg_set:$('lyFg')?wellNow('lyFg')" in src.replace(" ", "")
    assert "edge_set:$('lyEdge')?wellNow('lyEdge')" in src.replace(" ", "")


# ------------------------------------------------- end to end, in a browser

def _project(root):
    from mangatl.project import Project
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((900, 700, 3), 245, np.uint8)
    cv2.ellipse(img, (220, 220), (110, 80), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (220, 220), (110, 80), 0, 0, 360, (25, 25, 25), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0,
        "bbox": [150, 180, 140, 80],
        "bubble_bbox": [110, 140, 220, 160],
        "polygon": [[150, 180], [290, 180], [290, 260], [150, 260]],
        "src_text": "テスト", "dst_text": "HELLO THERE", "confidence": 0.9,
        "layout": {"lines": ["HELLO", "THERE"], "font_size": 18,
                   "leading": 1.1,
                   "origins": [[220, 205], [220, 228]],
                   "fg": "#000000", "edge": "#ffffff", "stroke": 1,
                   "font": "", "rotate": 0.0, "frame": [], "fixed": False,
                   "fit_ok": True, "used_compact": False}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    p.pages[0].typeset = True
    return p


def _panel(fn, root=scratch("_tmp_chose")):
    from mangatl import editor
    p = _project(root)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 1200})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit'); setView('typeset'); showPage(0)")
            browserpool.settled(pg)
            pg.evaluate("select(1)")
            pg.wait_for_timeout(800)
            assert not errs, errs
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()


def _saved(pg, timeout=180000):
    """Wait until the app says it has finished saving, then look.

    Not a stopwatch: a save re-lays the block out and rebuilds the page, and in
    a full run that can take tens of seconds. The browser knows exactly -
    nothing dirty, and no lane of `saveTypesetting._q` still holding a request.

    Waiting for this BEFORE the next edit matters as much as after: a save's
    reply rebuilds the panel, and a rebuild replaces the very field the next
    step is about to type into.
    """
    pg.wait_for_function(
        "()=>(typeof typesetDirty==='undefined'||typesetDirty===null)"
        "&&!(saveTypesetting._q&&Object.keys(saveTypesetting._q).length)",
        timeout=timeout)


def _nudge_glow(pg, p, by=3):
    """Change a field that has nothing to do with either colour."""
    _saved(pg)
    want = pg.evaluate("+document.getElementById('lyGlowS').value") + by
    pg.evaluate("""(n)=>{const e=document.getElementById('lyGlowS');
        e.value=String(n);
        e.dispatchEvent(new Event('input',{bubbles:true}));}""", want)
    _saved(pg)
    ov = p.pages[0].regions[0].get("layout_override") or {}
    assert float(ov.get("glow_size") or 0) == float(want), \
        ("the glow size never reached the server", ov.get("glow_size"), want)
    return want


def test_touching_another_field_does_not_freeze_the_colours():
    """The bug, end to end and in one line: nudge the outer glow, and the two
    colours must be exactly as un-chosen afterwards as they were before."""
    def check(pg, p):
        ov = p.pages[0].regions[0].get("layout_override") or {}
        assert not ov.get("edge"), ov
        assert not ov.get("fg"), ov
        _nudge_glow(pg, p)
        ov = p.pages[0].regions[0].get("layout_override") or {}
        assert not ov.get("edge"), ("the outline was written down", ov)
        assert not ov.get("fg"), ("the fill was written down", ov)
    _panel(check)


def test_a_colour_you_actually_pick_is_kept():
    """...and the fix must not be "never save a colour". Picked through the
    real picker, off the well itself, the way somebody would."""
    def check(pg, p):
        pg.click("span.colwell:has(#lyEdge)")
        pg.wait_for_timeout(200)
        pg.click("#pkSw i[title='#2b2b2b']")
        _saved(pg)
        ov = p.pages[0].regions[0].get("layout_override") or {}
        assert (ov.get("edge") or "").lower() == "#2b2b2b", ov
        # ...and it survives the very save that used to invent one.
        _nudge_glow(pg, p)
        ov = p.pages[0].regions[0].get("layout_override") or {}
        assert (ov.get("edge") or "").lower() == "#2b2b2b", \
            ("a chosen colour was dropped", ov)
        assert not ov.get("fg"), ("...and the OTHER well was still sent", ov)
    _panel(check)
