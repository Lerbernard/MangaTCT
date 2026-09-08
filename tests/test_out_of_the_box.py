"""Outside text and sound effects may leave their box. Speech may not.

lee: *"accualy outside text and sfx shoud be able to got outside teh box if
the text size is bellow the miimum"*.

The box round a piece of outside text is where the JAPANESE ink was, and
Japanese runs down the page in a narrow column. The English runs across. So on
a line of free text the box is routinely the wrong SHAPE rather than the wrong
size, and squeezing English into it means 8pt type on a 1365px page - which is
not typesetting, it is a footnote. There is no balloon under those words either:
they sit on artwork, where a typesetter sets them at a readable size and lets
them cover the drawing.

Sound effects are the same argument with the volume up. An effect is drawn ON
the picture; its box is a note of where the ink was, not a wall.

Speech is the opposite and must not change. A balloon is white paper with a
line round it, and typesetting that leaves it is typesetting on the artwork beside
somebody's head. Inside a balloon the old rule still holds: shrink, and flag it
if that takes it under the minimum.

One limit on the spill: **off the box is allowed, off the PAGE is not**.
Letters outside the image are not typesetting, they are gone, with nothing left
on the page to say a word is missing.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.models import Page, TextLayout, TextRegion
from mangatl.typeset import (TypesetConfig, default_font_path, fit_region,
                             keep_on_page, typeset_page)

# Long enough that no legible size fits the narrow column below.
LONG = "SO THAT IS WHERE THE WHOLE WRETCHED THING HAS BEEN HIDING ALL THIS TIME"


def _cfg(**kw):
    return TypesetConfig(font_path=default_font_path(), **kw)


def _column(kind, text=LONG, box=(150, 150, 60, 100), page=(400, 400)):
    """One region in a tall narrow box - the shape a Japanese column leaves."""
    x, y, w, h = box
    m = np.zeros(page, np.uint8)
    cv2.rectangle(m, (x, y), (x + w, y + h), 255, -1)
    r = TextRegion(id=1, kind=kind, bbox=(x, y, w, h), dst_text=text)
    return r, m


def _fit(kind, **kw):
    r, m = _column(kind, **kw)
    return r, fit_region(r, _cfg(), mask=m)


# --------------------------------------------------------------- outside text

def test_outside_text_is_set_at_the_minimum_rather_than_under_it():
    r, lay = _fit("freefloat")
    cfg = _cfg()
    assert lay.font_size == cfg.min_font, lay.font_size
    assert lay.lines and " ".join(lay.lines).replace("  ", " ").startswith("SO")


def test_and_it_is_marked_as_leaving_its_box():
    """Everything downstream that would pull a block back inside its region
    asks this. A spill nothing knows about is a spill that gets undone."""
    _r, lay = _fit("freefloat")
    assert lay.spills is True


def test_it_really_is_wider_than_the_box_it_belongs_to():
    """The point of the round. If the block still fitted, nothing has
    changed."""
    from mangatl.typeset import _text_w
    r, lay = _fit("freefloat")
    widest = max(_text_w(lay.font_path or default_font_path(),
                         lay.font_size, ln) for ln in lay.lines)
    assert widest > r.bbox[2], (widest, r.bbox[2])


def test_the_spill_is_shared_between_both_sides():
    """Centred on the box, not hung off its top-left corner: a block that grows
    to the right only walks off the panel it belongs to."""
    from mangatl.typeset import _text_w
    r, lay = _fit("freefloat")
    x, _y, w, _h = r.bbox
    centre = x + w / 2.0
    xs = [px for px, _ in lay.line_origins]
    assert abs(sum(xs) / len(xs) - centre) < 2, (xs, centre)


def test_a_line_that_fits_is_left_alone():
    """The spill is a last resort, not the normal path - an ordinary line of
    outside text is fitted the way it always was, and is not marked."""
    _r, lay = _fit("freefloat", text="OK")
    assert lay.spills is False
    assert lay.font_size > _cfg().min_font


# ------------------------------------------------------------- sound effects

def test_a_sound_effect_is_never_typeset_under_the_minimum():
    _r, lay = _fit("sfx")
    assert lay.font_size >= _cfg().min_font, lay.font_size


def test_and_it_says_it_left_its_box():
    _r, lay = _fit("sfx")
    assert lay.spills is True


def test_an_effect_that_fits_its_own_footprint_is_not_marked():
    _r, lay = _fit("sfx", text="CRASH")
    assert lay.spills is False
    assert lay.font_size > _cfg().min_font


def test_the_clamp_still_shrinks_an_effect_that_can_afford_it():
    """`clamp_to_box` is not switched off - it stops at the minimum. An effect
    with room above that floor is still brought back towards its box."""
    from mangatl.typeset import clamp_to_box
    r = TextRegion(id=1, kind="sfx", bbox=(0, 0, 120, 60), dst_text="BOOM")
    lay = TextLayout(lines=["BOOM"], font_size=90, leading=1.0,
                     line_origins=[(60, 30)], font_path=default_font_path())
    out = clamp_to_box(r, lay, _cfg())
    assert out.font_size < 90
    assert out.font_size >= _cfg().min_font


def test_the_clamp_never_grows_an_effect_that_was_already_tiny():
    """The floor is `min(min_font, what it is)`. A flat `min_font` would make
    a shrink into a GROW on an effect the fitter had already put below it."""
    from mangatl.typeset import clamp_to_box
    r = TextRegion(id=1, kind="sfx", bbox=(0, 0, 20, 12), dst_text="BOOM")
    lay = TextLayout(lines=["BOOM"], font_size=9, leading=1.0,
                     line_origins=[(10, 6)], font_path=default_font_path())
    out = clamp_to_box(r, lay, _cfg())
    assert out.font_size <= 9, out.font_size


# ------------------------------------------------------------------- speech

def test_speech_still_shrinks_rather_than_leaving_the_balloon():
    """A balloon is white paper with a line round it. Typesetting outside it is
    typesetting on the drawing beside somebody's head."""
    r, lay = _fit("bubble")
    assert lay.font_size < _cfg().min_font, lay.font_size
    assert lay.spills is False
    assert r.flagged and "minimum" in r.flagged


