"""What the printed text is painted with, measured off the page.

lee: *"whe teh ai read teh text is it posible to have teh ai laos look for
color/formats f teh tetx that its reading for the typesetter for exmaple if
there is a gradient it shoud tel the colors and angle i fthere s aouter glo
outile etx? or is it better to have teh typesster try to find this info
itself"*.

The pixels, and not the reader. Everything measured in this chapter says a
vision model normalises what it is unsure of - 티리스 became 타리스, 드래건
became 드래곤, `….` became `...` - and a hex value and an angle are exactly the
sort of continuous quantity it would approximate while sounding certain. The
page can be asked instead, it answers exactly, it answers for free, and the
answer carries its own confidence: a gradient is a regression, and the R² says
whether there is a gradient there at all.

MEASURED on six pages of chapter 1, boxes detected for real:

    ordinary dialogue        R² 0.00 - 0.07   span   0 - 4    -> flat
    011's gold plaque        R² 0.93          span  78        -> a gradient
    066's 파 and 앙          R² 0.78          span 117        -> a gradient

The gates sit in the gap between those two groups, and the fixtures here are
built to land on either side of it.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inkstyle as S


def _block(h=200, w=400, box=(20, 20, 360, 160)):
    m = np.zeros((h, w), np.uint8)
    x, y, bw, bh = box
    m[y:y + bh, x:x + bw] = 255
    return m


def _letters(img, colour, rows=3, cols=8, x0=40, y0=40, size=26, gap=14):
    """Blocks of ink standing in for glyphs. `colour` may be a callable that
    takes (x, y) and gives back a BGR triple, which is how a gradient is
    painted."""
    for r in range(rows):
        for c in range(cols):
            x = x0 + c * (size + gap)
            y = y0 + r * (size + gap)
            for yy in range(y, y + size):
                for xx in range(x, x + size):
                    img[yy, xx] = colour(xx, yy) if callable(colour) else colour
    return img


# ------------------------------------------------------------- the plain case

def test_black_on_white_comes_back_black():
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0))
    got = S.measure_region(img, _block())
    assert got["fg"] == "#000000", got
    assert "fg1" not in got, "a flat fill must not be reported as a gradient"
    assert "edge" not in got, "there is no ring round these letters"


def test_the_block_mask_is_not_taken_for_the_letters():
    """The measurement that started this. `text_mask` is the BLOCK the detector
    found, and a plain bubble measured through it comes out #FAFAFA - which is
    the paper, not the writing. The letters are found inside the block."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0))
    m = _block()
    assert float(img[m > 0].mean()) > 170, "the block really is mostly paper"
    assert S.measure_region(img, m)["fg"] == "#000000"


def test_white_on_a_dark_panel_is_read_the_same_way():
    """029's system panel. "Differs from the paper" has no polarity, so this
    needs no second code path - and if it did, that path would be the one
    nobody tested."""
    img = np.full((200, 400, 3), 0, np.uint8)
    img[:, :] = (75, 31, 28)                       # the navy, in BGR
    _letters(img, (255, 248, 248))
    got = S.measure_region(img, _block())
    assert got["fg"] in ("#F8F8FF", "#F8F8FE", "#F8F9FF"), got


def test_a_colour_is_a_colour_and_not_a_shade_of_grey():
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (32, 16, 200))                   # BGR -> a strong red
    assert S.measure_region(img, _block())["fg"] == "#C81020"


# ------------------------------------------------------------- the gradient

def _grad(img, a=(38, 102, 115), b=(91, 154, 193), horizontal=False):
    """Letters whose colour runs from `a` to `b` down (or across) the block."""
    lo, hi = 40, 40 + 3 * 40

    def paint(x, y):
        t = ((x - 40) / 300.0) if horizontal else ((y - lo) / float(hi - lo))
        t = max(0.0, min(1.0, t))
        return tuple(int(round(a[k] + t * (b[k] - a[k]))) for k in range(3))
    return _letters(img, paint)


