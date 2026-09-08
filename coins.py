"""TCT Coins - what a chapter costs and what is left to spend it with.

lee: *"i wan you to impiment a credit syste using coins $1 is 100 coins i want
you to make all the steps that use ai to cost coins aprpretly also bubble teh
coin cost so if something cost $1 make it cost 2 dollar in coins make teh coin
system be dynamic and per text box in a page so if a page has 1 0r 2 tet box it
shoiukd be cheaper than a page that has 5-6 text boxes, the clenning fee shud be
a flat fee per page"*.

Three rules, and everything here is one of them:

**A hundred coins is a dollar.** One number, `COINS_PER_DOLLAR`, and no price
anywhere is written in coins - every price in this file is a real dollar cost
that goes through `coins_for_usd`. A published rate that changes is one line.

**Every price is doubled.** `MARKUP`. The same one function does it, so there
is no step that quietly forgot to.

**A page costs what the page cost.** Not a flat rate per page: the model is
sent the boxes on THAT page, so a page with two boxes is a smaller bill than a
page with six, and it falls out of the token count rather than being a table
somebody has to keep in step with the prompts. A run's charge is the tokens the
provider actually reported, not an estimate - see `charging`. The estimate in
`quote_page` exists for the other job, which is telling you the price BEFORE
you press the button and refusing a run that cannot pay for itself.

Cleaning is the exception lee named: a flat fee per page, because it is a
picture through a hosted GPU and the boxes on the page do not change what it
costs.

A model you run yourself costs nothing, so it is charged nothing. Somebody
translating a chapter on their own Ollama is not being sold anything.

## The unit

**Whole coins, always rounded up.** lee: *"it shoud oporate on whoel numbers,
always round up"*. There is no fraction of a coin anywhere - not in the purse,
not in a price, not on the screen. A page that came to nine tenths of a coin
costs one, and a page that came to nothing costs nothing.

Rounding up is done ONCE, at the end of a page, not on every call the page
made: a page read in four tiles is four calls and one charge, and rounding each
of the four would charge for up to three coins of nothing. That is what `Bill`
is for - it carries the real cost as it goes and is only turned into coins when
the page is finished with.

Dollars appear in this file and nowhere else. They are how a provider's rate is
written down, and the moment a price leaves here it is coins.

## Where the purse is

Two, and the same six functions read both. Signed in, the balance is a number
in Firestore that only a Cloud Function may write, and every call here is a
request - see `account.py`. Signed out, or with no Firebase project configured
at all, it is `wallet.json` beside the fonts, exactly as it was.

The local purse is not a fallback for the remote one. If a spend cannot reach
the server it fails, and the run does not start: quietly charging a local
wallet instead would be giving the work away, and quietly not charging at all
would be worse. It is the purse for a checkout with no billing behind it -
somebody running this from source, which is the case this app started as.
"""
from __future__ import annotations

import json
import math
import re
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from . import account, userdata

# ------------------------------------------------------------------ the unit

COINS_PER_DOLLAR = 100          # lee: *"$1 is 100 coins"*

# lee: *"bubble teh coin cost so if something cost $1 make it cost 2 dollar in
# coins"*. Nothing else in this file doubles anything; if this is 1 the app
# charges cost price, and that is the only thing that changes.
MARKUP = 2


# How much MORE than the estimate is held while a run is in flight, so the
# run cannot outrun its own purse. Measured, not chosen: over lee's 23 real
# pages the reply predictor's real/predicted ratio ran to a p99 of 1.066 and
# a maximum of 1.074 (see "Pricing the translate button", 2026-08-31), so a
# quarter of headroom covers every page seen with room to spare. The
# difference comes back at settle time - the hold is a hold, not a price.
HOLD = 1.25


def hold(price: int) -> int:
    """Coins to HOLD for a run quoted at `price` - the estimate plus the
    measured headroom, whole coins, rounded up. What is held and not used
    is returned when the run settles (`editor._charge`)."""
    price = int(price or 0)
    if price <= 0:
        return 0
    return int(math.ceil(price * HOLD))


