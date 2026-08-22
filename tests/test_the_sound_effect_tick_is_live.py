"""Sound effects: the tick is back, on every format.

**One measurement, five answers, and this is the fifth.** For four of them
this file said the opposite, and every one of the four came off a single
number: on all 67 pages of lee's chapter 1, with CRAFT's second opinion and
the box grown to the whole stroke, 82 boxes came back as sound effects and of
the 36 checked one at a time **eighteen held no writing at all** - sword
blades, a face, two buildings, clothing, a gold ornament, a leg, a bed, five
thought-balloon tails.

The four turns, kept because they say what the argument was actually about:

1. Untick it - *"for manhwa and manhua dissavle teh other the last boxes"*.
2. Grey it out with a Coming soon pill - *"make it say comming soone"*.
3. lee threw that out (*"it shouls syill exist"*), so it went back to a plain
   unticked box - which he threw out too: *"shound affct shoud be sissable
   for the detector not the user, only uswrs shoud be able to make sfx boxes
   for manhwa and manhua"*. The row came out of the dialog altogether.
4. *"keep the tick box but mark it as comiing soon"*.

Not one of the four was an argument about the tick. They were four ways of
living with a pass that was wrong half the time.

**The number moved.** Everything built since was aimed at exactly those false
positives: the character census (`_characters_in` - a box CRAFT reads no
characters in is artwork), the art veto, the stray-mark sweep. Re-measured
after them on all 46 pages of the new chapter, every sfx box cropped and
looked at one at a time: **49 boxes, 47 hold real writing.** The two that do
not are an architectural ornament on page 22 and a gold braid on page 32 -
the same class as before, 2 instead of 18. Four per cent against fifty.

lee, shown that: give me the tick back.

So `NO_SFX_MEDIA` and `detectable_kinds` are gone, and what is left is the
tick that was always in the dialog, live on every format and **starting
unticked** exactly as it does on manga. Nothing arrives on anybody's pages
until they ask for it, `only_kinds` enforces the asking, and drawing one by
hand - a box on the Translation view, then `3` - works as it always did.
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
def test_it_starts_ticked_now(medium):
    """It started unticked while the pass was fresh; lee, with the dialog on
    screen: *"make this the defaut tick boxes"* - all three rows on, and the
    biggest-effects guard on under it. Unticking is still one click and the
    sub-tick keeps its own state."""
    def go(pg, _p):
        assert pg.evaluate(STATE)["checked"] is True
        assert "sfx" in pg.evaluate("chosenKinds()")
        assert pg.evaluate(
            "document.getElementById('kFree').checked") is True
        assert pg.evaluate(
            "document.getElementById('kSfxBig').checked") is True
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", FORMATS)
def test_the_tick_is_the_whole_answer(medium):
    """It used to be dropped on the way out even when ticked - `chosenKinds`
    carried `&& sfxIsDetectable()`. No such force in either direction now:
    ticked asks for them, unticked leaves them out."""
    def go(pg, _p):
        assert pg.evaluate("chosenKinds()").count("sfx") == 1
        pg.evaluate("document.getElementById('kSfx').click()")
        assert "sfx" not in pg.evaluate("chosenKinds()")
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
        # The by-hand route used to be spelled out here as well. It went when
        # lee asked for the row to be short -- *"it shoud be in one box and
        # just be ine or 2 line"* -- and drawing a box then pressing `3` still
        # works exactly as it did; it is simply no longer explained in a
        # dialog that he found *"way too crowded ans tetx havvy"*.
        assert "kSfxByHand" not in s["rowText"]
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", FORMATS)
def test_the_row_says_the_pass_may_include_mistakes(medium):
    """lee: *"jus add a warning to the sfx box saying that its that 100%"*.

    47 of 49 is worth running and is not worth trusting blind, and those are
    different statements. The warning names the three ways it is wrong - a
    box short of the end of a stroke, two effects in one box, a faint one
    missed - because a bare caution tells somebody to worry without telling
    them what to look for.

    It sits BESIDE THE TICK, which is the only place it can change a
    decision: after the run it is a complaint, before it is a choice.

    The pill said **"Not exact"** first. lee, reading it back: *"insatd of
    saying no exact say may include mistake"* - and he is right that the two
    are different claims. "Not exact" says every box is a bit off, which is
    not what the measurement says; 47 of 49 boxes are right and two are
    wrong. "May include mistakes" is that, and it is also the sentence a
    reader with no English to spare can still parse.
    """
    def go(pg, _p):
        got = pg.evaluate("""()=>{
          const p=document.getElementById('kSfxRough');
          const row=document.getElementById('kSfx').closest('label');
          return {row: row.textContent,
                  pill: p ? p.textContent : null,
                  pillShown: p ? getComputedStyle(p).display!=='none' : false,
                  amber: p ? p.classList.contains('warn') : false};}""")
        assert got["pillShown"] and got["pill"], got
        assert got["pill"].strip().lower() == "may include mistakes", got["pill"]
        # Collapsed, because the markup wraps and "share one box" arrives as
        # "share one\n        box" - a phrase that a line break can hide is
        # a phrase this test would report as missing when it is on the screen.
        low = " ".join(got["row"].split()).lower()
        for fault in ("stroke", "one box", "missed"):
            assert fault in low, (fault, got["row"])
        # ...and the pill is the caution colour, not the same grey as every
        # other label on the screen.
        assert got["amber"], "the pill is not marked as a warning"
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", FORMATS)
def test_the_box_is_not_shouted(medium):
    """lee, with a screenshot of SOUND EFFECTS / NOT EXACT / LEAVE OUT
    EFFECTS OVER 300PX: *"what is this all caps"*.

    `.optbox` has carried `text-transform:none` since the box was built and
    it never did anything: the rows are `label`s and the bare `label` rule
    sets `uppercase`, which beats a value inherited from the parent whatever
    the parent's selector looks like. Asserted on the COMPUTED style of every
    row in the box, because that is the only place the bug was visible - the
    markup was innocent the whole time.
    """
    def go(pg, _p):
        got = pg.evaluate("""()=>{
          const box=document.getElementById('kSfx').closest('.optbox');
          return [...box.querySelectorAll('label,b,i,span')].map(
            e=>getComputedStyle(e).textTransform);}""")
        assert got, "the box has no rows"
        assert set(got) == {"none"}, got
    _serve(go, medium=medium)


@pytest.mark.parametrize("medium", FORMATS)
def test_the_copy_is_not_written_about_one_chapter(medium):
    """lee: *"dont mak it spacific to any mnahwa"*.

    Two numbers in this box were measured on his own pages and were false
    anywhere else. **"over 300px"** is the one that mattered: `BIG_SFX` is a
    share of the page width, `300/690` = 0.435, so a chapter scanned at
    1400px cuts at 609px and the label told the reader the wrong number.
    **"15 of 52 on a chapter"** was true of one chapter and of nothing else.

    Neither is replaced with a different number - the setting is said as the
    share it actually is, and as of `BIG_SFX_BY_MEDIUM` that share is the
    FORMAT's. `sayHowBig` writes the sentence from the number the server
    sent, so the copy cannot drift from the cut.
    """
    from mangatl.project import big_sfx_share

    def go(pg, _p):
        text = pg.evaluate(
            """()=>document.getElementById('kSfx')
                 .closest('.optbox').textContent""")
        for hard in ("300px", "15 of 52", "690"):
            assert hard not in text, (hard, text)
        want = "%d%%" % round(big_sfx_share(medium) * 100)
        assert want in text, (medium, want, text)
    _serve(go, medium=medium)


def test_the_share_the_copy_names_is_the_share_the_code_cuts_at():
    """The sentence is generated from the number, so what has to hold is that
    the number itself is still in the range that was measured."""
    from mangatl.project import BIG_SFX
    assert 0.36 <= BIG_SFX <= 0.48, BIG_SFX


def test_a_manga_page_is_several_panels_wide_so_the_bar_is_smaller():
    """lee: *"can you swith teh manga version of this to be something more
    appropriate to manga"*.

    0.435 of the page was measured on a webtoon, where the page IS the panel.
    Over 23 pages of manga **one sound effect in sixty-two** reached it -- the
    tick was doing nothing at all. Those pages split into 75 panels of median
    width 0.56 of the page, and 0.435 of a panel is 0.244 of the page.
    """
    from mangatl.project import big_sfx_share, BIG_SFX
    assert big_sfx_share("manga") < BIG_SFX
    assert 0.21 <= big_sfx_share("manga") <= 0.28


def test_the_strip_formats_keep_the_number_they_were_measured_on():
    """Nothing here was measured on a manhwa or a manhua, and both are read as
    one column, which is the shape 0.435 came off."""
    from mangatl.project import big_sfx_share, BIG_SFX
    for medium in ("manhwa", "manhua", None, "", "nonsense"):
        assert big_sfx_share(medium) == BIG_SFX, medium


def test_the_page_is_told_which_share_applies():
    from where import PKG
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert '"big_sfx_share": big_sfx_share(self.medium),' in src
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "proj.big_sfx_share" in js


def test_the_cut_uses_the_formats_own_share():
    """The sentence and the cut have to move together. This is the cut."""
    from where import PKG
    src = (PKG / "project.py").read_text(encoding="utf-8")
    assert "big_sfx_share(self.medium))" in src


def test_a_manga_effect_that_crosses_a_panel_is_left_out():
    from mangatl.project import big_sfx, big_sfx_share
    from mangatl.models import TextRegion

    def r(w, kind="sfx"):
        return TextRegion(id=0, bbox=(0, 0, w, 50), kind=kind)
    page = 960
    # 0.24 of the page is about half a panel on these pages; 0.30 is most of
    # one. The first survives, the second does not, and a BALLOON of either
    # size survives both -- paper with type on it is what the cleaner is best
    # at, which is why `big_sfx` only ever looks at sound effects.
    kept = big_sfx([r(220), r(290), r(290, "bubble")], page,
                   big_sfx_share("manga"))
    assert [q.bbox[2] for q in kept] == [220, 290]
    assert [q.kind for q in kept] == ["sfx", "bubble"]
    # ...and on a webtoon strip the same 290 is well under the bar.
    kept = big_sfx([r(290)], 690, big_sfx_share("manhwa"))
    assert len(kept) == 1


def test_the_warning_is_only_on_the_sound_effect_row():
    """The other two finders are not being apologised for. Bubble text is
    described as "the reliable one" and it earns that."""
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    top = html.split('id="kSfx"')[0]
    assert "kSfxRough" not in top, "the warning is above the row it is about"
    assert html.count('class="pill warn"') == 1, \
        "the caution pill has spread to something else"


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
    behaviour on its own - the server silently, which is worse."""
    import mangatl.project as P
    assert not hasattr(P, "NO_SFX_MEDIA")
    assert not hasattr(P, "detectable_kinds")
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    # The DEFINITION, not the word: the comment beside `chosenKinds` names the
    # call it used to carry, and a note saying what was removed is the reason
    # the removal is legible. A call left behind with no definition would be a
    # ReferenceError, and the three browser tests above assert on `pageerror`
    # for every format - so that half is covered by running it, not by reading.
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
    distinction the old rule turned on - and it still holds. Nothing here
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
    """Not just in the source - the panel is built from a template string and
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


# ------------------------------- ...and the big ones, which clean badly

def test_the_big_ones_are_left_out_by_default():
    """lee: *"i tested the clenner on them an the big one are always very bad
    while the midium to small one always clean up nice so i wan to cut off the
    big ones"*.

    A CLEANING rule wearing a detection rule's clothes, and worth saying so.
    Nothing is wrong with these boxes AS boxes - measured over the 52 sound
    effects of a 46-page chapter, all sixteen over a twentieth of the page
    hold real writing, and the chapter's only two junk boxes are its two
    SMALLEST (0.79% and 0.51%). Size does not sort right from wrong. What it
    sorts is what the cleaner can put back through the hole.
    """
    from types import SimpleNamespace

    from mangatl.project import BIG_SFX, big_sfx
    r = lambda w, h, k: SimpleNamespace(bbox=(0, 0, w, h), kind=k)
    big, small = r(338, 539, "sfx"), r(116, 155, "sfx")
    kept = big_sfx([big, small], 690)
    assert small in kept and big not in kept
    # 300px on a 690-wide page, which is the number lee picked off the sizes.
    assert round(BIG_SFX * 690) == 300

    # The LONGEST side, not the height. 001#1 is 499x242 - wide and flat is
    # as big a hole for the cleaner as tall and narrow, and a height-only
    # rule sails straight past it.
    flat = r(499, 242, "sfx")
    assert flat not in big_sfx([flat], 690)

    # ...and it is against the WIDTH, not the area. lee: *"i domnt think ratio
    # is a good ideo ... because all the ages are not the same sizes"*. His
    # pages are all 690 wide and run 1591 to 3713 tall, so the same effect on
    # a short page and on a long one has to get the same answer.
    for tall in (1591, 2131, 3713):
        assert big_sfx([big], 690) == [], tall
        assert big_sfx([small], 690) == [small], tall


def test_only_sound_effects_are_measured_this_way():
    """A caption plate or a wide balloon can be a tenth of a webtoon page and
    clean perfectly - it is paper with type on it, the case the cleaner is
    best at."""
    from types import SimpleNamespace

    from mangatl.project import big_sfx
    wide = [SimpleNamespace(bbox=(0, 0, 600, 700), kind=k)
            for k in ("bubble", "narration", "freefloat")]
    assert len(big_sfx(wide, 690)) == 3


def test_a_page_of_no_known_size_drops_nothing():
    """A share of nothing is not a measurement, and silently dropping every
    sound effect would look exactly like the detector failing."""
    from types import SimpleNamespace

    from mangatl.project import big_sfx
    huge = [SimpleNamespace(bbox=(0, 0, 900, 900), kind="sfx")]
    assert len(big_sfx(huge, 0)) == 1


def test_absent_reads_as_on_everywhere():
    """Three places have to agree that not saying anything means leave the big
    ones out: the endpoint, `Project.detect`, and the browser. A default that
    is on in two of the three is a run whose result depends on which door it
    came through."""
    import inspect

    from mangatl.project import Project
    from where import PKG
    assert "no_big_sfx: bool = True" in inspect.getsource(Project.detect)
    ed = (PKG / "editor.py").read_text(encoding="utf-8")
    assert 'body.get("no_big_sfx") is not False' in ed
    js = (PKG / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    assert "$('kSfxBig') ? $('kSfxBig').checked : true" in js
    # ...and it is SENT on both routes, or "this page only" quietly differs
    # from "every page".
    assert js.count("no_big_sfx:noBig") == 2


@pytest.mark.parametrize("medium", FORMATS)
def test_the_sub_tick_is_under_the_row_it_belongs_to(medium):
    def go(pg, _p):
        got = pg.evaluate("""()=>{
          const b=document.getElementById('kSfxBig');
          const s=document.getElementById('kSfx');
          if(!b||!s) return null;
          return {checked:b.checked, disabled:b.disabled,
                  after: !!(s.compareDocumentPosition(b) &
                            Node.DOCUMENT_POSITION_FOLLOWING),
                  indented: parseInt(getComputedStyle(
                     b.closest('label')).paddingLeft||'0',10)
                    > parseInt(getComputedStyle(
                     s.closest('label')).paddingLeft||'0',10),
                  text: b.closest('label').textContent};}""")
        assert got, "the sub-tick is not on the screen"
        assert got["checked"], "it has to start ticked"
        assert not got["disabled"]
        assert got["after"], "it is above the row it belongs to"
        # The indent is `padding-left` on `.optrow.sub` and not a margin -
        # the rows are flex children of one bordered box, so the inset has to
        # be inside the row or the box's own edge moves with it. Measured
        # against the row ABOVE rather than against zero, which is what makes
        # this an assertion about the two reading as parent and child.
        assert got["indented"], "it does not read as a sub-setting"
        assert "biggest effects" in got["text"], got["text"]
    _serve(go, medium=medium)