def test_a_gradient_is_reported_with_both_ends():
    """011's plaque: gold, dark at the top and light at the bottom."""
    img = np.full((200, 400, 3), 236, np.uint8)
    _grad(img)
    got = S.measure_region(img, _block())
    assert "fg1" in got and "fg2" in got, got
    # The ends are read at the 10th and 90th percentile along the axis rather
    # than at the extremes, so they sit a little inside the painted ones -
    # #736626 to #C19A5B here. Close, and deliberately not exact: a stop taken
    # from the single most extreme pixel is a stop taken from a speck.
    for got_hex, want in ((got["fg1"], (0x73, 0x66, 0x26)),
                          (got["fg2"], (0xC1, 0x9A, 0x5B))):
        have = tuple(int(got_hex[i:i + 2], 16) for i in (1, 3, 5))
        assert max(abs(a - b) for a, b in zip(have, want)) <= 14, (got_hex, want)


def test_and_the_angle_the_app_paints_it_at():
    """0 is top to bottom and it runs clockwise from there - the convention in
    `typesetting.js`, which paints (sin a, cos a) and puts fg1 at the low end.
    A number measured against a different convention is a gradient drawn
    sideways, which is worse than none."""
    img = np.full((200, 400, 3), 236, np.uint8)
    _grad(img)
    down = S.measure_region(img, _block())["grad_angle"]
    assert down < 15 or down > 345, down
    img = np.full((200, 400, 3), 236, np.uint8)
    _grad(img, horizontal=True)
    across = S.measure_region(img, _block())["grad_angle"]
    assert 75 < across < 105, across


def test_the_angle_is_a_plain_number_and_not_numpys():
    """`np.float64` subclasses `float`, so JSON takes it and nothing complains
    - and it comes back off disk as a plain float, so the same region is one
    type before a save and another after it. Pinned as the type, because that
    is the thing that differs."""
    import json
    img = np.full((200, 400, 3), 236, np.uint8)
    _grad(img)
    got = S.measure_region(img, _block())
    assert type(got["grad_angle"]) is float, type(got["grad_angle"])
    assert type(got["stroke"] if "stroke" in got else 0) is int
    json.dumps(got)


def test_a_gentle_shade_is_not_a_gradient():
    """A flat fill on uneven artwork fits a line beautifully and moves almost
    nothing. `GRAD_SPAN` is what refuses it - measured, the worst flat box on
    six pages moved 4 and the plaque moved 78."""
    img = np.full((200, 400, 3), 236, np.uint8)
    _grad(img, a=(60, 60, 60), b=(74, 74, 74))
    got = S.measure_region(img, _block())
    assert "fg1" not in got, got


def test_and_two_tone_noise_is_not_a_gradient():
    """The other half of the pair. Half the letters dark and half light spans
    a mile and fits nothing, so `GRAD_FIT` is what refuses it."""
    rng = np.random.default_rng(7)
    img = np.full((200, 400, 3), 236, np.uint8)
    _letters(img, lambda x, y: (30, 30, 30) if rng.random() < 0.5
             else (200, 200, 200))
    got = S.measure_region(img, _block())
    assert "fg1" not in got, got


def test_both_gates_have_to_clear_and_they_are_the_measured_ones():
    assert 0.07 < S.GRAD_FIT < 0.78, "between the worst flat and the real ones"
    assert 4 < S.GRAD_SPAN < 78


# --------------------------------------------------------------- the outline

def _ring(img, colour, edge, width=3):
    """Letters with a ring of `edge` painted round them."""
    ink = np.zeros(img.shape[:2], np.uint8)
    _letters(ink, 255)
    grown = cv2.dilate(ink, np.ones((2 * width + 1, 2 * width + 1), np.uint8))
    img[(grown > 0) & (ink == 0)] = edge
    img[ink > 0] = colour
    return img


def test_a_ring_round_the_letters_is_reported():
    """066's sound effects: dark red with a white edge, on pink artwork."""
    img = np.full((200, 400, 3), 0, np.uint8)
    img[:, :] = (184, 193, 252)                    # the pink, in BGR
    _ring(img, (4, 1, 117), (247, 249, 255))
    got = S.measure_region(img, _block())
    assert "edge" in got, got
    assert got["edge"].startswith("#FF") or got["edge"].startswith("#FE"), got
    assert got["stroke"] >= 2, got


def test_a_soft_falloff_is_not_a_ring():
    """A glow. The bands step away from the paper exactly as an outline's do,
    and the difference is that they never settle - 029's blue sound effects
    move 27 between the first band and the second, and an outline is one
    colour. Reported as a hard ring, a glow becomes a stroke the artist never
    drew round every letter."""
    img = np.full((200, 400, 3), 0, np.uint8)
    img[:, :] = (40, 30, 25)
    ink = np.zeros(img.shape[:2], np.uint8)
    _letters(ink, 255)
    for d in range(6, 0, -1):
        k = np.ones((2 * d + 1, 2 * d + 1), np.uint8)
        halo = cv2.dilate(ink, k) > 0
        t = 1.0 - d / 7.0
        img[halo] = tuple(int(round(img[0, 0][c] +
                                    t * (220 - img[0, 0][c])))
                          for c in range(3))
    img[ink > 0] = (235, 200, 150)
    got = S.measure_region(img, _block())
    assert "edge" not in got, got


