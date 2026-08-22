"""lee, with four screenshots, on the round after the round.

* *"only these should be default"* - a picture of the Box types list he wants.
* *"this shoud only show the 3 main type"* - the legend over the page had a
  chip for every sub-type as well.
* *"the side bar shoud only be visible on the edit tab"*
* *"the text still revert to the last state when i remove all the text"*
* *"remove teh move a shape tool its redundent"*
* *"make teh double clciking the hand too amek teh zoom 100%"*
* *"istaed of 1 green bubble it onteh last screenshot it sbhoud be 4 for the
  origibla page and 2 for the edit age one for each step"*
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root, pages=2, text="HELLO THERE"):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    for k in range(pages):
        p.add_uploaded("p%d.png" % k, cv2.imencode(".png", img)[1].tobytes())
    for k in range(pages):
        p.pages[k].regions = [{
            "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
            "bubble_bbox": [110, 100, 280, 160],
            "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
            "confidence": 0.9, "src_text": "テスト", "dst_text": text}]
        p.pages[k].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "third"))
    editor.do_typeset(p, 0)          # page 1 typeset, page 2 not
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip('chromium unavailable')
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1500, "height": 950})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit')")
        browserpool.settled(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


# ------------------------------------------------------ one dot per step

def _dots(pg):
    return pg.evaluate("""[...document.querySelectorAll('#pages .pg')]
        .map(r=>[r.querySelectorAll('.dots .dot').length,
                 r.querySelectorAll('.dots .dot.done').length])""")


def test_the_original_view_has_a_dot_for_each_of_the_four_word_steps(ed):
    """One dot said "something has happened to this page" and nothing else, so
    a page that had been read but not translated looked exactly like a page
    that was finished."""
    pg, _p, errs = ed
    pg.evaluate("setView('original')")
    browserpool.settled(pg)
    got = _dots(pg)
    assert got and all(n == 4 for n, _d in got), got
    assert not errs, errs[:2]


def test_the_edit_view_has_a_dot_for_each_of_the_two_picture_steps(ed):
    pg, _p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    got = _dots(pg)
    assert got and all(n == 2 for n, _d in got), got
    assert not errs, errs[:2]


def test_a_dot_is_filled_only_when_that_page_has_had_that_step(ed):
    """Page one was cleaned and typeset in the fixture and page two was not,
    so the two rows must not look the same."""
    pg, _p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    got = _dots(pg)
    assert got[0] == [2, 2], got
    assert got[1] == [2, 0], got
    assert not errs, errs[:2]


def test_the_step_bar_still_counts_the_same_pages(ed):
    """The bar and the dots are one rule asked twice - the bar reads the same
    per-page answer the dots draw, so they cannot drift apart."""
    pg, _p, errs = ed
    same = pg.evaluate("""(()=>{
        const P=proj.pages;
        const bar=stepProgress();
        for(let i=0;i<6;i++){
          const mine=P.filter(p=>pageDoneStep(p,i)).length;
          if(bar[i].done!==mine) return [i, bar[i].done, mine];
        }
        return true;})()""")
    assert same is True, same
    assert not errs, errs[:2]


# ------------------------------------------------------------- the legend

def test_the_legend_is_the_three_main_types(ed):
    """lee: *"this shoud only show the 3 main type"*. A chip for every
    sub-type made a paragraph of colour above the page longer than anything it
    explained, and the shade of a box already says which family it is in."""
    pg, _p, errs = ed
    pg.evaluate("setView('original')")
    browserpool.settled(pg)
    chips = pg.evaluate(
        "[...document.querySelectorAll('#legend > *')].map(s=>s.textContent.trim())")
    # The three main types are BUTTONS now - see
    # `tests/ui/the_legend_draws_the_box.test.js`. Still the same words,
    # with the select-boxes tool on the end of the row.
    assert chips == ["1 Bubble text", "2 Freefloat text", "3 Sound effect",
                     "unsure", "Select boxes"], chips
    assert not errs, errs[:2]


# ------------------------------------------------------------ the toolbox

def test_the_tool_strip_is_only_up_on_the_edit_view(ed):
    """lee: *"the side bar shoud only be visible on the edit tab"*. The paint
    canvas is not even mounted on the Original view, so every tool in the
    strip was a button that could be pressed and could not do anything."""
    pg, _p, errs = ed
    show = "getComputedStyle(document.getElementById('toolbox')).display"
    pg.evaluate("setView('original')")
    browserpool.settled(pg)
    assert pg.evaluate(show) == "none"
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    assert pg.evaluate(show) != "none"
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)
    assert pg.evaluate(show) == "none"
    assert not errs, errs[:2]


def test_the_move_a_shape_tool_is_gone_and_nothing_went_with_it(ed):
    """lee: *"remove teh move a shape tool its redundent"*. Clicking a shape
    picks it up now, so a tool whose whole job was to make that click work is
    a tool that asks you to arm something before you may point at what you can
    already see. The arrow itself stays - V, and the page click."""
    pg, _p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    keys = pg.evaluate("TOOLBOX.find(g=>g.slot==='shape').tools.map(t=>t.k)")
    assert keys == ["shrect", "shcirc", "shline"], keys
    assert pg.evaluate("typeof toggleShapeEdit") == "function"
    pg.evaluate("toggleShapeEdit(true)")
    pg.wait_for_timeout(300)
    assert pg.evaluate("shapeEdit") is True
    pg.evaluate("toggleShapeEdit(false)")
    assert not errs, errs[:2]


def test_double_clicking_the_hand_goes_to_actual_size(ed):
    """100% means one page pixel to one screen pixel.

    It used to call `fitPage`, and the readout used to call the fit "100%", so
    on a page already fitted the double-click changed nothing but the scroll
    position. lee: *"double clciking teh hadns dosnt change teh zoom it jyst
    centers it"* - it did exactly what the readout said, which was the
    problem."""
    pg, _p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    # A window SMALLER than the page, so the fit and actual size are two
    # different numbers. On a pane big enough to hold the page at 1:1 they are
    # the same, and a test run there cannot tell the two apart at all.
    pg.set_viewport_size({"width": 760, "height": 460})
    pg.wait_for_timeout(700)
    pg.evaluate("fitPage()")
    pg.wait_for_timeout(500)
    assert pg.evaluate("fitZoom") < 0.9, pg.evaluate("fitZoom")
    b = pg.evaluate("""(()=>{const r=document.querySelector(
        '.tbtn[data-slot=view]').getBoundingClientRect();
        return {x:r.left+r.width/2, y:r.top+r.height/2};})()""")

    for step in (1 / 1.25, 1.25):          # from below, and from above
        pg.evaluate("fitPage()")
        pg.wait_for_timeout(400)
        for _ in range(3):
            pg.evaluate(f"zoomBy({step})")
        pg.wait_for_timeout(400)
        away = pg.evaluate("scale")
        assert abs(away - 1) > 0.1, away
        assert pg.evaluate(
            "document.getElementById('zlabel').textContent") != "100%"
        pg.mouse.dblclick(b["x"], b["y"])
        pg.wait_for_timeout(900)
        now = pg.evaluate("scale")
        assert abs(now - 1) < 0.02, (away, now)
        assert pg.evaluate(
            "document.getElementById('zlabel').textContent") == "100%"
        assert pg.evaluate("handMode") is True, "it put the hand back down"
    assert not errs, errs[:2]


# ------------------------------------------- deleting the words, for good

def test_emptying_the_box_empties_the_words(ed):
    """lee: *"the text still revert to the last state when i remove all the
    text"*. The typesetting went and the sentence stayed, so the next Typeset -
    which throws hand corrections away on purpose and fits from `dst_text` -
    put the old typesetting straight back."""
    pg, p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(700)
    pg.evaluate("""(()=>{const t=document.getElementById('lyLines');
        t.value=''; t.dispatchEvent(new Event('input',{bubbles:true}));
        flushTypesetEdit();})()""")
    pg.wait_for_timeout(2000)
    assert pg.evaluate("(regions.find(r=>r.id===1).layout||{}).lines") == []
    assert (p.pages[0].regions[0].get("dst_text") or "") == "", \
        "the sentence is still there to be laid out again"
    assert not errs, errs[:2]


def test_it_is_still_empty_after_typeset(ed):
    from mangatl import editor
    pg, p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(700)
    was = pg.evaluate("regions.find(r=>r.id===1).layout.frame")
    pg.evaluate("""(()=>{const t=document.getElementById('lyLines');
        t.value=''; t.dispatchEvent(new Event('input',{bubbles:true}));
        flushTypesetEdit();})()""")
    pg.wait_for_timeout(2000)
    # the box keeps the frame it was left at, on screen and not just on disk
    assert pg.evaluate("regions.find(r=>r.id===1).layout.frame") == was, \
        "it snapped back to its box the moment the last character went"
    editor.do_typeset(p, 0)
    lay = p.pages[0].regions[0]["layout"]
    assert lay["lines"] == [], lay["lines"]
    assert lay["frame"] == was, (lay["frame"], was)
    assert not errs, errs[:2]


# --------------------------------------------------- what you start with

def test_the_preloaded_list_is_the_one_in_the_picture():
    """lee: *"only these should be default"*. Four under Bubble text, three
    under Outside text, two under Sound effect. A preload is a starting point,
    not a catalogue - every one is a row somebody reads past before reaching
    their own, and a shout, a yell and an angry line are one kind of typesetting
    asked for three times."""
    from mangatl import kinds as K
    assert [lb for _k, lb in K.PRELOADED["bubble"]] == [
        "Caption box", "Thought bubble", "Burst / shout", "Whisper"]
    assert [lb for _k, lb in K.PRELOADED["freefloat"]] == [
        "Narration on the art", "Aside / mutter", "Sign or label"]
    assert [lb for _k, lb in K.PRELOADED["sfx"]] == [
        "Big / impact", "Small / background"]
    assert len(K.PRELOAD_KEYS) == 9


def test_a_new_project_starts_with_exactly_those(tmp_path):
    from mangatl import kinds as K
    p = _project(str(tmp_path / "fresh"), pages=1)
    labels = [s["label"] for s in p.settings["custom_kinds"]]
    assert labels == [lb for fam in K.FAMILIES
                      for _k, lb in K.PRELOADED[fam]], labels
