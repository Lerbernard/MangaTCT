"""The landing page, and the two things about it that go wrong quietly.

**A picture that is not there yet.** Every image on this page is a real
screenshot, and lee supplies them as he takes them. So `build.slot()` renders a
labelled dashed hole for anything missing rather than a broken image, and the
test below is what stops a broken one shipping instead.

**A claim that stopped being true.** The page sold four AI services after the
app cut down to three, and told people to cut up their own webtoon strips after
the app started doing it for them. Marketing copy has no compiler; these are the
compiler.
"""
import re
import subprocess
import sys

import pytest

from where import PKG

SITE = PKG / "site"
INDEX = SITE / "index.html"
STANDALONE = SITE / "mangatct-site-standalone.html"


def _build():
    """The builder, imported without running it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sitebuild", SITE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def html():
    """The page as `build.py` MAKES it, not as it sits on disk.

    Every claim below is a claim about the builder — that is where a wrong one
    would be introduced and where it would have to be fixed. Whether the file
    on disk has been rebuilt since is a different question, asked once in
    `test_the_website_is_built.py`.
    """
    return _build().build()


# --------------------------------------------------------- no broken pictures

def test_every_picture_the_page_asks_for_is_really_there(html):
    """The one fault a visitor sees before they read a word."""
    b = _build()
    assert b.missing(html) == []


def test_a_picture_that_is_missing_leaves_a_labelled_hole():
    """lee: *"leave spots for screenshot and picture ill give yu later"*. The
    hole carries the FILENAME, because that is the one thing you need to know
    to fill it."""
    b = _build()
    b.WANTED.clear()
    out = b.slot("nothing-here-yet.jpg", "alt text", "what to photograph")
    assert "<img" not in out
    assert "nothing-here-yet.jpg" in out and "what to photograph" in out
    assert b.WANTED == [("nothing-here-yet.jpg", "what to photograph")]
    # ...and a picture that IS there is just the picture.
    real = b.slot("mark.svg", "the mark")
    assert real.startswith("<img") and "assets/mark.svg" in real


def test_the_holes_are_on_the_page_and_named(html):
    """Not a list in a document somewhere — the page itself says what it is
    waiting for, which is why it cannot go stale."""
    b = _build()
    b.WANTED.clear()
    b.build()
    assert b.WANTED, "there should still be shots to take"
    for name, want in b.WANTED:
        assert want.strip(), name
    assert "ba-before.jpg" in " ".join(n for n, _w in b.WANTED)


# --------------------------------------------------- what the page claims

def test_the_page_offers_the_services_the_app_offers(html):
    """Three, since the day OpenAI, Groq, Cerebras and Ollama came out of the
    menus. A landing page naming a service the app cannot reach is a support
    ticket that starts with "but your website says"."""
    from mangatl.project import SERVICES
    for _svc, label in [("anthropic", "Claude"), ("gemini", "Google AI Studio"),
                        ("openrouter", "OpenRouter")]:
        assert label in html, label
    assert len(SERVICES) == 3
    for gone in ("OpenAI", "Groq", "Cerebras"):
        assert gone not in html, gone


def test_the_page_says_the_app_cuts_webtoon_strips_up(html):
    """It used to tell people to do it themselves. `strip.py` has done it on
    upload since — at the gutters, near 2,400px — and the old sentence sent
    manhwa readers away for no reason.

    Asked of the FAQ ANSWER and of the manhwa panel separately: they are
    written in two places and somebody reads only one of them.
    """
    b = _build()
    faq = dict(b.FAQ)["What about long webtoon strips?"]
    assert "re-cut into pages near 2,400px" in faq
    assert "cut it up first" in faq, "and it should still say where the limit is"
    manhwa = [f for f in b.FORMATS if f["id"] == "manhwa"][0]
    assert any("2,400px" in d for _t, d in manhwa["good"])
    assert faq in html


def test_the_page_names_the_languages_it_can_translate_into(html):
    from mangatl.translate import TARGETS
    assert len(TARGETS) == 4
    assert "English, Spanish, Portuguese and French" in html


# -------------------------------------------------------- the three formats

def test_there_is_a_section_for_each_format(html):
    """lee: *"add a section for manga mnahwa manhua and esplain how we deal
    with each"*."""
    from mangatl.translate import MEDIA
    assert 'id="formats"' in html
    for medium in MEDIA:
        assert f'id="f-{medium}"' in html, medium
        assert f'id="t-{medium}"' in html, medium


