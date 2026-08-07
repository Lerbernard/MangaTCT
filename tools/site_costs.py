#!/usr/bin/env python3
"""Write `site/costs.js` from `coins.py`.

The pricing page used to carry a hand-typed table of what a chapter costs on
each model. It was right when it was typed and wrong by the time anybody
noticed: `coins.py` gained thinking-token output, prompt caching and the drift
correction, every figure moved, and nothing anywhere said so. A number on a
sales page that disagrees with what the app charges is worse than no number.

So the page does not hold numbers any more. It holds a calculator, and the
calculator reads this file, and this file is generated from the same functions
that take the coins. `tests/test_the_website.py` regenerates it and fails if
what is committed is not what comes out, which is what makes it stay true.

    python tools/site_costs.py            # write it
    python tools/site_costs.py --check    # say whether it is current

What is exported is not a price list but a SHAPE: two numbers per model per
step, being the cost of a page with no boxes on it and the cost of one box.
`usd_page` is linear in the box count for a fixed model and step, so those two
numbers reproduce it exactly rather than approximately - and a calculator that
is exact is one somebody can check against their own bill.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(ROOT))

from mangatl import coins                                       # noqa: E402

OUT = os.path.join(ROOT, "site", "costs.js")

# The chapter the page talks in. lee's, measured: 23 pages, 217 boxes. Every
# "about a chapter" claim on the site is this one.
CHAPTER = (23, 217)

# What to offer, in the order the page shows them, cheapest first. Not every
# model the app can reach - a menu of thirty on a pricing page is a menu
# nobody reads. One from each rung of the ladder, both vendors represented.
SHOW = [
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "gemini",
     "The cheapest thing that does the job. Fine for reading text off a page."),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "gemini",
     "A generation newer for not much more. A good default."),
    ("claude-haiku-4-5", "Claude Haiku 4.5", "anthropic",
     "Claude's small one. Better at holding a voice than its price suggests."),
    ("gemini-3.6-flash", "Gemini 3.6 Flash", "gemini",
     "Fast, and it thinks before it answers. The usual choice for translating."),
    ("claude-sonnet-5", "Claude Sonnet 5", "anthropic",
     "The one most people proofread with. Catches what the others miss."),
    ("claude-opus-5", "Claude Opus 5", "anthropic",
     "The best there is, and priced like it. Worth it on a page that matters."),
]

STEPS = ("ocr", "translate", "proofread")


def three_points(step, model, backend):
    """`(per page, per box, per context box per page)` in real dollars, exact.

    `usd_page` is flat in three variables for boxes >= 1, so three readings
    recover it: the page itself, the boxes ON the page, and the boxes of the
    CHAPTER that ride along as context.

    That third one is not a detail. Translating sends the whole chapter as
    context with every page, so a 217-box chapter puts 217 boxes of context on
    each of its 23 pages - and a calculator that left it out understated a
    Sonnet chapter by a third. It is also the reason "this page only" on a long
    chapter is not a twenty-third of the price, which is a thing the page
    should be able to show somebody rather than surprise them with.

    Read at 1 and 2 rather than 0 and 1 because 0 is the one value the
    function special-cases: a page with no text on it costs nothing at all,
    and that is a fact about empty pages, not a slope.
    """
    def at(b, ctx):
        return coins.usd_page(step, boxes=b, model=model, backend=backend,
                              chapter_boxes=ctx)
    box = at(2, 0) - at(1, 0)
    ctx = at(1, 1) - at(1, 0)
    return at(1, 0) - box, box, ctx


def data():
    out = []
    for mid, name, backend, blurb in SHOW:
        row = {"id": mid, "name": name, "backend": backend, "blurb": blurb}
        for step in STEPS:
            row[step] = three_points(step, mid, backend)
        out.append(row)
    return out


def num(x):
    """Enough figures to be exact, and no tail of float noise.

    A page costs a small fraction of a cent, so this needs to be fine; ten
    significant figures is far past where a dollar amount can notice and short
    enough that the file reads.
    """
    s = f"{x:.10g}"
    return "0" if s in ("-0", "0") else s


def js():
    pages, boxes = CHAPTER
    rows = []
    for r in data():
        steps = "".join(
            f"    {s}: [{num(r[s][0])}, {num(r[s][1])}, {num(r[s][2])}],\n"
            for s in STEPS)
        # `json.dumps` and not `!r`: a blurb with an apostrophe in it comes
        # out of Python single-quoted, and this file is JavaScript.
        q = json.dumps
        rows.append(
            f"  {{\n    id: {q(r['id'])}, name: {q(r['name'])},\n"
            f"    backend: {q(r['backend'])},\n"
            f"    blurb: {q(r['blurb'])},\n"
            f"{steps}  }},\n")
    return f"""/* GENERATED by tools/site_costs.py. Do not edit.
 *
 * Three numbers per model per step, all in real dollars before the markup:
 * what a page costs before any text is counted, what one box on that page
 * costs, and what one box of CHAPTER CONTEXT costs on that page. The third is
 * why a long chapter is not cheap per page - every page is sent the whole
 * chapter so the names and the honorifics hold from page 1 to page 39.
 *
 * `usd_page` in coins.py is flat in all three, so these reproduce it exactly.
 * The calculator is not an approximation of what you will be charged; it is
 * the arithmetic that charges you.
 *
 * A test regenerates this and fails if it has drifted from coins.py, which is
 * the only reason a number on a sales page can be trusted.
 */
export const CHAPTER = {{ pages: {pages}, boxes: {boxes} }};

/* A hundred coins is a dollar, and the coin price is double the real one.
 * lee: *"bubble teh coin cost so if something cost $1 make it cost 2 dollar in
 * coins"*. Rounded UP, once, over the whole run: rounding down is a free tier
 * for anybody who can arrange to land just under. */
export const COINS_PER_DOLLAR = {coins.COINS_PER_DOLLAR};
export const MARKUP = {coins.MARKUP};
export const coinsFor = (usd) =>
  Math.ceil(Math.max(0, usd) * COINS_PER_DOLLAR * MARKUP);

/* The hosted cleaner, which is per page and not per box - it is looking at
 * the picture, and the picture is the same size whatever is written on it.
 * The cleaners that run on your own machine cost nothing and are not here. */
export const CLEAN_USD_PAGE = {num(coins.CLEAN_USD_PER_PAGE)};

export const MODELS = [
{''.join(rows)}];

/* What a run of this shape costs, in coins. `steps` is which of them are
 * switched on: reading and translating always are, proofreading and the
 * hosted cleaner are choices.
 *
 * Rounded up once PER STEP and not once over the lot, because that is what
 * the app does - each step is its own run and its own button. Rounding once
 * at the end would come out one or two coins under, which is the wrong
 * direction for a number somebody is about to check against a real bill. */
export function quote(model, pages, boxes, steps) {{
  let total = 0;
  for (const s of ["ocr", "translate", "proofread"]) {{
    if (!steps[s]) continue;
    total += coinsFor(pages * model[s][0] + boxes * model[s][1]
                      + pages * boxes * model[s][2]);
  }}
  if (steps.clean) total += coinsFor(pages * CLEAN_USD_PAGE);
  return total;
}}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    want = js()
    if args.check:
        got = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if got == want:
            print("site/costs.js is current")
            return 0
        print("site/costs.js is STALE. Run: python tools/site_costs.py")
        return 1
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(want)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
