"""Two things the fitter was not allowed to know.

lee, twice: *"try to make teh typesetting more constsant and better fit the
boxes"*, and, with a crop of COUGH printed straight through "...THIS MUCH IS
ONLY NATURAL!": *"make the typesetter use a the image that i see to typeset"*.

## The dashes the author already wrote

Breaking a word where the text already has a dash or a row of dots was a LAST
RESORT - reached only when nothing fitted at the minimum size at all. That is
one of the two cases it is for, and not the common one.

The other is a single long word in a tall narrow balloon, where the width of
that one word is the whole ceiling. "Double...?!" is 77px at 11pt against a
widest usable chord of 84, so eleven - the floor - was the largest size that
fitted, in a balloon 102 wide and 214 tall with nothing else in it: a block
covering 8% of its own balloon. Broken where the author put the dots it sets
at 18 on two lines. Nothing was wrong with the arithmetic; the layout was
never considered.

Tried always now, and kept when it typesets MEANINGFULLY bigger - a sixth,
`AUTHOR_BREAK_GAIN`. Bigger and not better-scoring: the two fits are scored
against different `_feasible_top`s - `small` is normalised by what that
arrangement can reach - so their scores are not on one scale, while their point
sizes are. And a sixth rather than any gain at all: in a balloon with room to
spare the same break goes 39 to 40, a word cut in half to tidy the arithmetic
by a point.

Measured over lee's 23 pages, 173 blocks:

    mean point size            16.91 -> 17.34
    block against its balloon   0.42 ->  0.44
    blocks under 30% of it        46 ->    39
    blocks under 20% of it        23 ->    18

## And the sound effect standing where the words want to go

Every block is fitted against its own area and told nothing about any other,
so a page where two of them want the same paper prints one through the other.
Between two speech balloons that cannot happen - a balloon is drawn round its
own words. A sound effect has no balloon, is drawn over the artwork wherever
the original mark was, and is not clipped to anything. It cannot move; the
dialogue can, so the dialogue is the one told.

Over the same 23 pages that takes the one dialogue-through-effect collision
off the chapter and costs 0.01pt of mean size. What is left is effects printed
through each other, which is the artist's own arrangement and not ours to
move.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import typeset as T
from mangatl.models import Page, TextRegion

H, W = 400, 400


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


# --------------------------------------------- 1. the dots the author wrote

TALL = dict(cx=200, cy=200, rx=51, ry=107)      # 102 x 214, like lee's page 017


def test_a_word_too_wide_for_a_tall_balloon_breaks_where_the_author_did():
    m = _oval(**TALL)
    r = _region(0, m, (170, 150, 60, 110), "Double...?!")
    cfg = _cfg()
    lay = T.fit_region(r, cfg, m)
    whole = T._best("Double...?!", m > 0, cfg)
    assert len(lay.lines) == 2, lay.lines
    assert "".join(lay.lines) == "Double...?!", lay.lines
    assert lay.font_size > whole.font_size + 2, (lay.font_size,
                                                 whole.font_size, lay.lines)


def test_and_the_fixture_really_is_the_shape_that_causes_it():
    """One word, one line, and a balloon far taller than it is wide - or the
    test above is measuring nothing."""
    m = _oval(**TALL)
    ys, xs = np.nonzero(m)
    assert (ys.max() - ys.min()) > 1.8 * (xs.max() - xs.min())
    one = T._best("Double...?!", m > 0, _cfg())
    assert one is not None and len(one.lines) == 1, one.lines


def test_a_word_with_nothing_the_author_wrote_to_break_at_is_left_by_THIS_rule():
    """No dash, no dots: nothing the AUTHOR wrote to break at, so this rule
    declines and hands the word on.

    It used to assert `lay.lines == ["Unbelievable"]` - that a word is never
    split at all - and that was wrong. It was written before lee sent the
    published English chapter 22, which has `TRANS-/FIGURA-/TION` and `BEING
    TRANS-/FIGURED` set by a professional. A word IS split; just not by this
    rule, and only about twice in every hundred lines. See
    `test_a_hyphen_of_our_own.py`.

    Narrowed to the claim this rule actually makes, rather than deleted: the
    author-break path is the thing under test and it still has to decline.
    """
    m = _oval(**TALL)
    assert T._fit_on_author_breaks("Unbelievable", m > 0, _cfg()) is None


def test_a_break_that_buys_nothing_is_not_taken():
    """A balloon with room to spare sets the line whole. There the break gains
    one point and costs a word cut in half, which is a break for its own sake -
    see `AUTHOR_BREAK_GAIN`."""
    m = _oval(cx=200, cy=200, rx=150, ry=110)
    r = _region(0, m, (90, 160, 220, 80), "Double...?!")
    lay = T.fit_region(r, _cfg(), m)
    assert lay.lines == ["Double...?!"], lay.lines


# ------------------------------------------ 2. and the effect already there

def _page_with_effect(effect_box):
    m = _oval(cx=200, cy=200, rx=140, ry=100)
    talk = _region(0, m, (90, 170, 220, 60), "This much is only natural!")
    sfx = _region(1, None, effect_box, "COUGH", kind="sfx")
    sfx.text_mask = np.zeros((H, W), np.uint8)
    x, y, w, h = effect_box
    sfx.text_mask[y:y + h, x:x + w] = 255
    page = Page(image=np.full((H, W, 3), 255, np.uint8))
    page.regions = [talk, sfx]
    page.clean_plate = page.image.copy()
    return page, talk, sfx


def test_the_dialogue_keeps_off_a_sound_effect_standing_in_the_balloon():
    page, talk, sfx = _page_with_effect((240, 150, 90, 70))
    T.typeset_page(page, _cfg(), redo=True)
    assert talk.share_mask is not None
    inside = talk.share_mask > 0
    x, y, w, h = sfx.bbox
    assert not inside[y:y + h, x:x + w].any(), \
        "the effect's box is still being offered to the dialogue"


def test_and_the_effect_itself_is_not_moved_out_of_anyone_s_way():
    """It is drawn where the mark it replaces was. That is the whole of its
    placement and there is nothing to negotiate."""
    page, talk, sfx = _page_with_effect((240, 150, 90, 70))
    T.typeset_page(page, _cfg(), redo=True)
    assert sfx.layout and sfx.layout.lines == ["COUGH"], sfx.layout
    x, y, w, h = sfx.bbox
    cx = sum(a for a, _ in sfx.layout.line_origins) / len(sfx.layout.line_origins)
    assert abs(cx - (x + w / 2.0)) < 8, (cx, x + w / 2.0)


def test_an_effect_across_the_middle_of_a_balloon_is_lived_with():
    """Dialogue at half the size to dodge a collision is a worse page than
    dialogue with a collision. `SFX_ROOM` is the share of its room a block may
    lose to this, and an effect over most of the balloon is past it."""
    page, talk, sfx = _page_with_effect((70, 120, 260, 160))
    before = int((talk.place_mask() > 0).sum())
    T.typeset_page(page, _cfg(), redo=True)
    kept = before if talk.share_mask is None else int((talk.share_mask > 0).sum())
    assert kept == before, "the balloon was cut down to a shape nothing fits"


def test_a_page_with_no_effects_on_it_is_untouched():
    m = _oval(cx=200, cy=200, rx=140, ry=100)
    talk = _region(0, m, (90, 170, 220, 60), "This much is only natural!")
    page = Page(image=np.full((H, W, 3), 255, np.uint8))
    page.regions = [talk]
    page.clean_plate = page.image.copy()
    T.typeset_page(page, _cfg(), redo=True)
    assert talk.share_mask is None, "a lone balloon gained a share it never had"
