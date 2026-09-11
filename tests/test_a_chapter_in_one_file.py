"""A chapter in one file, and a series in another.

lee: *"can you creat custo file that end with .tct and .tctp? is taht
posible?"*, then, on what the project one should hold: *"make it so tht
everything is save including kayers custom boxes fonts besicaly everything
when ii load this project file it shoud be excaty as it it now"*, and on the
other: *"it shoud jut be a rename of the json file we laready have withthe
spory synopsis and charatter and places"*.

So there are two files and they are different kinds of thing.

**`.tct`** is the SERIES: the synopsis, the characters, the places and terms,
the fonts and sizes, the box types, the translation engine. Byte for byte the
JSON "Export everything" already wrote, under a name of its own, so a `.json`
exported last month still imports.

**`.tctp`** is the CHAPTER: a zip of everything that cannot be worked out
again - the pages, every box, both languages, the layouts, the paint, the
hand-cleaned plates, and the faces it typesets in. The faces are the part that
is easy to miss: an uploaded one lives in `~/.mangatl/fonts`, deliberately
outside any chapter so it outlives the chapter, which means it is not in the
project folder and would not travel with it.

What is NOT carried: `plate_cache` and `ai_clean_cache`. Both are things the
app makes for itself and can make again, and together they are usually bigger
than the chapter. A bundle is what you cannot rebuild.
"""
import io
import json
import os
import shutil
import threading
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")



from mangatl import bundle, editor
from mangatl.project import Project
from where import PKG

# Any face this build ships. It was `AnimeAce.ttf` until 2026-08-26, when
# that file left the repo - Blambot permits use but not redistribution,
# and this app is downloaded. See `fonts/LICENSES.md`.
FONT = os.path.join(str(PKG), "fonts",
                    "ComicNeue-Regular.ttf")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """This person's own folder - where uploaded faces live."""
    d = str(tmp_path / "home")
    monkeypatch.setenv("MANGATL_HOME", d)
    return d


def _face(where, name="MyTypesetting.ttf", mark=b""):
    os.makedirs(where, exist_ok=True)
    at = os.path.join(where, name)
    shutil.copy(FONT, at)
    if mark:                         # same name, different file
        with open(at, "ab") as fh:
            fh.write(mark)
    return at


def _installed(home, **kw):
    """A face already uploaded on THIS machine."""
    from mangatl.userdata import fonts_dir
    return _face(fonts_dir(), **kw)


def _project(tmp_path, home, pages=3):
    """A chapter with work on it: boxes, both languages, paint, a hand-cleaned
    plate, a custom box type and a face of its own."""
    p = Project(None, str(tmp_path / "proj"))
    for i in range(pages):
        p.add_uploaded("%03d.png" % (i + 1), cv2.imencode(
            ".png", np.full((80, 60, 3), 200 + i, np.uint8))[1].tobytes())
    for sub, field in (("custom_clean", "custom_clean"),
                       ("paint", "paint_overlay"), ("paint", "paint_over")):
        d = os.path.join(p.output_dir, sub)
        os.makedirs(d, exist_ok=True)
        at = os.path.join(d, f"{field}.png")
        cv2.imwrite(at, np.zeros((80, 60, 4), np.uint8))
        setattr(p.pages[0], field, at)
    p.pages[0].paint_layers = [{"tool": "brush", "pts": [[1, 2], [3, 4]]}]
    # Somewhere of its own, so a reference that is NOT rewritten on the way
    # back in points at a file that is not there - which is the whole failure
    # being guarded against, and is invisible if the face happens to start out
    # in the folder it would be installed into.
    face = _face(str(tmp_path / "grabbed"))
    p.settings.update({"font": face, "fonts": {"sfx": face},
                       "min_font": 9, "max_font": 41,
                       "custom_kinds": [{"key": "shout", "name": "Shout",
                                         "family": "bubble", "font": face}]})
    p.ctx.synopsis = "a girl who would be a villainess"
    p.ctx.characters = {"Yui": "the maid"}
    p.pages[0].regions = [{
        "id": 1, "bbox": [1, 1, 10, 10], "bubble_bbox": None, "polygon": [],
        "kind": "shout", "order": 0, "src_text": "悪女", "dst_text": "VILLAINESS",
        "own_text": True, "layout": {"lines": ["VILLAINESS"], "font": face},
        "layout_override": {"font": face, "lines": ["VILLAINESS"]}}]
    p.save()
    return p


