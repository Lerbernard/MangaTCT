"""Making, renaming, recolouring and deleting sub-types, in the editor.

The model is pinned in `test_balloon_types.py`. This is the part a person
touches: the Box types section in settings, the two menus on a box, and what
happens to a page when a sub-type it is using is deleted out from under it.

lee: *"the user shoud be abe to modify and dletect teh subcategories exampty
for teh default one"* — so the default of each family has no × and no colour
to cycle, and everything else has both.
"""
import shutil
import time
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

from mangatl import kinds as K


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
        "confidence": 0.9, "src_text": "テスト", "dst_text": "HELLO"}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "kinds"))
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
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _settings(pg):
    pg.evaluate("setTab('settings')")
    browserpool.settled(pg)


def _labels(pg, sel):
    return pg.evaluate(f"[...document.querySelectorAll({sel!r})].map(e=>e.textContent.trim())")


# ------------------------------------------------------------ the two menus

def test_a_box_has_a_main_type_and_a_sub_type(ed):
    pg, _p, errs = ed
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(500)
    got = pg.evaluate("""(()=>{const s=[...document.querySelectorAll('.rinline select')];
        return {main:[...s[0].options].map(o=>o.text),
                sub:[...s[1].options].map(o=>o.text),
                mainNow:s[0].value, subNow:s[1].value};})()""")
    assert got["main"] == ["Bubble text", "Outside text", "Sound effect"]
    assert got["sub"][0] == "Regular speech"
    assert "Thought bubble" in got["sub"]
    assert got["mainNow"] == "bubble" and got["subNow"] == "bubble"
    assert not errs, errs[:2]


def test_the_sub_type_menu_follows_the_main_type(ed):
    """A thought balloon is not a kind of sound effect, so changing the family
    drops the box on that family's default rather than carrying a sub-type
    across into a family it means nothing in."""
    pg, _p, errs = ed
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)
    pg.evaluate("select(1); setKindSelected('thought')")
    pg.wait_for_timeout(700)
    assert pg.evaluate("regions.find(r=>r.id===1).kind") == "thought"
    pg.evaluate("setKindSelected('sfx')")
    pg.wait_for_timeout(700)
    assert pg.evaluate("regions.find(r=>r.id===1).kind") == "sfx"
    subs = pg.evaluate("""[...document.querySelectorAll('.rinline select')[1]
        .options].map(o=>o.text)""")
    assert subs[0] == "Sound effect"
    assert "Thought bubble" not in subs
    assert not errs, errs[:2]


def test_one_two_three_are_the_families_and_nothing_else_is_a_key(ed):
    """lee: *"only 1,2,3 shud work to swith box types"*.

    It went up to 8, and 4 upwards picked a sub-type by POSITION out of
    whatever family the box was already in — so 4 on a balloon and 4 on a sound
    effect were two different types, and nothing on screen numbered them. The
    three families are the three you can name and they are numbered the same
    way in the legend and in the Kind menu; sub-types are a menu away, where
    they are written out."""
    pg, _p, errs = ed
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(300)
    assert pg.evaluate("[kindForKey(1),kindForKey(2),kindForKey(3)]") == \
        ["bubble", "freefloat", "sfx"]
    for n in (0, 4, 5, 8, 9):
        assert pg.evaluate("(n)=>kindForKey(n)", n) is None, n
    # ...and it stays nothing whatever the box already is: the old 4 answered
    # differently on a balloon and on a sound effect.
    pg.evaluate("setKindSelected('sfx')")
    pg.wait_for_timeout(600)
    assert pg.evaluate("kindForKey(4)") is None
    assert not errs, errs[:2]


def test_pressing_four_leaves_the_box_alone(ed):
    """Through the keyboard, which is where it matters: a key that no longer
    means anything must not mean the LAST thing it meant."""
    pg, _p, errs = ed
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(300)
    pg.evaluate("setKindSelected('bubble')")
    pg.wait_for_timeout(600)
    pg.keyboard.press("4")
    pg.wait_for_timeout(600)
    assert pg.evaluate("regions.find(r=>r.id===1).kind") == "bubble"
    pg.keyboard.press("3")
    pg.wait_for_timeout(700)
    assert pg.evaluate("regions.find(r=>r.id===1).kind") == "sfx", \
        "1, 2 and 3 still have to work"
    # A letter is not a number, and `+"q"` is NaN — which must read as "no
    # family", not as the first one.
    pg.keyboard.press("q")
    pg.wait_for_timeout(500)
    assert pg.evaluate("regions.find(r=>r.id===1).kind") == "sfx"
    assert not errs, errs[:2]


