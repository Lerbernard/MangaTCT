"""The balloons ink cannot find.

lee, with three screenshots side by side -- two shouts on an ice panel boxed
red, a sound effect boxed red, and two flat grey speech balloons boxed green::

    how are these bubble text ? and these grey bubble are not

An inversion, and the mechanism is exact. Every balloon this package finds it
finds from INK: `balloon._free_labels` dilates everything under 128 and calls
the rest paper, so a balloon exists when a dark outline stands between its
inside and the page. Page 050's balloons are flat grey with **no outline**,
and they overlap the bright panels above and below. Nothing lies between the
balloon and the panel, the two run together into one blob, the blob fails
every shape test, and the region arrives with the box round its writing and
the word `freefloat` on it. No threshold reaches a boundary that is not there.

`detect/comicbubble.py` is `ogkalu/comic-text-and-bubble-detector` --
RT-DETR-v2 fine-tuned on about 11,000 pages of manga, webtoons, manhua and
western comics, colour included. Measured on lee's chapter: 050's two grey
balloons at **0.98 and 0.96**, 029's four white ones at 0.93-0.97, and no box
at all on the balustrade CRAFT invented one on.

What it changes, whole chapter, 69 pages, against the same chapter without it:

    boxes           177 -> 177     it never adds or removes one
    kind changed      4 regions    049, 050 twice, 051 -- all grey balloons,
                                   all freefloat -> bubble
    regressions       0

Two guards earned that zero, and both were written after watching it get one
wrong:

  * **029** put the upper 웅성 inside the shout balloon it is painted across,
    and called the sound effect dialogue. Effects are now skipped outright.
  * **072** called the studio credits a balloon, because the flat fill inside
    the model's rectangle was the white PAGE. A shape that reaches the paper's
    edge is refused, which is the rule `balloon._plausible` already uses and
    the complaint lee already filed: *"outside etxt beigng detected as inside
    box"*.

It is not a replacement for CRAFT and these tests say so out loud. Asked to
find the sixteen sound effects CRAFT finds, it finds six, and every one of the
six is typeset. The ten it misses are brush-drawn. It is here for balloons.
"""
import cv2
import numpy as np
import pytest

from where import PKG

from mangatl.detect import comicbubble as CB
from mangatl.models import TextRegion


def _r(x, y, w, h, kind="freefloat", mask=None):
    return TextRegion(id=0, bbox=(x, y, w, h), kind=kind, bubble_mask=mask)


def _page_with_a_grey_balloon(fill=(200, 208, 199)):
    """A flat balloon with no outline, overlapping a bright panel -- the shape
    of page 050 and the case ink cannot separate."""
    page = np.zeros((600, 400, 3), np.uint8)
    page[0:180, :] = (150, 152, 158)              # the panel above
    cv2.ellipse(page, (200, 250), (150, 110), 0, 0, 360, fill, -1)
    for i in range(3):                            # writing inside it
        cv2.rectangle(page, (110, 210 + i * 34), (290, 232 + i * 34),
                      (40, 40, 40), -1)
    return page, (110, 210, 180, 90)


# ------------------------------------------------- it can be absent

def test_no_weights_means_the_pass_does_not_run():
    assert CB.available("") is False
    assert CB.available("/no/such/detector.onnx") is False


def test_a_run_with_no_weights_changes_nothing():
    r = _r(10, 10, 50, 20)
    assert CB.name_the_balloons(np.zeros((80, 80, 3), np.uint8), [r], "") == 0
    assert r.kind == "freefloat"
    assert r.bubble_mask is None


def test_no_regions_is_not_an_error():
    assert CB.name_the_balloons(np.zeros((80, 80, 3), np.uint8), [], "x") == 0


# ------------------------------------------------- tall pages are read in windows

def test_a_normal_page_is_one_window():
    assert CB._windows(900, 600) == [(0, 900)]


