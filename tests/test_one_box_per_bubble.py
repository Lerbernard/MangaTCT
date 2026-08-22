"""One balloon, one box - and inside that box, one section per clump.

lee, on the boxes the finder drew: "the boxes shoud be around the bubbles no 2
of them split randomly, each bubbles shoud have their own box". What he sent
back was a single shout balloon with a dead-flat horizontal seam across the
middle of it - box 11 stopped part way down, box 12 started seven pixels lower,
and between them they divided one outline.

That seam does not come from the neck finder, whose lobes are irregular and
overlap. It comes from the other end: two blocks of writing are read out of one
enclosure, `attach_balloons` sees two regions wanting one balloon, and `_share`
slices the balloon into full-width horizontal BANDS so each of them has
somewhere to be typeset.

Then he drew on the picture: a green ring round the sentence, a blue ring round
the small あっ！ beneath it, a dot at the centre of each, both inside the one red
box. "make it so that the bubbles can have 2 sections the green text shouyd be
its own section and the blue be its own section under the one box, and the
typesetting should still typeset them in their own sections where the dot is".

So neither block is thrown away and neither is banded. They keep their own
writing, their own translation and their own typesetting; they are given the same
`box_group`, which is what makes the editor draw ONE box round the pair; and
the balloon is divided between them by NEARNESS, so the boundary runs between
the two clumps rather than straight across the balloon and through both.

The tests that matter most are the ones about what must NOT be sectioned: two
genuinely separate balloons, and a two-lobed balloon whose halves the outline
detector has already divided.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl.detect import classical
from mangatl.detect.balloon import attach_balloons, sections_in_one_balloon
from mangatl.models import Page, TextRegion

H, W = 900, 1000


def _rim(img):
    cnts, _ = cv2.findContours((img >= 250).astype(np.uint8),
                               cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, cnts, -1, 20, 3)
    return img


def _write(img, boxes):
    """Stamp blocks of typesetting, and hand back one mask per block.

    Characters, not solid slabs. Real typesetting leaves the paper around it
    connected, and that connectedness is the whole signal here: two clumps
    standing on one run of white paper are two clumps in one balloon.
    """
    out = []
    for x0, y0, x1, y1 in boxes:
        m = np.zeros((H, W), np.uint8)
        for x in range(x0, x1 - 12, 30):
            for y in range(y0, y1 - 12, 30):
                cv2.rectangle(m, (x, y), (x + 18, y + 18), 255, -1)
        m[img < 250] = 0                      # nothing written on the rim
        img[m > 0] = 15
        out.append(m)
    return out


def _blocks(masks):
    """The regions a text detector hands over: writing, and no balloon yet."""
    return [TextRegion(id=i, kind="bubble", text_mask=m,
                       bbox=tuple(int(v) for v in cv2.boundingRect(m)))
            for i, m in enumerate(masks)]


def _one_balloon():
    """One oval, laid out the way lee's shout balloon reads.

    The sentence runs up the RIGHT of the balloon and the small あっ！ sits
    lower and to the LEFT of it, so the two clumps share about twenty rows.
    That is what made the old code band the balloon: the overlap is under
    `stack_overlap`, so the blocks looked stacked, and stacked blocks got a
    straight cut across the full width.
    """
    img = np.full((H, W), 246, np.uint8)
    cv2.ellipse(img, (430, 420), (150, 210), 0, 0, 360, 255, -1)
    _rim(img)
    masks = _write(img, [(430, 250, 540, 430), (330, 410, 420, 500)])
    return img, masks


def _two_balloons():
    """Two separate ovals - lee's picture 1, which he sent back as CORRECT."""
    img = np.full((H, W), 246, np.uint8)
    cv2.ellipse(img, (350, 400), (130, 170), 0, 0, 360, 255, -1)
    cv2.ellipse(img, (620, 620), (85, 80), 0, 0, 360, 255, -1)
    _rim(img)
    masks = _write(img, [(280, 300, 420, 500), (570, 580, 670, 660)])
    return img, masks


