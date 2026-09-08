"""The mask a saved region is rebuilt with, and the day it was the shirt.

lee, with a crop of a sound effect erased off a screentone shirt, the whole box
of tone rebuilt and its rectangle plainly visible: *"see how i can see the lines
of teh clenner that shoud not happen it should clenly fit with teh art and there
still some box error"*.

## What the mask was

A region is stored as geometry - a polygon and some metadata, never a bitmap,
because a 40-page chapter with eight bubbles a page would sit on close to a
gigabyte of masks. So every clean after the first rebuilds the glyph mask from
the only thing geometry can give:

    glyph = (gray <= INK) & (inside the box)

THE DARK PIXELS IN THE BOX. On a white bubble that is the words and nothing
else, which is why it stood for so long. On lee's page 013 it is the shirt:
a white-outlined `クルッ` over a horizontal line screen has 11,352 dark pixels
in its box and the letters are not among them. The mask was every tone line,
the whole rectangle went to the model, and what came back was a rebuilt patch
of tone with the shape of the box in it.

Measured over his 221 regions, every rescue in `inpaint_page` and both of the
obvious repairs:

    `_letterlike` on that box            11,352 -> 7,179    still the tone
    keep the components the reader
      touches                            11,352 -> 8,113    the panel is one
                                                            component, so on a
                                                            black balloon this
                                                            keeps 167% of the box
    what the reader says                 11,352 -> 5,066    the letters

The comment `_letterlike` used to end with says exactly this: *"What is needed
is a reading of WHAT the split found that the mask did not - rows of letters,
or scattered dots - and neither the ratio nor the tone test is that."* The text
segmenter is that reading, and the app already runs it - it is what found the
boxes in the first place. Cleaning was using a stand-in for its answer.

## and where the stand-in is not a guess

On a fully white bubble "darker than the background" IS the writing, exactly
and completely, because the background is one known colour. There the reader
has nothing to add and something to lose: on a plain block-font word it finds
431 pixels of 2,884, and acting on that turns a box the flat fill takes off
perfectly into a box with the word still legibly on it. So the reader is asked
everywhere EXCEPT there. See `_plain_paper`.

Measured on lee's chapter, the reader against the rebuilt mask, 221 regions:

    median                        1.92x   the reader finds MORE - it sees the
                                          white outline no dark threshold can
    below half                    10      every one a black panel, a screentone
                                          or a caption on artwork: cases where
                                          the rebuilt mask is the ARTWORK
    painted inside the boxes      964,148 -> 934,942
    still reads as text after          20 ->      50 px, over the whole chapter
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I
from mangatl.models import Page, TextRegion


# ------------------------------------------------------------- the fixtures

def _tone_page(w=300, h=300):
    """A horizontal line screen, which is what lee's shirt is."""
    img = np.full((h, w, 3), 255, np.uint8)
    img[::3] = 60
    return img


def _sfx_on_tone():
    """A white-outlined mark over the tone: the letters are not the dark
    pixels in the box, and the dark pixels in the box are the shirt."""
    img = _tone_page()
    cv2.putText(img, "!!", (110, 190), cv2.FONT_HERSHEY_SIMPLEX, 3.0,
                (255, 255, 255), 22)
    cv2.putText(img, "!!", (110, 190), cv2.FONT_HERSHEY_SIMPLEX, 3.0,
                (0, 0, 0), 9)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    box = np.zeros(g.shape, bool)
    box[110:210, 100:210] = True
    r = TextRegion(id=0, bbox=(100, 110, 110, 100), kind="sfx",
                   text_mask=((g <= 128) & box).astype(np.uint8) * 255,
                   bubble_mask=None)
    r.src_text, r.order = "a", 0
    page = Page(image=img, source_path="t.png")
    page.regions = [r]
    return page


def _letters(page):
    """A reader that says what the letters are, and calls the tone artwork."""
    g = cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
    m = np.zeros(g.shape, np.uint8)
    cv2.putText(m, "!!", (110, 190), cv2.FONT_HERSHEY_SIMPLEX, 3.0, 255, 24)
    return lambda img: m.copy()


def test_the_rebuilt_mask_is_the_screentone():
    """The fixture has to have the bug in it, or the test below proves
    nothing."""
    page = _sfx_on_tone()
    r = page.regions[0]
    x, y, w, h = r.bbox
    share = float((r.text_mask[y:y + h, x:x + w] > 0).mean())
    assert share > 0.25, "the dark pixels in this box are the tone: %.2f" % share


