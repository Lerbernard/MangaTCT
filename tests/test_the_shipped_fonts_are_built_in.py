"""The faces the app ships are built in, not yours to remove.

lee, with Settings > Fonts open and "Your fonts" reading Bangers-Regular,
ComicNeue-Bold, ComicNeue-Italic, ComicNeue-Regular, Kalam-Regular, Mangaka -
each with a remove button: *"these fonts shoud be bilt in not in the list of
your fonts"*, then *"exept for mangaka"*.

WHY THEY WERE THERE. His `~/.mangatl/fonts` really does hold those five files,
byte for byte the ones in `fonts/`, all written in the same second - and the
five are exactly the faces `typeset.DEFAULT_FONTS` names. Nothing in the app
seeds that folder; what writes into it and rewrites a project's font paths to
point there is opening a `.tctp` (`bundle.read` -> `bundle._install_font`), and
`bundle.write` carries every face a project names, the app's own included. The
list was then `os.listdir` of the folder (`userdata.uploaded_fonts`), so a copy
of a shipped face was indistinguishable from a face somebody bought.

So a file in that folder whose NAME and BYTES are a shipped face's is a copy of
the built-in face: it is not listed as yours and it cannot be removed. It is
not deleted either - lee's project names `...\\.mangatl\\fonts\\ComicNeue-Bold.ttf`
on its boxes, and that path has to keep typesetting and keep being the option
the menus select.
"""
import os
import shutil
import threading
from http.server import ThreadingHTTPServer

import pytest

import browserpool

from mangatl import userdata
from scratch import scratch
from where import PKG

SHIPPED = PKG / "fonts"
LEES_COPIES = ("Bangers-Regular.ttf", "ComicNeue-Bold.ttf",
               "ComicNeue-Italic.ttf", "ComicNeue-Regular.ttf",
               "Kalam-Regular.ttf")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """lee's folder, in miniature: the five copies and one face of his own."""
    from mangatl import typeset
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    typeset._font_dirs.cache_clear()
    d = userdata.fonts_dir()
    os.makedirs(d, exist_ok=True)
    for n in LEES_COPIES:
        shutil.copy(str(SHIPPED / n), os.path.join(d, n))
    # His own face. Not a shipped file under a shipped name, whatever its bytes.
    shutil.copy(str(SHIPPED / "PatrickHand-Regular.ttf"),
                os.path.join(d, "Mangaka.ttf"))
    yield tmp_path
    typeset._font_dirs.cache_clear()


def _names(paths):
    return [os.path.basename(p) for p in paths]


def test_a_copy_of_a_shipped_face_is_not_one_of_yours(home):
    assert _names(userdata.uploaded_fonts()) == ["Mangaka.ttf"]


def test_the_copies_are_known_to_be_the_built_in_faces(home):
    assert _names(userdata.builtin_copies()) == sorted(LEES_COPIES)
    shipped = _names(userdata.builtin_fonts())
    for n in LEES_COPIES:
        assert n in shipped, n


def test_the_same_name_with_other_bytes_is_yours(home):
    """A newer Bangers dropped in under the shipped name is a DIFFERENT face -
    and it wins, because the person's folder is looked in first - so it is
    theirs to see and to take back out."""
    d = userdata.fonts_dir()
    shutil.copy(str(SHIPPED / "Chewy-Regular.ttf"),
                os.path.join(d, "Bangers-Regular.ttf"))
    assert "Bangers-Regular.ttf" in _names(userdata.uploaded_fonts())
    assert "Bangers-Regular.ttf" not in _names(userdata.builtin_copies())


def test_a_built_in_face_cannot_be_removed_from_under_the_app(home):
    copy = os.path.join(userdata.fonts_dir(), "ComicNeue-Bold.ttf")
    assert userdata.remove_font(copy) is False
    assert os.path.isfile(copy)


def test_your_own_face_can_still_be_removed(home):
    mine = os.path.join(userdata.fonts_dir(), "Mangaka.ttf")
    assert userdata.remove_font(mine) is True
    assert not os.path.exists(mine)


def test_nothing_is_deleted_by_asking(home):
    from mangatl import editor
    before = sorted(os.listdir(userdata.fonts_dir()))
    got = editor.fonts_answer()
    assert sorted(os.listdir(userdata.fonts_dir())) == before
    assert _names(got["uploaded"]) == ["Mangaka.ttf"]
    assert "ComicNeue-Bold.ttf" in _names(got["builtin"])


def test_a_saved_path_to_the_copy_is_still_on_the_menu(home):
    """lee's boxes name the copy. The menus select an option by path, so the
    copy's path has to stay the option - as a built-in face, not an upload."""
    from mangatl import editor
    copy = os.path.join(userdata.fonts_dir(), "ComicNeue-Bold.ttf")
    rows = [f for f in editor.find_fonts()
            if os.path.normcase(f["path"]) == os.path.normcase(copy)]
    assert len(rows) == 1, rows
    assert rows[0]["uploaded"] is False
    assert rows[0]["bundled"] is True
    # ...and offered once, not again from the shipped folder
    names = [f["name"] for f in editor.find_fonts()]
    assert names.count("ComicNeue-Bold") == 1


def test_the_settings_screen_lists_only_mangaka_and_says_what_is_built_in(
        home):
    import cv2
    import numpy as np
    from mangatl import editor
    from mangatl.project import Project
    root = scratch("_tmp_builtin_fonts")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((400, 300, 3), 245, np.uint8))[1].tobytes())
    copy = os.path.join(userdata.fonts_dir(), "ComicNeue-Bold.ttf")
    p.settings["font"] = copy
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
            pg.evaluate("setTab('settings'); setSettingsTab('fonts')")
            browserpool.settled(pg)
            # The font answer walks the machine's own font folders and can
            # land after the page has settled - under a loaded run, well
            # after. Both lists are drawn from it, so wait for it.
            pg.wait_for_function(
                "document.getElementById('builtinFonts').textContent.length>0"
                " && document.querySelectorAll('#upFontList .upfont-nm')"
                ".length>0", timeout=60000)
            got = pg.evaluate("""(()=>({
                mine: [...document.querySelectorAll('#upFontList .upfont-nm')]
                        .map(e=>e.textContent),
                removes: document.querySelectorAll('#upFontList .xbtn').length,
                builtin: document.getElementById('builtinFonts').textContent,
                builtinRemoves: document.querySelectorAll(
                        '#builtinFonts button').length,
                bubble: document.querySelector('#ckList .ckfam .ckdef .ckft')
                        .value,
                gone: (document.querySelector('#ckList .ckgone')||{})
                        .textContent||''}))()""")
            assert got["mine"] == ["Mangaka"], got
            assert got["removes"] == 1, got
            assert got["builtinRemoves"] == 0, got
            for fam in ("Bangers", "Comic Neue", "Kalam"):
                assert fam in got["builtin"], got
            # The saved path to the copy is still the face the row selects,
            # and nothing says it is missing.
            assert os.path.normcase(got["bubble"]) == os.path.normcase(copy)
            assert got["gone"] == "", got
            assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()
        shutil.rmtree(root, ignore_errors=True)