def test_the_rim_every_letter_has_is_not_a_ring():
    """Anti-aliasing. The first band outside black-on-white measures #D7D7D7,
    which is 39 off the paper - every letter ever printed would come back with
    an outline if the first band counted on its own."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0))
    img = cv2.GaussianBlur(img, (3, 3), 0)
    assert "edge" not in S.measure_region(img, _block())


def test_the_outline_gates_are_the_measured_ones():
    assert S.EDGE_STEP >= 30, "26 is a glow on 029 and must not qualify"
    assert S.EDGE_FLAT <= 27, "27 is that same glow's step between bands"


# ------------------------------------------------------------ nothing to say

def test_an_empty_box_says_nothing_rather_than_guessing():
    img = np.full((200, 400, 3), 255, np.uint8)
    assert S.measure_region(img, _block()) == {}


def test_a_box_with_three_specks_in_it_says_nothing():
    img = np.full((200, 400, 3), 255, np.uint8)
    img[60:66, 60:66] = 0
    assert S.measure_region(img, _block()) == {}


def test_no_image_and_no_block_are_both_survivable():
    assert S.measure_region(None, _block()) == {}
    assert S.measure_region(np.zeros((10, 10, 3), np.uint8), None) == {}


# ------------------------------------------------------- over a whole page

def _page(img, boxes):
    from mangatl.models import Page, TextRegion
    p = Page(image=img, source_path="t.png")
    rs = []
    for i, b in enumerate(boxes):
        r = TextRegion(id=i, bbox=b, text_mask=None, bubble_mask=None,
                       bubble_bbox=b, kind="bubble")
        r.order = i
        rs.append(r)
    p.regions = rs
    return p


def test_a_page_is_measured_box_by_box():
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0), rows=1, cols=4, x0=40, y0=40)
    _letters(img, (32, 16, 200), rows=1, cols=4, x0=40, y0=120)
    p = _page(img, [(20, 20, 360, 60), (20, 100, 360, 60)])
    assert S.measure_page(p) == 2
    assert p.regions[0].layout_override["fg"] == "#000000"
    assert p.regions[1].layout_override["fg"] == "#C81020"


def test_a_colour_somebody_chose_is_never_overwritten():
    """It fills in blanks. A person who set the sound effects yellow does not
    want them measured back to grey on the next re-read."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0), rows=1, cols=4, x0=40, y0=40)
    p = _page(img, [(20, 20, 360, 60)])
    p.regions[0].layout_override = {"fg": "#FFCC00", "font": "Bangers"}
    S.measure_page(p)
    assert p.regions[0].layout_override["fg"] == "#FFCC00"
    assert p.regions[0].layout_override["font"] == "Bangers"


def test_a_page_with_no_regions_is_not_an_error():
    assert S.measure_page(_page(np.full((80, 80, 3), 255, np.uint8), [])) == 0


def test_two_boxes_that_overlap_do_not_measure_each_other():
    """`_pixel_owner` settles every inked pixel on one region, so a box lying
    across its neighbour reports its own letters and not the pair."""
    import numpy as _np
    from mangatl.models import Page, TextRegion
    img = _np.full((200, 400, 3), 255, _np.uint8)
    _letters(img, (0, 0, 0), rows=1, cols=3, x0=40, y0=60)
    _letters(img, (32, 16, 200), rows=1, cols=3, x0=220, y0=60)
    p = Page(image=img, source_path="t.png")
    rs = []
    for i, b in enumerate([(20, 40, 340, 80), (200, 40, 180, 80)]):
        m = _np.zeros((200, 400), _np.uint8)
        x, y, w, h = b
        m[y:y + h, x:x + w] = 255
        r = TextRegion(id=i, bbox=b, text_mask=m, bubble_mask=None,
                       bubble_bbox=b, kind="bubble")
        r.order = i
        rs.append(r)
    p.regions = rs
    S.measure_page(p)
    assert p.regions[0].layout_override["fg"] == "#000000"
    assert p.regions[1].layout_override["fg"] == "#C81020"