def _names(data):
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


# ------------------------------------------------------------ what is in it

def test_the_pages_and_the_work_are_in_it(tmp_path, home):
    p = _project(tmp_path, home)
    got = _names(bundle.write(p._state(), p.output_dir))
    assert "mangatct.json" in got and "project.json" in got
    assert [n for n in got if n.startswith("input/")] == \
        ["input/001.png", "input/002.png", "input/003.png"]
    assert "custom_clean/custom_clean.png" in got
    assert "paint/paint_overlay.png" in got and "paint/paint_over.png" in got


def test_the_faces_it_typesets_in_are_in_it(tmp_path, home):
    """The one thing that is not in the project folder at all."""
    p = _project(tmp_path, home)
    got = _names(bundle.write(p._state(), p.output_dir))
    assert "fonts/MyTypesetting.ttf" in got


def test_the_slices_a_webtoon_arrived_as_travel_too(tmp_path, home):
    """After re-cutting, the tiles are the only copy of the original scan."""
    p = _project(tmp_path, home)
    d = os.path.join(p.upload_dir(), "tiles")
    os.makedirs(d)
    cv2.imwrite(os.path.join(d, "image_1.png"), np.zeros((10, 10, 3), np.uint8))
    assert "input/tiles/image_1.png" in _names(
        bundle.write(p._state(), p.output_dir))


def test_what_the_app_can_make_again_is_left_out(tmp_path, home):
    """The two caches are bigger than the chapter and are not the chapter.

    The FOLDERS, that is. The cleaned plates inside `plate_cache` do travel
    now - under `plates/`, one per page, re-keyed on the way in - because
    "can make again" turned out to mean "will spend coins and minutes making
    again". See `test_the_cleaners_own_work_travels_too`."""
    p = _project(tmp_path, home)
    for sub in ("plate_cache", "ai_clean_cache"):
        d = os.path.join(p.output_dir, sub)
        os.makedirs(d, exist_ok=True)
        cv2.imwrite(os.path.join(d, "x.png"), np.zeros((10, 10, 3), np.uint8))
    got = _names(bundle.write(p._state(), p.output_dir))
    assert not [n for n in got if "cache" in n], got


def test_nothing_in_it_names_a_place_on_this_machine(tmp_path, home):
    """A file whose whole point is opening somewhere else cannot carry
    `C:\\Users\\leema\\...` in it."""
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    state = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("project.json"))
    assert state["input_dir"] == "input"
    for pg in state["pages"]:
        for field in ("path", "custom_clean", "paint_overlay", "paint_over"):
            v = pg.get(field) or ""
            assert not os.path.isabs(v) and ":" not in v and "\\" not in v, v
    assert state["settings"]["font"] == "fonts/MyTypesetting.ttf"


# ------------------------------------------------------- and it comes back