def coins_for_usd(usd: float) -> int:
    """Real dollars -> whole coins, doubled and rounded UP.

    Up, not nearest: rounding down is not a rounding, it is a free tier for
    anybody who can arrange to land just under. Nothing that cost anything at
    all comes back as nothing - but a step that cost NOTHING (a model you run
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
    of `inp` - Anthropic reads at a tenth and writes at a quarter over, Google
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
# here rather than nine times below - but the input and output prices are not
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
    # end of August. lee: *"no promotianal rate us teh normal rate"* - and he
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
    #
    # 3.7 Flash at $1.50/$7.50, which is the rate from 1 January 2027 and NOT
    # the $0.75/$3.75 Google is running until the end of 2026. Same call as
    # the Anthropic one above and lee's own rule: *"no promotianal rate us teh
    # normal rate"*. A discount somebody else can withdraw is a price that
    # changes under you on a date you do not control.
    #
    # It costs what 3.6 Flash costs, so `one_per_price` keeps only one of the
    # two - and because the table is read newest-first, the one it keeps is
    # 3.7. That is the rule working, not a model going missing: 3.6 stays
    # priced for anybody already set on it.
    #
    # ...and 3.8 Flash (September 2026) arrives on exactly the same terms:
    # $0.75/$3.75 until the last day of 2026 and double that from 1 January
    # 2027, which is the number written here. lee: *"google realseased 3.8
    # flash, keep 3.7 and add 3.8 as anouther option"* - so all three sit in
    # the table at one rate, and the menu offers the newest of them while the
    # other two stay priced for anybody already set on one.
    "gemini-3.8-flash": _google(1.50, 7.50),
    "gemini-3.7-flash": _google(1.50, 7.50),
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
    # 3.7 before 3.6, and the ONE place in this block where the order carries
    # a decision: they cost the same, so `one_per_price` keeps whichever it
    # meets first. Everything else in the group has a price of its own and
    # sits in whatever order it was added in.
    "google/gemini-3.8-flash": _google(1.50, 7.50),
    "google/gemini-3.7-flash": _google(1.50, 7.50),
    "google/gemini-3.6-flash": _google(1.50, 7.50),
    "anthropic/claude-haiku-4.5": _anthropic(1.0, 5.0),
    "anthropic/claude-sonnet-5": _anthropic(3.0, 15.0),
    "deepseek/deepseek-v4-flash": Rate(0.084, 0.168),
    "deepseek/deepseek-v3.2": Rate(0.2072, 0.3108),
    # OpenAI's current generation, reached the same way. The three 5.6 tiers
    # and no more: Sol is the flagship, Terra the workhorse, Luna the cheap
    # one, and every Pro variant costs the same as its plain sibling for a
    # difference this app cannot use.
    "openai/gpt-5.6-sol": Rate(5.00, 30.00),
    "openai/gpt-5.6-terra": Rate(1.00, 6.00),
    "openai/gpt-5.6-luna": Rate(0.10, 0.60),
    # ...and Qwen, which is the cheapest sighted model on the menu by an
    # order of magnitude - 3.7 Flash reads a page for a fortieth of what
    # Gemini's cheapest asks.
    "qwen/qwen3.7-max": Rate(1.475, 4.425),
    "qwen/qwen3.7-plus": Rate(0.32, 1.28),
    "qwen/qwen3.7-flash": Rate(0.03, 0.13),
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
# recoverable. It is also said out loud on screen - see `priced`.
#
# The dearest rate on the list, and a test holds it there as models are added:
# a fallback that drifts under the top of the range is a discount for anything
# unrecognised, which is the wrong way for an unknown to fail.
UNKNOWN = _anthropic(15.0, 75.0)

# Backends that run on the person's own machine. Their own electricity, their
# own hardware, nothing bought from anyone - so nothing to charge for.
FREE_BACKENDS = ("ollama", "llamacpp", "llama.cpp", "lmstudio", "local",
                 "koboldcpp", "textgen", "vllm")


# Which provider each family of model ids belongs to. Used to offer a step the
# models it can actually reach - and, because this list IS the price table, to
# offer it only models the app can price. A dropdown that can put a step on a
# model nobody priced is a dropdown that quietly charges the top rate.
#
# Three services and no more. OpenAI, Groq, Cerebras and Ollama are gone: each
# was a menu with nothing behind it that anybody here had priced or tested, and
# an offer the app cannot stand behind is worse than no offer. `gpt-` rates
# stay in the table below - a project set up on one before today is still on
# disk, and an UNPRICED model is charged at the top of the range - but nothing
# offers one.
FAMILIES = {
    "anthropic": ("claude-",),
    "gemini": ("gemini-",),
    "openrouter": ("google/", "anthropic/", "deepseek/", "openai/", "qwen/"),
}

# The models that cannot look at a picture. Reading text off a page is a vision
# job, so a menu that offers one of these for it is offering a 404 one step
# later - the same failure the whole crossing in `editor.model_menu` exists to
# stop, arriving through a different door.
# Matched with the vendor off, so the DeepSeek that arrives as
# `deepseek/deepseek-v4-flash` and the one that arrives bare are the same
# blind model.
# ...and Qwen is the reason this list can no longer be one prefix per maker.
# Its range is MIXED: 3.7 Flash and 3.7 Plus are vision-language models and
# read a page perfectly well, while 3.7 Max is text-only. So the blind one is
# named on its own, and the sighted ones are simply absent.
#
# lee: *"make sure only taht suport iage eai show up in the red etx list"*.
# The cost is asymmetric and decides which way an uncertain model goes: a
# sighted model wrongly listed here loses one row from the Read text menu and
# still translates, while a blind one left out is a chapter that dies on page
# one. Uncertain means blind.
NO_SIGHT = ("deepseek-", "qwen3.7-max")


def sees(model: str) -> bool:
    """Can this model be shown a page?"""
    return not vendor_free(model).startswith(NO_SIGHT)


# Priced, because somebody may still have one configured and an old model
# nobody prices would be charged at the top rate - but not OFFERED. A menu of
# every model a provider ever shipped is a menu nobody can choose from.
RETIRED = frozenset({
    "claude-opus-4", "claude-sonnet-4", "claude-haiku-4",
    "claude-3-5-haiku", "claude-3-haiku",
    "gemini-2.0-flash", "gemini-2.0-flash-lite",
    # The GPT-4 family. lee named it as an example of what is too old to be
    # worth offering - *"dont go for models taht are too old i generation
    # behind shiud be teh limit like gpt 4, gmeini 2 etc"* - and the
    # generation rule below cannot see it, because there is no GPT-5 in this
    # table for it to be a generation behind OF. Written down instead of
    # inferred, which is what this set is for.
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
})


#: Which models each row of the "AI company" menu stands for.
#:
#: The menu names MAKERS - lee: *"sinatsd of otrher it shodu be open deepsek
#: quwen etc"* - and the price table names MODELS, so something has to join
#: the two. It lives here, next to the table it reads, because `blind_makers`
#: below is the answer it exists to give and that answer has to move when a
#: row is added to `RATES`.
#:
#: Both spellings of a maker are listed: OpenRouter prefixes a model with who
#: made it and the direct services do not, so `claude-opus-5` and
#: `anthropic/claude-opus-5` are one maker with two ids.
MAKER_MODELS = {
    "claude": ("claude-", "anthropic/"),
    "google": ("gemini-", "google/"),
    "openai": ("gpt-", "openai/"),
    "deepseek": ("deepseek-", "deepseek/"),
    "qwen": ("qwen", "qwen/"),
}


def blind_makers() -> list:
    """The makers with nothing in the table that can be shown a page.

    Read text hands the model a picture. A maker whose whole range is
    text-only therefore has no model to offer for that step, and putting it
    on the menu anyway is a choice that lands on "No models - check the key
    for this service" one click later: it reads as a broken key rather than
    as a maker that does not do this job. lee, at a Read text menu offering
    DeepSeek: *"for thsi only visin caplabel models hsoud show up"*.

    Translate and proofread are text jobs and keep every maker - this is
    asked of the ocr step alone, the same way `offered` asks `sees`.

    Read off `sees` rather than written down, so `NO_SIGHT` stays the one
    place that says which models are blind. A maker lands here only when
    EVERY model it still offers fails, which is why Qwen does not: 3.7 Max is
    text-only, and 3.7 Flash and Plus read a page perfectly well.
    """
    out = []
    for maker, pre in MAKER_MODELS.items():
        mine = [m for m in RATES
                if m.startswith(pre) and vendor_free(m) not in RETIRED]
        if mine and not any(sees(m) for m in mine):
            out.append(maker)
    return sorted(out)


# ------------------------------------------------- what a menu may offer
#
# Three rules, and all three are about the same thing: a menu is a promise
# that what is in it can be chosen. Everything they exclude stays PRICED -
# somebody may have it set already, and an unpriced model is charged at the
# top of the range - it is simply not offered to somebody choosing afresh.

# A provider's model list is not a list of translators. Google's carries
# text-to-speech, native audio, image generation and embedding models, all of
# which answer `GET /models` and none of which can be handed a page and asked
# for JSON. lee, with a screenshot of a menu holding
# `gemini-2.5-flash-preview-tts`: *"only keep the models that my api can
# aculy use"*.
#
# Matched as WORDS between dashes, not as substrings: `image` must not strike
# out a model whose name merely contains those letters, and this list is going
# to grow.
NOT_A_TRANSLATOR = frozenset({
    "tts", "audio", "image", "imagen", "veo", "sora", "embed", "embedding",
    "embeddings", "rerank", "reranker", "moderation", "guard", "whisper",
    "realtime", "live", "speech", "transcribe", "customtools", "computer",
})
# "vision" is deliberately NOT in that set. A vision model is the one thing
# Read text cannot do without.

# ...and the ones that are translators but are not a thing to point a chapter
# at. A preview is withdrawn without notice, which is the 404 this whole menu
# exists to prevent, and an experiment is a preview that says so.
NOT_SETTLED = frozenset({"preview", "exp", "experimental", "beta", "alpha"})


def usable_model(model: str) -> bool:
    """Can this id be handed a page and asked for a translation?

    Answered off the NAME, because the name is all a listing gives. That is a
    heuristic and it is allowed to be: the cost of striking out a good model
    is one absent row in a menu that has others, and the cost of keeping a
    bad one is a chapter that dies on page one.
    """
    parts = set(re.split(r"[-_./]", vendor_free(model)))
    return not (parts & NOT_A_TRANSLATOR) and not (parts & NOT_SETTLED)


def _version(model: str) -> tuple:
    """(family, major, minor) - or None where there is no version to read.

    `gemini-3.6-flash` -> ("gemini", 3, 6). `claude-haiku-4-5` -> ("claude",
    4, 5). `claude-sonnet-5` -> ("claude", 5, 0).
    """
    m = vendor_free(model)
    fam = m.split("-", 1)[0]
    v = re.search(r"(?:^|-)(\d+)(?:[.-](\d+))?(?=$|[-.])", m[len(fam):])
    if not v:
        return None
    return (fam, int(v.group(1)), int(v.group(2) or 0))


def current_enough(model: str) -> bool:
    """Is this model within one generation of the newest of its family?

    lee: *"dont go for models taht are too old i generation behind shiud be
    teh limit"*. Read against the price table rather than against a date: the
    table is the thing that gets updated when a range moves, so this cannot
    drift out of step with it.

    "One behind" is the whole of the newest major, plus the LAST minor of the
    one before it - Gemini keeps 3.x and 2.5 and drops 2.0, which is the line
    lee drew. A family with only one major in the table keeps all of it.
    """
    v = _version(model)
    if v is None:
        return True                      # nothing to compare; do not guess
    fam, major, minor = v
    seen = [x for x in (_version(k) for k in RATES) if x and x[0] == fam]
    if not seen:
        return True
    top = max(x[1] for x in seen)
    if major >= top:
        return True
    if major != top - 1:
        return False
    return minor >= max(x[2] for x in seen if x[1] == major)


def offered(backend: str, step: str = "") -> list:
    """The menu this app would show for a service if it could not ask it.

    The written-down catalogue with all three menu rules applied, in one
    place, so the fallback in `editor.model_menu` and every test that says
    what a menu holds are reading the same answer. Two copies of this
    arithmetic is two answers to "what is on the menu".
    """
    out = [m for m in models_for(backend)
           if usable_model(m) and current_enough(m)
           and (step != "ocr" or sees(m))]
    return one_per_price(out)


#: Offered even when something else already holds their price.
#:
#: The one-per-price rule below is right almost everywhere and wrong when the
#: two models are the SAME line a generation apart: then the price says they
#: are one choice and the person knows they are not. Google shipped 3.8 Flash
#: at 3.7 Flash's exact rate in September 2026 and lee wanted the pair, not
#: the newer one: *"google realseased 3.8 flash, keep 3.7 and add 3.8 as
#: anouther option"*.
#:
#: Written out rather than derived, because "same line, one generation apart"
#: is a guess about names and this is a decision about a menu. A model listed
#: here still has to be reachable, priceable, current and (for Read text)
#: able to see - it is exempt from the duplicate-price trim and from nothing
#: else.
ALWAYS_OFFERED = frozenset({"gemini-3.7-flash"})


def one_per_price(models) -> list:
    """Two models at the SAME rate are one choice with two names.

    `gemini-2.5-flash` and `gemini-3.5-flash-lite` cost exactly the same, and
    a menu that offers both is asking somebody to decide something that has no
    consequence they can see. The FIRST of each rate wins, and the caller
    hands them in newest-first, so what survives is the newest model at each
    price.

    ...except the few in `ALWAYS_OFFERED`, which are a deliberate second
    choice at a price already taken.

    Order is preserved, so this can be dropped into a list that has already
    been sorted.
    """
    out, seen = [], set()
    for m in models:
        r = rate_for(m)
        k = (r.inp, r.out, r.cache_read, r.cache_write)
        if k in seen and vendor_free(m) not in ALWAYS_OFFERED:
            continue
        seen.add(k)
        out.append(m)
    return out


def models_for(backend: str) -> list:
    """The models this backend can run, best first.

    In the order the price table lists them, which is newest first - a menu
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
    from looking at the number. The fallback is the right one - charging an
    unknown model as free is a bill this app eats - but it must not be silent.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return True
    m = (model or "").strip().lower()
    return (_prefix(m) or _prefix(vendor_free(m))) is not None


