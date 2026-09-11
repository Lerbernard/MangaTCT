"""TCT Coins - what the steps cost and what is left to spend.

lee: *"i wan you to impiment a credit syste using coins $1 is 100 coins i want
you to make all the steps that use ai to cost coins aprpretly also bubble teh
coin cost so if something cost $1 make it cost 2 dollar in coins make teh coin
system be dynamic and per text box in a page so if a page has 1 0r 2 tet box it
shoiukd be cheaper than a page that has 5-6 text boxes, the clenning fee shud be
a flat fee per page call teh coin tct coind and use teh logo as the coin face
also add a coin count in the ui at the top"*.

Every claim in that sentence is a test below, and the two that are easiest to
get quietly wrong are the arithmetic ones: a hundred coins to the dollar, and
the doubling. Both are asked against a REAL provider rate rather than against
the constant, so a test cannot pass by restating the code back to itself.
"""
import json
import os
import shutil
import threading

import browserpool
import pytest

from http.server import ThreadingHTTPServer

from mangatl import coins
from where import PKG

# The Claude these arithmetic tests price on. Sonnet 4 and not Sonnet 5,
# since task #125: the 5 line thinks unasked - Anthropic: *"On Claude Opus 5,
# Claude Sonnet 5 ... thinking is already on and needs no configuration"* -
# and a test about the PAYLOAD half of a price wants a model whose output is
# only the reply. Sonnet 4 is off the menu (`RETIRED`) but it is still priced,
# at exactly Sonnet 5's rate, so every number these tests were written
# against stays the number; it marks its cache like the rest of the family;
# and it thinks only when asked, which nothing here does.
PLAIN_CLAUDE = "claude-sonnet-4"


@pytest.fixture(autouse=True)
def purse(tmp_path, monkeypatch):
    """A fresh, empty home for every test - its own wallet, its own ledger."""
    monkeypatch.setenv("MANGATL_HOME", str(tmp_path / "home"))
    return tmp_path


# ------------------------------------------------------ a hundred to the dollar

# The two things `usd_page` works out for itself, written once here so the
# tests below can check the arithmetic without each repeating it - and
# repeating it slightly differently.
#
# `sys_in` is COUNTED off the real prompt now rather than read out of the
# shape (see `coins.sys_tokens`), and the reply has a source-character term as
# well as a per-box one (see `Shape.per_src_char_out`). A test that still
# reaches for `sh.sys_in` is testing the fallback, not the price.


def _sys(step):
    return coins.sys_tokens(step)


def _reply(step, boxes, src=None):
    sh = coins.SHAPES[step]
    if src is None:
        src = coins.SRC_CHARS_PER_BOX * boxes
    # Exact, like `usd_page` - it does not round tokens, and a test that did
    # would land a fraction of a token either side of the price it checks.
    return sh.fixed_out + sh.per_box_out * boxes + sh.per_src_char_out * src


def test_a_dollar_is_a_hundred_coins():
    """lee: *"$1 is 100 coins"*. Doubled, so a dollar of real cost is 200."""
    assert coins.COINS_PER_DOLLAR == 100
    assert coins.coins_for_usd(1.0) == 200
    assert coins.coins_for_usd(0.5) == 100
    assert coins.coins_for_usd(0) == 0


def test_the_price_is_doubled():
    """lee: *"bubble teh coin cost so if something cost $1 make it cost 2
    dollar in coins"*.

    Asked as a RATIO against the undoubled arithmetic rather than against
    `MARKUP`: this is the one number in the app that decides whether the thing
    makes money, and a test that reads the constant it is checking would pass
    just as happily against a markup of one.
    """
    for usd in (0.01, 0.25, 1.0, 7.5):
        plain = usd * coins.COINS_PER_DOLLAR
        assert coins.coins_for_usd(usd) == pytest.approx(plain * 2, abs=1)


def test_a_fraction_of_a_coin_rounds_up_and_never_to_nothing():
    """Down at a hundredth of a cent is not a rounding, it is a free tier for
    anybody who can arrange to land just under."""
    assert coins.coins_for_usd(0.0000001) == 1
    assert coins.coins_for_usd(0.0000000001) == 1
    assert coins.coins_for_usd(-5) == 0


# --------------------------------------------------------- what a model costs

def test_a_model_is_priced_at_what_its_provider_charges():
    """Haiku 4.5 at $1 in / $5 out per million, doubled. Written out in full
    so the sum is legible: this is the whole business model in one line.

    Haiku rather than Sonnet because Sonnet has a promotion running against it
    at the moment, and a worked example ought to be arithmetic rather than
    news.
    """
    r = coins.rate_for("claude-haiku-4-5")
    assert (r.inp, r.out) == (1.0, 5.0)
    # a million in and a million out is $6 of cost, so $12 of coins
    assert coins.coins_for_usd(r.usd(tin=1_000_000, tout=1_000_000)) == 1200


def test_a_dated_build_of_a_model_prices_as_the_model():
    """Longest prefix. A new dated build must not silently fall to the
    unknown-model rate on the day the provider ships it."""
    assert coins.rate_for("claude-sonnet-5-20260514") is \
        coins.rate_for("claude-sonnet-5")
    assert coins.rate_for("gemini-3.5-flash-lite-preview").inp == 0.30
    # ...and the LONGER key wins: flash-lite is not flash.
    assert coins.rate_for("gemini-3.5-flash").inp == 1.50


def test_the_longer_key_wins_however_the_table_is_written(monkeypatch):
    """The table happens to list every colliding pair longest-first today, so
    taking the FIRST match that fits gives the same answers - which means the
    rule is untested by the table as it stands and a reordering would start
    charging flash-lite at flash prices with nothing to say so.

    Asked of a table written the other way round, which is the only way to ask
    it about the rule rather than about today's dictionary.
    """
    monkeypatch.setattr(coins, "RATES", {
        "mini": coins.Rate(9.0, 9.0),               # the SHORT key, first
        "mini-lite": coins.Rate(0.1, 0.1),
    })
    assert coins.rate_for("mini-lite-preview").inp == 0.1
    assert coins.rate_for("mini-plus").inp == 9.0


def test_a_model_nobody_priced_is_charged_as_the_dearest():
    """An unknown model that turns out to be Opus and was charged as free is a
    bill this app ate. An unknown model that was really cheap is a customer who
    can be refunded. Only one of those is recoverable."""
    r = coins.rate_for("some-model-shipped-this-morning")
    assert (r.inp, r.out) == (coins.UNKNOWN.inp, coins.UNKNOWN.out)
    assert r.inp >= max(q.inp for q in coins.RATES.values())


def test_a_model_you_run_yourself_is_free():
    """Their own electricity, their own hardware, nothing bought from anyone."""
    for back in ("ollama", "llamacpp", "lmstudio"):
        assert coins.quote_page("translate", 9, "qwen2.5:14b", back) == 0
    assert coins.quote_page("translate", 9, PLAIN_CLAUDE, "anthropic") > 0


def test_a_cached_prompt_is_priced_as_a_cached_prompt():
    """`translate.py` marks the system prompt for the cache on every page, so
    pricing it at full input rate charges for tokens nobody was billed for."""
    r = coins.rate_for(PLAIN_CLAUDE)
    assert r.cache_read == pytest.approx(r.inp * 0.10)
    assert r.usd(cached=1_000_000) == pytest.approx(r.inp / 10)
    assert r.usd(cached=1_000_000) < r.usd(tin=1_000_000)


# ------------------------------------------------- per box, which is the point

def test_a_chapter_of_two_box_pages_costs_less_than_one_of_six_box_pages():
    """lee, in as many words: *"make teh coin system be dynamic and per text
    box in a page so if a page has 1 0r 2 tet box it shoiukd be cheaper than a
    page that has 5-6 text boxes"*.

    Asked over a RUN, because that is where whole coins let it be asked. At a
    hundred coins to the dollar one page of translation costs well under one
    coin, so a single two-box page and a single six-box page both round up to
    1 and no rounding scheme can separate them - the price would have to be a
    fraction, and lee asked for whole numbers. Over the chapter somebody
    actually buys, the difference is the whole difference.
    """
    for step in ("ocr", "translate", "proofread"):
        two = coins.quote(step, [2] * 23, PLAIN_CLAUDE)
        six = coins.quote(step, [6] * 23, PLAIN_CLAUDE)
        assert six > two, (step, two, six)


def test_every_extra_box_costs_the_same_as_the_last_one():
    """Not merely "more is dearer" - the price RISES WITH the boxes, evenly,
    because a box is a fixed lump of payload and a fixed lump of reply. A step
    that charged, say, the square of the count would pass the test above."""
    q = [coins.quote("translate", [n] * 23, PLAIN_CLAUDE)
         for n in range(1, 9)]
    steps = [b - a for a, b in zip(q, q[1:])]
    assert min(steps) > 0
    assert max(steps) - min(steps) <= 1, steps       # rounding, and nothing else


def test_a_run_is_rounded_up_once_and_not_once_a_page():
    """The reason `quote` takes a LIST. Twenty-three pages rounded up one at a
    time is twenty-three coins whatever is on them, which is the flat rate lee
    explicitly did not want; the same pages summed and rounded once keep their
    boxes. Rounded UP, still - never down to the sum itself."""
    pages = [1] * 23
    once = coins.quote("proofread", pages, "gemini-2.5-flash-lite")
    each = sum(coins.quote_page("proofread", n, "gemini-2.5-flash-lite")
               for n in pages)
    assert once < each == 23, (once, each)
    real = sum(coins.usd_page("proofread", n, "gemini-2.5-flash-lite")
               for n in pages)
    assert once == coins.coins_for_usd(real) >= real * 200


def test_the_chapter_goes_with_every_page_of_a_translation():
    """The term that was missing, and the biggest one in the file.

    `do_translate` hands the model the whole chapter's lines as context - that
    is what lets a single page be translated with the story in view - and it
    does it on EVERY page. For a 217-box chapter that is thousands of tokens a
    page nobody was counting, twenty-three times over, and it is why a chapter
    estimated at eighteen coins really cost more than a hundred.

    lee, having run one through Gemini 3.6 Flash and read his Google invoice:
    *"before i had $0.502 of money spent and then i did the translation and now
    i have $1.032, so it cost $0.508 to translate the chapter"*.
    """
    one = coins.usd_page("translate", 9, "gemini-3.6-flash",
                         chapter_boxes=0)
    big = coins.usd_page("translate", 9, "gemini-3.6-flash",
                         chapter_boxes=217)
    # The difference is exactly the context, at the input rate - checked
    # against the shape rather than against a ratio, because a ratio moves
    # whenever anything ELSE on the page is repriced and then says nothing
    # about the term it was written to guard. It sat at 1.3 and the counted
    # prompt took it to 1.29.
    sh = coins.SHAPES["translate"]
    r = coins.rate_for("gemini-3.6-flash")
    assert big - one == pytest.approx(r.usd(tin=sh.chapter_in * 217)), (one, big)
    assert sh.chapter_in > 0
    # ...and it is the CHAPTER that makes it dearer, not this page.
    assert coins.usd_page("translate", 9, "gemini-3.6-flash", chapter_boxes=900) \
        > big
    # Reading and proofreading do not send it, so they do not pay for it.
    for step in ("ocr", "proofread"):
        assert coins.usd_page(step, 9, "gemini-3.6-flash", chapter_boxes=0) == \
            coins.usd_page(step, 9, "gemini-3.6-flash", chapter_boxes=900), step


