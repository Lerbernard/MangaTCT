# -*- coding: utf-8 -*-
"""Faces worth using for each box type, and the half-answer that hid them.

lee: *"i want you to vcreate a pge inteh webisyte witha bunch of reciomended
fonts fro each box type and subtype anbd a link to doenload them from a
trusted website for tehe ones that rae not on the app"*.

## Why the app can only ship eleven

Every face in `fonts/` is under the SIL Open Font Licence, because that is the
only licence that lets a program somebody downloads carry a font at all -
`fonts/LICENSES.md` has the argument, and the three faces removed on
2026-08-26 are what it cost. The faces most of this craft is actually set in
are not among them **for exactly that reason**, so the honest answer is not a
smaller list, it is a list that says where each one comes from and what its
licence permits.

Three sources and no more, because a recommendation is a promise that somebody
checked: Google Fonts for everything that can be, Blambot for Anime Ace, and
Comicraft for Wild Words with its price written on the row.

## The bug the page found on the way in

`takeFonts` in the browser has said this in its own comment since it was
written:

> *One answer, four lists. Every font endpoint returns all of them so nothing
> can be redrawn from a half-updated picture.*

`/api/fonts` kept the promise. `/api/font` - the one that adds, removes and
notes a font as recently used - did not: it answered with `fonts`, `recent`
and `uploaded`, and `takeFonts` takes what it is handed::

    KIND_DEFAULTS = f.defaults || {};
    MARK_LIB      = f.marks    || [];
    SERVER_STALE  = !('defaults' in f);

So **picking a font in any dropdown** emptied the defaults table, emptied the
marks picker, and raised the flag that means *the app is older than this page*.
Every row of Box types then fell through to the project's own font and read the
same name twelve times, under a banner telling you to restart an app that was
not out of date.

That is lee's screenshot: twelve rows of `ComicNeue-Bold` under the stale line.
One `fonts_answer()` now, so a reply cannot be half a reply.
"""
import inspect
import re
from urllib.parse import urlparse

import pytest

from mangatl import fontpicks as FP
from mangatl import kinds as K


ALL_KINDS = list(K.FAMILIES) + list(K.PRELOAD_KEYS)


def _code(js):
    """JavaScript with its comments taken out.

    Every guard in this suite that reads source has been fooled once by the
    comment explaining the thing it forbids. This one bans the names of things
    that were removed, and the note left where they stood says both of them.
    """
    out = "\n".join(l.split("//", 1)[0] for l in js.splitlines())
    while "/*" in out:
        a = out.index("/*")
        b = out.find("*/", a + 2)
        if b < 0:
            break
        out = out[:a] + out[b + 2:]
    return out


# ------------------------------------------------------------- the list

def test_every_box_type_the_panel_lists_has_picks():
    """Families and sub-types alike - lee asked for both by name."""
    for key in ALL_KINDS:
        assert key in FP.PICKS, key
        assert FP.PICKS[key], key


def test_and_nothing_else_does():
    """A pick for a kind the app does not have is a row nobody can reach."""
    assert set(FP.PICKS) == set(ALL_KINDS), set(FP.PICKS) ^ set(ALL_KINDS)


def test_the_app_s_own_default_is_among_the_picks_for_its_own_type():
    """It is the face that type comes out in when nobody chooses, so leaving
    it off the recommendations would be the page disagreeing with the app."""
    from mangatl.typeset import DEFAULT_FONTS
    for key, filename in DEFAULT_FONTS.items():
        fam = filename.split("-")[0]
        names = [p.family.replace(" ", "") for p in FP.PICKS[key]]
        assert fam in names, (key, fam, names)


@pytest.mark.parametrize("key", ALL_KINDS)
def test_a_type_gets_more_than_one_answer(key):
    """One pick is not a recommendation, it is the default said twice."""
    assert len(FP.PICKS[key]) >= 3, (key, len(FP.PICKS[key]))