def test_and_the_reader_is_asked_instead():
    page = _sfx_on_tone()
    r = page.regions[0]
    seen = I._looked(_letters(page), page.image, page.image.shape)
    told = I._reader_ink(seen, r, page.image.shape)
    assert told is not None
    # What it keeps is the letters, and the tone away from them it does not.
    # The corner of the box is shirt in both readings and writing in neither.
    x, y, w, h = r.bbox
    corner = (slice(y, y + 20), slice(x, x + 8))
    assert (r.text_mask[corner] > 0).any(), "the fixture's corner is tone"
    assert not told[corner].any(), "the reader kept the shirt"


def test_the_whole_box_is_erased_no_longer():
    """The bug was the WHOLE box: every dark pixel in it is the shirt, so the
    shirt went and a rebuilt rectangle of tone came back with the box's shape
    printed in it.

    Half, and not the third it used to be. The doorstep no longer adopts tone
    the reader's mask happens to touch - 416px of it here - which is the right
    answer about the mask and has a second-order cost on this fixture: tone
    deliberately LEFT inside a cleaned box is exactly what `_sweep_ghosts`
    reads as a clean that failed, so it repaints wider. The same effect was
    recorded when the containment rule went into `_off_the_ground` ("ink still
    standing in a cleaned box" went up while the detector-visible number stayed
    flat), and it does not appear in the aggregate on real pages: over lee's 23
    pages the doorstep rule paints 866,776px where it used to paint 875,308.
    What this test is for is the rectangle, and half a box is not one.
    """
    page = _sfx_on_tone()
    before = page.image.copy()
    I.inpaint_page(page, look=_letters(page))
    r = page.regions[0]
    x, y, w, h = r.bbox
    changed = (np.abs(before.astype(int) - page.clean_plate.astype(int))
               .max(2) > 12)[y:y + h, x:x + w]
    assert float(changed.mean()) < 0.50, \
        "%.0f%% of the box was repainted" % (100 * changed.mean())


def test_and_without_a_reader_it_still_is():
    """The old behaviour is exactly the old behaviour: a project with no
    detector weights, or the switch off, cleans the page it always did."""
    page = _sfx_on_tone()
    before = page.image.copy()
    I.inpaint_page(page, look=None)
    r = page.regions[0]
    x, y, w, h = r.bbox
    changed = (np.abs(before.astype(int) - page.clean_plate.astype(int))
               .max(2) > 12)[y:y + h, x:x + w]
    assert float(changed.mean()) > 0.40


# ------------------------------------------- and the background it is not asked on

def _white_bubble():
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 120, (0, 0, 0), 3)
    cv2.putText(img, "GO", (90, 175), cv2.FONT_HERSHEY_SIMPLEX, 2.0,
                (20, 20, 20), 8)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bm = np.zeros(g.shape, np.uint8)
    cv2.circle(bm, (150, 150), 116, 255, -1)
    box = np.zeros(g.shape, bool)
    box[130:190, 80:230] = True
    r = TextRegion(id=0, bbox=(80, 130, 150, 60), kind="bubble",
                   text_mask=((g <= 128) & box).astype(np.uint8) * 255,
                   bubble_mask=bm, bubble_bbox=(30, 30, 240, 240))
    r.src_text, r.order = "a", 0
    page = Page(image=img, source_path="t.png")
    page.regions = [r]
    return page


def _half_blind(page):
    """A reader that finds a seventh of the word - which is what a text
    segmenter trained on manga does with a plain block font."""
    r = page.regions[0]
    m = (r.text_mask > 0).copy()
    m[:, ::7] = False
    m[:, 1::7] = False
    m[:, 2::7] = False
    m[:, 3::7] = False
    m[:, 4::7] = False
    m[:, 5::7] = False
    return lambda img: m.astype(np.uint8) * 255


def test_a_ground_that_is_one_level_needs_nobody_asked():
    """On paper the writing is exactly what differs from the paper, and a
    reader can only lose there: given one that sees a seventh of the word, the
    box still comes out clean, because nothing was taken away from what the
    ground measured."""
    page = _white_bubble()
    r = page.regions[0]
    assert I._off_the_ground(cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY),
                             r.bbox) is not None
    out = I.inpaint_page(page, look=_half_blind(page))
    x, y, w, h = r.bbox
    assert int(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[y:y + h, x:x + w].min()) \
        > 200, "a reader that saw a seventh of the word shrank the mask"
    assert page.clean_stats.get("flat fill") == 1


