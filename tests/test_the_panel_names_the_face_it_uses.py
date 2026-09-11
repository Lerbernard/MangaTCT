"""Box types shows the face a row will ACTUALLY typeset in.

lee sent one screenshot of the panel and no words. It reads:

    BUBBLE TEXT
      Regular speech    ComicNeue-Bold
      Caption box       AnimeAce.ttf        x
      Thought bubble    AnimeAce.ttf        x
      Burst / shout     AnimeAce.ttf        x
      Whisper           AnimeAce.ttf        x
    FREEFLOAT TEXT
      Freefloat text    ComicNeue-Bold
      ...
    SOUND EFFECT
      Sound effect      ComicNeue-Bold
      Big / impact      CCWildWords.ttf     x
      Small / background CCWildWords.ttf    x

Every line of that is wrong, in two different ways, and neither had anything to
do with the pages - which come out in Comic Neue, Bangers and Luckiest Guy, as
they should.

## The nine rows naming a font that is gone

`AnimeAce.ttf` and `CCWildWords.ttf` were removed from `fonts/` on 2026-08-26
because this app may not redistribute either (see `fonts/LICENSES.md`), and
they are not on lee's disk any more. His saved `custom_kinds` still name them.

The server has always coped: `typeset.font_for` SKIPS a step whose file cannot
be opened, which is the guard that stops a dead path reaching the renderer and
drawing nothing at all. The browser did not - `fontPathFor` returned the saved
string - so the panel printed a face the page would never use.

A row that names the wrong face is worse than a row that says nothing, because
it is an answer.

## The three rows showing the first font in the list

`Regular speech`, `Freefloat text` and `Sound effect` all read `ComicNeue-Bold`.
Only the first is right. The others are `ComicNeue-Regular` and
`Bangers-Regular`.

Two causes, one on top of the other. The family rows had no "nothing chosen"
option, so a `<select>` with no matching value showed its first entry as though
somebody had picked it - the exact defect the sub-type rows had fixed years
earlier and that never crossed to the row above them.

And under that: `fontPathFor` stopped at the project's own font. Everything
past that - `typeset.DEFAULT_FONTS`, a face per kind - lives on the server and
the browser had never been told. So there was no right answer available to
show even if the option had been there.

## The fix, and the shape of it

The browser is not given a copy of `DEFAULT_FONTS`; it is given the ANSWER.
`/api/fonts` now carries `defaults`, resolved by `editor.shipped_kind_fonts()`
through the real `font_for` against an empty config. Duplicating the table in
JavaScript is how these two got out of step in the first place.

Nothing is written back to the settings. The dead path stays where it is, so
putting the font back in your own fonts folder brings the old choice with it.
"""
import time
import shutil
import threading

import numpy as np
import pytest

import browserpool
from scratch import scratch

cv2 = pytest.importorskip("cv2")

from mangatl import kinds as K
from mangatl import typeset as T


# ------------------------------------- what the server tells the browser

def test_the_server_answers_for_every_kind_the_panel_lists():
    from mangatl import editor
    got = editor.shipped_kind_fonts()
    for key in list(K.FAMILIES) + list(K.PRELOAD_KEYS):
        assert key in got, key
        assert T.usable_font(got[key]), (key, got[key])


def test_and_the_answers_are_the_ones_the_typesetter_would_use():
    """Not a second table that agrees today. The endpoint calls `font_for`, so
    there is one place a default is decided and this is a view of it."""
    from mangatl import editor
    got = editor.shipped_kind_fonts()
    blank = T.TypesetConfig(font_path="")
    for key, path in got.items():
        assert path == T.font_for(blank, key), key


def test_it_is_asked_with_no_project_font():
    """The project's own font is a step the BROWSER has and can apply itself.
    Asking with it in hand would answer this question with that font twelve
    times over and tell the panel nothing it did not already know."""
    from mangatl import editor
    got = editor.shipped_kind_fonts()
    assert len(set(got.values())) > 1, got
    assert got["sfx"] != got["bubble"], got


def test_the_endpoint_carries_it():
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor)
    assert '"defaults": shipped_kind_fonts()' in src


