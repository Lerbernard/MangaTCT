"""Pages from a chapter you are no longer working on.

lee loaded a folder of manga and got back his `024.jpg … 039.jpg` **and** a run
of `page0xx` files he had never seen: *"soem pages that wrere not i the folder
are showing uo when i upload teh foler"*.

`page001.png` and its friends are what the webtoon re-cut wrote - for the
chapter before. Every chapter uploads into the same `input/` folder and nothing
ever emptied it. `clear()` forgets the PAGES, which is a different thing from
the FILES: everything that lists the folder afterwards - reopening the project,
a re-cut, a rescan - finds every file every chapter ever put there and calls
them all pages.

So the folder is emptied when a chapter is put down, and emptied by MOVING:
into `input-previous`, one generation, replacing the one before it. Deleting
would be the tidy answer and the wrong one, because the re-cut pages and the
halves of anything you split exist nowhere else. Keeping every generation would
be the safe answer and also the wrong one, on a chapter that is a third of a
gigabyte.

Two other things in the same paste:

* the re-cut switch on the File tab was still there on manga. lee: *"the
  setting shoud not be there for manga"*.
* a page whose picture never arrives used to leave the canvas scrolled to 0,0,
  which is deep inside the stage's 46vmax margin - a screen of nothing at all.
"""
import json
import os
import shutil
import threading
import urllib.request

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from mangatl.project import Project

W = 320


def _img(h=400, seed=1):
    return np.repeat(np.random.default_rng(seed).integers(
        60, 200, (h, W, 1), dtype=np.uint8), 3, axis=2)


def _png(h=400, seed=1):
    return cv2.imencode(".png", _img(h, seed))[1].tobytes()


@pytest.fixture()
def proj(tmp_path):
    p = Project(None, str(tmp_path / "out"))
    yield p
    shutil.rmtree(str(tmp_path / "out"), ignore_errors=True)


def _serve(p):
    was, editor.PROJECT = editor.PROJECT, p
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, was, "http://127.0.0.1:%d" % srv.server_address[1]