# ------------------------------------------------- ...and it runs at the read

def test_the_read_step_measures_the_colours_before_the_page_is_cleaned():
    """The timing is the whole design. Cleaning wipes the Japanese, so the read
    is the last moment the original letters exist to be measured."""
    import inspect

    from mangatl import editor
    src = inspect.getsource(editor.do_ocr)
    assert "measure_page(page" in src
    assert src.index("measure_page(page") < src.rindex("p.commit(i, page)")


def test_a_colour_that_cannot_be_measured_does_not_take_the_read_down():
    """A nicety must never cost the words. Driven by making the measurement
    throw, which is the case the try/except is there for."""
    import types

    from mangatl import editor, inkstyle, ocr as O, translate as T
    from mangatl.models import Page, TextRegion

    def boom(page):
        raise RuntimeError("no")

    saved = inkstyle.measure_page
    inkstyle.measure_page = boom
    real_tiles, real_read = O.page_label_tiles, T.read_page_ocr
    O.page_label_tiles = lambda *a, **k: []
    T.read_page_ocr = lambda *a, **k: {0: "읽었다"}
    try:
        r = TextRegion(id=0, bbox=(0, 0, 10, 10), text_mask=None,
                       bubble_mask=None, bubble_bbox=(0, 0, 10, 10),
                       kind="bubble")
        page = Page(image=np.full((40, 40, 3), 245, np.uint8), regions=[r])
        done = {}
        p = types.SimpleNamespace(
            settings={"medium": "manhwa"},
            ctx=types.SimpleNamespace(medium="manhwa", source="", target="en",
                                      safety="", synopsis="", characters="",
                                      glossary="", story="", notes=""),
            job={}, materialize=lambda i: page,
            commit=lambda i, pg: done.setdefault("committed", True))
        try:
            editor.do_ocr(p, 0)
        except Exception as e:                        # pragma: no cover
            raise AssertionError("the read died over a colour: %r" % e)
        assert done.get("committed"), "the page was never written back"
        assert r.src_text == "읽었다", r.src_text
    finally:
        inkstyle.measure_page = saved
        O.page_label_tiles, T.read_page_ocr = real_tiles, real_read


# ------------------------------- the ring and the gradient look alike to Otsu

def test_a_letter_filled_with_a_gradient_is_not_mistaken_for_a_ringed_one():
    """Both split into two populations, and the split means opposite things.

    Writing inside a ring is dark-then-light and so is writing filled with a
    gradient; the difference is WHERE the light half is. In a ring it is
    around the outside; in a gradient it runs through the middle. Take the
    split on a gradient and what is left is the dark core, which is how 066's
    파 lost its red - measured, `fg` went to #010000 and both stops with it."""
    img = np.full((200, 400, 3), 236, np.uint8)
    _grad(img, a=(20, 20, 20), b=(150, 150, 150))
    ink = S.glyph_ink(img, _block(),
                      np.array([236.0, 236.0, 236.0]))
    kept = float(ink.sum())
    assert kept > 12000, ("the light half of the gradient was thrown away", kept)
    got = S.measure_region(img, _block())
    assert "fg1" in got and "fg2" in got, got


def test_and_a_ring_still_comes_off():
    """The same machinery, the other way round: here the light half IS the
    ring and it must not be measured as part of the letter."""
    img = np.full((200, 400, 3), 0, np.uint8)
    img[:, :] = (184, 193, 252)
    _ring(img, (4, 1, 117), (247, 249, 255))
    ink = S.glyph_ink(img, _block(), np.array([184.0, 193.0, 252.0]))
    assert 15000 < float(ink.sum()) < 20000, float(ink.sum())
    got = S.measure_region(img, _block())
    assert got["fg"] == "#750104" and got["edge"].startswith("#FF"), got


def test_the_inside_share_is_the_measured_one():
    assert 0.1 < S.NEAR_INSIDE < 0.6


