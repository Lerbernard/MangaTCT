"""A speech written across two joined balloons is typeset as two blocks.

lee's pages have balloons drawn as two ovals meeting at a waist: one speech,
written down the first lobe and continued in the second. The detector hands
that over as ONE region with ONE block of Japanese in it, so the translator
returns one sentence and the fitter typeset it as one paragraph — straight
through the pinch. Every line then has to clear the narrowest part of the
shape, so the whole speech shrinks to fit a gap it was never meant to cross.
That is why his double balloons came out tiny.

A typesetter does the obvious thing: the first part of the sentence fills the
first lobe, the rest fills the second, both at one size so it still reads as
one voice. These tests pin that this happens WHENEVER the balloon has a waist —
the shape decides, not the length of this particular sentence, so the same
balloon always typesets the same way — that a balloon with no waist is left
alone, that the one thing still able to refuse a division is type too small to
read, that no word is split and none is dropped, and — the part lee filmed
going wrong — that touching the block afterwards does not slide the second half
back into the waist.

The division is read off the SHAPE at typesetting time, not at detection time,
because a chapter already translated cannot be re-detected without throwing
away every translation on it.
"""
import copy
import re
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import Page, TextRegion
from mangatl.project import region_record
from mangatl.typeset import (TypesetConfig, _best, anchor_to_frame,
                             balloon_lobes, default_font_path, fit_region,
                             layout_from_override, typeset_page)
from scratch import scratch
from where import PKG

H, W = 700, 700
TEXT = "I'M SORRY, ADA... IT'S MY OWN WEAKNESS THAT DID THIS TO YOU."
JS = PKG / "static" / "js"


def _cfg(**kw):
    kw.setdefault("font_path", default_font_path())
    kw.setdefault("min_font", 10)
    kw.setdefault("max_font", 34)
    return TypesetConfig(**kw)


def _columns(xs, ys):
    """Vertical Japanese: small blocks stacked down a column."""
    ink = np.zeros((H, W), np.uint8)
    for x in xs:
        for y in ys:
            cv2.rectangle(ink, (x - 8, y), (x + 8, y + 18), 255, -1)
    return ink


def _stacked(rx=150, ry=80, dy=70):
    """Two ovals one above the other, meeting at a waist, Japanese in both.

    Stacked is the shape that hurts: the waist is a HORIZONTAL pinch, so every
    line of a single paragraph laid across it has to clear it.
    """
    bub = np.zeros((H, W), np.uint8)
    cv2.ellipse(bub, (350, 350 - dy), (rx, ry), 0, 0, 360, 255, -1)
    cv2.ellipse(bub, (350, 350 + dy), (rx, ry), 0, 0, 360, 255, -1)
    ink = _columns((330, 360),
                   list(range(350 - dy - 40, 350 - dy + 40, 26))
                   + list(range(350 + dy - 40, 350 + dy + 40, 26)))
    return bub, cv2.bitwise_and(ink, bub)


def _side_by_side(rx=80, ry=100, dx=75):
    """Two ovals meeting side by side — a waist, but a VERTICAL one.

    Horizontal lines are not squeezed by it: across the middle of the pair the
    shape is one wide opening, so typesetting the speech as one paragraph is
    already as big as it can be. Dividing it here would make it smaller, and
    the point of dividing is that it is bigger.
    """
    bub = np.zeros((H, W), np.uint8)
    cv2.ellipse(bub, (350 - dx, 350), (rx, ry), 0, 0, 360, 255, -1)
    cv2.ellipse(bub, (350 + dx, 350), (rx, ry), 0, 0, 360, 255, -1)
    ink = _columns((350 - dx - 10, 350 - dx + 10, 350 + dx - 10, 350 + dx + 10),
                   range(300, 420, 26))
    return bub, cv2.bitwise_and(ink, bub)


def _oval():
    """One plain balloon with one block of Japanese in it."""
    bub = np.zeros((H, W), np.uint8)
    cv2.ellipse(bub, (350, 350), (200, 140), 0, 0, 360, 255, -1)
    ink = _columns((330, 360), range(280, 420, 26))
    return bub, cv2.bitwise_and(ink, bub)


