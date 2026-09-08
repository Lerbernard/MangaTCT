# -*- coding: utf-8 -*-
"""A hold, then a settle - the revamp of what a run is charged.

lee: *"i want to reveamp teh builing system wit teh coins i want to get a
very good extimate"*. The recommendation that came out of the pricing bench
("Pricing the translate button", 2026-08-31), now built:

* The QUOTE is what the button shows. What leaves the purse at the press is
  the quote times a measured headroom - `coins.hold`, 1.25x, which covered
  100% of the bench's real pages with room to spare - so a run can never
  outrun its own purse (task #116).
* Every call is metered, and the run SETTLES at the end: the metered cost
  is kept, the rest of the hold comes back as one credit on the same run
  id (task #115). The settle never takes a second helping - a meter past
  the hold is written down (`over`) and absorbed.
* The reply is bounded: `coins.reply_cap` sends max_tokens at about twice
  the predicted reply, floor 1500, ceiling the old flat 8000 - so the
  unbounded half of the bill became a number we chose (task #118). A retry
  after a truncated reply gets the full ceiling.
* Where the provider reports its own price (OpenRouter's `usage.cost`),
  the bill takes THAT over our copy of their rate table, and reasoning
  tokens are read off the reply where they are reported (task #119's
  settle half).

`test_what_it_costs_in_coins.py` covers the whole flow through
`editor._run_one`; this file pins the primitives.
"""
import os

import pytest

from where import PKG                                       # noqa: E402
from mangatl import coins


@pytest.fixture(autouse=True)
def _own_purse(tmp_path, monkeypatch):
    from mangatl import userdata
    monkeypatch.setattr(userdata, "user_dir", lambda: str(tmp_path))
    yield


# ------------------------------------------------------------------ the hold

def test_the_hold_is_the_quote_plus_the_measured_headroom():
    assert coins.HOLD == 1.25
    assert coins.hold(0) == 0
    assert coins.hold(-3) == 0
    assert coins.hold(4) == 5          # 5.0 exactly
    assert coins.hold(10) == 13        # 12.5, whole coins round UP
    assert coins.hold(100) == 125


def test_the_hold_never_rounds_below_the_quote():
    for price in range(1, 50):
        assert coins.hold(price) >= price


# ------------------------------------------------- what the reply may cost

def test_the_reply_cap_is_twice_the_prediction_inside_its_rails():
    sh = coins.SHAPES["translate"]
    boxes, src = 9, 120.0
    want = 2 * (sh.fixed_out + sh.per_box_out * boxes
                + sh.per_src_char_out * src)
    got = coins.reply_cap("translate", boxes, src, "claude-sonnet-5")
    assert got == int(min(8000, max(1500, want)))
    # rails: an empty page gets the old flat ceiling, a tiny one the floor
    assert coins.reply_cap("translate", 0, 0) == 8000
    assert coins.reply_cap("translate", 1, 4.0) >= 1500
    assert coins.reply_cap("translate", 10_000, 1e6) == 8000


def test_a_model_that_thinks_gets_its_thinking_on_top():
    """max_tokens counts a model's reasoning against the reply on every
    provider that reports it, so capping at twice the visible reply alone
    would truncate a thinking model's real answer."""
    # Haiku 4.5, not Sonnet 5: the 5 line thinks unasked (task #125) and
    # gets its allowance too, which is the next assertion.
    plain = coins.reply_cap("translate", 40, 900.0, "claude-haiku-4-5")
    think = coins.reply_cap("translate", 40, 900.0, "gemini-3.7-flash")
    assert think > plain
    assert coins.reply_cap("translate", 40, 900.0, "claude-sonnet-5") > plain


def test_the_call_sites_pass_the_cap_and_retries_do_not():
    src = open(os.path.join(str(PKG), "translate.py"), encoding="utf8").read()
    body = src.split("def _ask(")[1].split("\ndef ")[0]
    assert "max_tokens" in body.split('"""')[0], \
        "_ask no longer takes the cap"
    # both page callers compute a cap on the first attempt only
    assert src.count('reply_cap("translate"') == 1
    assert src.count('reply_cap("proofread"') == 1
    assert src.count("if attempt == 0 and not last_err:") == 2, \
        "a retry after a truncated reply must get the full ceiling"


# ------------------------------------- what the provider says it charged

def _resp(usage):
    return {"choices": [], "usage": usage}


