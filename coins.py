"""TCT Coins — what a chapter costs and what is left to spend it with.

lee: *"i wan you to impiment a credit syste using coins $1 is 100 coins i want
you to make all the steps that use ai to cost coins aprpretly also bubble teh
coin cost so if something cost $1 make it cost 2 dollar in coins make teh coin
system be dynamic and per text box in a page so if a page has 1 0r 2 tet box it
shoiukd be cheaper than a page that has 5-6 text boxes, the clenning fee shud be
a flat fee per page"*.

Three rules, and everything here is one of them:

**A hundred coins is a dollar.** One number, `COINS_PER_DOLLAR`, and no price
anywhere is written in coins — every price in this file is a real dollar cost
that goes through `coins_for_usd`. A published rate that changes is one line.

**Every price is doubled.** `MARKUP`. The same one function does it, so there
is no step that quietly forgot to.

**A page costs what the page cost.** Not a flat rate per page: the model is
sent the boxes on THAT page, so a page with two boxes is a smaller bill than a
page with six, and it falls out of the token count rather than being a table
somebody has to keep in step with the prompts. A run's charge is the tokens the
provider actually reported, not an estimate — see `charging`. The estimate in
`quote_page` exists for the other job, which is telling you the price BEFORE
you press the button and refusing a run that cannot pay for itself.

Cleaning is the exception lee named: a flat fee per page, because it is a
picture through a hosted GPU and the boxes on the page do not change what it
costs.

A model you run yourself costs nothing, so it is charged nothing. Somebody
translating a chapter on their own Ollama is not being sold anything.

## The unit

**Whole coins, always rounded up.** lee: *"it shoud oporate on whoel numbers,
always round up"*. There is no fraction of a coin anywhere — not in the purse,
not in a price, not on the screen. A page that came to nine tenths of a coin
costs one, and a page that came to nothing costs nothing.

Rounding up is done ONCE, at the end of a page, not on every call the page
made: a page read in four tiles is four calls and one charge, and rounding each
of the four would charge for up to three coins of nothing. That is what `Bill`
is for — it carries the real cost as it goes and is only turned into coins when
the page is finished with.

Dollars appear in this file and nowhere else. They are how a provider's rate is
written down, and the moment a price leaves here it is coins.

## Where the purse is

Two, and the same six functions read both. Signed in, the balance is a number
in Firestore that only a Cloud Function may write, and every call here is a
request — see `account.py`. Signed out, or with no Firebase project configured
at all, it is `wallet.json` beside the fonts, exactly as it was.

The local purse is not a fallback for the remote one. If a spend cannot reach
the server it fails, and the run does not start: quietly charging a local
wallet instead would be giving the work away, and quietly not charging at all
would be worse. It is the purse for a checkout with no billing behind it —
somebody running this from source, which is the case this app started as.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import account, userdata

# ------------------------------------------------------------------ the unit

COINS_PER_DOLLAR = 100          # lee: *"$1 is 100 coins"*

# lee: *"bubble teh coin cost so if something cost $1 make it cost 2 dollar in
# coins"*. Nothing else in this file doubles anything; if this is 1 the app
# charges cost price, and that is the only thing that changes.
MARKUP = 2


def coins_for_usd(usd: float) -> int:
    """Real dollars -> whole coins, doubled and rounded UP.

    Up, not nearest: rounding down is not a rounding, it is a free tier for
    anybody who can arrange to land just under. Nothing that cost anything at
    all comes back as nothing — but a step that cost NOTHING (a model you run
    yourself, a page with no text on it) still comes back as nothing, which is
    why the ceiling is taken of the real number rather than a floor of one.
    """
    return int(math.ceil(max(0.0, float(usd)) * COINS_PER_DOLLAR * MARKUP))


def show(coins: int) -> str:
    """The number a person reads. Whole, because they all are."""
    return str(int(coins))


# --------------------------------------------------------------- what models cost

@dataclass(frozen=True)
class Rate:
    """USD per MILLION tokens, as the provider publishes it.

    `cache_read` and `cache_write` are what a cached input token costs instead
    of `inp` — Anthropic reads at a tenth and writes at a quarter over, Google
    reads at a quarter and charges nothing to write. `translate.py` marks the
    system prompt for the cache on every step, so leaving these out would price
    a cached chapter as if nothing were cached and charge for tokens nobody was
    billed for.
    """
    inp: float
    out: float
    cache_read: float = 0.0
    cache_write: float = 0.0

    def usd(self, tin: int = 0, tout: int = 0,
            cached: int = 0, written: int = 0) -> float:
        cr = self.cache_read if self.cache_read else self.inp
        cw = self.cache_write if self.cache_write else self.inp
        return (max(0, tin) * self.inp + max(0, tout) * self.out
                + max(0, cached) * cr + max(0, written) * cw) / 1e6


# Anthropic's cache reads at a tenth of input and writes at a quarter over, on
# every model; Google's reads at a tenth and costs nothing to write. Both are
# ratios their providers hold across the whole range, so they are written once
# here rather than nine times below — but the input and output prices are not
# ratios of anything, and every one of them is written out.
def _anthropic(inp: float, out: float) -> Rate:
    return Rate(inp, out, round(inp * 0.10, 4), round(inp * 1.25, 4))


def _google(inp: float, out: float) -> Rate:
    return Rate(inp, out, round(inp * 0.10, 4), 0.0)


# Every active Claude and Gemini model, at the price its provider publishes.
# lee: *"do price all teh claude and gemini active modeles"*.
#
# Matched by LONGEST PREFIX on the model id, so `claude-sonnet-5-20260514` and
# `claude-sonnet-5` price the same and a dated snapshot needs no entry of its
# own. USD per million tokens.
RATES: dict[str, Rate] = {
    # ---- Anthropic
    "claude-fable-5": _anthropic(10.0, 50.0),
    "claude-opus-5": _anthropic(5.0, 25.0),
    "claude-opus-4": _anthropic(15.0, 75.0),
    # The STANDING rate, not the promotional one Anthropic is running until the
    # end of August. lee: *"no promotianal rate us teh normal rate"* — and he
    # is right: a price that is a discount somebody else can withdraw is a
    # price that changes under you on a date you do not control, and every
    # quote given while it lasted would be a quote that has to go up.
    "claude-sonnet-5": _anthropic(3.0, 15.0),
    "claude-sonnet-4": _anthropic(3.0, 15.0),
    "claude-haiku-4-5": _anthropic(1.0, 5.0),
    "claude-haiku-4": _anthropic(1.0, 5.0),
    "claude-3-5-haiku": _anthropic(0.80, 4.0),
    "claude-3-haiku": _anthropic(0.25, 1.25),
    # ---- Google
    "gemini-3.6-flash": _google(1.50, 7.50),
    "gemini-3.5-flash-lite": _google(0.30, 2.50),
    "gemini-3.5-flash": _google(1.50, 9.00),
    "gemini-3.1-pro": _google(2.00, 12.00),
    "gemini-3.1-flash-lite": _google(0.25, 1.50),
    "gemini-3-pro": _google(2.00, 12.00),
    "gemini-3-flash": _google(0.50, 3.00),
    "gemini-2.5-pro": _google(1.25, 10.00),
    "gemini-2.5-flash-lite": _google(0.10, 0.40),
    "gemini-2.5-flash": _google(0.30, 2.50),
    "gemini-2.0-flash-lite": _google(0.075, 0.30),
    "gemini-2.0-flash": _google(0.10, 0.40),
    # ---- OpenRouter, which names a model by who makes it.
    #
    # These are written out rather than left to `vendor_free` for two of them
    # and to make a promise for the rest: OpenRouter does not mark tokens up,
    # so the slug's rate is the provider's own published rate and its money
    # comes off the top-up instead (5.5% on a card). A test holds each slug's
    # price equal to the direct one, so a rate change that misses one of the
    # two is caught rather than charged.
    #
    # The Anthropic slugs are the reason this list is not left to the prefix
    # matcher alone: they carry DOTS where the direct ids carry dashes
    # (`claude-haiku-4.5` against `claude-haiku-4-5`), so `claude-haiku-4.5`
    # matches the `claude-haiku-4` entry by prefix and prices right today by
    # luck. One price change and it would be wrong, and quiet.
    "google/gemini-2.5-flash-lite": _google(0.10, 0.40),
    "google/gemini-2.5-flash": _google(0.30, 2.50),
    "google/gemini-2.5-pro": _google(1.25, 10.00),
    "google/gemini-3.1-flash-lite": _google(0.25, 1.50),
    "google/gemini-3.5-flash": _google(1.50, 9.00),
    "google/gemini-3.6-flash": _google(1.50, 7.50),
    "anthropic/claude-haiku-4.5": _anthropic(1.0, 5.0),
    "anthropic/claude-sonnet-5": _anthropic(3.0, 15.0),
    "deepseek/deepseek-v4-flash": Rate(0.084, 0.168),
    "deepseek/deepseek-v3.2": Rate(0.2072, 0.3108),
    # ---- OpenAI, reached through the OpenAI-compatible route
    "gpt-4o-mini": Rate(0.15, 0.60),
    "gpt-4o": Rate(2.50, 10.0),
    "gpt-4.1-mini": Rate(0.40, 1.60),
    "gpt-4.1-nano": Rate(0.10, 0.40),
    "gpt-4.1": Rate(2.00, 8.00),
}

# A model nobody has priced. The DEAREST thing on the list, not the cheapest
# and not free: an unknown model that turns out to be the top of somebody's
# range and was charged as free is a bill this app eats, and an unknown model
# that was really cheap is a customer who can be refunded. Only one of those is
# recoverable. It is also said out loud on screen — see `priced`.
#
# The dearest rate on the list, and a test holds it there as models are added:
# a fallback that drifts under the top of the range is a discount for anything
# unrecognised, which is the wrong way for an unknown to fail.
UNKNOWN = _anthropic(15.0, 75.0)

# Backends that run on the person's own machine. Their own electricity, their
# own hardware, nothing bought from anyone — so nothing to charge for.
FREE_BACKENDS = ("ollama", "llamacpp", "llama.cpp", "lmstudio", "local",
                 "koboldcpp", "textgen", "vllm")


# Which provider each family of model ids belongs to. Used to offer a step the
# models it can actually reach — and, because this list IS the price table, to
# offer it only models the app can price. A dropdown that can put a step on a
# model nobody priced is a dropdown that quietly charges the top rate.
#
# Three services and no more. OpenAI, Groq, Cerebras and Ollama are gone: each
# was a menu with nothing behind it that anybody here had priced or tested, and
# an offer the app cannot stand behind is worse than no offer. `gpt-` rates
# stay in the table below — a project set up on one before today is still on
# disk, and an UNPRICED model is charged at the top of the range — but nothing
# offers one.
FAMILIES = {
    "anthropic": ("claude-",),
    "gemini": ("gemini-",),
    "openrouter": ("google/", "anthropic/", "deepseek/"),
}

# The models that cannot look at a picture. Reading text off a page is a vision
# job, so a menu that offers one of these for it is offering a 404 one step
# later — the same failure the whole crossing in `editor.model_menu` exists to
# stop, arriving through a different door.
# Matched with the vendor off, so the DeepSeek that arrives as
# `deepseek/deepseek-v4-flash` and the one that arrives bare are the same
# blind model.
NO_SIGHT = ("deepseek-",)


def sees(model: str) -> bool:
    """Can this model be shown a page?"""
    return not vendor_free(model).startswith(NO_SIGHT)


# Priced, because somebody may still have one configured and an old model
# nobody prices would be charged at the top rate — but not OFFERED. A menu of
# every model a provider ever shipped is a menu nobody can choose from.
RETIRED = frozenset({
    "claude-opus-4", "claude-sonnet-4", "claude-haiku-4",
    "claude-3-5-haiku", "claude-3-haiku",
    "gemini-2.0-flash", "gemini-2.0-flash-lite",
})


def models_for(backend: str) -> list:
    """The models this backend can run, best first.

    In the order the price table lists them, which is newest first — a menu
    sorted alphabetically opens on the oldest model in the range.

    Empty for a provider whose range is not in the table: Ollama, OpenRouter,
    anything local or odd. Those are asked what they have instead, and they
    cost nothing to run anyway.
    """
    pre = FAMILIES.get((backend or "").strip().lower())
    if not pre:
        return []
    return [k for k in RATES if k.startswith(pre) and k not in RETIRED]


def priced(model: str, backend: str = "") -> bool:
    """Is this model in the price list at all?

    Worth asking OUT LOUD, because an unpriced model is charged at the dearest
    rate on the list and that is an eightfold difference nobody would guess
    from looking at the number. The fallback is the right one — charging an
    unknown model as free is a bill this app eats — but it must not be silent.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return True
    m = (model or "").strip().lower()
    return (_prefix(m) or _prefix(vendor_free(m))) is not None