def vendor_free(m: str) -> str:
    """`anthropic/claude-sonnet-5` -> `claude-sonnet-5`. Anything else, itself.

    OpenRouter names a model by who makes it, so the same model has two ids
    depending on where it was bought. Every question this file answers about a
    model - what it costs, whether its cache can be asked for, whether it
    thinks - has the same answer for both, and each of them is matched by
    prefix. Without this they all quietly take the wrong branch: an unpriced
    model is charged at the top of the range, a marked cache is never priced,
    and a thinking model is quoted at a fifth of its bill. None of the three
    announces itself.

    Only ONE leading segment goes. `google/gemini-2.5-flash-lite` has no other
    slash in it, but cutting at the LAST one would leave `flash-lite` - and
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
    a namespaced slug that is priced in its own right - because OpenRouter
    charges something the direct provider does not - beats the general answer.
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
# and refusing a run that cannot pay. What is CHARGED is this estimate too -
# the price is taken up front - so an estimate that drifts is not a cosmetic
# problem, it is the business either losing money or overcharging. What the run
# really cost is metered underneath and written to the ledger beside it, which
# is how the drift is caught.
@dataclass(frozen=True)
class Shape:
    sys_in: int          # the system prompt - identical on every page
    fixed_in: int        # per page and not cacheable: the page image, the JSON
    per_box_in: int      # the boxes on THIS page
    chapter_in: int      # every box of CONTEXT sent with this page
    per_box_out: int     # the visible reply - the words that reach the page
    fixed_out: int = 0
    # ...and how much of the reply is decided by the LENGTH of the lines
    # rather than by how many there are. A box holding one word and a box
    # holding a sentence do not come back the same size, and a box count
    # cannot see the difference.
    #
    # Measured on lee's 23 pages, every page predicted by a model fitted on
    # the other 22 (so nothing is scored on itself):
    #
    #     per box alone, as it was    mean error 20.6%, worst page 31.1%
    #     per box, refitted            6.4%   29.0%
    #     per source character        16.3%   35.7%
    #     both together                2.3%    7.8%
    #
    # Both together, then. `src_chars` reaches here from `run_price`, which
    # counts the real source text; a caller that does not know it gets
    # `SRC_CHARS_PER_BOX` and the one-term answer, which is still three times
    # better than what this replaced.
    per_src_char_out: float = 0.0
    # Does this step send PICTURES? Only the reader does, and how many depends
    # on the reading detail somebody chose - one a page, four, nine, or one
    # per box. See `pictures` and `ocr.DETAILS`.
    pictures: bool = False
    # The reasoning figure this shape was FIRST fitted with, per page. Not
    # read by any price any more: thinking is priced per box from
    # `THINK_PER_BOX` and switched by `thinks`, which asks the meter. It was
    # also the switch - a shape with 0 here charged no thinking whatever the
    # model did - and that switch is what left Opus 5's reasoning off every
    # Read text quote. Kept because the one invoice it was fitted to is
    # still checked against it (`test_three_quarters_of_that_bill_was_the_
    # model_thinking`), and because a number with a story is worth more
    # than a blank.
    think_out: int = 0


# Anthropic's cache has to be asked for and only pays above this; below it the
# prompt is sent, and charged, in full. `translate._system_blocks` uses the
# same number and this has to agree with it or the estimate prices a cache
# that was never asked for. Not imported from there - that module imports THIS
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
# app makes, FOR A MODEL THE METER HAS NOT SEEN YET. Once a step has run on a
# model, `thinks` reads the answer off the ledger and this list is not
# consulted - see `_meter_thinks`. It is the first-run guess and nothing more.
#
# This is a fact about the MODEL, not about the provider, which is why it is
# matched on the id and read through the vendor prefix - `google/gemini-3.6-
# flash` bought through OpenRouter thinks exactly as much as the same model
# bought direct, and pricing it as though it did not quotes a Gemini chapter at
# a fraction of what it comes to.
#
# THIS SAID "Claude thinks only when a request turns it on, and no request
# here does", AND IT WAS TRUE UNTIL THE 5 LINE. Anthropic's own docs on the
# thinking parameter: *"On Claude Opus 5, Claude Sonnet 5, Claude Fable 5.1,
# Claude Mythos 5.1, Claude Fable 5, Claude Mythos 5, and Claude Mythos
# Preview, thinking is already on and needs no configuration"* - and the
# request this app sends carries no `thinking` at all, which on those models
# is adaptive thinking at the default effort. Measured on lee's 58-page
# manhwa (task #125): Opus 5 returned 19,576 output tokens for 144 boxes
# where Gemini 3.8 Flash returned 3,110 for the same boxes and the same JSON.
# The other sixteen thousand were reasoning, billed as output, reported
# nowhere. Five sixths of Opus's output and a third of its bill, and the quote
# had it at nothing.
#
# Qwen 3.7 Plus is the same finding from a provider that does say: OpenRouter
# reported 30,755 reasoning tokens out of 34,598 output on the same read.
#
# Opus 4.8 and earlier, Sonnet 4.6 and earlier, Haiku 4.5: off unless asked,
# and nothing here asks. They are deliberately not on this list.
THINKS = ("gemini-",
          "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
          "qwen3.7-plus", "qwen3.7-max")

# ...and the steps a listed thinker is known NOT to think on, for the same
# first-run purpose. A read is a transcription, and Gemini does not reason
# over one: 3.8 Flash reported 0 across 145 read calls, and 3.5 Flash Lite's
# 145 calls before it returned 31 output tokens a box, which is the JSON and
# nothing else. It reasons hard on a translate - nine tenths of lee's output
# there - so this is a fact about the step, and it is written per step.
# Matched on the same prefixes as `THINKS`. Once the meter has seen the pair
# it is not consulted, like the list above it.
THINKS_NOT_ON = {"gemini-": ("ocr",)}

# THE READER TURNS CLAUDE 5's THINKING OFF. lee, shown that five sixths of
# Opus's output on a read was reasoning: *"turn it of ad let me do a run and
# compare"*. `translate._ask_vision` sends `thinking: {"type": "disabled"}`
# for these models, and `thinks` quotes them without reasoning on the `ocr`
# step - ONE list, read by both, so the quote and the request cannot say
# different things about the same call.
#
# Opus 5 and Sonnet 5 accept the parameter (at effort `high` or below, which
# is the default). Fable 5 and the Mythos line REJECT it - Anthropic:
# *"Thinking can't be turned off on these models"* - so they are not here,
# and a read on them thinks and is quoted for it. A model that turns out to
# refuse anyway is remembered by the reader for the rest of the process and
# read with thinking on; that case is priced high rather than low, which is
# the direction a hold can absorb.
#
# Reads only. The translate and the proofread are left thinking: nobody has
# measured them without it, and a translation is the step where reasoning
# most plausibly earns its cost.
#
# IT LOST. The same 58 pages read twice on Opus 5, thinking on and thinking
# off, 142 boxes each, settled against the artwork:
#
#     thinking on    274 coins   0 dialogue errors    6 of 11 disputed sfx right
#     thinking off   190 coins   2 dialogue errors    1 of 11 disputed sfx right
#
# The two dialogue errors were on CLEAN PRINTED TYPE: page 012's balloon
# reads `생일 축하해,\n오빠!` in a two-line font and came back without the
# second line, and page 009's `현실이었음을` came back as `이였음을`. Both are
# the errors Gemini made on the same boxes. Without its thinking, Opus reads
# like a cheaper model - which is exactly what the 84 coins were buying.
#
# So the tuple is EMPTY and the machinery stays: `_create_read` still sends
# the knob for whatever is listed here, `thinks` still quotes it that way,
# `drift` still keeps the two regimes apart, and the ledger now holds one
# measured run of each. Putting a model back is one name in this tuple.
# The 84-coin saving is written down here so nobody buys it twice.
READ_THINKING_OFF: tuple = ()

# Backends whose replies SAY how much was reasoning. A meter line from any
# other backend that happens to carry `think` was written before
# `usage_extras` learned to tell silence from zero, and its 0 is silence -
# `_meter_thinks` must not read it as a measurement.
REPORTS_THINK = ("openrouter", "gemini")

# ------------------------------------------------------------ counting text
#
# A price needs to know how many tokens a string is, and the app cannot ask:
# Claude's tokenizer is not published, `count_tokens` needs the network and a
# key, and a chapter is priced before anything is sent. So it is counted here,
# from the characters, by a rule FITTED TO THE STRINGS THIS APP REALLY SENDS.
#
# Measured on lee's chapter - 49 real requests, 198,000 characters, built by
# the app's own prompt builders and tokenized twice (o200k, and Claude's own
# published tokenizer; the two agree on a whole bill to 3.7%):
#
#     1.25 tokens an English word     the usual ~1.3, near enough
#     0.95 tokens a CJK character     Japanese is about one token a character
#     0.63 tokens a punctuation mark  braces and quotes merge with their
#                                     neighbours more often than not
#
#     over whole requests   mean error 2.9%, worst 7.3%, whole bill +1.0%
#     over bare lines       mean error 11.1%
#
# THE OBVIOUS RULE IS THE WRONG ONE. Four characters to a token - which is
# what `translate._cacheable` uses, and it is right there, for an English
# prompt - is 25% LOW over these requests and 41% low over bare lines: a page
# payload is a third punctuation, and a Japanese character is not a quarter of
# a token but nearly a whole one. Applied to the source side it would
# undercharge every chapter this app was built to translate.
_CJK = re.compile("[⺀-鿿가-힯豈-﫿"
                  "＀-￯　-〿]")
_WORD = re.compile(r"[A-Za-z0-9]+")

TOK_WORD = 1.25
TOK_CJK = 0.95
TOK_PUNCT = 0.63


def tokens(text: str) -> int:
    """About how many tokens this string is. Never negative, never raises."""
    s = str(text or "")
    if not s:
        return 0
    cjk = len(_CJK.findall(s))
    rest = _CJK.sub("", s)
    words = _WORD.findall(rest)
    # Whitespace is free - it rides along with the token beside it. Whatever
    # is neither a word character nor a space is punctuation.
    punct = (len(rest) - sum(len(w) for w in words)
             - sum(1 for c in rest if c.isspace()))
    return int(round(TOK_WORD * len(words) + TOK_CJK * cjk
                     + TOK_PUNCT * max(0, punct)))


# THE SYSTEM PROMPTS ARE COUNTED, NOT REMEMBERED.
#
# `sys_in` used to be a number typed into `SHAPES`, and on 2026-08-31 the
# translate one read 2,086 against a real 4,600: the prompt had more than
# doubled since it was measured, and the quote was 18% short on lee's own
# chapter because of it. The comments in this file had warned twice that these
# numbers cross thresholds whenever a prompt is edited, which is exactly what
# happened, twice, for reasons that had nothing to do with money.
#
# They need not be written down at all. `build_system`,
# `build_proofread_system` and `build_ocr_system` take no page - only the four
# project settings below - so the real prompt can be built and counted the
# moment it is wanted, and this whole class of staleness stops existing. The
# figures left in `SHAPES` are the fallback for a build where `translate`
# cannot be imported, and nothing else.
#
# Imported inside the function on purpose: `translate` reaches for `coins` in
# `_meter`, and a module-level import here would close the cycle.
_SYS_BUILDERS = {
    "translate": lambda t, m, tg, sr, h: t.build_system(m, tg, sr, h),
    "proofread": lambda t, m, tg, sr, h: t.build_proofread_system(m, tg, sr),
    "ocr": lambda t, m, tg, sr, h: t.build_ocr_system(
        t.source_language(m, sr)),
}


@lru_cache(maxsize=64)
def sys_tokens(step: str, medium: str = "manga", target: str = "en",
               source: str = "", honorifics: bool = False) -> int:
    """The step's system prompt, counted from the prompt itself.

    Falls back to the `SHAPES` figure when the prompt cannot be built - a
    trimmed build, an import that is not there. A stale number beats no price
    at all, and it is the only thing those numbers are still for.
    """
    sh = SHAPES.get(step)
    build = _SYS_BUILDERS.get(step)
    if build is None:
        return sh.sys_in if sh else 0
    try:
        from . import translate as _t
        got = tokens(build(_t, medium, target, source, bool(honorifics)))
        return got or (sh.sys_in if sh else 0)
    except Exception:
        return sh.sys_in if sh else 0


# ------------------------------------------------------- pictures, not words
#
# WHAT A PICTURE COSTS, and it is the biggest single number in a read.
#
# `fixed_in` on the reader's shape used to carry it as 1,747 tokens a page,
# which was wrong twice over: wrong in size, and wrong in SHAPE. The reader
# sends one picture per BOX when it is reading zoomed (`ocr.DETAILS`), so a
# ten-box page sends ten pictures, and the cost is per box and not per page at
# all.
#
# Measured off lee's own ledger - 138 real runs, 1,000+ pages:
#
#     gemini-3.7-flash        2,479 tokens a picture   (8 runs, 18% spread)
#     gemini-3.5-flash-lite   1,735                    (17 runs, noisier)
#     claude-opus-5           1,127
#
# ...and the providers' own rules say why. Google tiles an image into 768px
# squares at 258 tokens each, so a crop capped at `ocr.MAX_SIDE` (1568) is 3x3
# tiles = 2,322 - which is the 2,479 measured, with the prompt's own words
# making up the rest. Anthropic charges about width x height / 750.
#
# So this is a real fact about a provider rather than a fitted constant, and
# it is per vendor because that is the level the fact lives at.
IMAGE_TOKENS = {
    "google": 2400,
    "gemini": 2400,
    "anthropic": 1150,
    "claude": 1150,
}
IMAGE_TOKENS_DEFAULT = 1800


def image_tokens(model: str = "", backend: str = "") -> int:
    """What one picture sent to the reader costs, in input tokens."""
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return 0
    m = vendor_free((model or "").strip().lower())
    for key, n in IMAGE_TOKENS.items():
        if m.startswith(key):
            return n
    return IMAGE_TOKENS_DEFAULT


def pictures(detail: str = "", boxes: int = 0) -> float:
    """How many pictures ONE PAGE of a read sends, at this reading detail.

    Zoomed sends one a box, which is what makes it the dearest mode and what
    `ocr.DETAILS` now says out loud on the settings screen. Everything else
    sends a fixed few of the page itself.

    Asked of `ocr.DETAILS` rather than answered here, so the price and the
    reader cannot disagree about what a mode means. Imported inside the
    function - `ocr` is a heavy module and this one is imported by everything.
    """
    try:
        from .ocr import DETAILS, detail_for
        spec = DETAILS.get(detail_for("", detail)) or {}
    except Exception:
        spec = {}
    n = int(spec.get("pieces") or 0)
    return float(n) if n else float(max(0, int(boxes or 0)))


# ...AND HOW MUCH, WHICH IS PER BOX AND NOT PER PAGE.
#
# `Shape.think_out` carried 1,689 tokens A PAGE, flat, fitted to one Gemini
# 3.6 Flash chapter. Two things about that turned out to be wrong.
#
# **The number.** Measured against lee's ledger - 283 real 3.7 Flash pages,
# metered per call - a translate page returns 440 output tokens in total,
# reply and reasoning together, against the 1,995 that constant predicts.
#
# **The shape.** Flat per page cannot fit the data at all. Two runs on two
# model versions, thinking taken as what is left after the visible reply:
#
#     gemini-3.7-flash   283 pages, 8.7 boxes a page   ~15 tokens a box
#     gemini-3.6-flash    73 pages, 2.0 boxes a page   ~19 tokens a box
#
# Per PAGE those two are 133 and 37 and agree about nothing; per BOX they are
# 15 and 19 and agree closely. A model reasons about the lines it was given,
# and a two-box page gives it a fifth of the work a ten-box page does. The old
# comment argued the opposite - "a model given a two-box page and a model
# given a ten-box page do not reason a fifth as hard for the smaller one" -
# and the meter says otherwise.
#
# **The figure that said 1,689 is not thrown away, it is explained.** It came
# from a balance on a billing page read before and after a chapter - lee:
# *"before i had $0.502 of money spent and then i did the translation and now
# i have $1.032"* - and a balance delta catches every call in the window,
# including the READ, which is the dearest step there is. The ledger meters
# each call on its own and does not have that problem. Where a real invoice
# and real per-call metering disagree by nine times, it is the method that
# cannot separate two steps that is wrong.
#
# The two below the Gemini pair are from the same 58-page manhwa read three
# ways (task #125), and they are a different order of magnitude:
#
#     claude-opus-5       19,576 out for 144 boxes, of which the visible reply
#                         is what Gemini returned for the same JSON, 3,110 -
#                         so (19,576 - 3,110) / 144  ~ 114 a box, unreported
#     qwen/qwen3.7-plus   30,755 REPORTED reasoning over 146 boxes  ~ 211 a box
#
# Those are READ-text figures. A model reasons about what it is asked, and a
# transcription is not a translation; `drift` keeps a correction per step and
# per model and will move each of these to where that step really lands. What
# matters here is the first quote being the right order of magnitude, because
# the first quote is the hold, and a hold a third short is a run that ends in
# the app absorbing the difference.
THINK_PER_BOX = {
    "gemini-3.6": 19,
    "gemini-3.7": 15,
    "claude-opus-5": 114,
    "qwen3.7-plus": 211,
}
THINK_DEFAULT = 40


def think_tokens(shape: "Shape", model: str = "", backend: str = "",
                 boxes: float = 0, step: str = "") -> float:
    """Reasoning tokens this page bills back as output, for these boxes.

    Gated on `thinks` alone. It used to be gated on `shape.think_out` as
    well, which switched thinking off for every step but translate - and
    that is how a Read text quote for Opus 5 carried no reasoning at all
    while the read spent five sixths of its output on it. Whether a model
    thinks on a step is a question for the meter, not for the shape, and
    `thinks` asks the meter first.
    """
    if not thinks(model, backend, step):
        return 0.0
    m = vendor_free((model or "").strip().lower())
    best = ""
    for key in THINK_PER_BOX:
        if m.startswith(key) and len(key) > len(best):
            best = key
    per = THINK_PER_BOX[best] if best else THINK_DEFAULT
    return float(per) * max(0.0, float(boxes or 0))


def cached_tokens(shape: "Shape", model: str = "", backend: str = "",
                  sys_in: int = 0) -> int:
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

    `sys_in` overrides the shape's remembered figure with a counted one - see
    `sys_tokens`. It matters twice: the SIZE of the cache read, and whether
    there is one at all, because a prompt under `CACHE_MIN_TOKENS` is never
    marked for the cache and is paid for in full on every page of a chapter.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return 0
    n = int(sys_in or 0) or shape.sys_in
    if n < CACHE_MIN_TOKENS:
        return 0
    return n if vendor_free(model).startswith(MARKS_CACHE) else 0


def reply_cap(step: str, boxes: int, src_chars: float = 0,
              model: str = "", backend: str = "") -> int:
    """`max_tokens` for one page's request: about twice the predicted reply.

    The unbounded half of a bill is the reply, and this turns it into a
    number we chose. TWICE the prediction, with a wide floor, because the cap
    must never truncate a real reply - the predictor's worst page ran 1.074x
    (measured, "Pricing the translate button"), so double is not a close
    shave, it is a roof with a margin of nearly 2x on the worst page seen.
    Thinking counts against a provider's output limit, so a model that
    reasons gets its thinking allowance on top. Never above the old flat
    8000, which now becomes the ceiling instead of the everyday value."""
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0:
        return 8000
    src = float(src_chars) if src_chars else SRC_CHARS_PER_BOX * boxes
    tout = (sh.fixed_out + sh.per_box_out * boxes
            + sh.per_src_char_out * src)
    tout += think_tokens(sh, model, backend, boxes, step)
    return int(min(8000, max(1500, 2 * tout)))


def thinks(model: str, backend: str = "", step: str = "") -> bool:
    """Does this model bill reasoning tokens back as output - on THIS step?

    Wrong in either direction is expensive: a thinking model quoted without it
    is quoted at a fifth of the bill, and a non-thinking one quoted with it is
    quoted at seven times.

    Per step, because the same model does not reason the same amount at
    every job: Gemini 3.8 Flash reported 0 reasoning tokens across 145 Read
    text calls on lee's manhwa, and nine tenths of its output on a translate
    was reasoning. Asked of the METER first - the last few runs of this step
    on this model, where the provider said - and of the `THINKS` name list
    only for a model the meter has never seen on this step. A name list is
    where the answer starts; it is not where it lives.
    """
    if (backend or "").strip().lower() in FREE_BACKENDS:
        return False
    m = vendor_free((model or "").strip().lower())
    if step:
        # What this app ASKS FOR outranks what the model does unasked: a read
        # on Claude 5 is sent with thinking disabled, so it is quoted that
        # way. Before the meter, because Anthropic's meter never speaks.
        if step == "ocr" and m.startswith(READ_THINKING_OFF):
            return False
        said = _meter_thinks(step, (model or "").strip().lower())
        if said is not None:
            return said
        for pre, steps in THINKS_NOT_ON.items():
            if m.startswith(pre) and step in steps:
                return False
    return m.startswith(THINKS)


def read_thinks_off(model: str) -> bool:
    """Is a read on this model sent with thinking disabled? The reader's
    half of `READ_THINKING_OFF`, so `translate` asks here rather than
    keeping a copy of the list."""
    return vendor_free((model or "").strip().lower()).startswith(
        READ_THINKING_OFF)


def _meter_thinks(step: str, model: str):
    """What the ledger says about reasoning on this step and model.

    `True` when any recent measured run reported reasoning, `False` when the
    runs that could have reported it all said 0, `None` when there is no
    measurement - no runs, or only runs from a provider that does not say.

    Only lines from `REPORTS_THINK` backends count, and only lines that carry
    the key: an Anthropic line written before `usage_extras` learned to leave
    the key off is a `think: 0` that means nothing, and reading it as "Opus
    does not think" is exactly the mistake this function exists to stop.

    Held still for the length of a run like `drift` is, and for the same
    reason: a run ends by writing a meter line, and a charge and its refund
    must not be priced on two different answers to this question.
    """
    at = getattr(_STEADY, "at", None)
    key = ("thinks", step, model)
    if at is not None and key in at:
        return at[key]
    got = None
    seen = 0
    for e in ledger(400):
        if seen >= DRIFT_RUNS:
            break
        if e.get("kind") != "meter" or e.get("step") != step:
            continue
        if (e.get("model") or "").strip().lower() != model:
            continue
        if (e.get("backend") or "").strip().lower() not in REPORTS_THINK:
            continue
        if "think" not in e or int(e.get("boxes") or 0) < DRIFT_MIN_BOXES:
            continue
        seen += 1
        if int(e.get("think") or 0) > 0:
            got = True
            break
        got = False
    if at is not None:
        at[key] = got
    return got

# Measured against the real prompt builders - `build_system`, `build_payload`,
# `build_proofread_payload`, `_ocr_context` - at 2, 9 and 20 boxes a page, and
# checked against a real bill. lee, having run one chapter through Gemini 3.6
# Flash and read his Google invoice: *"before i had $0.502 of money spent and
# then i did the translation and now i have $1.032, so it cost $0.508 to
# translate the chapter"*.
#
# `chapter_in` is the context term, and it is charged for exactly the boxes
# `editor.run_context` really sends - no more. It used to be the biggest error
# in this file in BOTH directions: first missing altogether, then invented. A
# full-chapter run sends no context at all, and quoting it the whole chapter's
# boxes anyway put some hundred thousand imaginary input tokens on lee's
# twenty-three page bill.
#
# **The output figures are where the money actually is.** lee's real invoice
# for that chapter: 75,400 input and 44,870 output. Three quarters of the bill
# was output, and nine tenths of the output was the model THINKING - the
# visible reply, the words that reach the page, was about 6,000 tokens of it.
#
# So the two are split. `per_box_out` is the reply and scales with boxes;
# the reasoning is `THINK_PER_BOX`, charged only where `thinks()` says the
# model does any ON THIS STEP. Written as one per-box number they were wrong
# twice over: a two-box page was quoted as thinking a fifth as hard as a
# ten-box page, and Claude 4 - which was not asked to think anywhere in this
# app - was quoted at seven times its real output cost. (Claude 5 thinks
# unasked; see `THINKS`.)
SHAPES: dict[str, Shape] = {
    # 1,110 of system prompt, plus 1,747 for the page image - which is
    # different every page and could not be cached whatever its size. The boxes
    # cost nothing to SEND: the reader is given a picture, not a list.
    #
    # THIS PROMPT USED TO BE 552 AND UNDER THE CACHE FLOOR, and the comment
    # here said so as a fact about the file. It crossed the floor when the
    # reader was taught to keep the marks a line carries - a heart, a star, a
    # music note - and at that moment two numbers here went wrong at once: the
    # size, and the CACHE TREATMENT, which is worth more. `sys_in` under the
    # floor is priced as ordinary input, paid in full on every page; over it,
    # at a tenth. Left alone this would have overcharged every Anthropic
    # chapter, quietly, for a prompt edit that had nothing to do with money.
    #
    # `test_the_quote_prices_the_cache_the_way_the_code_asks_for_one` is what
    # caught it, because it asks `_cacheable(prompt)` rather than trusting a
    # number - and that test exists because the labeller's prompt had already
    # crossed the same line in the other direction a few hours earlier. Twice
    # in one day is the argument for never writing this down as a constant
    # without a test that reads the prompt.
    # `fixed_in` was 1,747 and was meant to be the page image. It is 190 now,
    # which is the prompt's own per-page words, because THE PICTURES ARE
    # PRICED SEPARATELY - see `image_tokens` and `pictures`. The reader sends
    # one picture a box when it reads zoomed, so the cost is per BOX, and no
    # per-page constant could ever say that. Measured against 138 real runs it
    # was charging about a third of what a read costs.
    # `per_box_out` was 60 and the real thing is 24 - a transcribed line and
    # its JSON, measured over 526 real pages on two Gemini models. Claude Opus
    # 5 returns seven times that on the one run there is of it, which is what
    # a model reasoning through a read looks like; one run is not enough to
    # write a constant from, and the widened drift clamp is what carries it
    # until there are more.
    "ocr": Shape(sys_in=1110, fixed_in=190, per_box_in=3, chapter_in=0,
                 per_box_out=25, pictures=True),
    # The second turn Read text can make: what KIND of box each one is
    # (`translate.label_kinds`, settings key `label_kinds`). Not a step - there
    # is no way to run it on its own - but a shape of its own, because it is
    # OFF unless somebody switches it on, and folding it into "ocr" would quote
    # a request most chapters never make. `editor.run_price` adds it when the
    # setting says to.
    #
    #   sys_in     1379   its own prompt, which lists the types it may use and
    #                     how to tell the ones that look alike apart
    #
    # 1,379 is the prompt WITHOUT the sound-effect-against-outside-text rule,
    # which is added only when `retype_kinds` is also on and takes it to 1,560.
    # Not modelled, and said out loud rather than left to be discovered: it
    # needs two switches on at once, and 181 tokens read back from a cache at a
    # tenth of input is below anything this file can meaningfully price. `drift`
    # absorbs it. Splitting the shape in two for it would cost more clarity
    # than it buys accuracy.
    #   fixed_in    553   the whole page at 768px, and 768 is where every
    #                     number tag is still legible - a third of what the
    #                     reader's own full-resolution page costs
    #   per_box_in    9   one line per box: "12: family bubble, currently ..."
    #   per_box_out   7   {"id":12,"kind":"thought"},
    #
    # THE PROMPT GOES IN `sys_in` AND THAT IS NOT COSMETIC. `sys_in` is the
    # part a cache can hold, and `_system_blocks` marks a system prompt for the
    # cache only when it clears `CACHE_MIN_TOKENS`. This one does.
    #
    # Having its own shape is what lets it keep its own answer to that
    # question. While the two turns shared one, the answer had to be right for
    # both at once - and both wrong ways of doing that were written before this
    # one. ADDING the prompts prices a single prompt that clears the floor
    # while neither real turn is that size, and charges a cache read on the
    # reader's, which was not cached then: undercharging every Anthropic page.
    # Putting this one in `fixed_in` does the opposite and charges full price
    # for tokens that come back at a tenth.
    #
    # It was UNDER the floor when first written and went over it when the
    # reference charts lee sent turned four descriptions into eleven. The
    # reader's prompt then crossed the same line, the other way, a few hours
    # later. So this is not a fact to read off the file once - it is a
    # threshold any of these prompts can cross by being edited, and the tests
    # ask `_cacheable(prompt)` rather than trusting the numbers here.
    #
    # It grew again when the pass took on the ANGLE of loose writing - lee:
    # *"is posible while looking at the box type with reas text ask it to give
    # the angle of the text for the typesetter"*. `ANGLE_RULE` is 988
    # characters of system prompt, one `, angle?` in the listing for every
    # region it applies to, and an `"angle":-12.5` back for each of those.
    # Priced at the page that HAS loose writing on it, which is the page this
    # is for: a page of nothing but balloons never carries the rule at all and
    # is charged a little over, and that is the right way round.
    # ...and again when a FLASH balloon became a type of its own and the pass
    # was told to say when it is not sure. lee: *"make a new clasificicaton
    # and name it fancy bubble"*, *"if the ai is not confident of a box
    # acthergory it shoud not change the type"*.
    "label": Shape(sys_in=1873, fixed_in=553, per_box_in=11, chapter_in=0,
                   per_box_out=10),
    # The big one. 2,158 of series context, ~870 of scaffolding, 43 a box for
    # the page itself - and 21 a box for the whole chapter, on every page.
    # 2,158 / 43 until the length budget came out. lee: *"i wan the most
    # accurate transaltion no matter the leght of the of it so i dont want to
    # shrink or expand teh translation to fit anythng"*. The prompt lost the
    # SHORT rule (14,664 -> 14,172 characters) and every region lost
    # `src_char_count` and `fits_chars`, which were 45 of the 130 characters a
    # box was costing. `chapter_in` does NOT move with it: `chapter_context`
    # builds its own line entries and never carried either number.
    #
    # `sys_in` here is now only the fallback - the real figure is counted off
    # `build_system` by `sys_tokens`, and on lee's chapter that is 4,600
    # against the 2,086 this said. The number is left at what it was measured
    # to be so that a build which cannot import `translate` still prices
    # something, and it is deliberately NOT updated to 4,600: a constant
    # nothing reads is a constant nobody maintains, and the whole point of
    # counting is that it stops mattering.
    #
    # `per_box_out` and `per_src_char_out` are the two-term fit of the visible
    # reply over lee's 23 real pages:
    #
    #     out = 24 + 25.1*boxes + 0.57*source characters   (per page)
    #
    # which comes to about 35 tokens a box on that chapter - against the 28
    # this used to say, and 20.6% of the reply that went unbilled with it.
    "translate": Shape(sys_in=2086, fixed_in=873, per_box_in=28, chapter_in=21,
                       per_box_out=25, fixed_out=24, per_src_char_out=0.57,
                       think_out=1689),
    # 1,355 until the honorific rule went into `PROOFREAD_TEMPLATE` and
    # `keep_honorifics` into the payload: the prompt grew 5,648 -> 6,091
    # characters, which is 106 more tokens at the ratio the 1,355 was measured
    # at. The boolean itself is inside the rounding on `fixed_in`.
    #
    # 1,744 now: the copy editor was told that a mark is not punctuation and
    # not its to tidy. Its own "plain punctuation only" rule would otherwise
    # have taken back out every heart the reader had just been taught to keep -
    # the three prompts have to agree about this or the last one wins.
    # Comfortably over the floor before and after, so only the size moved.
    # 70 against a measured 25 a box over 166 real pages. The copy editor
    # returns the lines it CHANGED and most lines come back untouched, which
    # is the thing a per-box constant fitted to a worst case cannot see.
    "proofread": Shape(sys_in=1744, fixed_in=607, per_box_in=58, chapter_in=0,
                       per_box_out=25),
}

# How much source text a box holds when nobody counted. Measured over lee's
# chapter: 3,089 Japanese characters across 234 boxes. Only a fallback - every
# caller that has the page counts the real thing - and `drift` corrects it for
# a series whose bubbles are longer or shorter than his.
SRC_CHARS_PER_BOX = 13.2


# lee: *"the clenning fee shud be a flat fee per page"*. The cleaner is a
# hosted GPU and it is handed a picture; how many boxes are on it moves the
# seconds hardly at all, which is why this one is not per box like the rest.
# Roughly eight seconds of an A10G at Modal's published rate.
CLEAN_USD_PER_PAGE = 0.0035


def _prompt_key(prompt) -> tuple:
    """The four project settings the system prompts are built from, padded.

    A tuple rather than four arguments threaded through five functions, and a
    tuple rather than the context object itself because this module knows
    about money and should not learn about `SeriesContext` to ask how long a
    string is. Empty means the defaults, which is what the builders use.
    """
    got = tuple(prompt or ())
    d = ("manga", "en", "", False)
    return tuple(got[i] if i < len(got) else d[i] for i in range(4))


def usd_page(step: str, boxes: int = 0, model: str = "",
             backend: str = "", chapter_boxes: int = 0,
             src_chars: float = 0, prompt=(), detail: str = "") -> float:
    """What this page of this step really costs, in dollars. No rounding.

    `src_chars` is the source text on THIS page, which decides how long the
    reply comes back - see `Shape.per_src_char_out`. `prompt` is the four
    settings the system prompt is built from, so it can be counted rather
    than remembered - see `sys_tokens`. Both are optional and both have a
    measured fallback, so an older caller still gets a price.

    `chapter_boxes` is the boxes of CONTEXT this page is sent - what
    `editor.run_context` really puts in the payload, and nothing else.

    **Nought means nought.** This used to read `max(boxes, chapter_boxes)`, so
    an explicit zero was quietly read as "well, this page's worth". A
    full-chapter run sends no context at all, and that one `max` put about a
    hundred thousand input tokens of pure invention on lee's twenty-three page
    quote. A default that overrides what the caller said is not a default.

    The rounding happens once, over a whole RUN - see `quote`. Rounding here
    would be rounding 23 times for a chapter and would flatten exactly the
    thing lee asked for: at a hundred coins to the dollar a single page of
    translation costs well under one coin, so a page with two boxes and a page
    with six both round to 1 and the per-box price disappears.

    A page with no text box costs nothing at all - there is nothing to send.
    That is not a special case bolted on, it is what the arithmetic says, and
    it matters because a chapter is full of splash pages.
    """
    if step == "clean":
        return CLEAN_USD_PER_PAGE
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0:
        return 0.0
    r = rate_for(model, backend)
    sys_in = sys_tokens(step, *_prompt_key(prompt))
    cached = cached_tokens(sh, model, backend, sys_in)
    tin = (sh.fixed_in + sh.per_box_in * boxes
           + sh.chapter_in * max(0, int(chapter_boxes or 0))
           + (0 if cached else sys_in))
    if sh.pictures:
        tin += pictures(detail, boxes) * image_tokens(model, backend)
    src = (float(src_chars) if src_chars
           else SRC_CHARS_PER_BOX * boxes)
    tvis = sh.fixed_out + sh.per_box_out * boxes + sh.per_src_char_out * src
    tthk = think_tokens(sh, model, backend, boxes, step)
    # ...and then what the last few runs of this step on this model really
    # came to, against what this same shape predicted for them. All 1.0 on a
    # fresh install, and 1.0 for as long as the shape is right. The reply
    # and the thinking are corrected apart where the meter has seen them
    # apart - see `drift`.
    din, dout, dthk = drift(step, model, backend)
    # NO ROUNDING, which is what the name of this function promises and what
    # its callers need. Tokens were rounded to whole numbers here, and once
    # the reply gained a source-character term that made the price a
    # STAIRCASE in the box count instead of a line - which broke the site's
    # calculator, because `tools/site_costs.py` reconstructs this function
    # from three readings and can only do that while it is flat.
    #
    # A fraction of a token is not a thing anybody is billed for either way:
    # the rounding that matters happens once, over a whole run, in
    # `coins_for_usd`.
    return r.usd(tin=tin * din, cached=cached * din,
                 tout=tvis * dout + tthk * dthk)


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
# ...and it was (0.5, 2.0), which could not say what lee's own ledger said.
# Measured over 138 real runs the reader was charging a third of its cost and
# the translator four and a half times over - both outside a clamp that only
# reaches half and double, so the correction pinned itself and stayed wrong.
#
# It is still asymmetric and still tight upward: charging MORE than the shape
# says is the direction that takes somebody's money, so that side moves least.
DRIFT_CLAMP = (0.2, 2.5)

# ...and the VISIBLE reply gets a band of its own, because it is not the same
# kind of number any more. Since the reply was refit on boxes + source
# characters it predicts real pages at about 2% error with a worst page of
# 7.8% (measured, "Pricing the translate button") - so a visible-reply drift
# outside a quarter either way no longer means "a dense series"; it means the
# arithmetic is broken somewhere, and a broken thing should SAY SO rather
# than be silently corrected into the price. The correction is clamped to
# this band and an `alarm` line goes in the ledger. THINKING is the opposite
# kind of number - unobservable in advance, the largest unverified figure in
# this file - so where the meter can see it apart (OpenRouter and Gemini
# report reasoning tokens) it gets its own coefficient on the wide clamp,
# and a thinking overrun stops masquerading as a reply overrun.
DRIFT_VIS_CLAMP = (0.75, 1.25)

# The alarms already sounded this process, so each rings once.
_ALARMED = set()


def predicted_think(step: str, boxes: int, model: str = "",
                    backend: str = "", labelled: bool = False) -> int:
    """The THINKING half of `predicted`'s output, alone - so drift can hold
    the visible reply and the reasoning to different standards."""
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0:
        return 0
    total = think_tokens(sh, model, backend, boxes, step)
    if labelled and step == "ocr" and "label" in SHAPES:
        # As its own step, the way `predicted("label", ...)` asks it - the
        # two have to add up, or the drift correction for a labelled read
        # is measured against a different sum than the quote uses.
        total += think_tokens(SHAPES["label"], model, backend, boxes,
                              "label")
    return int(total)


def predicted(step: str, boxes: int, pages: int, ctx: int = 0,
              model: str = "", backend: str = "", labelled: bool = False,
              src_chars: float = 0, prompt=(), detail: str = "") -> tuple:
    """What the SHAPE says a run of this size sends and gets back.

    `(input, cached, output)` in tokens, uncorrected - this is the thing drift
    is measured against, so it must not have drift already in it.

    `labelled` is the one thing a shape cannot know from its own arguments: a
    Read text run that ALSO said what kind each box is made two requests a page
    and both were metered onto one bill, under `step="ocr"`. Predicting only
    the read against that measurement says the reader costs half again what it
    does - for ever, for anybody who switched labelling on - and `run_price`
    then adds the labelling on top of a shape drift has already inflated by it.
    The same tokens, charged twice, to exactly the people who asked for the
    feature.

    Read back off the ledger line, which records it. An older line has no such
    key and comes back False, which is right: labelling did not exist when it
    was written.
    """
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0 or pages <= 0:
        return (0, 0, 0)
    parts = [sh]
    if labelled and step == "ocr" and "label" in SHAPES:
        parts.append(SHAPES["label"])
    tin = cached = tout = 0
    src = float(src_chars) if src_chars else SRC_CHARS_PER_BOX * boxes
    key = _prompt_key(prompt)
    for part, name in zip(parts, (step, "label")):
        sys_in = sys_tokens(name, *key)
        c = cached_tokens(part, model, backend, sys_in) * pages
        cached += c
        tin += (part.fixed_in * pages + part.per_box_in * boxes
                + part.chapter_in * max(0, int(ctx or 0)) * pages
                + (0 if c else sys_in * pages))
        if part.pictures:
            # per PAGE at a fixed detail, per BOX when zoomed - which is why
            # this is worked out from the run's own totals and not multiplied
            # up from one page
            tin += (pictures(detail, 0) * pages or boxes) \
                * image_tokens(model, backend)
        tout += (part.fixed_out * pages + part.per_box_out * boxes
                 + part.per_src_char_out * src)
        tout += think_tokens(part, model, backend, boxes, name)
    return (int(tin), int(cached), int(tout))


def _clamp(x: float) -> float:
    lo, hi = DRIFT_CLAMP
    return max(lo, min(hi, float(x)))


def _clamp_vis(x: float, key=None) -> float:
    """The visible reply's tight band - and the bell when it is left.

    See `DRIFT_VIS_CLAMP`. The alarm is one ledger line per step-and-model
    per process, kind `alarm`: it moves no money and votes in no ratio, it
    is there so a broken predictor is a sentence in the receipt rather than
    a number quietly absorbed."""
    lo, hi = DRIFT_VIS_CLAMP
    if key is not None and not lo <= float(x) <= hi and key not in _ALARMED:
        _ALARMED.add(key)
        try:
            with _LOCK:
                w = _read()
                _entry(w, kind="alarm",
                       what="the visible reply is drifting %.2fx from a "
                            "prediction that should be within a few percent "
                            "- the estimate's arithmetic needs looking at, "
                            "not correcting" % float(x),
                       step=key[0], model=key[1])
                _write(w)
        except Exception:
            pass
    return max(lo, min(hi, float(x)))


def drift(step: str, model: str = "", backend: str = "") -> tuple:
    """`(input, visible output, thinking)` corrections for this step here.

    Three numbers now, not two - task #120. Where the meter could see the
    reasoning apart from the reply (`think` on the line), the reply and the
    reasoning each get their own coefficient: the reply on the tight band
    (`DRIFT_VIS_CLAMP`, with the alarm), the thinking on the wide clamp,
    because thinking is the one number that cannot be predicted and the
    reply is the one that now can. Lines written before the split - or by
    providers that do not report reasoning - fall back to one combined
    output ratio for both, exactly as before.

    Read off the meter lines the last few runs wrote. Both corrections are a
    SUM over runs and not an average of their ratios, so a forty-page run
    outweighs a one-page one - which is right, because the forty-page run is
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
    rvis = rthk = pvis = pthk = 0
    seen = 0
    # Which REGIME the quote is for. A read on Claude 5 is sent with thinking
    # off now and was sent with it on until today; those are two different
    # outputs for the same boxes (3,600 tokens against 19,600 on lee's
    # chapter), and a line from the other regime is not evidence about this
    # one - it is the very error that would drag a non-thinking quote up
    # 2.5x for the next eight runs. Lines say which they were (`think_off`);
    # a line from before the key existed was a thinking run.
    want_off = step == "ocr" and read_thinks_off(model)
    for e in ledger(400):
        if seen >= DRIFT_RUNS:
            break
        if e.get("kind") != "meter" or e.get("step") != step:
            continue
        if (e.get("model") or "").strip().lower() != model:
            continue
        if bool(e.get("think_off")) != want_off:
            continue
        boxes, pages = int(e.get("boxes") or 0), int(e.get("pages") or 0)
        if boxes < DRIFT_MIN_BOXES or pages <= 0:
            continue
        # Predicted with whatever that run recorded about itself. A line
        # written before this existed has no `src` key and comes back 0, which
        # falls to `SRC_CHARS_PER_BOX` - the same answer the quote it is being
        # compared against would have used, which is the only way the ratio
        # means anything.
        tin, cached, tout = predicted(step, boxes, pages,
                                      int(e.get("ctx") or 0), model,
                                      e.get("backend") or backend,
                                      bool(e.get("labelled")),
                                      float(e.get("src") or 0))
        if tin + cached <= 0 or tout <= 0:
            continue
        seen += 1
        pin += tin + cached
        rin += int(e.get("tin") or 0) + int(e.get("cached") or 0)
        # A line that saw the reasoning apart votes on the SPLIT ratios; a
        # line that did not votes on the combined one. The two populations
        # never mix, so neither can launder the other's overrun.
        #
        # "Saw" means the BACKEND says, not that the key is there. Every
        # Anthropic line written before `usage_extras` learned to leave the
        # key off carries `think: 0`, and that 0 is silence: read as a
        # measurement it puts Opus 5's whole reasoning under the visible
        # reply (clamped, with the bell) AND votes the thinking ratio down to
        # its floor for having "reported" nothing - the quote lands a third
        # short twice over. Those lines are in lee's ledger now and will be
        # for as long as the window reaches back; they vote on the combined
        # ratio, which is the only honest one for a single number.
        if "think" in e and (e.get("backend") or backend
                             or "").strip().lower() in REPORTS_THINK:
            thk_p = predicted_think(step, boxes, model,
                                    e.get("backend") or backend,
                                    bool(e.get("labelled")))
            thk_r = int(e.get("think") or 0)
            pthk += thk_p
            rthk += thk_r
            pvis += max(0, tout - thk_p)
            rvis += max(0, int(e.get("tout") or 0) - thk_r)
        else:
            pout += tout
            rout += int(e.get("tout") or 0)
    din = _clamp(rin / pin) if pin and rin else 1.0
    if pvis or pthk:
        dvis = (_clamp_vis(rvis / pvis, (step, model)) if pvis and rvis
                else 1.0)
        # `if pthk`, not `if pthk and rthk`. A line here SAW the reasoning,
        # so a real 0 against a predicted N is a measurement - the model did
        # not think on this step - and the old test threw exactly that
        # measurement away, leaving a thinking model's full allowance on a
        # step it never thinks on. (`thinks` now asks the meter first and
        # usually gets there sooner; this is the same fact reaching the
        # ratio, for the runs before it flips.)
        dthk = _clamp(rthk / pthk) if pthk else 1.0
        return (din, dvis, dthk)
    dout = _clamp(rout / pout) if pout and rout else 1.0
    return (din, dout, dout)


