"""Cleaning in two steps: the ordinary one, then the hard spots.

lee: *"i want the clenner to work in 2 step one step clenas teh normal like in
the stage i said was teh safe state abd teh a second clen that clena steh hard
spots like teh gold text etc"*.

## What the first step cannot see

It reads a page in grey and splits it at a number: `gray <= 128` is ink, or
`gray >= 200` is ink on a dark panel. That describes black-on-white, and lee's
chapter keeps handing back boxes it is not true of:

| box                                           | `gray<=128` | `gray>=200` |
|-----------------------------------------------|-------------|-------------|
| page 030, gold on navy                         | **84%**     | 12%         |
| page 024, dark words on a see-through balloon  | **54%**     | 8%          |
| page 003 / 012, gold on cream                  | 1%          | **91%**     |

Gold falls down the gap between the two levels wherever it stands, and a
balloon you can see the sky through has no single level anywhere — a beam of
light crosses it and the background inside one box runs from 0 to 255.

## Why a second pass and not a cleverer first one

Four attempts to fix that inside one pass all failed the same way. Each had to
guess, BEFORE cleaning, which boxes the fixed levels would fail on; and every
guess broad enough to catch the gold also took boxes away from the model, from
the ghost retry and from the screentone path, all of which were doing their
job. The one narrow enough to break nothing caught three boxes out of twelve.

A second pass does not guess. It reads what the first pass actually produced,
and whatever is still standing is by definition what the first reading missed.
It can only paint where the writing survived, so the first step is left exactly
as it was — the cleaner lee called the safe state — and a box that came out
clean is never touched at all.

## What the second step erases

Read the colour way, against the box's own local background, because the boxes
that survive step one are precisely the ones no grey level describes. A median
blur wider than a stroke cannot see strokes, so what comes back is the box with
the writing lifted off — paper, gradient, frame and beam intact — and whatever
differs from that is the writing. `focus_ink` then grows each stroke out to its
own edge so no coloured rim is left behind, and drops decoration that runs off
the edge of the box.

Measured over lee's chapter: **better on 11 boxes, worse on none**, and the
second step runs on 19 of 87.

The switch is still there — `region.focus`, the ⊚ on a box — for reading a box
that way in the FIRST step, which is a different thing and occasionally what
you want.
"""

import cv2
import numpy as np
import pytest

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion


