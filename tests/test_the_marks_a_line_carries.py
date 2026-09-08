"""A heart in a line reaches the page.

lee, with a crop of 「これから本番♥」: *"i want teh read text to be able to read
stuff like haearts and other thiungs that text can usualy have like in the
picture i wan a big librey of icons that can be put there"*.

## Why it did not, and it was not the reader

Three prompts each told the model to take it out, and the middle one says why:

    "Use plain punctuation that comic typesetting fonts can actually draw"
    "decorative symbols, music notes and source-language punctuation are not"

That rule was RIGHT. Measured over the sixteen faces this app ships, against
eighteen marks manga uses:

    ComicNeue (the speech face)     none at all
    Bangers, Chewy, Luckiest Guy    none
    Jua                             heart, hollow heart, star, hollow star
    Patrick Hand                    heart

So a heart the translator let through came out as an empty box on the page, and
stripping it was the better of two bad answers. It is a consequence of the font
problem and not a matter of taste - which is why fixing the font problem is
what let the rule change.

The proofreader had its own version of it ("plain punctuation only") that would
have taken back out anything the translator kept. All three had to move
together or the last one wins.

## How a mark is drawn

The em-dash already worked this way and came first: a comic face that ships
only a hyphen still gets a real long dash, drawn by hand and stamped through
`ImageDraw.bitmap` so it takes the TEXT COLOUR. `typeset.mark_glyph`
generalises it, and returns the same `(advance, top, mask)` tuple so both go
down one drawing path in `render.draw_line` rather than two that can disagree.

Two sources, in order - lee: *"A with B behind it as a fallback"*:

1. `marks.py`, a shape drawn here. Round, short-pointed, the heart manga
   draws. Chosen over a font's after rendering both at size: a font's heart is
   angular with a long tail and reads as a playing card.
2. Any font on this machine that has the character. Nothing new is shipped for
   it - which, the day after two fonts had to be removed for licence reasons,
   is worth something.

...and if neither can, the character is left alone for the font to draw. A
mark that looks wrong beats a line that quietly says something else.

## What is NOT in scope

lee: *"the app shou only worry about symobys in the text not any other
symobs"*. A mark typeset among the words is in; a sound painted on the artwork
is a sound effect with a box of its own, and a balloon holding nothing but a
mark still gets deleted after the read exactly as it did.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import marks as M
from mangatl import render as R
from mangatl import typeset as T
from mangatl.models import TextRegion
from where import PKG

FONTS = PKG / "fonts"
SPEECH = str(FONTS / "ComicNeue-Bold.ttf")


# ------------------------------------------------- the measurement behind it

def test_the_speech_face_really_cannot_draw_any_of_them():
    """The premise. If this ever goes green-for-the-wrong-reason - somebody
    ships a face with a heart - the whole substitution stops being needed for
    that face, and `mark_glyph` returning None is how it notices."""
    have = [c for c in M.CHARS if T.font_supports(SPEECH, c)]
    assert not have, have


def test_and_the_two_faces_that_can_are_left_alone():
    """Jua and Patrick Hand have a heart of their own. A drawn substitute in
    either would be a stranger dropped into a line that already had the
    letter - and it is the FONT'S heart that matches its own weight."""
    for name in ("Jua-Regular.ttf", "PatrickHand-Regular.ttf"):
        path = str(FONTS / name)
        assert T.font_supports(path, "♥"), name
        assert T.mark_glyph(path, 40, "♥") is None, name


# ------------------------------------------------------------ drawing one

@pytest.mark.parametrize("ch", list(M.CHARS))
def test_every_mark_in_the_picker_can_actually_be_drawn(ch):
    """A character the picker offers and the app then refuses to draw is a
    button that does nothing. Either the shape is here or a font on this
    machine has it."""
    got = T.mark_glyph(SPEECH, 40, ch)
    assert got is not None, ch
    adv, _top, mask = got
    assert adv > 0 and mask.width > 0 and mask.height > 0, (ch, got)


def test_a_mark_is_as_tall_as_the_capitals():
    """It sits in a line of type, so it is measured against the type. Not the
    em, which would make it enormous, and not the baseline-to-ascender, which
    would leave it floating."""
    cap = T._glyph_ink(SPEECH, 60, "H")
    assert cap
    for ch in "♥★♪":
        _adv, _top, mask = T.mark_glyph(SPEECH, 60, ch)
        assert abs(mask.height - cap[0].height * T.MARK_CAP) <= 2, ch


def test_marks_are_scaled_by_their_INK_and_not_by_their_box():
    """The shapes fill different amounts of the 100x100 box they are drawn in -
    a heart spans 6..90, a sweat drop 12..72. Scaling by the box made the drop
    two thirds the height of the heart beside it and it read as a smaller size
    of type."""
    hs = [T.mark_glyph(SPEECH, 60, ch)[2].height for ch in "♥★♪\U0001f4a7"]
    assert max(hs) - min(hs) <= 1, hs