_STEADY = threading.local()


@contextmanager
def steady():
    """Hold the corrections still for the length of a run.

    A run ENDS by writing a meter line. Without this, a run that is cancelled
    half way would have its refund priced against evidence its own charge never
    saw - the charge computed before the line existed, the refund after - and
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
          chapter_boxes: int = None, src_counts=None, prompt=(),
          detail: str = "") -> int:
    """Coins a whole run is expected to cost - one box count per page.

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
    # `src_counts` is the source text on each of those pages, in the same
    # order. Missing - an older caller, or the scope dialog pricing pages it
    # has not opened - and every page falls back to `SRC_CHARS_PER_BOX`.
    srcs = [float(n or 0) for n in (src_counts or [])]
    srcs += [0.0] * (len(counts) - len(srcs))
    return coins_for_usd(sum(usd_page(step, n, model, backend, whole,
                                      src_chars=s, prompt=prompt,
                                      detail=detail)
                             for n, s in zip(counts, srcs)))


def quote_counted(step: str, system: str, user: str, boxes: int,
                  src_chars: float = 0, model: str = "", backend: str = "",
                  detail: str = "") -> int:
    """The price of ONE page whose real strings are in hand - task #117.

    A single-page run has already built (or can cheaply build) the exact
    system prompt and the exact payload it will send, so the input side is
    COUNTED off those strings instead of predicted from the shape - and a
    counted number takes no input drift, because it is not an estimate.
    The reply is still the predictor's (nothing can count a reply that has
    not happened), corrected the same way `usd_page` corrects it. SHAPES
    remain the whole answer for the scope dialog and multi-page runs,
    which price pages nobody has built payloads for.
    """
    sh = SHAPES.get(step)
    if sh is None or boxes <= 0:
        return 0
    r = rate_for(model, backend)
    sys_in = tokens(system or "")
    cached = sys_in if cached_tokens(sh, model, backend, sys_in) else 0
    tin = tokens(user or "")
    if not cached:
        tin += sys_in
    if sh.pictures:
        tin += pictures(detail, boxes) * image_tokens(model, backend)
    src = float(src_chars) if src_chars else SRC_CHARS_PER_BOX * boxes
    tvis = sh.fixed_out + sh.per_box_out * boxes + sh.per_src_char_out * src
    tthk = think_tokens(sh, model, backend, boxes, step)
    _din, dout, dthk = drift(step, model, backend)
    return coins_for_usd(r.usd(tin=tin, cached=cached,
                               tout=tvis * dout + tthk * dthk))