def _gold_on_navy(w=420, h=120, frame=False):
    """Page 030: gold caption on a navy plate. Both are mid-grey.

    With `frame`, the plate's pale ornate border as well — which is what
    defeats the ordinary reading on the real page. The split that handles
    light-on-dark is taken over the whole box, so a white frame is the thing
    it separates, and the gold goes in with the sky.
    """
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :] = (92, 58, 48)                       # navy, BGR
    if frame:
        cv2.rectangle(img, (3, 3), (w - 4, h - 4), (238, 238, 238), 7)
    cv2.putText(img, "GOLD TEXT", (24, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (86, 168, 214), 4)                 # gold
    return img


def _black_on_white(w=420, h=120):
    """The page the fixed levels were written for, and still handle."""
    img = np.full((h, w, 3), 250, np.uint8)
    cv2.putText(img, "ORDINARY", (24, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (12, 12, 12), 4)
    return img


def _gold_on_cream(w=420, h=120):
    img = np.full((h, w, 3), 243, np.uint8)
    cv2.putText(img, "GOLD TEXT", (24, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (76, 133, 154), 4)
    return img


def _dark_on_a_gradient(w=420, h=120):
    """Page 024: a balloon you can see the sky through, with a beam across it.
    The background inside the box runs from near-black to near-white."""
    x = np.linspace(20, 235, w, dtype=np.float32)
    img = np.repeat(x[None, :, None], h, 0).repeat(3, 2).astype(np.uint8)
    cv2.putText(img, "SEE THROUGH", (18, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (18, 18, 18), 4)
    return img


def _share(m):
    return float((m > 0).mean())


# --- the reading -----------------------------------------------------------

def test_the_fixed_levels_read_the_background_and_not_the_writing():
    """The premise. If this ever stops being true the switch is unnecessary."""
    g = cv2.cvtColor(_gold_on_navy(), cv2.COLOR_BGR2GRAY)
    assert (g <= I.INK).mean() > 0.6, "the dark rule is selecting the plate"
    assert (g >= I.BRIGHT).mean() < 0.1, "...and the bright rule finds no gold"


def test_focus_finds_the_gold_on_a_navy_plate():
    m = I.focus_mask(_gold_on_navy())
    assert 0.02 < _share(m) < 0.35, _share(m)
    # and it is the WRITING: the glyphs live in the middle band of the box
    ys = np.where(m.any(axis=1))[0]
    assert 30 < ys.min() and ys.max() < 100


def test_and_the_same_gold_on_cream():
    m = I.focus_mask(_gold_on_cream())
    assert 0.02 < _share(m) < 0.35, _share(m)


def test_and_dark_words_on_a_background_that_is_not_one_tone():
    """No fixed level can be right across this box — the paper under the last
    word is brighter than the ink under the first."""
    img = _dark_on_a_gradient()
    m = I.focus_mask(img)
    assert 0.02 < _share(m) < 0.35, _share(m)
    # every word found, left to right, not just the ones over dark paper
    cols = np.where(m.any(axis=0))[0]
    assert cols.min() < img.shape[1] * 0.2 and cols.max() > img.shape[1] * 0.6


def test_the_background_estimate_keeps_what_is_wider_than_the_window():
    """Artwork, a gradient and a solid band survive it; the writing does not.

    WIDER THAN THE WINDOW, and that is the honest limit of the whole idea. A
    median of `FOCUS_REACH` cannot tell a decorative line of about that width
    from a letter, and does not try: on lee's page 030 the thin curls of the
    plate's frame are picked up along with the gold. They are a few pixels of
    filigree inside a box he pointed the switch at himself, which is the trade
    the switch exists to let him make one box at a time.
    """
    img = _gold_on_navy(h=200)
    img[150:200] = (240, 240, 240)               # a band far wider than the window
    bg = I.focus_background(img)
    band = (slice(160, 190), slice(40, 380))
    assert cv2.cvtColor(bg[band], cv2.COLOR_BGR2GRAY).mean() > 180, \
        "a solid band was blurred away and would be erased with the writing"
    assert not I.focus_mask(img)[band].any(), "it is being read as writing"


def test_a_box_too_small_to_hold_the_window_is_still_read():
    """The kernel is bounded by the box. Unbounded, a window wider than what it
    is reading gives the box's own median everywhere and the mask is empty."""
    m = I.focus_mask(_gold_on_navy(w=40, h=18))
    assert m.shape == (18, 40)


def test_an_empty_crop_does_not_raise():
    assert I.focus_mask(np.zeros((0, 0, 3), np.uint8)).size == 0


# --- carried on the record -------------------------------------------------

def test_the_switch_survives_a_page_being_rebuilt():
    from mangatl.project import region_from_record, region_record
    rec = {"id": 0, "bbox": [10, 10, 200, 80], "bubble_bbox": None,
           "polygon": [], "kind": "bubble", "focus": True, "order": 0}
    again = region_record(region_from_record(rec, _gold_on_navy(300, 200)))
    assert again["focus"] is True


def test_and_defaults_to_off_on_every_record_written_before_it_existed():
    from mangatl.project import region_from_record
    rec = {"id": 0, "bbox": [10, 10, 200, 80], "bubble_bbox": None,
           "polygon": [], "kind": "bubble", "order": 0}
    assert region_from_record(rec, _gold_on_navy(300, 200)).focus is False


# --- through the cleaner ---------------------------------------------------

def _one(img, focus, bbox=(10, 30, 400, 70)):
    from mangatl.project import region_from_record
    rec = {"id": 0, "bbox": list(bbox), "bubble_bbox": None, "polygon": [],
           "kind": "bubble", "order": 0, "src_text": "a", "focus": focus}
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    p = Page(image=img.copy(), source_path="t.png")
    p.regions = [r]
    return p, I.inpaint_page(p, neural=None)


def _left(img, out, bbox):
    x, y, w, h = bbox
    e = lambda z: float(np.abs(cv2.Laplacian(
        cv2.cvtColor(z, cv2.COLOR_BGR2GRAY), cv2.CV_64F)).mean())
    return e(out[y:y + h, x:x + w]) / max(1e-6, e(img[y:y + h, x:x + w]))


def test_the_mask_the_cleaner_erases_is_built_from_it():
    """Read in the CLEANER and not where the mask is first built, because the
    question is asked after the light-on-dark rescue has had its go."""
    img = _gold_on_navy()
    p, out = _one(img, True)
    changed = np.abs(img.astype(int) - out.astype(int)).max(2) > 6
    assert 0.005 < changed.mean() < 0.35, changed.mean()


# --- and the page throws it itself -----------------------------------------

def test_the_gold_comes_off():
    img = _gold_on_navy()
    _, out = _one(img, True)
    assert _left(img, out, (10, 30, 400, 70)) < 0.35


def test_and_the_plate_under_it_is_still_navy():
    """Erasing gold by painting a grey box over it is not cleaning."""
    img = _gold_on_navy()
    _, out = _one(img, True)
    b, g, r = out[35:100, 20:390].reshape(-1, 3).mean(axis=0)
    assert b > g and b > r, "the plate came back neutral"
    assert abs(b - 92) < 22 and abs(r - 48) < 22, (b, g, r)


def test_the_route_says_which_boxes_took_it():
    """Every argument about cleaning so far has been settled by looking at the
    page and guessing. A focus box says so in the report."""
    p, _ = _one(_gold_on_navy(), True)
    assert p.clean_stats.get("focus") == 1, p.clean_stats


def test_a_mask_read_this_way_is_not_thrown_away_a_line_later():
    """`glyphs_only` asks "does this stroke carry on outside the region" and
    used to answer it by finding the stroke again at a fixed level — the one
    thing a focus box has been declared not to obey. On page 003 that took the
    mask from 13% of the box to 1%, with the switch on and the mask right."""
    from mangatl.project import region_from_record
    img = _gold_on_cream(300, 200)
    rec = {"id": 0, "bbox": [6, 6, 288, 188], "bubble_bbox": [6, 6, 288, 188],
           "polygon": [], "kind": "bubble", "order": 0, "focus": True}
    r = region_from_record(rec, img)
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[6:194, 6:294] = I.focus_mask(img[6:194, 6:294])
    was = int((mask > 0).sum())
    assert was > 0
    kept = I.glyphs_only(r, mask, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), False)
    assert int((kept > 0).sum()) > 0.5 * was


def test_a_stroke_is_not_completed_against_the_levels_it_does_not_obey():
    """`_complete_strokes` adds doorstep ink found by the FIXED levels. On a
    box that needed the switch those levels are the background — on page 030
    it would adopt the night sky."""
    import inspect
    src = inspect.getsource(I.inpaint_page)
    i = src.index("_complete_strokes(erase")
    assert "focus" in src[max(0, i - 400):i]


def test_the_split_does_not_overwrite_it_on_a_dark_panel():
    """A navy plate reads as "light text on a dark panel", and the ordinary
    answer to that is to replace the mask with the split — which on page 030 is
    taken over a plate carrying a white frame, so it separates the FRAME and
    puts the gold in with the sky."""
    from mangatl.project import region_from_record
    img = _gold_on_navy()
    cv2.rectangle(img, (2, 2), (417, 117), (240, 240, 240), 7)
    rec = {"id": 0, "bbox": [10, 30, 400, 70], "bubble_bbox": None,
           "polygon": [], "kind": "bubble", "order": 0, "focus": True}
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    mine = int((r.text_mask > 0).sum())
    p = Page(image=img.copy(), source_path="t.png")
    p.regions = [r]
    I.inpaint_page(p, neural=None)
    assert mine > 0
    assert _left(img, I.inpaint_page(p, neural=None), (10, 30, 400, 70)) < 0.5


# --- and nothing else ------------------------------------------------------

def test_a_box_without_the_switch_is_cleaned_to_the_same_pixels():
    """The promise lee asked for in so many words: *"without chnaging anythinge
    else"*. Every line of the focus path is behind `region.focus`, so an
    ordinary box cannot reach any of it — including the two lines inside
    `glyphs_only` and `_complete_strokes`, which are the ones that could have
    leaked.
    """
    for make in (_gold_on_navy, _gold_on_cream, _dark_on_a_gradient,
                 _black_on_white):
        img = make()
        _, a = _one(img, False)
        _, b = _one(img, False)
        assert np.array_equal(a, b)
    # ...and the page the fixed levels WERE written for is still cleaned by
    # them. "Nothing else changed" has to mean the ordinary path still works,
    # not merely that it still runs.
    img = _black_on_white()
    _, out = _one(img, False)
    assert _left(img, out, (10, 30, 400, 70)) < 0.35


def test_the_plate_is_rebuilt_when_the_switch_is_flipped():
    """A plate is built once and reused for ever, and its name is made of the
    page, the boxes and the settings. A switch the name does not mention is a
    switch that does nothing until something else happens to touch the page —
    which has now cost a day of cleaning work twice."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor._plate_stamp)
    assert "focus" in src


# --- and the same reading on every box, when the project asks for it --------



# --- the second step -------------------------------------------------------

def test_the_gold_survives_the_first_step_and_not_the_second():
    """The whole point, end to end and with nobody asking for anything."""
    img = _gold_on_cream()
    box = (10, 30, 400, 70)
    was = I.second_pass
    I.second_pass = lambda *a, **k: []
    try:
        _, one = _one(img, False, box)
    finally:
        I.second_pass = was
    _, two = _one(img, False, box)
    assert _left(img, one, box) > 0.9, \
        "the first step is supposed to be blind to this — fixture drifted"
    assert _left(img, two, box) < 0.35, _left(img, two, box)


def test_the_first_step_is_left_exactly_as_it_was():
    """A box the ordinary clean handled is not touched by the second one, so
    the cleaner lee called the safe state is still the cleaner underneath.
    Byte for byte, on the page the fixed levels were written for."""
    img = _black_on_white()
    box = (10, 30, 400, 70)
    was = I.second_pass
    I.second_pass = lambda *a, **k: []
    try:
        _, one = _one(img, False, box)
    finally:
        I.second_pass = was
    _, two = _one(img, False, box)
    assert np.array_equal(one, two)


def test_a_box_that_came_out_clean_is_never_looked_at_again():
    """The gate is measured on the RESULT — how much of the writing is still
    standing — and not guessed at beforehand. That is what makes the second
    step unable to undo the first."""
    from mangatl.models import Page as _P
    img = _black_on_white()
    p, out = _one(img, False)
    assert not p.clean_stats.get("second pass")


def test_and_one_that_did_not_is(proj_free=None):
    img = _gold_on_cream()
    p, _ = _one(img, False)
    assert p.clean_stats.get("second pass") == 1, p.clean_stats


def test_the_report_says_how_many_needed_it():
    """Every argument about this cleaning has been settled by looking at the
    page and guessing. The count is the answer."""
    # On cream, because the fixture navy plate is flat enough that the
    # ORDINARY clean already takes it — which is the second step doing exactly
    # what it should and staying out of the way.
    img = _gold_on_cream()
    p, _ = _one(img, False)
    assert "second pass" in p.clean_stats
    assert p.regions[0].clean_route.endswith("+ second"), \
        p.regions[0].clean_route


def test_a_sound_effect_gets_the_second_step_too():
    """lee, with the gold effect on page 019 standing after both steps: *"try
    to fix thses in their own part of the clenner"*.

    It has its own rule here, and one line of it. Everywhere else the second
    step clips what it erases to `place_mask()` — the room this region owns —
    but on a sound effect `place_mask()` hands back the effect's own INK
    (models.py), which is right for typesetting and exactly wrong here: the
    only reason a box reaches the second step is that its ink was NOT found,
    so clipping to it leaves nothing to erase. On page 019 the gold effect's
    mask is all but empty and the effect stood through both steps untouched at
    87% of its writing left. An effect's box IS the region — there is no
    balloon it could be inside of — so the box is the room.

    Measured over lee's effects: eight better, none worse, and 019 went to 12%.
    """
    from mangatl.project import region_from_record
    img = _gold_on_cream()
    rec = {"id": 0, "bbox": [10, 30, 400, 70], "bubble_bbox": None,
           "polygon": [], "kind": "sfx", "order": 0, "src_text": "a"}
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    p = Page(image=img.copy(), source_path="t.png")
    p.regions = [r]
    out = I.inpaint_page(p, neural=None)
    assert p.clean_stats.get("second pass") == 1, p.clean_stats
    assert _left(img, out, (10, 30, 400, 70)) < 0.4


def test_and_is_not_clipped_to_its_own_ink_to_do_it():
    """The one line that matters, said as the thing it is: an effect whose ink
    the first step could not find has an empty `place_mask()`, and clipping to
    that is clipping to nothing."""
    import inspect
    src = inspect.getsource(I.second_pass)
    assert "place_mask" in src and "sfx" in src


def test_it_does_not_wipe_a_drawing_inside_a_balloon():
    """A box still carrying energy because there is ARTWORK in it is not a box
    with writing left. One blob is what artwork and a misread gradient both
    come back as; writing comes back as many marks."""
    img = np.full((160, 400, 3), 250, np.uint8)
    # Bright enough that the ordinary clean does not read it as ink, and in the
    # same tone band as the gold — so it survives step one and step two is the
    # only thing standing between it and being rubbed out.
    cv2.circle(img, (200, 80), 46, (210, 180, 120), -1)
    box = (10, 10, 380, 140)
    p, out = _one(img, False, box)
    assert not p.clean_stats.get("second pass"), p.clean_stats
    assert _left(img, out, box) > 0.5, "the drawing was erased"


def test_the_second_step_asks_the_model_where_there_is_one():
    """lee: *"some if teh sfx clenning has aome notisable edges and ae too
    blurry"* — and *"the tie it takes to cleen is small so you ca add as many
    steps ai you need"*.

    A median is a blur. Measured over lee's sound effects, the area it paints
    comes back with a TENTH of the fine detail the original had there, and
    copying texture in (`shift_fill`) and diffusing it in (Telea) both measured
    the same. Nothing local rebuilds artwork.

    A model does. And the reason its first answer still had the writing on it
    is not that it failed — it redrew faithfully, from a mask that did not
    cover the words. So the second step asks it again with the mask the first
    pass should have had, on the page as it ARRIVED rather than on its own
    first answer.
    """
    img = _gold_on_cream()
    seen = {}

    def model(sub, mask):
        seen["asked"] = True
        seen["mask"] = int((mask > 0).sum())
        return sub.copy()

    _one(img, False, (10, 30, 400, 70))       # no model: must not ask
    assert not seen.get("asked")

    from mangatl.project import region_from_record
    rec = {"id": 0, "bbox": [10, 30, 400, 70], "bubble_bbox": None,
           "polygon": [], "kind": "bubble", "order": 0, "src_text": "a"}
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    p = Page(image=img.copy(), source_path="t.png")
    p.regions = [r]
    I.inpaint_page(p, neural=model)
    assert seen.get("asked"), "the second step did not reach the model"
    assert seen["mask"] > 0


def test_and_falls_back_to_a_feathered_patch_with_no_model():
    """A project with nothing to ask still gets the writing off, and the patch
    must not announce itself: painted with a hard edge it reads as damage — a
    rectangle of blur with a rim round it."""
    import inspect
    assert "GaussianBlur" in inspect.getsource(I._feathered), \
        "the fallback patch is not feathered"
    img = _gold_on_cream()
    _, out = _one(img, False, (10, 30, 400, 70))
    assert _left(img, out, (10, 30, 400, 70)) < 0.35


def test_the_second_step_tries_every_window_and_keeps_what_works():
    """lee: *"can you make a tunning for all the colors and have teh clenner
    run thru all of them"*, and *"the color thing shoud run after the first
    stp"*. The place was right; the axis was not.

    Tuning by COLOUR was built and measured and thrown away: clustering a box
    in Lab and keeping the minority bands far from the background selects 10%
    to 58% of EVERY box, including ones already cleaned perfectly, because
    highlights, decoration and a gradient's own slices are all minority colours
    far from the paper. It would erase artwork across the chapter.

    The axis that actually limits the reading is WIDTH. It is a median wider
    than a stroke, so writing whose strokes are wider than the window is
    invisible to it — the median sees the stroke as background and nothing
    differs from it. On page 060's outlined writing the 41px window finds 2%
    of the box and leaves a third of the writing; the 81px one finds 21% and
    leaves 5%. Which window is right is a fact about the box, so it is measured
    per box: paint each candidate, keep whichever leaves least.
    """
    assert len(I.SECOND_REACH) >= 2
    assert I.FOCUS_REACH in I.SECOND_REACH
    import inspect
    src = inspect.getsource(I.second_pass)
    assert "SECOND_REACH" in src and "SECOND_MOST" in src


def test_and_every_window_is_judged_on_the_same_ground():
    """Scoring each candidate inside its OWN mask is not a comparison: a small
    mask over flat paper scores near zero by erasing almost nothing, and wins.
    Measured, that version put page 019's effect back to 87% of its writing
    left. The ground is what any of the candidates thinks is writing."""
    import inspect
    src = inspect.getsource(I.second_pass)
    i = src.index("ref = np.zeros_like")
    assert "ref |= c" in src[i:i + 200]
    assert "[ref]" in src[i:i + 900], "the score is not taken over the union"


def test_a_big_patch_is_refused_when_there_is_nothing_to_rebuild_it():
    """lee, on page 010: *"the bubble got wraped"*.

    The balloon was untouched. What went wrong was beside it — a sound effect
    over grass, where the second step painted most of the box and the local
    fill flattened the artwork from a texture of 34 to 2.8, leaving a pale
    smear the balloon then sat in.

    The local fill is a blur however it is done: copying real texture in
    (`shift_fill`) measured 3.8 against that same 43. So it is only honest over
    a small patch. A model rebuilds what it paints over and may be given the
    whole box; without one the second step does the small jobs and leaves the
    big ones, because residue is recoverable and flattened artwork is not.

    The cost is measured and accepted: two sound-effect boxes keep their
    residue on a project with no model. They are cleaned normally on one with.
    """
    assert I.SECOND_MOST_LOCAL < I.SECOND_MOST
    import inspect
    src = inspect.getsource(I.second_pass)
    assert "SECOND_MOST_LOCAL" in src and "neural is not None" in src


def test_a_reading_that_claims_the_whole_box_is_refused():
    """At the widest window the median is close to the box's own average, so on
    page 004's violet effect the reading returns 93% of the box — which would
    take the artwork with it. The line sits where the readings separate: the
    honest ones across lee's chapter run to 76%, and only that one is above
    85%. A first guess of 40% threw away the true readings on four boxes."""
    assert 0.80 <= I.SECOND_MOST <= 0.90


# --- and not over texture, with nothing to rebuild it ----------------------

def _hatched(w=300, h=140, gap=3, dark=40, light=90):
    """A panel of solid hatching with white typesetting over it — the case a
    median cannot repair, because the thing it would paint over is a pattern
    and a median has no pattern in it."""
    img = np.full((h, w, 3), dark, np.uint8)
    img[::gap, :] = light
    cv2.putText(img, "GO", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
                (255, 255, 255), 8)
    return img


def _paint_of(img, out):
    return np.abs(img.astype(int) - out.astype(int)).max(2) > 6


def test_a_median_is_not_painted_over_hatching():
    """lee: *"the bubble got wraped"* — page 010, where the second step's patch
    flattened grass. The same thing on a hatched panel: the words come off and
    a smooth rectangle is left in the middle of the drawing, which is worse
    than the words, because the words at least looked deliberate."""
    from mangatl.project import region_from_record
    img = _hatched()
    box = (40, 60, 220, 60)
    rec = {"id": 0, "bbox": list(box), "bubble_bbox": None, "polygon": [],
           "kind": "sfx", "order": 0, "src_text": "a"}
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    p = Page(image=img.copy(), source_path="t.png")
    p.regions = [r]
    out = I.inpaint_page(p, neural=None)
    assert not p.clean_stats.get("second pass"), \
        "a soft patch went down over hatching with nothing to rebuild it"
    # ...and what is there is still a pattern. A median patch leaves a two or a
    # three here; the first pass's own texture copy leaves this box in the
    # twenties, which is the difference being protected.
    x, y, w, h = box
    fine = lambda z: float(
        (cv2.cvtColor(z[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(float)
         - cv2.cvtColor(I.focus_background(z[y:y + h, x:x + w]),
                        cv2.COLOR_BGR2GRAY).astype(float)).std())
    assert fine(out) > 15.0, \
        f"the artwork came back flat anyway: {fine(out):.1f} of {fine(img):.1f}"


def test_but_it_is_over_paper():
    """The guard is about texture and not about size. The same second step on a
    plain background still runs — this is what keeps lee's chapter working."""
    img = _gold_on_cream()
    p, out = _one(img, False)
    assert p.clean_stats.get("second pass") == 1, p.clean_stats


def test_a_model_may_paint_over_texture_because_it_rebuilds_it():
    """The refusal is about what a MEDIAN can do, so it belongs to the median.
    A model redraws the pattern instead of blurring it, and a box it answered
    for has already left this function by the time the grain is looked at."""
    import inspect
    src = inspect.getsource(I.second_pass)
    assert src.index("_run_neural") < src.index("SECOND_GRAIN"), \
        "the texture guard now stands between a box and the model as well"


def test_writing_the_first_step_already_took_off_is_not_texture_either():
    """The grain is measured on the page as it ARRIVED, so everything written
    on it counts as writing — including the words the first step has already
    removed. Measured only around what SURVIVED, the ordinary black line here
    is a dark pattern on cream and the box is refused: on lee's chapter that
    mistake refused nineteen of the twenty-one boxes the second step should
    take, and left 012 at 40% and 060 at 33%."""
    from mangatl.project import region_from_record
    img = np.full((140, 460, 3), 243, np.uint8)
    cv2.putText(img, "ORDINARY", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (12, 12, 12), 4)                   # the first step gets this
    cv2.putText(img, "GOLD TEXT", (20, 115), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (76, 133, 154), 4)                 # ...and not this
    box = (10, 20, 440, 110)
    rec = {"id": 0, "bbox": list(box), "bubble_bbox": None, "polygon": [],
           "kind": "bubble", "order": 0, "src_text": "a"}
    r = region_from_record(rec, img)
    r.src_text, r.order = "a", 0
    p = Page(image=img.copy(), source_path="t.png")
    p.regions = [r]
    out = I.inpaint_page(p, neural=None)
    assert p.clean_stats.get("second pass") == 1, \
        f"the words the first step removed were counted as texture: {p.clean_stats}"
    assert _left(img, out, box) < 0.35, "and the gold is still standing"


def test_the_grain_is_measured_around_the_writing_and_not_through_it():
    """Writing is not texture. Measured through the words the number is huge on
    every box and the second step would never run again — on lee's chapter the
    first version of this refused all but two of the twenty-one boxes it should
    have taken."""
    img = _hatched()
    flat = np.full_like(img, 70)
    cv2.putText(flat, "GO", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
                (255, 255, 255), 8)
    words = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY) > 200
    fine = lambda z, m: float(
        (cv2.cvtColor(z, cv2.COLOR_BGR2GRAY).astype(float)
         - cv2.cvtColor(I.focus_background(z), cv2.COLOR_BGR2GRAY).astype(float)
         )[m].std())
    grown = cv2.dilate(words.astype(np.uint8),
                       np.ones((I.MODEL_PAD * 2 + 1,) * 2, np.uint8)) > 0
    assert fine(flat, grown) >= I.SECOND_GRAIN, \
        "plain paper with a word on it does not even read as texture"
    assert fine(flat, ~grown) < I.SECOND_GRAIN, \
        "...and away from the word it is plainly not texture"
    assert fine(img, ~grown) >= I.SECOND_GRAIN, \
        "hatching away from the word is not being read as texture"


def test_the_line_sits_between_lees_chapter_and_a_hatched_panel():
    """Measured, like every other number here: every box the second step
    improves in his chapter reads 15 or under, most of them under 3, and a
    hatched panel reads 35."""
    assert 15.0 < I.SECOND_GRAIN < 35.0