def test_a_narration_box_counts_as_speech():
    """`narration` is a sub-type of the bubble family - it is a box on paper,
    not words on art - so it keeps the balloon's rule."""
    r, lay = _fit("narration")
    assert lay.spills is False
    assert lay.font_size < _cfg().min_font


# --------------------------------------------------------- but not off the page

def _page_with(kind, text=LONG):
    img = np.full((300, 300, 3), 255, np.uint8)
    page = Page(image=img, source_path="p.png")
    r = TextRegion(id=1, kind=kind, order=0, dst_text=text,
                   bbox=(6, 140, 40, 90))
    m = np.zeros((300, 300), np.uint8)
    cv2.rectangle(m, (6, 140), (46, 230), 255, -1)
    r.bubble_mask = m
    page.regions = [r]
    return page


def test_a_spilling_block_is_slid_back_onto_the_paper():
    """A box hard against the left edge would otherwise put half the words at
    negative x, where nothing is drawn and nothing says so."""
    page = _page_with("freefloat")
    typeset_page(page, _cfg())
    lay = page.regions[0].layout
    assert lay and lay.spills
    from mangatl.typeset import _text_w
    left = min(x - _text_w(lay.font_path, lay.font_size, ln) / 2.0
               for (x, _), ln in zip(lay.line_origins, lay.lines))
    assert left > -2, left


def test_the_slide_never_moves_a_block_that_is_already_on_the_page():
    lay = TextLayout(lines=["HELLO"], font_size=20, leading=1.2,
                     line_origins=[(150, 150)], font_path=default_font_path(),
                     spills=True)
    before = list(lay.line_origins)
    out = keep_on_page(lay, _cfg(), (300, 300))
    assert out.line_origins == before


def test_a_block_wider_than_the_whole_page_is_left_where_it_is():
    """There is nowhere to put it. Sliding it to fit one edge only guarantees
    it runs off the other, and moves the words away from the thing they are
    about."""
    # Off-centre on purpose. A block wider than the page but centred ON it
    # already wants to move by zero, so it cannot tell the guard from its
    # absence: the two overhangs cancel.
    lay = TextLayout(lines=["X" * 400], font_size=40, leading=1.2,
                     line_origins=[(20, 150)], font_path=default_font_path(),
                     spills=True)
    before = list(lay.line_origins)
    out = keep_on_page(lay, _cfg(), (300, 300))
    assert out.line_origins == before