def _post(base, route, body):
    req = urllib.request.Request(base + route, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# ------------------------------------------------- the folder is emptied

def test_the_last_chapters_files_are_not_in_the_upload_folder(proj):
    for i in range(3):
        proj.add_uploaded("page%03d.png" % i, _png(seed=i))
    d = proj.upload_dir()
    assert len(os.listdir(d)) == 3

    moved = proj.put_the_last_chapter_away()
    assert moved == 3
    assert os.listdir(d) == [], os.listdir(d)


def test_they_are_moved_and_not_deleted(proj):
    """The re-cut pages and the halves of anything you split exist nowhere
    else. Tidy is not worth a chapter."""
    proj.add_uploaded("page001.png", _png())
    was = proj.pages[0].path
    proj.put_the_last_chapter_away()
    kept = os.path.join(proj.output_dir, "input-previous", "page001.png")
    assert not os.path.isfile(was)
    assert os.path.isfile(kept)


def test_only_one_chapter_back_is_kept(proj):
    """Every generation would be the safe answer and the wrong one: a webtoon
    chapter is a third of a gigabyte and this runs on every new project."""
    proj.add_uploaded("first.png", _png(seed=1))
    proj.put_the_last_chapter_away()
    proj.add_uploaded("second.png", _png(seed=2))
    proj.put_the_last_chapter_away()
    prev = os.path.join(proj.output_dir, "input-previous")
    assert sorted(os.listdir(prev)) == ["second.png"]


def test_an_empty_folder_is_left_alone(proj):
    """It exists - `upload_dir()` makes it - and it has nothing in it. Moving
    an empty folder aside throws away the one generation that was being kept
    and puts an empty one in its place, so the chapter before last is gone for
    no reason at all."""
    proj.add_uploaded("real.png", _png())
    proj.put_the_last_chapter_away()          # `real.png` is now the kept one
    assert os.path.isdir(proj.upload_dir())
    assert os.listdir(proj.upload_dir()) == []

    assert proj.put_the_last_chapter_away() == 0
    assert sorted(os.listdir(
        os.path.join(proj.output_dir, "input-previous"))) == ["real.png"]


def test_a_rescan_after_it_finds_only_the_new_chapter(proj):
    """The bug itself, end to end. A rescan is what happens when the project
    is reopened, and it is what put lee's old `page0xx` files back in a list
    of manga pages."""
    for i in range(3):
        proj.add_uploaded("page%03d.png" % i, _png(seed=i))
    proj.put_the_last_chapter_away()
    for n in (24, 25):
        proj.add_uploaded("%03d.jpg" % n, _png(seed=n))
    proj.rescan()
    assert sorted(pg.name for pg in proj.pages) == ["024.jpg", "025.jpg"]


def test_starting_a_new_chapter_empties_it(proj):
    """Through the route the browser actually calls. `/api/reset` is the first
    thing an upload does."""
    proj.add_uploaded("page001.png", _png())
    srv, was, base = _serve(proj)
    try:
        _post(base, "/api/reset", {"keep_settings": True})
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
    assert os.listdir(proj.upload_dir()) == []
    assert os.path.isfile(os.path.join(proj.output_dir, "input-previous",
                                       "page001.png"))


# ------------------------------------------------------- renumbering

def test_the_knife_puts_the_numbering_straight(proj):
    """lee: *"wheni clcik splite it shoud rename every file from 1 - whatever
    so teh pages are properly numbered"*.

    `012a` and `012b` sort where `012` sorted, which is right, and is also how
    a chapter comes to be called 011, 012a, 012b, 013."""
    for n in (11, 12, 13):
        proj.add_uploaded("%03d.png" % n, _png(seed=n))
    assert proj.split_page(1, 200)[0]
    assert [pg.name for pg in proj.pages] == \
        ["001.png", "002.png", "003.png", "004.png"]


def test_joining_renumbers_too(proj):
    for n in (1, 2, 3):
        proj.add_uploaded("%03d.png" % n, _png(seed=n))
    assert proj.merge_pages(0, 2)[0]
    assert [pg.name for pg in proj.pages] == ["001.png", "002.png"]


def test_the_order_is_kept_and_the_pictures_go_with_the_names(proj):
    """Renaming in the wrong order - or renaming the file without moving the
    page's path with it - shuffles the chapter, which is unrecoverable."""
    for n in (11, 12, 13):
        proj.add_uploaded("%03d.png" % n, _png(seed=n))
    before = [proj.image(i).copy() for i in range(3)]
    proj.split_page(2, 200)
    proj._img_cache.clear()
    assert np.array_equal(proj.image(0), before[0])
    assert np.array_equal(proj.image(1), before[1])
    assert np.array_equal(np.vstack([proj.image(2), proj.image(3)]), before[2])


def test_renumbering_over_names_that_are_already_taken(proj):
    """A chapter numbered from 1 already. `002` becoming `001` while another
    `001` is still there is a page lost, so it goes through temporary names."""
    for n in (1, 2, 3):
        proj.add_uploaded("%03d.png" % n, _png(seed=n))
    shots = [proj.image(i).copy() for i in range(3)]
    assert proj.renumber_pages() == 0, "they are already right"
    proj.split_page(0, 200)
    proj._img_cache.clear()
    assert [pg.name for pg in proj.pages] == \
        ["001.png", "002.png", "003.png", "004.png"]
    assert all(os.path.isfile(pg.path) for pg in proj.pages)
    assert np.array_equal(proj.image(2), shots[1]), "page 2 is still page 2"


def test_nothing_else_ever_renames_a_persons_files(proj):
    """An editor that quietly renumbers a folder every time you open it is an
    editor you cannot hand a folder to. Only the knife does this."""
    for n in (7, 9):
        proj.add_uploaded("%03d.jpg" % n, _png(seed=n))
    proj.rescan()
    proj.restitch_if_sliced()
    assert [pg.name for pg in proj.pages] == ["007.jpg", "009.jpg"]


def test_the_extension_travels_with_the_page(proj):
    """A page renamed to the wrong extension is a page the reader cannot
    open."""
    proj.add_uploaded("a.jpg", cv2.imencode(".jpg", _img())[1].tobytes())
    proj.add_uploaded("b.png", _png(seed=4))
    proj.split_page(0, 200)
    assert [pg.name for pg in proj.pages] == \
        ["001.jpg", "002.jpg", "003.png"]
