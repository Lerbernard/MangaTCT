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
    """Not a list in a document somewhere - the page itself says what it is
    waiting for, which is why it cannot go stale.

    This used to name `ba-before.jpg` as one of the holes. It is not a hole
    any more: the before/after is shot, and so is every other slot the page
    asks for except the manhua one, which needs a Chinese chapter nobody
    here has. So what is asserted is the MECHANISM - every hole the build
    reports carries a filename and a sentence saying what to photograph -
    and the count is left to say whatever is true on the day.
    """
    b = _build()
    b.WANTED.clear()
    page = b.build()
    for name, want in b.WANTED:
        assert want.strip(), name
        assert name.strip(), want
        # ...and the hole is drawn where the picture will go, carrying its
        # own name, so nobody has to come here to find out what is missing.
        assert name.split(" / ")[0] in page, name
    # A slot whose picture EXISTS is the picture and nothing else.
    assert "ba-before.jpg" not in [n for n, _w in b.WANTED], \
        "the before/after is shot - the most important picture on the page"
    assert 'src="assets/ba-before.jpg"' in page


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
    manhwa = [f for f in b.FORMATS if "manhwa" in f["media"]][0]
    assert any("three and a half times as tall as they are wide" in d
               for _t, d in manhwa["good"]), \
        "the height is said as a shape now, the way the app says it"
    assert not any("quietest row" in d for _t, d in manhwa["good"]), \
        "the page must not still promise a cut the app stopped making"
    assert faq in html


def test_the_page_names_the_languages_it_can_translate_into(html):
    from mangatl.translate import TARGETS
    assert len(TARGETS) == 4
    assert "English, Spanish, Portuguese and French" in html


# -------------------------------------------------------- the three formats

def test_every_format_the_app_supports_is_on_the_page(html):
    """lee: *"add a section for manga mnahwa manhua and esplain how we deal
    with each"*, and later *"so for the mnahua just skip it or jys lump in
    mnhwa and manhua as one"*.

    Lumped - because the APP lumps them. `STRIP_MEDIA` is the set
    `{manhwa, manhua}`, `MEDIA` gives both `rtl: False`, `LANG_ENGINE` sends
    both to easyocr, and `BIG_SFX_BY_MEDIUM` overrides manga alone. Three
    panels claimed a distinction the code does not make.

    So a panel now covers one or more media, and what is checked is that
    every medium the app supports is covered by EXACTLY ONE of them - which
    is a stronger guarantee than the old per-id one: a format added to
    `MEDIA` and forgotten on the page fails here.
    """
    from mangatl.translate import MEDIA
    b = _build()
    assert 'id="formats"' in html
    covered = [m for f in b.FORMATS for m in f["media"]]
    assert sorted(covered) == sorted(MEDIA), (covered, list(MEDIA))
    assert len(covered) == len(set(covered)), "a medium in two panels"
    for f in b.FORMATS:
        assert f'id="f-{f["id"]}"' in html, f["id"]
        assert f'id="t-{f["id"]}"' in html, f["id"]
        # ...and every medium it covers is NAMED, so somebody looking for
        # the word "manhua" finds it.
        for m in f["media"]:
            assert m in html.lower(), m


def test_each_format_says_its_language_and_its_direction(html):
    """The two facts that actually change between them, and the two a reader
    is deciding on. Checked against `MEDIA` so the page cannot drift from the
    code — the direction especially, since getting it backwards numbers a
    whole chapter the wrong way."""
    from mangatl.translate import MEDIA
    b = _build()
    for f in b.FORMATS:
        for medium in f["media"]:
            m = MEDIA[medium]
            assert m["source"] in f["lang"], (f["id"], medium)
            want = "Right to left" if m["rtl"] else "Left to right"
            assert f["dir"] == want, (f["id"], medium)
        assert f'<span class="chip">{f["lang"]}</span>' in html
    # ...and the directions really are in the panel markup, not just the tab.
    lr = sum(1 for f in b.FORMATS if f["dir"] == "Left to right")
    rl = sum(1 for f in b.FORMATS if f["dir"] == "Right to left")
    assert html.count('class="chip">Left to right</span>') == lr
    assert html.count('class="chip">Right to left</span>') == rl
    assert rl == 1, "manga, and only manga"


