"""A block of typesetting is a text box, and there is only one of it.

lee filmed the bug: click a block of English and the words jump somewhere else;
click away and they jump back. Nothing had changed but the selection.

The cause was that three different pieces of the program each had their own
answer to "where does line 3 of this block go":

* the FITTER placed lines against the balloon's shape and returned absolute
  positions;
* the BROWSER, the moment it had to place them itself - while dragging, or on
  a block whose positions it didn't trust - filled a box instead, and had no
  box, so it borrowed the BUBBLE's rectangle (or worse, the rectangle of the
  vertical Japanese it replaced, which is tall and narrow and nowhere near);
* the EDITOR you type into filled a third box with CSS.

Word and Photoshop have no such problem because in them the box IS the layout:
the text has a frame, the frame decides the width the words wrap to and the
middle they sit on, and moving the frame moves the words. Nothing else can
disagree with the frame, because there is nothing else.

So the fitter still decides everything it decided before - the size, the line
breaks, which chord of the balloon each line belongs in - and then hands the
result over as a frame plus one line of arithmetic that fills it. These tests
pin that the frame really is drawn round the WORDS (not the bubble, not the
Japanese), that filling it reproduces the fitter's own placement exactly, and
that the browser fills it with the same sum the server does.

The one exception is a sound effect, which is not a paragraph in a box: it
runs along its own measured axis with the gap between lines taken from the ink.
It keeps its own placement, and a test here says so.
"""
import re
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import Page, TextRegion
from mangatl.typeset import (TypesetConfig, anchor_to_frame, default_font_path,
                             fit_region, layout_from_override, typeset_page)
from where import PKG

H, W = 520, 460
TEXT = ("I'M SORRY, ADA... IT'S MY OWN WEAKNESS THAT DID THIS TO YOU, AND "
        "NOTHING ELSE.")

JS = PKG / "static" / "js"


def _cfg(**kw):
    kw.setdefault("font_path", default_font_path())
    kw.setdefault("min_font", 10)
    kw.setdefault("max_font", 34)
    return TypesetConfig(**kw)


def _oval():
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (230, 250), (170, 190), 0, 0, 360, 255, -1)
    return m


def _columns(x0=300, top=90, bot=430):
    """The footprint of vertical Japanese: tall, narrow, off to one side.

    This is the rectangle the browser used to fall back to, and the reason the
    words in lee's video flew off into a thin column when he clicked them.
    """
    m = np.zeros((H, W), np.uint8)
    for x in (x0, x0 + 30):
        for y in range(top, bot, 26):
            cv2.rectangle(m, (x - 9, y), (x + 9, y + 18), 255, -1)
    return m


def _fill_the_box(frame, lines, size, leading):
    """The arithmetic every engine uses to fill a text box.

    Transcribed from the browser (frames.js `layoutOrigins`), which is the
    copy furthest from this code - if the server ever drifts, this is what
    notices.
    """
    fx, fy, fw, fh = frame
    lh = size * (leading or 1.12)
    top = fy + (fh - len(lines) * lh) / 2.0
    return [(fx + fw / 2.0, round(top + (k + 0.5) * lh))
            for k in range(len(lines))]


# ------------------------------------------------------- the box is the layout

def test_a_fitted_block_comes_back_with_the_box_it_occupies():
    m = _oval()
    r = TextRegion(id=1, bbox=cv2.boundingRect(m), bubble_mask=m)
    r.dst_text = TEXT
    cfg = _cfg()
    lay = anchor_to_frame(fit_region(r, cfg, m), cfg)
    assert lay.frame is not None
    fx, fy, fw, fh = lay.frame
    assert fw > 0 and fh > 0
    for x, y in lay.line_origins:
        assert fx <= x <= fx + fw, (x, lay.frame)
        assert fy <= y <= fy + fh, (y, lay.frame)


