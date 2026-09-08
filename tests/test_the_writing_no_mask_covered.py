"""The kana the cleaner never had in a mask, and the 23% of every fill that
was never replaced.

lee, with two crops of a cleaned white balloon that still plainly says しゅぁ
and もる: *"can you fix the issue of the text not fully getting clenned off
boxes"*. Before that, with four more: *"i also want to create a systhem that
looks for thet text ain the boxes and tells teh clenner where they are and the
clenner will only clenn that are isnstad of the whoile box"*, and then the
question this whole file is the answer to - *"can read text return the are athat
need to be clenned?"*

Yes. Two separate bugs were under that one screenshot.

## 1 - the balloon stopped short of the writing

Both ghost tests in this file start from `rec["ink"]` - from WHERE THE MASK WENT
- so a glyph no mask ever covered is invisible to them by construction. On page
003 the balloon finder's interior stops a dozen rows above the last line of
kana. Every step is clipped to that interior, so those kana were never in a
mask; and the fence at the end, which keeps a fill inside the balloon, would
have put them back if they had been.

Inferring it from TONE - "the balloon is clean, so anything off its level is ink
somebody missed" - was tried and marked a balloon outline, a rock texture, hair,
speed lines and a whole small panel of artwork. A level cannot tell writing from
a drawing. What can is the thing trained to, so `_reread` runs the text
segmenter over the FINISHED plate: whatever it still calls text, inside a box
this page cleaned, where nothing was painted, in pieces the size of a letter, is
text that is still there.

Measured on lee's own chapter - his 23 pages, his boxes, his plates:

    boxes the reader points at        2      003's two bubbles, and nothing else
    pages changed                     1      888 pixels
    artwork touched                   0

Both of the two are the crops he sent.

## 2 - and every fill was leaving a quarter of the ink

`_feather` blends the fill over the original across a soft edge, and its
docstring says the ramp lies outside the mask so that "the mask is fully
replaced right up to its own boundary". It did not. A Gaussian at that radius
peaks at 0.77 in the middle of a WIDE stroke and 0.64 on a thin one, so 23% to
36% of the original ink survived every fill this file makes - the model's and
the local one's. On black glyphs over white paper that is a pixel at 206: a
legible outline of the word that was there, on an otherwise clean patch. It is
exactly the ghost `ghost_detail` was written to catch, and it was being made
here.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion


import contextlib


@contextlib.contextmanager
def _no_ground():
    """Test the second look on its own terms.

    These fixtures are writing on plain paper, and since `_off_the_ground` the
    FIRST pass takes that outright - it measures the box's own ground and
    erases what stands off it, the mark set apart from the column included. So
    on paper there is nothing left for a second look to find, which is the
    right answer and no test of the thing this file is about. What the second
    look is for now is the ground the first pass declines to model - artwork
    and screentone - and the way to exercise it here is to have the first pass
    decline, which is what this does.
    """
    was = I._off_the_ground
    I._off_the_ground = lambda *a, **k: None
    try:
        yield
    finally:
        I._off_the_ground = was


# ------------------------------------------------- what counts as writing

def test_a_run_of_small_marks_is_writing():
    """lee's box, in numbers: the three kana left standing measure 230, 53 and
    36 pixels. A per-piece threshold that keeps the 36 keeps a speck of tone,
    and one that drops it erases one character of three."""
    m = np.zeros((60, 120), bool)
    m[20:38, 20:38] = True                 # 324
    m[24:32, 50:57] = True                 # 56
    m[25:31, 70:76] = True                 # 36
    kept = I._whole_glyphs(m)
    assert kept[24:32, 50:57].all() and kept[25:31, 70:76].all()


def test_and_a_speck_on_its_own_is_not():
    m = np.zeros((60, 120), bool)
    m[25:31, 70:76] = True                 # the same 36 pixels, alone
    assert not I._whole_glyphs(m).any()


def test_the_gaps_a_run_is_grouped_across_are_never_painted():
    m = np.zeros((60, 120), bool)
    m[20:38, 20:38] = True
    m[25:31, 70:76] = True
    kept = I._whole_glyphs(m)
    assert not kept[25:31, 40:70].any(), "the space between two kana is paper"


# ------------------------------------------------------ what the reader is for

def _page_with_a_kana_the_mask_missed():
    """A white balloon, a column of writing, and one mark set apart from it.

    The mask is built from the column alone - which is what a balloon interior
    that stops short of the last mark produces, and what lee's page 003 is.
    """
    img = np.full((260, 260, 3), 255, np.uint8)
    cv2.circle(img, (130, 130), 120, (0, 0, 0), 3)
    for y in (60, 92, 124):
        cv2.putText(img, "A", (108, y + 24), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (0, 0, 0), 3)
    cv2.putText(img, "B", (108, 196), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 0, 0), 3)      # ...and this one nothing will erase
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    seen = np.zeros(g.shape, np.uint8)
    seen[30:150, 100:150] = 255
    bm = np.zeros(g.shape, np.uint8)
    cv2.circle(bm, (130, 130), 116, 255, -1)
    r = TextRegion(id=0, bbox=(96, 30, 60, 180), kind="bubble",
                   text_mask=((g <= 128) & (seen > 0)).astype(np.uint8) * 255,
                   bubble_mask=bm, bubble_bbox=(14, 14, 232, 232))
    r.src_text, r.order = "a", 0
    page = Page(image=img, source_path="t.png")
    page.regions = [r]
    return page


def _reader(page):
    """Stands in for comic-text-detector: it calls the glyphs text and the
    balloon outline artwork, which is what the real one does."""
    def look(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        m = np.zeros(g.shape, np.uint8)
        m[20:230, 96:160] = 255
        return ((g <= 128) & (m > 0)).astype(np.uint8) * 255
    return look


def test_the_mark_the_mask_missed_is_erased():
    page = _page_with_a_kana_the_mask_missed()
    before = page.image.copy()
    out = I.inpaint_page(page, look=_reader(page))
    was = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)[186:210, 100:140]
    now = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[186:210, 100:140]
    assert was.min() < 60, "the fixture has to have writing there"
    assert now.min() > 200, "and it is still on the page"


def test_with_no_reader_the_page_is_cleaned_exactly_as_before():
    """The check is a setting and an extra pass, not a rewrite of the cleaner.
    A project with no detector weights has no reader and must get the page it
    has always got."""
    with _no_ground():
        a = I.inpaint_page(_page_with_a_kana_the_mask_missed())
        b = I.inpaint_page(_page_with_a_kana_the_mask_missed(), look=None)
    assert np.array_equal(a, b)
    was = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)[186:210, 100:140]
    assert was.min() < 60, "...and without one, the mark is still there"


def test_the_count_says_how_many_boxes_it_found_something_in():
    """A reader that saw nothing beside a column of type, and sees it once the
    column is gone. That is not a contrivance - it is why there are two looks:
    the second one is taken of a page with almost nothing on it."""
    page = _page_with_a_kana_the_mask_missed()
    seen = {"n": 0}

    def late(img):
        seen["n"] += 1
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        m = np.zeros(g.shape, np.uint8)
        if seen["n"] > 1:                  # the plate, not the scan
            m[180:215, 96:160] = 255
        return ((g <= 128) & (m > 0)).astype(np.uint8) * 255
    with _no_ground():
        I.inpaint_page(page, look=late)
    assert seen["n"] == 2, "the page is read once before and once after"
    assert page.clean_stats.get("missed text found") == 1
    assert "reread" in page.regions[0].clean_route


def test_a_reader_that_fails_does_not_fail_the_page():
    def angry(img):
        raise RuntimeError("no weights")
    page = _page_with_a_kana_the_mask_missed()
    out = I.inpaint_page(page, look=angry)
    assert np.array_equal(out, I.inpaint_page(
        _page_with_a_kana_the_mask_missed()))


def test_nothing_outside_the_box_is_looked_at():
    """Run on lee's page 001 the reader still marks 44% of what it marked on
    the original, and nearly all of it is a painted chapter title and two drawn
    sound effects nobody drew a box round. They are not residue - they are text
    this page was never asked to erase."""
    page = _page_with_a_kana_the_mask_missed()
    img = page.image
    cv2.putText(img, "T", (14, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 0, 0), 3)              # outside the box, and text
    def look(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return (g <= 128).astype(np.uint8) * 255
    out = I.inpaint_page(page, look=look)
    a = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[225:255, 10:45]
    b = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[225:255, 10:45]
    assert np.array_equal(a, b), "it erased a title nobody boxed"


def test_and_neither_is_anything_the_cleaner_painted():
    """A stroke that was erased and left a faint rim is still read as text, and
    it is not this test's business: `ghost_delta` and `ghost_detail` have been
    asking about exactly that for a version, and they can say how faint it is.
    This one is only ever about pixels NOTHING touched."""
    page = _page_with_a_kana_the_mask_missed()
    column = page.regions[0].text_mask > 0     # what was erased, to the pixel
    seen = {}
    real = I._whole_glyphs

    def spy(mask):
        seen["px"] = int(np.asarray(mask).sum()) + seen.get("px", 0)
        return real(mask)
    I._whole_glyphs = spy
    try:
        # A reader that still calls the erased column text, which is what a
        # real one does over a fill that left a rim.
        with _no_ground():
            I.inpaint_page(page, look=lambda img: column.astype(np.uint8) * 255)
    finally:
        I._whole_glyphs = real
    assert seen.get("px", 0) == 0, "the cleaned column came back as residue"


def test_a_reader_that_disagrees_about_the_whole_box_changes_nothing():
    """Erasing "most of a box" on the strength of a second opinion is how a
    panel of artwork goes, and artwork does not come back."""
    page = _page_with_a_kana_the_mask_missed()
    before = page.image.copy()

    def everything(img):
        return np.full(img.shape[:2], 255, np.uint8)
    with _no_ground():
        out = I.inpaint_page(page, look=everything)
    box = (slice(186, 215), slice(100, 150))
    assert np.array_equal(before[box], out[box]), "it repainted the box"
    assert "most of this box" in (page.regions[0].flagged or "")


# --------------------------------------------- and the fence lets it through

def test_the_fence_opens_for_writing_a_reader_named_and_for_nothing_else():
    """The balloon clause, and only that: on lee's page the words are inside
    his box, on the balloon's own white, and outside the interior the finder
    drew. Clipped to that shape the cleaner cannot reach them.

    A trained reader calling those pixels writing is the one claim that
    outranks a guessed outline - and it is still inside the box he drew, which
    is the rule he actually stated: *"it hsoud never touch a pixel outside teh
    box area ... the box that i see"*.
    """
    page = _page_with_a_kana_the_mask_missed()
    bm = page.regions[0].bubble_mask
    cv2.circle(bm, (130, 130), 116, 0, -1)
    cv2.circle(bm, (130, 100), 70, 255, -1)     # ...well short of the "B"
    assert not bm[196, 118], "the fixture has to leave it outside"
    out = I.inpaint_page(page, look=_reader(page))
    now = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[186:210, 100:140]
    assert now.min() > 200
    x, y, w, h = (int(v) for v in page.regions[0].bbox)
    changed = np.abs(page.image.astype(int) - out.astype(int)).max(2) > 2
    room = np.zeros(changed.shape, bool)
    room[max(0, y - I.GLYPH_REACH):y + h + I.GLYPH_REACH,
         max(0, x - I.GLYPH_REACH):x + w + I.GLYPH_REACH] = True
    assert not (changed & ~room).any(), "it painted outside the box"


# ------------------------------------------ why it is asked as its own question

def test_a_little_residue_beside_a_lot_of_clean_is_invisible_to_a_median():
    """Both ghost measures are medians over the whole ink mask. Folding the
    reader's find into it and asking once would ask about three thousand
    cleaned pixels and two hundred kana, and a median does not hear the two
    hundred. Measured as its own mask it is the loudest thing on the page."""
    page = np.full((120, 400), 255, np.uint8)
    cleaned = np.zeros(page.shape, bool)
    cleaned[20:100, 20:300] = True         # a big, properly cleaned area
    left = np.zeros(page.shape, bool)
    left[40:70, 330:360] = True
    page[left] = 30                        # ...and a small mark still on it
    before = np.full((120, 400), 255, np.uint8)
    before[cleaned] = 30
    before[left] = 30
    folded = cleaned | left
    assert I.ghost_delta(before, page, folded) <= I.GHOST_TOL
    assert I.ghost_delta(before, page, left) > I.GHOST_TOL


def test_and_the_flag_says_which_question_caught_it():
    page = np.full((120, 400), 255, np.uint8)
    left = np.zeros(page.shape, bool)
    left[40:70, 330:360] = True
    page[left] = 30
    before = np.full((120, 400), 255, np.uint8)
    before[left] = 30
    rec = {"win": (slice(0, 120), slice(0, 400)),
           "ink": np.zeros(page.shape, bool), "inv": False, "left": left}
    still, how = I._ghost_left(before, page, rec)
    assert still and how.startswith("missed")


def test_a_repaired_box_stops_saying_it():
    """The same measurement is what clears it, so nothing has to remember to."""
    page = np.full((120, 400), 255, np.uint8)
    left = np.zeros(page.shape, bool)
    left[40:70, 330:360] = True
    before = np.full((120, 400), 255, np.uint8)
    before[left] = 30                      # it WAS there; the page is clean now
    rec = {"win": (slice(0, 120), slice(0, 400)),
           "ink": np.zeros(page.shape, bool), "inv": False, "left": left}
    assert not I._ghost_left(before, page, rec)[0]


# ------------------------------------------------------------- and the feather

def test_a_fill_replaces_every_pixel_of_its_own_mask():
    """23% of the ink survived every fill in this file, model and local alike.
    A black glyph over white paper came back at 206, which is legible."""
    orig = np.full((60, 60, 3), 255, np.uint8)
    orig[10:50, 28:33] = 20                # a stroke
    mask = np.zeros((60, 60), np.uint8)
    mask[10:50, 28:33] = 255
    filled = np.full((60, 60, 3), 255, np.uint8)
    out = I._feather(orig, filled, mask)
    assert int(out[mask > 0].min()) == 255


def test_a_one_pixel_stroke_too():
    """The thinner it is, the worse it was: the alpha reached 0.64 there."""
    orig = np.full((60, 60, 3), 255, np.uint8)
    orig[10:50, 30] = 20
    mask = np.zeros((60, 60), np.uint8)
    mask[10:50, 30] = 255
    out = I._feather(orig, np.full((60, 60, 3), 255, np.uint8), mask)
    assert int(out[mask > 0].min()) == 255


def test_and_the_seam_outside_it_is_still_soft():
    """The ramp was always meant to be the pixels OUTSIDE. A hard boundary
    reads as damage - lee: *"some if teh sfx clenning has aome notisable
    edges"*."""
    orig = np.full((60, 60, 3), 40, np.uint8)
    mask = np.zeros((60, 60), np.uint8)
    mask[20:40, 20:40] = 255
    out = I._feather(orig, np.full((60, 60, 3), 255, np.uint8), mask)
    ring = out[18, 30, 0]
    assert 40 < int(ring) < 255, "no ramp at all is a rectangle on the page"


