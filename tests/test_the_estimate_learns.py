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
    assert coins.drift("translate", "gemini-3.6-flash") == (1.0, 1.0, 1.0)
    assert coins.drift("ocr", "claude-sonnet-5") == (1.0, 1.0, 1.0)


def test_a_run_that_came_in_on_the_shape_leaves_it_alone():
    _ran()
    assert coins.drift("translate", "gemini-3.6-flash") == (1.0, 1.0, 1.0)


# ------------------------------------------------------------- and from runs

def test_a_series_that_costs_more_than_the_shape_says_raises_the_quote():
    """The whole point. A dense chapter is dearer per box than the one the
    table was fitted to, and after a run or two the price says so."""
    before = coins.quote_page("translate", 9, "gemini-3.6-flash")
    for _ in range(3):
        _ran(ratio_in=1.6)
    din, dout, _dthk = coins.drift("translate", "gemini-3.6-flash")
    assert din == pytest.approx(1.6, abs=0.01)
    assert dout == 1.0, "the input running over says nothing about the output"
    assert coins.quote_page("translate", 9, "gemini-3.6-flash") > before


def test_the_two_corrections_are_separate():
    """Input and output are priced differently - five times differently on
    Gemini - and they drift for different reasons. One number for both would
    correct a thinking overrun by charging for context nobody sent."""
    _ran(ratio_out=1.5)
    din, dout, _dthk = coins.drift("translate", "gemini-3.6-flash")
    assert din == 1.0
    assert dout == pytest.approx(1.5, abs=0.01)


def test_it_is_per_step_and_per_model():
    """Reading is not translating and Gemini is not Claude. A correction
    pooled across them all learns nothing about any of them."""
    _ran(ratio_in=1.8)
    assert coins.drift("translate", "gemini-3.6-flash")[0] > 1.5
    assert coins.drift("proofread", "gemini-3.6-flash") == (1.0, 1.0, 1.0)
    assert coins.drift("translate", "claude-sonnet-5") == (1.0, 1.0, 1.0)


def test_cached_tokens_are_counted_on_both_sides_of_the_ratio():
    """They are input the provider charged less for, not input that did not
    happen. Counted as real input but left out of the prediction, every Claude
    run reads as having used about two and a half times what was expected - for
    ever, and pinned to the clamp."""
    for _ in range(3):
        _ran(model="claude-sonnet-5", backend="anthropic")
    assert coins.drift("translate", "claude-sonnet-5") == (1.0, 1.0, 1.0)
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
    din, dout, _dthk = coins.drift("translate", "gemini-3.6-flash")
    assert din == coins.DRIFT_CLAMP[1]
    assert dout == coins.DRIFT_CLAMP[0]


def test_a_run_too_small_to_mean_anything_does_not_vote():
    """A one-page run's ratio says more about the page image than about the
    series: the fixed cost of a page swamps the boxes. Still metered, just no
    vote."""
    _ran(boxes=coins.DRIFT_MIN_BOXES - 1, pages=1, ratio_in=1.9)
    assert coins.drift("translate", "gemini-3.6-flash") == (1.0, 1.0, 1.0)


def test_a_big_run_outweighs_a_small_one():
    """Summed across runs, not averaged over them - the forty-page run is
    forty times as much evidence, and an average of ratios pretends the two
    are worth the same."""
    _ran(boxes=400, pages=40, ratio_in=1.5)
    _ran(boxes=25, pages=3, ratio_in=1.0)
    din = coins.drift("translate", "gemini-3.6-flash")[0]
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
    from test_what_it_costs_in_coins import _project
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
    # Since the settle, what is kept is the METER of the four pages that ran
    # - no re-quote of the tail happens at all, so the freeze property this
    # test was written for ("what was taken and what was given back have to
    # agree") is now arithmetic on three ledger lines rather than two quotes
    # agreeing: hold out, settle back, meter charged.
    reserve = coins.hold(price)
    line = next(e for e in coins.ledger() if e["kind"] == "meter")
    final = min(int(line["coins"]), reserve)
    back_line = next(e for e in coins.ledger() if e["kind"] == "credit")
    assert int(back_line["coins"]) == reserve - final
    assert coins.balance() == start - final
    assert p.job["spent"] == final
    assert line["charged"] == final


