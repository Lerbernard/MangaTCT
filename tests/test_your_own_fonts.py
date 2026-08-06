"""Fonts you added, and the ones you keep reaching for.

lee: *"Allow uploading fonts in the setting and a way to remove the fonts that
were uploaded - the fonts should presist to new projects"* and *"Add a recent
fonts to the top of the font search top 5"*.

Two rules do all the work here:

* An uploaded face belongs to the PERSON. It is kept beside the app, not in the
  chapter folder, so the next project already has it — and so that copying a
  new version of the editor over the top cannot take it away.
* A path that arrives from a browser is not a path until it has been checked.
  An upload endpoint that takes a name, and a delete endpoint that takes a
  path, are a file writer and a file remover if they trust what they are given.
"""
import json
import os
import shutil
import threading
from http.server import ThreadingHTTPServer

import pytest

import browserpool

from mangatl import userdata
from scratch import scratch
from where import PKG


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    return tmp_path


def _real_font() -> bytes:
    """A font file the typesetter would actually accept, taken from whatever this
    machine has — a made-up byte string would be refused for the right reason
    and prove nothing about the ones that should get through."""
    from mangatl import typeset
    p = typeset.default_font_path()
    with open(p, "rb") as fh:
        return fh.read()


# ------------------------------------------------------ it belongs to you

def test_an_uploaded_font_lands_outside_any_project(home):
    p = userdata.add_font("Wild.ttf", _real_font())
    assert os.path.isfile(p)
    assert os.path.dirname(p) == userdata.fonts_dir()
    assert "home" in p


def test_it_is_still_there_for_the_next_project(home):
    """The whole ask. Nothing about the list is keyed to a chapter, so opening
    a different one changes nothing about it."""
    userdata.add_font("Wild.ttf", _real_font())
    names = [os.path.basename(f) for f in userdata.uploaded_fonts()]
    assert names == ["Wild.ttf"]
    # a brand new project, made from nothing
    from mangatl.project import Project
    root = str(home / "fresh")
    Project(None, root)
    assert [os.path.basename(f) for f in userdata.uploaded_fonts()] == \
        ["Wild.ttf"]
    shutil.rmtree(root, ignore_errors=True)


def test_the_typesetter_looks_in_there_too(home):
    """Offering a face in the picker and then not finding it when the page is
    typeset is worse than not offering it."""
    from mangatl import typeset
    typeset._font_dirs.cache_clear()
    try:
        assert userdata.fonts_dir() in typeset._font_dirs()
    finally:
        typeset._font_dirs.cache_clear()


def test_uploading_the_same_face_twice_replaces_it(home):
    """You are fixing a bad copy, not collecting them."""
    userdata.add_font("Wild.ttf", _real_font())
    userdata.add_font("Wild.ttf", _real_font())
    assert len(userdata.uploaded_fonts()) == 1


# ------------------------------------------------------ what it refuses

def test_a_file_that_is_not_a_font_is_refused(home):
    with pytest.raises(ValueError):
        userdata.add_font("evil.ttf", b"this is not a font")
    assert userdata.uploaded_fonts() == []


def test_a_refused_file_does_not_stay_on_disk(home):
    """It is written before it can be opened — there is no other way to ask
    the font library about it. What must not happen is that the half-written
    file is left behind under a name the picker will later offer."""
    with pytest.raises(ValueError):
        userdata.add_font("evil.ttf", b"nope")
    left = os.listdir(userdata.fonts_dir()) if \
        os.path.isdir(userdata.fonts_dir()) else []
    assert left == [], left


def test_an_empty_file_is_refused(home):
    with pytest.raises(ValueError):
        userdata.add_font("empty.ttf", b"")


@pytest.mark.parametrize("given,want", [
    ("../../.ssh/authorized_keys", "authorized_keys.ttf"),
    ("..\\..\\Windows\\System32\\evil.ttf", "evil.ttf"),
    ("/etc/passwd", "passwd.ttf"),
    (".hidden.ttf", "hidden.ttf"),
    ("", "font.ttf"),
])
def test_the_name_cannot_be_a_path(given, want):
    assert userdata.safe_name(given) == want


