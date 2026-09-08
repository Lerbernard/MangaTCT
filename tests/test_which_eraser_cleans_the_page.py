"""Which eraser the cleaner uses is a setting, not a redeploy.

lee, after seven of them were measured on nine hard boxes off his own chapter
3 - the app's own crops and masks, sound effects and outside text over hatching
and screentone: **"anime lama is the shout, add it in the list"**.

    anime-lama   nearer the surrounding artwork on 6 of 9, 1.5s a box
    lama         1.6s a box - the two that never drew something the page
                 never had
    fcf          drew a human FACE into a blank panel
    migan        a solid black blob in the same place
    manga        blotchy grey mottle on all nine
    zits         hanging streaks, and 34s a box
    cv2 / telea  0.07 of the surrounding texture kept - the floor

`lama_clean_modal.py` served whichever model the word `MODEL` named, so
comparing two meant editing the file, deploying again and pasting a second URL.
It loads both now - they are 200MB each and the container holds both without
noticing - and the app names the one it wants per request.

**It keeps the app name `mangatl-clean-lama`**, so a URL already in Settings
goes on working and a redeploy is all this costs. Not the bare `mangatl-clean`:
that is `manga_clean_modal.py`'s app, and taking it would replace that deploy.

Three caches had to learn about it, which is the whole of the risk here: a
plate on disk, a crop in `ai_clean_cache`, and the answer to "has this page
changed". Miss one and switching the eraser changes nothing at all, which is
the bug lee reported as *"nothing vhanged"* the last time a cache could not
tell two answers apart.
"""
import pytest

from where import PKG

cv2 = pytest.importorskip("cv2")


def _project(tmp_path, **settings):
    import numpy as np
    from mangatl.project import Project
    p = Project(None, str(tmp_path))
    p.add_uploaded("a.png", cv2.imencode(
        ".png", np.full((80, 80, 3), 240, np.uint8))[1].tobytes())
    p.settings.update(settings)
    return p


# ------------------------------------------------------------- the setting

def test_anime_lama_is_what_a_project_gets_by_default(tmp_path):
    from mangatl.editor import clean_model
    assert clean_model(_project(tmp_path)) == "anime-lama"


def test_a_new_project_carries_it_in_its_settings(tmp_path):
    assert _project(tmp_path).settings["clean_model"] == "anime-lama"


def test_the_other_one_can_no_longer_be_asked_for(tmp_path):
    """There is no card to ask with, and a project.json carrying the other
    name from when there was gets the measured one anyway. lee: *"...ad only ai
    and the card make this the deaflau clenner"*."""
    from mangatl.editor import clean_model
    assert clean_model(_project(tmp_path, clean_model="lama")) == "anime-lama"


def test_a_name_nobody_knows_cleans_the_page_anyway(tmp_path):
    """A typo in a settings box should clean the page, not fail it - and it
    must not be forwarded, or the endpoint decides what a typo means."""
    from mangatl.editor import clean_model
    for junk in ("", "  ", "anime lama", "sdxl", None):
        assert clean_model(_project(tmp_path, clean_model=junk)) == "anime-lama"


def test_the_list_is_the_two_the_deploy_serves(tmp_path):
    from mangatl.editor import CLEAN_MODELS
    src = (PKG / "lama_clean_modal.py").read_text(encoding="utf-8")
    for name in CLEAN_MODELS:
        assert '"%s"' % name in src, name
    assert CLEAN_MODELS[0] == "anime-lama", "the default is the measured one"


# -------------------------------------------------------------- the caches

def test_the_eraser_is_still_part_of_a_plates_identity(tmp_path):
    """Nothing can switch it any more, so nothing can invalidate a plate this
    way - but the stamp still carries it, because the day something can, the
    `nothing vhanged` bug comes straight back: two erasers give two answers and
    a plate cached under one key would serve both."""
    import inspect
    from mangatl import editor
    assert "clean_model(p)" in inspect.getsource(editor._plate_stamp)


