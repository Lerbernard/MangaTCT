"""Paying once for the words that never change.

Measured on chapter 3: a 23-page chapter is 176,663 input tokens, and
**103,523 of them - 59% - are byte-identical from one page to the next**. The
same system prompt, the same synopsis, the same glossary, the same schema
hint, twenty-three times.

Every provider's prompt cache works on a PREFIX: the longest run of bytes from
the START of the request that matches something it has already seen. Google's
is implicit, automatic and free above 1,024 tokens and asks only that the
repeated part come first. Anthropic's is asked for with `cache_control` and
pays above the same sort of threshold.

Two things were in the way, and neither was the cache:

* **`characters` sat in the middle of the payload.** The character sheet grows
  as a chapter is read, so it is different on every page - and it was above
  `previous_page_tail`, `keep_honorifics` and everything else. A prefix ends at
  the first byte that differs, so one moving field in the middle threw away
  every fixed byte after it. Fixed keys first now, moving keys last.
* **`keep_honorifics` sat below the moving fields**, which is a field that
  never changes at all, stranded behind ones that always do.

The model is handed exactly the same information either way. A JSON object's
key order carries no meaning to a reader; it carries the whole of this to a
cache.

The reader's own system prompt (442 tokens) is deliberately NOT marked for
Anthropic's cache: a cache write costs more than a plain read, so marking
something under the minimum is a small loss on every page rather than a
saving.
"""
import json

import pytest

from mangatl import translate as T
from mangatl.models import Page, TextRegion
from mangatl.translate import SeriesContext


def _ctx(characters=None, tail=None):
    return SeriesContext(
        synopsis="A saint's reincarnation story set in Zaldone. " * 20,
        glossary={f"term{i}": f"what term {i} means" for i in range(12)},
        characters=characters if characters is not None else {"Ada": "she/her"},
        previous_page_tail=tail or ["Ada: ...yes."],
        honorifics=True, medium="manga", target="en")


def _page(n_regions=4, first_id=1):
    from mangatl.models import Page as P
    import numpy as np
    page = P(image=np.zeros((10, 10, 3), "uint8"))
    rs = []
    for k in range(n_regions):
        r = TextRegion(id=first_id + k, bbox=(0, k * 2, 5, 2), polygon=[],
                       kind="bubble", order=k)
        r.src_text = "王宮の連中があんたを探してる"
        r.dst_text = "The palace lot are after you."
        r.speaker = "Grouve"
        rs.append(r)
    page.regions = rs
    return page