def test_a_hollow_mark_is_the_open_version_of_the_solid_one():
    """lee: *"also add hearts that are hallow"*. ♡ next to ♥ is the open
    heart next to the filled one - since the marks come from real faces the
    two are a type designer's pair rather than one path drawn twice, so what
    is pinned is what matters: same height, much less ink, but not none."""
    solid = T.mark_glyph(SPEECH, 80, "♥")[2]
    hollow = T.mark_glyph(SPEECH, 80, "♡")[2]
    assert abs(solid.height - hollow.height) <= 1
    ink = lambda m: (np.asarray(m) > 128).mean()
    assert ink(hollow) < ink(solid) * 0.75, (ink(hollow), ink(solid))
    assert ink(hollow) > 0.05, "the outline vanished"


def test_every_picker_mark_is_drawn_by_the_app_itself():
    """No tofu, by construction. The picker used to lean on "whatever font on
    this machine has it" for half its rows, and on lee's own machine that was
    twelve grey squares: Windows fonts cover ♫ and ☺ (code-page leftovers)
    and not ♬ or ☹. Since the redo every offered character has a shape in
    `marks.py`, so what the picker shows cannot depend on whose disk the app
    is running from."""
    undrawn = [c for c in M.CHARS if not M.for_char(c)]
    assert not undrawn, undrawn


def test_the_bundled_mark_faces_cover_the_whole_picker():
    """lee: *"instad of making your own glyphs find some charter only and use
    those"*. The three subsets in fonts/marks/ ARE the library now: between
    them every character the picker offers has a real glyph, so the picture
    on the page is a type designer's and the same on every machine."""
    faces = T._mark_faces()
    assert len(faces) == 3, faces
    for ch in M.CHARS:
        assert any(T.font_supports(p, ch) for p in faces), ch


def test_a_marks_picture_comes_from_a_face_and_not_the_hand_drawn_set():
    """The order of lee's ask: face first, hand shape only when the face
    files are missing. ♥ is in both, so ♥ is the character that proves the
    preference."""
    got = T.mark_glyph(SPEECH, 60, "♥")[2]
    face = T._font_mask(T._mark_faces()[0], "♥", got.height)
    assert face is not None
    assert got.tobytes() == face.tobytes(), \
        "the heart on the page is not the bundled face's heart"


def test_the_mark_faces_travel_with_their_licence():
    """OFL subsets, renamed as the licence requires of a modified copy - and
    written down in the same manifest every bundled face answers to."""
    import os
    lic = os.path.join(os.path.dirname(os.path.abspath(SPEECH)),
                       "LICENSES.md")
    text = open(lic, encoding="utf-8").read()
    for name in ("marks-emoji.ttf", "marks-symbols.ttf", "marks-music.ttf"):
        assert name in text, "%s left without saying where it came from" % name


def test_the_donor_net_still_catches_what_the_shapes_do_not():
    """The B half of lee's *"A with B behind it as a fallback"* stays for a
    character a LINE carries that the shape library has never heard of - it
    is just no longer load-bearing for anything the picker offers."""
    got = T._donor_mask("—", 40)
    assert got is not None and got.height == 40, got


def test_no_two_marks_in_the_picker_draw_the_same_picture():
    """Two buttons that put the same thing on the page are one button and a
    question. ❤ was ♥, and ♫ and ♬ were both the single-note shape - three
    rows of the picker that did the same thing."""
    seen = {}
    for ch in M.CHARS:
        mask = T.mark_glyph(SPEECH, 48, ch)[2]
        key = (mask.size, bytes(mask.tobytes()))
        assert key not in seen, (ch, seen[key])
        seen[key] = ch


# ------------------------------------------------ ...and into the layout

def test_the_fitter_counts_the_width_it_will_really_take():
    """`_text_w` measures every candidate line. A stamped mark it does not
    count is a line the fitter thinks is narrower than it is, and the first
    thing anybody sees is a heart sitting on the balloon edge."""
    plain = T._text_w(SPEECH, 40, "HI")
    with_mark = T._text_w(SPEECH, 40, "HI♥")
    adv = T.mark_glyph(SPEECH, 40, "♥")[0]
    assert abs((with_mark - plain) - adv) < 1.5, (plain, with_mark, adv)


def test_two_marks_in_a_row_do_not_drift_apart():
    """Their side bearings ADD, which is the case that shows a bearing up. At
    the first value tried, `♪♪` came out with a fifth of an em between the two
    notes and read as a gap rather than a pair."""
    one = T.mark_glyph(SPEECH, 48, "♪")
    gap = one[0] - one[2].width
    assert gap <= 48 * 0.14, gap


def test_a_line_with_a_mark_still_fits_its_balloon():
    """End to end through the real fitter. The mark is wider than the letter
    the font would have drawn, so a line that fitted before must still fit."""
    m = np.zeros((290, 400), np.uint8)
    cv2.ellipse(m, (200, 145), (150, 95), 0, 0, 360, 255, -1)
    r = TextRegion(id=1, bbox=(50, 50, 300, 190), kind="bubble",
                   text_mask=None, bubble_mask=m, bubble_bbox=(50, 50, 300, 190))
    r.order, r.dst_text = 1, "THIS IS IT♥"
    cfg = T.TypesetConfig(font_path=SPEECH, min_font=11, max_font=48)
    lay = T.fit_region(r, cfg)
    assert lay.lines and any("♥" in ln for ln in lay.lines), lay.lines
    for line in lay.lines:
        assert T._text_w(SPEECH, lay.font_size, line) <= 300, line