def test_it_comes_back_exactly_as_it_was(tmp_path, home):
    """lee: *"when ii load this project file it shoud be excaty as it it
    now"*. Opened into a folder that has never seen this chapter."""
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    root = str(tmp_path / "elsewhere")
    q = Project(None, root)
    state = bundle.read(data, root)
    with open(q.state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    q.load()

    assert len(q.pages) == len(p.pages)
    assert [x.name for x in q.pages] == [x.name for x in p.pages]
    assert all(cv2.imread(x.path) is not None for x in q.pages)
    assert q.ctx.synopsis == p.ctx.synopsis
    assert q.ctx.characters == p.ctx.characters
    assert q.settings["min_font"] == 9 and q.settings["max_font"] == 41
    assert [k["key"] for k in q.settings["custom_kinds"]] == \
        [k["key"] for k in p.settings["custom_kinds"]]
    r = q.pages[0].regions[0]
    assert r["src_text"] == "悪女" and r["dst_text"] == "VILLAINESS"
    assert r["own_text"] is True
    assert q.pages[0].paint_layers == p.pages[0].paint_layers
    for field in ("custom_clean", "paint_overlay", "paint_over"):
        at = getattr(q.pages[0], field)
        assert at and os.path.isfile(at), field


def test_the_face_is_installed_where_this_machine_keeps_faces(tmp_path, home):
    """Opened on a machine that has never seen the font. It must typeset in the
    face it was typeset in, and the face must be there for the NEXT chapter
    too - which is where uploaded faces live."""
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    from mangatl.userdata import fonts_dir
    shutil.rmtree(fonts_dir(), ignore_errors=True)

    shutil.rmtree(str(tmp_path / "grabbed"))     # the face is gone from here
    state = bundle.read(data, str(tmp_path / "elsewhere"))
    r = state["pages"][0]["regions"][0]
    named = {"the project's own": state["settings"]["font"],
             "the sound-effect family's": state["settings"]["fonts"]["sfx"],
             "a custom box type's": state["settings"]["custom_kinds"][0]["font"],
             "one box's layout": r["layout"]["font"],
             "one box's override": r["layout_override"]["font"]}
    for where, at in named.items():
        assert os.path.isfile(at), f"{where} face is not on this machine: {at}"
        assert os.path.dirname(at) == os.path.abspath(fonts_dir()), \
            f"{where} face was not installed where faces go: {at}"


def test_a_face_already_here_is_not_installed_twice(tmp_path, home):
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    from mangatl.userdata import fonts_dir
    _installed(home)                    # the same face, already uploaded here
    before = sorted(os.listdir(fonts_dir()))
    bundle.read(data, str(tmp_path / "elsewhere"))
    assert sorted(os.listdir(fonts_dir())) == before


def test_somebody_elses_face_of_the_same_name_does_not_replace_yours(tmp_path, home):
    """Two people, two faces, both called MyTypesetting.ttf. Overwriting the one
    on this machine would re-typeset every other chapter that uses it."""
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    from mangatl.userdata import fonts_dir
    mine = _installed(home, mark=b"\x00mine")
    was = open(mine, "rb").read()

    state = bundle.read(data, str(tmp_path / "elsewhere"))
    assert open(mine, "rb").read() == was, "my own face must be untouched"
    got = state["settings"]["font"]
    assert os.path.abspath(got) != os.path.abspath(mine)
    assert os.path.isfile(got), "and theirs is installed beside it"


def test_a_face_that_was_already_missing_is_left_saying_so(tmp_path, home):
    """Rewriting a path to a file that does not exist would only make the loss
    harder to see."""
    p = _project(tmp_path, home)
    p.settings["font"] = os.path.join(str(tmp_path), "gone.ttf")
    data = bundle.write(p._state(), p.output_dir)
    state = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("project.json"))
    assert state["settings"]["font"].endswith("gone.ttf")


# --------------------------------------------------------------- and safety

def test_a_file_that_is_not_ours_is_refused(tmp_path, home):
    assert not bundle.looks_like_bundle(b"not a zip at all")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pages/001.png", b"x")
    assert not bundle.looks_like_bundle(buf.getvalue()), \
        "a zip of pages is not a project, whatever it has been renamed to"