# ------------------------------------------------- what the meter has to write

def test_a_run_writes_down_the_size_of_what_it_did(tmp_path):
    """"It used 44,870 tokens" cannot be compared with what was predicted
    unless the size of the thing that used them is beside it."""
    from mangatl import editor
    from test_what_it_costs_in_coins import _project
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
    from test_what_it_costs_in_coins import _project
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



def _shape_tokens(boxes, model="gemini-3.6-flash"):
    """(input, output) the way `usd_page` works them out, uncorrected.

    `sys_in` is COUNTED off the real prompt now (`coins.sys_tokens`) and the
    reply has a source-character term as well as a per-box one, so a test that
    still reaches into `SHAPES` for either is checking the fallback rather
    than the price.
    """
    sh = coins.SHAPES["translate"]
    tin = sh.fixed_in + sh.per_box_in * boxes + coins.sys_tokens("translate")
    tout = int(round(sh.fixed_out + sh.per_box_out * boxes
                     + sh.per_src_char_out * coins.SRC_CHARS_PER_BOX * boxes))
    # Thinking is per BOX now, not a flat number a page - two model versions
    # agreed on 15-19 tokens a box and on nothing at all per page. See
    # `coins.THINK_PER_BOX`.
    tout += int(round(coins.think_tokens(sh, model, "", boxes)))
    return tin, tout


def test_the_output_correction_lands_on_the_output():
    """Two corrections, and each has to reach its own side of the bill.

    Input and output are priced differently - five times differently on
    Gemini - so applying the output correction to the input is not a small
    error, it is a different price. Measured against the shape directly rather
    than against "it went up", which one number for both would also satisfy.
    """
    for _ in range(3):
        _ran(ratio_out=1.5)
    r = coins.rate_for("gemini-3.6-flash")
    tin, tout = _shape_tokens(9)
    want = r.usd(tin=tin, tout=int(round(tout * 1.5)))
    got = coins.usd_page("translate", 9, "gemini-3.6-flash")
    assert got == pytest.approx(want, rel=1e-3), (got, want)
    # ...and the input side was left exactly where it was.
    assert coins.drift("translate", "gemini-3.6-flash")[0] == 1.0


def test_the_input_correction_lands_on_the_input():
    for _ in range(3):
        _ran(ratio_in=1.4)
    r = coins.rate_for("gemini-3.6-flash")
    tin, tout = _shape_tokens(9)
    want = r.usd(tin=int(round(tin * 1.4)), tout=tout)
    got = coins.usd_page("translate", 9, "gemini-3.6-flash")
    assert got == pytest.approx(want, rel=1e-3), (got, want)


# ------------------------------------- the reply and the thinking, apart

def _ran_split(step="translate", model="gemini-3.6-flash", backend="gemini",
               boxes=213, pages=23, vis_ratio=1.0, think_ratio=1.0):
    """A metered run whose line SAW the reasoning apart from the reply."""
    tin, cached, tout = coins.predicted(step, boxes, pages, 0, model, backend)
    thk = coins.predicted_think(step, boxes, model, backend)
    vis = tout - thk
    coins.note("%s cost" % step, "pages 1-%d" % pages, model,
               step=step, backend=backend, boxes=boxes, pages=pages, ctx=0,
               tin=int(tin), cached=int(cached),
               tout=int(vis * vis_ratio + thk * think_ratio),
               think=int(thk * think_ratio),
               calls=pages, coins=1, charged=1)


def test_a_thinking_overrun_corrects_the_thinking_and_not_the_reply():
    """Task #120. Half of a Gemini bill is reasoning, and it was the largest
    unverified number in the file - one output multiplier let a thinking
    overrun masquerade as a reply overrun and charge for words nobody got."""
    for _ in range(3):
        _ran_split(think_ratio=2.0)
    din, dvis, dthk = coins.drift("translate", "gemini-3.6-flash")
    assert din == 1.0
    assert dvis == pytest.approx(1.0, abs=0.01), \
        "the reply took the blame for the thinking"
    assert dthk == pytest.approx(2.0, abs=0.05)


