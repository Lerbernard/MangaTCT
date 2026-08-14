"""The flat fill is the one route that can be marked, so it is.

lee, about page 024 — a see-through balloon with a beam of light across it,
cleaned into a grey slab with the words still perfectly legible on top of it:
*"can this be fixed?"*.

It could, and not where it looked. The second pass was leaving a fifth of that
box's writing standing, so the obvious suspect was the second pass; the fault
was two steps earlier. `_flat_from` samples the paper immediately AROUND the
words, because that is the paper its answer will be used to paint. On a box
whose writing covers half of it, that sample is a corner — and a corner of a
gradient is flat. So the verdict "this balloon is one colour" was reached from
a sample that could not see the balloon, and a slab of one grey went down.

That is the worst outcome available, because it also blinds the step that would
have caught it. The second pass reads the page the FIRST one produced — it
must, or it would undo work already done — and what it now reads is a uniform
field: it finds 4% of the box where the original shows 60%.

Several ways of second-guessing the verdict before painting were measured and
all of them failed: a flatness question asked over a wider sample either misses
the beam or reaches the drawn outline and takes plain white bubbles down with
it. What has no such ambiguity is the fill's own result. The flat fill is
justified by KNOWING the colour, so it can be checked — paint it and look, and
if the words are still standing where the paint went, the colour was not known.

Measured over lee's chapter: 121 boxes take the flat fill, their median leaves
1% of the writing where it painted and their ninetieth leaves 2%. Page 024
leaves 20%, the next worst is 5.5%, and exactly one box out of 145 changes
route — page 024, from 20% of its writing left to 12%, and with a model
configured to the model, where a balloon with artwork behind it belonged.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def _bubble(bg=252, w=340, h=200):
    """A plain white balloon with writing in it — the case that must not move,
    whatever else this change does."""
    from mangatl.models import Page, TextRegion
    x, y, bw, bh = 40, 40, 260, 120
    img = np.full((h, w, 3), 245, np.uint8)
    inner = np.zeros((h, w), np.uint8)
    cv2.rectangle(inner, (x, y), (x + bw, y + bh), 255, -1)
    img[y:y + bh, x:x + bw] = bg
    cv2.rectangle(img, (x - 3, y - 3), (x + bw + 3, y + bh + 3), (0, 0, 0), 3)
    cv2.putText(img, "AB", (x + 20, y + 62), cv2.FONT_HERSHEY_SIMPLEX,
                1.1, (20, 20, 20), 5)
    cv2.putText(img, "CDE", (x + 110, y + 62), cv2.FONT_HERSHEY_SIMPLEX,
                1.1, (20, 20, 20), 5)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tm = np.zeros((h, w), np.uint8)
    sub = gray[y:y + bh, x:x + bw]
    tm[y:y + bh, x:x + bw] = (sub < 190).astype(np.uint8) * 255
    r = TextRegion(id=1, bbox=(x, y, bw, bh), kind="bubble", order=0,
                   src_text="a", dst_text="AB CDE",
                   bubble_mask=inner, bubble_bbox=(x, y, bw, bh))
    r.text_mask = tm
    pg = Page(image=img.copy())
    pg.regions = [r]
    return pg


def _model(sub, sm):
    """A cleaner that answers. What it answers does not matter here."""
    return np.full_like(sub, 127)


def _routes(pg):
    return {k: v for k, v in pg.clean_stats.items() if v}


def _swap(monkeypatch, verdict):
    """Make the check answer `verdict`, whatever it is looking at."""
    from mangatl import inpaint as I
    monkeypatch.setattr(I, "_slab_worked", lambda *a, **k: verdict)


# ---------------------------------------------------------------- the check

def _painted(orig, ink, colour):
    got = orig.copy()
    got[ink > 0] = colour
    return got


def _part_of(mask, share):
    """The left `share` of the word — by where the word actually is, not by
    where the patch happens to end."""
    from mangatl import inpaint as I
    cols = np.where(mask.any(0))[0]
    part = I._dilated(mask).copy()
    part[:, cols.min() + int(round((cols.max() + 1 - cols.min()) * share)):] = 0
    return part


def _written_on(bg=250, ink_level=20, h=90, w=260):
    """A patch of paper with a word on it, and the mask of that word."""
    img = np.full((h, w, 3), bg, np.uint8)
    cv2.putText(img, "ABCDE", (14, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (ink_level,) * 3, 5)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = ((gray < 128) if ink_level < bg else (gray > 128)).astype(np.uint8)
    return img, mask


def test_a_fill_that_took_the_writing_off_is_kept():
    from mangatl import inpaint as I
    img, mask = _written_on()
    assert I._slab_worked(img, _painted(img, I._dilated(mask), 250), mask)


def test_a_fill_the_writing_survived_is_not():
    """The whole point. The paint went down and the words are still there."""
    from mangatl import inpaint as I
    img, mask = _written_on()
    # painted somewhere else entirely — the words are untouched
    elsewhere = np.zeros(mask.shape, np.uint8)
    elsewhere[:12, :12] = 1
    assert not I._slab_worked(img, _painted(img, elsewhere, 250), mask)
    # ...and the degenerate case of painting nothing at all
    assert not I._slab_worked(img, img.copy(), mask)


def test_half_a_word_left_standing_is_still_a_failure():
    """It does not have to be all of it. On page 024 the fill covered the box
    and the writing stayed legible on top of the slab."""
    from mangatl import inpaint as I
    img, mask = _written_on()
    assert not I._slab_worked(img, _painted(img, _part_of(mask, 0.5), 250),
                              mask)


def test_nothing_recorded_and_nothing_there_are_both_left_alone():
    """"I cannot see enough to tell" is not a verdict — it is `_flat_from`'s own
    rule, and this is a fix for the case where it was broken."""
    from mangatl import inpaint as I
    img, mask = _written_on()
    assert I._slab_worked(img, img.copy(), np.zeros(mask.shape, np.uint8))
    blank = np.full_like(img, 250)
    assert I._slab_worked(blank, blank.copy(), mask)


def test_the_line_is_where_the_chapter_separates():
    """SLAB_LEFT is a measured number, not a feeling: the flat fill's median box
    leaves 1% of its writing, page 024 leaves 20%, and the next worst leaves
    5.5%. Anything through this line is a fill that did not do its job."""
    from mangatl import inpaint as I
    assert 0.055 < I.SLAB_LEFT < 0.199, \
        "the line no longer sits inside the gap it was measured from"
    img, mask = _written_on()
    kept, thrown = [], []
    for share in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        part = _part_of(mask, share)           # paint `share` of the word out
        (kept if I._slab_worked(img, _painted(img, part, 250), mask)
         else thrown).append(share)
    assert thrown and kept, f"nothing separated: kept {kept} thrown {thrown}"
    assert max(thrown) < min(kept), \
        f"the verdict is not monotone in what was left: {thrown} {kept}"


# ------------------------------------------------------------- the wiring

def test_a_fill_that_failed_is_not_used():
    """With the check saying no, the box goes where a box the local fill cannot
    do belongs — the model when there is one, and the rebuilding paths when
    there is not. Not to the slab either way."""
    from mangatl import inpaint as I
    with pytest.MonkeyPatch.context() as mp:
        _swap(mp, False)
        pg = _bubble()
        I.inpaint_page(pg, neural=_model, neural_all=False)
        assert not pg.clean_stats.get("flat fill"), _routes(pg)
        assert pg.clean_stats.get("neural") == 1, _routes(pg)

        pg2 = _bubble()
        I.inpaint_page(pg2, neural=None)
        assert not pg2.clean_stats.get("flat fill"), _routes(pg2)


def test_a_fill_that_worked_is():
    """...and the guarantee on the other side. A plain white bubble is the one
    thing the local fill is unbeatable at, and 120 of the 121 boxes that took
    it in lee's chapter still do."""
    from mangatl import inpaint as I
    for neural in (_model, None):
        pg = _bubble()
        I.inpaint_page(pg, neural=neural, neural_all=False)
        assert pg.clean_stats.get("flat fill") == 1, _routes(pg)