def vendor_free(m: str) -> str:
    """`anthropic/claude-sonnet-5` -> `claude-sonnet-5`. Anything else, itself.

    OpenRouter names a model by who makes it, so the same model has two ids
    depending on where it was bought. Every question this file answers about a
    model — what it costs, whether its cache can be asked for, whether it
    thinks — has the same answer for both, and each of them is matched by
    prefix. Without this they all quietly take the wrong branch: an unpriced
    model is charged at the top of the range, a marked cache is never priced,
    and a thinking model is quoted at a fifth of its bill. None of the three
    announces itself.

    Only ONE leading segment goes. `google/gemini-2.5-flash-lite` has no other
    slash in it, but cutting at the LAST one would leave `flash-lite` — and
    cutting nothing off `anthropic/claude-sonnet-5` leaves a name no table has.
    """
    m = (m or "").strip().lower()
    return m.split("/", 1)[1] if "/" in m else m


def _prefix(m: str):
    hit = ""
    for key in RATES:
        if m.startswith(key) and len(key) > len(hit):
            hit = key
    return RATES[hit] if hit else None


def rate_for(model: str, backend: str = "") -> Rate:
    """What one model's tokens cost. Longest prefix wins.

    The id is looked up WHOLE first and only then with the vendor stripped, so
    a namespaced slug that is priced in its own right — because OpenRouter
    charges something the direct provider does not — beats the general answer.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return Rate(0.0, 0.0)
    m = (model or "").strip().lower()
    return _prefix(m) or _prefix(vendor_free(m)) or UNKNOWN


# ------------------------------------------------------- what a page will cost

# What a page of each step really sends and gets back, so the price can be
# worked out before the button is pressed.
#
# This is the ESTIMATE, and it is used for two things: the price on the button,
# and refusing a run that cannot pay. What is CHARGED is this estimate too —
# the price is taken up front — so an estimate that drifts is not a cosmetic
# problem, it is the business either losing money or overcharging. What the run
# really cost is metered underneath and written to the ledger beside it, which
# is how the drift is caught.
@dataclass(frozen=True)
class Shape:
    sys_in: int          # the system prompt — identical on every page
    fixed_in: int        # per page and not cacheable: the page image, the JSON
    per_box_in: int      # the boxes on THIS page
    chapter_in: int      # every box of CONTEXT sent with this page
    per_box_out: int     # the visible reply — the words that reach the page
    fixed_out: int = 0
    # What the model spends THINKING, per page, charged only where `thinks`
    # says the model does. It is per PAGE and not per box on purpose: a model
    # given a two-box page and a model given a ten-box page do not reason a
    # fifth as hard for the smaller one. Smearing this across the boxes is
    # exactly the error it replaces — see the note above `SHAPES`.
    think_out: int = 0


# Anthropic's cache has to be asked for and only pays above this; below it the
# prompt is sent, and charged, in full. `translate._system_blocks` uses the
# same number and this has to agree with it or the estimate prices a cache
# that was never asked for. Not imported from there — that module imports THIS
# one, and a cycle to share an integer is a bad trade.
CACHE_MIN_TOKENS = 1024

# The providers whose cache this app actually gets. `_system_blocks` marks the
# system prompt for Anthropic and nobody else; Google's implicit caching is
# real but it is not something you can ask for, and it is not something the
# OpenAI-compatible endpoint this app reaches Gemini through is documented to
# do. Pricing a cache that does not happen undercharges by the whole of it,
# and undercharging is the failure that does not announce itself.
MARKS_CACHE = ("claude-",)

# The models that bill their reasoning back as output tokens on the calls this
# app makes. Gemini thinks by default and there is no way to ask it not to
# through the endpoint this app uses; Claude thinks only when a request turns
# it on, and no request here does.
#
# This is a fact about the MODEL, not about the provider, which is why it is
# matched on the id and read through the vendor prefix — `google/gemini-3.6-
# flash` bought through OpenRouter thinks exactly as much as the same model
# bought direct, and pricing it as though it did not quotes a Gemini chapter at
# a fraction of what it comes to.
THINKS = ("gemini-",)


def cached_tokens(shape: "Shape", model: str = "", backend: str = "") -> int:
    """How much of the system prompt is priced as a cache READ, not as input.

    Only where this app actually asks for a cache, which is Anthropic and
    nowhere else. Google's implicit caching is real and is not something you
    can ask for, and it is not documented on the OpenAI-compatible endpoint
    this app reaches Gemini through; pricing it here would undercharge by the
    whole of it on every Gemini chapter, and undercharging is the failure that
    does not announce itself.

    Read through the vendor prefix, or `anthropic/claude-sonnet-5` bought
    through OpenRouter never has its cache priced and the system prompt is
    quoted at full price on every page of every chapter.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return 0
    if shape.sys_in < CACHE_MIN_TOKENS:
        return 0
    return (shape.sys_in
            if vendor_free(model).startswith(MARKS_CACHE) else 0)