def _region(bub, ink, text=TEXT):
    r = TextRegion(id=1, bbox=cv2.boundingRect(ink), text_mask=ink,
                   bubble_mask=bub, bubble_bbox=cv2.boundingRect(bub))
    r.dst_text = text
    return r


@pytest.fixture(scope="module")
def divided():
    """The double balloon, typeset. Shared: a fit costs a couple of seconds."""
    bub, ink = _stacked()
    r = _region(bub, ink)
    cfg = _cfg()
    return r, cfg, bub, fit_region(r, cfg, bub)


# ------------------------------------------------------------ it divides at all

def test_a_double_balloon_is_seen_as_two_lobes_at_typesetting_time():
    """Detection cannot help here: the page was found before necks existed.

    The shape still says what it always said, so the question is asked again
    at the moment the English is placed.
    """
    bub, ink = _stacked()
    assert len(balloon_lobes(bub, ink)) == 2


def test_a_plain_balloon_is_not_two_lobes():
    """Any chord divides any shape, so the refusal is the load-bearing half."""
    bub, ink = _oval()
    assert balloon_lobes(bub, ink) == []


def test_the_speech_is_divided_between_the_lobes(divided):
    r, cfg, bub, lay = divided
    assert lay.fixed, "the division has to be marked, or it gets re-spaced"
    ys = [y for _, y in lay.line_origins]
    top = [y for y in ys if y < 350]
    bot = [y for y in ys if y >= 350]
    assert top and bot, (ys, "both lobes must be used")


def test_it_typesets_bigger_than_typesetting_it_across_the_waist(divided):
    """lee's whole complaint: "the split bubbles should show both the text but
    bigger". On a STACKED pair the waist is a horizontal pinch every line of a
    merged paragraph has to clear, so dividing is both righter and bigger. It
    is no longer the reason the division is taken — see the test below — but it
    is still what the reader gets on the shape that hurts most."""
    r, cfg, bub, lay = divided
    merged = _best(TEXT, bub > 0, cfg)
    assert merged is not None
    assert lay.font_size > merged.font_size, (lay.font_size, merged.font_size)


def test_a_waist_divides_even_when_merging_would_typeset_bigger():
    """The balloon decides, not the sentence.

    Side by side, the pair is one wide opening across its middle, so typesetting
    the speech straight through the waist comes out BIGGER than putting half in
    each lobe. The old rule kept the bigger one, and that is what lee has been
    sending back: the same balloon divides under a long line and merges under a
    short one, because "does it typeset bigger" is a question about the sentence.
    A reader cannot see any reason for the difference — they just see two lobes
    with one paragraph smeared across both. A waist is two places to put words,
    so words go in both, every time.
    """
    bub, ink = _side_by_side()
    assert len(balloon_lobes(bub, ink)) == 2, "fixture must have a waist"
    r = _region(bub, ink)
    cfg = _cfg()
    lay = fit_region(r, cfg, bub)
    merged = _best(TEXT, bub > 0, cfg)
    assert merged is not None
    assert lay.fixed, "a waist must divide"
    # It costs size here, and it is taken anyway — that is the whole point.
    assert lay.font_size < merged.font_size, (lay.font_size, merged.font_size)
    assert lay.font_size >= cfg.min_font, lay.font_size
    xs = [x for x, _ in lay.line_origins]
    assert [x for x in xs if x < 350] and [x for x in xs if x >= 350], \
        (xs, "both lobes must be used")


def test_a_division_too_small_to_read_is_refused():
    """The one thing still allowed to overrule the waist: readability.

    Run together is bad. Too small to read is worse — it is the failure lee
    started this whole thread with. So when dividing drops the type under the
    floor a human set while merging clears it, merging wins. Same balloon and
    same sentence as the test above; only the floor has moved.
    """
    bub, ink = _side_by_side()
    r = _region(bub, ink)
    loose, tight = _cfg(), _cfg(min_font=26)
    divided_size = fit_region(_region(bub, ink), loose, bub).font_size
    merged = _best(TEXT, bub > 0, tight)
    assert merged is not None
    assert divided_size < 26 <= merged.font_size, \
        (divided_size, merged.font_size, "fixture no longer straddles the floor")

    lay = fit_region(r, tight, bub)
    assert not lay.fixed, (lay.font_size, "divided under the floor anyway")
    assert lay.font_size == merged.font_size