def test_a_ring_the_first_split_keeps_is_taken_off_by_the_second():
    """The case the second split exists for.

    Where the ring's colour sits between the paper and the letters - grey
    round black on white - one split cannot separate them, and the letters
    come back as the average of black and grey, which is a colour that is on
    no part of the page."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _ring(img, (0, 0, 0), (128, 128, 128), width=3)
    got = S.measure_region(img, _block())
    assert got["fg"] == "#000000", got
    assert got.get("edge") == "#808080", got



def test_the_blended_rim_of_a_glyph_is_not_part_of_its_colour():
    """Every printed letter has one - a band where the ink and the paper are
    mixed - and it is a fifth of a small glyph. Measured in, a red caption on
    white reports pink."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (32, 16, 200), size=14, gap=22)
    img = cv2.GaussianBlur(img, (7, 7), 0)
    got = S.measure_region(img, _block())
    have = tuple(int(got["fg"][i:i + 2], 16) for i in (1, 3, 5))
    # 0 off with the rim dropped, 11 off with it kept - and 11 on a colour is
    # the difference between the red the artist drew and a pinker one.
    assert max(abs(a - b) for a, b in zip(have, (200, 16, 32))) <= 6, got


def test_the_rim_is_not_an_outline_even_at_full_contrast():
    """White on black is the worst case: the blend between them is mid-grey,
    which is 127 off the paper and clears any step you could set. It is still
    not an outline - it is the edge of the letter."""
    img = np.zeros((200, 400, 3), np.uint8)
    _letters(img, (255, 255, 255))
    img = cv2.GaussianBlur(img, (5, 5), 0)
    got = S.measure_region(img, _block())
    assert "edge" not in got, got


# ------------------------------------------------------------------ the glow

def _halo(img, colour, edge, reach=6):
    """Letters with light fading outwards from them, the way a glow does."""
    ink = np.zeros(img.shape[:2], np.uint8)
    _letters(ink, 255)
    base = np.array(img[0, 0], float)
    for d in range(reach, 0, -1):
        k = np.ones((2 * d + 1, 2 * d + 1), np.uint8)
        band = cv2.dilate(ink, k) > 0
        t = 1.0 - d / float(reach + 1)
        img[band] = tuple(int(round(base[c] + t * (edge[c] - base[c])))
                          for c in range(3))
    img[ink > 0] = colour
    return img


def test_a_halo_that_keeps_fading_is_a_glow():
    """029's blue sound effects: 125 94 78 56 36 23 off the paper, a decay
    that goes on. Nothing else on six pages does that."""
    img = np.zeros((200, 400, 3), np.uint8)
    img[:, :] = (35, 25, 20)
    _halo(img, (250, 235, 185), (200, 150, 90))
    got = S.measure_region(img, _block())
    assert "glow" in got, got
    assert got["glow_size"] >= 3, got
    assert "edge" not in got, "a glow drawn as a hard ring is a ring nobody drew"


def test_a_ring_is_not_reported_as_a_glow():
    img = np.full((200, 400, 3), 0, np.uint8)
    img[:, :] = (184, 193, 252)
    _ring(img, (4, 1, 117), (247, 249, 255))
    got = S.measure_region(img, _block())
    assert "edge" in got and "glow" not in got, got


def test_plain_writing_has_neither():
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0))
    got = S.measure_region(img, _block())
    assert "glow" not in got and "edge" not in got, got


def test_the_blended_rim_is_not_a_glow_either():
    """It is the biggest step of the lot - white on black blends to 175 - and
    it is one band wide. The tail is read from the SECOND ring for that
    reason."""
    img = np.zeros((200, 400, 3), np.uint8)
    _letters(img, (255, 255, 255))
    img = cv2.GaussianBlur(img, (5, 5), 0)
    assert "glow" not in S.measure_region(img, _block())


# ---------------------------------------------------------------- the shadow

def test_the_letters_offset_and_darker_are_a_shadow():
    img = np.full((200, 400, 3), 255, np.uint8)
    ink = np.zeros(img.shape[:2], np.uint8)
    _letters(ink, 255)
    moved = np.roll(np.roll(ink, 4, 0), 4, 1)
    img[moved > 0] = (150, 150, 150)
    img[ink > 0] = (0, 0, 0)
    got = S.measure_region(img, _block())
    assert "shadow" in got, got
    assert 2 <= got["sh_dist"] <= 8, got


