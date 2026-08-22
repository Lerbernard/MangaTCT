"""The editor typesets in the same colours the export does.

lee kept sending back the same picture: white Japanese on a black panel,
replaced by English that came out black with a hairline white halo - unreadable
on the artwork it was standing on. The exported page was always right, which is
what made it confusing.

The exporter looks at the page every time it draws, so it can decide the
colours afresh. The browser cannot: it has no page, only the record the server
sends it, and it typesets from `layout.fg` / `layout.edge` / `layout.stroke`.
Nothing was writing those. `render.assign_colours` existed but was called from
nowhere, so every layout kept the dataclass defaults - black on white, stroke 1
- no matter what it was drawn over.

So these pin the whole chain: laying a page out records the colours, the
recorded colours agree with what the exporter works out live, they survive the
trip through a saved record, and a normal white balloon is still black on
white - a fix that turned every bubble white would be worse than the bug.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import Page, TextRegion
from mangatl.typeset import TypesetConfig, default_font_path, typeset_page, on_art
from mangatl import render
from mangatl.project import region_record
from where import PKG

H, W = 520, 560
BOX = (150, 130, 250, 240)
TEXT = "A GHOST... THERE'S A GHOST LADY!!"


def _cfg():
    c = TypesetConfig(font_path=default_font_path())
    c.min_font, c.max_font = 10, 34
    return c


def _japanese(shape=(H, W)):
    """A column of kana-sized blobs where the English will go."""
    x, y, w, h = BOX
    ink = np.zeros(shape, np.uint8)
    for cy in range(y + 16, y + h - 10, 34):
        cv2.rectangle(ink, (x + w // 2 - 10, cy - 12),
                      (x + w // 2 + 10, cy + 12), 255, -1)
    return ink


def _on_dark_art():
    """lee's own case: no balloon, white type straight onto a black panel."""
    plate = np.full((H, W, 3), 40, np.uint8)
    ink = _japanese()
    orig = plate.copy()
    orig[ink > 0] = (255, 255, 255)
    r = TextRegion(id=1, bbox=BOX, kind="bubble", text_mask=ink)
    r.dst_text, r.order = TEXT, 0
    page = Page(image=orig, source_path="dark")
    page.regions = [r]
    page.clean_plate = plate
    return page


