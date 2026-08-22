"""Typesetting that comes back the colour of the Japanese it replaces.

The old rule read the brightness of the cleaned plate and called anything below
a threshold "dark". That is wrong on the page shape this file is built around:
a balloon filled with fine hatching, whose average brightness lands in the
middle of the range whichever way round it was drawn. Averaged, a black balloon
under light hatching and a white balloon under dark hatching are the SAME
NUMBER - so the old rule cannot tell them apart even in principle, and typeset
white-on-black speech in black.

``original_tone`` does not average anything. It asks the original scan which of
its two populations the writing was, by the one property writing has: there is
more of it inside the text box than there is around it.

The pages here are drawn rather than loaded, so the tests run anywhere and each
one names the property that broke.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from PIL import Image, ImageDraw

from mangatl.models import TextRegion
from mangatl.render import DARK_BG, _ink_colours, original_tone
from mangatl.typeset import _font, default_font_path

H, W = 300, 400
CX, CY, RX, RY = 200, 150, 150, 110
BOX = (120, 100, 160, 80)          # the text box, well inside the balloon

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


class _Layout:
    """Just enough of a TextLayout for the colour pass."""
    font_size = 30
    line_origins = [(200, 120), (200, 158)]


def _balloon_mask():
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (CX, CY), (RX, RY), 0, 0, 360, 255, -1)
    return m


def _page(fill, hatch, ink):
    """A page with one elliptical balloon, optionally hatched, with text in it.

    ``fill`` paints the balloon, ``hatch`` (or None) rules vertical lines
    across it, and ``ink`` is the colour the two lines of typesetting are drawn
    in. Returns the BGR page and the region describing the text inside it.
    """
    img = np.full((H, W), 255, np.uint8)
    cv2.ellipse(img, (CX, CY), (RX, RY), 0, 0, 360, fill, -1)
    if hatch is not None:
        for x in range(CX - RX, CX + RX, 2):
            cv2.line(img, (x, CY - RY), (x, CY + RY), hatch, 1)
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img[_balloon_mask() == 0] = 255           # keep the hatch inside the oval

    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    f = _font(default_font_path(), 30)
    for i, line in enumerate(("HELLO", "THERE")):
        d.text((CX, 120 + i * 38), line, font=f, fill=ink, anchor="mm")
    img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    region = TextRegion(id="r1", bbox=BOX,
                        bubble_bbox=(CX - RX, CY - RY, 2 * RX, 2 * RY))
    region.bubble_mask = _balloon_mask()
    return img, region


def _balloon_mean(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(g[_balloon_mask() > 0].mean())


# fill, hatch, ink, the tone that should come back
PLAIN = [
    ("white balloon, black writing", 255, None, BLACK, -1),
    ("black balloon, white writing", 20, None, WHITE, +1),
]
HATCHED = [
    ("dark balloon under light hatching", 10, 245, WHITE, +1),
    ("light balloon under dark hatching", 255, 20, BLACK, -1),
]


@pytest.mark.parametrize("name, fill, hatch, ink, want", PLAIN + HATCHED)
def test_tone_follows_the_original_writing(name, fill, hatch, ink, want):
    img, region = _page(fill, hatch, ink)
    assert original_tone(img, region) == want, name


@pytest.mark.parametrize("name, fill, hatch, ink, want", HATCHED)
def test_hatching_defeats_the_brightness_rule(name, fill, hatch, ink, want):
    """The hatched pages are the ones brightness cannot answer.

    Both of them average out to roughly the same middling number, on the light
    side of the threshold - so brightness alone typesets both of them black, and
    is wrong about one. This test is what makes the new rule load-bearing: it
    fails the moment the colour decision goes back to reading the background.
    """
    img, region = _page(fill, hatch, ink)
    mean = _balloon_mean(img)
    assert mean > DARK_BG, (
        f"{name}: the point of this case is that averaging calls it light "
        f"(mean {mean:.0f} vs threshold {DARK_BG})")
    fg, edge, _ = _ink_colours(img, region, _Layout, False, orig=img)
    if want > 0:
        assert fg[:3] == WHITE and edge[:3] == BLACK, name
    else:
        assert fg[:3] == BLACK and edge[:3] == WHITE, name


def test_white_writing_survives_the_clean():
    """The colour comes from the ORIGINAL, not from the plate being drawn on.

    By typesetting time the balloon has been cleaned flat, and on a dark balloon
    the cleaner may well fill it with something bright. The original is the
    only witness left to what colour the speech was.
    """
    orig, region = _page(10, 245, WHITE)
    cleaned = np.full_like(orig, 30)          # cleaned flat, and dark
    fg, edge, _ = _ink_colours(cleaned, region, _Layout, False, orig=orig)
    assert fg[:3] == WHITE and edge[:3] == BLACK


def test_no_original_falls_back_to_the_background():
    """With nothing to compare against, the old brightness rule still runs."""
    dark = np.full((H, W, 3), 20, np.uint8)
    region = TextRegion(id="r1", bbox=BOX)
    region.bubble_mask = _balloon_mask()
    fg, _, _ = _ink_colours(dark, region, _Layout, False, orig=None)
    assert fg[:3] == WHITE

    light = np.full((H, W, 3), 250, np.uint8)
    fg, _, _ = _ink_colours(light, region, _Layout, False, orig=None)
    assert fg[:3] == BLACK


def test_flat_crop_says_nothing():
    """A box with no writing in it must not invent an answer."""
    flat = np.full((H, W, 3), 200, np.uint8)
    region = TextRegion(id="r1", bbox=BOX)
    region.bubble_mask = _balloon_mask()
    assert original_tone(flat, region) == 0
    assert original_tone(None, region) == 0
    assert original_tone(flat, TextRegion(id="r2", bbox=(0, 0, 0, 0))) == 0


def test_outline_on_art_defaults_to_two():
    """Anything with artwork behind it gets a real edge, not a hairline.

    Nothing out on the artwork has paper behind it, so the outline is the whole
    of its legibility. What decides the question is whether a balloon was ever
    found round the words - NOT what the region is labelled. lee's on-art
    captions come through as `narration`, which is a perfectly good description
    of what they say and no description at all of what is behind them, and they
    were the ones typeset with a hairline over the art.
    """
    from mangatl.typeset import (OUTLINE_IN_BUBBLE, OUTLINE_ON_ART,
                                 default_stroke, on_art)

    assert OUTLINE_ON_ART == 2

    # No balloon anywhere: whatever it is called, it is out on the art.
    for kind in ("sfx", "freefloat", "narration", "bubble"):
        r = TextRegion(id=kind, bbox=BOX, kind=kind)
        assert on_art(r) is True, kind
        assert default_stroke(r) == OUTLINE_ON_ART, kind

    # A balloon was found: there is paper behind the words.
    for kind in ("bubble", "narration"):
        r = TextRegion(id=kind, bbox=BOX, kind=kind)
        r.bubble_mask = _balloon_mask()
        assert on_art(r) is False, kind
        assert default_stroke(r) == OUTLINE_IN_BUBBLE, kind

    # Sound effects are drawn over the art even when one is found round them.
    sfx = TextRegion(id="sfx", bbox=BOX, kind="sfx")
    sfx.bubble_mask = _balloon_mask()
    assert default_stroke(sfx) == OUTLINE_ON_ART

    # Small type inside a bubble is the one place a hairline is right.
    class Tiny:
        font_size = 10
        line_origins = [(200, 130)]

    light = np.full((H, W, 3), 250, np.uint8)
    region = TextRegion(id="r1", bbox=BOX)
    region.bubble_mask = _balloon_mask()
    assert _ink_colours(light, region, Tiny, False)[2] == OUTLINE_IN_BUBBLE
    assert _ink_colours(light, region, Tiny, True)[2] == OUTLINE_ON_ART


# ------------------------------------------------- after a chapter is reloaded

def _forget_masks(region):
    """Put a region into the state a saved chapter comes back in.

    ``TextRegion.to_dict`` drops the masks, so nothing that is written to disk
    remembers the shape of the balloon. Every region in a reopened chapter
    therefore has ``place_mask() is None`` - and that, not anything about the
    artwork, is why lee's reloaded pages typeset white speech in black.
    """
    region.bubble_mask = None
    region.text_mask = None
    assert region.place_mask() is None
    return region


@pytest.mark.parametrize("name, fill, hatch, ink, want", PLAIN + HATCHED)
def test_tone_still_reads_after_a_reload(name, fill, hatch, ink, want):
    """No balloon mask, same answer.

    The inside-versus-around test needs something to call "around". It used to
    ask the balloon, and with no balloon it gave up and guessed - which is the
    one case that actually matters, because a chapter is reloaded far more
    often than it is first opened. A ring drawn just outside the text box is
    background wherever a text box is a text box, so the test can still run.
    """
    img, region = _page(fill, hatch, ink)
    assert original_tone(img, _forget_masks(region)) == want, name


def test_white_speech_survives_a_reload_end_to_end():
    """The whole colour decision, on the page shape lee reported.

    Dark hatched balloon, white Japanese, cleaned flat by the time typesetting
    runs, and no masks left after the reload. Every one of those is true of the
    page in the screenshot, and together they used to produce black typesetting.
    """
    orig, region = _page(10, 245, WHITE)
    cleaned = np.full_like(orig, 90)          # cleaned to a middling grey
    fg, edge, _ = _ink_colours(cleaned, _forget_masks(region), _Layout, False,
                               orig=orig)
    assert fg[:3] == WHITE and edge[:3] == BLACK


# ------------------------------------------------------ tone, not an average

def _toned_plate(fill, hatch, step, thick):
    """A cleaned plate whose balloon is a screentone rather than a flat fill."""
    img = np.full((H, W), 255, np.uint8)
    cv2.ellipse(img, (CX, CY), (RX, RY), 0, 0, 360, fill, -1)
    for x in range(CX - RX, CX + RX, step):
        cv2.line(img, (x, CY - RY), (x, CY + RY), hatch, thick)
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img[_balloon_mask() == 0] = 255
    return img


def test_mostly_dark_paper_typesets_white_even_when_it_averages_light():
    """With no original to ask, how much of the paper is dark decides.

    A dark balloon ruled with bright lines averages up past the threshold while
    remaining, pixel for pixel, mostly black - and black typesetting on mostly
    black paper cannot be read whatever the average says. The question the
    fallback asks is the answerable one: what is under the words?
    """
    plate = _toned_plate(60, 255, 8, 2)      # ~5/8 of the paper is near-black
    region = TextRegion(id="r1", bbox=BOX)
    region.bubble_mask = _balloon_mask()
    assert _balloon_mean(plate) > DARK_BG, (
        "this case only tests something if averaging calls the balloon light")
    fg, edge, _ = _ink_colours(plate, region, _Layout, False, orig=None)
    assert fg[:3] == WHITE and edge[:3] == BLACK