def thinks(model: str, backend: str = "") -> bool:
    """Does this model bill reasoning tokens back as output?

    Wrong in either direction is expensive: a thinking model quoted without it
    is quoted at a fifth of the bill, and a non-thinking one quoted with it is
    quoted at seven times.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return False
    return vendor_free((model or "").strip().lower()).startswith(THINKS)

# Measured against the real prompt builders — `build_system`, `build_payload`,
# `build_proofread_payload`, `_ocr_context` — at 2, 9 and 20 boxes a page, and
# checked against a real bill. lee, having run one chapter through Gemini 3.6
# Flash and read his Google invoice: *"before i had $0.502 of money spent and
# then i did the translation and now i have $1.032, so it cost $0.508 to
# translate the chapter"*.
#
# `chapter_in` is the context term, and it is charged for exactly the boxes
# `editor.run_context` really sends — no more. It used to be the biggest error
# in this file in BOTH directions: first missing altogether, then invented. A
# full-chapter run sends no context at all, and quoting it the whole chapter's
# boxes anyway put some hundred thousand imaginary input tokens on lee's
# twenty-three page bill.
#
# **The output figures are where the money actually is.** lee's real invoice
# for that chapter: 75,400 input and 44,870 output. Three quarters of the bill
# was output, and nine tenths of the output was the model THINKING — the
# visible reply, the words that reach the page, was about 6,000 tokens of it.
#
# So the two are split. `per_box_out` is the reply and scales with boxes;
# `think_out` is the reasoning, is per page, and is charged only where
# `thinks()` says the model does any. Written as one per-box number they were
# wrong twice over: a two-box page was quoted as thinking a fifth as hard as a
# ten-box page, and Claude — which is not asked to think anywhere in this app —
# was quoted at seven times its real output cost.
SHAPES: dict[str, Shape] = {
    # 552 of system prompt — under the cache floor, so it is paid for on every
    # page — plus 1,747 for the page image, which is different every page and
    # could not be cached anyway. The boxes cost nothing to SEND: the reader is
    # given a picture, not a list.
    "ocr": Shape(sys_in=552, fixed_in=1747, per_box_in=0, chapter_in=0,
                 per_box_out=60),
    # The big one. 2,158 of series context, ~870 of scaffolding, 43 a box for
    # the page itself — and 21 a box for the whole chapter, on every page.
    "translate": Shape(sys_in=2158, fixed_in=873, per_box_in=43, chapter_in=21,
                       per_box_out=28, think_out=1689),
    "proofread": Shape(sys_in=1355, fixed_in=607, per_box_in=58, chapter_in=0,
                       per_box_out=70),
}

# lee: *"the clenning fee shud be a flat fee per page"*. The cleaner is a
# hosted GPU and it is handed a picture; how many boxes are on it moves the
# seconds hardly at all, which is why this one is not per box like the rest.
# Roughly eight seconds of an A10G at Modal's published rate.
CLEAN_USD_PER_PAGE = 0.0035


def usd_page(step: str, boxes: int = 0, model: str = "",
             backend: str = "", chapter_boxes: int = 0) -> float:
    """What this page of this step really costs, in dollars. No rounding.

    `chapter_boxes` is the boxes of CONTEXT this page is sent — what
    `editor.run_context` really puts in the payload, and nothing else.

    **Nought means nought.** This used to read `max(boxes, chapter_boxes)`, so
    an explicit zero was quietly read as "well, this page's worth". A
    full-chapter run sends no context at all, and that one `max` put about a
    hundred thousand input tokens of pure invention on lee's twenty-three page
    quote. A default that overrides what the caller said is not a default.

    The rounding happens once, over a whole RUN — see `quote`. Rounding here
    would be rounding 23 times for a chapter and would flatten exactly the
    thing lee asked for: at a hundred coins to the dollar a single page of
    translation costs well under one coin, so a page with two boxes and a page
    with six both round to 1 and the per-box price disappears.

    A page with no text box costs nothing at all — there is nothing to send.
    That is not a special case bolted on, it is what the arithmetic says, and
    it matters because a chapter is full of splash pages.
    """
    if step == "clean":
        return CLEAN_USD_PER_PAGE
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0:
        return 0.0
    r = rate_for(model, backend)
    cached = cached_tokens(sh, model, backend)
    tin = (sh.fixed_in + sh.per_box_in * boxes
           + sh.chapter_in * max(0, int(chapter_boxes or 0))
           + (0 if cached else sh.sys_in))
    tout = sh.fixed_out + sh.per_box_out * boxes
    if thinks(model, backend):
        tout += sh.think_out
    # ...and then what the last few runs of this step on this model really
    # came to, against what this same shape predicted for them. Both are 1.0
    # on a fresh install, and stay 1.0 for as long as the shape is right.
    din, dout = drift(step, model, backend)
    return r.usd(tin=int(round(tin * din)), cached=int(round(cached * din)),
                 tout=int(round(tout * dout)))


# ------------------------------------------------- the estimate that learns
#
# `SHAPES` above was fitted to one chapter of one series on one model. A gag
# manga with three words a bubble and a dense fantasy webtoon do not cost the
# same per box, and no constant written here will ever know which one is on
# screen. The meter does: every run writes down what it really used beside what
# it was quoted, and `drift` reads them back.
#
# What this is NOT: a second price table. It is two numbers per step and model,
# input and output, and they multiply the shape. If the shape is right they are
# both 1.0 and nothing happens.

# How many runs back to look. Far enough that one strange chapter cannot own
# the answer, near enough that a series the person has stopped working on stops
# voting on the one they are working on now.
DRIFT_RUNS = 8

# A run smaller than this is noise: the fixed cost of a page swamps the boxes,
# so a one-page run's ratio says more about the page image than about the
# series. It is still METERED, it just does not get a vote.
DRIFT_MIN_BOXES = 20

# Nothing may more than double or more than halve the shape. One run against a
# provider having a bad day, one chapter of nothing but sound effects, and an
# unclamped correction would carry that into every quote after it. The clamp is
# the difference between an estimate that learns and an estimate that can be
# taught anything.
DRIFT_CLAMP = (0.5, 2.0)


def predicted(step: str, boxes: int, pages: int, ctx: int = 0,
              model: str = "", backend: str = "") -> tuple:
    """What the SHAPE says a run of this size sends and gets back.

    `(input, cached, output)` in tokens, uncorrected — this is the thing drift
    is measured against, so it must not have drift already in it.
    """
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0 or pages <= 0:
        return (0, 0, 0)
    cached = cached_tokens(sh, model, backend) * pages
    tin = (sh.fixed_in * pages + sh.per_box_in * boxes
           + sh.chapter_in * max(0, int(ctx or 0)) * pages
           + (0 if cached else sh.sys_in * pages))
    tout = sh.fixed_out * pages + sh.per_box_out * boxes
    if thinks(model, backend):
        tout += sh.think_out * pages
    return (tin, cached, tout)


def _clamp(x: float) -> float:
    lo, hi = DRIFT_CLAMP
    return max(lo, min(hi, float(x)))


def drift(step: str, model: str = "", backend: str = "") -> tuple:
    """`(input correction, output correction)` for this step on this model.

    Read off the meter lines the last few runs wrote. Both corrections are a
    SUM over runs and not an average of their ratios, so a forty-page run
    outweighs a one-page one — which is right, because the forty-page run is
    forty times as much evidence.

    **Cached tokens go on both sides.** They are input the provider charged
    less for, not input that did not happen. Counting them as real input while
    leaving them out of the prediction says every Claude run used 2.6x what was
    expected, for ever, and the correction pins itself to the clamp.

    A fresh install is `(1.0, 1.0)`: the table is the whole answer until the
    machine has said otherwise.
    """
    at = getattr(_STEADY, "at", None)
    key = (step, (model or "").strip().lower(), (backend or "").strip().lower())
    if at is not None and key in at:
        return at[key]
    got = _drift_uncached(*key)
    if at is not None:
        at[key] = got
    return got


def _drift_uncached(step: str, model: str, backend: str) -> tuple:
    rin = rout = pin = pout = 0
    seen = 0
    for e in ledger(400):
        if seen >= DRIFT_RUNS:
            break
        if e.get("kind") != "meter" or e.get("step") != step:
            continue
        if (e.get("model") or "").strip().lower() != model:
            continue
        boxes, pages = int(e.get("boxes") or 0), int(e.get("pages") or 0)
        if boxes < DRIFT_MIN_BOXES or pages <= 0:
            continue
        tin, cached, tout = predicted(step, boxes, pages,
                                      int(e.get("ctx") or 0), model,
                                      e.get("backend") or backend)
        if tin + cached <= 0 or tout <= 0:
            continue
        seen += 1
        pin += tin + cached
        pout += tout
        rin += int(e.get("tin") or 0) + int(e.get("cached") or 0)
        rout += int(e.get("tout") or 0)
    return (_clamp(rin / pin) if pin and rin else 1.0,
            _clamp(rout / pout) if pout and rout else 1.0)


_STEADY = threading.local()


@contextmanager
def steady():
    """Hold the corrections still for the length of a run.

    A run ENDS by writing a meter line. Without this, a run that is cancelled
    half way would have its refund priced against evidence its own charge never
    saw — the charge computed before the line existed, the refund after — and
    the two would not add back up. Whatever else is true of a price, what was
    taken and what was given back have to agree.

    Nested runs share the outer freeze, which is what you want: a step that
    calls another step is one purchase.
    """
    had = getattr(_STEADY, "at", None)
    if had is None:
        _STEADY.at = {}
    try:
        yield
    finally:
        if had is None:
            _STEADY.at = None


def quote(step: str, box_counts, model: str = "", backend: str = "",
          chapter_boxes: int = None) -> int:
    """Coins a whole run is expected to cost — one box count per page.

    Rounded up ONCE, over the run, because a run is what somebody presses a
    button to buy. lee: *"it shoud oporate on whoel numbers, always round
    up"*.

    `chapter_boxes` is the whole chapter's boxes and defaults to the pages
    being run. It is a separate argument because it really is a separate
    number: translating ONE page still sends the whole chapter as context, so
    "This page only" on a long chapter is not a twenty-third of the price.
    """
    counts = [int(n or 0) for n in (box_counts or [])]
    whole = sum(counts) if chapter_boxes is None else int(chapter_boxes)
    return coins_for_usd(sum(usd_page(step, n, model, backend, whole)
                             for n in counts))


def quote_page(step: str, boxes: int = 0, model: str = "",
               backend: str = "", chapter_boxes: int = None) -> int:
    """Coins ONE page of this step is expected to cost.

    A run of one. Used for the price beside "This page only" and for the check
    made before each page of a longer run — where erring high is right, since
    the alternative is starting a page the purse cannot finish.
    """
    return quote(step, [boxes], model, backend, chapter_boxes)


# --------------------------------------------------------------- the meter

@dataclass
class Bill:
    """What one page of one step has run up so far.

    It carries the REAL cost in dollars as it goes and only becomes coins when
    it is asked for them. That is the whole reason this class exists: prices
    round up, and a page read in four tiles is four calls and ONE charge. Round
    each call and a four-tile page pays for up to three coins of nothing.
    """
    step: str
    page: str = ""
    model: str = ""
    tin: int = 0
    tout: int = 0
    cached: int = 0
    written: int = 0
    usd: float = 0.0
    flat_coins: int = 0             # fees that were never tokens — see `flat`
    calls: int = 0

    @property
    def coins(self) -> int:
        return coins_for_usd(self.usd) + self.flat_coins

    def add(self, model: str, rate: Rate, tin: int, tout: int,
            cached: int, written: int) -> float:
        got = rate.usd(tin, tout, cached, written)
        self.model = self.model or model
        self.tin += tin
        self.tout += tout
        self.cached += cached
        self.written += written
        self.usd += got
        self.calls += 1
        return got


_LOCAL = threading.local()


@contextmanager
def charging(step: str, page: str = "", model: str = "", backend: str = ""):
    """Meter every model call made inside this block against one page.

    Nothing is debited here — `spend` is called by the caller once it knows
    whether there is anything to charge for. Two of these nested (a step that
    calls another step) keep their own bills and the inner one restores the
    outer, so a page is never billed twice for the same tokens.
    """
    bill = Bill(step=step, page=page, model=model)
    prev = getattr(_LOCAL, "bill", None)
    rate = getattr(_LOCAL, "rate", None)
    _LOCAL.bill = bill
    _LOCAL.rate = rate_for(model, backend)
    try:
        yield bill
    finally:
        _LOCAL.bill = prev
        _LOCAL.rate = rate


def record(tin: int, tout: int, cached: int = 0, written: int = 0,
           model: str = "") -> float:
    """One model call's usage. Called from the two places every AI step goes
    through — see `translate._ask` and `translate._ask_vision`. Returns the
    real cost it added, or 0 when nothing is metering.

    Real cost, not coins: this is one call, and the page it belongs to is what
    gets rounded up. See `Bill`.
    """
    bill = getattr(_LOCAL, "bill", None)
    if bill is None:
        return 0
    rate = getattr(_LOCAL, "rate", None) or rate_for(model or bill.model)
    return bill.add(model or bill.model, rate, int(tin or 0), int(tout or 0),
                    int(cached or 0), int(written or 0))


def flat(coins: int, what: str = "", page: str = "") -> int:
    """A charge that is not tokens — cleaning's flat fee per page.

    On the current bill when something is metering, straight out of the purse
    when nothing is. That second half is what lets the fee live at the one
    place a plate is actually BUILT, rather than at the four call sites that
    might reach it: a page cleaned on the way to an export costs the same as
    one cleaned by pressing Clean, and a page whose plate came out of the
    cache costs nothing, because nothing was built.

    It is already whole coins, so it goes on the bill BESIDE the tokens. Put
    back into dollars and added to them it would come to exactly the same
    number — ceil(x + n) is ceil(x) + n for a whole n — which is worth knowing
    and not worth relying on: the field says what it is.
    """
    coins = int(coins or 0)
    if coins <= 0:
        return 0
    bill = getattr(_LOCAL, "bill", None)
    if bill is None:
        return spend(coins, what or "clean", page)
    bill.flat_coins += coins
    bill.calls += 1
    return coins


def usage_of(resp) -> tuple:
    """(in, out, cached, cache-written) off a provider's reply.

    Two shapes: an Anthropic `Message` with a `usage` object, and the JSON dict
    an OpenAI-compatible endpoint returns. Anything else reports nothing rather
    than raising — a metering bug must not be able to fail a page.
    """
    try:
        u = resp.get("usage") if isinstance(resp, dict) else \
            getattr(resp, "usage", None)
        if u is None:
            return (0, 0, 0, 0)

        def g(*names):
            for n in names:
                v = u.get(n) if isinstance(u, dict) else getattr(u, n, None)
                if v:
                    return int(v)
            return 0

        # Anthropic reports the three input kinds SEPARATELY — `input_tokens`
        # excludes what was read from or written to the cache. OpenAI-shaped
        # replies report one total, and the cached part inside a details
        # object, so it has to come back OUT of the total or it is paid for
        # twice at two different rates.
        cached = g("cache_read_input_tokens")
        written = g("cache_creation_input_tokens")
        tin = g("input_tokens", "prompt_tokens")
        tout = g("output_tokens", "completion_tokens")
        if not cached and isinstance(u, dict):
            det = u.get("prompt_tokens_details") or {}
            if isinstance(det, dict):
                cached = int(det.get("cached_tokens") or 0)
                tin = max(0, tin - cached)
        return (tin, tout, cached, written)
    except Exception:
        return (0, 0, 0, 0)


def meter(resp, model: str = "") -> float:
    """`record` straight off a provider reply. The one line a call site adds."""
    tin, tout, cached, written = usage_of(resp)
    if not (tin or tout or cached or written):
        return 0
    return record(tin, tout, cached, written, model)


# ----------------------------------------------------------------- the purse

WALLET = "wallet.json"

# Where the Buy coins button goes. Not a payment form inside the editor: the
# editor is a thing somebody runs on their own machine, and a card number does
# not belong in it. lee: *"just have a buy coin button that will link to oa
# page on the website"*.
BUY_URL = "https://mangatct.com/coins"

# What a new install starts with. Enough to translate a chapter and see what
# the thing does before being asked for anything — a wallet that opens empty
# means the first button anybody presses refuses, which reads as broken rather
# than as priced.
WELCOME = 1000

# The ledger is the receipt, not an audit log. Long enough to answer "what did
# that chapter cost me", short enough that reading the file is instant.
LEDGER_MAX = 400

_LOCK = threading.RLock()


def _path() -> str:
    return os.path.join(userdata.user_dir(), WALLET)


def _read() -> dict:
    try:
        with open(_path(), encoding="utf8") as fh:
            got = json.load(fh)
        if isinstance(got, dict) and isinstance(got.get("balance"), int):
            got.setdefault("ledger", [])
            return got
    except Exception:
        pass
    return {"balance": WELCOME, "ledger": [
        {"at": int(time.time()), "kind": "credit", "what": "welcome",
         "coins": WELCOME}]}


def _write(w: dict) -> None:
    d = userdata.user_dir()
    try:
        os.makedirs(d, exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf8") as fh:
            json.dump(w, fh, indent=1)
        os.replace(tmp, _path())
    except OSError:
        pass


def remote() -> bool:
    """True when the purse is the account's rather than this machine's.

    Asked before every read and every spend rather than decided once at start
    up, because somebody can sign in while the editor is open and the next
    thing they press should come off the account they just signed into.
    """
    return account.signed_in()


def balance() -> int:
    """Coins in the purse."""
    if remote():
        return account.balance()
    with _LOCK:
        return int(_read().get("balance") or 0)


def ledger(n: int = 60) -> list:
    """Most recent first. The receipt — kept on disk so "what did that chapter
    cost me" has an answer, and not shown on the coin panel: lee asked for the
    count and the prices there and nothing else."""
    if remote():
        # The account's receipt lives on the website, where it can be read
        # from any machine. This one is still the local file's, which is what
        # was spent before signing in.
        return []
    with _LOCK:
        return list(reversed((_read().get("ledger") or [])[-n:]))


def _entry(w: dict, **kw) -> None:
    w.setdefault("ledger", []).append(dict(at=int(time.time()), **kw))
    del w["ledger"][:-LEDGER_MAX]


def credit(coins: int, what: str = "top-up", run: str = "") -> int:
    """Put coins in. Returns the new balance.

    On an account this is only ever a REFUND — pages that were paid for and
    then not run. There is no other way in from here, and there must not be:
    a client that could add coins to its own balance is a client that could
    add any number of them. Buying is the website's job, through Stripe.
    """
    coins = int(coins)
    if coins <= 0:
        return balance()
    if remote():
        if not run:
            raise account.AccountError(
                "Coins are bought on the website.", "no-minting")
        account.refund(coins, run)
        return account.balance()
    with _LOCK:
        w = _read()
        w["balance"] = int(w.get("balance") or 0) + coins
        _entry(w, kind="credit", what=what, coins=coins)
        _write(w)
        return w["balance"]


def new_run() -> str:
    """An id for one run of one step, made before the coins are taken.

    It matters on an account and costs nothing on a local wallet: a spend that
    times out on the wire may well have arrived, and the retry carrying the
    same id is charged once. The refund quotes it too, so a run can never give
    back more than it took.
    """
    return account.new_run()


def can_afford(coins: int) -> bool:
    if remote():
        # Asked fresh. Everywhere else a few seconds of staleness costs
        # nothing; here it is the difference between refusing a run that could
        # have paid and starting one that cannot.
        try:
            return account.balance(fresh=True) >= int(coins or 0)
        except account.AccountError:
            return False
    return balance() >= int(coins or 0)


def spend(bill: "Bill | int", what: str = "", page: str = "",
          model: str = "", run: str = "") -> int:
    """Take a bill out of the purse. Returns the coins taken.

    It goes through even when it takes the balance below zero, and that is on
    purpose: this is called AFTER the tokens were bought, so the money is gone
    whatever the purse says. Refusing the entry would not un-spend it, it would
    only lose the record of it. Not being able to START a run that cannot pay
    is what keeps the balance positive, and that is `can_afford`, asked before
    a page rather than after it.
    """
    if isinstance(bill, Bill):
        coins, what = bill.coins, what or bill.step
        page, model = page or bill.page, model or bill.model
        extra = dict(tin=bill.tin, tout=bill.tout, cached=bill.cached,
                     calls=bill.calls)
    else:
        coins, extra = int(bill or 0), {}
    if coins <= 0:
        return 0
    if remote():
        # `run` is what makes this happen once. A request that times out may
        # well have arrived, and the retry carries the same id.
        return account.spend(coins, what or "ai", page, run or account.new_run())
    with _LOCK:
        w = _read()
        w["balance"] = int(w.get("balance") or 0) - coins
        _entry(w, kind="spend", what=what or "ai", page=page, model=model,
               coins=coins, **extra)
        _write(w)
        return coins


def note(what: str, page: str = "", model: str = "", **facts) -> None:
    """A ledger line that moves no money.

    What a run really cost, written beside what it was charged. Nobody is
    billed on it — the quote is the price — but a quote drifting away from the
    truth is the one thing that would quietly turn this from a business into a
    subsidy, and it can only be seen if it is written down.
    """
    # Local even on an account. Nothing is billed on it, so there is nothing
    # to send: the account's ledger records what was CHARGED, and what a run
    # really cost is a question about this machine's calls.
    with _LOCK:
        w = _read()
        _entry(w, kind="meter", what=what, page=page, model=model, **facts)
        _write(w)


def state() -> dict:
    """Everything the screen needs, in one read.

    No dollars. lee: *"remove teh real money comarasion"* — a coin is the unit
    the app is priced in, and putting a currency beside it invites the question
    of which currency, in which country, at today's rate. `where coins come
    from` is a link, not an exchange rate.
    """
    if remote():
        got = account.state()
        got["buy_url"] = BUY_URL
        return got
    with _LOCK:
        return {"balance": int(_read().get("balance") or 0),
                "buy_url": BUY_URL,
                "configured": account.configured(), "signed_in": False}


# ------------------------------------------------------------- from the shell

def _main(argv=None) -> int:
    """`python -m mangatl.coins` — read the purse, and put coins in it.

        python -m mangatl.coins                 what is in it
        python -m mangatl.coins add 5000        put 5000 in
        python -m mangatl.coins ledger          the last 20 lines of the receipt

    Deliberately not a button. Until there is a Firebase account behind the
    balance and a Stripe checkout in front of it, SOMETHING has to be able to
    put coins in or the person who wrote the app locks himself out of it — and
    that something should be a command you have to know about, on the machine
    the wallet lives on, rather than a control on a screen that will one day be
    a customer's.
    """
    import argparse
    ap = argparse.ArgumentParser(prog="python -m mangatl.coins",
                                 description="TCT Coins.")
    ap.add_argument("what", nargs="?", default="balance",
                    choices=("balance", "add", "ledger", "accuracy"))
    ap.add_argument("coins", nargs="?", type=int, default=0)
    a = ap.parse_args(argv)
    if a.what == "add":
        if a.coins <= 0:
            ap.error("how many coins? e.g. `add 5000`")
        print("%s TCT Coins" % show(credit(a.coins, "added from the shell")))
        return 0
    if a.what == "ledger":
        for e in ledger(20):
            print("%+8s  %-28s %s" % (
                ("+%d" % e["coins"]) if e.get("kind") == "credit"
                else ("-%d" % e["coins"]) if e.get("kind") == "spend"
                else str(e.get("coins", "")),
                e.get("what", ""), e.get("page", "")))
        return 0
    if a.what == "accuracy":
        return _accuracy()
    print("%s TCT Coins" % show(balance()))
    return 0


def _accuracy() -> int:
    """What the runs on this machine say about the estimate.

    Per step and model: how many runs voted, how big they were, what was
    charged against what it really came to, and the two corrections the next
    quote will use. A correction sitting on a clamp is the thing to look for —
    it means the shape is wrong by more than this is allowed to fix.
    """
    runs = {}
    for e in ledger(400):
        if e.get("kind") != "meter" or not e.get("step"):
            continue
        runs.setdefault((e["step"], e.get("model") or ""), []).append(e)
    if not runs:
        print("No runs metered yet — the table is the whole answer.")
        return 0
    print("%-11s %-24s %5s %6s %9s %9s %6s %6s"
          % ("step", "model", "runs", "boxes", "charged", "really", "in", "out"))
    for (step, model), es in sorted(runs.items()):
        din, dout = drift(step, model, es[0].get("backend") or "")
        print("%-11s %-24s %5d %6d %9d %9d %6.2f %6.2f"
              % (step, model[:24], len(es),
                 sum(int(e.get("boxes") or 0) for e in es),
                 sum(int(e.get("charged") or 0) for e in es),
                 sum(int(e.get("coins") or 0) for e in es), din, dout))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
