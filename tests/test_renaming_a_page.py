"""Right-click a page to rename it, and no brush over a dialog.

Two of lee's, from the same message:

* *"if i right clcik on one of these tabs i shou dhave the option to rename the
  file"* - and the FILE moves, not just the label. The name in the list is the
  name on disk and they must not come apart.
* *"if have a have a tool active and i clcik of cleaned ot nay other tab and a
  popup window opend it shoud just be the mouse pointer over the popup"* - the
  brush ring and the eyedropper's loupe are pinned to the window at z-index 70
  and 71, above the dialog backdrop at 60, so "Clean the pages?" came up with a
  brush circle drawn across it.
"""
import json
import os
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

from mangatl.project import Project
from scratch import scratch
from where import PKG

CSS = (PKG / "static" / "css"
       / "editor.css").read_text(encoding="utf-8")


def _proj(root, n=3, ext=".jpg"):
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((60, 40, 3), 240, np.uint8)
    for k in range(n):
        p.add_uploaded(f"00{k}{ext}", cv2.imencode(ext, img)[1].tobytes())
    return p


# ------------------------------------------------------------- the file moves

def test_the_file_on_disk_moves_with_the_name(tmp_path):
    p = _proj(str(tmp_path / "out"))
    assert p.rename_page(1, "cover") == ""
    assert p.pages[1].name == "cover.jpg"
    assert os.path.exists(p.pages[1].path)
    assert sorted(os.listdir(p.upload_dir())) == ["000.jpg", "002.jpg",
                                                  "cover.jpg"]


def test_it_survives_being_reloaded(tmp_path):
    root = str(tmp_path / "out")
    p = _proj(root)
    p.rename_page(0, "cover")
    assert Project(None, root).pages[0].name == "cover.jpg"


def test_the_extension_is_not_the_person_s_to_change(tmp_path):
    """What a page is called has nothing to do with what format it is in, and
    a page renamed to "cover.txt" is a page the reader can no longer open."""
    p = _proj(str(tmp_path / "out"))
    assert p.rename_page(0, "cover.txt") == ""
    assert p.pages[0].name == "cover.jpg"


@pytest.mark.parametrize("bad", ["art/cover", "art\\cover", "a:b",
                                 "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"])
def test_a_name_that_is_a_path_is_refused(tmp_path, bad):
    """`os.path.basename` would turn "art/cover" into "cover" and save the page
    under a name nobody asked for, which is a worse answer than saying no."""
    p = _proj(str(tmp_path / "out"))
    assert p.rename_page(0, bad)
    assert p.pages[0].name == "000.jpg"


@pytest.mark.parametrize("bad", ["", "   "])
def test_an_empty_name_is_refused(tmp_path, bad):
    p = _proj(str(tmp_path / "out"))
    assert p.rename_page(0, bad) == "a page needs a name"


@pytest.mark.parametrize("bad", [".jpg", ".", "..", ".hidden"])
def test_a_name_that_starts_with_a_dot_is_refused(tmp_path, bad):
    """".jpg" splits as a whole hidden filename with no extension, not as an
    extension with nothing in front of it - so it would make a hidden file
    called ".jpg.jpg"."""
    p = _proj(str(tmp_path / "out"))
    assert p.rename_page(0, bad) == "a name cannot start with a dot"
    assert p.pages[0].name == "000.jpg"


def test_two_pages_cannot_share_a_name(tmp_path):
    p = _proj(str(tmp_path / "out"))
    assert "already" in p.rename_page(1, "000")
    assert p.pages[1].name == "001.jpg"
    assert os.path.exists(p.pages[1].path)


def test_not_even_when_they_live_in_different_folders(tmp_path):
    """The name check is not the file check wearing another hat.

    A project scanned from a folder and then added to keeps its pages in TWO
    directories, so two pages really can be called the same thing while neither
    file is in the other's way. What breaks then is everything keyed by name -
    the ticks, the cache keys, the export filenames - and the list shows the
    same name twice with no way to tell which is which.
    """
    src = tmp_path / "scan"
    src.mkdir()
    cv2.imwrite(str(src / "a1.jpg"), np.full((60, 40, 3), 240, np.uint8))
    p = Project(str(src), str(tmp_path / "out"))
    p.add_uploaded("b1.jpg", cv2.imencode(
        ".jpg", np.full((60, 40, 3), 240, np.uint8))[1].tobytes())
    assert os.path.dirname(p.pages[0].path) != os.path.dirname(p.pages[1].path)
    assert not os.path.exists(
        os.path.join(os.path.dirname(p.pages[1].path), "a1.jpg"))

    assert "already" in p.rename_page(1, "a1")
    assert [x.name for x in p.pages] == ["a1.jpg", "b1.jpg"]