def test_the_visible_reply_is_held_to_the_tight_band_and_rings_the_bell():
    """The refit reply predicts real pages at about 2%; a visible drift past
    a quarter means the arithmetic is broken, and a broken thing says so in
    the ledger instead of being silently corrected into the price."""
    coins._ALARMED.clear()
    for _ in range(3):
        _ran_split(vis_ratio=2.0)
    _din, dvis, _dthk = coins.drift("translate", "gemini-3.6-flash")
    lo, hi = coins.DRIFT_VIS_CLAMP
    assert dvis == hi, "the tight band did not hold"
    bells = [e for e in coins.ledger() if e.get("kind") == "alarm"]
    assert len(bells) == 1, "the bell rang %d times" % len(bells)
    assert "arithmetic" in bells[0]["what"]
    # ...and it rings once per process, not once per quote
    coins.drift("translate", "gemini-3.6-flash")
    with coins.steady():
        coins.quote_page("translate", 9, "gemini-3.6-flash")
    assert len([e for e in coins.ledger()
                if e.get("kind") == "alarm"]) == 1


def test_old_lines_without_the_split_still_correct_the_whole_output():
    """A ledger written before the split - or a provider that does not
    report reasoning - keeps exactly the old behaviour: one combined output
    ratio, wide clamp, for both halves."""
    _ran(ratio_out=1.5)
    din, dvis, dthk = coins.drift("translate", "gemini-3.6-flash")
    assert din == 1.0
    assert dvis == dthk == pytest.approx(1.5, abs=0.01)


def test_the_thinking_correction_lands_on_the_thinking_alone():
    """The mutant that survived the first pass: `usd_page` applying one
    output multiplier to visible-plus-thinking prices exactly the same as
    the split whenever the two coefficients agree - which is every test
    above. Here they disagree: a pure THINKING overrun must raise the
    price (the thinking half doubled), and by less than doubling the whole
    output would."""
    fresh = coins.quote_page("translate", 40, "gemini-3.6-flash", "gemini",
                             0, 900.0)
    for _ in range(3):
        _ran_split(boxes=213, pages=23, think_ratio=2.0)
    with coins.steady():
        corrected = coins.quote_page("translate", 40, "gemini-3.6-flash",
                                     "gemini", 0, 900.0)
    assert corrected > fresh, \
        "a thinking overrun never reached the price at all"
    # ...and the rise is the THINKING half's, not the whole output's: the
    # visible reply held at 1.0, so doubling everything would be more.
    sh = coins.SHAPES["translate"]
    r = coins.rate_for("gemini-3.6-flash", "gemini")
    tvis = sh.fixed_out + sh.per_box_out * 40 + sh.per_src_char_out * 900.0
    both_doubled = fresh + coins.coins_for_usd(
        r.usd(tout=tvis))                      # the extra a 2x on vis adds
    assert corrected < both_doubled, \
        "the thinking correction landed on the visible reply too"


# ------------------------------------ who thinks is a question for the meter
#
# Task #125, off lee's own ledger. Three readers over one 58-page manhwa:
#
#     claude-opus-5       19,576 out for 144 boxes, `think` reported nowhere
#     gemini-3.8-flash     3,110 out for 144 boxes, `think` reported as 0
#     qwen/qwen3.7-plus   34,598 out for 146 boxes, `think` reported 30,755
#
# Same boxes, same JSON. Gemini's is the visible reply; the other sixteen
# thousand of Opus's are reasoning, billed as output. The quote had Opus at
# nothing (`THINKS` said Claude never thinks unasked - true until the 5 line),
# Gemini at something (it thinks on a translate, not on a read), and qwen at
# nothing (it was not on the list). Two of the three overshot their holds.
#
# A name list cannot be right per step. The meter can: it is asked first.


def test_a_model_the_meter_saw_thinking_thinks_whatever_the_list_says():
    """qwen3.7-plus was nowhere on `THINKS` when it reported thirty thousand
    reasoning tokens. Any model can be that model next month."""
    model = "somebody/brand-new-9b"
    assert coins.thinks(model, "openrouter", "ocr") is False, "not on the list"
    coins.note("ocr cost", "58 pages", model, step="ocr", backend="openrouter",
               boxes=146, pages=58, tin=257_192, tout=34_598, think=30_755,
               calls=147, coins=26, charged=24)
    assert coins.thinks(model, "openrouter", "ocr") is True


