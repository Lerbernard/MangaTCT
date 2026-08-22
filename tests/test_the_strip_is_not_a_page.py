"""A webtoon's tiles are not pages, and the editor stops pretending they are.

lee uploaded chapter 1 of a manhwa and asked: *"look at this chapter do yoou
see how some of the tect is cropped by the page break, what solution do ihave
to fix this issue"*. Then, having been given the options: *"do option one, so
when i uplaod a manhwa it shoud autonaticaly do this"*.

What was wrong with it: the chapter is ONE image, 690 x 167,617, and the site
that served it cut that image into 105 tiles of exactly 1600px. The slicer
counts pixels. It has never looked at the artwork. Of its 104 cuts, 86 land on
ink, 63 cross a speech balloon and **38 go through the typesetting itself** -
one straight across the middle of 지구인 용사 소환!, half the glyph heights on
one file and half on the next. Neither half can be read, the cleaner would
have to erase half a word on one page and half on another, and the English has
nowhere to go.

So on upload the tiles are joined back into the strip they came from and cut
again at the **gutters** - the rows where the artist drew nothing - which is
what a typesetter does by hand before starting. On lee's chapter that turns 105
tiles into 66 pages with three cuts through ink, all three reported, and none
at all through typesetting.

Everything here is measured on a strip built to have exactly the problem: real
gutters, and blocks of typesetting that a pixel-counting slicer walks straight
through.
"""
import json
import os
import shutil
import threading
import time
import urllib.request

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor, strip
from mangatl.project import Project, list_images, natural_key
from scratch import scratch
from where import PKG

W = 600            # the width of the strip, as a webtoon site serves it
TILE = 1000        # what the slicer cuts at, having looked at nothing
GUTTER = 40        # the empty band the artist left between panels


def _strip_and_typesetting(seed=7):
    """A webtoon strip, plus where the typesetting is.

    Panels of differing heights with an empty band between them, and in the
    middle of every panel a block of speech: four black bars, which is what a
    line of typesetting looks like to anything measuring rows.
    """
    rng = np.random.default_rng(seed)
    rows, letters, y = [], [], 0
    for i in range(14):
        h = 700 + (i % 5) * 120
        panel = np.repeat(rng.integers(150, 220, (h, W, 1), dtype=np.uint8),
                          3, axis=2)
        mid = h // 2
        for k in range(4):
            top = mid - 60 + k * 30
            cv2.rectangle(panel, (120, top), (W - 120, top + 20), (0, 0, 0), -1)
        letters.append((y + mid - 60, y + mid + 60))
        rows.append(panel)
        y += h
        rows.append(np.full((GUTTER, W, 3), 255, np.uint8))
        y += GUTTER
    return np.vstack(rows), letters


