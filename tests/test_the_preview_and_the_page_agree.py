# -*- coding: utf-8 -*-
"""What you are shown while you edit, and what gets drawn.

lee, after the measured style was made live: *"the changes ate only appkied
when i select a box"*.

They were. Selecting a box asks `/api/page/N/layout_preview`, and the answer
becomes `r.style`, which the browser's preview prefers over everything else it
has. `layout_preview` worked the colours out **for itself**:

    fg = render.hex_rgb(o.get("fg")) or fg
    edge = render.hex_rgb(o.get("edge")) or edge

Three sources rank in this app - a hand edit, then the measurement, then the
automatic choice - and those two lines know about the first and the third. So
the page drew one thing and the panel drew another, and which one you saw
depended on whether the box was selected.

`render.style_of` is the ranking and `colours_for`/`stroke_for` apply it.
`layout_preview` calls them now, with the unsaved override handed in as an
argument - it cannot be put on the region, because the region is shared and
the server answers on threads, which is what the lock a few lines above it is
for.

**The divergence is the bug, not the wrong answer.** Two copies of one rule
agree until the day one of them is changed, and then they disagree silently -
on the screen somebody is looking at while they decide whether the change was
right. So the test is that there is ONE copy.
"""
import inspect

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import editor, render as R                     # noqa: E402
from mangatl.models import TextRegion                       # noqa: E402


W = (255, 255, 255, 255)
B = (0, 0, 0, 255)


def _r(kind="sfx_big", measured=None, override=None):
    return TextRegion(id=1, bbox=[0, 0, 10, 10], kind=kind,
                      layout_measured=measured, layout_override=override)


# ------------------------------------------------------------ one copy

def test_the_preview_asks_the_same_three_functions_the_page_does():
    src = inspect.getsource(editor.layout_preview)
    for want in ("colours_for(", "stroke_for(", "_hollow_colours("):
        assert want in src, f"the preview does not call {want}"


def _code(fn) -> str:
    """The function's CODE, with its prose taken out.

    Every one of these guards has now been fooled once by the comment that
    explains the thing it forbids - `test_shapes` by a line that wrapped,
    this one by a docstring quoting the very line it was written to ban. A
    test that reads source has to read the SOURCE.
    """
    src = inspect.getsource(fn)
    out = []
    for line in src.splitlines():
        bare = line.split("#", 1)[0]
        out.append(bare)
    body = "\n".join(out)
    # ...and the docstring, which is not a comment and survives the above.
    while '"""' in body:
        a = body.index('"""')
        b = body.find('"""', a + 3)
        if b < 0:
            break
        body = body[:a] + body[b + 3:]
    return "".join(body.split())


def test_the_preview_does_not_rank_the_sources_itself():
    """The line that caused it. Anything of this shape is a second copy of
    `style_of`, however carefully it is written."""
    flat = _code(editor.layout_preview)
    for bad in ('hex_rgb(o.get("fg"))or', "hex_rgb(o.get('fg'))or",
                'hex_rgb(o.get("edge"))or', "hex_rgb(o.get('edge'))or"):
        assert bad not in flat, bad


def test_the_width_is_ranked_once_too():
    """`stroke` was worked out twice in one function: `stroke_for` above, and
    then `int(override["stroke"]) if ... else stroke` in the reply, which is
    the hand edit and nothing else. The second one won."""
    flat = _code(editor.layout_preview)
    assert 'int(override["stroke"])' not in flat, \
        "the reply still ranks the width for itself"


# --------------------------------------------- and they give one answer

def _both(region, override, fg=W, edge=B, automatic=11):
    """The colours the two paths arrive at, from the same starting point.

    The exporter reads the override off the REGION; the preview is handed one
    that is not on it yet. Same answer either way, or selecting a box changes
    the page.
    """
    page_fg, page_edge = R.colours_for(
        _like(region, override), fg, edge)
    page_stroke = R.stroke_for(_like(region, override), automatic)
    pre_fg, pre_edge = R.colours_for(region, fg, edge, override)
    pre_stroke = R.stroke_for(region, automatic, override)
    return (page_fg, page_edge, page_stroke), (pre_fg, pre_edge, pre_stroke)


def _like(region, override):
    return TextRegion(id=region.id, bbox=region.bbox, kind=region.kind,
                      layout_measured=region.layout_measured,
                      layout_override=override)


def test_a_measured_sound_reads_the_same_both_ways():
    r = _r(measured={"fg": "#020202", "edge": "#f6f6f6", "stroke": 4})
    page, pre = _both(r, {})
    assert page == pre, (page, pre)
    assert R._css(pre[0]) == "#020202" and pre[2] == 4


def test_a_hand_edit_that_is_not_saved_yet_reads_the_same_both_ways():
    r = _r(measured={"fg": "#020202", "edge": "#f6f6f6", "stroke": 4})
    page, pre = _both(r, {"fg": "#a15e1b", "stroke": 9})
    assert page == pre, (page, pre)
    assert R._css(pre[0]) == "#a15e1b" and pre[2] == 9


def test_a_bubble_takes_the_automatic_pair_both_ways():
    """The case lee was looking at. The preview knew nothing about the scale
    in `measured_for`, so a bubble showed its measured grey while selected and
    the automatic white when not."""
    r = _r(kind="bubble", measured={"fg": "#646464"})
    page, pre = _both(r, {})
    assert page == pre, (page, pre)
    assert R._css(pre[0]) == "#ffffff"


def test_an_emptied_fill_reads_the_same_both_ways():
    r = _r(kind="bubble")
    page, pre = _both(r, {"fg": R.NO_FILL})
    assert page == pre, (page, pre)
    assert pre[0][3] == 0


def test_the_css_the_browser_gets_says_no_fill():
    """`_css_rgba` is the one thing the preview does that the exporter does
    not - the browser reads these into `color` and `-webkit-text-stroke`, and
    an alpha of zero is the only way to say "no fill" in a colour."""
    fg, edge = R.colours_for(_r(kind="bubble"), W, B, {"fg": R.NO_FILL})
    assert editor._css_rgba(fg) == "rgba(0,0,0,0)"
    assert editor._css_rgba(edge) == "rgba(0,0,0,1)"


def test_a_hollow_letterform_reads_the_same_both_ways():
    r = _r(measured={"hollow": True, "rim": 2, "fg": "#020202"})
    page, pre = _both(r, {})
    pf, pe = R._hollow_colours(_like(r, {}), *page[:2])
    qf, qe = R._hollow_colours(r, *pre[:2], {})
    assert (pf, pe) == (qf, qe)
    assert pf[3] == 0, "a hollow letter has nothing inside it"