def test_only_a_font_extension_is_kept():
    assert userdata.safe_name("x.exe") == "x.ttf"
    assert userdata.safe_name("x.otf") == "x.otf"


def test_removing_only_ever_removes_one_of_yours(home, tmp_path):
    """The path comes from the browser. A delete that trusts it is a file
    remover with a web interface."""
    outside = tmp_path / "precious.ttf"
    outside.write_bytes(_real_font())
    assert userdata.remove_font(str(outside)) is False
    assert outside.exists(), "it deleted a file outside the fonts folder"


def test_removing_a_font_that_is_not_there_says_so(home):
    assert userdata.remove_font(
        os.path.join(userdata.fonts_dir(), "ghost.ttf")) is False


def test_a_font_can_be_removed(home):
    p = userdata.add_font("Wild.ttf", _real_font())
    assert userdata.remove_font(p) is True
    assert userdata.uploaded_fonts() == []


# ------------------------------------------------------------- recents

def test_the_last_face_used_comes_first(home):
    a = userdata.add_font("A.ttf", _real_font())
    b = userdata.add_font("B.ttf", _real_font())
    userdata.note_font_used(a)
    userdata.note_font_used(b)
    assert userdata.recent_fonts()[0] == b


def test_using_one_again_moves_it_up_rather_than_repeating_it(home):
    a = userdata.add_font("A.ttf", _real_font())
    b = userdata.add_font("B.ttf", _real_font())
    userdata.note_font_used(a)
    userdata.note_font_used(b)
    userdata.note_font_used(a)
    assert userdata.recent_fonts() == [a, b]


def test_it_remembers_five(home):
    """lee asked for five. Past five, "recent" has stopped meaning anything and
    the list it sits above is pushed off the screen."""
    made = [userdata.add_font(f"F{k}.ttf", _real_font()) for k in range(8)]
    for p in made:
        userdata.note_font_used(p)
    got = userdata.recent_fonts()
    assert len(got) == 5
    assert got == list(reversed(made))[:5]


def test_a_face_that_has_gone_is_not_offered(home):
    """Deleted by hand, or removed in the settings. Offering it means a picker
    row that does nothing."""
    a = userdata.add_font("A.ttf", _real_font())
    userdata.note_font_used(a)
    os.remove(a)
    assert userdata.recent_fonts() == []


def test_removing_a_font_takes_it_out_of_the_recents(home):
    a = userdata.add_font("A.ttf", _real_font())
    userdata.note_font_used(a)
    userdata.remove_font(a)
    assert userdata.recent_fonts() == []


def test_nothing_useful_is_remembered_about_a_path_that_is_not_there(home):
    userdata.note_font_used("/no/such/font.ttf")
    assert userdata.recent_fonts() == []


def test_a_broken_prefs_file_is_not_a_broken_editor(home):
    os.makedirs(userdata.user_dir(), exist_ok=True)
    with open(os.path.join(userdata.user_dir(), "prefs.json"), "w") as fh:
        fh.write("{not json at all")
    assert userdata.load_prefs() == {}
    assert userdata.recent_fonts() == []


# ------------------------------------------------------------- the editor

def _serve(fn, home_path, root=scratch("_tmp_fonts")):
    import urllib.request
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((60, 40, 3), 240, np.uint8))[1].tobytes())
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def call(path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if obj is not None else "GET")
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    try:
        return fn(p, call)
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def test_the_editor_takes_an_upload_and_answers_with_the_new_list(home):
    import base64

    def check(p, call):
        j = call("/api/font", {"do": "add", "files": [
            {"name": "Mine.ttf",
             "data": base64.b64encode(_real_font()).decode()}]})
        assert j["ok"] is True, j
        assert any(f["name"] == "Mine" for f in j["fonts"]), \
            "the new face was not in the answer"
        assert any(os.path.basename(u) == "Mine.ttf" for u in j["uploaded"])
    _serve(check, home)


