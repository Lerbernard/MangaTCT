"""A box 95% inside a similar-sized bigger box is the same paint twice.

lee, with a white-on-black effect wearing two overlapping boxes: *"thsi si
aculy 2 boxes fix double boxing"*, then the rule in his own words: *"two
bozes should not be covering teh same text if a bigger box cover it
100%-95%]"*. His number is `DUPE_IN`.

Why the ink rule missed these: white-on-black paint leaves the seg head
silent, so `_one_answer_per_writing` has nothing to measure - and a
COO-vouched fragment walks past the kids-union rule on its vouch. Both boxes
witness the SAME paint, so at 95% containment the vouch proves nothing.

The RATIO cap is the other half. Measured on the 39-page chapter: the true
dupes sit at 2.6x and 3.3x the smaller box (001's painted title boxed
twice, 013's breath boxed inside its own two-line box - both eyeballed);
the 015 panel monster at 7.6x; the vouched-breaths-in-a-panel case at 20x.
Applied to every box of all 39 pages the rule drops exactly the two dupes
and nothing else.
"""
import pytest

from where import PKG

from mangatl.detect import dbcoo as D


def test_the_painted_title_keeps_one_box():
    """001: the fragment fully inside the box that holds all of it."""
    got = D._one_box_per_paint([(0, 0, 166, 179), (0, 0, 434, 180)])
    assert got == [(0, 0, 434, 180)]


def test_the_breath_keeps_one_box():
    """013: measured share 1.0, ratio 3.3."""
    a, b = (697, 1013, 728, 1081), (695, 973, 759, 1082)
    assert D._one_box_per_paint([a, b]) == [b]


def test_the_panel_monster_absorbs_nothing():
    """015: the real box sits fully inside a box 7.6x its size. Deleting
    the small REAL box into the junk panel box would be the worst fix, and
    the ratio cap is what forbids it."""
    real = (454, 925, 591, 1104)
    panel = (431, 905, 836, 1365)
    assert len(D._one_box_per_paint([real, panel])) == 2


def test_under_95_percent_is_not_a_dupe():
    """015's other pair stands 82% inside the panel: two answers about two
    things that happen to share ground."""
    a = (751, 987, 855, 1165)          # 82% inside b
    b = (431, 905, 836, 1365)
    got = D._one_box_per_paint([a, b], ratio=100)   # even with no ratio cap
    assert len(got) == 2


def test_boxes_that_merely_overlap_are_left_alone():
    got = D._one_box_per_paint([(0, 0, 100, 100), (50, 0, 160, 100)])
    assert len(got) == 2


def test_the_numbers_are_lees_and_the_measured_wedge():
    assert D.DUPE_IN == 0.95, 'lee: "100%-95%"'
    assert 3.3 < D.DUPE_RATIO < 7.6, "between the dupes and the panel box"


def test_the_route_runs_it_after_the_ink_rule():
    """Ink decides what it can; this rule only sees what ink could not
    arbitrate."""
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_animetext("):]
    body = body[:body.index("\ndef ")]
    a = body.index("_one_answer_per_writing(found, tmask, raw)")
    b = body.index("_one_box_per_paint(found)")
    assert a < b


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
