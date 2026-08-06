"""Two speeches in one balloon come out as two speeches.

A balloon drawn as two overlapping ovals is ONE enclosure. The outline detector
finds enclosures, so it found one region, read one block of Japanese out of it,
sent the translator one speech and got one paragraph back — which was then
typeset straight across the waist as though the artist had drawn a circle.
lee's page has two of them: "I'M SORRY, ADA..." in the bud and "...IT'S MY OWN
WEAKNESS THAT DID THIS TO YOU." in the trunk, merged into a single block.

The machinery to typeset each lobe separately was already there and already
tested — it just never fired, because it needs two regions sharing one balloon
before it has anything to divide. So the division is made where the evidence
is: at detection, off the shape of the outline, before a single word has been
read.

What has to be refused is the harder half. Any chord divides any shape in two,
so these tests are mostly about balloons that must NOT be split: a plain oval,
an oval with two well-separated columns of Japanese in it (the chord would slip
neatly between them), and a balloon with a tail (whose dents are as deep as any
neck's).

The pages are drawn here rather than loaded, so the tests run anywhere.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import classical
from mangatl.models import Page

H, W = 900, 1000
BUD = "I'M SORRY, ADA..."
TRUNK = "...IT'S MY OWN WEAKNESS THAT DID THIS TO YOU."


def _outline(img):
    """Ink in the balloon's rim, the way a page is actually drawn.

    The detector finds the region a dark outline ENCLOSES, so a fixture with no
    outline is not a fixture for it.
    """
    m = (img >= 250).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, 20, 3)
    return img


def _columns(img, xs, top=300, bot=500):
    """Vertical Japanese: pairs of columns of small blocks."""
    ink = np.zeros((H, W), np.uint8)
    for x in xs:
        for y in range(top, bot, 26):
            cv2.rectangle(ink, (x - 9, y), (x + 9, y + 18), 255, -1)
    img[ink > 0] = 15
    return ink


def _two_lobed(tail=False):
    """Two overlapping ovals, a block of Japanese written in each."""
    img = np.full((H, W), 246, np.uint8)
    for cx in (300, 480):
        cv2.ellipse(img, (cx, 400), (110, 150), 0, 0, 360, 255, -1)
    if tail:
        cv2.fillPoly(img, [np.array([[300, 540], [360, 540], [320, 640]])], 255)
    _outline(img)
    _columns(img, (230, 260, 510, 540))
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _one_oval(xs):
    """One plain oval with Japanese in it, wherever `xs` puts the columns."""
    img = np.full((H, W), 246, np.uint8)
    cv2.ellipse(img, (400, 400), (260, 160), 0, 0, 360, 255, -1)
    _outline(img)
    _columns(img, xs, 320, 480)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _found(img):
    return classical.detect_outline(Page(image=img))


def _cfg():
    from mangatl.typeset import TypesetConfig, default_font_path
    return TypesetConfig(font_path=default_font_path(), min_font=10,
                         max_font=34)


# --------------------------------------------------------------- it divides

def test_a_two_lobed_balloon_is_found_as_two_regions():
    regions = _found(_two_lobed())
    assert len(regions) == 2, [r.bbox for r in regions]
    # Neither lobe's writing is in the other's box.
    (ax, _, aw, _), (bx, _, bw, _) = (r.bbox for r in regions)
    assert ax + aw <= bx or bx + bw <= ax, [r.bbox for r in regions]


def test_the_two_halves_are_read_as_one_sentence():
    """One sentence written across two lobes is still one sentence.

    They are separate boxes to TYPESET and one line to TRANSLATE, which is what
    `link` says: the translator is handed the pair in order and told to read
    them together, so "I'M SORRY, ADA..." and the clause that finishes it are
    not translated as two unrelated fragments.
    """
    regions = _found(_two_lobed())
    assert len({r.link for r in regions}) == 1
    assert regions[0].link > 0
    # In reading order: the right-hand lobe first, as Japanese is read.
    assert regions[0].bbox[0] > regions[1].bbox[0], [r.bbox for r in regions]


def test_each_lobe_gets_its_own_half_of_the_balloon():
    """Not the whole balloon each — that is the same merge one step later.

    Whatever the typesetter works out for a shared balloon, it measures against
    what the detector already said. Hand both halves the whole balloon and what
    it measures against is the two speeches typeset on top of one another,
    which wins on size every time and throws the division straight back out.
    """
    regions = _found(_two_lobed())
    a, b = (r.bubble_mask for r in regions)
    assert a is not None and b is not None
    assert not ((a > 0) & (b > 0)).any(), "the two lobes overlap"
    for r in regions:
        own = (r.bubble_mask > 0)
        ink = (r.text_mask > 0)
        assert float((own & ink).sum()) / float(ink.sum()) > 0.99, r.id


def test_the_typesetter_keeps_the_division_and_typesets_it_big():
    """End to end: the whole point of the exercise.

    Merged, this balloon holds one nine-word paragraph and typesets it small
    across the waist. Divided, each lobe letters its own speech, and lee asked
    for exactly that — each block in its own box.

    It used to say *and bigger*: 34pt and 25pt, against about 15 and 10 from
    the page's own typesetter. But big and in the box turned out to be two
    different things. A lobe and the trunk are one piece of paper either side
    of the neck, so a block free to use its whole side of the division reaches
    across the waist to get there — at 34pt this block's words start 60px
    outside its own box, on his page the word HUH!? left the top lobe entirely
    and sat at the balloon's waist. Trimming the share back to the box costs
    exactly half the point size, and lee called it: *"that fine the size dnst
    mattaer as long as it in the box"*.

    So the size assertion here is the floor, not a boast, and what is actually
    tested is that every line lands inside the box it belongs to.
    """
    from mangatl.typeset import fit_region, share_masks, BOX_LEEWAY, _font

    regions = _found(_two_lobed())
    for r, t in zip(regions, (BUD, TRUNK)):
        r.dst_text = t
    cfg = _cfg()
    shares = share_masks(regions, cfg)
    assert set(shares) == {r.id for r in regions}, "the division was discarded"
    for r, said in zip(regions, (BUD, TRUNK)):
        ink = r.text_mask > 0
        kept = float(((shares[r.id] > 0) & ink).sum()) / float(ink.sum())
        assert kept > 0.9, (r.id, kept)      # its own lobe, all of it
        lay = fit_region(r, cfg, shares[r.id])
        assert lay.lines, r.id
        # Nothing is dropped to make it fit — a translation goes in whole.
        assert " ".join(lay.lines).split() == said.split(), (r.id, lay.lines)
        assert lay.font_size >= cfg.min_font, (r.id, lay.font_size)
        x, y, w, h = (int(v) for v in r.bbox)
        reach = BOX_LEEWAY * max(4.0, float(min(w, h)))
        f = _font(lay.font_path, lay.font_size)
        for ln, (ox, oy) in zip(lay.lines, lay.line_origins):
            half = f.getlength(ln) / 2.0
            assert ox - half >= x - reach - 1, (r.id, ln, ox - half, x - reach)
            assert ox + half <= x + w + reach + 1, (r.id, ln, ox + half,
                                                    x + w + reach)
            assert oy >= y - reach - 1, (r.id, ln, oy, y - reach)
            assert oy + lay.font_size * lay.leading <= y + h + reach + 1, (
                r.id, ln, oy, y + h + reach)


def test_the_box_is_what_costs_the_point_size():
    """The trade, measured, so nobody undoes it by accident.

    Without the trim these two typeset at 34 and 25 and both reach clear
    outside their own boxes. With it they typeset at 17 and 12 and both stay
    in. If a later change ever makes the untrimmed lobe land inside the box on
    its own, the test above stops proving anything and this one says so.
    """
    from mangatl.typeset import fit_region, _lobe_cut, BOX_LEEWAY, _font

    regions = _found(_two_lobed())
    for r, t in zip(regions, (BUD, TRUNK)):
        r.dst_text = t
    cfg = _cfg()
    lobes = _lobe_cut(regions, [r.bubble_mask for r in regions], cfg)
    assert lobes, "no neck cut; this test protects nothing"
    strayed = 0
    for r in regions:
        lay = fit_region(r, cfg, lobes[r.id])
        assert lay.font_size >= 24, (r.id, lay.font_size)   # the size on offer
        x, y, w, h = (int(v) for v in r.bbox)
        reach = BOX_LEEWAY * max(4.0, float(min(w, h)))
        f = _font(lay.font_path, lay.font_size)
        for ln, (ox, oy) in zip(lay.lines, lay.line_origins):
            half = f.getlength(ln) / 2.0
            if ox - half < x - reach - 1 or ox + half > x + w + reach + 1:
                strayed += 1
    assert strayed, "the untrimmed lobe already stays in the box"


def test_the_division_survives_being_saved_and_reopened():
    """Masks are not saved — a chapter is held as geometry.

    So the outline stored for each half has to be the LOBE's outline. Store the
    whole balloon's and both speeches get the whole balloon back on reload, and
    the merge returns the first time the person reopens the chapter.
    """
    from mangatl.project import region_from_record

    img = _two_lobed()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    regions = _found(img)
    for r, t in zip(regions, (BUD, TRUNK)):
        r.dst_text = t
    back = []
    for r in regions:
        d = r.to_dict()
        d["dst_text"] = r.dst_text
        back.append(region_from_record(d, gray))

    assert [r.link for r in back] == [regions[0].link] * 2
    for r in back:
        assert r.bubble_mask is not None, "reloaded with no balloon at all"
    a, b = (r.bubble_mask > 0 for r in back)
    assert float((a & b).sum()) / float(a.sum()) < 0.05, (
        "the halves came back on top of each other")


def test_the_whole_detector_keeps_the_two_lobes():
    """`detect_combined` is what actually runs, and it de-duplicates.

    Every later pass sees the same balloon again, and the two lobes carry the
    same `bubble_bbox` on purpose — that is how the typesetter knows they are one
    balloon to divide. Weighed one region at a time against what has already
    been taken, the second lobe therefore looks exactly like a duplicate of the
    first, and half of what the balloon says is thrown away between detection
    and the screen.
    """
    regions = classical.detect_combined(Page(image=_two_lobed()))
    assert len(regions) == 2, [r.bbox for r in regions]
    assert len({r.link for r in regions}) == 1 and regions[0].link > 0
    a, b = (r.bubble_mask > 0 for r in regions)
    assert not (a & b).any(), "the two lobes came back on top of each other"


def test_a_second_pass_does_not_reuse_a_link_id():
    """Two passes over one page hand out link ids from one sequence.

    A link id means "these are one sentence, read them in order". Start the
    later pass back at 1 and a balloon it finds is spliced onto an unrelated
    balloon the first pass found, and the translator is told to read the two
    as a single line.
    """
    img = _two_lobed()
    assert [r.link for r in classical.detect_outline(Page(image=img),
                                                    link_base=7)] == [8, 8]


# ---------------------------------------------------------- and what it refuses

def test_a_plain_balloon_is_still_one_region():
    assert len(_found(_one_oval((380, 410)))) == 1


def test_a_chord_may_not_slip_between_two_columns_of_one_balloon():
    """The dangerous false positive, and the reason for two separate guards.

    An ordinary balloon holding a wide gap between two groups of columns offers
    a chord that divides the writing perfectly without touching a character —
    so "no character is cut in half" cannot be the only test. What refuses this
    page is that the oval has no dent deep enough to hang a chord on: a neck is
    a place the outline turns back on itself, and this outline never does.
    """
    regions = _found(_one_oval((220, 250, 540, 570)))
    assert len(regions) == 1, [r.bbox for r in regions]
    assert regions[0].link == 0


def test_a_tail_is_not_a_neck():
    """A tail is a spike, and the hull spans it: two dents, as deep as a neck's.

    Nothing about the outline tells the two apart. What does is that the piece
    a tail's chord cuts off has no writing in it — so the candidate is dropped
    and the real neck is tried next, instead of the balloon being cut at the
    first deep pair of dents and left at that.
    """
    regions = _found(_two_lobed(tail=True))
    assert len(regions) == 2, [r.bbox for r in regions]
    for r in regions:
        assert float((r.text_mask > 0).sum()) > 0, r.id


def test_nothing_of_the_writing_is_lost_in_the_division():
    """Every stroke of the Japanese ends up in one half or the other.

    The text mask is what gets ERASED. A character dropped on the floor between
    the two halves is a character left on the cleaned page forever.
    """
    img = _two_lobed()
    one = classical.detect_outline(Page(image=img))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    whole = np.zeros_like(gray)
    for r in one:
        whole[r.bubble_mask > 0] = 255
    ink = ((gray <= 128) & (whole > 0))
    got = np.zeros_like(gray)
    for r in one:
        got[r.text_mask > 0] = 255
    missed = float((ink & (got == 0)).sum()) / float(ink.sum())
    assert missed < 0.02, missed


# ------------------------------------------------- a dent is not always a neck

SHOUT = [[203, 0], [110, 10], [85, 109], [89, 209], [80, 216], [38, 207],
         [25, 254], [11, 269], [24, 198], [13, 242], [0, 257], [0, 291],
         [12, 288], [3, 330], [49, 430], [137, 429], [150, 353], [187, 361],
         [251, 284], [254, 221], [267, 209], [254, 203], [260, 162], [254, 69]]


def _shout(scale=1.2, at=(330, 210)):
    """lee's angular shout balloon, traced off the page he sent back.

    ONE enclosure. The right-hand flank is a smooth arc; the LEFT is a
    staircase, with a deep step half way down and a spike below it, and the
    typesetting sits in two clumps — a sentence up the right and a small あっ！
    lower and to the left of it. Nothing about that makes it two balloons, and
    lee drew a single box round it by hand.
    """
    img = np.full((H, W), 246, np.uint8)
    p = (np.array(SHOUT, float) * scale + at).astype(np.int32)
    cv2.fillPoly(img, [p], 255)
    _outline(img)
    ink = np.zeros((H, W), np.uint8)
    sx, sy = at

    def col(x, y0, y1):
        for y in range(int(y0), int(y1), int(26 * scale)):
            cv2.rectangle(ink, (int(x - 9 * scale), int(y)),
                          (int(x + 9 * scale), int(y + 18 * scale)), 255, -1)

    col(sx + 165 * scale, sy + 40 * scale, sy + 195 * scale)
    col(sx + 120 * scale, sy + 40 * scale, sy + 195 * scale)
    col(sx + 75 * scale, sy + 300 * scale, sy + 390 * scale)
    img[ink > 0] = 15
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def test_an_angular_balloon_is_one_box_not_two():
    """lee: "each bubbles shoud have their own box".

    Depth alone cannot tell a waist from a staircase. This outline has two
    dents as deep as any neck's — the step in the flank and the spike under it
    — and a chord between them separates the two clumps of writing without
    cutting a character, so every other guard passes it. It is still one
    balloon, and cutting it hands the translator half a sentence twice.
    """
    regions = _found(_shout())
    assert len(regions) == 1, [r.bbox for r in regions]
    assert regions[0].link == 0
    # and the one box holds all of the writing, both clumps of it.
    x, y, w, h = regions[0].bbox
    assert h > 380 and w > 120, regions[0].bbox


def test_the_dents_of_a_real_neck_still_face_each_other():
    """The refusal above must not be a refusal to split anything.

    A waist is two dents pointing at each other along the chord between them.
    lee's staircase bites in from one side twice; a two-lobed balloon dives in
    from both. Measured on these two fixtures the difference is wide — the
    guard is set at 0.85 and the real neck scores near 1.
    """
    two = classical.detect_outline(Page(image=_two_lobed()))
    assert len(two) == 2, [r.bbox for r in two]