def test_a_model_the_meter_saw_not_thinking_is_not_charged_for_it():
    """Gemini 3.8 Flash reported 0 reasoning across 145 read calls. The list
    says gemini thinks - and it does, on a translate. Per step, then.

    Gemini-on-a-read is now also the first-run default (`THINKS_NOT_ON`), so
    the measured case is played on the translate, where the list says it
    thinks and a run that reports otherwise has to be believed."""
    assert coins.thinks("gemini-3.8-flash", "gemini", "translate") is True, \
        "the list"
    coins.note("translate cost", "58 pages", "gemini-3.8-flash",
               step="translate", backend="gemini", boxes=144, pages=58,
               tin=329_736, tout=3_110, think=0, calls=58, coins=104,
               charged=104)
    assert coins.thinks("gemini-3.8-flash", "gemini", "translate") is False
    # ...on THIS step. The proofread is a different question with no
    # measurement yet, and falls back to the list.
    assert coins.thinks("gemini-3.8-flash", "gemini", "proofread") is True
    # ...and the translate is now quoted without the thinking
    assert coins.think_tokens(coins.SHAPES["translate"], "gemini-3.8-flash",
                              "gemini", 144, "translate") == 0


def test_a_silent_zero_from_a_provider_that_does_not_say_is_not_evidence():
    """The line lee's ledger already holds for Opus 5: `think: 0`, written
    before `usage_extras` learned to leave the key off. Anthropic reports
    nothing, so that 0 is silence. Read as a measurement it says Opus does
    not think, which is the opposite of what the same line's 19,576 output
    tokens say."""
    coins.note("ocr cost", "58 pages", "claude-opus-5", step="ocr",
               backend="anthropic", boxes=144, pages=58, tin=164_114,
               tout=19_576, cached=94_335, think=0, calls=58, coins=274,
               charged=225)
    assert coins._meter_thinks("ocr", "claude-opus-5") is None
    # ...so the answer falls to the list, on a step where nothing switches
    # it off (the read is switched off by decision - `READ_THINKING_OFF`).
    assert coins.thinks("claude-opus-5", "anthropic", "proofread") is True


def test_a_silent_zero_votes_on_the_combined_ratio_not_the_split():
    """...and the same line must not vote as though it had seen the
    reasoning apart. Split, its 19,576 lands on the visible reply (clamped
    to 1.25, bell rung) and its 0 votes the thinking down to the floor - the
    quote comes out a third short twice over. Combined, it is one ratio on
    one number, which is all Anthropic gave."""
    coins._ALARMED.clear()
    coins.note("ocr cost", "58 pages", "claude-opus-5", step="ocr",
               backend="anthropic", boxes=144, pages=58, tin=164_114,
               tout=19_576, cached=94_335, think=0, calls=58, coins=274,
               charged=225, src=1757, detail="boxes")
    din, dvis, dthk = coins.drift("ocr", "claude-opus-5", "anthropic")
    assert dvis == dthk, "the line was split; Anthropic never split it"
    assert dthk > coins.DRIFT_CLAMP[0], "the thinking was voted to the floor"
    assert not [e for e in coins.ledger() if e.get("kind") == "alarm"], \
        "the bell rang for a number that was never a visible reply"


def test_a_reported_zero_against_a_predicted_thinking_corrects_it_down(monkeypatch):
    """Where a provider DOES say, zero is a measurement. Two things now read
    it. `thinks` asks the meter and stops predicting the thinking at all -
    the quote drops to the no-reasoning price. And underneath that, for the
    ratio itself, `dthk` used to be left at 1.0 when the real figure was 0 -
    `if pthk and rthk` - which kept a thinking model's whole allowance on a
    step it never thinks on. Both are checked: the second with the first
    held off, or it can never be reached."""
    fresh = coins.quote_page("translate", 40, "gemini-3.6-flash", "gemini",
                             0, 900.0)
    for _ in range(3):
        _ran_split(step="translate", model="gemini-3.6-flash",
                   backend="gemini", think_ratio=0.0)
    # 1. the meter says it did not think here, so it is not quoted for it
    assert coins.thinks("gemini-3.6-flash", "gemini", "translate") is False
    with coins.steady():
        after = coins.quote_page("translate", 40, "gemini-3.6-flash",
                                 "gemini", 0, 900.0)
    assert after < fresh, (fresh, after)
    # 2. the ratio, with the meter's answer held off so the list still says
    # it thinks and there IS a predicted thinking for the 0 to vote against
    monkeypatch.setattr(coins, "_meter_thinks", lambda *_a: None)
    _din, dvis, dthk = coins.drift("translate", "gemini-3.6-flash", "gemini")
    assert dvis == pytest.approx(1.0, abs=0.01)
    assert dthk == coins.DRIFT_CLAMP[0], dthk