def test_the_frame_travels_with_the_lines():
    """The frame is the box the browser draws and the box you type into. A
    slide that moved the words and left the frame behind puts the handles
    somewhere the words are not."""
    lay = TextLayout(lines=["HELLO"], font_size=20, leading=1.2,
                     line_origins=[(-40, 150)], font_path=default_font_path(),
                     frame=(-70, 138, 60, 24), spills=True)
    out = keep_on_page(lay, _cfg(), (300, 300))
    dx = out.line_origins[0][0] - (-40)
    assert dx > 0
    assert out.frame[0] == -70 + dx


# ------------------------------------------------ and nothing pulls it back in

def test_the_containment_pass_leaves_a_spilling_block_alone():
    """`enforce_bounds` clamps every line's ORIGIN into the region's own mask.
    Run over a block that is bigger than the region on purpose it stacks all
    fourteen lines on the one row that fits - measured, origins
    (26,92),(26,106),(26,121)… become (26,146),(26,146),(26,146)…

    Asked of the clamp directly rather than through `typeset_page`, because
    that is where the rule lives. Through the whole pipeline the damage is
    invisible: `anchor_to_frame` runs afterwards and rebuilds the block from
    its own centre, so the stack is undone by accident a step later. Measuring
    it there would have proved nothing about the rule and everything about the
    accident.
    """
    from mangatl.typeset import enforce_bounds
    r, m = _column("freefloat")
    lay = fit_region(r, _cfg(), mask=m)
    assert lay.spills
    before = list(lay.line_origins)
    out = enforce_bounds(r, lay, _cfg(), m)
    assert out.line_origins == before, "the clamp moved a spilling block"
    assert len(set(out.line_origins)) == len(out.line_origins), \
        "the lines were stacked on one another"


def test_and_speech_is_still_clamped_by_it():
    """The other half: the same call over a block that is NOT meant to leave
    its balloon still does its job."""
    from mangatl.typeset import enforce_bounds
    r, m = _column("bubble")
    lay = fit_region(r, _cfg(), mask=m)
    assert not lay.spills
    lay.line_origins = [(5, 5)] + list(lay.line_origins[1:])
    out = enforce_bounds(r, lay, _cfg(), m)
    x, y = out.line_origins[0]
    assert m[int(y), int(x)] > 0, "a line was left off the balloon"


def test_speech_is_still_contained():
    """The other half of the same switch: with `strict_containment` on, a
    balloon's typesetting is still held inside the balloon."""
    img = np.full((300, 300, 3), 255, np.uint8)
    page = Page(image=img, source_path="p.png")
    m = np.zeros((300, 300), np.uint8)
    cv2.ellipse(m, (150, 150), (70, 50), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, kind="bubble", order=0, dst_text=LONG,
                   bbox=(90, 115, 120, 70))
    r.bubble_mask = m
    page.regions = [r]
    typeset_page(page, _cfg(strict_containment=True))
    lay = page.regions[0].layout
    assert not lay.spills
    for x, y in lay.line_origins:
        assert 0 <= x < 300 and 0 <= y < 300
        assert m[int(y), int(x)] > 0, "a line centre landed off the balloon"


def test_a_spilling_block_is_not_dragged_back_over_its_own_box():
    """`pull_to_box` carries a block that SHARES a balloon back over the box it
    belongs to - the fix for lee's *"the typesetting shoud not be putting text
    across 2 boxes"*. That is right for two speeches in one balloon and wrong
    for a block that is deliberately bigger than its box: dragging it back is
    the spill being undone one step after it was made.

    Two boxes of outside text inside one shape, so `share_masks` gives each of
    them a share and the drag has something to do.
    """
    img = np.full((300, 300, 3), 255, np.uint8)
    page = Page(image=img, source_path="p.png")
    shape = np.zeros((300, 300), np.uint8)
    cv2.rectangle(shape, (40, 40), (110, 250), 255, -1)
    a = TextRegion(id=1, kind="freefloat", order=0, dst_text=LONG,
                   bbox=(50, 50, 50, 90))
    b = TextRegion(id=2, kind="freefloat", order=1, dst_text=LONG,
                   bbox=(50, 150, 50, 90))
    for r in (a, b):
        r.bubble_mask = shape
        r.bubble_bbox = (40, 40, 70, 210)
    page.regions = [a, b]
    typeset_page(page, _cfg())

    for r in (a, b):
        assert r.layout.spills, r.id
        x, y, w, h = r.bbox
        cx = x + w / 2.0
        got = sum(px for px, _ in r.layout.line_origins) / len(r.layout.line_origins)
        assert abs(got - cx) < 8, (r.id, got, cx)
        # ...and it is still the full block, at the minimum, not squeezed
        assert r.layout.font_size == _cfg().min_font


