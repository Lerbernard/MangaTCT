"""The doorstep finishes a stroke; it does not follow a line home.

lee sent a crop of page 008's sound effect box - あはは drawn over a character's
hair - with the hair strand coming back **chopped into segments** where the
kana crossed it: *"thry to have the clneer fix his"*.

The mask that goes to the cleaner is clean. Measured on that box:

    base mask        1081 px   of it artwork      0
    after doorstep   2647 px   of it artwork   1347
                     ------                    ----
    doorstep added   1566 px   of it artwork   1347   (86%)

Every pixel of hair in it was added by ONE rule. `_complete_strokes` is the
doorstep: eight pixels past the box, where a glyph drawn a little too big is
finished instead of left as a stub. It adopts ink out there that is CONNECTED
to ink the box caught - and hair the kana touches is one component with them,
so it followed the strand out of the box and the fill took it.

A stroke the box cut ENDS in the doorstep. That is what eight pixels is for. A
mark with most of itself still to come out there is not a tail, it is a line
that happens to touch the writing - and on a sound effect, drawn over the
picture rather than in a bubble, that is the ordinary case.

As a SHARE, not a yes-or-no. "Does any of it lie past the doorstep" reads
better and is useless: one anti-aliased pixel at the tip of the 1,804px bar in
`test_a_glyph_poking_past_a_turned_edge_still_comes_off` lies past it, and that
single pixel threw the whole stroke away and put the stub back.

Chapter-wide, all 23 pages, the offline path: 875,308 -> 866,776 px of page
painted, for 23px more writing left unpainted and 32px more still readable out
of 801,840.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion

H, W = 300, 400
BOX = (150, 110, 90, 80)          # x, y, w, h


def _region(img, box=BOX, kind="sfx"):
    x, y, w, h = box
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = np.zeros((H, W), np.uint8)
    ink[y:y + h, x:x + w] = (g[y:y + h, x:x + w] <= I.INK).astype(np.uint8) * 255
    r = TextRegion(id=0, bbox=box, text_mask=ink, bubble_mask=None,
                   bubble_bbox=box, kind=kind)
    r.src_text, r.order = "a", 0
    return r


def _page(img, r):
    p = Page(image=img, source_path="t.png")
    p.regions = [r]
    return p


def _ink(img, where):
    return int(((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) <= 128) & where).sum())


def _blank():
    return np.full((H, W, 3), 250, np.uint8)


# ------------------------------------------------------ the line that survives

def _hair():
    """A long strand crossing the page, with a kana-ish blob sitting on it.

    The blob is the writing and the strand is the artwork, and they touch -
    which is the whole difficulty. Nothing here is separable by threshold,
    position, or thickness; only by where the strand goes.
    """
    img = _blank()
    cv2.line(img, (205, 0), (185, H - 1), (15, 15, 15), 5)        # the strand
    cv2.circle(img, (185, 150), 16, (10, 10, 10), -1)             # the writing
    return img


def test_a_strand_that_crosses_the_page_is_left_alone_outside_the_box():
    """The hair, in one page. It touches the writing, so it is one component
    with it, and the doorstep used to follow it."""
    img = _hair()
    x, y, w, h = BOX
    ring = np.zeros((H, W), bool)
    ring[max(0, y - I.GLYPH_REACH):y + h + I.GLYPH_REACH,
         max(0, x - I.GLYPH_REACH):x + w + I.GLYPH_REACH] = True
    ring[y:y + h, x:x + w] = False
    was = _ink(img, ring)
    assert was > 60, "the fixture must have strand standing in the doorstep"
    out = I.inpaint_page(_page(img.copy(), _region(img)), neural=None)
    # 112px of strand stand in the doorstep here. Six of them survived before;
    # eighty-two survive now. What is still lost is the ordinary couple of
    # pixels the halo sweep reaches past the box, which is a different rule and
    # not what this is about - hence a threshold with both answers a long way
    # from it rather than one drawn tight round today's number.
    assert _ink(out, ring) > 0.6 * was, (
        "the strand outside the box was erased along with the writing")


def test_the_strand_is_still_one_component_with_the_writing():
    """If they did not touch, this would all be beside the point - the guard
    being tested is the one that has to tell apart marks nothing else can."""
    img = _hair()
    full = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) <= I.INK).astype(np.uint8)
    _, lab = cv2.connectedComponents(full, 8)
    assert lab[150, 185] == lab[5, 205] != 0


# --------------------------------------------------- the stroke still finished

def test_a_stroke_drawn_past_its_box_is_still_finished():
    """The other half, and the one that must not regress: writing drawn a
    little past its box comes off whole, or "the text must go" and "never
    outside the box" cannot both be true."""
    img = _blank()
    # a stub of a letter: inside the box, poking a few pixels out of the top
    cv2.rectangle(img, (180, 104), (192, 150), (10, 10, 10), -1)
    x, y, w, h = BOX
    ring = np.zeros((H, W), bool)
    ring[max(0, y - I.GLYPH_REACH):y + h + I.GLYPH_REACH,
         max(0, x - I.GLYPH_REACH):x + w + I.GLYPH_REACH] = True
    ring[y:y + h, x:x + w] = False
    was = _ink(img, ring)
    assert was > 20, "the fixture must have the stub standing in the doorstep"
    out = I.inpaint_page(_page(img.copy(), _region(img)), neural=None)
    assert _ink(out, ring) < 0.2 * was, "the stub was left on the page"


def test_one_stray_pixel_past_the_doorstep_does_not_condemn_a_stroke():
    """The share is the point. A yes-or-no on "any of it lies past the
    doorstep" is thrown by a single anti-aliased pixel, which is how the first
    version of this rule broke the turned-box test."""
    img = _blank()
    cv2.rectangle(img, (180, 104), (192, 150), (10, 10, 10), -1)
    x, y, w, h = BOX
    # ...and one pixel of it, far out, exactly as an anti-aliased tip would be
    img[max(0, y - I.GLYPH_REACH) - 1, 186] = (10, 10, 10)
    img[max(0, y - I.GLYPH_REACH):y - 1, 186] = (10, 10, 10)
    ring = np.zeros((H, W), bool)
    ring[max(0, y - I.GLYPH_REACH):y + h + I.GLYPH_REACH,
         max(0, x - I.GLYPH_REACH):x + w + I.GLYPH_REACH] = True
    ring[y:y + h, x:x + w] = False
    was = _ink(img, ring)
    out = I.inpaint_page(_page(img.copy(), _region(img)), neural=None)
    assert _ink(out, ring) < 0.2 * was, "one pixel outside condemned the stroke"


def test_the_share_is_the_one_the_rest_of_the_file_uses():
    """A second number for the same claim is a second number to keep in step.
    `OUTSIDE_SHARE` already means "most of this mark lies elsewhere" in
    `glyphs_only` and in `_only_what_the_box_contains`."""
    assert I.DOORSTEP_SHARE == I.OUTSIDE_SHARE