def test_the_answer_is_held_still_for_the_length_of_a_run():
    """Same reason `drift` is: a run ends by writing a meter line, and if that
    line flips the answer, a charge and its refund are priced on two
    different truths."""
    model = "somebody/brand-new-9b"
    with coins.steady():
        before = coins.thinks(model, "openrouter", "ocr")
        coins.note("ocr cost", "p", model, step="ocr", backend="openrouter",
                   boxes=146, pages=58, tin=1, tout=1, think=30_755,
                   calls=1, coins=1, charged=1)
        during = coins.thinks(model, "openrouter", "ocr")
    after = coins.thinks(model, "openrouter", "ocr")
    assert before is False and during is False and after is True


def test_lees_three_reads_are_all_covered_by_a_fresh_quote(monkeypatch):
    """The receipt. Boxes and source characters per page of the chapter,
    what each read really cost by the meter, and the rule: the hold a fresh
    install takes at the button must cover the bill. Before this, two of the
    three did not."""
    boxes = [2, 2, 1, 2, 1, 1, 3, 2, 2, 3, 2, 2, 1, 2, 5, 4, 3, 1, 6, 3, 1, 3,
             3, 4, 2, 1, 4, 3, 2, 3, 2, 2, 0, 4, 4, 2, 5, 1, 2, 2, 1, 3, 4, 2,
             6, 4, 2, 2, 1, 3, 3, 3, 2, 3, 4, 0, 1, 1]
    srcs = [33, 17, 3, 4, 0, 2, 40, 28, 29, 23, 18, 24, 21, 27, 76, 33, 14,
            13, 70, 29, 18, 35, 25, 69, 62, 12, 80, 62, 24, 84, 60, 43, 0, 11,
            4, 15, 43, 10, 25, 37, 25, 37, 59, 48, 62, 73, 27, 12, 5, 4, 24,
            37, 20, 32, 66, 0, 2, 2]
    key = ("manhwa", "en", "ko", True)
    really = {("claude-opus-5", "anthropic"): 274,
              ("gemini-3.8-flash", "gemini"): 104,
              ("qwen/qwen3.7-plus", "openrouter"): 26}
    # Opus's 274 was a THINKING read, and reads on Opus are sent with
    # thinking off since lee's decision (`READ_THINKING_OFF`). The receipt is
    # checked in the regime it was written in: with the knob held on, the
    # quote must cover what the thinking read really cost.
    monkeypatch.setattr(coins, "READ_THINKING_OFF", ())
    for (model, backend), cost in really.items():
        q = coins.quote("ocr", boxes, model, backend, 0, srcs, key, "boxes")
        assert coins.hold(q) >= cost, (model, q, coins.hold(q), cost)
        # ...and not by absurdly much either: the point of a quote is to be
        # near, and a hold at twice the bill is a purse nobody can use.
        assert coins.hold(q) <= 2 * cost, (model, q, coins.hold(q), cost)


def test_a_listed_thinker_is_not_quoted_for_thinking_on_a_step_it_never_thinks_on():
    """The first-run default, per step. Gemini reasons on a translate and
    not on a read - 0 reported across 145 read calls - and a fresh install
    should not quote every Gemini read a reasoning allowance the meter will
    only take back after the first chapter."""
    assert coins.thinks("gemini-3.8-flash", "gemini", "ocr") is False
    assert coins.thinks("gemini-3.8-flash", "gemini", "translate") is True
    # ...and the meter still outranks it, either way round
    coins.note("ocr cost", "p", "gemini-3.8-flash", step="ocr",
               backend="gemini", boxes=144, pages=58, tin=1, tout=1,
               think=5_000, calls=1, coins=1, charged=1)
    assert coins.thinks("gemini-3.8-flash", "gemini", "ocr") is True