def test_lees_invoice_is_the_read_and_the_translation_together():
    """The one real number this file is calibrated against - and what it is
    actually a number FOR.

    lee: *"before i had $0.502 of money spent and then i did the translation
    and now i have $1.032, so it cost $0.508 to translate the chapter"*. 23
    pages, 213 boxes, Gemini 3.6 Flash, read off Google's own billing page:
    75,400 input and 44,870 output, **$0.4496**.

    It was read as the price of TRANSLATING, and it is not. A balance on a
    billing page is a delta over a window, and it catches every call in that
    window - including the READ, which is the dearest step there is because it
    sends the page as a picture. Fitting the translate step alone to it put
    the read's image tokens into the translator's output, which is where the
    1,689-tokens-a-page "thinking" figure came from and why it was nine times
    what per-call metering later measured.

    Read the way it was really produced - the read at one picture a page,
    which is what the reader did then, plus the translation - it comes back at
    1.2%, with nothing fitted to it:

        ocr(page) 35 coins + translate 56 = 91 = $0.4550 against $0.4496

    That is the whole of the arithmetic in this file agreeing with a real
    invoice: rates, cache, image tokens, thinking per box, and the markup.
    """
    pages = [213 // 23] * 23
    pages[0] += 213 - sum(pages)
    read = coins.quote("ocr", pages, "gemini-3.6-flash", "", 0, None, (),
                       "page")
    tr = coins.quote("translate", pages, "gemini-3.6-flash", "", 0)
    assumed = (read + tr) / coins.COINS_PER_DOLLAR / coins.MARKUP
    assert abs(assumed - 0.4496) <= 0.4496 / 12, (read, tr, assumed)
    # ...and reading it ZOOMED really is the dearer thing, which is the fact
    # that brought the choice back onto the settings screen.
    zoomed = coins.quote("ocr", pages, "gemini-3.6-flash", "", 0, None, (),
                         "boxes")
    assert zoomed > read * 3, (read, zoomed)


def test_and_the_prompt_has_grown_since_that_invoice():
    """The reason the test above has to hold the prompt still.

    `sys_in` is not read for a price any more - `sys_tokens` counts the real
    prompt - and this is what that fixed: the number in the table is less than
    half of what `build_system` really comes to. Measured, not asserted at a
    constant, so it keeps being true as the prompt keeps being edited.
    """
    counted = coins.sys_tokens("translate")
    assert counted > coins.SHAPES["translate"].sys_in * 1.5, counted
    # ...and it is over the cache floor, which is the other thing this number
    # decides. Under it the prompt is never marked for the cache and is paid
    # for in full on every page of a chapter.
    assert counted > coins.CACHE_MIN_TOKENS


def test_three_quarters_of_that_bill_was_the_model_thinking():
    """The half of the invoice the input-side work never touched.

    Of lee's 44,870 output tokens, the visible reply - the words that reach the
    page - was about 6,000. The other 38,800 were reasoning. A shape that
    smears that across the boxes prices a two-box page as thinking a fifth as
    hard as a ten-box page, and prices Claude, which is not asked to think
    anywhere in this app, as though it did.
    """
    sh = coins.SHAPES["translate"]
    pages = [213 // 23] * 23
    pages[0] += 213 - sum(pages)
    reply = sum(_reply("translate", n) for n in pages)
    reasoning = sh.think_out * len(pages)
    assert abs(reply + reasoning - 44_870) <= 44_870 / 12
    # ...and the reasoning really is the bulk of it.
    assert reasoning > 5 * reply
    # Per PAGE, not per box: two pages of the same length reason the same
    # amount however the boxes are spread between them.
    thin = coins.usd_page("translate", 1, "gemini-3.6-flash")
    fat = coins.usd_page("translate", 20, "gemini-3.6-flash")
    assert fat < 3 * thin, (thin, fat)


def test_a_box_costs_what_a_box_puts_in_the_payload():
    """The per-box price has two halves - what the box adds to what is SENT and
    what it adds to what comes BACK - and a test that only watches the total
    rise is satisfied by either one of them working.

    So the dollars are checked against the shape directly. A price that had
    quietly frozen the payload at nine boxes and was riding on the reply alone
    would still rise with the boxes, and would still be wrong for every page
    that is not nine boxes long.
    """
    sh = coins.SHAPES["translate"]
    r = coins.rate_for(PLAIN_CLAUDE)
    for n in (1, 4, 11):
        # No context asked for is no context charged for. Nought means nought.
        want = r.usd(tin=sh.fixed_in + sh.per_box_in * n,
                     cached=_sys("translate"),
                     tout=_reply("translate", n))
        assert coins.usd_page("translate", n, PLAIN_CLAUDE) == want, n
        # ...and context, when there IS some, is charged for what was sent and
        # not for the page it was sent with.
        with_ctx = r.usd(tin=sh.fixed_in + sh.per_box_in * n + sh.chapter_in * 60,
                         cached=_sys("translate"),
                         tout=_reply("translate", n))
        assert coins.usd_page("translate", n, PLAIN_CLAUDE,
                              chapter_boxes=60) == with_ctx, n
    # ...and the two halves really are both in there.
    assert sh.per_box_in > 0 and sh.per_box_out > 0


def test_a_page_with_no_text_box_costs_nothing():
    """A splash page has nothing to send. Not a special case bolted on - it is
    what the arithmetic says, and a chapter is full of them."""
    for step in ("ocr", "translate", "proofread"):
        assert coins.quote_page(step, 0, PLAIN_CLAUDE) == 0


def test_a_whole_run_is_its_pages_added_up():
    """Added up as REAL cost and rounded at the end - the pages are what vary,
    the rounding happens once."""
    pages = (2, 6, 0, 9)
    got = coins.quote("translate", pages, PLAIN_CLAUDE)
    real = sum(coins.usd_page("translate", n, PLAIN_CLAUDE, "", sum(pages))
               for n in pages)
    assert got == coins.coins_for_usd(real) > 0


# ------------------------------------------------------- cleaning, flat a page

def test_cleaning_is_a_flat_fee_a_page():
    """lee: *"the clenning fee shud be a flat fee per page"*. It is a picture
    through a hosted GPU; how many boxes are on it does not change the work."""
    assert coins.usd_page("clean", 0) > 0
    for n in (1, 2, 6, 40):
        assert coins.usd_page("clean", n, "claude-opus-5") == \
            coins.usd_page("clean", 0)
    # ...and a run of them is that fee times the pages, rounded once.
    assert coins.quote("clean", [1, 9, 0]) == \
        coins.coins_for_usd(3 * coins.CLEAN_USD_PER_PAGE)
    assert coins.quote("clean", [0] * 40) > coins.quote("clean", [0] * 4)


def test_the_free_steps_are_free():
    """Find text, Typeset and Export run on this machine. Nobody is billed for
    somebody else's CPU."""
    for step in ("detect", "typeset", "export", ""):
        assert coins.quote_page(step, 9, "claude-opus-5") == 0
        assert coins.quote(step, [9] * 23, "claude-opus-5") == 0


# ------------------------------------------------------------------ the purse

def test_a_new_purse_opens_with_something_in_it():
    """A wallet that opens empty means the first button anybody presses
    refuses, which reads as broken rather than as priced."""
    assert coins.balance() == coins.WELCOME > 0
    assert [e["kind"] for e in coins.ledger()] == ["credit"]


def test_putting_coins_in_and_taking_them_out():
    start = coins.balance()
    assert coins.credit(500) == start + 500
    assert coins.spend(120, "translate", "003.png") == 120
    assert coins.balance() == start + 380
    top = coins.ledger()[0]
    assert (top["kind"], top["what"], top["page"]) == \
        ("spend", "translate", "003.png")


def test_the_purse_is_on_disk_where_the_next_reader_will_find_it():
    """It is a file, and the editor is threaded: two runs and the browser all
    read it. Read back off the disk rather than out of the module, because a
    balance held only in memory passes every other test in this file and is
    gone the moment the app is closed."""
    from mangatl import userdata
    coins.spend(7, "ocr")
    with open(os.path.join(userdata.user_dir(), coins.WALLET),
              encoding="utf8") as fh:
        on_disk = json.load(fh)
    assert on_disk["balance"] == coins.balance() == coins.WELCOME - 7
    assert on_disk["ledger"][-1]["what"] == "ocr"


def test_nothing_is_credited_by_asking_for_nothing():
    start = coins.balance()
    assert coins.credit(0) == start
    assert coins.credit(-500) == start
    assert coins.spend(0) == 0
    assert coins.balance() == start


def test_the_ledger_does_not_grow_for_ever():
    for n in range(coins.LEDGER_MAX + 40):
        coins.spend(1, "translate", "p%d" % n)
    assert len(coins.ledger(10_000)) == coins.LEDGER_MAX
    assert coins.ledger()[0]["page"] == "p%d" % (coins.LEDGER_MAX + 39)


def test_a_wallet_file_that_is_nonsense_is_started_again():
    """Never raises. A hand-edited wallet is a reason to start again, not a
    reason the editor will not open."""
    from mangatl import userdata
    os.makedirs(userdata.user_dir(), exist_ok=True)
    with open(os.path.join(userdata.user_dir(), coins.WALLET), "w") as fh:
        fh.write("{not json at all")
    assert coins.balance() == coins.WELCOME


def test_can_afford_is_what_stops_a_run_not_the_spend():
    """`spend` goes through even into the red, on purpose: it is called AFTER
    the tokens were bought, and refusing the entry would not un-buy them - it
    would only lose the record of the money going."""
    coins.spend(coins.balance() + 50, "translate")
    assert coins.balance() < 0
    assert not coins.can_afford(1)


# ------------------------------------------------------------- the meter

class _Usage:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Reply:
    def __init__(self, **kw):
        self.usage = _Usage(**kw)


def test_the_meter_reads_an_anthropic_reply():
    """Anthropic reports the three input kinds SEPARATELY - `input_tokens`
    already excludes what was read from or written to the cache."""
    assert coins.usage_of(_Reply(
        input_tokens=900, output_tokens=250,
        cache_read_input_tokens=2010, cache_creation_input_tokens=0)) == \
        (900, 250, 2010, 0)


def test_the_meter_reads_an_openai_shaped_reply():
    """One total, with the cached part inside a details object - so it has to
    come back OUT of the total, or it is paid for twice at two rates."""
    assert coins.usage_of({"usage": {
        "prompt_tokens": 2910, "completion_tokens": 250,
        "prompt_tokens_details": {"cached_tokens": 2010}}}) == (900, 250, 2010, 0)


def test_a_reply_with_no_usage_costs_nothing_and_raises_nothing():
    """A metering bug that loses a charge costs money. A metering bug that
    raises loses the translation, and the translation is what the person came
    for."""
    for junk in (None, {}, "hello", object(), {"usage": None}):
        assert coins.usage_of(junk) == (0, 0, 0, 0)


def test_a_reply_whose_usage_blows_up_still_does_not_raise():
    """The case the one above cannot reach: a `usage` that is THERE and throws
    when it is read. A provider that ships a lazy or broken usage object must
    cost the page nothing, not lose it."""
    class Landmine:
        @property
        def usage(self):
            raise RuntimeError("provider changed the shape of this")

    assert coins.usage_of(Landmine()) == (0, 0, 0, 0)
    assert coins.meter(Landmine(), PLAIN_CLAUDE) == 0


def test_what_is_charged_is_what_the_page_really_used():
    """The quote is an estimate; the charge is the tokens the provider
    reported. Metered here at exactly the shape the estimate assumes, so the
    two agree - which is the check that the estimate is honest."""
    sh, r = coins.SHAPES["translate"], coins.rate_for(PLAIN_CLAUDE)
    tin = sh.fixed_in + (sh.per_box_in + sh.chapter_in) * 9
    tout = int(round(_reply("translate", 9)))
    with coins.charging("translate", "003.png", PLAIN_CLAUDE) as bill:
        coins.record(tin, tout, cached=_sys("translate"))
    assert bill.coins == coins.quote_page("translate", 9, PLAIN_CLAUDE)
    assert (bill.tin, bill.tout, bill.cached, bill.calls) == \
        (tin, tout, _sys("translate"), 1)


def test_two_calls_on_one_page_are_one_bill():
    """A page read in four tiles is four calls and one charge."""
    with coins.charging("ocr", "003.png", PLAIN_CLAUDE) as bill:
        for _ in range(4):
            coins.record(600, 40)
    assert bill.calls == 4
    assert bill.coins == coins.coins_for_usd(
        coins.rate_for(PLAIN_CLAUDE).usd(tin=2400, tout=160))


def test_a_call_with_nothing_metering_is_not_charged_to_anybody():
    """Model calls happen outside a run too - listing models, a test button.
    Nothing is metering, so nothing is billed, and nothing raises."""
    start = coins.balance()
    assert coins.record(500, 50) == 0
    assert coins.balance() == start


def test_a_nested_bill_does_not_charge_the_outer_one_twice():
    with coins.charging("translate", "a.png", PLAIN_CLAUDE) as outer:
        coins.record(100, 10)
        with coins.charging("ocr", "a.png", PLAIN_CLAUDE) as inner:
            coins.record(100, 10)
        assert inner.coins > 0
        coins.record(100, 10)
    assert outer.calls == 2


def test_the_flat_fee_lands_on_the_bill_when_one_is_open():
    start = coins.balance()
    with coins.charging("clean", "003.png") as bill:
        coins.flat(coins.quote_page("clean"), "clean", "003.png")
        # ON THE BILL and nowhere else. A fee that also went straight to the
        # purse would be taken twice the moment the bill was settled, and the
        # only sign of it would be a balance falling faster than the ledger
        # says it should.
        assert coins.balance() == start
    assert bill.coins == coins.quote_page("clean")
    assert coins.balance() == start
    coins.spend(bill)
    assert coins.balance() == start - coins.quote_page("clean")


def test_the_flat_fee_goes_straight_to_the_purse_when_none_is():
    """Cleaning is reached from Export and from Typeset as well as from the
    Clean button, and it costs the same however it was reached."""
    start = coins.balance()
    coins.flat(coins.quote_page("clean"), "clean", "003.png")
    assert coins.balance() == start - coins.quote_page("clean")
    assert coins.ledger()[0]["what"] == "clean"


# ------------------------------------------------------ what the numbers mean

def test_a_chapter_costs_about_what_it_really_costs():
    """The check that the whole table is in the right decade. lee measured his
    own chapters at about a dollar for twenty-five pages on Sonnet; doubled,
    that is two dollars, and a 23-page chapter of nine boxes a page has to
    land near it. An order of magnitude out in either direction is a decimal
    point in a rate, and this is what catches it."""
    pages = [9] * 23
    total = sum(coins.quote(s, pages, PLAIN_CLAUDE)
                for s in ("ocr", "translate", "proofread"))
    total += coins.quote("clean", pages)
    usd = total / coins.COINS_PER_DOLLAR
    assert 2.0 <= usd <= 12.0, usd
    # ...and which model you pick has to MATTER, across the whole table, or
    # the per-step model choice is a setting nobody has a reason to touch.
    def chapter(model):
        return sum(coins.quote(s, pages, model)
                   for s in ("ocr", "translate", "proofread")) \
            + coins.quote("clean", pages)
    every = {m: chapter(m) for m in coins.RATES}
    assert max(every.values()) > min(every.values()) * 8, every


def test_show_is_a_whole_number():
    """lee: *"it shoud oporate on whoel numbers"*. There is no fraction of a
    coin anywhere, so there is nothing here to format."""
    assert coins.show(1) == "1"
    assert coins.show(138) == "138"
    assert coins.show(0) == "0"


# ------------------------------------------------------ and in the editor

def _box(k):
    from mangatl.models import TextRegion
    y = 30 + k * 70
    r = TextRegion(id=k, bbox=(30, y, 120, 50), kind="bubble",
                   bubble_bbox=(30, y, 120, 50), confidence=0.9,
                   polygon=[(30, y), (150, y), (150, y + 50), (30, y + 50)])
    r.order, r.src_text, r.dst_text = k, "x", "y"
    return r


def _project(tmp_path, boxes, model=PLAIN_CLAUDE):
    """A chapter of pages with the given box counts."""
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl.project import Project, region_record
    root = str(tmp_path / "proj")
    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    for n, count in enumerate(boxes):
        p.add_uploaded("%03d.png" % (n + 1), cv2.imencode(
            ".png", np.full((600, 420, 3), 240, np.uint8))[1].tobytes())
        # Built the way the app builds them - a hand-written dict is missing
        # keys `materialize` needs and the page-warmer dies on it in a
        # background thread, where nothing fails the test and everything is
        # slower and stranger for it.
        p.pages[n].regions = [region_record(_box(k)) for k in range(count)]
        p.pages[n].detected = True
    # Every step on the one model, because these tests are about the PRICE and
    # not about which step runs where. There is no project-wide engine to set
    # any more - each step carries its own.
    for step in ("ocr", "translate", "proofread"):
        p.settings[f"{step}_backend"] = "anthropic"
        p.settings[f"{step}_model"] = model
        p.settings[f"{step}_key"] = "k"
    p.save()
    return p


def test_the_editor_prices_a_run_off_the_boxes_on_its_pages(tmp_path):
    """Six boxes a page costs more than two - compared between chapters, not
    between halves of one.

    Within a single chapter the comparison does not hold, and it is not the
    price that is wrong: translating the twelve THIN pages sends the twelve fat
    ones as context, and translating the fat ones sends the thin ones. The
    smaller run carries the larger context. See the test below, which is that
    fact written down on purpose.
    """
    from mangatl import editor
    mixed = _project(tmp_path / "mixed", [2] * 12 + [6] * 12)
    assert editor.page_boxes(mixed, 0) == 2
    assert editor.page_boxes(mixed, 23) == 6

    thin = _project(tmp_path / "thin", [2] * 12)
    fat = _project(tmp_path / "fat", [6] * 12)
    whole = list(range(12))
    assert 0 < editor.quote_run(thin, "translate", whole) < \
        editor.quote_run(fat, "translate", whole)
    # ...and the whole chapter is its pages' real cost, rounded once - with no
    # context, because a run that is translating every page has nothing to be
    # consistent with that is not already in it.
    # ...priced with the same two things `run_price` hands `coins.quote`: the
    # SOURCE TEXT on each page (a one-character box does not come back the
    # size of a real one) and the settings the system prompt is built from.
    boxes = [2] * 12 + [6] * 12
    srcs = [editor.page_src_chars(mixed, i) for i in range(24)]
    assert editor.quote_run(mixed, "translate", list(range(24))) == coins.quote(
        "translate", boxes, PLAIN_CLAUDE, "", 0, srcs,
        editor.prompt_key(mixed))


def test_a_page_costs_what_the_chapter_around_it_costs_to_read(tmp_path):
    """The surprising half of restoring the whole-chapter context, written down
    so nobody reads it as a bug later.

    "This page only" is not priced off that page. The page is translated with
    the REST of the chapter in view, so the same page in a long chapter costs
    more than in a short one - and two runs of the same length can be priced
    differently by what is around them rather than what is in them.
    """
    from mangatl import editor
    short = _project(tmp_path / "short", [4] * 3)
    long_ = _project(tmp_path / "long", [4] * 30)
    assert editor.quote_run(long_, "translate", [1]) > \
        editor.quote_run(short, "translate", [1]) > 0


def test_what_is_charged_for_as_context_is_what_is_sent_as_context(tmp_path):
    """One decision, two readers. `run_context` builds the payload and
    `context_boxes` prices it, and this is the test that says so.

    Written out twice they drift, and drift here is silent in BOTH directions:
    charge for context that is not sent and every subset run is overpriced,
    send context that is not charged for and the app eats the difference.
    Neither shows up anywhere but on a bill nobody reads until it is large.
    """
    from mangatl import editor
    p = _project(tmp_path, [3] * 8)
    for idx in ([0], [0, 1], [2, 5], list(range(7))):
        sent = editor.run_context(p, idx) or []
        assert editor.context_boxes(p, "translate", idx) == \
            sum(len(e["lines"]) for e in sent), idx
        assert editor.context_boxes(p, "translate", idx) > 0, idx


def test_a_full_chapter_run_is_charged_no_context_because_it_sends_none(tmp_path):
    """Every page is being translated, so there is nothing to be consistent
    WITH that is not already in the run - and the old price said otherwise.

    On lee's twenty-three page chapter that one `max(boxes, chapter_boxes)` was
    about a hundred thousand input tokens of pure invention.
    """
    from mangatl import editor
    p = _project(tmp_path, [9] * 12)
    whole = list(range(12))
    assert editor.run_context(p, whole) is None
    assert editor.context_boxes(p, "translate", whole) == 0
    # Priced with the page's own source text and prompt settings - the two
    # things `run_price` knows and a bare call to `quote` has to be told.
    srcs = [editor.page_src_chars(p, i) for i in whole]
    key = editor.prompt_key(p)
    assert editor.quote_run(p, "translate", whole) == coins.quote(
        "translate", [9] * 12, PLAIN_CLAUDE, "anthropic", 0, srcs, key)
    # ...and a subset of the same chapter really does pay for its context, or
    # this test would pass on a price that had dropped the term entirely.
    # A single page is priced off its REAL strings now (task #117), and the
    # chapter context is IN those strings - so the check is made against the
    # same counted arithmetic with the context stripped out of the payload,
    # not against the shape. The tiny fixture rounds both into the same coin
    # unless the pages carry real amounts of text, so they are fattened
    # first.
    for pg in p.pages:
        for r in pg.regions:
            r["src_text"] = (r.get("src_text") or "x") * 40
    part = [4]
    assert editor.context_boxes(p, "translate", part) > 0
    with_ctx = editor._counted_page_price(
        p, "translate", 4, 9, editor.page_src_chars(p, 4),
        PLAIN_CLAUDE, "anthropic")
    import json as _json
    from mangatl import translate as T
    page = p.materialize(4)
    bare = T.build_payload(page, p.ctx, None)
    user = (_json.dumps(bare, ensure_ascii=False, indent=1)
            + "\n\n" + T.SCHEMA_HINT)
    system = T.build_system(p.ctx.medium, p.ctx.target,
                            getattr(p.ctx, "source", ""),
                            getattr(p.ctx, "honorifics", True))
    without = coins.quote_counted("translate", system, user, 9,
                                  editor.page_src_chars(p, 4),
                                  PLAIN_CLAUDE, "anthropic")
    assert with_ctx > without, \
        "the counted single-page price does not carry the chapter it sends"


def test_only_translation_pays_for_context(tmp_path):
    """Reading and proofreading are handed one page and asked about that page.
    Charging them for a chapter they never see is charging for nothing."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 6)
    for step in ("ocr", "proofread"):
        assert editor.context_boxes(p, step, [1]) == 0, step


def test_the_editor_prices_against_the_model_the_step_will_use(tmp_path):
    """Reading with Gemini and proofreading with Claude is the whole point of
    the per-step overrides, and a price quoted against the project's default
    would be the wrong price for both."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 8)
    p.settings.update({"translate_model": "gemini-3.5-flash-lite",
                       "translate_backend": "openai",
                       "translate_key": "k"})
    assert editor.step_engine(p, "translate")[0] == "gemini-3.5-flash-lite"
    idx = list(range(len(p.pages)))
    assert editor.quote_run(p, "translate", idx) < \
        editor.quote_run(p, "proofread", idx)


def test_the_free_steps_cost_nothing_in_the_editor_either(tmp_path):
    """...and pricing one does not touch the project's context on the way.

    `run_price` points the context at the step to find out which model to
    price against. There is nothing to price for a free step, so there is
    nothing to point at - and the context belongs to the paid steps, which may
    be part-way through a run of their own."""
    from mangatl import editor
    p = _project(tmp_path, [9, 9])
    p.ctx.model = "left-exactly-as-it-was"
    for step in ("", "detect", "typeset", "export"):
        assert editor.quote_run(p, step, [0, 1]) == 0
        assert p.ctx.model == "left-exactly-as-it-was", step
    assert editor.quote_run(p, "translate", [0, 1]) > 0
    assert p.ctx.model == PLAIN_CLAUDE     # the step's own, from _project


def test_the_hold_leaves_the_purse_when_the_run_starts(tmp_path):
    """lee: *"make teh edit remove the coins when the person click teh
    button"* - and, later, the revamp he asked for: *"i want to get a very
    good extimate"*. What leaves at the press is now the HOLD - the quote
    plus its measured headroom (`coins.hold`, 1.25x) - so the run can never
    outrun its own purse. What is kept at the end is the METER: the settle
    puts the difference back, so an estimate can be wrong in either
    direction without anyone being overcharged. Task #115/#116."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 8)
    price = editor.quote_run(p, "translate", list(range(8)))
    assert price > 0
    reserve = coins.hold(price)
    assert reserve > price, "the hold carries no headroom"
    start = coins.balance()
    seen = []

    def fn(i):
        # ...before the FIRST page, not after the last one.
        seen.append(coins.balance())
        coins.record(909, 252, cached=2010)

    editor._run_one(p, {"label": "Translating", "indices": list(range(8)),
                        "fn": fn, "step": "translate"})
    assert seen[0] == start - reserve, "the press takes the quote, not the hold"
    metered = next(e for e in coins.ledger()
                   if e["kind"] == "meter")["coins"]
    final = min(metered, reserve)
    assert coins.balance() == start - final, \
        "the settle did not put the unused hold back"
    assert p.job["spent"] == final
    give = next((e for e in coins.ledger() if e["kind"] == "credit"), None)
    if reserve > final:
        assert give and give["coins"] == reserve - final
        assert "settle" in give["what"]


def test_cancelling_gives_back_the_pages_it_never_reached(tmp_path):
    """lee: *"if they cancel teh job it shoud refund them the amount for teh
    pages that werent done"*."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 10)
    price = editor.quote_run(p, "translate", list(range(10)))
    start = coins.balance()

    def fn(i):
        coins.record(909, 252, cached=2010)
        if i == 3:
            p.job["cancel"] = True          # the Cancel button, mid-run

    editor._run_one(p, {"label": "Translating", "indices": list(range(10)),
                        "fn": fn, "step": "translate"})
    assert p.job["cancelled"] is True
    assert p.job["done"] == 4
    # The settle needs no arithmetic about the unrun pages any more: calls
    # that never happened were never metered, so their share of the hold
    # comes back by construction. What the invariant is about is that the
    # money adds up: what went out, what came back, and what the purse says.
    reserve = coins.hold(price)
    metered = next(e for e in coins.ledger()
                   if e["kind"] == "meter")["coins"]
    final = min(metered, reserve)
    back_line = next(e for e in coins.ledger() if e["kind"] == "credit")
    back = int(back_line["coins"])
    assert back == reserve - final > 0
    assert coins.balance() == start - final
    assert p.job["spent"] == final
    assert "settle" in back_line["what"]
    assert "6 pages not run" in back_line["what"]
    assert final < price, \
        "four pages of ten metered at the whole run's price"


def test_a_finished_run_pays_its_meter_and_no_more(tmp_path):
    """The old rule was "a finished run gives nothing back - the quote is the
    price". The revamp lee asked for retires it: the meter is the price now,
    the quote (plus headroom) is only what is HELD, and a finished run
    settles down to what its calls really cost - capped at the hold, because
    the settle never takes a second helping."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 5)
    price = editor.quote_run(p, "translate", list(range(5)))
    reserve = coins.hold(price)
    start = coins.balance()
    editor._run_one(p, {"label": "Translating", "indices": list(range(5)),
                        "fn": lambda i: coins.record(909, 252, cached=2010),
                        "step": "translate"})
    metered = next(e for e in coins.ledger()
                   if e["kind"] == "meter")["coins"]
    final = min(metered, reserve)
    assert coins.balance() == start - final
    assert p.job["spent"] == final
    assert final <= reserve


def test_a_run_that_fell_over_gives_back_what_it_never_reached(tmp_path):
    """Same rule as cancelling, and for the same reason: those pages were paid
    for and did not happen. It is the pages, not the fault, that decides."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 10)
    price = editor.quote_run(p, "translate", list(range(10)))
    start = coins.balance()

    def blow_up(i):
        coins.record(909, 252, cached=2010)
        if i == 2:
            raise RuntimeError("the provider hung up")

    editor._run_one(p, {"label": "Translating", "indices": list(range(10)),
                        "fn": blow_up, "step": "translate"})
    assert "hung up" in p.job["error"]
    assert p.job["done"] == 2
    # The page that blew up had already bought its tokens before it fell
    # over, so the meter honestly carries THREE pages of calls against two
    # pages done - and the settle keeps the metered cost, not the done count.
    reserve = coins.hold(price)
    metered = next(e for e in coins.ledger()
                   if e["kind"] == "meter")["coins"]
    final = min(metered, reserve)
    assert coins.balance() == start - final > start - reserve


def test_a_run_nobody_can_pay_for_never_starts(tmp_path):
    """The whole price is taken up front, so there is no such thing any more as
    a run that pays for what it can and stops. It says what it needs and what
    there is, and what to do about it."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 30)
    coins.spend(coins.balance(), "emptying it")
    short = editor.afford_run(p, "translate", list(range(30)))
    assert "not enough TCT Coins" in short
    assert "Run fewer pages" in short
    # ...and a run that IS affordable says nothing at all.
    coins.credit(10_000)
    assert editor.afford_run(p, "translate", list(range(30))) == ""
    # A free step is never short of anything.
    assert editor.afford_run(p, "typeset", list(range(30))) == ""


def test_the_endpoint_refuses_a_run_it_cannot_pay_for(tmp_path):
    """402 Payment Required, and the sentence goes on screen through the same
    error channel every other refusal uses."""
    import urllib.error
    p = _project(tmp_path, [9] * 30)
    coins.spend(coins.balance(), "emptying it")

    def check(call):
        with pytest.raises(urllib.error.HTTPError) as e:
            call("/api/translate_all", {"pages": list(range(30))})
        assert e.value.code == 402
        assert "not enough TCT Coins" in e.value.read().decode()
        # ...and nothing was started.
        assert not editor_job_running()
    from mangatl import editor

    def editor_job_running():
        return bool(p.job.get("running"))
    _serve(check, p)


def test_what_it_really_cost_is_recorded_beside_what_was_charged(tmp_path):
    """The meter line is the evidence the estimate learns from - and since
    the settle, it is also the bill: `charged` on it is what the run finally
    cost after the hold came back."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 6)
    sh, r = coins.SHAPES["translate"], coins.rate_for(PLAIN_CLAUDE)
    # What a page of a FULL-chapter run really sends: no context, because
    # every page is in the run. The meter and the quote are fed the same
    # numbers, so a difference here is the estimate drifting and nothing else.
    tin = sh.fixed_in + sh.per_box_in * 9
    tout = int(round(_reply("translate", 9)))
    editor._run_one(p, {"label": "Translating", "indices": list(range(6)),
                        "fn": lambda i: coins.record(tin, tout,
                                                     cached=_sys("translate")),
                        "step": "translate"})
    assert p.job["cost"] > 0
    assert p.job["cost"] == editor.quote_run(p, "translate", list(range(6)))
    top = next(e for e in coins.ledger() if e["kind"] == "meter")
    held = next(e for e in coins.ledger() if e["kind"] == "spend")
    assert (top["tin"], top["calls"]) == (tin * 6, 6)
    assert top["coins"] == p.job["cost"]
    # the meter line says what was finally CHARGED and what was HELD
    assert top["charged"] == p.job["spent"]
    assert top["held"] == held["coins"] == coins.hold(top["quoted"])
    assert coins.balance() == coins.WELCOME - p.job["spent"]


def test_a_free_step_is_not_charged_and_records_nothing(tmp_path):
    from mangatl import editor
    p = _project(tmp_path, [9] * 4)
    start, n = coins.balance(), len(coins.ledger(10_000))
    editor._run_one(p, {"label": "Laying out text", "indices": [0, 1],
                        "fn": lambda i: None, "step": ""})
    assert coins.balance() == start
    assert len(coins.ledger(10_000)) == n
    assert "cost" not in p.job


def test_a_chapter_with_nothing_on_its_pages_costs_nothing(tmp_path):
    """Pages nobody has run Find text on have no boxes, so there is nothing to
    send and nothing to charge - and the run still goes ahead."""
    from mangatl import editor
    p = _project(tmp_path, [0, 0, 0])
    start, n = coins.balance(), len(coins.ledger(10_000))
    done = []
    editor._run_one(p, {"label": "Translating", "indices": [0, 1, 2],
                        "fn": done.append, "step": "translate"})
    assert done == [0, 1, 2]
    assert coins.balance() == start
    assert len(coins.ledger(10_000)) == n


# ------------------------------------------------------------- over the wire

def _serve(fn, p):
    import urllib.request
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def call(path, obj=None):
        data = json.dumps(obj).encode() if obj is not None else None
        req = urllib.request.Request(
            base + path, data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if obj is not None else "GET")
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    try:
        return fn(call)
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_the_purse_and_the_prices_come_down_together(tmp_path):
    """One answer, because they are shown together - a price quoted from a
    different moment than the balance is how a screen comes to say you can
    afford something you cannot."""
    p = _project(tmp_path, [2, 6])

    def check(call):
        j = call("/api/coins")
        assert j["balance"] == coins.balance()
        assert j["pages"] == 2 and j["boxes"] == 8
        assert set(j["prices"]) == set(("ocr", "translate", "proofread",
                                        "clean"))
        assert j["prices"]["translate"] > 0
        assert j["buy_url"].startswith("http")
        # ...and no money. lee: *"remove teh real money comarasion"*.
        assert "per_dollar" not in j and "usd" not in j
        assert not any(isinstance(v, float) for v in j.values())
    _serve(check, p)


def test_coins_can_be_put_in_over_the_wire(tmp_path):
    p = _project(tmp_path, [2])

    def check(call):
        start = coins.balance()
        j = call("/api/coins", {"coins": 750})
        assert j["ok"] is True
        assert j["balance"] == start + 750 == coins.balance()
    _serve(check, p)


def test_the_only_thing_that_endpoint_can_do_is_add(tmp_path):
    """No way to spend from there and no way to set a balance outright, so the
    worst a stray request can do is give somebody coins."""
    import urllib.error
    p = _project(tmp_path, [2])

    def check(call):
        start = coins.balance()
        for bad in ({"coins": 0}, {"coins": -500}, {"balance": 0}):
            with pytest.raises(urllib.error.HTTPError) as e:
                call("/api/coins", bad)
            assert e.value.code == 400
        assert coins.balance() == start
    _serve(check, p)


# ------------------------------------------------------------- on the screen

def _browser(fn, p):
    from mangatl import editor
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            browserpool.settled(pg)
            pg.wait_for_function("typeof wallet!=='undefined' && wallet",
                                 timeout=8000)
            try:
                return fn(pg)
            finally:
                assert not errs, errs
    finally:
        editor.PROJECT = was
        srv.shutdown()


def test_the_count_is_at_the_top_of_the_screen(tmp_path):
    """lee: *"also add a coin count in the ui at the top"*.

    In `#top` itself, not inside the two groups that swap with the tab you are
    on: what is left to spend is true on Settings and on Results as well.
    """
    p = _project(tmp_path, [2, 6])

    def check(pg):
        assert pg.evaluate(
            "!!document.querySelector('#top #coinBtn')"), "not in the top bar"
        assert pg.evaluate("document.getElementById('coinN').textContent") == \
            coins.show(coins.balance())
        for tab in ("settings", "results", "new", "edit"):
            pg.evaluate("setTab('%s')" % tab)
            browserpool.settled(pg)
            assert pg.evaluate(
                "document.getElementById('coinBtn')"
                ".getBoundingClientRect().width") > 0, tab
    _browser(check, p)


def test_the_coin_wears_the_logo(tmp_path):
    """lee: *"use the logo as the coin face"*. The same path as the mark in
    the corner and the same path as the app icon - read off the drawn SVG, so
    a coin that has quietly become a circle with nothing on it fails here."""
    import re
    from pathlib import Path
    p = _project(tmp_path, [2])
    root = PKG / "static"
    brand = re.search(r'd="(M7 10[^"]+)"',
                      (root / "favicon.svg").read_text(encoding="utf8")).group(1)

    def check(pg):
        paths = pg.evaluate(
            "[...document.querySelectorAll('#tctcoin path')]"
            ".map(e=>({d:e.getAttribute('d'), fill:e.getAttribute('fill')}))")
        assert [q["d"] for q in paths] == [brand, brand], paths
        # Struck, not printed: a highlight under a darker face. One path alone
        # is a mark laid on the metal, and it is the pair that reads as a coin
        # at the 15px the bar draws it at.
        assert len({q["fill"] for q in paths}) == 2, paths
        # ...and it IS a coin: a disc under the mark, not the bare mark.
        assert pg.evaluate(
            "document.querySelectorAll('#tctcoin circle').length") >= 2
        # ...and the count in the bar is drawing THAT coin, not a copy of it.
        assert pg.evaluate(
            "document.querySelector('#coinBtn use').getAttribute('href')") == \
            "#tctcoin"
    _browser(check, p)


def test_the_purse_opens_and_says_what_the_chapter_costs(tmp_path):
    p = _project(tmp_path, [2, 6])

    def check(pg):
        pg.evaluate("toggleWallet()")
        browserpool.settled(pg)
        txt = pg.evaluate("document.getElementById('walletPop').textContent")
        assert "TCT Coins" in txt
        for label in ("Read text", "Translate", "Proofread", "Clean"):
            assert label in txt, label
        assert "8 text boxes" in txt          # 2 + 6, and it says which
        # The total is the four steps added up, off the same per-page prices.
        assert str(sum(coins.quote(s, [2, 6], PLAIN_CLAUDE)
                       for s in ("ocr", "translate", "proofread", "clean"))) \
            in txt
    _browser(check, p)


def test_buying_coins_opens_the_website_and_nothing_else(tmp_path):
    """lee: *"the top up just have a buy coin button that will link to oa page
    on the website"*. There is no way to give yourself coins from inside the
    editor any more - it is a thing somebody runs on their own machine, and a
    card number has no business in it."""
    p = _project(tmp_path, [2])

    def check(pg):
        pg.evaluate("toggleWallet()")
        browserpool.settled(pg)
        txt = pg.evaluate("document.getElementById('walletPop').textContent")
        assert "Buy coins" in txt
        # The suite runs on the developer's test purse (conftest), whose own
        # +100/+1000/+5000 row is allowed to be there; the old top-up amounts
        # are matched as whole numbers so +5000 is not read as +500.
        import re
        for gone in ("+500", "+2000", "+10000"):
            assert not re.search(re.escape(gone) + r"(?!\d)", txt), gone
        for gone in ("Recently", "$"):
            assert gone not in txt, gone
        opened = pg.evaluate("""(()=>{
            const was = window.open; let got = null;
            window.open = (u)=>{got = u; return null;};
            try { buyCoins(); } finally { window.open = was; }
            return got;})()""")
        assert opened == coins.BUY_URL, opened
    _browser(check, p)


def test_the_count_falls_while_a_run_is_spending_and_not_twice(tmp_path):
    """`job.spent` is what the run has taken SO FAR and the balance behind it
    is what the last read of the purse saw. Subtracting one from the other is
    the live figure - and it must be drawn, not stored, or every poll takes
    the same spend off again and the count falls twice as fast as the money.
    """
    p = _project(tmp_path, [2])

    def check(pg):
        pg.evaluate("wallet.balance = 100")        # whatever is really there
        for _ in range(4):
            pg.evaluate("coinsSpending(20)")       # the same 20 coins, 4 polls
        assert pg.evaluate("document.getElementById('coinN').textContent") == "80"
        assert pg.evaluate("wallet.balance") == 100
    _browser(check, p)


# ----------------------------------------- and the cleaning fee, where it lands

def _fake_clean(monkeypatch, neural):
    """Stand in for the inpainter and say how much of the page the HOSTED
    cleaner did. Everything else about `clean_page` runs for real."""
    import numpy as np
    from mangatl import editor

    def fake(page, **kw):
        page.clean_plate = page.image.copy()
        page.clean_stats = {"neural": neural, "flat fill": 3 - neural}
        return page
    monkeypatch.setattr(editor.inpaint_mod, "inpaint_page", fake)


def test_a_page_the_hosted_cleaner_touched_pays_the_flat_fee(tmp_path,
                                                             monkeypatch):
    from mangatl import editor
    p = _project(tmp_path, [4])
    _fake_clean(monkeypatch, neural=2)
    start = coins.balance()
    editor.do_clean(p, 0, force=True)
    assert start - coins.balance() == coins.quote_page("clean")
    assert coins.ledger()[0]["what"] == "clean"


def test_a_page_cleaned_on_this_machine_is_free(tmp_path, monkeypatch):
    """The fee is for somebody else's GPU. A chapter filled flat here is this
    person's own CPU, exactly as Typeset and Export are - and it matters more
    than it looks, because the background page-builder cleans pages nobody
    asked it to and a fee there would be charged silently."""
    from mangatl import editor
    p = _project(tmp_path, [4])
    _fake_clean(monkeypatch, neural=0)
    start = coins.balance()
    editor.do_clean(p, 0, force=True)
    assert coins.balance() == start


def test_a_plate_out_of_the_cache_is_not_charged_again(tmp_path, monkeypatch):
    """Pressing Clean twice on a page that is already clean sends nothing
    anywhere, so it costs nothing."""
    from mangatl import editor
    p = _project(tmp_path, [4])
    _fake_clean(monkeypatch, neural=2)
    editor.do_clean(p, 0, force=True)
    start = coins.balance()
    editor.do_clean(p, 0)                      # no force: reuse what is there
    assert coins.balance() == start


def test_a_page_with_its_own_cleaned_file_is_not_charged(tmp_path, monkeypatch):
    """lee: *"if i uploade my own file it shoud exclude that page from
    cleaing"*. It is excluded from the bill for the same reason."""
    import numpy as np
    cv2 = pytest.importorskip("cv2")
    from mangatl import editor
    p = _project(tmp_path, [4])
    dest = str(tmp_path / "mine.png")
    cv2.imwrite(dest, np.full((600, 420, 3), 255, np.uint8))
    p.pages[0].custom_clean = dest
    _fake_clean(monkeypatch, neural=2)
    start = coins.balance()
    editor.do_clean(p, 0, force=True)
    assert coins.balance() == start
    assert p.pages[0].cleaned is True


def test_the_count_is_a_whole_number_and_nothing_else(tmp_path):
    """lee: *"it shoud oporate on whoel numbers"*. No decimal point anywhere
    on the screen - the server never sends a fraction, and the count must not
    invent one either."""
    p = _project(tmp_path, [2])

    def check(pg):
        for n in (0, 1, 7, 138, 100000):
            pg.evaluate("paintCount(%d)" % n)
            assert pg.evaluate(
                "document.getElementById('coinN').textContent") == str(n), n
        assert "." not in pg.evaluate(
            "document.querySelector('.coinwrap').textContent")
    _browser(check, p)


def test_a_run_can_be_priced_for_the_pages_it_would_touch(tmp_path):
    """lee: *"on the pop up it shoud tell teh price for all the pages and and
    this page onli on the side"*. Both numbers, one request, priced for
    exactly the pages each button would run.

    Priced on the SERVER for each set, not assembled on the screen out of
    per-page numbers: a price is whole coins rounded up once over the run, and
    twenty-three pages rounded up one at a time is twenty-three coins whatever
    is on them."""
    p = _project(tmp_path, [9] * 20)

    def check(call):
        whole = call("/api/coins")["prices"]["translate"]
        half = call("/api/coins?pages=0,1,2,3,4,5,6,7,8,9")["prices"]["translate"]
        one = call("/api/coins?page=0")["one"]["translate"]
        assert 0 < one < half < whole, (one, half, whole)
        # One page is a big share of the whole chapter, and that is not a bug:
        # translating one page still sends the whole chapter as context. The
        # per-page saving is real but it is nothing like a twentieth.
        assert one * 21 >= whole > one * 2, (one, whole)
        # An empty `pages` is the whole chapter - that is what the button says
        # when nothing is ticked. An empty `page` is nothing at all, because
        # "This page only" with no page is not the chapter.
        assert call("/api/coins?pages=")["prices"]["translate"] == whole
        assert call("/api/coins")["one"]["translate"] == 0
        # A page number nobody has is not a page - including a NEGATIVE one,
        # which Python would otherwise happily read as counting back from the
        # end and quote the last page of the chapter for.
        assert call("/api/coins?page=999")["one"]["translate"] == 0
        assert call("/api/coins?page=-1")["one"]["translate"] == 0
        assert call("/api/coins?pages=-1,-2")["prices"]["translate"] == whole
        assert call("/api/coins?pages=nonsense")["pages"] == 20
    _serve(check, p)


def test_the_dialog_puts_a_price_beside_each_choice(tmp_path):
    """Beside the label, not in it - the label still reads as the label and
    the number is the thing you are comparing between the two rows."""
    p = _project(tmp_path, [9] * 6)

    def check(pg):
        pg.evaluate("stepScope('translate_all','Translate')")
        pg.wait_for_function(
            "document.querySelectorAll('#scpAll .scpcoin,#scpOne .scpcoin')"
            ".length===2", timeout=8000)
        got = pg.evaluate("""({
            all: document.querySelector('#scpAll .scpcoin').textContent.trim(),
            one: document.querySelector('#scpOne .scpcoin').textContent.trim(),
            label: document.getElementById('scpOne').firstChild.textContent})""")
        assert got["label"].strip() == "This page only", got
        assert int(got["all"]) > int(got["one"]) > 0, got
        # ...and the COIN is drawn beside the number - the same coin as the
        # one in the top bar, not a gold dot standing in for it. lee: *"also
        # make the coin look like the oher coins"*.
        assert pg.evaluate(
            "document.querySelectorAll('#scpAll .scpcoin use').length") == 1
        assert pg.evaluate(
            "document.querySelector('#scpAll .scpcoin use')"
            ".getAttribute('href')") == "#tctcoin"
    _browser(check, p)


def test_a_free_step_shows_no_price_at_all(tmp_path):
    """A zero on a button reads as a price nobody has worked out yet, not as
    free. Typeset runs on this machine; it has no price, so it shows none.

    Asked in the order that catches it: the PAID step first, so there is a
    price on the dialog, and then the free one. The dialog is one dialog
    reused for every step, and a price it forgets to clear is the last step's
    price sitting under this step's label.
    """
    p = _project(tmp_path, [9] * 3)

    def check(pg):
        pg.evaluate("stepScope('clean_all','Clean the pages')")
        pg.wait_for_function(
            "document.querySelectorAll('#scopedlg .scpcoin').length===2",
            timeout=8000)
        pg.evaluate("stepScope('typeset_all','Lay the text out')")
        pg.wait_for_timeout(500)
        assert pg.evaluate(
            "document.querySelectorAll('#scopedlg .scpcoin').length") == 0
    _browser(check, p)


def test_pricing_the_dialog_twice_leaves_one_price(tmp_path):
    """`priceScope` runs at least twice for every opening - once immediately,
    so the dialog is not blank, and again when the quote comes back from the
    server. It has to be safe to run any number of times: the second run must
    REPLACE the price, not add another one beside it.

    Called directly rather than through `stepScope`, because `stepScope` also
    rewrites the button labels and rewriting a label happens to wipe the price
    with it. That side effect is not the guarantee - this is.
    """
    p = _project(tmp_path, [9] * 4)

    def check(pg):
        pg.evaluate("stepScope('translate_all','Translate')")
        pg.wait_for_function(
            "document.querySelectorAll('#scopedlg .scpcoin').length===2",
            timeout=8000)
        for _ in range(3):
            pg.evaluate("priceScope()")
        assert pg.evaluate(
            "document.querySelectorAll('#scopedlg .scpcoin').length") == 2
        # ...and it is still the price, not a price with a price after it.
        assert pg.evaluate(
            "document.querySelectorAll('#scpAll .coinpip').length") == 1
    _browser(check, p)


def test_the_dialog_prices_the_pages_that_button_would_run(tmp_path):
    """"Selected pages (4)" has to be the price of those four. Quoting the
    whole chapter beside a button that will run four pages is not a rounding
    error, it is the wrong number - and it is the number somebody decides on.
    """
    p = _project(tmp_path, [9] * 20)

    def check(pg):
        pg.evaluate("""selPages = new Set(proj.pages.slice(0,4)
                                              .map(q=>q.name))""")
        pg.evaluate("stepScope('translate_all','Translate')")
        pg.wait_for_function(
            "document.querySelectorAll('#scpAll .scpcoin').length===1",
            timeout=8000)
        four = int(pg.evaluate(
            "document.querySelector('#scpAll .scpcoin').textContent.trim()"))
        assert pg.evaluate("$('scpAll').textContent").startswith(
            "Selected pages (4)")

        pg.evaluate("selPages = new Set(proj.pages.map(q=>q.name))")
        pg.evaluate("stepScope('translate_all','Translate')")
        pg.wait_for_function(
            "document.querySelectorAll('#scpAll .scpcoin').length===1",
            timeout=8000)
        every = int(pg.evaluate(
            "document.querySelector('#scpAll .scpcoin').textContent.trim()"))
        assert 0 < four < every, (four, every)
    _browser(check, p)


# ---------------------------------------------------------- from the shell

def test_coins_can_be_added_from_the_shell():
    """Until there is a Firebase account behind the balance and a Stripe
    checkout in front of it, SOMETHING has to be able to put coins in, or the
    person who wrote the app locks himself out of it after a chapter and a
    half.

    A command and not a button: it has to be something you know about, on the
    machine the wallet lives on, rather than a control on a screen that will
    one day be a customer's."""
    start = coins.balance()
    assert coins._main([]) == 0
    assert coins.balance() == start                  # reading takes nothing
    assert coins._main(["add", "250"]) == 0
    assert coins.balance() == start + 250
    assert coins.ledger()[0]["what"] == "added from the shell"
    assert coins._main(["ledger"]) == 0


def test_the_shell_cannot_add_nothing_or_less():
    """`add` with no number, or a negative one, is a typo - and a negative one
    would be a way to empty somebody's purse from a shell history."""
    start = coins.balance()
    for bad in (["add"], ["add", "0"], ["add", "-500"]):
        with pytest.raises(SystemExit) as e:
            coins._main(bad)
        assert e.value.code != 0, bad
    assert coins.balance() == start


def test_the_shell_refuses_a_word_it_does_not_know():
    """`python -m mangatl.coins spend 999` must not quietly do nothing and
    exit 0 - an unknown verb is a mistake and has to look like one."""
    for bad in (["spend", "999"], ["set", "0"], ["--everything"]):
        with pytest.raises(SystemExit) as e:
            coins._main(bad)
        assert e.value.code != 0, bad


# ------------------------------------------------- a model nobody has priced

def test_an_unpriced_model_is_named_out_loud(tmp_path):
    """It is charged at the dearest rate on the list. That is the right way
    round - charging an unknown model as free is a bill this app eats - and it
    is an eightfold difference nobody would guess from the number.

    lee's own screenshot is what this is for: Read text 2 coins beside
    Translate 171, on the same chapter, because one step was on a model in the
    list and the other was not.
    """
    p = _project(tmp_path, [9] * 4)
    p.settings.update({"translate_model": "gemini-4-does-not-exist-yet",
                       "translate_backend": "openai", "translate_key": "k"})

    def check(call):
        j = call("/api/coins")
        assert j["unpriced"] == ["translate"]
        assert j["models"]["translate"] == "gemini-4-does-not-exist-yet"
        # ...and it really is dearer, by a lot.
        assert j["prices"]["translate"] > 4 * j["prices"]["proofread"]
    _serve(check, p)


def test_a_priced_model_is_not_flagged(tmp_path):
    p = _project(tmp_path, [9] * 4)

    def check(call):
        assert call("/api/coins")["unpriced"] == []
    _serve(check, p)


def test_a_model_you_run_yourself_is_not_flagged(tmp_path):
    """It costs nothing, so there is nothing to be wrong about."""
    p = _project(tmp_path, [9] * 4)
    for step in ("ocr", "translate", "proofread"):
        p.settings[f"{step}_backend"] = "ollama"
        p.settings[f"{step}_model"] = "qwen2.5:14b"

    def check(call):
        j = call("/api/coins")
        assert j["unpriced"] == []
        assert j["prices"]["translate"] == 0
    _serve(check, p)


def test_the_purse_says_so_on_the_screen(tmp_path):
    p = _project(tmp_path, [9] * 4)
    p.settings.update({"translate_model": "gemini-4-does-not-exist-yet",
                       "translate_backend": "openai", "translate_key": "k"})

    def check(pg):
        pg.evaluate("toggleWallet()")
        browserpool.settled(pg)
        pg.wait_for_function(
            "document.querySelectorAll('#walletPop .wnote.warn').length===1",
            timeout=8000)
        txt = pg.evaluate("document.getElementById('walletPop').textContent")
        assert "gemini-4-does-not-exist-yet" in txt
        assert "not in the price list" in txt
        # ...and the row itself is marked, so the number is not read alone.
        assert pg.evaluate(
            "document.querySelectorAll('#walletPop .wrow.unpriced').length") == 1
    _browser(check, p)


def test_priced_knows_what_it_knows():
    assert coins.priced("claude-sonnet-5-20260514") is True
    assert coins.priced("gemini-3.5-flash-lite") is True
    assert coins.priced("gemini-4-ultra") is False
    assert coins.priced("") is False
    # Your own machine is free, so there is nothing to price.
    assert coins.priced("anything-at-all", "ollama") is True


# ------------------------------------------------ every model, at its own price

CLAUDE = ["claude-fable-5", "claude-opus-5", "claude-sonnet-5",
          "claude-haiku-4-5"]
GEMINI = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
          "gemini-3.1-pro", "gemini-3.1-flash-lite", "gemini-3-flash",
          "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


@pytest.mark.parametrize("model", CLAUDE + GEMINI)
def test_every_active_claude_and_gemini_model_has_a_price(model):
    """lee: *"do price all teh claude and gemini active modeles"*.

    Not "the table has an entry" - the entry has to be REACHED, by the same
    longest-prefix lookup a real model id goes through, and it has to be a
    price rather than the unknown-model fallback wearing one."""
    assert coins.priced(model), model
    r = coins.rate_for(model)
    assert r.inp > 0 and r.out > r.inp, model
    assert (r.inp, r.out) != (coins.UNKNOWN.inp, coins.UNKNOWN.out), model


@pytest.mark.parametrize("model", CLAUDE + GEMINI)
def test_a_dated_snapshot_of_a_model_is_the_model(model):
    """`claude-sonnet-5-20260514` and `-preview` and `-latest` are the same
    model at the same price. A dated snapshot falling through to the
    unknown-model rate is a bill five times too big on the day a provider
    pins a version."""
    for suffix in ("-20260514", "-preview", "-latest", "-001"):
        assert coins.rate_for(model + suffix) is coins.rate_for(model), \
            model + suffix


def test_the_lite_models_are_not_priced_as_their_full_size_siblings():
    """The one that longest-prefix exists for. `gemini-3.5-flash-lite` starts
    with `gemini-3.5-flash`, and matching the shorter key first would charge
    the cheapest model in the range at five times its price - which is exactly
    what was happening before this table was checked against the real one."""
    for lite, full in (("gemini-3.5-flash-lite", "gemini-3.5-flash"),
                       ("gemini-3.1-flash-lite", "gemini-3.1-pro"),
                       ("gemini-2.5-flash-lite", "gemini-2.5-flash")):
        assert coins.rate_for(lite).inp < coins.rate_for(full).inp, lite


def test_the_cache_is_a_tenth_of_input_on_both_providers():
    for m in CLAUDE:
        assert coins.rate_for(m).cache_read == pytest.approx(
            coins.rate_for(m).inp * 0.10), m
        # Anthropic charges a quarter over to WRITE the cache; Google does not
        # charge to write at all, and a rate that claimed otherwise would show
        # up as a bill on the first page of every chapter.
        assert coins.rate_for(m).cache_write > coins.rate_for(m).inp, m
    for m in GEMINI:
        assert coins.rate_for(m).cache_read == pytest.approx(
            coins.rate_for(m).inp * 0.10), m
        assert coins.rate_for(m).cache_write == 0.0, m


def test_the_unknown_rate_is_the_dearest_thing_on_the_list():
    """It has to stay the dearest as models are added, or the fallback quietly
    becomes a discount for anything unrecognised."""
    dearest = max(r.inp for r in coins.RATES.values())
    assert coins.UNKNOWN.inp >= dearest


def test_a_price_is_never_a_discount_somebody_else_can_withdraw():
    """Sonnet 5 is on a promotional rate at the moment. It is NOT the rate
    here. lee: *"no promotianal rate us teh normal rate"*.

    A price that is somebody else's discount is a price that changes under you
    on a date you do not control, and every quote given while it lasted would
    be a quote that has to go up. The standing rate is the one that survives
    the discount ending, and a quote that is a little over cost for a few weeks
    is the cheaper mistake.
    """
    assert coins.rate_for("claude-sonnet-5").inp == 3.0
    assert coins.rate_for("claude-sonnet-5").out == 15.0
    assert not hasattr(coins, "SONNET_PROMO_ENDS")


def test_a_chapter_costs_a_sensible_number_of_coins_on_every_model():
    """The sanity rail across the whole table at once: 23 pages of nine boxes
    is somewhere between a few coins and a few hundred, on everything from the
    cheapest Flash-Lite to the dearest Claude. A decimal point in the wrong
    place in any one row shows up here."""
    pages = [9] * 23
    for m in CLAUDE + GEMINI:
        total = sum(coins.quote(s, pages, m)
                    for s in ("ocr", "translate", "proofread"))
        assert 3 <= total <= 1600, (m, total)


# ------------------------------------------------ thinking, and whose name it is

def test_a_thinking_model_is_priced_for_its_thinking(tmp_path):
    """Gemini bills its reasoning back as output tokens and there is no way to
    ask it not to through the endpoint this app uses. Nine tenths of lee's
    output bill was reasoning; a quote without it is a quote at a fifth."""
    with_ = coins.usd_page("translate", 9, "gemini-3.6-flash")
    sh, r = coins.SHAPES["translate"], coins.rate_for("gemini-3.6-flash")
    without = r.usd(tin=sh.fixed_in + sh.per_box_in * 9 + _sys("translate"),
                    tout=_reply("translate", 9))
    # The difference is the reasoning, at the output rate - PER BOX, which is
    # the shape the meter says it has. Flat per page fitted two runs on two
    # model versions to 133 and 37 and agreed about nothing; per box they are
    # 15 and 19. See `coins.THINK_PER_BOX`.
    assert with_ - without == pytest.approx(
        r.usd(tout=coins.think_tokens(sh, "gemini-3.6-flash", "", 9)))
    # ...and it is a real term rather than a rounding: pricing it at nothing,
    # which is the bug this guards, would make these two equal.
    #
    # It is NOT "the bigger half of the page" any more, and that claim is what
    # this assertion used to make. It came from reading lee's billing-page
    # delta as the translator's output when most of it was the READ's picture
    # tokens - see the invoice test above. Metered per call, a 3.7 Flash page
    # returns 440 output tokens all in, and the reasoning is about 15 a box.
    assert with_ > without, (without, with_)
    # ...and it grows with the BOXES, because a model reasons about the lines
    # it was given. Flat per page is the shape this replaced.
    thin = coins.usd_page("translate", 2, "gemini-3.6-flash")
    fat = coins.usd_page("translate", 20, "gemini-3.6-flash")
    sh2 = coins.SHAPES["translate"]
    grew = (coins.think_tokens(sh2, "gemini-3.6-flash", "", 20)
            - coins.think_tokens(sh2, "gemini-3.6-flash", "", 2))
    assert grew > 0
    assert fat - thin > r.usd(tout=grew) * 0.5, (thin, fat)


def test_a_claude_that_is_not_asked_to_think_is_not_charged_for_it(tmp_path):
    """No request in this app turns Claude's thinking on. On the 4 line that
    means it is off, and pricing it anyway quoted Sonnet 4 at seven times its
    real output cost."""
    for m in ("claude-haiku-4-5", "claude-sonnet-4", "claude-opus-4"):
        assert coins.thinks(m) is False, m
    sh, r = coins.SHAPES["translate"], coins.rate_for(PLAIN_CLAUDE)
    want = r.usd(tin=sh.fixed_in + sh.per_box_in * 9, cached=_sys("translate"),
                 tout=_reply("translate", 9))
    assert coins.usd_page("translate", 9, PLAIN_CLAUDE) == want


def test_the_claude_5_line_thinks_whether_asked_or_not(tmp_path):
    """Task #125. The sentence above was true until the 5 line. Anthropic:
    *"On Claude Opus 5, Claude Sonnet 5, Claude Fable 5.1 ... thinking is
    already on and needs no configuration"*, billed as output tokens and
    reported nowhere. Measured on lee's 58-page manhwa: 19,576 output
    tokens for a read Gemini answered in 3,110 - five sixths reasoning - and
    a quote that had it at nothing let the run overshoot its hold by 49
    coins."""
    for m in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5",
              "anthropic/claude-opus-5"):
        assert coins.thinks(m) is True, m
    sh, r = coins.SHAPES["translate"], coins.rate_for("claude-sonnet-5")
    without = r.usd(tin=sh.fixed_in + sh.per_box_in * 9,
                    cached=_sys("translate"), tout=_reply("translate", 9))
    assert coins.usd_page("translate", 9, "claude-sonnet-5") > without
    # ...and on a step where nothing switches it off, a thinking model is
    # quoted for its thinking. The old `shape.think_out` gate switched
    # reasoning off for every step but translate, whatever the model did.
    assert coins.think_tokens(coins.SHAPES["proofread"], "claude-opus-5", "",
                              10, "proofread") > 0
    # ...and on the READ too, which is where it was found. The reader CAN
    # turn it off (`READ_THINKING_OFF`, see `test_a_read_without_the_
    # thinking.py`); lee measured both and kept it on, so the read is quoted
    # with it. This assertion follows that list, whichever way it is set.
    assert coins.thinks("claude-opus-5", "anthropic", "ocr") is \
        (not coins.read_thinks_off("claude-opus-5"))


