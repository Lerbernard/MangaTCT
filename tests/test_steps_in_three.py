"""The seven steps are three pieces of work, and none of them is locked.

lee: *"this shoud be split into 3 section text for the fist 4, image or panel
fro teh next 2 and exort, the fisrt 4 shoude be liniar with the next one
disable until the first one is doen so not read text until find text is done
etc, for teh next section cleanning shoud be open and typesettting shoud be
locked untill translation iand cleanin is doen and expost shoud have nothing"*.

The GROUPS are what survived that, and they are the half worth keeping: the
seven are the words, the picture, and writing it out, and the bar says which
of the three you are in the middle of.

**The locks are gone.** They went away once - *"allow the user to clcik all
the button like clean translate without any locks"* - came back on the next
word - *"accualty bring ba k the locks for the 1-6 tabs but kepp the lock offf
the edit tab"* - and are now gone for good: *"remove the loacks on all the
tabs"*.

What they encoded is still true. You cannot read text that has not been found;
typesetting onto Japanese that is still there sits on top of it. It is lee's
chapter and his order of work, and the bar still SAYS where everything is - a
count on every button and a fill under it. It just does not decide what he may
press. A step run out of turn does what it always did: nothing, over nothing,
and says so.
"""
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")


def _bubble(img, cx, cy):
    cv2.ellipse(img, (cx, cy), (95, 62), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (cx, cy), (95, 62), 0, 0, 360, (25, 25, 25), 3)


def _serve(fn, root=scratch("_tmp_steps"), pages=3, mark=None):
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 420, 3), 245, np.uint8)
    _bubble(img, 200, 200)
    for k in range(pages):
        p.add_uploaded(f"p{k}.png", cv2.imencode(".png", img)[1].tobytes())
    if mark:
        mark(p)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('edit')")
            browserpool.settled(pg)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


_LOCKS = """[...document.querySelectorAll('#steps .step')].map(b=>({
    label: b.querySelector('.sl').textContent,
    locked: b.classList.contains('locked')}))"""


def _region(k, **extra):
    r = {"id": k + 1, "kind": "bubble", "order": k,
         "bbox": [110, 140, 180, 120],
         "bubble_bbox": [105, 138, 190, 124],
         "polygon": [[110, 140], [290, 140], [290, 260], [110, 260]],
         "confidence": 0.9}
    r.update(extra)
    return r


def _detected(p, **extra):
    for st in p.pages:
        st.regions = [_region(0, **extra)]
        st.detected = True


# ------------------------------------------------------------ three groups

def test_the_steps_are_in_three_named_groups():
    def check(pg, p):
        got = pg.evaluate("""[...document.querySelectorAll('#steps .stepgrp')]
            .map(g=>({name: g.querySelector('.sgl').textContent,
                      steps: [...g.querySelectorAll('.step')]
                               .map(b=>b.querySelector('.sl').textContent)}))""")
        # "Text" named the thing on the page rather than the work these four
        # steps do. lee: *"chnage the text on screenshot 4 to say
        # translation"*.
        assert [g["name"] for g in got] == ["Translation", "Image",
                                            "Export"], got
        assert got[0]["steps"] == ["Find text", "Read text", "Translate",
                                   "Proofread"], got
        assert got[1]["steps"] == ["Clean", "Typeset"], got
        assert got[2]["steps"] == ["Export"], got
    _serve(check)


def test_no_step_is_left_out_of_a_group():
    """Seven steps, three groups. A step in none of them would simply not be
    drawn any more."""
    def check(pg, p):
        n = pg.evaluate(
            "document.querySelectorAll('#steps .stepgrp .step').length")
        assert n == pg.evaluate("STEPS.length"), n
    _serve(check)


# ------------------------------------------------------- nothing is locked

