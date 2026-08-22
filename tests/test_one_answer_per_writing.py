"""The double bubble and the bad bubble, both fixed by asking the ink.

lee, with four crops from his chapter: *"also fot anime text detector  fix
these  the double bubble ,a nd bad bubble if possibel"*.

THE BAD BUBBLES were embroidery. Twelve boxes across his 39 pages - eight
rosettes on the dresses of 004, a leaf vine on 011, chevron trim on 015, 022
and 024 - all called text by AnimeText, all kept alive by `regions_from`'s
dark-ink fallback, because dark embroidery on a white dress is nothing but
dark ink. What separates them is measurable and does not mention a language:
the CTD seg head has NO ink in any of the twelve, and the sound-effect
specialist claims none of them, while the real writing that also fails the
seg head - 013's hand-drawn breaths - is COO-claimed at 0.29-0.97 cover
against the junk's uniform 0.00. Two witnesses silent = artwork. CRAFT was
auditioned as a third witness and failed the audition: its one vote at 4x
upscale was FOR a rosette. Cost on 39 pages: one real box, 039's tiny drawn
label on a sandal, which every model on the machine is silent about.

THE DOUBLE BUBBLE is one piece of writing answered twice - ちから boxed
inside 癒やしの力, きょう inside its own column. Sixteen nested pairs on the
chapter, and SIZE cannot resolve them: 020's tight inner box is the right
one, 038's tight inner box is the wrong one. INK can. Measured, the kids'
union held 0.85-1.00 of the parent's seg ink when the parent was padding,
and 0.03-0.57 when the kids were fragments; `SAME_INK` = 0.72 sits between
the ranges with margins of 0.13 and 0.15.

On the 226-site ground truth this costs nothing: 11 missed before and after,
and the route's one junk box is gone - 1 to 0.
"""
import numpy as np
import pytest

from where import PKG

from mangatl.detect import dbcoo as D


def _page(w=200, h=200):
    return np.zeros((h, w), np.uint8)


# ------------------------------------------------------ the bad bubble

def test_a_box_with_no_witness_at_all_is_artwork():
    tm = _page()
    tm[20:60, 120:180] = 255                 # real writing elsewhere
    boxes = [(120, 20, 180, 60),             # seg ink: kept
             (10, 10, 50, 50)]               # embroidery: nothing anywhere
    got = D._backed_by_a_witness(boxes, tm, raw=[])
    assert got == [(120, 20, 180, 60)]


def test_the_specialist_alone_is_witness_enough():
    """013's breaths: zero seg ink, COO all over them."""
    tm = _page()
    b = (10, 10, 50, 50)
    got = D._backed_by_a_witness([b], tm, raw=[(10, 10, 50, 50, 0.9)])
    assert got == [b]


def test_a_kept_neighbour_vouches_for_the_box_on_its_ground():
    """The second breath: no witness of its own, standing on the cluster the
    specialist already claimed."""
    tm = _page()
    claimed = (10, 10, 60, 60)
    rider = (12, 12, 40, 40)                 # >50% inside the claimed one
    got = D._backed_by_a_witness([claimed, rider], tm,
                                 raw=[(10, 10, 60, 60, 0.9)])
    assert claimed in got and rider in got


def test_the_junk_cannot_vouch_for_its_twin():
    """Two boxes of embroidery on top of each other must not save each other
    - the weak pool is only ever measured against the KEPT pool."""
    tm = _page()
    got = D._backed_by_a_witness([(10, 10, 50, 50), (12, 12, 48, 48)],
                                 tm, raw=[])
    assert got == []


# ------------------------------------------------------ the double bubble

def test_a_parent_that_is_only_padding_dies():
    """020: the tight box holds every pixel of the big one's ink."""
    tm = _page()
    tm[50:100, 50:100] = 255
    tight = (50, 50, 100, 100)
    padded = (30, 30, 130, 130)
    got = D._one_answer_per_writing([tight, padded], tm)
    assert got == [tight]


def test_a_furigana_fragment_dies_into_its_column():
    """003: ちから holds a sliver of 癒やしの力's ink."""
    tm = _page()
    tm[20:180, 80:120] = 255                 # the column
    column = (80, 20, 120, 180)
    furi = (80, 150, 120, 178)               # a corner of the same writing
    got = D._one_answer_per_writing([column, furi], tm)
    assert got == [column]


def test_a_coo_claimed_child_is_never_a_fragment():
    """015: the breath strokes inside a panel-sized box. The specialist's
    word outranks the arithmetic it was drowned out of."""
    tm = _page()
    tm[20:180, 20:180] = 255                 # ink all over the panel box
    panel = (10, 10, 190, 190)
    breath = (20, 20, 60, 60)                # a sliver of the panel's ink
    got = D._one_answer_per_writing([panel, breath], tm,
                                    raw=[(20, 20, 60, 60, 0.9)])
    assert breath in got, "COO vouched for it"
    assert panel in got, "and the panel still holds unclaimed ink"


def test_boxes_that_merely_touch_are_left_alone():
    """Two balloons side by side overlap a little and are two answers about
    two writings. `ABSORB_IN` is what keeps this rule off them."""
    tm = _page()
    tm[20:80, 20:80] = 255
    tm[20:80, 90:150] = 255
    a, b = (20, 20, 85, 80), (80, 20, 150, 80)
    got = D._one_answer_per_writing([a, b], tm)
    assert a in got and b in got


# ------------------------------------------------------ the numbers

def test_the_thresholds_are_the_measured_ones():
    """0.72 sits between the fragment range (up to 0.57) and the padding
    range (0.85 and up); 0.58 catches every measured pair (0.60-1.00) and
    leaves grazing balloons alone."""
    assert 0.57 < D.SAME_INK < 0.85
    assert 0.50 < D.ABSORB_IN < 0.60
    assert 0 < D.WITNESS_VOUCH <= 0.29, "under the weakest real COO cover"


def test_the_route_asks_both_questions_in_the_right_order():
    """Artwork first, so a junk box can never save a nested twin by being
    its witnessed neighbour."""
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_animetext("):]
    body = body[:body.index("\ndef ")]
    a = body.index("_backed_by_a_witness(found, tmask, raw)")
    b = body.index("_one_answer_per_writing(found, tmask, raw)")
    assert a < b
    assert body.index("AT.pieces(") < a, "after the model, before the labels"


def test_the_card_records_the_junk_going_to_zero():
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    at = html.index('data-route="animetext"')
    assert 'data-junk="0"' in html[at - 300:at + 300]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