def test_a_project_file_with_no_project_in_it_is_refused(tmp_path, home):
    """It says it is one and there is nothing to open. Finding that out in
    `read` means finding it out after the chapter that was open is gone."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(bundle.MANIFEST, json.dumps({"mangatct": 1}))
        z.writestr("input/001.png", b"x")
    assert not bundle.looks_like_bundle(buf.getvalue())


def test_nothing_is_deleted_before_the_file_is_known_to_be_one(tmp_path, home):
    """Opening one REPLACES what is open. A file that turns out not to be a
    project must not take the chapter with it on the way out."""
    p = _project(tmp_path, home)
    with pytest.raises(ValueError):
        bundle.read(b"not a zip at all", p.output_dir)
    assert len(os.listdir(p.upload_dir())) == 3


@pytest.mark.parametrize("named", [
    "input/../../../escaped.txt",       # upwards
    "C:/escaped.txt",                   # sideways, onto another drive
    "/escaped.txt",                     # and straight at the root
])
def test_a_name_in_a_zip_can_never_reach_outside_the_folder(named, tmp_path):
    """A bundle can arrive from anyone, and a zip may name anything at all.
    `C:/…` is the one that does not look dangerous: `os.path.join` throws the
    root away when the second part names a drive, so on Windows a check that
    the answer starts with the root is the check that lets it through."""
    root = os.path.abspath(str(tmp_path / "here"))
    got = os.path.abspath(bundle._abs(named, root))
    assert got.startswith(root + os.sep), got
    assert "escaped.txt" == os.path.basename(got)
    # No segment below the root may still name a drive. This machine may not
    # be the one it matters on: `ntpath.join("C:/work", "D:", "evil")` throws
    # the root away, so a drive that survives this far is out of the folder on
    # Windows however harmless it looks here.
    assert ":" not in got[len(root):], got


def test_a_zip_cannot_write_outside_the_folder_it_is_opened_into(tmp_path, home):
    """The same thing again, through the real thing."""
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, \
            zipfile.ZipFile(buf, "w") as out:
        for info in src.infolist():
            out.writestr(info.filename, src.read(info.filename))
        out.writestr("input/../../../escaped.txt", b"got out")
    root = str(tmp_path / "elsewhere")
    bundle.read(buf.getvalue(), root)
    assert not os.path.exists(str(tmp_path / "escaped.txt"))
    assert not os.path.exists(os.path.join(root, "..", "escaped.txt"))


# ------------------------------------------------------------- through the app

def _serve(p):
    was, editor.PROJECT = editor.PROJECT, p
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _stop(srv, was):
    srv.shutdown()
    srv.server_close()
    editor._warm["gen"] += 1
    editor.PROJECT = was


def _post(base, route, body):
    req = urllib.request.Request(base + route, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_save_writes_it_and_open_brings_it_back(tmp_path, home):
    p = _project(tmp_path, home)
    srv, was, base = _serve(p)
    dest = str(tmp_path / "chapter one.tctp")
    try:
        got = _post(base, "/api/project_save", {"path": dest})
        assert os.path.isfile(dest) and got["bytes"] > 0
        assert p.settings["project_file"] == dest, \
            "Save has to remember where, or it is Save as every time"
        p.clear()
        p.save()
        assert not p.pages
        got = _post(base, "/api/project_open", {"path": dest})
        assert got["pages"] == 3
        assert p.ctx.synopsis.startswith("a girl")
        assert p.pages[0].regions[0]["dst_text"] == "VILLAINESS"
    finally:
        _stop(srv, was)


def test_save_adds_the_extension_when_it_is_not_typed(tmp_path, home):
    """A project file called `chapter 3` is a project file nothing opens."""
    p = _project(tmp_path, home)
    srv, was, base = _serve(p)
    try:
        got = _post(base, "/api/project_save", {"path": str(tmp_path / "ch3")})
        assert got["path"].endswith(".tctp")
    finally:
        _stop(srv, was)


def test_the_browser_can_hand_one_over_when_there_is_no_file_dialog(tmp_path, home):
    """A headless install, or the editor reached from another desk."""
    p = _project(tmp_path, home)
    data = bundle.write(p._state(), p.output_dir)
    srv, was, base = _serve(p)
    try:
        p.clear()
        p.save()
        req = urllib.request.Request(base + "/api/project_upload", data,
                                     {"Content-Type": "application/zip"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["pages"] == 3
        assert len(p.pages) == 3
    finally:
        _stop(srv, was)


def test_a_file_that_is_not_a_project_leaves_the_open_one_alone(tmp_path, home):
    p = _project(tmp_path, home)
    srv, was, base = _serve(p)
    try:
        req = urllib.request.Request(base + "/api/project_upload", b"junk",
                                     {"Content-Type": "application/zip"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 400
        assert len(p.pages) == 3, "the chapter that was open is still open"
    finally:
        _stop(srv, was)


def test_the_download_is_named_after_the_chapter(tmp_path, home):
    p = _project(tmp_path, home)
    srv, was, base = _serve(p)
    try:
        with urllib.request.urlopen(base + "/api/project_file") as r:
            assert ".tctp" in r.headers.get("Content-Disposition", "")
            assert "input" not in r.headers.get("Content-Disposition", ""), \
                "every project's upload folder is called input; that is not a name"
            assert bundle.looks_like_bundle(r.read())
    finally:
        _stop(srv, was)


# ------------------------------------------------------------------ on screen

def _ui():
    import glob
    static = os.path.join(str(PKG), "static")
    parts = [open(os.path.join(static, "editor.html")).read()]
    for f in sorted(glob.glob(os.path.join(static, "js", "*.js"))):
        parts.append(open(f).read())
    return "\n".join(parts)


def _file_rail():
    import re
    html = _ui()
    return re.search(r'<nav id="fileNav">.*?</nav>', html, re.S).group(0)


def test_saving_and_opening_are_buttons_on_the_rail_itself():
    """lee: *"add a save project save as and a load project and move into te
    files tab too"*, and then, of a row of them inside the screen: *"these
    shoud be button onthe side bar"*. So they are the rail, not a row you have
    to open a screen to reach."""
    rail = _file_rail()
    for fn in ("saveProject()", "saveProjectAs()", "openProject()",
               "exportSettings()"):
        assert 'onclick="' + fn in rail, fn
    assert "Import story context" in rail, \
        "and importing one, which was the last thing left under Settings"


def test_pressing_one_shows_the_screen_that_says_what_it_did():
    """A button on a rail with no panel showing is a button that gives no
    answer - and these have one worth reading: where the file went."""
    src = _ui()
    for fn in ("async function saveProject(){", "async function saveProjectAs(){",
               "async function openProject(){"):
        body = src.split(fn, 1)[1].split("\n}", 1)[0]
        assert "setFileTab('save')" in body, fn


def test_the_screen_they_show_is_still_reachable_on_its_own():
    assert 'data-sec="save"' in _file_rail()


def test_the_series_file_is_a_tct_now():
    src = _ui()
    assert "Export everything (.json)" not in src, "renamed, lee's screenshot"
    assert ".tct'" in src, "and that is what it downloads as"


def test_settings_no_longer_has_a_screen_for_files():
    """lee: *"move the import to the file tab and remove this tab"*. Every
    file the app writes or reads is under File now, and a Settings screen
    holding one of them was a second place to look."""
    src = _ui()
    assert 'data-sec="project"' not in src
    assert "setSettingsTab('project')" not in src
    assert "Carry this series forward" not in src


def test_the_button_that_opens_one_is_beside_the_file_it_opens():
    """The hidden input moved with its button. Left behind on a screen that no
    longer exists, pressing Import would have opened nothing."""
    src = _ui()
    body = src.split('id="fileBody"', 1)[1]
    assert 'id="impSet"' in body, "the file input lives on the File screen now"


@pytest.mark.parametrize("gone", [
    "Download JSON",                    # the Results toolbar
    "Save series file",                 # what it was called for an hour
    "Drop a .json here",                # the new-project screen
    "Choose a settings file",
    "Settings file</span>",             # the step it is labelled with
])
def test_nothing_calls_the_series_file_json_any_more(gone):
    """lee: *"replace everywhere it say json with story context"*. It is the
    synopsis, the characters and the places - calling it by its file format
    told nobody what was in it."""
    assert gone not in _ui(), gone


def test_it_is_called_the_story_context_everywhere_instead():
    src = _ui()
    for said in ("Export story context", "Drop a story context here",
                 "Choose a story context", "Story context</span>"):
        assert said in src, said


def test_the_files_that_are_not_the_story_context_keep_their_own_names():
    """The AI request, the AI's reply and the translated text are three other
    files that happen to be JSON as well. Renaming those would be renaming the
    wrong thing - "Download the AI request (story context)" is not a sentence
    about anything."""
    src = _ui()
    for kept in ("Download the AI request (.json)",
                 "Export translated text (.json)",
                 "Upload a .json file"):
        assert kept in src, kept


def test_a_settings_file_exported_before_the_rename_still_opens():
    """It is the same JSON under a new name, so both go in the same door."""
    src = _ui()
    assert 'accept=".tct,.json,application/json"' in src


def test_the_person_is_told_the_file_carries_their_keys():
    """It holds the settings, and an OLD project's settings hold whatever key
    was saved in it. Somebody handing the chapter to a typesetter should know
    that before they do it, not after.

    The warning got NARROWER rather than going away. Keys live in the `.env`
    now - lee: *"they key shoud be in the .env file and all teh project shoud
    use them"* - so a chapter set up since then has none inside it, and
    saying otherwise would teach people to distrust a file that is fine. A
    chapter set up before still does, and that is what the sentence is for.
    """
    src = _ui()
    # ...and narrower again: a person has no keys at all now (the relay calls
    # with the project's - lee: *"the user should not have the keys"*), so the
    # one line the screen keeps is the promise, not the warning.
    assert "never a key" in src


# --------------------------------------------------------- and it has a name

def test_the_synopsis_screen_has_a_title_box():
    """lee: *"in teh symo[psis tab add a tilee box fort the manga"*. It goes
    with the synopsis and the cast rather than with the settings, because it
    is content: it belongs to the story, not to how the story is translated."""
    src = _ui()
    # No `on` in the markup on any section any more - the nav button is the
    # one default and `openSettingsDlg` opens what it names. See
    # `test_the_page_that_opens_is_the_one_lit`.
    sec = src.split('<section class="set-section" data-sec="synopsis">',
                    1)[1].split("</section>", 1)[0]
    assert 'id="title"' in sec and ">Title<" in sec
    assert "proj.context.title" in src, "…and it is read back off the project"
    assert "title:($('title')?$('title').value:'')" in src, "…and saved"


def test_the_title_is_part_of_the_story_and_travels_with_it(tmp_path, home):
    """Into the chapter file, and into the story context, because both carry
    the series bible and this is part of it."""
    p = _project(tmp_path, home)
    p.ctx.title = "Villainess in Training"
    p.save()
    state = bundle.read(bundle.write(p._state(), p.output_dir),
                        str(tmp_path / "elsewhere"))
    assert state["context"]["title"] == "Villainess in Training"
    assert "title:ctx.title" in _ui(), "and out with the story context too"


def test_a_chapter_is_named_after_the_manga(tmp_path, home):
    """`mangatl-project.json` is not the name of anybody's manga."""
    p = _project(tmp_path, home)
    p.ctx.title = "Villainess in Training"
    srv, was, base = _serve(p)
    try:
        with urllib.request.urlopen(base + "/api/project_file") as r:
            assert "Villainess in Training.tctp" in \
                r.headers.get("Content-Disposition", "")
    finally:
        _stop(srv, was)


