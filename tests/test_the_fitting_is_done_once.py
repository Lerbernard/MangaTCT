# -*- coding: utf-8 -*-
"""A page is laid out once, and looked at as often as you like.

lee: *"make it so that teh typesettng is setting every time i swtitch pages -
it shoud do it one and when i switch it shou ld already be teher"*.

## What it cost

Building a finished page is three seconds, and 2.6 of them are `typeset_page`:
the fitter searching sizes and line breaks for every block. It ran on every
render, every export and every restart - to arrive at the layout already
written on the record. `region_from_record` threw that layout away on purpose:

    a block with typesetting is typeset again from scratch by whichever
    stage asked for it

which is the right default and the wrong price. Laying out again is only
necessary when something that decides the layout has moved.

## The key

Each layout now carries a fingerprint of what it was fitted from
(`typeset.page_fit_key`), and a page whose fingerprint still matches keeps the
layouts it has. Three things decide what goes in it:

* **the whole page, not one block.** Blocks are fitted against each other -
  `share_masks` cuts a shared balloon between two of them, `_level_caps` sets
  one size across the page - so one box moving can move everyone's lines. One
  key for the page, coarse on purpose.
* **what steers the fitter, not what steers the paint** (`FIT_KEYS`). A colour
  cannot move a line, so changing one must not cost a re-fit.
* **nothing that is an output of fitting**, or the key would change every time
  it was used.

Remembered twice over: stamped on the record, so it survives a restart, and
held in memory for the run, because plenty of renders never commit - the exact
view asks read-only on purpose, and a page served from the disk cache never
lays anything out at all, so it never stamps.

Measured on lee's page 009, nine blocks: **2379 ms to fit, 97 ms to reuse**,
identical lines, sizes, origins and colours. The chapter cold went from 110 s
to 32 s.

## The one that bit

The reuse path returned early and skipped `assign_colours` along with
everything else, so a reused layout kept whatever colours it was carrying - a
plain white balloon came back with white letters on it. **The colours are not
part of the fit**: they are read off the page, which is exactly why they are
not in the key, and exactly why they still have to be worked out every time.
"""
import shutil

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import Page, TextRegion            # noqa: E402
from mangatl.typeset import (FIT_KEYS, TypesetConfig,  # noqa: E402
                             page_fit_key, typeset_page)


def _page(text="a line of dialogue", dark=False):
    """A balloon with words in it, on paper or on a black panel."""
    ground = 20 if dark else 250
    img = np.full((400, 360, 3), 120, np.uint8)
    cv2.ellipse(img, (180, 180), (150, 110), 0, 0, 360,
                (ground,) * 3, -1)
    cv2.ellipse(img, (180, 180), (150, 110), 0, 0, 360,
                (250 if dark else 20,) * 3, 3)
    bub = np.zeros((400, 360), np.uint8)
    cv2.ellipse(bub, (180, 180), (150, 110), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, bbox=(90, 130, 180, 100), kind="bubble", order=0,
                   src_text="テスト", dst_text=text,
                   bubble_mask=bub, bubble_bbox=(30, 70, 300, 220),
                   text_mask=np.zeros((400, 360), np.uint8))
    pg = Page(image=img)
    pg.regions = [r]
    return pg


def _cfg():
    from mangatl.typeset import default_font_path
    return TypesetConfig(font_path=default_font_path(), min_font=10,
                         max_font=34)


def _shape(pg):
    return [(r.layout.lines, r.layout.font_size,
             [tuple(o) for o in r.layout.line_origins])
            for r in pg.regions if r.layout]


def _colours(pg):
    return [(r.layout.fg, r.layout.edge) for r in pg.regions if r.layout]


# --------------------------------------------------------------- the key

def test_the_same_page_asks_the_same_question():
    a, b = _page(), _page()
    assert page_fit_key(a, _cfg()) == page_fit_key(b, _cfg())


def test_the_words_are_in_it():
    a, b = _page("one thing"), _page("something else entirely")
    assert page_fit_key(a, _cfg()) != page_fit_key(b, _cfg())


def test_the_box_is_in_it():
    a, b = _page(), _page()
    b.regions[0].bbox = (90, 130, 181, 100)
    assert page_fit_key(a, _cfg()) != page_fit_key(b, _cfg())


def test_the_font_settings_are_in_it():
    from mangatl.typeset import default_font_path
    a = _page()
    one = TypesetConfig(font_path=default_font_path(), min_font=10, max_font=34)
    two = TypesetConfig(font_path=default_font_path(), min_font=10, max_font=48)
    assert page_fit_key(a, one) != page_fit_key(a, two)


