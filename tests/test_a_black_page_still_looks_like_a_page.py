"""Three reports of a page not being centred, and it was centred every time.

lee, three separate times, the last with a screenshot::

    thers still the issiues of teh page not being in teh center of the page

Twice this was answered by changing the centring code -- once so a page whose
picture 404s still centres, once so a page opened while the pane was a
different size is refitted. Both were real. Neither was this.

The page in the screenshot is 005 of his Korean chapter, and it is **68.6% pure
black**. The workspace behind it is `#0b0d11`. So the only part of that page
visible against the pane was a dark red band near the top and a watermark, and
those sat high in the window -- which is exactly what a page pushed to the top
looks like. The rest of it was there, centred, in the same colour as the room
it was in.

Measured, so this is not another guess::

    005.png  720x1364   mean luminance 29.1   median 0
    pixels below 20: 68.6%
    rows brighter than 25: 289 to 950   (of 1364)

Nothing about the scroll position was wrong. What was wrong is that a page had
no edge, so there was no way to tell where it ended.
"""
import re

from where import PKG

CSS = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """The body of the first rule for this exact selector."""
    at = CSS.index(selector + "{")
    return CSS[at:CSS.index("}", at)]


def test_the_page_has_an_edge_that_does_not_depend_on_its_colour():
    """A border drawn by the page itself would be invisible on a black page,
    which is the whole case. The edge has to be drawn by the pane."""
    body = _rule("#stage img")
    assert "box-shadow" in body, \
        "a black page on a near-black pane needs an edge from outside it"


def test_the_edge_is_a_hairline_and_not_a_glow():
    """It sits behind every box and every overlay all day. Anything heavier
    than a hairline competes with the boxes it is supposed to be framing."""
    body = _rule("#stage img")
    ring = re.search(r"0 0 0 (\d+)px", body)
    assert ring, "an even ring, not an offset border"
    assert int(ring.group(1)) == 1


def test_the_edge_is_lighter_than_the_workspace_behind_it():
    """`--line` is the app's own divider colour, #2b313d, against a pane of
    #0b0d11. Reusing it rather than inventing a shade means the page's edge
    matches every other edge in the app and moves with the theme."""
    body = _rule("#stage img")
    assert "var(--line)" in body
    assert "--line:#2b313d" in CSS.replace(" ", "")
    assert "#0b0d11" in _rule("#canvasWrap")


def test_the_reference_pane_gets_the_same_edge():
    """Side by side, one page framed and one not would read as the unframed
    one being broken."""
    assert "box-shadow" in _rule("#refImg")


def test_the_page_is_still_glued_to_its_overlays():
    """The boxes are positioned against the image's own box. An edge drawn
    with `border` would move the coordinate origin and put every box a pixel
    or two off its writing; a shadow paints outside the layout and cannot.

    The stage says the same thing about its pan margin, and for the same
    reason -- see the comment on `#stage`.
    """
    body = _rule("#stage img")
    assert "border:" not in body.replace("border-radius", "")
    assert "padding" not in body