# --------------------------------------------------------- and onto the page

def _draw(text, size=44, **kw):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (600, 140), kw.pop("bg", "white"))
    f = ImageFont.truetype(SPEECH, size)
    R.draw_line(ImageDraw.Draw(im), 300, 70, text, f, **kw)
    return np.asarray(im.convert("L"))


def test_a_mark_puts_ink_on_the_page():
    """The whole point, and the failure it replaces: `♥` in Comic Neue used to
    render as a tofu box."""
    with_mark = (_draw("HI♥", fill=(0, 0, 0)) < 128).sum()
    without = (_draw("HI", fill=(0, 0, 0)) < 128).sum()
    assert with_mark > without * 1.1, (with_mark, without)


def test_it_takes_the_text_colour_and_not_black():
    """A mark on a dark panel is white like the letters beside it. It is
    stamped through `ImageDraw.bitmap`, which takes a colour - painting the
    mask black would have been invisible on exactly the pages that need the
    most care."""
    a = _draw("HI♥", bg="black", fill=(255, 255, 255))
    assert (a > 200).sum() > 50, "nothing white was drawn"
    # ...and there is no black-on-black blob where the mark is
    assert (a > 200).sum() > (_draw("HI", bg="black",
                                    fill=(255, 255, 255)) > 200).sum()


def test_and_it_takes_the_outline_too():
    """Every other character on the page gets a halo on artwork. A mark
    without one is the one thing on the line that disappears into a dark
    panel."""
    plain = _draw("♥", bg="white", fill=(255, 255, 255))
    haloed = _draw("♥", bg="white", fill=(255, 255, 255),
                   stroke_width=4, stroke_fill=(0, 0, 0))
    assert (plain < 128).sum() == 0, "nothing to see without the outline"
    assert (haloed < 128).sum() > 100, "the outline was not drawn"


def test_the_dash_and_the_marks_go_down_one_path():
    """`em_dash_glyph` and `mark_glyph` return the same tuple on purpose, so
    `draw_line` has one table and one branch. Two drawing paths for one idea is
    two places for it to go wrong - and the dash's was there first."""
    import inspect
    src = inspect.getsource(R.draw_line)
    assert "stamps" in src
    assert src.count("_draw_stamp") == 1
    assert "_draw_em_dash" not in src


# ----------------------------------------------------- what stays out of it

def test_only_the_characters_on_the_list_are_ever_substituted():
    """lee: *"the app shou only worry about symobys in the text not any other
    symobs"*. A RULE - "anything outside Latin-1", say - would sweep up
    source-language punctuation, the long-vowel mark and every kanji on a page
    the reader failed to translate, and start stamping pictures over them."""
    for ch in "あ漢ー。、！？Aa1":
        assert ch not in T.MARK_CHARS, ch
        assert T.mark_glyph(SPEECH, 40, ch) is None, ch


def test_a_balloon_holding_only_a_mark_is_still_dropped():
    """Unchanged, and asked for. A mark IN a line is what lee wanted; a box
    that is nothing but one is the symbols-only case he had already asked to
    have deleted after the read."""
    from mangatl.ocr import only_symbols
    assert only_symbols("♥") is True
    assert only_symbols("♥♥") is True
    assert only_symbols("YES♥") is False


def test_the_picker_and_the_substitution_agree():
    """One list. A mark offered but not drawable is a dead button; a mark
    drawable but not offered is one nobody can reach."""
    assert set(M.CHARS) <= T.MARK_CHARS
    assert set(M.GLYPHS) <= T.MARK_CHARS


# ------------------------------------------------------- and the prompts

def test_all_three_prompts_now_agree_that_a_mark_stays():
    """The reader transcribes it, the translator carries it, the proofreader
    leaves it alone. Any one of them still stripping marks undoes the other
    two - the proofreader runs last and would have won."""
    from mangatl import translate as TR
    ocr = TR.build_ocr_system("Japanese")
    tr = TR.build_system("manga", "en")
    pr = TR.build_proofread_system()
    assert "MARKS SET IN THE LINE ARE PART OF THE LINE" in ocr
    assert "A MARK THE SOURCE LINE CARRIES STAYS ON IT" in tr
    assert "A MARK IS NOT PUNCTUATION AND IS NOT YOURS TO TIDY" in pr


def test_and_none_of_them_may_invent_one():
    """The half of the old rule that was always right. A mark the source does
    not have is decoration somebody's model reached for, and it goes onto the
    artwork as though the artist drew it."""
    from mangatl import translate as TR
    assert "does NOT let you add one" in TR.build_system("manga", "en")
    assert "not there" in TR.build_ocr_system("Japanese")
