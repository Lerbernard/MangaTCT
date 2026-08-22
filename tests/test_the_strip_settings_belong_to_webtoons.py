"""The strip settings, and where they belong.

Three things lee asked for at once, looking at the two boxes in Settings ▸
Language & direction:

* *"this setting shoud only be a thing for manhwa and manhua"* - a manga
  chapter is never re-cut, so on manga those were controls for something that
  could not happen;
* *"change teh value to be a more understandable metrics"* - they said 2400
  and 6000, which are pixels, which is a unit nobody thinks a page in. They are
  now MULTIPLES OF THE PAGE WIDTH, which reads as a shape, means the same on a
  690px strip and a 1600px one, and for the ceiling is the genuinely correct
  unit: the detector letterboxes a whole page into 1024px, so what costs you
  text is how many times taller than wide the page is;
* *"add a check box oprion in the files uoload page to turn on and off the
  automated merging thing and have it on by default"* - the switch put where
  the decision is being made, not three screens away.

And *"add a loading bar in the file page when the files are getting
processed"*, because loading a chapter was a hundred files read, uploaded and
re-cut behind one line of small grey text.
"""
import re
import shutil
import threading

import numpy as np
import pytest

import browserpool

cv2 = pytest.importorskip("cv2")

from where import PKG

HTML = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
IO = (PKG / "static" / "js" / "project-io.js").read_text(encoding="utf-8")


# ------------------------------------------------------- said in the markup

def test_the_boxes_are_multiples_and_not_pixels():
    assert 'id="strip_tall"' in HTML and 'id="strip_tall_max"' in HTML
    assert 'id="strip_target"' not in HTML, "the pixel box is gone"
    assert 'id="strip_max"' not in HTML
    assert HTML.count("&times; the width") == 2


def test_the_second_box_no_longer_promises_a_wall():
    """It was "Never taller than", and it no longer is one: a page runs past
    it to reach a gap rather than being cut through the artwork. A label that
    promises something the code stopped doing is worse than no label."""
    assert "Never taller than" not in HTML
    assert "Tell me when a page passes" in HTML


def test_the_file_tab_switch_carries_no_explanation():
    """lee: *"remove the discriotion for teh tool"*. The label says what it
    does; four more lines under it is the sort of thing you read once."""
    assert "On by default. A manhwa or manhua" not in HTML
    assert "Join webtoon strips back up and re-cut them" in HTML


def test_the_file_tab_has_the_switch_and_it_is_on():
    assert 'id="restitch_new"' in HTML, "the File tab needs its own switch"
    # The bare attribute, right after the id. Looking for the WORD anywhere in
    # the tag matches `onchange="stripSwitch(this.checked)"` and passes with
    # the attribute gone, which is the one thing this test is for.
    assert re.search(r'id="restitch_new"\s+checked\b', HTML), \
        'lee: *"have it on by default"*'
    assert "restitchNewWrap" in HTML, "and it is the wrapper that is gated"


def test_the_file_tab_has_a_bar():
    for want in ('id="pkbar"', 'id="pkBarOuter"', 'id="pkBarFill"',
                 'id="pkBarWhat"'):
        assert want in HTML, want


def test_the_two_switches_are_one_setting():
    """Two boxes showing one fact, able to disagree, is worse than one box in
    the wrong place."""
    assert "function stripSwitch(" in IO
    assert "$('restitch_strips')" in IO and "$('restitch_new')" in IO


def test_the_screen_and_the_server_agree_on_which_formats_are_strips():
    """`STRIP_MEDIA` decides what actually happens; the list in the browser
    decides what is on screen. They have to be the same list, or the settings
    are hidden for a format that uses them or shown for one that cannot."""
    from mangatl.project import STRIP_MEDIA

    said = re.search(r"const STRIP_MEDIA=\[([^\]]*)\]", IO)
    assert said, "project-io.js has to name them"
    assert set(re.findall(r"'([a-z]+)'", said.group(1))) == STRIP_MEDIA