def _prefix(a: str, b: str) -> int:
    """How many leading characters two requests share."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# ---------------------------------------------------- the order of the keys

def test_the_translate_payload_puts_the_fixed_part_first():
    keys = list(T._base_payload(_page(), _ctx()))
    fixed = ["medium", "source_language", "target_language", "keep_honorifics",
             "series_context", "glossary"]
    assert keys[:len(fixed)] == fixed, keys
    moving = keys[len(fixed):]
    assert "characters" in moving and "regions" in moving, keys
    # nothing fixed may hide behind something that moves
    assert moving.index("characters") < moving.index("regions")


def test_the_proofread_payload_puts_the_fixed_part_first():
    """The SAME fixed part as the translator's, in the same order.

    `keep_honorifics` joined it when the proofreader turned out to be undoing
    a setting nobody had ever told it about - see
    `test_the_honorific_the_proofreader_took_off`. It belongs up here with the
    other fields that do not change during a run: a fixed field sitting below
    a moving one ends the cached prefix and throws away every byte after it.
    """
    keys = list(T.build_proofread_payload(_page(), _ctx()))
    fixed = ["medium", "source_language", "target_language", "keep_honorifics",
             "series_context", "glossary"]
    assert keys[:len(fixed)] == fixed, keys
    assert keys[len(fixed)] == "characters", keys


def test_both_payloads_open_with_the_same_fixed_keys():
    """One run, one set of settings, one order. A field added to one builder
    and forgotten in the other is exactly how `keep_honorifics` came to be
    obeyed at step three and ignored at step four."""
    a = list(T._base_payload(_page(), _ctx()))
    b = list(T.build_proofread_payload(_page(), _ctx()))
    n = a.index("characters")
    assert b[:n] == a[:n], (a[:n], b[:n])


def test_two_pages_of_one_chapter_share_a_long_prefix():
    """The point, measured: page two's request begins with page one's request
    and only parts company where the pages actually differ."""
    ctx = _ctx()
    a = json.dumps(T._base_payload(_page(4, 1), ctx), ensure_ascii=False, indent=1)
    b = json.dumps(T._base_payload(_page(6, 90), ctx), ensure_ascii=False, indent=1)
    shared = _prefix(a, b)
    # the synopsis alone is ~900 characters, and the glossary follows it
    assert shared > 1200, f"only {shared} characters of prefix in common"
    # ...and the shared part reaches the end of the glossary
    assert '"glossary"' in a[:shared]
    # (with the same character sheet on both pages the prefix runs further
    # still - that is a bonus, not a requirement. What must hold is that the
    # fixed part is inside it, which the growing-sheet test below pins down.)


def test_a_growing_character_sheet_does_not_cut_the_prefix_short():
    """The sheet grows page by page - that is what it is for. It must not take
    the synopsis and the glossary down with it."""
    page = _page()
    early = json.dumps(T._base_payload(page, _ctx({"Ada": "she/her"})),
                       ensure_ascii=False, indent=1)
    late = json.dumps(
        T._base_payload(page, _ctx({"Ada": "she/her", "Grouve": "he/him",
                                    "Leonora": "she/her, formal"})),
        ensure_ascii=False, indent=1)
    shared = _prefix(early, late)
    assert shared > 1200, f"a longer character sheet cut the prefix to {shared}"
    assert '"glossary"' in early[:shared]


def test_the_same_holds_for_proofreading():
    ctx = _ctx()
    a = json.dumps(T.build_proofread_payload(_page(4, 1), ctx),
                   ensure_ascii=False, indent=1)
    b = json.dumps(T.build_proofread_payload(_page(6, 90), ctx),
                   ensure_ascii=False, indent=1)
    shared = _prefix(a, b)
    assert shared > 1000, f"only {shared} characters of prefix in common"
    assert '"glossary"' in a[:shared]


def test_a_different_chapter_does_not_share_the_prefix():
    """A cache hit across two different series would be a bug, not a saving -
    it would mean the synopsis and glossary were not in the request."""
    a = json.dumps(T._base_payload(_page(), _ctx()), ensure_ascii=False, indent=1)
    other = SeriesContext(synopsis="Something else entirely.",
                          glossary={"x": "y"}, medium="manhwa", target="es")
    b = json.dumps(T._base_payload(_page(), other), ensure_ascii=False, indent=1)
    assert _prefix(a, b) < 200


# ------------------------------------------------ Anthropic's marked blocks

def test_a_long_system_prompt_is_marked_for_the_cache():
    sysm = "x" * (T.CACHE_MIN_TOKENS * 4 + 10)
    blocks = T._system_blocks(sysm)
    assert isinstance(blocks, list) and len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == sysm
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_a_short_one_is_left_alone():
    """A cache WRITE costs more than a plain read. Marking something under the
    minimum is a loss on every page, not a saving."""
    sysm = "x" * 100
    assert T._system_blocks(sysm) == sysm
    assert not T._cacheable(sysm)


def test_the_real_prompts_land_on_the_right_side_of_the_line():
    """Every real prompt is marked for the cache exactly when it clears the
    minimum, and `coins.SHAPES` prices it the same way.

    This used to assert that the READER's prompt was under the line - *"if that
    ever changes, this says so rather than quietly costing money"*. It changed,
    and the test did its job: the reader was taught to keep the marks a line
    carries - a heart, a star, a music note - and the prompt went 4,012 to
    4,438 characters, past the 4,096 `_cacheable` wants.

    The answer to the question it asked - *worth caching?* - is that the
    caching is automatic and began the moment the prompt grew. What was NOT
    automatic is the PRICE: `SHAPES["ocr"].sys_in` still said 552 and still sat
    under the floor, so the estimate went on charging a prompt twice that size
    at full input rate instead of at a tenth.

    That is the money this test is really about, so it is what it checks now.
    Which side of the line a prompt lands on is READ OFF `_cacheable` rather
    than written down - a figure in a test is a figure somebody has to notice.

    It does NOT check that `sys_in` equals the prompt's length. The first
    version did, at four characters to the token, and went red on `translate`:
    16,593 characters against a `sys_in` of 2,086, which is eight to the token.
    Four is an English rule of thumb and `SHAPES["translate"]` was fitted to a
    real invoice, so the test was wrong and the number may or may not be. Where
    the ratio is known good the size IS pinned - see
    `test_what_kind_of_box_this_is.py` - and here the claim is only the one
    that can be made exactly.
    """
    from mangatl import coins
    from mangatl import kinds as K
    prompts = {"translate": T.build_system("manga", "en"),
               "ocr": T.build_ocr_system(T.source_language("manga", "")),
               "proofread": T.build_proofread_system(),
               "label": T.build_label_system(
                   K.labelling_vocabulary(K.migrate([], seed=True)))}
    for step, text in prompts.items():
        sh = coins.SHAPES[step]
        assert (coins.cached_tokens(sh, "claude-sonnet-5") > 0) \
            is T._cacheable(text), (step, len(text), sh.sys_in)


def test_both_turns_send_the_marked_blocks():
    """Text and vision alike - a change that only reaches one of them saves
    half of what it says it does."""
    import inspect
    for fn in (T._ask, T._ask_vision):
        src = inspect.getsource(fn)
        assert "_system_blocks(system)" in src, fn.__name__
        assert "system=system," not in src, \
            f"{fn.__name__} still sends the bare string"