def test_they_belong_to_the_translation_view(ed):
    """In the Image view those keys belong to painting and typesetting.

    Honest note: this passes with the view guard REMOVED as well, because the
    selection does not survive into that view — so it pins the intent rather
    than discriminating. The guard stays because it is the thing that would
    matter the day a selection does survive; there is no mutant for it,
    because there is nothing yet for a mutant to change."""
    pg, _p, errs = ed
    pg.evaluate("setTab('edit'); setView('original')")
    browserpool.settled(pg)
    pg.evaluate("select(1); setKindSelected('bubble')")
    pg.wait_for_timeout(600)
    pg.evaluate("setView('typeset')")
    browserpool.settled(pg)
    pg.keyboard.press("3")
    pg.wait_for_timeout(600)
    assert pg.evaluate("regions.find(r=>r.id===1).kind") == "bubble"
    assert not errs, errs[:2]


# ------------------------------------------------------------- the settings

def test_the_list_is_grouped_by_family_with_each_default_at_its_head(ed):
    pg, _p, errs = ed
    _settings(pg)
    assert _labels(pg, ".ckfamh") == ["Bubble text", "Outside text",
                                      "Sound effect"]
    heads = pg.evaluate("""[...document.querySelectorAll('.ckfam')]
        .map(g=>g.querySelector('.ckrow').textContent.trim())""")
    assert heads[0].startswith("Regular speech")
    assert heads[2].startswith("Sound effect")
    assert not errs, errs[:2]


def test_a_default_cannot_be_deleted_or_recoloured(ed):
    """lee: *"the user shoud be abe to modify and dletect teh subcategories
    exampty for teh default one"*. There has to be something a box IS when
    nothing finer has been said about it."""
    pg, _p, errs = ed
    _settings(pg)
    # The default's row DOES carry an ×, and it is deliberately not there to
    # see or to press: the row has to be the same width as one that can be
    # deleted or every row under it starts a button further along, which is
    # what lee saw — *"line up"*. So what matters is that it cannot be used.
    got = pg.evaluate("""(()=>{const d=[...document.querySelectorAll('.ckrow.ckdef')];
        const live=r=>{const b=r.querySelector('button.danger');
          if(!b) return false;
          const st=getComputedStyle(b);
          return !b.disabled && st.visibility!=='hidden'
                 && st.pointerEvents!=='none';};
        return {rows:d.length,
                withX:d.filter(live).length,
                clickable:d.filter(r=>r.querySelector('.swatch:not(.fixed)')).length,
                renameable:d.filter(r=>r.querySelector('input.cknm')).length};})()""")
    assert got["rows"] == 3
    assert got["withX"] == 0, "a default can be deleted"
    assert got["clickable"] == 0, "a default's colour can be changed"
    assert got["renameable"] == 0, "a default can be renamed"
    assert not errs, errs[:2]


def test_making_one_puts_it_in_the_family_that_was_chosen(ed):
    pg, p, errs = ed
    _settings(pg)
    pg.evaluate("""(()=>{document.getElementById('ckFamily').value='sfx';
        onCkFamily();
        document.getElementById('ckName').value='Rumble';
        addCustomKind();})()""")
    pg.wait_for_timeout(900)
    made = [s for s in p.settings["custom_kinds"] if s["label"] == "Rumble"]
    assert len(made) == 1, [s["label"] for s in p.settings["custom_kinds"]]
    assert made[0]["family"] == "sfx"
    assert made[0]["color"] in K.family_shades("sfx")
    assert not errs, errs[:2]


def test_its_colour_can_only_be_one_of_its_own_familys(ed):
    pg, p, errs = ed
    _settings(pg)
    offered = pg.evaluate("""(()=>{document.getElementById('ckFamily').value='freefloat';
        onCkFamily();
        return [...document.querySelectorAll('#ckSwatches .swatch')]
          .map(s=>s.style.background);})()""")
    assert offered, "no colours offered"

    def hexes(css):
        import re
        m = re.match(r"rgb\((\d+), (\d+), (\d+)\)", css)
        return "#%02x%02x%02x" % tuple(int(x) for x in m.groups()) if m else css

    shades = K.family_shades("freefloat")
    for c in offered:
        assert hexes(c) in shades, (c, shades)
    assert not errs, errs[:2]


def test_cycling_a_colour_never_leaves_the_family(ed):
    pg, p, errs = ed
    _settings(pg)
    pg.evaluate("cycleKindColor('thought'); cycleKindColor('thought')")
    pg.wait_for_timeout(800)
    got = [s for s in p.settings["custom_kinds"] if s["key"] == "thought"][0]
    assert got["color"] in K.family_shades("bubble")
    assert not errs, errs[:2]