def test_a_model_you_run_yourself_thinks_for_free():
    """Nothing bought from anyone. There is no bill to put reasoning on."""
    assert coins.thinks("gemini-3.6-flash", "ollama") is False
    assert coins.usd_page("translate", 9, "gemini-3.6-flash", "ollama") == 0.0


def test_the_same_model_costs_the_same_whoever_sold_it_to_you():
    """OpenRouter names a model by who MAKES it, so the same model arrives
    under two ids. Every question this file answers about a model has the same
    answer for both - and each one is matched by prefix, so without the vendor
    coming off they all take the wrong branch in silence: an unpriced model is
    charged at the top of the range, a marked cache is never priced, and a
    thinking model is quoted at a fifth of its bill."""
    for slug, direct in (("google/gemini-3.6-flash", "gemini-3.6-flash"),
                         ("anthropic/claude-sonnet-5", "claude-sonnet-5")):
        assert coins.rate_for(slug) == coins.rate_for(direct), slug
        assert coins.thinks(slug) == coins.thinks(direct), slug
        assert coins.priced(slug), slug
        assert coins.usd_page("translate", 9, slug) == \
            coins.usd_page("translate", 9, direct), slug


def test_only_one_segment_of_the_name_comes_off():
    """`google/gemini-2.5-flash-lite` has one slash and the price table's key
    has none. Cutting at the LAST slash leaves `flash-lite`, which is not a
    model anybody prices; cutting nothing leaves a name no table has."""
    assert coins.vendor_free("google/gemini-2.5-flash-lite") == \
        "gemini-2.5-flash-lite"
    assert coins.vendor_free("claude-sonnet-5") == "claude-sonnet-5"
    assert coins.vendor_free("") == ""
    assert coins.rate_for("google/gemini-2.5-flash-lite") == \
        coins.rate_for("gemini-2.5-flash-lite")


