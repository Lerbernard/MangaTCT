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
manifest the installed app reads, and the button is `/get/latest/installer`
- this site's own address, answered by a function that reads that same
manifest - which is right whatever the version is.

**A link to GitHub.** lee: *"there should be no link to github on the
website"*. The files live on the project's releases, but no address the
site prints says so: downloads go through `/get/`, the list of versions and
checksums is `releases.html`, the license is `license.html`.

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
         "pricing.html", "account.html", "signin.html", "releases.html",
         "license.html")


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
    """Fetch blocked, JS off - the button in the HTML is the site's own
    address for the current installer, answered by the `get` function, so
    it is right whatever the version is and nothing is typed into it."""
    btn = page[page.index('id="dlbtn"'):]
    btn = btn[:btn.index("</a>")]
    assert 'href="/get/latest/installer"' in btn
    assert 'href="#"' not in page
    js = page[page.index("<script>"):]
    assert "b.href" not in js, "the script fills the label and the size, never the address"


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
    """The GPL asks that whoever gets the binary can get the source. The app
    zip IS the source, and it is offered from this site's own address, with
    the license itself a page of this site."""
    assert "GNU GPL v3" in page
    assert 'href="/get/latest/app"' in page
    assert 'href="license.html"' in page
    lic = (SITE / "license.html").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in lic and "Version 3, 29 June 2007" in lic
    import html
    assert html.escape((PKG / "LICENSE").read_text(encoding="utf-8"))[:2000] in lic, \
        "the license page carries the repo's LICENSE, unchanged"


def test_nothing_on_the_site_links_to_github(index):
    """lee: *"there should be no link to github on the website"*. Files
    still live on the project's releases - the workflow puts them there and
    installed copies fetch updates from there - but no address the site
    prints says so. Every download is `/get/<version>/<what>`; the releases
    list and the license are pages of this site. A `fetch` of data is not a
    link and is allowed; an `href` is what a person sees, and is not."""
    for name in PAGES:
        text = index if name == "index.html" else (SITE / name).read_text(encoding="utf-8")
        hrefs = re.findall(r'href="([^"]+)"', text)
        bad = [h for h in hrefs if "github" in h.lower()]
        assert not bad, (name, bad)
        assert "Source on GitHub" not in text, name


def test_every_download_goes_through_the_sites_own_door(page):
    """`/get/**` is a Hosting rewrite to the `get` function, which turns a
    version and a file kind into the real file. Held here: the rewrite is
    in firebase.json, the function knows the three kinds and `latest`, and
    the releases page links the same way."""
    import json
    fb = json.loads((PKG / "firebase.json").read_text(encoding="utf-8"))
    rw = fb["hosting"].get("rewrites", [])
    assert any(r.get("source") == "/get/**" and r.get("function", {}).get("functionId") == "get"
               for r in rw), rw
    fn = (PKG / "firebase" / "functions" / "index.js").read_text(encoding="utf-8")
    assert "export const get = onRequest" in fn
    assert "(latest|\\d+\\.\\d+\\.\\d+)\\/(installer|app|checksums)" in fn
    assert "const REPO = 'Lerbernard/MangaTCT'" in fn
    assert "https://raw.githubusercontent.com/${REPO}/main/manifest.json" in fn, \
        "latest is what the launcher's manifest says it is"
    rel = (SITE / "releases.html").read_text(encoding="utf-8")
    assert "/get/' + esc(v) + '/installer" in rel
    # lee: *"make it just be the installer and remove the long string at the
    # end"* - one button a version, no checksum column, no source row
    assert "/get/' + esc(v) + '/app" not in rel and "digest" not in rel
    assert 'href="releases.html"' in page


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
    # Two link columns now, Product and Help; every href in both is checked.
    foot = index[index.index("<footer"):]
    hrefs = re.findall(r'<nav class="footlinks"[^>]*>(.*?)</nav>', foot, re.S)
    assert len(hrefs) >= 2, "the footer has its link columns"
    hrefs = re.findall(r'href="([^"]+)"', "".join(hrefs))
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

PREFIXED = {"download.html": "dl", "releases.html": "rl", "license.html": "lc"}


@pytest.mark.parametrize("name,prefix", sorted(PREFIXED.items()))
def test_it_coins_no_class_style_css_already_owns(name, prefix):
    """The lesson from the guide page's three bugs: a page that loads
    style.css must not name a class or a variable somebody else owns. The
    three pages built on the download page's chrome each own a prefix."""
    css = (SITE / "style.css").read_text(encoding="utf-8")
    theirs = set(re.findall(r"\.([a-zA-Z][\w-]*)\s*[,{:]", css))
    text = (SITE / name).read_text(encoding="utf-8")
    block = text[text.index("<style>"):text.index("</style>")]
    mine = set(re.findall(r"\.([a-zA-Z][\w-]*)\s*[,{:]", block))
    clash = mine & theirs
    assert clash <= {"brand", "mk", "wm", "navb", "lede", "mut", "on"}, clash
    assert all(m.startswith(prefix) for m in mine - theirs), (name, sorted(mine - theirs))


@pytest.mark.parametrize("name", sorted(PREFIXED))
def test_it_names_no_variable_style_css_does_not_define(name):
    css = (SITE / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    text = (SITE / name).read_text(encoding="utf-8")
    block = text[text.index("<style>"):text.index("</style>")]
    used = set(re.findall(r"var\((--[\w-]+)\)", block))
    assert used <= defined, (name, used - defined)


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