def test_renaming_one_keeps_every_box_that_uses_it(ed):
    """The key is what a box points at; the label is what you read. Renaming
    must not orphan a page."""
    pg, p, errs = ed
    pg.evaluate("setTab('edit'); setView('original'); select(1); setKindSelected('thought')")
    browserpool.settled(pg)
    _settings(pg)
    pg.evaluate("renameKind('thought','Inner voice')")
    pg.wait_for_timeout(800)
    got = [s for s in p.settings["custom_kinds"] if s["key"] == "thought"][0]
    assert got["label"] == "Inner voice"
    assert p.pages[0].regions[0]["kind"] == "thought"
    assert not errs, errs[:2]


def test_a_family_stops_offering_more_once_it_is_full(ed):
    pg, p, errs = ed
    _settings(pg)
    pg.evaluate(f"""(()=>{{
      document.getElementById('ckFamily').value='sfx'; onCkFamily();
      for(let i=0;i<{K.SUBS_PER_FAMILY + 4};i++){{
        document.getElementById('ckName').value='S'+i;
        document.getElementById('ckFamily').value='sfx';
        addCustomKind();
      }}}})()""")
    # Fourteen round-trips to the server, waited for rather than slept on: a
    # fixed pause long enough on an idle machine is not long enough on a busy
    # one, and this test failed once in a full parallel run for no other
    # reason.
    end = time.time() + 20
    while time.time() < end and \
            len(K.subs_of("sfx", p.settings["custom_kinds"])) \
            < K.SUBS_PER_FAMILY:
        pg.wait_for_timeout(120)
    assert len(K.subs_of("sfx", p.settings["custom_kinds"])) == K.SUBS_PER_FAMILY
    # ...and the other two are untouched by that
    assert K.subs_of("bubble", p.settings["custom_kinds"])
    assert not errs, errs[:2]


# ------------------------------------------------- a page using a deleted one

def test_deleting_one_leaves_the_boxes_using_it_working(ed):
    """A box points at a sub-type by key. Delete the sub-type and the key is
    still on the page — so it has to keep drawing, keep being cleaned, and
    keep obeying the switch that puts its family away. Balloon is where being
    wrong costs least, and it is what an unknown kind falls back to."""
    pg, p, errs = ed
    pg.evaluate("setTab('edit'); setView('original'); select(1); setKindSelected('thought')")
    browserpool.settled(pg)
    _settings(pg)
    pg.evaluate("delCustomKind('thought')")
    pg.wait_for_timeout(900)
    assert not [s for s in p.settings["custom_kinds"] if s["key"] == "thought"]
    assert p.pages[0].regions[0]["kind"] == "thought"

    from mangatl import editor, render
    assert render.kind_colour("thought", p.settings["custom_kinds"]) \
        in K.family_shades("bubble")
    # and the page still builds
    out = editor.render_index(p, 0, "typeset")
    assert out and len(out) > 500
    assert not errs, errs[:2]


def test_what_the_browser_holds_and_what_the_server_stores_agree(ed):
    """The browser posts the whole list; the server checks it and keeps its
    own. A sub-type that only exists in the tab is one that vanishes on
    reload."""
    pg, p, errs = ed
    _settings(pg)
    pg.evaluate("""(()=>{document.getElementById('ckFamily').value='bubble';
        onCkFamily();
        document.getElementById('ckName').value='Radio';
        addCustomKind();})()""")
    pg.wait_for_timeout(900)
    from mangatl.project import Project
    again = Project(None, p.output_dir)
    assert any(s["label"] == "Radio" for s in again.settings["custom_kinds"])
    assert not errs, errs[:2]


def test_a_posted_list_is_checked_not_trusted(ed):
    """It arrives from a browser, so a colour from another family, a family
    that does not exist and an eleventh sub-type all have to be caught."""
    pg, p, errs = ed
    said = pg.evaluate("""(async ()=>{
      const bad=[{key:'x1',label:'X1',family:'nonsense',color:'#00ff00'}];
      for(let i=0;i<14;i++) bad.push({key:'y'+i,label:'Y'+i,family:'sfx'});
      return await api('/api/settings','POST',{settings:{custom_kinds:bad}});
    })()""")
    assert not said.get("error"), said
    got = p.settings["custom_kinds"]
    assert all(s["family"] in K.FAMILIES for s in got)
    for f in K.FAMILIES:
        assert len(K.subs_of(f, got)) <= K.SUBS_PER_FAMILY
        for s in K.subs_of(f, got):
            assert s["color"] in K.family_shades(f), s
    assert not errs, errs[:2]