def test_a_colour_is_not_in_it():
    """A colour cannot move a line, and a page being re-fitted every time
    somebody nudges a glow is the whole cost this exists to avoid."""
    a, b = _page(), _page()
    b.regions[0].layout_override = {"glow": "#ff0000", "glow_size": 9,
                                    "fg": "#123456", "shadow": "#000000"}
    assert page_fit_key(a, _cfg()) == page_fit_key(b, _cfg())


def test_what_steers_the_fitter_is_in_it():
    for k, v in (("font_size", 22), ("lines", ["a", "b"]), ("lspace", 3),
                 ("frame", [1, 2, 3, 4]), ("caps", True), ("rotate", 12)):
        a, b = _page(), _page()
        b.regions[0].layout_override = {k: v}
        assert page_fit_key(a, _cfg()) != page_fit_key(b, _cfg()), k
    for k in ("caps", "font", "lines", "frame", "locked", "rotate"):
        assert k in FIT_KEYS, k


# ------------------------------------------------------------- the reuse

def test_a_page_that_has_not_changed_keeps_its_fitting():
    cfg = _cfg()
    pg = _page()
    typeset_page(pg, cfg)
    was = _shape(pg)
    assert was and was[0][0]

    # the same page again, carrying the layouts it was given
    again = _page()
    for r, src in zip(again.regions, pg.regions):
        r.layout = src.layout
    typeset_page(again, cfg)
    assert _shape(again) == was


def test_the_colours_are_worked_out_even_when_the_fitting_is_reused():
    """The one that bit. Colours are read off the PAGE, so they are not in the
    key - and a reuse path that returns early must not skip them. A white
    balloon came back with white letters in it."""
    cfg = _cfg()
    dark = _page("some words here", dark=True)
    typeset_page(dark, cfg)
    on_black = _colours(dark)

    light = _page("some words here", dark=False)
    # the same words in the same box, so the same fit - and the OPPOSITE page
    for r, src in zip(light.regions, dark.regions):
        r.layout = src.layout
    typeset_page(light, cfg)
    assert _shape(light) == _shape(dark), "this test needs the fit to be reused"
    assert _colours(light) != on_black, \
        "a reused layout kept the other page's colours"
    assert _colours(light)[0][0].lower() in ("#000000", "#0a0a0a", "#101010"), \
        _colours(light)


def test_a_change_that_moves_a_line_is_fitted_again():
    cfg = _cfg()
    pg = _page("a line of dialogue")
    typeset_page(pg, cfg)
    was = _shape(pg)

    moved = _page("a very much longer line of dialogue than the one before it")
    for r, src in zip(moved.regions, pg.regions):
        r.layout = src.layout          # a stale layout, deliberately
    typeset_page(moved, cfg)
    assert _shape(moved) != was, "the words changed and the fitting did not"


def test_pressing_typeset_always_fits_again():
    """`redo` is the button. It has to ignore every remembered answer, or
    "lay this page out again" would be a no-op.

    Note what `redo` does NOT mean: it drops the placement keys out of the
    override (`clear_fitting`), so a hand-set size is exactly what it throws
    away. The thing to check is that it does not stop at the stamp.
    """
    from mangatl.typeset import _FITS
    cfg = _cfg()
    pg = _page()
    typeset_page(pg, cfg)
    good = _shape(pg)

    # A layout stamped with the right fingerprint and carrying rubbish. Left
    # alone, the stamp is believed - that is the whole point of the stamp.
    pg.regions[0].layout.lines = ["nonsense"]
    _FITS.clear()
    typeset_page(pg, cfg)
    assert _shape(pg) != good, "this test needs the stamp to be believed first"

    typeset_page(pg, cfg, redo=True)
    assert _shape(pg) == good, "Typeset reused a fitting instead of doing one"


def test_moving_a_hand_placed_box_does_not_refit_the_page():
    """lee, watching "building the exported page..." after every nudge: *"is
    there a way to make building teh exprted page be faster when i move
    something"*. A locked override never enters the fitter and `_level_caps`
    skips it, so its frame cannot move anyone else's lines - dragging it must
    not throw the page's fitting away."""
    cfg = _cfg()
    a, b = _page(), _page()
    b.regions[0].layout_override = {
        "lines": ["a line of", "dialogue"], "locked": True,
        "frame": [40, 60, 130, 80], "dx": 12, "dy": -7}
    ka, kb = page_fit_key(a, cfg), page_fit_key(b, cfg)
    assert ka != kb, "locking is part of the key - unlocking must refit"
    b2 = _page()
    b2.regions[0].layout_override = {
        "lines": ["a line of", "dialogue"], "locked": True,
        "frame": [90, 100, 130, 80], "dx": -3, "dy": 20}   # moved elsewhere
    assert page_fit_key(b2, cfg) == kb,         "a drag changed the page key - every nudge refits the whole page"