@pytest.mark.parametrize("key", ALL_KINDS)
def test_no_type_offers_the_same_face_twice(key):
    got = [p.family for p in FP.PICKS[key]]
    assert len(set(got)) == len(got), got


# ---------------------------------------------------------- every entry

def _all():
    return [p for picks in FP.PICKS.values() for p in picks]


def test_every_entry_names_a_family_and_never_a_file():
    """A file is what this app's own folder deals in; a family is what a
    person downloads. Mixing them is how a page tells somebody to fetch
    `ComicNeue-Bold.ttf` from a site that offers Comic Neue."""
    for p in _all():
        assert not re.search(r"\.(ttf|otf)$", p.family, re.I), p.family


def test_every_entry_comes_from_one_of_the_three_sources():
    for p in _all():
        assert p.source in FP.SOURCES, (p.family, p.source)


def test_and_the_link_goes_where_the_row_says_it_does():
    """The row names the source and the link is the promise. A row that says
    Google Fonts and links somewhere else is worse than no row."""
    for p in _all():
        host = urlparse(p.url).netloc
        home = urlparse(FP.SOURCES[p.source]["home"]).netloc
        assert host == home, (p.family, p.source, p.url)


def test_every_link_is_https():
    for p in _all():
        assert p.url.startswith("https://"), (p.family, p.url)
        assert FP.SOURCES[p.source]["home"].startswith("https://"), p.source


def test_every_entry_says_what_its_licence_permits():
    """"Free to download", "free to use in work you sell" and "free to
    redistribute" are three different permissions, and the difference is the
    whole reason half of these are links rather than files."""
    for p in _all():
        assert p.licence.strip(), p.family


def test_anything_that_costs_money_says_so_on_the_row():
    """Wild Words is here because leaving the industry's actual answer off a
    page about recommended faces would be a kind of lie. Its price is on the
    row so nobody clicks it expecting a free download."""
    paid = [p for p in _all() if p.source == FP.COMICRAFT]
    assert paid, "the one paid recommendation went missing"
    for p in paid:
        assert p.price, p.family


def test_the_free_ones_do_not_carry_a_price():
    for p in _all():
        if p.source == FP.GOOGLE:
            assert not p.price, p.family


def test_a_google_link_is_the_family_s_own_page():
    """Not a search, not the home page. `fonts.google.com/specimen/Dela+Gothic
    +One` is one click from the zip; the browse page is a search box."""
    for p in _all():
        if p.source != FP.GOOGLE:
            continue
        assert p.url == FP.google(p.family), (p.family, p.url)
        assert "/specimen/" in p.url, p.url


def test_every_why_is_about_the_box_type():
    """A sentence about the FONT - "a lovely geometric sans" - says nothing
    about whether it belongs in a thought bubble. Checked as "it is a real
    sentence", which is as far as a test can honestly go; the rest is the
    reason it is worth reading them."""
    for p in _all():
        assert len(p.why) > 40, (p.family, p.why)
        assert p.why.rstrip().endswith("."), (p.family, p.why)


# ------------------------------------------------- what is already here

def test_the_bundled_faces_come_back_marked_as_installed():
    from mangatl.editor import find_fonts
    got = FP.with_availability([f["path"] for f in find_fonts()])
    have = {r["family"] for rows in got.values() for r in rows
            if r["installed"]}
    for family in ("Comic Neue", "Bangers", "Luckiest Guy", "Patrick Hand",
                   "Kalam", "Anton", "Gaegu", "Gochi Hand",
                   "Nanum Pen Script"):
        assert family in have, (family, sorted(have))


def test_and_the_ones_this_app_may_not_ship_are_not():
    from mangatl.editor import find_fonts
    got = FP.with_availability([f["path"] for f in find_fonts()])
    rows = {r["family"]: r for rows in got.values() for r in rows}
    assert rows["Anime Ace"]["installed"] is False
    assert rows["Wild Words"]["installed"] is False