def test_reasoning_and_cost_are_read_off_an_openrouter_reply():
    think, cost = coins.usage_extras(_resp({
        "prompt_tokens": 900, "completion_tokens": 250,
        "completion_tokens_details": {"reasoning_tokens": 180},
        "cost": 0.0123}))
    assert (think, cost) == (180, 0.0123)


def test_a_reply_that_says_nothing_about_reasoning_says_none_not_zero():
    """Task #125. Silence and zero are different answers. Anthropic bills
    reasoning as output and reports it nowhere; handing that back as 0 put
    `think: 0` on every Opus line, which `drift` read as "the reasoning was
    seen apart from the reply, and it was nothing" - and filed sixteen
    thousand thinking tokens under the visible reply, where the tight band
    refused them and rang the alarm."""
    assert coins.usage_extras(_resp({"prompt_tokens": 1})) == (None, 0.0)
    assert coins.usage_extras({"junk": True}) == (None, 0.0)
    assert coins.usage_extras(None) == (None, 0.0)
    # ...and garbage cannot raise - a metering bug must not fail a page
    assert coins.usage_extras(_resp({"cost": "not-a-number"})) == (None, 0.0)
    # A provider that SAID zero is a zero - that is a measurement.
    assert coins.usage_extras(_resp({
        "completion_tokens_details": {"reasoning_tokens": 0}})) == (0, 0.0)
    assert coins.usage_extras(_resp({"thoughts_token_count": 0})) == (0, 0.0)


def test_the_bill_knows_whether_anybody_said():
    """The meter line carries `think` only where a reply reported it, so a
    provider that gives one number votes on one ratio."""
    with coins.charging("ocr", "p", "claude-opus-5") as quiet:
        coins.record(100, 500, model="claude-opus-5")
        coins.record(100, 500, model="claude-opus-5", think=None)
    assert quiet.think_seen is False and quiet.think == 0
    with coins.charging("ocr", "p", "qwen/qwen3.7-plus") as loud:
        coins.record(100, 500, model="qwen/qwen3.7-plus", think=0)
    assert loud.think_seen is True and loud.think == 0
    with coins.charging("ocr", "p", "qwen/qwen3.7-plus") as louder:
        coins.record(100, 500, model="qwen/qwen3.7-plus", think=420)
    assert louder.think_seen is True and louder.think == 420


def test_the_receipt_says_who_priced_it():
    """Task #119. OpenRouter's `usage.cost` already wins over the table in
    `Bill.add`; what was missing was any way to tell from the ledger that it
    had. `priced_direct` counts the calls the provider priced."""
    with coins.charging("ocr", "p", "qwen/qwen3.7-plus") as b:
        coins.record(100, 50, model="qwen/qwen3.7-plus", usd_direct=0.002)
        coins.record(100, 50, model="qwen/qwen3.7-plus")
        coins.record(100, 50, model="qwen/qwen3.7-plus", usd_direct=0.002)
    assert b.calls == 3 and b.priced_direct == 2
    src = open(os.path.join(str(PKG), "editor.py"), encoding="utf8").read()
    assert "priced_direct=bill.priced_direct" in src
    assert '**({"think": bill.think} if bill.think_seen' in src


def test_the_providers_own_price_beats_the_rate_table():
    """OpenRouter puts what it charged on the reply. Their price for their
    call beats our copy of their price table - the table can be a week
    stale, the reply cannot."""
    with coins.charging("translate", "p1", "some/openrouter-model",
                        "openrouter") as bill:
        coins.meter(_resp({"prompt_tokens": 1000, "completion_tokens": 500,
                           "cost": 0.5}))
    assert bill.usd == pytest.approx(0.5)
    # the markup still applies on the way to coins - cost price is theirs,
    # the price is ours
    assert bill.coins == coins.coins_for_usd(0.5)


def test_without_a_reported_cost_the_table_still_answers():
    with coins.charging("translate", "p1", "claude-sonnet-5",
                        "anthropic") as bill:
        coins.meter(_resp({"prompt_tokens": 1000, "completion_tokens": 500}))
    r = coins.rate_for("claude-sonnet-5")
    assert bill.usd == pytest.approx(r.usd(1000, 500))


def test_reasoning_tokens_ride_the_bill():
    with coins.charging("translate", "p1", "some/model", "openrouter") as bill:
        coins.meter(_resp({"prompt_tokens": 10, "completion_tokens": 400,
                           "completion_tokens_details":
                               {"reasoning_tokens": 300}}))
        coins.meter(_resp({"prompt_tokens": 10, "completion_tokens": 100}))
    assert bill.think == 300
    assert bill.calls == 2