def test_a_webtoon_is_cut_into_overlapping_windows():
    """Squashed whole into the model's 640 square, a 690x3462 strip shows it
    writing four times narrower than anything it was trained on."""
    ws = CB._windows(3462, 690)
    assert len(ws) > 1
    assert ws[0][0] == 0 and ws[-1][1] == 3462
    for a, b in zip(ws, ws[1:]):
        assert b[0] < a[1], "the windows must overlap"


def test_every_row_of_a_tall_page_is_looked_at():
    ws = CB._windows(3462, 690)
    seen = np.zeros(3462, bool)
    for a, b in ws:
        seen[a:b] = True
    assert seen.all()


# ------------------------------------------------- the outline

def test_the_outline_follows_a_balloon_with_no_line_round_it():
    page, text = _page_with_a_grey_balloon()
    got = CB.outline(page, (40, 130, 360, 370), text)
    assert got is not None
    mask, box, poly = got
    # the ellipse, not the rectangle it was found in
    assert 0.55 < float((mask > 0).sum()) / (360 * 240) < 0.95
    x, y, w, h = box
    assert abs(w - 300) < 40 and abs(h - 220) < 40


def test_the_colour_is_taken_from_between_the_letters():
    """Not from the margin: the model's rectangle is a box round an ellipse,
    so on a dark page 38% of that margin is the page and the mode came back
    black. Same balloon on a black page and on a white one, same answer."""
    dark, text = _page_with_a_grey_balloon()
    light = dark.copy()
    light[light.sum(axis=2) == 0] = (255, 255, 255)
    a = CB.outline(dark, (40, 130, 360, 370), text)
    b = CB.outline(light, (40, 130, 360, 370), text)
    assert a is not None and b is not None
    assert abs(a[1][2] - b[1][2]) < 30


def test_a_fill_that_runs_on_past_the_rectangle_is_not_a_balloon():
    """072's studio credits: a type block on a white page. The fill inside the
    model's rectangle is flat, and it is flat because it is the PAGE. A
    balloon has something else outside it; a page has more page."""
    page = np.full((600, 400, 3), 250, np.uint8)
    cv2.rectangle(page, (80, 260), (320, 340), (30, 30, 30), -1)
    assert CB.outline(page, (40, 220, 360, 380), (80, 260, 240, 80)) is None


def test_a_rectangle_full_of_artwork_gives_no_outline():
    """Closing gaps with an 11-pixel brush welds noise into one shape too. What
    refuses it is what it is MADE of -- `balloon._interior_ok`'s question and
    its number."""
    rng = np.random.default_rng(4)
    page = rng.integers(0, 255, (600, 400, 3), dtype=np.uint8)
    assert CB.outline(page, (40, 130, 360, 370), (150, 250, 100, 60)) is None


def test_a_balloon_ends_and_a_page_does_not():
    """`_it_ends` on its own, because it is the only thing between a balloon
    and the paper a caption is printed on."""
    page, text = _page_with_a_grey_balloon()
    fill = np.asarray(cv2.cvtColor(np.uint8([[[200, 208, 199]]]),
                                   cv2.COLOR_BGR2LAB)[0, 0], float)
    assert CB._it_ends(page, (40, 130, 360, 370), fill)

    plain = np.full((600, 400, 3), 250, np.uint8)
    paper = np.asarray(cv2.cvtColor(np.uint8([[[250, 250, 250]]]),
                                    cv2.COLOR_BGR2LAB)[0, 0], float)
    assert not CB._it_ends(plain, (40, 220, 360, 380), paper)


def test_the_numbers_are_the_ones_that_were_measured():
    """Pinned, because every one of them was arrived at by watching it get a
    page wrong and none of them can be re-derived from reading the code.

    `HOLDS` and `GAIN`: a rectangle is that writing's balloon when it holds
    nine tenths of it and is at least a seventh bigger. `MAX_PAGE`: a balloon
    is not a panel. The three slicing numbers are comic-translate's own, and
    they are what stop a 690x3462 strip being squashed into a 640 square.
    """
    assert CB.HOLDS == 0.90
    assert CB.GAIN == 1.15
    assert CB.MAX_PAGE == 0.45
    assert (CB.TALL, CB.SLICE_MIN, CB.OVERLAP) == (3.5, 0.7, 0.2)
    assert CB.SIDE == 640


