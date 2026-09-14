"""Clicking into a block with an outline does not draw the outline twice as tall.

lee, with a screenshot of a dark balloon: the English in black inside the box,
and behind it the same words as big white blobs running past the top and the
bottom of the balloon - *"can you fix thsi , i happedns when i lcik on a text
box"*.

The box you type into is one element, so the white rim round the letters is
drawn by a MIRROR under it (`editInkMirror`), one line div per line of text.
The mirror asks `editLines` for the lines, and `editLines` only reads the
editor's own document for `editBox` - which `editOnCanvas` set AFTER placing
the box, and placing the box is what builds the mirror. So the first mirror
read the box's innerText, where the browser puts a blank line between two
paragraphs: six lines came back as eleven, the rim stack stood nearly twice
as tall as the letters, and every line of white ink sat between and beyond the
black ones. Typing anything rebuilt it correctly, which is why it looked like
something that happens "when I click".
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")


def _project(root):
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.full((700, 500, 3), 235, np.uint8)
    cv2.ellipse(img, (250, 330), (170, 260), 0, 0, 360, (15, 15, 15), -1)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [180, 180, 140, 300],
        "bubble_bbox": [100, 90, 300, 480],
        "polygon": [[180, 180], [320, 180], [320, 480], [180, 480]],
        "confidence": 0.9, "src_text": "テスト",
        "dst_text": "In other words, a search for an Eda who would never betray me.",
        "layout_override": {"fg": "#000000", "edge": "#ffffff", "stroke": 3}}]
    p.pages[0].detected = True
    p.pages[0].cleaned = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor
    p = _project(str(tmp_path / "rim"))
    editor.do_typeset(p, 0)
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip("chromium unavailable")
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1300, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset'); showPage(0)")
        pg.wait_for_function(
            "()=>{const i=document.getElementById('img');"
            "return i&&i.complete&&i.naturalWidth>0;}", timeout=60000)
        pg.wait_for_function(
            "!(document.getElementById('pageLoading')||{classList:"
            "{contains:()=>false}}).classList.contains('on')", timeout=60000)
        browserpool.settled(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


_LINES = """(()=>{
  const ce=document.getElementById('canvasEdit');
  const rim=document.getElementById('canvasEditRim');
  const mid=e=>{const b=e.getBoundingClientRect(); return b.top+b.height/2;};
  return {paras: ce?[...ce.querySelectorAll('p')].map(p=>[p.textContent, mid(p)]):null,
          rim: rim?[...rim.children].map(d=>[d.textContent, mid(d)]):null};})()"""


def test_the_rim_has_one_line_per_line_of_text_when_the_box_opens(ed):
    pg, p, errs = ed
    lines = p.pages[0].regions[0]["layout"]["lines"]
    assert len(lines) >= 3, "fixture: the block has to wrap to show the bug"
    pg.evaluate("editOnCanvas(1)")
    browserpool.settled(pg)
    got = pg.evaluate(_LINES)
    assert got["paras"] and got["rim"] is not None, \
        "fixture: no rim was drawn, so there is nothing to check (%r)" % got
    assert len(got["rim"]) == len(got["paras"]), (
        "the rim has %d lines for %d lines of text"
        % (len(got["rim"]), len(got["paras"])))
    for (_t, ym), (_r, yr) in zip(got["paras"], got["rim"]):
        assert abs(ym - yr) <= 2, (
            "a line of the rim sits %.1fpx off its letters" % (yr - ym))
    assert not errs, errs[:2]


def test_edit_lines_reads_the_editor_even_before_it_is_the_edit_box(ed):
    """The guard on the other side: asked about the editor by its element,
    `editLines` answers from the document, never from innerText."""
    pg, _p, errs = ed
    pg.evaluate("editOnCanvas(1)")
    browserpool.settled(pg)
    got = pg.evaluate("""(()=>{const ce=document.getElementById('canvasEdit');
        const was=editBox; editBox=null;
        try { return editLines(ce); } finally { editBox=was; }})()""")
    assert all(s.strip() for s in got), got
    assert not errs, errs[:2]