def test_an_uploaded_face_is_always_offered(home):
    """`find_fonts` decides what is a typesetting font by looking at the name.
    Somebody who went to the trouble of uploading a face has already decided."""
    import base64
    from mangatl import editor

    def check(p, call):
        call("/api/font", {"do": "add", "files": [
            {"name": "zzzz.ttf",
             "data": base64.b64encode(_real_font()).decode()}]})
        row = [f for f in editor.find_fonts() if f["name"] == "zzzz"]
        assert row, "the uploaded face is missing from the list"
        assert row[0]["comic"] is True
        assert row[0]["uploaded"] is True
        # ...and it sits under its own letter with everything else. It used to
        # be pinned to the top of the list, in upload order; lee: *"the fonts
        # shoud be in aphabetical order with the new fonts"* — with, not
        # above. Always offered is the promise; first is not.
        names = [f["name"] for f in editor.find_fonts()]
        assert names == sorted(names, key=str.lower), names[:12]
    _serve(check, home)


def test_a_bad_upload_comes_back_with_a_reason_and_changes_nothing(home):
    import base64

    def check(p, call):
        j = call("/api/font", {"do": "add", "files": [
            {"name": "bad.ttf", "data": base64.b64encode(b"nope").decode()}]})
        assert j["ok"] is False
        assert "bad.ttf" in j["error"], j["error"]
        assert j["uploaded"] == []
    _serve(check, home)


def test_the_editor_removes_and_answers_with_the_new_list(home):
    import base64

    def check(p, call):
        call("/api/font", {"do": "add", "files": [
            {"name": "Mine.ttf",
             "data": base64.b64encode(_real_font()).decode()}]})
        path = userdata.uploaded_fonts()[0]
        j = call("/api/font", {"do": "remove", "path": path})
        assert j["ok"] is True, j
        assert j["uploaded"] == []
    _serve(check, home)


def test_the_editor_will_not_remove_a_font_it_did_not_put_there(home,
                                                                tmp_path):
    outside = tmp_path / "theirs.ttf"
    outside.write_bytes(_real_font())

    def check(p, call):
        j = call("/api/font", {"do": "remove", "path": str(outside)})
        assert j["ok"] is False
        assert outside.exists()
    _serve(check, home)


def test_the_font_list_carries_the_recents(home):
    """One answer, not two: the picker draws recents and the list together, and
    two round trips means it can render one and then jump."""
    import base64

    def check(p, call):
        call("/api/font", {"do": "add", "files": [
            {"name": "Mine.ttf",
             "data": base64.b64encode(_real_font()).decode()}]})
        path = userdata.uploaded_fonts()[0]
        call("/api/font", {"do": "used", "path": path})
        j = call("/api/fonts")
        assert j["recent"] == [path], j["recent"]
    _serve(check, home)


def test_a_newly_uploaded_face_can_be_typeset_with_at_once(home):
    """The bundled-folder list is worked out once and kept for the life of the
    process. A folder that did not exist when the editor started, and does now,
    is exactly the case that cache gets wrong."""
    import base64
    from mangatl import typeset

    def check(p, call):
        typeset._font_dirs()                       # warm it, as real use does
        call("/api/font", {"do": "add", "files": [
            {"name": "Mine.ttf",
             "data": base64.b64encode(_real_font()).decode()}]})
        assert userdata.fonts_dir() in typeset._font_dirs()
    _serve(check, home)


# ------------------------------------------------------- on the screen

def _browser(fn, home_path, root=scratch("_tmp_fontui")):
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl import editor
    from mangatl.project import Project
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((400, 300, 3), 245, np.uint8))[1].tobytes())
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1400, "height": 1000})
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