def test_a_panel_shows_a_picture_of_every_language_it_claims(html):
    """lee: *"i added the manhua folder"* - and the panel that says "one
    route, two languages" now shows both, because a claim like that is the
    kind a reader checks by looking rather than by believing.

    Held as a rule, not as a count: a panel covering two media carries at
    least two pictures, each with its own caption saying which is which.
    """
    b = _build()
    for f in b.FORMATS:
        assert len(f["imgs"]) >= len(f["media"]), f["id"]
        for pic in f["imgs"]:
            assert pic["file"].endswith((".jpg", ".png", ".gif")), pic
            assert pic["want"].strip() and pic["cap"].strip(), pic["file"]
            assert f'<figcaption>{pic["cap"]}</figcaption>' in html, pic["file"]
    # ...and each panel's pictures are distinct files, so a merged panel
    # cannot quietly show the same screenshot twice.
    for f in b.FORMATS:
        files = [pic["file"] for pic in f["imgs"]]
        assert len(files) == len(set(files)), f["id"]


def test_the_chinese_side_says_how_much_it_has_actually_been_run(html):
    """It used to say the Chinese path had never been run on a real page.
    A 41-page manhua later that is false, and the panel says what was
    measured instead - including that one chapter is not a body of
    evidence."""
    b = _build()
    web = [f for f in b.FORMATS if "manhua" in f["media"]][0]
    rough = " ".join(t + " " + d for t, d in web["rough"])
    assert "41-page manhua" in rough
    assert "not a body of evidence" in rough
    assert "has not been run" not in rough, "that stopped being true"


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
    b = _build()
    assert 'role="tablist"' in html
    # Counted off the tables rather than typed, so merging two format panels
    # into one (manhwa + manhua) moves this on its own.
    assert html.count('role="tab"') == len(b.FORMATS) + len(b.TABS)
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


# ------------------------------------------------- the numbers on the page