def test_the_browser_is_given_the_answer_and_not_the_table():
    """`DEFAULT_FONTS` stays in one place. A copy in JavaScript is exactly how
    the panel and the typesetter came to disagree, and a second copy would only
    schedule the next disagreement.

    Asked as "no font FILENAME is written into the browser", which is what a
    copy of the table would need. The first version of this searched for the
    word "ComicNeue" and went red on the comment explaining the bug - prose
    naming a face is not a table, and a guard that cannot tell them apart
    punishes writing the reason down.
    """
    import re
    from where import PKG
    for name in ("project.js", "project-io.js", "frames.js"):
        js = (PKG / "static" / "js" / name).read_text(encoding="utf-8")
        # A filename in a string or a key - the only forms a table can take.
        hits = re.findall(r'["\'][^"\']*\.(?:ttf|otf)["\']', js, re.I)
        assert not hits, (name, hits)


# ------------------------------------------------------- and on the screen

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
    # ...and lee's own settings, which is the whole fixture: a project font and
    # nine sub-type fonts naming two files that no longer exist anywhere.
    gone = str(PKG_FONTS / "AnimeAce.ttf")
    wild = str(PKG_FONTS / "CCWildWords.ttf")
    p.settings["font"] = gone
    for s in p.settings["custom_kinds"]:
        s["font"] = wild if s["family"] == "sfx" else gone
    p.save()
    return p


from where import PKG
PKG_FONTS = PKG / "fonts"


@pytest.fixture()
def ed(tmp_path):
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    p = _project(str(tmp_path / "dead"))
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
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        try:
            yield pg, p, errs
        finally:
            srv.shutdown(); srv.server_close(); editor.PROJECT = was


def _rows(pg):
    """{label: the face this row says it will use}."""
    return pg.evaluate("""(()=>{
        const out={};
        for(const r of document.querySelectorAll('#ckList .ckrow')){
          const n=r.querySelector('.cknm');
          const s=r.querySelector('select.fontsel');
          if(!n||!s) continue;
          const label=n.value!==undefined?n.value:n.textContent;
          const opt=s.options[s.selectedIndex];
          out[label.trim()]=(opt&&(opt.dataset.name||opt.textContent)||'').trim();
        }
        return out;})()""")


def test_no_row_names_a_font_that_is_not_there(ed):
    """The screenshot, as an assertion. Nine rows named a file that had been
    deleted from the fonts folder a day earlier."""
    pg, _p, errs = ed
    said = _rows(pg)
    assert said, "the panel drew no rows"
    for label, face in said.items():
        assert "AnimeAce" not in face or "missing" in face, (label, face)
        assert "CCWildWords" not in face or "missing" in face, (label, face)
    assert not errs, errs[:2]


def test_each_row_names_the_face_the_typesetter_would_pick(ed):
    """The positive half. Every one of these is a default the SERVER decides -
    the panel is only reporting it, and if the two disagree the panel is
    wrong."""
    pg, _p, errs = ed
    said = _rows(pg)
    want = {"Regular speech": "ComicNeue-Bold",
            "Caption box": "ComicNeue-Regular",
            "Thought bubble": "ComicNeue-Italic",
            "Fancy bubble": "ComicNeue-Regular",
            "Burst / shout": "Bangers-Regular",
            "Whisper": "ComicNeue-Regular",
            "Freefloat text": "ComicNeue-Regular",
            "Narration on the art": "ComicNeue-Regular",
            "Aside / mutter": "ComicNeue-Regular",
            "Sign or label": "ComicNeue-Regular",
            "Sound effect": "Bangers-Regular",
            "Big / impact": "Bangers-Regular",
            "Small / background": "Kalam-Regular"}
    for label, face in want.items():
        assert label in said, (label, sorted(said))
        assert said[label].startswith(face), (label, said[label], face)
    assert not errs, errs[:2]


def test_the_three_family_rows_are_not_all_the_same(ed):
    """The tell in lee's screenshot: `Regular speech`, `Freefloat text` and
    `Sound effect` all read ComicNeue-Bold, which is what a `<select>` with no
    matching value shows - its first entry, as though it had been chosen."""
    pg, _p, errs = ed
    said = _rows(pg)
    fams = {said["Regular speech"], said["Freefloat text"],
            said["Sound effect"]}
    assert len(fams) == 3, fams
    assert not errs, errs[:2]


