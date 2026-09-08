"""The half of lee's sentence I argued away, and the chapter that settled it.

lee asked for two things at once, twice: *"try to make teh typesetting more
constsant and better fit the boxes"*. I did the second half, measured it, and
talked myself out of the first:

    levelling those means pulling one down - more even, less well filled, the
    opposite of the other half of the same sentence. Not done on a hunch.

Then he sent the raw Japanese chapter 22 and, beside it, the published English
release of the SAME chapter: *"here are some exampek to use to how proper
tysetting is doen"*. Measured with one instrument - our detector over both sets
of pages, our arithmetic over both:

                            professional      ours
        block / balloon          0.382        0.549
        biggest / smallest       1.33x        1.91x
        middle half             +/-15%       +/-21%

We were already filling balloons half again as full as the people who do this
for a living. The thing we were not doing was keeping the letters one size. A
professional TAKES 0.38 to get 1.33x - so the two halves were never opposites,
and the trade between them is the answer to both. I had it backwards because I
had only ever measured our chapter against its own previous version, which can
tell you a change moved a number and cannot tell you which way it should point.

`_level_caps`: the page's median dialogue size is what the page is set at, and
anything fitted more than `LEVEL_BAND` above it is fitted again with that
ceiling. Downward only, effects and hand-set sizes left out. `LEVEL_BAND` was
swept, not picked - the table is in `typeset.py`.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import typeset as T
from mangatl.models import Page, TextRegion

H, W = 700, 700


def _oval(cx, cy, rx, ry):
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
    return m


def _region(rid, mask, box, text, kind="bubble"):
    r = TextRegion(id=rid, bbox=box, text_mask=None, bubble_mask=mask,
                   bubble_bbox=box, kind=kind)
    r.order, r.dst_text = rid, text
    return r


def _cfg():
    return T.TypesetConfig(font_path=T.default_font_path(),
                           min_font=11, max_font=40)


def _page(regions):
    page = Page(image=np.full((H, W, 3), 255, np.uint8))
    page.regions = regions
    page.clean_plate = page.image.copy()
    return page


def _sizes(page):
    return {r.id: (r.layout.font_size if r.layout else None)
            for r in page.regions}


# ---------------------------------------------------------- a roomy page

def _four_talkers():
    """Three full lines of talk and one very short one, all in balloons of the
    same size.

    The short one is what the fitter blows up: two words in a balloon sized for
    a sentence fit at any size on offer, so it takes the largest, and the page
    carries a block half again as tall as its neighbours for a reason nobody
    reading it could name.
    """
    out = []
    for k, (cx, cy, text) in enumerate([
            (170, 170, "I started work today at ten o'clock, so it is "
                       "already half past five."),
            (520, 170, "An ordinary person transfigured like that "
                       "eventually stops living."),
            (170, 520, "But what happens to a jujutsu sorcerer who is "
                       "caught by the same thing?"),
            (520, 520, "Oh?")]):
        m = _oval(cx, cy, 130, 105)
        out.append(_region(k, m, (cx - 120, cy - 95, 240, 190), text))
    return out


def test_the_odd_one_out_is_brought_back_to_the_page():
    """The rule is stated against the page's OWN median - every dialogue block
    on it, the loud one included. A median taken of "the others" is a different
    number for every block and is not a page size at all."""
    page = _page(_four_talkers())
    T.typeset_page(page, _cfg(), redo=True)
    got = _sizes(page)
    cap = round(T.LEVEL_BAND * float(np.median(list(got.values()))))
    assert got[3] is not None
    assert got[3] <= cap, got
    assert got[3] < max(got[k] for k in (0, 1, 2)) * 2, \
        ("the fixture is not producing an outlier to level", got)


def test_and_the_page_it_is_brought_back_to_is_not_moved_by_it():
    """Only the overshooting block is refitted. The other three are the page's
    own size and must come out of a levelled page exactly as they went in."""
    a = _page(_four_talkers())
    T.typeset_page(a, _cfg(), redo=True)
    was = dict(T.__dict__)
    T.LEVEL_MIN = 10 ** 9                     # levelling off
    try:
        b = _page(_four_talkers())
        T.typeset_page(b, _cfg(), redo=True)
    finally:
        T.LEVEL_MIN = was["LEVEL_MIN"]
    for k in (0, 1, 2):
        assert _sizes(a)[k] == _sizes(b)[k], (k, _sizes(a), _sizes(b))
    assert _sizes(a)[3] < _sizes(b)[3], (_sizes(a), _sizes(b))


def test_the_spread_across_the_page_actually_narrows():
    """The point of the whole thing, stated as the number it is aimed at."""
    def spread(page):
        s = [r.layout.font_size for r in page.regions if r.layout]
        return max(s) / float(min(s))
    a = _page(_four_talkers())
    T.typeset_page(a, _cfg(), redo=True)
    T.LEVEL_MIN, keep = 10 ** 9, T.LEVEL_MIN
    try:
        b = _page(_four_talkers())
        T.typeset_page(b, _cfg(), redo=True)
    finally:
        T.LEVEL_MIN = keep
    assert spread(a) < spread(b), (spread(a), spread(b))


# ------------------------------------------------- what is NOT levelled

def test_a_sound_effect_keeps_the_size_the_artwork_gave_it():
    """It is drawn along the mark it replaces. Its size is a fact about the
    page, not a choice about dialogue - and the professional's 1.33x is
    measured with effects excluded too."""
    rs = _four_talkers()
    m = np.zeros((H, W), np.uint8)
    m[300:400, 250:600] = 255
    sfx = _region(9, None, (250, 300, 350, 100), "DOOM", kind="sfx")
    sfx.text_mask = m
    page = _page(rs + [sfx])
    T.typeset_page(page, _cfg(), redo=True)
    lay = page.regions[-1].layout
    assert lay is not None and lay.lines == ["DOOM"], lay
    talk = [r.layout.font_size for r in page.regions[:4] if r.layout]
    assert lay.font_size > T.LEVEL_BAND * float(np.median(talk)), \
        "the effect was levelled with the dialogue"


def test_a_size_somebody_typed_is_never_given_a_ceiling():
    """A hand edit is not an accident to be tidied away.

    Asked of the rule itself rather than of a finished page: a locked override
    goes down a different road in `typeset_page` (`layout_from_override`) which
    would pass this whatever `_level_caps` did, so a page-level assertion here
    would be green with the guard deleted.
    """
    rs = _four_talkers()
    rs[3].layout_override = {"locked": True, "font_size": 38,
                             "lines": ["Oh?"], "leading": 1.1}
    page = _page(rs)
    cfg = _cfg()
    shares = T.share_masks(page.regions, cfg)
    probe, caps = T._level_caps(page, cfg, shares)
    assert 3 not in caps, caps
    assert 3 not in probe, "a locked block was fitted by the levelling pass"
    assert set(probe) == {0, 1, 2}, sorted(probe)


def test_a_page_with_barely_anything_on_it_has_no_size_to_level_to():
    """Two balloons of which one is a shout have a median that means nothing.
    `LEVEL_MIN`."""
    rs = _four_talkers()[:2]
    rs[1].dst_text = "Oh?"
    page = _page(rs)
    T.typeset_page(page, _cfg(), redo=True)
    assert len(rs) < T.LEVEL_MIN
    T.LEVEL_MIN, keep = 10 ** 9, T.LEVEL_MIN
    try:
        b = _page([_region(r.id, r.bubble_mask, r.bbox, r.dst_text)
                   for r in _four_talkers()[:2]])
        b.regions[1].dst_text = "Oh?"
        T.typeset_page(b, _cfg(), redo=True)
    finally:
        T.LEVEL_MIN = keep
    assert _sizes(page) == _sizes(b), (_sizes(page), _sizes(b))


# ------------------------------------------------------- and it stays legible

def test_nothing_is_levelled_into_an_empty_bubble():
    """The ceiling can never be pushed under the floor: a block refitted into
    nothing is a balloon with no words in it, which is worse than a balloon
    whose words are a size too big."""
    page = _page(_four_talkers())
    T.LEVEL_BAND, keep = 0.01, T.LEVEL_BAND     # absurd on purpose
    try:
        T.typeset_page(page, _cfg(), redo=True)
    finally:
        T.LEVEL_BAND = keep
    for r in page.regions:
        assert r.layout and r.layout.lines, (r.id, r.layout)
        assert r.layout.font_size >= _cfg().min_font, (r.id, r.layout.font_size)


def test_the_band_is_the_one_that_was_measured():
    """1.10 put the middle half exactly on the professional's +/-15%. Written
    down because the sweep is in a comment and a comment cannot fail."""
    assert T.LEVEL_BAND == 1.10, T.LEVEL_BAND
    assert T.LEVEL_MIN == 4, T.LEVEL_MIN