def test_the_recents_are_drawn_at_the_head_of_the_font_list(home):
    """The point of the whole thing: the face you always use is the first row,
    not somewhere in four hundred.

    Two native <optgroup>s now — the picker is a plain <select> again (see
    `fontWidget` in project.js), and a group is the native way to say the same
    thing the custom menu's "Recent" band said."""
    mine = userdata.add_font("Zzz.ttf", _real_font())
    userdata.note_font_used(mine)

    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const sel=document.querySelector('#ckList .ckfam .ckdef .ckft');
            const gs=[...sel.querySelectorAll('optgroup')];
            return {labels: gs.map(g=>g.label),
                    firstFont: gs[0] && gs[0].querySelector('option').value};})()""")
        assert got["labels"] == ["Recent", "All fonts"], got
        assert got["firstFont"] == mine, got
    _browser(check, home)


def test_with_nothing_used_yet_the_list_is_just_the_list(home):
    """An empty "Recent" heading above nothing is a row of furniture."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        n = pg.evaluate("""(()=>{
            const sel=document.querySelector('#ckList .ckfam .ckdef .ckft');
            return sel.querySelectorAll('optgroup').length;})()""")
        assert n == 0
    _browser(check, home)


def test_a_face_is_offered_once(home):
    """A recent is moved to the head, not copied to it. The custom menu drew
    both and hid one while searching; a native group cannot, and must not."""
    mine = userdata.add_font("Zzz.ttf", _real_font())
    userdata.note_font_used(mine)

    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const sel=document.querySelector('#ckList .ckfam .ckdef .ckft');
            const v=[...sel.options].map(o=>o.value);
            return {n:v.length, uniq:new Set(v).size};})()""")
        assert got["n"] == got["uniq"], got
    _browser(check, home)


def test_the_picker_is_the_browser_s_own_control(home):
    """lee, four times over, ending with *"the text drop down still dosent work
    re design it and remake it so taht it works"*. So it is a <select>: the
    browser opens it, scrolls it, filters it on type-ahead, and cannot leave it
    open over a panel that has since been rebuilt."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        got = pg.evaluate("""(()=>{
            const sel=document.querySelector('#ckList .ckfam .ckdef .ckft');
            return {tag: sel.tagName,
                    shown: getComputedStyle(sel).display!=='none',
                    widget: !!sel._fw,
                    leftovers: document.querySelectorAll('.fsel').length};})()""")
        assert got == {"tag": "SELECT", "shown": True,
                       "widget": False, "leftovers": 0}, got
    _browser(check, home)


def test_the_font_menu_asks_the_server_for_nothing():
    """One <img> per row is one REQUEST per row, and this menu holds every
    font the machine has — four hundred of them on lee's — rebuilt on every
    poll, save and selection. Several hundred image requests arriving at once
    at a stdlib http.server is what the browser was waiting on while the menu
    would not open. lee: *"the font dropdwon is still broken it seems to be the
    sidebard thats teh issue for now reove the sample text form to see if that
    help"*.

    The samples in "your own fonts" went too, on lee's next word: *"remove teh
    smaple from the add fonts"*. So there is no request for a picture of a
    face anywhere in the page any more.
    """
    from pathlib import Path
    js = (PKG / "static" / "js"
          / "project.js").read_text(encoding="utf-8")
    opts = js.split("function fontOptionHTML(f, sel){")[1].split("\n}")[0]
    assert "fontsample" not in opts, "a request per row is back in the menu"
    assert "fontsample" not in js, "something still asks for a picture"


# ------------------------------------------------------------ A to Z, together

def test_the_font_list_is_alphabetical(tmp_path, monkeypatch):
    """It used to open with whatever had been uploaded, in the order it was
    uploaded, and then five comic-sounding prefixes bumped above the rest — so
    the menu read Mangaka, AnimeAce, ComicNeue, Komika, comic, comicbd, Anton,
    Bangers, and there was no way to guess where any face would be.
    lee: *"the fonts shoud be in aphabetical order with the new fonts"*.
    """
    from mangatl import editor
    names = [f["name"] for f in editor.find_fonts()]
    assert names, "no fonts at all on this machine"
    assert names == sorted(names, key=str.lower), names[:12]


def test_an_uploaded_face_is_in_the_list_not_above_it(tmp_path, monkeypatch):
    """*"with the new fonts"* — with, not above. It is still always offered;
    it is simply offered under its own letter."""
    from mangatl import editor, userdata
    fake = str(tmp_path / "ZzzTest-Regular.ttf")
    open(fake, "wb").write(b"")
    monkeypatch.setattr(userdata, "uploaded_fonts", lambda: [fake])
    fonts = editor.find_fonts()
    names = [f["name"] for f in fonts]
    assert "ZzzTest-Regular" in names, names[:6]
    assert names == sorted(names, key=str.lower), names[:12]
    # ...and it is still marked as one of his own, so nothing about the name
    # can decide it is not a typesetting font
    mine = next(f for f in fonts if f["name"] == "ZzzTest-Regular")
    assert mine["uploaded"] and mine["comic"] and mine["bundled"]


def test_no_sample_strip_on_the_uploaded_rows():
    """lee: *"remove teh smaple from the add fonts"*. The row is the list of
    what you have added and the way to take one back out; the face itself is
    looked at in the menu you typeset from, where choosing it is the next thing
    you do."""
    from pathlib import Path
    root = PKG / "static"
    js = (root / "js" / "project.js").read_text(encoding="utf-8")
    css = (root / "css" / "editor.css").read_text(encoding="utf-8")
    body = js.split("function renderUploadedFonts()")[1].split("\n}")[0]
    assert "fontsample" not in body, body[:400]
    assert "fsel-sm" not in body, body[:400]
    # ...and no rule left behind for a thing nothing draws
    assert ".fsel-sm{" not in css


# ------------------------------------------- only that font, unless you say so

"""lee: *"Fonts should only us that font no substitute, hve a use subtitute
button in the setting that if turned n will allow teh typeseeter to use
subtitute symeboxes, if its of the text the typesster shoud not use them"*.

