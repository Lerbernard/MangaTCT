"""Making a sound effect by hand: draw a box, press 3.

lee: *"for manhwa and manhua users shoud be able to create manual sfx boxes"*.
Find text does not tick sound effects by default on those formats -- measured on
his chapter 1, half of what came back as one had no writing in it -- so the ones
that matter are made by hand.

THIS FILE IS THE THIRD ANSWER TO THAT SENTENCE, and the first two are worth
keeping written down, because both were tools and both were wrong.

**A tool in the toolbox.** Second in the text slot, behind a right-click, on a
view the toolbox is not shown on. lee: *"still cant make manual sfx boxes"*.
Every test here passed, because every one of them armed it by calling
`toggleAddSfx` out of the console. Nothing pressed anything.

**A `+ Sound effect` button** beside Hide boxes. Reachable, visible, tested by
clicking -- and not what he wanted: *"i dont want a button i wan to be able to
clcik 3 to st teh button to a sond affct like the manga version"*.

He is right, and the second attempt was the sillier of the two, because **the
manga way already worked here**. `kindForKey` has meant balloon / outside text /
sound effect on 1, 2 and 3 since he asked for those keys. Both tools were a
second way to do a thing one key already did, with a mode you could leave armed.

WHAT WAS ACTUALLY STOPPING HIM was never a missing tool. His pages carry
`hidden_kinds: ["sfx"]`. He pressed 3, the box became a sound effect, the sound
effects were hidden on that page, and the box vanished -- with nothing on screen
saying why. Asking for a box of a kind is asking to see it, so `setKindSelected`
brings the group back out. That is the fix, and it is four lines where the
behaviour lives rather than a tool bolted beside it.
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


def _serve(fn, medium="manhwa", root=scratch("_tmp_handsfx")):
    from mangatl import editor
    from mangatl.project import Project

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 480, 3), 245, np.uint8)
    cv2.putText(img, "BANG", (60, 300), 0, 3.0, (20, 20, 20), 12)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
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
            try:
                return fn(pg, p)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


DRAG = """(f)=>{
  const b=document.getElementById('img').getBoundingClientRect();
  const at=(fx,fy)=>({x:b.left+b.width*fx, y:b.top+b.height*fy});
  const a=at(f[0],f[1]), c=at(f[2],f[3]);
  const st=document.getElementById('stage');
  const ev=(t,p)=>st.dispatchEvent(new MouseEvent(t,{bubbles:true,button:0,
      clientX:p.x, clientY:p.y}));
  ev('mousedown',a);
  window.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,
      clientX:c.x, clientY:c.y}));
  window.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0,
      clientX:c.x, clientY:c.y}));
  return true;}"""


def _draw(pg, box=(0.10, 0.40, 0.85, 0.62)):
    pg.evaluate("setTab('edit'); setView('original')")
    pg.wait_for_timeout(300)
    pg.evaluate(DRAG, list(box))
    pg.wait_for_timeout(900)


def _press(pg, key):
    pg.evaluate(
        "(k)=>window.dispatchEvent(new KeyboardEvent('keydown',"
        "{key:k,bubbles:true}))", key)
    pg.wait_for_timeout(700)


# --------------------------------------------------- draw a box, press 3

def test_three_turns_the_selected_box_into_a_sound_effect():
    def go(pg, p):
        _draw(pg)
        assert pg.evaluate("sel") is not None, "the drawn box is not selected"
        _press(pg, "3")
        assert [r.get("kind") for r in p.pages[0].regions] == ["sfx"]
    _serve(go)


def test_one_two_and_three_are_the_three_families_in_order():
    """3 only means sound effect because it is third. If the order ever moves,
    lee's key means something else and nothing else would say so."""
    js = (PKG / "static" / "js" / "frames.js").read_text(encoding="utf-8")
    assert "const KIND_FAMILIES=['bubble','freefloat','sfx'];" in js
    ro = (PKG / "static" / "js" / "region-ops.js").read_text(encoding="utf-8")
    assert "return (n >= 1 && n <= 3) ? KIND_FAMILIES[n - 1] : null;" in ro


def test_manga_gets_the_same_key():
    def go(pg, p):
        _draw(pg)
        _press(pg, "3")
        assert [r.get("kind") for r in p.pages[0].regions] == ["sfx"]
    _serve(go, medium="manga")


def test_two_puts_it_back_to_outside_text():
    """The control. If 3 did nothing at all the test above could still pass on
    a box that arrived as a sound effect by some other route."""
    def go(pg, p):
        _draw(pg)
        _press(pg, "3")
        _press(pg, "2")
        assert [r.get("kind") for r in p.pages[0].regions] == ["freefloat"]
    _serve(go)


# ------------------------------------ the box does not vanish when you do it

def test_the_box_comes_back_out_when_its_group_is_hidden():
    """lee's actual failure. With the sound effects put away — which is how his
    pages are saved — the box he just made disappeared the instant he made it.
    """
    def go(pg, p):
        _draw(pg)
        pg.evaluate("setKindShown('sfx', false)")
        pg.wait_for_timeout(800)
        assert "sfx" in (p.pages[0].hidden_kinds or [])
        # Putting a group away redraws the page, which drops the selection.
        # Picking the box up again is what lee does with the mouse.
        pg.evaluate("sel = regions[0].id")
        _press(pg, "3")
        assert (p.pages[0].hidden_kinds or []) == [], \
            "the group is still hidden, so the box is still invisible"
        assert pg.evaluate("regions.length") == 1
        assert [r.get("kind") for r in p.pages[0].regions] == ["sfx"]
    _serve(go)


def test_a_group_that_is_already_showing_is_left_alone():
    """It brings a hidden group out; it does not go round turning switches on
    that nobody touched."""
    def go(pg, p):
        _draw(pg)
        _press(pg, "3")                       # a sound effect, and showing
        pg.evaluate("setKindShown('bubble', false)")
        pg.wait_for_timeout(800)
        pg.evaluate("sel = regions[0].id")
        _press(pg, "3")                       # ...set to what it already is
        assert (p.pages[0].hidden_kinds or []) == ["bubble"], \
            "a switch nobody touched was flipped"
    _serve(go)


# ------------------------------------------------------- and no tool for it

def test_there_is_no_sound_effect_tool_anywhere():
    """Two of them shipped and lee did not want either. A third would be the
    third."""
    for name in ("region-ops.js", "toolbar.js", "view.js"):
        js = (PKG / "static" / "js" / name).read_text(encoding="utf-8")
        assert "toggleAddSfx" not in js, name
        assert "addSfxBtn" not in js, name
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert "addSfxBtn" not in html


def test_a_plain_drag_still_makes_an_ordinary_box():
    """Removing the tool must not take the drag with it — it is how the box you
    then press 3 on gets there in the first place."""
    def go(pg, p):
        _draw(pg)
        kinds = [r.get("kind") for r in p.pages[0].regions]
        assert kinds and kinds[0] != "sfx", kinds
    _serve(go)


def test_the_endpoint_takes_the_kind_it_is_given():
    """Without a browser. Every route to a kind goes through this."""
    import inspect

    from mangatl import editor

    src = inspect.getsource(editor.Handler.do_POST)
    assert 'kind=body.get("kind", "freefloat" if own else "bubble")' in src
