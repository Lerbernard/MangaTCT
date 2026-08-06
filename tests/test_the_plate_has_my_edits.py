"""What is saved has to be what is on screen.

lee, with a panel whose balloon border had a gap in it after cleaning:

> when typesetting the clean page it uses shoud have all the edit i make in
> it, becuase here on the picure the bubble had a big bap in teh border, i
> fixed it but its still not using the fixed version

He had painted the border closed and it stayed closed on his screen. The
typeset page did not have it.

Two pictures of the same strokes exist, and they were allowed to disagree:

* the EDITABLE LAYERS, which the browser replays onto the paint canvas — that
  is what he was looking at;
* the OVERLAY, one flat PNG the browser sends up, which the server composites
  into the cleaned plate before the typesetting is drawn — that is what the
  typeset page and the export are built from.

The overlay was built by replaying the layer stack into a buffer and reading
that buffer straight back out. Two things could quietly leave a layer out of
that replay, and neither left a mark:

* **A picture that had not decoded yet.** A heal or clone-stamp patch is a
  PNG and an eraser's fence is a PNG, and a browser decodes those
  asynchronously. `replayStroke` skipped a layer whose picture had not landed
  — right for the screen, where the decode fires another repaint a moment
  later, and wrong for the save, which nothing repeats. The save now waits for
  every picture to decode, and refuses to send a replay that still came up
  short.
* **A family folded away.** The Layers panel has a master eye over the drawing
  family and another over the retouch family, so a heavily-healed page does
  not drown the list. Those two live in the tab and are back on the moment the
  page is reopened — but they were filtering the buffer that gets SAVED, so
  folding the retouch family away and carrying on painting wrote a plate with
  every heal and clone patch missing. Reopening put them all back on screen,
  with no sign the saved copy disagreed. They are a way of LOOKING at the page
  now, not a fact about it: the screen honours them, the save does not.

And because a page could already be carrying a bad overlay, opening one
rewrites it once from the full decoded stack. That would have thrown away
every rendered page in the chapter each time — writing the overlay bumps the
render epoch — so a save that changes nothing now costs nothing: the server
compares before it writes.
"""
import os
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