The switch lives in Settings, and the four tests below follow it from there to
the page: the setting has to reach the typesetter's config, the config has to
change what the fitter does, and the screen has to offer the switch at all. A
font that is short of a glyph then says so on the box instead of quietly
becoming a different font.
"""


def _fit(p, text):
    """One bubble, typeset with whatever this project's settings say."""
    import numpy as np
    from mangatl import editor
    from mangatl.models import TextRegion
    from mangatl.typeset import fit_region
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((400, 400), np.uint8)
    cv2.ellipse(mask, (200, 200), (150, 110), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, bbox=(60, 100, 280, 200), bubble_mask=mask,
                   bubble_bbox=(50, 90, 300, 220), dst_text=text)
    return r, fit_region(r, editor._typeset_cfg(p))


def _proj(tmp_path):
    from mangatl.project import Project
    from mangatl import typeset
    p = Project(None, str(tmp_path / "subs"))
    p.settings["font"] = typeset.default_font_path()
    return p


def test_a_project_starts_with_substitutes_on(tmp_path):
    """It started OFF, and the reason was good: a silent swap is a silent edit
    to what the page says, and lee wanted to SEE a face that was short of a
    glyph rather than have it papered over.

    What that cost in practice was a flag on every box holding a character no
    comic face has ever carried — a music note, a heart, a full-width bracket —
    which is most pages, and none of them were wrong. lee, of the switch:
    *"this shoud be on by default"*. So the default is the one that letters,
    and turning it off is how you ask to be told instead."""
    p = _proj(tmp_path)
    assert p.settings["substitutes"] is True