def quote_page(step: str, boxes: int = 0, model: str = "",
               backend: str = "", chapter_boxes: int = None,
               src_chars: float = 0, prompt=(), detail: str = "") -> int:
    """Coins ONE page of this step is expected to cost.

    A run of one. Used for the price beside "This page only" and for the check
    made before each page of a longer run - where erring high is right, since
    the alternative is starting a page the purse cannot finish.
    """
    return quote(step, [boxes], model, backend, chapter_boxes,
                 [src_chars] if src_chars else None, prompt, detail)


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
    think: int = 0                  # reasoning tokens, where the reply says
    # ...and whether any reply on this bill SAID. A provider that reports
    # reasoning and a provider that does not both leave `think` at 0 when
    # nothing was spent on it; this is what tells the two apart, so the meter
    # line can leave `think` off for the second and `drift` can file the
    # whole output as one number. See `usage_extras` for the bill it cost.
    think_seen: bool = False
    # How many calls the provider priced itself (`usage.cost`), against how
    # many went through our table. Written on the meter line so a receipt
    # says which number it was settled on - task #119.
    priced_direct: int = 0
    usd: float = 0.0
    flat_coins: int = 0             # fees that were never tokens - see `flat`
    calls: int = 0

    @property
    def coins(self) -> int:
        return coins_for_usd(self.usd) + self.flat_coins

    def add(self, model: str, rate: Rate, tin: int, tout: int,
            cached: int, written: int, think=None,
            usd_direct: float = 0.0) -> float:
        # THE PROVIDER'S OWN NUMBER WINS. OpenRouter puts what it charged on
        # the reply (`usage.cost`), and their price for their call beats our
        # copy of their price table - the table can be a week stale, the
        # reply cannot. Everything else still goes through the table.
        direct = bool(usd_direct and usd_direct > 0)
        got = (float(usd_direct) if direct
               else rate.usd(tin, tout, cached, written))
        self.model = self.model or model
        self.tin += tin
        self.tout += tout
        self.cached += cached
        self.written += written
        if think is not None:
            self.think_seen = True
            self.think += max(0, int(think or 0))
        self.priced_direct += 1 if direct else 0
        self.usd += got
        self.calls += 1
        return got