def test_filling_the_box_puts_the_lines_back_exactly_where_the_fitter_had_them():
    """The whole fix in one assertion.

    The words may not move by a pixel when something other than the fitter has
    to place them - which happens every time a block is selected, dragged or
    typed into. That is only true if the box the fitter hands over reproduces
    the fitter's own placement when filled.
    """
    m = _oval()
    r = TextRegion(id=1, bbox=cv2.boundingRect(m), bubble_mask=m)
    r.dst_text = TEXT
    cfg = _cfg()
    lay = anchor_to_frame(fit_region(r, cfg, m), cfg)
    assert len(lay.lines) > 2, lay.lines
    want = _fill_the_box(lay.frame, lay.lines, lay.font_size, lay.leading)
    got = [(float(x), float(y)) for x, y in lay.line_origins]
    for (ax, ay), (bx, by) in zip(got, want):
        assert abs(ax - bx) <= 0.5, (got, want)
        assert abs(ay - by) <= 0.5, (got, want)


def test_the_box_is_drawn_round_the_words_not_round_the_japanese():
    """lee's video: the block jumped into a tall narrow column when clicked.

    That column was the vertical Japanese the English replaced. A text box has
    nothing to do with it - the box belongs to the English.
    """
    ink = _columns()
    m = _oval()
    # What the detector hands over: `bbox` is the Japanese, off to one side of
    # a balloon that is much bigger than it.
    r = TextRegion(id=1, bbox=cv2.boundingRect(ink), text_mask=ink,
                   bubble_mask=m, bubble_bbox=cv2.boundingRect(m))
    r.dst_text = TEXT
    cfg = _cfg()
    lay = anchor_to_frame(fit_region(r, cfg, m), cfg)
    fx, fy, fw, fh = lay.frame
    jx, jy, jw, jh = r.bbox
    assert jh > jw, (r.bbox, "fixture is not a column of Japanese")
    # Nothing like the Japanese's rectangle: the English is wrapped across the
    # balloon, so its box is wider and shorter and sits somewhere else.
    assert fw > jw, (lay.frame, r.bbox)
    assert abs((fx + fw / 2) - (jx + jw / 2)) > 20, (lay.frame, r.bbox)
    # And centred on the words themselves.
    xs = [x for x, _ in lay.line_origins]
    ys = [y for _, y in lay.line_origins]
    assert abs((fx + fw / 2) - sum(xs) / len(xs)) <= 1, (lay.frame, xs)
    assert abs((fy + fh / 2) - (min(ys) + max(ys)) / 2) <= 1, (lay.frame, ys)


def test_the_box_does_not_move_the_words_it_is_drawn_round():
    """Anchoring is a re-description, never a nudge.

    It runs on every block on every page, so if it moved anything at all it
    would be moving typesetting that was already right.
    """
    m = _oval()
    r = TextRegion(id=1, bbox=cv2.boundingRect(m), bubble_mask=m)
    r.dst_text = TEXT
    cfg = _cfg()
    lay = fit_region(r, cfg, m)
    before = [(int(x), int(y)) for x, y in lay.line_origins]
    after = [(int(x), int(y)) for x, y in
             anchor_to_frame(lay, cfg).line_origins]
    for (ax, ay), (bx, by) in zip(before, after):
        assert abs(ax - bx) <= 1 and abs(ay - by) <= 1, (before, after)


# ------------------------------------------------------ down the whole pipeline

def _page(regions):
    img = np.full((H, W, 3), 240, np.uint8)
    return Page(image=img, regions=regions)


def test_every_typeset_block_on_a_page_gets_a_box():
    m = _oval()
    r = TextRegion(id=1, bbox=cv2.boundingRect(m), bubble_mask=m)
    r.dst_text = TEXT
    p = _page([r])
    typeset_page(p, _cfg())
    assert r.layout is not None and r.layout.frame, r.layout
    want = _fill_the_box(r.layout.frame, r.layout.lines,
                         r.layout.font_size, r.layout.leading)
    for (ax, ay), (bx, by) in zip(r.layout.line_origins, want):
        assert abs(ax - bx) <= 0.5 and abs(ay - by) <= 0.5


