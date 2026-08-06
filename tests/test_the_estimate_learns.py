"""The estimate corrects itself against what runs really cost.

`SHAPES` was fitted to one chapter of one series on one model. A gag manga with
three words a bubble and a dense fantasy webtoon do not cost the same per box,
and no constant written in the table will ever know which one is on screen. The
meter does: every run writes down what it used beside the size of what it was
asked to do, and `coins.drift` reads them back as two multipliers.

lee: *"also write a estimating systhem taht will estimate teh cost in coin for
each step try to mak eit accurate"*.
"""
import pytest

from mangatl import coins


@pytest.fixture(autouse=True)
def purse(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    return tmp_path


def _ran(step="translate", model="gemini-3.6-flash", backend="gemini",
         boxes=213, pages=23, ctx=0, ratio_in=1.0, ratio_out=1.0):
    """A metered run of the given size that came in at the given ratio."""
    tin, cached, tout = coins.predicted(step, boxes, pages, ctx, model, backend)
    coins.note("%s cost" % step, "pages 1-%d" % pages, model,
               step=step, backend=backend, boxes=boxes, pages=pages, ctx=ctx,
               tin=int(tin * ratio_in), cached=int(cached * ratio_in),
               tout=int(tout * ratio_out), calls=pages, coins=1, charged=1)


# --------------------------------------------------------------- from nothing

def test_a_fresh_install_trusts_the_table():
    """Until the machine has said otherwise, the shape is the whole answer.
    Anything else would be inventing evidence to correct with."""
    assert coins.drift("translate", "gemini-3.6-flash") == (1.0, 1.0)
    assert coins.drift("ocr", "claude-sonnet-5") == (1.0, 1.0)


def test_a_run_that_came_in_on_the_shape_leaves_it_alone():
    _ran()
    assert coins.drift("translate", "gemini-3.6-flash") == (1.0, 1.0)


# ------------------------------------------------------------- and from runs

def test_a_series_that_costs_more_than_the_shape_says_raises_the_quote():
    """The whole point. A dense chapter is dearer per box than the one the
    table was fitted to, and after a run or two the price says so."""
    before = coins.quote_page("translate", 9, "gemini-3.6-flash")
    for _ in range(3):
        _ran(ratio_in=1.6)
    din, dout = coins.drift("translate", "gemini-3.6-flash")
    assert din == pytest.approx(1.6, abs=0.01)
    assert dout == 1.0, "the input running over says nothing about the output"
    assert coins.quote_page("translate", 9, "gemini-3.6-flash") > before


def test_the_two_corrections_are_separate():
    """Input and output are priced differently — five times differently on
    Gemini — and they drift for different reasons. One number for both would
    correct a thinking overrun by charging for context nobody sent."""
    _ran(ratio_out=1.5)
    din, dout = coins.drift("translate", "gemini-3.6-flash")
    assert din == 1.0
    assert dout == pytest.approx(1.5, abs=0.01)


def test_it_is_per_step_and_per_model():
    """Reading is not translating and Gemini is not Claude. A correction
    pooled across them all learns nothing about any of them."""
    _ran(ratio_in=1.8)
    assert coins.drift("translate", "gemini-3.6-flash")[0] > 1.5
    assert coins.drift("proofread", "gemini-3.6-flash") == (1.0, 1.0)
    assert coins.drift("translate", "claude-sonnet-5") == (1.0, 1.0)


def test_cached_tokens_are_counted_on_both_sides_of_the_ratio():
    """They are input the provider charged less for, not input that did not
    happen. Counted as real input but left out of the prediction, every Claude
    run reads as having used about two and a half times what was expected — for
    ever, and pinned to the clamp."""
    for _ in range(3):
        _ran(model="claude-sonnet-5", backend="anthropic")
    assert coins.drift("translate", "claude-sonnet-5") == (1.0, 1.0)
    # ...and the cache really is the bulk of that run's input, so this test
    # would fail loudly if the two sides ever came apart.
    tin, cached, _out = coins.predicted("translate", 213, 23, 0,
                                        "claude-sonnet-5", "anthropic")
    assert cached > tin


# ------------------------------------------------------------- and not too fast

def test_one_wild_run_cannot_run_away_with_the_price():
    """A provider having a bad day, a chapter of nothing but sound effects.
    The clamp is the difference between an estimate that learns and an
    estimate that can be taught anything."""
    _ran(ratio_in=40.0, ratio_out=0.001)
    din, dout = coins.drift("translate", "gemini-3.6-flash")
    assert din == coins.DRIFT_CLAMP[1]
    assert dout == coins.DRIFT_CLAMP[0]


def test_a_run_too_small_to_mean_anything_does_not_vote():
    """A one-page run's ratio says more about the page image than about the
    series: the fixed cost of a page swamps the boxes. Still metered, just no
    vote."""
    _ran(boxes=coins.DRIFT_MIN_BOXES - 1, pages=1, ratio_in=1.9)
    assert coins.drift("translate", "gemini-3.6-flash") == (1.0, 1.0)


def test_a_big_run_outweighs_a_small_one():
    """Summed across runs, not averaged over them — the forty-page run is
    forty times as much evidence, and an average of ratios pretends the two
    are worth the same."""
    _ran(boxes=400, pages=40, ratio_in=1.5)
    _ran(boxes=25, pages=3, ratio_in=1.0)
    din, _ = coins.drift("translate", "gemini-3.6-flash")
    assert din > 1.4, din


def test_a_series_you_have_stopped_working_on_stops_voting():
    """Only the last few runs. Otherwise the chapter you finished in March is
    still pricing the one you are on now."""
    _ran(ratio_in=2.0)
    for _ in range(coins.DRIFT_RUNS):
        _ran(ratio_in=1.0)
    assert coins.drift("translate", "gemini-3.6-flash")[0] == 1.0


# ------------------------------------------------------------------- held still

def test_the_correction_is_held_still_for_the_length_of_a_run():
    """A run ENDS by writing a meter line. Without this the refund would be
    priced against evidence the charge never saw, and the two would not add
    back up."""
    before = coins.drift("translate", "gemini-3.6-flash")
    with coins.steady():
        assert coins.drift("translate", "gemini-3.6-flash") == before
        for _ in range(3):
            _ran(ratio_in=1.9)
        assert coins.drift("translate", "gemini-3.6-flash") == before
    # ...and outside the run, the new evidence counts.
    assert coins.drift("translate", "gemini-3.6-flash") != before


def test_a_charge_and_its_refund_are_priced_the_same_way(tmp_path):
    """The property the freeze exists for, asked of the editor rather than of
    the freeze: what was taken and what was given back have to agree."""
    from mangatl import editor
    from tests.test_what_it_costs_in_coins import _project
    for _ in range(3):
        _ran(model="claude-sonnet-5", backend="anthropic", ratio_in=1.7)
    p = _project(tmp_path, [9] * 10)
    price = editor.quote_run(p, "translate", list(range(10)))
    start = coins.balance()

    def fn(i):
        coins.record(1200, 300, cached=2158)
        if i == 3:
            p.job["cancel"] = True

    editor._run_one(p, {"label": "Translating", "indices": list(range(10)),
                        "fn": fn, "step": "translate"})
    back = coins.quote("translate", [9] * 6, "claude-sonnet-5", "anthropic", 0)
    assert coins.balance() == start - price + back
    assert p.job["spent"] == price - back


# ------------------------------------------------- what the meter has to write

def test_a_run_writes_down_the_size_of_what_it_did(tmp_path):
    """"It used 44,870 tokens" cannot be compared with what was predicted
    unless the size of the thing that used them is beside it."""
    from mangatl import editor
    from tests.test_what_it_costs_in_coins import _project
    p = _project(tmp_path, [9] * 6)
    editor._run_one(p, {"label": "Translating", "indices": list(range(6)),
                        "fn": lambda i: coins.record(1200, 300, cached=2158),
                        "step": "translate"})
    line = next(e for e in coins.ledger() if e.get("kind") == "meter")
    assert line["step"] == "translate"
    assert line["backend"] == "anthropic"
    assert (line["boxes"], line["pages"], line["ctx"]) == (54, 6, 0)


def test_the_size_written_down_is_the_pages_that_actually_ran(tmp_path):
    """A cancelled run metered four pages. Charging the evidence with ten
    would teach the estimate that the series is cheap."""
    from mangatl import editor
    from tests.test_what_it_costs_in_coins import _project
    p = _project(tmp_path, [9] * 10)

    def fn(i):
        coins.record(1200, 300, cached=2158)
        if i == 3:
            p.job["cancel"] = True

    editor._run_one(p, {"label": "Translating", "indices": list(range(10)),
                        "fn": fn, "step": "translate"})
    line = next(e for e in coins.ledger() if e.get("kind") == "meter")
    assert (line["boxes"], line["pages"]) == (36, 4)


def test_the_accuracy_report_runs(capsys):
    """`python -m mangatl.coins accuracy`. A correction sitting on a clamp is
    the thing to look for in it."""
    assert coins._main(["accuracy"]) == 0
    assert "No runs metered" in capsys.readouterr().out
    for _ in range(2):
        _ran(ratio_in=1.3)
    assert coins._main(["accuracy"]) == 0
    out = capsys.readouterr().out
    assert "translate" in out and "gemini-3.6-flash" in out
    assert "1.30" in out


def test_the_output_correction_lands_on_the_output():
    """Two corrections, and each has to reach its own side of the bill.

    Input and output are priced differently — five times differently on
    Gemini — so applying the output correction to the input is not a small
    error, it is a different price. Measured against the shape directly rather
    than against "it went up", which one number for both would also satisfy.
    """
    for _ in range(3):
        _ran(ratio_out=1.5)
    sh = coins.SHAPES["translate"]
    r = coins.rate_for("gemini-3.6-flash")
    tin = sh.fixed_in + sh.per_box_in * 9 + sh.sys_in
    tout = sh.per_box_out * 9 + sh.think_out
    want = r.usd(tin=tin, tout=int(round(tout * 1.5)))
    got = coins.usd_page("translate", 9, "gemini-3.6-flash")
    assert got == pytest.approx(want, rel=1e-3), (got, want)
    # ...and the input side was left exactly where it was.
    assert coins.drift("translate", "gemini-3.6-flash")[0] == 1.0


def test_the_input_correction_lands_on_the_input():
    for _ in range(3):
        _ran(ratio_in=1.4)
    sh = coins.SHAPES["translate"]
    r = coins.rate_for("gemini-3.6-flash")
    tin = sh.fixed_in + sh.per_box_in * 9 + sh.sys_in
    tout = sh.per_box_out * 9 + sh.think_out
    want = r.usd(tin=int(round(tin * 1.4)), tout=tout)
    got = coins.usd_page("translate", 9, "gemini-3.6-flash")
    assert got == pytest.approx(want, rel=1e-3), (got, want)
