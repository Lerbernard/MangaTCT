"""The box round a line of dialogue covers the end of the line.

lee, with a screenshot of one balloon and the trailing em dash sitting outside
the red rectangle: *"can you make it so taht the whole text is detected"*.

The box is 009.png#1 of his own chapter, round::

    마탑의 주인이시자
    불멸의 대마법사이자—

Measured on the page rather than guessed at: the dash and the 자 in front of it
are ONE ink component of 226 pixels, and the box holds 208 of them. **92%
inside, nine pixels out.** So this is not a new kind of failure. It is exactly
what `_grow_to_the_stroke` was written for -- and the one sort of box it was not
allowed near, because the caller ran it `if r.kind == "sfx"`.

WHAT WAS TRIED FIRST AND THROWN AWAY. Before reaching for that function I wrote
a rule of its own: look for letter-sized marks near the box and take them in.
Asking simply "is there ink outside the box" says 64% of dialogue boxes and a
median spill of a quarter of the box -- and it is measuring the BALLOON, whose
outline passes through the halo round every box in the chapter. Constraining the
mark to the box's own glyph size, and then to marks the window can see all of,
and then to marks along the run rather than above or below it, walked that down
to 29% -- three guards, each one bolted on after looking at crops, all of them
approximating the single rule the sfx grow already states outright: **a mark the
box already holds most of is the box's own.** The extra rule was deleted.

THE ONE NUMBER THIS ADDS. `text_grow = 0.70`, against the effects' 0.40, and no
extra `pad`. A sound effect is a drawn shape whose box came off something only
ever looking for writing; a letter is a letter. Measured:

    lee's own chapter   2 of 39 dialogue boxes move: his, by the nine
                        pixels of the dash, and one other by one pixel.
    chapter 8          29 of 114 move -- it has far more hand-drawn
                        writing the block head calls dialogue -- median
                        1.09x, max 2.14x. The sixteen biggest were
                        cropped and looked at one at a time and none
                        leaves the balloon it started in.

Manga stays off, the same as `sfx_grow`: the clipping was measured on a Korean
webtoon and nothing here re-measured manga.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT

MANHWA = CT.TUNING["manhwa"]


def _page(h=600, w=600, fill=255):
    return np.full((h, w), fill, np.uint8)


def _mark(g, x, y, w, h, v=0):
    g[y:y + h, x:x + w] = v
    return g


# ------------------------------------------------------------- the numbers

def test_the_share_is_the_measured_one():
    assert MANHWA["text_grow"] == 0.70
    assert CT.TUNING["manhua"]["text_grow"] == 0.70


def test_it_is_a_higher_bar_than_the_effects_get():
    """The whole reason there are two numbers instead of one. If these ever
    become equal, one of the two measurements has been thrown away."""
    assert MANHWA["text_grow"] > MANHWA["sfx_grow"]


def test_manga_does_not_grow_its_dialogue_either():
    assert CT.TUNING["manga"]["text_grow"] is None


def test_the_default_is_off():
    """A caller that does not ask for it does not get it -- the same shape as
    `sfx_grow`, so an untuned format cannot silently pick it up."""
    import inspect
    sig = inspect.signature(CT.detect_comictext)
    assert sig.parameters["text_grow"].default is None


# ---------------------------------------------- what the share buys, in ink

def test_a_dash_running_out_of_the_box_is_taken_in():
    """lee's case, in miniature: a box holding all but the last few pixels of
    a mark follows it to the end."""
    g = _page()
    _mark(g, 100, 200, 220, 12)                  # the line, ending at 320
    box = (100, 190, 200, 32)                    # the box stops at 300
    bb, mask = CT._grow_to_the_stroke(g, box, 0.70, 0.12)
    assert mask is not None
    assert bb[0] + bb[2] >= 320, bb


def test_a_mark_the_box_barely_touches_is_not_followed():
    """The balloon wall clipping a corner, in miniature. At 0.70 a box holding
    a fifth of something has no claim on the rest of it."""
    g = _page()
    _mark(g, 100, 200, 500, 12)                  # a long rule, 100..600
    box = (100, 190, 100, 32)                    # holding a fifth of it
    bb, mask = CT._grow_to_the_stroke(g, box, 0.70, 0.12)
    assert mask is None and bb == box


def test_the_effects_bar_would_have_followed_that_one():
    """...which is the point of the two numbers, said as a test: the same mark
    and the same box, and the looser sound-effect share does follow it."""
    g = _page()
    _mark(g, 100, 200, 500, 12)
    box = (100, 190, 220, 32)                    # holding 44% of the rule
    assert CT._grow_to_the_stroke(g, box, 0.40, 0.12)[1] is not None
    assert CT._grow_to_the_stroke(g, box, 0.70, 0.12)[1] is None


def test_a_grow_the_size_of_a_panel_is_refused():
    g = _page()
    _mark(g, 20, 20, 560, 560)                   # most of the page
    box = (20, 20, 500, 500)
    bb, mask = CT._grow_to_the_stroke(g, box, 0.70, 0.12)
    assert mask is None and bb == box


# ------------------------------------------------------- and in the caller

def _regions(kinds, bbox):
    from mangatl.models import TextRegion
    out = []
    for i, k in enumerate(kinds):
        out.append(TextRegion(id=i, bbox=bbox, text_mask=None,
                              bubble_mask=None, bubble_bbox=bbox, kind=k))
    return out


def test_the_caller_grows_every_kind_and_not_only_the_effects():
    """The bug, stated once: the loop used to read `if r.kind != "sfx":
    continue`, so a dialogue box could not be widened however far its own ink
    ran outside it."""
    import inspect
    src = inspect.getsource(CT.detect_comictext)
    at = src.index("_grow_to_the_stroke(gray, r.bbox")
    loop = src[src.rindex("for r in regions", 0, at):at]
    assert 'if r.kind != "sfx"' not in loop
    assert "sfx_grow if" in loop and "else text_grow" in loop


def test_dialogue_gets_no_extra_breathing_room():
    """A sound-effect box is grown with `pad=PAD` on top. A dialogue box is
    not: it already carries PAD from where it was cut out of the mask, and a
    second helping of it is how every box on the page 'moves'.

    (This is not a detail. Measured with the pad on, 100% of dialogue boxes
    change and the median grow is 1.28x, which reads as a detector that has
    started guessing; with it off, 25% change and the median is 1.09x.)
    """
    import inspect
    src = inspect.getsource(CT.detect_comictext)
    at = src.index("_grow_to_the_stroke(gray, r.bbox")
    call = src[at:src.index(")", src.index("pad=", at))]
    assert 'pad=PAD if r.kind == "sfx" else 0' in call, call


def test_the_mask_grows_with_the_box():
    """A box that covers the dash over a mask that does not leaves the dash on
    the page after cleaning -- which is the half of this lee would actually
    see."""
    import inspect
    src = inspect.getsource(CT.detect_comictext)
    at = src.index("_grow_to_the_stroke(gray, r.bbox")
    assert "np.maximum(np.asarray(r.text_mask), mask)" in src[at:at + 900]
