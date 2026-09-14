"""The cleaner says what it found once, and no longer says one thing at all.

lee, of the red panel under a box whose notes read "clean: the typesetting here
is hard to tell from the artwork, so only the strokes were erased — check it"
twice over: *"remoev this"*.

The sentence was written on every box the careful clean took, and every note
the cleaner writes was appended to what the box already carried, so a page
cleaned twice said it twice (43 boxes on his chapter). See `cleannotes`.
"""
import shutil

import numpy as np
import pytest
from scratch import scratch

cv2 = pytest.importorskip("cv2")

RETIRED = ("clean: the typesetting here is hard to tell from the artwork, so "
           "only the strokes were erased — check it")
GHOST = ("ghost: source text is still faintly visible after the neural (still "
         "drawn (detail 0.47)) — paint it out in Edit")
TONE = "screentone: cleaned by pattern copy, worth a look"


def test_the_retired_sentence_comes_off_saved_notes():
    from mangatl.cleannotes import without_retired
    assert without_retired(" " + RETIRED + " " + RETIRED) is None
    # ...with or without its tail, which a clipped copy can lack
    assert without_retired(" " + RETIRED[:-len(" — check it")]) is None


def test_a_cleaner_note_saved_twice_is_kept_once():
    from mangatl.cleannotes import without_retired
    got = without_retired(" " + TONE + " " + TONE)
    assert got == TONE, got


def test_notes_that_are_not_the_cleaners_are_left_alone():
    from mangatl.cleannotes import without_clean_notes, without_retired
    mixed = (GHOST + "; the outline runs off its balloon (77% outside) "
             "ocr: no text read")
    assert without_retired(mixed) == mixed.strip()
    left = without_clean_notes(mixed)
    assert left == "; the outline runs off its balloon (77% outside) ocr: no text read"
    assert without_retired("about 57 characters for a balloon that holds ~33") \
        == "about 57 characters for a balloon that holds ~33"


def test_a_project_loads_without_them(tmp_path):
    from mangatl.project import Project
    root = scratch("_tmp_clean_note_once")
    try:
        shutil.rmtree(root, ignore_errors=True)
        p = Project(None, root)
        img = np.full((200, 200, 3), 240, np.uint8)
        p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
        p.pages[0].regions = [
            {"id": 1, "kind": "sfx", "bbox": [10, 10, 50, 50],
             "flagged": " " + RETIRED + " " + RETIRED},
            {"id": 2, "kind": "bubble", "bbox": [80, 80, 50, 50],
             "flagged": " " + TONE + " " + TONE + " ocr: no text read"}]
        p.save()
        q = Project(None, root)
        notes = {r["id"]: r.get("flagged") for r in q.pages[0].regions}
        assert notes[1] is None, notes
        assert notes[2] == TONE + " ocr: no text read", notes
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_clean_does_not_repeat_what_the_last_clean_said():
    """The same careful clean as test_pipeline's, run on a box that still
    carries what two earlier cleans wrote."""
    from mangatl import inpaint
    from mangatl.models import Page, TextRegion
    rng = np.random.default_rng(11)
    img = rng.integers(10, 70, (240, 240, 3), dtype=np.uint8)
    cv2.circle(img, (120, 120), 55, (240, 240, 240), -1)
    box = np.zeros(img.shape[:2], np.uint8)
    box[50:190, 50:190] = 255
    r = TextRegion(id=0, bbox=(50, 50, 140, 140), text_mask=box.copy(),
                   bubble_mask=box, bubble_bbox=(50, 50, 140, 140))
    r.flagged = " " + RETIRED + " " + TONE + " " + TONE + " ocr: no text read"
    page = Page(image=img.copy(), regions=[r])
    inpaint.inpaint_page(page, neural=lambda im, m: im)
    assert page.clean_stats.get("core only") == 1, page.clean_stats
    text = r.flagged or ""
    assert "only the strokes were erased" not in text, text
    assert text.count("screentone:") <= 1, text
    assert "ocr: no text read" in text, "a note that is not the cleaner's went"