def test_the_gate_asks_about_the_hold_not_the_bare_quote():
    """A run whose own hold bounces must not start (task #116)."""
    src = open(os.path.join(str(PKG), "editor.py"), encoding="utf8").read()
    body = src.split("def afford_run(")[1].split("\ndef ")[0]
    assert "coins.can_afford(coins.hold(price))" in body, \
        "the gate lets in a run whose hold cannot be paid"


# --------------------------------------- what an OpenRouter request carries

def test_an_openrouter_request_asks_for_its_own_receipt_and_sets_a_ceiling():
    from mangatl import translate as T
    got = T._openrouter_body_extras("https://openrouter.ai/api/v1",
                                    "anthropic/claude-sonnet-5")
    assert got.get("usage") == {"include": True}, \
        "without usage accounting the reply carries no cost to settle on"
    cap = (got.get("provider") or {}).get("max_price") or {}
    r = coins.rate_for("anthropic/claude-sonnet-5", "openrouter")
    assert cap.get("prompt") == pytest.approx(r.inp * 1.5, abs=0.001)
    assert cap.get("completion") == pytest.approx(r.out * 1.5, abs=0.001)


def test_no_ceiling_is_guessed_for_a_model_the_table_does_not_price():
    from mangatl import translate as T
    got = T._openrouter_body_extras("https://openrouter.ai/api/v1",
                                    "somebody/nobody-priced-this-9b")
    assert got.get("usage") == {"include": True}
    assert "provider" not in got, \
        "a guessed ceiling can route every request away"


def test_a_local_server_gets_no_openrouter_fields():
    from mangatl import translate as T
    assert T._openrouter_body_extras("http://127.0.0.1:11434/v1",
                                     "qwen3:8b") == {}


def test_a_refused_ceiling_is_dropped_and_the_page_survives():
    """A stale table or a price rise must cost accuracy, never the page:
    the client retries without the extras, once, and remembers."""
    src = open(os.path.join(str(PKG), "translate.py"),
               encoding="utf8").read()
    assert src.count("_no_or_extras = True") == 2, \
        "one of the two request paths cannot drop a refused ceiling"
    assert src.count('"max_price" in low or "provider" in low') == 2


# ----------------------------- one page, priced off its real strings

def test_a_single_page_is_priced_off_the_strings_it_will_send(tmp_path):
    """Task #117. A one-page run has its exact payload in hand, so the
    input side is counted, not predicted - and a page whose words double
    gets dearer without any constant having to know it."""
    from mangatl import editor
    from test_what_it_costs_in_coins import _project
    p = _project(tmp_path, [9, 9])
    price1, _m, _b = editor.run_price(p, "translate", [0])
    assert price1 > 0
    # fatten every box on page 0 and the counted price must move
    for r in p.pages[0].regions:
        r["src_text"] = (r.get("src_text") or "x") * 60
    p._materialized = {}
    price2, _m, _b = editor.run_price(p, "translate", [0])
    assert price2 > price1, \
        "the single-page price never read the page's own words"


def test_the_counted_price_and_the_shape_price_are_the_same_arithmetic():
    """The counted quote must not be a second price table: same rate, same
    reply predictor, same rounding. Fed a user string of exactly the
    tokens the shape would have predicted, the two agree to the coin."""
    sh = coins.SHAPES["translate"]
    boxes, src = 12, 160.0
    model = "claude-sonnet-5"
    sys_txt = "s " * 10
    shaped_in = int(sh.fixed_in + sh.per_box_in * boxes)
    user = "word " * shaped_in            # ~1 token a word plus a margin
    a = coins.quote_counted("translate", sys_txt, user, boxes, src, model)
    tin = coins.tokens(user)
    sys_in = coins.tokens(sys_txt)
    cached = sys_in if coins.cached_tokens(sh, model, "", sys_in) else 0
    r = coins.rate_for(model)
    tvis = (sh.fixed_out + sh.per_box_out * boxes
            + sh.per_src_char_out * src)
    tthk = coins.think_tokens(sh, model, "", boxes)
    want = coins.coins_for_usd(
        r.usd(tin=tin + (0 if cached else sys_in), cached=cached,
              tout=tvis + tthk))
    assert a == want
