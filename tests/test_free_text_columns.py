"""Reading the writing that is typeset straight onto the artwork.

lee sent three screenshots of the last page of his chapter: "exaample it missed
a bunch of pages in teh last page". Two different faults in them, and one cause.

In one, whole passages have NO box at all - a shout down the middle of a splash
page, the vertical captions on the left of another. In the other the boxes exist
but are grossly wrong: box 5 covering a whole panel, box 4 a thin vertical strip
crossing a panel boundary.

The cause is the same for both. Every detector in `classical.py` is
enclosure-first: it looks for a shape - a white blob, a dark outline - that
HOLDS dark glyphs, and takes the inside of that shape as the region. Manga
typesets a large fraction of its text directly onto the drawing, where there is
no shape to find. So that text is either missed outright, or found by accident
when a pale panel happens to enclose it, and then the box is the whole panel.

`read_the_writing` asks the question from the other end: not "what shape is
holding writing" but "which of these marks ARE writing". Marks of ink, stacked
into columns, columns grouped into passages, and the passages filtered on what
separates typesetting from artwork.

These tests pin the parts of that chain that took the most measuring to get
right, and the one setting lee can turn.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import freetext as F
from mangatl.models import Page

H, W = 600, 500
CH = 14                       # a character, in pixels
STROKE = 2                    # how thickly it is drawn


def _glyph(img, x, y, size=CH, stroke=STROKE):
    """A mark shaped like a letter: an outline, not a slab.

    Thinness is what tells typesetting from artwork, so a test fixture made of
    solid blocks would be rejected by the very measure under test - a filled
    square measures 1.0, which is twice the top of the band. A hollow square of
    side s drawn with stroke t measures about 2t/s, so 14 and 2 put it at 0.29,
    in the middle of the range real Japanese lands in.
    """
    cv2.rectangle(img, (x, y), (x + size - 1, y + size - 1), 0, stroke)


def _column(img, x, y0, n=8, pitch=18, size=CH):
    for k in range(n):
        _glyph(img, x, y0 + k * pitch, size)


def _two_columns(gap=25, n=8):
    """Two columns of writing on bare paper, a known gap apart.

    No balloon, no panel, nothing enclosing them - which is the whole point.
    An enclosure-first detector has nothing to find here.
    """
    img = np.full((H, W), 255, np.uint8)
    x0 = 120
    _column(img, x0, 100, n)
    _column(img, x0 + CH + gap, 100, n)
    return img


def _blocks(img, cfg=None):
    _, _, blocks = F.column_blocks(img, cfg or F.ColumnConfig())
    return blocks


# ------------------------------------------- there is no setting to turn now

def test_splitting_boxes_by_distance_is_not_a_setting_any_more():
    """lee: "remove the slider and teh whole split box by distance".

    The slider set how wide a run of blank paper ended one block of writing.
    It was the wrong question to put to him: he does not know, page by page,
    how far apart the columns of a shout are printed, and neither did the
    slider help - on his own chapter seven pages in nine gave the same boxes at
    every value from 1.0 to 4.0. What he wants is stated once and for all: a
    body of writing is ONE box.

    A join distance still exists inside the reader, because page 10 of his
    chapter has seven separate captions on one drawing and they must stay seven
    boxes. It is a constant now, measured here rather than asked of him.
    """
    from mangatl import project

    assert not hasattr(F.ColumnConfig, "with_gap")
    fresh = project.Project(None, str(_tmp_project()))
    assert "split_gap" not in fresh.settings


def test_nothing_in_the_editor_still_asks_for_a_split_gap():
    """A removed setting has to leave the panel too, or lee sees a slider that
    saves a value nothing reads - which is exactly the bug he reported."""
    import pathlib
    root = pathlib.Path(F.__file__).resolve().parent.parent / "static"
    for name in ("editor.html", "js/project.js"):
        text = (root / name).read_text(encoding="utf-8")
        assert "split_gap" not in text, name
        assert "sgv" not in text, name


def test_the_writing_is_read_before_the_stroke_pass():
    """Order is the whole fix, so it is pinned in the source.

    `detect_free_text` groups ink by closing it with a 13-pixel brush, which is
    narrower than the paper between two columns of Japanese, so it hands back
    one box per column. Running first, it took lee's shout three boxes wide and
    the reader - which knows those columns are one passage - then found the
    ground taken and stood aside. Reading first puts one box round the whole
    body of writing and leaves the stroke pass the crumbs.
    """
    import inspect
    from mangatl import project

    # Find text is TWO methods since the AI option arrived: `detect` chooses
    # which way to get boxes, `_detect_measured` is the measuring way. Read
    # both, or a source check silently stops covering the half that moved.
    src = (inspect.getsource(project.Project.detect)
           + inspect.getsource(project.Project._detect_measured))
    calls = [ln.strip() for ln in src.splitlines()
             if "_ft.read_the_writing(" in ln or "_ft.detect_free_text(" in ln
             or "_ft.absorb_fragments(" in ln]
    assert len(calls) == 3, calls
    assert "read_the_writing" in calls[0], calls
    assert "detect_free_text" in calls[1], calls
    assert "absorb_fragments" in calls[2], calls


def _tmp_project():
    import tempfile, pathlib
    return pathlib.Path(tempfile.mkdtemp()) / "proj"


# ------------------------------------------------- what counts as writing

def test_writing_on_bare_paper_is_found_at_all():
    """The miss lee reported, in its simplest form."""
    blocks = _blocks(_two_columns())
    assert len(blocks) == 1
    assert len(blocks[0]["ids"]) == 16


def test_a_solid_blob_is_not_writing():
    """The embroidery on the dress on page 8, which measured 0.604.

    Filled marks the size of a character, stacked as neatly as a column of
    kanji - every test but thinness passes them.
    """
    img = np.full((H, W), 255, np.uint8)
    for x in (120, 154):
        for k in range(8):
            y = 100 + k * 18
            cv2.rectangle(img, (x, y), (x + CH - 1, y + CH - 1), 0, -1)
    assert _blocks(img) == []


def test_a_hairline_is_not_writing():
    """Two strands of the girl's hair on page 38, at 0.165 and 0.183.

    The band has to reject on BOTH sides. An earlier version tested only that
    marks were not too fat, and these went straight through it.
    """
    img = np.full((H, W), 255, np.uint8)
    for x in (120, 154):
        for k in range(8):
            y = 100 + k * 18
            cv2.rectangle(img, (x, y), (x + CH - 1, y + CH - 1), 0, 1)
    blocks = _blocks(img)
    if blocks:                       # measured, so say what it measured
        assert blocks[0]["stroke"] < F.ColumnConfig.min_stroke, blocks[0]
    assert blocks == []


def test_the_thinness_of_real_typesetting_lands_inside_the_band():
    """The fixture is only honest if it sits where real Japanese sits.

    Measured over nineteen hand-labelled blocks off lee's pages, true passages
    ran 0.212 to 0.423 - across 12-pixel captions and 60-pixel shouts alike.
    """
    blocks = _blocks(_two_columns())
    assert 0.212 <= blocks[0]["stroke"] <= 0.423, blocks[0]["stroke"]


def test_a_stray_pair_of_marks_is_not_a_passage():
    """Below `min_glyphs` there is not enough to be sure, and a wrong box on
    the artwork costs more than a missed two-character aside."""
    img = np.full((H, W), 255, np.uint8)
    _column(img, 120, 100, n=2)
    assert _blocks(img) == []


# --------------------------------------------------- columns, not fragments

def test_a_column_is_found_whole_however_the_marks_are_ordered():
    """The stacker used to grow columns greedily and never look back.

    Marks arrive in x order, so the third character of a column can be seen
    before the second, land too far below the head of the column to join it,
    and start a rival column four pixels underneath. On lee's splash page that
    left one shout in eighteen fragments, every one too short and too ragged to
    read as writing. Merging is order-free now, so a column comes back whole.
    """
    img = np.full((H, W), 255, np.uint8)
    _column(img, 120, 100, n=8)
    cfg = F.ColumnConfig()
    lab, marks = F._marks(img, cfg)
    by_id = {m[0]: m for m in marks}
    shuffled = [marks[i] for i in (4, 0, 7, 2, 5, 1, 6, 3)]
    cols = F._stack(shuffled, by_id, cfg)
    assert len(cols) == 1, [(c["y0"], c["y1"]) for c in cols]
    assert len(cols[0]["ids"]) == 8


def _as_column(marks):
    """The marks, handed to `_tidy` as one column, however ragged they are.

    Put through `_stack` instead, a wandering trail would be broken into
    several columns before `_tidy` ever saw it, and the test would pass for the
    wrong reason. This asks `_tidy` the question directly.
    """
    xs = [(m[1], m[1] + m[3]) for m in marks]
    return dict(ids=[m[0] for m in marks],
                x0=min(a for a, _ in xs), x1=max(b for _, b in xs))


def test_a_trail_of_marks_that_does_not_run_straight_is_not_a_column():
    """Writing is set on a LINE, and artwork is not. Real columns wander by
    0.05 to 0.19 of their own width; stipple and hair by 0.26 and up.

    The obvious measure here is PITCH - characters come at a regular spacing,
    artwork does not - and it was measured on lee's pages and thrown out. Real
    columns came in at 0.40, 0.47, 0.51, 0.55, 0.70 and 0.79, because a ruby
    mark between two kanji halves one gap and a missed character doubles the
    next. Rejecting on it threw away nearly every true column on the page.
    """
    cfg = F.ColumnConfig()

    wavy = np.full((H, W), 255, np.uint8)
    for k in range(8):
        _glyph(wavy, 120 + (11 * k) % 33, 100 + k * 18)
    lab, marks = F._marks(wavy, cfg)
    assert len(marks) == 8
    assert not F._tidy(_as_column(marks), {m[0]: m for m in marks}, cfg)

    # the control: the same eight marks in a line ARE a column, so the test
    # above is failing on the wandering and not on anything else
    straight = np.full((H, W), 255, np.uint8)
    _column(straight, 120, 100, n=8)
    lab, marks = F._marks(straight, cfg)
    assert F._tidy(_as_column(marks), {m[0]: m for m in marks}, cfg)


# -------------------------------------------- one passage, not three boxes

def _mixed_column(img, x, y0):
    """A column of Japanese as it is actually printed: big characters with
    small ones hung among them - a run of dots, a small っ, a ruby mark.

    The sizes are lee's own, off page 38: three dots and a small っ measuring
    10 pixels beside characters of 36 and 46.
    """
    y = y0
    for size in (8, 8, 8, 34, 44, 44):
        _glyph(img, x + (44 - size) // 2, y, size)
        y += size + 8


def test_a_column_carrying_small_marks_is_still_writing():
    """lee's page 38: the shout 私…っ / 今日から / 悪女になります!! came back
    with a box round two columns and 私…っ left outside it.

    The rejected column measured [10, 10, 10, 36, 46, 46] - three dots and a
    small っ beside three full characters - and its spread over ALL of that is
    0.633, just past the 0.60 limit that throws artwork away. Over the
    full-size characters alone it is 0.11. A column of writing is not one size,
    and asking it to be one cost lee a third of his shout.
    """
    img = np.full((H, W), 255, np.uint8)
    _mixed_column(img, 120, 100)
    cfg = F.ColumnConfig()
    lab, marks = F._marks(img, cfg)
    assert len(marks) == 6
    by_id = {m[0]: m for m in marks}
    col = _as_column(marks)
    assert F._tidy(col, by_id, cfg)

    # the control: measured over every mark, as it used to be, this same
    # column IS rejected - so the test above is passing on the new rule and
    # not because the fixture happens to be tidy anyway
    class _Old(F.ColumnConfig):
        body_size = 0.0
    assert not F._tidy(col, by_id, _Old())


def test_ruby_belongs_to_the_characters_it_is_printed_beside():
    """Page 39: the あくじょ ruby stood in its own column at size 17 next to a
    36-pixel body, and 36/17 = 2.1 broke the old one-passage-one-size rule of
    1.75. So the shout was boxed without its ruby, and the ruby came back as a
    box of its own - which is two boxes over one body of writing.

    Ruby is set at about half the body size, so the rule has to reach that far.
    It still stops well short of a caption beside a shout, which on his pages
    runs three to five times.
    """
    img = np.full((H, W), 255, np.uint8)
    for k in range(7):                     # the body: 34 pixels a character
        _glyph(img, 200, 60 + k * 38, 30, stroke=4)
    for k in range(13):                    # its ruby, half size, beside it
        _glyph(img, 170, 60 + k * 20, 14, stroke=2)
    blocks = _blocks(img)
    assert len(blocks) == 1, [(b["x0"], b["x1"]) for b in blocks]
    assert blocks[0]["x0"] <= 170 and blocks[0]["x1"] >= 230

    class _Old(F.ColumnConfig):
        size_ratio = 1.75
    assert len(_blocks(img, _Old())) == 2


def _region(bbox, kind="freefloat", mask=None, rid=0):
    from mangatl.models import TextRegion
    return TextRegion(id=rid, bbox=bbox, kind=kind, bubble_mask=mask)


def test_a_crumb_left_inside_a_passage_is_swallowed():
    """lee: "make the box be one text ... shoud be one box for example".

    Reading the writing first puts one box round the whole shout, but the
    enclosure-first detectors have already been over the page and they leave
    crumbs sitting inside it: on page 39 a box round the single kanji 国, whose
    white counter looked like a tiny balloon, and on page 38 boxes round 悪 and
    round the きょう ruby. One body of writing, four boxes.
    """
    passage = _region((78, 502, 180, 463), rid=0)
    crumb = _region((203, 638, 25, 25), kind="narration", rid=1)
    kept = F.absorb_fragments([passage, crumb])
    assert [r.id for r in kept] == [0]


def test_what_stands_beside_a_passage_is_left_alone():
    """Two conditions, and both are load-bearing. Overlap alone would eat a
    balloon that happened to fall inside a passage's rectangle; size alone
    would eat the caption standing next to a shout."""
    passage = _region((78, 502, 180, 463), rid=0)
    neighbour = _region((270, 520, 30, 200), rid=1)        # tiny, but outside
    big = _region((90, 520, 150, 400), rid=2)              # inside, not small
    kept = F.absorb_fragments([passage, neighbour, big])
    assert sorted(r.id for r in kept) == [0, 1, 2]


def test_only_a_body_of_writing_may_swallow_anything():
    """A balloon is not a passage. It holds one thing and it is entitled to
    hold something small beside it - a section of a two-part balloon, an
    あっ！ under a sentence - so a balloon region never eats its neighbours."""
    balloon = _region((78, 502, 180, 463), kind="bubble",
                      mask=np.ones((463, 180), np.uint8), rid=0)
    inside = _region((203, 638, 25, 25), kind="bubble", rid=1)
    kept = F.absorb_fragments([balloon, inside])
    assert sorted(r.id for r in kept) == [0, 1]


# ------------------------------------------------------- the panel guard

def test_a_block_running_across_a_panel_border_is_thrown_away():
    """No passage of writing crosses a gutter, and one that appears to has
    stacked two unrelated things together.

    On page 8 a sprig of embroidery on a dress in the upper panel stacked
    straight down into the speech below it and came back as one tall box
    across the gutter between them.
    """
    box = (100, 250, 40, 200)                     # straddles the seam at 300
    frames = [(0, 0, 500, 300), (0, 310, 500, 290)]
    assert F._straddles(box, frames)
    # a box sitting wholly inside one panel does not straddle
    assert not F._straddles((100, 60, 40, 120), frames)
    # nor does one on a page where no panels were found
    assert not F._straddles(box, [])


def test_a_panel_corner_does_not_count_as_straddling():
    """Panel finding is approximate by design, so the guard is deliberately
    blunt: two panels have to hold a fifth of the box each.

    A tall block that pokes eight pixels over the seam gives the panel above it
    only 0.08 of itself, so it is left alone - the box is plainly the lower
    panel's, and a passage should not be thrown away over a rounded corner or a
    panel edge found a few pixels out.
    """
    frames = [(0, 0, 500, 300), (0, 310, 500, 290)]
    assert not F._straddles((100, 292, 40, 100), frames)


# ------------------------------------------------------ the whole pass

def test_the_pass_leaves_alone_what_a_balloon_finder_already_took():
    """It adds to the boxes, it does not duplicate them."""
    img = _two_columns()
    page = Page(image=cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    fresh = F.read_the_writing(page, [])
    assert len(fresh) == 1
    already = F.read_the_writing(page, fresh)
    assert already == []


def test_what_it_hands_back_survives_a_save_and_a_load():
    """Writing on bare art has no balloon outline, so its region must carry a
    rectangle and NO mask - store anything else and the reload builds a
    pretend bubble out of it and typesets the English to the wrong shape."""
    from mangatl.project import region_record, region_from_record

    img = _two_columns()
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    r = F.read_the_writing(Page(image=bgr), [])[0]
    r.id = 0
    assert r.bubble_mask is None
    assert r.kind == "freefloat"
    back = region_from_record(region_record(r), bgr)
    assert back.bubble_mask is None
    assert back.bbox == r.bbox


# ------------------------- seeing the same writing twice

def test_a_stroke_block_sitting_on_writing_already_read_is_dropped():
    """The two passes look at the same page, so they can find the same text.

    The stroke pass is deliberately shown the untouched page - blanking the
    reader's writing out first changes how it groups the ink that is left,
    which on lee's page 10 closed two toy rabbits into a text box. So it is
    left to find whatever it finds, and what it hands back is compared with
    the reader's boxes afterwards."""
    read = _region((80, 500, 180, 460), rid=0)
    again = _region((90, 520, 150, 400), rid=1)     # the same writing, re-found
    kept = F.not_already_read([again], [read])
    assert kept == []