def test_the_windows_really_do_share_ground():
    """At `OVERLAP` 0 the last window is still snapped back to the foot of the
    page, so a two-window strip overlaps by accident. Ask a taller one, where
    the middle windows have nothing to snap them together."""
    ws = CB._windows(690 * 12, 690)
    assert len(ws) >= 4
    share = min(a[1] - b[0] for a, b in zip(ws, ws[1:]))
    assert share > 0.1 * (ws[0][1] - ws[0][0])


def test_a_rectangle_too_small_to_mean_anything_is_refused():
    page, _ = _page_with_a_grey_balloon()
    assert CB.outline(page, (10, 10, 14, 14), (11, 11, 2, 2)) is None


# ------------------------------------------------- what it will and will not touch

def _patched(monkeypatch, boxes):
    monkeypatch.setattr(CB, "available", lambda p: True)
    monkeypatch.setattr(CB, "balloons", lambda img, p, conf=CB.CONF: boxes)


def test_a_grey_balloon_makes_the_writing_dialogue(monkeypatch):
    page, text = _page_with_a_grey_balloon()
    _patched(monkeypatch, [(40, 130, 360, 370, 0, 0.98)])
    r = _r(*text)
    assert CB.name_the_balloons(page, [r], "weights") == 1
    assert r.kind == "bubble"
    assert r.bubble_mask is not None
    assert r.polygon
    assert r.bubble_bbox is not None and r.bubble_bbox != tuple(text)


def test_a_region_that_already_has_a_balloon_keeps_it(monkeypatch):
    """The mask that is already there was measured off THIS page; this is a
    guess about comics in general. Where they disagree the measurement wins."""
    page, text = _page_with_a_grey_balloon()
    _patched(monkeypatch, [(40, 130, 360, 370, 0, 0.98)])
    mine = np.zeros(page.shape[:2], np.uint8)
    r = _r(*text, kind="bubble", mask=mine)
    assert CB.name_the_balloons(page, [r], "weights") == 0
    assert r.bubble_mask is mine


def test_a_sound_effect_is_left_alone(monkeypatch):
    """029: the upper 웅성 is painted across the spikes of a shout balloon, so
    the model's rectangle holds all of it. Calling it dialogue would send it to
    the balloon fitter and have the cleaner paint out the whole shout."""
    page, text = _page_with_a_grey_balloon()
    _patched(monkeypatch, [(40, 130, 360, 370, 0, 0.98)])
    r = _r(*text, kind="sfx")
    assert CB.name_the_balloons(page, [r], "weights") == 0
    assert r.kind == "sfx"
    assert r.bubble_mask is None


def test_a_balloon_that_does_not_hold_the_writing_is_not_its_balloon(monkeypatch):
    """A perfectly good balloon somewhere else on the page is still not this
    region's balloon. The fixture gives it a real one to be tempted by."""
    page, text = _page_with_a_grey_balloon()
    cv2.ellipse(page, (200, 480), (120, 80), 0, 0, 360, (200, 208, 199), -1)
    _patched(monkeypatch, [(70, 390, 330, 570, 0, 0.98)])
    r = _r(*text)
    assert CB.name_the_balloons(page, [r], "weights") == 0
    assert r.bubble_mask is None


def test_a_balloon_no_bigger_than_the_writing_buys_nothing(monkeypatch):
    page, text = _page_with_a_grey_balloon()
    x, y, w, h = text
    _patched(monkeypatch, [(x, y, x + w, y + h, 0, 0.98)])
    r = _r(*text)
    assert CB.name_the_balloons(page, [r], "weights") == 0


def test_the_smallest_balloon_that_holds_it_wins(monkeypatch):
    page, text = _page_with_a_grey_balloon()
    _patched(monkeypatch, [(0, 0, 400, 600, 0, 0.99),
                           (40, 130, 360, 370, 0, 0.95)])
    r = _r(*text)
    assert CB.name_the_balloons(page, [r], "weights") == 1
    assert r.bubble_bbox[2] < 360


