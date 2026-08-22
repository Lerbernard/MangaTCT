"""Four things lee asked for on the same afternoon, and one bug behind two.

1. *"add pace for me to dd the tittl e and sysnopis for new projects"* - step
   2 of Add pages could only LOAD a story context, which is the one thing a
   first chapter cannot do.
2. *"when i loded a new chapter the tick boxes came in pre uncheesced"* - 8 of
   71, on a chapter he had never opened.
3. *"alwo me to resize teh side side bar with the titles"*.
4. *"make teh dealt 25% bigger"* - 168px to 210.

**The bug behind two of them.** `title` has always been saved, exported and
used to name the files, and `Project.summary()` never sent it back. So the
Title box in Settings read empty on every reload, and the new box on step 2
would have read empty too and then written its emptiness over the name. One
missing key in one dict; it is asserted here at the level it broke, which is
the HTTP round trip and not the dataclass.

**Why the ticks came in unchecked.** They are remembered by page NAME, which
is stable inside a chapter and meaningless between two of them -
`page001.png … page071.png` is every chapter anybody has ever downloaded. 63
of lee's 71 names were already in `seen` from the chapter before, unticked
there, and a name that has been seen does not get the new-page tick. The
memory now carries the chapter it was made on.
"""
import json
import os
import shutil
import threading
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

import browserpool
from scratch import scratch
from where import PKG

cv2 = pytest.importorskip("cv2")

ROOT = scratch("_tmp_railstory")


def _serve(fn, root=ROOT, pages=3, names=None, title="", synopsis=""):
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 420, 3), 245, np.uint8)
    for k in range(pages):
        nm = (names[k] if names else "p%d.png" % k)
        p.add_uploaded(nm, cv2.imencode(".png", img)[1].tobytes())
    p.ctx.title = title
    p.ctx.synopsis = synopsis
    p.save()
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
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- the title that never came back

def test_the_title_comes_back_out_of_the_project():
    """Saved, exported, used to name the files - and never in `summary()`."""
    from mangatl.project import Project
    root = scratch("_tmp_titleback")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.ctx.title = "Villainess in Training"
    p.ctx.synopsis = "She is not sorry."
    assert p.summary()["context"]["title"] == "Villainess in Training"
    assert p.summary()["context"]["synopsis"] == "She is not sorry."
    shutil.rmtree(root, ignore_errors=True)


def test_the_settings_screen_shows_the_title_it_saved():
    """The round trip, at the level it actually broke."""
    def go(pg, _p):
        assert pg.evaluate("proj.context.title") == "Sworn Sword"
        assert pg.evaluate("document.getElementById('title').value") == \
            "Sworn Sword"
    _serve(go, title="Sworn Sword")


# --------------------------------------- somewhere to WRITE a story context

def test_step_two_has_a_title_and_a_synopsis_to_type_into():
    def go(pg, _p):
        pg.evaluate("showPicker(true); pkStep(2)")
        got = pg.evaluate("""()=>{
          const t=document.getElementById('pkStoryTitle');
          const s=document.getElementById('pkStorySynopsis');
          const step=document.querySelector('#picker .pkstep[data-step="2"]');
          const drop=document.getElementById('dropJson');
          return {t: !!t, s: !!s,
                  shown: t ? getComputedStyle(t).display!=='none' : false,
                  // the boxes come before the drop zone: typing is the common
                  // case on a new series, importing is the shortcut
                  first: !!(t && drop && (t.compareDocumentPosition(drop) &
                            Node.DOCUMENT_POSITION_FOLLOWING))};}""")
        assert got["t"] and got["s"], got
        assert got["shown"], "the boxes are on the step but not on the screen"
        assert got["first"], "the drop zone comes before the boxes"
    _serve(go)


def test_the_boxes_are_filled_from_the_project_and_not_left_empty():
    """Coming back to this step must not show two empty boxes over a synopsis
    that is already written - pressing Done would then erase it."""
    def go(pg, _p):
        pg.evaluate("showPicker(true); pkStep(2)")
        assert pg.evaluate(
            "document.getElementById('pkStoryTitle').value") == "Sworn Sword"
        assert pg.evaluate(
            "document.getElementById('pkStorySynopsis').value") == "A knight."
    _serve(go, title="Sworn Sword", synopsis="A knight.")