def test_a_cache_is_only_priced_where_this_app_asks_for_one():
    """Anthropic and nowhere else. Google's implicit caching is real and is not
    something you can ask for; pricing it here undercharges by the whole of it
    on every Gemini chapter, and undercharging is the failure that does not
    announce itself."""
    sh = coins.SHAPES["translate"]
    assert coins.cached_tokens(sh, PLAIN_CLAUDE) == sh.sys_in
    assert coins.cached_tokens(sh, "anthropic/claude-sonnet-5") == sh.sys_in
    assert coins.cached_tokens(sh, "gemini-3.6-flash") == 0
    # Below the floor there is no cache to price, whoever the model is.
    #
    # Asked of a shape MADE HERE, where it used to borrow `SHAPES["ocr"]`.
    # That was the smallest prompt in the table until Read text learned to
    # label boxes: the labeller's own prompt is over the floor and IS cached,
    # so the shape stopped illustrating the rule and this went red for a reason
    # that had nothing to do with the rule.
    #
    # A test that borrows a real value as an illustration breaks whenever that
    # value moves for its own reasons - and the temptation each time is to
    # reach for whichever entry is smallest today, which only sets the trap
    # again. The claim is about the FLOOR, so the fixture is a shape under it.
    small = coins.Shape(sys_in=coins.CACHE_MIN_TOKENS - 1, fixed_in=500,
                        per_box_in=0, chapter_in=0, per_box_out=10)
    assert coins.cached_tokens(small, PLAIN_CLAUDE) == 0
    over = coins.Shape(sys_in=coins.CACHE_MIN_TOKENS, fixed_in=500,
                       per_box_in=0, chapter_in=0, per_box_out=10)
    assert coins.cached_tokens(over, PLAIN_CLAUDE) == over.sys_in, \
        "the floor has to be the only thing deciding it"