def test_a_title_that_is_not_a_filename_is_made_into_one(tmp_path, home):
    """Somebody will type `Re:Zero - Vol 3/4`, and a slash in a filename is
    not a filename."""
    p = _project(tmp_path, home)
    p.ctx.title = 'Re:Zero <vol 3/4>'
    srv, was, base = _serve(p)
    try:
        with urllib.request.urlopen(base + "/api/project_file") as r:
            got = r.headers.get("Content-Disposition", "")
        name = got.split('filename="', 1)[1].rstrip('"')
        for bad in ':/<>"|?*\\':
            assert bad not in name, name
        assert name.endswith(".tctp") and name.startswith("Re-Zero")
    finally:
        _stop(srv, was)


# ------------------------------- what "everything" turned out not to include
#
# lee, going into the beta: *"also update teh .tctp project file to inlcude
# all teh new stuff since we made it"*. Three things had been added to the app
# since the bundle was written, and each one travelled badly or not at all.

def test_pages_that_live_outside_the_project_folder_travel(tmp_path, home):
    """A folder USED IN PLACE still bundles its pages.

    `use_folder` points a project at pages where they already are and copies
    nothing - that is the whole point of it - so `input/` is empty, and the
    bundle used to come out holding a manifest, a project.json and NOT ONE
    PAGE. The same hole swallowed a re-cut webtoon whose stitched pages land
    in `<project>/strip/`, which is not a carried folder either: manhwa and
    manhua are the formats that arrive that way.

    Silent, both times: the file wrote, the zip opened, and the chapter came
    back with every box and every translation over blank artwork.
    """
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    for i in range(3):
        cv2.imwrite(str(theirs / ("p%03d.png" % i)),
                    np.full((40, 30, 3), 200 + i, np.uint8))
    p = Project(None, str(tmp_path / "proj"))
    p.use_folder(str(theirs))
    p.save()
    data = bundle.write(p._state(), p.output_dir)
    assert [n for n in _names(data) if n.startswith("input/")] == \
        ["input/p000.png", "input/p001.png", "input/p002.png"]
    back = tmp_path / "opened"
    back.mkdir()
    state = bundle.read(data, str(back))
    for pg in state["pages"]:
        assert os.path.isfile(pg["path"]), pg["path"]