def test_a_stroke_block_standing_clear_of_the_reading_is_kept():
    read = _region((80, 500, 180, 460), rid=0)
    elsewhere = _region((600, 120, 150, 200), rid=1)
    assert [r.id for r in F.not_already_read([elsewhere], [read])] == [1]


def test_the_stroke_pass_is_shown_the_page_before_the_reader_touched_it():
    """`avoid` must be the boxes as they stood BEFORE read_the_writing added
    to them, or the stroke pass regroups the leftover ink and invents boxes
    round drawings."""
    import inspect
    from mangatl import project
    # Find text is TWO methods since the AI option arrived: `detect` chooses
    # which way to get boxes, `_detect_measured` is the measuring way. Read
    # both, or a source check silently stops covering the half that moved.
    src = (inspect.getsource(project.Project.detect)
           + inspect.getsource(project.Project._detect_measured))
    lines = [ln.strip() for ln in src.splitlines()]
    made = next(i for i, ln in enumerate(lines) if ln == "enclosed = list(found)")
    read = next(i for i, ln in enumerate(lines)
                if ln.startswith("found += _ft.read_the_writing("))
    assert made < read, "the pre-reader boxes are captured too late"
    assert any("avoid=enclosed" in ln for ln in lines)
    assert any("_ft.not_already_read(" in ln for ln in lines)