def test_writing_a_synopsis_saves_it():
    def go(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.fill("#pkStoryTitle", "Sworn Sword")
        pg.fill("#pkStorySynopsis", "A knight who does not kneel.")
        pg.evaluate("pkFinish()")
        pg.wait_for_timeout(500)
        assert p.ctx.title == "Sworn Sword", p.ctx.title
        assert p.ctx.synopsis == "A knight who does not kneel.", p.ctx.synopsis
    _serve(go)


def test_skip_keeps_what_was_typed():
    """Skip means "no settings FILE", not "throw away what I just wrote" -
    they are the same handler and both save."""
    def go(pg, p):
        pg.evaluate("showPicker(true); pkStep(2)")
        pg.fill("#pkStoryTitle", "Sworn Sword")
        pg.evaluate("pkFinish()")
        pg.wait_for_timeout(500)
        assert p.ctx.title == "Sworn Sword"
    _serve(go)


def test_typing_a_title_is_enough_to_press_done():
    """Done was shut until a FILE had been imported. With somewhere to type,
    that sends anybody who wrote a synopsis to Skip - the button that means
    "I did nothing"."""
    def go(pg, _p):
        pg.evaluate("showPicker(true); pkStep(2)")
        assert pg.evaluate("document.getElementById('pkDoneBtn').disabled"), \
            "Done starts open on an empty step"
        pg.fill("#pkStoryTitle", "Sworn Sword")
        pg.dispatch_event("#pkStoryTitle", "input")
        assert not pg.evaluate("document.getElementById('pkDoneBtn').disabled")
    _serve(go)


def test_an_untouched_step_does_not_wipe_the_story():
    """`pkSaveContext` may only write boxes that were FILLED from the project.
    Two empty boxes are "never shown", and posting those over a synopsis the
    project already had would lose it."""
    def go(pg, p):
        pg.evaluate("""(()=>{ pkFillContext.primed=false;
          document.getElementById('pkStoryTitle').value='';
          document.getElementById('pkStorySynopsis').value=''; })()""")
        pg.evaluate("pkSaveContext()")
        pg.wait_for_timeout(400)
        assert p.ctx.title == "Sworn Sword", p.ctx.title
        assert p.ctx.synopsis == "A knight."
    _serve(go, title="Sworn Sword", synopsis="A knight.")


# ------------------------------------------ the ticks, and whose ticks they are

CH1 = ["page001.png", "page002.png", "page003.png"]


def test_every_page_of_a_new_chapter_starts_ticked():
    """The 71-page case, at three pages: ticks saved against ANOTHER chapter's
    folder, page names identical, and this chapter still comes in all on."""
    def go(pg, _p):
        pg.evaluate("""(()=>{
          localStorage.setItem('mangatl_sel', JSON.stringify(
            {byName:true, chapter:'/somewhere/else/chapter-7',
             sel:[], seen:%s}));})()""" % json.dumps(CH1))
        pg.reload(wait_until="load")
        browserpool.ready(pg)
        pg.wait_for_timeout(400)
        got = pg.evaluate("""()=>({
          ticked: [...document.querySelectorAll('.pgchk')]
                    .filter(c=>c.checked).length,
          all: document.querySelectorAll('.pgchk').length,
          scoped: scopedPages().length})""")
        assert got["all"] == 3, got
        assert got["ticked"] == 3, got
        assert got["scoped"] == 3, got
    _serve(go, pages=3, names=CH1)


def test_a_tick_taken_off_survives_a_reload_of_the_same_chapter():
    """The memory is not thrown away - only somebody else's is. Untick one,
    press F5, and it is still off."""
    def go(pg, _p):
        pg.evaluate("togglePageSel(1)")
        pg.wait_for_timeout(200)
        assert pg.evaluate("scopedPages().length") == 2
        pg.reload(wait_until="load")
        browserpool.ready(pg)
        pg.wait_for_timeout(400)
        assert pg.evaluate("scopedPages().length") == 2, \
            "the unticked page came back ticked"
    _serve(go, pages=3, names=CH1)


def test_the_remembered_ticks_say_which_chapter_they_are_for():
    def go(pg, _p):
        pg.evaluate("togglePageSel(1)")
        pg.wait_for_timeout(200)
        blob = pg.evaluate("JSON.parse(localStorage.getItem('mangatl_sel'))")
        assert blob.get("chapter"), blob
        assert blob["chapter"] == pg.evaluate("selChapterKey()")
    _serve(go, pages=3, names=CH1)


def test_a_new_chapter_in_the_same_folder_is_a_new_chapter():
    """lee: *"unsettion page in a project and sarting a new project, the same
    pages are automaticaly unselcetd , that hsoud not happen"*.

    Every chapter he makes lives in ONE folder - "new project" is /api/reset
    on it - and his chapters' pages carry the same names. So ticks keyed on
    the folder alone were the old chapter's ticks, and the deselections came
    with them. The reset stamps a fresh `chapter_id`, the key carries it, and
    the ticks of a dead chapter stop matching.
    """
    def go(pg, _p):
        before = pg.evaluate("selChapterKey()")
        assert before, "no key, no memory"
        pg.evaluate("togglePageSel(1)")            # lee's manual deselect
        pg.wait_for_timeout(200)
        assert pg.evaluate("scopedPages().length") == 2
        # ...the new project, same folder, same page names.
        pg.evaluate("api('/api/reset','POST',{keep_settings:true})")
        pg.wait_for_timeout(400)
        pg.reload(wait_until="load")
        browserpool.ready(pg)
        pg.wait_for_timeout(400)
        after = pg.evaluate("selChapterKey()")
        assert after and after != before,             "the key must change or the old ticks claim the new chapter"
    _serve(go, pages=3, names=CH1)


def test_the_stamp_survives_keep_settings():
    """`keep_settings` copies the old settings over the new project AFTER the
    clear - a stamp written before that copy would be quietly put back."""
    src = (PKG / "editor.py").read_text(encoding="utf-8")
    at = src.index('if path == "/api/reset":')
    branch = src[at:at + 3000]
    assert '"chapter_id"' in branch
    assert branch.index("p.settings.update(keep)")         < branch.index('p.settings["chapter_id"]'),         "stamped after the copy, or the old id comes back"


# -------------------------------------------------------------- the rail

def test_the_rail_starts_a_quarter_wider_than_it_was():
    """168 → 210. Asserted on the computed width, because a rule that is
    present and overridden is a rule that is not there."""
    def go(pg, _p):
        w = pg.evaluate(
            "Math.round(document.getElementById('pages')"
            ".getBoundingClientRect().width)")
        assert w == 210, w
        assert pg.evaluate("RAIL_DEFAULT") == 210
        assert round(210 / 168.0, 2) == 1.25
    _serve(go)


def test_the_rail_can_be_dragged_wider_and_stays():
    def go(pg, _p):
        pg.evaluate("railWidth(300)")
        pg.wait_for_timeout(120)
        assert pg.evaluate(
            "Math.round(document.getElementById('pages')"
            ".getBoundingClientRect().width)") == 300
        pg.reload(wait_until="load")
        browserpool.ready(pg)
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "Math.round(document.getElementById('pages')"
            ".getBoundingClientRect().width)") == 300, \
            "the width was not remembered"
    _serve(go)