def _white_balloon():
    """An ordinary balloon, which happens to sit on the same black panel."""
    x, y, w, h = BOX
    cx, cy = x + w // 2, y + h // 2
    ball = np.zeros((H, W), np.uint8)
    cv2.ellipse(ball, (cx, cy), (w // 2 + 14, h // 2 + 14), 0, 0, 360, 255, -1)
    plate = np.full((H, W, 3), 40, np.uint8)
    plate[ball > 0] = (255, 255, 255)
    orig = plate.copy()
    ink = _japanese()
    orig[ink > 0] = (0, 0, 0)
    r = TextRegion(id=1, bbox=BOX, kind="bubble", text_mask=ink, bubble_mask=ball)
    r.dst_text, r.order = TEXT, 0
    page = Page(image=orig, source_path="balloon")
    page.regions = [r]
    page.clean_plate = plate
    return page


def test_typesetting_on_a_dark_panel_is_recorded_white_with_a_black_outline():
    page = _on_dark_art()
    typeset_page(page, _cfg())
    lay = page.regions[0].layout
    assert lay.lines, "nothing was typeset, so there is nothing to colour"
    assert lay.fg == "#ffffff"
    assert lay.edge == "#000000"
    # A hairline is what the default was; on artwork the outline has to carry
    # the letters, so it is sized from the type.
    assert lay.stroke > 1


def test_the_recorded_colours_are_the_ones_the_exporter_uses():
    page = _on_dark_art()
    cfg = _cfg()
    typeset_page(page, cfg)
    r = page.regions[0]
    fg, edge, stroke = render._ink_colours(page.clean_plate, r, r.layout,
                                           on_art(r), orig=page.image)
    assert r.layout.fg == "#%02x%02x%02x" % fg[:3]
    assert r.layout.edge == "#%02x%02x%02x" % edge[:3]
    assert int(r.layout.stroke) == int(stroke)


def test_the_colours_survive_being_saved_and_read_back():
    page = _on_dark_art()
    typeset_page(page, _cfg())
    saved = region_record(page.regions[0])["layout"]
    assert saved["fg"] == "#ffffff"
    assert saved["edge"] == "#000000"
    assert saved["stroke"] > 1


def test_an_ordinary_white_balloon_stays_black_on_white():
    page = _white_balloon()
    typeset_page(page, _cfg())
    lay = page.regions[0].layout
    assert lay.lines
    assert lay.fg == "#000000"
    assert lay.edge == "#ffffff"


def test_a_page_with_no_artwork_still_lays_out():
    """The fitter is exercised on its own elsewhere with a stand-in page that
    has no image at all. Colouring must not be what breaks it."""
    class Stand:
        def __init__(self, regions):
            self.regions = regions

        def ordered(self):
            return self.regions

    r = TextRegion(id=1, bbox=BOX, kind="bubble", text_mask=_japanese())
    r.dst_text, r.order = TEXT, 0
    typeset_page(Stand([r]), _cfg())
    assert r.layout is not None and r.layout.lines


def test_the_lit_label_is_not_left_to_cleartype():
    """lee sent a crop of the lit view switch: "Translation", black on its
    yellow pill, reading blue-violet.

    That is ClearType. Windows fakes a third of a pixel of horizontal
    resolution by lighting the red, green and blue subpixels of a pixel by
    different amounts - invisible on black-on-white, and on DARK TEXT OVER A
    SATURATED YELLOW the fringes have nothing to blend into, so the label
    picks up a colour it was never given. Every lit control here is that
    combination: the view switch, the open tab, every `.pri` button.

    Greyscale antialiasing has no colour to fringe with, so the label is the
    colour the stylesheet says. Set on `body` and inherited, because the
    problem is not one control's.
    """
    import re
    from pathlib import Path
    css = (PKG / "static" / "css"
           / "editor.css").read_text(encoding="utf-8")
    body = re.search(r"\nbody\{(.*?)\}", css, re.S)
    assert body, "no body rule"
    assert "-webkit-font-smoothing:antialiased" in body.group(1)
    assert "-moz-osx-font-smoothing:grayscale" in body.group(1)


def test_the_unlit_view_label_is_readable():
    """The other half of the same crop: "Image", unlit, almost invisible
    against the strip it sits on. `--dim` is the right weight for a line of
    help text under a field; it is not enough for a 12px control label that is
    one of the two things you can press."""
    import re
    from pathlib import Path
    css = (PKG / "static" / "css"
           / "editor.css").read_text(encoding="utf-8")
    rule = re.search(r"\n\.vw\{(.*?)\}", css, re.S).group(1)
    col = re.search(r"color:(#[0-9a-fA-F]{6})", rule)
    assert col, f"the unlit label went back to a variable: {rule}"

    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h):
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        return .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b)

    a, b = lum(col.group(1)), lum("#12151b")   # the strip behind it
    ratio = (max(a, b) + .05) / (min(a, b) + .05)
    assert ratio >= 7.0, f"{col.group(1)} on #12151b is only {ratio:.1f}:1"


def test_the_name_is_one_word():
    """lee: *"remve teh gap between mangatctc"*. `.brand` is a flex row with a
    gap, and a flex gap falls between EVERY child - so the space meant to sit
    between the mark and the name also sat inside the name."""
    import re
    from pathlib import Path
    root = PKG / "static"
    html = (root / "editor.html").read_text(encoding="utf-8")
    css = (root / "css" / "editor.css").read_text(encoding="utf-8")
    assert '<span class="wm"><b>Manga</b><i>TCT</i></span>' in html, \
        "the two halves are back to being siblings of the mark"
    wm = re.search(r"\.brand \.wm\{(.*?)\}", css, re.S)
    assert wm and "gap:0" in wm.group(1), "the word can still be split by a gap"
