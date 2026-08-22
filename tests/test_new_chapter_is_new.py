"""A new chapter is never the old one.

lee: *"wheni uploaded a new chnater the old chapter is showing up as teh new
chnapeter this shoud neveer happen"*.

Three separate caches named a page by what it was CALLED and how big it was:

* `_scan_key` - the token on the `/img/` URL, served with
  `Cache-Control: immutable`, so the browser is entitled to never ask again;
* `_render_stamp` - the rendered clean and typeset pages;
* `_plate_stamp` - the cleaned plate, which is kept on disk.

For one chapter that is enough. Chapters are numbered the same way every time
- `001.png`, `002.png` - and scanned at the same size, so page 1 of the new
chapter had the same name, the same width and the same height as page 1 of the
old one. Every key matched, and the browser answered from its own cache with a
picture it had been told would never change. It never does; it was a picture of
a different chapter.

So a page is named by what is IN it. Two different pictures cannot share a key,
whatever they are called.
"""
import shutil

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor
from mangatl.project import Project


def _png(fill, mark=None):
    """Same size, same name, different picture - the case that broke."""
    img = np.full((400, 300, 3), fill, np.uint8)
    if mark is not None:
        cv2.circle(img, mark, 40, (10, 10, 10), -1)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def proj(tmp_path):
    root = str(tmp_path / "out")
    p = Project(None, root)
    yield p
    shutil.rmtree(root, ignore_errors=True)


def test_two_different_pages_under_one_name_get_different_keys(proj):
    """The whole bug, at its root."""
    proj.add_uploaded("001.png", _png(240, (100, 100)))
    first = editor._scan_key(proj, 0)
    proj.clear()
    proj.add_uploaded("001.png", _png(240, (200, 300)))
    assert editor._scan_key(proj, 0) != first


def test_the_same_page_keeps_its_key(proj):
    """The point of the key is that going back to a page you have already seen
    costs nothing. A key that changed every time would be no key at all."""
    data = _png(240, (100, 100))
    proj.add_uploaded("001.png", data)
    assert editor._scan_key(proj, 0) == editor._scan_key(proj, 0)


def test_two_pages_of_the_same_blank_size_are_told_apart(proj):
    """Two DIFFERENT files that happen to be identical byte for byte are the
    same picture and may share a key - but two pages of one chapter are not,
    and this is the case where name and size say they are."""
    proj.add_uploaded("001.png", _png(240, (80, 80)))
    proj.add_uploaded("002.png", _png(240, (220, 320)))
    assert editor._scan_key(proj, 0) != editor._scan_key(proj, 1)


def test_the_rendered_page_is_not_the_old_chapters(proj):
    """`/img/` is only the original scan. Clean and Typeset come through a
    different cache with a key of its own, and it had the same hole."""
    proj.add_uploaded("001.png", _png(240, (100, 100)))
    first = editor._render_key(proj, 0)
    proj.clear()
    proj.add_uploaded("001.png", _png(240, (200, 300)))
    assert editor._render_key(proj, 0) != first


def test_the_cleaned_plate_is_not_the_old_chapters(proj):
    """This one is kept on DISK, so it outlives the run that made it - a
    restart would not have shaken it loose."""
    proj.add_uploaded("001.png", _png(240, (100, 100)))
    first = editor._plate_stamp(proj, 0)
    proj.clear()
    proj.add_uploaded("001.png", _png(240, (200, 300)))
    assert editor._plate_stamp(proj, 0) != first


def test_a_page_edited_on_disk_underneath_is_noticed(proj):
    """The answer is kept against the file's size and modification time. A file
    rewritten in place is exactly the case where trusting the path alone would
    hand back the fingerprint of what used to be there."""
    proj.add_uploaded("001.png", _png(240, (100, 100)))
    was = editor._scan_key(proj, 0)
    import os
    import time
    with open(proj.pages[0].path, "wb") as fh:
        fh.write(_png(240, (200, 300)))
    # a rewrite inside the same clock tick is the hard case
    os.utime(proj.pages[0].path, ns=(time.time_ns(), time.time_ns()))
    assert editor._scan_key(proj, 0) != was


def test_a_page_whose_file_has_gone_does_not_take_the_editor_down(proj):
    """A saved project pointing at pages that have moved. Every one of these
    keys is asked for on the way to drawing a page; raising here would mean a
    blank editor rather than one missing picture."""
    proj.add_uploaded("001.png", _png(240, (100, 100)))
    import os
    os.remove(proj.pages[0].path)
    assert isinstance(editor._scan_key(proj, 0), str)
    assert editor._scan_key(proj, 0)


def test_the_answer_is_not_worked_out_twice_for_one_file(proj):
    """Hashing a few megabytes is cheap once and not cheap on every page view -
    and this is asked for by the URL builder, the render cache and the plate
    cache, all three, on every single page."""
    proj.add_uploaded("001.png", _png(240, (100, 100)))
    editor._scan_key(proj, 0)
    reads = {"n": 0}
    real = open

    def counting(path, *a, **k):
        if str(path) == proj.pages[0].path and "b" in (a[0] if a else ""):
            reads["n"] += 1
        return real(path, *a, **k)

    import builtins
    builtins.open = counting
    try:
        for _ in range(5):
            editor._scan_key(proj, 0)
    finally:
        builtins.open = real
    assert reads["n"] == 0, reads