def test_and_the_crop_cache_can_tell_them_apart():
    """`ai_clean_cache` is keyed on the bytes of the question. The model is
    part of the question."""
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor._ai_clean_call)
    at = src.index("hashlib.sha1(")
    assert "model.encode" in src[at:src.index("hexdigest()", at)]


def test_the_request_says_which_one(tmp_path):
    import inspect
    from mangatl import editor
    src = inspect.getsource(editor._ai_clean_call)
    assert '"model": model,' in src


def test_the_self_test_asks_the_one_that_will_run():
    """A Test cleaner that passes on a model the run does not use is a test of
    nothing."""
    import inspect
    from mangatl import editor
    assert "clean_model(p)" in inspect.getsource(editor.clean_selftest)


# --------------------------------------------------------------- the deploy

def test_one_deploy_holds_both():
    src = (PKG / "lama_clean_modal.py").read_text(encoding="utf-8")
    assert "self.models = {" in src
    assert "for c in _CLASS.values()" in src, "both sets of weights are baked in"


def test_it_keeps_the_name_the_url_was_built_from():
    """A URL already pasted into Settings has to go on working."""
    src = (PKG / "lama_clean_modal.py").read_text(encoding="utf-8")
    assert 'modal.App("mangatl-clean-lama")' in src


def test_and_does_not_take_the_manga_deploys_name():
    """`mangatl-clean` is `manga_clean_modal.py`'s app. Two files deploying one
    name means the second one replaces the first."""
    lama = (PKG / "lama_clean_modal.py").read_text(encoding="utf-8")
    manga = (PKG / "manga_clean_modal.py").read_text(encoding="utf-8")
    import re
    names = {f: re.search(r'modal\.App\(\s*"([^"]+)"', s).group(1)
             for f, s in (("lama", lama), ("manga", manga))}
    assert names["lama"] != names["manga"], names


def test_an_older_app_that_names_nothing_still_gets_served():
    """It sends no `model` key at all. It has to get MODEL rather than a
    KeyError, or upgrading the endpoint breaks the app that has not been
    upgraded."""
    src = (PKG / "lama_clean_modal.py").read_text(encoding="utf-8")
    assert 'self.models.get(want) or self.models[MODEL]' in src
    assert 'MODEL = "anime-lama"' in src, "and the default is the measured one"


# ------------------------------------------------------------------ the UI

def test_there_are_no_cards_left_to_pick_from():
    """Two stood here, from when the hosted model was one choice among three
    and the difference between the erasers showed across a chapter. lee:
    *"...ad only ai and the card make this the deaflau clenner"*."""
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert 'id="eraserCards"' not in html
    assert "<select id=\"clean_model\"" not in html, "and it did not become a menu"
    assert "function pickEraser(" not in js and "function syncEraserCards(" not in js
    assert "syncEraserCards();" not in js, "something still calls it"


def test_but_the_page_still_says_which_one_and_why():
    """A setting that has become a fact still has to be a fact somebody can
    read, or the next person wonders what the cleaner is using and measures
    the field again."""
    import re
    html = (PKG / "static" / "editor.html").read_text(encoding="utf-8")
    at = html.index('id="aicfg"')
    flat = re.sub(r"\s+", " ", html[at:html.index('id="clean_url"')])
    assert "anime-lama" in flat
    assert "6 of 9" in flat, "the measurement that picked it is not on the page"
    assert "never drew something the page did not have" in flat


def test_the_setting_still_travels_with_the_project():
    js = (PKG / "static" / "js" / "project.js").read_text(encoding="utf-8")
    assert "clean_model:(proj.settings.clean_model||'anime-lama')" in js


# ------------------------------------------------- and the address is built in

def test_a_new_project_already_knows_where_the_cleaner_is():
    """lee, having deployed it: *"make it built in the app and not a thing i
    have to add to the app"*. The address is PUBLIC - the token beside it is
    what guards the endpoint - so the app carries it and one less thing gets
    pasted into a new project."""
    import tempfile
    from mangatl.project import Project, CLEAN_URL
    p = Project(None, tempfile.mkdtemp())
    assert p.settings["clean_url"] == CLEAN_URL
    assert CLEAN_URL.startswith("https://") and CLEAN_URL.endswith(".modal.run")
    assert "mangatl-clean-lama" in CLEAN_URL, \
        "the app it points at is the one lama_clean_modal.py deploys"