def test_each_format_says_its_language_and_its_direction(html):
    """The two facts that actually change between them, and the two a reader
    is deciding on. Checked against `MEDIA` so the page cannot drift from the
    code — the direction especially, since getting it backwards numbers a
    whole chapter the wrong way."""
    from mangatl.translate import MEDIA
    b = _build()
    for f in b.FORMATS:
        m = MEDIA[f["id"]]
        assert f["lang"] == m["source"], f["id"]
        want = "Right to left" if m["rtl"] else "Left to right"
        assert f["dir"] == want, f["id"]
        assert f'<span class="chip">{f["lang"]}</span>' in html
    # ...and all three really are in the panel markup, not just the tab.
    assert html.count('class="chip">Left to right</span>') == 2
    assert html.count('class="chip">Right to left</span>') == 1


def test_every_format_admits_what_is_rough_about_it():
    """The point of the section. A page that only lists strengths for the two
    formats that were added later is a page that gets found out on somebody's
    own chapter, and then nothing else on it is believed either."""
    b = _build()
    for f in b.FORMATS:
        assert f["rough"], f["id"]
        for title, body in f["rough"]:
            assert title.strip() and len(body) > 40, f["id"]


def test_the_reader_that_does_not_ship_is_named_as_such(html):
    """`requirements.txt` installs manga-ocr and leaves easyocr commented out,
    so Korean and Chinese have no LOCAL reader out of the box. Saying so is the
    difference between a known limit and a bug report."""
    req = (PKG / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^#\s*easyocr", req, re.M), \
        "easyocr now ships — the site should stop warning about it"
    assert "pip install easyocr" in html


# ---------------------------------------------------------------- the shell

def test_the_footer_says_who_built_it(html):
    """lee: *"at the footer make it say built by lmb techology"*."""
    assert "Built by <b>LMB Technology</b>" in html


def test_the_page_works_with_no_javascript(html):
    """Everything the script does is an enhancement. Nothing may be hidden by
    the STYLESHEET, or a reader with JS off gets a page with holes in it."""
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ".nojs .rise{opacity:1" in style.replace("\n", ""), \
        "the reveal must start visible for a reader whose observer never runs"
    # The only thing hidden without JS is the inactive tab panel, and each one
    # is a real section with a heading — reachable, just not on top.
    assert html.count("<section class=\"pan\"") == html.count("role=\"tabpanel\"")


def test_the_tabs_are_reachable_from_a_keyboard(html):
    """A tab strip built out of divs is a tab strip a screen reader cannot
    describe and a keyboard cannot move through."""
    assert 'role="tablist"' in html
    assert html.count('role="tab"') >= 7            # 3 formats + 4 screens
    assert 'aria-controls=' in html and 'aria-selected=' in html
    assert "ArrowRight" in html and "ArrowLeft" in html


def test_the_slider_is_a_real_slider(html):
    """The handle is an `<input type=range>` stretched over the picture at zero
    opacity, so dragging, tapping and the arrow keys all work with no pointer
    code — and a screen reader is handed a slider rather than a div."""
    b = _build()
    if b.have("ba-before.jpg") and b.have("ba-after.jpg"):
        assert 'type="range"' in html and 'aria-label="Reveal' in html
    else:
        assert "ba-before.jpg" in html, "the hole should still name both files"


def test_an_anchor_lands_below_the_sticky_header(html):
    """Every nav link jumps to a section, and the header floats over the top of
    it. Measured against the header's own height rather than against a number
    written down twice — a clearance that is merely PRESENT is a clearance that
    can be zero."""
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    clear = re.search(r"\[id\]\{scroll-margin-top:(\d+)px\}", style)
    head = re.search(r"\.hd\{[^}]*height:(\d+)px", style)
    assert clear and head, "both the clearance and the header height must be set"
    assert int(clear.group(1)) >= int(head.group(1)), \
        f"{clear.group(1)}px of clearance under a {head.group(1)}px header"


# ---------------------------------------------------- what the price promises

def test_the_pricing_page_says_the_tax_is_already_in_the_price():
    """lee: *"also make the price will include the tax"*.

    Stripe is the merchant of record and works out each country's sales tax,
    VAT or GST; with `tax_behavior: inclusive` it comes OUT of the figure
    rather than being added on top, so the number on the page is the number on
    the card in every country.

    Said twice, doing two different jobs: a mark beside each figure, because
    nobody reads a footnote before they read a price; and a sentence saying who
    is collecting it. And it must not say the opposite anywhere — a page that
    promises tax-inclusive in one place and tax-on-top in another is worse than
    one that says nothing.
    """
    from where import PKG
    page = (PKG / "site" / "pricing.html").read_text(encoding="utf-8")
    assert 'class="plustax">tax in<' in page, "each price needs the mark"
    assert "Every price includes tax" in page
    assert "Stripe" in page
    body = page.split("<body", 1)[-1]
    for wrong in ("plus tax", "before tax", "+ tax", "excluding tax"):
        assert wrong not in body, wrong
    css = (PKG / "site" / "style.css").read_text(encoding="utf-8")
    assert ".plustax{" in css, "the mark has to be smaller than the price"


def test_the_going_live_note_says_to_set_it():
    """Tax-inclusive is NOT Stripe's default, and a price's tax behaviour is
    fixed once it has been used — so the one chance to get this right is
    before the four prices exist."""
    from where import PKG
    doc = (PKG / "docs" / "going-live-with-payments.md").read_text(encoding="utf-8")
    assert "tax_behavior: inclusive" in doc
    assert "fixed once it has been used" in doc.replace("\n", " ")
    assert "not the default" in doc.lower()


def test_the_packs_on_the_page_are_the_packs_the_server_grants():
    """The page draws whatever `config/prices` holds, and `seed.js` writes that
    from `PACKS` in `purse.js` — which is also what grants the coins. One
    source. This is the test that says the chain is unbroken, because a pack
    priced on the page and unknown to the server is a Buy button that 400s."""
    import re
    from where import PKG
    purse = (PKG / "firebase" / "functions" / "purse.js").read_text(encoding="utf-8")
    block = purse.split("export const PACKS = [", 1)[1].split("];", 1)[0]
    packs = re.findall(r"id:\s*'(\w+)',\s*coins:\s*(\d+),\s*usd:\s*([\d.]+)", block)
    assert len(packs) == 4, packs
    assert [p[0] for p in packs] == ["pack1", "pack2", "pack3", "pack4"]
    seed = (PKG / "firebase" / "functions" / "seed.js").read_text(encoding="utf-8")
    assert "from './purse.js'" in seed, \
        "seed.js must read the packs rather than repeat them"
    # ...and the going-live note quotes the same four, because somebody will
    # create the Stripe products from that table.
    doc = (PKG / "docs" / "going-live-with-payments.md").read_text(encoding="utf-8")
    for pid, coins, usd in packs:
        assert f"`{pid}`" in doc, pid
        assert f"${usd}" in doc, usd
        assert f"{int(coins)}" in doc, coins


def test_the_product_copy_matches_the_packs_that_grant_the_coins():
    """The four names and prices somebody will paste into Stripe by hand.

    Stripe is the one link in this chain no test can reach — `seed.js` writes
    the price ids into Firestore but nothing can check that the $4.99 in the
    Dashboard is the $4.99 in `purse.js`. So the note they are copied FROM is
    checked instead, which is as close as it gets.
    """
    import re
    from where import PKG
    doc = (PKG / "docs" / "the-four-products.md").read_text(encoding="utf-8")
    purse = (PKG / "firebase" / "functions" / "purse.js").read_text(encoding="utf-8")
    block = purse.split("export const PACKS = [", 1)[1].split("];", 1)[0]
    packs = re.findall(r"id:\s*'(\w+)',\s*coins:\s*(\d+),\s*usd:\s*([\d.]+)", block)
    assert len(packs) == 4
    for pid, coins, usd in packs:
        assert f"`{pid}`" in doc, pid
        assert f"`${usd}`" in doc, usd
        assert f"{int(coins):,} coins" in doc, coins
    # ...and every one of them is sold tax-inclusive, which is the setting
    # that cannot be changed after the first sale.
    assert doc.count("tax inclusive") == 4
    assert "Inclusive" in doc


def test_seed_refuses_a_price_id_that_is_not_one_before_it_writes():
    """`seed.js` writes what it is given and says nothing. That is fine for a
    MISSING id — the bottom of the file reports those — and it was not fine for
    a WRONG one: a pasted `…` went in as all four, was written, was reported as
    success, and turned up as a 500 from the live buy button and
    `No such price: '…'` in a Cloud Logging query twenty minutes later.

    The check has to be BEFORE the writes, and it has to exit non-zero, or it
    is a warning scrolled past."""
    from where import PKG
    seed = (PKG / "firebase" / "functions" / "seed.js").read_text(encoding="utf-8")
    purse = (PKG / "firebase" / "functions" / "purse.js").read_text(encoding="utf-8")

    assert "export function looksLikePriceId" in purse, \
        "the shape check belongs with the packs, where vitest can reach it"
    assert "looksLikePriceId } from './purse.js'" in seed, \
        "seed.js must import it rather than repeat the regex"

    guard = seed.index("looksLikePriceId(v)")
    write = seed.index("db.doc('config/prices')")
    assert guard < write, \
        "the check has to run before anything is written, not after"
    assert "process.exit(1)" in seed[guard:write], \
        "a bad id has to stop the run, not print a warning nobody reads"
    assert "Nothing was written." in seed, \
        "and it has to say so, or somebody re-runs it in a panic"


def _seed(*args):
    """Actually run `seed.js`, with credentials it cannot use.

    It can be run: `applicationDefault()` and `getFirestore()` are both lazy,
    so nothing is authenticated and nothing is sent until a document is
    written — which means the refusal path completes, on its own, offline.
    The project id is overridden too, so that even on a machine that DOES hold
    a credential the only thing reachable is a project that does not exist.
    """
    import os
    import shutil
    import subprocess
    import pytest
    from where import PKG
    node = shutil.which("node")
    if not node:
        pytest.skip("no node")
    env = dict(os.environ,
               GOOGLE_CLOUD_PROJECT="mangatct-there-is-no-such-project",
               GOOGLE_APPLICATION_CREDENTIALS="")
    return subprocess.run(
        [node, "seed.js", *args], cwd=str(PKG / "firebase" / "functions"),
        capture_output=True, text=True, timeout=120, env=env)


def test_seed_stops_on_a_pasted_placeholder_and_says_what_it_wanted():
    """The source check above says the guard is written; this one says it
    runs. Two mutants live in the gap between those: one that turns the
    condition off, and one that leaves the whole block unreachable. Both leave
    a file that still reads as careful."""
    got = _seed("price_pack1=…", "price_pack2=price_1U1fCAPRGT41DjkSNiPmuk4f")
    assert got.returncode == 1, got.stdout + got.stderr
    assert "not a Stripe price id: price_pack1=…" in got.stderr
    # The one that WAS an id is not complained about — an error naming all four
    # when one is wrong sends you looking in the wrong place.
    assert "price_pack2" not in got.stderr
    # And it says what one looks like, because "not a price id" without an
    # example is a person guessing at the difference between prod_ and price_.
    assert "price_1U1fCAPRGT41DjkSNiPmuk4f" in got.stderr
    assert "Nothing was written." in got.stderr


def test_seed_does_not_refuse_an_id_that_is_shaped_like_one():
    """The other half. A guard that refuses everything is not a guard, and it
    would be caught here rather than by somebody with a real id in their hand
    wondering why the tool will not take it."""
    got = _seed("price_pack1=price_1U1fCAPRGT41DjkSNiPmuk4f")
    assert "not a Stripe price id" not in got.stderr
    # It gets past the guard and dies at Firestore instead, which is the point:
    # the refusal happened before the network, and this one reached it.
    assert got.returncode != 1 or "Nothing was written." not in got.stderr
