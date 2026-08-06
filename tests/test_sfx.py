"""Tests for the sound-effect angle reader and the one-word fitter.

Written to drop into tests/ alongside test_pipeline.py. Every one of them was
checked by disabling the code it covers and confirming it fails: the intruder
filter, the size filter, the dead zone, the split-gap guard and the elongation
floor are all load-bearing here.

    python3 -m pytest tests/test_sfx.py -q
"""
import math
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

try:                      # tests run from inside the package folder
    from sfx import fit_sfx, sfx_frame
except ImportError:       # tests run from the folder that contains it
    from mangatl.sfx import fit_sfx, sfx_frame

# A CJK face to draw the fixtures with, and any face to measure English in.
# The fixtures ARE the Japanese sound effects, so a CJK face is not optional.
_JP_CANDIDATES = [
    os.environ.get("MANGATL_TEST_CJK_FONT", ""),
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_EN_CANDIDATES = [
    os.environ.get("MANGATL_TEST_FONT", ""),
    "fonts/CCWildWords.ttf",
    "fonts/ComicNeue-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "C:/Windows/Fonts/comicbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _first(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


JP = _first(_JP_CANDIDATES)
EN = _first(_EN_CANDIDATES)

pytestmark = pytest.mark.skipif(
    not JP or not EN,
    reason="needs a CJK face to draw the fixtures; set MANGATL_TEST_CJK_FONT")

_fonts = {}


def _font(path, size):
    return _fonts.setdefault((path, size), ImageFont.truetype(path, size))


def measure(size, s):
    """Ink extent -- stands in for typeset.ink_extents in these tests."""
    l, t, r, b = _font(EN, size).getbbox(s)
    return (r - l, b - t)


def page_with(text, angle, vertical=True, size=48, canvas=(520, 640),
              tone=False, artline=False, pad=6):
    """A page carrying `text` drawn at `angle`, and the box around it."""
    f = _font(JP, size)
    if vertical:
        w, h = size + 20, size * len(text) + 20
    else:
        w, h = int(size * 1.05 * len(text)) + 20, size + 20
    lay = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(lay)
    for i, ch in enumerate(text):
        xy = (10, 10 + i * size) if vertical else (10 + int(i * size * 1.05), 10)
        d.text(xy, ch, font=f, fill=255)
    lay = lay.rotate(-angle, expand=True, resample=Image.BICUBIC)

    page = Image.new("L", canvas, 255)
    if tone:
        a = np.array(page)
        for yy in range(0, canvas[1], 6):
            for xx in range(0, canvas[0], 6):
                a[yy:yy + 3, xx:xx + 3] = 30
        page = Image.fromarray(a)
    px, py = (canvas[0] - lay.width) // 2, (canvas[1] - lay.height) // 2
    page.paste(Image.new("L", lay.size, 0), (px, py), lay)
    if artline:
        ImageDraw.Draw(page).line([(0, canvas[1]), (canvas[0], 0)], fill=0, width=9)
    box = (max(px - pad, 0), max(py - pad, 0),
           min(lay.width + 2 * pad, canvas[0]),
           min(lay.height + 2 * pad, canvas[1]))
    return np.array(page), box


# --------------------------------------------------------------------------

@pytest.mark.parametrize("drawn", [-30, -20, -12, -6, 0, 6, 12, 20, 30])
def test_a_slanted_vertical_effect_is_read_back_to_the_degree(drawn):
    gray, box = page_with("グルルル", drawn)
    fr = sfx_frame(gray, box)
    assert fr.vertical
    assert abs(fr.tilt - (0 if abs(drawn) < 4 else drawn)) <= 4.5


@pytest.mark.parametrize("drawn", [-25, -10, 0, 10, 25])
def test_a_slanted_horizontal_effect_is_read_back_too(drawn):
    gray, box = page_with("ドオオン", drawn, vertical=False)
    fr = sfx_frame(gray, box)
    assert not fr.vertical
    assert abs(fr.tilt - (0 if abs(drawn) < 4 else drawn)) <= 4.5


def test_screentone_under_the_effect_does_not_steer_it():
    gray, box = page_with("グルルル", 20, tone=True)
    fr = sfx_frame(gray, box)
    assert fr.vertical and abs(fr.tilt - 20) <= 6


def test_artwork_crossing_the_box_does_not_steer_it():
    """A panel border through the region used to drag the angle onto it."""
    gray, box = page_with("グルルル", 0, artline=True)
    assert abs(sfx_frame(gray, box).tilt) <= 6


def test_a_single_round_glyph_invents_no_angle():
    gray, box = page_with("ン", 0, size=90)
    fr = sfx_frame(gray, box)
    assert fr.tilt == 0.0 and not fr.trusted


def test_an_almost_straight_effect_is_left_straight():
    gray, box = page_with("グルルル", 3)
    assert sfx_frame(gray, box).tilt == 0.0


def test_an_empty_box_falls_back_to_its_own_shape():
    fr = sfx_frame(np.full((300, 300), 255, np.uint8), (20, 20, 120, 200))
    assert fr.tilt == 0.0 and fr.vertical and fr.ink == 0


def test_an_effect_that_turns_a_corner_is_not_rotated():
    page = Image.new("L", (400, 400), 255)
    d = ImageDraw.Draw(page)
    for i, ch in enumerate("ドド"):
        d.text((120, 90 + i * 46), ch, font=_font(JP, 44), fill=0)
    for i, ch in enumerate("オオオ"):
        d.text((120 + i * 46, 190), ch, font=_font(JP, 44), fill=0)
    fr = sfx_frame(np.array(page), (80, 80, 250, 250))
    assert fr.tilt == 0.0 and not fr.trusted


def test_two_effects_sharing_one_box_are_not_rotated():
    """The line between two far-apart clusters is not an angle anybody wrote."""
    page = Image.new("L", (400, 400), 255)
    d = ImageDraw.Draw(page)
    for x, y in ((110, 100), (250, 230)):
        for i, ch in enumerate("グル"):
            d.text((x, y + i * 46), ch, font=_font(JP, 44), fill=0)
    fr = sfx_frame(np.array(page), (80, 80, 250, 250))
    assert fr.tilt == 0.0 and not fr.trusted


# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["GRRRR", "GRRR!!", "TA-DA", "DON DON", "..."])
def test_an_effect_is_one_word_however_the_japanese_ran(text):
    """Japanese stacks because Japanese is written down a column. English is
    not, and a column of English capitals reads as a ransom note rather than a
    sound — so whatever the original did, the word goes down as a word."""
    gray, box = page_with("グルルル", -22)
    lay = fit_sfx(sfx_frame(gray, box), text, measure)
    assert lay.lines == [text]


def test_the_word_fits_where_the_original_was():
    """A vertical column's footprint is read along its own writing, not as
    height and breadth: the word may run as far as the effect was long and
    stand as tall as it was wide. That is what keeps a stacked effect's
    replacement the same weight of ink instead of shrinking to the width of
    one Japanese character."""
    gray, box = page_with("グルルル", -22)
    fr = sfx_frame(gray, box)
    lay = fit_sfx(fr, "GRRRR", measure)
    assert fr.vertical, "the fixture is meant to be a column"
    run, across = measure(lay.size, lay.lines[0])
    assert lay.lines == ["GRRRR"]
    assert lay.fitted
    assert run <= fr.length * 1.02
    assert across <= fr.width * 1.35
    assert lay.angle == fr.tilt


def test_fewer_letters_means_bigger_type():
    gray, box = page_with("グルルル", -22)
    fr = sfx_frame(gray, box)
    assert fit_sfx(fr, "GRR", measure).size > fit_sfx(fr, "GRRRR", measure).size


def test_a_word_that_cannot_fit_is_flagged_not_crashed():
    """One line shrinks a long word rather than breaking it, so it takes a
    very long one to run out of room at the floor size — but it still has to
    come back flagged rather than raise or return nothing."""
    gray, box = page_with("グルルル", -22)
    lay = fit_sfx(sfx_frame(gray, box), "W" + "H" * 60 + "AM", measure)
    assert lay.lines and not lay.fitted


def test_a_horizontal_effect_stays_on_one_line_and_is_still_rotated():
    gray, box = page_with("ドオオン", -14, vertical=False)
    lay = fit_sfx(sfx_frame(gray, box), "BOOM", measure)
    assert lay.lines == ["BOOM"]
    assert abs(lay.angle + 14) <= 3
