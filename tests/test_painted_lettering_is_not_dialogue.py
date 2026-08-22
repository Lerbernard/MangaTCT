"""Painted type is not dialogue.

lee: *"i remenber making a rule that all bubble text needed to find their
container or be labbled outside text"*.

He did make it, and it works. Closing every escape from that rule and running
the whole 69-page chapter both ways moves **zero** boxes, so nothing on the
chapter is dialogue because of a loophole. Sixteen boxes reach the paper test
at all, and fifteen of them are labelled right.

The sixteenth is 055's **로얀 수틀렉스** -- a magenta brush title laid across
an impact flash -- and the container rule was never going to catch it, because
it *has* a container as far as anything in the demotion can tell. A flash is
bright and its margin is dense with drawn strokes, which is exactly what
`_ring_rays` was added to recognise as a speech burst, and the white core
under the letters is exactly what `_paper_under` was added to recognise as a
caption plate. It was kept twice over: 0.053 rays against the 0.04 bar, and
248 floor against 210. Both doors had to shut.

Every measurement in the demotion asks about the PAPER, and the paper round a
title is the same paper as round a shout. The letters are not. So this adds
the one question the rest never asks -- **what colour is the writing** -- and
uses it only to veto the two escapes that never find anything drawn round the
letters at all.
"""
import numpy as np
import cv2
import pytest

from where import PKG

from mangatl.detect import comictext as CT
from mangatl.models import Page


INPUT = 1024


# --------------------------------------------------- what the measure reads

def _typed(fg, bg, size=(200, 300)):
    """A box of set type, whatever colour either of them is."""
    im = np.full((size[0], size[1], 3), bg, np.uint8)
    cv2.putText(im, "HELLO", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 3, fg, 8)
    return im


def test_black_on_white_is_ink():
    assert CT._ink_chroma(_typed((10, 10, 10), 250), (0, 0, 300, 200)) == 0.0


def test_grey_on_white_is_ink():
    assert CT._ink_chroma(_typed((120, 120, 120), 250),
                          (0, 0, 300, 200)) == 0.0


def test_white_on_black_is_ink_too():
    """The reason `_glyph_share`'s `gray < INK` cannot be reused: a caption
    reversed out of a black plate has no dark letters in it at all, and every
    dark pixel in the box is the plate."""
    assert CT._ink_chroma(_typed((250, 250, 250), 12), (0, 0, 300, 200)) == 0.0


def test_magenta_on_white_is_paint():
    assert CT._ink_chroma(_typed((180, 20, 190), 250),
                          (0, 0, 300, 200)) > 4 * CT.INK_CHROMA


def test_the_ground_is_found_by_the_border_not_by_being_bigger():
    """Three fat glyphs cropped close are MOST of their own box, so "keep the
    smaller side" hands back the paper and every painted title reads as ink.
    The ground is whatever runs to the edges of the box."""
    im = np.full((240, 240, 3), 250, np.uint8)
    cv2.rectangle(im, (8, 8), (110, 230), (190, 20, 150), -1)
    cv2.rectangle(im, (128, 8), (231, 230), (190, 20, 150), -1)
    ink = (cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) < 128).mean()
    assert ink > 0.5, "the fixture is not glyph-heavy, so it tests nothing"
    assert CT._ink_chroma(im, (0, 0, 240, 240)) > CT.INK_CHROMA


def test_paint_reversed_out_of_a_black_plate_is_still_paint():
    """The border rule cuts both ways. If the ink were taken to be the dark
    side of the threshold, a magenta title knocked out of a black panel would
    hand back the panel and read as neutral."""
    im = np.full((200, 300, 3), 14, np.uint8)
    cv2.putText(im, "HELLO", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 3,
                (190, 20, 150), 8)
    assert CT._ink_chroma(im, (0, 0, 300, 200)) > 4 * CT.INK_CHROMA