def test_the_panel_says_which_fonts_are_gone(ed):
    """Not silently right. Somebody who chose Anime Ace deliberately needs to
    know it is not being used, or the panel has quietly overruled them and
    looks like it agreed.

    Said ONCE, above the list, and not on the rows. The first version put
    "— AnimeAce.ttf is missing" after the face name inside the picker, which is
    280px wide: every row rendered "ComicNeue-Regular — AnimeAce.ttf is mis".
    Nine truncated warnings say less than one whole sentence, and they bury the
    answer the row exists to give.
    """
    pg, _p, errs = ed
    note = pg.evaluate(
        "(document.querySelector('#ckList .ckgone')||{}).textContent||''")
    assert "AnimeAce.ttf" in note, note
    assert "CCWildWords.ttf" in note, note
    assert "not installed" in note, note
    # ...and the rows are left to name the face, undiluted.
    for label, face in _rows(pg).items():
        assert "missing" not in face and "installed" not in face, (label, face)
    assert not errs, errs[:2]


def test_and_the_row_itself_carries_it_as_a_tooltip(ed):
    """The banner names the fonts; it cannot name the twelve rows. Hovering a
    row is how you find out whether THIS one is affected."""
    pg, _p, errs = ed
    tips = pg.evaluate("""[...document.querySelectorAll('#ckList select.fontsel')]
        .map(s=>s.title||'')""")
    assert any("AnimeAce.ttf is not installed" in t for t in tips), tips
    assert not errs, errs[:2]


def test_the_font_list_keeps_the_real_case_of_every_path():
    """The Windows-only bug, and the reason it took two rounds to find: it is
    INVISIBLE on Linux and macOS.

    `find_fonts` built its bundled roots with `os.path.normcase(...)` and then
    WALKED them. On Windows `normcase` lowercases a path, so `os.walk` yielded
    a lowercased `dirpath` and every font arrived at the browser as
    `c:\\users\\leema\\...\\comicneue-bold.ttf` - while `typeset._bundled`
    returns the real-case path. Box types compares the two to name each row's
    face, matched nothing, and printed "Project default" twelve times.

    lee, on the second screenshot of it: *"is it because my project isnt new
    that its stuck like this"* - a fair guess, and no: it was his operating
    system. On Linux `normcase` is the identity function, so every test of this
    panel passed here while the panel was broken on the only machine that
    matters.

    NORMCASE IS FOR COMPARING, NOT FOR KEEPING.

    So the test MAKES this machine behave like Windows, and it takes TWO things
    to do that. The obvious one is `os.path.normcase`, replaced with the
    lower-casing one Windows has. The one that is easy to miss is a folder with
    an upper-case letter IN IT: this repo lives at `/root/mangatl/fonts`, which
    lower-cases to itself, so the first version of this test passed against the
    broken code - the only capital in the answer was in the FILE name, which
    comes from `os.walk`'s file list and was never at risk.

    `find_fonts` looks in `os.getcwd()/fonts`, so the fixture is a directory
    named with capitals, made the working directory, with a font in it.

    And that font has to carry a name no other root can answer to. The walk
    de-duplicates by FILE NAME, so `Chewy-Regular.ttf` was answered by the
    repo's own `fonts/` folder - the first candidate, real-cased, on a path
    with no capital to lose - and the fixture in the working directory was
    never reached. The face is copied under a name that exists nowhere else,
    so the mixed-case root is the only place it can come from.

    A test for a platform difference has to simulate the platform, and a test
    for a case difference has to supply a case to lose.
    """
    import os
    import shutil
    import mangatl.editor as ed_mod
    from mangatl import editor
    root = scratch("_tmp_MixedCase_Fonts")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "fonts"), exist_ok=True)
    only = "ZzOnlyHere-Regular"
    shutil.copy(str(PKG_FONTS / "Chewy-Regular.ttf"),
                os.path.join(root, "fonts", only + ".ttf"))
    here, was = os.getcwd(), ed_mod.os.path.normcase
    try:
        os.chdir(root)
        ed_mod.os.path.normcase = lambda s: s.lower()   # ...as Windows does
        got = [f for f in editor.find_fonts()
               if f["name"] == only and f.get("bundled")]
    finally:
        ed_mod.os.path.normcase = was
        os.chdir(here)
        shutil.rmtree(root, ignore_errors=True)

    # Two ways for the old code to fail this, and they are the same defect
    # seen from two filesystems. Here, where names are case-SENSITIVE, walking
    # the lower-cased root finds no such directory and the face is missing
    # altogether; on Windows the walk succeeds and hands back a lower-cased
    # path that nothing else in the app will match.
    assert got, ("the fixture font was not found as a bundled one - the "
                 "lower-cased root does not exist on this filesystem")
    path = got[0]["path"]
    assert "MixedCase" in path, \
        ("the directory came back lower-cased (%r) - normcase leaked into the "
         "list, and on Windows nothing will match these" % path)