def _sectioned():
    img, masks = _one_balloon()
    regions = _blocks(masks)
    assert sections_in_one_balloon(img, regions) == 1
    return img, masks, regions


# ------------------------------------------------------- what it sections

def test_two_blocks_in_one_balloon_share_one_box_group():
    """Both blocks live. They are grouped, not merged."""
    img, masks, regions = _sectioned()
    assert len(regions) == 2, [r.bbox for r in regions]
    a, b = regions
    assert a.box_group > 0 and a.box_group == b.box_group
    assert {a.order, b.order} == {0, 1}
    # NOT linked. A link means "one sentence split across balloons", and the
    # translator honours it by splitting one English sentence between them.
    # lee asked for these to be READ as two sections, so each keeps its own
    # reading and its own translation.
    assert a.link == 0 and b.link == 0


def test_the_box_the_editor_draws_is_one_box_round_the_balloon():
    """The group's boxes union to the balloon, not to half of it.

    This is the seam lee sent back, stated as a measurement: whatever the two
    sections are, together they have to reach from the top of the writing to
    the foot of it and across the balloon's width.
    """
    img, masks, regions = _sectioned()
    xs = [r.bubble_bbox for r in regions]
    x0 = min(b[0] for b in xs)
    y0 = min(b[1] for b in xs)
    x1 = max(b[0] + b[2] for b in xs)
    y1 = max(b[1] + b[3] for b in xs)
    assert y0 <= 250 and y1 >= 560, xs
    assert x1 - x0 > 250, xs


def test_each_section_keeps_its_own_writing_and_only_its_own():
    """A section is where one block's English goes. It must hold that block.

    And it must not hold the other's: a share that covers both clumps is a
    share the fitter will typeset across both, which is the two-speeches-on-top
    -of-each-other fault in another costume.
    """
    img, masks, regions = _sectioned()
    for r, other in zip(regions, regions[::-1]):
        mine = r.text_mask > 0
        share = r.bubble_mask > 0
        # Nearly all of my own writing - the few strokes that fall short are
        # the ones running under the rim, which is outside the balloon's
        # filled outline and so outside every share.
        assert float((mine & share).sum()) >= 0.9 * float(mine.sum())
        theirs = other.text_mask > 0
        assert not (theirs & share).any()


def test_the_two_sections_do_not_overlap():
    """One pixel of paper belongs to one section."""
    img, masks, regions = _sectioned()
    a, b = (r.bubble_mask > 0 for r in regions)
    assert not (a & b).any()


def test_the_division_follows_the_writing_not_a_flat_band():
    """The seam, gone.

    A band cut gives the upper block every row above the cut and the lower
    block every row below it, so the two shares cannot overlap in rows at all.
    Dividing by nearness puts the boundary BETWEEN the two clumps instead, so
    the sentence keeps the upper right while あっ！ keeps the lower left and the
    two shares share rows.
    """
    img, masks, regions = _sectioned()
    (ax, ay, aw, ah), (bx, by, bw, bh) = (r.bubble_bbox for r in regions)
    rows = min(ay + ah, by + bh) - max(ay, by)
    assert rows > 40, ((ax, ay, aw, ah), (bx, by, bw, bh))


def test_the_sections_survive_a_save_and_a_load():
    """A chapter is held as geometry, so each share has to be stored as one.

    Store the whole balloon's outline against both sections and they both get
    the whole balloon back on reload, and the two speeches are typeset on top
    of each other again - with nothing in the editor to show why.
    """
    from mangatl.project import region_record, region_from_record

    img, masks, regions = _sectioned()
    page = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    back = [region_from_record(region_record(r), page) for r in regions]
    assert [r.box_group for r in back] == [r.box_group for r in regions]
    assert all(r.bubble_mask is not None for r in back)
    a, b = (r.bubble_mask > 0 for r in back)
    assert float((a & b).sum()) < 0.05 * float(min(a.sum(), b.sum()))
    for was, now in zip(regions, back):
        want = float((was.bubble_mask > 0).sum())
        got = float((now.bubble_mask > 0).sum())
        assert 0.8 * want <= got <= 1.25 * want, (want, got)