def _site_costs():
    import importlib.util
    from where import PKG
    spec = importlib.util.spec_from_file_location(
        "site_costs", str(PKG / "tools" / "site_costs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_cost_table_on_the_site_is_what_coins_py_says_today():
    """`site/costs.js` is generated. This is the test that makes generated
    mean CURRENT.

    The pricing page used to carry six hand-typed figures. They were right the
    day they were typed; `coins.py` then gained thinking-token output, prompt
    caching and the drift correction, every one of them moved, and nothing
    anywhere noticed. A chapter the page priced at 28 coins was 14, and one it
    priced at 268 was 237. A sales page cannot audit itself, so this does.
    """
    from where import PKG
    got = (PKG / "site" / "costs.js").read_text(encoding="utf-8")
    assert got == _site_costs().js(), \
        "site/costs.js is stale. Run: python tools/site_costs.py"


def test_the_models_named_on_the_landing_page_are_the_ones_you_can_buy():
    """`build.py` may import nothing but the standard library - the site
    workflow installs no dependencies and depends on that staying true - so
    the list of models is written out there by hand. This is what stops the
    hand-written copy and the generated one drifting: a model dropped from the
    calculator cannot linger on the sales page beside it."""
    import re
    from where import PKG
    src = (PKG / "site" / "build.py").read_text(encoding="utf-8")
    block = src.split("AIS = [", 1)[1].split("\n]", 1)[0]
    named = re.findall(r'\(\s*"([^"]+)"', block)
    want = [name for _id, name, _b, _w in _site_costs().SHOW]
    assert named == want, (named, want)

    # ...and every blurb is the same sentence in both places, so the page and
    # the calculator cannot describe the same model differently.
    why = re.findall(r'"([^"]{20,})"\),', block)
    assert why == [w for _i, _n, _b, w in _site_costs().SHOW], why


# ------------------------------------------------------------- the house style

def _rendered(html):
    """Just the words. Comments and script and style are not what a reader
    reads, and a rule about punctuation is a rule about what they read."""
    import re
    out = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    out = re.sub(r"<script\b.*?</script>", " ", out, flags=re.S | re.I)
    out = re.sub(r"<style\b.*?</style>", " ", out, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", out)


def test_no_page_uses_an_em_dash_or_a_middot():
    """lee: *"avoid using em dahes and use rehulat dahses and vertical bars
    when needed"*.

    Asked of the RENDERED text rather than of the file, because a comment is
    not something anybody reads and a rule that fails on one is a rule people
    start working around."""
    from where import PKG
    for name in ("index.html", "pricing.html", "account.html", "signin.html",
                 "tutorial.html"):
        words = _rendered((PKG / "site" / name).read_text(encoding="utf-8"))
        assert "—" not in words, f"{name}: em dash"
        assert "–" not in words, f"{name}: en dash"
        assert "·" not in words, f"{name}: middot, use a vertical bar"


# ------------------------------------------------------------- the guide

def _tutorial():
    from where import PKG
    return (PKG / "site" / "tutorial.html").read_text(encoding="utf-8")


def test_the_guide_is_a_page_and_the_landing_page_points_at_it():
    """lee: *"make a very compriensive tutorila page ... add that as a page
    on the website"*. Linked from BOTH the built page and its source, so the
    next `build.py` run keeps the link rather than erasing it."""
    from where import PKG
    for f in ("index.html", "build.py"):
        src = (PKG / "site" / f).read_text(encoding="utf-8")
        assert 'href="tutorial.html"' in src, f


def test_the_guide_is_tabs_and_sub_tabs_not_a_wall():
    """lee: *"make it organoised in tabs and sub tabs ... dont make a block
    of text"*. One top strip, three sub strips, all real tab semantics - the
    same aria contract the landing page's strips keep, so a keyboard reaches
    every one."""
    page = _tutorial()
    for strip in ("maintabs", "steptabs", "boxtabs", "settabs"):
        assert f'id="{strip}"' in page, strip
        assert f"wire('{strip}')" in page, f"{strip} is wired"
    assert page.count('role="tab"') >= 16, "five main tabs and the sub tabs"
    assert page.count('role="tabpanel"') >= 16
    assert "keydown" in page and "ArrowRight" in page, "arrow keys work"


def test_every_step_and_every_box_tool_has_its_place_in_the_guide():
    """Comprehensive means the seven steps by name, the three box types, and
    the tools lee asked for this week: the select square, merge, the
    detector cards."""
    page = _tutorial()
    for word in ("Find text", "Read text", "Translate", "Proofread", "Clean",
                 "Typeset", "Export"):
        assert word in page, word
    for word in ("Bubble text", "Freefloat text", "Sound effect",
                 "Select boxes", "merge the selected boxes",
                 "detector cards" if "detector cards" in page else "Detectors"):
        assert word in page, word
    # ...and the keys, shown as keys.
    for key in ("S", "M", "L", "Del", "Esc"):
        assert f"<kbd>{key}</kbd>" in page, key


def test_the_guide_shows_real_pictures_and_the_pairs_are_pairs():
    """lee: *"include picture and begore and after"*. Every tut-* picture the
    page asks for ships with it (the ui-* and clip-* ones are the landing
    page's own and already on disk), and before never appears without its
    after."""
    import re
    from where import PKG
    page = _tutorial()
    asked = set(re.findall(r"assets/(tut-[A-Za-z0-9_.\-]+)", page))
    assert len(asked) >= 10, "a guide with fewer pictures than tabs"
    for name in asked:
        assert (PKG / "site" / "assets" / name).exists(), name
    for pair in ("find", "clean"):
        assert f"tut-{pair}-before" in page and f"tut-{pair}-after" in page
    # every picture explains itself to a screen reader too
    assert page.count("<img") == page.count('alt="'), "an img without alt"


def test_the_guide_speaks_to_somebody_new():
    """lee: *"someone whose never usd this before can reed it"*. The words a
    first-timer needs are on the page in plain English, and the jargon that
    would stop them is not."""
    page = _tutorial()
    for phrase in ("first time", "Add your pages", "costs nothing"):
        assert phrase in page, phrase
    import re
    low = _rendered(page).lower()
    for jargon in ("onnx", "yolo", "checkpoint", "regression", "pipeline.js",
                   "bbox", "iou"):
        # whole words - "previous" carries "iou" and is fine
        assert not re.search(r"\b%s\b" % re.escape(jargon), low), \
            f"{jargon} is not a word for a beginner"


def test_the_password_link_is_written_the_way_people_say_it():
    """lee, on "Forgotten your password?": *"are you serious?"*"""
    from where import PKG
    page = (PKG / "site" / "signin.html").read_text(encoding="utf-8")
    assert "Forgot your password?" in page
    assert "Forgotten" not in page


def test_proofreading_is_offered_as_a_choice_and_not_as_a_step():
    """lee: *"make it so that proffsetting is optional and is theer for better
    quality"*. It is a second pass for quality, not a part of translating, and
    a page that lists it between Translate and Clean has told somebody it is
    compulsory."""
    from where import PKG
    page = (PKG / "site" / "index.html").read_text(encoding="utf-8")
    proof = page[page.index("Proofread"):page.index("Proofread") + 700]
    assert "optional" in proof.lower(), proof[:200]
    pricing = (PKG / "site" / "pricing.html").read_text(encoding="utf-8")
    assert "Proofreading is optional" in pricing
    assert 'data-step="proofread"' in pricing, \
        "and it has to be a thing you can switch off in the calculator"


def test_every_page_carries_both_themes_and_the_control():
    """The media query is the default and the attribute is the decision. A
    page with the tokens and no boot script flashes the wrong theme on every
    load; one with the boot script and no tokens does nothing at all."""
    from where import PKG
    css = (PKG / "site" / "style.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: light" in css
    assert 'html[data-theme="light"]' in css and 'html[data-theme="dark"]' in css

    for name in ("pricing.html", "account.html", "signin.html"):
        page = (PKG / "site" / name).read_text(encoding="utf-8")
        assert "localStorage.getItem('tct-theme')" in page, name
        assert 'id="theme"' in page, name
        # The dead man. These pages hide their sections for the reveal, and
        # the thing that reveals them comes from a CDN.
        assert "dataset.chrome" in page, name

    built = (PKG / "site" / "index.html").read_text(encoding="utf-8")
    assert "prefers-color-scheme:light" in built
    assert 'html[data-theme="light"]' in built
    assert "tct-theme" in built


# ------------------------------------------- the gaps the guide used to have

def test_the_guide_names_every_settings_screen_the_app_actually_has():
    """#160. The guide covered four Settings screens out of ten, and three of
    the rail's own headings - Language & direction, Translation, Page cleaning
    - were never written down anywhere a person could read them.

    The rail is read OUT OF THE APP rather than typed here, so adding a screen
    to Settings and not to the guide is a failing test rather than a thing
    somebody notices six months later.
    """
    import html
    import re
    from where import PKG
    app = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    # The Settings rail and not the File screen's, which wears the same class:
    # a Settings screen is one `setSettingsTab` opens.
    rail = re.findall(r"onclick=\"setSettingsTab\('[^']+'\)\"[^>]*>([^<]+)<", app)
    rail = [html.unescape(x).strip() for x in rail]
    assert len(rail) >= 10, rail

    def flat(s):
        # Entities, and the non-breaking spaces that keep a heading off two
        # lines, are typography rather than words.
        return re.sub(r"\s+", " ", html.unescape(s).replace("\xa0", " "))

    page = flat(_rendered(_tutorial()))
    missing = [name for name in rail if flat(name) not in page]
    assert not missing, "Settings screens the guide never names: %s" % missing


def test_the_guide_says_which_of_the_two_translation_screens_is_which():
    """`wording` is labelled "Translation" and `translation` is labelled "AI
    models" - two neighbours in the rail, one about words and one about the
    machine. A guide that lists both and distinguishes neither is worse than
    one that lists neither."""
    page = _rendered(_tutorial())
    assert "AI models" in page and "Translation" in page
    low = page.lower()
    assert "about the words, not the machine" in low or \
        "is about the words" in low, "the difference is stated"
    assert "keep honorifics" in low, "the switch that screen is really for"


def test_the_guide_covers_the_beta_pill_and_how_an_update_arrives():
    """Somebody on a self-updating beta needs to know what the pill says, that
    an update never lands mid-chapter, and that the old version is kept."""
    page = _rendered(_tutorial())
    low = page.lower()
    for phrase in ("beta 1.0.0", "next start", "previous version"):
        assert phrase in low, phrase
    assert "checks when it starts" in low or "checks for a new version" in low


def test_the_guide_tells_somebody_how_to_report_a_problem():
    """And tells them the truth about what is in the box: no key ever, and
    nothing is sent by the app - the person copies it themselves."""
    page = _rendered(_tutorial())
    low = page.lower()
    assert "report a problem" in low
    assert "never the key" in low or "anything key-shaped" in low
    assert "copy to clipboard" in low, "the app transmits nothing by itself"
    assert "read it before you send it" in low


def test_the_guide_covers_the_tools_that_had_no_words_anywhere():
    """Cut / join, Special characters, the curve picker and inner glow all
    shipped without a sentence about them on any page."""
    page = _rendered(_tutorial())
    low = page.lower()
    assert "cut / join" in low
    for kind in ("arch", "sag", "wave", "rise"):
        assert kind in low, "curve kind %s" % kind
    assert "inner glow" in low and "outer glow" in low
    assert "special characters" in low


def test_the_curve_and_glow_the_guide_describes_are_the_ones_in_the_app():
    """Four curve kinds and two glows, named out of the panel that draws
    them. A fifth curve added to the app fails here."""
    import re
    from where import PKG
    js = (PKG / "static" / "js" / "panels.js").read_text(encoding="utf-8")
    kinds = re.search(r"\[([^\]]*)\]\.map\(k=>\{", js)
    assert kinds, "the curve-kind list moved"
    kinds = re.findall(r"'(\w+)'", kinds.group(1))
    assert set(kinds) == {"arch", "sag", "wave", "rise"}, kinds
    low = _rendered(_tutorial()).lower()
    for k in kinds:
        assert k in low, k
    assert "lyIGlow" in js and "iglow" in js, "there is an inner glow to document"


def test_the_guide_says_manhua_now_that_there_is_one():
    """It said "Manhwa too" and nothing about Chinese at all, while the app
    has had a manhua route and the landing page now shows a Chinese chapter.
    It also has to keep saying how little that has been run."""
    page = _rendered(_tutorial())
    low = page.lower()
    assert "manhua" in low
    assert "41 pages" in low, "the honest size of the Chinese evidence"
    assert "korean has had many" in low