def test_nothing_is_locked_on_a_fresh_chapter():
    """Not one of the seven, with nothing done to the chapter at all - which
    is the state every lock used to be visible in."""
    def check(pg, p):
        got = pg.evaluate(_LOCKS)
        assert [g["locked"] for g in got] == [False] * 7, got
        assert len(got) == 7, got
    _serve(check)


def test_nor_at_any_point_in_between():
    """The three states the locks used to distinguish: boxes found, Japanese
    read, English written. Every one of the seven is open in all of them."""
    for mark in (_detected,
                 lambda p: _detected(p, src_text="テスト"),
                 lambda p: _detected(p, src_text="テスト", dst_text="HELLO")):
        def check(pg, p):
            got = pg.evaluate(_LOCKS)
            assert not any(g["locked"] for g in got), got
        _serve(check, mark=mark)


def test_a_step_out_of_turn_runs():
    """Typeset before anything is cleaned, on a chapter with nothing read.
    The point is that it is not stopped - what it then does is its own
    business, and it is the same nothing it always did."""
    def check(pg, p):
        pg.evaluate("window._ran=[]; "
                    "STEPS.forEach((s,i)=>{s.act=()=>window._ran.push(i);});"
                    "renderSteps()")
        browserpool.settled(pg)
        for i in range(7):
            pg.evaluate(f"document.querySelectorAll('#steps .step')[{i}]"
                        ".click()")
        pg.wait_for_timeout(300)
        assert pg.evaluate("window._ran") == list(range(7)), \
            pg.evaluate("window._ran")
    _serve(check)


def test_no_step_says_it_cannot_be_pressed():
    """The `aria-disabled` and the reason in the tooltip went with the lock.
    Left behind they would tell a screen reader the opposite of the truth."""
    def check(pg, p):
        got = pg.evaluate("""[...document.querySelectorAll('#steps .step')]
            .map(b=>({dis:b.disabled, aria:b.getAttribute('aria-disabled'),
                      title:b.getAttribute('title')||''}))""")
        assert not any(g["dis"] for g in got), got
        assert not any(g["aria"] == "true" for g in got), got
        assert not any(g["title"] for g in got), got
    _serve(check)


def test_the_bar_still_says_where_the_chapter_is():
    """Unlocked is not unsaid. Every button carries its own count, and the
    fill under it is that count - which is the whole of what the step bar is
    for now."""
    def check(pg, p):
        got = pg.evaluate("""[...document.querySelectorAll('#steps .step')]
            .map(b=>({c:b.querySelector('.sc').textContent,
                      fill:b.querySelector('.sfill').style.width}))""")
        assert [g["c"] for g in got] == ["3/3"] + ["0/3"] * 6, got
        assert got[0]["fill"] == "100%" and got[1]["fill"] == "0%", got
    _serve(check, mark=_detected)


def test_one_page_short_is_still_one_page_short():
    """The count is over the pages a "do all" run would touch, and it is the
    thing that survived the lock: three read out of four is a step in
    progress, and the bar has to say so."""
    def mark(p):
        _detected(p, src_text="テスト")
        p.pages[-1].regions[0].pop("src_text")

    def check(pg, p):
        got = pg.evaluate("""[...document.querySelectorAll('#steps .step')]
            .map(b=>b.querySelector('.sc').textContent)""")
        assert got[1] == "2/3", got
    _serve(check, mark=mark)