def test_a_panel_sized_rectangle_is_not_a_balloon():
    """`MAX_PAGE` keeps the pass from wrapping a region in half the page."""
    assert CB.MAX_PAGE < 0.5


def test_a_sub_type_the_person_picked_is_not_overwritten(monkeypatch):
    """A thought bubble is still a thought bubble. Only a region the detectors
    called something OTHER than dialogue moves."""
    page, text = _page_with_a_grey_balloon()
    _patched(monkeypatch, [(40, 130, 360, 370, 0, 0.98)])
    r = _r(*text, kind="thought")
    CB.name_the_balloons(page, [r], "weights")
    assert r.kind == "thought"


# ------------------------------------------------- and what each box IS

def _kpatched(monkeypatch, boxes):
    monkeypatch.setattr(CB, "available", lambda p: True)
    monkeypatch.setattr(CB, "look", lambda img, p, conf=CB.CONF: boxes)


def _blank():
    return np.zeros((400, 400, 3), np.uint8)


def test_a_caption_on_a_pale_page_stops_being_dialogue(monkeypatch):
    """022's ruled caption boxes. The app calls them Bubble text because it
    asks whether the margin is brighter than 200 and a cream page says yes.
    The model was told which writing is in a balloon; it says 0.91 outside."""
    _kpatched(monkeypatch, [(40, 40, 260, 140, 2, 0.91)])
    r = _r(60, 60, 180, 60, kind="bubble")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 1
    assert r.kind == "freefloat"


def test_writing_in_a_balloon_on_a_dark_panel_becomes_dialogue(monkeypatch):
    """066, the same failure the other way up: the margin is dark, so every
    tone test says outside, and it is in a balloon."""
    _kpatched(monkeypatch, [(40, 40, 260, 140, 1, 0.95)])
    r = _r(60, 60, 180, 60, kind="freefloat")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 1
    assert r.kind == "bubble"


def test_it_agrees_silently_when_it_agrees(monkeypatch):
    _kpatched(monkeypatch, [(40, 40, 260, 140, 1, 0.95)])
    r = _r(60, 60, 180, 60, kind="bubble")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 0
    assert r.kind == "bubble"


def test_a_sound_effect_is_never_relabelled(monkeypatch):
    """The question is dialogue-versus-outside-text. It has nothing to say
    about paint, and CRAFT is the only thing here that can see paint."""
    _kpatched(monkeypatch, [(40, 40, 260, 140, 1, 0.99)])
    r = _r(60, 60, 180, 60, kind="sfx")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 0
    assert r.kind == "sfx"


def test_a_sub_type_somebody_chose_is_never_relabelled(monkeypatch):
    """A thought bubble, an angry balloon, a caption moved by hand. Those are
    decisions; only a box still on the family default it was detected as can
    move."""
    _kpatched(monkeypatch, [(40, 40, 260, 140, 2, 0.99)])
    for kind in ("thought", "narration"):
        r = _r(60, 60, 180, 60, kind=kind)
        assert CB.name_the_kinds(_blank(), [r], "weights") == 0
        assert r.kind == kind


def test_a_box_it_is_not_sure_about_is_left_alone(monkeypatch):
    _kpatched(monkeypatch, [(40, 40, 260, 140, 2, 0.2)])
    r = _r(60, 60, 180, 60, kind="bubble")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 0
    assert r.kind == "bubble"


def test_the_box_that_covers_it_best_is_the_one_that_speaks(monkeypatch):
    """The model boxes a LINE where the app boxes a balloon, so several of its
    boxes can land on one region. The one that actually covers it decides --
    not whichever happens to come out of the net first."""
    _kpatched(monkeypatch, [(52, 52, 92, 96, 2, 0.99),      # a corner of it
                            (40, 40, 260, 140, 1, 0.95)])   # all of it
    r = _r(60, 60, 180, 60, kind="freefloat")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 1
    assert r.kind == "bubble"