RED = [85, 45, 255]        # BGR of #ff2d55


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((300, 460, 3), 240, np.uint8)
    cv2.ellipse(img, (230, 150), (130, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (230, 150), (130, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    st = p.pages[0]
    st.regions = [{"id": 1, "kind": "bubble", "order": 0,
                   "bbox": [150, 110, 160, 80],
                   "bubble_bbox": [110, 70, 240, 160],
                   "polygon": [[150, 110], [310, 110], [310, 190], [150, 190]],
                   "confidence": 0.9, "src_text": "テスト",
                   "dst_text": "MIND THE GAP"}]
    st.detected = True
    return p


@pytest.fixture()
def page(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    root = str(tmp_path / "plate")
    p = _project(root)
    editor.do_typeset(p, 0)
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
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        try:
            yield pg, p, root, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


# A patch layer is the shape a heal or a clone stamp leaves behind: a picture
# with a position, decoded from a data URL. This is the one that used to be
# lost, so this is what the tests below paint with.
_PATCH = """(group, x, col, decode)=>{
  const c=document.createElement('canvas');
  c.width=60; c.height=24;
  const g=c.getContext('2d');
  g.fillStyle=col; g.fillRect(0,0,60,24);
  const st={id:layerSeq++, type:'patch', x:x, y:250, png:c.toDataURL(),
            img:null, pts:[], op:1, visible:true, group:group,
            label:group==='retouch'?'':'Patch'};
  // `decode` false leaves the picture undecoded, which is the state a patch
  // is in for the first few milliseconds of its life — the window the save
  // used to fall into.
  if(decode!==false){
    const im=new Image();
    im.onload=()=>{ st.img=im; repaintAll(); };
    im.src=st.png;
  }
  layers.push(st);
  renderLayers(); queueSync();
}"""

GREEN = [96, 221, 44]      # BGR of #2cdd60


def _patch(pg, group="drawing", x=20, col="#ff2d55", decode=True):
    pg.evaluate(f"({_PATCH})({group!r}, {x}, {col!r}, {str(decode).lower()})")


def _has(img, bgr, box=None):
    if box is not None:
        x0, y0, x1, y1 = box
        img = img[y0:y1, x0:x1]
    return float((np.abs(img.astype(int) - np.array(bgr)).sum(2) < 70).mean())


def _red(img):
    return _has(img, RED)


def _plate(p):
    """The cleaned plate as the typesetter is handed it."""
    from mangatl import editor
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    return page.clean_plate


def _synced(pg, timeout=20000):
    """Wait until the paint really is on the server, not for 2.5 seconds.

    `queueSync` debounces for 800ms and then posts. A fixed sleep long enough
    for both is a guess in two directions — too short and the test reads the
    plate before the strokes land, which is how this file went red once in a
    full run and never once on its own; too long and every case here pays for
    it. Watching the flags instead does not work either: `syncTimer` keeps its
    id after it has fired, and between the timer firing and `syncInflight`
    being assigned there is an await where both read as idle.

    So this does not wait, it FLUSHES: `syncPaint` clears the pending timer,
    sends whatever is dirty and hands back the request, and Playwright awaits
    the promise. Nothing is guessed at.
    """
    pg.evaluate("() => syncPaint()")


def _export(p, root):
    from mangatl import editor
    p.settings["export_dir"] = root
    p.settings["export_name"] = "out"
    os.makedirs(editor.export_root(p), exist_ok=True)
    return cv2.imread(editor.export_page(p, 0))


# ------------------------------------------- a picture that had not decoded

def test_a_patch_saved_the_instant_it_is_made_reaches_the_plate(page):
    """The whole complaint, in one test.

    The save is asked for in the same breath as the layer is created, before
    its picture can possibly have decoded. That is not a contrived race — it
    is what pressing the heal brush does.
    """
    pg, p, root, errs = page
    _patch(pg, decode=False)          # nothing has started decoding it
    pg.wait_for_timeout(3000)
    assert p.pages[0].paint_overlay, "no overlay reached the server at all"
    ov = cv2.imread(p.pages[0].paint_overlay, cv2.IMREAD_UNCHANGED)
    assert ov is not None and ov.shape[2] == 4
    assert (ov[:, :, 3] > 0).sum() > 800, "the overlay is empty"
    assert _red(_plate(p)) > 0.005, "the plate does not have the patch"
    assert _red(_export(p, root)) > 0.005, "the exported page does not have it"
    assert not errs, errs[:2]


def test_a_picture_that_will_never_decode_does_not_stop_the_saving(page):
    """The waiting has to end.

    A broken picture never decodes, so the replay is never complete and a save
    that waits for it waits for ever — and every stroke made after it is lost
    with nothing on screen saying so. Waiting for something slow is right;
    waiting for something that is not coming is worse than going without it.
    """
    pg, p, root, errs = page
    pg.evaluate("""(()=>{ layers.push({id:layerSeq++, type:'patch', x:300,
        y:250, png:'data:image/png;base64,Tk9UQVBORw==', img:null, pts:[],
        op:1, visible:true, group:'drawing', label:'broken'});
      renderLayers(); queueSync(); })()""")
    pg.wait_for_timeout(1200)
    _patch(pg, "drawing", x=20, col="#ff2d55")     # a good one, after it
    pg.wait_for_timeout(6000)
    assert _red(_plate(p)) > 0.005, \
        "one undrawable layer stopped everything else from ever being saved"
    assert _red(_export(p, root)) > 0.005
    assert not errs, errs[:2]


def test_the_save_waits_for_the_picture_rather_than_sending_what_it_has(page):
    """The mechanism, pinned separately: `syncPaint` must not read the buffer
    until every layer's picture has decoded."""
    pg, _p, _root, _e = page
    got = pg.evaluate("""(async ()=>{
      const c=document.createElement('canvas');
      c.width=8; c.height=8;
      c.getContext('2d').fillStyle='#000';
      c.getContext('2d').fillRect(0,0,8,8);
      const st={id:layerSeq++, type:'patch', x:0, y:0, png:c.toDataURL(),
                img:null, pts:[], op:1, visible:true, group:'drawing'};
      layers.push(st);                       // deliberately: no decode started
      await layersReady();
      return !!st.img;
    })()""")
    assert got is True, "layersReady() came back with a layer still undecoded"


# ---------------------------------------------------- a family folded away

def test_folding_the_retouch_family_away_does_not_empty_the_plate(page):
    """The master eye is a way of looking at the page, not a fact about it.

    Fold the family away, paint on, and the heal and clone patches must still
    be in the plate — because reopening the page brings them all back on
    screen, and a saved copy that disagrees with the screen is the bug.
    """
    pg, p, root, errs = page
    _patch(pg, "retouch", x=20, col="#ff2d55")
    _synced(pg)
    before = _red(_plate(p))
    assert before > 0.005, "the patch never reached the plate to begin with"

    # Fold it away, then paint something else — somewhere else, in another
    # colour — so a save happens and the two cannot be confused for each other.
    pg.evaluate("toggleGroupEye('retouch')")
    _patch(pg, "drawing", x=340, col="#2cdd60")
    _synced(pg)
    assert pg.evaluate("showRetouch") is False
    plate = _plate(p)
    assert _has(plate, GREEN) > 0.005, "the new stroke did not reach the plate"
    assert _red(plate) >= before, \
        f"folding the retouch family away took it out of the plate ({before:.4f} -> {_red(plate):.4f})"
    assert not errs, errs[:2]


def test_folding_a_family_away_still_takes_it_off_the_screen(page):
    """...and the other half of that: it has to keep doing what it is for."""
    pg, _p, _root, errs = page
    _patch(pg, "retouch")
    _synced(pg)
    on = pg.evaluate("""(()=>{const c=$('paint');
      return [...$('paint').getContext('2d')
        .getImageData(0,0,c.width,c.height).data].filter((v,k)=>k%4===3&&v>0).length;})()""")
    assert on > 800, "the patch is not on the screen canvas"
    pg.evaluate("toggleGroupEye('retouch')")
    pg.wait_for_timeout(400)
    off = pg.evaluate("""(()=>{const c=$('paint');
      return [...$('paint').getContext('2d')
        .getImageData(0,0,c.width,c.height).data].filter((v,k)=>k%4===3&&v>0).length;})()""")
    assert off == 0, "folding the family away left it on screen"
    assert not errs, errs[:2]


def test_a_layers_own_eye_still_takes_it_off_the_page(page):
    """The per-layer eye is the one that means "not on the page", and it has
    to keep meaning that — this change must not turn every eye into a view."""
    pg, p, _root, errs = page
    _patch(pg)
    _synced(pg)
    assert _red(_plate(p)) > 0.005
    pg.evaluate("layers[0].visible=false; repaintAll(); queueSync();")
    _synced(pg)
    assert _red(_plate(p)) < 0.0005, "a hidden layer is still in the plate"
    assert not errs, errs[:2]


# ------------------------------------------------- repairing an old page

def test_opening_a_page_rewrites_an_overlay_that_lost_a_layer(page):
    """A page painted before this was fixed carries a bad overlay, and nothing
    on screen says so. Opening it must put it right."""
    pg, p, root, errs = page
    _patch(pg)
    _synced(pg)
    good = p.pages[0].paint_overlay
    assert good and _red(_plate(p)) > 0.005

    # Break it exactly the way the old code did: the editable layers keep the
    # patch, the flat overlay loses it.
    blank = np.zeros((300, 460, 4), np.uint8)
    cv2.imwrite(good, blank)
    from mangatl import editor
    editor._page_cache.clear()
    editor._invalidate_renders()
    assert _red(_plate(p)) < 0.0005, "the overlay was not actually broken"

    pg.reload(wait_until="load")
    pg.wait_for_timeout(1300)
    pg.evaluate("setTab('edit'); setView('typeset')")
    browserpool.settled(pg)
    assert _red(_plate(p)) > 0.005, \
        "opening the page did not repair the overlay"
    assert not errs, errs[:2]


def test_a_save_that_changes_nothing_changes_nothing(page):
    """The repair above runs on every page opened, and writing the overlay
    bumps the render epoch — which throws away every rendered page in the
    chapter, not just this one. So an identical save must be a no-op."""
    pg, p, _root, errs = page
    _patch(pg)
    _synced(pg)

    from mangatl import editor
    before_epoch = editor._render_epoch
    before_mtime = os.path.getmtime(p.pages[0].paint_overlay)
    said = pg.evaluate("""(async ()=>{
      const body={overlay:layersBuf().toDataURL('image/png'),
                  overlay_over:'', layers:serializeLayers()};
      return await api(`/api/page/${cur}/paint`,'POST',body);
    })()""")
    assert said.get("unchanged") is True, said
    assert editor._render_epoch == before_epoch, \
        "an identical save threw away every rendered page in the chapter"
    assert os.path.getmtime(p.pages[0].paint_overlay) == before_mtime
    assert not errs, errs[:2]


def test_a_save_that_does_change_something_still_lands(page):
    """...and the guard must not swallow a real change."""
    pg, p, _root, errs = page
    _patch(pg)
    _synced(pg)
    from mangatl import editor
    before_epoch = editor._render_epoch
    pg.evaluate("""(()=>{ layers.push({id:layerSeq++, type:'shape',
        shape:'rect', col:'#2cdd60', sz:4, fill:true, op:1, visible:true,
        pts:[{x:30,y:30},{x:90,y:70}]});
      repaintAll(); renderLayers(); queueSync(); })()""")
    _synced(pg)
    assert editor._render_epoch > before_epoch, "a real change was swallowed"
    assert len(p.pages[0].paint_layers) == 2
    assert not errs, errs[:2]
