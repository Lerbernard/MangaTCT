"""Changing a box's type actually changes the typesetting.

lee: *"i changed teh bubble to outside buuble an it still typeseete the same
make t so that when i update it teh bubble type it accuavly changes or make it
the typeseeting accuaooly redo the page when i hit the tyset tehh page"*.

He was right, and the reason is worth writing down. A chapter is held as
GEOMETRY — masks are rebuilt from records on every load — and the balloon a
region was given is stored as its `polygon`. Calling a box "outside text" only
rewrote `kind`. The panel-shaped polygon the balloon finder had handed it was
still sitting in the record, so the page came back with the same placement area
and typeset exactly the same. The label said one thing and the geometry said
another, and the geometry won. Pressing Typeset could not help: it lays the
page out again from the same geometry.

So a change of kind now takes the geometry with it. Calling a box something
that cannot have a balloon — outside text, or a sound effect — puts its polygon
back to a plain rectangle round the writing, which is how "no balloon" is
written everywhere else in the project. The placement is dropped either way, so
the region is measured again instead of keeping a fit made for a shape it no
longer has.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.editor import NO_BALLOON_KINDS, _kind_changed


def _rec(kind="bubble"):
    """A record whose polygon is a PANEL — the shape lee was stuck with."""
    return {"id": 1, "bbox": [600, 120, 40, 300],
            "bubble_bbox": [80, 80, 700, 400],
            "polygon": [[80, 80], [780, 90], [770, 470], [90, 460]],
            "kind": kind, "order": 0,
            "layout_override": {"lines": ["OLD"], "font_size": 33,
                                "font": "MyFont.ttf", "locked": True}}


def test_calling_it_outside_text_drops_the_balloon():
    r = _rec("freefloat")
    _kind_changed(r, "bubble")
    assert r["polygon"] == [[600, 120], [640, 120], [640, 420], [600, 420]]
    assert r["bubble_bbox"] == [600, 120, 40, 300]


def test_the_new_polygon_is_a_plain_rectangle():
    """`project._is_a_box` is what decides there is no balloon on the way back
    in. If the rectangle is not written the way that function recognises, the
    region reloads with a balloon again and nothing has changed."""
    from mangatl.project import _is_a_box
    r = _rec("freefloat")
    _kind_changed(r, "bubble")
    assert _is_a_box(np.array(r["polygon"], np.int32))


def test_a_sound_effect_drops_it_too():
    r = _rec("sfx")
    _kind_changed(r, "bubble")
    assert r["bubble_bbox"] == [600, 120, 40, 300]


def test_calling_it_a_bubble_keeps_the_outline():
    """The other direction must not throw a real balloon away: a caption
    relabelled as speech still lives in the same paper."""
    r = _rec("bubble")
    _kind_changed(r, "narration")
    assert r["polygon"] == [[80, 80], [780, 90], [770, 470], [90, 460]]
    assert r["bubble_bbox"] == [80, 80, 700, 400]


def test_the_old_fit_is_dropped_whichever_way_the_kind_moved():
    for new, old in (("freefloat", "bubble"), ("bubble", "freefloat"),
                     ("narration", "bubble")):
        r = _rec(new)
        _kind_changed(r, old)
        ov = r.get("layout_override") or {}
        assert "lines" not in ov and "font_size" not in ov, new


def test_the_typesetting_already_on_the_page_stays_until_typeset():
    """Emptying the bubble the moment somebody changes a label would blank the
    page in front of them. The old typesetting stays; pressing Typeset replaces
    it, now with geometry that has actually changed."""
    r = _rec("freefloat")
    r["layout"] = {"lines": ["KEEP"], "font_size": 20}
    _kind_changed(r, "bubble")
    assert r.get("layout"), "the typesetting on the page was thrown away"


def test_the_dressing_survives():
    """Font and colours are how the box was DRESSED, not how it was placed."""
    r = _rec("freefloat")
    _kind_changed(r, "bubble")
    assert (r["layout_override"] or {}).get("font") == "MyFont.ttf"


def test_an_untouched_region_does_not_grow_an_override():
    r = _rec("freefloat")
    r["layout_override"] = None
    _kind_changed(r, "bubble")
    assert r.get("layout_override") is None


def test_the_kinds_that_cannot_have_a_balloon():
    assert set(NO_BALLOON_KINDS) == {"freefloat", "sfx"}


def test_end_to_end_the_typesetting_stops_covering_the_drawing():
    """The whole point, measured on a page shaped like lee's page 10: a
    caption printed on a blank panel, a drawing beside it, and a balloon the
    finder invented that spans both."""
    from mangatl.project import region_from_record, find_balloons

    img = np.zeros((600, 800, 3), np.uint8)
    img[40:560, 40:760] = 255                            # one blank panel
    cv2.circle(img, (480, 300), 120, (30, 30, 30), -1)   # the drawing
    for k in range(120, 400, 22):                        # a column of writing
        cv2.rectangle(img, (600, k), (640, k + 14), (20, 20, 20), -1)
    drawing = np.zeros(img.shape[:2], np.uint8)          # the circle alone
    cv2.circle(drawing, (480, 300), 120, 255, -1)
    drawing = drawing > 0

    rec = {"id": 1, "bbox": [600, 120, 41, 280],
           "bubble_bbox": [360, 60, 390, 480],
           # a rectangle would read as "no balloon", so this one has a bent
           # corner, the way a real found outline does
           "polygon": [[360, 60], [748, 62], [750, 540], [360, 540]],
           "kind": "bubble", "order": 0}

    before = region_from_record(rec, img)
    find_balloons(img, [before])
    on_art_before = int((drawing & (before.place_mask() > 0)).sum())
    assert on_art_before > 0, "fixture is wrong: the balloon misses the drawing"

    rec["kind"] = "freefloat"
    _kind_changed(rec, "bubble")

    after = region_from_record(rec, img)
    find_balloons(img, [after])
    on_art_after = int((drawing & (after.place_mask() > 0)).sum())
    # A rounded tip can put a pixel or two inside the room: the scan ignores a
    # row carrying less ink than GROW_STOP, which is what lets sparse
    # screentone under a caption alone. The drawing itself is out.
    assert on_art_after < 0.01 * on_art_before, \
        f"the typesetting would still land on the drawing ({on_art_after}px)"
    # and it did not collapse back to the bare column of Japanese
    assert (after.place_mask() > 0).sum() > 41 * 280


def test_the_label_beats_a_stale_outline_on_the_way_back_in():
    """lee changed the type, saw it work, restarted, and got the panel back.

    Nothing rewrites the stored outline except the moment of the change
    itself, so a page saved before that — or a record the change never touched
    — reloaded with the balloon it used to have. The label has to win at the
    door every page comes back through, not only at the moment somebody
    clicks.
    """
    from mangatl.project import region_from_record

    img = np.full((600, 800, 3), 255, np.uint8)
    for k in range(120, 400, 22):
        cv2.rectangle(img, (600, k), (640, k + 14), (20, 20, 20), -1)
    rec = {"id": 1, "bbox": [600, 120, 41, 280],
           # the panel the balloon finder handed it, still in the record
           "bubble_bbox": [360, 60, 390, 480],
           "polygon": [[360, 60], [748, 62], [750, 540], [360, 540]],
           "kind": "freefloat", "order": 0}
    r = region_from_record(rec, img)
    assert r.bubble_mask is None, "a stale outline came back as a balloon"


def test_a_stale_outline_does_not_become_writing_to_erase():
    """The same rectangle is where the WRITING is read from. Reading it out of
    a panel-sized outline would hand the cleaner a whole panel to erase."""
    from mangatl.project import region_from_record

    img = np.full((600, 800, 3), 255, np.uint8)
    cv2.circle(img, (480, 300), 110, (30, 30, 30), -1)      # artwork
    for k in range(120, 400, 22):
        cv2.rectangle(img, (600, k), (640, k + 14), (20, 20, 20), -1)
    rec = {"id": 1, "bbox": [600, 120, 41, 280],
           "bubble_bbox": [360, 60, 390, 480],
           "polygon": [[360, 60], [748, 62], [750, 540], [360, 540]],
           "kind": "freefloat", "order": 0}
    r = region_from_record(rec, img)
    drawing = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(drawing, (480, 300), 110, 255, -1)
    assert not ((drawing > 0) & (r.text_mask > 0)).any(), \
        "the cleaner was handed the artwork to erase"


def test_speech_still_reads_its_outline_back():
    from mangatl.project import region_from_record
    img = np.full((600, 800, 3), 255, np.uint8)
    rec = {"id": 1, "bbox": [600, 120, 41, 280],
           "bubble_bbox": [360, 60, 390, 480],
           "polygon": [[360, 60], [748, 62], [750, 540], [360, 540]],
           "kind": "bubble", "order": 0}
    assert region_from_record(rec, img).bubble_mask is not None
