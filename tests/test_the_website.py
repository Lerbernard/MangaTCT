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
