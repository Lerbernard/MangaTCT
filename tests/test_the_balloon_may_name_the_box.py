"""Finding a balloon round a block is allowed to say the block is a bubble.

lee::

    when you lable a bubble i want you ta do a very quick text that try to find
    teh bubble if it fins teh bubble then lable it a bubble box if it cant fins
    it labble it a outsude test, te test need to be fast, is that posible?

Yes to the test, yes to fast, and **no to the second half** — which is the
interesting part, so the measurement is written out here rather than in a note
somebody has to go looking for.

THE TEST ALREADY EXISTS. `detect/balloon.py` walks outward from a block's ink
until it meets the drawn outline round it, takes the enclosed paper, and
refuses anything that is not flat pale paper with no drawn edges in it.
`attach_balloons` has run at the end of every `detect_comictext` since it was
written. Two things it did not do: the upright pass was offered only blocks
already called bubble or narration, and nothing was ever renamed on it.

FAST, as a number. Measured over 55 pages of two chapters: offering the search
to the free-floating blocks as well costs **0.05s a page against 17.9s
detecting them — 0.3%**. It is the same page, the same labelled runs of paper,
and a handful more blocks asking which one they are in.

WHAT PROMOTING BUYS: 1 box in 21 over those 55 pages. Small — `_classify_kind`
does not often call something free when it is sitting in a findable balloon —
but it is free, it is positive evidence, and the same rule was already running
on the inverted pass for black balloons.

WHY DEMOTING IS NOT HERE. Measured on the same 55 pages, "no balloon found"
fires on **71 of 132 dialogue boxes — 54%**. Split by chapter it is 73% and 5%,
which is the first sign it is measuring the artwork and not the label. Cropping
all twelve of a sample settles it: they are **caption panels** — a pale
rectangle filling the panel with narration set in it. This pass refuses those
deliberately. Such a rectangle touches the page edge, or fails `min_gain`
because the text box already fills it, or is not a drawn balloon at all.

So `bubble_mask is None` means *"not a drawn balloon"*, and lee's rule reads it
as *"loose on the artwork"*. Those are different sentences, and a rule built on
the confusion would have relabelled half the dialogue in a chapter as outside
text. Shown the numbers, lee picked promote only.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect.balloon import BalloonConfig, attach_balloons
from mangatl.models import TextRegion


def _page(h=420, w=420, fill=250):
    return np.full((h, w), fill, np.uint8)


def _balloon(page, cx, cy, rx, ry):
    cv2.ellipse(page, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (cx, cy), (rx, ry), 0, 0, 360, 0, 3)
    return page


def _ink(page, x, y, w=70, h=26):
    m = np.zeros(page.shape, np.uint8)
    for i in range(3):
        cv2.rectangle(page, (x, y + i * 10), (x + w, y + i * 10 + 5), 0, -1)
        cv2.rectangle(m, (x, y + i * 10), (x + w, y + i * 10 + 5), 255, -1)
    return m


def _region(mask, kind):
    ys, xs = np.nonzero(mask)
    bb = (int(xs.min()), int(ys.min()),
          int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1)
    return TextRegion(id=0, bbox=bb, text_mask=mask, bubble_mask=None,
                      bubble_bbox=bb, kind=kind)


def _in_a_balloon(kind):
    page = _page()
    _balloon(page, 210, 210, 150, 110)
    return page, _region(_ink(page, 170, 195), kind)


def _on_bare_paper(kind):
    """No outline anywhere — nothing encloses the block."""
    page = _page()
    return page, _region(_ink(page, 170, 195), kind)


# --------------------------------------------------------------- promoting

def test_outside_text_in_a_balloon_is_called_a_bubble():
    page, r = _in_a_balloon("freefloat")
    assert attach_balloons(page, [r]) == 1
    assert r.kind == "bubble"
    assert r.bubble_mask is not None


def test_outside_text_with_no_balloon_stays_outside_text():
    """The control. Without it the test above passes on a function that renames
    everything it is handed."""
    page, r = _on_bare_paper("freefloat")
    assert attach_balloons(page, [r]) == 0
    assert r.kind == "freefloat"
    assert r.bubble_mask is None


def test_a_caption_is_not_renamed_by_finding_its_box():
    """Promotion is for free text only. A caption in a balloon is a caption —
    somebody said so, and this pass has nothing to say about it."""
    page, r = _in_a_balloon("narration")
    assert attach_balloons(page, [r]) == 1
    assert r.bubble_mask is not None
    assert r.kind == "narration"


def test_a_sound_effect_is_left_alone_entirely():
    """It has no balloon and the ink's own footprint is the right place for
    it — and a sound effect that happens to be drawn across a balloon must not
    be turned into dialogue."""
    page, r = _in_a_balloon("sfx")
    attach_balloons(page, [r])
    assert r.kind == "sfx"
    assert r.bubble_mask is None


# --------------------------------------------------- and NOT demoting

def test_nothing_is_ever_demoted():
    """The half of lee's sentence that was measured and refused. A dialogue box
    the pass cannot find a balloon for keeps its name.

    Stated against the code as well as the behaviour, because the behaviour
    here is an absence: there is no arrangement of a fixture that proves a
    rename that never happens, only one that proves this one case."""
    import inspect

    from mangatl.detect import balloon as B
    src = inspect.getsource(B._attach)
    renames = [ln.strip() for ln in src.splitlines()
               if ".kind =" in ln and ".kind ==" not in ln]
    assert renames == ['r.kind = "bubble"'], renames
    page, r = _on_bare_paper("bubble")
    assert attach_balloons(page, [r]) == 0
    assert r.kind == "bubble", "a bubble with no balloon found is still a bubble"


def test_a_caption_panel_is_exactly_what_the_pass_refuses():
    """Why demoting would have been wrong, as a fixture rather than a claim.

    A caption panel is a pale rectangle filling the panel with the narration in
    it. The balloon search refuses it — `min_gain` alone does, because the text
    box already fills the rectangle — and it is dialogue all the same. This is
    the shape that 54% of the demotes turned out to be.
    """
    page = _page(200, 400, 255)
    cv2.rectangle(page, (0, 0), (399, 199), 0, 2)     # the panel rule
    r = _region(_ink(page, 40, 80, w=320, h=26), "narration")
    attach_balloons(page, [r])
    assert r.kind == "narration", "the panel must not turn into outside text"


# --------------------------------------------------------------- and fast

def test_the_free_blocks_are_searched_on_the_upright_pass():
    """The one line the speed claim rests on: they are eligible, so the answer
    comes off the labelling the pass already did rather than a second search.
    """
    import inspect

    from mangatl.detect import balloon as B
    src = inspect.getsource(B.attach_balloons)
    up = src.split("_attach(gray, regions")[1].split("\n    dark")[0]
    assert "freefloat" in up, up
    assert "promote=True" in up, up


def test_one_labelling_of_the_page_serves_both_kinds_of_block():
    """`_free_labels` is the expensive part and it runs once per pass whatever
    is eligible. If a second call ever appears the 0.3% stops being true."""
    import inspect

    from mangatl.detect import balloon as B
    assert inspect.getsource(B._attach).count("_free_labels(") == 1
