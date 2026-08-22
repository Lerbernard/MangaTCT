"""Who gets to say a box is dialogue, and who gets to say it is one box.

lee, over a chapter detected by the two-specialist route: *"the box labblig as
messed up and teh box merging shou not happen try to fi thosee"*.

Two faults, two causes, and neither was a threshold.

## THE LABEL

`speech` was the non-sfx boxes only, so a box DB++/COO had claimed never
reached the balloon question at all. COO claims writing set in a display face
inside a balloon -- a display face is what it was trained on -- and once the
label was `sfx` nothing could take it back. 009's また グロウさん…ね, 001's
よく見てください, 005's ...覗けって言います?, 008's どうでした? 温泉初めてで
しょう: all dialogue, all inside a drawn balloon, all coming back `sfx`.

So every box is asked now, and the balloon decides. The evidence it takes is
the strongest there is and only that -- `attach_balloons` having FITTED a
balloon -- because the two weaker tests were measured beside it:

    signal                        promotes                    right?
    a fitted balloon mask         001 よく見てください           yes
                                  005 ...覗けって言います?       yes
                                  008 どうでした? 温泉...        yes
                                  006 きゅっ                    arguable
    a round wall, nothing fitted  003 あ over speed lines       NO
                                  012 っ over screentone        NO
                                  008 おっ, 014 あーもー!        arguable
    the gentle enclosure test     three of eleven artwork fragments read
                                  as enclosed -- see `dbcoo.SFX_GLYPHS`

Every clear win is in the fitted column and both clear losses are outside it.

## THE MERGE

008's ガチャ ガチャ ガチャ arrives from comic-text-detector as ONE 434px
rectangle. Three attacks were measured and two of them cannot work:

    the sound-effect pool's reach   swept 0.30 -> 0. The widest sfx box moves
                                    by ZERO pixels. Not this route's weld.
    `_two_texts_in`                 fires on nothing: three effects in a row
                                    share every row and stack nowhere.
    an empty-band split             0.19 of a character on 008 and 0.04 on
                                    007, against 0.45 INSIDE 003's ひゃあぁ,
                                    which is one effect. Ranges reversed.

What works is asking the specialist, which detected each effect separately
before anything grouped them: 008's rectangle holds three COO polygons, 007's
ゲホ ゲホ two, and every effect that really is one holds one.
"""
import numpy as np
import pytest

from where import PKG

from mangatl.detect import dbcoo
from mangatl.detect import comictext as CT
from mangatl.models import TextRegion


def _region(kind, mask):
    h, w = mask.shape
    return TextRegion(id=0, bbox=(0, 0, w, h), text_mask=mask,
                      bubble_mask=None, bubble_bbox=(0, 0, w, h), kind=kind,
                      src_vertical=False)


def _two_stacked():
    """Two blocks of writing with a wide empty band between them."""
    m = np.zeros((300, 200), np.uint8)
    for r in range(4):
        for c in range(4):
            m[20 + r * 20:32 + r * 20, 20 + c * 20:32 + c * 20] = 255
    for r in range(4):
        for c in range(4):
            m[200 + r * 20:212 + r * 20, 20 + c * 20:32 + c * 20] = 255
    return m


def _label(kind, fitted=False, wall=False, enclosed=False):
    return dbcoo.label_from_balloon(kind, fitted, lambda: wall,
                                    lambda: enclosed)


def test_a_fitted_balloon_makes_it_dialogue_whoever_found_it():
    """009's また グロウさん…ね and 008's どうでした? 温泉初めてでしょう."""
    for kind in ("sfx", "bubble", "freefloat", "narration"):
        assert _label(kind, fitted=True) == "bubble", kind


def test_a_sound_effect_is_not_promoted_by_a_wall():
    """003's あ over speed lines and 012's っ over screentone."""
    assert _label("sfx", wall=True) == "sfx"
    assert _label("sfx", enclosed=True) == "sfx"
    assert _label("sfx", wall=True, enclosed=True) == "sfx"


def test_a_sound_effect_with_no_balloon_is_left_alone():
    """Not demoted either: COO said paint and nothing has contradicted it."""
    assert _label("sfx") == "sfx"


