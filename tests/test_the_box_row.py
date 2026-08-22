"""The row for one box, cleaned up.

lee: *"clean this box up remove tehup and down arrow remove teh 3 dots mak eteh
link a deapper blue and make it chnage the backgotund to that blue of what are
linked and make the icon the same types as the other and mkw it so athat
everything in the top row fits and remve the last row"*, and, with a picture of
the fold arrow on the Text folder: *"malke this bigger for teh drop down in teh
layers"*.

The head carried a ⋮ grip and a ▲▼ pair as well as the chips, and both were
duplicates: the whole head is the drag handle, and dragging is how the reading
order is set. With them gone everything fits on one line, and the type name is
what gives way when it does not.
"""
import re
import shutil
import threading
from pathlib import Path

import numpy as np
import pytest

import browserpool
from where import PKG

cv2 = pytest.importorskip("cv2")

ROOT = PKG


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [
        {"id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
         "bubble_bbox": [110, 100, 280, 160], "link": 0,
         "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
         "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO THERE"},
        {"id": 2, "kind": "narration_free", "order": 1, "link": 7,
         "bbox": [60, 320, 200, 70],
         "polygon": [[60, 320], [260, 320], [260, 390], [60, 390]],
         "confidence": 0.42, "src_text": "ナレ", "dst_text": "A caption",
         "manual": True},
        {"id": 3, "kind": "sfx_big", "order": 2, "link": 7,
         "bbox": [300, 420, 150, 60],
         "polygon": [[300, 420], [450, 420], [450, 480], [300, 480]],
         "confidence": 0.81, "src_text": "ドン", "dst_text": "BOOM"}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "boxrow"))
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
        pg.evaluate("setTab('edit'); setView('original')")
        browserpool.settled(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


# ------------------------------------------------------------- what is gone

def test_no_grip_and_no_order_arrows(ed):
    pg, _p, errs = ed
    assert pg.evaluate("document.querySelectorAll('#list .lgrip').length") == 0
    assert pg.evaluate("document.querySelectorAll('#list .ordbtns').length") == 0
    assert not errs, errs[:2]


def test_the_order_can_still_be_changed(ed):
    """The arrows are gone; the ability is not. The head is the drag handle,
    and `moveOrder` is still there for anything that asks for it."""
    pg, _p, errs = ed
    assert pg.evaluate("typeof moveOrder") == "function"
    assert pg.evaluate("""(()=>{const h=document.querySelector('#list .rowhead');
        return !!(h && h.getAttribute('onmousedown')||'').match(/armRowDrag/);})()""")
    pg.evaluate("moveOrder(1,1)")
    pg.wait_for_timeout(900)
    nums = pg.evaluate(
        "[...document.querySelectorAll('#list .chip.num')].map(c=>c.textContent)")
    assert nums == ["1", "2", "3"], nums
    first = pg.evaluate(
        "[...document.querySelectorAll('#list .lrow .tx')][0].textContent.trim()")
    assert first != "HELLO THERE", "nothing moved"
    assert not errs, errs[:2]


def test_the_point_size_readout_is_gone(ed):
    """The last line of every card said "27pt, 1 line" - a readout of the
    fitter's arithmetic on a list you read to find a sentence."""
    pg, _p, errs = ed
    txt = pg.evaluate("document.getElementById('list').textContent")
    assert not re.search(r"\d+pt,", txt), txt[:300]
    assert "line" not in txt.replace("Regular speech", ""), txt[:300]
    assert not errs, errs[:2]


# -------------------------------------------------------------- it all fits

def test_the_head_is_one_line(ed):
    pg, _p, errs = ed
    heights = pg.evaluate("""[...document.querySelectorAll('#list .rowhead')]
        .map(h=>Math.round(h.getBoundingClientRect().height))""")
    assert heights, "no rows"
    assert max(heights) - min(heights) <= 1, heights
    assert max(heights) <= 24, heights
    assert not errs, errs[:2]


def test_a_long_type_name_gives_way_rather_than_wrapping(ed):
    """Measured with a name longer than the panel, because that is the case
    that used to push the link badge onto a second line."""
    pg, _p, errs = ed
    was = pg.evaluate("""[...document.querySelectorAll('#list .rowhead')]
        .map(h=>Math.round(h.getBoundingClientRect().height))""")
    pg.evaluate("""(()=>{proj.settings.custom_kinds.forEach(k=>{
        if(k.key==='narration_free')
          k.label='A very long sub type name indeed and then some more';});
        renderList();})()""")
    pg.wait_for_timeout(600)
    now = pg.evaluate("""[...document.querySelectorAll('#list .rowhead')]
        .map(h=>Math.round(h.getBoundingClientRect().height))""")
    assert now == was, (was, now)
    # the colour is the point of that chip, so it is the last thing to go
    dot = pg.evaluate("""(()=>{const i=document.querySelectorAll(
        '#list .chip.kind i.kd')[1];
        return i ? Math.round(i.getBoundingClientRect().width) : 0;})()""")
    assert dot >= 8, dot
    # ...and the link badge is still on the same line, not pushed off it
    same = pg.evaluate("""(()=>{const h=document.querySelectorAll('#list .rowhead')[1];
        const k=h.querySelector('.chip.kind'), l=h.querySelector('.chip.link');
        if(!k||!l) return 'missing';
        return Math.abs(k.getBoundingClientRect().top
                       -l.getBoundingClientRect().top) < 2;})()""")
    assert same is True, same
    assert not errs, errs[:2]


# ----------------------------------------------------------------- the link

def test_the_three_link_colours_are_one_colour():
    """The editor draws the connector, the box sheet draws it again server
    side, and the CSS tints the row. Three copies of one decision, so a test
    stands where they could drift apart."""
    from mangatl import render
    js = (ROOT / "static" / "js" / "frames.js").read_text(encoding="utf8")
    css = (ROOT / "static" / "css" / "editor.css").read_text(encoding="utf8")
    a = re.search(r"const LINK_COLOR='(#[0-9a-fA-F]{6})'", js).group(1).lower()
    b = render.LINK_COLOUR.lower()
    c = re.search(r"--link:\s*(#[0-9a-fA-F]{6})", css).group(1).lower()
    assert a == b == c, (a, b, c)


def test_the_link_is_a_deep_blue():
    """Pale cyan read as a highlight rather than as a relationship, and at chip
    size on a dark panel it was almost white. lee: *"a deapper blue"*."""
    from mangatl import render
    h = render.LINK_COLOUR.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    assert b > 150, h                      # it is blue
    assert b - max(r, g) > 60, h           # …and clearly blue, not cyan
    assert (r + g + b) / 3 < 150, h        # …and deep, not pale


def test_a_row_is_the_same_plate_whatever_kind_it_is(ed, tmp_path):
    """lee, in order: *"make it chnage the backgotund to that blue of what are
    linked"* - a linked PAIR was one thing to look at; then *"can you make the
    tabs background match the color of the box and remove the blue
    background"*; then, having looked at two goes at that, *"aslo just go back
    to the  grey backgrounf"*. So the plate is plain again, and the type is
    said by the coloured dot and the name beside it.

    Read off the PICTURE, and by the MODE pixel of it: two of these three rows
    are a linked pair and carry a bright blue border, which would land in any
    average taken along an edge.
    """
    pg, _p, errs = ed
    tagged = pg.evaluate("""[...document.querySelectorAll('#list .lrow')]
        .map(r=>r.classList.contains('linked'))""")
    assert tagged == [False, True, True], tagged

    def plate(k):
        f = str(tmp_path / f"row{k}.png")
        pg.query_selector_all("#list .lrow")[k].screenshot(path=f)
        im = cv2.imread(f).reshape(-1, 3)
        keys, counts = np.unique(im, axis=0, return_counts=True)
        return keys[counts.argmax()].astype(float)      # BGR

    plates = [plate(k) for k in range(3)]
    for p2 in plates[1:]:
        assert float(np.linalg.norm(p2 - plates[0])) < 3, (plates[0], p2)
    # ...and it is grey: no channel standing out from the others
    b, g, r = plates[0]
    assert max(b, g, r) - min(b, g, r) < 14, plates[0]
    assert not errs, errs[:2]

def test_the_link_mark_is_line_art_like_every_other_icon(ed):
    """It was a 🔗 emoji - a colour picture from the system font, in a
    different weight, palette and size from everything beside it."""
    pg, _p, errs = ed
    txt = pg.evaluate("document.getElementById('list').textContent")
    assert "\U0001f517" not in txt, "the emoji is still there"
    n = pg.evaluate(
        "document.querySelectorAll('#list .chip.link svg path').length")
    assert n == 2, n
    assert pg.evaluate("""(()=>{const p=document.querySelector(
        '#list .chip.link svg path');
        return p.getAttribute('fill')==='none'
            && p.getAttribute('stroke')==='currentColor';})()""")
    assert not errs, errs[:2]


# ------------------------------------------------------- the layers arrow

def test_the_fold_arrow_on_the_text_folder_is_big_enough_to_hit(ed):
    """lee, with a screenshot of it: *"malke this bigger for teh drop down in
    teh layers"*. It was 9px in a 10px box - a speck you had to aim at, and
    the one control on that row."""
    pg, _p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    box = pg.evaluate("""(()=>{const c=document.querySelector('.lcar');
        if(!c) return null; const r=c.getBoundingClientRect();
        return [Math.round(r.width), Math.round(r.height),
                parseFloat(getComputedStyle(c).fontSize)];})()""")
    assert box is not None, "no fold arrow on the Text folder"
    assert box[0] >= 14 and box[1] >= 14, box
    assert box[2] >= 13, box
    assert not errs, errs[:2]


def test_it_still_folds(ed):
    pg, _p, errs = ed
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    was = pg.evaluate("textShut")
    pg.evaluate("document.querySelector('.lcar').click()")
    pg.wait_for_timeout(500)
    assert pg.evaluate("textShut") is not was
    assert not errs, errs[:2]
