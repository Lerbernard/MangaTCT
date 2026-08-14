"""A sound effect the page has selected always gets cleaned.

lee, with a screenshot of an untouched sound effect on page 12 and another on
page 1:

* *"the sfx is not gettig clened that the biggest issiue"*
* *"both pages have that, it unacceaptable, ill ratter have it do a bad job
  then not do it at all look into it and make sure that teh cleaner donet skip
  cleaning sfx tht are slected"*

The cause is one line in `models.place_mask()`: a sound effect is handed **its
own ink** as its area, because for TYPESETTING that is right — an sfx is drawn
along an axis of its own and belongs exactly where the original was, not
spread over a rectangle drawn round it. For CLEANING it is ruinous. Every
measurement the cleaner makes about the area around the writing is then taken
over the writing itself:

* `ink_and_background`'s rim vote reads `area & ~erode(area, 7x7)`, which for a
  mask of strokes is nearly the whole mask — so "is the background dark?" is
  answered by looking at the letters.
* `_flat_from` stands off the ink to sample a background and finds nothing.
* `_with_halo`'s halo is a subset of the ink, so it can add nothing.

When that vote comes back `inverted`, `inpaint_page` used to throw the
detector's mask away and replace it with `_letterlike(polar)` — the letter-
shaped part of an Otsu split of the page. On a plain dark sfx over dark hatched
artwork the split hands back the bright hatch lines, `_letterlike` keeps a few
specks of them, and the sound effect is left on the page with a fraction of it
rubbed out.

The replacement's own justification cannot apply to an sfx: it exists because a
dark-ink detector mask on a black panel is the PANEL rather than the words, and
an sfx's mask comes off the segmentation head and is the mark itself. So it is
skipped for sfx — `inverted` still stands, because the halo, the stroke
completion and the ghost check all need to know which way the ink runs.

The second half is the safety net lee asked for: the empty-mask fallback now
reaches the detector's own `text_mask`, not what is left of it after the
filters. The filter most able to empty it ran BEFORE the value the fallback
fell back to, so "fall back to the detector's mask" fell back to nothing.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion
from mangatl.typeset import _font, default_font_path

H, W = 300, 220


def _draw(base, txt, size, fill, sw=0, edge=255, xy=(110, 140)):
    p = Image.fromarray(base)
    d = ImageDraw.Draw(p)
    d.text(xy, txt, font=_font(default_font_path(), size), fill=fill,
           anchor="mm", stroke_width=sw, stroke_fill=edge, align="center")
    return np.array(p)


def _hatched():
    """Dark artwork with fine bright hatching over it — what lee's sfx sit on."""
    a = np.full((H, W), 30, np.uint8)
    for y in range(0, H, 9):
        cv2.line(a, (0, y), (W, y - 70), 90, 2)
    return a


def _sfx_page(sw=0, edge=15, fill=15, size=54, txt="GUBA"):
    """The page, and the mask the segmentation head would return for the mark.

    The mask is taken by drawing the same mark on black, so it is exactly the
    ink and nothing else — which is what that head gives, and the reason its
    answer is worth keeping.
    """
    img = _draw(_hatched(), txt, size, fill, sw, edge)
    probe = _draw(np.zeros((H, W), np.uint8), txt, size, 255, sw, 255)
    return img, (probe > 0).astype(np.uint8) * 255


def _dark_panel():
    """White typesetting on a black panel — the case the replacement exists for.

    Here the detector's dark-ink mask really IS the panel, so replacing it is
    right, and this file must not break that.
    """
    img = np.full((H, W), 245, np.uint8)
    cv2.rectangle(img, (40, 80), (190, 220), 18, -1)
    img = _draw(img, "WHO IS\nTHERE", 26, 250, xy=(115, 150))
    sel = np.zeros((H, W), bool)
    sel[100:200, 50:180] = True
    tm = np.zeros((H, W), np.uint8)
    tm[(img <= 110) & sel] = 255
    return img, tm


def _gone(before, after, tm):
    """How much of the MARK is left, said as the thing that matters: is the
    shape of it still darker (or lighter) than the artwork around it.

    Not "how many pixels changed", which was the old measure and cannot tell a
    repair from a residue. These marks sit on hatching, and the redraw step
    carries the hatch lines back across the patch — putting a pixel back to
    what the artwork had there is the whole object of that step, and it counts
    as a pixel that did not change.
    """
    ink = tm > 0
    ring = (cv2.dilate(tm, np.ones((11, 11), np.uint8)) > 0) & ~ink
    was = abs(float(before[ink].mean()) - float(before[ring].mean()))
    now = abs(float(after[ink].mean()) - float(after[ring].mean()))
    return now / max(1e-6, was)


def _clean(img, tm, kind):
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind=kind, text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    out = I.inpaint_page(page)
    after = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    moved = cv2.absdiff(after, img) > 8
    page.mark_left = _gone(img.astype(float), after.astype(float), tm)
    return r, page, float(moved[tm > 0].mean()), moved


# ------------------------------------------------------ the reported failure

def test_a_plain_dark_sound_effect_on_dark_art_is_erased():
    """lee's page 12, box 5. Measured before the fix: 7% of the mark gone."""
    img, tm = _sfx_page()
    r, page, erased, _moved = _clean(img, tm, "sfx")
    assert page.mark_left < 0.15, page.mark_left
    assert page.clean_stats.get("kept", 0) == 0
    assert page.clean_stats.get("skipped", 0) == 0


