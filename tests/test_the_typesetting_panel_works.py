"""Everything lee found wrong with the typesetting panel, in one sitting.

* *"the all caos does nothing"*
* *"the outline obsucures the gradient"*
* *"ehen i turn off teh gradient it donts accualy turn off"*
* *"th outer line donet work"*
* *"remove the last 2 buttons"* - Keep this / Auto-fit again
* *"make the x buttons red"*
* *"remove this box"* - the Text box, with a picture of it
* *"the text is overflowing"* - the overflow warning, cut off by the row
* *"this message sho8d show on teh edit page"*
* *"something i make the text big it randonly becomes smalle while teh text box
  remain big"*
* *"sometime the text just revert back why im eddit it"*
* *"allow me to lock other [layers] an allow me to turn text layer into image
  layers"*
"""
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

WARN = "overflow: shrunk below the minimum font size (10pt) to fit the box"


def _project(root, text="look closely at this", flag=None):
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
        "confidence": 0.9, "src_text": "よく見てください", "dst_text": text}]
    p.pages[0].detected = True
    p.save()
    return p


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "panel"))
    editor.do_typeset(p, 0)
    p.pages[0].regions[0]["flagged"] = WARN
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip('chromium unavailable')
    with browserpool.session() as br:
        pg = br.new_page(viewport={"width": 1500, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        browserpool.ready(pg)
        pg.evaluate("setTab('edit'); setView('typeset')")
        browserpool.settled(pg)
        pg.evaluate("select(1)")
        pg.wait_for_timeout(900)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _lines(pg):
    return pg.evaluate("(regions.find(r=>r.id===1).layout||{}).lines")


# --------------------------------------------------------- what the panel is

def test_the_text_box_is_gone_and_the_warning_is_there_instead(ed):
    """lee, with a picture of the Text group: *"remove this box"*. The words
    are typed on the PAGE, where you can see them land; a second copy in the
    panel was the same sentence in two places. And the warning about this
    block belongs where the block is worked on - it used to be a chip in the
    box list, which is not on screen in the Edit view at all."""
    pg, _p, errs = ed
    titles = pg.evaluate(
        "[...document.querySelectorAll('#inspector details.grp > summary')]"
        ".map(s=>s.textContent.trim())")
    assert titles == ["Paragraph", "Character", "Colour", "Effects"], titles
    assert pg.evaluate(
        "getComputedStyle(document.getElementById('lyLines')).display") == "none"
    assert WARN in pg.evaluate(
        "document.getElementById('inspector').textContent")
    assert pg.evaluate("!!document.querySelector('#inspector .lyflag')")
    assert not errs, errs[:2]


def test_the_warning_is_not_cut_off(ed):
    """lee: *"the text is overflowing"*, over a row whose warning ended
    "…to fit the bo". A warning is a sentence, and a sentence that may not
    wrap is a sentence with its end missing."""
    pg, _p, errs = ed
    got = pg.evaluate("""(()=>{const c=document.querySelector('#inspector .lyflag');
        if(!c) return null;
        return [c.scrollWidth-c.clientWidth, c.textContent.trim(),
                c.clientHeight];})()""")
    assert got is not None, "no warning in the panel"
    assert got[0] <= 1, got                     # nothing hidden sideways
    assert got[1] == WARN, got                  # the whole sentence
    assert got[2] >= 30, got                    # and it really did wrap
    assert not errs, errs[:2]


def test_the_warning_is_only_in_one_place(ed):
    """lee, with a picture of each: *"this shoud not be on this page anymore
    becasue its alraedy on teh edit page remve it"*.

    It used to be in both - a chip in the box list AND the line under the
    sub-type. The list copy is the one that goes: everything the warning asks
    you to do about it (set the block smaller, widen the box, cut a word) is
    done in the Edit view."""
    pg, _p, errs = ed
    # It is in the one place it belongs...
    assert WARN in pg.evaluate(
        "document.getElementById('inspector').textContent")
    # ...and nowhere else. The box list is the same list in either view, so
    # looking at it in the one the screenshot was taken in is enough.
    pg.evaluate("setView('original')")
    browserpool.settled(pg)
    assert WARN not in pg.evaluate(
        "document.getElementById('list').textContent")
    assert not pg.evaluate("!!document.querySelector('#list .chip.r')")
    assert not errs, errs[:2]


def test_the_warning_is_not_hard_against_the_sub_type_box(ed):
    """lee, with a picture: *"add some sapce betwwen these in teh edit page"*.

    A red box touching the bottom edge of a select reads as part of that
    select - as if the sub-type itself were in error. It needs more air above
    it than the 3px a label sits above its own control, or the grouping says
    the wrong thing."""
    pg, _p, errs = ed
    gap = pg.evaluate("""(()=>{
        const s=document.getElementById('lyKind');
        const f=document.querySelector('#inspector .lyflag');
        if(!s||!f) return null;
        return f.getBoundingClientRect().top - s.getBoundingClientRect().bottom;
      })()""")
    assert gap is not None, "sub-type select or warning missing"
    assert gap >= 8, gap
    assert not errs, errs[:2]


def test_the_two_buttons_at_the_foot_are_gone(ed):
    pg, _p, errs = ed
    txt = pg.evaluate("document.getElementById('inspector').textContent")
    assert "Keep this" not in txt
    assert "Auto-fit again" not in txt
    assert not errs, errs[:2]


def test_every_clear_button_is_red(ed):
    """lee: *"make the x buttons red"*. They throw something away, and the
    Delete button beside them has said so in red all along."""
    pg, _p, errs = ed
    got = pg.evaluate("""[...document.querySelectorAll('#inspector button')]
        .filter(b=>b.textContent.trim()==='\\u00d7')
        .map(b=>b.classList.contains('danger'))""")
    assert got and all(got), got
    # Five since the outline gained a gradient of its own, which has its own
    # From, To, angle and × like the fill's does.
    assert len(got) == 5, got
    assert not errs, errs[:2]


# ----------------------------------------------------------- what it now does

def test_all_caps_reaches_the_page(ed):
    pg, _p, errs = ed
    assert _lines(pg) == ["look closely", "at this"], _lines(pg)
    pg.evaluate("""(()=>{const c=document.getElementById('lyCaps');
        c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true}));})()""")
    pg.wait_for_timeout(2000)
    assert _lines(pg) == ["LOOK CLOSELY", "AT THIS"], _lines(pg)
    assert not errs, errs[:2]


def test_turning_the_gradient_off_turns_it_off(ed):
    """It was read as `ov.fg2 || st.fg2` - the SAVED override first - so a
    colour just cleared went on being drawn: the live style was `''`, which
    `||` steps straight past, and the override still held the old value.
    lee: *"ehen i turn off teh gradient it donts accualy turn off"*."""
    pg, _p, errs = ed
    pg.evaluate("""(()=>{
      document.getElementById('lyFg1').value='#000000';
      document.getElementById('lyFg2').value='#f48414';
      onTypesetStyle(1);})()""")
    pg.wait_for_timeout(1500)
    assert pg.evaluate(
        "document.querySelectorAll('#overlay .tl.grad').length") > 0
    # Checked AT ONCE. The round trip eventually writes the empty colour into
    # the override as well, at which point both readings agree and the bug is
    # invisible - the whole complaint is about what the page does in the
    # meantime, which is every moment you are actually looking at it.
    pg.evaluate("clearGradient(1)")
    pg.wait_for_timeout(120)
    assert pg.evaluate(
        "document.querySelectorAll('#overlay .tl.grad').length") == 0, \
        "still drawn from the saved override"
    assert pg.evaluate("(regions.find(r=>r.id===1).layout_override||{}).fg2") \
        in ("#f48414",), "the override cleared too fast for this to prove it"
    pg.wait_for_timeout(1500)
    assert pg.evaluate(
        "document.querySelectorAll('#overlay .tl.grad').length") == 0
    assert pg.evaluate("""(()=>{const el=document.querySelector('#overlay .tl');
        return el && getComputedStyle(el).color;})()""") != "rgba(0, 0, 0, 0)"
    assert not errs, errs[:2]


def test_the_outline_does_not_cover_the_gradient(ed):
    """The gradient was a background on the LINE, and the outline span is a
    child of that line - so it painted over the background and swallowed the
    whole gradient at any width above a hairline.
    lee: *"the outline obsucures the gradient"*."""
    pg, _p, errs = ed
    pg.evaluate("""(()=>{
      document.getElementById('lyFg1').value='#000000';
      document.getElementById('lyFg2').value='#f48414';
      document.getElementById('lyStroke').value='3';
      onTypesetStyle(1);})()""")
    pg.wait_for_timeout(1600)
    got = pg.evaluate("""(()=>{
      const l=document.querySelector('#overlay .tl.grad');
      if(!l) return 'no gradient line';
      const f=l.querySelector('.tf'), s=l.querySelector('.ts');
      if(!f) return 'no fill span';
      const cs=getComputedStyle(f);
      return {onFill: cs.backgroundImage.indexOf('gradient')>=0,
              clear: cs.color === 'rgba(0, 0, 0, 0)',
              onLine: getComputedStyle(l).backgroundImage.indexOf('gradient')>=0,
              hasStroke: !!s};})()""")
    assert isinstance(got, dict), got
    assert got["hasStroke"] is True, "the fixture has no outline to cover it"
    assert got["onFill"] is True, got
    assert got["clear"] is True, got
    assert got["onLine"] is False, "still painted behind the outline"
    assert not errs, errs[:2]


def test_the_outer_glow_shows(ed):
    pg, _p, errs = ed
    pg.evaluate("""(()=>{
      document.getElementById('lyGlow').value='#ff2d55';
      document.getElementById('lyGlowS').value='10';
      onTypesetStyle(1);})()""")
    pg.wait_for_timeout(1500)
    sh = pg.evaluate("""(()=>{const l=document.querySelector('#overlay .tl');
        return l ? getComputedStyle(l).textShadow : '';})()""")
    assert "255, 45, 85" in sh, sh
    assert not errs, errs[:2]


# ------------------------------------------------- the two that lost work

def test_a_reply_that_predates_the_last_keystroke_is_thrown_away(ed):
    """The ordering counter was bumped where the request went OUT, so a reply
    was only discarded when a newer request had already been sent - and typing
    between "sent" and "received" sends nothing. The older reply was then
    accepted and overwrote the whole layout.

    lee: *"something i make the text big it randonly becomes smalle while teh
    text box remain big"* and *"sometime the text just revert back"*.
    """
    pg, _p, errs = ed
    # a slow preview, and an edit made while it is in the air
    # `fetch`, not `api` - `const api` in a classic script is a lexical
    # binding and not a property of `window`, so replacing `window.api`
    # replaces nothing and the whole race would quietly never happen.
    got = pg.evaluate("""(async()=>{
        const real=window.fetch;
        let release;
        const held=new Promise(r=>{release=r;});
        window.fetch=async(u,o)=>{
          const r=await real(u,o);
          if(String(u).indexOf('layout_preview')>=0) await held;
          return r;
        };
        const sz=document.getElementById('lySize');
        sz.value='9'; onTypesetEdit(1);            // asks for 9…
        await new Promise(r=>setTimeout(r,250));  // …and it goes out
        sz.value='40'; onTypesetEdit(1);           // typed again while it is in
        clearTimeout(previewTimer);               // …the air, and NOTHING new
        release();                                //   is sent. Only the edit
        await new Promise(r=>setTimeout(r,700));  //   itself says 9 is stale.
        window.fetch=real;
        return {size:(regions.find(r=>r.id===1).layout||{}).font_size,
                field:+document.getElementById('lySize').value};})()""")
    assert got["field"] == 40, got
    assert got["size"] == 40, \
        f"the reply for a size typed over is what the page kept: {got}"
    assert not errs, errs[:2]


def test_a_shorter_list_of_lines_is_not_mistaken_for_agreement(ed):
    """`typeof [] === 'object'`, so an array fell into the object branch and
    was walked over the indices present in `want` only: `_matches(["A","B"],
    ["A"])` came back TRUE. The server still holding two lines "agreed" with
    the one line just typed, the mark was dropped, and the deleted line came
    straight back."""
    pg, _p, errs = ed
    assert pg.evaluate("_matches(['A','B'], ['A'])") is False
    assert pg.evaluate("_matches(['A'], ['A','B'])") is False
    assert pg.evaluate("_matches(['A','B'], ['A','B'])") is True
    assert pg.evaluate("_matches([], [])") is True
    assert pg.evaluate("_matches({lines:['A','B']}, {lines:['A']})") is False
    assert not errs, errs[:2]


def test_the_list_is_not_rebuilt_under_the_caret(ed):
    """`renderList` blew the list DOM away including the box being typed in,
    and rebuilt it from `r.dst_text` - which is a keystroke behind by
    definition, because typing only notes a pending edit."""
    pg, _p, errs = ed
    pg.evaluate("setView('original')")
    browserpool.settled(pg)
    pg.evaluate("select(1)")
    pg.wait_for_timeout(800)
    got = pg.evaluate("""(()=>{
        const t=[...document.querySelectorAll('#list .rinline textarea')]
          .find(x=>(x.getAttribute('oninput')||'').indexOf('dst_text')>=0);
        if(!t) return 'no english box';
        t.focus();
        t.value='half a word';
        t.dispatchEvent(new Event('input',{bubbles:true}));
        renderList();                      // a poll landing mid-word
        const now=[...document.querySelectorAll('#list .rinline textarea')]
          .find(x=>(x.getAttribute('oninput')||'').indexOf('dst_text')>=0);
        return {same: now===t, value: now?now.value:null,
                focused: document.activeElement===now};})()""")
    assert isinstance(got, dict), got
    assert got["same"] is True, "the box was replaced under the caret"
    assert got["value"] == "half a word", got
    assert got["focused"] is True, got
    assert not errs, errs[:2]


# ------------------------------------------------------------- the layers

def test_any_layer_can_be_locked(ed):
    """Only the page had a lock, which is the one layer nobody was going to
    move by accident. lee: *"allow me to lock other [layers]"*."""
    pg, _p, errs = ed
    pg.evaluate("select(null)")
    pg.wait_for_timeout(600)
    pg.evaluate("""(()=>{
        layers.push({id:layerSeq++, type:'stroke', label:'test', group:'drawing',
                     col:'#fff', sz:4, pts:[{x:5,y:5},{x:9,y:9}], visible:true});
        renderLayers();})()""")
    pg.wait_for_timeout(500)
    n = pg.evaluate("document.querySelectorAll('#stackList .lay .llock').length")
    assert n >= 2, n                      # the page, and the new layer
    lid = pg.evaluate("layers[0].id")
    assert pg.evaluate(f"layerLocked({lid})") is False
    pg.evaluate(f"toggleLayerLock({lid})")
    pg.wait_for_timeout(400)
    assert pg.evaluate(f"layerLocked({lid})") is True
    # …and a locked layer is left alone
    pg.evaluate(f"deleteLayer({lid})")
    pg.wait_for_timeout(400)
    assert pg.evaluate("layers.length") == 1, "a locked layer was deleted"
    assert pg.evaluate(
        f"!document.querySelector('#stackList .lay[data-lid=\\'{lid}\\'] .lx[title^=Delete]')")
    assert not errs, errs[:2]


def test_a_text_box_can_be_locked_too(ed):
    pg, p, errs = ed
    pg.evaluate("select(null)")
    pg.wait_for_timeout(700)
    assert pg.evaluate(
        "document.querySelectorAll('#stackList .textrow .llock').length") == 1
    pg.evaluate("toggleTextLock(1)")
    pg.wait_for_timeout(900)
    assert pg.evaluate("regions.find(r=>r.id===1).locked") is True
    assert not errs, errs[:2]


def test_a_text_layer_becomes_an_image_layer(ed):
    """The words stop being words: what lands in the paint stack is a picture
    of them exactly as they were set, and the text box is emptied so nothing
    is drawn twice. lee: *"allow me to turn text layer into image layers"*."""
    pg, p, errs = ed
    pg.evaluate("select(null)")
    pg.wait_for_timeout(700)
    assert pg.evaluate("layers.length") == 0
    assert _lines(pg) == ["look closely", "at this"]
    pg.evaluate("textToImage(1)")
    # Waited for, not slept on. The picture is drawn by the SERVER and fetched,
    # so how long it takes is how busy the machine is - a fixed pause that is
    # long enough on an idle box is not long enough on a loaded one, and this
    # test failed twice in a full suite run while passing every time on its
    # own.
    pg.wait_for_function("layers.length===1", timeout=30000)
    assert pg.evaluate("layers.length") == 1, "no picture was made"
    assert pg.evaluate("layers[0].type") == "patch"
    assert pg.evaluate("!!layers[0].png")
    pg.wait_for_function(
        "((regions.find(r=>r.id===1)||{}).layout||{}).lines &&"
        " ((regions.find(r=>r.id===1)||{}).layout||{}).lines.length===0",
        timeout=15000)
    assert _lines(pg) == [], "the words are still there as well"
    assert not errs, errs[:2]


def test_the_picture_is_the_typesetting_and_nothing_else(tmp_path):
    """Drawn by the SERVER, by the same renderer that writes the exported
    page - so what you get is what would have been printed, not the browser's
    approximation of it. On clear paper: no plate, no other block."""
    from mangatl import editor, render as render_mod
    p = _project(str(tmp_path / "rast"))
    editor.do_typeset(p, 0)
    page = p.materialize(0)
    editor.clean_page(p, 0, page)
    cfg = editor._typeset_cfg(p)
    from mangatl import typeset as typeset_mod
    typeset_mod.typeset_page(page, cfg)
    bgra = render_mod.render_page(page, cfg, only={1}, bare=True)
    assert bgra.shape[2] == 4, bgra.shape
    a = bgra[:, :, 3]
    assert a.max() == 255, "nothing was drawn"
    # only where the block is
    ys, xs = np.nonzero(a)
    assert 100 < xs.min() and xs.max() < 400, (xs.min(), xs.max())
    # and nothing at all for a block that was not asked for
    none = render_mod.render_page(page, cfg, only={99}, bare=True)
    assert none[:, :, 3].max() == 0


# ------------------------------------ emptying a box, the way it is done now

def test_deleting_every_word_on_the_page_leaves_it_empty(ed):
    """lee: *"deleeting all teh etxt from a text box still dont just leave it,
    look into that and dont stop untill it works"*.

    The words are typed on the PAGE now, and `closeCanvasEdit` refused to
    commit an edit that came back empty - `lines.length` was a guard on the
    save. So selecting everything in a block and pressing delete committed
    nothing at all and the words came straight back when the editor closed.
    Deleting all of it is the most deliberate edit there is.
    """
    pg, p, errs = ed
    assert _lines(pg) == ["look closely", "at this"], _lines(pg)
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    assert pg.evaluate("editing") == 1, "the block did not open for typing"
    pg.evaluate("editBox.innerText=''")
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(2200)
    assert _lines(pg) == [], _lines(pg)
    assert p.pages[0].regions[0]["layout"]["lines"] == []
    assert (p.pages[0].regions[0].get("dst_text") or "") == "", \
        "the sentence is still there to be laid out again"
    assert not errs, errs[:2]


def test_and_it_is_still_empty_when_the_page_comes_back(ed):
    pg, p, errs = ed
    was = pg.evaluate("regions.find(r=>r.id===1).layout.frame.slice()")
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    pg.evaluate("editBox.innerText=''")
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(2200)
    pg.evaluate("showPage(0)")
    pg.wait_for_timeout(2200)
    assert _lines(pg) == [], _lines(pg)
    # …at the size it was left, so there is something there to click
    assert pg.evaluate("regions.find(r=>r.id===1).layout.frame") == was
    assert not errs, errs[:2]


def test_deleting_the_words_is_in_the_history_and_can_be_undone(ed):
    """lee: *"the text is deleting and teh empty box stay but its not in the
    history so i cant undo the delete chnage that"*.

    Two faults in one line. `saveTypesetting` snapshots `r.layout_override` for
    its undo - but `closeCanvasEdit` had already written the edit into the
    region before calling it, so the undo restored the edit and pressing it
    did nothing. And the entry said "typesetting changed", which over an emptied
    block is the one line in the list you would never think to press. The
    snapshot is taken before the edit now, and the entry says what happened.

    The translation is put back too: the server clears `dst_text` on its own
    when the lines come in empty, so an undo that only restored the override
    brought back an empty box."""
    pg, p, errs = ed
    assert _lines(pg) == ["look closely", "at this"], _lines(pg)
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    pg.evaluate("editBox.innerText=''")
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(2200)
    assert _lines(pg) == [], _lines(pg)

    top = pg.evaluate("hist.length ? hist[hist.length-1].label : ''")
    assert "deleted" in top, top
    assert pg.evaluate("undoStack.length") > 0, "nothing to undo"

    pg.evaluate("undoLast()")
    pg.wait_for_timeout(2600)
    assert _lines(pg) == ["look closely", "at this"], _lines(pg)
    assert (p.pages[0].regions[0].get("dst_text") or "") == "look closely at this", \
        p.pages[0].regions[0].get("dst_text")
    assert not errs, errs[:2]


def test_an_ordinary_typesetting_edit_still_says_what_it_is(ed):
    """The label is chosen, not hard-coded: a change that leaves words behind
    is still "typesetting changed"."""
    pg, _p, errs = ed
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    pg.evaluate("editBox.innerText='SOMETHING ELSE'")
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(2200)
    top = pg.evaluate("hist.length ? hist[hist.length-1].label : ''")
    assert "typesetting changed" in top, top
    assert not errs, errs[:2]


def test_undo_puts_back_the_hand_edit_and_does_not_re_typeset(ed):
    """lee: *"undo shou dnot undo the typeseeting only user made chnages"*.

    Set the size by hand, then delete the words, then undo. What must come
    back is the block as the PERSON left it - hand size and all - not the
    fitter's own answer. `reset` is the endpoint's word for "there was no hand
    edit here, typeset it from the sentence"; using it unconditionally would
    make every undo throw away whatever the person had already done to that
    block and hand it to the typesetter."""
    pg, p, errs = ed
    pg.evaluate("document.getElementById('lySize').value=15; onTypesetEdit(1)")
    pg.wait_for_timeout(1800)
    assert pg.evaluate("regions.find(r=>r.id===1).layout.font_size") == 15, \
        pg.evaluate("regions.find(r=>r.id===1).layout.font_size")

    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    pg.evaluate("editBox.innerText=''")
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(2200)
    assert _lines(pg) == [], _lines(pg)

    pg.evaluate("undoLast()")
    pg.wait_for_timeout(2600)
    assert _lines(pg) == ["look closely", "at this"], _lines(pg)
    assert pg.evaluate("regions.find(r=>r.id===1).layout.font_size") == 15, \
        ("the hand size was thrown away and the block was laid out again",
         pg.evaluate("regions.find(r=>r.id===1).layout.font_size"))
    assert not errs, errs[:2]


def test_the_outline_box_says_what_is_actually_drawn(ed):
    """lee, with a screenshot of a heavily outlined *COUGH*: *"make sure the
    outile alway match, the caufht outline says 1 when it clearly not"*.

    The box fell back to a bare 1 when the region carried no saved style -
    which is every region on a page that has just been opened, because
    `r.style` only exists after a save has been round-tripped. Meanwhile the
    canvas drew `L.stroke`, the width the fitter chose: two or more on
    anything standing on artwork, and three or four on a big sound effect. The
    box and the letters have to say the same thing."""
    pg, _p, errs = ed
    pg.evaluate("const r=regions.find(x=>x.id===1);"
                "delete r.style; r.layout.stroke=4; r.layout_override=null;"
                "renderInspector()")
    pg.wait_for_timeout(700)
    assert pg.evaluate("+document.getElementById('lyStroke').value") == 4, \
        pg.evaluate("document.getElementById('lyStroke').value")
    # …and a width the person set by hand still wins over both.
    pg.evaluate("const r=regions.find(x=>x.id===1);"
                "r.layout_override={stroke:9}; renderInspector()")
    pg.wait_for_timeout(700)
    assert pg.evaluate("+document.getElementById('lyStroke').value") == 9
    assert not errs, errs[:2]


def test_a_blank_line_typed_on_the_page_survives(ed):
    """`editLines` trimmed every line and dropped the empty ones - the same
    rule the panel's line box abandoned rounds ago."""
    pg, _p, errs = ed
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    pg.evaluate("editBox.innerText='FIRST\\n\\nTHIRD'")
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(2200)
    assert _lines(pg) == ["FIRST", "", "THIRD"], _lines(pg)
    assert not errs, errs[:2]


def test_clicking_a_block_and_clicking_away_is_still_not_an_edit(ed):
    """The guard that had to stay: opening a block and closing it unchanged
    used to save anyway, which locks it onto the hand-edit path and visibly
    moves the typesetting on a click that changed nothing."""
    pg, p, errs = ed
    assert not p.pages[0].regions[0].get("layout_override")
    pg.evaluate("editOnCanvas(1)")
    pg.wait_for_timeout(500)
    pg.evaluate("closeCanvasEdit(true)")
    pg.wait_for_timeout(1500)
    assert _lines(pg) == ["look closely", "at this"], _lines(pg)
    assert not p.pages[0].regions[0].get("layout_override"), \
        "an untouched block was locked onto the hand-edit path"
    assert not errs, errs[:2]