def test_and_it_reads_white_on_black_the_same_way():
    """The median does not care which way round the tones run, which is the
    light/dark split and its rim vote replaced by a measurement. lee's page 009
    is a brushed black balloon: the ruby beside its kanji is six pixels of
    white, which `_letterlike` dropped as a speck and left in a column down the
    middle of the bubble."""
    img = np.full((300, 300, 3), 20, np.uint8)
    rng = np.random.default_rng(3)
    img = np.clip(img.astype(np.int16)
                  + rng.normal(0, 9, img.shape), 0, 255).astype(np.uint8)
    cv2.putText(img, "AB", (95, 175), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                (240, 240, 240), 5)
    cv2.putText(img, "..", (150, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (240, 240, 240), 1)        # the ruby, six pixels a mark
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    got = I._off_the_ground(g, (80, 100, 130, 90))
    assert got is not None, "a grainy black ground is still one ground"
    assert got[110:125, 148:175].any(), "the ruby went with the specks"


def test_and_a_tone_background_is_not_one_ground():
    page = _sfx_on_tone()
    g = cv2.cvtColor(page.image, cv2.COLOR_BGR2GRAY)
    assert I._off_the_ground(g, page.regions[0].bbox) is None


def test_nor_is_a_box_that_is_more_ink_than_ground():
    """A box so full of ink that the median IS the ink: the answer would be
    the paper, and painting that out is the box erased."""
    img = np.full((120, 120, 3), 255, np.uint8)
    img[20:100, 20:100] = 10
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert I._off_the_ground(g, (10, 10, 100, 100)) is None


def test_a_reader_that_claims_most_of_the_box_is_not_believed():
    page = _sfx_on_tone()
    r = page.regions[0]
    everything = np.ones(page.image.shape[:2], bool)
    assert I._reader_ink(everything, r, page.image.shape) is None


def test_a_reader_that_finds_nothing_leaves_the_mask_alone():
    page = _sfx_on_tone()
    r = page.regions[0]
    assert I._reader_ink(np.zeros(page.image.shape[:2], bool), r,
                         page.image.shape) is None


# --------------------------------------------- the white bubble and the model

def test_a_white_bubble_is_filled_locally_even_with_the_model_on_everything():
    """lee, having run a whole chapter with "AI for the whole page" and looked
    at a plain balloon the model had left one speck of a kana in: *"look into
    making the local clenner do teh white biexes because it did a bettr jib"*.

    Not a preference between two cleaners. On a white balloon the colour is
    KNOWN, so the fill is exactly right by construction, instant and free; a
    model is guessing at something that was never in doubt."""
    page = _white_bubble()
    asked = []
    out = I.inpaint_page(page, neural=lambda im, m: (asked.append(1), im)[1],
                         neural_all=True)
    assert not asked, "the model was asked about a plain white bubble"
    assert page.clean_stats.get("flat fill") == 1
    x, y, w, h = page.regions[0].bbox
    assert int(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[y:y + h, x:x + w].min()) > 200


def test_everything_else_still_goes_to_the_model():
    """"The whole page" still means the whole page - it is one background that
    is kept back, and only because nothing about it is in doubt."""
    page = _sfx_on_tone()
    asked = []
    I.inpaint_page(page, neural=lambda im, m: (asked.append(1), im)[1],
                   neural_all=True)
    assert asked, "the tone was not sent to the model"


def test_there_is_no_method_menu_left_to_get_it_wrong():
    """The menu is gone and the AI cleaner is THE cleaner. lee: *"also remove
    the option for no ai, i for tough boxes ad only ai and the card make this
    the deaflau clenner"*.

    The white-bubble rule outlives it, and the rule is the reason the menu
    could go: "the model cleans the page" is only a simple thing to say
    because the one case it does not cover is the one case nothing is in doubt
    about.

    The STORED default is the one thing that did not follow it, and it is
    worth saying why rather than leaving the difference to be found. A project
    whose settings have never been written starts at "off", because "all"
    there also turns page pre-warming off: `_worth_warming` will not build a
    page nobody has asked for when building it spends the hosted cleaner, and
    ten tests describe that consequence. The moment the settings panel is
    saved the UI writes "all", so what a person runs IS the AI cleaner - what
    the default buys is a first look at a page they have not paid for yet.
    """
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert 'id="ai_clean"' not in html
    assert "ai_clean:'all'," in js, "and what is saved is the AI cleaner"
    # ("_pj.py", the old snapshot that also carried the default, went in
    # the 2026-09-02 dead-code sweep.)
    for mod in ("project.py",):
        src = (PKG / mod).read_text(encoding="utf-8")
        assert '"ai_clean": "off"' in src, mod


def test_the_cleaner_version_was_bumped():
    """Both halves change pixels on pages that look fine today: the mask on
    every sound effect over tone, and the route on every plain balloon."""
    assert I.ALGO >= "2026-08-23-b"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ------------------------------------------- and the doorstep that bit a bubble

def _box_corner_on_the_outline():
    """A bubble whose box overlaps its own outline at one corner - which is
    what lee's page 003 is, and what any box drawn to the edge of a bubble
    with writing that reaches it will be."""
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.ellipse(img, (150, 150), (110, 130), 0, 0, 360, (0, 0, 0), 4)
    img[250:300, :] = 90                       # artwork under the bubble
    cv2.putText(img, "AB", (95, 165), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                (20, 20, 20), 5)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bm = np.zeros(g.shape, np.uint8)
    cv2.ellipse(bm, (150, 150), (108, 128), 0, 0, 360, 255, -1)
    box = np.zeros(g.shape, bool)
    box[120:260, 90:215] = True                # the corner lands on the outline
    r = TextRegion(id=0, bbox=(90, 120, 125, 140), kind="bubble",
                   text_mask=((g <= 128) & box).astype(np.uint8) * 255,
                   bubble_mask=bm, bubble_bbox=(40, 20, 220, 260))
    r.src_text, r.order = "a", 0
    page = Page(image=img, source_path="t.png")
    page.regions = [r]
    return page


def test_the_doorstep_does_not_follow_the_outline_out_of_the_box():
    """lee, with the crop: *"this is bad its reaching out of teh box"*. The
    mask catches 23 pixels of the bubble's own outline where the box corner
    lands on it; the doorstep followed the arc out and took 125 more, and the
    fill painted white over the outline and the leaves behind it.

    End to end the bubble's edge is now safe twice over - `_off_the_ground`
    will not put an outline in a mask at all, because an outline is not
    CONTAINED in the box - so the rule itself is asserted where it lives.
    """
    page = _box_corner_on_the_outline()
    before = page.image.copy()
    out = I.inpaint_page(page)
    r = page.regions[0]
    changed = (np.abs(before.astype(int) - out.astype(int)).max(2) > 12)
    assert not (changed & (r.bubble_mask == 0)).any(), \
        "%d pixels of the bubble's edge went" % int(
            (changed & (r.bubble_mask == 0)).sum())

    # ...and the rule, on its own: an arc the box clipped a corner of is not a
    # stroke the box caught, and NEITHER of the two things that say so may be
    # the only one saying it. The balloon clause used to be alone here and the
    # loose call adopted 125px of outline; the doorstep's own containment now
    # refuses the same arc without being told there is a balloon at all, which
    # is why `loose` and `tight` agree. That is not the clause going quiet - it
    # is a second lock on the same door, and the assertion is that the door is
    # shut, by whichever of them gets there first.
    g = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    corner = np.zeros(g.shape, np.uint8)
    corner[250:262, 200:212] = ((g <= 128) * 255)[250:262, 200:212]
    if int((corner > 0).sum()) < 5:
        pytest.skip("the fixture's corner missed the outline")
    box = (90, 120, 125, 140)
    was = int((corner > 0).sum())
    loose = I._complete_strokes(corner, g, False, box, None)
    tight = I._complete_strokes(corner, g, False, box, r.bubble_mask)
    assert int((tight > 0).sum()) == was, "the balloon clause adopted the arc"
    assert int((loose > 0).sum()) == was, \
        "the doorstep followed the arc out with no balloon to stop it"


def _leaving(end_x):
    """A stroke out of a box with no balloon round it, running to `end_x`."""
    img = np.full((200, 200, 3), 255, np.uint8)
    cv2.line(img, (60, 100), (end_x, 100), (0, 0, 0), 9)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    box = np.zeros(g.shape, bool)
    box[80:120, 60:100] = True
    m = ((g <= 128) & box).astype(np.uint8) * 255
    return m, I._complete_strokes(m, g, False, (60, 80, 40, 40))


def test_and_a_box_with_no_balloon_keeps_its_doorstep():
    """Every sound effect and every caption. The doorstep is what finishes a
    glyph drawn a little past its box, and most boxes drawn by hand have no
    balloon to lean on - *"the tetxt is a non negotiable they need to go"*."""
    m, grown = _leaving(106)                 # ends inside the eight pixels
    assert int((grown > 0).sum()) > int((m > 0).sum()), "the stub was left"


def test_but_it_does_not_follow_a_line_that_is_still_going():
    """The other side of it, and it was the other way round until lee sent the
    hair.

    This fixture used to run to x=150 - fifty pixels past the box, six times
    the doorstep - and assert it was adopted anyway, on the grounds that a
    sound effect's box is drawn tight on a mark that carries on. What the
    geometry cannot tell that from is a strand of hair behind the effect, and
    that is what lee got back chopped into segments.

    So it was measured rather than argued. Refusing every component with more
    than `OUTSIDE_SHARE` of itself past the doorstep costs, over lee's 23
    pages, 23px of writing left unpainted and 32 more readable out of 801,840
    - and saves 8,532px of artwork, 1,347 of them hair on one box. The fear
    this fixture was built out of does not appear in the chapter.
    """
    m, grown = _leaving(150)                 # still going, well past the ring
    assert int((grown > 0).sum()) == int((m > 0).sum()), \
        "the doorstep followed a line that had not finished"


def test_the_cleaner_version_moved_again():
    assert I.ALGO >= "2026-08-23-c"