_LOCAL = threading.local()


@contextmanager
def charging(step: str, page: str = "", model: str = "", backend: str = ""):
    """Meter every model call made inside this block against one page.

    Nothing is debited here - `spend` is called by the caller once it knows
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
           model: str = "", think=None, usd_direct: float = 0.0) -> float:
    """One model call's usage. Called from the two places every AI step goes
    through - see `translate._ask` and `translate._ask_vision`. Returns the
    real cost it added, or 0 when nothing is metering.

    Real cost, not coins: this is one call, and the page it belongs to is what
    gets rounded up. See `Bill`.

    `think` is `None` for a provider that did not say - not 0. See
    `usage_extras` for why the difference is worth forty-nine coins.
    """
    bill = getattr(_LOCAL, "bill", None)
    if bill is None:
        return 0
    rate = getattr(_LOCAL, "rate", None) or rate_for(model or bill.model)
    return bill.add(model or bill.model, rate, int(tin or 0), int(tout or 0),
                    int(cached or 0), int(written or 0),
                    think=None if think is None else int(think or 0),
                    usd_direct=float(usd_direct or 0))


def flat(coins: int, what: str = "", page: str = "") -> int:
    """A charge that is not tokens - cleaning's flat fee per page.

    On the current bill when something is metering, straight out of the purse
    when nothing is. That second half is what lets the fee live at the one
    place a plate is actually BUILT, rather than at the four call sites that
    might reach it: a page cleaned on the way to an export costs the same as
    one cleaned by pressing Clean, and a page whose plate came out of the
    cache costs nothing, because nothing was built.

    It is already whole coins, so it goes on the bill BESIDE the tokens. Put
    back into dollars and added to them it would come to exactly the same
    number - ceil(x + n) is ceil(x) + n for a whole n - which is worth knowing
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
    than raising - a metering bug must not be able to fail a page.
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

        # Anthropic reports the three input kinds SEPARATELY - `input_tokens`
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