def _soft_strokes(wide=100, thin=4, thins=16, ramp=28, h=420, w=1200,
                  ground=(40, 20, 220), ink=(10, 10, 10)):
    """One fat stroke and sixteen hairlines on magenta, every edge blended into
    the ground over `ramp` pixels. Built with arithmetic, and that is the point.

    This fixture used to be `putText` + `GaussianBlur`, and it stopped meaning
    what it says the day OpenCV 5 shipped: both calls render differently from
    4.11 - the same 504,000 black pixels come out of `putText` with a different
    hash, and the blur then lands at mean 83.9 against 76.4 - so the picture was
    simply softer, most of the ink was washed away, and `_ink_chroma` returned
    27.3 to a question nobody had asked it. `threshold`, `distanceTransform` and
    `cvtColor` agree exactly across the two versions; it was only the two calls
    that DREW the fixture that moved. CI installs opencv unpinned, so it drew a
    different picture from the one this was written against and reported it as
    a defect in the app.

    The mixture of widths is the substance, not decoration. The hairlines are
    mostly blend, so the whole ink region votes coloured; the fat stroke is what
    lifts the ninetieth percentile of the distance transform, so the core
    selection lands inside black and nowhere else. That is the property being
    tested - a threshold picked from the strokes rather than a fixed erosion.
    """
    a = np.zeros((h, w), np.float32)
    x = 30
    for core in [wide] + [thin] * thins:
        span = int(round(core / 2.0 + ramp))
        cx = x + span
        xs = np.arange(max(0, cx - span), min(w, cx + span + 1))
        al = np.clip((core / 2.0 + ramp - np.abs(xs - cx)) / ramp, 0, 1)
        a[50:h - 50, xs] = np.maximum(a[50:h - 50, xs], al[None, :])
        x = cx + span + 8
    g = np.asarray(ground, np.float32)[None, None, :]
    k = np.asarray(ink, np.float32)[None, None, :]
    return np.clip(g * (1 - a[..., None]) + k * a[..., None], 0, 255
                   ).astype(np.uint8)


def test_a_soft_edge_wider_than_one_pixel_is_still_not_the_letter():
    """A page printed soft, or scaled down from a bigger one, blends ink into
    ground over many pixels. Take the whole glyph and the blend outvotes the
    letter; erode by a fixed pixel and it still does. The distance transform
    takes the middle of the stroke at whatever width the stroke happens to be,
    and only that reads the letter as black."""
    im = _soft_strokes()
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    _t, dark = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV +
                             cv2.THRESH_OTSU)
    ink = dark > 0
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB)
    chroma = np.hypot(lab[..., 1].astype(np.float32) - 128.0,
                      lab[..., 2].astype(np.float32) - 128.0)
    dt = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
    assert np.median(chroma[ink]) > CT.INK_CHROMA, "the fixture has no blend"
    assert np.median(chroma[dt >= 1.0]) > CT.INK_CHROMA, \
        "one pixel of erosion already clears it, so this tests nothing"
    assert CT._ink_chroma(im, (0, 0, 1200, 420)) < CT.INK_CHROMA


def test_thin_type_on_tinted_paper_is_still_ink():
    """022's caption face is three pixels wide on cream. Every letter has a
    warm rim where ink meets paper, and over a face that thin the rim
    outnumbers the middle -- so the median of the whole glyph reads coloured
    and the stroke CORES read black."""
    im = np.full((200, 420, 3), (225, 236, 250), np.uint8)
    cv2.putText(im, "HELLO", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.2,
                (12, 12, 12), 2)
    assert CT._ink_chroma(im, (0, 0, 420, 200)) < CT.INK_CHROMA


def test_a_box_with_nothing_in_it_reads_nothing():
    assert CT._ink_chroma(np.full((60, 60, 3), 255, np.uint8),
                          (0, 0, 60, 60)) == 0.0


def test_a_box_too_small_to_hold_letters_reads_nothing():
    assert CT._ink_chroma(_typed((180, 20, 190), 250), (0, 0, 5, 5)) == 0.0


def test_a_scrap_of_solid_colour_is_not_a_painted_word():
    """Sixty-three pixels of magenta with a pale border round them is enough
    ink to measure and reads 91.5 if it is measured. It is a chip of artwork
    inside somebody's box, not type, and a box this small has no letters
    in it to ask about."""
    p = np.full((11, 9, 3), (190, 20, 150), np.uint8)
    p[0, :] = p[-1, :] = (250, 250, 250)
    p[:, 0] = p[:, -1] = (250, 250, 250)
    assert 9 * 11 < CT.CHROMA_MIN_BOX
    assert CT._ink_chroma(p, (0, 0, 9, 11)) == 0.0