def test_a_glow_is_not_a_shadow():
    """The one asymmetric thing round a letter. Everything else sits evenly all
    the way round, so the centre of the dark does not move."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _halo(img, (0, 0, 0), (90, 90, 90))
    assert "shadow" not in S.measure_region(img, _block())


def test_a_balloon_outline_is_not_a_shadow():
    """Three plain bubbles claimed one before the shape test went in: their
    own black outline is dark, and it happened to sit down and to the right.
    A shadow is the LETTERS again, so the letters have to land on it."""
    img = np.full((200, 400, 3), 255, np.uint8)
    _letters(img, (0, 0, 0), rows=1, cols=5, x0=60, y0=70)
    cv2.rectangle(img, (30, 30), (370, 150), (10, 10, 10), 5)
    assert "shadow" not in S.measure_region(img, _block())


def test_a_shadow_the_renderer_cannot_draw_is_not_reported():
    """It draws down and to the right at a fixed 45 degrees. One measured up
    and to the left would be drawn on the wrong side of every letter, which is
    worse than none."""
    img = np.full((200, 400, 3), 255, np.uint8)
    ink = np.zeros(img.shape[:2], np.uint8)
    _letters(ink, 255)
    moved = np.roll(np.roll(ink, -5, 0), -5, 1)
    img[moved > 0] = (150, 150, 150)
    img[ink > 0] = (0, 0, 0)
    assert "shadow" not in S.measure_region(img, _block())


# ------------------------------------------------------- one black per chapter

def test_the_same_ink_on_two_pages_is_one_colour():
    seen = {}
    assert S._snap(seen, "#010101") == "#010101"
    assert S._snap(seen, "#000000") == "#010101"
    assert S._snap(seen, "#040404") == "#010101"
    assert seen == {"#010101": 3}


def test_two_colours_that_are_different_stay_different():
    seen = {}
    S._snap(seen, "#746826")
    assert S._snap(seen, "#C09548") == "#C09548"
    assert len(seen) == 2


def test_the_most_used_one_wins_so_the_colour_cannot_walk():
    """Without that, a chain of near-misses carries the black across the
    chapter one shade at a time and page 40 is grey."""
    seen = {"#000000": 9, "#060606": 1}
    assert S._snap(seen, "#050505") == "#000000"


def test_the_snap_is_the_measured_distance():
    assert 4 < S.SNAP < 16


def test_a_page_measured_with_no_tally_is_left_alone():
    assert S._snap(None, "#123456") == "#123456"


def test_the_read_step_keeps_the_tally_on_the_project():
    import inspect

    from mangatl import editor
    src = inspect.getsource(editor.do_ocr)
    assert "ink_seen" in src and "measure_page(page, p.ink_seen)" in src


def test_a_flat_patch_behind_the_words_is_not_a_glow():
    """059's caption: a white patch four pixels wide behind small dark text on
    artwork, which reads 47 88 87 85 12 - a plateau, and a plateau is a shape
    a glow never makes. Without that guard it comes back as a four-pixel white
    halo round every letter."""
    img = np.full((200, 400, 3), 0, np.uint8)
    img[:, :] = (168, 166, 170)                    # grey artwork
    ink = np.zeros(img.shape[:2], np.uint8)
    _letters(ink, 255)
    patch = cv2.dilate(ink, np.ones((9, 9), np.uint8)) > 0
    img[patch] = (254, 254, 254)
    img[ink > 0] = (4, 4, 4)
    got = S.measure_region(img, _block())
    assert "glow" not in got, got


def test_a_tail_too_faint_to_see_is_not_a_glow():
    """A step of a few levels is JPEG and tone, and it is on every page. The
    ones that are really there start at 76 and 125."""
    img = np.full((200, 400, 3), 236, np.uint8)
    _halo(img, (20, 20, 20), (228, 228, 228), reach=6)
    got = S.measure_region(img, _block())
    assert "glow" not in got, got



def test_two_pages_read_in_one_run_share_a_black():
    """The tally is what makes a chapter one colour. Driven through
    `measure_page`, because the snapping has to happen where the styles are
    written and not only in the helper."""
    seen = {}
    a = np.full((200, 400, 3), 255, np.uint8)
    _letters(a, (1, 1, 1), rows=1, cols=4, x0=40, y0=40)
    b = np.full((200, 400, 3), 255, np.uint8)
    _letters(b, (5, 5, 5), rows=1, cols=4, x0=40, y0=40)
    pa, pb = _page(a, [(20, 20, 360, 60)]), _page(b, [(20, 20, 360, 60)])
    S.measure_page(pa, seen)
    S.measure_page(pb, seen)
    assert pa.regions[0].layout_override["fg"] == \
        pb.regions[0].layout_override["fg"], (pa.regions[0].layout_override,
                                              pb.regions[0].layout_override)