def usage_extras(resp) -> tuple:
    """(reasoning tokens, provider-reported cost in USD) off a reply.

    OpenRouter says both: `usage.completion_tokens_details.reasoning_tokens`
    and `usage.cost` (their credits are dollars). Gemini's native shape says
    the first as `thoughts_token_count`. Nothing here can raise - a metering
    bug must not be able to fail a page.

    THE REASONING COMES BACK AS `None` WHERE THE PROVIDER SAID NOTHING, and
    that is the whole of task #125. Anthropic bills thinking as output tokens
    and reports it nowhere - their docs: *"the tokens Claude spends reasoning
    are billed as output tokens, even when the thinking text isn't returned
    to you"* - so an Anthropic reply has no reasoning field at all. This used
    to hand that silence back as 0, the meter line then carried `think: 0`,
    and `drift` took the key's presence to mean the reasoning had been SEEN
    apart from the reply. Every one of Opus 5's thinking tokens - sixteen
    thousand of them on one 58-page read, five sixths of its output - was
    filed under the visible reply, where the tight band refused to correct
    for it and rang the alarm instead. The run overshot its own hold by 49
    coins. Silence and zero are different answers, and only one of them is a
    measurement.

    The cost stays 0.0 when unsaid: `Bill.add` reads 0 as "use the table",
    which is right, and there is no drift arithmetic hanging off it."""
    try:
        u = resp.get("usage") if isinstance(resp, dict) else \
            getattr(resp, "usage", None)
        if u is None:
            return (None, 0.0)
        think = None
        cost = 0.0
        if isinstance(u, dict):
            det = u.get("completion_tokens_details") or {}
            if isinstance(det, dict) and "reasoning_tokens" in det:
                think = int(det.get("reasoning_tokens") or 0)
            if think is None and "thoughts_token_count" in u:
                think = int(u.get("thoughts_token_count") or 0)
            try:
                cost = float(u.get("cost") or 0.0)
            except (TypeError, ValueError):
                cost = 0.0
        elif hasattr(u, "reasoning_tokens"):
            think = int(getattr(u, "reasoning_tokens", 0) or 0)
        return (None if think is None else max(0, think), max(0.0, cost))
    except Exception:
        return (None, 0.0)