def test_two_pages_of_the_same_name_both_travel(tmp_path, home):
    """...and re-cutting a chapter over another one leaves exactly that."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for d, tone in ((a, 40), (b, 220)):
        cv2.imwrite(str(d / "001.png"), np.full((30, 20, 3), tone, np.uint8))
    p = Project(None, str(tmp_path / "proj"))
    p.use_folder(str(a))
    p.pages.append(type(p.pages[0])(**{**vars(p.pages[0]),
                                       "path": str(b / "001.png"),
                                       "name": "001.png"}))
    p.save()
    got = [n for n in _names(bundle.write(p._state(), p.output_dir))
           if n.startswith("input/")]
    assert len(got) == 2, got
    back = tmp_path / "opened"
    back.mkdir()
    state = bundle.read(bundle.write(p._state(), p.output_dir), str(back))
    tones = [int(cv2.imread(pg["path"])[0, 0, 0]) for pg in state["pages"]]
    assert sorted(tones) == [40, 220], tones


def test_a_face_set_on_part_of_the_text_travels(tmp_path, home):
    """Part of a box can be set in a face of its own now
    (`layout_override.spans`), which is one more place a font file is named -
    and the newest one. A chapter with a word in an uploaded face travelled
    with the face left behind and opened with that word in the default."""
    face = _face(str(tmp_path / "grabbed"), name="RangeFace.ttf")
    p = Project(None, str(tmp_path / "proj"))
    p.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((60, 40, 3), 210, np.uint8))[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "bbox": [1, 1, 10, 10], "bubble_bbox": None, "polygon": [],
        "kind": "bubble", "order": 0, "src_text": "x", "dst_text": "HELLO",
        "layout_override": {"lines": ["HELLO"], "spans": [
            {"s": 0, "e": 3, "st": {"font": face, "fg": "#ff0000"}}]}}]
    p.save()
    data = bundle.write(p._state(), p.output_dir)
    assert "fonts/RangeFace.ttf" in _names(data)
    inside = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("project.json"))
    st = inside["pages"][0]["regions"][0]["layout_override"]["spans"][0]["st"]
    assert st["font"] == "fonts/RangeFace.ttf", st
    back = tmp_path / "opened"
    back.mkdir()
    state = bundle.read(data, str(back))
    got = (state["pages"][0]["regions"][0]["layout_override"]
           ["spans"][0]["st"]["font"])
    assert os.path.isfile(got), got
    # ...and the range keeps everything else it was carrying
    assert (state["pages"][0]["regions"][0]["layout_override"]
            ["spans"][0]["st"]["fg"]) == "#ff0000"


def test_nobody_elses_keys_are_in_the_file_you_hand_over(tmp_path, home):
    """A `.tctp` is the file you GIVE somebody - and the settings in it hold
    the Claude, Gemini, OpenRouter and cleaner credentials. They went in the
    clear, so sharing a chapter shared whatever those keys can spend.

    Costs the person nothing: keys live in `~/.mangatl/.env`, which beats
    whatever a chapter has saved in it, so your own bundle opens on your own
    machine with your own keys."""
    from mangatl.project import secret_keys
    p = _project(tmp_path, home)
    for k in secret_keys():
        p.settings[k] = "SECRET-" + k
    p.settings["min_font"] = 9
    p.save()
    data = bundle.write(p._state(), p.output_dir)
    raw = zipfile.ZipFile(io.BytesIO(data)).read("project.json").decode()
    for k in secret_keys():
        assert ("SECRET-" + k) not in raw, k
    # the settings that are NOT secrets are untouched...
    assert '"min_font": 9' in raw
    # ...and the project it was written from still has its keys
    assert p.settings["clean_token"] == "SECRET-clean_token"


def test_the_cleaners_own_work_travels_too(tmp_path, home):
    """lee, opening a chapter he had cleaned: *"teh clened pages didnt survive
    teh closinga and opeing a tctp file"*, then the half that names it
    exactly: *"the manual fixes survide butr teh automated one didnt"*.

    His hand-cleaned plates and his paint were carried - they are files the
    project names. The CLEANER's plates live in a cache keyed by a hash, the
    cache was left out on the rule that a bundle holds what you cannot
    rebuild, and rebuilding one costs coins and minutes a page.

    Opened into a DIFFERENT folder on purpose: the cache's name is a hash of
    things that are not the same on the machine that opens the file, so a
    plate copied in under its old name would sit there unread and the page
    would be cleaned again. It has to be re-keyed, and this is the test that
    it is.
    """
    from mangatl import editor
    p = Project(None, str(tmp_path / "proj"))
    for i in range(2):
        p.add_uploaded("%03d.png" % i, cv2.imencode(
            ".png", np.full((60, 40, 3), 200 + i, np.uint8))[1].tobytes())
    p.pages[0].regions = [{
        "id": 1, "bbox": [5, 5, 20, 20], "bubble_bbox": [5, 5, 20, 20],
        "polygon": [[5, 5], [25, 5], [25, 25], [5, 25]], "kind": "bubble",
        "order": 0, "src_text": "x", "dst_text": "HI", "confidence": .9}]
    p.save()
    # a cleaned plate, exactly where the cache keeps one
    was = editor._plate_disk_path(p, 0)
    cv2.imwrite(was, np.full((60, 40, 3), 111, np.uint8))
    p.pages[0].cleaned = True
    p.save()

    data = bundle.write(p._state(), p.output_dir,
                        plates=editor._plates_to_carry(p))
    assert "plates/0.png" in _names(data), _names(data)

    q = Project(None, str(tmp_path / "elsewhere"))
    state = bundle.read(data, q.output_dir)
    editor._adopt(q, state)
    want = editor._plate_disk_path(q, 0)
    assert os.path.isfile(want), "the cleaned page did not survive"
    assert int(cv2.imread(want)[0, 0, 0]) == 111, "a different plate came back"
    assert q.pages[0].cleaned, "and the page still says it was cleaned"
    # the staging folder is not left lying in the project
    assert not os.path.isdir(os.path.join(q.output_dir, bundle.PLATES))


def test_a_plate_for_a_page_that_is_not_here_is_ignored(tmp_path, home):
    """A bundle can arrive from anyone, and `plates/` names pages by index."""
    from mangatl import editor
    q = Project(None, str(tmp_path / "proj"))
    q.add_uploaded("001.png", cv2.imencode(
        ".png", np.full((30, 20, 3), 200, np.uint8))[1].tobytes())
    q.save()
    d = os.path.join(q.output_dir, bundle.PLATES)
    os.makedirs(d, exist_ok=True)
    for name in ("7.png", "notanumber.png", "0.txt"):
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(b"x")
    cv2.imwrite(os.path.join(d, "0.png"), np.full((30, 20, 3), 99, np.uint8))
    assert editor._take_in_carried_plates(q) == 1
    assert int(cv2.imread(editor._plate_disk_path(q, 0))[0, 0, 0]) == 99