def test_a_face_downloaded_an_hour_ago_stops_being_a_link():
    """Availability is asked of the fonts on the machine RIGHT NOW, not of a
    list of what the app shipped with."""
    got = FP.with_availability(["/anywhere/Caveat-Regular.ttf"])
    caveat = next(r for r in got["narration"] if r["family"] == "Caveat")
    assert caveat["installed"] is True


def test_nothing_is_installed_when_nothing_is_there():
    got = FP.with_availability([])
    assert not any(r["installed"] for rows in got.values() for r in rows)


# ---------------------------------------------- one answer, every time

# `picks` and `sources` travelled here while the page was a tab in the editor.
# The page is on the website now, so the payload went with it.
FONT_KEYS = {"fonts", "recent", "uploaded", "defaults", "marks"}


def test_the_font_answer_carries_everything_the_browser_reads():
    from mangatl import editor
    got = editor.fonts_answer()
    assert FONT_KEYS <= set(got), FONT_KEYS - set(got)


def test_and_every_font_endpoint_answers_with_it():
    """THE BUG. `/api/font` answered with three of the seven, and `takeFonts`
    takes what it is handed - so noting a font as recently used emptied the
    defaults table, emptied the marks picker and raised the stale-app flag."""
    from mangatl import editor
    src = inspect.getsource(editor.Handler)
    for route in ('if path == "/api/fonts":', 'if path == "/api/font":'):
        assert route in src, route
    # No endpoint builds its own. One function, so a reply cannot be half one.
    bad = re.findall(r'\{"fonts": find_fonts\(\)', src)
    assert not bad, "a font endpoint is still assembling its own answer"
    assert src.count("fonts_answer()") >= 2, src.count("fonts_answer()")


def test_the_editor_no_longer_carries_the_page():
    """lee: *"move teh fonts tab into the front end website not the app"*.

    He is right about where it belongs, and the reason is what the page IS:
    everything else in the editor acts on the chapter you have open, and this
    acts on nothing. It is read once before you start and again when a series
    wants a different voice - which you want without a project loaded, and
    want to be able to send to somebody.

    So the tab, the page, the renderer and the payload all went, together. An
    answer nothing reads is a request nobody can see is wasted.
    """
    from where import PKG
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    for gone in ("tabFonts", "fontsPage", "fpList", 'data-sec="fontpicks"'):
        assert gone not in html, gone
    # Asked of the CODE, with the prose taken out. The note left where the
    # renderer stood names both of these, and a guard that cannot tell a
    # comment from a call punishes writing down why something went.
    for name in ("project.js", "project-io.js", "view.js"):
        js = _code((PKG / "static" / "js" / name).read_text(encoding="utf-8"))
        for gone in ("renderFontPicks", "FONT_PICKS", "FONT_SOURCES",
                     "fontsPage", "tabFonts"):
            assert gone not in js, (name, gone)


def test_the_list_is_not_copied_into_the_browser():
    """`fontpicks.PICKS` is mostly about LICENCES - which faces this app may
    carry and which it may only point at - and that reasoning belongs beside
    `fonts/LICENSES.md`. A second copy in a script tag is the mistake
    `DEFAULT_FONTS` already taught."""
    from where import PKG
    for name in ("project.js", "project-io.js", "frames.js"):
        js = (PKG / "static" / "js" / name).read_text(encoding="utf-8")
        assert "fonts.google.com" not in js, name
        assert "blambot" not in js.lower(), name


def test_the_website_page_is_generated_from_this_table():
    """A hand-written page would be a second copy of a list that changes -
    right on the day it was written and quietly wrong the third time somebody
    added a recommendation."""
    from where import PKG
    gen = (PKG / "site" / "build_fonts.py")
    assert gen.exists(), "nothing builds the page"
    src = gen.read_text(encoding="utf-8")
    assert "fontpicks" in src and "FP.PICKS" in src, src[:400]
    page = (PKG / "site" / "fonts.html")
    assert page.exists(), "the page has not been built"
    html = page.read_text(encoding="utf-8")
    # every face on it, and every family set in its own webfont
    for p in _all():
        assert p.family in html, p.family
    assert "fonts.googleapis.com/css2?family=" in html, \
        "the specimens are not set in the faces they name"