def test_typesetting_typesets_each_section_inside_its_own_section():
    """lee: "the typsetting shoud still typeseet them in there own sections".

    Every line of each block's English has to land in that block's share of
    the paper - the dot he drew is the centre of the share, not the centre of
    the balloon.
    """
    from mangatl.typeset import TypesetConfig, typeset_page

    img, masks, regions = _sectioned()
    page = Page(image=cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), regions=regions)
    regions[0].dst_text = "THERE'S SOMETHING IN THERE"
    regions[1].dst_text = "AH!"
    typeset_page(page, TypesetConfig())
    for r in regions:
        assert r.layout is not None and r.layout.line_origins
        share = r.bubble_mask > 0
        for x, y in r.layout.line_origins:
            yy = min(max(int(y), 0), share.shape[0] - 1)
            xx = min(max(int(x), 0), share.shape[1] - 1)
            assert share[yy, xx], (r.id, (x, y), r.bubble_bbox)


# --------------------------------------------------------- what it leaves alone

def test_two_separate_balloons_still_get_a_box_each():
    """Two enclosures is two balloons is two boxes. lee's picture 1."""
    img, masks = _two_balloons()
    regions = _blocks(masks)
    assert sections_in_one_balloon(img, regions) == 0
    assert len(regions) == 2, [r.bbox for r in regions]
    assert all(r.box_group == 0 for r in regions)
    assert all(r.bubble_mask is None for r in regions)


def test_a_two_lobed_balloon_keeps_its_two_lobes():
    """The outline detector already divided this one, and it was right to.

    Its regions arrive carrying a balloon of their own, and anything carrying
    one is left alone - otherwise the section pass would re-divide a division
    that was already correct, and might do it differently.
    """
    from test_two_lobes import _two_lobed

    img = _two_lobed()
    regions = classical.detect_outline(Page(image=img))
    assert len(regions) == 2
    before = [(r.bubble_mask > 0).sum() for r in regions]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert sections_in_one_balloon(gray, regions) == 0
    assert [(r.bubble_mask > 0).sum() for r in regions] == before
    assert all(r.box_group == 0 for r in regions)


def test_sfx_is_never_sectioned_with_a_speech():
    """An effect painted over the balloon is not part of what is said."""
    img, masks = _one_balloon()
    regions = _blocks(masks)
    regions[1].kind = "sfx"
    assert sections_in_one_balloon(img, regions) == 0
    assert all(r.box_group == 0 for r in regions)


def test_the_old_band_cut_is_what_this_replaces():
    """Left to `attach_balloons`, this balloon still bands. That is the bug.

    Kept as a test so that the section pass is never quietly moved to the
    reload path, where it would re-cut a division somebody had corrected by
    hand: the two are different answers to the same question, and this states
    which one `attach_balloons` gives.
    """
    img, masks = _one_balloon()
    banded = _blocks(masks)
    attach_balloons(img, banded)
    a, b = (r.bubble_bbox for r in banded)
    top, low = sorted((a, b), key=lambda t: t[1])
    assert top[1] + top[3] <= low[1] + 12, (a, b)      # the flat seam


def test_detection_sections_them_before_anything_is_numbered():
    """Ids are handed out after the pass, so they run 0,1,2,... with no hole.

    And the pass has to happen HERE and nowhere else: `attach_balloons` runs
    again on every load, and re-cutting the shares there would overwrite a
    division somebody had corrected by hand.
    """
    import inspect
    from mangatl import project

    # Find text is TWO methods since the AI option arrived: `detect` chooses
    # which way to get boxes, `_detect_measured` is the measuring way. Read
    # both, or a source check silently stops covering the half that moved.
    src = (inspect.getsource(project.Project.detect)
           + inspect.getsource(project.Project._detect_measured))
    assert "sections_in_one_balloon" in src
    assert "sections_in_one_balloon" not in inspect.getsource(
        project.Project.materialize)