def test_a_slug_nobody_wrote_out_is_still_priced_by_its_maker():
    """Ten OpenRouter models are written into the table by hand. Everything
    ELSE that arrives namespaced falls back to the model's own entry - and
    without that fallback it is UNKNOWN, which is the top of the range, an
    eightfold difference, and silent.

    Asked with a slug that is deliberately NOT in the table, because the ten
    that are would pass this whether the fallback existed or not.
    """
    for slug in ("google/gemini-3-pro", "anthropic/claude-opus-5",
                 "openai/gpt-4o"):
        assert slug not in coins.RATES, "pick one that is not written out"
        assert coins.rate_for(slug) == coins.rate_for(coins.vendor_free(slug)), slug
        assert coins.rate_for(slug) != coins.UNKNOWN, slug
        assert coins.priced(slug), slug
    # ...and the cache and the thinking follow the same road.
    sh = coins.SHAPES["translate"]
    assert coins.cached_tokens(sh, "anthropic/claude-opus-5") == sh.sys_in
    assert coins.thinks("google/gemini-3-pro") is True
    assert coins.thinks("anthropic/claude-opus-5") is True
    assert coins.thinks("anthropic/claude-opus-4") is False
    # A slug cut at the LAST slash would be `gemini-3-pro` here too, so the
    # multi-segment case is what pins the rule.
    assert coins.vendor_free("meta/llama/3-70b") == "llama/3-70b"