def test_the_slide_happens_after_the_frame_is_settled():
    """`anchor_to_frame` rebuilds a block's frame AND its line positions from
    scratch. A slide made before it is thrown away, so the words go back off
    the page with nothing to show for the trip. Ordering, measured on a block
    that needs both."""
    page = _page_with("freefloat")
    typeset_page(page, _cfg())
    lay = page.regions[0].layout
    assert lay.spills and lay.frame
    from mangatl.typeset import _text_w
    left = min(x - _text_w(lay.font_path, lay.font_size, ln) / 2.0
               for (x, _), ln in zip(lay.line_origins, lay.lines))
    assert left > -2, left
    # ...and the frame went with them, so the handles are where the words are
    fx, _fy, fw, _fh = lay.frame
    assert fx > -6, lay.frame
    assert fx <= left + 2 and fx + fw >= left - 2 + fw - 2, lay.frame


# ------------------------------------------------------- and it is DRAWN spilling

def test_the_export_draws_the_part_that_hangs_out_of_the_box():
    """The last place a spill can be undone, and the worst: `render_page`
    clips each block's layer to the region's own mask, so a block that leaves
    its box came out with the first and last letter of every line sliced off
    - on the exported page, after everything upstream had got it right.
    Caught on a real page, where OF COURSE printed as :OURSE.
    """
    from mangatl import render
    img = np.full((300, 300, 3), 255, np.uint8)
    page = Page(image=img, source_path="p.png")
    m = np.zeros((300, 300), np.uint8)
    cv2.rectangle(m, (130, 100), (170, 200), 255, -1)
    r = TextRegion(id=1, kind="freefloat", order=0, dst_text=LONG,
                   bbox=(130, 100, 40, 100))
    r.bubble_mask = m
    page.regions = [r]
    page.clean_plate = img.copy()
    typeset_page(page, _cfg())
    assert page.regions[0].layout.spills

    out = render.render_page(page, _cfg())
    ink = np.argwhere(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY) < 128)
    assert ink.size, "nothing was drawn at all"
    left, right = int(ink[:, 1].min()), int(ink[:, 1].max())
    assert left < 130 or right > 170, \
        f"the typesetting was cut back to the box ({left}..{right})"


def test_speech_is_still_cut_to_its_balloon_when_it_is_drawn():
    """The other half of the same switch. Clipping is what keeps a stray line
    of dialogue off the artwork, and it stays on for everything that is not
    deliberately spilling."""
    from mangatl import render
    img = np.full((300, 300, 3), 255, np.uint8)
    page = Page(image=img, source_path="p.png")
    m = np.zeros((300, 300), np.uint8)
    cv2.ellipse(m, (150, 150), (60, 45), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, kind="bubble", order=0, dst_text="HELLO THERE",
                   bbox=(105, 125, 90, 50))
    r.bubble_mask = m
    page.regions = [r]
    page.clean_plate = img.copy()
    typeset_page(page, _cfg())
    lay = page.regions[0].layout
    assert not lay.spills
    # Pushed out by hand. The fitter tries hard never to overflow a balloon,
    # so a layout it produced cannot show whether the clip still works - this
    # is the guarantee BEHIND the fitter, and the only way to ask for it is to
    # hand it something that overflows.
    lay.line_origins = [(20, y) for _x, y in lay.line_origins]
    lay.frame = None
    out = render.render_page(page, _cfg())
    ink = np.argwhere(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY) < 128)
    assert ink.size == 0 or all(m[y, x] > 0 for y, x in ink), \
        "dialogue was drawn outside its balloon"


# ------------------------------- but it takes every break before it takes art

HYPHENATED = "LITTLE VILLAINESS-IN-TRAINING."


def _widest(lay, cfg):
    from mangatl.typeset import _text_w
    return max(_text_w(cfg.font_path, lay.font_size, ln) for ln in lay.lines)