# ------------------------------------------------------------- on the screen

def _project(root, medium):
    from mangatl.project import Project

    shutil.rmtree(root, ignore_errors=True)
    p = Project(None, root)
    img = np.repeat(np.random.default_rng(2).integers(
        60, 200, (900, 500, 1), dtype=np.uint8), 3, axis=2)
    p.add_uploaded("p0.png", cv2.imencode(".png", img)[1].tobytes())
    p.settings["medium"] = medium
    p.save()
    return p


@pytest.fixture()
def screen(tmp_path):
    """A running editor and a browser on it, on a project you choose."""
    from http.server import ThreadingHTTPServer
    from mangatl import editor

    made = {}

    def open_on(medium):
        p = _project(str(tmp_path / medium), medium)
        made["p"], editor.PROJECT = p, p
        srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.setdefault("srv", []).append(srv)
        return p, "http://127.0.0.1:%d" % srv.server_address[1]

    was = editor.PROJECT
    if not browserpool.available():
        pytest.skip("chromium unavailable")
    with browserpool.session() as br:
        made["br"] = br
        try:
            yield open_on, br
        finally:
            for srv in made.get("srv", []):
                srv.shutdown(); srv.server_close()
            editor.PROJECT = was


def _settings(br, base):
    ctx = br.new_context(viewport={"width": 1400, "height": 950})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/", wait_until="load")
    browserpool.ready(pg)
    pg.evaluate("setTab('settings'); setSettingsTab('language')")
    browserpool.settled(pg)
    return pg, errs


def shown(pg, el):
    return pg.evaluate(
        "(id)=>{const e=document.getElementById(id);"
        "return !!(e && e.offsetParent!==null)}", el)


def test_a_manga_chapter_is_not_offered_them(screen):
    open_on, br = screen
    _p, base = open_on("manga")
    pg, errs = _settings(br, base)
    assert not shown(pg, "stripSet"), \
        "a manga chapter is never re-cut, so there is nothing to set"
    assert not errs, errs


@pytest.mark.parametrize("medium", ["manhwa", "manhua"])
def test_a_webtoon_chapter_is(screen, medium):
    open_on, br = screen
    _p, base = open_on(medium)
    pg, errs = _settings(br, base)
    assert shown(pg, "stripSet")
    assert not errs, errs


def test_changing_the_format_opens_and_closes_it_without_a_reload(screen):
    """The medium menu is right above these. Having to leave the page and come
    back to see the change is the sort of thing you never find out about."""
    open_on, br = screen
    _p, base = open_on("manga")
    pg, errs = _settings(br, base)
    assert not shown(pg, "stripSet")
    pg.select_option("#medium", "manhwa")
    browserpool.settled(pg)
    assert shown(pg, "stripSet")
    pg.select_option("#medium", "manga")
    browserpool.settled(pg)
    assert not shown(pg, "stripSet")
    assert not errs, errs


def test_the_pixels_are_said_underneath(screen):
    """The multiple is the setting; the pixels are what it means on this
    chapter, and somebody who has been reading these boxes as pixels needs
    both for one chapter at least."""
    open_on, br = screen
    _p, base = open_on("manhwa")
    pg, errs = _settings(br, base)
    said = pg.text_content("#stripPx")
    assert "500px wide" in said, said
    assert "1,750px" in said, "500 x 3.5 a page"
    assert "4,250px" in said, "500 x 8.5 before it is reported"
    assert not errs, errs


def test_the_pixels_follow_the_box(screen):
    open_on, br = screen
    _p, base = open_on("manhwa")
    pg, errs = _settings(br, base)
    pg.fill("#strip_tall", "6")
    pg.dispatch_event("#strip_tall", "change")
    browserpool.settled(pg)
    assert "3,000px" in pg.text_content("#stripPx")
    assert not errs, errs