# ------------------------------------------- no passage crosses a panel rule

BIG = 20                      # a character, where the rule fixtures need room
PITCH = 24


def _ruled_page(bar_y=200, decor=3, above=True):
    """A panel border across the page, embroidery one side of it, speech the
    other.

    This is lee's page 8 in miniature. A sprig on a dress in the panel above
    stands directly over 落ちてたわよ in the panel below, close enough and
    tidy enough to stack into the same column, and the box came back reaching
    up out of the speech and into the dress.
    """
    img = np.full((H, W), 255, np.uint8)
    cv2.rectangle(img, (20, bar_y), (W - 20, bar_y + 5), 0, -1)
    sprig, speech = (bar_y - 28, bar_y + 12) if above else (bar_y + 12,
                                                            bar_y - 28)
    step = -PITCH if above else PITCH
    for k in range(decor):
        _glyph(img, 240, sprig + k * step, BIG)
    _column(img, 240, speech, n=8, pitch=PITCH if above else -PITCH, size=BIG)
    return img


def test_the_sprig_and_the_speech_are_one_column_with_no_rule_between_them():
    """The fixture has to be a real trap or the cut proves nothing: rub the
    border out and the two DO stack into one passage."""
    img = _ruled_page()
    img[195:212, :] = 255
    blocks = _blocks(img)
    assert blocks and min(b["y0"] for b in blocks) < 195