def test_and_the_two_sides_agree_on_the_path_for_every_kind():
    """The comparison the panel actually makes. `shipped_kind_fonts` answers
    with `typeset.font_for`, the list comes from `find_fonts`, and the browser
    matches one against the other - so a path that the two spell differently is
    a row that cannot name its face."""
    from mangatl import editor
    known = {f["path"] for f in editor.find_fonts()}
    for kind, path in editor.shipped_kind_fonts().items():
        assert path in known, (kind, path)


def test_and_the_browser_compares_them_forgivingly_anyway():
    """Belt and braces, and worth it: the browser cannot know what filesystem
    it is looking at, and one honest comparison is cheaper than trusting every
    path-building site in the app to agree forever. Nothing may compare a font
    path with `===`."""
    import re
    from where import PKG
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "function samePath(" in js
    stray = re.findall(r"f\.path\s*===", js)
    assert not stray, stray


def test_it_says_so_when_the_app_is_older_than_the_page(ed):
    """lee sent a screenshot of this panel with "Project default" on all twelve
    rows and asked why. It was not a font problem at all: the app is a
    long-running Python process and these pages are files on disk, so copying a
    new build over the top leaves the two on DIFFERENT builds until somebody
    restarts it. His server predated `shipped_kind_fonts`, so the answer came
    back with no `defaults` in it.

    The panel then printed the one thing it says when it does not know - twelve
    times, looking exactly like an answer. Which is the same sin this whole
    file is about: a row that names the wrong face is worse than a row that
    says nothing.

    Reproduced by emptying what the server sent, which is what an older server
    sends.
    """
    pg, _p, errs = ed
    pg.evaluate("SERVER_STALE=true; KIND_DEFAULTS={}; renderCustomKinds()")
    browserpool.settled(pg)
    note = pg.evaluate(
        "(document.querySelector('#ckList .ckgone')||{}).textContent||''")
    assert "Restart the app" in note, note
    assert not errs, errs[:2]


def test_and_the_stale_flag_is_the_key_being_absent_not_empty():
    """An empty answer is a server that looked and found nothing - a machine
    with no usable fonts at all, which is a different problem and has its own
    message. A MISSING key is a server that was never asked the question."""
    from where import PKG
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "hasOwnProperty.call(f,'defaults')" in js
    assert "SERVER_STALE=!(" in js


def test_and_no_banner_when_every_font_is_there(ed):
    """The other half. A note that is always on screen is furniture, and
    nothing about a project with its fonts in place needs a warning."""
    pg, _p, errs = ed
    good = str(PKG_FONTS / "Chewy-Regular.ttf")
    pg.evaluate("""(()=>{
        proj.settings.font=%r;
        for(const k of proj.settings.custom_kinds) k.font='';
        renderCustomKinds();})()""" % good)
    browserpool.settled(pg)
    assert pg.evaluate("!document.querySelector('#ckList .ckgone')")
    assert not errs, errs[:2]


def test_the_dead_setting_is_not_quietly_rewritten(ed):
    """Showing the truth and CHANGING the truth are different things. The saved
    path stays, so putting the font back where the app can find it brings the
    old choice back with it - which is the arrangement `fonts/LICENSES.md`
    promises anybody who has licensed one of the two."""
    pg, p, errs = ed
    said = _rows(pg)
    assert said, "the panel drew no rows"
    subs = {s["key"]: s.get("font") or "" for s in p.settings["custom_kinds"]}
    assert any("AnimeAce" in v for v in subs.values()), subs
    assert "AnimeAce" in (p.settings.get("font") or "")
    assert not errs, errs[:2]


def test_choosing_a_face_still_works(ed):
    """The blank option is now selected on rows that HAVE a saved font, so the
    thing to check is that picking a real one still writes it - the fix must
    not have turned the row into a label."""
    pg, p, errs = ed
    good = str(PKG_FONTS / "Chewy-Regular.ttf")
    pg.evaluate("setKindFont('thought', %r)" % good)
    # WAITED FOR ON THE SERVER, not for two animation frames.
    #
    # `setKindFont` calls `saveSettings()` without awaiting it, so what this
    # asserts is the far end of a network round trip while `browserpool.settled`
    # is a pair of `requestAnimationFrame`s. The test has always been a race
    # and only ever won it because the panel had nothing else to do in those
    # two frames; the row specimens gave it twelve pictures to fetch and it
    # started losing. Waiting for the thing being asserted is not a loosening.
    def _saved():
        return next((s for s in p.settings["custom_kinds"]
                     if s["key"] == "thought"), {}).get("font") == good
    for _ in range(100):
        if _saved():
            break
        browserpool.settled(pg)
        time.sleep(0.05)
    sub = next(s for s in p.settings["custom_kinds"] if s["key"] == "thought")
    assert sub["font"] == good, sub
    assert _rows(pg)["Thought bubble"].startswith("Chewy"), _rows(pg)
    assert not errs, errs[:2]