# --------------------------------------------------------------- the plumbing

def test_the_reader_is_the_detector_the_page_was_found_with():
    """Nothing to set up and nothing to download: a project that can find its
    text can check it."""
    import tempfile
    from mangatl.project import Project
    from mangatl import editor as E
    p = Project(None, tempfile.mkdtemp())
    p.settings["weights"] = "/definitely/not/here.onnx"
    assert E._make_reader(p) is None, "a missing weights file is not a reader"


def test_and_the_switch_turns_it_off():
    import tempfile
    from mangatl.project import Project
    from mangatl import editor as E
    p = Project(None, tempfile.mkdtemp())
    p.settings["clean_reread"] = False
    assert E._make_reader(p) is None


def test_it_is_on_by_default():
    import tempfile
    from mangatl.project import Project
    p = Project(None, tempfile.mkdtemp())
    assert p.settings["clean_reread"] is True


def test_both_copies_of_the_defaults_have_it():
    from where import PKG
    # ("_pj.py", the old project.py snapshot, went in the 2026-09-02
    # dead-code sweep.)
    for f in ("project.py",):
        assert '"clean_reread": True' in \
            (PKG / f).read_text(encoding="utf-8"), f


def test_turning_it_off_retires_the_plates():
    """Otherwise a page keeps the plate the check already cleaned, and the
    switch does nothing anybody can see. lee: *"nothing vhanged"*."""
    import tempfile
    from mangatl.project import Project
    from mangatl import editor as E
    p = Project(None, tempfile.mkdtemp())
    img = np.full((200, 200, 3), 250, np.uint8)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.pages[0].regions = [{"id": 1, "kind": "bubble", "order": 0,
                           "bbox": [40, 40, 90, 60]}]
    a = E._plate_stamp(p, 0)
    p.settings["clean_reread"] = False
    assert E._plate_stamp(p, 0) != a


def test_the_switch_is_on_the_settings_page_and_defaults_on():
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    at = html.index('id="clean_reread"')
    assert "checked" in html[at:at + 200]
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    line = js[js.index("const DEFAULT_ON"):]
    assert "clean_reread" in line[:line.index("\n")], \
        "read with !==false, or a project saved before it existed is off"


def test_the_cleaner_version_was_bumped():
    """It changes pixels twice over - writing no mask covered is erased, and
    every fill now replaces the whole of its own mask. A plate made before it
    still has both on it."""
    assert I.ALGO >= "2026-08-23-a"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