def test_the_setting_that_is_saved_is_the_multiple(screen):
    open_on, br = screen
    p, base = open_on("manhwa")
    pg, errs = _settings(br, base)
    pg.fill("#strip_tall", "5.5")
    pg.dispatch_event("#strip_tall", "change")
    pg.wait_for_timeout(700)
    browserpool.settled(pg)
    assert float(p.settings["strip_tall"]) == 5.5
    assert p.strip_heights()[0] == round(500 * 5.5)
    assert not errs, errs


def test_the_two_switches_move_together(screen):
    open_on, br = screen
    p, base = open_on("manhwa")
    pg, errs = _settings(br, base)
    pg.evaluate("stripSwitch(false)")
    pg.wait_for_timeout(700)
    browserpool.settled(pg)
    assert pg.evaluate("$('restitch_strips').checked") is False
    assert pg.evaluate("$('restitch_new').checked") is False
    assert p.settings["restitch_strips"] is False
    assert not errs, errs


def test_the_bar_shows_and_goes_away_again(screen):
    """A bar left running says the chapter is still loading for as long as the
    tab is open, which is worse than no bar at all."""
    open_on, br = screen
    _p, base = open_on("manhwa")
    pg, errs = _settings(br, base)
    assert not shown(pg, "pkbar")
    pg.evaluate("setTab('new'); pkBar(0.5, 'Loading 3 of 6 pages…')")
    browserpool.settled(pg)
    assert shown(pg, "pkbar")
    assert pg.evaluate("$('pkBarFill').style.width") == "50%"
    assert "3 of 6" in pg.text_content("#pkBarWhat")
    pg.evaluate("pkBar(false)")
    browserpool.settled(pg)
    assert not shown(pg, "pkbar")
    assert not errs, errs


def test_a_step_with_nothing_to_count_paces_instead_of_inventing_a_number(screen):
    """The re-cut is one long call on the server with no progress to report.
    A bar that creeps to 90% and sits there is a lie about how far along it
    is."""
    open_on, br = screen
    _p, base = open_on("manhwa")
    pg, errs = _settings(br, base)
    pg.evaluate("setTab('new'); pkBar(null, 'Re-cutting…')")
    browserpool.settled(pg)
    assert pg.evaluate("$('pkBarOuter').classList.contains('wait')")
    assert not errs, errs


def _filetab(br, base):
    ctx = br.new_context(viewport={"width": 1400, "height": 950})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/", wait_until="load")
    browserpool.ready(pg)
    pg.evaluate("setTab('new'); showPicker(true)")
    browserpool.settled(pg)
    return pg, errs


def test_the_file_tab_switch_is_not_there_for_manga(screen):
    """The second half of the same ask, which the first pass missed: the
    Settings block was gated and this one was not. lee: *"the setting shoud
    not be there for manga"*."""
    open_on, br = screen
    _p, base = open_on("manga")
    pg, errs = _filetab(br, base)
    assert not shown(pg, "restitchNewWrap")
    assert not errs, errs


@pytest.mark.parametrize("medium", ["manhwa", "manhua"])
def test_the_file_tab_switch_is_there_for_a_webtoon(screen, medium):
    open_on, br = screen
    _p, base = open_on(medium)
    pg, errs = _filetab(br, base)
    assert shown(pg, "restitchNewWrap")
    assert not errs, errs


def test_it_follows_the_menu_on_ITS_OWN_screen(screen):
    """There are two format menus and they are the same question on two
    screens. The File tab's switch has to follow the File tab's menu - that is
    the one in front of the person while they choose a folder."""
    open_on, br = screen
    _p, base = open_on("manga")
    pg, errs = _filetab(br, base)
    assert not shown(pg, "restitchNewWrap")
    pg.select_option("#pkMedium", "manhwa")
    browserpool.settled(pg)
    assert shown(pg, "restitchNewWrap")
    pg.select_option("#pkMedium", "manga")
    browserpool.settled(pg)
    assert not shown(pg, "restitchNewWrap")
    assert not errs, errs