def test_the_reuse_path_places_the_moved_box_where_it_now_stands():
    """The half that makes the one above safe: with the frame out of the
    key, the STORED layout may be the box where it stood before the drag -
    so the reuse path must re-place every hand-placed box from its
    override, not trust the stamp."""
    from mangatl.typeset import _FITS
    cfg = _cfg()
    pg = _page()
    pg.regions[0].layout_override = {
        "lines": ["a line of", "dialogue"], "locked": True,
        "frame": [40, 60, 130, 80]}
    typeset_page(pg, cfg)
    was = tuple(pg.regions[0].layout.frame)

    moved = _page()
    moved.regions[0].layout_override = {
        "lines": ["a line of", "dialogue"], "locked": True,
        "frame": [90, 100, 130, 80]}
    # the stored layout still says the OLD place, stamped with the same key
    import copy as _c
    moved.regions[0].layout = _c.deepcopy(pg.regions[0].layout)
    typeset_page(moved, cfg)
    now = tuple(moved.regions[0].layout.frame)
    assert now != was, "the reuse path drew the box where it stood "         "before the drag"
    assert now[:2] == (90, 100), now


def test_a_move_reuses_in_milliseconds_not_seconds():
    """The measurement the feature is for."""
    import time
    from mangatl.typeset import _FITS
    cfg = _cfg()
    pg = _page()
    typeset_page(pg, cfg)                      # page fitted and remembered
    pg.regions[0].layout_override = {
        "lines": ["a line of", "dialogue"], "locked": True,
        "frame": [40, 60, 130, 80]}
    typeset_page(pg, cfg)                      # first time under the lock
    t0 = time.time()
    pg.regions[0].layout_override = dict(pg.regions[0].layout_override,
                                         frame=[90, 100, 130, 80])
    typeset_page(pg, cfg)                      # the drag
    took = time.time() - t0
    assert tuple(pg.regions[0].layout.frame)[:2] == (90, 100)
    assert took < 0.35, "a drag cost %.0f ms - the page refitted"         % (took * 1000)


def test_the_share_search_is_paid_once_per_page(monkeypatch):
    """`share_masks` is not geometry - deciding how to divide a shared
    balloon TYPESETS THE CANDIDATES AND MEASURES, and it sat above the
    fit-cache early return, so every render of an unchanged page paid it.
    Three seconds here, ten on lee's machine: *"its taking a good 10s secor
    or more to rebuild"*. The cuts are remembered under the fit key now,
    PNG-encoded, and an unchanged page decodes instead of measuring."""
    import mangatl.typeset as M
    from mangatl.typeset import _FITS, _SHARES
    _FITS.clear(); _SHARES.clear()
    calls = []
    real = M.share_masks
    monkeypatch.setattr(M, "share_masks",
                        lambda *a, **k: (calls.append(1) or real(*a, **k)))
    cfg = _cfg()
    pg = _page()
    # already hand-placed: LOCKING changes the key (rightly - one search),
    # so start locked and count from there.
    pg.regions[0].layout_override = {
        "lines": ["a line of", "dialogue"], "locked": True,
        "frame": [40, 60, 130, 80]}
    typeset_page(pg, cfg)
    typeset_page(pg, cfg)                  # unchanged: no search
    pg.regions[0].layout_override = dict(
        pg.regions[0].layout_override, frame=[90, 100, 130, 80])   # a drag
    typeset_page(pg, cfg)                  # a drag: no search either
    assert len(calls) == 1, \
        "the share search ran %d times on one unchanged page" % len(calls)
    assert pg.regions[0].layout.frame[:2] == (90, 100), \
        "the remembered cuts drew the box where it stood before the drag"


def test_a_layout_with_no_stamp_is_fitted():
    """A chapter typeset by an older build has layouts and no fingerprints.
    That must be the old behaviour exactly: fit it."""
    cfg = _cfg()
    pg = _page()
    typeset_page(pg, cfg)
    good = _shape(pg)
    stale = _page()
    for r, src in zip(stale.regions, pg.regions):
        import copy as _c
        r.layout = _c.deepcopy(src.layout)
        r.layout.fit = ""              # written before stamps existed
        r.layout.lines = ["nonsense"]
    from mangatl.typeset import _FITS
    _FITS.clear()
    typeset_page(stale, cfg)
    assert _shape(stale) == good, "an unstamped layout was trusted"