def test_a_passage_is_cut_where_a_panel_rule_crosses_it():
    blocks = _blocks(_ruled_page())
    assert blocks, "the speech was lost entirely"
    assert min(b["y0"] for b in blocks) > 200


def test_the_writing_on_the_far_side_of_the_rule_is_all_still_there():
    b = max(_blocks(_ruled_page()), key=lambda b: len(b["ids"]))
    assert len(b["ids"]) >= 8


def test_the_cut_keeps_whichever_side_holds_more_of_the_writing():
    """The speech is below the rule on lee's page. Nothing in the rule says
    which side that is, and the test says so by putting it above."""
    blocks = _blocks(_ruled_page(above=False))
    assert blocks and max(b["y1"] for b in blocks) < 200


def test_a_short_bar_is_not_a_panel_rule():
    """A rule runs from one side of the frame to the other. A dash, an
    underline, the top of a drawn box - writing may sit on either side of
    those."""
    img = _ruled_page()
    img[195:212, :] = 255
    cv2.rectangle(img, (215, 200), (285, 205), 0, -1)
    assert min(b["y0"] for b in _blocks(img)) < 195


# --------------------------------- and the two things the cut refuses to do

def _column_page(x=240, y0=100, n=8, pitch=28, size=BIG):
    """A passage of writing with room between the characters for a rule to be
    drawn in without touching them."""
    img = np.full((H, W), 255, np.uint8)
    for k in range(n):
        _glyph(img, x, y0 + k * pitch, size)
    return img