def test_nothing_is_left_over_from_the_locks():
    """A stylesheet that still greys `.step.locked`, or a `stepLocked` nobody
    calls, is a rule waiting for a state that cannot happen - and the next
    person to read either one will believe the locks are still there. The
    same standard the rows were held to when their colour went."""
    from pathlib import Path
    root = PKG / "static"
    css = (root / "css" / "editor.css").read_text(encoding="utf-8")
    js = (root / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert ".step.locked" not in css
    assert "stepLocked" not in js
    assert "aria-disabled" not in js


def test_the_edit_view_opens_on_a_page_that_was_never_cleaned():
    """It paints on the scan instead of the cleaned plate, which is a thing to
    look at rather than a thing to be stopped from doing.
    lee: *"kepp the lock offf the edit tab"*."""
    def check(pg, p):
        assert pg.evaluate("!!pageReady(proj.pages[0])") is True
        got = pg.evaluate("""(()=>{const b=document.getElementById('vTypeset');
            return [b.disabled, b.classList.contains('locked')];})()""")
        assert got == [False, False], got
        pg.evaluate("setView('typeset')")
        browserpool.settled(pg)
        assert pg.evaluate("view") == "typeset", pg.evaluate("view")
    _serve(check)


# ------------------------------------------------- every step takes the press

def test_a_step_runs_what_it_is_for():
    """Which is now the whole of what pressing one does."""
    def check(pg, p):
        pg.evaluate("window._ran=[]; "
                    "STEPS.forEach((s,i)=>{s.act=()=>window._ran.push(i);});"
                    "renderSteps()")
        pg.wait_for_timeout(200)
        pg.evaluate("runStep(0)")
        pg.wait_for_timeout(200)
        assert pg.evaluate("window._ran") == [0]
    _serve(check)


# ------------------------------------------------------------ L links two

def test_l_arms_the_link_and_the_next_box_joins_it():
    """lee: *"if i lcik l while a box is selected ted it shoud start thelink
    thing and i shoud be able to click another box to linkthem"*.

    Linking is a two-box job and the button for it is in the sidebar, so it
    took a reach for the mouse, a click, and then the second box. The key does
    the first two."""
    def mark(p):
        for st in p.pages:
            st.regions = [_region(k, src_text="テスト") for k in range(2)]
            st.detected = True

    def check(pg, p):
        # setView kicks off a page refresh, and a refresh landing after a
        # select clears it - so let it settle first.
        pg.evaluate("setView('original')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(400)
        pg.keyboard.press("l")
        pg.wait_for_timeout(300)
        assert pg.evaluate("linkPick") == 1
        assert pg.evaluate("""(()=>{const b=document.getElementById('linkbanner');
            return !!b && b.style.display!=='none';})()"""), "no sign of it"
        pg.evaluate("select(2)")
        pg.wait_for_timeout(900)
        got = pg.evaluate("regions.map(r=>r.link)")
        assert got[0] and got[0] == got[1], got
        assert pg.evaluate("linkPick") == None
    _serve(check, mark=mark)


def test_l_with_nothing_selected_does_nothing():
    def check(pg, p):
        pg.evaluate("setView('original')")
        browserpool.settled(pg)
        pg.evaluate("sel=null; drawBoxes()")
        pg.wait_for_timeout(300)
        pg.keyboard.press("l")
        pg.wait_for_timeout(300)
        assert pg.evaluate("linkPick") == None
    _serve(check)


def test_escape_gives_up_on_the_link():
    def mark(p):
        for st in p.pages:
            st.regions = [_region(k) for k in range(2)]
            st.detected = True

    def check(pg, p):
        pg.evaluate("setView('original')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(400)
        pg.keyboard.press("l")
        pg.wait_for_timeout(300)
        assert pg.evaluate("linkPick") == 1
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        assert pg.evaluate("linkPick") == None
        assert pg.evaluate("regions.every(r=>!r.link)")
    _serve(check, mark=mark)


def test_typing_an_l_in_a_text_box_is_just_an_l():
    """The English of a bubble is full of them."""
    def mark(p):
        for st in p.pages:
            st.regions = [_region(k, src_text="テスト") for k in range(2)]
            st.detected = True

    def check(pg, p):
        pg.evaluate("setView('original')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(600)
        box = pg.query_selector("#side textarea")
        assert box is not None, "no text box to type in"
        box.click()
        pg.keyboard.type("hello")
        pg.wait_for_timeout(300)
        assert pg.evaluate("linkPick") == None
        assert "hello" in pg.evaluate(
            "document.querySelector('#side textarea').value")
    _serve(check, mark=mark)
