"""On the AnimeText route, only a FITTED balloon makes a box dialogue.

lee, over a page of monologue set straight onto hatched art with two boxes
wrongly red: *"can you try to improve the animetext box clasification
expesialy the  freefloat and inside etxt"*.

Measured over the 23-page chapter he was looking at. The text-family boxes
split three ways:

    133  balloon fitted from the ink        - right
     12  promoted by the wall/enclosure     - ELEVEN of them monologue on
         texture tests                        artwork, by eye; the twelfth a
                                              drawn plate
     26  freefloat                          - four of them REAL balloons the
                                              ink fitter cannot fit: two
                                              clouds, two white-on-black

So both texture tests are gone from this route - hatching reads as a wall
far too often on manga for either to be trusted with the question - and the
balloon MODEL (`comicbubble.name_the_balloons`, which only ever ADDS a
balloon where measurement found nothing) is asked instead, for exactly the
four the fitter misses. After the change, all sixteen decisive boxes come
back right or defensible: the eleven monologues freefloat, the four missed
balloons fitted and bubble - including 009's white-on-black, which this
pipeline had never once got right - and the plate the model fitted on 021
is a drawn enclosure by eye.

Ground truth after: missed 11, junk 0 - both unchanged.
"""
import pytest

from where import PKG

from mangatl.detect import dbcoo as D


def _route_body():
    src = (PKG / "detect" / "dbcoo.py").read_text(encoding="utf-8")
    body = src[src.index("def detect_animetext("):]
    return body[:body.index("\ndef ")]


def test_the_texture_tests_are_gone_from_this_route():
    """`_round_wall_around` promoted eleven pieces of monologue on 23 pages.
    The label loop hands `label_from_balloon` constant noes instead."""
    body = _route_body()
    at = body.index("label_from_balloon")
    call = body[at:at + 300]
    assert "lambda: False, lambda: False" in call
    assert "_round_wall_around" not in body[body.index("B.attach_balloons"):]


def test_the_balloon_model_is_asked_for_what_ink_cannot_fit():
    """Two clouds and two white-on-black on the measured chapter. The model
    runs after the fitter and before the labels, or its answer names nothing."""
    body = _route_body()
    a = body.index("B.attach_balloons(gray, regions)")
    b = body.index("_CB.name_the_balloons(img, regions, bubble_weights)")
    c = body.index("label_from_balloon")
    assert a < b < c
    assert "if bubble_weights:" in body[a:b], "and absent weights cost nothing"


def test_the_route_is_handed_the_weights_by_the_project():
    src = (PKG / "project.py").read_text(encoding="utf-8")
    at = src.index("dbcoo.detect_animetext(")
    call = src[at:at + 600]
    assert "bubble_weights=self.bubble_weights()" in call


def test_without_a_balloon_the_box_is_freefloat_full_stop():
    """The label function itself, asked the way this route now asks it."""
    assert D.label_from_balloon("text", False,
                                lambda: False, lambda: False) == "freefloat"
    assert D.label_from_balloon("text", True,
                                lambda: False, lambda: False) == "bubble"
    # ...and a sound effect is a sound effect whatever the balloon says.
    assert D.label_from_balloon("sfx", False,
                                lambda: False, lambda: False) == "sfx"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