def test_the_rail_cannot_be_dragged_to_nothing_or_to_half_the_window():
    """Under the floor the checkbox and the dots leave no room for a name at
    all; over the ceiling it has stopped being a rail."""
    def go(pg, _p):
        assert pg.evaluate("railWidth(10)") == pg.evaluate("RAIL_MIN")
        assert pg.evaluate("railWidth(4000)") == pg.evaluate("RAIL_MAX")
        assert pg.evaluate("RAIL_MIN") < 210 < pg.evaluate("RAIL_MAX")
    _serve(go)


def test_there_is_something_to_grab():
    """A handle with a cursor that says so, next to the rail and before the
    reference pane."""
    def go(pg, _p):
        got = pg.evaluate("""()=>{
          const g=document.getElementById('pagesGrip');
          const p=document.getElementById('pages');
          if(!g||!p) return null;
          return {cursor: getComputedStyle(g).cursor,
                  wide: Math.round(g.getBoundingClientRect().width),
                  after: !!(p.compareDocumentPosition(g) &
                            Node.DOCUMENT_POSITION_FOLLOWING)};}""")
        assert got, "there is no handle"
        assert got["cursor"] == "col-resize", got
        assert got["wide"] >= 3, got
        assert got["after"], "the handle is on the wrong side of the rail"
    _serve(go)


def test_double_clicking_the_handle_puts_it_back():
    def go(pg, _p):
        pg.evaluate("railWidth(400)")
        pg.dblclick("#pagesGrip")
        pg.wait_for_timeout(150)
        assert pg.evaluate(
            "Math.round(document.getElementById('pages')"
            ".getBoundingClientRect().width)") == 210
    _serve(go)