def test_writing_with_a_line_round_it_is_dialogue():
    assert _label("bubble", wall=True) == "bubble"
    assert _label("bubble", enclosed=True) == "bubble"
    assert _label("freefloat", wall=True) == "bubble"


def test_writing_with_nothing_round_it_is_outside_text():
    assert _label("bubble") == "freefloat"
    assert _label("freefloat") == "freefloat"


def test_the_walls_are_not_measured_unless_they_are_needed():
    """Each is a Canny pass round the rectangle, and most boxes never need
    one: a fitted balloon settles it, and so does the sound-effect family."""
    calls = []

    def wall():
        calls.append("wall")
        return True

    def enclosed():
        calls.append("enclosed")
        return True

    dbcoo.label_from_balloon("bubble", True, wall, enclosed)
    assert calls == []
    dbcoo.label_from_balloon("sfx", False, wall, enclosed)
    assert calls == []
    dbcoo.label_from_balloon("bubble", False, wall, enclosed)
    assert calls == ["wall"]


def test_a_sound_effect_is_left_alone_by_default():
    """The manhwa behaviour, unchanged: a painted effect is not split."""
    out = CT._each_text_its_own_box([_region("sfx", _two_stacked())])
    assert len(out) == 1


def test_the_manga_route_asks_about_the_sound_effects_too():
    out = CT._each_text_its_own_box([_region("sfx", _two_stacked())],
                                    skip_sfx=False)
    assert len(out) == 2


def test_dialogue_is_split_either_way():
    for skip in (True, False):
        out = CT._each_text_its_own_box([_region("bubble", _two_stacked())],
                                        skip_sfx=skip)
        assert len(out) == 2, skip


def test_a_box_with_no_mask_is_never_split():
    r = TextRegion(id=0, bbox=(0, 0, 10, 10), text_mask=None,
                   bubble_mask=None, bubble_bbox=(0, 0, 10, 10),
                   kind="bubble", src_vertical=False)
    assert len(CT._each_text_its_own_box([r], skip_sfx=False)) == 1


def test_both_splits_are_on_for_manga():
    """lee: *"teh box merging shou not happen"*."""
    assert dbcoo.SPLIT_TEXTS is True
    assert dbcoo.SPLIT_SFX is True


def test_the_route_reads_both_switches():
    import inspect
    sig = inspect.signature(dbcoo.detect_ctd_sfx)
    assert sig.parameters["split_texts"].default is dbcoo.SPLIT_TEXTS
    assert sig.parameters["split_sfx"].default is dbcoo.SPLIT_SFX


def test_a_grazing_effect_is_not_one_of_the_things_in_the_box():
    """`SFX_PIECE_IN` is a share of the PIECE, not of the box.

    008's three ガチャ each sit almost wholly inside the rectangle drawn round
    them; a neighbouring effect that overlaps a corner does not.
    """
    box = (100, 100, 400, 300)
    inside = (120, 120, 200, 280)
    grazing = (380, 280, 600, 500)
    assert dbcoo._share(inside, box) > dbcoo.SFX_PIECE_IN
    assert dbcoo._share(grazing, box) < dbcoo.SFX_PIECE_IN


def test_the_piece_share_sits_between_a_whole_effect_and_a_corner():
    assert 0.3 < dbcoo.SFX_PIECE_IN < 0.9


def test_the_share_is_measured_of_the_piece_and_not_of_the_box():
    """The direction matters and the two answers are nothing alike.

    COO regularly returns a polygon far BIGGER than the box that claimed it,
    because it has found more of the effect than comic-text-detector did.
    Measuring the BOX's share of the piece would read that as a whole effect
    sitting inside, and split a rectangle that holds exactly one thing.
    """
    box = (100, 100, 200, 200)
    piece = (0, 0, 400, 400)
    assert dbcoo._share(piece, box) < dbcoo.SFX_PIECE_IN     # not one of many
    assert dbcoo._share(box, piece) > dbcoo.SFX_PIECE_IN     # the wrong way


def test_the_measurements_stay_next_to_the_code():
    """The reach sweep is the reason this pass exists rather than a tighter
    pool, and somebody will ask why."""
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    assert "ZERO pixels" in src
    assert "SFX_PIECE_IN" in src