def test_the_token_is_not_built_in_with_it():
    """Shipping that would let anyone holding a copy of the app spend the GPU
    time it pays for, which is a bill nobody can cap."""
    import tempfile
    from mangatl.project import Project
    p = Project(None, tempfile.mkdtemp())
    assert p.settings["clean_token"] == ""
    src = (PKG / "project.py").read_text(encoding="utf-8")
    tok = (PKG / "lama_clean_modal.py").read_text(encoding="utf-8")
    import re
    secret = re.search(r'CLEAN_TOKEN\s*=\s*"([^"]+)"', tok).group(1)
    assert secret not in src, "the deploy's token is in the shipped app"


def test_both_copies_of_the_defaults_agree():
    """There USED to be two copies: `_pj.py` was an old snapshot of
    `project.py` with its own settings block. It went in the 2026-09-02
    dead-code sweep; the one copy left just has to carry the defaults."""
    a = (PKG / "project.py").read_text(encoding="utf-8")
    for want in ('"clean_url": CLEAN_URL', '"clean_model": "anime-lama"'):
        assert want in a, want


# ---------------------------------------------- and what a picked card looks like

def test_a_picked_card_is_yellow_like_everything_else_that_is_picked():
    """lee, with a picture: *"the secleted boxes for all the card shoud be
    yellow not blue"*.

    EVERY card - the eraser, who reads the text, the detector routes - because
    the rule was one line of CSS for all of them. A chosen card was the only
    thing on screen saying "picked" in a colour nothing else used: the lit row
    in the text list, the row whose editor is open and a multiple selection are
    all `--accent`. The literal it used was also a hair off `--link`, which
    means a link and not a selection."""
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    at = css.index(".cards .card.on{")
    rule = css[at:css.index("}", at)]
    assert "var(--accent)" in rule
    assert "#2f6fd0" not in rule and "#2a63d8" not in rule
    assert rule.count("var(--accent)") == 2, "the border AND the inset ring"


def test_the_box_select_marquee_keeps_its_blue():
    """It is not a card and it is deliberately not dressed like one - a MODE
    that changes what the next drag does. Its own comment says so."""
    css = (PKG / "static" / "css" / "editor.css").read_text(encoding="utf-8")
    assert ".legend .lgmain.lgsel{--lgc:#2f6fd0" in css


# ------------------------------------------------------------- and on screen

def test_the_cleaners_setup_is_on_the_page_without_switching_anything_on(tmp_path):
    """Chromium, against the real server. This block used to be hidden until a
    method menu said otherwise; there is no method menu, and the endpoint in it
    is what every page is cleaned through - so it has to be reachable."""
    import threading
    from http.server import ThreadingHTTPServer

    import browserpool
    from mangatl import editor

    p = _project(tmp_path / "ui", clean_url="https://example.modal.run",
                 clean_token="t")
    was, editor.PROJECT = editor.PROJECT, p
    srv = ThreadingHTTPServer(("127.0.0.1", 0), editor.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    if not browserpool.available():
        srv.shutdown(); srv.server_close(); editor.PROJECT = was
        pytest.skip("chromium unavailable")
    try:
        with browserpool.session() as br:
            pg = br.new_page(viewport={"width": 1500, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            browserpool.ready(pg)
            pg.evaluate("setTab('settings'); setSettingsTab('cleaning')")
            browserpool.settled(pg)
            for want in ("aicfg", "clean_url", "clean_token"):
                assert pg.evaluate(
                    "getComputedStyle(document.getElementById('%s'))"
                    ".display !== 'none'" % want), "%s is not on the page" % want
            assert pg.evaluate(
                "document.getElementById('clean_url').value") \
                == "https://example.modal.run", "the saved address is not shown"
            assert not errs, errs[:3]
    finally:
        srv.shutdown(); srv.server_close(); editor.PROJECT = was


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