def test_a_file_already_sitting_there_is_not_overwritten(tmp_path):
    """Not the same test: the clash can be with a file that is not a page of
    this project at all, and losing it would be losing someone's work."""
    p = _proj(str(tmp_path / "out"))
    other = os.path.join(p.upload_dir(), "cover.jpg")
    Path(other).write_bytes(b"not a page of this project")
    assert "already" in p.rename_page(0, "cover")
    assert Path(other).read_bytes() == b"not a page of this project"


def test_renaming_to_what_it_already_is_does_nothing(tmp_path):
    p = _proj(str(tmp_path / "out"))
    assert p.rename_page(0, "000") == ""
    assert p.pages[0].name == "000.jpg"


def test_there_is_no_page_nine(tmp_path):
    assert _proj(str(tmp_path / "out")).rename_page(9, "x") == "no such page"


# ---------------------------------------------------------- through the server

def _post(base, url, body):
    import urllib.error
    import urllib.request
    r = urllib.request.Request(base + url, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"},
                               method="POST")
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return json.load(e)


def test_the_endpoint_renames_and_says_the_new_name(tmp_path):
    from mangatl import editor
    p = _proj(str(tmp_path / "out"))
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        assert _post(base, "/api/page/0/rename", {"name": "cover"}) == \
            {"ok": True, "name": "cover.jpg"}
        assert "error" in _post(base, "/api/page/1/rename", {"name": "cover"})
        assert [x.name for x in p.pages] == ["cover.jpg", "001.jpg", "002.jpg"]
    finally:
        editor.PROJECT = was
        srv.shutdown()


# ------------------------------------------------------------- in the browser

def _serve(fn, root=scratch("_tmp_rename"), pages=3):
    from mangatl import editor
    p = _proj(root, n=pages, ext=".png")
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


def test_right_clicking_a_page_offers_to_rename_it():
    def check(pg, p):
        assert not pg.evaluate("!!document.getElementById('pgmenu')")
        pg.click('.pg[data-i="1"]', button="right")
        pg.wait_for_timeout(300)
        said = pg.evaluate("""(()=>{const m=document.getElementById('pgmenu');
          return m ? m.textContent.trim() : null;})()""")
        assert said and "Rename" in said, said
    _serve(check)


def test_typing_a_new_name_moves_the_file():
    """The whole way round: menu, field, Enter, server, disk, and the list
    showing the new name afterwards."""
    def check(pg, p):
        pg.click('.pg[data-i="1"]', button="right")
        pg.wait_for_timeout(250)
        pg.click("#pgmenu .tbrow")
        pg.wait_for_timeout(250)
        assert pg.evaluate("!!document.querySelector('.pg .nmedit')")
        # the extension is not offered - the field holds the stem
        assert pg.evaluate("document.querySelector('.pg .nmedit').value") == "001"
        pg.fill(".pg .nmedit", "cover")
        pg.press(".pg .nmedit", "Enter")
        pg.wait_for_timeout(700)
        assert p.pages[1].name == "cover.png"
        assert os.path.exists(p.pages[1].path)
        names = pg.evaluate("[...document.querySelectorAll('.pg .nm')]"
                            ".map(e=>e.textContent)")
        assert "cover.png" in names, names
    _serve(check)


def test_a_press_anywhere_else_ends_it():
    """Blur alone does not do this. The canvas, the toolbox and the page strip
    all call preventDefault on mousedown to stop a drag selecting text, and a
    prevented mousedown never moves the focus - so the field sat open with the
    click having gone somewhere else entirely. lee: *"for teh rename thing if i
    clcik anywhere on teh screen it shoud turn off"*."""
    def check(pg, p):
        pg.click('.pg[data-i="1"]', button="right")
        pg.wait_for_timeout(250)
        pg.click("#pgmenu .tbrow")
        pg.wait_for_timeout(250)
        assert pg.evaluate("!!document.querySelector('.pg .nmedit')")
        pg.fill(".pg .nmedit", "cover")
        # a press on the canvas, which is exactly the case blur does not cover
        pg.mouse.click(760, 500)
        pg.wait_for_timeout(800)
        assert not pg.evaluate("!!document.querySelector('.pg .nmedit')"), \
            "the field is still sitting there"
        assert p.pages[1].name == "cover.png"
    _serve(check)


