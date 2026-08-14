"""Sound effects: the tick is back, on every format.

**One measurement, five answers, and this is the fifth.** For four of them
this file said the opposite, and every one of the four came off a single
number: on all 67 pages of lee's chapter 1, with CRAFT's second opinion and
the box grown to the whole stroke, 82 boxes came back as sound effects and of
the 36 checked one at a time **eighteen held no writing at all** — sword
blades, a face, two buildings, clothing, a gold ornament, a leg, a bed, five
thought-balloon tails.

The four turns, kept because they say what the argument was actually about:

1. Untick it — *"for manhwa and manhua dissavle teh other the last boxes"*.
2. Grey it out with a Coming soon pill — *"make it say comming soone"*.
3. lee threw that out (*"it shouls syill exist"*), so it went back to a plain
   unticked box — which he threw out too: *"shound affct shoud be sissable
   for the detector not the user, only uswrs shoud be able to make sfx boxes
   for manhwa and manhua"*. The row came out of the dialog altogether.
4. *"keep the tick box but mark it as comiing soon"*.

Not one of the four was an argument about the tick. They were four ways of
living with a pass that was wrong half the time.

**The number moved.** Everything built since was aimed at exactly those false
positives: the character census (`_characters_in` — a box CRAFT reads no
characters in is artwork), the art veto, the stray-mark sweep. Re-measured
after them on all 46 pages of the new chapter, every sfx box cropped and
looked at one at a time: **49 boxes, 47 hold real writing.** The two that do
not are an architectural ornament on page 22 and a gold braid on page 32 —
the same class as before, 2 instead of 18. Four per cent against fifty.

lee, shown that: give me the tick back.

So `NO_SFX_MEDIA` and `detectable_kinds` are gone, and what is left is the
tick that was always in the dialog, live on every format and **starting
unticked** exactly as it does on manga. Nothing arrives on anybody's pages
until they ask for it, `only_kinds` enforces the asking, and drawing one by
hand — a box on the Translation view, then `3` — works as it always did.
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

FORMATS = ["manhwa", "manhua", "manga"]


def _serve(fn, medium="manhwa", root=scratch("_tmp_sfxtick")):
    from mangatl import editor
    from mangatl.project import Project

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    im = np.full((900, 690, 3), 240, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", im)[1].tobytes())
    p.settings["medium"] = medium
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
            pg.wait_for_timeout(900)
            pg.evaluate("openDetect()")
            pg.wait_for_timeout(400)
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


STATE = """()=>{
  const s=document.getElementById('kSfx');
  const row=s.closest('label');
  return {shown: getComputedStyle(row).display!=='none',
          checked: s.checked, disabled: s.disabled,
          dimmed: row.classList.contains('disabled'),
          soon: !!document.getElementById('kSfxSoon'),
          byHand: !!document.getElementById('kSfxByHand'),
          rowText: row.textContent,
          bubble: document.getElementById('kBubble').disabled,
          free: document.getElementById('kFree').disabled};}"""


# ------------------------------------------------ the row, on every format

@pytest.mark.parametrize("medium", FORMATS)
def test_the_tick_is_live_and_the_three_rows_are_alike(medium):
    """The webtoons used to get this row greyed, dimmed and force-unticked.
    Whatever the medium, it is now the same row bubble text and outside text
    get."""
    def go(pg, _p):
        s = pg.evaluate(STATE)
        assert s["shown"], s
        assert not s["disabled"] and not s["dimmed"], s
        assert not s["bubble"] and not s["free"], s
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", FORMATS)
def test_it_starts_unticked(medium):
    """The half of lee's answer that is not "give me the tick back". A pass
    measured at 4% wrong is worth offering and is not worth doing to somebody
    who did not ask — and a chapter that has been through Find text once
    already must not gain a row of new boxes because the app changed its
    mind."""
    def go(pg, _p):
        assert pg.evaluate(STATE)["checked"] is False
        assert "sfx" not in pg.evaluate("chosenKinds()")
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", FORMATS)
def test_ticking_it_really_asks_for_them(medium):
    """It used to be dropped on the way out even when ticked — `chosenKinds`
    carried `&& sfxIsDetectable()`, because the row could be ticked on a manga
    project and the format changed afterwards. There is no such force now, so
    the tick is the whole answer."""
    def go(pg, _p):
        pg.evaluate("document.getElementById('kSfx').click()")
        assert pg.evaluate("chosenKinds()").count("sfx") == 1
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", ["manhwa", "manhua"])
def test_the_coming_soon_pill_and_the_by_hand_note_are_gone(medium):
    """Both existed to explain a row that could not be pressed. A pill saying
    "Coming soon" over a working tick is worse than no pill: it says the thing
    you are about to do does not work yet."""
    def go(pg, _p):
        s = pg.evaluate(STATE)
        assert not s["soon"], "the Coming soon pill is still in the document"
        assert not s["byHand"], "the standalone by-hand paragraph is still there"
        # ...but the by-hand route is still SAID, because it still works and
        # is the only way to box an effect the detector missed.
        assert "3" in s["rowText"] and "Translation view" in s["rowText"], \
            s["rowText"]
    _serve(go, medium=medium)


def test_nothing_can_be_run_with_nothing_ticked():
    """Untick them all and the button has to say so rather than launch a run
    that filters everything out."""
    def go(pg, _p):
        pg.evaluate("""document.getElementById('kBubble').checked=false;
                       document.getElementById('kFree').checked=false;
                       document.getElementById('kSfx').checked=false;""")
        pg.evaluate("runDetect(true)")
        pg.wait_for_timeout(400)
        assert pg.evaluate(
            "document.getElementById('modal').classList.contains('on')"), \
            "it closed the dialog and ran with nothing ticked"
    _serve(go)


# --------------------------------------- and the server no longer overrules

def test_the_server_asks_for_what_it_was_told_to_ask_for():
    """`Project.detect` used to run `kinds` through `detectable_kinds`, which
    struck `sfx` out on two formats whatever had been posted. That is the line
    this change is: the format no longer has a vote."""
    import inspect

    from mangatl.project import Project
    src = inspect.getsource(Project.detect)
    assert "detectable_kinds" not in src
    assert 'kinds = list(kinds or ["bubble"])' in src


def test_the_override_is_gone_from_both_sides():
    """Server and browser. Either one left behind would keep the old
    behaviour on its own — the server silently, which is worse."""
    import mangatl.project as P
    assert not hasattr(P, "NO_SFX_MEDIA")
    assert not hasattr(P, "detectable_kinds")
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    # The DEFINITION, not the word: the comment beside `chosenKinds` names the
    # call it used to carry, and a note saying what was removed is the reason
    # the removal is legible. A call left behind with no definition would be a
    # ReferenceError, and the three browser tests above assert on `pageerror`
    # for every format — so that half is covered by running it, not by reading.
    assert "function sfxIsDetectable" not in js
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert "kSfxSoon" not in html and "kSfxByHand" not in html


def test_the_tick_is_still_what_decides_on_the_server():
    """Taking the format's veto away must not take the TICK's authority with
    it. `only_kinds` is what a hand-rolled POST runs into, and it was always
    the thing really enforcing the dialog."""
    from types import SimpleNamespace

    from mangatl.project import only_kinds
    found = [SimpleNamespace(kind="bubble"), SimpleNamespace(kind="sfx"),
             SimpleNamespace(kind="freefloat")]
    assert [r.kind for r in only_kinds(found, ["bubble"])] == ["bubble"]
    assert [r.kind for r in only_kinds(found, ["bubble", "sfx"])] == \
        ["bubble", "sfx"]
    assert len(only_kinds(found, ["bubble", "freefloat", "sfx"])) == 3


def test_a_box_drawn_by_hand_is_untouched_by_any_of_this():
    """It never went through the detector's kinds at all, which was the whole
    distinction the old rule turned on — and it still holds. Nothing here
    changes what pressing 3 does."""
    js = (PKG / "static" / "js" / "region-ops.js").read_text(encoding="utf-8")
    assert "e.key==='s'&&sel!=null" in js or "setKindSelected('sfx')" in js


# ------------------------------------------------- input text / output text
#
# These rode in the same file as the rule and have nothing to do with it. They
# stay together because they were one screen's worth of work.

def test_the_side_panel_says_input_and_output():
    js = (PKG / "static" / "js" / "panels.js").read_text(encoding="utf-8")
    assert "<label>Input text</label>" in js
    assert "<label>Output text</label>" in js
    assert "<label>Japanese</label>" not in js
    assert "<label>English</label>" not in js


def test_the_undo_list_says_the_same_thing():
    """It named the same two fields "Japanese" and "English" in the history,
    which is the same wrong word in a second place."""
    js = (PKG / "static" / "js" / "region-ops.js").read_text(encoding="utf-8")
    assert "src_text:'Input text'" in js
    assert "dst_text:'Output text'" in js


def test_they_are_on_the_screen_that_way():
    """Not just in the source — the panel is built from a template string and
    a label can be written and never rendered."""
    def go(pg, _p):
        pg.evaluate("closeModal()")
        pg.wait_for_timeout(200)
        got = pg.evaluate("""()=>{
          if(typeof regionInlineEditor!=='function') return null;
          const h=regionInlineEditor({id:0,order:0,src_text:'a',dst_text:'b',
                                      kind:'bubble',bbox:[0,0,10,10]});
          return h;}""")
        assert got is not None, "regionInlineEditor is not there any more"
        assert "Input text" in got and "Output text" in got, got[:400]
        assert "Japanese" not in got and "English" not in got, got[:400]
    _serve(go)