def test_an_outlined_sound_effect_on_dark_art_is_erased():
    """lee's page 1, box 2 — the same mark drawn with a white keyline round
    it, which is how most sound effects over artwork are drawn."""
    img, tm = _sfx_page(sw=5, edge=250)
    r, page, erased, _moved = _clean(img, tm, "sfx")
    assert page.mark_left < 0.15, page.mark_left


def test_the_polarity_vote_is_meaningless_for_a_sound_effect():
    """Why, not just that. The rim `ink_and_background` votes on is the area
    minus its own 7x7 erosion; for a mask of strokes that is nearly the whole
    mask, so the question "is the background dark?" is answered by looking at
    the letters. This pins the degenerate geometry rather than any particular
    answer it happens to give."""
    img, tm = _sfx_page()
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="sfx", text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    area = r.place_mask()
    assert area is tm, "an sfx no longer gets its ink as its area; rewrite this"
    a = area > 0
    rim = a & ~(cv2.erode(a.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
    assert float(rim.sum()) / float(a.sum()) > 0.8, \
        "the rim is no longer the whole mask; the reasoning here has changed"


def test_the_detectors_mask_is_kept_for_a_sound_effect():
    """The change itself. Whatever `ink_and_background` votes, an sfx erases
    what the segmentation head found — most of it, and not a few specks of
    hatching."""
    img, tm = _sfx_page()
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="sfx", text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    win = I._window(img.shape, r.place_mask(), tm > 0)
    polar, _lvl, inverted = I.ink_and_background(
        img[win], r.place_mask()[win] > 0, tm[win] > 0)
    assert inverted, "the vote no longer comes back inverted here; refixture"
    kept = int((I._letterlike(polar) > 0).sum())
    assert kept < 0.2 * int((tm > 0).sum()), (kept, int((tm > 0).sum()))
    # …and that is exactly what is NOT used.
    _r, page, erased, _moved = _clean(img, tm, "sfx")
    assert page.mark_left < 0.15, page.mark_left


# ------------------------------------------------------- and what must not change

def test_white_typesetting_on_a_black_panel_still_gets_the_split():
    """The replacement stays where it belongs. Here the detector's dark-ink
    mask is the panel, and erasing it would take the artwork with it — so the
    letter-shaped part of the split is what gets erased, and only a small
    fraction of the panel mask is touched."""
    img, tm = _dark_panel()
    r, _page, erased, moved = _clean(img, tm, "free")
    assert erased < 0.25, erased            # not the panel
    assert int(moved.sum()) > 400, int(moved.sum())   # but the words did go
    # the words are the bright pixels inside the panel; they must be gone
    sel = np.zeros((H, W), bool)
    sel[100:200, 50:180] = True
    letters = (img >= 200) & sel
    assert letters.any()
    assert float(moved[letters].mean()) > 0.5, float(moved[letters].mean())


def test_a_sound_effect_with_the_eye_closed_is_still_left_alone():
    """"Never skip an sfx" is about the cleaner's own decisions, not about
    lee's. The per-region keep toggle still keeps."""
    img, tm = _sfx_page()
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="sfx", text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    r.skip_clean = True
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    out = I.inpaint_page(page)
    assert np.array_equal(out, bgr)
    assert page.clean_stats.get("kept") == 1


# ------------------------------------------------------------- the safety net

def test_an_emptied_mask_falls_back_to_what_the_detector_found():
    """lee: *"ill ratter have it do a bad job then not do it at all"*.

    Every filter in the chain is a judgement about WHICH ink to erase, and
    none of them is a reason to erase none of it. Emptied here by forcing the
    containment filter to return nothing — the fallback must still put the
    detector's mask back and say so in the flag."""
    img, tm = _sfx_page()
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="sfx", text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    was = I.glyphs_only
    I.glyphs_only = lambda *a, **k: np.zeros((H, W), np.uint8)
    try:
        out = I.inpaint_page(page)
    finally:
        I.glyphs_only = was
    left = _gone(img.astype(float),
                 cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(float), tm)
    assert left < 0.15, left
    assert "fell back to the detector" in (r.flagged or ""), r.flagged


def test_the_fallback_reaches_past_the_letterlike_filter():
    """The bug inside the bug. The fallback used to fall back to `base_u8` —
    the detector's mask AFTER `_letterlike` had run on it — and `_letterlike`
    is the filter most able to empty it. Empty it there, and the old fallback
    had nothing to give back."""
    img, tm = _dark_panel()
    x, y, w, h = cv2.boundingRect(tm)
    r = TextRegion(id=1, bbox=(x, y, w, h), kind="free", text_mask=tm,
                   bubble_mask=None, bubble_bbox=(x, y, w, h))
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    page = Page(image=bgr.copy())
    page.original = bgr.copy()
    page.regions = [r]
    was = I._letterlike
    I._letterlike = lambda m: np.zeros(np.asarray(m).shape[:2], np.uint8)
    try:
        out = I.inpaint_page(page)
    finally:
        I._letterlike = was
    moved = cv2.absdiff(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), img) > 8
    assert int(moved.sum()) > 400, int(moved.sum())
    assert "fell back to the detector" in (r.flagged or ""), r.flagged
