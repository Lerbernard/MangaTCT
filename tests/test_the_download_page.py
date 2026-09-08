"""The download page, and the links that used to be yellow `todo` chips.

lee picked the download route: *"lets go with teh doenload option, i still
want to be able to send out update and keep suporting teh app"*. So the site
has a door: a page that hands somebody a Windows installer, tells them the
truth about SmartScreen and about what the first start downloads, and says
how updates and support work.

Two things this file is here to stop.

**A version number typed into a page.** The site deploys when the site
changes; the app releases when the app changes. A number written into the
HTML is wrong from the first release after it, so the page reads the SAME
manifest the installed app reads, and the button falls back to
`/releases/latest`, which is right whatever the version is.

**A link that goes nowhere.** `before-deploying-the-site.md` listed two
buttons pointing at `#` with yellow chips beside them. They point somewhere
now, and the two that depend on doors lee has not built yet (Discord, an
email) are DRAWN ONLY WHEN THEY EXIST rather than pointing at `#`.
"""
import importlib.util
import re

import pytest

from where import PKG

SITE = PKG / "site"
DOWNLOAD = SITE / "download.html"
PAGES = ("index.html", "download.html", "tutorial.html", "fonts.html",
         "pricing.html", "account.html", "signin.html")


def _build():
    spec = importlib.util.spec_from_file_location("sitebuild", SITE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def page():
    return DOWNLOAD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index():
    return _build().build()


# ------------------------------------------------------------- the version

def test_the_page_names_no_version_of_its_own(page):
    """The one number on this page comes from the manifest at runtime. A
    literal here is a number that goes stale on the next release."""
    from mangatl import version as V
    assert V.__version__ not in page, "the version is read, never written"
    assert 'id="dlver"' in page
    assert "m.app && m.app.version" in page


def test_it_reads_the_same_manifest_the_launcher_does(page):
    import sys
    sys.path.insert(0, str(PKG / "launcher"))
    import mangatct_launcher as L
    got = re.search(r"var MANIFEST = '([^']+)'", page)
    assert got, "the manifest url"
    assert got.group(1) == L.MANIFEST_URL, \
        "the page and the app must look at one channel"


def test_the_button_works_with_the_script_off(page):
    """Fetch blocked, JS off, GitHub down for the raw file - the button in
    the HTML still lands on a page with the installer on it."""
    btn = page[page.index('id="dlbtn"'):]
    btn = btn[:btn.index("</a>")]
    assert "/releases/latest" in btn
    assert 'href="#"' not in page


# ---------------------------------------------------------------- the truth

def test_it_says_the_three_things_a_first_run_surprises_people_with(page):
    # 1. Windows will refuse to run it, and what to click
    assert "SmartScreen" in page
    assert "More info" in page and "Run anyway" in page
    # 2. the first start downloads models, and why they are not in the installer
    assert "200 MB" in page
    assert "redistribute" in page
    # 3. the browser is the interface, not the internet
    assert "127.0.0.1" in page


def test_it_says_what_updating_does_and_does_not_do(page):
    assert "updates itself" in page
    assert "next time you" in page, "an update never swaps a chapter mid-session"
    assert "previous version stays" in page
    assert "Report a problem" in page, "where support starts"


def test_it_says_where_the_persons_own_things_live(page):
    assert ".mangatl" in page and "untouched by updates" in page
    assert "LOCALAPPDATA" in page


def test_it_makes_the_source_offer_the_license_asks_for(page):
    assert "GNU GPL v3" in page
    assert "github.com/Lerbernard/MangaTCT" in page, \
        "the source is the project's own repo - there is no second one"


# ----------------------------------------------------------- the site links

def test_every_page_can_reach_the_download(index):
    for name in PAGES:
        text = index if name == "index.html" else (SITE / name).read_text(encoding="utf-8")
        assert 'href="download.html"' in text, name


def test_the_landing_page_leads_with_it_and_has_no_todo_chips(index):
    assert "download.html" in index
    hero = index[index.index('<section class="hero"'):index.index("</section>")]
    assert 'href="download.html"' in hero, "the first button on the page"
    assert 'class="todo"' not in index, "the yellow chips are gone"
    assert 'href="#" data-fill' not in index
    assert "footer links go here" not in index and "need a URL" not in index


def test_the_footer_links_all_go_somewhere(index):
    foot = index[index.index('<nav class="footlinks">'):]
    foot = foot[:foot.index("</nav>")]
    hrefs = re.findall(r'href="([^"]+)"', foot)
    assert hrefs, "there are some"
    assert all(h and h != "#" for h in hrefs), hrefs
    for want in ("download.html", "tutorial.html", "pricing.html"):
        assert want in hrefs, want


def test_a_door_that_does_not_exist_yet_is_not_drawn(index):
    """lee has Discord and an email coming. Until `version.SUPPORT` names
    them, the site offers neither rather than offering a dead button - and
    the moment it names them, both appear here and in the footer."""
    from mangatl import version as V
    b = _build()
    assert b.SUPPORT == V.SUPPORT, "one source, read by path in CI"
    if not V.SUPPORT["discord"]:
        assert "Discord" not in index
    else:
        assert V.SUPPORT["discord"] in index
    if not V.SUPPORT["email"]:
        assert "mailto:" not in index
    else:
        assert "mailto:" + V.SUPPORT["email"] in index
    # ...and the helper is what decides, so both places agree
    assert b.contact_links() == "" or "Discord" in b.contact_links() \
        or "Email" in b.contact_links()


# ------------------------------------------------------ borrowed stylesheet

def test_it_coins_no_class_style_css_already_owns(page):
    """The lesson from the guide page's three bugs: a page that loads
    style.css must not name a class or a variable somebody else owns."""
    css = (SITE / "style.css").read_text(encoding="utf-8")
    theirs = set(re.findall(r"\.([a-zA-Z][\w-]*)\s*[,{:]", css))
    block = page[page.index("<style>"):page.index("</style>")]
    mine = set(re.findall(r"\.([a-zA-Z][\w-]*)\s*[,{:]", block))
    clash = mine & theirs
    assert clash <= {"brand", "mk", "wm", "navb", "lede", "mut", "on"}, clash
    assert all(m.startswith("dl") for m in mine - theirs), sorted(mine - theirs)


def test_it_names_no_variable_style_css_does_not_define(page):
    css = (SITE / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    block = page[page.index("<style>"):page.index("</style>")]
    used = set(re.findall(r"var\((--[\w-]+)\)", block))
    assert used <= defined, used - defined


def test_the_guide_page_lost_its_undefined_variable_too():
    """`.note b{color:var(--fg)}` - style.css has --ink, not --fg, so the
    bolded word in every note resolved to `inherit` and was not bold-looking
    at all. Same family as the three bugs that page was fixed for once."""
    css = (SITE / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    for name in ("tutorial.html", "download.html", "fonts.html"):
        text = (SITE / name).read_text(encoding="utf-8")
        if "<style>" not in text:
            continue
        block = text[text.index("<style>"):text.index("</style>")]
        used = set(re.findall(r"var\((--[\w-]+)\)", block))
        assert used <= defined, (name, used - defined)