def test_a_sound_effect_keeps_the_axis_it_was_measured_on():
    """An effect is not a paragraph: its line gaps come from the ink.

    Re-describing it as a box and re-spacing it evenly would straighten out
    the very thing that makes it look drawn rather than typed.
    """
    ink = np.zeros((H, W), np.uint8)
    for i in range(6):                      # a leaning streak of ink
        cv2.circle(ink, (120 + i * 34, 130 + i * 22), 17, 255, -1)
    r = TextRegion(id=1, bbox=cv2.boundingRect(ink), text_mask=ink, kind="sfx")
    r.dst_text = "KRAAASH"
    cfg = _cfg()
    solo = fit_region(r, cfg)
    p = _page([r])
    typeset_page(p, cfg)
    assert [tuple(o) for o in r.layout.line_origins] == \
        [tuple(o) for o in solo.line_origins], (r.layout.line_origins,
                                                solo.line_origins)
    # An effect measures its own box as it lays itself out, along the axis it
    # found in the ink. That box is not the one a paragraph would get, and it
    # is the box the page is exported from, so it has to survive untouched.
    assert list(r.layout.frame) == list(solo.frame), (r.layout.frame,
                                                      solo.frame)


def test_selecting_a_block_writes_an_override_that_places_it_identically():
    """Clicking a block locks it, and a locked block goes down another path.

    That path is where the jump lived, so it has to land on the same pixels as
    the fit it replaced - including the box, which the browser then draws a
    frame around.
    """
    m = _oval()
    r = TextRegion(id=1, bbox=cv2.boundingRect(m), bubble_mask=m)
    r.dst_text = TEXT
    cfg = _cfg()
    lay = anchor_to_frame(fit_region(r, cfg, m), cfg)
    # exactly what the browser sends when you click a block and change nothing
    r.layout_override = {"lines": list(lay.lines), "font_size": lay.font_size,
                         "leading": lay.leading, "locked": True,
                         "frame": None}
    back = layout_from_override(r, cfg, m)
    assert back is not None
    assert list(back.frame) == list(lay.frame), (back.frame, lay.frame)
    for (ax, ay), (bx, by) in zip(back.line_origins, lay.line_origins):
        assert abs(ax - bx) <= 1 and abs(ay - by) <= 1, (back.line_origins,
                                                         lay.line_origins)


# ------------------------------------------------- and the browser's own copy

def test_the_browser_fills_the_box_with_the_same_sum():
    """The browser has to place lines itself - it is what makes dragging
    smooth - so its arithmetic is a second copy of this one. Copies drift;
    this is the thing that noticed the drift in the first place, so it is
    worth a test that reads the copy.
    """
    src = (JS / "frames.js").read_text(encoding="utf-8")
    body = src.split("function layoutOrigins")[1].split("\n}")[0]
    code = re.sub(r"//[^\n]*", "", body)          # the code, not the prose
    flat = re.sub(r"\s+", "", code)
    assert "top=fy+(fh-L.lines.length*lh)/2" in flat, body
    assert "Math.round(top+(k+0.5)*lh)" in flat, body
    assert "fx+fw/2" in flat, body
    # and it must not add dx/dy on top: a frame already carries them
    assert "dx" not in flat, body


def test_the_browser_does_not_fall_back_to_the_bubble_for_a_box():
    """A chapter typeset before boxes existed has origins and no box.

    Borrowing the bubble's rectangle for one is exactly the bug in the video,
    so the fallback measures the words instead.
    """
    src = (JS / "typesetting.js").read_text(encoding="utf-8")
    body = src.split("function derivedFrame")[1].split("\n}\n")[0]
    assert "L.origins" in body or "org" in body, body
    assert "textW(" in body, body