# ------------------------------------------- and the row drawn in that face

def test_every_row_is_drawn_in_the_face_it_names(ed):
    """lee, looking at a column of twelve font NAMES: *"can youu show the font
    for every box trype"*.

    A name is not a face. Twelve rows reading twelve different names look
    exactly as much like an answer as twelve rows reading the same one, and
    neither tells you what the page will come out looking like - which is the
    only question this panel exists to answer.

    So each row carries its own label, rendered in its own face by the server
    from the actual file. `/fontsample` is the same endpoint the font
    dropdowns used to use, and it is here rather than there for the reason it
    left there: a sample per row is an HTTP request per row, and the dropdowns
    have four hundred rows. This panel has twelve, rows that share a face
    share a URL and therefore the browser's cache, and the server keeps the
    last 600 renders.
    """
    pg, _p, errs = ed
    # Waited for, because a picture is a round trip: two animation frames is
    # long enough for the twelve `<img>`s to exist and not for one of them to
    # have arrived.
    # Not a fixed twelve: the number of rows is the number of box types, and
    # that list grows - `Fancy bubble` joined it on 2026-08-28. A test that
    # counts rows has to count the same thing the panel does.
    rows = len(K.FAMILIES) + len(K.PRELOAD_KEYS)
    pg.wait_for_function(
        """(n) => {const a=[...document.querySelectorAll('#ckList .cksamp img')];
                  return a.length===n && a.every(i=>i.complete);}""",
        arg=rows, timeout=10000)
    got = pg.evaluate("""(()=>[...document.querySelectorAll('#ckList .cksamp img')]
        .map(i=>({w:i.naturalWidth, src:i.getAttribute('src'), t:i.title})))()""")
    assert len(got) == rows, ("a row has no specimen", len(got))
    for g in got:
        assert g["w"] > 0, ("a specimen did not load", g)
        assert "/fontsample?p=" in g["src"], g
    assert not errs, errs[:2]


def test_the_specimen_is_the_face_the_row_names(ed):
    """It is drawn from `fontPathFor` - the same chain `typeset.font_for`
    walks - so a row cannot say one face and show another."""
    pg, _p, _e = ed
    said = _rows(pg)
    shown = pg.evaluate("""(()=>{
        const out={};
        for(const fam of document.querySelectorAll('#ckList .ckfam'))
          for(const el of fam.children){
            if(!el.classList.contains('ckrow')) continue;
            const n=el.querySelector('.cknm');
            const s=el.nextElementSibling;
            if(!n||!s||!s.classList.contains('cksamp')) continue;
            const label=n.value!==undefined?n.value:n.textContent;
            const img=s.querySelector('img');
            out[label.trim()]=img?img.title:'';
          }
        return out;})()""")
    assert shown, "no specimen sits under any row"
    for label, face in said.items():
        assert label in shown, (label, shown)
        assert shown[label] == face, (label, face, shown[label])


def test_the_specimen_shows_the_type_s_own_name(ed):
    """"Burst / shout" drawn in the face bursts are set in needs no legend and
    no second column - the row IS the specimen. The word "sample" twelve times
    would have needed both."""
    pg, _p, _e = ed
    alts = pg.evaluate(
        "[...document.querySelectorAll('#ckList .cksamp img')].map(i=>i.alt)")
    assert any(a.startswith("Burst / shout,") for a in alts), alts
    assert any(a.startswith("Big / impact,") for a in alts), alts


def test_an_unset_project_font_stays_unset_across_a_save():
    """lee, on the installed copy, every row reading ComicNeue-Italic: *"we had
    a bunch of set defaults"*. The project font select had no blank entry, so
    with nothing set it showed its first face - the most recent one - and the
    first Save wrote that face into `font`, where it sits ABOVE the shipped
    per-kind defaults and hid all of them. The select carries a blank first
    now, selected while nothing is set, and only a usable path is put on it."""
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    body = js[js.index("function rebuildFontSelects("):js.index("function fontName(")]
    assert "<option value=\"\">Shipped default</option>" in body
    assert "$('font').value = fontUsable(want) ? want : '';" in body