def test_a_spill_breaks_where_the_author_already_broke_it_first():
    """lee, with LITTLE VILLAINESS-IN-TRAINING. laid across a panel in one
    strip: *"shou create new line if its too big for the box"*.

    Spilling wrapped on SPACES, so a 23-character hyphenated compound was one
    word nothing could break, and it went out sideways over the drawing when
    it could have been four lines standing in the box. Leaving the box is the
    last thing tried, and it still takes every break the text offers first."""
    r, lay = _fit("freefloat", text=HYPHENATED, box=(150, 150, 60, 220),
                  page=(500, 400))
    assert lay.lines == ["LITTLE", "VILLAINESS-", "IN-", "TRAINING."], lay.lines


def test_and_that_leaves_it_very_nearly_inside_the_box():
    """The measurement that matters: how far out onto the artwork it goes."""
    box = (150, 150, 60, 220)
    r, lay = _fit("freefloat", text=HYPHENATED, box=box, page=(500, 400))
    from mangatl.typeset import _spill_fit, author_break_tokens
    cfg = _cfg()
    # what wrapping on spaces alone gave: one unbreakable 23-character word
    plain = max(len(t) for t in HYPHENATED.split())
    assert plain > max(len(ln) for ln in lay.lines), \
        "the longest line must be shorter than the longest whole word"
    assert _widest(lay, cfg) < box[2] * 1.4, \
        "and the block must be close to the width of its own box"


def test_the_dash_stays_on_the_line_it_ends():
    """VILLAINESS- then IN-, the way a typesetter sets it and the way
    `author_breaks` has always set it. A line opening with a dash is the one
    thing a dash must never do."""
    r, lay = _fit("freefloat", text=HYPHENATED, box=(150, 150, 60, 220),
                  page=(500, 400))
    assert not any(ln.startswith("-") for ln in lay.lines), lay.lines
    assert [ln for ln in lay.lines if ln.endswith("-")] == \
        ["VILLAINESS-", "IN-"]


def test_a_piece_that_fits_beside_its_neighbour_is_not_split_off():
    """The pieces are handed to the wrap spaced apart so it MAY break between
    them. Two that end up on one line are one word again and must be drawn as
    one - VILLAINESS- IN- with a space in it is not a word anybody wrote.

    A box wide enough for most of the line but too short for two of them, so
    the spill runs and still has to fit pieces together."""
    # 140x14, down from 220x20 on 2026-08-26 when Comic Neue became the
    # default face (`fonts/LICENSES.md`). It is narrower, so the old box fitted
    # the whole line and the spill never ran - a fixture that had stopped
    # asking its own question.
    r, lay = _fit("freefloat", text=HYPHENATED, box=(150, 150, 140, 14),
                  page=(400, 600))
    assert lay.spills, "this box must be one the spill actually handles"
    assert lay.lines == ["LITTLE VILLAINESS-IN-", "TRAINING."], lay.lines
    assert not any(" -" in ln or "- " in ln for ln in lay.lines), lay.lines


def test_text_with_nothing_to_break_at_spills_exactly_as_it_did():
    """No dash and no row of dots means nothing to do, and a wall of ordinary
    words must go out onto the artwork the way it always has."""
    r, lay = _fit("freefloat", box=(150, 150, 60, 220), page=(500, 400))
    assert lay.spills
    assert not any(ln.endswith("-") for ln in lay.lines)
    assert " ".join(lay.lines) == LONG, "and all of it goes in"


# ------------------------------------------ and no words at all leave the PAGE

def _sfx_at(x, y, text="CLACK", angle=0.0, page=(300, 300)):
    """A sound effect whose box is hard against the right edge."""
    img = np.full((page[0], page[1], 3), 255, np.uint8)
    pg = Page(image=img, source_path="p.png")
    m = np.zeros(page, np.uint8)
    cv2.rectangle(m, (x, y), (x + 46, y + 34), 255, -1)
    r = TextRegion(id=1, kind="sfx", order=0, dst_text=text,
                   bbox=(x, y, 46, 34), text_mask=m, angle=angle)
    pg.regions = [r]
    return pg