def test_even_a_press_on_something_that_swallows_the_event():
    """`capture`, and this is why it has to be.

    Some controls stop a mousedown dead so a drag on them cannot start one
    somewhere else - the eye on a box row does, and so does every frame handle
    on the Translation view. A listener on the way UP never hears those, so the
    field stayed open for exactly the presses most likely to be the one that
    means "I am done here"."""
    def check(pg, p):
        pg.evaluate("""(()=>{
          regions=[{id:0,kind:'bubble',order:0,dst_text:'a',src_text:'a',
                    confidence:.9,bbox:[0,0,9,9]}];
          hiddenRows=[]; sel=null; renderList();})()""")
        pg.wait_for_timeout(300)
        pg.click('.pg[data-i="1"]', button="right")
        pg.wait_for_timeout(250)
        pg.click("#pgmenu .tbrow")
        pg.wait_for_timeout(250)
        pg.fill(".pg .nmedit", "cover")
        # A text frame's move body: `startFrame` calls preventDefault AND
        # stopPropagation, so the press neither blurs the field nor bubbles.
        pg.evaluate("""(()=>{
          const el=document.createElement('div');
          el.id='swallower';
          el.style.cssText='position:fixed;left:400px;top:400px;'
            +'width:120px;height:120px;z-index:99';
          el.addEventListener('mousedown', e=>{
            e.preventDefault(); e.stopPropagation();}, false);
          document.body.appendChild(el);})()""")
        # ...and it is a DRAG, released somewhere else, so no `click` event is
        # ever produced. The press is the moment the person moved on; waiting
        # for the click means waiting for one that may never come.
        pg.mouse.move(460, 460)
        pg.mouse.down()
        pg.mouse.move(900, 700)
        pg.mouse.up()
        pg.wait_for_timeout(800)
        assert not pg.evaluate("!!document.querySelector('.pg .nmedit')"), \
            "the field is still sitting there"
        assert p.pages[1].name == "cover.png"
    _serve(check)


def test_escape_leaves_the_name_alone():
    def check(pg, p):
        pg.click('.pg[data-i="0"]', button="right")
        pg.wait_for_timeout(250)
        pg.click("#pgmenu .tbrow")
        pg.wait_for_timeout(250)
        pg.fill(".pg .nmedit", "nope")
        pg.press(".pg .nmedit", "Escape")
        pg.wait_for_timeout(500)
        assert p.pages[0].name == "000.png"
    _serve(check)


def test_a_renamed_page_keeps_its_tick():
    """`selPages` is keyed by page NAME, so without help the tick would stay
    behind on a name that no longer exists and the page would come back
    unticked - quietly dropped from every "do all"."""
    def check(pg, p):
        pg.wait_for_timeout(300)
        assert pg.evaluate("selPages.has('001.png')")
        pg.click('.pg[data-i="1"]', button="right")
        pg.wait_for_timeout(250)
        pg.click("#pgmenu .tbrow")
        pg.wait_for_timeout(250)
        pg.fill(".pg .nmedit", "cover")
        pg.press(".pg .nmedit", "Enter")
        pg.wait_for_timeout(800)
        assert pg.evaluate("selPages.has('cover.png')")
        assert not pg.evaluate("selPages.has('001.png')")
        assert pg.evaluate("""document.querySelector('.pg[data-i="1"]')
          .classList.contains('sel')""")
    _serve(check)


def test_the_ring_is_gone_the_moment_a_dialog_opens():
    """Measured, not read off the stylesheet - and with the mouse standing
    still, which is the case the JS guard alone cannot cover."""
    def check(pg, p):
        pg.evaluate("setView('typeset')")
        browserpool.settled(pg)
        box = pg.evaluate("""(()=>{const b=document.getElementById('img')
          .getBoundingClientRect();
          return {x:b.left+b.width/2, y:b.top+b.height/2};})()""")
        pg.evaluate("toggleBrush(true)")
        pg.mouse.move(box["x"], box["y"])
        pg.wait_for_timeout(300)
        shown = pg.evaluate("""(()=>{const c=document.getElementById('brushCursor');
          return c ? getComputedStyle(c).display : 'missing';})()""")
        assert shown == "block", f"the brush ring never came up ({shown})"
        # ...and now a dialog, without the mouse moving at all
        pg.evaluate("document.getElementById('scopedlg').classList.add('on')")
        pg.wait_for_timeout(300)
        assert pg.evaluate(
            "getComputedStyle(document.getElementById('brushCursor')).display"
        ) == "none", "the brush circle is drawn across the dialog"
    _serve(check)


# --------------------------------------------------- and nothing over a dialog

def test_the_brush_ring_is_hidden_while_a_dialog_is_up():
    """In the stylesheet rather than in the code that moves it: the ring is
    moved on mousemove, and a dialog can open without the mouse moving at all.
    `!important` because the display it is fighting is set inline."""
    rule = [ln for ln in CSS.splitlines() if "#brushCursor" in ln and ":has(" in ln]
    assert rule, "nothing hides the ring when an overlay comes up"
    block = CSS.split("body:has(.modal.on) #brushCursor")[1].split("}")[0]
    assert "display:none !important" in block
    assert "#loupe" in block, "the eyedropper's loupe is over the dialog too"
    assert "#picker.on" in block, "the File screen is an overlay as well"