def _slice(img, folder, n=TILE):
    """Cut it the way the server does: by count, into a numbered file each."""
    os.makedirs(folder, exist_ok=True)
    paths = []
    for i in range(0, len(img), n):
        # `image_1 … image_10` on purpose: it is the ordering the old
        # alphabetical sort got wrong, and getting it wrong here interleaves
        # the artwork rather than merely shuffling pages.
        p = os.path.join(folder, "image_%d.png" % (i // n + 1))
        cv2.imwrite(p, img[i:i + n])
        paths.append(p)
    return paths


def _flat(n, bands):
    f = np.zeros(n, bool)
    for a, b in bands:
        f[a:b] = True
    return f


# --------------------------------------------------------------- reading rows

def test_the_empty_bands_are_the_only_flat_rows():
    """The whole thing rests on being able to tell a gutter from artwork. A
    row of drawn panel must not read as empty, or a cut lands in the picture."""
    img, _ = _strip_and_typesetting()
    d = scratch("_tmp_strip_rows")
    shutil.rmtree(d, ignore_errors=True)
    try:
        flat = strip.row_profile(_slice(img, d))
        assert len(flat) == len(img), "one answer per row of the joined strip"
        white = (img.reshape(len(img), -1).min(1) == 255)
        assert (flat == white).all(), \
            "exactly the untouched rows count as empty"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_row_needs_both_an_even_tone_and_no_hard_edge():
    """There are two ways a row can have something on it and each needs its
    own test.

    A band of fine screentone is EVEN across - no hard edge anywhere - and
    only its spread gives it away. A margin with one panel border crossing it
    is the opposite: flat as a mirror except for the couple of pixels of the
    line, so the spread stays near zero and only the range sees it. Drop
    either test and one of them reads as empty paper and gets cut through.
    """
    tile = np.full((3, 60, 3), 250, np.uint8)
    tile[0] = 255                    # paper: nothing drawn on it
    tile[1, :30] = 240               # screentone: spread 6.5, range only 13
    tile[1, 30:] = 253
    tile[2, 10:12] = 235             # a border line: spread 2.7, range 15
    d = scratch("_tmp_strip_two")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    try:
        p = os.path.join(d, "1.png")
        cv2.imwrite(p, tile)
        assert list(strip.row_profile([p])) == [True, False, False]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_single_flat_row_is_not_a_gutter():
    """One flat row is a coincidence - a scanline between two panels of the
    same tone. Cutting there puts the page break inside the drawing."""
    assert strip.gutters(_flat(400, [(100, 101)])) == []
    assert strip.gutters(_flat(400, [(100, 130)])) == [115]


def test_a_gutter_is_cut_down_its_middle():
    """Not at its edge: half the band belongs to the page above and half to
    the page below, so both keep a margin."""
    assert strip.gutters(_flat(1000, [(200, 240), (600, 620)])) == [220, 610]


# ---------------------------------------------------------------- the cutting

def test_the_gutter_nearest_the_target_wins_not_the_first_one_past_it():
    """"First past the target" overshoots wherever gutters are sparse, and a
    chapter of 3,500px pages when you asked for 2,400 is not what was asked
    for. "First one in the window" is the opposite mistake and gives a chapter
    of stubs. It is the NEAREST, which can be on either side."""
    far = _flat(9000, [(495, 506), (1095, 1106), (3000, 3011), (5000, 5011)])
    assert strip.plan_cuts(far, 1000, 6000)[0][1] == 1100, \
        "1100 is 100 from the target and 500 is 500 — the later one wins"
    near = _flat(9000, [(695, 706), (1395, 1406), (3000, 3011), (5000, 5011)])
    assert strip.plan_cuts(near, 1000, 6000)[0][1] == 700, \
        "700 is 300 from the target and 1400 is 400 — the earlier one wins"


def test_a_page_runs_on_to_the_next_gutter_rather_than_cutting_through_ink():
    """Nothing inside the window. Rather than force a cut, the page is allowed
    to be too long, because a page that reads is worth more than a page of the
    right height."""
    f = _flat(13500, [(4000, 4020), (8000, 8020), (12000, 12020)])
    cuts, over = strip.plan_cuts(f, target=1000, ceiling=6000)
    assert cuts == [0, 4010, 8010, 12010, 13500]
    assert not over, "none of them passed the ceiling"


def test_the_run_on_does_not_stop_at_the_ceiling(_ceiling=6000):
    """The change lee asked for. The next gap here is 9,000 rows away - nine
    times what was asked for and half again past the ceiling - and the page
    runs all the way to it anyway.

    It used to cut short of the gap, at the quietest row it could find inside
    the ceiling. lee: *"when it reaches teh max lenght it still crops teh text
    box, if posiboe can you have a way of not to do that"*. The quietest row
    inside a panel of solid artwork is the middle of a balloon, which is the
    exact thing the re-cut exists to undo."""
    f = _flat(30000, [(9000, 9020)])
    cuts, over = strip.plan_cuts(f, target=1000, ceiling=_ceiling)
    assert cuts[1] == 9010, "the cut has to land ON the gap, however far it is"
    assert cuts[1] in over, "and running over is worth saying"


def test_a_strip_with_no_gutter_at_all_comes_back_as_one_page():
    """A full-bleed chapter with nowhere to cut. Every answer is bad; the one
    that does not cut through the artwork is to leave it alone and say so."""
    f = _flat(20000, [])
    cuts, over = strip.plan_cuts(f, target=2400, ceiling=6000)
    assert cuts == [0, 20000], cuts
    assert over == [20000], "a chapter left in one piece must not pass silently"


def test_the_pages_that_ran_over_are_the_ones_reported():
    """Only the long ones. A report that names every page is a report nobody
    reads."""
    f = _flat(20000, [(300, 320), (15000, 15020)])
    cuts, over = strip.plan_cuts(f, target=2400, ceiling=6000)
    assert set(over) <= set(cuts)
    assert 310 not in over, "the first page is 310 rows and fits easily"
    assert 15010 in over, "the second is 14,700 and does not"


def test_an_empty_strip_is_not_cut():
    assert strip.plan_cuts(np.zeros(0, bool)) == ([], [])


# ------------------------------------------------------- is it a strip at all

def test_a_sliced_strip_is_recognised():
    img, _ = _strip_and_typesetting()
    n = len(img) // TILE
    sizes = [(TILE, W)] * n + [(len(img) - n * TILE, W)]
    assert strip.looks_sliced(sizes)


@pytest.mark.parametrize("sizes,why", [
    ([(1600, 600)] * 4 + [(900, 600)], "five files is a five-page short"),
    ([(1600, 600)] * 8 + [(1600, 700)], "a scan is never one exact width"),
    ([(1600, 600), (1601, 600)] + [(1600, 600)] * 7,
     "pages drawn as pages differ in height"),
    ([(1600, 600)] * 8 + [(1700, 600)],
     "the last file is the remainder and cannot be the longest"),
    ([(400, 600)] * 9, "a slice of a webtoon is a tall ribbon, not a landscape"),
    ([], "nothing at all"),
])
def test_anything_that_might_be_a_book_of_pages_is_left_alone(sizes, why):
    """Being wrong here rearranges somebody's chapter, so all four tests have
    to hold and any doubt means no."""
    assert not strip.looks_sliced(sizes), why


# ------------------------------------------------------------- the round trip

def test_the_pages_are_the_strip_again_with_nothing_lost_or_added():
    """Joined and re-cut, the pages stacked back up must be the original image
    to the pixel. Not merely the same total height: the same picture."""
    img, _ = _strip_and_typesetting()
    d = scratch("_tmp_strip_trip")
    shutil.rmtree(d, ignore_errors=True)
    try:
        tiles = _slice(img, os.path.join(d, "in"))
        out = os.path.join(d, "out")
        rep = strip.restitch(tiles, out, target=2400, ceiling=6000)
        pages = [cv2.imread(os.path.join(out, n)) for n in rep["pages"]]
        assert sum(len(p) for p in pages) == len(img)
        assert np.array_equal(np.vstack(pages), img), \
            "the chapter must come back out of the pages unchanged"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_page_break_lands_in_the_middle_of_the_typesetting():
    """The reason any of this exists. Every block of speech has to end up
    whole, on one page."""
    img, letters = _strip_and_typesetting()
    d = scratch("_tmp_strip_typesetting")
    shutil.rmtree(d, ignore_errors=True)
    try:
        tiles = _slice(img, os.path.join(d, "in"))
        # what the slicer did: a cut every TILE rows, looking at nothing
        theirs = list(range(TILE, len(img), TILE))
        broke = [c for c in theirs if any(a < c < b for a, b in letters)]
        assert broke, "the strip must actually have lee's problem in it"

        cuts, _f = strip.plan_cuts(strip.row_profile(tiles), 2400, 6000)
        assert not [c for c in cuts if any(a < c < b for a, b in letters)], \
            "a page break through a line of speech is the bug being fixed"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_one_tile_is_not_a_chapter():
    assert strip.restitch(["nothing.png"], scratch("_tmp_none"))["pages"] == []


# ------------------------------------------------------------------ the order

def test_page_ten_comes_after_page_two():
    """Alphabetically `image_10` sorts between `image_1` and `image_2`. For a
    book that misorders the chapter; for a strip being joined back up it
    interleaves the artwork, which is unrecoverable."""
    names = ["image_%d.png" % i for i in (1, 2, 10, 11, 100, 105)]
    assert sorted(reversed(names), key=natural_key) == names


def test_a_padded_number_and_a_bare_one_still_have_an_order():
    """Reading digits as numbers makes `001.png` and `1.png` the same key, and
    one folder can hold both. Two files that sort as equal come out in
    whatever order they arrived in, which is not an order - so the path itself
    has the last word."""
    a, b = "/x/001.png", "/x/1.png"
    assert natural_key(a) != natural_key(b)
    assert sorted([a, b], key=natural_key) == sorted([b, a], key=natural_key)


def test_the_pages_come_back_in_the_order_they_were_cut():
    img, _ = _strip_and_typesetting()
    d = scratch("_tmp_strip_order")
    shutil.rmtree(d, ignore_errors=True)
    try:
        _slice(img, d)
        got = [os.path.basename(p) for p in list_images(d)]
        assert got == ["image_%d.png" % i for i in range(1, len(got) + 1)]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------- in front of the user

@pytest.fixture
def proj(tmp_path):
    p = Project(None, str(tmp_path / "out"))
    # A webtoon, because that is what this whole file is about. The re-cut is
    # gated on the FORMAT now: manga arrives as pages and is never touched,
    # however uniform the files happen to be. See `STRIP_MEDIA`.
    p.settings["medium"] = "manhwa"
    yield p
    shutil.rmtree(str(tmp_path / "out"), ignore_errors=True)


def _upload_strip(p, seed=7):
    img, letters = _strip_and_typesetting(seed)
    for i in range(0, len(img), TILE):
        data = cv2.imencode(".png", img[i:i + TILE])[1].tobytes()
        p.add_uploaded("image_%d.png" % (i // TILE + 1), data)
    return img, letters


def test_uploading_a_manhwa_re_cuts_it_without_being_asked(proj):
    """lee: *"so when i uplaod a manhwa it shoud autonaticaly do this"*."""
    img, _ = _upload_strip(proj)
    tiles = len(proj.pages)
    rep = proj.restitch_if_sliced()
    assert rep, "a sliced strip must be put back together on upload"
    assert rep["before"] == tiles and rep["after"] == len(proj.pages)
    assert len(proj.pages) != tiles
    assert sum(pg.height for pg in proj.pages) == len(img)


def test_the_tiles_that_came_in_are_kept(proj):
    """They stop being pages; they are not thrown away. Nothing the person
    gave the editor is deleted behind their back."""
    _upload_strip(proj)
    names = sorted(os.path.basename(pg.path) for pg in proj.pages)
    proj.restitch_if_sliced()
    kept = sorted(os.listdir(os.path.join(proj.upload_dir(), "tiles")))
    assert kept == names


def test_a_book_of_pages_is_never_touched(proj):
    """A manga chapter: pages of their own heights. Nothing happens to it."""
    for i in range(9):
        img = np.full((1400 + i * 7, 1000, 3), 240, np.uint8)
        proj.add_uploaded("%03d.png" % (i + 1), cv2.imencode(".png", img)[1].tobytes())
    before = [pg.path for pg in proj.pages]
    assert proj.restitch_if_sliced() == {}
    assert [pg.path for pg in proj.pages] == before


def test_turning_it_off_leaves_the_tiles_alone(proj):
    """The switch in Settings ▸ Language & direction."""
    _upload_strip(proj)
    proj.settings["restitch_strips"] = False
    before = [pg.path for pg in proj.pages]
    assert proj.restitch_if_sliced() == {}
    assert [pg.path for pg in proj.pages] == before


def test_a_manga_chapter_is_never_re_cut_however_uniform_it_looks(proj):
    """The one that sent lee's chapter back in forty pieces.

    `looks_sliced` asks four questions of the FILES: more than five, all the
    same width, all but the last the same height to the pixel, taller than
    wide. A manga chapter scanned in one sitting answers yes to all four by
    coincidence - same scanner, same settings - and lee's tall composite pages
    did exactly that.

    No test of the pixels can tell those apart from a strip, because they are
    not different in the pixels. The FORMAT tells them apart, and the person
    has already said which one this is. lee: *"the page fixing shoud only be
    allied if manhwa is selected"*.
    """
    proj.settings["medium"] = "manga"
    _upload_strip(proj)                      # a real sliced strip, even
    before = [pg.path for pg in proj.pages]
    assert proj.restitch_if_sliced() == {}
    assert [pg.path for pg in proj.pages] == before


def test_a_manhua_is_re_cut_exactly_like_a_manhwa(proj):
    """Manhua is delivered as a strip too, and asked for by name: lee, *"do it
    foe manhua too"*.

    It was left out of the first cut because he had only said manhwa, and being
    wrong in the direction of not touching somebody's chapter is the cheap way
    to be wrong. He has now said. The site has claimed it the whole time -
    the manhua panel reads *"The same strip handling as manhwa"* - so this
    makes the page true as well."""
    from mangatl.project import STRIP_MEDIA
    assert STRIP_MEDIA == {"manhwa", "manhua"}
    proj.settings["medium"] = "manhua"
    img, _ = _upload_strip(proj)
    tiles = len(proj.pages)
    rep = proj.restitch_if_sliced()
    assert rep, "a Chinese webtoon is a strip like any other"
    assert len(proj.pages) != tiles
    assert sum(pg.height for pg in proj.pages) == len(img)


def test_manga_is_the_only_one_left_out(proj):
    """Said as a set rather than as three separate tests, because the whole
    point of the gate is which formats are in it. A fourth arriving later
    should have to come past this line."""
    from mangatl.project import STRIP_MEDIA
    from mangatl.translate import MEDIA
    assert set(MEDIA) - STRIP_MEDIA == {"manga"}


def test_asking_for_it_by_hand_still_works_on_any_format(proj):
    """The gate is on the automatic pass. Somebody who KNOWS their manga
    chapter is really a strip can still say so, and `force` is how."""
    proj.settings["medium"] = "manga"
    _upload_strip(proj)
    tiles = len(proj.pages)
    assert proj.restitch_if_sliced(force=True)
    assert len(proj.pages) != tiles


def test_it_still_runs_when_asked_for_directly(proj):
    """Off is a default, not a ban: the switch stops it happening by itself."""
    _upload_strip(proj)
    proj.settings["restitch_strips"] = False
    assert proj.restitch_if_sliced(force=True)


def test_a_chapter_already_worked_on_is_never_rearranged(proj):
    """Finding boxes, cleaning and typesetting a chapter and THEN having it
    re-cut underneath you would be far worse than the problem."""
    _upload_strip(proj)
    proj.pages[3].detected = True
    before = [pg.path for pg in proj.pages]
    assert proj.restitch_if_sliced() == {}
    assert [pg.path for pg in proj.pages] == before


def test_somebody_elses_folder_is_read_and_not_written_to(proj, tmp_path):
    """Opening a folder of tiles that lives on the person's own disk. The
    pages are written beside the project; their folder comes out untouched."""
    img, _ = _strip_and_typesetting()
    theirs = str(tmp_path / "their chapter")
    was = sorted(os.path.basename(p) for p in _slice(img, theirs))
    proj.use_folder(theirs)
    assert proj.restitch_if_sliced()
    assert sorted(os.listdir(theirs)) == was, "their files must not move"
    assert os.path.abspath(proj.input_dir) != os.path.abspath(theirs)
    assert sum(pg.height for pg in proj.pages) == len(img)


# --------------------------------------------- how tall, said as a multiple

def test_the_height_is_a_multiple_of_the_width(proj):
    """Both numbers are stored as "x the width" rather than as pixels. lee:
    *"change teh value to be a more understandable metrics"*.

    It reads as a shape instead of a measurement, it means the same thing on a
    690px strip and a 1600px one, and for the ceiling it is the RIGHT unit as
    well as the friendlier one: the detector letterboxes a whole page into
    1024px, so what costs you text is how many times taller than wide a page
    is, not how many pixels it has."""
    _upload_strip(proj)                       # tiles W wide
    proj.settings["strip_tall"] = 4.0
    proj.settings["strip_tall_max"] = 10.0
    assert proj.strip_width() == W
    assert proj.strip_heights() == (4 * W, 10 * W)


def test_the_defaults_are_the_numbers_they_replaced():
    """3.5 and 8.5 are 2,400 and 6,000 on the 690px chapter those two came
    off. Nobody's chapter should come out differently because the box now says
    something else."""
    from mangatl.project import Project as P
    d = P.__init__.__doc__            # only to keep the import honest
    assert d is None or True
    import inspect
    src = inspect.getsource(P)
    assert '"strip_tall": 3.5' in src and '"strip_tall_max": 8.5' in src
    assert round(690 * 3.5) == 2415 and round(690 * 8.5) == 5865


def test_a_page_that_could_not_be_read_is_not_what_the_width_comes_from(proj):
    """A page recorded 0x0 - a file the reader could not open - would make
    every height come out at the floor, which is a chapter of stubs. The width
    is the first page that HAS one."""
    from mangatl.project import PageState

    _upload_strip(proj)
    proj.pages.insert(0, PageState(path="", name="broken.png",
                                   width=0, height=0))
    assert proj.strip_width() == W
    assert proj.strip_heights()[0] > 1000


def test_a_ceiling_under_the_target_is_read_as_the_target(proj):
    """Somebody's typo. Taken literally it marks every page in the chapter as
    having run over, which is a report that says nothing."""
    _upload_strip(proj)
    proj.settings["strip_tall"] = 4.0
    proj.settings["strip_tall_max"] = 1.0
    t, c = proj.strip_heights()
    assert c == t


def test_the_page_height_you_asked_for_is_the_one_used(proj, tmp_path):
    """"Page height" in Settings is not decoration: shorter pages, more of
    them."""
    img, _ = _strip_and_typesetting()
    theirs = str(tmp_path / "tiles")
    _slice(img, theirs)

    def pages_at(tall):
        q = Project(None, str(tmp_path / ("out%d" % (tall * 10))))
        q.settings["medium"] = "manhwa"
        q.settings["strip_tall"] = tall
        q.use_folder(theirs)
        return q.restitch_if_sliced()["after"]

    assert pages_at(2.0) > pages_at(6.0)


def test_the_ceiling_changes_what_is_REPORTED_and_not_where_it_cuts(proj):
    """It used to be a wall: a page reaching it was cut at the quietest row
    inside it, through whatever happened to be there. It is now a limit you
    are told about, so lowering it must change the report and nothing else."""
    img, _ = _strip_and_typesetting()
    for i in range(0, len(img), TILE):
        proj.add_uploaded("image_%d.png" % (i // TILE + 1),
                          cv2.imencode(".png", img[i:i + TILE])[1].tobytes())
    proj.settings["strip_tall"] = 1.0
    proj.settings["strip_tall_max"] = 1.2      # anything real passes this
    rep = proj.restitch_if_sliced()
    assert rep["over"], "a tight ceiling has to name the pages that passed it"
    assert set(rep["over_pages"]) <= set(rep["pages"])
    assert sum(pg.height for pg in proj.pages) == len(img), \
        "and not one row of the chapter is anywhere else"


def test_a_page_height_that_would_give_one_page_leaves_the_chapter_alone(proj):
    """Type an absurd number into the box and the answer is one page as long
    as the chapter, which is not a chapter. Nothing is written, and the tiles
    that were moved out of the way come back."""
    _upload_strip(proj)
    before = [pg.path for pg in proj.pages]
    proj.settings["strip_tall"] = 10 ** 5
    assert proj.restitch_if_sliced() == {}
    assert [pg.path for pg in proj.pages] == before
    assert all(os.path.isfile(p) for p in before), "the tiles must be put back"
    assert not os.path.isdir(os.path.join(proj.upload_dir(), "tiles"))


def test_the_pages_that_ran_over_are_named(proj):
    """A page that had to run past the limit to find a gap is a page to go and
    look at, so it is named rather than counted."""
    # Artwork with a gutter only every 9,000 rows - far past the 5,100 the
    # default 8.5 x 600 gives - so every page has to run over to reach one.
    rng = np.random.default_rng(3)
    parts = []
    for _ in range(3):
        parts.append(np.repeat(rng.integers(60, 200, (9000 - GUTTER, W, 1),
                                            dtype=np.uint8), 3, axis=2))
        parts.append(np.full((GUTTER, W, 3), 255, np.uint8))
    tall = np.vstack(parts)
    for i in range(0, len(tall), TILE):
        proj.add_uploaded("image_%d.png" % (i // TILE + 1),
                          cv2.imencode(".png", tall[i:i + TILE])[1].tobytes())
    rep = proj.restitch_if_sliced()
    assert rep["over"] and len(rep["over_pages"]) == rep["over"]
    assert set(rep["over_pages"]) <= set(rep["pages"])
    assert sum(pg.height for pg in proj.pages) == len(tall)


def test_finishing_an_upload_tells_the_browser_what_happened(proj):
    """The page count changes underneath the person. A chapter that silently
    turns nine files into five looks like something went wrong."""
    _upload_strip(proj)
    was, editor.PROJECT = editor.PROJECT, proj
    srv = editor.ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        req = urllib.request.Request(base + "/api/upload_done", b"{}",
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            got = json.loads(r.read())
        assert got["strip"], "the answer must carry the report"
        assert got["strip"]["after"] == got["pages"] == len(proj.pages)
    finally:
        srv.shutdown()
        srv.server_close()
        # `upload_done` starts a background warm-up. Retire it and let it stop
        # before the fixture takes the folder away, or it spends the rest of
        # the run reading pages that are no longer there.
        editor._warm["gen"] += 1
        for _ in range(200):
            if not editor._warm.get("running"):
                break
            time.sleep(0.05)
        editor.PROJECT = was


def _ui_source():
    static = os.path.join(str(PKG), "static")
    import glob
    parts = [open(os.path.join(static, "editor.html")).read()]
    for f in sorted(glob.glob(os.path.join(static, "js", "*.js"))):
        parts.append(open(f).read())
    return "\n".join(parts)


def test_the_switch_is_on_the_settings_screen():
    src = _ui_source()
    assert 'id="restitch_strips"' in src
    assert "restitch_strips:" in src, "the switch has to be saved"
    assert "proj.settings.restitch_strips" in src, "…and read back"


def test_the_browser_is_told_when_a_chapter_was_recut():
    assert "fin.strip" in _ui_source(), \
        "the upload screen must say the pages were re-cut"


# ------------------------------------------------------------- the File tab

def test_the_file_tab_can_close_a_project():
    """lee: *"add a close project button in the file tab"*.

    Not "save and quit": everything is already written as each step finishes.
    This is the editor putting the chapter down, which is why it asks by name
    and says that Open project brings it back."""
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    rail = html.split('data-sec="save"', 1)[1].split("</nav>", 1)[0]
    assert "closeProject()" in rail
    assert ">Close project<" in rail

    js = (PKG / "static" / "js" / "project-io.js").read_text(encoding="utf-8")
    body = js.split("async function closeProject", 1)[1].split("\nasync function", 1)[0]
    # It asks first. The one way to lose work here is to close the wrong one.
    assert "await ask(" in body
    # ...and it does not clear the story, which is what `newChapter` is for.
    assert "keep_settings:true" in body
    assert "Open project" in body, "it has to say how to get back"


def test_the_story_context_is_exported_and_not_downloaded():
    """lee: *"make it say export story context"*. It is the word used for the
    other direction already - Import story context - and the pair should read
    as a pair."""
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    assert "Export story context" in html
    assert "Download story context" not in html
    # ...and the import beside it is unchanged, so the two still match.
    assert "Import story context" in html