def _reach(lay, cfg):
    """How far the block's ink gets, left and right, allowing for its angle."""
    import math
    from mangatl.typeset import _text_w
    rot = math.radians(float(getattr(lay, "rotate", 0.0) or 0.0))
    c, s = abs(math.cos(rot)), abs(math.sin(rot))
    hh = lay.font_size * 0.6
    half = [((_text_w(lay.font_path or cfg.font_path, lay.font_size, ln) * c
              + 2 * hh * s) / 2.0) for ln in lay.lines]
    return (min(x - w for (x, _), w in zip(lay.line_origins, half)),
            max(x + w for (x, _), w in zip(lay.line_origins, half)))


def test_a_sound_effect_is_never_set_off_the_edge_of_the_page():
    """lee, with CLACK hanging into the black beside the scan: *"a text shoud
    never be set outside of the page like this"*.

    Sliding a block back onto the paper only ever ran on layouts marked as
    LEAVING their box, and a sound effect is never marked that way - the clamp
    is its authority, and the clamp is measured against the effect's own
    footprint, not against the page. So nothing at all was keeping one on."""
    page = _sfx_at(258, 20)
    typeset_page(page, _cfg())
    lay = page.regions[0].layout
    assert lay and lay.lines
    left, right = _reach(lay, _cfg())
    assert right <= 300 + 2, f"it reaches {right:.0f} on a 300px page"
    assert left >= -2, left


def test_a_turned_line_is_measured_turned():
    """A sound effect is drawn on a slant, and a turned line does not occupy
    its own width: once it leans, its HEIGHT starts reaching sideways too, and
    the corner of the box round it is what crosses the margin first.

    A short word is where that bites. Level, `OK!` clears the edge with room
    to spare; stood up at sixty degrees the same word reaches half as far
    again, and measuring it level says there is nothing to do."""
    cfg = _cfg()
    # 278, up from 274, and the reach figures with it: Comic Neue became the
    # default face on 2026-08-26 (`fonts/LICENSES.md`) and sets `OK!` narrower,
    # so at 274 the turned word no longer crossed the edge and the fixture
    # stopped posing its question.
    at = 278                     # level it reaches 297; turned, past 300
    level = TextLayout(lines=["OK!"], font_size=26, leading=1.2,
                       line_origins=[(at, 150)],
                       font_path=default_font_path(), rotate=0.0)
    turned = TextLayout(lines=["OK!"], font_size=26, leading=1.2,
                        line_origins=[(at, 150)],
                        font_path=default_font_path(), rotate=45.0)
    assert keep_on_page(level, cfg, (300, 300)).line_origins == [(at, 150)], \
        "level, it is on the page and nothing should move"
    moved = keep_on_page(turned, cfg, (300, 300)).line_origins
    assert moved != [(at, 150)], "turned, it is over the edge and must come back"
    assert _reach(turned, cfg)[1] <= 300 + 2


def test_speech_well_inside_the_page_is_not_nudged():
    """The pass now runs on every layout, so it has to come to nothing for the
    several thousand regions a chapter that typesets normally has."""
    page = _page_with("bubble", text="HELLO THERE")
    typeset_page(page, _cfg())
    before = list(page.regions[0].layout.line_origins)
    out = keep_on_page(page.regions[0].layout, _cfg(), (300, 300))
    assert out.line_origins == before


# ------------------------------- narrower before it is allowed onto the artwork

NARROW = "I DO NOT KNOW WHY YOU ASK ME TO GO TO THE OLD TOWN AT ALL"