def test_the_check_is_asked_before_the_paint_goes_down():
    """It is asked about the fill this box would GET — its own colour, its own
    mask, on its own pixels — and not about some page-wide average."""
    from mangatl import inpaint as I
    seen = []
    real = I._slab_worked

    def spy(orig, painted, ink):
        seen.append((orig.shape, painted.shape, int(np.count_nonzero(ink))))
        return real(orig, painted, ink)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(I, "_slab_worked", spy)
        pg = _bubble()
        I.inpaint_page(pg, neural=None)
    assert len(seen) == 1, f"asked {len(seen)} times for one box"
    orig, painted, ink = seen[0]
    assert orig == painted, "the check compared two different windows"
    assert ink > 0, "the check was handed an empty mask"


def test_a_page_cleaned_twice_the_same_way_comes_out_the_same():
    """The check reads pixels, so it must not read pixels something else has
    already changed: the same page cleaned twice has to give the same plate."""
    from mangatl import inpaint as I
    a = I.inpaint_page(_bubble(), neural=None)
    b = I.inpaint_page(_bubble(), neural=None)
    assert np.array_equal(a, b)


def test_the_box_is_still_cleaned_when_the_fill_is_thrown_away():
    """Rejecting the fill must not mean leaving the writing. Whatever route it
    lands on has to take the words off, which is the entire object."""
    from mangatl import inpaint as I
    pg = _bubble()
    x, y, w, h = pg.regions[0].bbox
    before = pg.image[y:y + h, x:x + w].copy()

    def edge(z):
        return float(np.abs(cv2.Laplacian(
            cv2.cvtColor(z, cv2.COLOR_BGR2GRAY), cv2.CV_64F)).mean())

    with pytest.MonkeyPatch.context() as mp:
        _swap(mp, False)
        out = I.inpaint_page(pg, neural=None)
    assert edge(out[y:y + h, x:x + w]) < 0.25 * edge(before), \
        "the fill was thrown away and nothing cleaned the box instead"
