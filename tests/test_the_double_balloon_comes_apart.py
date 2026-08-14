"""Two lobes, two boxes.

lee: *"here are some issue to try to fix , the missclasification of the text
and the doubke bubble"*, with screenshots of ONE red rectangle drawn across
both lobes of a two-lobed balloon.

One box there is one translation and one typesetting for two separate things
said, and the typesetter then has to fit both into whichever lobe the rectangle
happens to sit over.

**The first idea was wrong and is worth keeping written down.** Two balloons
ought to mean two white regions, so a box straddling two of them could be found
without any threshold at all. On lee's page 010 the two lobes share ONE white
interior -- the wall between them is not drawn -- and eroding the white by
eleven pixels does not separate them. There is nothing to count. The only thing
that distinguishes the lobes is the gap in the WRITING, which is what
`split_height` already measures, and it was walking past it:

    page 010 box 1   median mark 37   biggest empty row band 76px
                     split_height 3.50 wanted 130

**So it is one number, and the number came from the distribution.** Every block
the block head produced on all 67 pages of chapter 1 -- 142 of them -- scored as
the biggest empty row band over the median mark. Everything above 0.83 was
looked at by eye:

    13 are two lobes of one balloon under one box     1.17 .. 4.67
     2 are real text that must stay whole             0.83, 1.00
     4 are boxes on artwork with no writing at all    1.40 .. 4.20
    123 others are all at 0.40 or below

The bar is set by the chapter title card at 1.00: three lines with a whole
line-height of leading, airy rather than doubled. Nothing real sits between
1.00 and 1.17, so 1.10 is the middle of an empty gap -- 13 of 13 lobes split,
0 of 125 whole blocks broken.

Checked end to end on the pages themselves, with the model: 010, 012, 013, 015,
022, 028, 046 and 054 all come back as two boxes, one per lobe. 047 and 056
were already right -- their lobes are far enough apart SIDEWAYS that
`_blob_split` had them -- and 046's box changed kind from `freefloat` to
`bubble` on the way, which is the other half of what lee reported.

These tests do not need the 95MB model. They exercise `_split_clusters`, which
is where the decision is made, on masks built to the measured shapes.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT

MANHWA = CT.TUNING["manhwa"]


def _lines(mark, rows, x=60, y=60, page=(1400, 720), lead=None, gap_before=()):
    """A block of writing: rows of square marks, `mark` across.

    Hangul sets as separate syllable blocks, so square marks of the median size
    are a fair stand-in -- the median mark is exactly what the threshold is a
    multiple of. `gap_before` names the rows that start a new lobe.
    """
    lead = mark // 4 if lead is None else lead
    m = np.zeros(page, np.uint8)
    cy = y
    for i, ncols in enumerate(rows):
        if i in gap_before:
            cy += gap_before[i] if isinstance(gap_before, dict) else 0
        for c in range(ncols):
            cx = x + c * (mark + mark // 4)
            m[cy:cy + mark, cx:cx + mark] = 1
        cy += mark + lead
    return m


def _pieces(m, tune=None):
    t = tune or MANHWA
    return CT._split_clusters(m, gap_mult=t["split_gap"],
                              height_mult=t["split_height"])


# ------------------------------------------------------------ the number

def test_the_threshold_sits_in_the_measured_gap():
    """Above the title card at 1.00, below the closest double balloon at 1.17.
    Any value in there splits all thirteen and breaks none of the hundred and
    twenty-five; outside it, one of those two stops being true."""
    assert 1.00 < MANHWA["split_height"] <= 1.17, MANHWA["split_height"]


def test_the_sideways_gap_was_not_touched():
    """3.50 is there for the sound effects that came back in two boxes SIDE BY
    SIDE, measured on chapter 227, which this change did not re-measure."""
    assert MANHWA["split_gap"] == 3.5
    assert CT.TUNING["manhua"]["split_gap"] == 3.5


def test_manga_keeps_its_own_numbers():
    """The distribution was measured on a Korean webtoon. Manga was measured
    separately and is not downstream of any of this."""
    assert CT.TUNING["manga"]["split_gap"] == 1.8
    assert CT.TUNING["manga"]["split_height"] == 1.8


def test_manhua_follows_manhwa():
    assert CT.TUNING["manhua"]["split_height"] == MANHWA["split_height"]


# ------------------------------------------------------- the two lobes

def test_the_double_balloon_comes_apart():
    """Page 010 box 1 to the measured numbers: marks of 37, two lines a lobe,
    and 76 pixels of nothing between the lobes."""
    m = _lines(37, [3, 3], y=60)
    ys = np.nonzero(m)[0]
    low = _lines(37, [3, 3], y=int(ys.max()) + 1 + 76)
    both = ((m | low) > 0).astype(np.uint8)
    assert len(_pieces(both)) == 2, "the lobes stayed in one box"


def test_the_title_card_stays_whole():
    """The block that sets the bar: three lines with a whole line-height of
    leading, which is 1.00 median marks and must not read as two lobes."""
    m = _lines(26, [4, 4, 4], lead=26)
    assert len(_pieces(m)) == 1, "the title card was cut up"


def test_ordinary_leading_stays_whole():
    """The other 123 blocks. A quarter of a mark between lines is what the
    chapter actually sets at, and it is nowhere near the threshold."""
    m = _lines(37, [4, 4, 4])
    assert len(_pieces(m)) == 1


@pytest.mark.parametrize("band,split", [(36, False), (37, False),
                                        (42, True), (76, True)])
def test_the_cut_lands_where_the_number_says(band, split):
    """1.10 median marks of 37 is 41 pixels, so 37 is under the bar and 42 is
    over it. A test that only used the 76-pixel real case would pass on any
    threshold from 0.3 to 2.0.
    """
    top = _lines(37, [3, 3], y=60)
    ys = np.nonzero(top)[0]
    bot = _lines(37, [3, 3], y=int(ys.max()) + 1 + band)
    both = ((top | bot) > 0).astype(np.uint8)
    got = len(_pieces(both))
    assert (got == 2) is split, "%d pixels -> %d pieces" % (band, got)


def test_the_lobes_are_not_merged_back_as_columns():
    """`_merge_columns` undoes a split when two pieces are side by side with
    matching tops and bottoms. Lobes are stacked, so it must not fire -- and if
    it ever grew a vertical case it would silently undo all of this."""
    top = _lines(37, [3, 3], y=60)
    ys = np.nonzero(top)[0]
    bot = _lines(37, [3, 3], y=int(ys.max()) + 1 + 76)
    both = ((top | bot) > 0).astype(np.uint8)
    parts = _pieces(both)
    assert len(parts) == 2
    boxes = []
    for p in parts:
        py, px = np.nonzero(p)
        boxes.append((int(px.min()), int(py.min()),
                      int(px.max()), int(py.max())))
    boxes.sort(key=lambda b: b[1])
    assert boxes[0][3] < boxes[1][1], "the pieces overlap vertically: %r" % (
        boxes,)


def test_every_mark_survives_the_split():
    """A split that loses writing is worse than no split: the lost line never
    gets read, translated or typeset, and nothing on screen says so."""
    top = _lines(37, [3, 3], y=60)
    ys = np.nonzero(top)[0]
    bot = _lines(37, [3, 3], y=int(ys.max()) + 1 + 76)
    both = ((top | bot) > 0).astype(np.uint8)
    covered = np.zeros_like(both)
    for p in _pieces(both):
        covered |= (p > 0)
    assert int((both & ~covered).sum()) == 0


def test_a_lobe_of_one_line_still_splits():
    """Half the real cases have a single line in one lobe, and a block with one
    gap in it has no second gap to compare against -- which is why the rule is
    the mark size and not 'biggest gap over next biggest'. That alternative was
    tried: 59 of the 125 whole blocks score infinity under it."""
    top = _lines(37, [3], y=60)
    ys = np.nonzero(top)[0]
    bot = _lines(37, [4, 4], y=int(ys.max()) + 1 + 90)
    both = ((top | bot) > 0).astype(np.uint8)
    assert len(_pieces(both)) == 2


def test_the_sideways_gap_still_uses_the_sideways_number():
    """The two numbers are now three apart, so swapping them is a real risk --
    and every vertical fixture above survives the swap, because 3.50 sideways
    separates a 76-pixel vertical gap in `_blob_split` anyway, just by a
    different road. Only a SIDEWAYS gap tells them apart.

    The numbers are not 3.50 and 1.10 times the mark, though, because
    `_blob_split` closes with an ellipse and a close bridges a gap only if the
    shapes either side are thick next to the kernel. On 37-pixel marks the
    3.50 kernel gives out at about 75 pixels rather than 130, and the 1.10 one
    at about 35. Measured, not derived: 60 pixels is one body of writing under
    the real numbers and two under the swapped ones.
    """
    near = np.zeros((1400, 720), np.uint8)
    near |= _lines(37, [2], x=60, y=200)
    near |= _lines(37, [2], x=60 + 2 * 46 + 60, y=200)
    assert len(_pieces(near)) == 1, "60 pixels apart is one body of writing"

    far = np.zeros((1400, 720), np.uint8)
    far |= _lines(37, [2], x=60, y=200)
    far |= _lines(37, [2], x=60 + 2 * 46 + 200, y=200)
    assert len(_pieces(far)) == 2, "200 pixels apart is two"


def test_a_tall_piece_beside_a_short_one_is_not_merged_back():
    """`_merge_columns` exists to undo a split of ONE bubble into columns, and
    it wants all of: close together, same height, tops and bottoms in line,
    truly side by side. Loosen any one of them and it starts merging things
    that were correctly separated -- here a tall piece and a short one that
    overlap vertically but are 200 pixels apart and nothing like the same
    height."""
    m = np.zeros((1400, 720), np.uint8)
    m |= _lines(37, [2, 2, 2, 2, 2], x=60, y=60)
    m |= _lines(37, [2], x=60 + 2 * 46 + 200, y=120)
    assert len(_pieces(m)) == 2


def test_three_lobes_come_apart_into_three():
    """Nothing in the rule caps it at two, and the XY-cut recurses."""
    m = np.zeros((1400, 720), np.uint8)
    y = 60
    for _ in range(3):
        part = _lines(37, [3, 3], y=y)
        m |= part
        y = int(np.nonzero(part)[0].max()) + 1 + 90
    assert len(_pieces(m)) == 3