def _bar(img, y, x0=20, x1=W - 20, thick=4):
    cv2.rectangle(img, (x0, y), (x1, y + thick - 1), 0, -1)


def test_a_cut_that_would_leave_almost_nothing_leaves_the_passage_alone():
    """Two rules with one character between them. Cutting at the first keeps
    everything below it, cutting at the second keeps everything above, and what
    survives both is a single mark - which is not a passage of writing, it is
    the wreck of one. Losing a box is worse than a box a little too tall, so
    nothing happens.
    """
    img = _column_page(n=7)
    _bar(img, 178)                # after the third character
    _bar(img, 206)                # after the fourth
    b = max(_blocks(img), key=lambda b: len(b["ids"]))
    assert len(b["ids"]) == 7
    assert b["y0"] < 178 and b["y1"] > 206


def test_a_rule_that_only_clips_the_edge_of_a_passage_does_not_cut_it():
    """The bar has to run right across the writing. One that stops halfway
    through the column is something drawn beside it - the top of a signboard,
    the edge of a table - and the writing carries on past it.
    """
    img = _column_page()
    _bar(img, 178, x0=60, x1=250)          # the column stands at 240..259
    b = max(_blocks(img), key=lambda b: len(b["ids"]))
    assert len(b["ids"]) == 8
    assert b["y0"] < 178 and b["y1"] > 178