def test_a_plain_balloon_is_typeset_in_one_piece():
    bub, ink = _oval()
    r = _region(bub, ink)
    cfg = _cfg()
    lay = fit_region(r, cfg, bub)
    assert not lay.fixed, "nothing to divide here"


# --------------------------------------------------- and the words survive it

def test_every_word_goes_in_and_no_word_is_split(divided):
    """No hyphenation, ever, and never a reworded or dropped clause: the
    division is made at a space and nowhere else."""
    r, cfg, bub, lay = divided
    assert " ".join(" ".join(lay.lines).split()) == TEXT
    assert "-\n" not in "\n".join(lay.lines)


def test_both_halves_stay_inside_the_balloon(divided):
    r, cfg, bub, lay = divided
    for x, y in lay.line_origins:
        assert bub[int(y), int(x)] > 0, ((x, y), "a line left the balloon")


def test_the_two_halves_are_typeset_at_one_size(divided):
    """One voice, one size — a speech that changes size at the waist reads as
    two people talking."""
    r, cfg, bub, lay = divided
    assert isinstance(lay.font_size, int)
    assert lay.font_size >= cfg.min_font


def test_the_pair_gets_one_box_round_both_halves(divided):
    r, cfg, bub, lay = divided
    assert lay.frame is not None
    fx, fy, fw, fh = lay.frame
    assert fw > 8 and fh > 8, lay.frame
    for x, y in lay.line_origins:
        assert fx <= x <= fx + fw and fy <= y <= fy + fh, (x, y, lay.frame)


# ------------------------------------------------- and touching it leaves it be

def test_the_box_does_not_re_space_a_divided_speech(divided):
    """Anchoring evenly spaces lines down a box. Doing that to two blocks is
    exactly what would drag the second half back up into the waist."""
    r, cfg, bub, lay = divided
    before = [tuple(o) for o in lay.line_origins]
    # anchoring rewrites in place, so this must not be the shared layout
    after = [tuple(o) for o in
             anchor_to_frame(copy.deepcopy(lay), cfg).line_origins]
    assert after == before, (before, after)


def test_selecting_a_divided_speech_puts_it_back_exactly(divided):
    """The bug lee filmed, in its last hiding place.

    Clicking a block writes an override and the override is re-laid out. For
    an ordinary block the box reproduces the fit; for a divided speech there
    is no such box, so the positions travel with the override.
    """
    r, cfg, bub, lay = divided
    r.layout_override = {"lines": list(lay.lines),
                         "font_size": lay.font_size,
                         "leading": lay.leading, "locked": True,
                         "fixed": True,
                         "origins": [[int(x), int(y)]
                                     for x, y in lay.line_origins],
                         "frame": None}
    try:
        back = layout_from_override(r, cfg, bub)
    finally:
        r.layout_override = None
    assert back is not None and back.fixed
    assert [tuple(o) for o in back.line_origins] == \
        [tuple(o) for o in lay.line_origins]


def test_retyping_the_speech_gives_the_box_back():
    """Once the words are not the words that were divided, the stored
    positions mean nothing — it becomes an ordinary block in an ordinary box
    rather than keeping stale coordinates."""
    bub, ink = _stacked()
    r = _region(bub, ink)
    cfg = _cfg()
    r.layout_override = {"lines": ["HELLO", "THERE", "AGAIN"],
                         "font_size": 20, "leading": 1.12, "locked": True,
                         "fixed": True,
                         "origins": [[350, 280], [350, 420]],   # stale: 2 of 3
                         "frame": None}
    back = layout_from_override(r, cfg, bub)
    assert back is not None
    assert not back.fixed
    assert len(back.line_origins) == 3