def test_a_box_off_the_edge_of_the_page_is_clipped_not_crashed():
    assert CT._ink_chroma(_typed((180, 20, 190), 250),
                          (-40, -40, 900, 900)) >= 0


# --------------------------------------------------- where the bar sits

def test_the_bar_sits_between_the_ink_and_the_paint():
    """1.0 is the highest of the six boxes at the gate that are rightly
    dialogue -- 042's two bursts, 044's two spiky balloons, 017's ornate
    caption frame, 072's credit line. 33.5 is 로얀 수틀렉스. Nothing on the
    chapter lands between them."""
    assert 1.0 < CT.INK_CHROMA < 33.5


def test_it_leaves_room_for_dialogue_that_happens_to_be_tinted():
    """Not by the number -- 008's blue second line scores 24.3 and 065's
    tinted shout 22.1, both over the bar. By WHERE the veto is asked: both are
    inside drawn ovals, and a box with a balloon, a wall or an enclosure never
    reaches either escape this touches."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    body = src[src.index("    demoted: set = set()"):]
    body = body[:body.index("r.kind = \"freefloat\"")]
    wall = body.index("if _round_wall_around(gray, r.bbox):")
    assert body.index("_ink_chroma") > wall, \
        "the wall rescue must not be vetoed -- a drawn balloon is a container"
    enc = body.index("lo=ENCLOSE_LO")
    assert body.index("_ink_chroma") > enc, \
        "the enclosure rescue must not be vetoed either"


def test_both_of_the_weak_escapes_are_vetoed_and_not_just_one():
    """로얀 needed both doors shut: the rays escape holds it at 0.053, and
    with that closed the bright floor holds it at 248."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert ("if _ring_rays(gray, r.bbox) >= RAYS_DENS \\\n"
            "                        and _ink_chroma(img, r.bbox) "
            "< INK_CHROMA:") in src
    assert ("elif _paper_under(gray, r.bbox, r.text_mask) >= UNDER_PAPER \\\n"
            "                    and _ink_chroma(img, r.bbox) "
            "< INK_CHROMA:") in src


def test_it_is_measured_on_the_colour_page_not_the_grey_one():
    """Every other test in the demotion takes `gray`. This one cannot."""
    src = (PKG / "detect" / "comictext.py").read_text(encoding="utf-8")
    assert "_ink_chroma(gray," not in src


# --------------------------------------------- end to end, through the detector

class _Net:
    def __init__(self, blocks, seg):
        self.blocks, self.seg = blocks, seg

    def setInput(self, blob):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["blk", "seg"]

    def forward(self, names):
        blk = np.zeros((1, max(1, len(self.blocks)), 6), np.float32)
        for i, (x0, y0, x1, y1) in enumerate(self.blocks):
            blk[0, i] = [(x0 + x1) / 2.0, (y0 + y1) / 2.0,
                         x1 - x0, y1 - y0, 0.9, 0.9]
        seg = np.zeros((1, 1, INPUT, INPUT), np.float32)
        seg[0, 0] = (self.seg > 0).astype(np.float32)
        return [blk, seg]


def _flash(colour, page_tone=255, line_tone=40):
    """Writing standing on a clear white core with a field of speed lines
    round it and no wall anywhere -- a speech burst, or an impact flash. The
    page cannot tell them apart, and that is the point.

    Straight lines and not a radial fan on purpose: a tidy ring of rays reads
    as an ENCLOSURE at the gentle thresholds, and the enclosure rescue is
    asked before this one and is not vetoed. 로얀's flash does not enclose it
    either -- measured False -- so a fixture that encloses would be testing a
    different escape.
    """
    page = np.full((INPUT, INPUT, 3), page_tone, np.uint8)
    rng = np.random.RandomState(0 if page_tone > 128 else 1)
    for _k in range(150 if page_tone > 128 else 120):
        y = rng.randint(0, INPUT)
        length = rng.randint(200, 600)
        x = rng.randint(0, INPUT - length)
        cv2.line(page, (x, y), (x + length, y + rng.randint(-6, 6)),
                 (line_tone,) * 3, rng.randint(2, 5))
    spec = np.zeros((INPUT, INPUT), np.uint8)
    for i in range(3):
        cv2.rectangle(spec, (380 + i * 110, 460),
                      (470 + i * 110, 550), 255, -1)
    ys, xs = np.nonzero(spec)
    box = (int(xs.min()) - 8, int(ys.min()) - 8,
           int(xs.max()) + 8, int(ys.max()) + 8)
    cv2.rectangle(page, (box[0] + 1, box[1] + 1), (box[2] - 1, box[3] - 1),
                  (255, 255, 255), -1)
    page[spec > 0] = colour
    return page, [box], spec


