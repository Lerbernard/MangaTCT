"""The typesetting panel, after lee used it.

* *"the tools are duplicated it shoud only be onteh side bar"*
* *"when i make e shape and clcik the freen transform tool it dissapears aand
  reaapers when i clcik on it"*
* *"if i dlete all teh text from a text box its shoud accesp the edit and stay
  the last size it was and i shoud be able to lcick on it to add text or dleete
  it"*
* *"reove the text in tehsecond screen shot and allow the text bx to acces line
  breaks without text and empty space just like photoshop"*
* *"remove the this box section too and add teh 2 pannels in the last screen
  shot, only add what you time will acuuucaly be useful to teh text editor"*

The last one came with a picture of Photoshop's Paragraph and Character
panels. What was taken from them is what a typesetter actually reaches for on a
comic page: which edge the lines hang from, the line and letter gaps, and
capitals. What was left out: first-line indent and space-before/after (a
balloon holds one paragraph), and hyphenation, which this project has never
done and never will.
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
    img = np.full((600, 500, 3), 240, np.uint8)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, (250, 180), (150, 90), 0, 0, 360, (20, 20, 20), 3)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "kind": "bubble", "order": 0, "bbox": [170, 140, 160, 80],
        "bubble_bbox": [110, 100, 280, 160],
        "polygon": [[170, 140], [330, 140], [330, 220], [170, 220]],
        "confidence": 0.9, "src_text": "テスト",
        "dst_text": "hello there my friend how are you today"}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "te"))
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
        pg.evaluate("select(1)")
        pg.wait_for_timeout(700)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _set_lines(pg, lines):
    pg.evaluate("""(ls)=>{const t=document.getElementById('lyLines');
        t.value=ls.join(String.fromCharCode(10));
        t.dispatchEvent(new Event('input',{bubbles:true}));
        flushTypesetEdit();}""", lines)
    pg.wait_for_timeout(1600)


def _lines(pg):
    return pg.evaluate("(regions.find(r=>r.id===1)||{}).layout.lines")


# ------------------------------------------------------------- the sections

def test_the_panel_reads_text_paragraph_character_colour_effects(ed):
    pg, _p, errs = ed
    titles = pg.evaluate(
        "[...document.querySelectorAll('#inspector details.grp > summary')]"
        ".map(s=>s.textContent.trim())")
    # The Text group is gone - the words are typed on the page.
    # lee, with a picture of it: *"remove this box"*.
    assert titles == ["Paragraph", "Character", "Colour", "Effects"]
    assert "This box" not in " ".join(titles)
    assert not errs, errs[:2]


def test_what_the_box_is_reads_before_anything_else(ed):
    """The two menus were folded away at the bottom under "This box". What a
    box IS decides everything else about it, so it is the first thing on the
    panel now, not a fold under the effects."""
    pg, _p, errs = ed
    first = pg.evaluate("""(()=>{const i=document.getElementById('inspector');
        const fam=document.getElementById('lyFam');
        const grp=i.querySelector('details.grp');
        return !!fam && !!grp &&
          (fam.compareDocumentPosition(grp) & 4) === 4;})()""")
    assert first is True, "the type menus are not above the folds"
    assert not errs, errs[:2]


def test_there_is_no_label_over_the_line_box(ed):
    """lee: *"reove the text in tehsecond screen shot"*. One line per row is
    what a text box IS, and the box says so by being one."""
    pg, _p, errs = ed
    assert pg.evaluate(
        "!/Line breaks/.test(document.getElementById('inspector').textContent)")
    assert not errs, errs[:2]


# ------------------------------------------------------------ what you type

def test_a_blank_line_between_two_paragraphs_survives(ed):
    """It used to be trimmed away, so a break could not be typed at all."""
    pg, _p, errs = ed
    _set_lines(pg, ["FIRST", "", "THIRD"])
    assert _lines(pg) == ["FIRST", "", "THIRD"]
    assert not errs, errs[:2]


def test_leading_spaces_survive(ed):
    pg, _p, errs = ed
    _set_lines(pg, ["   INDENTED", "FLUSH"])
    assert _lines(pg) == ["   INDENTED", "FLUSH"]
    assert not errs, errs[:2]


def test_trailing_blank_lines_are_dropped(ed):
    """Those are only where the cursor was left, not something typed."""
    pg, _p, errs = ed
    _set_lines(pg, ["ONE", "TWO", "", ""])
    assert _lines(pg) == ["ONE", "TWO"]
    assert not errs, errs[:2]


def _typeset(text, ov):
    """One region, one hand edit, typeset the way a preview or an export
    typesets it - `redo=False`, because Typeset itself deliberately throws hand
    corrections away and this is about what happens when it does not."""
    from mangatl import typeset as T
    from mangatl.models import Page, TextRegion
    img = np.full((200, 300, 3), 240, np.uint8)
    m = np.zeros((200, 300), np.uint8)
    m[20:180, 20:280] = 255
    r = TextRegion(id=1, bbox=(20, 20, 260, 160), kind="bubble",
                   text_mask=m, bubble_mask=m, bubble_bbox=(20, 20, 260, 160))
    r.dst_text = text
    page = Page(image=img)
    page.regions = [r]
    cfg = T.TypesetConfig(font_path=T.default_font_path(),
                          min_font=10, max_font=30)
    r.layout_override = dict(ov, locked=True)
    T.typeset_page(page, cfg)
    return r


def test_trailing_blank_lines_are_dropped_by_the_server_too():
    """The panel drops them before it sends, so the browser test above never
    reaches the server's own guard - and a layout can arrive from a saved
    project or another client without ever passing through the panel. The rule
    lives in both places, so it is proved in both places."""
    r = _typeset("one two",
                  {"lines": ["ONE", "TWO", "", ""], "font_size": 18})
    assert r.layout.lines == ["ONE", "TWO"], r.layout.lines
    # ...and one in the MIDDLE is still a line somebody typed
    r = _typeset("one two",
                  {"lines": ["ONE", "", "TWO", ""], "font_size": 18})
    assert r.layout.lines == ["ONE", "", "TWO"], r.layout.lines


def test_emptying_a_box_is_accepted_and_keeps_its_size(ed):
    pg, p, errs = ed
    was = pg.evaluate("regions.find(r=>r.id===1).layout.font_size")
    _set_lines(pg, [])
    got = pg.evaluate("regions.find(r=>r.id===1).layout")
    assert got["lines"] == [], got
    assert got["font_size"] == was, (got["font_size"], was)
    assert got["frame"], "it lost the frame it was standing in"
    # ...and on disk
    rec = p.pages[0].regions[0]
    assert (rec.get("layout") or {}).get("lines") == []
    assert not errs, errs[:2]


def test_an_emptied_box_is_still_there_to_click(ed):
    """lee: *"i shoud be able to lcick on it to add text or dleete it"*. A
    dashed placeholder stands where the block was, the way an empty text layer
    does in any editor."""
    pg, _p, errs = ed
    _set_lines(pg, [])
    assert pg.evaluate("!!document.querySelector('.temptyph')")
    assert pg.evaluate("frameAt(250,180)") == 1, "it cannot be clicked"
    # ...and it is still a row in the layer list
    pg.evaluate("select(null); if(textShut) toggleTextFold();")
    pg.wait_for_timeout(500)
    assert pg.evaluate(
        "document.querySelectorAll('#stackList .textrow').length") == 1
    assert not errs, errs[:2]


def test_typing_into_an_emptied_box_brings_it_back(ed):
    pg, _p, errs = ed
    _set_lines(pg, [])
    assert _lines(pg) == []
    _set_lines(pg, ["BACK AGAIN"])
    assert _lines(pg) == ["BACK AGAIN"]
    assert pg.evaluate("!document.querySelector('.temptyph')")
    assert not errs, errs[:2]


# ------------------------------------------------------ Paragraph, Character

def test_the_lines_can_hang_off_the_left_or_the_right(ed):
    """Everything was centred, which is right for a balloon and wrong for a
    caption: a block of narration ranged left is what a typesetter sets."""
    pg, p, errs = ed
    _set_lines(pg, ["A SHORT ONE", "A CONSIDERABLY LONGER LINE"])
    mid = pg.evaluate("regions.find(r=>r.id===1).layout.origins.map(o=>o[0])")
    pg.evaluate("setAlign(1,'left')")
    pg.wait_for_timeout(1400)
    left = pg.evaluate("layoutOrigins(regions.find(r=>r.id===1),"
                       " regions.find(r=>r.id===1).layout).map(o=>o[0])")
    pg.evaluate("setAlign(1,'right')")
    pg.wait_for_timeout(1400)
    right = pg.evaluate("layoutOrigins(regions.find(r=>r.id===1),"
                        " regions.find(r=>r.id===1).layout).map(o=>o[0])")
    # centred: every line shares one centre. Ranged: the short line's centre
    # moves, and it moves the opposite way for left and for right.
    assert len(set(mid)) == 1, mid
    assert left[0] < left[1], left
    assert right[0] > right[1], right
    assert not errs, errs[:2]


def test_the_page_is_drawn_with_the_alignment_too():
    """The preview and the exported page are two drawings of one thing."""
    from mangatl import typeset as T
    from mangatl.models import Page, TextRegion
    img = np.full((200, 300, 3), 240, np.uint8)
    page = Page(image=img)
    m = np.zeros((200, 300), np.uint8)
    m[20:180, 20:280] = 255
    r = TextRegion(id=1, bbox=(20, 20, 260, 160), kind="bubble",
                   text_mask=m, bubble_mask=m, bubble_bbox=(20, 20, 260, 160))
    r.dst_text = "one two three four five six seven"
    page.regions = [r]
    cfg = T.TypesetConfig(font_path=T.default_font_path(),
                          min_font=10, max_font=30)
    out = {}
    for how in ("center", "left", "right"):
        r.layout_override = {"align": how}
        T.typeset_page(page, cfg, redo=True)
        out[how] = [x for x, _ in r.layout.line_origins]
    assert len(set(out["center"])) == 1, out["center"]
    assert out["left"][0] < out["left"][-1], out["left"]
    assert out["right"][0] > out["right"][-1], out["right"]


def test_all_caps_is_a_thing_one_block_can_ask_for():
    """It was a project-wide switch. One shout in capitals on a page that is
    not could not be asked for at all - and the capitals go on BEFORE the fit,
    because capitals are wider and uppercasing a finished layout is how a line
    ends up past the edge of its balloon."""
    from mangatl import typeset as T
    from mangatl.models import Page, TextRegion
    img = np.full((200, 300, 3), 240, np.uint8)
    page = Page(image=img)
    m = np.zeros((200, 300), np.uint8)
    m[20:180, 20:280] = 255
    r = TextRegion(id=1, bbox=(20, 20, 260, 160), kind="bubble",
                   text_mask=m, bubble_mask=m, bubble_bbox=(20, 20, 260, 160))
    r.dst_text = "quietly now"
    page.regions = [r]
    cfg = T.TypesetConfig(font_path=T.default_font_path(),
                          min_font=10, max_font=30)
    r.layout_override = {"caps": True}
    T.typeset_page(page, cfg, redo=True)
    assert " ".join(r.layout.lines) == "QUIETLY NOW"
    assert r.layout.fit_ok, "the capitals were allowed to overflow"
    # the translation itself is untouched - the capitals were for setting it
    assert r.dst_text == "quietly now"

    # ...and it holds for lines that were typed by hand, which take the other
    # road through the typesetter entirely - `layout_from_override`, not the
    # fitter. A switch that works on fitted text and not on edited text is a
    # switch that stops working the moment you touch the box.
    hand = _typeset("quietly now", {"caps": True,
                                     "lines": ["quietly", "now"],
                                     "font_size": 18})
    assert hand.layout.lines == ["QUIETLY", "NOW"], hand.layout.lines
    hand = _typeset("quietly now", {"caps": False,
                                     "lines": ["quietly", "now"],
                                     "font_size": 18})
    assert hand.layout.lines == ["quietly", "now"], hand.layout.lines


def test_the_panel_offers_both_and_nothing_that_does_nothing(ed):
    pg, _p, errs = ed
    # `.alignb` is also the styling of the curve-kind chips now, so the
    # alignment row is counted by its own name.
    assert pg.evaluate(
        "document.querySelectorAll('.alignrow .alignb').length") == 3
    assert pg.evaluate("!!document.getElementById('lyCaps')")
    assert pg.evaluate("!!document.getElementById('lyLead')")
    assert pg.evaluate("!!document.getElementById('lyLspace')")
    # ...and none of what a balloon has no use for
    body = pg.evaluate("document.getElementById('inspector').textContent")
    for gone in ("Hyphenate", "Indent", "Space before", "Space after",
                 "Baseline"):
        assert gone not in body, gone
    assert not errs, errs[:2]


# -------------------------------------------------------------- the healing

def test_there_is_one_healing_brush_and_it_is_the_ai_one():
    """Two tests stood here, both about how fast the LOCAL healing brush ran
    over a big spot - lee: *"teh healing brush and teh ai healing brush are
    taking a long time to edit, look into that"*. That brush is gone, and with
    it the question: *"remoev teh regualr healing brush, its ass"*.

    Rewritten rather than deleted, because the requirement did not disappear,
    it REVERSED. What has to be true now is that nothing anywhere can still
    reach the local fill - a leftover call would be the slow, disliked brush
    coming back under the other one's name.
    """
    import inspect
    from mangatl import editor, inpaint

    assert not hasattr(inpaint, "heal_spot"), "the local brush is back"
    assert not hasattr(inpaint, "content_heal"), "its patch fill is back"
    # ...and shift_fill stays, because it is the Clean step's own fill and
    # was never the brush.
    assert hasattr(inpaint, "shift_fill")

    code = inspect.getsource(editor.Handler.do_POST)
    heal = code[code.index('/heal'):]
    heal = heal[:heal.index('/rename')]
    assert "heal_spot" not in heal, "the endpoint still falls back to it"
    assert "_make_cleaner" in heal, "the brush no longer asks the AI cleaner"
