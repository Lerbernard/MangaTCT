"""Find text got faster without answering differently.

lee: *"right now its taking a very ong tike to do pages is theer anything i ca
do to speed this up?"*

Profiled with the real model on a real 720x5702 page, `cProfile`, cumulative:

    34.1s total
    21.4s   morphologyEx            (3 calls, from _blob_split)
    10.9s   cv2.dnn.Net.forward
     1.0s   attach_balloons

Not the neural net. **Two thirds of the page went into one OpenCV call**, and
it was the same call every time. Two things were wrong with how it was asked.

**It was asked about the whole page.** `_split_clusters` gets a full-page mask
holding one block. On a webtoon that is 720 by up to 7,000 -- four megapixels
of empty around a few hundred pixels of ink -- and the close was run over all
of it. Cropping to the ink first: 21.4s -> 5.3s.

**And the kernel was enormous.** It is as wide as the gap being bridged, 3.5
median marks on these formats, and on a page with a big brush sound effect the
median mark is 148 pixels, so the kernel came out **518 across**. An ellipse is
not separable. But the close is only ever asked which pieces of ink are
CONNECTED -- the masks it returns are cut from the original ink, so the closing
never contributes a pixel to an answer -- and a connectivity question can be
answered at a smaller scale. 5.3s -> under a tenth of a second.

    34.1s -> 13.0s on that page, and morphology is out of the top fourteen.
    Measured on three pages, old against new, every box identical:

        037.png  720x5702   33.7s -> 10.6s   3.2x   same boxes
        021.png  720x3479   26.1s ->  9.7s   2.7x   same boxes
        005.png  720x1364    8.9s ->  9.0s   1.0x   same boxes

The short page does not move because it was already all neural net, which is
the honest shape of this: what is left is the model, and the model costs what
it costs.

These tests do the same comparison without the 95MB download -- the old passes
are written out here and run against the new ones on masks shaped like the real
cases.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT


# --------------------------------------------- the passes as they used to be

def slow_blob_split(ink, gap):
    """Full kernel, full scale."""
    k = max(3, int(gap))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
    nb, blab, _s, _c = cv2.connectedComponentsWithStats(closed, 8)
    if nb <= 2:
        return [ink]
    total = int(ink.sum())
    out = []
    for li in range(1, nb):
        m = ((blab == li) & (ink > 0))
        if int(m.sum()) >= max(20, 0.03 * total):
            out.append(m.astype(np.uint8))
    return out if len(out) >= 2 else [ink]


def _page(h=3000, w=720):
    return np.zeros((h, w), np.uint8)


def _blob(mask, x, y, w, h):
    mask[y:y + h, x:x + w] = 1
    return mask


def _grouping(parts, ink):
    """Which pieces of the original ink ended up together.

    The comparison is the GROUPING and not the pixels, because the grouping is
    the whole of what `_blob_split` decides -- the masks it hands back are cut
    from `ink`, so nothing downstream can see the closing itself.

    They do differ by a pixel here and there, and in the new pass's favour: a
    big ellipse erodes back off the outermost row of ink, so the old close
    sometimes left that row unlabelled and dropped it from its own group. The
    coarse pass unions the closing with the ink it is labelling, so it cannot.
    A one-pixel border is invisible under the 8-pixel PAD every box gets, and
    on three real pages the boxes came out identical -- but it is a real
    difference and comparing pixels would be comparing the wrong thing.
    """
    n, lab = cv2.connectedComponents((ink > 0).astype(np.uint8), 8)
    out = []
    for p in parts:
        got = set(np.unique(lab[p > 0]).tolist()) - {0}
        if got:
            out.append(tuple(sorted(got)))
    return sorted(out)


def _same(a, b, ink):
    return _grouping(a, ink) == _grouping(b, ink)


# ------------------------------------------------------------- the crop

def test_cropping_to_the_ink_does_not_change_the_split():
    """The same block, alone on a tall page and again on a short one. Where
    the ink sits on the page cannot change how it is divided."""
    counts, places = [], []
    for h in (600, 3000, 7000):
        m = _page(h)
        # Far enough apart to really be split -- 1.8 median marks is 162
        # pixels on these 90-wide blobs and the gap is 370. A fixture whose
        # pieces merge takes the `[ink]` shortcut and never reaches the crop
        # at all, which is what the first version of this did: it asserted 2
        # against a 110-pixel gap and got 1.
        _blob(m, 60, 200, 90, 60)
        _blob(m, 520, 200, 90, 60)
        got = CT._split_clusters(m, 1.8, 1.8)
        counts.append(len(got))
        for p in got:
            assert p.shape == m.shape, "still a full-page mask"
        # ...and back where they came from, whatever the page's height.
        places.append(sorted((int(np.nonzero(p)[1].min()),
                              int(np.nonzero(p)[0].min())) for p in got))
    assert counts == [2, 2, 2], \
        "the page's height changed the split: %r" % (counts,)
    assert places[0] == places[1] == places[2] == [(60, 200), (520, 200)], \
        places


def test_the_crop_leaves_room_for_the_kernel():
    """The close reaches half a kernel outside the ink. A crop tighter than
    that would clip what the close is doing at the edges and could break a
    join that the full page would have made."""
    import inspect

    src = inspect.getsource(CT._split_clusters)
    assert "pad = max(hgap, vgap) + 2" in src
    assert "ink[y0:y1, x0:x1]" in src


def test_a_block_that_fills_the_page_still_works():
    """The crop is a no-op here, and the no-op has to be harmless."""
    m = _page(400)
    _blob(m, 0, 0, 720, 400)
    got = CT._split_clusters(m, 1.8, 1.8)
    assert got and all(p.shape == m.shape for p in got)


# -------------------------------------------------- the kernel, at scale

@pytest.mark.parametrize("gap", [40, 120, 300, 518])
def test_a_big_kernel_answered_small_groups_the_same_pieces(gap):
    """The question is which pieces are connected, and shrinking the gap and
    the kernel together does not change the answer to that. Checked across the
    range the real pages produce -- 518 is the kernel measured on lee's
    page 037."""
    m = np.zeros((1400, 720), np.uint8)
    _blob(m, 60, 100, 140, 120)
    _blob(m, 60 + 140 + gap // 3, 100, 140, 120)     # well within the gap
    _blob(m, 80, 100 + 120 + gap * 3, 140, 120)      # well beyond it
    assert _same(CT._blob_split(m, gap), slow_blob_split(m, gap), m), gap


def test_a_small_kernel_is_not_shrunk_at_all():
    """Under the threshold nothing changes: same code path, same numbers, no
    resampling to reason about."""
    import inspect

    src = inspect.getsource(CT._blob_split)
    assert "if f > 1:" in src
    m = np.zeros((600, 400), np.uint8)
    _blob(m, 40, 40, 60, 60)
    _blob(m, 250, 40, 60, 60)
    assert _same(CT._blob_split(m, 20), slow_blob_split(m, 20), m)


def test_the_coarse_pass_never_loses_a_piece_of_ink():
    """A thin mark can fall between two sample rows on the way down and come
    back with no label, which would drop it from every group. The closing is
    unioned with the ink it is labelling, so that cannot happen."""
    m = np.zeros((1200, 720), np.uint8)
    _blob(m, 100, 100, 200, 150)
    m[400, 100:300] = 1                    # one pixel tall
    parts = CT._blob_split(m, 300)
    covered = np.zeros_like(m)
    for p in parts:
        covered |= (p > 0)
    assert int((m & ~covered).sum()) == 0, "every mark is in some group"


def test_the_coarse_threshold_is_written_down():
    assert CT.COARSE >= 16, "too coarse to trust the connectivity"
    assert CT.COARSE <= 96, "too fine to be worth the trouble"


# --------------------------------------------------------- and it is faster

def test_the_big_kernel_case_is_actually_quicker():
    """The point of all of it. Not a benchmark -- a floor, loose enough not to
    fail on a busy machine and tight enough that losing the optimisation
    entirely would trip it."""
    import time

    m = np.zeros((1400, 720), np.uint8)
    _blob(m, 60, 100, 200, 200)
    _blob(m, 400, 900, 200, 200)

    t = time.time(); CT._blob_split(m, 518); fast = time.time() - t
    t = time.time(); slow_blob_split(m, 518); slow = time.time() - t
    assert fast < slow / 3.0, "fast %.2fs vs slow %.2fs" % (fast, slow)