def _dark(colour):
    """The same writing on a bright plate, with the margin NOT reading as
    paper -- which is the other door, `_paper_under`."""
    return _flash(colour, page_tone=60, line_tone=215)


def _run(monkeypatch, img, blocks, seg):
    from mangatl.detect import balloon as B
    monkeypatch.setattr(CT, "_get_net", lambda p: _Net(blocks, seg))
    monkeypatch.setattr(B, "attach_balloons", lambda *a, **k: None)
    monkeypatch.setattr(CT, "_classify_kind", lambda g, box: "bubble")
    tune = dict(CT.tuning_for("manhwa"))
    tune.update(craft_x=None, craft_y=None, second_opinion=False,
                effect_fill=None)
    return CT.detect_comictext(Page(image=img), "no-such-model.onnx", **tune)


def _numbers(make):
    img, blocks, _seg = make((20, 20, 20))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    x0, y0, x1, y1 = blocks[0]
    bb = (x0, y0, x1 - x0, y1 - y0)
    from mangatl.detect.balloon import _round_wall_around
    return {
        "wall": _round_wall_around(gray, bb),
        "enc": _round_wall_around(gray, bb, roundish=False, lo=CT.ENCLOSE_LO,
                                  hi=CT.ENCLOSE_HI, seal=CT.ENCLOSE_SEAL),
        "ring": CT._ring_paper(gray, bb),
        "rays": CT._ring_rays(gray, bb),
        "under": CT._paper_under(gray, bb, None),
    }


def test_the_bright_fixture_is_held_by_the_rays_and_nothing_else():
    """If it had a wall or an enclosure the pair below would prove nothing --
    the box would be kept by a rescue this change does not touch."""
    n = _numbers(_flash)
    assert not n["wall"] and not n["enc"]
    assert n["ring"] >= CT.LOOSE_RING and n["rays"] >= CT.RAYS_DENS


def test_the_dark_fixture_is_held_by_the_floor_and_nothing_else():
    n = _numbers(_dark)
    assert not n["wall"] and not n["enc"]
    assert n["ring"] < CT.LOOSE_RING and n["under"] >= CT.UNDER_PAPER


def test_black_letters_in_a_burst_stay_dialogue(monkeypatch):
    rs = _run(monkeypatch, *_flash((20, 20, 20)))
    assert rs and rs[0].kind == "bubble", [r.kind for r in rs]


def test_the_same_burst_with_painted_letters_is_outside_text(monkeypatch):
    """The one that matters. Same page, same speed lines, same white under
    the letters -- only the colour of the writing changes."""
    rs = _run(monkeypatch, *_flash((190, 20, 150)))
    assert rs and rs[0].kind == "freefloat", [r.kind for r in rs]


def test_black_letters_on_a_bright_plate_stay_dialogue(monkeypatch):
    rs = _run(monkeypatch, *_dark((20, 20, 20)))
    assert rs and rs[0].kind == "bubble", [r.kind for r in rs]


def test_painted_letters_on_a_bright_plate_are_outside_text(monkeypatch):
    """The second door. 로얀 needed both: with the rays shut it was still
    standing on 248 of white."""
    rs = _run(monkeypatch, *_dark((190, 20, 150)))
    assert rs and rs[0].kind == "freefloat", [r.kind for r in rs]


# ------------------------------------------------------------ the format fork

def test_manga_never_reaches_any_of_this():
    """The veto lives inside the demotion, and the demotion is off for manga
    because `loose_bubble` is None there."""
    assert CT.tuning_for("manga").get("loose_bubble") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
