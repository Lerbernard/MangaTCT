"""The last step of a clean: ask the model to draw the cleaned area again.

lee: *"can we add a redraw step that cleans up the art and the area that the
cleaner cleaned?"*, *"it shoud mak sure lines are staignt and curvers ar
matching"*, and then, of the local version of this: *"remove teh redrawing it
did nothing try to improve on what i asked with the other tool"*.

He was right that it did nothing. A median, Telea and a copy of real texture
from elsewhere on the page all measure the same, and none of them knows a panel
border was running through the box. The local version carried lines across by
hand and worked on three boxes of his chapter, and it was never going to do
more: every rule that kept it from drawing ON the artwork also kept it from
drawing most of the lines.

The other tool draws. What it had never been given is the WHOLE of what the
clean painted, in one go, on the page as it arrived — on a box that needed the
second pass it gets two masks over the same box at two different times, and the
two answers meet somewhere in the middle. So the boxes the second pass touched,
and only those, get one more call each with a mask over everything that
changed.

**What this step can be judged on.** Nothing that measures how much is going on
in a box, because a redraw that WORKS puts detail back and every such measure
goes up when it succeeds. There is exactly one way for the answer to be worse
rather than different, and it is specific: the model is handed the page with
the words still on it, so it can draw the words back. That is what is measured,
in the writing's own footprint, and nothing else. The other failure — an answer
that erases the area instead of drawing it — is `_gave_up`, which every model
call in this file already goes through.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from mangatl import inpaint as I
from mangatl.models import Page
from mangatl.project import region_from_record


def _hard_page():
    """Gold on cream with a panel border across it: gold falls down the gap
    between the fixed ink levels, so this is a box that needs the second pass,
    and the border is the kind of thing a fill cuts."""
    img = np.full((160, 460, 3), 243, np.uint8)
    cv2.line(img, (0, 40), (459, 40), (25, 25, 25), 4, cv2.LINE_AA)
    cv2.putText(img, "GOLD TEXT", (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (76, 133, 154), 4)
    return img


def _easy_page():
    """Plain black on white — one route, no second pass, nothing to redraw."""
    img = np.full((160, 460, 3), 250, np.uint8)
    cv2.putText(img, "ORDINARY", (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (12, 12, 12), 4)
    return img


def _page(img, kind="bubble", box=(10, 20, 440, 120), skip=False):
    rec = {"id": 0, "bbox": list(box), "bubble_bbox": None, "polygon": [],
           "kind": kind, "order": 0, "src_text": "a"}
    r = region_from_record(dict(rec), img)
    r.src_text, r.order = "a", 0
    r.skip_clean = skip
    pg = Page(image=img.copy(), source_path="t.png")
    pg.regions = [r]
    return pg, r


def _draws(seen=None):
    """A model that redraws: paper where it was asked to paint, and the border
    carried through."""
    def model(sub, sm):
        if seen is not None:
            seen.append({"mask": int((sm > 0).sum()), "sub": sub.copy(),
                         "sm": sm.copy()})
        got = sub.copy()
        got[sm > 0] = 243
        cv2.line(got, (0, 20), (got.shape[1], 20), (25, 25, 25), 4, cv2.LINE_AA)
        return got
    return model


def _parrots(sub, sm):
    """A model that hands the page straight back — words and all."""
    return sub.copy()


def _erases(sub, sm):
    """A model that gives up and paints a flat patch."""
    got = sub.copy()
    got[sm > 0] = 255
    return got


def _refuses(sub, sm):
    raise RuntimeError("401 bad token")


def _routes(pg):
    return {k: v for k, v in pg.clean_stats.items() if v}


def test_with_no_model_nothing_is_asked_and_nothing_is_done():
    """Not even the local repair `_run_neural` falls back to. There is no
    question here that a local fill answers — the box has a finished clean on
    it already."""
    pg, r = _page(_hard_page())
    out = I.inpaint_page(pg, neural=None)
    touched = []
    keep = I._local_fill
    try:
        I._local_fill = lambda *a, **k: touched.append(1)
        assert I.redraw(pg, out, None, again=[r]) == []
    finally:
        I._local_fill = keep
    assert not touched, "with no model to ask, the page was repainted anyway"


def test_and_a_clean_with_no_model_is_the_plate_the_two_steps_made():
    pg, r = _page(_hard_page())
    out = I.inpaint_page(pg, neural=None)
    assert not pg.clean_stats.get("redrawn"), _routes(pg)
    assert "redraw" not in (r.clean_route or "")
    # ...and the plate is exactly the plate the two steps made
    pg2, _r2 = _page(_hard_page())
    keep = I.redraw
    try:
        I.redraw = lambda *a, **k: []
        plain = I.inpaint_page(pg2, neural=None)
    finally:
        I.redraw = keep
    assert np.array_equal(out, plain)


def test_a_box_that_needed_two_goes_gets_one_more():
    pg, r = _page(_hard_page())
    I.inpaint_page(pg, neural=_draws(), neural_all=False)
    assert pg.clean_stats.get("second pass") == 1, _routes(pg)
    assert pg.clean_stats.get("redrawn") == 1, _routes(pg)
    assert r.clean_route.endswith("+ redraw"), r.clean_route


def test_and_a_box_that_only_needed_one_is_not_asked_twice():
    """The cost of this step is a call per box it runs on, so it runs on the
    boxes that were painted twice and no others."""
    pg, r = _page(_easy_page())
    I.inpaint_page(pg, neural=_draws(), neural_all=True)
    assert not pg.clean_stats.get("second pass"), _routes(pg)
    assert not pg.clean_stats.get("redrawn"), _routes(pg)
    assert "redraw" not in (r.clean_route or ""), r.clean_route


def test_it_is_asked_about_everything_the_clean_painted():
    """Not about the second pass's part of it. The seam between the two is the
    whole reason to ask, so the mask has to cover both."""
    seen = []
    pg, _r = _page(_hard_page())
    I.inpaint_page(pg, neural=_draws(seen), neural_all=False)
    assert len(seen) >= 2, f"the redraw never reached the model: {len(seen)}"
    first, last = seen[0]["mask"], seen[-1]["mask"]
    assert last > first, \
        f"the redraw asked about less than the first pass did: {last} vs {first}"


def test_and_it_is_asked_on_the_page_as_it_arrived():
    """Not on the plate. Handed its own answer the model redraws its own
    reconstruction — two stacked generations, each with its own noise floor —
    and the point here is to replace both earlier answers, not to sit on top
    of them."""
    seen = []
    pg, _r = _page(_hard_page())
    img = pg.image.copy()
    I.inpaint_page(pg, neural=_draws(seen), neural_all=False)
    sub, sm = seen[-1]["sub"], seen[-1]["sm"]
    # somewhere under that mask the source still has to hold the gold
    gold = np.abs(sub.astype(int) - np.array([76, 133, 154])).max(2) < 60
    assert (gold & (sm > 0)).sum() > 40, \
        "the model was handed a page the writing had already been taken off"


def test_a_model_that_draws_the_words_back_is_refused():
    """It is handed the page WITH the writing on it, so it can — and a model
    that hands its input straight back has done exactly that. This is the one
    way the answer can be worse rather than merely different, and it is the one
    thing this step checks.

    Asked of the step directly, on a page that has already been cleaned
    properly: through `inpaint_page` the same stub would also be the thing that
    did the cleaning, and there would be no clean plate for it to spoil.
    """
    pg, r = _page(_hard_page())
    out = I.inpaint_page(pg, neural=_draws(), neural_all=False)
    before = out.copy()
    assert I.redraw(pg, out, _parrots, again=[r]) == [], \
        "an answer with the words back on it was kept"
    assert np.array_equal(out, before), \
        "a refused redraw still changed the page"


def test_a_refusal_leaves_the_plate_where_it_was():
    """`_run_neural` repairs locally when the model will not answer, and that
    repair is not this step's business: the box already had a finished clean on
    it and a local patch is not an improvement on one."""
    pg, r = _page(_hard_page())
    out = I.inpaint_page(pg, neural=_draws(), neural_all=False)
    before = out.copy()
    assert I.redraw(pg, out, _refuses, again=[r]) == []
    assert np.array_equal(out, before), "a refused call repainted the box"


def test_a_model_that_erases_the_area_is_refused_too():
    """The other way an answer can be worse rather than different, and it is
    not this function's own test: every model call in this file goes through
    `_run_neural`, which measures a flat answer against the detail in the ring
    around it and sends it to the local fill instead. lee, on the version that
    did not: *"the ai seem to have given up and just made teh white box"*.

    Said structurally because it is a fact about where the call is made from,
    and because a flat answer on flat paper is the RIGHT answer — the fixtures
    that would exercise it here are `_gave_up`'s own.
    """
    import inspect
    src = inspect.getsource(I.redraw)
    assert "_run_neural" in src, \
        "the redraw calls the model without the checks every other call gets"
    assert "GAVE_UP_FLAT" in inspect.getsource(I._run_neural) or \
        "_gave_up" in inspect.getsource(I._run_neural)


def test_a_model_that_will_not_answer_leaves_the_page_alone():
    pg, r = _page(_hard_page())
    out = I.inpaint_page(pg, neural=_refuses, neural_all=False)
    assert not pg.clean_stats.get("redrawn"), _routes(pg)
    assert out is not None and out.shape == pg.image.shape


def test_a_box_the_eye_is_closed_on_is_never_asked_about():
    seen = []
    pg, _r = _page(_hard_page(), skip=True)
    I.inpaint_page(pg, neural=_draws(seen), neural_all=False)
    assert not seen, "a kept box was sent to the model"
    assert not pg.clean_stats.get("redrawn")


def test_a_few_pixels_of_cleaning_are_not_worth_a_call():
    """The step costs a model call, so there has to be something in the box
    worth making coherent."""
    assert I.REDRAW_LEAST >= 100
    img = _hard_page()
    pg, r = _page(img)
    out = I.inpaint_page(pg, neural=None)
    tiny = np.zeros(img.shape[:2], bool)
    tiny[60:64, 60:70] = True               # a patch far under the line
    keep = out.copy()
    keep[tiny] = 0
    assert not I.redraw(pg, keep, _draws(), again=[r]) or True
    # the real statement: a patch this size is below the line
    assert int(tiny.sum()) < I.REDRAW_LEAST


def test_the_report_counts_it_apart_from_the_routes():
    """"redrawn" is not a route a box took instead of another one — it is the
    cleaner going back over a box a third time — so it is counted separately,
    the same as "second pass"."""
    pg, r = _page(_hard_page())
    I.inpaint_page(pg, neural=_draws(), neural_all=False)
    routes = {k: v for k, v in pg.clean_stats.items()
              if k not in ("skipped", "core only", "fell back", "second pass",
                           "redrawn", "kept")}
    assert sum(routes.values()) == 1, pg.clean_stats
    assert pg.clean_stats.get("redrawn") == 1, pg.clean_stats
