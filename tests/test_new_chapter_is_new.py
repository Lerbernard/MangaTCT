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


# --------------------------------- the last chapter's story is not this one's

def test_a_new_chapter_does_not_inherit_the_last_ones_synopsis(tmp_path):
    """lee, uploading a new chapter with the last one's synopsis in front of
    him: *"im oploading a new chapter thsi should not be there"*, and then
    *"its here to and a new project"* - the settings screen showing it as
    well, which is what says the value had reached the SERVER rather than
    being left on a stale screen.

    The server side was already right: `/api/reset` builds a fresh
    `SeriesContext` carrying only the configuration - honorifics, medium,
    target, source, backend, key - and drops the story's own content. The
    round trip is what put it back. Step 2 of the picker holds a VIEW of the
    title and synopsis, filled from the project when the step is shown; a
    reset under those boxes left them saying what the last chapter said, and
    `pkSaveContext` then did exactly its job - it found the boxes disagreeing
    with the project and wrote the boxes back.

    Both halves are pinned here: the reset really clears it, and the browser
    has a hook to stop the boxes restoring it. The end-to-end proof is the
    jsdom-free probe in the session notes; this is the guard that survives.
    """
    from mangatl.project import SeriesContext
    from where import PKG

    p = Project(None, str(tmp_path / "out"))
    p.ctx.synopsis = "LAST CHAPTER: a saint, a maid, and a lot of water."
    p.ctx.title = "Last Chapter"
    p.ctx.glossary = {"성녀": "saint"}
    p.settings["medium"] = "manhwa"
    p.save()

    # what /api/reset does, in the same order and with the same arguments
    old = p.ctx
    p.clear()
    p.ctx = SeriesContext(
        honorifics=old.honorifics, medium=old.medium, target=old.target,
        source=old.source, backend=old.backend, base_url=old.base_url,
        model=old.model, api_key=old.api_key)
    p.save()
    assert not p.ctx.synopsis, "the reset kept the last chapter's synopsis"
    assert not p.ctx.title
    assert not p.ctx.glossary, "and its glossary"
    # ...and the configuration it is right to keep is still there
    assert p.ctx.medium == old.medium and p.ctx.target == old.target

    # THE BROWSER'S HALF. The boxes are a view of the project, so something
    # has to tell them the project underneath them was just emptied - or
    # `pkSaveContext` writes the old words back the moment the step closes.
    js = (PKG / "static" / "js" / "project-io.js").read_text(encoding="utf-8")
    assert "function pkAfterReset" in js, "nothing clears the story boxes"
    body = js[js.index("function pkAfterReset"):]
    body = body[:body.index("\n}") + 2]
    assert "primed = false" in body, \
        "the boxes are cleared but still allowed to save themselves back"
    # every place the project is reset calls it
    assert js.count("pkAfterReset()") >= 3, \
        "a reset path that does not tell the story boxes about it"