def test_a_slug_priced_in_its_own_right_beats_its_makers_price(monkeypatch):
    """The id is looked up WHOLE before the vendor comes off, and this is the
    only thing that turns on it.

    Every OpenRouter slug in the table today costs exactly what the direct
    model costs, so today the two orders give the same answer. The order is
    the guarantee for the day one of them does NOT - a reseller surcharge, a
    promotional rate, a slug that lands on a different tier - and a guarantee
    with nothing testing it is a guarantee that quietly stops holding.
    """
    slug, direct = "google/gemini-3.6-flash", "gemini-3.6-flash"
    dearer = coins.Rate(9.0, 45.0)
    assert coins.rate_for(slug) != dearer
    monkeypatch.setitem(coins.RATES, slug, dearer)
    assert coins.rate_for(slug) == dearer, \
        "the slug's own entry must win over the model it wraps"
    assert coins.rate_for(direct) != dearer, "...and only for the slug"


# ------------------------------------------- the prompt is counted, not typed
#
# The whole reason this section exists: on 2026-08-31 `translate.sys_in` read
# 2,086 against a real 4,600, and lee's chapter was quoted 18% short because of
# it. The prompt had more than doubled while nobody was pricing it. These tests
# ask the PROMPT, never a constant, so the same thing cannot happen twice.