def meter(resp, model: str = "") -> float:
    """`record` straight off a provider reply. The one line a call site adds."""
    tin, tout, cached, written = usage_of(resp)
    if not (tin or tout or cached or written):
        return 0
    think, cost = usage_extras(resp)
    return record(tin, tout, cached, written, model,
                  think=think, usd_direct=cost)


# ----------------------------------------------------------------- the purse

WALLET = "wallet.json"

# Where the Buy coins button goes. Not a payment form inside the editor: the
# editor is a thing somebody runs on their own machine, and a card number does
# not belong in it. lee: *"just have a buy coin button that will link to oa
# page on the website"*.
BUY_URL = "https://mangatct.com/coins"

# What a new install starts with. Enough to translate a chapter and see what
# the thing does before being asked for anything - a wallet that opens empty
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
    """Most recent first. The receipt - kept on disk so "what did that chapter
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

    On an account this is only ever a REFUND - pages that were paid for and
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
    billed on it - the quote is the price - but a quote drifting away from the
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


# The editor may put coins in when this is set, and only then. lee: *"i ran
# out of coins to test stuff"* and *"just add coins to the editor not teh
# website"*.
#
# It is an environment variable and not a switch on the screen, and that is
# the whole of the design. `account.py` says the editor never writes a
# balance, because the editor runs on the CUSTOMER'S machine and anything it
# can do they can do - a Top up button on a screen is a Top up button on their
# screen. An environment variable is not a hole in that: the person who can
# set one on the machine the purse lives on is the person who could edit the
# purse file with a text editor.
#
# So it tops up the LOCAL purse only. On an account it does nothing, because
# the account's balance lives behind a Cloud Function and the only thing that
# adds to it is a payment. Running the editor with
#
#     MANGATL_TEST_PURSE=1
#
# and signed out gives a purse on this machine with an Add button beside it.
TEST_PURSE = "MANGATL_TEST_PURSE"


def can_top_up() -> bool:
    """True when this editor is allowed to put coins in its own purse."""
    return bool(os.environ.get(TEST_PURSE)) and not remote()


def state() -> dict:
    """Everything the screen needs, in one read.

    No dollars. lee: *"remove teh real money comarasion"* - a coin is the unit
    the app is priced in, and putting a currency beside it invites the question
    of which currency, in which country, at today's rate. `where coins come
    from` is a link, not an exchange rate.
    """
    if remote():
        got = account.state()
        got["buy_url"] = BUY_URL
        got["can_top_up"] = False       # never, on an account
        return got
    with _LOCK:
        return {"balance": int(_read().get("balance") or 0),
                "buy_url": BUY_URL, "can_top_up": can_top_up(),
                "configured": account.configured(), "signed_in": False}


# ------------------------------------------------------------- from the shell

def _main(argv=None) -> int:
    """`python -m mangatl.coins` - read the purse, and put coins in it.

        python -m mangatl.coins                 what is in it
        python -m mangatl.coins add 5000        put 5000 in
        python -m mangatl.coins ledger          the last 20 lines of the receipt

    Deliberately not a button. Until there is a Firebase account behind the
    balance and a Stripe checkout in front of it, SOMETHING has to be able to
    put coins in or the person who wrote the app locks himself out of it - and
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
    quote will use. A correction sitting on a clamp is the thing to look for -
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
        din, dout, dthk = drift(step, model, es[0].get("backend") or "")
        print("%-11s %-24s %5d %6d %9d %9d %6.2f %6.2f"
              % (step, model[:24], len(es),
                 sum(int(e.get("boxes") or 0) for e in es),
                 sum(int(e.get("charged") or 0) for e in es),
                 sum(int(e.get("coins") or 0) for e in es), din, dout))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