def test_with_the_setting_off_the_page_keeps_the_character(tmp_path):
    """A music note the face has no glyph for stays in the words and the box
    is flagged — a problem you can see and put right, rather than a silent
    edit to what the page says. Turned off by hand now that on is the
    default, which is the point of it being a switch."""
    p = _proj(tmp_path)
    p.settings["substitutes"] = False
    r, lay = _fit(p, "OH ♪ REALLY")
    assert "♪" in " ".join(lay.lines), lay.lines
    assert r.flagged and "glyph" in r.flagged, r.flagged


def test_with_the_setting_on_the_page_is_made_drawable(tmp_path):
    """What a project now does out of the box — and it must be the SETTING
    that decides it, not the code. Set here explicitly all the same, so the
    test still says which way it is testing when the default next moves."""
    p = _proj(tmp_path)
    p.settings["substitutes"] = True
    r, lay = _fit(p, "OH ♪ REALLY")
    assert "♪" not in " ".join(lay.lines), lay.lines
    assert "REALLY" in " ".join(lay.lines).upper()


def test_the_switch_is_on_the_settings_screen(home):
    """A setting with no way to set it is not a setting.

    Read off the screen, not off the source: a grep for `id="substitutes"`
    passes just as happily against a switch nothing loads and nothing saves."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        assert pg.evaluate("!!document.getElementById('substitutes')"), \
            "there is no switch on the screen"
        # It opens ticked, because that is what a project starts as. lee:
        # *"this shoud be on by default"*.
        assert pg.evaluate("document.getElementById('substitutes').checked") \
            is True
    _browser(check, home)


def test_turning_the_switch_off_turns_the_setting_off(home):
    """Off is how you ask to be TOLD about a face that is short of a glyph
    instead of having it papered over — so the switch has to actually reach
    the project, and the screen has to come back the way it was left."""
    def check(pg, p):
        pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
        browserpool.settled(pg)
        pg.evaluate("document.getElementById('substitutes').checked=false;"
                    "saveSettings()")
        browserpool.settled(pg)
        pg.wait_for_timeout(250)
        assert p.settings["substitutes"] is False, p.settings["substitutes"]

        # ...and the screen agrees with the project when it is opened again.
        pg.evaluate("loadProject()")
        browserpool.settled(pg)
        pg.wait_for_timeout(250)
        assert pg.evaluate(
            "document.getElementById('substitutes').checked") is False

        pg.evaluate("document.getElementById('substitutes').checked=true;"
                    "saveSettings()")
        browserpool.settled(pg)
        pg.wait_for_timeout(250)
        assert p.settings["substitutes"] is True, p.settings["substitutes"]
    _browser(check, home)


def test_the_default_face_is_named_the_same_way_the_list_names_it(monkeypatch,
                                                                  tmp_path):
    """The one place a font path was allowed to be relative.

    `.env` in the repository carries `MANGATL_FONT=fonts/CCWildWords.ttf`, and
    the editor loads it. Returned as typed, that string never matches the
    absolute path the same file has in the font list — so the menu could not
    find the face it was about to typeset in, and printed the filename with the
    extension on it instead of the name. It reads as a bug in the menu and is a
    bug in a path.
    """
    from mangatl import typeset

    face = PKG / "fonts" / "CCWildWords.ttf"
    if not face.exists():
        pytest.skip("the bundled face is not in this checkout")
    monkeypatch.chdir(str(PKG))
    monkeypatch.setenv("MANGATL_FONT", "fonts/CCWildWords.ttf")
    got = typeset.default_font_path()
    assert os.path.isabs(got), got
    assert os.path.samefile(got, str(face))


def test_the_default_face_is_one_of_the_faces_on_the_menu(monkeypatch):
    """Whatever route it was found by. A default the menu cannot find is a
    menu that cannot show which face is in use."""
    from mangatl import editor, typeset

    monkeypatch.delenv("MANGATL_FONT", raising=False)
    monkeypatch.chdir(str(PKG))
    paths = {os.path.abspath(f["path"]) for f in editor.find_fonts()}
    assert os.path.abspath(typeset.default_font_path()) in paths