def test_the_counter_agrees_with_a_real_tokenizer():
    """The rule, against the numbers it was fitted to.

    Measured on lee's chapter with two independent tokenizers (o200k, and
    Claude's own published one). Written down as the strings themselves rather
    than as a token count, so this keeps checking the RULE rather than
    checking that a number equals itself.
    """
    # English prose: about four characters to a token, one and a quarter
    # tokens to a word.
    prose = ("The copy editor on a professional typesetting team polishes "
             "the script one page at a time, and fixes only what is wrong.")
    assert 0.85 < coins.tokens(prose) / (len(prose) / 4.0) < 1.25, \
        coins.tokens(prose)
    # Japanese: about ONE token a character, not a quarter of one. Four
    # characters to a token here would undercharge by more than three times,
    # on every page of every chapter this app was built for.
    ja = "これから本番、やっぱりグロウさんなんか嫌い、この地域の温泉には"
    assert coins.tokens(ja) > len(ja) * 0.8, coins.tokens(ja)
    assert coins.tokens(ja) > coins.tokens("x" * len(ja)) * 3
    # ...and nothing raises on the shapes a caller can really pass.
    for weird in ("", None, "   ", "{}", "\n\n", "♥★♪", "a" * 5000):
        assert coins.tokens(weird) >= 0


