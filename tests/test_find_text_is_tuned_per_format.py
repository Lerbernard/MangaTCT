"""Find text, frozen for manga and forked for the webtoons.

lee: *"save what we ahve for find text for manga and now we will modify it for
manhwa"*.

Every number the detector runs on was measured on his manga chapters — the
confidence the block head must reach, how much two blocks may overlap, how sure
a pixel of the mask has to be, and the two gaps that end one block of writing.
They were arrived at by cropping and looking at every box the gates dropped
across 39 pages. They are not to be moved by anything done for another format.

So they are a TABLE, one entry per format, and `manhwa` and `manhua` hold their
own COPIES rather than being aliases of `manga`. Five of those seven have since
moved for the webtoons — see `WEBTOON` below — and manga has not, which is the
table earning itself.

These tests are the guard on that. They pin manga's numbers to the measured
ones, they check the entries are separate objects, and one of them tunes manhwa
on purpose and asserts manga stayed where it was.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import comictext as CT
from mangatl.project import Project

# What Find text has run on since the numbers were measured. Written out here
# rather than read from the module, because a test that reads the value it is
# checking checks nothing.
MEASURED = {
    "conf_thresh": 0.4,
    "nms_thresh": 0.35,
    "mask_thresh": 0.30,
    "split_gap": 1.8,
    "split_height": 1.8,
    # None means the CIRCLE — the straight-line reach of `LEFT_NEAR`, which is
    # what manga was measured on. The webtoons use an ellipse instead.
    "join_x": None,
    "join_y": None,
    # The second detector, off. `blk` and `seg` were measured on manga across
    # 39 pages and they find it; CRAFT exists for the case they go blank on,
    # which is a coloured brush-drawn shape over artwork on a Korean webtoon.
    "craft_x": None,
    "craft_y": None,
    "craft_cap": 0.05,
    # Widening a sound-effect box to the strokes it already holds most of.
    # None is off, and manga is off: the clipping lee reported was measured on
    # his Korean webtoon and the number is that chapter's.
    "sfx_grow": None,
    "sfx_grow_cap": 0.12,
    # ...and the same for a dialogue box, at a much higher bar. Off here for
    # the same reason: lee's em dash was measured on his Korean webtoon.
    "text_grow": None,
    # Calling an almost-empty OUTSIDE TEXT box a drawn sound effect. Off, and
    # for the third time for the same reason: the fill numbers behind it were
    # measured on two Korean webtoon chapters and on nothing else. See
    # `comictext._looks_hand_drawn` and `tests/test_too_empty_to_be_type.py`.
    "effect_fill": None,
    # Taking the word "dialogue" back off a box with no balloon near it. Off,
    # and for the fourth time for the same reason: the margin tones behind it
    # were measured on chapter 1 of the Korean webtoon. See
    # `tests/test_the_sky_is_not_a_balloon.py`.
    "loose_bubble": None,
    # Reading a box the coverage pass found as writing the block head missed
    # rather than as a drawn shape. Off, and for the fifth time for the same
    # reason: measured on the Korean webtoons. See
    # `tests/test_the_writing_the_block_head_missed.py`.
    "cover_text": None,
    # Joining the two lobes of one balloon. Off, and for the sixth time for the
    # same reason: measured on lee's webtoon pages. See
    # `tests/test_two_lobes_two_boxes.py`.
    "link_touching": None,
    # Reading two overlapping boxes as one piece of writing that came back in
    # pieces, and throwing away a box holding one thin mark and nothing else.
    # Off, and for the seventh and eighth time for the same reason: both were
    # measured on 46 pages of a Korean webtoon. See
    # `tests/test_one_piece_of_writing_one_box.py`.
    "join_over": None,
    "stray_fill": None,
    # The second detector counting the characters in a box -- the veto on a
    # box it sees none in, and the shout/writing calls either side of the
    # count. Off, and manga is off twice over: these need CRAFT, which manga
    # does not run, and the counts were measured on 46 Korean webtoon pages.
    "art_veto": False,
    "fx_chars": None,
    # Splitting one box that holds two texts. Off, and manga is off: the
    # staircase and the stacked band were both measured on 46 Korean webtoon
    # pages. See `tests/test_one_piece_of_writing_one_box.py`.
    "split_texts": False,
}


def test_manga_runs_on_the_numbers_it_was_measured_on():
    assert CT.tuning_for("manga") == MEASURED


def test_the_mask_floor_is_the_one_the_module_publishes():
    """`SEG_KEEP` is quoted in the comment above the leftover harvest and in
    the docs. Two copies of one number is one too many."""
    assert CT.tuning_for("manga")["mask_thresh"] == CT.SEG_KEEP


def test_a_format_nobody_has_tuned_is_read_as_manga():
    """The measured numbers are a better answer than no answer."""
    assert CT.tuning_for("western") == MEASURED
    assert CT.tuning_for("") == MEASURED
    assert CT.tuning_for(None) == MEASURED


def test_every_format_has_the_same_knobs():
    """A missing key falls back to `detect_comictext`'s own default, which is
    a second place for the value to live and a silent way for two formats to
    diverge on something nobody changed."""
    for m in ("manga", "manhwa", "manhua"):
        assert set(CT.tuning_for(m)) == set(MEASURED), m


# The webtoons' first pass. lee, with all three box types ticked: *"its still
# missing a lot of sfx"*, and the ones it did find came back in pieces.
WEBTOON = dict(MEASURED, mask_thresh=0.20,
               split_gap=3.5, split_height=1.1, join_x=1.8, join_y=0.6,
               craft_x=0.30, craft_y=0.05, sfx_grow=0.40, text_grow=0.70,
               effect_fill=0.28, loose_bubble=230, cover_text=0.25,
               link_touching=12, join_over=0.05, stray_fill=0.115,
               art_veto=True, fx_chars=2, split_texts=True)


def test_the_webtoons_split_less_and_reach_further():
    """What moved, and in the direction the screenshots asked for: keep more
    mask, so a brush-drawn sound effect lying on bare artwork has ink for the
    coverage pass to find; widen both gaps and give the leftover marks an
    elliptical reach, so the one that IS found comes back as one box rather
    than two."""
    for m in ("manhwa", "manhua"):
        got = CT.tuning_for(m)
        assert got == WEBTOON, m
        assert got["mask_thresh"] < MEASURED["mask_thresh"], m
        assert got["split_gap"] > MEASURED["split_gap"], m
        # ...but only SIDEWAYS. `split_height` moved with its twin here and was
        # measured afterwards, on all 142 blocks of chapter 1, and came back
        # NARROWER than manga's: the gap between the two lobes of a double
        # balloon is the thing it has to catch. See
        # `test_the_double_balloon_comes_apart.py`.
        assert got["split_height"] < MEASURED["split_height"], m
        assert got["join_x"] > got["join_y"], \
            "the reach is wide and flat: writing runs along a line"


def test_the_block_head_is_asked_the_same_question_on_every_format():
    """`conf_thresh` was dropped to 0.22 for the webtoons for one turn, to
    make the block head propose the Korean sound effects. lee then ran the
    diagnostic on his own chapter and it does not:

        === 028.png  720x2770
        blocks: conf>0.05: 0   conf>0.10: 0   conf>0.22: 0
        mask:   keep>0.20: 0.04% of the page   keep>0.05: 0.25% of the page

    on a page whose sound effects cover something like a sixth of it; and on
    021 the head returns the same 2 blocks at 0.05 as at 0.40. The effects are
    not in that head's output at ANY score, so there is no bar low enough to
    catch them. The 0.22 bought nothing and cost boxes on an eye and a jewel
    on page 026. Finding them is the coverage pass's job, or a different
    detector's; it is not this number's.
    """
    for m in ("manga", "manhwa", "manhua"):
        assert CT.tuning_for(m)["conf_thresh"] == MEASURED["conf_thresh"], m


def test_the_second_detector_runs_on_a_reach_of_its_own():
    """The mask's 1.8 x 0.9 does not transfer to CRAFT and was not reused.

    The mask's marks are stroke fragments, often a fraction of one syllable, so
    1.8 is a fraction of a syllable. CRAFT's pieces are whole character groups,
    so the same 1.8 is 1.8 whole syllables, and on page 026 it swept all eight
    하아 into one box covering 26% of the page. Swept again on the same 36
    pages:

        jx / jy    026    pages >5%   chapter groups
        0.20/0.20    8            6              525
        0.25/0.10    8            4              571
        0.30/0.05    8            4              548   <- here
        0.50/0.10    5            4              452

    Page 026 holds eight sound effects, so eight groups is the answer and 0.50
    undershoots it; between the two that reach eight, 0.30/0.05 fragments the
    chapter less. End to end on that page: 1 box before, 16 after, biggest
    4.7%.
    """
    got = CT.tuning_for("manhwa")
    assert (got["craft_x"], got["craft_y"]) == (0.30, 0.05)
    assert got["craft_x"] != got["join_x"], \
        "the mask's reach is measured on fragments, not on syllables"


def test_the_second_detectors_reach_is_flatter_than_the_masks():
    """Both are wide and flat because writing runs along a line, and CRAFT's is
    flatter -- 6:1 against the mask's 2:1. Its pieces are whole syllables
    sharing a baseline, so two of one effect have almost no vertical gap."""
    got = CT.tuning_for("manhwa")
    assert got["craft_x"] > got["craft_y"]
    assert got["craft_x"] / got["craft_y"] > got["join_x"] / got["join_y"]


def test_manga_could_not_turn_the_second_detector_on_even_by_accident():
    """Whatever happens for the webtoons, `blk` and `seg` were measured on
    manga across 39 pages and they find it. A second opinion it never asked
    for is a second chance to be wrong."""
    assert CT.TUNING["manga"]["craft_x"] is None
    assert CT.TUNING["manga"]["craft_y"] is None


def test_the_one_nothing_asked_to_move_did_not():
    """`nms_thresh` is about two boxes ON TOP OF one another. Nothing lee
    showed was that — they were two boxes side by side — so it stays where it
    was measured, and a change to it should have to be argued for."""
    assert CT.tuning_for("manhwa")["nms_thresh"] == MEASURED["nms_thresh"]


def test_manga_did_not_move_when_the_webtoons_did():
    """The fork earning itself. Eight numbers changed for manhwa and manhua in
    the same file, and manga is still on the ones measured for it."""
    assert CT.tuning_for("manga") == MEASURED


def test_they_are_copies_and_not_the_same_object():
    """The entire point. Aliases would look identical to every test above and
    would silently move manga the first time a webtoon number was tuned."""
    assert CT.TUNING["manhwa"] is not CT.TUNING["manga"]
    assert CT.TUNING["manhua"] is not CT.TUNING["manga"]
    assert CT.TUNING["manhua"] is not CT.TUNING["manhwa"]


def test_tuning_manhwa_cannot_move_manga():
    """Said as the thing it is protecting against, rather than as a fact about
    object identity."""
    was = CT.tuning_for("manga")
    keep = CT.tuning_for("manhwa")
    CT.TUNING["manhwa"]["conf_thresh"] = 0.9
    try:
        assert CT.tuning_for("manga") == was
        assert CT.tuning_for("manhwa")["conf_thresh"] == 0.9
    finally:
        # Back to the webtoon's OWN numbers, not to manga's. Restoring the
        # wrong ones here would leave the rest of the run measuring a manhwa
        # chapter with manga's settings and nothing would say so.
        CT.TUNING["manhwa"] = keep


def test_what_you_are_handed_is_yours_to_scribble_on():
    """A caller that adjusts what it gets must not adjust the table."""
    got = CT.tuning_for("manga")
    got["conf_thresh"] = 0.99
    assert CT.tuning_for("manga")["conf_thresh"] == 0.4


# ------------------------------------------------------- and the app uses it

def test_the_detector_takes_all_of_them(tmp_path):
    """A number in the table that `detect_comictext` does not accept is a
    number that does nothing, and it would do nothing quietly."""
    import inspect

    args = inspect.signature(CT.detect_comictext).parameters
    for k in MEASURED:
        assert k in args, k


def test_a_chapter_is_found_with_its_own_formats_numbers(tmp_path, monkeypatch):
    """The wiring. `Project.detect` has to ask the table which format it is
    holding — a hard-coded call here is how the fork ends up decorative."""
    seen = {}

    def fake(page, weights, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(CT, "detect_comictext", fake)
    monkeypatch.setitem(CT.TUNING["manhwa"], "conf_thresh", 0.11)

    p = Project(None, str(tmp_path / "out"))
    img = np.repeat(np.random.default_rng(1).integers(
        60, 200, (300, 200, 1), dtype=np.uint8), 3, axis=2)
    p.add_uploaded("a.png", cv2.imencode(".png", img)[1].tobytes())
    p.settings["detector"] = "comictext"
    p.settings["weights"] = "not-a-real-model.onnx"

    p.settings["medium"] = "manga"
    p.detect(0)
    assert seen["conf_thresh"] == 0.4

    seen.clear()
    p.settings["medium"] = "manhwa"
    p.detect(0)
    assert seen["conf_thresh"] == 0.11, \
        "a manhwa chapter has to be found with the manhwa numbers"


# --------------------------------------- how far one mark reaches for another

def _marks(spec, shape=(700, 700)):
    """A mask of solid blobs at the boxes given, and nothing claimed."""
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in spec:
        m[y0:y1 + 1, x0:x1 + 1] = 255
    return m, np.zeros(shape, bool)


def _groups(spec, **kw):
    m, claimed = _marks(spec)
    return [g[0] for g in CT._harvest(m, claimed, **kw)]


def test_the_circle_is_what_manga_still_gets():
    """`join_x`/`join_y` unset falls back to `LEFT_NEAR` and the straight-line
    gap, which is the rule the manga numbers were measured on. Every manga
    chapter has to come out of this change byte for byte."""
    spec = [(100, 100, 140, 160), (170, 100, 210, 160)]
    assert _groups(spec) == _groups(spec, near=CT.LEFT_NEAR)
    assert CT.tuning_for("manga")["join_x"] is None


def test_two_strokes_of_one_sound_effect_join_sideways():
    """Measured on lee's page 18 of chapter 227. The two halves of one 퍽써!
    are 53px apart sideways and 10px vertically, next to a 36px mark — 1.47
    and 0.28 smaller-marks. The circle refuses that at 0.6 and cut the effect
    into two boxes; the ellipse takes it."""
    spec = [(100, 100, 136, 136), (189, 110, 225, 146)]
    assert len(_groups(spec)) == 2, "the circle keeps them apart"
    assert len(_groups(spec, near_x=1.8, near_y=0.9)) == 1


def test_two_different_sound_effects_stacked_do_not_join():
    """The other half of the measurement, from page 28. Two effects one above
    the other: no sideways gap at all and 129px vertically, next to a 126px
    mark — 1.02 smaller-marks. A circle wide enough to fix page 18 swallows
    both of these into one box 17% of the page; the ellipse refuses it."""
    spec = [(100, 100, 226, 226), (100, 355, 226, 481)]
    assert len(_groups(spec, near=2.0)) == 1, "a circle that wide merges them"
    assert len(_groups(spec, near_x=1.8, near_y=0.9)) == 2


def test_the_webtoon_reach_separates_the_two_by_itself():
    """Said once more through `tuning_for`, because the numbers in the table
    are what actually runs."""
    t = CT.tuning_for("manhwa")
    kw = dict(near_x=t["join_x"], near_y=t["join_y"])
    assert len(_groups([(100, 100, 136, 136), (189, 110, 225, 146)], **kw)) == 1
    assert len(_groups([(100, 100, 226, 226), (100, 355, 226, 481)], **kw)) == 2


def test_the_detector_passes_the_reach_down():
    """A number in the table that never reaches `_harvest` is a number that
    does nothing."""
    import inspect

    args = inspect.signature(CT.detect_comictext).parameters
    assert "join_x" in args and "join_y" in args
    src = inspect.getsource(CT.detect_comictext)
    assert "near_x=join_x" in src and "near_y=join_y" in src