def _lobe(w, h, text=NARROW, page=(560, 460)):
    m = np.zeros(page, np.uint8)
    cv2.ellipse(m, (page[1] // 2, page[0] // 2), (w // 2, h // 2),
                0, 0, 360, 255, -1)
    ys, xs = np.nonzero(m)
    r = TextRegion(id=1, kind="bubble", order=0, dst_text=text,
                   bbox=(int(xs.min()), int(ys.min()),
                         int(xs.max() - xs.min()), int(ys.max() - ys.min())),
                   text_mask=m, bubble_mask=m)
    return r, m


def _without_narrowing(r, m):
    from mangatl import typeset as T
    was = T._narrower_fit
    T._narrower_fit = lambda *a, **k: None
    try:
        r.flagged = None
        return fit_region(r, _cfg(), mask=m), r.flagged
    finally:
        T._narrower_fit = was


def test_a_tall_narrow_balloon_gets_more_lines_rather_than_smaller_type():
    """lee: *"if the text is going out of the text bot it shoud make teh with
    smaller if posible"*. A narrower line IS more lines - the line count is
    what decides how wide a line may be - and the cap on it was taste, which
    is not worth typesetting over somebody's drawing for."""
    # 48x420, down from 70x470 for the same reason: the narrower face fitted
    # the old lobe without needing to narrow the lines at all, so the "without
    # it" side came back a clean fit and there was nothing left to compare.
    r, m = _lobe(52, 390)
    was, was_flag = _without_narrowing(r, m)
    r.flagged = None
    now = fit_region(r, _cfg(), mask=m)

    # Without it the block came out of `_plain_fit` - a wrap into the bounding
    # RECTANGLE, which says so by reporting `fit_ok=False`; the corners of a
    # rectangle drawn round a balloon are outside the balloon, which is the
    # overflow lee was looking at.
    #
    # The flag was read here too. It is not read any more: that path flagged
    # EVERY layout it returned, including the ones at the minimum size that
    # had not been shrunk at all, and the message named a shrink that had not
    # happened. It flags when it actually goes under the floor now, and this
    # fixture does not.
    assert not was.fit_ok, "without it, this balloon fitted anyway"
    assert was_flag is None or "shrunk" not in was_flag, was_flag
    assert now.fit_ok and not r.flagged, "with it, the words go in"
    assert len(now.lines) > len(was.lines), \
        f"{len(was.lines)} -> {len(now.lines)} lines"
    assert now.font_size > was.font_size, \
        f"and BIGGER, not smaller: {was.font_size} -> {now.font_size}pt"


def test_the_whole_translation_still_goes_in():
    r, m = _lobe(70, 470)
    assert " ".join(fit_region(r, _cfg(), mask=m).lines) == NARROW


def test_a_balloon_that_typesets_normally_is_untouched():
    """It is reached only after the ordinary fit and the author's own breaks
    have both failed, so a chapter that typesets normally never comes near it -
    and a nine-line balloon does not start appearing where a four-line one
    used to."""
    r, m = _lobe(240, 240, text="HELLO THERE, WHAT A DAY")
    was, _flag = _without_narrowing(r, m)
    r.flagged = None
    now = fit_region(r, _cfg(), mask=m)
    assert (now.font_size, now.lines) == (was.font_size, was.lines)


def test_a_lobe_with_no_room_at_all_still_falls_through_to_the_old_answer():
    """Sixty pixels tall is not a balloon this sentence goes in at any width.
    The pass has to decline rather than return something worse."""
    r, m = _lobe(100, 60)
    was, _flag = _without_narrowing(r, m)
    r.flagged = None
    now = fit_region(r, _cfg(), mask=m)
    assert (now.font_size, now.lines) == (was.font_size, was.lines)


def test_the_narrower_fit_never_takes_the_spill_s_turn():
    """The order of the two is the whole point, and getting it wrong undid
    the rule this file exists for.

    A box round free text is where the JAPANESE ink was, and Japanese runs
    down the page in a narrow column - so there is nearly always a way to cram
    English into one by stacking a word per line, and the narrower fit finds
    it. That is not typesetting, it is a tower. Put it in front of the spill and
    every piece of outside text on a page becomes one."""
    text = "I DO NOT KNOW WHY YOU ASK ME TO GO TO THE OLD TOWN AT ALL"
    for kind in ("freefloat", "sfx"):
        r, m = _column(kind, text=text, box=(150, 40, 60, 460), page=(560, 460))
        lay = fit_region(r, _cfg(), mask=m)
        assert lay.spills, f"{kind} must still be allowed onto the artwork"
        assert lay.font_size >= _cfg().min_font, f"{kind} shrank instead"
        assert len(lay.lines) <= 12, \
            f"{kind} was stacked into a tower of {len(lay.lines)} lines"


def test_speech_in_the_same_shape_still_gets_the_narrower_fit():
    """A balloon IS a wall, so the same shape gets the opposite answer."""
    text = "I DO NOT KNOW WHY YOU ASK ME TO GO TO THE OLD TOWN AT ALL"
    r, m = _column("bubble", text=text, box=(150, 40, 60, 460), page=(560, 460))
    lay = fit_region(r, _cfg(), mask=m)
    assert not lay.spills and lay.fit_ok, "speech never leaves its balloon"
    assert len(lay.lines) > 9, "and is allowed past the line cap to stay in it"