def test_the_site_links_to_it_from_every_page():
    from where import PKG
    for name in ("tutorial.html", "pricing.html", "account.html",
                 "signin.html", "index.html"):
        html = (PKG / "site" / name).read_text(encoding="utf-8")
        assert 'href="fonts.html"' in html, name


def test_there_is_one_full_width_page_again():
    """For one afternoon there were two, and `setTab`'s `full` flag - which
    had always meant both "give this the whole window" and "this is Settings" -
    had to be split, so that a read-only page did not inherit the snapshot
    behind Settings' Cancel button, a font menu it has not got and a textarea
    that is not on it.

    The page has moved to the website, so `full` and `isSet` are the same
    question once more. The two names stay: the split cost nothing and the
    next full-width page will want them."""
    from where import PKG
    js = (PKG / "static" / "js" / "view.js").read_text(encoding="utf-8")
    body = js.split("function setTab(t, byHand){")[1].split("\n}\n")[0]
    assert "const isSet = t==='settings';" in body
    assert "const full = isSet;" in body, body[:400]
    for only in ("snapshotSettings", "growSynopsis"):
        assert "if(isSet && typeof %s" % only in body, only


# ------------------------------- and the picker does not then hide them

def test_every_face_the_page_recommends_is_offered_by_the_picker():
    """THE PICKER MUST NOT HIDE WHAT THE APP JUST TOLD SOMEBODY TO DOWNLOAD.

    That is exactly what it was doing. The picker shows a face whose NAME
    reads as comic typesetting - `_COMIC_HINTS`, there because a Windows font
    folder holds hundreds of office fonts nobody typesets with - and not one
    of Dela Gothic One, Titan One, Caveat, Klee One, Bebas Neue, Yomogi, Zen
    Kurenaido, Yusei Magic, Rampart One, Train One, Rubik Mono One, Mochiy Pop
    One, Archivo Black or Oswald was in it. So a face downloaded on this app's
    own advice, installed, and then looked for in Box types was not there.
    lee: *"no add teh otehr fonst in teh fonts picker list in teh app"*.

    Asked of the FILE NAME each family actually arrives as - `Dela Gothic One`
    downloads as `DelaGothicOne-Regular.ttf` - because the name on the disk is
    the only thing the picker ever sees.
    """
    from mangatl.editor import _is_comic_font
    for p in _all():
        for filename in (p.family.replace(" ", "") + "-Regular",
                         p.family.replace(" ", "_") + "-Bold",
                         p.family.replace(" ", "-") + "-Italic",
                         p.family):
            assert _is_comic_font(filename), (p.family, filename)


def test_and_it_is_read_off_the_recommendations_rather_than_copied():
    """The same fact - "this app thinks this face is worth typesetting with" -
    said in two places is the next thing to fall out of step. Adding a
    recommendation adds it to the picker, with nothing else to remember."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor._recommended_families)
    assert "fontpicks.PICKS" in src, src


def test_a_font_folder_full_of_office_faces_is_still_not_offered():
    """The reason the filter exists. Widening it until it lets everything in
    is not widening it, it is deleting it."""
    from mangatl.editor import _is_comic_font
    for dull in ("Arial", "Times New Roman", "Calibri", "Segoe UI",
                 "Consolas", "Georgia", "Wingdings", "Cambria", "Verdana",
                 "Tahoma", "Courier New", "Palatino Linotype"):
        assert not _is_comic_font(dull), dull


def test_a_very_short_family_name_cannot_sweep_the_folder_in():
    """`Jua` is three characters, and matching three characters anywhere in a
    name would offer `Juanita`, `Marjua`, anything. Four is the floor, so a
    family that short is carried by the hint list instead - which it is."""
    from mangatl.editor import _recommended_families, _is_comic_font
    assert all(len(f) >= 4 for f in _recommended_families())
    assert _is_comic_font("Jua-Regular"), "the short ones still have to work"