def test_the_system_prompts_are_counted_off_the_real_prompt():
    """Not read out of `SHAPES`. Each one is built here, counted here, and
    compared with what the price used - so an edit to a prompt moves the price
    in the same commit, with nobody having to remember."""
    from mangatl import translate as TR
    for step, build in (
            ("translate", lambda: TR.build_system("manga", "en", "", False)),
            ("proofread", lambda: TR.build_proofread_system("manga", "en", "")),
            ("ocr", lambda: TR.build_ocr_system(
                TR.source_language("manga", "")))):
        assert coins.sys_tokens(step) == coins.tokens(build()), step
    # ...and the one that was wrong is now right: the real prompt, counted, is
    # what the price uses.
    assert coins.sys_tokens("translate") > 4000


def test_a_longer_prompt_costs_more_the_moment_it_is_longer(monkeypatch):
    """The property the old constants could not have. Lengthen the prompt and
    the price moves, with no number anywhere to update."""
    from mangatl import translate as TR
    before = coins.usd_page("translate", 9, "gemini-3.6-flash")
    real = TR.build_system
    monkeypatch.setattr(TR, "build_system",
                        lambda *a, **k: real(*a, **k) + " and also " * 400)
    coins.sys_tokens.cache_clear()
    after = coins.usd_page("translate", 9, "gemini-3.6-flash")
    coins.sys_tokens.cache_clear()
    assert after > before, (before, after)


def test_a_build_that_cannot_read_the_prompt_still_has_a_price(monkeypatch):
    """The fallback, and the only thing the numbers in `SHAPES` are still for.

    A trimmed build, an import that is not there, a prompt builder that throws
    - the price must still come out, because a price that raises is a button
    nobody can press. A stale number beats no number.
    """
    def boom(*a, **k):
        raise ImportError("no translate in this build")

    monkeypatch.setitem(coins._SYS_BUILDERS, "translate", boom)
    coins.sys_tokens.cache_clear()
    try:
        assert coins.sys_tokens("translate") == \
            coins.SHAPES["translate"].sys_in
        assert coins.usd_page("translate", 9, PLAIN_CLAUDE) > 0
    finally:
        monkeypatch.undo()
        coins.sys_tokens.cache_clear()


# ------------------------------------- the reply follows the words, not the boxes

def test_a_long_line_costs_more_to_translate_than_a_short_one():
    """A box holding a sentence does not come back the size of a box holding
    one word, and a box count cannot see the difference. Measured over lee's
    23 pages, adding this took the reply's error from 20.6% to 2.3%."""
    short = coins.usd_page("translate", 9, PLAIN_CLAUDE, src_chars=20)
    long_ = coins.usd_page("translate", 9, PLAIN_CLAUDE, src_chars=900)
    assert long_ > short, (short, long_)
    sh, r = coins.SHAPES["translate"], coins.rate_for(PLAIN_CLAUDE)
    # ...by exactly the source-character term, at the output rate.
    assert long_ - short == pytest.approx(
        r.usd(tout=sh.per_src_char_out * (900 - 20)), abs=1e-9)


def test_a_page_nobody_has_read_yet_is_priced_at_the_average():
    """Zero source characters is not a free page - it is a page whose words
    are not known yet, which is every page before Find text has run. It falls
    back to what a box holds on average, which is what the price did before
    any of this existed."""
    unknown = coins.usd_page("translate", 9, PLAIN_CLAUDE, src_chars=0)
    average = coins.usd_page("translate", 9, PLAIN_CLAUDE,
                             src_chars=coins.SRC_CHARS_PER_BOX * 9)
    assert unknown == average > 0


def test_the_meter_line_records_the_words_as_well_as_the_boxes(tmp_path):
    """`drift` compares a real bill against a prediction, and the prediction
    now needs the source text. A meter line without it is compared against a
    different number than the quote used, and the correction it produces is
    the difference between two guesses."""
    from mangatl import editor
    p = _project(tmp_path, [9] * 4)
    editor._run_one(p, {"label": "Translating", "indices": list(range(4)),
                        "fn": lambda i: coins.record(900, 250, cached=4600),
                        "step": "translate"})
    line = coins.ledger()[0]
    assert line["kind"] == "meter"
    assert line["src"] == sum(editor.page_src_chars(p, i) for i in range(4))
    # ...and an OLD line, written before this existed, still reads: it falls
    # back to the same average the quote it is compared against used.
    assert coins.predicted("translate", 36, 4, 0, PLAIN_CLAUDE,
                           "anthropic", False, 0) == \
        coins.predicted("translate", 36, 4, 0, PLAIN_CLAUDE,
                        "anthropic", False,
                        coins.SRC_CHARS_PER_BOX * 36)


# ----------------------------------------- the reader sends PICTURES, and how
#
# The biggest single number in a read, and the one the estimate was most wrong
# about. `fixed_in` carried the page image as 1,747 tokens A PAGE; the reader
# sends one picture per BOX when it reads zoomed, so a ten-box page sends ten.
# Measured against 138 real runs off lee's own ledger the read was being
# charged at 0.28x of what it cost.

def test_a_read_is_priced_by_the_pictures_it_sends():
    """One a page, four, nine, or one per box - and the price follows,
    because the pictures ARE the cost of a read."""
    assert coins.pictures("page", 10) == 1
    assert coins.pictures("auto", 10) == 4
    assert coins.pictures("high", 10) == 9
    assert coins.pictures("boxes", 10) == 10
    # nothing chosen reads as zoomed, which is what the reader really does
    assert coins.pictures("", 10) == 10
    # ...and a mode nobody has heard of does not silently cost nothing
    assert coins.pictures("nonsense", 10) == 10


def test_reading_zoomed_costs_more_than_reading_the_whole_page():
    """The fact that brought the choice back onto the settings screen. lee:
    *"so teh ing increasing the price was teh zoom in images right?"* - it
    was, and on a ten-box page it is ten pictures against one."""
    whole = coins.usd_page("ocr", 10, "gemini-3.7-flash", "google",
                           detail="page")
    quarters = coins.usd_page("ocr", 10, "gemini-3.7-flash", "google",
                              detail="auto")
    zoomed = coins.usd_page("ocr", 10, "gemini-3.7-flash", "google",
                            detail="boxes")
    assert whole < quarters < zoomed, (whole, quarters, zoomed)
    # the difference really is the pictures, at the input rate
    r = coins.rate_for("gemini-3.7-flash", "google")
    step = coins.image_tokens("gemini-3.7-flash", "google")
    assert quarters - whole == pytest.approx(r.usd(tin=3 * step), abs=1e-9)
    assert zoomed - whole == pytest.approx(r.usd(tin=9 * step), abs=1e-9)


def test_a_picture_costs_what_its_provider_charges_for_one():
    """Google tiles an image into 768px squares at 258 tokens each, so a crop
    capped at `ocr.MAX_SIDE` is 3x3 = 2,322; Anthropic charges about width x
    height / 750. Measured off the ledger at 2,479 and 1,127 a picture."""
    assert coins.image_tokens("gemini-3.7-flash", "google") > \
        coins.image_tokens("claude-opus-5", "anthropic")
    # ...through the vendor prefix, or the same model bought through
    # OpenRouter is priced as an unknown
    assert coins.image_tokens("google/gemini-3.7-flash", "openrouter") == \
        coins.image_tokens("gemini-3.7-flash", "google")
    # a model you run yourself is not buying pictures from anybody
    assert coins.image_tokens("gemini-3.7-flash", "ollama") == 0
    # and only the reader sends any
    assert coins.SHAPES["ocr"].pictures is True
    for step in ("translate", "proofread", "label"):
        assert coins.SHAPES[step].pictures is False, step


def test_the_reader_and_the_price_read_one_list():
    """A mode the price has never heard of, or that means something different
    on each side, is a bill nobody can check."""
    from mangatl.ocr import DETAILS, detail_for
    assert set(DETAILS) == {"page", "auto", "high", "boxes"}
    for k in DETAILS:
        assert detail_for("manga", k) == k
    assert detail_for("manga") == "boxes"
    assert detail_for("manga", "nonsense") == "boxes"


# --------------------------------------------- and thinking is per box now

def test_thinking_is_priced_per_box_and_not_per_page():
    """Two runs on two model versions, thinking taken as what is left after
    the visible reply: per page they are 133 and 37 and agree about nothing;
    per box they are 15 and 19. A model reasons about the lines it was
    given."""
    sh = coins.SHAPES["translate"]
    two = coins.think_tokens(sh, "gemini-3.7-flash", "", 2)
    ten = coins.think_tokens(sh, "gemini-3.7-flash", "", 10)
    assert ten == pytest.approx(5 * two), (two, ten)
    assert two > 0
    # ...and a model that is never asked to think is charged nothing for it
    assert coins.think_tokens(sh, PLAIN_CLAUDE, "", 10) == 0
    # nor is one you run yourself
    assert coins.think_tokens(sh, "gemini-3.7-flash", "ollama", 10) == 0
    # an unpriced thinker still costs something rather than nothing
    assert coins.think_tokens(sh, "gemini-9-ultra", "", 10) > 0


def test_the_drift_clamp_can_say_what_the_meter_said():
    """It was (0.5, 2.0), and lee's own ledger said the reader was charging a
    third of its cost - a number that clamp cannot express, so the correction
    pinned itself and stayed wrong. Still tight upward, because charging MORE
    than the shape says is the direction that takes somebody's money."""
    lo, hi = coins.DRIFT_CLAMP
    assert lo <= 0.3, lo
    assert hi >= 2.0
    assert lo < 1.0 < hi