def test_a_box_it_barely_touches_does_not_get_a_say(monkeypatch):
    _kpatched(monkeypatch, [(230, 100, 500, 130, 2, 0.99)])
    r = _r(60, 60, 180, 60, kind="bubble")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 0


def test_the_word_changes_and_nothing_else(monkeypatch):
    """Never a corner, never a mask."""
    _kpatched(monkeypatch, [(40, 40, 260, 140, 2, 0.91)])
    r = _r(60, 60, 180, 60, kind="bubble")
    r.bubble_bbox = (1, 2, 3, 4)
    CB.name_the_kinds(_blank(), [r], "weights")
    assert r.bbox == (60, 60, 180, 60)
    assert r.bubble_bbox == (1, 2, 3, 4)
    assert r.bubble_mask is None


def test_the_balloon_boxes_do_not_vote_on_the_word(monkeypatch):
    """Class 0 is where a balloon IS, not what a box is. Only 1 and 2 speak."""
    _kpatched(monkeypatch, [(40, 40, 260, 140, 0, 0.99)])
    r = _r(60, 60, 180, 60, kind="bubble")
    assert CB.name_the_kinds(_blank(), [r], "weights") == 0


def test_no_weights_leaves_every_word_alone():
    r = _r(60, 60, 180, 60, kind="bubble")
    assert CB.name_the_kinds(_blank(), [r], "") == 0
    assert r.kind == "bubble"


def test_the_two_passes_share_one_forward_pass():
    """`look` exists so that giving a region its balloon and saying what the
    region is cost one pass between them, not one each."""
    import inspect
    for fn in (CB.name_the_balloons, CB.name_the_kinds):
        assert "boxes" in inspect.signature(fn).parameters
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert src.count("_CB.look(") == 1
    # ...and BOTH passes are handed it. One that asks for its own runs a
    # second forward pass over the page for the same answer.
    assert src.count("boxes=cb_boxes") == 2


def test_the_word_is_decided_after_every_measured_rule():
    """It runs at the END. Put it before `loose_bubble` and the measured
    demotion simply overwrites it again."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert src.index("if loose_bubble:") < src.index("_CB.name_the_kinds")


def test_the_measured_numbers_are_recorded():
    src = (PKG / "detect" / "comicbubble.py").read_text(encoding="utf-8")
    assert "96%" in src or "133" in src


# ------------------------------------------------- and it is wired in

def test_find_text_can_be_told_where_the_weights_are():
    import inspect
    from mangatl.detect import comictext as CT
    sig = inspect.signature(CT.detect_comictext)
    assert "bubble_weights" in sig.parameters
    assert sig.parameters["bubble_weights"].default == ""


def test_the_pass_runs_after_the_measurement_not_instead_of_it():
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    a = src.index("attach_balloons(gray, regions)")
    b = src.index("_CB.name_the_balloons")
    assert a < b, "ink first, and the model only for what ink could not find"


def test_the_weights_are_looked_for_beside_the_detectors(tmp_path):
    from mangatl.project import Project
    p = Project(None, str(tmp_path))
    p.settings["weights"] = str(tmp_path / "comictextdetector.pt.onnx")
    assert p.bubble_weights() == ""
    big = tmp_path / "detector.onnx"
    big.write_bytes(b"x")
    assert p.bubble_weights() == str(big)


def test_a_named_file_that_is_not_there_turns_the_pass_off(tmp_path):
    from mangatl.project import Project
    p = Project(None, str(tmp_path))
    p.settings["bubble_weights"] = str(tmp_path / "gone.onnx")
    assert p.bubble_weights() == ""


def test_it_is_not_sold_as_a_replacement_for_craft():
    """Six of the sixteen, and all six typeset. Written where somebody
    wondering why CRAFT is still here will read it."""
    src = (PKG / "detect" / "comicbubble.py").read_text(encoding="utf-8")
    assert "not a replacement for CRAFT" in src
    assert "six" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