def test_a_whole_page_keeps_the_division(divided):
    bub, ink = _stacked()
    r = _region(bub, ink)
    img = np.full((H, W, 3), 240, np.uint8)
    typeset_page(Page(image=img, regions=[r]), _cfg())
    assert r.layout is not None and r.layout.fixed
    _, _, _, solo = divided
    assert [tuple(o) for o in r.layout.line_origins] == \
        [tuple(o) for o in solo.line_origins]


def test_the_saved_page_records_the_division(divided):
    """A reload must not quietly turn a divided speech back into a paragraph."""
    r, cfg, bub, lay = divided
    r.layout = lay
    rec = region_record(r)
    assert rec["layout"]["fixed"] is True
    assert len(rec["layout"]["origins"]) == len(lay.lines)


def test_the_preview_the_person_looks_at_says_it_is_divided():
    """The preview is the picture on screen, and it is built by a different
    path from the export. If it drops the flag, the browser fills one box with
    the lines and the second half slides into the waist — on screen only,
    which is the most confusing way for it to be wrong.
    """
    import shutil

    from mangatl import editor
    from mangatl.project import Project

    shutil.rmtree(scratch("_tmp_lobes"), ignore_errors=True)
    was = editor.PROJECT
    try:
        bub, ink = _stacked()
        img = np.full((H, W), 245, np.uint8)
        img[bub > 0] = 255
        cnts, _ = cv2.findContours(bub, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(img, cnts, -1, 20, 3)
        img[ink > 0] = 15
        page = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        p = Project(None, scratch("_tmp_lobes"))
        p.add_uploaded("d0.png", cv2.imencode(".png", page)[1].tobytes())
        r = _region(bub, ink)
        r.polygon = [[int(a), int(b)] for a, b in
                     max(cnts, key=cv2.contourArea).reshape(-1, 2)]
        p.pages[0].regions = [region_record(r)]
        editor.PROJECT = p
        editor.invalidate_page(0)
        out = editor.layout_preview(p, 0, r.id, {})
        assert out.get("lines"), out
        assert out.get("fixed") is True, out
        want = fit_region(p.materialize(0).regions[0],
                          editor._typeset_cfg(p))
        assert [list(o) for o in want.line_origins] == out["origins"]
    finally:
        editor.PROJECT = was
        editor.invalidate_page(0)
        shutil.rmtree(scratch("_tmp_lobes"), ignore_errors=True)


# --------------------------------------------------------- the browser's copy

def test_the_browser_leaves_a_divided_speech_where_it_is():
    """The browser places lines itself while dragging, so it is a second copy
    of this rule and can drift away from it."""
    src = (JS / "frames.js").read_text(encoding="utf-8")
    body = src.split("function layoutOrigins")[1].split("\n}")[0]
    code = re.sub(r"//[^\n]*", "", body)
    flat = re.sub(r"\s+", "", code)
    assert "L.fixed" in flat, body
    assert "returnL.origins" in flat, body


def test_dragging_a_divided_speech_carries_the_words_with_the_box():
    src = (JS / "frames.js").read_text(encoding="utf-8")
    body = src.split("function setFrame")[1].split("\n}")[0]
    code = re.sub(r"//[^\n]*", "", body)
    flat = re.sub(r"\s+", "", code)
    assert "L.fixed" in flat, body
    assert "o[0]+ddx" in flat and "o[1]+ddy" in flat, body


def test_the_browser_sends_the_positions_back_when_it_saves():
    """If the save drops them the server has nothing to rebuild from, and the
    second half snaps into the waist on the next round trip."""
    src = (JS / "typesetting-edit.js").read_text(encoding="utf-8")
    body = src.split("function currentPatch")[1].split("\n}")[0]
    code = re.sub(r"//[^\n]*", "", body)
    flat = re.sub(r"\s+", "", code)
    assert "fixed:!!(r.layout&&r.layout.fixed)" in flat, body
    assert "origins:" in flat, body
